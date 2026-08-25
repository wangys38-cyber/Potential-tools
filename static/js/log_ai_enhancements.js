/**
 * 日志分析 AI 增强模块
 * 功能：异常模式自学习、根因推理链可视化、相似问题自动关联、修复方案知识库
 */

const LogAIEnhancements = (function() {
    'use strict';

    // ========== 工具函数 ==========
    function _getPrefix() {
        return window._USER_PREFIX || '';
    }

    function _storageKey(suffix) {
        return _getPrefix() + suffix;
    }

    function _loadJSON(key, fallback) {
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (e) {
            return fallback;
        }
    }

    function _saveJSON(key, data) {
        try {
            localStorage.setItem(key, JSON.stringify(data));
            return true;
        } catch (e) {
            console.warn('保存失败:', e);
            return false;
        }
    }

    function _uid() {
        return 'id_' + Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 6);
    }

    function _escapeHtml(s) {
        if (!s) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    function _showToast(msg, type) {
        if (window.showToast) {
            window.showToast(msg, type || 'success');
        } else if (window.ToolboxToast) {
            window.ToolboxToast.show(msg, type || 'success');
        } else {
            alert(msg);
        }
    }

    // ========== 1. 异常模式自学习 ==========
    const PatternLibrary = (function() {
        const STORAGE_KEY = 'log_anomaly_patterns';

        function getAll() {
            return _loadJSON(_storageKey(STORAGE_KEY), []);
        }

        function saveAll(patterns) {
            return _saveJSON(_storageKey(STORAGE_KEY), patterns);
        }

        function add(pattern) {
            const patterns = getAll();
            pattern.id = pattern.id || _uid();
            pattern.createdAt = pattern.createdAt || Date.now();
            patterns.push(pattern);
            saveAll(patterns);
            return pattern;
        }

        function update(id, updates) {
            const patterns = getAll();
            const idx = patterns.findIndex(p => p.id === id);
            if (idx === -1) return null;
            patterns[idx] = { ...patterns[idx], ...updates, updatedAt: Date.now() };
            saveAll(patterns);
            return patterns[idx];
        }

        function remove(id) {
            const patterns = getAll().filter(p => p.id !== id);
            saveAll(patterns);
        }

        /**
         * 匹配日志中的已知模式
         * @param {Array} logs - 日志数组 [{type, text, content, ...}]
         * @returns {Array} 匹配到的模式列表
         */
        function matchLogs(logs) {
            const patterns = getAll();
            if (patterns.length === 0 || !logs || logs.length === 0) return [];

            const logText = logs.map(l => (l.text || l.content || '').toLowerCase()).join(' ');
            const matches = [];

            patterns.forEach(p => {
                const keywords = (p.keywords || []).map(k => k.toLowerCase());
                const matchedKw = keywords.filter(kw => logText.includes(kw));
                if (matchedKw.length > 0) {
                    // 统计相关日志条数
                    const relatedLogs = logs.filter(l => {
                        const text = (l.text || l.content || '').toLowerCase();
                        return matchedKw.some(kw => text.includes(kw));
                    });
                    matches.push({
                        ...p,
                        matchedKeywords: matchedKw,
                        matchScore: matchedKw.length,
                        relatedLogCount: relatedLogs.length,
                        relatedLogs: relatedLogs.slice(0, 10)
                    });
                }
            });

            return matches.sort((a, b) => b.matchScore - a.matchScore);
        }

        function exportJSON() {
            return JSON.stringify(getAll(), null, 2);
        }

        function importJSON(jsonStr) {
            try {
                const data = JSON.parse(jsonStr);
                if (!Array.isArray(data)) throw new Error('格式错误：需要数组');
                const existing = getAll();
                const existingIds = new Set(existing.map(p => p.id));
                let imported = 0;
                data.forEach(p => {
                    if (!p.name) return;
                    if (p.id && existingIds.has(p.id)) {
                        p.id = _uid();
                    }
                    existing.push({
                        id: p.id || _uid(),
                        name: p.name,
                        keywords: p.keywords || [],
                        severity: p.severity || 'medium',
                        sample: p.sample || '',
                        rootCause: p.rootCause || '',
                        solution: p.solution || '',
                        createdAt: Date.now()
                    });
                    imported++;
                });
                saveAll(existing);
                return imported;
            } catch (e) {
                throw new Error('导入失败: ' + e.message);
            }
        }

        return {
            getAll, saveAll, add, update, remove,
            matchLogs, exportJSON, importJSON
        };
    })();

    // ========== 2. 根因推理链可视化 ==========
    const ReasoningChain = (function() {
        /**
         * 从 AI 返回数据中提取推理链
         * 支持格式：
         * 1. data.reasoningChain = { nodes: [...], edges: [...] }
         * 2. data.rootCauses 数组 → 自动构建简单链
         * 3. 纯文本 → 解析为节点
         */
        function extractChain(data, logs) {
            if (!data) return null;

            // 格式1：显式推理链
            if (data.reasoningChain && data.reasoningChain.nodes) {
                return _normalizeChain(data.reasoningChain);
            }

            // 格式2：从 rootCauses 构建
            if (data.rootCauses && data.rootCauses.length > 0) {
                return _buildFromRootCauses(data.rootCauses, logs);
            }

            // 格式3：纯文本
            if (data.rawResult || typeof data === 'string') {
                const text = data.rawResult || data;
                return _buildFromText(text, logs);
            }

            return null;
        }

        function _normalizeChain(chain) {
            const nodes = (chain.nodes || []).map((n, i) => ({
                id: n.id || ('node_' + i),
                type: n.type || 'intermediate',
                description: n.description || n.label || n.text || '',
                confidence: n.confidence || n.score || 0.5,
                relatedLogCount: n.relatedLogCount || n.logCount || 0,
                details: n.details || ''
            }));
            const edges = (chain.edges || []).map((e, i) => ({
                id: e.id || ('edge_' + i),
                source: e.source || e.from,
                target: e.target || e.to,
                label: e.label || e.relation || ''
            }));
            return { nodes, edges };
        }

        function _buildFromRootCauses(rootCauses, logs) {
            const nodes = [];
            const edges = [];

            // 起点：异常日志汇总
            const anomalyCount = logs ? logs.length : 0;
            nodes.push({
                id: 'start',
                type: 'anomaly',
                description: `检测到 ${anomalyCount} 条异常日志`,
                confidence: 1.0,
                relatedLogCount: anomalyCount,
                details: '日志分析入口'
            });

            rootCauses.forEach((rc, i) => {
                const nid = 'cause_' + i;
                nodes.push({
                    id: nid,
                    type: 'root_cause',
                    description: rc.substring(0, 200),
                    confidence: 0.7,
                    relatedLogCount: 0,
                    details: rc
                });
                edges.push({
                    id: 'e_start_' + i,
                    source: 'start',
                    target: nid,
                    label: '可能导致'
                });
            });

            return { nodes, edges };
        }

        function _buildFromText(text, logs) {
            if (!text) return null;
            const lines = text.split(/\n+/).filter(l => l.trim().length > 10).slice(0, 5);
            if (lines.length === 0) return null;

            const nodes = [{
                id: 'start',
                type: 'anomaly',
                description: `检测到 ${logs ? logs.length : 0} 条异常日志`,
                confidence: 1.0,
                relatedLogCount: logs ? logs.length : 0
            }];
            const edges = [];

            lines.forEach((line, i) => {
                const nid = 'step_' + i;
                nodes.push({
                    id: nid,
                    type: i === lines.length - 1 ? 'root_cause' : 'intermediate',
                    description: line.trim().substring(0, 200),
                    confidence: 0.6,
                    relatedLogCount: 0
                });
                edges.push({
                    id: 'e_' + i,
                    source: i === 0 ? 'start' : ('step_' + (i - 1)),
                    target: nid,
                    label: '→'
                });
            });

            return { nodes, edges };
        }

        /**
         * 渲染推理链为垂直时间线 HTML
         */
        function renderHTML(chain, onNodeClick) {
            if (!chain || !chain.nodes || chain.nodes.length === 0) {
                return '<div style="padding:12px;color:var(--ds-text-secondary);font-size:13px;">暂无推理链数据</div>';
            }

            const typeLabels = {
                anomaly: '异常日志',
                intermediate: '中间因素',
                possible_cause: '可能原因',
                root_cause: '最终根因'
            };
            const typeColors = {
                anomaly: '#007aff',
                intermediate: '#ff9500',
                possible_cause: '#ff9500',
                root_cause: '#ff3b30'
            };

            let html = '<div class="rc-chain" style="position:relative;padding-left:28px;">';
            html += '<div style="position:absolute;left:10px;top:8px;bottom:8px;width:2px;background:var(--ds-border-light);"></div>';

            chain.nodes.forEach((node, idx) => {
                const color = typeColors[node.type] || '#8e8e93';
                const label = typeLabels[node.type] || '节点';
                const confPct = Math.round((node.confidence || 0) * 100);
                const clickable = typeof onNodeClick === 'function';

                html += `
                    <div class="rc-chain-node" data-node-id="${_escapeHtml(node.id)}"
                         style="position:relative;margin-bottom:16px;cursor:${clickable ? 'pointer' : 'default'};"
                         ${clickable ? 'onclick="LogAIEnhancements._handleNodeClick(\'' + _escapeHtml(node.id) + '\')"' : ''}>
                        <div style="position:absolute;left:-24px;top:4px;width:14px;height:14px;border-radius:50%;background:${color};border:2px solid var(--ds-bg-elevated);box-shadow:0 0 0 2px ${color}33;"></div>
                        <div style="padding:12px 14px;background:var(--ds-bg-secondary);border-radius:10px;border:1px solid var(--ds-border-light);">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:4px;">
                                <span style="font-size:11px;font-weight:600;color:${color};text-transform:uppercase;letter-spacing:0.5px;">${label}</span>
                                <span style="font-size:10px;color:var(--ds-text-secondary);">置信度 ${confPct}%</span>
                            </div>
                            <div style="font-size:13px;color:var(--ds-text);line-height:1.6;margin-bottom:6px;">${_escapeHtml(node.description)}</div>
                            ${node.relatedLogCount > 0 ? `<div style="font-size:11px;color:var(--ds-text-secondary);">相关日志: ${node.relatedLogCount} 条</div>` : ''}
                        </div>
                    </div>
                `;
            });

            html += '</div>';

            // 节点详情弹窗
            html += `
                <div id="rcNodeDetailModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;align-items:center;justify-content:center;" onclick="if(event.target===this)this.style.display='none'">
                    <div style="background:var(--ds-bg-elevated);border-radius:14px;padding:24px;max-width:560px;width:90%;max-height:80vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.2);">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                            <h4 style="font-size:16px;font-weight:600;color:var(--ds-text);margin:0;">节点详情</h4>
                            <button onclick="document.getElementById('rcNodeDetailModal').style.display='none'" style="background:none;border:none;font-size:20px;color:var(--ds-text-secondary);cursor:pointer;line-height:1;">&times;</button>
                        </div>
                        <div id="rcNodeDetailContent"></div>
                    </div>
                </div>
            `;

            return html;
        }

        function _handleNodeClick(nodeId) {
            // 由外部设置回调
            if (typeof ReasoningChain._onNodeClick === 'function') {
                ReasoningChain._onNodeClick(nodeId);
            }
        }

        function showNodeDetail(node, relatedLogs) {
            const modal = document.getElementById('rcNodeDetailModal');
            const content = document.getElementById('rcNodeDetailContent');
            if (!modal || !content) return;

            let html = `
                <div style="margin-bottom:12px;">
                    <div style="font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">描述</div>
                    <div style="font-size:14px;color:var(--ds-text);line-height:1.6;">${_escapeHtml(node.description || '')}</div>
                </div>
                <div style="margin-bottom:12px;">
                    <div style="font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">置信度</div>
                    <div style="font-size:14px;color:var(--ds-text);">${Math.round((node.confidence || 0) * 100)}%</div>
                </div>
            `;

            if (node.details) {
                html += `
                    <div style="margin-bottom:12px;">
                        <div style="font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">详细信息</div>
                        <div style="font-size:13px;color:var(--ds-text);line-height:1.6;white-space:pre-wrap;">${_escapeHtml(node.details)}</div>
                    </div>
                `;
            }

            if (relatedLogs && relatedLogs.length > 0) {
                html += `
                    <div>
                        <div style="font-size:12px;color:var(--ds-text-secondary);margin-bottom:6px;">相关日志 (${relatedLogs.length})</div>
                        <div style="max-height:200px;overflow-y:auto;background:var(--ds-bg);border-radius:8px;padding:8px;">
                            ${relatedLogs.map(l => `<div style="font-size:11px;font-family:monospace;color:var(--ds-text);padding:4px 0;border-bottom:1px solid var(--ds-border-light);word-break:break-all;">${_escapeHtml((l.text || l.content || '').substring(0, 300))}</div>`).join('')}
                        </div>
                    </div>
                `;
            }

            content.innerHTML = html;
            modal.style.display = 'flex';
        }

        return {
            extractChain,
            renderHTML,
            showNodeDetail,
            _handleNodeClick,
            _onNodeClick: null
        };
    })();

    // ========== 3. 相似问题自动关联 ==========
    const SimilarIssues = (function() {
        const HISTORY_TOOL_ID = 'log-analyzer';

        /**
         * 从历史分析记录中查找相似问题
         * @param {Array} logs - 当前日志
         * @param {Object} stats - 当前统计
         * @returns {Array} 相似问题列表
         */
        function findSimilar(logs, stats) {
            const history = _loadJSON(_storageKey('history_' + HISTORY_TOOL_ID), []);
            if (history.length === 0 || !logs || logs.length === 0) return [];

            const currentKeywords = _extractKeywords(logs);
            const currentTypes = _extractErrorTypes(logs);
            const currentModules = _extractModules(logs);

            const results = [];

            history.forEach(record => {
                const recData = record.data || {};
                const recLogs = recData.logs || recData.allLogs || [];
                const recStats = recData.stats || {};

                // 关键词相似度
                const recKeywords = recData.keywords || (recLogs.length > 0 ? _extractKeywords(recLogs) : []);
                const kwOverlap = currentKeywords.filter(k => recKeywords.includes(k)).length;
                const kwSim = currentKeywords.length > 0 ? kwOverlap / Math.min(currentKeywords.length, 10) : 0;

                // 错误类型相似度
                const recTypes = recData.errorTypes || (recLogs.length > 0 ? _extractErrorTypes(recLogs) : {});
                let typeOverlap = 0;
                let typeTotal = 0;
                Object.keys(currentTypes).forEach(t => {
                    typeTotal++;
                    if (recTypes[t]) typeOverlap++;
                });
                const typeSim = typeTotal > 0 ? typeOverlap / typeTotal : 0;

                // 模块相似度
                const recModules = recData.modules || (recLogs.length > 0 ? _extractModules(recLogs) : []);
                const modOverlap = currentModules.filter(m => recModules.includes(m)).length;
                const modSim = currentModules.length > 0 ? modOverlap / currentModules.length : 0;

                // 综合相似度
                const similarity = Math.round((kwSim * 0.5 + typeSim * 0.3 + modSim * 0.2) * 100);

                if (similarity >= 15) {
                    results.push({
                        id: record.id || _uid(),
                        title: record.title || '历史分析记录',
                        timestamp: record.timestamp,
                        similarity: similarity,
                        rootCause: recData.rootCause || recData.aiRootCause || '',
                        solution: recData.solution || recData.recommendations || '',
                        stats: recStats,
                        data: recData,
                        matchedKeywords: currentKeywords.filter(k => recKeywords.includes(k)).slice(0, 5)
                    });
                }
            });

            return results.sort((a, b) => b.similarity - a.similarity).slice(0, 5);
        }

        function _extractKeywords(logs) {
            const keywords = new Set();
            const importantWords = ['malloc', 'memory', 'oom', 'crash', 'panic', 'watchdog', 'reset',
                'reboot', 'gps', 'ble', 'bluetooth', 'battery', 'power', 'i2c', 'spi', 'uart',
                'sensor', 'display', 'lcd', 'timeout', 'error', 'fail', 'fault', 'exception',
                'deadlock', 'null', 'overflow', 'leak', 'alloc', 'heap', 'stack', '中断', '死机',
                '内存', '重启', '功耗', '蓝牙', '定位', '传感器', '屏幕'];
            logs.forEach(l => {
                const text = (l.text || l.content || '').toLowerCase();
                importantWords.forEach(w => {
                    if (text.includes(w)) keywords.add(w);
                });
            });
            return Array.from(keywords);
        }

        function _extractErrorTypes(logs) {
            const types = {};
            logs.forEach(l => {
                const t = l.type || 'unknown';
                types[t] = (types[t] || 0) + 1;
            });
            return types;
        }

        function _extractModules(logs) {
            const modules = new Set();
            const modulePatterns = [
                /\b(gps|gnss)\b/i, /\b(ble|bluetooth|bt)\b/i, /\b(wifi|wlan)\b/i,
                /\b(lcd|display|screen)\b/i, /\b(i2c|spi|uart)\b/i, /\b(sensor|accel|gyro|hrm|spo2)\b/i,
                /\b(battery|pmic|power)\b/i, /\b(memory|heap|ram)\b/i, /\b(cpu|core|task|thread)\b/i,
                /\b(fs|file|storage|flash)\b/i, /\b(net|network|tcp|http)\b/i
            ];
            logs.forEach(l => {
                const text = l.text || l.content || '';
                modulePatterns.forEach(p => {
                    const m = text.match(p);
                    if (m) modules.add(m[1].toLowerCase());
                });
            });
            return Array.from(modules);
        }

        /**
         * 保存当前分析到历史记录
         */
        function saveToHistory(logs, stats, aiResult) {
            try {
                const key = _storageKey('history_' + HISTORY_TOOL_ID);
                const history = _loadJSON(key, []);
                const record = {
                    id: _uid(),
                    title: `日志分析 ${new Date().toLocaleString('zh-CN')}`,
                    timestamp: Date.now(),
                    data: {
                        stats: stats,
                        logCount: logs.length,
                        keywords: _extractKeywords(logs),
                        errorTypes: _extractErrorTypes(logs),
                        modules: _extractModules(logs),
                        rootCause: aiResult ? (aiResult.summary || (aiResult.rootCauses || []).join('; ')) : '',
                        solution: aiResult ? (aiResult.recommendations || []).join('; ') : '',
                        aiRootCause: aiResult
                    }
                };
                history.unshift(record);
                if (history.length > 20) history.length = 20;
                _saveJSON(key, history);
            } catch (e) {
                console.warn('保存历史失败:', e);
            }
        }

        /**
         * 渲染相似问题 HTML
         */
        function renderHTML(similarList, onView) {
            if (!similarList || similarList.length === 0) {
                return '<div style="padding:12px;color:var(--ds-text-secondary);font-size:13px;">暂无相似历史问题</div>';
            }

            return similarList.map((item, idx) => {
                const simColor = item.similarity >= 60 ? '#ff3b30' : item.similarity >= 35 ? '#ff9500' : '#34c759';
                const timeStr = item.timestamp ? new Date(item.timestamp).toLocaleString('zh-CN') : '';
                return `
                    <div style="padding:12px 14px;border-radius:10px;border:1px solid var(--ds-border-light);background:var(--ds-bg-elevated);margin-bottom:8px;cursor:pointer;"
                         onclick="LogAIEnhancements._viewSimilarIssue(${idx})">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:4px;">
                            <span style="font-weight:600;font-size:13px;color:var(--ds-text);">${_escapeHtml(item.title)}</span>
                            <span style="font-size:10px;padding:2px 8px;border-radius:10px;background:${simColor};color:#fff;font-weight:600;">相似度 ${item.similarity}%</span>
                        </div>
                        ${timeStr ? `<div style="font-size:11px;color:var(--ds-text-secondary);margin-bottom:6px;">分析时间: ${timeStr}</div>` : ''}
                        ${item.rootCause ? `<div style="font-size:12px;color:var(--ds-text);margin-bottom:4px;"><strong>根因：</strong>${_escapeHtml(String(item.rootCause).substring(0, 150))}</div>` : ''}
                        ${item.solution ? `<div style="font-size:12px;color:var(--ds-text-secondary);"><strong>方案：</strong>${_escapeHtml(String(item.solution).substring(0, 150))}</div>` : ''}
                        ${item.matchedKeywords && item.matchedKeywords.length > 0 ? `<div style="margin-top:6px;font-size:10px;color:var(--ds-text-secondary);">匹配关键词: ${item.matchedKeywords.map(k => _escapeHtml(k)).join(', ')}</div>` : ''}
                    </div>
                `;
            }).join('');
        }

        let _similarCache = [];
        function _viewSimilarIssue(idx) {
            const item = _similarCache[idx];
            if (!item) return;
            const modal = document.getElementById('similarIssueModal');
            const content = document.getElementById('similarIssueContent');
            if (!modal || !content) return;

            content.innerHTML = `
                <div style="margin-bottom:12px;">
                    <div style="font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">标题</div>
                    <div style="font-size:15px;font-weight:600;color:var(--ds-text);">${_escapeHtml(item.title)}</div>
                </div>
                <div style="margin-bottom:12px;">
                    <div style="font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">分析时间</div>
                    <div style="font-size:13px;color:var(--ds-text);">${item.timestamp ? new Date(item.timestamp).toLocaleString('zh-CN') : '未知'}</div>
                </div>
                <div style="margin-bottom:12px;">
                    <div style="font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">根因分析</div>
                    <div style="font-size:13px;color:var(--ds-text);line-height:1.6;white-space:pre-wrap;">${_escapeHtml(item.rootCause || '无')}</div>
                </div>
                <div>
                    <div style="font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">修复方案</div>
                    <div style="font-size:13px;color:var(--ds-text);line-height:1.6;white-space:pre-wrap;">${_escapeHtml(item.solution || '无')}</div>
                </div>
            `;
            modal.style.display = 'flex';
        }

        function setCache(list) {
            _similarCache = list;
        }

        return {
            findSimilar,
            saveToHistory,
            renderHTML,
            _viewSimilarIssue,
            setCache
        };
    })();

    // ========== 4. 修复方案知识库 ==========
    const FixLibrary = (function() {
        const STORAGE_KEY = 'log_fix_solutions';

        function getAll() {
            return _loadJSON(_storageKey(STORAGE_KEY), []);
        }

        function saveAll(solutions) {
            return _saveJSON(_storageKey(STORAGE_KEY), solutions);
        }

        function add(solution) {
            const solutions = getAll();
            solution.id = solution.id || _uid();
            solution.createdAt = solution.createdAt || Date.now();
            solutions.push(solution);
            saveAll(solutions);
            return solution;
        }

        function update(id, updates) {
            const solutions = getAll();
            const idx = solutions.findIndex(s => s.id === id);
            if (idx === -1) return null;
            solutions[idx] = { ...solutions[idx], ...updates, updatedAt: Date.now() };
            saveAll(solutions);
            return solutions[idx];
        }

        function remove(id) {
            const solutions = getAll().filter(s => s.id !== id);
            saveAll(solutions);
        }

        function search(query) {
            const solutions = getAll();
            if (!query) return solutions;
            const q = query.toLowerCase();
            return solutions.filter(s =>
                (s.problemType || '').toLowerCase().includes(q) ||
                (s.scenario || '').toLowerCase().includes(q) ||
                (s.steps || '').toLowerCase().includes(q) ||
                (s.keywords || []).some(k => k.toLowerCase().includes(q))
            );
        }

        /**
         * 根据日志和根因推荐修复方案
         */
        function recommend(logs, rootCauses) {
            const solutions = getAll();
            if (solutions.length === 0) return [];

            const logText = (logs || []).map(l => (l.text || l.content || '').toLowerCase()).join(' ');
            const causeText = (rootCauses || []).join(' ').toLowerCase();
            const fullText = logText + ' ' + causeText;

            const results = [];
            solutions.forEach(s => {
                const keywords = (s.keywords || []).map(k => k.toLowerCase());
                const matchedKw = keywords.filter(kw => fullText.includes(kw));
                // 也匹配问题类型
                if ((s.problemType || '').toLowerCase() && fullText.includes(s.problemType.toLowerCase())) {
                    matchedKw.push(s.problemType);
                }
                if (matchedKw.length > 0) {
                    results.push({
                        ...s,
                        matchedKeywords: [...new Set(matchedKw)],
                        matchScore: matchedKw.length
                    });
                }
            });

            return results.sort((a, b) => b.matchScore - a.matchScore).slice(0, 5);
        }

        function exportJSON() {
            return JSON.stringify(getAll(), null, 2);
        }

        function importJSON(jsonStr) {
            try {
                const data = JSON.parse(jsonStr);
                if (!Array.isArray(data)) throw new Error('格式错误：需要数组');
                const existing = getAll();
                let imported = 0;
                data.forEach(s => {
                    if (!s.problemType && !s.steps) return;
                    existing.push({
                        id: _uid(),
                        problemType: s.problemType || '',
                        scenario: s.scenario || '',
                        steps: s.steps || '',
                        notes: s.notes || '',
                        references: s.references || [],
                        keywords: s.keywords || [],
                        createdAt: Date.now()
                    });
                    imported++;
                });
                saveAll(existing);
                return imported;
            } catch (e) {
                throw new Error('导入失败: ' + e.message);
            }
        }

        /**
         * 渲染推荐修复方案 HTML
         */
        function renderRecommendHTML(recommendations) {
            if (!recommendations || recommendations.length === 0) {
                return '<div style="padding:12px;color:var(--ds-text-secondary);font-size:13px;">暂无匹配的修复方案</div>';
            }

            return recommendations.map((s, idx) => `
                <div style="padding:12px 14px;border-radius:10px;border:1px solid var(--ds-border-light);background:var(--ds-bg-elevated);margin-bottom:8px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:4px;">
                        <span style="font-weight:600;font-size:13px;color:var(--ds-text);">${_escapeHtml(s.problemType || '未命名方案')}</span>
                        <span style="font-size:10px;padding:2px 8px;border-radius:10px;background:#007aff;color:#fff;">匹配 ${s.matchScore}</span>
                    </div>
                    ${s.scenario ? `<div style="font-size:11px;color:var(--ds-text-secondary);margin-bottom:6px;">适用场景: ${_escapeHtml(s.scenario)}</div>` : ''}
                    <div style="font-size:12px;color:var(--ds-text);line-height:1.6;white-space:pre-wrap;margin-bottom:6px;">${_escapeHtml(s.steps || '')}</div>
                    ${s.notes ? `<div style="font-size:11px;color:#ff9500;margin-bottom:4px;">注意: ${_escapeHtml(s.notes)}</div>` : ''}
                    ${s.matchedKeywords && s.matchedKeywords.length > 0 ? `<div style="font-size:10px;color:var(--ds-text-secondary);">匹配关键词: ${s.matchedKeywords.map(k => _escapeHtml(k)).join(', ')}</div>` : ''}
                </div>
            `).join('');
        }

        return {
            getAll, saveAll, add, update, remove,
            search, recommend, exportJSON, importJSON,
            renderRecommendHTML
        };
    })();

    // ========== 管理面板（模态框） ==========
    const AdminPanel = (function() {
        let currentTab = 'patterns';
        let editingId = null;

        function open(tab) {
            currentTab = tab || 'patterns';
            editingId = null;
            _render();
            const modal = document.getElementById('logKbModal');
            if (modal) modal.style.display = 'flex';
        }

        function close() {
            const modal = document.getElementById('logKbModal');
            if (modal) modal.style.display = 'none';
        }

        function _render() {
            const body = document.getElementById('logKbBody');
            if (!body) return;

            const tabBtn = (id, label) =>
                `<button onclick="LogAIEnhancements.AdminPanel.switchTab('${id}')"
                    style="padding:8px 16px;border:none;background:${currentTab === id ? 'var(--ds-text)' : 'transparent'};color:${currentTab === id ? 'var(--ds-bg)' : 'var(--ds-text-secondary)'};border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;">${label}</button>`;

            let html = `
                <div style="display:flex;gap:6px;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--ds-border-light);">
                    ${tabBtn('patterns', '异常模式库')}
                    ${tabBtn('fixes', '修复方案库')}
                </div>
                <div id="logKbTabContent"></div>
            `;
            body.innerHTML = html;
            _renderTab();
        }

        function switchTab(tab) {
            currentTab = tab;
            editingId = null;
            _render();
        }

        function _renderTab() {
            const content = document.getElementById('logKbTabContent');
            if (!content) return;
            if (currentTab === 'patterns') {
                _renderPatterns(content);
            } else {
                _renderFixes(content);
            }
        }

        function _renderPatterns(container) {
            const patterns = PatternLibrary.getAll();
            let html = `
                <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
                    <button onclick="LogAIEnhancements.AdminPanel.newPattern()" style="padding:6px 14px;background:var(--ds-text);color:var(--ds-bg);border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;">+ 新增模式</button>
                    <button onclick="LogAIEnhancements.AdminPanel.exportPatterns()" style="padding:6px 14px;background:var(--ds-bg-secondary);color:var(--ds-text);border:1px solid var(--ds-border);border-radius:8px;cursor:pointer;font-size:13px;">导出</button>
                    <button onclick="LogAIEnhancements.AdminPanel.importPatterns()" style="padding:6px 14px;background:var(--ds-bg-secondary);color:var(--ds-text);border:1px solid var(--ds-border);border-radius:8px;cursor:pointer;font-size:13px;">导入</button>
                    <span style="margin-left:auto;font-size:12px;color:var(--ds-text-secondary);align-self:center;">共 ${patterns.length} 条</span>
                </div>
            `;

            if (patterns.length === 0) {
                html += '<div style="padding:30px;text-align:center;color:var(--ds-text-secondary);font-size:13px;">暂无异常模式，点击"新增模式"添加</div>';
            } else {
                html += '<div style="display:flex;flex-direction:column;gap:8px;max-height:400px;overflow-y:auto;">';
                patterns.forEach(p => {
                    const sevColor = p.severity === 'high' ? '#ff3b30' : p.severity === 'medium' ? '#ff9500' : '#34c759';
                    html += `
                        <div style="padding:12px;border-radius:10px;border:1px solid var(--ds-border-light);background:var(--ds-bg-secondary);">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                                <span style="font-weight:600;font-size:13px;">${_escapeHtml(p.name)}</span>
                                <span style="font-size:10px;padding:2px 8px;border-radius:10px;background:${sevColor};color:#fff;">${p.severity === 'high' ? '高' : p.severity === 'medium' ? '中' : '低'}</span>
                            </div>
                            ${p.keywords && p.keywords.length > 0 ? `<div style="font-size:11px;color:var(--ds-text-secondary);margin-bottom:4px;">关键词: ${p.keywords.map(k => _escapeHtml(k)).join(', ')}</div>` : ''}
                            ${p.rootCause ? `<div style="font-size:12px;color:var(--ds-text);margin-bottom:4px;">根因: ${_escapeHtml(String(p.rootCause).substring(0, 100))}</div>` : ''}
                            <div style="display:flex;gap:6px;margin-top:8px;">
                                <button onclick="LogAIEnhancements.AdminPanel.editPattern('${p.id}')" style="padding:3px 10px;font-size:11px;background:var(--ds-bg);border:1px solid var(--ds-border);border-radius:6px;cursor:pointer;color:var(--ds-text);">编辑</button>
                                <button onclick="LogAIEnhancements.AdminPanel.deletePattern('${p.id}')" style="padding:3px 10px;font-size:11px;background:rgba(255,59,48,0.1);border:1px solid rgba(255,59,48,0.3);border-radius:6px;cursor:pointer;color:#ff3b30;">删除</button>
                            </div>
                        </div>
                    `;
                });
                html += '</div>';
            }

            // 编辑表单
            html += `
                <div id="patternForm" style="display:none;margin-top:16px;padding:16px;border-radius:10px;border:1px solid var(--ds-border);background:var(--ds-bg);">
                    <h4 style="font-size:14px;margin-bottom:12px;" id="patternFormTitle">新增异常模式</h4>
                    <div style="margin-bottom:10px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">模式名称 *</label>
                        <input type="text" id="pf_name" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:13px;">
                    </div>
                    <div style="margin-bottom:10px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">关键词（逗号分隔）*</label>
                        <input type="text" id="pf_keywords" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:13px;" placeholder="malloc, memory, OOM">
                    </div>
                    <div style="margin-bottom:10px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">严重度</label>
                        <select id="pf_severity" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:13px;">
                            <option value="high">高</option>
                            <option value="medium" selected>中</option>
                            <option value="low">低</option>
                        </select>
                    </div>
                    <div style="margin-bottom:10px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">典型日志样例</label>
                        <textarea id="pf_sample" rows="2" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:12px;font-family:monospace;resize:vertical;"></textarea>
                    </div>
                    <div style="margin-bottom:10px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">根因</label>
                        <textarea id="pf_rootCause" rows="2" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:13px;resize:vertical;"></textarea>
                    </div>
                    <div style="margin-bottom:12px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">修复方案</label>
                        <textarea id="pf_solution" rows="3" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:13px;resize:vertical;"></textarea>
                    </div>
                    <div style="display:flex;gap:8px;">
                        <button onclick="LogAIEnhancements.AdminPanel.savePattern()" style="padding:8px 16px;background:var(--ds-text);color:var(--ds-bg);border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;">保存</button>
                        <button onclick="document.getElementById('patternForm').style.display='none'" style="padding:8px 16px;background:var(--ds-bg-secondary);border:1px solid var(--ds-border);border-radius:8px;cursor:pointer;font-size:13px;color:var(--ds-text);">取消</button>
                    </div>
                </div>
            `;

            container.innerHTML = html;
        }

        function newPattern() {
            editingId = null;
            document.getElementById('patternFormTitle').textContent = '新增异常模式';
            ['pf_name', 'pf_keywords', 'pf_sample', 'pf_rootCause', 'pf_solution'].forEach(id => {
                document.getElementById(id).value = '';
            });
            document.getElementById('pf_severity').value = 'medium';
            document.getElementById('patternForm').style.display = 'block';
        }

        function editPattern(id) {
            const p = PatternLibrary.getAll().find(x => x.id === id);
            if (!p) return;
            editingId = id;
            document.getElementById('patternFormTitle').textContent = '编辑异常模式';
            document.getElementById('pf_name').value = p.name || '';
            document.getElementById('pf_keywords').value = (p.keywords || []).join(', ');
            document.getElementById('pf_severity').value = p.severity || 'medium';
            document.getElementById('pf_sample').value = p.sample || '';
            document.getElementById('pf_rootCause').value = p.rootCause || '';
            document.getElementById('pf_solution').value = p.solution || '';
            document.getElementById('patternForm').style.display = 'block';
        }

        function savePattern() {
            const name = document.getElementById('pf_name').value.trim();
            const keywordsStr = document.getElementById('pf_keywords').value.trim();
            if (!name || !keywordsStr) {
                _showToast('请填写模式名称和关键词', 'warning');
                return;
            }
            const data = {
                name: name,
                keywords: keywordsStr.split(/[,，]/).map(k => k.trim()).filter(k => k),
                severity: document.getElementById('pf_severity').value,
                sample: document.getElementById('pf_sample').value.trim(),
                rootCause: document.getElementById('pf_rootCause').value.trim(),
                solution: document.getElementById('pf_solution').value.trim()
            };
            if (editingId) {
                PatternLibrary.update(editingId, data);
                _showToast('模式已更新', 'success');
            } else {
                PatternLibrary.add(data);
                _showToast('模式已添加', 'success');
            }
            editingId = null;
            _renderTab();
        }

        function deletePattern(id) {
            PatternLibrary.remove(id);
            _showToast('已删除', 'success');
            _renderTab();
        }

        function exportPatterns() {
            const data = PatternLibrary.exportJSON();
            const blob = new Blob([data], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'anomaly_patterns.json';
            a.click();
            URL.revokeObjectURL(url);
        }

        function importPatterns() {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.json';
            input.onchange = function(e) {
                const file = e.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = function(ev) {
                    try {
                        const count = PatternLibrary.importJSON(ev.target.result);
                        _showToast('成功导入 ' + count + ' 条模式', 'success');
                        _renderTab();
                    } catch (err) {
                        _showToast(err.message, 'error');
                    }
                };
                reader.readAsText(file);
            };
            input.click();
        }

        // ===== 修复方案管理 =====
        function _renderFixes(container) {
            const solutions = FixLibrary.getAll();
            let html = `
                <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
                    <button onclick="LogAIEnhancements.AdminPanel.newFix()" style="padding:6px 14px;background:var(--ds-text);color:var(--ds-bg);border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;">+ 新增方案</button>
                    <button onclick="LogAIEnhancements.AdminPanel.exportFixes()" style="padding:6px 14px;background:var(--ds-bg-secondary);color:var(--ds-text);border:1px solid var(--ds-border);border-radius:8px;cursor:pointer;font-size:13px;">导出</button>
                    <button onclick="LogAIEnhancements.AdminPanel.importFixes()" style="padding:6px 14px;background:var(--ds-bg-secondary);color:var(--ds-text);border:1px solid var(--ds-border);border-radius:8px;cursor:pointer;font-size:13px;">导入</button>
                    <input type="text" id="fixSearchInput" placeholder="搜索方案..." oninput="LogAIEnhancements.AdminPanel.searchFixes()" style="margin-left:auto;padding:6px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:12px;min-width:160px;">
                </div>
                <div id="fixListContainer"></div>
                <div id="fixForm" style="display:none;margin-top:16px;padding:16px;border-radius:10px;border:1px solid var(--ds-border);background:var(--ds-bg);">
                    <h4 style="font-size:14px;margin-bottom:12px;" id="fixFormTitle">新增修复方案</h4>
                    <div style="margin-bottom:10px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">问题类型 *</label>
                        <input type="text" id="ff_problemType" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:13px;" placeholder="内存分配失败">
                    </div>
                    <div style="margin-bottom:10px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">匹配关键词（逗号分隔）</label>
                        <input type="text" id="ff_keywords" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:13px;" placeholder="malloc, fail, OOM">
                    </div>
                    <div style="margin-bottom:10px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">适用场景</label>
                        <input type="text" id="ff_scenario" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:13px;">
                    </div>
                    <div style="margin-bottom:10px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">修复步骤 *</label>
                        <textarea id="ff_steps" rows="4" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:13px;resize:vertical;"></textarea>
                    </div>
                    <div style="margin-bottom:10px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">注意事项</label>
                        <textarea id="ff_notes" rows="2" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:13px;resize:vertical;"></textarea>
                    </div>
                    <div style="margin-bottom:12px;">
                        <label style="display:block;font-size:12px;color:var(--ds-text-secondary);margin-bottom:4px;">参考链接（每行一个）</label>
                        <textarea id="ff_references" rows="2" style="width:100%;padding:8px 12px;border:1px solid var(--ds-border);border-radius:8px;background:var(--ds-bg-elevated);color:var(--ds-text);font-size:12px;resize:vertical;"></textarea>
                    </div>
                    <div style="display:flex;gap:8px;">
                        <button onclick="LogAIEnhancements.AdminPanel.saveFix()" style="padding:8px 16px;background:var(--ds-text);color:var(--ds-bg);border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;">保存</button>
                        <button onclick="document.getElementById('fixForm').style.display='none'" style="padding:8px 16px;background:var(--ds-bg-secondary);border:1px solid var(--ds-border);border-radius:8px;cursor:pointer;font-size:13px;color:var(--ds-text);">取消</button>
                    </div>
                </div>
            `;
            container.innerHTML = html;
            searchFixes();
        }

        function searchFixes() {
            const query = document.getElementById('fixSearchInput') ? document.getElementById('fixSearchInput').value : '';
            const solutions = FixLibrary.search(query);
            const listContainer = document.getElementById('fixListContainer');
            if (!listContainer) return;

            if (solutions.length === 0) {
                listContainer.innerHTML = '<div style="padding:30px;text-align:center;color:var(--ds-text-secondary);font-size:13px;">暂无修复方案</div>';
                return;
            }

            listContainer.innerHTML = '<div style="display:flex;flex-direction:column;gap:8px;max-height:400px;overflow-y:auto;">' +
                solutions.map(s => `
                    <div style="padding:12px;border-radius:10px;border:1px solid var(--ds-border-light);background:var(--ds-bg-secondary);">
                        <div style="font-weight:600;font-size:13px;margin-bottom:4px;">${_escapeHtml(s.problemType || '未命名')}</div>
                        ${s.scenario ? `<div style="font-size:11px;color:var(--ds-text-secondary);margin-bottom:4px;">场景: ${_escapeHtml(s.scenario)}</div>` : ''}
                        <div style="font-size:12px;color:var(--ds-text);margin-bottom:6px;white-space:pre-wrap;">${_escapeHtml(String(s.steps || '').substring(0, 120))}</div>
                        <div style="display:flex;gap:6px;">
                            <button onclick="LogAIEnhancements.AdminPanel.editFix('${s.id}')" style="padding:3px 10px;font-size:11px;background:var(--ds-bg);border:1px solid var(--ds-border);border-radius:6px;cursor:pointer;color:var(--ds-text);">编辑</button>
                            <button onclick="LogAIEnhancements.AdminPanel.deleteFix('${s.id}')" style="padding:3px 10px;font-size:11px;background:rgba(255,59,48,0.1);border:1px solid rgba(255,59,48,0.3);border-radius:6px;cursor:pointer;color:#ff3b30;">删除</button>
                        </div>
                    </div>
                `).join('') + '</div>';
        }

        function newFix() {
            editingId = null;
            document.getElementById('fixFormTitle').textContent = '新增修复方案';
            ['ff_problemType', 'ff_keywords', 'ff_scenario', 'ff_steps', 'ff_notes', 'ff_references'].forEach(id => {
                document.getElementById(id).value = '';
            });
            document.getElementById('fixForm').style.display = 'block';
        }

        function editFix(id) {
            const s = FixLibrary.getAll().find(x => x.id === id);
            if (!s) return;
            editingId = id;
            document.getElementById('fixFormTitle').textContent = '编辑修复方案';
            document.getElementById('ff_problemType').value = s.problemType || '';
            document.getElementById('ff_keywords').value = (s.keywords || []).join(', ');
            document.getElementById('ff_scenario').value = s.scenario || '';
            document.getElementById('ff_steps').value = s.steps || '';
            document.getElementById('ff_notes').value = s.notes || '';
            document.getElementById('ff_references').value = (s.references || []).join('\n');
            document.getElementById('fixForm').style.display = 'block';
        }

        function saveFix() {
            const problemType = document.getElementById('ff_problemType').value.trim();
            const steps = document.getElementById('ff_steps').value.trim();
            if (!problemType || !steps) {
                _showToast('请填写问题类型和修复步骤', 'warning');
                return;
            }
            const data = {
                problemType: problemType,
                keywords: document.getElementById('ff_keywords').value.split(/[,，]/).map(k => k.trim()).filter(k => k),
                scenario: document.getElementById('ff_scenario').value.trim(),
                steps: steps,
                notes: document.getElementById('ff_notes').value.trim(),
                references: document.getElementById('ff_references').value.split('\n').map(r => r.trim()).filter(r => r)
            };
            if (editingId) {
                FixLibrary.update(editingId, data);
                _showToast('方案已更新', 'success');
            } else {
                FixLibrary.add(data);
                _showToast('方案已添加', 'success');
            }
            editingId = null;
            searchFixes();
            document.getElementById('fixForm').style.display = 'none';
        }

        function deleteFix(id) {
            FixLibrary.remove(id);
            _showToast('已删除', 'success');
            searchFixes();
        }

        function exportFixes() {
            const data = FixLibrary.exportJSON();
            const blob = new Blob([data], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'fix_solutions.json';
            a.click();
            URL.revokeObjectURL(url);
        }

        function importFixes() {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.json';
            input.onchange = function(e) {
                const file = e.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = function(ev) {
                    try {
                        const count = FixLibrary.importJSON(ev.target.result);
                        _showToast('成功导入 ' + count + ' 条方案', 'success');
                        searchFixes();
                    } catch (err) {
                        _showToast(err.message, 'error');
                    }
                };
                reader.readAsText(file);
            };
            input.click();
        }

        return {
            open, close, switchTab,
            newPattern, editPattern, savePattern, deletePattern,
            exportPatterns, importPatterns,
            newFix, editFix, saveFix, deleteFix,
            exportFixes, importFixes, searchFixes
        };
    })();

    // ========== 模态框 HTML 注入 ==========
    function ensureModals() {
        if (document.getElementById('logKbModal')) return;

        const modalHtml = `
            <div id="logKbModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9998;align-items:center;justify-content:center;" onclick="if(event.target===this)LogAIEnhancements.AdminPanel.close()">
                <div style="background:var(--ds-bg-elevated);border-radius:14px;padding:24px;max-width:680px;width:92%;max-height:85vh;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.2);">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                        <h3 style="font-size:17px;font-weight:600;color:var(--ds-text);margin:0;">知识库管理</h3>
                        <button onclick="LogAIEnhancements.AdminPanel.close()" style="background:none;border:none;font-size:22px;color:var(--ds-text-secondary);cursor:pointer;line-height:1;">&times;</button>
                    </div>
                    <div id="logKbBody" style="flex:1;overflow-y:auto;"></div>
                </div>
            </div>
            <div id="similarIssueModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;align-items:center;justify-content:center;" onclick="if(event.target===this)this.style.display='none'">
                <div style="background:var(--ds-bg-elevated);border-radius:14px;padding:24px;max-width:560px;width:90%;max-height:80vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.2);">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                        <h4 style="font-size:16px;font-weight:600;color:var(--ds-text);margin:0;">历史问题详情</h4>
                        <button onclick="document.getElementById('similarIssueModal').style.display='none'" style="background:none;border:none;font-size:20px;color:var(--ds-text-secondary);cursor:pointer;line-height:1;">&times;</button>
                    </div>
                    <div id="similarIssueContent"></div>
                </div>
            </div>
        `;
        const div = document.createElement('div');
        div.innerHTML = modalHtml;
        document.body.appendChild(div);
    }

    // ========== 公开 API ==========
    return {
        PatternLibrary,
        ReasoningChain,
        SimilarIssues,
        FixLibrary,
        AdminPanel,
        ensureModals,
        _handleNodeClick: ReasoningChain._handleNodeClick,
        _viewSimilarIssue: SimilarIssues._viewSimilarIssue
    };
})();

window.LogAIEnhancements = LogAIEnhancements;
