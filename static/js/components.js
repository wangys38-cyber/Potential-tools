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

// ==================== 统一导航栏 ====================
const ToolboxNav = (function() {
    /**
     * 自动注入浮动导航栏到页面
     * @param {Object} opts - 配置
     *   - title: 页面标题（可选，默认从 <title> 或 <h1> 获取）
     *   - showHome: 是否显示返回首页按钮（默认 true）
     *   - showTheme: 是否显示主题切换（默认 true）
     *   - extraActions: 额外按钮数组 [{html, onClick}]
     */
    function init(opts) {
        opts = opts || {};
        // 避免重复注入
        if (document.getElementById('tb-nav-bar')) return;

        var isHome = window.location.pathname === '/' || window.location.pathname === '/index';

        var bar = document.createElement('nav');
        bar.id = 'tb-nav-bar';
        bar.className = 'tb-nav-bar';

        var leftHtml = '';
        if (opts.showHome !== false && !isHome) {
            leftHtml += '<a href="/" class="tb-nav-home" title="返回首页 (Esc)">← 首页</a>';
        }
        if (opts.title) {
            leftHtml += '<span class="tb-nav-title">' + escapeHtml(opts.title) + '</span>';
        }

        var rightHtml = '';
        if (opts.extraActions) {
            opts.extraActions.forEach(function(a) {
                rightHtml += a.html;
            });
        }
        if (opts.showTheme !== false) {
            rightHtml += '<button class="tb-nav-theme" id="tb-nav-theme-btn" title="切换主题">🌙</button>';
        }

        bar.innerHTML =
            '<div class="tb-nav-left">' + leftHtml + '</div>' +
            '<div class="tb-nav-right">' + rightHtml + '</div>';

        document.body.insertBefore(bar, document.body.firstChild);

        // 主题按钮事件
        var themeBtn = document.getElementById('tb-nav-theme-btn');
        if (themeBtn) {
            function updateThemeIcon() {
                themeBtn.textContent = ToolboxTheme.isDark() ? '☀️' : '🌙';
            }
            updateThemeIcon();
            themeBtn.addEventListener('click', function() {
                ToolboxTheme.setTheme(ToolboxTheme.isDark() ? 'light' : 'dark');
                updateThemeIcon();
            });
            document.addEventListener('themechange', updateThemeIcon);
        }

        // 额外按钮事件
        if (opts.extraActions) {
            opts.extraActions.forEach(function(a, i) {
                if (a.onClick) {
                    var el = bar.querySelectorAll('.tb-nav-right button, .tb-nav-right a')[i];
                    if (el) el.addEventListener('click', a.onClick);
                }
            });
        }

        // Esc 返回首页
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && !isHome) {
                var tag = document.activeElement.tagName;
                if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') {
                    // 检查是否有模态框打开
                    var modal = document.querySelector('.tb-modal-overlay.tb-modal-show, .modal[style*="display: block"], .overlay[style*="display: flex"]');
                    if (!modal) {
                        window.location.href = '/';
                    }
                }
            }
        });

        // 给 body 添加 padding-top 避免遮挡内容
        document.body.style.paddingTop = (parseInt(getComputedStyle(document.body).paddingTop) || 0) + 0 + 'px';
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    return { init: init };
})();

// ==================== 最近使用工具追踪 ====================
const ToolboxRecent = (function() {
    var STORAGE_KEY = 'toolbox_recent_tools';
    var MAX_ITEMS = 6;

    function record(toolId, toolName, toolIcon) {
        var list = getAll();
        // 移除已存在的
        list = list.filter(function(t) { return t.id !== toolId; });
        // 添加到最前
        list.unshift({ id: toolId, name: toolName, icon: toolIcon, time: Date.now() });
        // 限制数量
        list = list.slice(0, MAX_ITEMS);
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(list)); } catch(e) {}
    }

    function getAll() {
        try {
            var data = localStorage.getItem(STORAGE_KEY);
            return data ? JSON.parse(data) : [];
        } catch(e) {
            return [];
        }
    }

    function clear() {
        try { localStorage.removeItem(STORAGE_KEY); } catch(e) {}
    }

    return { record: record, getAll: getAll, clear: clear };
})();

