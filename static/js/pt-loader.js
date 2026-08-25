/* ===== Potential-tools 阶段五性能优化：动态脚本加载器 =====
 * 按需加载大型工具页面的 JS，减少首屏 JS 体积
 * 支持缓存已加载脚本，避免重复下载
 * 支持并行加载多个脚本，按顺序执行
 *
 * 用法:
 *   PTLoader.load('/static/js/cr_deep_analysis.js').then(function() {
 *       // 脚本加载完成，初始化工具
 *   });
 *   PTLoader.loadMultiple(['/static/js/a.js', '/static/js/b.js']).then(...);
 */
(function(global) {
    'use strict';

    var _loaded = {};  // 已加载的脚本 URL -> Promise
    var _version = '';

    // 从页面中提取 STATIC_VERSION（_navbar.html 中通过模板变量注入）
    function _getVersion() {
        if (_version) return _version;
        // 尝试从已有 script 标签的 src 中提取 ?v=xxx
        var scripts = document.querySelectorAll('script[src*="?v="]');
        for (var i = 0; i < scripts.length; i++) {
            var match = scripts[i].src.match(/[?&]v=([^&]+)/);
            if (match) {
                _version = match[1];
                break;
            }
        }
        return _version;
    }

    function _buildUrl(src) {
        // 如果已经带了版本号或查询参数，直接返回
        if (src.indexOf('?') !== -1) return src;
        var v = _getVersion();
        if (v) {
            return src + '?v=' + v;
        }
        return src;
    }

    function load(src) {
        var url = _buildUrl(src);
        if (_loaded[url]) {
            return _loaded[url];
        }

        _loaded[url] = new Promise(function(resolve, reject) {
            // 检查是否已经通过 <script> 标签加载过
            var existing = document.querySelector('script[src="' + url + '"]');
            if (existing) {
                resolve();
                return;
            }

            var script = document.createElement('script');
            script.src = url;
            script.async = true;
            script.onload = function() { resolve(); };
            script.onerror = function() {
                delete _loaded[url];
                reject(new Error('Failed to load script: ' + url));
            };
            document.head.appendChild(script);
        });

        return _loaded[url];
    }

    function loadMultiple(srcs) {
        return Promise.all(srcs.map(function(src) { return load(src); }));
    }

    function isLoaded(src) {
        return !!_loaded[_buildUrl(src)];
    }

    function clearCache() {
        _loaded = {};
    }

    global.PTLoader = {
        load: load,
        loadMultiple: loadMultiple,
        isLoaded: isLoaded,
        clearCache: clearCache,
    };

})(window);
