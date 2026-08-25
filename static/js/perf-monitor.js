/* ===== Potential-tools 阶段五性能优化：前端性能监控 =====
 * 使用 Navigation Timing API + User Timing API 收集页面加载性能指标
 * 关键交互响应时间统计
 * 定期上报到后端 /api/frontend-metrics（可选，静默失败）
 * 系统信息页面可通过 window.PTPerf.getMetrics() 展示指标
 *
 * 通过 _navbar.html 自动引入（defer）
 */
(function(global) {
    'use strict';

    var _metrics = {
        pageLoad: null,       // 页面加载指标
        interactions: [],     // 关键交互响应时间
        maxInteractions: 50,
    };

    var _interactionMarks = {};  // 交互开始时间标记

    // ==================== 页面加载指标 ====================
    function collectPageLoadMetrics() {
        if (typeof performance === 'undefined' || !performance.timing) {
            return null;
        }
        var t = performance.timing;
        var nav = performance.getEntriesByType('navigation')[0];

        var metrics = {
            // 网络阶段
            dnsLookup: t.domainLookupEnd - t.domainLookupStart,
            tcpConnect: t.connectEnd - t.connectStart,
            sslHandshake: t.secureConnectionStart ? (t.connectEnd - t.secureConnectionStart) : 0,
            ttfb: t.responseStart - t.requestStart,           // 首字节时间
            download: t.responseEnd - t.responseStart,         // 内容下载时间
            // 渲染阶段
            domParse: t.domInteractive - t.responseEnd,        // DOM 解析时间
            domContentLoaded: t.domContentLoadedEventEnd - t.navigationStart,
            // 总时间
            pageLoad: t.loadEventEnd - t.navigationStart,
            // 白屏时间（近似）
            firstPaint: 0,
        };

        // 使用 Navigation Timing Level 2（更精确）
        if (nav) {
            metrics.ttfb = nav.responseStart;
            metrics.domContentLoaded = nav.domContentLoadedEventEnd;
            metrics.pageLoad = nav.loadEventEnd;
            metrics.transferSize = nav.transferSize || 0;
            metrics.encodedBodySize = nav.encodedBodySize || 0;
        }

        // First Paint（使用 Paint Timing API）
        if (performance.getEntriesByType) {
            var paints = performance.getEntriesByType('paint');
            for (var i = 0; i < paints.length; i++) {
                if (paints[i].name === 'first-paint') {
                    metrics.firstPaint = Math.round(paints[i].startTime);
                }
                if (paints[i].name === 'first-contentful-paint') {
                    metrics.fcp = Math.round(paints[i].startTime);
                }
            }
        }

        // 资源统计
        if (performance.getEntriesByType) {
            var resources = performance.getEntriesByType('resource');
            var jsCount = 0, cssCount = 0, imgCount = 0, otherCount = 0;
            var jsSize = 0, cssSize = 0, imgSize = 0;
            for (var j = 0; j < resources.length; j++) {
                var r = resources[j];
                var name = r.name || '';
                if (name.endsWith('.js') || name.indexOf('.js?') !== -1) {
                    jsCount++; jsSize += r.transferSize || 0;
                } else if (name.endsWith('.css') || name.indexOf('.css?') !== -1) {
                    cssCount++; cssSize += r.transferSize || 0;
                } else if (/\.(png|jpg|jpeg|gif|svg|webp|ico)(\?|$)/.test(name)) {
                    imgCount++; imgSize += r.transferSize || 0;
                } else {
                    otherCount++;
                }
            }
            metrics.resources = {
                total: resources.length,
                js: { count: jsCount, size_kb: Math.round(jsSize / 1024) },
                css: { count: cssCount, size_kb: Math.round(cssSize / 1024) },
                img: { count: imgCount, size_kb: Math.round(imgSize / 1024) },
                other: otherCount,
            };
        }

        // 四舍五入
        for (var key in metrics) {
            if (typeof metrics[key] === 'number') {
                metrics[key] = Math.round(metrics[key]);
            }
        }

        _metrics.pageLoad = metrics;
        return metrics;
    }

    // ==================== 关键交互计时 ====================
    function startInteraction(name) {
        _interactionMarks[name] = performance.now();
    }

    function endInteraction(name) {
        var start = _interactionMarks[name];
        if (!start) return null;
        var duration = Math.round(performance.now() - start);
        delete _interactionMarks[name];

        _metrics.interactions.push({
            name: name,
            duration_ms: duration,
            time: new Date().toISOString(),
        });
        // 限制数组长度
        if (_metrics.interactions.length > _metrics.maxInteractions) {
            _metrics.interactions.shift();
        }
        return duration;
    }

    // ==================== 内存使用（Chrome 专属）====================
    function getMemoryUsage() {
        if (performance.memory) {
            return {
                used_js_heap_mb: Math.round(performance.memory.usedJSHeapSize / 1024 / 1024),
                total_js_heap_mb: Math.round(performance.memory.totalJSHeapSize / 1024 / 1024),
                js_heap_limit_mb: Math.round(performance.memory.jsHeapSizeLimit / 1024 / 1024),
            };
        }
        return null;
    }

    // ==================== 获取全部指标 ====================
    function getMetrics() {
        return {
            url: location.pathname,
            pageLoad: _metrics.pageLoad,
            interactions: _metrics.interactions.slice(-20),
            memory: getMemoryUsage(),
            userAgent: navigator.userAgent,
            screen: { width: screen.width, height: screen.height },
            connection: navigator.connection ? {
                effectiveType: navigator.connection.effectiveType,
                downlink: navigator.connection.downlink,
                rtt: navigator.connection.rtt,
            } : null,
        };
    }

    // ==================== 静默上报（可选）====================
    function reportMetrics() {
        try {
            var data = getMetrics();
            // 使用 sendBeacon 异步上报，不阻塞页面
            if (navigator.sendBeacon) {
                var blob = new Blob([JSON.stringify(data)], { type: 'application/json' });
                navigator.sendBeacon('/api/frontend-metrics', blob);
            }
        } catch (e) {
            // 静默失败，不影响用户体验
        }
    }

    // ==================== 初始化 ====================
    function init() {
        // 页面加载完成后收集指标
        if (document.readyState === 'complete') {
            setTimeout(collectPageLoadMetrics, 0);
        } else {
            window.addEventListener('load', function() {
                setTimeout(collectPageLoadMetrics, 0);
            });
        }

        // 页面卸载前上报（如果后端有接收端点）
        window.addEventListener('beforeunload', reportMetrics);
    }

    // 导出
    global.PTPerf = {
        collectPageLoadMetrics: collectPageLoadMetrics,
        startInteraction: startInteraction,
        endInteraction: endInteraction,
        getMetrics: getMetrics,
        getMemoryUsage: getMemoryUsage,
        reportMetrics: reportMetrics,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})(window);