// ==================== v3.0 AI 对话助手 ====================
const ToolboxAIChat = (function() {
    let container = null;
    let messages = [];
    let isOpen = false;
    let currentModel = '';
    let abortController = null;

    function createStyles() {
        if (document.getElementById('tb-aichat-styles')) return;
        var style = document.createElement('style');
        style.id = 'tb-aichat-styles';
        style.textContent = `
            .tb-aichat-fab{position:fixed;bottom:24px;right:24px;width:56px;height:56px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;border:none;cursor:pointer;font-size:24px;box-shadow:0 4px 20px rgba(99,102,241,0.4);z-index:99998;transition:transform .2s,box-shadow .2s;display:flex;align-items:center;justify-content:center}
            .tb-aichat-fab:hover{transform:scale(1.1);box-shadow:0 6px 28px rgba(99,102,241,0.5)}
            .tb-aichat-panel{position:fixed;top:0;right:-420px;width:400px;height:100vh;background:var(--tb-bg,#fff);box-shadow:-4px 0 24px rgba(0,0,0,0.1);z-index:99999;display:flex;flex-direction:column;transition:right .3s ease}
            .tb-aichat-panel.open{right:0}
            [data-theme="dark"] .tb-aichat-panel{background:#1a1a2e;box-shadow:-4px 0 24px rgba(0,0,0,0.5)}
            .tb-aichat-header{padding:16px 20px;border-bottom:1px solid var(--tb-border,#e5e5ea);display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
            [data-theme="dark"] .tb-aichat-header{border-color:rgba(255,255,255,0.08)}
            .tb-aichat-title{font-size:16px;font-weight:600;color:var(--tb-text,#1d1d1f);display:flex;align-items:center;gap:8px}
            [data-theme="dark"] .tb-aichat-title{color:#f0f0f2}
            .tb-aichat-close{background:none;border:none;font-size:22px;cursor:pointer;color:var(--tb-text-muted,#86868b);padding:4px;line-height:1}
            [data-theme="dark"] .tb-aichat-close{color:#9b9ba3}
            .tb-aichat-models{padding:8px 16px;border-bottom:1px solid var(--tb-border,#e5e5ea);flex-shrink:0}
            [data-theme="dark"] .tb-aichat-models{border-color:rgba(255,255,255,0.08)}
            .tb-aichat-models select{width:100%;padding:6px 10px;border:1px solid var(--tb-border,#e5e5ea);border-radius:6px;background:var(--tb-bg-muted,#f5f5f7);color:var(--tb-text,#1d1d1f);font-size:13px;cursor:pointer}
            [data-theme="dark"] .tb-aichat-models select{background:#2a2a3e;border-color:rgba(255,255,255,0.1);color:#f0f0f2}
            .tb-aichat-messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
            .tb-aichat-msg{max-width:85%;padding:10px 14px;border-radius:12px;font-size:14px;line-height:1.6;word-break:break-word;white-space:pre-wrap}
            .tb-aichat-msg.user{align-self:flex-end;background:#6366f1;color:#fff;border-bottom-right-radius:4px}
            .tb-aichat-msg.assistant{align-self:flex-start;background:var(--tb-bg-muted,#f5f5f7);color:var(--tb-text,#1d1d1f);border-bottom-left-radius:4px}
            [data-theme="dark"] .tb-aichat-msg.assistant{background:#2a2a3e;color:#f0f0f2}
            .tb-aichat-msg.error{align-self:center;background:#fef2f2;color:#ef4444;font-size:13px}
            .tb-aichat-msg.system{align-self:center;color:var(--tb-text-muted,#86868b);font-size:12px;padding:4px 0}
            [data-theme="dark"] .tb-aichat-msg.system{color:#9b9ba3}
            .tb-aichat-typing{align-self:flex-start;padding:10px 14px;background:var(--tb-bg-muted,#f5f5f7);border-radius:12px;border-bottom-left-radius:4px;font-size:13px;color:var(--tb-text-muted,#86868b)}
            [data-theme="dark"] .tb-aichat-typing{background:#2a2a3e;color:#9b9ba3}
            .tb-aichat-typing span{display:inline-block;animation:tb-bounce 1.4s infinite ease-in-out both}
            .tb-aichat-typing span:nth-child(2){animation-delay:.16s}
            .tb-aichat-typing span:nth-child(3){animation-delay:.32s}
            @keyframes tb-bounce{0%,80%,100%{transform:scale(0)}40%{transform:scale(1)}}
            .tb-aichat-input-area{padding:12px 16px;border-top:1px solid var(--tb-border,#e5e5ea);flex-shrink:0}
            [data-theme="dark"] .tb-aichat-input-area{border-color:rgba(255,255,255,0.08)}
            .tb-aichat-input-wrap{display:flex;gap:8px;align-items:flex-end}
            .tb-aichat-input{flex:1;resize:none;border:1px solid var(--tb-border,#e5e5ea);border-radius:8px;padding:10px 12px;font-size:14px;font-family:inherit;background:var(--tb-bg,#fff);color:var(--tb-text,#1d1d1f);max-height:120px;min-height:42px;line-height:1.5}
            [data-theme="dark"] .tb-aichat-input{background:#2a2a3e;border-color:rgba(255,255,255,0.1);color:#f0f0f2}
            .tb-aichat-input:focus{outline:none;border-color:#6366f1}
            .tb-aichat-send{width:42px;height:42px;border-radius:8px;background:#6366f1;color:#fff;border:none;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background .2s}
            .tb-aichat-send:hover{background:#5457e5}
            .tb-aichat-send:disabled{background:#c5c5cc;cursor:not-allowed}
            .tb-aichat-clear{font-size:12px;color:var(--tb-text-muted,#86868b);cursor:pointer;margin-top:8px;text-align:center}
            [data-theme="dark"] .tb-aichat-clear{color:#9b9ba3}
            .tb-aichat-clear:hover{text-decoration:underline}
            .tb-aichat-backdrop{position:fixed;inset:0;background:rgba(0,0,0,0.2);z-index:99997;opacity:0;pointer-events:none;transition:opacity .3s}
            .tb-aichat-backdrop.show{opacity:1;pointer-events:auto}
        `;
        document.head.appendChild(style);
    }

    function createElements() {
        // FAB 按钮
        var fab = document.createElement('button');
        fab.className = 'tb-aichat-fab';
        fab.innerHTML = '🤖';
        fab.title = 'AI 助手 (Ctrl+J)';
        fab.onclick = toggle;

        // 遮罩
        var backdrop = document.createElement('div');
        backdrop.className = 'tb-aichat-backdrop';
        backdrop.id = 'tb-aichat-backdrop';
        backdrop.onclick = close;

        // 面板
        var panel = document.createElement('div');
        panel.className = 'tb-aichat-panel';
        panel.id = 'tb-aichat-panel';
        panel.innerHTML = `
            <div class="tb-aichat-header">
                <div class="tb-aichat-title">🤖 AI 助手</div>
                <button class="tb-aichat-close" onclick="ToolboxAIChat.close()">&times;</button>
            </div>
            <div class="tb-aichat-models">
                <select id="tb-aichat-model-select" onchange="ToolboxAIChat.setModel(this.value)">
                    <option value="">加载模型列表...</option>
                </select>
            </div>
            <div class="tb-aichat-messages" id="tb-aichat-messages">
                <div class="tb-aichat-msg system">你好！我是 AI 助手，有什么可以帮你的？</div>
            </div>
            <div class="tb-aichat-input-area">
                <div class="tb-aichat-input-wrap">
                    <textarea class="tb-aichat-input" id="tb-aichat-input" placeholder="输入消息... (Enter 发送, Shift+Enter 换行)" rows="1" onkeydown="ToolboxAIChat.onKeydown(event)"></textarea>
                    <button class="tb-aichat-send" id="tb-aichat-send" onclick="ToolboxAIChat.send()">➤</button>
                </div>
                <div class="tb-aichat-clear" onclick="ToolboxAIChat.clear()">清空对话</div>
            </div>
        `;

        document.body.appendChild(backdrop);
        document.body.appendChild(panel);
        document.body.appendChild(fab);

        container = panel;
    }

    async function loadModels() {
        try {
            var resp = await fetch('/api/ai-models');
            var data = await resp.json();
            var select = document.getElementById('tb-aichat-model-select');
            if (data.models) {
                select.innerHTML = data.models.map(function(m) {
                    var sel = m.id === data.current ? 'selected' : '';
                    return '<option value="' + m.id + '" ' + sel + '>' + m.name + ' — ' + m.desc + '</option>';
                }).join('');
                currentModel = data.current || (data.models[0] && data.models[0].id) || '';
            }
        } catch(e) {}
    }

    function toggle() {
        if (isOpen) close(); else open();
    }

    function open() {
        if (!container) { createStyles(); createElements(); loadModels(); }
        container.classList.add('open');
        document.getElementById('tb-aichat-backdrop').classList.add('show');
        isOpen = true;
        setTimeout(function() { document.getElementById('tb-aichat-input').focus(); }, 300);
    }

    function close() {
        if (container) container.classList.remove('open');
        var bd = document.getElementById('tb-aichat-backdrop');
        if (bd) bd.classList.remove('show');
        isOpen = false;
    }

    function setModel(m) { currentModel = m; }

    function clear() {
        messages = [];
        var msgBox = document.getElementById('tb-aichat-messages');
        if (msgBox) msgBox.innerHTML = '<div class="tb-aichat-msg system">对话已清空。</div>';
    }

    function onKeydown(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
        }
        // 自动调整高度
        var input = e.target;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    }

    async function send() {
        var input = document.getElementById('tb-aichat-input');
        var text = input.value.trim();
        if (!text) return;

        input.value = '';
        input.style.height = 'auto';

        // 添加用户消息
        messages.push({ role: 'user', content: text });
        appendMessage('user', text);

        // 显示 typing
        var typingEl = document.createElement('div');
        typingEl.className = 'tb-aichat-typing';
        typingEl.id = 'tb-aichat-typing';
        typingEl.innerHTML = '<span>●</span><span>●</span><span>●</span>';
        var msgBox = document.getElementById('tb-aichat-messages');
        msgBox.appendChild(typingEl);
        msgBox.scrollTop = msgBox.scrollHeight;

        // 创建 AI 消息占位
        var aiEl = null;
        var aiText = '';

        try {
            var sendBtn = document.getElementById('tb-aichat-send');
            sendBtn.disabled = true;

            var resp = await fetch('/api/ai-chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ messages: messages, model: currentModel })
            });

            // 移除 typing
            var tp = document.getElementById('tb-aichat-typing');
            if (tp) tp.remove();

            if (!resp.ok) {
                var errData = await resp.json().catch(function() { return {}; });
                appendMessage('error', errData.error || '请求失败 (' + resp.status + ')');
                return;
            }

            // 创建 AI 消息元素
            aiEl = document.createElement('div');
            aiEl.className = 'tb-aichat-msg assistant';
            msgBox.appendChild(aiEl);

            // 读取 SSE 流
            var reader = resp.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';

            while (true) {
                var chunk = await reader.read();
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });

                var lines = buffer.split('\n');
                buffer = lines.pop();

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line.startsWith('data:')) continue;
                    var jsonStr = line.slice(5).trim();
                    if (!jsonStr) continue;
                    try {
                        var sseData = JSON.parse(jsonStr);
                        // 检查错误
                        if (sseData.error) {
                            appendMessage('error', sseData.error);
                            if (aiEl) aiEl.remove();
                            return;
                        }
                        // 提取增量文本
                        var choices = sseData.output && sseData.output.choices;
                        if (choices && choices.length > 0) {
                            var delta = choices[0].message && choices[0].message.content;
                            if (delta) {
                                aiText += delta;
                                aiEl.textContent = aiText;
                                msgBox.scrollTop = msgBox.scrollHeight;
                            }
                        }
                    } catch(e) {}
                }
            }

            if (aiText) {
                messages.push({ role: 'assistant', content: aiText });
            } else if (aiEl) {
                aiEl.textContent = '(无响应)';
            }
        } catch(e) {
            var tp2 = document.getElementById('tb-aichat-typing');
            if (tp2) tp2.remove();
            appendMessage('error', '网络错误: ' + e.message);
        } finally {
            var sendBtn2 = document.getElementById('tb-aichat-send');
            if (sendBtn2) sendBtn2.disabled = false;
        }
    }

    function appendMessage(role, text) {
        var msgBox = document.getElementById('tb-aichat-messages');
        if (!msgBox) return;
        var el = document.createElement('div');
        el.className = 'tb-aichat-msg ' + role;
        el.textContent = text;
        msgBox.appendChild(el);
        msgBox.scrollTop = msgBox.scrollHeight;
    }

    function init() {
        createStyles();
        createElements();
        // 快捷键 Ctrl+J
        document.addEventListener('keydown', function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'j') {
                e.preventDefault();
                toggle();
            }
            if (e.key === 'Escape' && isOpen) {
                close();
            }
        });
    }

    return { init: init, open: open, close: close, toggle: toggle, send: send, clear: clear, setModel: setModel, onKeydown: onKeydown };
})();

