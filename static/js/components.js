/**
 * 工具集 v2.0 统一组件库
 * 提供全站共享的 JavaScript 组件：主题切换、Toast通知、文件上传、通用工具
 *
 * 使用方式：
 * 1. 在页面中引入 <script src="/static/js/components.js"></script>
 * 2. 调用 ToolboxTheme.init() 初始化主题
 * 3. 调用 ToolboxToast.show('消息') 显示通知
 * 4. 调用 ToolboxUpload.create(element, options) 创建上传组件
 */

// ==================== 主题管理器 ====================
const ToolboxTheme = (function() {
    const STORAGE_KEY = 'toolbox_theme';
    let currentTheme = 'auto';
    let systemDark = false;

    function detectSystemTheme() {
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    }

    function applyTheme(theme) {
        currentTheme = theme;
        const isDark = theme === 'dark' || (theme === 'auto' && systemDark);
        document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
        // 同步 localStorage
        try { localStorage.setItem(STORAGE_KEY, theme); } catch(e) {}
        // 通知所有监听器
        document.dispatchEvent(new CustomEvent('themechange', { detail: { theme, isDark } }));
    }

    function init() {
        // 读取存储的主题
        try {
            currentTheme = localStorage.getItem(STORAGE_KEY) || 'auto';
        } catch(e) {
            currentTheme = 'auto';
        }
        systemDark = detectSystemTheme();
        applyTheme(currentTheme);

        // 监听系统主题变化
        if (window.matchMedia) {
            const mq = window.matchMedia('(prefers-color-scheme: dark)');
            const handler = function(e) {
                systemDark = e.matches;
                if (currentTheme === 'auto') {
                    applyTheme('auto');
                }
            };
            if (mq.addEventListener) {
                mq.addEventListener('change', handler);
            } else if (mq.addListener) {
                mq.addListener(handler);
            }
        }
    }

    function setTheme(theme) {
        applyTheme(theme);
        // 尝试同步到服务器
        fetch('/api/user/preferences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme })
        }).catch(function() {}); // 静默失败
    }

    function getTheme() {
        return currentTheme;
    }

    function isDark() {
        return currentTheme === 'dark' || (currentTheme === 'auto' && systemDark);
    }

    /**
     * 创建主题切换按钮
     * @param {string} containerId - 容器元素ID
     */
    function createToggle(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const btn = document.createElement('button');
        btn.className = 'tb-theme-toggle';
        btn.title = '切换主题';

        function updateIcon() {
            btn.textContent = isDark() ? '☀️' : '🌙';
        }
        updateIcon();

        btn.addEventListener('click', function() {
            const next = isDark() ? 'light' : 'dark';
            setTheme(next);
            updateIcon();
        });

        document.addEventListener('themechange', updateIcon);
        container.appendChild(btn);
    }

    return { init, setTheme, getTheme, isDark, createToggle };
})();

