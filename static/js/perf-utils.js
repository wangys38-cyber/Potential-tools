/* ===== 前端性能优化工具：防抖/节流/批量请求 =====
 * 用法:
 *   var debouncedFn = PTUtils.debounce(fn, 300);
 *   var throttledFn = PTUtils.throttle(fn, 100);
 *   PTUtils.batchFetch(urls, { concurrency: 3 }).then(results => ...);
 */
(function(global) {
    'use strict';

    function debounce(fn, wait) {
        var timeout = null;
        return function() {
            var ctx = this, args = arguments;
            if (timeout) clearTimeout(timeout);
            timeout = setTimeout(function() {
                fn.apply(ctx, args);
                timeout = null;
            }, wait);
        };
    }

    function throttle(fn, limit) {
        var inThrottle = false;
        var lastArgs = null;
        return function() {
            var ctx = this, args = arguments;
            if (!inThrottle) {
                fn.apply(ctx, args);
                inThrottle = true;
                setTimeout(function() {
                    inThrottle = false;
                    if (lastArgs) {
                        fn.apply(ctx, lastArgs);
                        lastArgs = null;
                    }
                }, limit);
            } else {
                lastArgs = args;
            }
        };
    }

    function batchFetch(urls, options) {
        options = options || {};
        var concurrency = options.concurrency || 3;
        var results = new Array(urls.length);
        var index = 0;

        function worker() {
            if (index >= urls.length) return Promise.resolve();
            var i = index++;
            return fetch(urls[i], options.fetchOptions)
                .then(function(r) { return r.json(); })
                .then(function(data) { results[i] = data; })
                .catch(function(err) { results[i] = { error: err.message }; })
                .then(worker);
        }

        var workers = [];
        for (var i = 0; i < Math.min(concurrency, urls.length); i++) {
            workers.push(worker());
        }
        return Promise.all(workers).then(function() { return results; });
    }

    function lazyLoadImages(container) {
        if (!('IntersectionObserver' in window)) return;
        var observer = new IntersectionObserver(function(entries) {
            entries.forEach(function(entry) {
                if (entry.isIntersecting) {
                    var img = entry.target;
                    if (img.dataset.src) {
                        img.src = img.dataset.src;
                        img.removeAttribute('data-src');
                    }
                    observer.unobserve(img);
                }
            });
        }, { rootMargin: '50px' });

        var scope = container || document;
        scope.querySelectorAll('img[data-src]').forEach(function(img) {
            observer.observe(img);
        });
    }

    global.PTUtils = {
        debounce: debounce,
        throttle: throttle,
        batchFetch: batchFetch,
        lazyLoadImages: lazyLoadImages
    };

})(window);
