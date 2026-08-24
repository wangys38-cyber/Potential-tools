/**
 * Excel 分析 Web Worker — v6.0 性能优化
 * 用于在后台线程处理大数据集的排序、筛选、搜索，避免阻塞主线程
 *
 * 消息协议：
 * 接收: { type: 'init', data: [...] }
 *       { type: 'sort', field: '...', order: 'asc'|'desc' }
 *       { type: 'filter', conditions: {...} }
 *       { type: 'search', query: '...', fields: [...] }
 *       { type: 'paginate', page: N, pageSize: N }
 * 发送: { type: 'result', data: [...], total: N, page: N, pageSize: N }
 *       { type: 'progress', percent: N }
 *       { type: 'error', message: '...' }
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
        if (field === 'create_date' || field === 'resolved_date' || field === 'closed_date') {
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

            case 'paginate':
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

            case 'get_page':
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

            case 'get_all':
                self.postMessage({
                    type: 'all_data',
                    data: filteredData,
                    total: filteredData.length
                });
                break;

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
        self.postMessage({ type: 'error', message: err.message });
    }
};