// ==================== Toast 通知 ====================
const ToolboxToast = (function() {
    let container = null;

    function ensureContainer() {
        if (container && document.body.contains(container)) return container;
        container = document.createElement('div');
        container.className = 'tb-toast-container';
        document.body.appendChild(container);
        return container;
    }

    function show(message, type, duration) {
        type = type || 'info';
        duration = duration || 3000;
        const c = ensureContainer();
        const toast = document.createElement('div');
        toast.className = 'tb-toast tb-toast-' + type;
        toast.innerHTML = '<span class="tb-toast-icon">' + getIcon(type) + '</span>' +
                          '<span class="tb-toast-msg">' + escapeHtml(message) + '</span>';
        c.appendChild(toast);

        // 触发动画
        requestAnimationFrame(function() {
            toast.classList.add('tb-toast-show');
        });

        // 自动移除
        setTimeout(function() {
            toast.classList.remove('tb-toast-show');
            setTimeout(function() {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 300);
        }, duration);
    }

    function getIcon(type) {
        var icons = { info: 'ℹ️', success: '✅', error: '❌', warning: '⚠️' };
        return icons[type] || icons.info;
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    return {
        show: show,
        info: function(msg, d) { show(msg, 'info', d); },
        success: function(msg, d) { show(msg, 'success', d); },
        error: function(msg, d) { show(msg, 'error', d); },
        warning: function(msg, d) { show(msg, 'warning', d); }
    };
})();

// ==================== 分块文件上传组件 ====================
const ToolboxUpload = (function() {
    /**
     * 创建分块上传器
     * @param {HTMLElement} dropZone - 拖拽区域元素
     * @param {Object} options - 配置项
     *   - accept: 文件类型
     *   - maxRetries: 最大重试次数 (默认3)
     *   - concurrency: 并发数 (默认2)
     *   - onProgress: 进度回调 (received, total)
     *   - onComplete: 完成回调 (fileId, filename)
     *   - onError: 错误回调 (message)
     */
    function create(dropZone, options) {
        options = options || {};
        var maxRetries = options.maxRetries || 3;
        var concurrency = options.concurrency || 2;
        var chunkSize = 2 * 1024 * 1024; // 2MB

        var state = {
            file: null,
            uploadId: null,
            totalChunks: 0,
            uploadedChunks: 0,
            isUploading: false
        };

        // 绑定拖拽事件
        dropZone.addEventListener('dragover', function(e) {
            e.preventDefault();
            dropZone.classList.add('tb-drag-over');
        });
        dropZone.addEventListener('dragleave', function(e) {
            e.preventDefault();
            dropZone.classList.remove('tb-drag-over');
        });
        dropZone.addEventListener('drop', function(e) {
            e.preventDefault();
            dropZone.classList.remove('tb-drag-over');
            var files = e.dataTransfer.files;
            if (files.length > 0) {
                handleFile(files[0]);
            }
        });

        // 点击选择文件
        dropZone.addEventListener('click', function() {
            var input = document.createElement('input');
            input.type = 'file';
            if (options.accept) input.accept = options.accept;
            input.addEventListener('change', function() {
                if (input.files.length > 0) {
                    handleFile(input.files[0]);
                }
            });
            input.click();
        });

        function handleFile(file) {
            if (state.isUploading) {
                ToolboxToast.warning('正在上传中，请稍候');
                return;
            }
            state.file = file;
            state.totalChunks = Math.ceil(file.size / chunkSize);
            state.uploadedChunks = 0;
            startUpload();
        }

        async function startUpload() {
            state.isUploading = true;
            try {
                // 初始化上传会话
                var initResp = await fetch('/api/upload-init', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        filename: state.file.name,
                        fileSize: state.file.size,
                        chunkSize: chunkSize
                    })
                });
                var initData = await initResp.json();
                if (initData.error) throw new Error(initData.error);
                state.uploadId = initData.upload_id;
                state.totalChunks = initData.total_chunks;

                // 分块上传
                await uploadChunks();

                // 完成上传
                var completeResp = await fetch('/api/upload-complete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        upload_id: state.uploadId,
                        filename: state.file.name
                    })
                });
                var completeData = await completeResp.json();

                // 检查缺失分块并重试
                if (completeData.missing_chunks && completeData.missing_chunks.length > 0) {
                    ToolboxToast.warning('检测到 ' + completeData.missing_chunks.length + ' 个缺失分块，正在重试...');
                    await retryMissingChunks(completeData.missing_chunks);
                    // 再次完成
                    completeResp = await fetch('/api/upload-complete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            upload_id: state.uploadId,
                            filename: state.file.name
                        })
                    });
                    completeData = await completeResp.json();
                }

                if (completeData.error) throw new Error(completeData.error);

                state.isUploading = false;
                if (options.onComplete) {
                    options.onComplete(state.uploadId, state.file.name, completeData);
                }
            } catch (err) {
                state.isUploading = false;
                if (options.onError) {
                    options.onError(err.message);
                } else {
                    ToolboxToast.error('上传失败: ' + err.message);
                }
            }
        }

        async function uploadChunks() {
            var chunkIndices = [];
            for (var i = 0; i < state.totalChunks; i++) {
                chunkIndices.push(i);
            }
            await runConcurrent(chunkIndices, uploadSingleChunk);
        }

        async function retryMissingChunks(missingIndices) {
            await runConcurrent(missingIndices, uploadSingleChunk);
        }

        async function uploadSingleChunk(index) {
            var start = index * chunkSize;
            var end = Math.min(start + chunkSize, state.file.size);
            var chunk = state.file.slice(start, end);

            for (var attempt = 0; attempt < maxRetries; attempt++) {
                try {
                    var formData = new FormData();
                    formData.append('upload_id', state.uploadId);
                    formData.append('chunk_index', index);
                    formData.append('total_chunks', state.totalChunks);
                    formData.append('chunk', chunk);

                    var resp = await fetch('/api/upload-chunk', { method: 'POST', body: formData });
                    var data = await resp.json();

                    if (data.error) throw new Error(data.error);

                    state.uploadedChunks++;
                    if (options.onProgress) {
                        options.onProgress(state.uploadedChunks, state.totalChunks);
                    }
                    return; // 成功
                } catch (err) {
                    if (attempt < maxRetries - 1) {
                        // 指数退避
                        await new Promise(function(r) { setTimeout(r, Math.pow(2, attempt) * 1000); });
                    } else {
                        throw err;
                    }
                }
            }
        }

        async function runConcurrent(items, fn) {
            var queue = items.slice();
            var workers = [];
            for (var w = 0; w < concurrency; w++) {
                workers.push((async function() {
                    while (queue.length > 0) {
                        var item = queue.shift();
                        await fn(item);
                    }
                })());
            }
            await Promise.all(workers);
        }

        return {
            getState: function() { return state; },
            cancel: function() { state.isUploading = false; }
        };
    }

    return { create: create };
})();

// ==================== 通用工具函数 ====================
const ToolboxUtils = {
    /**
     * 防抖
     */
    debounce: function(fn, delay) {
        var timer = null;
        return function() {
            var ctx = this, args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function() { fn.apply(ctx, args); }, delay);
        };
    },

    /**
     * 格式化文件大小
     */
    formatSize: function(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
        return (bytes / 1024 / 1024 / 1024).toFixed(1) + ' GB';
    },

    /**
     * 转义HTML
     */
    escapeHtml: function(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    /**
     * 复制到剪贴板
     */
    copyToClipboard: function(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(function() {
                ToolboxToast.success('已复制到剪贴板');
            });
        } else {
            var ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            ToolboxToast.success('已复制到剪贴板');
        }
    },

    /**
     * 获取URL参数
     */
    getQueryParam: function(name) {
        var params = new URLSearchParams(window.location.search);
        return params.get(name);
    }
};

// ==================== 自动初始化 ====================
// 在 DOMContentLoaded 时初始化主题（最早执行，避免闪烁）
(function() {
    function earlyInit() {
        // 在DOMContentLoaded之前尝试初始化主题，减少闪烁
        var savedTheme = 'auto';
        try { savedTheme = localStorage.getItem('toolbox_theme') || 'auto'; } catch(e) {}
        var systemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        var isDark = savedTheme === 'dark' || (savedTheme === 'auto' && systemDark);
        document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    }
    earlyInit();

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { ToolboxTheme.init(); });
    } else {
        ToolboxTheme.init();
    }
})();
