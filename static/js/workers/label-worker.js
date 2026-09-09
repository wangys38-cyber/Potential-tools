// label-worker.js - Labels 筛选分析 Web Worker
// 1) 大 Excel/CSV 在后台线程解析（importScripts 加载 SheetJS），分批构建问题数据，先回传预览再回传全量
// 2) 大数据量的筛选、分组统计、趋势日聚合在后台执行，避免阻塞 UI
// Worker 失败时主线程自动降级为同步逻辑（见 label_filter.html）
//
// 消息协议：
//   入: {action:'parse', buffer:ArrayBuffer}
//       {action:'query', reqId, criteria:{selectedLabels,mode,search,status,severity}}
//   出: {type:'progress', percent, text}
//       {type:'preview', issues:[前N条]}
//       {type:'done', issues, labels, labelCounts, severities}
//       {type:'queryResult', reqId, indices, groups, daily}
//       {type:'error', message}

var XLSX_CDN = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js';
var PREVIEW_N = 200;       // 先渲染的预览行数
var BUILD_BATCH = 3000;    // 构建问题数据的批大小（setTimeout 让出事件循环）
var RESOLVED_STATUSES = ['resolved', 'closed', 'done', '已解决', '已关闭', '已完成', 'fixed'];

var _issues = [];

/* ============ 与主线程一致的纯工具函数（保持解析结果一致） ============ */

function fixEncoding(str) {
    if (!str || typeof str !== 'string') return str;
    var hasMojibake = /[ÃÂâäåæçèéêëìíîïðñòóôõöøùúûüýþÿ]/.test(str);
    if (!hasMojibake) return str;
    try {
        var bytes = new Uint8Array(str.length);
        for (var i = 0; i < str.length; i++) bytes[i] = str.charCodeAt(i) & 0xff;
        var fixed = new TextDecoder('utf-8').decode(bytes);
        if (/[一-龥]/.test(fixed)) return fixed;
        return str;
    } catch (e) { return str; }
}

function normalizeHeader(s) {
    return String(s || '').toLowerCase().replace(/[\s_\-]+/g, '');
}

function findColumn(headers, keywords) {
    for (var i = 0; i < headers.length; i++) {
        var h = normalizeHeader(headers[i]);
        for (var k = 0; k < keywords.length; k++) {
            if (h && h.indexOf(normalizeHeader(keywords[k])) >= 0) return i;
        }
    }
    return -1;
}

function findAllColumns(headers, keywords) {
    var result = [];
    for (var i = 0; i < headers.length; i++) {
        var h = normalizeHeader(headers[i]);
        for (var k = 0; k < keywords.length; k++) {
            if (h && h.indexOf(normalizeHeader(keywords[k])) >= 0) { result.push(i); break; }
        }
    }
    return result;
}

function getValue(row, index, defaultValue) {
    if (index >= 0 && index < row.length) return fixEncoding(String(row[index]).trim());
    return defaultValue;
}

