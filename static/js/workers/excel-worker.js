/**
 * Excel 分析 Web Worker — v8.0 性能优化
 * 用于在后台线程处理大数据集的排序、筛选、搜索、聚合，避免阻塞主线程
 *
 * 消息协议：
 * 接收: { type: 'init', data: [...] }
 *       { type: 'sort', field: '...', order: 'asc'|'desc' }
 *       { type: 'filter', conditions: {...} }                 // 支持 equals/contains/in/not_empty/contains_any/resolved_state
 *       { type: 'search', query: '...', fields: [...] }
 *       { type: 'paginate', page: N, pageSize: N }
 *       { type: 'get_page', page, pageSize }                  // 组合：筛选+排序+分页
 *       { type: 'get_all' }                                   // 返回筛选排序后的全量数据
 *       { type: 'apply_query', reqId, keywords:[], status:'', sortField, sortOrder }  // v8.0 一次性组合查询
 *       { type: 'filter_labels', reqId, labels: [...] }       // v8.0 Labels OR 匹配筛选
 *       { type: 'aggregate', reqId, data?: [...] }            // v8.0 大数组分组聚合（不传 data 用 allData）
 *       { type: 'reset' }
 * 发送: { type: 'result'|'sorted'|'filtered'|'searched'|'all_data'|'query_result'|'labels_result'|'aggregate_result'|'error' }
 */

let allData = [];
let filteredData = [];
let currentSort = { field: null, order: 'asc' };
let currentFilter = null;
let currentSearch = { query: '', fields: [] };

// 严重程度排序权重
const SEVERITY_WEIGHT = {
    'blocker': 0, 'critical': 1, 'major': 2, 'minor': 3, 'trivial': 4,
    'p0': 0, 'p1': 1, 'p2': 2, 'p3': 3, 'p4': 4,
    's0': 0, 's1': 1, 's2': 2, 's3': 3, 's4': 4,
    '致命': 0, '严重': 1, '高': 1, '中等': 2, '一般': 2, '低': 3, '轻微': 3, '提示': 4
};

function matchSeverity(value) {
    if (!value) return 99;
    const v = String(value).toLowerCase().trim();
    if (v in SEVERITY_WEIGHT) return SEVERITY_WEIGHT[v];
    // 数字
    if (/^\d+$/.test(v)) {
        const n = parseInt(v);
        if (n >= 1 && n <= 5) return n - 1;
    }
    // 包含匹配
    for (const key in SEVERITY_WEIGHT) {
        if (v.includes(key)) return SEVERITY_WEIGHT[key];
    }
    return 99;
}

function sortData(data, field, order) {
    if (!field || data.length === 0) return data;
    const multiplier = order === 'desc' ? -1 : 1;
    const sorted = [...data];

    sorted.sort((a, b) => {
        let va = a[field] !== undefined ? a[field] : '';
        let vb = b[field] !== undefined ? b[field] : '';

        // 严重程度特殊排序
        if (field === 'severity') {
            return (matchSeverity(va) - matchSeverity(vb)) * multiplier;
        }

        // 日期排序
        if (field === 'create_date' || field === 'resolved_date' || field === 'closed_date' || field === 'created_date') {
            const da = new Date(va).getTime() || 0;
            const db = new Date(vb).getTime() || 0;
            return (da - db) * multiplier;
        }

        // 字符串比较
        va = String(va).toLowerCase();
        vb = String(vb).toLowerCase();
        if (va < vb) return -1 * multiplier;
        if (va > vb) return 1 * multiplier;
        return 0;
    });

    return sorted;
}

// v8.0: 判断一条 issue 是否已解决（与前端 resolved_date 口径一致）
function isIssueResolved(item) {
    const rd = item.resolved_date !== undefined && item.resolved_date !== null
        ? String(item.resolved_date).toLowerCase().trim() : '';
    return !!(rd && rd !== '-' && rd !== 'nan' && rd !== 'none' && rd !== 'nat');
}

