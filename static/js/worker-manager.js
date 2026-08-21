// worker-manager.js - Web Worker管理器
// 提供统一的Worker创建、通信、进度回调和降级方案

(function() {
    var WorkerManager = {
        workers: {},
        supported: typeof Worker !== 'undefined',

        createWorker: function(workerPath, options) {
            options = options || {};
            var self = this;

            if (!this.supported && !options.forceFallback) {
                console.warn('[WorkerManager] Web Worker not supported, using fallback');
                return this.createFallback(workerPath, options);
            }

            try {
                var worker = new Worker(workerPath);
                var workerId = 'w_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
                this.workers[workerId] = worker;

                var wrapper = {
                    id: workerId,
                    worker: worker,
                    onMessage: null,
                    onProgress: null,
                    onError: null,
                    onDone: null,
                    terminated: false,

                    post: function(data) {
                        if (this.terminated) return;
                        worker.postMessage(data);
                    },

                    terminate: function() {
                        this.terminated = true;
                        worker.terminate();
                        delete WorkerManager.workers[this.id];
                    }
                };

                worker.onmessage = function(e) {
                    var msg = e.data;
                    if (msg.type === 'progress' && wrapper.onProgress) {
                        wrapper.onProgress(msg);
                    } else if (msg.type === 'done' && wrapper.onDone) {
                        wrapper.onDone(msg);
                    } else if (wrapper.onMessage) {
                        wrapper.onMessage(msg);
                    }
                };

                worker.onerror = function(err) {
                    if (wrapper.onError) {
                        wrapper.onError(err);
                    } else {
                        console.error('[WorkerManager] Worker error:', err);
                    }
                    // 出错时自动降级到主线程
                    if (options.autoFallback) {
                        console.warn('[WorkerManager] Worker failed, falling back to main thread');
                        wrapper.terminate();
                    }
                };

                return wrapper;
            } catch (e) {
                console.error('[WorkerManager] Failed to create worker:', e);
                if (!options.forceFallback) {
                    return this.createFallback(workerPath, options);
                }
                throw e;
            }
        },

        createFallback: function(workerPath, options) {
            // 降级方案：在主线程模拟Worker
            console.warn('[WorkerManager] Using main-thread fallback for', workerPath);
            var wrapper = {
                id: 'fallback_' + Date.now(),
                worker: null,
                onMessage: null,
                onProgress: null,
                onError: null,
                onDone: null,
                terminated: false,
                isFallback: true,

                post: function(data) {
                    if (this.terminated) return;
                    var self = this;
                    // 模拟异步处理
                    setTimeout(function() {
                        self._processMainThread(data);
                    }, 0);
                },

                terminate: function() {
                    this.terminated = true;
                },

                _processMainThread: function(data) {
                    // 主线程降级处理逻辑
                    if (data.action === 'analyze' && workerPath.indexOf('log-worker') >= 0) {
                        this._analyzeLogsMainThread(data);
                    } else if (data.action === 'parseCSV' && workerPath.indexOf('excel-worker') >= 0) {
                        this._parseCSVMainThread(data);
                    } else {
                        if (this.onError) this.onError({ message: 'Unsupported action in fallback: ' + data.action });
                    }
                },

                _analyzeLogsMainThread: function(data) {
                    var content = data.content || '';
                    var lines = content.split(/\r?\n/);
                    var PATTERNS = {
                        crash: /(?:panic|fatal|kernel\s+panic|watchdog|hardfault|busfault|memmanage|assert\s+failed|abort|crash|死机|崩溃)/i,
                        reboot: /(?:reboot|restart|reset|watchdog\s+reset|power\s+on|power_on|POR|异常重启|重启)/i,
                        memory: /(?:malloc\s+fail|out\s+of\s+memory|OOM|memory\s+leak|heap\s+overflow|stack\s+overflow|buffer\s+overflow|内存不足|内存溢出|内存泄漏)/i,
                        power: /(?:low\s+battery|battery\s+low|overheat|thermal\s+shutdown|power\s+fail|undervoltage|功耗|低电|过热|欠压)/i,
                        error: /(?:error|err|fail|failed|exception|invalid|错误|失败|异常)/i,
                        warning: /(?:warn|warning|注意|警告)/i
                    };
                    var LABELS = { crash: '死机/崩溃', reboot: '异常重启', memory: '内存问题', power: '功耗异常', error: '通用错误', warning: '警告信息' };
                    var results = [];
                    var counts = { crash: 0, reboot: 0, memory: 0, power: 0, error: 0, warning: 0 };
                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i];
                        if (!line || !line.trim()) continue;
                        for (var type in PATTERNS) {
                            if (PATTERNS.hasOwnProperty(type) && PATTERNS[type].test(line)) {
                                counts[type]++;
                                results.push({ line: i+1, type: type, label: LABELS[type], text: line.substring(0, 500) });
                                break;
                            }
                        }
                        if (i % 1000 === 0 && this.onProgress) {
                            this.onProgress({ progress: Math.round(i / lines.length * 100), processed: i, total: lines.length });
                        }
                    }
                    if (this.onProgress) this.onProgress({ progress: 100, processed: lines.length, total: lines.length });
                    if (this.onDone) this.onDone({ type: 'done', results: results, counts: counts, totalLines: lines.length, anomalyCount: results.length });
                },

                _parseCSVMainThread: function(data) {
                    var content = data.content || '';
                    var options = data.options || {};
                    var delimiter = options.delimiter || ',';
                    var lines = content.split(/\r?\n/);
                    var headers = [];
                    var rows = [];
                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i];
                        if (!line || !line.trim()) continue;
                        var fields = line.split(delimiter).map(function(s) { return s.trim(); });
                        if (i === 0 && options.hasHeader !== false) {
                            headers = fields;
                        } else {
                            rows.push(fields);
                        }
                        if (i % 500 === 0 && this.onProgress) {
                            this.onProgress({ progress: Math.round(i / lines.length * 100), processed: i, total: lines.length, rowsCount: rows.length });
                        }
                    }
                    if (this.onProgress) this.onProgress({ progress: 100, processed: lines.length, total: lines.length, rowsCount: rows.length });
                    if (this.onDone) this.onDone({ type: 'done', headers: headers, rows: rows, rowCount: rows.length, colCount: headers.length });
                }
            };

            return wrapper;
        },

        terminateAll: function() {
            for (var id in this.workers) {
                if (this.workers.hasOwnProperty(id)) {
                    try { this.workers[id].terminate(); } catch(e) {}
                }
            }
            this.workers = {};
        }
    };

    // 暴露到全局
    window.WorkerManager = WorkerManager;
})();
