/**
 * AI 智能助手前端 v8.0
 * 支持流式对话、会话管理、配置管理
 */
(function() {
    'use strict';

    // 状态
    let currentSessionId = null;
    let isStreaming = false;
    let currentMessages = [];

    // DOM 元素
    const messagesEl = document.getElementById('messages');
    const inputEl = document.getElementById('aiInput');
    const sendBtn = document.getElementById('sendBtn');
    const sessionListEl = document.getElementById('sessionList');
    const configPanel = document.getElementById('configPanel');
    const modelBadge = document.getElementById('modelBadge');
    const usageStatsEl = document.getElementById('usageStats');

    // 初始化
    document.addEventListener('DOMContentLoaded', function() {
        loadConfig();
        loadSessions();
        loadUsage();
        autoResizeTextarea();
    });

    // 自动调整输入框高度
    function autoResizeTextarea() {
        inputEl.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 120) + 'px';
        });
    }

    // 键盘事件
    window.handleKeyDown = function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    // 发送消息
    window.sendMessage = function() {
        const message = inputEl.value.trim();
        if (!message || isStreaming) return;

        if (!currentSessionId) {
            currentSessionId = generateSessionId();
        }

        // 添加用户消息
        addMessage('user', message);
        inputEl.value = '';
        inputEl.style.height = 'auto';

        // 显示打字指示器
        const typingEl = showTypingIndicator();

        // 发送请求（流式）
        isStreaming = true;
        sendBtn.disabled = true;

        fetch('/api/ai/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                session_id: currentSessionId
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('请求失败');
            }
            return response.body.getReader();
        })
        .then(reader => {
            const decoder = new TextDecoder();
            let assistantContent = '';
            let assistantEl = null;

            function read() {
                reader.read().then(({ done, value }) => {
                    if (done) {
                        isStreaming = false;
                        sendBtn.disabled = false;
                        removeTypingIndicator(typingEl);
                        loadSessions();
                        loadUsage();
                        return;
                    }

                    const chunk = decoder.decode(value);
                    const lines = chunk.split('\n');

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                if (data.error) {
                                    throw new Error(data.error);
                                }
                                if (data.content) {
                                    if (!assistantEl) {
                                        removeTypingIndicator(typingEl);
                                        assistantEl = addMessage('assistant', '');
                                    }
                                    assistantContent += data.content;
                                    assistantEl.querySelector('.message-content').textContent = assistantContent;
                                    scrollToBottom();
                                }
                            } catch (e) {
                                // 忽略解析错误
                            }
                        }
                    }

                    read();
                });
            }
            read();
        })
        .catch(error => {
            isStreaming = false;
            sendBtn.disabled = false;
            removeTypingIndicator(typingEl);
            addMessage('assistant', '❌ 错误: ' + error.message);
        });
    };

    // 快捷消息
    window.sendQuickMessage = function(message) {
        inputEl.value = message;
        sendMessage();
    };

    // 添加消息
    function addMessage(role, content) {
        const welcome = messagesEl.querySelector('.ai-welcome');
        if (welcome) welcome.remove();

        const msgEl = document.createElement('div');
        msgEl.className = 'message ' + role;
        msgEl.innerHTML = `
            <div class="message-avatar">${role === 'user' ? '👤' : '🤖'}</div>
            <div class="message-content"></div>
        `;
        msgEl.querySelector('.message-content').textContent = content;
        messagesEl.appendChild(msgEl);
        scrollToBottom();
        return msgEl;
    }

    // 显示打字指示器
    function showTypingIndicator() {
        const welcome = messagesEl.querySelector('.ai-welcome');
        if (welcome) welcome.remove();

        const el = document.createElement('div');
        el.className = 'message assistant';
        el.innerHTML = `
            <div class="message-avatar">🤖</div>
            <div class="typing-indicator"><span></span><span></span><span></span></div>
        `;
        messagesEl.appendChild(el);
        scrollToBottom();
        return el;
    }

    function removeTypingIndicator(el) {
        if (el && el.parentNode) {
            el.parentNode.removeChild(el);
        }
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // 新对话
    window.newConversation = function() {
        currentSessionId = null;
        messagesEl.innerHTML = `
            <div class="ai-welcome">
                <div class="ai-welcome-icon">🤖</div>
                <h3>欢迎使用 AI 智能助手</h3>
                <p>我可以帮你分析 Bug 数据、生成报告、解释趋势、提供改进建议。</p>
            </div>
        `;
        loadSessions();
    };

    // 清空当前对话
    window.clearConversation = function() {
        if (currentSessionId) {
            if (confirm('确定要删除这个对话吗？')) {
                fetch(`/api/ai/conversations/${currentSessionId}`, { method: 'DELETE' })
                    .then(() => {
                        newConversation();
                    });
            }
        }
    };

    // 加载会话列表
    function loadSessions() {
        fetch('/api/ai/conversations')
            .then(r => r.json())
            .then(data => {
                if (data.sessions && data.sessions.length > 0) {
                    sessionListEl.innerHTML = data.sessions.map(s => `
                        <div class="ai-session-item ${s.session_id === currentSessionId ? 'active' : ''}"
                             onclick="loadConversation('${s.session_id}')">
                            <div class="session-title">对话 ${s.session_id.slice(0, 8)}</div>
                            <div class="session-meta">${s.msg_count} 条消息</div>
                        </div>
                    `).join('');
                } else {
                    sessionListEl.innerHTML = '<div class="ai-empty-hint">暂无对话</div>';
                }
            });
    }

    // 加载对话
    window.loadConversation = function(sessionId) {
        currentSessionId = sessionId;
        fetch(`/api/ai/conversations/${sessionId}`)
            .then(r => r.json())
            .then(data => {
                messagesEl.innerHTML = '';
                if (data.messages && data.messages.length > 0) {
                    for (const msg of data.messages) {
                        addMessage(msg.role, msg.content);
                    }
                }
                loadSessions();
            });
    };

    // 配置面板
    window.toggleConfigPanel = function() {
        configPanel.style.display = configPanel.style.display === 'none' ? 'block' : 'none';
    };

    // 加载配置
    function loadConfig() {
        fetch('/api/ai/config')
            .then(r => r.json())
            .then(data => {
                if (data.active) {
                    document.getElementById('aiProvider').value = data.active.provider || 'openai';
                    document.getElementById('aiBaseUrl').value = data.active.base_url || '';
                    document.getElementById('aiModel').value = data.active.model || 'gpt-3.5-turbo';
                    document.getElementById('aiTemperature').value = data.active.temperature || 0.7;
                    document.getElementById('tempValue').textContent = data.active.temperature || 0.7;
                    document.getElementById('aiMaxTokens').value = data.active.max_tokens || 2000;
                    modelBadge.textContent = data.active.model || '已配置';
                    modelBadge.classList.add('configured');
                }
            });
    }

    // 保存配置
    window.saveAiConfig = function() {
        const config = {
            provider: document.getElementById('aiProvider').value,
            base_url: document.getElementById('aiBaseUrl').value,
            api_key: document.getElementById('aiApiKey').value,
            model: document.getElementById('aiModel').value,
            temperature: parseFloat(document.getElementById('aiTemperature').value),
            max_tokens: parseInt(document.getElementById('aiMaxTokens').value)
        };

        const statusEl = document.getElementById('configStatus');
        statusEl.className = 'config-status';
        statusEl.textContent = '保存中...';

        fetch('/api/ai/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                statusEl.className = 'config-status success';
                statusEl.textContent = '✅ 配置已保存';
                modelBadge.textContent = config.model;
                modelBadge.classList.add('configured');
                setTimeout(() => { statusEl.textContent = ''; }, 3000);
            } else {
                statusEl.className = 'config-status error';
                statusEl.textContent = '❌ ' + (data.error || '保存失败');
            }
        })
        .catch(e => {
            statusEl.className = 'config-status error';
            statusEl.textContent = '❌ ' + e.message;
        });
    };

    // 测试配置
    window.testAiConfig = function() {
        const statusEl = document.getElementById('configStatus');
        statusEl.className = 'config-status';
        statusEl.textContent = '测试中...';

        fetch('/api/ai/config/test', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    statusEl.className = 'config-status success';
                    statusEl.textContent = `✅ 连接成功 (${data.latency_ms}ms)`;
                } else {
                    statusEl.className = 'config-status error';
                    statusEl.textContent = '❌ ' + (data.error || '连接失败');
                }
            })
            .catch(e => {
                statusEl.className = 'config-status error';
                statusEl.textContent = '❌ ' + e.message;
            });
    };

    // 加载使用统计
    function loadUsage() {
        fetch('/api/ai/usage?days=7')
            .then(r => r.json())
            .then(data => {
                if (data.stats) {
                    usageStatsEl.innerHTML = `
                        <span>7天: ${data.stats.total_messages || 0} 条消息</span>
                        <span>Token: ${data.stats.total_tokens || 0}</span>
                    `;
                }
            });
    }

    // 生成会话 ID
    function generateSessionId() {
        return 'sess_' + Date.now().toString(36) + Math.random().toString(36).substr(2, 9);
    }

})();
