/* Potential-tools 动态资源加载器：JS/CSS 按需加载、preload 提示、就绪 Promise，结果缓存
 * 用法:
 *   PTLoader.load('/static/js/a.js').then(fn);
 *   PTLoader.loadMultiple(['a.js','b.js']).then(fn);
 *   PTLoader.loadCSS('/static/css/a.css').then(fn);
 *   PTLoader.preload('/static/js/a.js','script');
 *   PTLoader.whenReady().then(fn);
 */
(function(global) {
    'use strict';
    var _loaded = {}, _cssLoaded = {}, _preloaded = {};
    var _version = '', _readyPromise = null;

    function _getVersion() {
        if (_version) return _version;
        var scripts = document.querySelectorAll('script[src*="?v="]');
        for (var i = 0; i < scripts.length; i++) {
            var m = scripts[i].src.match(/[?&]v=([^&]+)/);
            if (m) { _version = m[1]; break; }
        }
        return _version;
    }

    function _buildUrl(src) {
        if (src.indexOf('?') !== -1) return src;
        // 外部 CDN URL 不追加本地版本号，避免破坏 CDN 缓存键
        if (/^https?:/i.test(src) || src.indexOf('//') === 0) return src;
        var v = _getVersion();
        return v ? src + '?v=' + v : src;
    }

    function load(src) {
        var url = _buildUrl(src);
        if (_loaded[url]) return _loaded[url];
        _loaded[url] = new Promise(function(resolve, reject) {
            if (document.querySelector('script[src="' + url + '"]')) { resolve(); return; }
            var s = document.createElement('script');
            s.src = url; s.async = true;
            s.onload = function() { resolve(); };
            s.onerror = function() { delete _loaded[url]; reject(new Error('Failed to load script: ' + url)); };
            document.head.appendChild(s);
        });
        return _loaded[url];
    }

    function loadMultiple(srcs) {
        return Promise.all(srcs.map(function(src) { return load(src); }));
    }

    // 动态加载 CSS：<link rel="stylesheet">，结果缓存
    function loadCSS(href) {
        var url = _buildUrl(href);
        if (_cssLoaded[url]) return _cssLoaded[url];
        _cssLoaded[url] = new Promise(function(resolve, reject) {
            if (document.querySelector('link[rel="stylesheet"][href="' + url + '"]')) { resolve(); return; }
            var l = document.createElement('link');
            l.rel = 'stylesheet'; l.href = url;
            l.onload = function() { resolve(); };
            l.onerror = function() { delete _cssLoaded[url]; reject(new Error('Failed to load CSS: ' + url)); };
            document.head.appendChild(l);
        });
        return _cssLoaded[url];
    }

    // <link rel="preload"> 提示，同一 URL 只插入一次
    function preload(url, as) {
        var built = _buildUrl(url);
        if (_preloaded[built]) return built;
        if (document.querySelector('link[rel="preload"][href="' + built + '"]')) { _preloaded[built] = true; return built; }
        var l = document.createElement('link');
        l.rel = 'preload'; l.href = built; l.as = as || 'script';
        document.head.appendChild(l);
        _preloaded[built] = true;
        return built;
    }

    // DOMContentLoaded 后 resolve 的 Promise，用于延迟非关键初始化
    function whenReady() {
        if (_readyPromise) return _readyPromise;
        _readyPromise = new Promise(function(resolve) {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', function() { resolve(); });
            } else { resolve(); }
        });
        return _readyPromise;
    }

    function isLoaded(src) {
        var url = _buildUrl(src);
        return !!_loaded[url] || !!_cssLoaded[url];
    }

    function clearCache() { _loaded = {}; _cssLoaded = {}; }

    global.PTLoader = {
        load: load, loadMultiple: loadMultiple, loadCSS: loadCSS,
        preload: preload, whenReady: whenReady,
        isLoaded: isLoaded, clearCache: clearCache
    };
})(window);
