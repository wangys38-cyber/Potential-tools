// log-worker.js - 日志分析Web Worker
// 处理大文件日志的关键词匹配、统计、聚合，避免阻塞主线程
//
// 消息类型：
//   analyze        {content, chunkSize}                 一次性分析整段文本（分片让出事件循环）
//   analyzeChunks  {chunks:[...]}                       多段文本分析
//   streamInit     {}                                   初始化流式分析状态（配合大文件分片读取）
//   streamLines    {lines:[...], startLineNo:N}         送入一批完整行（行号全局连续）
//   streamEnd      {}                                   结束流式分析，回传最终结果
//   setResults     {results:[...]}                      缓存分析结果，供 filterView 使用
//   filterView     {type, query, sortBy, reqId}         对缓存结果做筛选/排序（大数据量不阻塞主线程）
//   sortView       {results, sortBy, reqId}             对传入结果直接排序
//   ping

var PATTERNS = {
    crash: { label: '死机/崩溃', regex: /(?:panic|fatal|kernel\s+panic|watchdog|hardfault|busfault|memmanage|assert\s+failed|abort|crash|死机|崩溃)/i },
    reboot: { label: '异常重启', regex: /(?:reboot|restart|reset|watchdog\s+reset|power\s+on|power_on|POR|异常重启|重启)/i },
    memory: { label: '内存问题', regex: /(?:malloc\s+fail|out\s+of\s+memory|OOM|memory\s+leak|heap\s+overflow|stack\s+overflow|buffer\s+overflow|内存不足|内存溢出|内存泄漏)/i },
    power: { label: '功耗异常', regex: /(?:low\s+battery|battery\s+low|overheat|thermal\s+shutdown|power\s+fail|undervoltage|功耗|低电|过热|欠压)/i },
    error: { label: '通用错误', regex: /(?:error|err|fail|failed|exception|invalid|错误|失败|异常)/i },
    warning: { label: '警告信息', regex: /(?:warn|warning|注意|警告)/i }
};

// 严重程度排序权重（数字越小越严重）
var SEVERITY_ORDER = { crash: 0, memory: 1, reboot: 2, power: 3, error: 4, warning: 5 };

function classifyLine(line) {
    for (var type in PATTERNS) {
        if (PATTERNS.hasOwnProperty(type) && PATTERNS[type].regex.test(line)) {
            return type;
        }
    }
    return null;
}

function emptyCounts() {
    return { crash: 0, reboot: 0, memory: 0, power: 0, error: 0, warning: 0 };
}

function sortBySeverity(arr) {
    arr.sort(function(a, b) {
        var sa = SEVERITY_ORDER.hasOwnProperty(a.type) ? SEVERITY_ORDER[a.type] : 99;
        var sb = SEVERITY_ORDER.hasOwnProperty(b.type) ? SEVERITY_ORDER[b.type] : 99;
        if (sa !== sb) return sa - sb;
        return (a.line || 0) - (b.line || 0);
    });
    return arr;
}

// 流式分析状态
var streamState = null;
// 缓存的分析结果（供 filterView 使用，避免每次筛选都跨线程拷贝全量数据）
var cachedResults = null;

self.onmessage = function(e) {
    var data = e.data;
    var action = data.action;

    if (action === 'analyze') {
        analyzeLogs(data.content, data.chunkSize);
    } else if (action === 'analyzeChunks') {
        analyzeInChunks(data.chunks);
    } else if (action === 'streamInit') {
        streamState = { results: [], counts: emptyCounts(), totalLines: 0 };
        self.postMessage({ type: 'streamReady' });
    } else if (action === 'streamLines') {
        handleStreamLines(data.lines, data.startLineNo || 0);
    } else if (action === 'streamEnd') {
        finishStream();
    } else if (action === 'setResults') {
        cachedResults = data.results || [];
        self.postMessage({ type: 'resultsCached', total: cachedResults.length });
    } else if (action === 'filterView') {
        filterView(data);
    } else if (action === 'sortView') {
        var sorted = (data.results || []).slice();
        sortBySeverity(sorted);
        self.postMessage({ type: 'viewDone', reqId: data.reqId, results: sorted, total: sorted.length });
    } else if (action === 'ping') {
        self.postMessage({ type: 'pong' });
    }
};

