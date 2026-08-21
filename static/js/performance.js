/* ===== Potential-tools v5.0 性能优化脚本 =====
 * 懒加载、预取、资源优化、减少重排
 * 通过 _navbar.html 自动引入
 */
(function() {
    'use strict';

    // ==================== 图片懒加载 ====================
    function initLazyImages() {
        if (!('IntersectionObserver' in window)) {
            // 不支持 IntersectionObserver 的浏览器直接加载所有图片
            document.querySelectorAll('img[data-src]').forEach(function(img) {
                img.src = img.dataset.src;
                img.removeAttribute('data-src');
            });
            return;
        }

        var imgObserver = new IntersectionObserver(function(entries, observer) {
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
        }, { rootMargin: '50px 0px', threshold: 0.01 });

        document.querySelectorAll('img[data-src]').forEach(function(img) {
            imgObserver.observe(img);
        });
    }

    // ==================== 链接预取（鼠标悬停时） ====================
    function initLinkPrefetch() {
        var prefetched = {};
        var prefetchTimer = null;

        function prefetch(url) {
            if (prefetched[url]) return;
            prefetched[url] = true;

            // 只预取同源页面
            try {
                var link = document.createElement('link');
                link.rel = 'prefetch';
                link.href = url;
                link.as = 'document';
                document.head.appendChild(link);
            } catch(e) {}
        }

        document.addEventListener('mouseover', function(e) {
            var link = e.target.closest('a[href]');
            if (!link) return;
            var href = link.getAttribute('href');
            if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('mailto:')) return;

            // 只预取内部链接
            if (href.startsWith('/') || href.startsWith(window.location.origin)) {
                clearTimeout(prefetchTimer);
                prefetchTimer = setTimeout(function() {
                    prefetch(href.startsWith('/') ? window.location.origin + href : href);
                }, 150); // 悬停150ms后才预取，避免误触
            }
        }, { passive: true });

        document.addEventListener('mouseout', function(e) {
            var link = e.target.closest('a[href]');
            if (link) clearTimeout(prefetchTimer);
        }, { passive: true });
    }

    // ==================== 减少滚动事件重排 ====================
    function initScrollOptimization() {
        var ticking = false;
        var scrollHandlers = [];

        window.addScrollHandler = function(fn) {
            scrollHandlers.push(fn);
        };

        window.addEventListener('scroll', function() {
            if (!ticking) {
                window.requestAnimationFrame(function() {
                    scrollHandlers.forEach(function(fn) {
                        try { fn(window.scrollY); } catch(e) {}
                    });
                    ticking = false;
                });
                ticking = true;
            }
        }, { passive: true });
    }

    // ==================== 表单输入防抖 ====================
    window.ptDebounce = function(fn, delay) {
        var timer = null;
        return function() {
            var context = this;
            var args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function() {
                fn.apply(context, args);
            }, delay || 300);
        };
    };

    // ==================== 节流 ====================
    window.ptThrottle = function(fn, limit) {
        var inThrottle = false;
        return function() {
            var context = this;
            var args = arguments;
            if (!inThrottle) {
                fn.apply(context, args);
                inThrottle = true;
                setTimeout(function() { inThrottle = false; }, limit || 300);
            }
        };
    };

    // ==================== 初始化 ====================
    function init() {
        initLazyImages();
        initLinkPrefetch();
        initScrollOptimization();

        // 标记性能优化已加载
        document.documentElement.setAttribute('data-pt-perf', '1');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
