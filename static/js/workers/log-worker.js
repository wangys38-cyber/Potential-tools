// log-worker.js - 日志分析Web Worker
// 处理大文件日志的关键词匹配、统计、聚合，避免阻塞主线程

var PATTERNS = {
    crash: { label: '死机/崩溃', regex: /(?:panic|fatal|kernel\s+panic|watchdog|hardfault|busfault|memmanage|assert\s+failed|abort|crash|死机|崩溃)/i },
    reboot: { label: '异常重启', regex: /(?:reboot|restart|reset|watchdog\s+reset|power\s+on|power_on|POR|异常重启|重启)/i },
    memory: { label: '内存问题', regex: /(?:malloc\s+fail|out\s+of\s+memory|OOM|memory\s+leak|heap\s+overflow|stack\s+overflow|buffer\s+overflow|内存不足|内存溢出|内存泄漏)/i },
    power: { label: '功耗异常', regex: /(?:low\s+battery|battery\s+low|overheat|thermal\s+shutdown|power\s+fail|undervoltage|功耗|低电|过热|欠压)/i },
    error: { label: '通用错误', regex: /(?:error|err|fail|failed|exception|invalid|错误|失败|异常)/i },
    warning: { label: '警告信息', regex: /(?:warn|warning|注意|警告)/i }
};

function classifyLine(line) {
    for (var type in PATTERNS) {
        if (PATTERNS.hasOwnProperty(type) && PATTERNS[type].regex.test(line)) {
            return type;
        }
    }
    return null;
}

self.onmessage = function(e) {
    var data = e.data;
    var action = data.action;

    if (action === 'analyze') {
        analyzeLogs(data.content, data.chunkSize);
    } else if (action === 'analyzeChunks') {
        analyzeInChunks(data.chunks);
    } else if (action === 'ping') {
        self.postMessage({ type: 'pong' });
    }
};

function analyzeLogs(content, chunkSize) {
    chunkSize = chunkSize || 5000;
    var lines = content.split(/\r?\n/);
    var total = lines.length;
    var results = [];
    var counts = { crash: 0, reboot: 0, memory: 0, power: 0, error: 0, warning: 0 };
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
    var counts = { crash: 0, reboot: 0, memory: 0, power: 0, error: 0, warning: 0 };
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

    self.postMessage({
        type: 'done',
        results: results,
        counts: counts,
        totalLines: totalLines,
        anomalyCount: results.length
    });
}