function filterData(data, conditions) {
    if (!conditions || Object.keys(conditions).length === 0) return data;
    return data.filter(item => {
        for (const field in conditions) {
            const cond = conditions[field];
            const value = item[field] !== undefined ? String(item[field]).toLowerCase() : '';

            if (cond.type === 'equals') {
                if (value !== String(cond.value).toLowerCase()) return false;
            } else if (cond.type === 'contains') {
                if (!value.includes(String(cond.value).toLowerCase())) return false;
            } else if (cond.type === 'in') {
                const values = (cond.value || []).map(v => String(v).toLowerCase());
                if (!values.includes(value)) return false;
            } else if (cond.type === 'not_empty') {
                if (!value) return false;
            } else if (cond.type === 'contains_any') {
                // v8.0: 字段值包含数组中任意一个关键字即通过（OR）
                const kws = (cond.value || []).map(v => String(v).toLowerCase()).filter(Boolean);
                if (kws.length === 0) continue;
                if (!kws.some(kw => value.includes(kw))) return false;
            } else if (cond.type === 'resolved_state') {
                // v8.0: 按 resolved_date 判断 open/resolved
                const resolved = isIssueResolved(item);
                if (cond.value === 'open' && resolved) return false;
                if (cond.value === 'resolved' && !resolved) return false;
            }
        }
        return true;
    });
}

function searchData(data, query, fields) {
    if (!query || !fields || fields.length === 0) return data;
    const q = String(query).toLowerCase();
    return data.filter(item => {
        for (const field of fields) {
            const value = item[field] !== undefined ? String(item[field]).toLowerCase() : '';
            if (value.includes(q)) return true;
        }
        return false;
    });
}

function applyAllFilters() {
    let result = allData;

    // 筛选
    if (currentFilter) {
        result = filterData(result, currentFilter);
    }

    // 搜索
    if (currentSearch.query && currentSearch.fields.length > 0) {
        result = searchData(result, currentSearch.query, currentSearch.fields);
    }

    // 排序
    if (currentSort.field) {
        result = sortData(result, currentSort.field, currentSort.order);
    }

    filteredData = result;
    return result;
}

function paginate(data, page, pageSize) {
    const start = (page - 1) * pageSize;
    const end = start + pageSize;
    return {
        data: data.slice(start, end),
        total: data.length,
        page: page,
        pageSize: pageSize,
        totalPages: Math.ceil(data.length / pageSize)
    };
}

/* ============================================================
 * v8.0: Labels 筛选 + 大数组统计聚合（从主线程下沉）
 * ============================================================ */

// 与前端 _parseIssueLabels 保持一致
function parseIssueLabels(issue) {
    let raw = issue.labels || issue.label || issue.tag || issue.tags || '';
    if (!raw) return [];
    const s = String(raw).trim();
    if (!s) return [];
    let parts;
    if (s.indexOf(',') >= 0 || s.indexOf(';') >= 0) {
        parts = s.split(/[,;]/);
    } else {
        parts = s.split(/\s+/);
    }
    return parts.map(p => p.trim()).filter(p => p.length > 0);
}

function filterByLabels(data, labels) {
    if (!labels || labels.length === 0) return data;
    const selected = new Set(labels);
    return data.filter(item => {
        const issueLabels = parseIssueLabels(item);
        for (let i = 0; i < issueLabels.length; i++) {
            if (selected.has(issueLabels[i])) return true;
        }
        return false;
    });
}

// 与前端 _matchSeverityLevelJS 保持一致
function matchSeverityLevel(value) {
    if (!value) return null;
    const v = String(value).trim();
    if (!v) return null;
    const vl = v.toLowerCase();
    const priorityMap = {
        'p0': 'blocker', 's0': 'blocker', 'highest': 'blocker', '紧急': 'blocker',
        'p1': 'critical', 's1': 'critical', 'high': 'critical', '高': 'critical', '严重': 'critical',
        'p2': 'major', 's2': 'major', 'medium': 'major', '中': 'major', '一般': 'major',
        'p3': 'minor', 's3': 'minor', 'low': 'minor', '低': 'minor', '轻微': 'minor',
        'p4': 'trivial', 's4': 'trivial', 'lowest': 'trivial', '最低': 'trivial', '提示': 'trivial'
    };
    if (priorityMap[vl]) return priorityMap[vl];
    if (/^\d$/.test(v)) {
        const numMap = { '1': 'blocker', '2': 'critical', '3': 'major', '4': 'minor', '5': 'trivial' };
        if (numMap[v]) return numMap[v];
    }
    const pm = vl.match(/^[ps](\d)$/);
    if (pm) {
        const nm = { '1': 'blocker', '2': 'critical', '3': 'major', '4': 'minor', '5': 'trivial' };
        if (nm[pm[1]]) return nm[pm[1]];
    }
    const patterns = {
        'blocker': ['blocker', 'block', 'fatal', '致命', '阻断', 'urgent', 'immediate', 'showstopper'],
        'critical': ['critical', 'crit', '严重', '重要'],
        'major': ['major', 'main', '中等', '一般', 'normal', 'moderate', '普通'],
        'minor': ['minor', '轻微', 'small', 'less'],
        'trivial': ['trivial', 'triv', '很小', '微小', 'cosmetic', 'info', 'informational', 'suggestion', '建议']
    };
    for (const level in patterns) {
        for (let i = 0; i < patterns[level].length; i++) {
            if (vl.indexOf(patterns[level][i]) >= 0) return level;
        }
    }
    const cnNum = { '一': 'blocker', '二': 'critical', '三': 'major', '四': 'minor', '五': 'trivial' };
    if (cnNum[v]) return cnNum[v];
    return null;
}