function parseLabels(labelStr) {
    if (!labelStr) return [];
    var str = String(labelStr);
    if (!str.trim()) return [];
    var labels = [];
    var trimmed = str.trim();
    if (trimmed.charAt(0) === '[' && trimmed.charAt(trimmed.length - 1) === ']') {
        try {
            var parsed = JSON.parse(trimmed);
            if (Array.isArray(parsed)) labels = parsed.map(String);
        } catch (e) { /* 非 JSON，继续 */ }
    }
    if (labels.length === 0) {
        str = str.replace(/[\u00A0\u1680\u2000-\u200B\u202F\u205F\u3000\uFEFF]/g, ' ');
        var hasSpecialSeparator = /[,，;；\n\r\t|]/.test(str);
        if (hasSpecialSeparator) {
            labels = str.split(/[,，;；\n\r\t|\s]+/);
        } else {
            var regex = /"([^"]+)"|'([^']+)'|(\S+)/g;
            var match;
            while ((match = regex.exec(str)) !== null) {
                labels.push(match[1] || match[2] || match[3]);
            }
        }
    }
    return labels
        .map(function(l) { return String(l).trim().replace(/^["']|["']$/g, ''); })
        .filter(function(l) { return l && l.length > 0; });
}

function isResolved(issue) {
    var s = (issue.status || '').toLowerCase();
    if (!s) return false;
    return RESOLVED_STATUSES.some(function(k) { return s.indexOf(k) >= 0; });
}

function parseDate(dateStr) {
    if (!dateStr) return null;
    var num = Number(dateStr);
    if (!isNaN(num) && num > 20000 && num < 80000) {
        var jsDate = new Date((num - 25569) * 86400 * 1000);
        if (!isNaN(jsDate.getTime())) return jsDate;
    }
    var formats = [
        /^(\d{4})-(\d{1,2})-(\d{1,2})/,
        /^(\d{1,2})\/(\d{1,2})\/(\d{4})/,
        /^(\d{1,2})\/(\d{1,2})\/(\d{2})/,
        /^(\d{4})年(\d{1,2})月(\d{1,2})日/
    ];
    for (var fi = 0; fi < formats.length; fi++) {
        var fmt = formats[fi];
        var m = String(dateStr).match(fmt);
        if (m) {
            var y, mo, d;
            if (fi === 0) { y = +m[1]; mo = +m[2]; d = +m[3]; }
            else if (fi === 1) { mo = +m[1]; d = +m[2]; y = +m[3]; }
            else if (fi === 2) { mo = +m[1]; d = +m[2]; y = 2000 + (+m[3]); }
            else { y = +m[1]; mo = +m[2]; d = +m[3]; }
            if (y > 2000 && mo >= 1 && mo <= 12 && d >= 1 && d <= 31) return new Date(y, mo - 1, d);
        }
    }
    var dd = new Date(dateStr);
    return isNaN(dd.getTime()) ? null : dd;
}

/* ============ 工作簿解析 ============ */

self.onmessage = function(e) {
    var msg = e.data;
    try {
        if (msg.action === 'parse') {
            parseWorkbook(msg.buffer);
        } else if (msg.action === 'query') {
            runQuery(msg);
        } else if (msg.action === 'ping') {
            self.postMessage({ type: 'pong' });
        }
    } catch (err) {
        self.postMessage({ type: 'error', message: err && err.message ? err.message : String(err) });
    }
};

function parseWorkbook(buffer) {
    var start = function() {
        self.postMessage({ type: 'progress', percent: 25, text: '正在解析工作簿...' });
        var workbook = XLSX.read(buffer, { type: 'array' });
        var firstSheet = workbook.Sheets[workbook.SheetNames[0]];
        var rows = XLSX.utils.sheet_to_json(firstSheet, { header: 1, defval: '' });
        self.postMessage({ type: 'progress', percent: 45, text: '正在构建问题数据...' });
        buildIssues(rows);
    };
    if (typeof XLSX === 'undefined') {
        self.postMessage({ type: 'progress', percent: 10, text: '正在加载解析组件...' });
        importScripts(XLSX_CDN);
    }
    start();
}

function buildIssues(rows) {
    _issues = [];
    if (!rows || rows.length < 2) {
        self.postMessage({ type: 'done', issues: [], labels: [], labelCounts: {}, severities: [] });
        return;
    }
    var headers = rows[0].map(function(h) { return fixEncoding(String(h).trim().toLowerCase()); });
    var fieldMap = {
        id: findColumn(headers, ['key', 'id', '问题编号', '编号', 'issue key']),
        title: findColumn(headers, ['summary', 'title', '标题', '问题标题', 'subject']),
        module: findColumn(headers, ['component', 'module', '模块', '组件', 'components']),
        developer: findColumn(headers, ['assignee', 'developer', '负责人', '处理人', '经办人']),
        status: findColumn(headers, ['status', '状态', '问题状态']),
        severity: findColumn(headers, ['priority', 'severity', '严重级别', '优先级', '严重程度']),
        labelsCols: findAllColumns(headers, ['labels', 'label', '标签', 'tag', 'tags', 'issue labels', 'issue label', 'bug labels', 'bug label', 'work item labels', 'work item tag']),
        created: findColumn(headers, ['created', 'create date', '创建时间', '创建日期']),
        resolved: findColumn(headers, ['resolved', 'resolve date', '解决时间', '解决日期', 'resolutiondate', 'resolution date'])
    };

    var total = rows.length;
    var idx = 1;
    var previewSent = false;

    function processBatch() {
        var end = Math.min(idx + BUILD_BATCH, total);
        for (; idx < end; idx++) {
            var row = rows[idx];
            if (!row || row.length === 0) continue;
            var labelStrs = (fieldMap.labelsCols || [])
                .map(function(colIdx) { return getValue(row, colIdx, ''); })
                .filter(function(v) { return v; });
            var issue = {
                id: getValue(row, fieldMap.id, 'ISSUE-' + idx),
                title: getValue(row, fieldMap.title, ''),
                module: getValue(row, fieldMap.module, ''),
                developer: getValue(row, fieldMap.developer, ''),
                status: getValue(row, fieldMap.status, ''),
                severity: getValue(row, fieldMap.severity, ''),
                labels: parseLabels(labelStrs.join(' ')),
                created: getValue(row, fieldMap.created, ''),
                resolved: getValue(row, fieldMap.resolved, '')
            };
            if (issue.title || issue.id !== 'ISSUE-' + idx) _issues.push(issue);

            if (!previewSent && _issues.length >= PREVIEW_N) {
                previewSent = true;
                self.postMessage({ type: 'preview', issues: _issues.slice(0, PREVIEW_N) });
            }
        }
        self.postMessage({ type: 'progress', percent: 45 + Math.round((idx - 1) / (total - 1) * 40), text: '正在构建问题数据 ' + idx + ' / ' + total });
        if (idx < total) {
            setTimeout(processBatch, 0);
        } else {
            finishBuild();
        }
    }
    processBatch();
}

function finishBuild() {
    self.postMessage({ type: 'progress', percent: 90, text: '正在提取 Labels 与统计...' });
    var labelSet = {};
    var labelCounts = {};
    var severitySet = {};
    for (var i = 0; i < _issues.length; i++) {
        var issue = _issues[i];
        for (var j = 0; j < issue.labels.length; j++) {
            var lb = issue.labels[j];
            labelSet[lb] = true;
            labelCounts[lb] = (labelCounts[lb] || 0) + 1;
        }
        if (issue.severity) severitySet[issue.severity] = true;
    }
    var labels = Object.keys(labelSet).sort();
    var severities = Object.keys(severitySet).sort();
    self.postMessage({
        type: 'progress',
        percent: 100,
        text: '分析完成'
    });
    self.postMessage({
        type: 'done',
        issues: _issues,
        labels: labels,
        labelCounts: labelCounts,
        severities: severities
    });
}

/* ============ 筛选 + 聚合查询 ============ */

function matchIssue(issue, c) {
    if (c.selectedLabels && c.selectedLabels.length > 0) {
        var ok;
        if (c.mode === 'all') {
            ok = c.selectedLabels.every(function(l) { return issue.labels.indexOf(l) >= 0; });
        } else {
            ok = issue.labels.some(function(l) { return c.selectedLabels.indexOf(l) >= 0; });
        }
        if (!ok) return false;
    }
    if (c.search) {
        var target = (issue.title + ' ' + issue.id).toLowerCase();
        if (target.indexOf(c.search) < 0) return false;
    }
    if (c.status === 'resolved' && !isResolved(issue)) return false;
    if (c.status === 'unresolved' && isResolved(issue)) return false;
    if (c.severity && issue.severity !== c.severity) return false;
    return true;
}

function runQuery(msg) {
    var c = msg.criteria || {};
    var indices = [];
    var groups = {
        severity: {}, module: {}, developer: {}, status: {},
        total: 0, resolved: 0
    };
    var dailyNew = {}, dailyResolved = {}, dateSet = {};

    function bump(map, key) { map[key] = (map[key] || 0) + 1; }

    for (var i = 0; i < _issues.length; i++) {
        var issue = _issues[i];
        if (!matchIssue(issue, c)) continue;
        indices.push(i);
        groups.total++;
        bump(groups.severity, issue.severity || '未设置');
        bump(groups.module, issue.module || '未设置');
        bump(groups.developer, issue.developer || '未分配');
        bump(groups.status, issue.status || '未设置');
        var resolved = isResolved(issue);
        if (resolved) groups.resolved++;

        var created = parseDate(issue.created);
        if (created) { var ck = created.toDateString(); dateSet[ck] = true; dailyNew[ck] = (dailyNew[ck] || 0) + 1; }
        var rd = parseDate(issue.resolved);
        if (rd && resolved) { var rk = rd.toDateString(); dateSet[rk] = true; dailyResolved[rk] = (dailyResolved[rk] || 0) + 1; }
    }

    self.postMessage({
        type: 'queryResult',
        reqId: msg.reqId,
        indices: indices,
        groups: groups,
        daily: { dailyNew: dailyNew, dailyResolved: dailyResolved, dates: Object.keys(dateSet) }
    });
}
