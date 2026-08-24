/**
 * Potential-tools v5.0 增强性能优化
 * 功能：首屏监控、虚拟列表、请求缓存、内存优化、离线检测、资源优先级
 */

(function() {
    'use strict';

    // ============ 1. 首屏性能监控 ============
    function initPerformanceMonitor() {
        if (!('performance' in window)) return;

        // 页面加载完成后上报性能数据
        window.addEventListener('load', function() {
            setTimeout(function() {
                try {
                    const nav = performance.getEntriesByType('navigation')[0];
                    if (!nav) return;

                    const metrics = {
                        // DNS 查询
                        dnsLookup: Math.round(nav.domainLookupEnd - nav.domainLookupStart),
                        // TCP 连接
                        tcpConnect: Math.round(nav.connectEnd - nav.connectStart),
                        // 首字节时间（TTFB）
                        ttfb: Math.round(nav.responseStart - nav.requestStart),
                        // 内容下载
                        contentDownload: Math.round(nav.responseEnd - nav.responseStart),
                        // DOM 解析
                        domParse: Math.round(nav.domInteractive - nav.responseEnd),
                        // DOM 构建完成
                        domComplete: Math.round(nav.domContentLoadedEventEnd - nav.domContentLoadedEventStart),
                        // 页面完全加载
                        loadTime: Math.round(nav.loadEventEnd - nav.startTime),
                        // 资源数量
                        resourceCount: performance.getEntriesByType('resource').length,
                    };

                    // 只在开发环境或慢速页面输出
                    if (metrics.loadTime > 3000 || window.location.hostname === 'localhost') {
                    }

                    // 慢速页面警告
                    if (metrics.ttfb > 1000) {
                        console.warn('[Performance] TTFB 过慢:', metrics.ttfb + 'ms，建议优化后端响应');
                    }
                    if (metrics.loadTime > 5000) {
                        console.warn('[Performance] 页面加载过慢:', metrics.loadTime + 'ms');
                    }

                    // 存储到全局，供调试使用
                    window.__pagePerformance = metrics;
                } catch (e) {
                    // 忽略性能监控错误
                }
            }, 0);
        });

        // 长任务监控（阻塞主线程超过50ms的任务）
        if ('PerformanceObserver' in window) {
            try {
                const observer = new PerformanceObserver(function(list) {
                    list.getEntries().forEach(function(entry) {
                        if (entry.duration > 100) {
                            console.warn('[Performance] 长任务:', Math.round(entry.duration) + 'ms', entry.name);
                        }
                    });
                });
                observer.observe({ entryTypes: ['longtask'] });
            } catch (e) {
                // 不支持 longtask 则忽略
            }
        }
    }

    // ============ 2. 虚拟列表（大数据量表格优化） ============
    window.PTVirtualList = function(container, options) {
        options = options || {};
        const itemHeight = options.itemHeight || 40;
        const overscan = options.overscan || 5;
        let items = [];
        let scrollTop = 0;
        let visibleCount = 0;

        function render() {
            if (!container) return;
            const containerHeight = container.clientHeight;
            visibleCount = Math.ceil(containerHeight / itemHeight) + overscan * 2;
            const startIndex = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
            const endIndex = Math.min(items.length, startIndex + visibleCount);

            const visibleItems = items.slice(startIndex, endIndex);
            const offsetY = startIndex * itemHeight;

            // 使用文档片段减少重排
            const fragment = document.createDocumentFragment();
            visibleItems.forEach(function(item, i) {
                const el = document.createElement('div');
                el.style.height = itemHeight + 'px';
                el.style.transform = 'translateY(' + (offsetY + i * itemHeight) + 'px)';
                el.style.position = 'absolute';
                el.style.left = '0';
                el.style.right = '0';
                if (options.renderItem) {
                    options.renderItem(el, item, startIndex + i);
                }
                fragment.appendChild(el);
            });

            container.innerHTML = '';
            container.appendChild(fragment);

            // 设置总高度
            if (container.parentElement) {
                container.parentElement.style.height = (items.length * itemHeight) + 'px';
                container.parentElement.style.position = 'relative';
            }
        }

        function onScroll() {
            scrollTop = container.parentElement ? container.parentElement.scrollTop : 0;
            requestAnimationFrame(render);
        }

        return {
            setItems: function(newItems) {
                items = newItems || [];
                render();
            },
            refresh: render,
            destroy: function() {
                if (container.parentElement) {
                    container.parentElement.removeEventListener('scroll', onScroll);
                }
            }
        };
    };

    // ============ 3. 请求缓存（避免重复请求） ============
    const requestCache = new Map();
    const CACHE_TTL = 5 * 60 * 1000; // 5分钟

    window.PTCachedFetch = async function(url, options) {
        options = options || {};
        const cacheKey = url + JSON.stringify(options.body || '');
        const now = Date.now();

        // 检查缓存
        if (!options.noCache && requestCache.has(cacheKey)) {
            const cached = requestCache.get(cacheKey);
            if (now - cached.time < CACHE_TTL) {
                return cached.data.clone ? cached.data.clone() : JSON.parse(JSON.stringify(cached.data));
            }
            requestCache.delete(cacheKey);
        }

        // 发起请求
        const response = await fetch(url, options);

        // 缓存 GET 请求
        if (!options.method || options.method === 'GET') {
            try {
                const clone = response.clone();
                requestCache.set(cacheKey, { time: now, data: clone });
            } catch (e) {
                // 无法克隆则不缓存
            }
        }

        return response;
    };

    window.PTClearCache = function() {
        requestCache.clear();
    };

    // ============ 4. 内存优化（大对象及时清理） ============
    function initMemoryOptimization() {
        // 页面隐藏时清理非必要数据
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                // 清理请求缓存
                if (requestCache.size > 50) {
                    requestCache.clear();
                }
                // 触发垃圾回收提示
                if (window.gc) {
                    try { window.gc(); } catch (e) {}
                }
            }
        });

        // 监控内存使用（Chrome 支持）
        if (performance.memory) {
            setInterval(function() {
                const mem = performance.memory;
                const usedMB = Math.round(mem.usedJSHeapSize / 1024 / 1024);
                const limitMB = Math.round(mem.jsHeapSizeLimit / 1024 / 1024);

                // 内存使用超过80%时警告并清理
                if (usedMB / limitMB > 0.8) {
                    console.warn('[Performance] 内存使用过高:', usedMB + '/' + limitMB + 'MB，正在清理缓存');
                    requestCache.clear();
                }
            }, 30000);
        }
    }

    // ============ 5. 离线检测和重连 ============
    function initOfflineDetection() {
        function updateOnlineStatus() {
            if (navigator.onLine) {
                document.documentElement.removeAttribute('data-offline');
                if (window.__wasOffline) {
                    window.__wasOffline = false;
                    // 重连后刷新关键数据
                    if (typeof window.PTOnReconnect === 'function') {
                        window.PTOnReconnect();
                    }
                }
            } else {
                document.documentElement.setAttribute('data-offline', 'true');
                window.__wasOffline = true;
            }
        }

        window.addEventListener('online', updateOnlineStatus);
        window.addEventListener('offline', updateOnlineStatus);
        updateOnlineStatus();
    }

    // ============ 6. 资源优先级提示 ============
    function initResourceHints() {
        // 预连接到常用域名
        const origins = [
            window.location.origin,
        ];

        origins.forEach(function(origin) {
            if (!document.querySelector('link[rel="preconnect"][href="' + origin + '"]')) {
                const link = document.createElement('link');
                link.rel = 'preconnect';
                link.href = origin;
                document.head.appendChild(link);
            }
        });

        // DNS 预解析
        if (!document.querySelector('meta[name="dns-prefetch-control"]')) {
            const meta = document.createElement('meta');
            meta.httpEquiv = 'x-dns-prefetch-control';
            meta.content = 'on';
            document.head.appendChild(meta);
        }
    }

    // ============ 7. 防抖输入优化（搜索框等） ============
    window.PTSmartInput = function(input, callback, delay) {
        delay = delay || 300;
        let timer = null;
        let lastValue = '';

        input.addEventListener('input', function() {
            const value = input.value;
            if (value === lastValue) return;
            lastValue = value;

            clearTimeout(timer);
            timer = setTimeout(function() {
                callback(value);
            }, delay);
        });

        // 回车立即执行
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                clearTimeout(timer);
                callback(input.value);
            }
        });
    };

    // ============ 8. 图片优化（自动压缩和格式检测） ============
    function initImageOptimization() {
        // 检测 WebP 支持
        const webpSupported = new Promise(function(resolve) {
            const img = new Image();
            img.onload = function() { resolve(true); };
            img.onerror = function() { resolve(false); };
            img.src = 'data:image/webp;base64,UklGRkoAAABXRUJQVlA4WAoAAAAQAAAAAAAAAAAAQUxQSAwAAAABBxAR/Q9ERP8DAABWUDggGAAAADABAJ0BKgEAAQADADQlpAADcAD++/1QAA==';
        });

        window.PTImageOptimizer = {
            webpSupported: webpSupported,
            // 压缩图片（返回压缩后的 dataURL）
            compressImage: function(file, maxWidth, quality) {
                return new Promise(function(resolve, reject) {
                    maxWidth = maxWidth || 1920;
                    quality = quality || 0.8;

                    const reader = new FileReader();
                    reader.onload = function(e) {
                        const img = new Image();
                        img.onload = function() {
                            // 计算缩放比例
                            let width = img.width;
                            let height = img.height;
                            if (width > maxWidth) {
                                height = Math.round(height * maxWidth / width);
                                width = maxWidth;
                            }

                            const canvas = document.createElement('canvas');
                            canvas.width = width;
                            canvas.height = height;
                            const ctx = canvas.getContext('2d');
                            ctx.drawImage(img, 0, 0, width, height);

                            webpSupported.then(function(supportWebp) {
                                const mimeType = supportWebp ? 'image/webp' : 'image/jpeg';
                                resolve(canvas.toDataURL(mimeType, quality));
                            });
                        };
                        img.onerror = reject;
                        img.src = e.target.result;
                    };
                    reader.onerror = reject;
                    reader.readAsDataURL(file);
                });
            }
        };
    }

    // ============ 9. 批量 DOM 更新（减少重排） ============
    window.PTBatchUpdate = function(container, updates) {
        // 临时禁用过渡，批量更新后恢复
        const prevTransition = container.style.transition;
        container.style.transition = 'none';

        // 使用 requestAnimationFrame 确保在同一帧内更新
        requestAnimationFrame(function() {
            updates.forEach(function(fn) {
                try { fn(); } catch (e) {}
            });

            // 强制重排后恢复过渡
            container.offsetHeight; // 触发重排
            container.style.transition = prevTransition;
        });
    };

    // ============ 10. 错误监控 ============
    function initErrorMonitoring() {
        // 捕获未处理的 Promise 错误
        window.addEventListener('unhandledrejection', function(e) {
            console.error('[Performance] 未处理的 Promise 错误:', e.reason);
        });

        // 捕获全局错误
        window.addEventListener('error', function(e) {
            if (e.message && e.message.indexOf('ResizeObserver') === -1) {
                console.error('[Performance] 全局错误:', e.message, e.filename + ':' + e.lineno);
            }
        });
    }

    // ============ 初始化 ============
    function init() {
        initPerformanceMonitor();
        initMemoryOptimization();
        initOfflineDetection();
        initResourceHints();
        initImageOptimization();
        initErrorMonitoring();

    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