// 与前端 _normalizeDateJS 保持一致
function normalizeDateJS(d) {
    if (!d) return '';
    const s = String(d).trim();
    if (!s || s.toLowerCase() === 'nan' || s.toLowerCase() === 'none' || s.toLowerCase() === 'nat') return '';
    let m = s.match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
    if (m) return m[1] + '-' + m[2].padStart(2, '0') + '-' + m[3].padStart(2, '0');
    const m2 = s.match(/(\d{1,2})[-/]([A-Za-z]{3})[-/](\d{4})/);
    if (m2) {
        const months = { jan: '01', feb: '02', mar: '03', apr: '04', may: '05', jun: '06', jul: '07', aug: '08', sep: '09', oct: '10', nov: '11', dec: '12' };
        const mon = months[m2[2].toLowerCase()];
        if (mon) return m2[3] + '-' + mon + '-' + m2[1].padStart(2, '0');
    }
    const m3 = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
    if (m3) return m3[3] + '-' + m3[1].padStart(2, '0') + '-' + m3[2].padStart(2, '0');
    const m4 = s.match(/^(\d{4})(\d{2})(\d{2})/);
    if (m4) return m4[1] + '-' + m4[2] + '-' + m4[3];
    return '';
}

// 与前端 _recomputeStatsFromIssues 保持一致（大数组聚合，避免阻塞主线程）
function aggregateIssues(issues) {
    const total = issues.length;
    const bySeverity = { blocker: 0, critical: 0, major: 0, minor: 0, trivial: 0 };
    const bySeverityResolved = { blocker: 0, critical: 0, major: 0, minor: 0, trivial: 0 };
    const byModule = {};
    const byDeveloper = {};
    let resolved = 0;
    const dailyStats = {};
    const unresolvedStatusDist = {};
    const blockerUnresolvedStatusDist = {};
    const severityValues = new Set();

    issues.forEach(issue => {
        const sevRaw = (issue.severity || '').trim();
        let sevLevel = null;
        if (sevRaw) {
            severityValues.add(sevRaw);
            sevLevel = matchSeverityLevel(sevRaw);
            if (sevLevel) bySeverity[sevLevel]++;
        }

        const mod = (issue.module || '').trim();
        if (mod) {
            if (!byModule[mod]) byModule[mod] = { total: 0, resolved: 0, unresolved: 0 };
            byModule[mod].total++;
        }

        const dev = (issue.developer || '').trim();
        if (dev) {
            if (!byDeveloper[dev]) byDeveloper[dev] = { total: 0, resolved: 0, unresolved: 0, modules: [] };
            byDeveloper[dev].total++;
            if (mod && byDeveloper[dev].modules.indexOf(mod) < 0) byDeveloper[dev].modules.push(mod);
        }

        const status = (issue.status || '').toLowerCase();
        const isResolved = ['resolved', 'fixed', 'closed', 'done', '已解决', '已关闭'].some(kw => status.indexOf(kw) >= 0);

        if (isResolved) {
            resolved++;
            if (mod && byModule[mod]) byModule[mod].resolved++;
            if (dev && byDeveloper[dev]) byDeveloper[dev].resolved++;
            if (sevLevel && bySeverityResolved[sevLevel] !== undefined) bySeverityResolved[sevLevel]++;
        } else {
            if (mod && byModule[mod]) byModule[mod].unresolved++;
            if (dev && byDeveloper[dev]) byDeveloper[dev].unresolved++;
            const statusRaw = (issue.status || '').trim();
            if (statusRaw) {
                unresolvedStatusDist[statusRaw] = (unresolvedStatusDist[statusRaw] || 0) + 1;
                if (sevLevel === 'blocker') blockerUnresolvedStatusDist[statusRaw] = (blockerUnresolvedStatusDist[statusRaw] || 0) + 1;
            }
        }

        const created = (issue.create_date || issue.created_date || '').trim();
        if (created) {
            const dk = normalizeDateJS(created);
            if (dk) {
                if (!dailyStats[dk]) dailyStats[dk] = { new: 0, resolved: 0 };
                dailyStats[dk].new++;
            }
        }
        const resolvedDate = (issue.resolved_date || '').trim();
        if (resolvedDate) {
            const dk2 = normalizeDateJS(resolvedDate);
            if (dk2) {
                if (!dailyStats[dk2]) dailyStats[dk2] = { new: 0, resolved: 0 };
                dailyStats[dk2].resolved++;
            }
        }
    });

    function calcRate(count) { return total > 0 ? Math.round(count / total * 1000) / 10 : 0; }
    const bcTotal = bySeverity.blocker + bySeverity.critical;
    const bcResolved = bySeverityResolved.blocker + bySeverityResolved.critical;
    const bcRate = bcTotal > 0 ? Math.round(bcResolved / bcTotal * 1000) / 10 : 0;

    const summary = {
        total_issues: total,
        total_resolved: resolved,
        total_unresolved: total - resolved,
        resolution_rate: calcRate(resolved),
        blocker_total: bySeverity.blocker,
        blocker_resolved: bySeverityResolved.blocker,
        blocker_unresolved: bySeverity.blocker - bySeverityResolved.blocker,
        blocker_unresolved_rate: bySeverity.blocker > 0 ? Math.round((bySeverity.blocker - bySeverityResolved.blocker) / bySeverity.blocker * 1000) / 10 : 0,
        blocker_rate: calcRate(bySeverity.blocker),
        critical_total: bySeverity.critical,
        critical_resolved: bySeverityResolved.critical,
        critical_rate: calcRate(bySeverity.critical),
        major_total: bySeverity.major,
        major_resolved: bySeverityResolved.major,
        major_rate: calcRate(bySeverity.major),
        minor_total: bySeverity.minor,
        minor_resolved: bySeverityResolved.minor,
        minor_rate: calcRate(bySeverity.minor),
        trivial_total: bySeverity.trivial,
        trivial_resolved: bySeverityResolved.trivial,
        trivial_rate: calcRate(bySeverity.trivial),
        blocker_critical_total: bcTotal,
        blocker_critical_rate: bcRate,
        unresolved_status_dist: unresolvedStatusDist,
        blocker_unresolved_status_dist: blockerUnresolvedStatusDist
    };

    const moduleStats = {};
    for (const m in byModule) {
        moduleStats[m] = { total: byModule[m].total, resolved: byModule[m].resolved, unresolved: byModule[m].unresolved };
    }
    const devStats = {};
    for (const dv in byDeveloper) {
        devStats[dv] = {
            total: byDeveloper[dv].total,
            resolved: byDeveloper[dv].resolved,
            unresolved: byDeveloper[dv].unresolved,
            modules: byDeveloper[dv].modules.slice(0, 5)
        };
    }
    const dailyStatsList = Object.keys(dailyStats).sort().map(d => ({
        date: d, new_count: dailyStats[d].new, resolved_count: dailyStats[d].resolved
    }));

    const resolvedUnverified = [];
    issues.forEach(issue => {
        const st = (issue.status || '').toLowerCase().trim();
        if (st && (st.indexOf('resolved') >= 0 || st.indexOf('已解决') >= 0)
            && st.indexOf('verified') < 0 && st.indexOf('closed') < 0
            && st.indexOf('done') < 0 && st.indexOf('已关闭') < 0) {
            resolvedUnverified.push({
                issue_id: issue.id || issue.issue_id || '',
                title: issue.title || '',
                module: issue.module || '',
                severity: issue.severity || '',
                status: issue.status || '',
                developer: issue.developer || '',
                resolution: issue.resolution || '',
                create_date: issue.create_date || ''
            });
        }
    });

    return {
        summary: summary,
        module_stats: moduleStats,
        dev_stats: devStats,
        daily_stats: dailyStatsList,
        resolved_unverified: resolvedUnverified,
        severity_values: Array.from(severityValues)
    };
}