// ==================== v3.0 OCR 粘贴识别 ====================
const ToolboxOCR = (function() {
    function init() {
        document.addEventListener('paste', function(e) {
            var items = e.clipboardData && e.clipboardData.items;
            if (!items) return;
            for (var i = 0; i < items.length; i++) {
                if (items[i].type && items[i].type.indexOf('image') === 0) {
                    var blob = items[i].getAsFile();
                    if (!blob) continue;
                    e.preventDefault();
                    handleImage(blob);
                    return;
                }
            }
        });
    }

    async function handleImage(blob) {
        // 显示 OCR 弹窗
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100000;display:flex;align-items:center;justify-content:center';
        overlay.id = 'tb-ocr-overlay';

        var reader = new FileReader();
        reader.onload = function(ev) {
            overlay.innerHTML = `
                <div style="background:#fff;border-radius:12px;padding:24px;max-width:500px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
                    <h3 style="margin:0 0 12px;font-size:16px">📷 OCR 图片识别</h3>
                    <img src="${ev.target.result}" style="max-width:100%;max-height:200px;border-radius:8px;margin-bottom:12px" />
                    <div id="tb-ocr-result" style="min-height:40px;font-size:14px;color:#666">正在识别中...</div>
                    <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end">
                        <button id="tb-ocr-copy" style="padding:6px 16px;border:1px solid #ddd;border-radius:6px;cursor:pointer;background:#f5f5f7;font-size:13px" disabled>复制文字</button>
                        <button id="tb-ocr-close" style="padding:6px 16px;border:none;border-radius:6px;cursor:pointer;background:#6366f1;color:#fff;font-size:13px">关闭</button>
                    </div>
                </div>
            `;
            document.body.appendChild(overlay);

            document.getElementById('tb-ocr-close').onclick = function() { overlay.remove(); };
            document.getElementById('tb-ocr-copy').onclick = function() {
                var text = document.getElementById('tb-ocr-result').textContent;
                navigator.clipboard.writeText(text).then(function() {
                    if (window.ToolboxToast) ToolboxToast.show('已复制到剪贴板', 'success');
                });
            };

            // 发送到 OCR API
            var formData = new FormData();
            formData.append('file', blob, 'pasted.png');

            fetch('/api/ocr', { method: 'POST', body: formData })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var resultEl = document.getElementById('tb-ocr-result');
                    if (data.error) {
                        resultEl.innerHTML = '<span style="color:#ef4444">' + data.error + '</span>';
                    } else {
                        resultEl.innerHTML = '<pre style="white-space:pre-wrap;word-break:break-word;margin:0;max-height:300px;overflow-y:auto;font-family:inherit">' + escapeHtml(data.text || '(未识别到文字)') + '</pre>';
                        resultEl.style.color = '#1d1d1f';
                        document.getElementById('tb-ocr-copy').disabled = false;
                    }
                })
                .catch(function(err) {
                    document.getElementById('tb-ocr-result').innerHTML = '<span style="color:#ef4444">请求失败: ' + err.message + '</span>';
                });
        };
        reader.readAsDataURL(blob);
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    return { init: init, handleImage: handleImage };
})();

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

    function initAll() {
        ToolboxTheme.init();
        var isHome = window.location.pathname === '/' || window.location.pathname === '/index';
        // 自动注入导航栏（首页除外）
        if (!isHome && !document.getElementById('tb-nav-bar')) {
            ToolboxNav.init();
        }
        // v3.0: 初始化 AI 对话助手（全部页面）
        if (typeof ToolboxAIChat !== 'undefined' && !document.querySelector('.tb-aichat-fab')) {
            ToolboxAIChat.init();
        }
        // v3.0: 初始化 OCR 粘贴识别（全部页面）
        if (typeof ToolboxOCR !== 'undefined') {
            ToolboxOCR.init();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }
})();
