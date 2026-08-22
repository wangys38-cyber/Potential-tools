/**
 * 全局 AI 助手模块
 * 功能：增强命令面板的 AI 能力、自然语言操作、跨工具查询、智能建议
 */

(function() {
    'use strict';

    // ============ 配置 ============
    const AI_CHAT_API = '/api/ai-chat';
    const STORAGE_KEY = (typeof window._USER_PREFIX !== 'undefined' ? window._USER_PREFIX : '') + 'ai_assistant_history';
    const MAX_HISTORY = 20;

    // ============ 工具函数 ============
    function showToast(msg, type) {
        if (window.showToast) {
            window.showToast(msg, type || 'success');
        } else {
            alert(msg);
        }
    }

    function getHistory() {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        } catch (e) {
            return [];
        }
    }

    function saveHistory(history) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-MAX_HISTORY)));
    }

    // ============ AI 命令理解 ============
    const TOOL_INTENTS = [
        { keywords: ['cr', '问题', 'bug', '缺陷', '分析', 'excel'], tool: 'excel-analysis', action: '上传Excel进行CR分析' },
        { keywords: ['计划', '节点', '排期', '项目', '甘特'], tool: 'plan-generator', action: '生成项目计划' },
        { keywords: ['周报', '总结', 'weekly'], tool: 'weekly-report', action: '生成周报' },
        { keywords: ['会议', '纪要', 'minutes', '录音'], tool: 'meeting-minutes', action: '生成会议纪要' },
        { keywords: ['日志', 'log', '异常', '崩溃', '死机'], tool: 'log-analyzer', action: '分析设备日志' },
        { keywords: ['邮件', 'email', '回复', '翻译'], tool: 'email-assistant', action: '生成/翻译邮件' },
        { keywords: ['趋势', 'trend', '增长', '解决曲线'], tool: 'bug-trend', action: '查看Bug趋势' },
        { keywords: ['测试', '报告', 'test', 'report'], tool: 'test-report', action: '分析测试报告' },
        { keywords: ['pdf', '转换', 'markdown', 'word'], tool: 'md2pdf', action: 'PDF转换' },
        { keywords: ['发布', '版本', 'checklist', '检查清单'], tool: 'release-checklist', action: '版本发布检查' },
        { keywords: ['可视化', '图表', 'chart', '数据'], tool: 'data-viz', action: '数据可视化' },
        { keywords: ['mttf', '可靠性', '寿命', '稳定'], tool: 'mttf-dashboard', action: 'MTTF可靠性分析' },
        { keywords: ['站会', 'daily', 'standup', '昨日', '今日'], tool: 'daily-standup', action: '每日站会' },
        { keywords: ['设置', '配置', 'setting', 'api', '飞书'], tool: 'settings', action: '打开设置' },
        { keywords: ['笔记', 'note', 'markdown', '牛马'], tool: 'noteNB', action: '打开牛马笔记' },
    ];

    const ACTION_INTENTS = [
        { keywords: ['深色', '暗黑', 'dark', '夜间'], action: () => { if (window.ToolboxTheme) window.ToolboxTheme.setTheme('dark'); else document.documentElement.setAttribute('data-theme', 'dark'); }, desc: '切换深色模式' },
        { keywords: ['浅色', '亮色', 'light', '白天'], action: () => { if (window.ToolboxTheme) window.ToolboxTheme.setTheme('light'); else document.documentElement.setAttribute('data-theme', 'light'); }, desc: '切换浅色模式' },
        { keywords: ['首页', '主页', 'home', '返回'], action: () => { window.location.href = '/'; }, desc: '返回首页' },
        { keywords: ['刷新', 'reload', '重新'], action: () => { location.reload(); }, desc: '刷新页面' },
        { keywords: ['同步', 'sync', '云端'], action: () => { if (window.V5Sync) window.V5Sync.sync(false); else showToast('同步功能未就绪'); }, desc: '同步数据到云端' },
    ];

    function understandIntent(query) {
        const q = query.toLowerCase();

        // 检查动作意图
        for (const intent of ACTION_INTENTS) {
            if (intent.keywords.some(k => q.includes(k))) {
                return { type: 'action', ...intent };
            }
        }

        // 检查工具意图
        for (const intent of TOOL_INTENTS) {
            if (intent.keywords.some(k => q.includes(k))) {
                return { type: 'tool', ...intent };
            }
        }

        return { type: 'chat', desc: 'AI 对话' };
    }

    // ============ AI 对话（SSE 流式） ============
    async function chatWithAI(messages, onChunk, onDone, onError) {
        try {
            const resp = await fetch(AI_CHAT_API, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ messages })
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.error || `HTTP ${resp.status}`);
            }

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let fullText = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6);
                        if (data === '[DONE]') continue;
                        try {
                            const parsed = JSON.parse(data);
                            const text = parsed.content || parsed.delta || '';
                            if (text) {
                                fullText += text;
                                if (onChunk) onChunk(text, fullText);
                            }
                        } catch (e) {
                            // 忽略解析错误
                        }
                    }
                }
            }

            if (onDone) onDone(fullText);
            return fullText;
        } catch (e) {
            if (onError) onError(e);
            throw e;
        }
    }

    // ============ AI 命令面板增强 ============
    let aiMode = false;
    let aiResponseEl = null;

    function enhanceCommandPalette() {
        // 等待 ToolboxCommandPalette 初始化
        if (typeof window.ToolboxCommandPalette === 'undefined') {
            setTimeout(enhanceCommandPalette, 500);
            return;
        }

        const originalOpen = window.ToolboxCommandPalette.open;
        window.ToolboxCommandPalette.open = function() {
            originalOpen.apply(this, arguments);
            setTimeout(addAIModeUI, 100);
        };

        // 监听输入框，添加 AI 模式切换
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Tab' && document.getElementById('tb-cp-input')) {
                const input = document.getElementById('tb-cp-input');
                if (document.activeElement === input) {
                    e.preventDefault();
                    toggleAIMode();
                }
            }
        });
    }

    function addAIModeUI() {
        const input = document.getElementById('tb-cp-input');
        if (!input || input.dataset.aiEnhanced) return;
        input.dataset.aiEnhanced = 'true';

        // 修改 placeholder
        input.placeholder = '搜索工具或输入命令... (Tab 切换 AI 模式)';

        // 添加 AI 模式指示器
        const searchWrap = input.parentElement;
        if (searchWrap && !document.getElementById('tb-cp-ai-indicator')) {
            const indicator = document.createElement('span');
            indicator.id = 'tb-cp-ai-indicator';
            indicator.style.cssText = 'font-size:11px;padding:3px 8px;border-radius:6px;background:var(--bg-primary,#f5f5f7);color:var(--text-secondary,#86868b);flex-shrink:0;margin-right:6px;display:none;';
            indicator.textContent = 'AI 模式';
            searchWrap.insertBefore(indicator, input);
        }

        // 监听输入，显示 AI 建议
        input.addEventListener('input', function() {
            if (aiMode) {
                showAISuggestions(this.value);
            }
        });

        // 监听回车，AI 模式下执行 AI 查询
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && aiMode) {
                e.preventDefault();
                e.stopPropagation();
                executeAIQuery(this.value);
            }
        }, true);
    }

    function toggleAIMode() {
        aiMode = !aiMode;
        const indicator = document.getElementById('tb-cp-ai-indicator');
        const input = document.getElementById('tb-cp-input');
        const list = document.getElementById('tb-cp-list');

        if (aiMode) {
            if (indicator) indicator.style.display = 'inline-block';
            if (input) {
                input.placeholder = '输入自然语言，AI 帮你操作...';
                input.style.color = 'var(--accent,#0071e3)';
            }
            if (list) {
                list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-secondary,#86868b);font-size:13px;">AI 模式：输入问题或指令，按回车执行<br><span style="font-size:11px;opacity:0.7;">例如：分析上周的 Bug 趋势 / 切换深色模式 / 生成周报</span></div>';
            }
        } else {
            if (indicator) indicator.style.display = 'none';
            if (input) {
                input.placeholder = '搜索工具或输入命令... (Tab 切换 AI 模式)';
                input.style.color = '';
            }
        }
    }

    function showAISuggestions(query) {
        if (!query.trim()) return;
        const list = document.getElementById('tb-cp-list');
        if (!list) return;

        const intent = understandIntent(query);
        let html = '';

        if (intent.type === 'tool') {
            html = `<div class="tb-cp-item selected" onclick="AIAssistant.openTool('${intent.tool}')">
                <div class="tb-cp-item-icon"></div>
                <div class="tb-cp-item-text">
                    <div class="tb-cp-item-name">跳转到「${intent.action}」</div>
                    <div class="tb-cp-item-desc">AI 识别到你想使用这个工具</div>
                </div>
                <span class="tb-cp-item-type">AI 建议</span>
            </div>`;
        } else if (intent.type === 'action') {
            html = `<div class="tb-cp-item selected" onclick="AIAssistant.executeAction()">
                <div class="tb-cp-item-icon"></div>
                <div class="tb-cp-item-text">
                    <div class="tb-cp-item-name">执行：${intent.desc}</div>
                    <div class="tb-cp-item-desc">AI 识别到你想执行这个操作</div>
                </div>
                <span class="tb-cp-item-type">AI 建议</span>
            </div>`;
        }

        html += `<div class="tb-cp-item" onclick="AIAssistant.askAI('${query.replace(/'/g, "\\'")}')">
            <div class="tb-cp-item-icon"></div>
            <div class="tb-cp-item-text">
                <div class="tb-cp-item-name">询问 AI：${query}</div>
                <div class="tb-cp-item-desc">让 AI 回答你的问题</div>
            </div>
            <span class="tb-cp-item-type">AI 对话</span>
        </div>`;

        list.innerHTML = html;
    }

    function executeAIQuery(query) {
        if (!query.trim()) return;
        const intent = understandIntent(query);

        if (intent.type === 'tool') {
            openTool(intent.tool);
        } else if (intent.type === 'action') {
            intent.action();
            if (window.ToolboxCommandPalette) window.ToolboxCommandPalette.close();
        } else {
            askAI(query);
        }
    }

    function openTool(toolId) {
        const toolMap = {
            'excel-analysis': '/excel-analysis',
            'plan-generator': '/plan-generator',
            'weekly-report': '/weekly-report',
            'meeting-minutes': '/meeting-minutes',
            'log-analyzer': '/log-analyzer',
            'email-assistant': '/email-assistant',
            'bug-trend': '/bug-trend',
            'test-report': '/test-report',
            'md2pdf': '/md2pdf',
            'release-checklist': '/release-checklist',
            'data-viz': '/data-viz',
            'mttf-dashboard': '/mttf-dashboard',
            'daily-standup': '/daily-standup',
            'settings': '/settings',
            'noteNB': '/noteNB/',
        };
        const url = toolMap[toolId];
        if (url) {
            window.location.href = url;
        }
    }

    function executeAction() {
        const input = document.getElementById('tb-cp-input');
        if (!input) return;
        const intent = understandIntent(input.value);
        if (intent.type === 'action') {
            intent.action();
            if (window.ToolboxCommandPalette) window.ToolboxCommandPalette.close();
        }
    }

    async function askAI(query) {
        const list = document.getElementById('tb-cp-list');
        if (!list) return;

        // 显示加载状态
        list.innerHTML = `<div style="padding:20px;">
            <div style="font-size:13px;color:var(--text-secondary,#86868b);margin-bottom:10px;"> AI 正在思考...</div>
            <div id="ai-response-content" style="font-size:14px;line-height:1.7;color:var(--text-primary,#1d1d1f);white-space:pre-wrap;word-break:break-word;"></div>
        </div>`;

        aiResponseEl = document.getElementById('ai-response-content');

        const history = getHistory();
        const messages = [
            ...history.slice(-6).map(h => ({ role: h.role, content: h.content })),
            { role: 'user', content: query }
        ];

        try {
            await chatWithAI(
                messages,
                (chunk, fullText) => {
                    if (aiResponseEl) aiResponseEl.textContent = fullText;
                },
                (fullText) => {
                    // 保存历史
                    history.push({ role: 'user', content: query });
                    history.push({ role: 'assistant', content: fullText });
                    saveHistory(history);

                    // 添加复制按钮
                    if (aiResponseEl) {
                        aiResponseEl.innerHTML += `<div style="margin-top:12px;"><button onclick="AIAssistant.copyResponse()" style="padding:6px 14px;font-size:12px;border:1px solid var(--border,rgba(0,0,0,0.1));border-radius:6px;background:var(--bg-primary,#f5f5f7);cursor:pointer;"> 复制回复</button></div>`;
                    }
                },
                (err) => {
                    if (aiResponseEl) {
                        aiResponseEl.innerHTML = `<span style="color:var(--error,#ff3b30);"> ${err.message}</span>`;
                    }
                }
            );
        } catch (e) {
            if (aiResponseEl) {
                aiResponseEl.innerHTML = `<span style="color:var(--error,#ff3b30);"> ${e.message}</span>`;
            }
        }
    }

    function copyResponse() {
        if (aiResponseEl) {
            const text = aiResponseEl.textContent.replace(' 复制回复', '').trim();
            navigator.clipboard.writeText(text).then(() => {
                showToast('已复制到剪贴板');
            });
        }
    }

    // ============ 全局 AI 助手浮窗 ============
    let floatingBtn = null;
    let chatPanel = null;
    let chatMessages = [];

    function createFloatingAssistant() {
        // 创建浮动按钮
        floatingBtn = document.createElement('div');
        floatingBtn.id = 'ai-floating-btn';
        floatingBtn.innerHTML = '';
        floatingBtn.style.cssText = `
            position:fixed;bottom:24px;right:24px;width:52px;height:52px;border-radius:50%;
            background:var(--text-primary,#1d1d1f);color:var(--bg-card,#fff);
            display:flex;align-items:center;justify-content:center;font-size:24px;
            cursor:pointer;box-shadow:0 4px 20px rgba(0,0,0,0.2);z-index:9999;
            transition:transform 0.2s,box-shadow 0.2s;
        `;
        floatingBtn.onmouseenter = () => floatingBtn.style.transform = 'scale(1.1)';
        floatingBtn.onmouseleave = () => floatingBtn.style.transform = 'scale(1)';
        floatingBtn.onclick = toggleChatPanel;
        document.body.appendChild(floatingBtn);

        // 创建聊天面板
        chatPanel = document.createElement('div');
        chatPanel.id = 'ai-chat-panel';
        chatPanel.style.cssText = `
            position:fixed;bottom:88px;right:24px;width:380px;max-width:calc(100vw - 48px);
            height:520px;max-height:calc(100vh - 120px);background:var(--bg-card,#fff);
            border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,0.25);
            z-index:10000;display:none;flex-direction:column;overflow:hidden;
            border:1px solid var(--border,rgba(0,0,0,0.08));
        `;
        chatPanel.innerHTML = `
            <div style="padding:14px 18px;border-bottom:1px solid var(--border,rgba(0,0,0,0.08));display:flex;align-items:center;gap:10px;">
                <span style="font-size:20px;"></span>
                <div style="flex:1;">
                    <div style="font-size:15px;font-weight:600;color:var(--text-primary,#1d1d1f);">AI 助手</div>
                    <div style="font-size:11px;color:var(--text-secondary,#86868b);">随时问我任何问题</div>
                </div>
                <button onclick="AIAssistant.toggleChatPanel()" style="background:none;border:none;cursor:pointer;font-size:20px;color:var(--text-secondary,#86868b);padding:4px;">×</button>
            </div>
            <div id="ai-chat-messages" style="flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;"></div>
            <div style="padding:12px;border-top:1px solid var(--border,rgba(0,0,0,0.08));display:flex;gap:8px;">
                <input type="text" id="ai-chat-input" placeholder="输入问题..." style="flex:1;padding:10px 14px;border:1px solid var(--border,rgba(0,0,0,0.1));border-radius:10px;font-size:14px;background:var(--bg-primary,#f5f5f7);color:var(--text-primary,#1d1d1f);outline:none;">
                <button onclick="AIAssistant.sendChatMessage()" style="padding:10px 16px;background:var(--text-primary,#1d1d1f);color:var(--bg-card,#fff);border:none;border-radius:10px;cursor:pointer;font-size:14px;">发送</button>
            </div>
        `;
        document.body.appendChild(chatPanel);

        // 回车发送
        setTimeout(() => {
            const input = document.getElementById('ai-chat-input');
            if (input) {
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') sendChatMessage();
                });
            }
        }, 100);

        // 加载历史
        loadChatHistory();
    }

    function toggleChatPanel() {
        if (chatPanel) {
            chatPanel.style.display = chatPanel.style.display === 'flex' ? 'none' : 'flex';
            if (chatPanel.style.display === 'flex') {
                setTimeout(() => {
                    const input = document.getElementById('ai-chat-input');
                    if (input) input.focus();
                }, 100);
            }
        }
    }

    function loadChatHistory() {
        const history = getHistory();
        const container = document.getElementById('ai-chat-messages');
        if (!container) return;

        chatMessages = history.slice(-10);
        renderChatMessages();
    }

    function renderChatMessages() {
        const container = document.getElementById('ai-chat-messages');
        if (!container) return;

        container.innerHTML = chatMessages.map(msg => {
            const isUser = msg.role === 'user';
            return `<div style="display:flex;justify-content:${isUser ? 'flex-end' : 'flex-start'};">
                <div style="max-width:80%;padding:10px 14px;border-radius:12px;font-size:13px;line-height:1.6;
                    background:${isUser ? 'var(--text-primary,#1d1d1f)' : 'var(--bg-primary,#f5f5f7)'};
                    color:${isUser ? 'var(--bg-card,#fff)' : 'var(--text-primary,#1d1d1f)'};
                    white-space:pre-wrap;word-break:break-word;">${msg.content}</div>
            </div>`;
        }).join('');

        container.scrollTop = container.scrollHeight;
    }

    async function sendChatMessage() {
        const input = document.getElementById('ai-chat-input');
        if (!input || !input.value.trim()) return;

        const query = input.value.trim();
        input.value = '';

        chatMessages.push({ role: 'user', content: query });
        renderChatMessages();

        // 显示加载中
        const container = document.getElementById('ai-chat-messages');
        const loadingEl = document.createElement('div');
        loadingEl.id = 'ai-chat-loading';
        loadingEl.style.cssText = 'display:flex;justify-content:flex-start;';
        loadingEl.innerHTML = '<div style="padding:10px 14px;border-radius:12px;font-size:13px;background:var(--bg-primary,#f5f5f7);color:var(--text-secondary,#86868b);"> 思考中...</div>';
        container.appendChild(loadingEl);
        container.scrollTop = container.scrollHeight;

        try {
            const messages = chatMessages.slice(-10).map(m => ({ role: m.role, content: m.content }));
            const response = await chatWithAI(messages);

            // 移除加载
            const loading = document.getElementById('ai-chat-loading');
            if (loading) loading.remove();

            chatMessages.push({ role: 'assistant', content: response });
            saveHistory(chatMessages);
            renderChatMessages();
        } catch (e) {
            const loading = document.getElementById('ai-chat-loading');
            if (loading) loading.remove();

            chatMessages.push({ role: 'assistant', content: ` ${e.message}` });
            renderChatMessages();
        }
    }

    // ============ 智能建议 ============
    function showSmartSuggestions() {
        // 根据当前页面提供智能建议
        const path = window.location.pathname;
        const suggestions = [];

        if (path.includes('excel-analysis')) {
            suggestions.push('上传 CR Excel 进行分析');
            suggestions.push('查看研发效率排名');
            suggestions.push('推送到飞书');
        } else if (path.includes('plan-generator')) {
            suggestions.push('生成项目计划');
            suggestions.push('查看甘特图');
            suggestions.push('分析关键路径');
        } else if (path.includes('bug-trend')) {
            suggestions.push('导入 CR 数据查看趋势');
            suggestions.push('对比版本 Bug 趋势');
        } else if (path === '/') {
            suggestions.push('今天有什么需要帮助的？');
            suggestions.push('按 ⌘K 打开命令面板');
        }

        return suggestions;
    }

    // ============ 初始化 ============
    function init() {
        // 增强命令面板
        enhanceCommandPalette();

        // 创建浮动 AI 助手
        if (!document.getElementById('ai-floating-btn')) {
            createFloatingAssistant();
        }

        console.log('AIAssistant initialized');
    }

    // 暴露到全局
    window.AIAssistant = {
        init,
        openTool,
        executeAction,
        askAI,
        copyResponse,
        toggleChatPanel,
        sendChatMessage,
        understandIntent,
        showSmartSuggestions
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