self.onmessage = function(e) {
    const msg = e.data;
    try {
        switch (msg.type) {
            case 'init':
                allData = msg.data || [];
                filteredData = allData;
                currentSort = { field: null, order: 'asc' };
                currentFilter = null;
                currentSearch = { query: '', fields: [] };
                self.postMessage({
                    type: 'result',
                    data: [],
                    total: allData.length,
                    page: 1,
                    pageSize: msg.pageSize || 50,
                    totalPages: Math.ceil(allData.length / (msg.pageSize || 50)),
                    message: '初始化完成，共 ' + allData.length + ' 条数据'
                });
                break;

            case 'sort':
                currentSort = { field: msg.field, order: msg.order || 'asc' };
                applyAllFilters();
                self.postMessage({
                    type: 'sorted',
                    total: filteredData.length,
                    field: msg.field,
                    order: msg.order
                });
                break;

            case 'filter':
                currentFilter = msg.conditions || null;
                applyAllFilters();
                self.postMessage({
                    type: 'filtered',
                    total: filteredData.length
                });
                break;

            case 'search':
                currentSearch = {
                    query: msg.query || '',
                    fields: msg.fields || []
                };
                applyAllFilters();
                self.postMessage({
                    type: 'searched',
                    total: filteredData.length
                });
                break;

            case 'paginate': {
                const result = paginate(filteredData, msg.page || 1, msg.pageSize || 50);
                self.postMessage({
                    type: 'result',
                    data: result.data,
                    total: result.total,
                    page: result.page,
                    pageSize: result.pageSize,
                    totalPages: result.totalPages
                });
                break;
            }

            case 'get_page': {
                // 组合操作：应用筛选+排序+分页
                applyAllFilters();
                const pageResult = paginate(filteredData, msg.page || 1, msg.pageSize || 50);
                self.postMessage({
                    type: 'result',
                    data: pageResult.data,
                    total: pageResult.total,
                    page: pageResult.page,
                    pageSize: pageResult.pageSize,
                    totalPages: pageResult.totalPages
                });
                break;
            }

            case 'get_all':
                self.postMessage({
                    type: 'all_data',
                    data: filteredData,
                    total: filteredData.length
                });
                break;

            // v8.0: 一次性组合查询（关键字 + 状态 + 排序），用于虚拟滚动列表
            case 'apply_query': {
                let result = allData;
                const keywords = (msg.keywords || []).map(k => String(k).toLowerCase().trim()).filter(Boolean);
                if (keywords.length > 0) {
                    result = result.filter(item => {
                        const mod = String(item.module || '').toLowerCase();
                        return keywords.some(kw => mod.indexOf(kw) >= 0);
                    });
                }
                if (msg.status === 'open') {
                    result = result.filter(item => !isIssueResolved(item));
                } else if (msg.status === 'resolved') {
                    result = result.filter(item => isIssueResolved(item));
                }
                // v8.0: 通用文本搜索（多字段 OR）
                if (msg.search) {
                    const q = String(msg.search).toLowerCase().trim();
                    const fields = (msg.searchFields && msg.searchFields.length)
                        ? msg.searchFields : ['issue_id', 'title', 'module', 'developer'];
                    if (q) {
                        result = result.filter(item => fields.some(f =>
                            String(item[f] !== undefined && item[f] !== null ? item[f] : '').toLowerCase().indexOf(q) >= 0));
                    }
                }
                if (msg.sortField) {
                    result = sortData(result, msg.sortField, msg.sortOrder || 'asc');
                }
                filteredData = result;
                self.postMessage({
                    type: 'query_result',
                    reqId: msg.reqId,
                    data: result,
                    total: result.length
                });
                break;
            }

            // v8.0: Labels OR 匹配
            case 'filter_labels': {
                const result = filterByLabels(allData, msg.labels || []);
                filteredData = result;  // 后续 aggregate(useFiltered) 直接复用，避免重复传输
                self.postMessage({
                    type: 'labels_result',
                    reqId: msg.reqId,
                    data: result,
                    total: result.length
                });
                break;
            }

            // v8.0: 大数组分组聚合（默认 allData，也可传入 data）
            case 'aggregate': {
                const source = Array.isArray(msg.data) ? msg.data
                    : (msg.useFiltered ? filteredData : allData);
                const agg = aggregateIssues(source);
                self.postMessage({
                    type: 'aggregate_result',
                    reqId: msg.reqId,
                    data: agg
                });
                break;
            }

            case 'reset':
                allData = [];
                filteredData = [];
                currentSort = { field: null, order: 'asc' };
                currentFilter = null;
                currentSearch = { query: '', fields: [] };
                self.postMessage({ type: 'reset_done' });
                break;

            default:
                self.postMessage({ type: 'error', message: '未知消息类型: ' + msg.type });
        }
    } catch (err) {
        self.postMessage({ type: 'error', reqId: msg && msg.reqId, message: err.message });
    }
};
