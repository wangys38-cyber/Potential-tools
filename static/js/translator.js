/**
 * IT 技术文档翻译器前端逻辑
 */
(function() {
    'use strict';

    // ===== DOM 元素 =====
    const sourceText = document.getElementById('sourceText');
    const targetText = document.getElementById('targetText');
    const sourceCharCount = document.getElementById('sourceCharCount');
    const targetCharCount = document.getElementById('targetCharCount');
    const translateBtn = document.getElementById('translateBtn');
    const copyBtn = document.getElementById('copyBtn');
    const clearBtn = document.getElementById('clearBtn');
    const swapBtn = document.getElementById('swapBtn');
    const exportBtn = document.getElementById('exportBtn');
    const sourceLang = document.getElementById('sourceLang');
    const targetLang = document.getElementById('targetLang');
    const itMode = document.getElementById('itMode');
    const streamMode = document.getElementById('streamMode');
    const settingsToggle = document.getElementById('settingsToggle');
    const advancedPanel = document.getElementById('advancedPanel');
    const glossaryFile = document.getElementById('glossaryFile');
    const glossaryStatus = document.getElementById('glossaryStatus');
    const clearGlossary = document.getElementById('clearGlossary');
    const statusText = document.getElementById('statusText');
    const historyList = document.getElementById('historyList');
    const historyClear = document.getElementById('historyClear');
    const toast = document.getElementById('toast');

    // ===== 状态 =====
    let userGlossary = null;
    let isTranslating = false;
    let currentAbortController = null;
    const _USER_PREFIX = window._USER_PREFIX || '';
    const HISTORY_KEY = _USER_PREFIX + 'translator_history';
    const TARGET_LANG_KEY = _USER_PREFIX + 'translator_target_lang';
    const IT_MODE_KEY = _USER_PREFIX + 'translator_it_mode';
    const MAX_HISTORY = 10;

    // ===== 工具函数 =====
    function showToast(msg, duration) {
        toast.textContent = msg;
        toast.classList.add('show');
        clearTimeout(toast._timer);
        toast._timer = setTimeout(function() {
            toast.classList.remove('show');
        }, duration || 2000);
    }

    function setStatus(msg, type) {
        statusText.textContent = msg || '';
        statusText.className = 'status-text' + (type ? ' ' + type : '');
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ===== 字数统计 =====
    function updateCharCount() {
        const srcLen = sourceText.value.length;
        const tgtLen = targetText.textContent.trim() === '译文将显示在这里' ? 0 : targetText.textContent.length;
        sourceCharCount.textContent = srcLen + ' 字';
        targetCharCount.textContent = tgtLen + ' 字';
    }

    sourceText.addEventListener('input', updateCharCount);

    // ===== 清空 =====
    clearBtn.addEventListener('click', function() {
        sourceText.value = '';
        targetText.innerHTML = '<span class="output-placeholder">译文将显示在这里</span>';
        setStatus('');
        updateCharCount();
        sourceText.focus();
    });

    // ===== 语言交换 =====
    swapBtn.addEventListener('click', function() {
        if (sourceLang.value === 'auto') {
            showToast('自动检测模式下无法交换');
            return;
        }
        const tmp = sourceLang.value;
        sourceLang.value = targetLang.value;
        targetLang.value = tmp;

        // 交换文本内容
        const srcVal = sourceText.value;
        const tgtVal = targetText.textContent.trim() === '译文将显示在这里' ? '' : targetText.textContent;
        sourceText.value = tgtVal;
        if (srcVal) {
            targetText.textContent = srcVal;
        } else {
            targetText.innerHTML = '<span class="output-placeholder">译文将显示在这里</span>';
        }
        updateCharCount();
    });

    // ===== 高级设置切换 =====
    settingsToggle.addEventListener('click', function() {
        const isHidden = advancedPanel.style.display === 'none';
        advancedPanel.style.display = isHidden ? 'block' : 'none';
        settingsToggle.classList.toggle('active', isHidden);
    });

    // ===== 术语库上传 =====
    glossaryFile.addEventListener('change', function(e) {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        glossaryStatus.textContent = '解析中...';

        fetch('/api/translate/glossary', {
            method: 'POST',
            body: formData
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                glossaryStatus.textContent = '解析失败';
                showToast(data.error);
                return;
            }
            userGlossary = data.glossary;
            glossaryStatus.textContent = '已加载 ' + data.count + ' 条术语';
            clearGlossary.style.display = 'flex';
            showToast('术语库加载成功，共 ' + data.count + ' 条');
        })
        .catch(function() {
            glossaryStatus.textContent = '解析失败';
            showToast('网络错误，请重试');
        });
    });

    clearGlossary.addEventListener('click', function() {
        userGlossary = null;
        glossaryFile.value = '';
        glossaryStatus.textContent = '未加载';
        clearGlossary.style.display = 'none';
        showToast('术语库已清除');
    });

    // ===== 术语高亮渲染 =====
    function renderGlossaryHighlights(text, hits) {
        if (!hits || hits.length === 0) {
            return escapeHtml(text);
        }

        // 按位置排序，去重（避免重叠）
        const sorted = hits.slice().sort(function(a, b) { return a.index - b.index; });
        const filtered = [];
        let lastEnd = -1;
        for (var i = 0; i < sorted.length; i++) {
            var hit = sorted[i];
            if (hit.index >= lastEnd) {
                filtered.push(hit);
                lastEnd = hit.index + hit.translation.length;
            }
        }

        if (filtered.length === 0) {
            return escapeHtml(text);
        }

        let result = '';
        let pos = 0;
        for (var j = 0; j < filtered.length; j++) {
            var h = filtered[j];
            if (h.index > pos) {
                result += escapeHtml(text.substring(pos, h.index));
            }
            result += '<span class="glossary-hit" title="' + escapeHtml(h.term) + ' → ' + escapeHtml(h.translation) + '">' + escapeHtml(h.translation) + '</span>';
            pos = h.index + h.translation.length;
        }
        if (pos < text.length) {
            result += escapeHtml(text.substring(pos));
        }
        return result;
    }

    // ===== AI 配置检查 =====
    async function checkAIConfig() {
        try {
            const resp = await fetch('/api/ai-config');
            const result = await resp.json();
            const data = result.data || {};
            return data.enabled && data.has_key;
        } catch (e) {
            return false;
        }
    }

    // ===== 翻译主逻辑 =====
    async function doTranslate() {
        const text = sourceText.value.trim();
        if (!text) {
            showToast('请输入要翻译的文本');
            sourceText.focus();
            return;
        }

        // 检查 AI 配置
        const aiEnabled = await checkAIConfig();
        if (!aiEnabled) {
            setStatus('AI 未配置，请先在设置页面配置 API Key', 'error');
            showToast('请先在设置页面配置 AI API Key');
            return;
        }

        if (isTranslating) {
            // 取消当前翻译
            if (currentAbortController) {
                currentAbortController.abort();
            }
            return;
        }

        isTranslating = true;
        currentAbortController = new AbortController();
        translateBtn.classList.add('loading');
        translateBtn.querySelector('span').textContent = '翻译中...';
        targetText.innerHTML = '';
        targetText.classList.add('streaming');
        setStatus('翻译中...');

        const payload = {
            text: text,
            source_lang: sourceLang.value,
            target_lang: targetLang.value,
            glossary: userGlossary,
            it_mode: itMode.checked
        };

        const useStream = streamMode.checked;

        if (useStream) {
            translateStream(payload);
        } else {
            translateNormal(payload);
        }
    }

    function translateStream(payload) {
        let fullText = '';
        let finalHits = [];

        fetch('/api/translate/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal: currentAbortController.signal
        })
        .then(function(response) {
            if (!response.ok) {
                return response.json().then(function(d) {
                    throw new Error(d.error || '翻译失败');
                });
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            function read() {
                reader.read().then(function(_ref) {
                    var done = _ref.done;
                    var value = _ref.value;
                    if (done) {
                        finishTranslation(fullText, finalHits);
                        return;
                    }
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n\n');
                    buffer = lines.pop() || '';

                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i].trim();
                        if (!line || !line.startsWith('data:')) continue;
                        var dataStr = line.substring(5).trim();
                        if (!dataStr) continue;
                        try {
                            var data = JSON.parse(dataStr);
                            if (data.error) {
                                throw new Error(data.error);
                            }
                            if (data.chunk) {
                                fullText += data.chunk;
                                targetText.textContent = fullText;
                                updateCharCount();
                            }
                            if (data.done) {
                                finalHits = data.hits || [];
                            }
                        } catch (e) {
                            if (e.name === 'AbortError') return;
                            console.warn('SSE parse error:', e);
                        }
                    }
                    read();
                }).catch(function(err) {
                    if (err.name === 'AbortError') {
                        handleAbort();
                        return;
                    }
                    handleError(err);
                });
            }
            read();
        })
        .catch(function(err) {
            if (err.name === 'AbortError') {
                handleAbort();
                return;
            }
            handleError(err);
        });
    }

    function translateNormal(payload) {
        fetch('/api/translate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal: currentAbortController.signal
        })
        .then(function(r) {
            if (!r.ok) {
                return r.json().then(function(d) {
                    throw new Error(d.error || '翻译失败');
                });
            }
            return r.json();
        })
        .then(function(data) {
            finishTranslation(data.translation, data.hits || []);
        })
        .catch(function(err) {
            if (err.name === 'AbortError') {
                handleAbort();
                return;
            }
            handleError(err);
        });
    }

    function finishTranslation(text, hits) {
        targetText.classList.remove('streaming');
        if (hits && hits.length > 0) {
            targetText.innerHTML = renderGlossaryHighlights(text, hits);
        } else {
            targetText.textContent = text;
        }
        updateCharCount();
        setStatus('翻译完成', 'success');
        addToHistory(sourceText.value.trim(), text, sourceLang.value, targetLang.value);
        resetTranslateBtn();
    }

    function handleError(err) {
        targetText.classList.remove('streaming');
        let errorMsg = err.message || '翻译失败';
        // 优化常见错误提示
        if (errorMsg.includes('AI功能未配置') || errorMsg.includes('未配置')) {
            errorMsg = 'AI 未配置，请先在设置页面配置 API Key';
        } else if (errorMsg.includes('429') || errorMsg.includes('过于频繁')) {
            errorMsg = '请求过于频繁，请稍后重试（AI API 限流 20 次/分钟）';
        } else if (errorMsg.includes('timeout') || errorMsg.includes('超时')) {
            errorMsg = '请求超时，请检查网络或稍后重试';
        } else if (errorMsg.includes('CSRF')) {
            errorMsg = '会话已过期，请刷新页面后重试';
        }
        if (!targetText.textContent.trim() || targetText.textContent === '译文将显示在这里') {
            targetText.innerHTML = '<span class="output-placeholder">翻译失败</span>';
        }
        setStatus(errorMsg, 'error');
        showToast(errorMsg);
        resetTranslateBtn();
    }

    function handleAbort() {
        targetText.classList.remove('streaming');
        setStatus('已取消');
        resetTranslateBtn();
    }

    function resetTranslateBtn() {
        isTranslating = false;
        currentAbortController = null;
        translateBtn.classList.remove('loading');
        translateBtn.querySelector('span').textContent = '翻译';
    }

    translateBtn.addEventListener('click', doTranslate);

    // Ctrl+Enter 快捷键
    sourceText.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            doTranslate();
        }
    });

    // ===== 复制译文 =====
    copyBtn.addEventListener('click', function() {
        const text = targetText.textContent.trim();
        if (!text || text === '译文将显示在这里' || text === '翻译失败') {
            showToast('没有可复制的译文');
            return;
        }
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(function() {
                showToast('已复制到剪贴板');
            }).catch(function() {
                fallbackCopy(text);
            });
        } else {
            fallbackCopy(text);
        }
    });

    function fallbackCopy(text) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try {
            document.execCommand('copy');
            showToast('已复制到剪贴板');
        } catch (e) {
            showToast('复制失败');
        }
        document.body.removeChild(ta);
    }

    // ===== 导出译文 =====
    exportBtn.addEventListener('click', function() {
        const text = targetText.textContent.trim();
        if (!text || text === '译文将显示在这里' || text === '翻译失败') {
            showToast('没有可导出的译文');
            return;
        }
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'translation_' + Date.now() + '.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('译文已导出');
    });

    // ===== 翻译历史 =====
    function getHistory() {
        try {
            return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
        } catch (e) {
            return [];
        }
    }

    function saveHistory(history) {
        try {
            localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
        } catch (e) {}
    }

    function addToHistory(source, target, srcLang, tgtLang) {
        const history = getHistory();
        const item = {
            source: source.substring(0, 200),
            target: target.substring(0, 200),
            source_full: source,
            target_full: target,
            srcLang: srcLang,
            tgtLang: tgtLang,
            time: Date.now()
        };
        history.unshift(item);
        if (history.length > MAX_HISTORY) {
            history = history.slice(0, MAX_HISTORY);
        }
        saveHistory(history);
        renderHistory();
    }

    function renderHistory() {
        const history = getHistory();
        if (history.length === 0) {
            historyList.innerHTML = '<div class="history-empty">暂无翻译记录</div>';
            return;
        }

        const langNames = {
            auto: '自动', zh: '中', en: '英', ja: '日',
            ko: '韩', fr: '法', de: '德', es: '西',
            ru: '俄', pt: '葡', it: '意', ar: '阿'
        };

        historyList.innerHTML = history.map(function(item, idx) {
            const mins = Math.floor((Date.now() - item.time) / 60000);
            let timeStr;
            if (mins < 1) timeStr = '刚刚';
            else if (mins < 60) timeStr = mins + '分钟前';
            else if (mins < 1440) timeStr = Math.floor(mins / 60) + '小时前';
            else timeStr = Math.floor(mins / 1440) + '天前';

            const srcLabel = langNames[item.srcLang] || item.srcLang;
            const tgtLabel = langNames[item.tgtLang] || item.tgtLang;

            return '<div class="history-item" data-idx="' + idx + '">' +
                '<span class="history-lang">' + srcLabel + '→' + tgtLabel + '</span>' +
                '<div class="history-content">' +
                    '<div class="history-source">' + escapeHtml(item.source) + '</div>' +
                    '<div class="history-target">' + escapeHtml(item.target) + '</div>' +
                '</div>' +
                '<span class="history-time">' + timeStr + '</span>' +
            '</div>';
        }).join('');

        // 绑定点击事件
        var items = historyList.querySelectorAll('.history-item');
        for (var i = 0; i < items.length; i++) {
            items[i].addEventListener('click', function() {
                var idx = parseInt(this.dataset.idx);
                var h = getHistory()[idx];
                if (h) {
                    sourceText.value = h.source_full;
                    targetText.textContent = h.target_full;
                    if (h.srcLang !== 'auto') sourceLang.value = h.srcLang;
                    targetLang.value = h.tgtLang;
                    updateCharCount();
                    showToast('已加载历史记录');
                }
            });
        }
    }

    historyClear.addEventListener('click', function() {
        if (getHistory().length === 0) {
            showToast('暂无历史记录');
            return;
        }
        saveHistory([]);
        renderHistory();
        showToast('历史记录已清除');
    });

    // ===== 初始化 =====
    renderHistory();
    updateCharCount();

    // 从 localStorage 恢复设置
    try {
        const savedTarget = localStorage.getItem(TARGET_LANG_KEY);
        if (savedTarget) targetLang.value = savedTarget;
        const savedItMode = localStorage.getItem(IT_MODE_KEY);
        if (savedItMode !== null) itMode.checked = savedItMode === 'true';
    } catch (e) {}

    targetLang.addEventListener('change', function() {
        try { localStorage.setItem(TARGET_LANG_KEY, targetLang.value); } catch (e) {}
    });

    itMode.addEventListener('change', function() {
        try { localStorage.setItem(IT_MODE_KEY, itMode.checked); } catch (e) {}
    });

})();