function handleStreamLines(lines, startLineNo) {
    if (!streamState || !lines) return;
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        streamState.totalLines++;
        if (!line || line.trim().length === 0) continue;
        var type = classifyLine(line);
        if (type) {
            streamState.counts[type]++;
            streamState.results.push({
                line: startLineNo + i + 1,
                type: type,
                label: PATTERNS[type].label,
                text: line.substring(0, 500)
            });
        }
    }
    self.postMessage({
        type: 'progress',
        processed: streamState.totalLines,
        found: streamState.results.length
    });
}

function finishStream() {
    if (!streamState) {
        self.postMessage({ type: 'done', results: [], counts: emptyCounts(), totalLines: 0, anomalyCount: 0 });
        return;
    }
    var state = streamState;
    streamState = null;
    cachedResults = state.results;
    self.postMessage({
        type: 'done',
        results: state.results,
        counts: state.counts,
        totalLines: state.totalLines,
        anomalyCount: state.results.length
    });
}

function filterView(data) {
    if (!cachedResults) {
        // 主线程尚未同步结果：通知其回退同步过滤
        self.postMessage({ type: 'viewDone', reqId: data.reqId, results: null, emptyCache: true });
        return;
    }
    var source = cachedResults;
    var type = data.type || 'all';
    var query = data.query ? String(data.query).toLowerCase() : '';
    var out = [];
    for (var i = 0; i < source.length; i++) {
        var r = source[i];
        if (type !== 'all' && r.type !== type) continue;
        if (query && String(r.text).toLowerCase().indexOf(query) < 0) continue;
        out.push(r);
    }
    if (data.sortBy === 'severity') sortBySeverity(out);
    self.postMessage({ type: 'viewDone', reqId: data.reqId, results: out, total: out.length });
}

function analyzeLogs(content, chunkSize) {
    chunkSize = chunkSize || 5000;
    var lines = content.split(/\r?\n/);
    var total = lines.length;
    var results = [];
    var counts = emptyCounts();
    var processed = 0;

    function processChunk() {
        var end = Math.min(processed + chunkSize, total);
        for (var i = processed; i < end; i++) {
            var line = lines[i];
            if (!line || line.trim().length === 0) continue;
            var type = classifyLine(line);
            if (type) {
                counts[type]++;
                results.push({
                    line: i + 1,
                    type: type,
                    label: PATTERNS[type].label,
                    text: line.substring(0, 500)
                });
            }
        }
        processed = end;
        var progress = Math.round(processed / total * 100);

        self.postMessage({
            type: 'progress',
            progress: progress,
            processed: processed,
            total: total
        });

        if (processed < total) {
            setTimeout(processChunk, 0);
        } else {
            cachedResults = results;
            self.postMessage({
                type: 'done',
                results: results,
                counts: counts,
                totalLines: total,
                anomalyCount: results.length
            });
        }
    }

    processChunk();
}

function analyzeInChunks(chunks) {
    var results = [];
    var counts = emptyCounts();
    var totalLines = 0;
    var lineOffset = 0;

    for (var c = 0; c < chunks.length; c++) {
        var lines = chunks[c].split(/\r?\n/);
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (!line || line.trim().length === 0) continue;
            var type = classifyLine(line);
            if (type) {
                counts[type]++;
                results.push({
                    line: lineOffset + i + 1,
                    type: type,
                    label: PATTERNS[type].label,
                    text: line.substring(0, 500)
                });
            }
        }
        lineOffset += lines.length;
        totalLines += lines.length;

        self.postMessage({
            type: 'progress',
            progress: Math.round((c + 1) / chunks.length * 100),
            processed: c + 1,
            total: chunks.length
        });
    }

    cachedResults = results;
    self.postMessage({
        type: 'done',
        results: results,
        counts: counts,
        totalLines: totalLines,
        anomalyCount: results.length
    });
}
