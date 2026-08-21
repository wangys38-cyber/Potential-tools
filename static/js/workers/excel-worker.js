// excel-worker.js - Excel/CSV解析Web Worker
// 处理大文件CSV解析，支持进度回调，避免阻塞主线程
// 注意：xlsx格式需要SheetJS库，本worker优先处理CSV，xlsx需传入解析后的数据

self.onmessage = function(e) {
    var data = e.data;
    var action = data.action;

    if (action === 'parseCSV') {
        parseCSV(data.content, data.options || {});
    } else if (action === 'parseCSVChunks') {
        parseCSVChunks(data.chunks, data.options || {});
    } else if (action === 'analyzeData') {
        analyzeData(data.rows, data.headers, data.options || {});
    } else if (action === 'ping') {
        self.postMessage({ type: 'pong' });
    }
};

function parseCSV(content, options) {
    var delimiter = options.delimiter || detectDelimiter(content);
    var hasHeader = options.hasHeader !== false;
    var chunkSize = options.chunkSize || 2000;
    var lines = content.split(/\r?\n/);
    var total = lines.length;
    var headers = [];
    var rows = [];
    var processed = 0;

    function processChunk() {
        var end = Math.min(processed + chunkSize, total);
        for (var i = processed; i < end; i++) {
            var line = lines[i];
            if (!line || line.trim().length === 0) continue;
            var fields = parseCSVLine(line, delimiter);
            if (i === 0 && hasHeader) {
                headers = fields;
            } else {
                rows.push(fields);
            }
        }
        processed = end;
        var progress = Math.round(processed / total * 100);

        self.postMessage({
            type: 'progress',
            progress: progress,
            processed: processed,
            total: total,
            rowsCount: rows.length
        });

        if (processed < total) {
            setTimeout(processChunk, 0);
        } else {
            self.postMessage({
                type: 'done',
                headers: headers,
                rows: rows,
                rowCount: rows.length,
                colCount: headers.length
            });
        }
    }

    processChunk();
}

function parseCSVChunks(chunks, options) {
    var delimiter = options.delimiter || ',';
    var hasHeader = options.hasHeader !== false;
    var headers = [];
    var rows = [];
    var lineOffset = 0;
    var isFirst = true;

    for (var c = 0; c < chunks.length; c++) {
        var lines = chunks[c].split(/\r?\n/);
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (!line || line.trim().length === 0) continue;
            var fields = parseCSVLine(line, delimiter);
            if (isFirst && hasHeader) {
                headers = fields;
                isFirst = false;
            } else {
                rows.push(fields);
            }
        }
        lineOffset += lines.length;

        self.postMessage({
            type: 'progress',
            progress: Math.round((c + 1) / chunks.length * 100),
            processed: c + 1,
            total: chunks.length,
            rowsCount: rows.length
        });
    }

    self.postMessage({
        type: 'done',
        headers: headers,
        rows: rows,
        rowCount: rows.length,
        colCount: headers.length
    });
}

function detectDelimiter(content) {
    var firstLine = content.split(/\r?\n/)[0] || '';
    var delimiters = [',', '\t', ';', '|'];
    var best = ',';
    var bestCount = 0;
    for (var i = 0; i < delimiters.length; i++) {
        var count = firstLine.split(delimiters[i]).length - 1;
        if (count > bestCount) {
            bestCount = count;
            best = delimiters[i];
        }
    }
    return best;
}

function parseCSVLine(line, delimiter) {
    var result = [];
    var current = '';
    var inQuotes = false;
    for (var i = 0; i < line.length; i++) {
        var char = line[i];
        if (inQuotes) {
            if (char === '"') {
                if (line[i + 1] === '"') {
                    current += '"';
                    i++;
                } else {
                    inQuotes = false;
                }
            } else {
                current += char;
            }
        } else {
            if (char === '"') {
                inQuotes = true;
            } else if (char === delimiter) {
                result.push(current.trim());
                current = '';
            } else {
                current += char;
            }
        }
    }
    result.push(current.trim());
    return result;
}

function analyzeData(rows, headers, options) {
    // 基础数据分析：统计、去重、空值检测
    var colCount = headers.length;
    var stats = [];
    var totalRows = rows.length;

    for (var col = 0; col < colCount; col++) {
        var values = [];
        var emptyCount = 0;
        var uniqueSet = {};
        var numericCount = 0;
        var sum = 0;
        var min = Infinity;
        var max = -Infinity;

        for (var r = 0; r < rows.length; r++) {
            var val = rows[r][col] !== undefined ? String(rows[r][col]) : '';
            if (val === '' || val === null || val === undefined) {
                emptyCount++;
            } else {
                values.push(val);
                uniqueSet[val] = true;
                var num = parseFloat(val);
                if (!isNaN(num) && isFinite(num)) {
                    numericCount++;
                    sum += num;
                    if (num < min) min = num;
                    if (num > max) max = num;
                }
            }
        }

        stats.push({
            header: headers[col] || ('col_' + col),
            total: totalRows,
            empty: emptyCount,
            emptyRate: totalRows > 0 ? Math.round(emptyCount / totalRows * 100) : 0,
            unique: Object.keys(uniqueSet).length,
            isNumeric: numericCount > totalRows * 0.5,
            numericCount: numericCount,
            avg: numericCount > 0 ? (sum / numericCount).toFixed(2) : null,
            min: min === Infinity ? null : min,
            max: max === -Infinity ? null : max
        });

        self.postMessage({
            type: 'progress',
            progress: Math.round((col + 1) / colCount * 100),
            processed: col + 1,
            total: colCount
        });
    }

    self.postMessage({
        type: 'done',
        stats: stats,
        totalRows: totalRows,
        totalCols: colCount
    });
}
