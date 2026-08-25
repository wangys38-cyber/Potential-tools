/**
 * 研发知识图谱前端逻辑
 * 功能：图谱可视化、节点交互、数据导入、智能问答
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
    let animationId = null;

    // 节点位置（力导向布局）
    let nodePositions = {};
    let velocities = {};

    /**
     * 初始化
     */
    function init() {
        canvas = document.getElementById('graphCanvas');
        ctx = canvas.getContext('2d');
        resizeCanvas();
        window.addEventListener('resize', resizeCanvas);

        // 鼠标事件
        canvas.addEventListener('mousedown', onMouseDown);
        canvas.addEventListener('mousemove', onMouseMove);
        canvas.addEventListener('mouseup', onMouseUp);
        canvas.addEventListener('mouseleave', onMouseLeave);
        canvas.addEventListener('wheel', onWheel, { passive: false });

        // 加载数据
        loadGraph();
    }

    /**
     * 调整画布大小
     */
    function resizeCanvas() {
        const container = document.getElementById('graphContainer');
        canvas.width = container.clientWidth;
        canvas.height = container.clientHeight;
        if (nodes.length > 0) render();
    }

    /**
     * 加载图谱数据
     */
    async function loadGraph() {
        try {
            const resp = await fetch('/api/kg/graph');
            const data = await resp.json();
            nodes = data.nodes || [];
            relations = data.relations || [];
            nodeTypes = data.nodeTypes || {};
            relationTypes = data.relationTypes || {};

            // 初始化节点位置
            initNodePositions();

            // 更新统计
            updateStats(data.stats);

            // 更新图例
            updateLegend();

            // 更新核心节点
            loadCoreNodes();

            // 开始力导向布局动画
            startForceLayout();
        } catch (e) {
            console.error('加载图谱失败:', e);
            showToast('加载图谱失败: ' + e.message, 'error');
        }
    }

    /**
     * 初始化节点位置（圆形布局）
     */
    function initNodePositions() {
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const radius = Math.min(canvas.width, canvas.height) * 0.35;

        nodes.forEach((node, i) => {
            const angle = (2 * Math.PI * i) / nodes.length;
            nodePositions[node.id] = {
                x: centerX + radius * Math.cos(angle),
                y: centerY + radius * Math.sin(angle)
            };
            velocities[node.id] = { x: 0, y: 0 };
        });
    }

    /**
     * 力导向布局
     */
    function startForceLayout() {
        if (animationId) cancelAnimationFrame(animationId);

        let iterations = 0;
        const maxIterations = 300;

        function tick() {
            if (iterations >= maxIterations) {
                render();
                return;
            }

            // 计算力
            const forces = {};
            nodes.forEach(n => forces[n.id] = { x: 0, y: 0 });

            // 斥力（节点之间）
            for (let i = 0; i < nodes.length; i++) {
                for (let j = i + 1; j < nodes.length; j++) {
                    const a = nodePositions[nodes[i].id];
                    const b = nodePositions[nodes[j].id];
                    const dx = b.x - a.x;
                    const dy = b.y - a.y;
                    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    const force = 2000 / (dist * dist);
                    const fx = (dx / dist) * force;
                    const fy = (dy / dist) * force;
                    forces[nodes[i].id].x -= fx;
                    forces[nodes[i].id].y -= fy;
                    forces[nodes[j].id].x += fx;
                    forces[nodes[j].id].y += fy;
                }
            }

            // 引力（关系之间）
            relations.forEach(rel => {
                const a = nodePositions[rel.source];
                const b = nodePositions[rel.target];
                if (!a || !b) return;
                const dx = b.x - a.x;
                const dy = b.y - a.y;
                const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                const force = (dist - 120) * 0.02;
                const fx = (dx / dist) * force;
                const fy = (dy / dist) * force;
                forces[rel.source].x += fx;
                forces[rel.source].y += fy;
                forces[rel.target].x -= fx;
                forces[rel.target].y -= fy;
            });

            // 中心引力
            const centerX = canvas.width / 2;
            const centerY = canvas.height / 2;
            nodes.forEach(n => {
                const pos = nodePositions[n.id];
                forces[n.id].x += (centerX - pos.x) * 0.01;
                forces[n.id].y += (centerY - pos.y) * 0.01;
            });

            // 更新位置
            const damping = 0.85;
            nodes.forEach(n => {
                velocities[n.id].x = (velocities[n.id].x + forces[n.id].x) * damping;
                velocities[n.id].y = (velocities[n.id].y + forces[n.id].y) * damping;
                nodePositions[n.id].x += velocities[n.id].x;
                nodePositions[n.id].y += velocities[n.id].y;
            });

            render();
            iterations++;
            animationId = requestAnimationFrame(tick);
        }

        tick();
    }

    /**
     * 渲染图谱
     */
    function render() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.save();
        ctx.translate(offsetX, offsetY);
        ctx.scale(scale, scale);

        // 绘制关系
        relations.forEach(rel => {
            const source = nodePositions[rel.source];
            const target = nodePositions[rel.target];
            if (!source || !target) return;

            const relType = relationTypes[rel.type] || {};
            ctx.strokeStyle = relType.color || '#8e8e93';
            ctx.lineWidth = 1.5;
            ctx.globalAlpha = 0.5;
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

            // 节点阴影
            if (isHovered) {
                ctx.shadowColor = nodeType.color || '#007aff';
                ctx.shadowBlur = 15;
            }

            // 节点圆
            ctx.fillStyle = nodeType.color || '#007aff';
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, radius, 0, 2 * Math.PI);
            ctx.fill();

            ctx.shadowBlur = 0;

            // 节点边框
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.stroke();

            // 节点文字
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 10px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            const text = node.name.length > 8 ? node.name.substring(0, 8) + '...' : node.name;
            ctx.fillText(text, pos.x, pos.y);
        });

        ctx.restore();
    }

    /**
     * 鼠标事件
     */
    function onMouseDown(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left - offsetX) / scale;
        const y = (e.clientY - rect.top - offsetY) / scale;

        // 检查是否点击节点
        const clicked = findNodeAt(x, y);
        if (clicked) {
            showNodeDetail(clicked, e.clientX - rect.left, e.clientY - rect.top);
        } else {
            isDragging = true;
            dragStartX = e.clientX - offsetX;
            dragStartY = e.clientY - offsetY;
            hideNodeDetail();
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
            // 检查悬停节点
            const hovered = findNodeAt(x, y);
            if (hovered !== hoveredNode) {
                hoveredNode = hovered;
                canvas.style.cursor = hovered ? 'pointer' : 'grab';
                render();
            }
        }
    }

    function onMouseUp() {
        isDragging = false;
    }

    function onMouseLeave() {
        isDragging = false;
        hoveredNode = null;
        render();
    }

    function onWheel(e) {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newScale = Math.max(0.3, Math.min(3, scale * delta));
        scale = newScale;
        render();
    }

    /**
     * 查找指定位置的节点
     */
    function findNodeAt(x, y) {
        for (let i = nodes.length - 1; i >= 0; i--) {
            const pos = nodePositions[nodes[i].id];
            if (!pos) continue;
            const dx = x - pos.x;
            const dy = y - pos.y;
            const radius = nodes[i].type === 'module' ? 22 : 18;
            if (dx * dx + dy * dy <= radius * radius) {
                return nodes[i];
            }
        }
        return null;
    }

    /**
     * 显示节点详情
     */
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

    function hideNodeDetail() {
        document.getElementById('nodeDetail').style.display = 'none';
    }

    /**
     * 更新统计
     */
    function updateStats(stats) {
        document.getElementById('totalNodes').textContent = stats.totalNodes || 0;
        document.getElementById('totalRelations').textContent = stats.totalRelations || 0;
        document.getElementById('bugCount').textContent = (stats.nodesByType && stats.nodesByType.bug) || 0;
        document.getElementById('moduleCount').textContent = (stats.nodesByType && stats.nodesByType.module) || 0;
        document.getElementById('personCount').textContent = (stats.nodesByType && stats.nodesByType.person) || 0;
    }

    /**
     * 更新图例
     */
    function updateLegend() {
        const legend = document.getElementById('graphLegend');
        legend.innerHTML = Object.entries(nodeTypes).map(([key, val]) => `
            <div class="legend-item">
                <span class="legend-dot" style="background:${val.color}"></span>
                <span>${val.label}</span>
            </div>
        `).join('');
    }

    /**
     * 加载核心节点
     */
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
        } catch (e) {
            console.error('加载核心节点失败:', e);
        }
    }

    /**
     * 智能问答
     */
    async function askQuestion() {
        const input = document.getElementById('queryInput');
        const result = document.getElementById('queryResult');
        const btn = document.getElementById('askBtn');
        const question = input.value.trim();

        if (!question) {
            showToast('请输入问题', 'warning');
            return;
        }

        btn.disabled = true;
        btn.textContent = '思考中...';
        result.style.display = 'block';
        result.innerHTML = '<div class="loading">AI 正在分析图谱数据...</div>';

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
            }
        } catch (e) {
            result.innerHTML = `<div style="color:var(--ds-danger);">请求失败: ${escapeHtml(e.message)}</div>`;
        } finally {
            btn.disabled = false;
            btn.textContent = '提问';
        }
    }

    /**
     * 从 CR 分析导入数据
     */
    async function importFromCRAnalysis() {
        const btn = document.getElementById('importBtn');
        btn.disabled = true;
        btn.textContent = '导入中...';

        try {
            // 从 localStorage 获取最近的 CR 分析结果
            const prefix = window._USER_PREFIX || '';
            const crData = JSON.parse(localStorage.getItem(prefix + 'cr_analysis_result') ||
                                       localStorage.getItem(prefix + 'excel_analysis_last') || '{}');

            if (!crData || !crData.all_issues || crData.all_issues.length === 0) {
                showToast('未找到 CR 分析数据，请先进行 CR 分析', 'warning');
                btn.disabled = false;
                btn.textContent = '从 CR 分析导入';
                return;
            }

            // 转换为导入格式
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

    /**
     * 视图控制
     */
    function refreshGraph() {
        loadGraph();
        showToast('图谱已刷新', 'success');
    }

    function zoomIn() {
        scale = Math.min(3, scale * 1.2);
        render();
    }

    function zoomOut() {
        scale = Math.max(0.3, scale / 1.2);
        render();
    }

    function resetView() {
        scale = 1;
        offsetX = 0;
        offsetY = 0;
        render();
    }

    /**
     * 工具函数
     */
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
        importFromCRAnalysis: importFromCRAnalysis,
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

// 全局函数（供 HTML 调用）
window.askQuestion = KnowledgeGraph.askQuestion;
window.importFromCRAnalysis = KnowledgeGraph.importFromCRAnalysis;
window.refreshGraph = KnowledgeGraph.refreshGraph;
window.zoomIn = KnowledgeGraph.zoomIn;
window.zoomOut = KnowledgeGraph.zoomOut;
window.resetView = KnowledgeGraph.resetView;
