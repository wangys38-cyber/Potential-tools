/**
 * 研发知识图谱前端逻辑
 * 功能：图谱可视化、节点交互、数据导入、AI抽取、知识推理、多跳问答、知识导出
 */

const KnowledgeGraph = (function() {
    'use strict';

    // 状态
    let nodes = [];
    let relations = [];
    let nodeTypes = {};
    let relationTypes = {};
    let canvas, ctx;
    let scale = 1;
    let offsetX = 0, offsetY = 0;
    let isDragging = false;
    let dragStartX, dragStartY;
    let hoveredNode = null;
    let selectedNode = null;
    let animationId = null;
    let highlightedNodes = new Set();
    let highlightedRelations = new Set();

    // 节点位置（力导向布局）
    let nodePositions = {};
    let velocities = {};

    // 抽取结果缓存
    let extractResult = { nodes: [], relations: [] };

    /**
     * 初始化
     */
    function init() {
        canvas = document.getElementById('graphCanvas');
        ctx = canvas.getContext('2d');
        resizeCanvas();
        window.addEventListener('resize', resizeCanvas);

        canvas.addEventListener('mousedown', onMouseDown);
        canvas.addEventListener('mousemove', onMouseMove);
        canvas.addEventListener('mouseup', onMouseUp);
        canvas.addEventListener('mouseleave', onMouseLeave);
        canvas.addEventListener('wheel', onWheel, { passive: false });

        loadGraph();
        loadQAHistory();
    }

    function resizeCanvas() {
        const container = document.getElementById('graphContainer');
        canvas.width = container.clientWidth;
        canvas.height = container.clientHeight;
        if (nodes.length > 0) render();
    }

    async function loadGraph() {
        try {
            const resp = await fetch('/api/kg/graph');
            const data = await resp.json();
            nodes = data.nodes || [];
            relations = data.relations || [];
            nodeTypes = data.nodeTypes || {};
            relationTypes = data.relationTypes || {};

            initNodePositions();
            updateStats(data.stats);
            updateLegend();
            loadCoreNodes();
            populateNodeSelects();
            startForceLayout();
        } catch (e) {
            console.error('加载图谱失败:', e);
            showToast('加载图谱失败: ' + e.message, 'error');
        }
    }

    function initNodePositions() {
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const radius = Math.min(canvas.width, canvas.height) * 0.35;

        nodes.forEach((node, i) => {
            if (!nodePositions[node.id]) {
                const angle = (2 * Math.PI * i) / Math.max(nodes.length, 1);
                nodePositions[node.id] = {
                    x: centerX + radius * Math.cos(angle),
                    y: centerY + radius * Math.sin(angle)
                };
                velocities[node.id] = { x: 0, y: 0 };
            }
        });
    }

    function startForceLayout() {
        if (animationId) cancelAnimationFrame(animationId);
        let iterations = 0;
        const maxIterations = 300;

        function tick() {
            if (iterations >= maxIterations) { render(); return; }
            const forces = {};
            nodes.forEach(n => forces[n.id] = { x: 0, y: 0 });

            for (let i = 0; i < nodes.length; i++) {
                for (let j = i + 1; j < nodes.length; j++) {
                    const a = nodePositions[nodes[i].id];
                    const b = nodePositions[nodes[j].id];
                    if (!a || !b) continue;
                    const dx = b.x - a.x, dy = b.y - a.y;
                    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    const force = 2000 / (dist * dist);
                    const fx = (dx / dist) * force, fy = (dy / dist) * force;
                    forces[nodes[i].id].x -= fx; forces[nodes[i].id].y -= fy;
                    forces[nodes[j].id].x += fx; forces[nodes[j].id].y += fy;
                }
            }

            relations.forEach(rel => {
                const a = nodePositions[rel.source], b = nodePositions[rel.target];
                if (!a || !b) return;
                const dx = b.x - a.x, dy = b.y - a.y;
                const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                const force = (dist - 120) * 0.02;
                const fx = (dx / dist) * force, fy = (dy / dist) * force;
                forces[rel.source].x += fx; forces[rel.source].y += fy;
                forces[rel.target].x -= fx; forces[rel.target].y -= fy;
            });

            const centerX = canvas.width / 2, centerY = canvas.height / 2;
            nodes.forEach(n => {
                const pos = nodePositions[n.id];
                if (!pos) return;
                forces[n.id].x += (centerX - pos.x) * 0.01;
                forces[n.id].y += (centerY - pos.y) * 0.01;
            });

            const damping = 0.85;
            nodes.forEach(n => {
                if (!velocities[n.id]) velocities[n.id] = { x: 0, y: 0 };
                velocities[n.id].x = (velocities[n.id].x + forces[n.id].x) * damping;
                velocities[n.id].y = (velocities[n.id].y + forces[n.id].y) * damping;
                if (nodePositions[n.id]) {
                    nodePositions[n.id].x += velocities[n.id].x;
                    nodePositions[n.id].y += velocities[n.id].y;
                }
            });

            render();
            iterations++;
            animationId = requestAnimationFrame(tick);
        }
        tick();
    }

    function render() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.save();
        ctx.translate(offsetX, offsetY);
        ctx.scale(scale, scale);

        // 绘制关系
        relations.forEach(rel => {
            const source = nodePositions[rel.source], target = nodePositions[rel.target];
            if (!source || !target) return;
            const isHighlighted = highlightedRelations.has(rel.id);
            const relType = relationTypes[rel.type] || {};
            ctx.strokeStyle = isHighlighted ? '#ff9500' : (relType.color || '#8e8e93');
            ctx.lineWidth = isHighlighted ? 3 : 1.5;
            ctx.globalAlpha = isHighlighted ? 1 : 0.5;
            ctx.beginPath();
            ctx.moveTo(source.x, source.y);
            ctx.lineTo(target.x, target.y);
            ctx.stroke();
            ctx.globalAlpha = 1;
        });

        // 绘制节点
        nodes.forEach(node => {
            const pos = nodePositions[node.id];
            if (!pos) return;
            const nodeType = nodeTypes[node.type] || {};
            const radius = node.type === 'bug' ? 18 : node.type === 'module' ? 22 : 16;
            const isHovered = hoveredNode === node.id;
            const isHighlighted = highlightedNodes.has(node.id);
            const isSelected = selectedNode === node.id;

            if (isHovered || isSelected) {
                ctx.shadowColor = nodeType.color || '#007aff';
                ctx.shadowBlur = 15;
            }

            // 高亮环
            if (isHighlighted) {
                ctx.beginPath();
                ctx.arc(pos.x, pos.y, radius + 5, 0, 2 * Math.PI);
                ctx.strokeStyle = '#ff9500';
                ctx.lineWidth = 3;
                ctx.stroke();
            }

            ctx.fillStyle = nodeType.color || '#007aff';
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, radius, 0, 2 * Math.PI);
            ctx.fill();
            ctx.shadowBlur = 0;

            ctx.strokeStyle = isSelected ? '#1d1d1f' : '#fff';
            ctx.lineWidth = isSelected ? 3 : 2;
            ctx.stroke();

            ctx.fillStyle = '#fff';
            ctx.font = 'bold 10px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            const text = node.name.length > 8 ? node.name.substring(0, 8) + '...' : node.name;
            ctx.fillText(text, pos.x, pos.y);
        });

        ctx.restore();
    }

    // ==================== 鼠标交互 ====================

    function onMouseDown(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left - offsetX) / scale;
        const y = (e.clientY - rect.top - offsetY) / scale;
        const clicked = findNodeAt(x, y);
        if (clicked) {
            selectedNode = clicked.id;
            showNodeDetail(clicked, e.clientX - rect.left, e.clientY - rect.top);
            render();
        } else {
            isDragging = true;
            dragStartX = e.clientX - offsetX;
            dragStartY = e.clientY - offsetY;
            hideNodeDetail();
            selectedNode = null;
            render();
        }
    }

    function onMouseMove(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left - offsetX) / scale;
        const y = (e.clientY - rect.top - offsetY) / scale;
        if (isDragging) {
            offsetX = e.clientX - dragStartX;
            offsetY = e.clientY - dragStartY;
            render();
        } else {
            const hovered = findNodeAt(x, y);
            if (hovered !== hoveredNode) {
                hoveredNode = hovered;
                canvas.style.cursor = hovered ? 'pointer' : 'grab';
                render();
            }
        }
    }

    function onMouseUp() { isDragging = false; }
    function onMouseLeave() { isDragging = false; hoveredNode = null; render(); }

    function onWheel(e) {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        scale = Math.max(0.3, Math.min(3, scale * delta));
        render();
    }

    function findNodeAt(x, y) {
        for (let i = nodes.length - 1; i >= 0; i--) {
            const pos = nodePositions[nodes[i].id];
            if (!pos) continue;
            const dx = x - pos.x, dy = y - pos.y;
            const radius = nodes[i].type === 'module' ? 22 : 18;
            if (dx * dx + dy * dy <= radius * radius) return nodes[i];
        }
        return null;
    }

    function showNodeDetail(node, x, y) {
        const detail = document.getElementById('nodeDetail');
        const nodeType = nodeTypes[node.type] || {};
        detail.innerHTML = `
            <div class="node-detail-title">${escapeHtml(node.name)}</div>
            <div class="node-detail-type">${nodeType.label || node.type}</div>
            <div class="node-detail-desc">${escapeHtml(node.description || '暂无描述')}</div>
        `;
        detail.style.left = Math.min(x + 10, canvas.width - 260) + 'px';
        detail.style.top = Math.min(y + 10, canvas.height - 150) + 'px';
        detail.style.display = 'block';
    }

    function hideNodeDetail() { document.getElementById('nodeDetail').style.display = 'none'; }

    // ==================== 统计与图例 ====================

    function updateStats(stats) {
        document.getElementById('totalNodes').textContent = stats.totalNodes || 0;
        document.getElementById('totalRelations').textContent = stats.totalRelations || 0;
        document.getElementById('bugCount').textContent = (stats.nodesByType && stats.nodesByType.bug) || 0;
        document.getElementById('moduleCount').textContent = (stats.nodesByType && stats.nodesByType.module) || 0;
        document.getElementById('personCount').textContent = (stats.nodesByType && stats.nodesByType.person) || 0;
    }

    function updateLegend() {
        const legend = document.getElementById('graphLegend');
        legend.innerHTML = Object.entries(nodeTypes).map(([key, val]) => `
            <div class="legend-item">
                <span class="legend-dot" style="background:${val.color}"></span>
                <span>${val.label}</span>
            </div>
        `).join('');
    }

    function populateNodeSelects() {
        const options = nodes.map(n => `<option value="${n.id}">${escapeHtml(n.name)} (${nodeTypes[n.type]?.label || n.type})</option>`).join('');
        const selects = ['assocNodeSelect', 'pathStartSelect', 'pathEndSelect', 'impactNodeSelect'];
        selects.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = options;
        });
    }

    async function loadCoreNodes() {
        try {
            const resp = await fetch('/api/kg/stats');
            const data = await resp.json();
            const list = document.getElementById('coreNodesList');
            if (data.coreNodes && data.coreNodes.length > 0) {
                list.innerHTML = data.coreNodes.map(n => `
                    <div class="core-node-item">
                        <div>
                            <span class="core-node-name">${escapeHtml(n.name)}</span>
                            <span class="core-node-type"> ${n.type}</span>
                        </div>
                        <span class="core-node-degree">${n.degree}关联</span>
                    </div>
                `).join('');
            } else {
                list.innerHTML = '<div style="text-align:center;color:var(--ds-text-secondary);font-size:12px;">暂无数据</div>';
            }
        } catch (e) { console.error('加载核心节点失败:', e); }
    }

    // ==================== 智能问答（多跳推理） ====================

    async function askQuestion() {
        const input = document.getElementById('queryInput');
        const result = document.getElementById('queryResult');
        const trace = document.getElementById('reasoningTrace');
        const btn = document.getElementById('askBtn');
        const question = input.value.trim();

        if (!question) { showToast('请输入问题', 'warning'); return; }

        btn.disabled = true;
        btn.textContent = '思考中...';
        result.style.display = 'block';
        result.innerHTML = '<div class="loading">AI 正在多跳推理分析...</div>';
        trace.style.display = 'none';

        try {
            const resp = await fetch('/api/kg/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question })
            });
            const data = await resp.json();
            if (data.error) {
                result.innerHTML = `<div style="color:var(--ds-danger);">${escapeHtml(data.error)}</div>`;
            } else {
                result.innerHTML = escapeHtml(data.answer || '（无回答）');
                // 显示推理溯源
                if (data.reasoning) {
                    const r = data.reasoning;
                    let traceHtml = '';
                    if (r.matchedNodes && r.matchedNodes.length) {
                        traceHtml += `<div>匹配实体: ${r.matchedNodes.map(n => `[${n.type}]${n.name}`).join(', ')}</div>`;
                    }
                    if (r.reasoningSteps && r.reasoningSteps.length) {
                        traceHtml += `<div>推理步骤: ${r.reasoningSteps.join(' → ')}</div>`;
                    }
                    if (r.evidenceNodes && r.evidenceNodes.length) {
                        traceHtml += `<div>涉及节点(${r.evidenceNodes.length}): ${r.evidenceNodes.slice(0, 10).map(n => n.name).join(', ')}${r.evidenceNodes.length > 10 ? '...' : ''}</div>`;
                    }
                    if (traceHtml) {
                        document.getElementById('reasoningContent').innerHTML = traceHtml;
                        trace.style.display = 'block';
                    }
                }
                saveQAHistory(question);
            }
        } catch (e) {
            result.innerHTML = `<div style="color:var(--ds-danger);">请求失败: ${escapeHtml(e.message)}</div>`;
        } finally {
            btn.disabled = false;
            btn.textContent = '提问';
        }
    }

    function getHistoryKey() {
        const prefix = window._USER_PREFIX || 'default';
        return prefix + '_kg_qa_history';
    }

    function loadQAHistory() {
        try {
            const history = JSON.parse(localStorage.getItem(getHistoryKey()) || '[]');
            const list = document.getElementById('historyList');
            if (history.length === 0) {
                list.innerHTML = '<div style="font-size:11px;color:var(--ds-text-secondary);">暂无历史</div>';
                return;
            }
            list.innerHTML = history.slice(0, 5).map(q =>
                `<div class="qa-history-item" onclick="KnowledgeGraph.fillQuestion('${escapeHtml(q).replace(/'/g, "\\'")}')">${escapeHtml(q.length > 30 ? q.substring(0, 30) + '...' : q)}</div>`
            ).join('');
        } catch (e) { console.error('加载问答历史失败:', e); }
    }

    function saveQAHistory(question) {
        try {
            const key = getHistoryKey();
            let history = JSON.parse(localStorage.getItem(key) || '[]');
            history = history.filter(q => q !== question);
            history.unshift(question);
            history = history.slice(0, 20);
            localStorage.setItem(key, JSON.stringify(history));
            loadQAHistory();
        } catch (e) { console.error('保存问答历史失败:', e); }
    }

    function fillQuestion(q) {
        document.getElementById('queryInput').value = q;
    }

    // ==================== 知识推理（前端图算法） ====================

    function switchReasoningTab(tab) {
        document.querySelectorAll('.reasoning-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.reasoning-content').forEach(c => c.classList.remove('active'));
        event.target.classList.add('active');
        document.getElementById('tab-' + tab).classList.add('active');
    }

    function buildAdjacency() {
        const adj = {};
        nodes.forEach(n => adj[n.id] = new Set());
        relations.forEach(r => {
            if (adj[r.source]) adj[r.source].add(r.target);
            if (adj[r.target]) adj[r.target].add(r.source);
        });
        return adj;
    }

    function getNodeName(id) {
        const n = nodes.find(x => x.id === id);
        return n ? n.name : id;
    }

    function setHighlight(nodeIds, relIds) {
        highlightedNodes = new Set(nodeIds || []);
        highlightedRelations = new Set(relIds || []);
        const info = document.getElementById('highlightInfo');
        if (highlightedNodes.size > 0) {
            info.textContent = `高亮: ${highlightedNodes.size} 节点, ${highlightedRelations.size} 关系`;
            info.classList.add('active');
        }
        render();
    }

    function clearHighlight() {
        highlightedNodes.clear();
        highlightedRelations.clear();
        document.getElementById('highlightInfo').classList.remove('active');
        render();
    }

    // 关联推理
    function associationReasoning() {
        const nodeId = document.getElementById('assocNodeSelect').value;
        const depth = parseInt(document.getElementById('assocDepthSelect').value);
        if (!nodeId) { showToast('请选择节点', 'warning'); return; }

        const adj = buildAdjacency();
        const visited = new Set([nodeId]);
        const allRelIds = new Set();
        let current = new Set([nodeId]);
        const levels = [];

        for (let d = 0; d < depth; d++) {
            const next = new Set();
            current.forEach(nid => {
                (adj[nid] || new Set()).forEach(neighbor => {
                    if (!visited.has(neighbor)) {
                        visited.add(neighbor);
                        next.add(neighbor);
                    }
                });
            });
            levels.push({ depth: d + 1, nodes: Array.from(next) });
            current = next;
            if (current.size === 0) break;
        }

        // 收集涉及的关系
        relations.forEach(r => {
            if (visited.has(r.source) && visited.has(r.target)) {
                allRelIds.add(r.id);
            }
        });

        setHighlight(Array.from(visited), Array.from(allRelIds));

        const resultEl = document.getElementById('assocResult');
        resultEl.style.display = 'block';
        let html = `<div style="font-weight:600;margin-bottom:6px;">关联节点: ${visited.size - 1} 个</div>`;
        levels.forEach(lv => {
            if (lv.nodes.length > 0) {
                html += `<div style="margin-bottom:4px;"><strong>${lv.depth}跳:</strong> ${lv.nodes.map(id => getNodeName(id)).join(', ')}</div>`;
            }
        });
        resultEl.innerHTML = html;
    }

    // 路径分析（BFS找所有路径）
    function pathAnalysis() {
        const startId = document.getElementById('pathStartSelect').value;
        const endId = document.getElementById('pathEndSelect').value;
        if (!startId || !endId) { showToast('请选择起点和终点', 'warning'); return; }
        if (startId === endId) { showToast('起点和终点不能相同', 'warning'); return; }

        const adj = buildAdjacency();
        const paths = [];
        const queue = [[startId, [startId]]];
        const maxPaths = 10, maxDepth = 6;

        while (queue.length > 0 && paths.length < maxPaths) {
            const [current, path] = queue.shift();
            if (path.length > maxDepth) continue;
            (adj[current] || new Set()).forEach(neighbor => {
                if (path.includes(neighbor)) return;
                const newPath = [...path, neighbor];
                if (neighbor === endId) {
                    paths.push(newPath);
                } else {
                    queue.push([neighbor, newPath]);
                }
            });
        }

        const resultEl = document.getElementById('pathResult');
        resultEl.style.display = 'block';

        if (paths.length === 0) {
            resultEl.innerHTML = '<div>未找到连接路径</div>';
            clearHighlight();
            return;
        }

        // 高亮最短路径
        const shortest = paths[0];
        const hlNodes = new Set(shortest);
        const hlRels = new Set();
        for (let i = 0; i < shortest.length - 1; i++) {
            relations.forEach(r => {
                if ((r.source === shortest[i] && r.target === shortest[i + 1]) ||
                    (r.target === shortest[i] && r.source === shortest[i + 1])) {
                    hlRels.add(r.id);
                }
            });
        }
        setHighlight(Array.from(hlNodes), Array.from(hlRels));

        let html = `<div style="font-weight:600;margin-bottom:6px;">找到 ${paths.length} 条路径（高亮最短路径）</div>`;
        paths.forEach((p, i) => {
            html += `<div style="margin-bottom:4px;font-size:11px;">路径${i + 1} (${p.length - 1}跳): ${p.map(id => getNodeName(id)).join(' → ')}</div>`;
        });
        resultEl.innerHTML = html;
    }

    // 聚类分析（基于连通分量 + 模块度）
    function clusterAnalysis() {
        const adj = buildAdjacency();
        const visited = new Set();
        const clusters = [];

        nodes.forEach(node => {
            if (visited.has(node.id)) return;
            // BFS找连通分量
            const component = [];
            const queue = [node.id];
            visited.add(node.id);
            while (queue.length > 0) {
                const current = queue.shift();
                component.push(current);
                (adj[current] || new Set()).forEach(neighbor => {
                    if (!visited.has(neighbor)) {
                        visited.add(neighbor);
                        queue.push(neighbor);
                    }
                });
            }
            if (component.length > 1) {
                clusters.push(component);
            }
        });

        // 对大的连通分量做简单的社区检测（基于节点类型分组）
        const finalClusters = [];
        clusters.forEach(comp => {
            if (comp.length <= 5) {
                finalClusters.push(comp);
            } else {
                // 按节点类型分组
                const byType = {};
                comp.forEach(nid => {
                    const n = nodes.find(x => x.id === nid);
                    if (n) {
                        if (!byType[n.type]) byType[n.type] = [];
                        byType[n.type].push(nid);
                    }
                });
                Object.values(byType).forEach(group => {
                    if (group.length >= 2) finalClusters.push(group);
                });
            }
        });

        const resultEl = document.getElementById('clusterResult');
        resultEl.style.display = 'block';

        if (finalClusters.length === 0) {
            resultEl.innerHTML = '<div>未发现明显聚类</div>';
            clearHighlight();
            return;
        }

        // 高亮最大聚类
        const largest = finalClusters.reduce((a, b) => a.length > b.length ? a : b);
        setHighlight(largest, []);

        let html = `<div style="font-weight:600;margin-bottom:6px;">发现 ${finalClusters.length} 个聚类（高亮最大聚类）</div>`;
        finalClusters.forEach((c, i) => {
            const names = c.map(id => getNodeName(id));
            html += `<div class="cluster-item"><span class="cluster-label">聚类${i + 1} (${c.length}节点):</span> ${names.join(', ')}</div>`;
        });
        resultEl.innerHTML = html;
    }

    // 影响分析（从节点出发的有向传播）
    function impactAnalysis() {
        const nodeId = document.getElementById('impactNodeSelect').value;
        if (!nodeId) { showToast('请选择节点', 'warning'); return; }

        // 构建有向邻接表
        const directedAdj = {};
        nodes.forEach(n => directedAdj[n.id] = []);
        relations.forEach(r => {
            // 阻塞、导致、依赖关系表示影响方向
            if (['blocks', 'caused', 'depends', 'assigned'].includes(r.type)) {
                if (directedAdj[r.source]) directedAdj[r.source].push(r.target);
            } else {
                // 其他关系视为双向影响
                if (directedAdj[r.source]) directedAdj[r.source].push(r.target);
                if (directedAdj[r.target]) directedAdj[r.target].push(r.source);
            }
        });

        // BFS传播
        const visited = new Set([nodeId]);
        const queue = [nodeId];
        const impactLevels = [];
        let current = [nodeId];

        while (current.length > 0) {
            const next = [];
            current.forEach(nid => {
                (directedAdj[nid] || []).forEach(target => {
                    if (!visited.has(target)) {
                        visited.add(target);
                        next.push(target);
                    }
                });
            });
            if (next.length > 0) {
                impactLevels.push(next);
            }
            current = next;
            if (impactLevels.length >= 4) break;
        }

        // 收集关系
        const hlRels = new Set();
        relations.forEach(r => {
            if (visited.has(r.source) && visited.has(r.target)) hlRels.add(r.id);
        });

        setHighlight(Array.from(visited), Array.from(hlRels));

        const resultEl = document.getElementById('impactResult');
        resultEl.style.display = 'block';
        let html = `<div style="font-weight:600;margin-bottom:6px;">可能影响 ${visited.size - 1} 个节点</div>`;
        impactLevels.forEach((lv, i) => {
            html += `<div style="margin-bottom:4px;"><strong>${i + 1}级影响:</strong> ${lv.map(id => getNodeName(id)).join(', ')}</div>`;
        });
        if (impactLevels.length === 0) {
            html += '<div>该节点暂无下游影响</div>';
        }
        resultEl.innerHTML = html;
    }

    // ==================== AI知识抽取 ====================

    function openExtractModal(sourceType) {
        const modal = document.getElementById('extractModal');
        const body = document.getElementById('extractModalBody');
        const confirmBtn = document.getElementById('confirmExtractBtn');
        modal.classList.add('active');
        body.innerHTML = '<div class="loading">AI正在抽取实体和关系...</div>';
        confirmBtn.disabled = true;

        // 获取文本数据
        let text = '';
        const prefix = window._USER_PREFIX || '';

        if (sourceType === 'cr_analysis') {
            const crData = JSON.parse(localStorage.getItem(prefix + 'cr_analysis_result') ||
                                       localStorage.getItem(prefix + 'excel_analysis_last') || '{}');
            if (crData && crData.all_issues) {
                text = crData.all_issues.slice(0, 30).map(i =>
                    `问题: ${i.key || ''} | 标题: ${i.summary || i.title || ''} | 严重程度: ${i.severity || ''} | 状态: ${i.status || ''} | 模块: ${i.module || i.component || ''} | 负责人: ${i.assignee || i.developer || ''}`
                ).join('\n');
            }
        } else if (sourceType === 'log') {
            const logData = JSON.parse(localStorage.getItem(prefix + 'log_analysis_result') ||
                                       localStorage.getItem(prefix + 'log_ai_result') || '{}');
            if (logData) {
                text = JSON.stringify(logData).substring(0, 6000);
            }
        } else if (sourceType === 'meeting') {
            const meetingData = JSON.parse(localStorage.getItem(prefix + 'meeting_minutes_result') || '{}');
            if (meetingData) {
                text = JSON.stringify(meetingData).substring(0, 6000);
            }
        }

        if (!text || text.length < 10) {
            // 提供文本输入
            body.innerHTML = `
                <div style="margin-bottom:12px;">
                    <div style="font-size:13px;font-weight:600;margin-bottom:8px;">未找到缓存数据，请手动粘贴文本</div>
                    <textarea id="extractTextInput" style="width:100%;min-height:200px;padding:10px;border:1px solid var(--ds-border);border-radius:8px;font-size:12px;font-family:inherit;resize:vertical;" placeholder="粘贴需要抽取知识的文本..."></textarea>
                </div>
                <button class="import-btn" onclick="KnowledgeGraph.doExtract('${sourceType}')">开始抽取</button>
            `;
            return;
        }

        doExtractWithText(text, sourceType);
    }

    function doExtract(sourceType) {
        const text = document.getElementById('extractTextInput').value;
        if (!text || text.trim().length < 10) {
            showToast('请输入至少10个字符的文本', 'warning');
            return;
        }
        doExtractWithText(text, sourceType);
    }

    // 获取 CSRF Token
    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    async function doExtractWithText(text, sourceType) {
        const body = document.getElementById('extractModalBody');
        const confirmBtn = document.getElementById('confirmExtractBtn');
        body.innerHTML = '<div class="loading">AI正在抽取实体和关系...（可能需要1-3分钟）</div>';

        try {
            // 使用 AbortController 设置 200 秒超时
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 200000);

            const resp = await fetch('/api/kg/extract', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': getCsrfToken()
                },
                body: JSON.stringify({ text, source_type: sourceType }),
                signal: controller.signal
            });
            clearTimeout(timeoutId);

            const data = await resp.json();
            if (data.error) {
                body.innerHTML = `<div style="color:var(--ds-danger);">抽取失败: ${escapeHtml(data.error)}</div>`;
                return;
            }

            extractResult = { nodes: data.nodes || [], relations: data.relations || [] };
            renderExtractPreview();
            confirmBtn.disabled = false;
        } catch (e) {
            let errorMsg = e.message;
            if (e.name === 'AbortError') {
                errorMsg = '请求超时（200秒），AI 服务响应太慢。建议：1.更换更快的模型（如 glm-4-flash）2.减少抽取文本量 3.稍后重试';
            } else if (errorMsg === 'Failed to fetch') {
                errorMsg = '网络请求失败，可能原因：1.服务器无响应 2.网络连接中断 3.CSRF校验失败。建议刷新页面后重试，或检查服务器是否正常运行。';
            }
            body.innerHTML = `<div style="color:var(--ds-danger);">请求失败: ${escapeHtml(errorMsg)}</div>`;
        }
    }

    function renderExtractPreview() {
        const body = document.getElementById('extractModalBody');
        const typeColors = {};
        Object.entries(nodeTypes).forEach(([k, v]) => typeColors[k] = v.color);

        let html = `<div style="margin-bottom:12px;font-size:13px;font-weight:600;">抽取到 ${extractResult.nodes.length} 个节点, ${extractResult.relations.length} 个关系</div>`;

        html += '<div class="extract-preview-section"><div class="extract-preview-title">节点（取消勾选可排除）</div>';
        extractResult.nodes.forEach((n, i) => {
            const color = typeColors[n.type] || '#8e8e93';
            html += `
                <div class="extract-item">
                    <input type="checkbox" id="extract-node-${i}" checked data-index="${i}" class="extract-node-check">
                    <span class="extract-type-badge" style="background:${color}">${nodeTypes[n.type]?.label || n.type}</span>
                    <span class="extract-name">${escapeHtml(n.name)}</span>
                </div>`;
        });
        html += '</div>';

        html += '<div class="extract-preview-section"><div class="extract-preview-title">关系</div>';
        extractResult.relations.forEach((r, i) => {
            html += `
                <div class="extract-item">
                    <input type="checkbox" id="extract-rel-${i}" checked data-index="${i}" class="extract-rel-check">
                    <span class="extract-rel">${escapeHtml(r.source)} --[${relationTypes[r.type]?.label || r.type}]--> ${escapeHtml(r.target)}</span>
                </div>`;
        });
        html += '</div>';

        body.innerHTML = html;
    }

    async function confirmExtraction() {
        const nodeChecks = document.querySelectorAll('.extract-node-check:checked');
        const relChecks = document.querySelectorAll('.extract-rel-check:checked');

        const selectedNodes = Array.from(nodeChecks).map(c => extractResult.nodes[parseInt(c.dataset.index)]);
        const selectedRels = Array.from(relChecks).map(c => extractResult.relations[parseInt(c.dataset.index)]);

        if (selectedNodes.length === 0) {
            showToast('请至少选择一个节点', 'warning');
            return;
        }

        const confirmBtn = document.getElementById('confirmExtractBtn');
        confirmBtn.disabled = true;
        confirmBtn.textContent = '添加中...';

        try {
            const resp = await fetch('/api/kg/extract/confirm', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': getCsrfToken()
                },
                body: JSON.stringify({ nodes: selectedNodes, relations: selectedRels })
            });
            const data = await resp.json();
            if (data.error) {
                showToast('添加失败: ' + data.error, 'error');
            } else {
                showToast(`添加成功：${data.createdNodes} 节点，${data.createdRelations} 关系`, 'success');
                closeExtractModal();
                loadGraph();
            }
        } catch (e) {
            showToast('添加失败: ' + e.message, 'error');
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.textContent = '确认添加';
        }
    }

    function closeExtractModal() {
        document.getElementById('extractModal').classList.remove('active');
    }

    // ==================== 从CR分析导入 ====================

    async function importFromCRAnalysis() {
        const btn = document.getElementById('importBtn');
        btn.disabled = true;
        btn.textContent = '导入中...';

        try {
            const prefix = window._USER_PREFIX || '';
            const crData = JSON.parse(localStorage.getItem(prefix + 'cr_analysis_result') ||
                                       localStorage.getItem(prefix + 'excel_analysis_last') || '{}');

            if (!crData || !crData.all_issues || crData.all_issues.length === 0) {
                showToast('未找到 CR 分析数据，请先进行 CR 分析', 'warning');
                btn.disabled = false;
                btn.textContent = '从 CR 分析导入';
                return;
            }

            const issues = crData.all_issues.map(issue => ({
                key: issue.key || issue.issue_key || '',
                summary: issue.summary || issue.title || '',
                severity: issue.severity || issue.priority || '',
                status: issue.status || '',
                module: issue.module || issue.component || '',
                assignee: issue.assignee || issue.developer || ''
            })).filter(i => i.key || i.summary);

            const resp = await fetch('/api/kg/import/cr-analysis', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ issues })
            });
            const data = await resp.json();

            if (data.error) {
                showToast('导入失败: ' + data.error, 'error');
            } else {
                showToast(`导入成功：${data.createdNodes} 个节点，${data.createdRelations} 个关系`, 'success');
                loadGraph();
            }
        } catch (e) {
            showToast('导入失败: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = '从 CR 分析导入';
        }
    }

    // ==================== 知识导出 ====================

    async function exportGraph() {
        const fmt = document.getElementById('exportFormat').value;
        const scope = document.getElementById('exportScope').value;
        const body = { format: fmt, scope: scope };

        if (scope === 'subgraph') {
            if (!selectedNode) {
                showToast('请先在图谱中点击选择一个中心节点', 'warning');
                return;
            }
            body.centerNodeId = selectedNode;
            body.depth = 2;
        }

        try {
            const resp = await fetch('/api/kg/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            if (fmt === 'json') {
                const data = await resp.json();
                downloadFile(JSON.stringify(data, null, 2), 'knowledge_graph.json', 'application/json');
                showToast('JSON导出成功', 'success');
            } else if (fmt === 'graphml') {
                const text = await resp.text();
                downloadFile(text, 'knowledge_graph.graphml', 'application/xml');
                showToast('GraphML导出成功', 'success');
            } else if (fmt === 'csv') {
                const data = await resp.json();
                // 下载节点CSV
                downloadFile(data.nodes_csv, 'kg_nodes.csv', 'text/csv');
                // 下载关系CSV（延迟一下避免浏览器拦截）
                setTimeout(() => {
                    downloadFile(data.relations_csv, 'kg_relations.csv', 'text/csv');
                }, 500);
                showToast('CSV导出成功（节点表+关系表）', 'success');
            }
        } catch (e) {
            showToast('导出失败: ' + e.message, 'error');
        }
    }

    function exportPNG() {
        // 创建一个临时canvas，白色背景
        const tmpCanvas = document.createElement('canvas');
        tmpCanvas.width = canvas.width;
        tmpCanvas.height = canvas.height;
        const tmpCtx = tmpCanvas.getContext('2d');
        tmpCtx.fillStyle = '#ffffff';
        tmpCtx.fillRect(0, 0, tmpCanvas.width, tmpCanvas.height);
        tmpCtx.drawImage(canvas, 0, 0);

        const link = document.createElement('a');
        link.download = 'knowledge_graph.png';
        link.href = tmpCanvas.toDataURL('image/png');
        link.click();
        showToast('PNG导出成功', 'success');
    }

    function downloadFile(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }

    // ==================== 视图控制 ====================

    function refreshGraph() { loadGraph(); showToast('图谱已刷新', 'success'); }
    function zoomIn() { scale = Math.min(3, scale * 1.2); render(); }
    function zoomOut() { scale = Math.max(0.3, scale / 1.2); render(); }
    function resetView() { scale = 1; offsetX = 0; offsetY = 0; render(); }

    // ==================== 工具函数 ====================

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function showToast(msg, type) {
        if (typeof window.showToast === 'function') {
            window.showToast(msg, type);
        } else {
            alert(msg);
        }
    }

    // 公开 API
    return {
        init: init,
        askQuestion: askQuestion,
        fillQuestion: fillQuestion,
        importFromCRAnalysis: importFromCRAnalysis,
        openExtractModal: openExtractModal,
        doExtract: doExtract,
        confirmExtraction: confirmExtraction,
        closeExtractModal: closeExtractModal,
        switchReasoningTab: switchReasoningTab,
        associationReasoning: associationReasoning,
        pathAnalysis: pathAnalysis,
        clusterAnalysis: clusterAnalysis,
        impactAnalysis: impactAnalysis,
        clearHighlight: clearHighlight,
        exportGraph: exportGraph,
        exportPNG: exportPNG,
        refreshGraph: refreshGraph,
        zoomIn: zoomIn,
        zoomOut: zoomOut,
        resetView: resetView
    };
})();

// 页面加载完成后初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', KnowledgeGraph.init);
} else {
    KnowledgeGraph.init();
}