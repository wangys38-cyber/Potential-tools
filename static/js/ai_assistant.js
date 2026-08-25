/* ============================================================
 * Potential-tools AI Assistant — Apple Style
 * 功能：侧边栏对话、上下文感知、多轮对话、内容编辑、模板市场
 * ============================================================ */
(function () {
    'use strict';

    // ========== 工具函数 ==========
    function escapeHtml(str) {
        var d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }

    function getUserPrefix() {
        return window._USER_PREFIX || '';
    }

    function genId() {
        return 'c_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
    }

    function formatTime(ts) {
        var d = new Date(ts);
        var now = new Date();
        var diff = now - d;
        if (diff < 60000) return '刚刚';
        if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
        if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
        return d.getMonth() + 1 + '/' + d.getDate() + ' ' +
            String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    }

    // 简单 Markdown 渲染（代码块、行内代码、加粗、换行）
    function renderMarkdown(text) {
        if (!text) return '';
        var html = escapeHtml(text);
        // 代码块
        html = html.replace(/```([\s\S]*?)```/g, function (m, code) {
            return '<pre style="background:rgba(0,0,0,0.05);padding:10px;border-radius:8px;overflow-x:auto;margin:8px 0;font-size:12px;"><code>' + code + '</code></pre>';
        });
        // 行内代码
        html = html.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.06);padding:1px 5px;border-radius:4px;font-size:12px;">$1</code>');
        // 加粗
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        // 换行
        html = html.replace(/\n/g, '<br>');
        return html;
    }

    // ========== 预设模板 ==========
    var PRESET_TEMPLATES = [
        { id: 'code_review', name: '代码审查', prompt: '请审查以下代码，指出潜在问题、性能优化建议和最佳实践改进：\n\n', desc: '代码质量审查与优化建议' },
        { id: 'bug_analysis', name: 'Bug分析', prompt: '请分析以下错误信息和日志，给出可能的根因和修复方案：\n\n', desc: '错误日志根因分析' },
        { id: 'email', name: '邮件撰写', prompt: '请帮我撰写一封专业的英文技术邮件，主题是：\n\n', desc: '英文技术邮件撰写' },
        { id: 'doc_summary', name: '文档总结', prompt: '请总结以下文档的核心要点，分点列出：\n\n', desc: '长文档核心要点提取' },
        { id: 'translate', name: '翻译', prompt: '请将以下内容翻译成英文（技术语境，保持专业术语准确）：\n\n', desc: '中英技术翻译' },
        { id: 'explain', name: '概念解释', prompt: '请用通俗易懂的方式解释以下概念：\n\n', desc: '技术概念通俗解释' },
    ];

    // ========== 存储键 ==========
    function convKey() { return getUserPrefix() + 'ai_conversations'; }
    function currentConvKey() { return getUserPrefix() + 'ai_current_conversation'; }
    function templateKey() { return getUserPrefix() + 'ai_templates'; }
    function contextEnabledKey() { return getUserPrefix() + 'ai_context_enabled'; }

    // ========== 状态 ==========
    var state = {
        conversations: [],
        currentId: null,
        isOpen: false,
        currentModel: '',
        abortController: null,
        isStreaming: false,
        contextEnabled: true,
        customTemplates: [],
    };

    // ========== DOM 引用 ==========
    var dom = {};

    // ========== 对话存储 ==========
    function loadConversations() {
        try {
            state.conversations = JSON.parse(localStorage.getItem(convKey()) || '[]');
        } catch (e) { state.conversations = []; }
        try {
            state.currentId = localStorage.getItem(currentConvKey()) || null;
        } catch (e) { state.currentId = null; }
        // 确保当前对话存在
        if (state.currentId && !getConversation(state.currentId)) {
            state.currentId = null;
        }
        if (!state.currentId && state.conversations.length > 0) {
            state.currentId = state.conversations[0].id;
        }
    }

    function saveConversations() {
        try { localStorage.setItem(convKey(), JSON.stringify(state.conversations)); } catch (e) {}
        if (state.currentId) {
            try { localStorage.setItem(currentConvKey(), state.currentId); } catch (e) {}
        }
    }

    function getConversation(id) {
        return state.conversations.find(function (c) { return c.id === id; });
    }

    function getCurrentConversation() {
        return getConversation(state.currentId);
    }

    function createConversation(title) {
        var conv = {
            id: genId(),
            title: title || '新对话',
            messages: [],
            createdAt: Date.now(),
            updatedAt: Date.now(),
        };
        state.conversations.unshift(conv);
        state.currentId = conv.id;
        saveConversations();
        return conv;
    }

    function deleteConversation(id) {
        state.conversations = state.conversations.filter(function (c) { return c.id !== id; });
        if (state.currentId === id) {
            state.currentId = state.conversations.length > 0 ? state.conversations[0].id : null;
        }
        saveConversations();
    }

    function updateConversation(conv, data) {
        Object.assign(conv, data, { updatedAt: Date.now() });
        saveConversations();
    }

    function autoTitle(conv) {
        if (conv.messages.length > 0 && conv.title === '新对话') {
            var first = conv.messages[0].content;
            conv.title = first.length > 20 ? first.substring(0, 20) + '...' : first;
            saveConversations();
        }
    }

    // ========== 模板存储 ==========
    function loadTemplates() {
        try {
            state.customTemplates = JSON.parse(localStorage.getItem(templateKey()) || '[]');
        } catch (e) { state.customTemplates = []; }
    }

    function saveTemplates() {
        try { localStorage.setItem(templateKey(), JSON.stringify(state.customTemplates)); } catch (e) {}
    }

    function getAllTemplates() {
        return PRESET_TEMPLATES.concat(state.customTemplates);
    }

    // ========== 上下文感知 ==========
    function getPageContext() {
        if (window.AI_CONTEXT) return window.AI_CONTEXT;
        // 自动检测
        var path = window.location.pathname;
        var pageMap = {
            '/excel-analysis': { type: 'cr_analysis', label: 'CR 分析', quickQuestions: ['分析当前 CR 数据的主要问题', '给出根因分析建议', '总结高频缺陷类型'] },
            '/log-analyzer': { type: 'log_analysis', label: '日志分析', quickQuestions: ['分析日志中的异常模式', '定位可能的根因', '给出修复建议'] },
            '/plan-generator': { type: 'plan_generator', label: '计划生成器', quickQuestions: ['优化项目计划节点', '识别计划中的风险', '生成里程碑总结'] },
            '/test-report': { type: 'test_report', label: '测试报告', quickQuestions: ['总结测试报告要点', '分析未通过用例原因', '给出质量评估'] },
            '/meeting-minutes': { type: 'meeting_minutes', label: '会议纪要', quickQuestions: ['提炼会议待办事项', '总结会议决议', '生成会议摘要'] },
            '/weekly-report': { type: 'weekly_report', label: '周报', quickQuestions: ['优化周报表述', '补充风险提示', '提炼本周亮点'] },
            '/email-assistant': { type: 'email', label: '邮件助手', quickQuestions: ['润色邮件措辞', '翻译为英文', '生成回复邮件'] },
            '/notes': { type: 'notes', label: '笔记', quickQuestions: ['总结笔记要点', '生成知识卡片', '梳理笔记结构'] },
        };
        for (var key in pageMap) {
            if (path.indexOf(key) === 0) return pageMap[key];
        }
        return { type: 'general', label: '通用', quickQuestions: [] };
    }

    function getContextData() {
        var ctx = getPageContext();
        if (ctx && typeof ctx.getData === 'function') {
            try { return ctx.getData(); } catch (e) { return null; }
        }
        return null;
    }

    // ========== DOM 构建 ==========
    function buildDrawer() {
        // 遮罩
        var overlay = document.createElement('div');
        overlay.className = 'ai-overlay';
        overlay.id = 'ai-overlay';
        overlay.addEventListener('click', closeDrawer);

        // 侧边栏
        var drawer = document.createElement('div');
        drawer.className = 'ai-drawer';
        drawer.id = 'ai-drawer';
        drawer.innerHTML =
            '<div class="ai-header">' +
                '<div class="ai-header-left">' +
                    '<button class="ai-icon-btn" id="ai-conv-toggle" title="对话列表">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>' +
                    '</button>' +
                    '<div>' +
                        '<div class="ai-header-title" id="ai-header-title">AI 助手</div>' +
                        '<div class="ai-header-subtitle" id="ai-header-subtitle"></div>' +
                    '</div>' +
                '</div>' +
                '<div class="ai-header-actions">' +
                    '<select class="ai-model-select" id="ai-model-select" title="选择模型"></select>' +
                    '<button class="ai-icon-btn" id="ai-export-btn" title="导出对话">' +
                        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
                    '</button>' +
                    '<button class="ai-icon-btn ai-close-btn" id="ai-close-btn" title="关闭">×</button>' +
                '</div>' +
            '</div>' +
            '<div class="ai-conv-list" id="ai-conv-list">' +
                '<button class="ai-conv-new-btn" id="ai-new-conv-btn">+ 新建对话</button>' +
                '<div id="ai-conv-items"></div>' +
            '</div>' +
            '<div class="ai-context-bar" id="ai-context-bar" style="display:none;">' +
                '<span class="ai-context-label">上下文</span>' +
                '<span class="ai-context-text" id="ai-context-text"></span>' +
                '<button class="ai-context-toggle on" id="ai-context-toggle" title="是否发送上下文"></button>' +
            '</div>' +
            '<div class="ai-quick-questions" id="ai-quick-questions"></div>' +
            '<div class="ai-messages" id="ai-messages"></div>' +
            '<div class="ai-input-area">' +
                '<div class="ai-template-bar" id="ai-template-bar"></div>' +
                '<div class="ai-input-wrap">' +
                    '<textarea class="ai-input" id="ai-input" placeholder="输入消息... (Enter 发送, Shift+Enter 换行)" rows="1"></textarea>' +
                    '<button class="ai-send-btn" id="ai-send-btn" title="发送">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>' +
                    '</button>' +
                '</div>' +
                '<div class="ai-footer-hint">AI 生成内容仅供参考</div>' +
            '</div>';

        document.body.appendChild(overlay);
        document.body.appendChild(drawer);

        // 缓存 DOM
        dom.overlay = overlay;
        dom.drawer = drawer;
        dom.messages = drawer.querySelector('#ai-messages');
        dom.input = drawer.querySelector('#ai-input');
        dom.sendBtn = drawer.querySelector('#ai-send-btn');
        dom.closeBtn = drawer.querySelector('#ai-close-btn');
        dom.convList = drawer.querySelector('#ai-conv-list');
        dom.convItems = drawer.querySelector('#ai-conv-items');
        dom.convToggle = drawer.querySelector('#ai-conv-toggle');
        dom.newConvBtn = drawer.querySelector('#ai-new-conv-btn');
        dom.headerTitle = drawer.querySelector('#ai-header-title');
        dom.headerSubtitle = drawer.querySelector('#ai-header-subtitle');
        dom.modelSelect = drawer.querySelector('#ai-model-select');
        dom.contextBar = drawer.querySelector('#ai-context-bar');
        dom.contextText = drawer.querySelector('#ai-context-text');
        dom.contextToggle = drawer.querySelector('#ai-context-toggle');
        dom.quickQuestions = drawer.querySelector('#ai-quick-questions');
        dom.templateBar = drawer.querySelector('#ai-template-bar');
        dom.exportBtn = drawer.querySelector('#ai-export-btn');

        // 事件绑定
        dom.closeBtn.addEventListener('click', closeDrawer);
        dom.sendBtn.addEventListener('click', sendMessage);
        dom.convToggle.addEventListener('click', toggleConvList);
        dom.newConvBtn.addEventListener('click', function () { createConversation(); renderConvList(); renderMessages(); toggleConvList(); });
        dom.contextToggle.addEventListener('click', toggleContext);
        dom.exportBtn.addEventListener('click', exportConversation);
        dom.modelSelect.addEventListener('change', function () { state.currentModel = this.value; });

        dom.input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
            // 自动高度
            var el = e.target;
            setTimeout(function () {
                el.style.height = 'auto';
                el.style.height = Math.min(el.scrollHeight, 120) + 'px';
            }, 0);
        });

        // ESC 关闭
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && state.isOpen) closeDrawer();
            // Ctrl+J 切换
            if ((e.ctrlKey || e.metaKey) && e.key === 'j') {
                e.preventDefault();
                toggleDrawer();
            }
        });
    }

    // ========== 渲染 ==========
    function renderConvList() {
        if (state.conversations.length === 0) {
            dom.convItems.innerHTML = '<div style="padding:16px;text-align:center;font-size:12px;color:#86868b;">暂无对话</div>';
            return;
        }
        dom.convItems.innerHTML = state.conversations.map(function (conv) {
            var active = conv.id === state.currentId ? ' active' : '';
            var msgCount = conv.messages.filter(function (m) { return m.role !== 'system'; }).length;
            return '<div class="ai-conv-item' + active + '" data-id="' + conv.id + '">' +
                '<div class="ai-conv-item-info">' +
                    '<div class="ai-conv-item-title">' + escapeHtml(conv.title) + '</div>' +
                    '<div class="ai-conv-item-meta">' + msgCount + ' 条 · ' + formatTime(conv.updatedAt) + '</div>' +
                '</div>' +
                '<button class="ai-conv-item-del" data-del="' + conv.id + '" title="删除">×</button>' +
            '</div>';
        }).join('');

        // 事件
        dom.convItems.querySelectorAll('.ai-conv-item').forEach(function (el) {
            el.addEventListener('click', function (e) {
                if (e.target.dataset.del) return;
                state.currentId = this.dataset.id;
                saveConversations();
                renderConvList();
                renderMessages();
                updateHeader();
            });
        });
        dom.convItems.querySelectorAll('.ai-conv-item-del').forEach(function (el) {
            el.addEventListener('click', function (e) {
                e.stopPropagation();
                var id = this.dataset.del;
                if (confirm('确定删除这个对话？')) {
                    deleteConversation(id);
                    renderConvList();
                    renderMessages();
                    updateHeader();
                }
            });
        });
    }

    function renderMessages() {
        var conv = getCurrentConversation();
        if (!conv || conv.messages.length === 0) {
            dom.messages.innerHTML = '<div class="ai-msg system">有什么可以帮你的？</div>';
            return;
        }
        dom.messages.innerHTML = conv.messages.map(function (msg, idx) {
            return renderMessageEl(msg, idx);
        }).join('');
        scrollToBottom();
        bindMsgActions();
    }

    function renderMessageEl(msg, idx) {
        if (msg.role === 'system') {
            return '<div class="ai-msg system">' + escapeHtml(msg.content) + '</div>';
        }
        if (msg.role === 'error') {
            return '<div class="ai-msg error">' + escapeHtml(msg.content) + '</div>';
        }
        var editedTag = msg.edited ? '<span class="ai-msg-edited-tag">已编辑</span>' : '';
        var actions = '';
        if (msg.role === 'assistant') {
            actions = '<div class="ai-msg-actions">' +
                '<button class="ai-msg-action-btn" data-action="copy" data-idx="' + idx + '">复制</button>' +
                '<button class="ai-msg-action-btn" data-action="edit" data-idx="' + idx + '">编辑</button>' +
                '<button class="ai-msg-action-btn" data-action="regenerate" data-idx="' + idx + '">重新生成</button>' +
            '</div>';
        }
        return '<div class="ai-msg ' + msg.role + '" data-idx="' + idx + '">' +
            '<div class="ai-msg-content">' + renderMarkdown(msg.content) + editedTag + '</div>' +
            actions +
        '</div>';
    }

    function bindMsgActions() {
        dom.messages.querySelectorAll('.ai-msg-action-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var action = this.dataset.action;
                var idx = parseInt(this.dataset.idx);
                var conv = getCurrentConversation();
                if (!conv) return;
                var msg = conv.messages[idx];
                if (!msg) return;

                if (action === 'copy') {
                    copyToClipboard(msg.content);
                } else if (action === 'edit') {
                    enterEditMode(idx);
                } else if (action === 'regenerate') {
                    regenerateMessage(idx);
                }
            });
        });
    }

    function enterEditMode(idx) {
        var conv = getCurrentConversation();
        if (!conv) return;
        var msg = conv.messages[idx];
        var el = dom.messages.querySelector('.ai-msg[data-idx="' + idx + '"]');
        if (!el) return;
        el.innerHTML = '<textarea class="ai-msg-edit-area" id="ai-edit-' + idx + '">' + escapeHtml(msg.content) + '</textarea>' +
            '<div class="ai-msg-edit-actions">' +
                '<button class="ai-msg-edit-save" data-save="' + idx + '">保存</button>' +
                '<button class="ai-msg-edit-cancel" data-cancel="' + idx + '">取消</button>' +
            '</div>';
        var ta = el.querySelector('#ai-edit-' + idx);
        ta.focus();
        el.querySelector('[data-save]').addEventListener('click', function () {
            var newContent = ta.value.trim();
            if (newContent) {
                msg.content = newContent;
                msg.edited = true;
                saveConversations();
            }
            renderMessages();
        });
        el.querySelector('[data-cancel]').addEventListener('click', function () {
            renderMessages();
        });
    }

    function regenerateMessage(idx) {
        var conv = getCurrentConversation();
        if (!conv) return;
        // 找到该 AI 消息之前的用户消息
        var userMsg = null;
        for (var i = idx - 1; i >= 0; i--) {
            if (conv.messages[i].role === 'user') { userMsg = conv.messages[i]; break; }
        }
        if (!userMsg) return;
        // 删除该 AI 消息及之后的消息
        conv.messages = conv.messages.slice(0, idx);
        saveConversations();
        renderMessages();
        // 重新发送
        streamAIResponse(userMsg.content, conv);
    }

    function updateHeader() {
        var conv = getCurrentConversation();
        dom.headerTitle.textContent = conv ? conv.title : 'AI 助手';
        var ctx = getPageContext();
        dom.headerSubtitle.textContent = ctx && ctx.label ? ctx.label : '';
    }

    function renderContextBar() {
        var ctx = getPageContext();
        if (!ctx || ctx.type === 'general') {
            dom.contextBar.style.display = 'none';
            return;
        }
        dom.contextBar.style.display = 'flex';
        dom.contextText.textContent = ctx.label + (ctx.dataSummary ? ' · ' + ctx.dataSummary : '');
        // 读取设置
        try {
            state.contextEnabled = localStorage.getItem(contextEnabledKey()) !== '0';
        } catch (e) { state.contextEnabled = true; }
        dom.contextToggle.classList.toggle('on', state.contextEnabled);
    }

    function renderQuickQuestions() {
        var ctx = getPageContext();
        var questions = (ctx && ctx.quickQuestions) || [];
        if (questions.length === 0) {
            dom.quickQuestions.style.display = 'none';
            return;
        }
        dom.quickQuestions.style.display = 'flex';
        dom.quickQuestions.innerHTML = questions.map(function (q, i) {
            return '<button class="ai-quick-btn" data-q="' + i + '">' + escapeHtml(q) + '</button>';
        }).join('');
        dom.quickQuestions.querySelectorAll('.ai-quick-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var q = questions[parseInt(this.dataset.q)];
                dom.input.value = q;
                dom.input.style.height = 'auto';
                dom.input.style.height = Math.min(dom.input.scrollHeight, 120) + 'px';
                sendMessage();
            });
        });
    }

    function renderTemplateBar() {
        var templates = getAllTemplates();
        var html = templates.slice(0, 6).map(function (t) {
            return '<button class="ai-template-chip" data-tpl="' + t.id + '">' + escapeHtml(t.name) + '</button>';
        }).join('');
        html += '<button class="ai-template-manage-btn" id="ai-tpl-manage">管理</button>';
        dom.templateBar.innerHTML = html;

        dom.templateBar.querySelectorAll('.ai-template-chip').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var id = this.dataset.tpl;
                var tpl = getAllTemplates().find(function (t) { return t.id === id; });
                if (tpl) {
                    dom.input.value = tpl.prompt;
                    dom.input.focus();
                    dom.input.style.height = 'auto';
                    dom.input.style.height = Math.min(dom.input.scrollHeight, 120) + 'px';
                }
            });
        });
        dom.templateBar.querySelector('#ai-tpl-manage').addEventListener('click', openTemplateManager);
    }

    function scrollToBottom() {
        setTimeout(function () {
            dom.messages.scrollTop = dom.messages.scrollHeight;
        }, 10);
    }

    // ========== 对话操作 ==========
    function toggleConvList() {
        dom.convList.classList.toggle('open');
    }

    function toggleContext() {
        state.contextEnabled = !state.contextEnabled;
        dom.contextToggle.classList.toggle('on', state.contextEnabled);
        try { localStorage.setItem(contextEnabledKey(), state.contextEnabled ? '1' : '0'); } catch (e) {}
    }

    function sendMessage() {
        if (state.isStreaming) return;
        var text = dom.input.value.trim();
        if (!text) return;
        if (text.length > 50000) {
            showToast('消息过长，请限制在 50000 字符以内');
            return;
        }

        dom.input.value = '';
        dom.input.style.height = 'auto';

        var conv = getCurrentConversation();
        if (!conv) {
            conv = createConversation();
            renderConvList();
        }

        conv.messages.push({ role: 'user', content: text, timestamp: Date.now() });
        autoTitle(conv);
        saveConversations();
        renderMessages();
        updateHeader();

        streamAIResponse(text, conv);
    }

    function buildMessagesForAPI(userText, conv) {
        // 取最近 N 条历史
        var history = conv.messages.slice(-12);
        var messages = history.map(function (m) {
            return { role: m.role, content: m.content };
        });
        // 上下文注入
        if (state.contextEnabled) {
            var ctx = getPageContext();
            var ctxData = getContextData();
            if (ctx && ctx.type !== 'general') {
                var ctxText = '当前页面：' + ctx.label;
                if (ctxData) {
                    try { ctxText += '\n页面数据：' + JSON.stringify(ctxData).substring(0, 2000); } catch (e) {}
                }
                messages.unshift({ role: 'system', content: ctxText });
            }
        }
        return messages;
    }

    function streamAIResponse(userText, conv) {
        state.isStreaming = true;
        dom.sendBtn.disabled = true;

        // typing 指示器
        var typingEl = document.createElement('div');
        typingEl.className = 'ai-typing';
        typingEl.id = 'ai-typing';
        typingEl.innerHTML = '<span></span><span></span><span></span>';
        dom.messages.appendChild(typingEl);
        scrollToBottom();

        var aiEl = null;
        var aiText = '';

        state.abortController = new AbortController();

        fetch('/api/ai-chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                messages: buildMessagesForAPI(userText, conv),
                model: state.currentModel || undefined,
            }),
            signal: state.abortController.signal,
        }).then(function (resp) {
            var tp = document.getElementById('ai-typing');
            if (tp) tp.remove();

            if (!resp.ok) {
                return resp.json().catch(function () { return {}; }).then(function (errData) {
                    conv.messages.push({ role: 'error', content: errData.error || ('请求失败 (' + resp.status + ')'), timestamp: Date.now() });
                    saveConversations();
                    renderMessages();
                    throw new Error('request failed');
                });
            }

            // 创建 AI 消息元素
            aiEl = document.createElement('div');
            aiEl.className = 'ai-msg assistant';
            aiEl.innerHTML = '<div class="ai-msg-content"></div>';
            dom.messages.appendChild(aiEl);
            var contentEl = aiEl.querySelector('.ai-msg-content');

            var reader = resp.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';

            function readChunk() {
                reader.read().then(function (chunk) {
                    if (chunk.done) {
                        finishStream();
                        return;
                    }
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
                            if (sseData.error) {
                                conv.messages.push({ role: 'error', content: sseData.error, timestamp: Date.now() });
                                saveConversations();
                                renderMessages();
                                state.isStreaming = false;
                                dom.sendBtn.disabled = false;
                                return;
                            }
                            var choices = sseData.output && sseData.output.choices;
                            if (choices && choices.length > 0) {
                                var delta = choices[0].message && choices[0].message.content;
                                if (delta) {
                                    aiText += delta;
                                    contentEl.innerHTML = renderMarkdown(aiText);
                                    scrollToBottom();
                                }
                            }
                        } catch (e) {}
                    }
                    readChunk();
                }).catch(function (err) {
                    if (err.name === 'AbortError') {
                        finishStream();
                    } else {
                        var tp2 = document.getElementById('ai-typing');
                        if (tp2) tp2.remove();
                        conv.messages.push({ role: 'error', content: '网络错误: ' + err.message, timestamp: Date.now() });
                        saveConversations();
                        renderMessages();
                        state.isStreaming = false;
                        dom.sendBtn.disabled = false;
                    }
                });
            }

            function finishStream() {
                if (aiText) {
                    conv.messages.push({ role: 'assistant', content: aiText, timestamp: Date.now() });
                    saveConversations();
                    renderMessages();
                } else if (aiEl) {
                    aiEl.querySelector('.ai-msg-content').textContent = '(无响应)';
                }
                state.isStreaming = false;
                dom.sendBtn.disabled = false;
                state.abortController = null;
            }

            readChunk();
        }).catch(function (err) {
            var tp = document.getElementById('ai-typing');
            if (tp) tp.remove();
            if (err.name !== 'AbortError') {
                conv.messages.push({ role: 'error', content: '网络错误: ' + err.message, timestamp: Date.now() });
                saveConversations();
                renderMessages();
            }
            state.isStreaming = false;
            dom.sendBtn.disabled = false;
        });
    }

    // ========== 导出 ==========
    function exportConversation() {
        var conv = getCurrentConversation();
        if (!conv || conv.messages.length === 0) {
            showToast('没有可导出的对话内容');
            return;
        }
        var md = '# ' + conv.title + '\n\n';
        md += '> 导出时间：' + new Date().toLocaleString('zh-CN') + '\n\n';
        conv.messages.forEach(function (m) {
            if (m.role === 'user') {
                md += '## 用户\n\n' + m.content + '\n\n';
            } else if (m.role === 'assistant') {
                md += '## AI\n\n' + m.content + (m.edited ? ' *(已编辑)*' : '') + '\n\n';
            }
        });
        var blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = conv.title.replace(/[^\w\u4e00-\u9fa5]/g, '_') + '.md';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('对话已导出为 Markdown');
    }

    // ========== 模板管理弹窗 ==========
    function openTemplateManager() {
        var overlay = document.createElement('div');
        overlay.className = 'ai-modal-overlay show';
        overlay.innerHTML =
            '<div class="ai-modal">' +
                '<div class="ai-modal-header">' +
                    '<span class="ai-modal-title">模板管理</span>' +
                    '<button class="ai-icon-btn" id="ai-tpl-close">×</button>' +
                '</div>' +
                '<div class="ai-modal-body" id="ai-tpl-body"></div>' +
                '<div class="ai-modal-footer">' +
                    '<button class="ai-btn-secondary" id="ai-tpl-import">导入 JSON</button>' +
                    '<button class="ai-btn-secondary" id="ai-tpl-export">导出 JSON</button>' +
                    '<button class="ai-btn-primary" id="ai-tpl-add" style="margin-left:auto;">+ 新建模板</button>' +
                '</div>' +
            '</div>';
        document.body.appendChild(overlay);

        var body = overlay.querySelector('#ai-tpl-body');

        function renderList() {
            var all = getAllTemplates();
            if (all.length === 0) {
                body.innerHTML = '<div style="text-align:center;padding:30px;color:#86868b;font-size:13px;">暂无模板</div>';
                return;
            }
            body.innerHTML = all.map(function (t) {
                var isPreset = PRESET_TEMPLATES.find(function (p) { return p.id === t.id; });
                return '<div class="ai-template-list-item">' +
                    '<div class="ai-template-list-info">' +
                        '<div class="ai-template-list-name">' + escapeHtml(t.name) + (isPreset ? ' <span style="font-size:10px;color:#86868b;">预设</span>' : '') + '</div>' +
                        '<div class="ai-template-list-desc">' + escapeHtml(t.desc || t.prompt.substring(0, 50)) + '</div>' +
                    '</div>' +
                    '<div class="ai-template-list-actions">' +
                        (isPreset ? '' : '<button class="ai-msg-action-btn" data-edit="' + t.id + '">编辑</button>' +
                            '<button class="ai-msg-action-btn" data-del="' + t.id + '">删除</button>') +
                    '</div>' +
                '</div>';
            }).join('');

            body.querySelectorAll('[data-del]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var id = this.dataset.del;
                    state.customTemplates = state.customTemplates.filter(function (t) { return t.id !== id; });
                    saveTemplates();
                    renderList();
                    renderTemplateBar();
                });
            });
            body.querySelectorAll('[data-edit]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var id = this.dataset.edit;
                    var tpl = state.customTemplates.find(function (t) { return t.id === id; });
                    if (tpl) showTemplateForm(tpl);
                });
            });
        }

        function showTemplateForm(tpl) {
            var isEdit = !!tpl;
            tpl = tpl || { id: genId(), name: '', prompt: '', desc: '' };
            body.innerHTML =
                '<div class="ai-form-group">' +
                    '<label class="ai-form-label">模板名称</label>' +
                    '<input class="ai-form-input" id="ai-tpl-name" value="' + escapeHtml(tpl.name) + '" placeholder="如：代码审查">' +
                '</div>' +
                '<div class="ai-form-group">' +
                    '<label class="ai-form-label">描述（可选）</label>' +
                    '<input class="ai-form-input" id="ai-tpl-desc" value="' + escapeHtml(tpl.desc || '') + '" placeholder="简短描述">' +
                '</div>' +
                '<div class="ai-form-group">' +
                    '<label class="ai-form-label">Prompt 内容</label>' +
                    '<textarea class="ai-form-textarea" id="ai-tpl-prompt" placeholder="输入模板 Prompt...">' + escapeHtml(tpl.prompt) + '</textarea>' +
                '</div>' +
                '<div style="display:flex;gap:8px;margin-top:16px;">' +
                    '<button class="ai-btn-secondary" id="ai-tpl-back">返回</button>' +
                    '<button class="ai-btn-primary" id="ai-tpl-save" style="margin-left:auto;">' + (isEdit ? '保存' : '创建') + '</button>' +
                '</div>';

            body.querySelector('#ai-tpl-back').addEventListener('click', renderList);
            body.querySelector('#ai-tpl-save').addEventListener('click', function () {
                var name = body.querySelector('#ai-tpl-name').value.trim();
                var desc = body.querySelector('#ai-tpl-desc').value.trim();
                var prompt = body.querySelector('#ai-tpl-prompt').value.trim();
                if (!name || !prompt) { showToast('请填写名称和 Prompt'); return; }
                tpl.name = name;
                tpl.desc = desc;
                tpl.prompt = prompt;
                if (isEdit) {
                    var idx = state.customTemplates.findIndex(function (t) { return t.id === tpl.id; });
                    if (idx >= 0) state.customTemplates[idx] = tpl;
                } else {
                    state.customTemplates.push(tpl);
                }
                saveTemplates();
                renderTemplateBar();
                renderList();
            });
        }

        overlay.querySelector('#ai-tpl-close').addEventListener('click', function () { overlay.remove(); });
        overlay.addEventListener('click', function (e) { if (e.target === overlay) overlay.remove(); });
        overlay.querySelector('#ai-tpl-add').addEventListener('click', function () { showTemplateForm(null); });

        overlay.querySelector('#ai-tpl-export').addEventListener('click', function () {
            var data = JSON.stringify(state.customTemplates, null, 2);
            var blob = new Blob([data], { type: 'application/json' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'ai_templates.json';
            a.click();
            URL.revokeObjectURL(url);
            showToast('模板已导出');
        });

        overlay.querySelector('#ai-tpl-import').addEventListener('click', function () {
            var input = document.createElement('input');
            input.type = 'file';
            input.accept = '.json';
            input.onchange = function (e) {
                var file = e.target.files[0];
                if (!file) return;
                var reader = new FileReader();
                reader.onload = function (ev) {
                    try {
                        var imported = JSON.parse(ev.target.result);
                        if (Array.isArray(imported)) {
                            imported.forEach(function (t) {
                                if (t.name && t.prompt) {
                                    t.id = t.id || genId();
                                    state.customTemplates.push(t);
                                }
                            });
                            saveTemplates();
                            renderTemplateBar();
                            renderList();
                            showToast('导入成功，共 ' + imported.length + ' 个模板');
                        } else {
                            showToast('文件格式错误');
                        }
                    } catch (err) {
                        showToast('解析失败：' + err.message);
                    }
                };
                reader.readAsText(file);
            };
            input.click();
        });

        renderList();
    }

    // ========== 模型加载 ==========
    function loadModels() {
        fetch('/api/ai-models').then(function (r) { return r.json(); }).then(function (data) {
            if (data.models && data.models.length > 0) {
                dom.modelSelect.innerHTML = data.models.map(function (m) {
                    var sel = m.id === data.current ? 'selected' : '';
                    return '<option value="' + escapeHtml(m.id) + '" ' + sel + '>' + escapeHtml(m.name) + '</option>';
                }).join('');
                state.currentModel = data.current || (data.models[0] && data.models[0].id) || '';
            }
        }).catch(function () {});
    }

    // ========== Toast ==========
    function showToast(msg) {
        var existing = document.getElementById('ai-toast');
        if (existing) existing.remove();
        var toast = document.createElement('div');
        toast.id = 'ai-toast';
        toast.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:#1d1d1f;color:#fff;padding:10px 20px;border-radius:10px;font-size:13px;z-index:100001;box-shadow:0 4px 16px rgba(0,0,0,0.2);opacity:0;transition:opacity 0.2s;';
        toast.textContent = msg;
        document.body.appendChild(toast);
        setTimeout(function () { toast.style.opacity = '1'; }, 10);
        setTimeout(function () {
            toast.style.opacity = '0';
            setTimeout(function () { toast.remove(); }, 200);
        }, 2000);
    }

    function copyToClipboard(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(function () { showToast('已复制'); });
        } else {
            var ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); showToast('已复制'); } catch (e) {}
            document.body.removeChild(ta);
        }
    }

    // ========== 抽屉开关 ==========
    function openDrawer() {
        if (!dom.drawer) buildDrawer();
        dom.overlay.classList.add('show');
        dom.drawer.classList.add('open');
        state.isOpen = true;
        loadConversations();
        loadTemplates();
        renderConvList();
        renderMessages();
        renderContextBar();
        renderQuickQuestions();
        renderTemplateBar();
        updateHeader();
        loadModels();
        setTimeout(function () { dom.input.focus(); }, 300);
    }

    function closeDrawer() {
        if (dom.drawer) {
            dom.overlay.classList.remove('show');
            dom.drawer.classList.remove('open');
        }
        state.isOpen = false;
        if (state.abortController) {
            state.abortController.abort();
            state.abortController = null;
        }
    }

    function toggleDrawer() {
        if (state.isOpen) closeDrawer(); else openDrawer();
    }

    // ========== 对外接口 ==========
    window.AIAssistant = {
        open: openDrawer,
        close: closeDrawer,
        toggle: toggleDrawer,
        toggleChatPanel: toggleDrawer, // 兼容 navbar 调用
    };

    // 自动初始化（构建 DOM，但不打开）
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', buildDrawer);
    } else {
        buildDrawer();
    }
})();
