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

// ==================== 工具函数 ====================
function _fetchWithTimeout(url, options, timeoutMs) {
    timeoutMs = timeoutMs || 15000;
    var controller = new AbortController();
    var timer = setTimeout(function() { controller.abort(); }, timeoutMs);
    return fetch(url, Object.assign({}, options, { signal: controller.signal }))
        .finally(function() { clearTimeout(timer); });
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}

// ==================== 统一 Markdown 渲染器 ====================
/**
 * 全站共享的 Markdown → HTML 渲染器
 * 支持：代码块、行内代码、h1-h3、粗体、斜体、链接、引用、列表、表格、分割线
 * 安全：先转义 HTML，再解析 Markdown，链接协议白名单
 */
const ToolboxMarkdown = (function() {

    function render(md) {
        if (!md) return '';
        var text = String(md);

        // 1. 先转义 HTML
        text = escapeHtml(text);

        // 2. 提取代码块（保护内容不被后续替换影响）
        var codeBlocks = [];
        text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, function(match, lang, code) {
            var idx = codeBlocks.length;
            var langClass = lang ? ' class="language-' + escapeHtml(lang) + '"' : '';
            codeBlocks.push('<pre' + langClass + '><code>' + code.replace(/\n$/, '') + '</code></pre>');
            return '\u0000CODEBLOCK' + idx + '\u0000';
        });

        // 3. 行内代码
        var inlineCodes = [];
        text = text.replace(/`([^`]+)`/g, function(match, code) {
            var idx = inlineCodes.length;
            inlineCodes.push('<code>' + code + '</code>');
            return '\u0000INLINE' + idx + '\u0000';
        });

        // 4. 表格（简单的 Markdown 表格语法）
        text = renderTable(text);

        // 5. 标题
        text = text.replace(/^### (.+)$/gm, '<h4>$1</h4>');
        text = text.replace(/^## (.+)$/gm, '<h3>$1</h3>');
        text = text.replace(/^# (.+)$/gm, '<h2>$1</h2>');

        // 6. 分割线
        text = text.replace(/^---+$/gm, '<hr>');

        // 7. 引用
        text = text.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

        // 8. 粗体和斜体
        text = text.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
        text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');

        // 9. 链接（协议白名单）
        text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, label, url) {
            var trimmed = url.trim();
            if (/^(https?:|mailto:|\/|#)/i.test(trimmed)) {
                return '<a href="' + trimmed + '" target="_blank" rel="noopener noreferrer">' + label + '</a>';
            }
            return '<span>' + label + '</span>';
        });

        // 10. 无序列表
        text = text.replace(/^(\s*)[-*] (.+)$/gm, function(match, indent, content) {
            return '<li>' + content + '</li>';
        });
        text = text.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, function(match) {
            return '<ul>' + match + '</ul>';
        });

        // 11. 有序列表
        text = text.replace(/^(\s*)\d+\. (.+)$/gm, function(match, indent, content) {
            return '<oli>' + content + '</oli>';
        });
        text = text.replace(/(<oli>[\s\S]*?<\/oli>)(?!\s*<oli>)/g, function(match) {
            return '<ol>' + match.replace(/<oli>/g, '<li>').replace(/<\/oli>/g, '</li>') + '</ol>';
        });

        // 12. 段落和换行
        text = text.replace(/\n\n+/g, '\n\n');
        var paragraphs = text.split(/\n\n/);
        text = paragraphs.map(function(p) {
            p = p.trim();
            if (!p) return '';
            // 不包裹已经是块级元素的内容
            if (/^<(h[2-4]|hr|blockquote|pre|ul|ol|table|div)/.test(p)) return p;
            if (p.indexOf('\u0000CODEBLOCK') === 0) return p;
            return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
        }).join('\n');

        // 13. 还原代码块和行内代码
        text = text.replace(/\u0000CODEBLOCK(\d+)\u0000/g, function(match, idx) {
            return codeBlocks[parseInt(idx)];
        });
        text = text.replace(/\u0000INLINE(\d+)\u0000/g, function(match, idx) {
            return inlineCodes[parseInt(idx)];
        });

        return text;
    }

    function renderTable(text) {
        // 匹配 Markdown 表格：| col1 | col2 |\n|---|---|\n| a | b |
        var tableRegex = /((?:^\|.+?\|$\n?)+)/gm;
        return text.replace(tableRegex, function(block) {
            var lines = block.trim().split('\n');
            if (lines.length < 2) return block;

            // 第二行是分隔线
            if (!/^\|?[\s-:|]+\|?$/.test(lines[1])) return block;

            // 解析表头
            var headers = parseTableRow(lines[0]);
            // 解析数据行
            var rows = [];
            for (var i = 2; i < lines.length; i++) {
                rows.push(parseTableRow(lines[i]));
            }

            var html = '<table><thead><tr>';
            headers.forEach(function(h) {
                html += '<th>' + h + '</th>';
            });
            html += '</tr></thead><tbody>';
            rows.forEach(function(row) {
                html += '<tr>';
                row.forEach(function(cell) {
                    html += '<td>' + cell + '</td>';
                });
                html += '</tr>';
            });
            html += '</tbody></table>';
            return html;
        });
    }

    function parseTableRow(line) {
        line = line.trim();
        if (line.startsWith('|')) line = line.slice(1);
        if (line.endsWith('|')) line = line.slice(0, -1);
        return line.split('|').map(function(c) { return c.trim(); });
    }

    /** 安全渲染：先 render 再用 DOMPurify 风格的清理（简化版） */
    function renderSafe(md) {
        var html = render(md);
        // 移除可能的危险标签属性（on* 事件处理器）
        html = html.replace(/\son\w+\s*=\s*"[^"]*"/gi, '');
        html = html.replace(/\son\w+\s*=\s*'[^']*'/gi, '');
        html = html.replace(/\son\w+\s*=\s*[^\s>]+/gi, '');
        return html;
    }

    return { render: render, renderSafe: renderSafe };
})();

// ==================== 表单草稿恢复 ====================
/**
 * 自动保存和恢复表单输入内容
 * 使用 localStorage 持久化，防止页面刷新或崩溃导致数据丢失
 */
const ToolboxDraft = (function() {

    function getKey(pageId, fieldId) {
        var uid = window._SERVER_USER_ID || 'guest';
        return 'draft_' + pageId + '_' + fieldId + '_u' + uid;
    }

    /**
     * 初始化草稿恢复
     * @param {string} pageId - 页面唯一标识
     * @param {Object} fields - { fieldId: elementId } 映射
     * @param {number} interval - 自动保存间隔（毫秒），默认 3000
     */
    function init(pageId, fields, interval) {
        interval = interval || 3000;
        var timer = null;

        // 恢复保存的草稿
        Object.keys(fields).forEach(function(fieldId) {
            var el = document.getElementById(fields[fieldId]);
            if (!el) return;

            var saved = null;
            try { saved = localStorage.getItem(getKey(pageId, fieldId)); } catch(e) {}

            if (saved !== null && saved !== '') {
                // 只在有保存数据时恢复（不覆盖已有内容）
                if (!el.value) {
                    el.value = saved;
                    // 标记为已恢复草稿
                    el.setAttribute('data-draft-restored', 'true');
                }
            }

            // 监听输入变化
            el.addEventListener('input', function() {
                el.removeAttribute('data-draft-restored');
                scheduleSave();
            });
        });

        function scheduleSave() {
            if (timer) clearTimeout(timer);
            timer = setTimeout(saveAll, interval);
        }

        function saveAll() {
            Object.keys(fields).forEach(function(fieldId) {
                var el = document.getElementById(fields[fieldId]);
                if (!el) return;
                try {
                    localStorage.setItem(getKey(pageId, fieldId), el.value);
                } catch(e) {
                    console.error('草稿保存失败:', e);
                }
            });
        }

        // 页面卸载前保存
        window.addEventListener('beforeunload', saveAll);

        // 页面隐藏时保存
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) saveAll();
        });

        return {
            save: saveAll,
            clear: function() {
                Object.keys(fields).forEach(function(fieldId) {
                    try { localStorage.removeItem(getKey(pageId, fieldId)); } catch(e) {}
                });
            },
            hasDraft: function() {
                return Object.keys(fields).some(function(fieldId) {
                    try {
                        return localStorage.getItem(getKey(pageId, fieldId)) !== null;
                    } catch(e) { return false; }
                });
            }
        };
    }

    return { init: init, getKey: getKey };
})();

// ==================== SSE 流式消费器 ====================
const ToolboxSSE = (function() {
    /**
     * 发起 POST 请求并消费 SSE 流式响应
     * @param {string} url - API 端点
     * @param {object} body - POST body（将被 JSON.stringify）
     * @param {object} opts - 选项
     *   opts.onChunk(text)  — 每收到一段文本时调用
     *   opts.onDone(fullText) — 流结束时调用
     *   opts.onError(err)  — 出错时调用
     * @returns {Promise<void>}
     */
    async function postStream(url, body, opts) {
        opts = opts || {};
        var onChunk = opts.onChunk || function() {};
        var onDone = opts.onDone || function() {};
        var onError = opts.onError || function() {};

        try {
            var resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body || {})
            });

            if (!resp.ok) {
                var errText = '';
                try { errText = (await resp.json()).error || ''; } catch(e) {
                    try { errText = await resp.text(); } catch(e2) {}
                }
                onError(errText || ('HTTP ' + resp.status));
                return;
            }

            var reader = resp.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            var fullText = '';

            while (true) {
                var chunk = await reader.read();
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });

                // 按行解析 SSE
                var lines = buffer.split('\n');
                buffer = lines.pop(); // 保留最后不完整的一行

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line.startsWith('data:')) continue;
                    var jsonStr = line.substring(5).trim();
                    if (!jsonStr) continue;
                    try {
                        var data = JSON.parse(jsonStr);
                        // 检查错误
                        if (data.error) {
                            onError(data.error);
                            return;
                        }
                        // 提取内容（兼容 DashScope 和 OpenAI 格式）
                        var content = '';
                        if (data.output && data.output.choices && data.output.choices[0]) {
                            content = data.output.choices[0].message.content;
                        } else if (data.choices && data.choices[0]) {
                            content = data.choices[0].delta.content || data.choices[0].message.content || '';
                        }
                        if (content) {
                            fullText += content;
                            onChunk(content, fullText);
                        }
                    } catch(e) {
                        // 忽略解析失败的行
                    }
                }
            }

            onDone(fullText);
        } catch(e) {
            onError(e.message || '网络错误');
        }
    }

    return { postStream: postStream };
})();

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
        _fetchWithTimeout('/api/user/preferences', {
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

// ==================== 统一文件上传组件 ====================
// 支持：大文件分片上传、直接上传、拖拽、进度条、多格式、重试、取消
const ToolboxUpload = (function() {
    var DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024; // 2MB
    var DEFAULT_MAX_RETRIES = 3;
    var DEFAULT_CONCURRENCY = 2;

    /**
     * 文件校验
     * @param {File} file
     * @param {Object} options - { accept, maxSize }
     * @returns {string|null} 错误信息，null 表示通过
     */
    function validateFile(file, options) {
        options = options || {};
        if (!file) return '未选择文件';
        if (options.maxSize && file.size > options.maxSize) {
            return '文件大小超过限制（最大 ' + (options.maxSize / 1024 / 1024).toFixed(0) + 'MB）';
        }
        if (options.accept) {
            var accepts = options.accept.split(',').map(function(s) { return s.trim().toLowerCase(); });
            var fileName = file.name.toLowerCase();
            var fileType = file.type.toLowerCase();
            var matched = accepts.some(function(a) {
                if (a.startsWith('.')) return fileName.endsWith(a);
                if (a.endsWith('/*')) return fileType.startsWith(a.replace('/*', '/'));
                return fileType === a;
            });
            if (!matched) return '不支持的文件格式：' + file.name;
        }
        return null;
    }

    /**
     * 渲染内置进度条 UI
     * @param {HTMLElement} container
     * @param {Object} options - { filename, showCancel }
     * @returns {Object} { setProgress(pct), setStatus(text), destroy(), onCancel(cb) }
     */
    function renderProgress(container, options) {
        options = options || {};
        var wrap = document.createElement('div');
        wrap.className = 'tb-upload-progress';
        wrap.innerHTML =
            '<div class="tb-upload-progress-header">' +
                '<span class="tb-upload-progress-filename">' + escapeHtml(options.filename || '上传中...') + '</span>' +
                '<span class="tb-upload-progress-pct">0%</span>' +
            '</div>' +
            '<div class="tb-upload-progress-track"><div class="tb-upload-progress-fill" style="width:0%"></div></div>' +
            '<div class="tb-upload-progress-status">准备上传...</div>';
        if (options.showCancel !== false) {
            var cancelBtn = document.createElement('button');
            cancelBtn.className = 'tb-upload-progress-cancel';
            cancelBtn.textContent = '取消';
            wrap.querySelector('.tb-upload-progress-header').appendChild(cancelBtn);
        }
        container.appendChild(wrap);

        var fill = wrap.querySelector('.tb-upload-progress-fill');
        var pctEl = wrap.querySelector('.tb-upload-progress-pct');
        var statusEl = wrap.querySelector('.tb-upload-progress-status');
        var cancelCb = null;

        if (cancelBtn) {
            cancelBtn.addEventListener('click', function() {
                if (cancelCb) cancelCb();
            });
        }

        return {
            setProgress: function(pct) {
                pct = Math.max(0, Math.min(100, pct));
                fill.style.width = pct + '%';
                pctEl.textContent = Math.round(pct) + '%';
            },
            setStatus: function(text) { statusEl.textContent = text; },
            setError: function(text) {
                statusEl.textContent = text;
                statusEl.style.color = '#ef4444';
                fill.style.background = '#ef4444';
            },
            onCancel: function(cb) { cancelCb = cb; },
            destroy: function() { if (wrap.parentNode) wrap.parentNode.removeChild(wrap); }
        };
    }

    /**
     * 创建分片上传器（大文件）
     * @param {HTMLElement} dropZone - 拖拽区域元素
     * @param {Object} options
     *   - accept: 文件类型 (如 ".xlsx,.xls")
     *   - maxSize: 最大文件大小 (字节)
     *   - maxRetries: 最大重试次数 (默认3)
     *   - concurrency: 并发数 (默认2)
     *   - chunkSize: 分块大小 (默认2MB)
     *   - progressContainer: 进度条容器元素（可选，传入则自动渲染进度条）
     *   - onProgress: 进度回调 (uploadedChunks, totalChunks)
     *   - onComplete: 完成回调 (uploadId, filename, responseData)
     *   - onError: 错误回调 (message)
     *   - onFileSelected: 文件选中回调 (file)，可用于校验
     */
    function create(dropZone, options) {
        options = options || {};
        var maxRetries = options.maxRetries || DEFAULT_MAX_RETRIES;
        var concurrency = options.concurrency || DEFAULT_CONCURRENCY;
        var chunkSize = options.chunkSize || DEFAULT_CHUNK_SIZE;

        var state = {
            file: null,
            uploadId: null,
            totalChunks: 0,
            uploadedChunks: 0,
            isUploading: false,
            cancelled: false,
            progressUI: null
        };

        function _bindDrag() {
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
                if (files.length > 0) handleFile(files[0]);
            });
            dropZone.addEventListener('click', function() {
                if (state.isUploading) return;
                var input = document.createElement('input');
                input.type = 'file';
                if (options.accept) input.accept = options.accept;
                input.addEventListener('change', function() {
                    if (input.files.length > 0) handleFile(input.files[0]);
                });
                input.click();
            });
        }

        function handleFile(file) {
            if (state.isUploading) {
                ToolboxToast.warning('正在上传中，请稍候');
                return;
            }
            var err = validateFile(file, { accept: options.accept, maxSize: options.maxSize });
            if (err) {
                ToolboxToast.error(err);
                if (options.onError) options.onError(err);
                return;
            }
            if (options.onFileSelected) options.onFileSelected(file);
            state.file = file;
            state.totalChunks = Math.ceil(file.size / chunkSize);
            state.uploadedChunks = 0;
            state.cancelled = false;

            if (options.progressContainer) {
                state.progressUI = renderProgress(options.progressContainer, {
                    filename: file.name,
                    showCancel: true
                });
                state.progressUI.onCancel(function() {
                    state.cancelled = true;
                    state.isUploading = false;
                    if (state.progressUI) { state.progressUI.setStatus('已取消'); state.progressUI.destroy(); }
                    ToolboxToast.info('上传已取消');
                });
            }

            startUpload();
        }

        async function startUpload() {
            state.isUploading = true;
            try {
                if (state.progressUI) state.progressUI.setStatus('初始化上传会话...');
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
                state.totalChunks = initData.total_chunks || state.totalChunks;

                if (state.progressUI) state.progressUI.setStatus('正在上传分块...');
                await uploadChunks();

                if (state.cancelled) return;

                if (state.progressUI) state.progressUI.setStatus('正在完成上传...');
                var completeResp = await fetch('/api/upload-complete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ upload_id: state.uploadId, filename: state.file.name })
                });
                var completeData = await completeResp.json();

                if (completeData.missing_chunks && completeData.missing_chunks.length > 0) {
                    ToolboxToast.warning('检测到 ' + completeData.missing_chunks.length + ' 个缺失分块，正在重试...');
                    if (state.progressUI) state.progressUI.setStatus('补传缺失分块...');
                    await retryMissingChunks(completeData.missing_chunks);
                    completeResp = await fetch('/api/upload-complete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ upload_id: state.uploadId, filename: state.file.name })
                    });
                    completeData = await completeResp.json();
                }

                if (completeData.error) throw new Error(completeData.error);

                state.isUploading = false;
                if (state.progressUI) { state.progressUI.setProgress(100); state.progressUI.setStatus('上传完成'); }
                if (options.onComplete) options.onComplete(state.uploadId, state.file.name, completeData);
            } catch (err) {
                state.isUploading = false;
                if (state.progressUI) state.progressUI.setError('上传失败: ' + err.message);
                if (options.onError) options.onError(err.message);
                else ToolboxToast.error('上传失败: ' + err.message);
            }
        }

        async function uploadChunks() {
            var indices = [];
            for (var i = 0; i < state.totalChunks; i++) indices.push(i);
            await runConcurrent(indices, uploadSingleChunk);
        }

        async function retryMissingChunks(missingIndices) {
            await runConcurrent(missingIndices, uploadSingleChunk);
        }

        async function uploadSingleChunk(index) {
            if (state.cancelled) return;
            var start = index * chunkSize;
            var end = Math.min(start + chunkSize, state.file.size);
            var chunk = state.file.slice(start, end);

            for (var attempt = 0; attempt < maxRetries; attempt++) {
                if (state.cancelled) return;
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
                    var pct = state.uploadedChunks / state.totalChunks * 100;
                    if (state.progressUI) state.progressUI.setProgress(pct);
                    if (options.onProgress) options.onProgress(state.uploadedChunks, state.totalChunks);
                    return;
                } catch (err) {
                    if (attempt < maxRetries - 1) {
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

        _bindDrag();

        return {
            getState: function() { return state; },
            cancel: function() { state.cancelled = true; state.isUploading = false; },
            handleFile: handleFile
        };
    }

    /**
     * 直接上传模式（小文件，直接 POST 到指定 URL）
     * @param {File} file
     * @param {string} url - 上传地址
     * @param {Object} options - { fieldName, extraData, progressContainer, onProgress, onComplete, onError }
     */
    async function directUpload(file, url, options) {
        options = options || {};
        var err = validateFile(file, { accept: options.accept, maxSize: options.maxSize });
        if (err) {
            ToolboxToast.error(err);
            if (options.onError) options.onError(err);
            throw new Error(err);
        }

        var progressUI = null;
        if (options.progressContainer) {
            progressUI = renderProgress(options.progressContainer, { filename: file.name, showCancel: false });
        }

        return new Promise(function(resolve, reject) {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', url, true);

            xhr.upload.addEventListener('progress', function(e) {
                if (e.lengthComputable) {
                    var pct = e.loaded / e.total * 100;
                    if (progressUI) progressUI.setProgress(pct);
                    if (options.onProgress) options.onProgress(e.loaded, e.total);
                }
            });

            xhr.addEventListener('load', function() {
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (xhr.status >= 200 && xhr.status < 300) {
                        if (progressUI) { progressUI.setProgress(100); progressUI.setStatus('上传完成'); }
                        if (options.onComplete) options.onComplete(data);
                        resolve(data);
                    } else {
                        var msg = (data && data.error) || '上传失败 (' + xhr.status + ')';
                        if (progressUI) progressUI.setError(msg);
                        if (options.onError) options.onError(msg);
                        reject(new Error(msg));
                    }
                } catch (e) {
                    if (progressUI) progressUI.setError('服务器响应解析失败');
                    reject(e);
                }
            });

            xhr.addEventListener('error', function() {
                var msg = '网络错误，上传失败';
                if (progressUI) progressUI.setError(msg);
                if (options.onError) options.onError(msg);
                reject(new Error(msg));
            });

            var formData = new FormData();
            formData.append(options.fieldName || 'file', file);
            if (options.extraData) {
                Object.keys(options.extraData).forEach(function(k) {
                    formData.append(k, options.extraData[k]);
                });
            }
            if (progressUI) progressUI.setStatus('正在上传...');
            xhr.send(formData);
        });
    }

    return {
        create: create,
        directUpload: directUpload,
        validateFile: validateFile,
        renderProgress: renderProgress,
        DEFAULT_CHUNK_SIZE: DEFAULT_CHUNK_SIZE
    };
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
            }).catch(function() {
                // Fallback to execCommand
                var textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.style.position = 'fixed';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();
                try { document.execCommand('copy'); } catch(e) {}
                document.body.removeChild(textarea);
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

        // 中间分类标签（和首页一致），公文包放在最前面
        var centerHtml = '<div class="tb-nav-center">';
        if (opts.showHome !== false) {
            centerHtml += '<a href="/" class="tb-nav-home" title="返回首页"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg></a>';
        }
        var categories = [
            {id: 'all', name: '全部'},
            {id: 'fav', name: '收藏'},
            {id: 'notes', name: '笔记'},
            {id: 'convert', name: '转换'},
            {id: 'analysis', name: '分析'},
            {id: 'dev', name: '研发'},
            {id: 'office', name: '办公'},
            {id: 'manage', name: '管理'},
            {id: 'fun', name: '趣味'}
        ];
        categories.forEach(function(cat) {
            centerHtml += '<a href="/?cat=' + cat.id + '" class="tb-nav-category" data-cat="' + cat.id + '">' + cat.name + '</a>';
        });
        centerHtml += '</div>';

        var rightHtml = '';
        // 搜索图标
        rightHtml += '<a href="/?focus=search" class="tb-nav-btn" title="搜索"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35" stroke-linecap="round"/></svg></a>';
        // 设置按钮
        rightHtml += '<a href="/settings" class="tb-nav-btn" title="设置">⚙️</a>';
        if (opts.extraActions) {
            opts.extraActions.forEach(function(a) {
                rightHtml += a.html;
            });
        }
        if (opts.showTheme !== false) {
            rightHtml += '<button class="tb-nav-theme" id="tb-nav-theme-btn" title="切换主题">🌙</button>';
        }
        // 用户信息槽位（异步填充）
        if (opts.showUser !== false) {
            rightHtml += '<span id="tb-nav-user-slot" class="tb-nav-user-slot"></span>';
        }

        bar.innerHTML =
            (leftHtml ? '<div class="tb-nav-left">' + leftHtml + '</div>' : '') +
            centerHtml +
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

        // 填充用户信息槽位
        ToolboxNav.updateUserSlot();

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

    /**
     * 更新导航栏用户信息槽位
     * 已登录 → 头像 + 退出按钮
     * 未登录 → 登录按钮
     */
    function updateUserSlot() {
        var slot = document.getElementById('tb-nav-user-slot');
        if (!slot) return;

        fetch('/api/user/info').then(function(r){return r.json();}).then(function(data){
            if (data.logged_in && data.user) {
                var u = data.user;
                var avatarHtml = '';
                if (u.avatar) {
                    avatarHtml = '<img src="' + escapeHtml(u.avatar) + '" class="tb-nav-avatar-img" alt="">';
                } else {
                    var initial = (u.name || u.email || '?').charAt(0).toUpperCase();
                    avatarHtml = '<span class="tb-nav-avatar-letter">' + escapeHtml(initial) + '</span>';
                }
                var name = escapeHtml(u.name || u.email || '用户');
                slot.innerHTML = '<div class="tb-nav-user" title="' + name + '">' +
                    '<div class="tb-nav-avatar">' + avatarHtml + '</div>' +
                    '<span class="tb-nav-user-name">' + name + '</span>' +
                    '<a href="/auth/logout" class="tb-nav-logout" title="退出登录">退出</a>' +
                    '</div>';
            } else {
                slot.innerHTML = '<a href="/login" class="tb-nav-login-btn">登录</a>';
            }
        }).catch(function(){
            slot.innerHTML = '<a href="/login" class="tb-nav-login-btn">登录</a>';
        });
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    return { init: init, updateUserSlot: updateUserSlot };
})();

// ==================== 最近使用工具追踪 ====================
const ToolboxRecent = (function() {
    // 动态获取存储 key，支持用户隔离
    function _key() { return (window._USER_PREFIX || '') + 'toolbox_recent_tools'; }
    var MAX_ITEMS = 6;

    function record(toolId, toolName, toolIcon) {
        var list = getAll();
        // 移除已存在的
        list = list.filter(function(t) { return t.id !== toolId; });
        // 添加到最前
        list.unshift({ id: toolId, name: toolName, icon: toolIcon, time: Date.now() });
        // 限制数量
        list = list.slice(0, MAX_ITEMS);
        try { localStorage.setItem(_key(), JSON.stringify(list)); } catch(e) {}
    }

    function getAll() {
        try {
            var data = localStorage.getItem(_key());
            return data ? JSON.parse(data) : [];
        } catch(e) {
            return [];
        }
    }

    function clear() {
        try { localStorage.removeItem(_key()); } catch(e) {}
    }

    return { record: record, getAll: getAll, clear: clear };
})();
window.ToolboxRecent = ToolboxRecent;

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
            .tb-aichat-fab{position:fixed;bottom:90px;right:24px;width:56px;height:56px;border-radius:50%;background:#fff;color:#1a1a1a;border:1px solid #e5e5e5;cursor:pointer;font-size:24px;box-shadow:0 4px 16px rgba(0,0,0,0.12);z-index:99998;transition:transform .2s,box-shadow .2s;display:flex;align-items:center;justify-content:center;padding:0}
            .tb-aichat-fab:hover{transform:scale(1.1);box-shadow:0 6px 24px rgba(0,0,0,0.15)}
            .tb-aichat-panel{position:fixed;top:0;right:0;width:400px;height:100vh;transform:translateX(100%);background:var(--tb-bg,#fff);box-shadow:-4px 0 24px rgba(0,0,0,0.1);z-index:99999;display:flex;flex-direction:column;transition:right .3s ease}
            @media (max-width: 768px) {
                .tb-aichat-panel {
                    width: 100vw !important;will-change:transform;
                    height: 100vh !important;
                    height: 100dvh !important;
                    right: 0 !important;
                    top: 0 !important;
                    border-radius: 0 !important;
                    padding-top: env(safe-area-inset-top);
                }
                .tb-aichat-fab {
                    width:44px !important;height:44px !important;font-size:18px !important;
                    bottom: max(120px, env(safe-area-inset-bottom)) !important;
                    right: 14px !important;
                }
                .tb-aichat-input-area {
                    padding-bottom: env(safe-area-inset-bottom) !important;
                }
            }
            .tb-aichat-panel.open{transform:translateX(0)}
            [data-theme="dark"] .tb-aichat-panel{background:#1a1a2e;box-shadow:-4px 0 24px rgba(0,0,0,0.5)}
            .tb-aichat-header{padding:16px 20px;border-bottom:1px solid var(--tb-border,#e5e5ea);display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
            [data-theme="dark"] .tb-aichat-header{border-color:rgba(255,255,255,0.08)}
            .tb-aichat-title{font-size:16px;font-weight:600;color:var(--tb-text,#1d1d1f);display:flex;align-items:center;gap:8px}
            [data-theme="dark"] .tb-aichat-title{color:#f0f0f2}
            .tb-aichat-close{background:none;border:none;font-size:28px;cursor:pointer;color:var(--tb-text-muted,#86868b);padding:8px 12px;line-height:1;min-width:44px;min-height:44px;display:flex;align-items:center;justify-content:center}
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
            .tb-aichat-input{flex:1;resize:none;border:1px solid var(--tb-border,#e5e5ea);border-radius:8px;padding:10px 12px;font-size:16px;font-family:inherit;background:var(--tb-bg,#fff);color:var(--tb-text,#1d1d1f);max-height:120px;min-height:44px;line-height:1.5}
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
        fab.innerHTML = '<svg width="36" height="36" viewBox="0 0 64 64" fill="none"><ellipse cx="32" cy="52" rx="18" ry="8" fill="#e53935"/><circle cx="32" cy="28" r="20" fill="#ffcc80"/><path d="M14 22 Q20 8 32 10 Q44 8 50 22 Q48 16 40 14 Q32 12 24 14 Q16 16 14 22Z" fill="#1a1a1a"/><ellipse cx="24" cy="28" rx="3" ry="4" fill="#1a1a1a"/><ellipse cx="40" cy="28" rx="3" ry="4" fill="#1a1a1a"/><circle cx="25" cy="27" r="1" fill="#fff"/><circle cx="41" cy="27" r="1" fill="#fff"/><path d="M22 34 Q32 42 42 34" stroke="#1a1a1a" stroke-width="2" fill="none" stroke-linecap="round"/><path d="M20 20 L26 22 M44 20 L38 22" stroke="#1a1a1a" stroke-width="2.5" stroke-linecap="round"/></svg>';
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
                <div class="tb-aichat-title"><svg width="20" height="20" viewBox="0 0 64 64" fill="none"><circle cx="32" cy="28" r="20" fill="#ffcc80"/><path d="M14 22 Q20 8 32 10 Q44 8 50 22 Q48 16 40 14 Q32 12 24 14 Q16 16 14 22Z" fill="#1a1a1a"/><ellipse cx="24" cy="28" rx="3" ry="4" fill="#1a1a1a"/><ellipse cx="40" cy="28" rx="3" ry="4" fill="#1a1a1a"/><path d="M22 34 Q32 42 42 34" stroke="#1a1a1a" stroke-width="2" fill="none" stroke-linecap="round"/></svg> AI 助手</div>
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
        var select = document.getElementById('tb-aichat-model-select');
        if (!select) return;
        try {
            var resp = await _fetchWithTimeout('/api/ai-models');
            if (resp.status === 401) {
                select.innerHTML = '<option value="">请先登录后使用</option>';
                return;
            }
            var data = await resp.json();
            if (data.models && data.models.length > 0) {
                select.innerHTML = data.models.map(function(m) {
                    var sel = m.id === data.current ? 'selected' : '';
                    return '<option value="' + escapeHtml(m.id) + '" ' + sel + '>' + escapeHtml(m.name) + ' — ' + escapeHtml(m.desc) + '</option>';
                }).join('');
                currentModel = data.current || (data.models[0] && data.models[0].id) || '';
            } else if (data.error) {
                select.innerHTML = '<option value="">⚠ ' + data.error + '</option>';
            } else {
                select.innerHTML = '<option value="">暂无可用模型</option>';
            }
        } catch(e) {
            select.innerHTML = '<option value="">⚠ 加载失败，请检查网络</option>';
        }
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
        if (abortController) { abortController.abort(); abortController = null; }
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
        if (text.length > 50000) {
            if (typeof ToolboxToast !== 'undefined') {
                ToolboxToast.show('消息过长，请限制在50000字符以内', 'warning');
            }
            return;
        }

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

            abortController = new AbortController();
            var resp = await fetch('/api/ai-chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ messages: messages, model: currentModel }),
                signal: abortController.signal
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
                                aiEl.innerHTML = (typeof ToolboxMarkdown !== 'undefined') ? ToolboxMarkdown.renderSafe(aiText) : escapeHtml(aiText);
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
                }).catch(function() {
                    // Fallback to execCommand
                    var textarea = document.createElement('textarea');
                    textarea.value = text;
                    textarea.style.position = 'fixed';
                    textarea.style.opacity = '0';
                    document.body.appendChild(textarea);
                    textarea.select();
                    try { document.execCommand('copy'); } catch(e) {}
                    document.body.removeChild(textarea);
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
                        resultEl.textContent = data.error;
                        resultEl.style.color = '#ef4444';
                    } else {
                        resultEl.innerHTML = '<pre style="white-space:pre-wrap;word-break:break-word;margin:0;max-height:300px;overflow-y:auto;font-family:inherit">' + escapeHtml(data.text || '(未识别到文字)') + '</pre>';
                        resultEl.style.color = '#1d1d1f';
                        document.getElementById('tb-ocr-copy').disabled = false;
                    }
                })
                .catch(function(err) {
                    var errResultEl = document.getElementById('tb-ocr-result');
                    errResultEl.textContent = '请求失败: ' + err.message;
                    errResultEl.style.color = '#ef4444';
                });
        };
        reader.readAsDataURL(blob);
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function open() {
        // 创建文件选择器
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/*';
        input.style.display = 'none';
        input.onchange = function(e) {
            var file = e.target.files[0];
            if (file) handleImage(file);
            document.body.removeChild(input);
        };
        document.body.appendChild(input);
        input.click();
    }

    return { init: init, handleImage: handleImage, open: open };
})();

// ==================== v4.0 全局命令面板 (Cmd+K) ====================
const ToolboxCommandPalette = (function() {
    var isOpen = false;
    var selectedIndex = 0;
    var items = [];
    var container = null;

    // 工具列表（与首页 TOOLS 保持一致）
    var TOOLS = [
        {id:'noteNB', icon:'📝', name:'牛马笔记', desc:'Markdown笔记，双向链接，关系图谱', url:'/noteNB/'},
        {id:'md2pdf', icon:'📄', name:'PDF快转', desc:'Markdown/Word转PDF', url:'/md2pdf'},
        {id:'plan-generator', icon:'📅', name:'软件计划生成器', desc:'生成项目计划时间节点', url:'/plan-generator'},
        {id:'project-info', icon:'📊', name:'项目信息收集', desc:'管理项目技术规格', url:'/project-info'},
        {id:'excel-analysis', icon:'📊', name:'CR问题分析', desc:'问题清单分析+AI根因', url:'/excel-analysis'},
        {id:'merit', icon:'🔔', name:'功德+1', desc:'敲木鱼积功德', url:'/merit'},
        {id:'test-report', icon:'📋', name:'测试报告分析', desc:'测试报告提取+AI分析', url:'/test-report'},
        {id:'meeting-minutes', icon:'🎙️', name:'会议纪要', desc:'语音转写+AI纪要', url:'/meeting-minutes'},
        {id:'weekly-report', icon:'📋', name:'智能周报', desc:'AI生成结构化周报', url:'/weekly-report'},
        {id:'bug-trend', icon:'📈', name:'Bug趋势看板', desc:'CR Excel自动生成Bug趋势图', url:'/bug-trend'},
        {id:'release-checklist', icon:'✅', name:'版本发布检查清单', desc:'Bring up→CP→DF→RRR检查项', url:'/release-checklist'},
        {id:'log-analyzer', icon:'🔍', name:'日志分析器', desc:'设备日志异常关键词聚合', url:'/log-analyzer'},
        {id:'email-assistant', icon:'✉️', name:'邮件助手', desc:'英文技术邮件模板+翻译', url:'/email-assistant'},
        {id:'data-viz', icon:'📊', name:'数据可视化Builder', desc:'Excel自选轴生成图表导出', url:'/data-viz'},
        {id:'settings', icon:'⚙️', name:'系统设置', desc:'AI配置、主题定制', url:'/settings'},
    ];

    // 命令列表
    var COMMANDS = [
        {icon:'🌙', name:'切换深色模式', desc:'Toggle dark theme', action:function(){ var d=document.documentElement.getAttribute('data-theme')==='dark'; document.documentElement.setAttribute('data-theme', d?'light':'dark'); try{localStorage.setItem('toolbox_theme', d?'light':'dark');}catch(e){} }},
        {icon:'☀️', name:'切换浅色模式', desc:'Toggle light theme', action:function(){ document.documentElement.setAttribute('data-theme','light'); try{localStorage.setItem('toolbox_theme','light');}catch(e){} }},
        {icon:'🤖', name:'打开 AI 对话', desc:'AI Chat Assistant', action:function(){ if(typeof ToolboxAIChat!=='undefined') ToolboxAIChat.open(); }},
        {icon:'🔍', name:'OCR 图片识别', desc:'Paste image to recognize', action:function(){ if(typeof ToolboxOCR!=='undefined') ToolboxOCR.open(); }},
        {icon:'⭐', name:'查看收藏工具', desc:'Go to favorites', action:function(){ window.location.href='/'; }},
        {icon:'🏠', name:'返回首页', desc:'Back to home', action:function(){ window.location.href='/'; }},
        {icon:'⚙️', name:'打开设置', desc:'Open settings', action:function(){ window.location.href='/settings'; }},
        {icon:'🔄', name:'刷新页面', desc:'Reload page', action:function(){ location.reload(); }},
    ];

    // v5.0 上下文感知命令：根据当前页面显示工具内功能
    var CONTEXT_COMMANDS = {
        '/meeting-minutes': [
            {icon:'🎤', name:'开始录音', desc:'Start recording', action:function(){ var b=document.querySelector('button[onclick*="startRecording"], #startRecBtn'); if(b) b.click(); }},
            {icon:'⏹️', name:'停止录音', desc:'Stop recording', action:function(){ var b=document.querySelector('button[onclick*="stopRecording"], #stopRecBtn'); if(b) b.click(); }},
            {icon:'✨', name:'生成会议纪要', desc:'Generate minutes', action:function(){ var b=document.getElementById('generateBtn'); if(b) b.click(); }},
            {icon:'📋', name:'复制纪要', desc:'Copy minutes', action:function(){ if(typeof copyMinutes==='function') copyMinutes(); }},
            {icon:'📨', name:'推送到飞书', desc:'Push to Feishu', action:function(){ if(typeof pushMinutesToFeishu==='function') pushMinutesToFeishu(); }},
        ],
        '/weekly-report': [
            {icon:'✨', name:'生成周报', desc:'Generate weekly report', action:function(){ var b=document.getElementById('generateBtn'); if(b) b.click(); }},
            {icon:'📋', name:'复制周报', desc:'Copy report', action:function(){ if(typeof copyReport==='function') copyReport(); }},
            {icon:'🖨️', name:'导出/打印', desc:'Export / Print', action:function(){ if(typeof exportReport==='function') exportReport(); }},
            {icon:'📨', name:'推送到飞书', desc:'Push to Feishu', action:function(){ if(typeof pushToFeishu==='function') pushToFeishu(); }},
        ],
        '/md2pdf': [
            {icon:'📄', name:'选择文件', desc:'Select file', action:function(){ var i=document.querySelector('input[type=file]'); if(i) i.click(); }},
            {icon:'🔄', name:'开始转换', desc:'Convert to PDF', action:function(){ var b=document.querySelector('button[onclick*="convert"], #convertBtn'); if(b) b.click(); }},
        ],
        '/excel-analysis': [
            {icon:'📊', name:'上传Excel', desc:'Upload Excel', action:function(){ var i=document.querySelector('input[type=file]'); if(i) i.click(); }},
            {icon:'✨', name:'AI 根因分析', desc:'AI root cause analysis', action:function(){ var b=document.querySelector('button[onclick*="analyze"], #analyzeBtn'); if(b) b.click(); }},
        ],
        '/test-report': [
            {icon:'📋', name:'上传测试报告', desc:'Upload test report', action:function(){ var i=document.querySelector('input[type=file]'); if(i) i.click(); }},
            {icon:'✨', name:'AI 分析', desc:'AI analysis', action:function(){ var b=document.querySelector('button[onclick*="analyze"], #analyzeBtn'); if(b) b.click(); }},
        ],
        '/plan-generator': [
            {icon:'📅', name:'生成计划', desc:'Generate plan', action:function(){ if(typeof generatePlan==='function') generatePlan(); }},
            {icon:'📥', name:'导出CSV', desc:'Export CSV', action:function(){ var b=document.querySelector('button[onclick*="export"], #exportBtn'); if(b) b.click(); }},
        ],
        '/project-info': [
            {icon:'📊', name:'新建项目', desc:'New project', action:function(){ var b=document.querySelector('button[onclick*="newProject"], #newProjectBtn'); if(b) b.click(); }},
            {icon:'💾', name:'保存项目', desc:'Save project', action:function(){ var b=document.querySelector('button[onclick*="save"], #saveBtn'); if(b) b.click(); }},
        ],
        '/settings': [
            {icon:'🤖', name:'AI 配置', desc:'AI config', action:function(){ window.location.hash='#ai-config'; }},
            {icon:'📨', name:'飞书推送配置', desc:'Feishu push config', action:function(){ window.location.hash='#feishu'; }},
            {icon:'🎨', name:'主题设置', desc:'Theme settings', action:function(){ window.location.hash='#theme'; }},
        ],
    };

    function getContextCommands() {
        var path = window.location.pathname;
        // 匹配路径（支持末尾有无斜杠）
        for (var key in CONTEXT_COMMANDS) {
            if (path === key || path === key + '/' || path.indexOf(key) === 0) {
                return CONTEXT_COMMANDS[key].map(function(c) {
                    return {icon:c.icon, name:c.name, desc:c.desc, type:'action', action:c.action, category:'当前页面'};
                });
            }
        }
        return [];
    }

    function buildItems(query) {
        var toolItems = TOOLS.map(function(t) {
            return {icon:t.icon, name:t.name, desc:t.desc, type:'tool', url:t.url, category:'工具'};
        });
        var cmdItems = COMMANDS.map(function(c) {
            return {icon:c.icon, name:c.name, desc:c.desc, type:'cmd', action:c.action, category:'快捷命令'};
        });
        var actionItems = getContextCommands();
        var all = actionItems.concat(toolItems).concat(cmdItems);
        if (!query) return all;
        query = query.toLowerCase();
        return all.filter(function(item) {
            return item.name.toLowerCase().indexOf(query) >= 0 ||
                   item.desc.toLowerCase().indexOf(query) >= 0 ||
                   (item.category && item.category.toLowerCase().indexOf(query) >= 0);
        });
    }

    function createStyles() {
        var css = document.createElement('style');
        css.textContent = `
            .tb-cp-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.4);backdrop-filter:blur(4px);z-index:100000;opacity:0;transition:opacity .15s}
            .tb-cp-overlay.open{opacity:1}
            .tb-cp-panel{position:fixed;top:15%;left:50%;transform:translateX(-50%) translateY(-10px);
                width:90%;max-width:600px;background:var(--bg-card,#fff);
                border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.3);
                z-index:100001;overflow:hidden;opacity:0;transition:all .2s cubic-bezier(.4,0,.2,1);
                border:1px solid var(--border,rgba(0,0,0,0.08))}
            .tb-cp-panel.open{opacity:1;transform:translateX(-50%) translateY(0)}
            .tb-cp-search-wrap{display:flex;align-items:center;gap:10px;padding:16px 20px;border-bottom:1px solid var(--border,rgba(0,0,0,0.08))}
            .tb-cp-search-icon{width:20px;height:20px;color:var(--text-secondary,#86868b);flex-shrink:0}
            .tb-cp-input{flex:1;border:none;outline:none;background:transparent;font-size:16px;color:var(--text-primary,#1d1d1f);
                font-family:inherit}
            .tb-cp-input::placeholder{color:var(--text-secondary,#86868b)}
            .tb-cp-kbd{font-size:11px;color:var(--text-secondary,#86868b);background:var(--bg-primary,#f5f5f7);
                padding:3px 8px;border-radius:6px;border:1px solid var(--border,rgba(0,0,0,0.08));flex-shrink:0}
            .tb-cp-list{max-height:400px;overflow-y:auto;padding:8px}
            .tb-cp-item{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:10px;
                cursor:pointer;transition:background .1s}
            .tb-cp-item.selected{background:var(--accent,#0071e3);color:#fff}
            .tb-cp-item.selected .tb-cp-item-desc{color:rgba(255,255,255,0.7)}
            .tb-cp-item-icon{width:32px;height:32px;display:flex;align-items:center;justify-content:center;
                font-size:18px;background:var(--bg-primary,#f5f5f7);border-radius:8px;flex-shrink:0}
            .tb-cp-item.selected .tb-cp-item-icon{background:rgba(255,255,255,0.2)}
            .tb-cp-item-text{flex:1;min-width:0}
            .tb-cp-item-name{font-size:14px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
            .tb-cp-item-desc{font-size:12px;color:var(--text-secondary,#86868b);margin-top:2px}
            .tb-cp-item-type{font-size:10px;padding:2px 8px;border-radius:6px;flex-shrink:0;
                background:var(--bg-primary,#f5f5f7);color:var(--text-secondary,#86868b);font-weight:600}
            .tb-cp-item.selected .tb-cp-item-type{background:rgba(255,255,255,0.2);color:rgba(255,255,255,0.8)}
            .tb-cp-footer{display:flex;align-items:center;justify-content:space-between;padding:8px 16px;
                border-top:1px solid var(--border,rgba(0,0,0,0.08));font-size:11px;color:var(--text-secondary,#86868b)}
            .tb-cp-footer-hints{display:flex;gap:12px}
            .tb-cp-footer-hint{display:flex;align-items:center;gap:4px}
            .tb-cp-footer kbd{font-size:10px;padding:1px 5px;border-radius:4px;background:var(--bg-primary,#f5f5f7);
                border:1px solid var(--border,rgba(0,0,0,0.08));font-family:monospace}
            .tb-cp-empty{text-align:center;padding:32px;color:var(--text-secondary,#86868b);font-size:14px}
        `;
        document.head.appendChild(css);
    }

    function createElements() {
        var overlay = document.createElement('div');
        overlay.className = 'tb-cp-overlay';
        overlay.id = 'tb-cp-overlay';
        overlay.addEventListener('click', close);

        var panel = document.createElement('div');
        panel.className = 'tb-cp-panel';
        panel.id = 'tb-cp-panel';
        panel.innerHTML = `
            <div class="tb-cp-search-wrap">
                <svg class="tb-cp-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35" stroke-linecap="round"/></svg>
                <input type="text" class="tb-cp-input" id="tb-cp-input" placeholder="搜索工具或输入命令..." autocomplete="off" spellcheck="false">
                <span class="tb-cp-kbd">ESC</span>
            </div>
            <div class="tb-cp-list" id="tb-cp-list"></div>
            <div class="tb-cp-footer">
                <div class="tb-cp-footer-hints">
                    <span class="tb-cp-footer-hint"><kbd>↑↓</kbd> 导航</span>
                    <span class="tb-cp-footer-hint"><kbd>↵</kbd> 选择</span>
                    <span class="tb-cp-footer-hint"><kbd>ESC</kbd> 关闭</span>
                </div>
                <span>工具集 v4.0</span>
            </div>
        `;
        document.body.appendChild(overlay);
        document.body.appendChild(panel);
        container = panel;

        var input = document.getElementById('tb-cp-input');
        input.addEventListener('input', function() {
            items = buildItems(input.value);
            selectedIndex = 0;
            renderList();
        });
        input.addEventListener('keydown', onKeydown);
    }

    function renderList() {
        var list = document.getElementById('tb-cp-list');
        if (items.length === 0) {
            list.innerHTML = '<div class="tb-cp-empty">没有匹配的结果</div>';
            return;
        }
        list.innerHTML = items.map(function(item, i) {
            var sel = i === selectedIndex ? ' selected' : '';
            var typeLabel = item.type === 'cmd' ? '命令' : (item.type === 'action' ? '当前页' : '工具');
            return '<div class="tb-cp-item' + sel + '" data-idx="' + i + '">' +
                '<div class="tb-cp-item-icon">' + item.icon + '</div>' +
                '<div class="tb-cp-item-text">' +
                '<div class="tb-cp-item-name">' + item.name + '</div>' +
                '<div class="tb-cp-item-desc">' + item.desc + '</div>' +
                '</div>' +
                '<span class="tb-cp-item-type">' + typeLabel + '</span>' +
                '</div>';
        }).join('');

        // Click handlers
        list.querySelectorAll('.tb-cp-item').forEach(function(el) {
            el.addEventListener('click', function() {
                selectedIndex = parseInt(el.dataset.idx);
                executeSelected();
            });
            el.addEventListener('mouseenter', function() {
                selectedIndex = parseInt(el.dataset.idx);
                list.querySelectorAll('.tb-cp-item').forEach(function(e) { e.classList.remove('selected'); });
                el.classList.add('selected');
            });
        });
    }

    function onKeydown(e) {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
            renderList();
            scrollIntoView();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            selectedIndex = Math.max(selectedIndex - 1, 0);
            renderList();
            scrollIntoView();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            executeSelected();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            close();
        }
    }

    function scrollIntoView() {
        var list = document.getElementById('tb-cp-list');
        var sel = list.querySelector('.tb-cp-item.selected');
        if (sel) sel.scrollIntoView({ block: 'nearest' });
    }

    function executeSelected() {
        if (items.length === 0 || selectedIndex < 0) return;
        var item = items[selectedIndex];
        close();
        if (item.type === 'tool' && item.url) {
            // 记录最近使用
            if (typeof ToolboxRecent !== 'undefined') {
                var tool = TOOLS.find(function(t) { return t.id === item.id || t.url === item.url; });
                if (tool) ToolboxRecent.record(tool.id, tool.name, tool.icon);
            }
            window.location.href = item.url;
        } else if (item.action) {
            setTimeout(item.action, 100);
        }
    }

    function open() {
        if (!container) { createStyles(); createElements(); }
        var overlay = document.getElementById('tb-cp-overlay');
        var panel = document.getElementById('tb-cp-panel');
        overlay.classList.add('open');
        panel.classList.add('open');
        isOpen = true;
        var input = document.getElementById('tb-cp-input');
        input.value = '';
        items = buildItems('');
        selectedIndex = 0;
        renderList();
        setTimeout(function() { input.focus(); }, 100);
    }

    function close() {
        var overlay = document.getElementById('tb-cp-overlay');
        var panel = document.getElementById('tb-cp-panel');
        if (overlay) overlay.classList.remove('open');
        if (panel) panel.classList.remove('open');
        isOpen = false;
    }

    function toggle() {
        if (isOpen) close(); else open();
    }

    function init() {
        // 注册全局快捷键 Cmd+K / Ctrl+K
        document.addEventListener('keydown', function(e) {
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                toggle();
            }
        });
    }

    return { init: init, open: open, close: close, toggle: toggle };
})();

// ==================== 统一 Loading 组件 ====================
/**
 * 全站共享的 Loading 加载组件
 * 支持全屏加载和容器内局部加载
 *
 * 使用方式：
 *   ToolboxLoading.show('正在处理...')  // 全屏加载
 *   ToolboxLoading.hide()               // 隐藏
 *   var loader = ToolboxLoading.create(containerEl, '加载中')  // 局部加载
 *   loader.destroy()
 */
const ToolboxLoading = (function() {
    var _fullscreenEl = null;
    var _fullscreenCount = 0;

    function _buildSpinner(size) {
        size = size || 32;
        return '<div class="tb-spinner" style="width:' + size + 'px;height:' + size + 'px;"></div>';
    }

    function show(message, options) {
        options = options || {};
        _fullscreenCount++;
        if (_fullscreenEl) {
            if (message) _fullscreenEl.querySelector('.tb-loading-text').textContent = message;
            _fullscreenEl.style.display = 'flex';
            return;
        }
        _fullscreenEl = document.createElement('div');
        _fullscreenEl.className = 'tb-loading-fullscreen';
        _fullscreenEl.innerHTML =
            '<div class="tb-loading-box">' +
                _buildSpinner(40) +
                '<div class="tb-loading-text">' + (message || '加载中...') + '</div>' +
            '</div>';
        document.body.appendChild(_fullscreenEl);
    }

    function hide() {
        _fullscreenCount = Math.max(0, _fullscreenCount - 1);
        if (_fullscreenCount === 0 && _fullscreenEl) {
            _fullscreenEl.style.display = 'none';
        }
    }

    function forceHide() {
        _fullscreenCount = 0;
        if (_fullscreenEl) _fullscreenEl.style.display = 'none';
    }

    /**
     * 在指定容器内创建局部加载遮罩
     * @param {HTMLElement} container - 容器元素
     * @param {string} message - 提示文字
     * @returns {{destroy: function}} 控制器
     */
    function create(container, message) {
        if (!container) return { destroy: function() {} };
        var overlay = document.createElement('div');
        overlay.className = 'tb-loading-overlay';
        overlay.innerHTML =
            '<div class="tb-loading-inline">' +
                _buildSpinner(28) +
                (message ? '<div class="tb-loading-text">' + message + '</div>' : '') +
            '</div>';
        var prevPosition = container.style.position;
        if (getComputedStyle(container).position === 'static') {
            container.style.position = 'relative';
        }
        container.appendChild(overlay);
        return {
            destroy: function() {
                if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                container.style.position = prevPosition;
            }
        };
    }

    return { show: show, hide: hide, forceHide: forceHide, create: create };
})();

// ==================== 统一历史记录组件 ====================
/**
 * 全站共享的操作历史记录组件
 * 每个工具保留最近 N 条操作记录（默认5条），支持回溯查看
 * 数据存储在 localStorage，按用户隔离
 *
 * 使用方式：
 *   ToolboxHistory.add('excel-analysis', { title: 'bug分析.xlsx', timestamp: Date.now(), data: {...} })
 *   var records = ToolboxHistory.get('excel-analysis')
 *   ToolboxHistory.render(containerEl, 'excel-analysis', { onSelect: function(record) {...} })
 *   ToolboxHistory.clear('excel-analysis')
 */
const ToolboxHistory = (function() {
    var MAX_RECORDS = 5;

    function _getPrefix() {
        return (window._USER_PREFIX || '') + 'toolbox_history_';
    }

    function _storageKey(toolId) {
        return _getPrefix() + toolId;
    }

    /**
     * 添加一条操作记录
     * @param {string} toolId - 工具标识（如 'excel-analysis', 'test-report'）
     * @param {Object} record - 记录内容 { title, timestamp, data }
     */
    function add(toolId, record) {
        if (!toolId || !record) return;
        record.timestamp = record.timestamp || Date.now();
        try {
            var key = _storageKey(toolId);
            var records = JSON.parse(localStorage.getItem(key) || '[]');
            records.unshift(record);
            if (records.length > MAX_RECORDS) {
                records = records.slice(0, MAX_RECORDS);
            }
            localStorage.setItem(key, JSON.stringify(records));
        } catch(e) {
            console.warn('ToolboxHistory add failed:', e);
        }
    }

    /**
     * 获取某工具的历史记录
     * @param {string} toolId - 工具标识
     * @returns {Array} 历史记录数组（最新在前）
     */
    function get(toolId) {
        try {
            return JSON.parse(localStorage.getItem(_storageKey(toolId)) || '[]');
        } catch(e) {
            return [];
        }
    }

    /**
     * 清除某工具的历史记录
     * @param {string} toolId - 工具标识
     */
    function clear(toolId) {
        try {
            localStorage.removeItem(_storageKey(toolId));
        } catch(e) {}
    }

    /**
     * 清除所有工具的历史记录
     */
    function clearAll() {
        try {
            var prefix = _getPrefix();
            var keysToRemove = [];
            for (var i = 0; i < localStorage.length; i++) {
                var key = localStorage.key(i);
                if (key && key.indexOf(prefix + 'toolbox_history_') === 0) {
                    keysToRemove.push(key);
                }
            }
            keysToRemove.forEach(function(k) { localStorage.removeItem(k); });
        } catch(e) {}
    }

    function _formatTime(ts) {
        var d = new Date(ts);
        var now = new Date();
        var diff = now - d;
        if (diff < 60000) return '刚刚';
        if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
        if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
        if (diff < 604800000) return Math.floor(diff / 86400000) + '天前';
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }

    /**
     * 渲染历史记录UI
     * @param {HTMLElement} container - 容器元素
     * @param {string} toolId - 工具标识
     * @param {Object} options - { onSelect, onClear, emptyText, maxItems }
     */
    function render(container, toolId, options) {
        if (!container) return;
        options = options || {};
        var maxItems = options.maxItems || MAX_RECORDS;
        var records = get(toolId).slice(0, maxItems);

        if (records.length === 0) {
            container.innerHTML = '<div class="tb-history-empty">' + (options.emptyText || '暂无历史记录') + '</div>';
            return;
        }

        var html = '<div class="tb-history-list">';
        records.forEach(function(record, idx) {
            var title = escapeHtml(record.title || '未命名记录');
            var time = _formatTime(record.timestamp || Date.now());
            html += '<div class="tb-history-item" data-idx="' + idx + '" title="' + title + '">' +
                '<div class="tb-history-item-icon">📄</div>' +
                '<div class="tb-history-item-content">' +
                    '<div class="tb-history-item-title">' + title + '</div>' +
                    '<div class="tb-history-item-time">' + time + '</div>' +
                '</div>' +
                '<div class="tb-history-item-action">查看</div>' +
            '</div>';
        });
        html += '</div>';
        if (options.showClear !== false) {
            html += '<div class="tb-history-footer"><button class="tb-history-clear-btn">清除历史</button></div>';
        }
        container.innerHTML = html;

        // 绑定点击事件
        var items = container.querySelectorAll('.tb-history-item');
        items.forEach(function(item, idx) {
            item.addEventListener('click', function() {
                if (typeof options.onSelect === 'function') {
                    options.onSelect(records[idx], idx);
                }
            });
        });
        var clearBtn = container.querySelector('.tb-history-clear-btn');
        if (clearBtn) {
            clearBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                clear(toolId);
                render(container, toolId, options);
                if (typeof options.onClear === 'function') options.onClear();
            });
        }
    }

    return {
        add: add,
        get: get,
        clear: clear,
        clearAll: clearAll,
        render: render,
        MAX_RECORDS: MAX_RECORDS
    };
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

    // 用户隔离前缀：优先使用模板/服务端注入的值（同步），否则异步 fetch
    function _migrateRecentTools(prefix) {
        var oldKey = 'toolbox_recent_tools';
        var newKey = prefix + oldKey;
        if(localStorage.getItem(oldKey) !== null){
            if(localStorage.getItem(newKey) === null){
                localStorage.setItem(newKey, localStorage.getItem(oldKey));
            }
            localStorage.removeItem(oldKey);
        }
    }

    if (window._USER_PREFIX) {
        // 模板已通过 Jinja2 注入前缀，同步迁移
        _migrateRecentTools(window._USER_PREFIX);
    } else if (window._SERVER_USER_ID) {
        // noteNB 等静态页面通过服务端注入用户 ID
        window._USER_PREFIX = 'u' + window._SERVER_USER_ID + '_';
        _migrateRecentTools(window._USER_PREFIX);
    } else {
        // 回退：异步 fetch
        fetch('/api/user/info').then(function(r){return r.json();}).then(function(data){
            if(data.logged_in && data.user && data.user.id){
                window._USER_PREFIX = 'u' + data.user.id + '_';
                _migrateRecentTools(window._USER_PREFIX);
                // 异步完成后通知页面重新渲染最近使用
                document.dispatchEvent(new CustomEvent('userprefix-ready'));
            }
        }).catch(function(){/* 游客或网络错误，不设前缀 */});
    }

    function initAll() {
        ToolboxTheme.init();
        var isHome = window.location.pathname === '/' || window.location.pathname === '/index';
        var isLogin = window.location.pathname === '/login';
        // 自动注入导航栏（首页和登录页除外）
        if (!isHome && !isLogin && !document.getElementById('tb-nav-bar')) {
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
        // v4.0: 初始化命令面板（全部页面）
        if (typeof ToolboxCommandPalette !== 'undefined') {
            ToolboxCommandPalette.init();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }
})();
