/**
 * 项目计划增强模块
 * 功能：依赖关系、资源分配、里程碑管理、基线对比
 */

(function() {
    'use strict';

    // ============ 工具函数 ============

    function getCurrentPlan() {
        return window.currentPlan || [];
    }

    function setCurrentPlan(plan) {
        window.currentPlan = plan;
    }

    function parseDate(dateStr) {
        if (!dateStr) return null;
        const d = new Date(dateStr);
        return isNaN(d.getTime()) ? null : d;
    }

    function getStorageKey(suffix) {
        const prefix = (typeof window._USER_PREFIX !== 'undefined' ? window._USER_PREFIX : '');
        return prefix + suffix;
    }

    // ============ 功能1：依赖关系管理 ============

    function initDependencyManagement() {
        const container = document.getElementById('dependencySection');
        if (!container) return;

        container.innerHTML = `
            <div style="padding:20px;background:var(--bg-card);border-radius:var(--radius-lg);border:1px solid var(--border);margin-bottom:20px;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--text-primary)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>
                    <h3 style="margin:0;font-size:16px;font-weight:600;color:var(--text-primary);">依赖关系与关键路径</h3>
                    <button class="action-btn" onclick="PlanEnhancement.analyzeCriticalPath()" style="margin-left:auto;padding:6px 14px;font-size:12px;">分析关键路径</button>
                </div>
                <div style="margin-bottom:12px;">
                    <label style="font-size:13px;font-weight:500;color:var(--text-secondary);display:block;margin-bottom:6px;">设置节点依赖（选择当前节点依赖的前置节点，多个用逗号分隔）</label>
                    <div id="dependencyEditor" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px;"></div>
                </div>
                <div id="criticalPathResult" style="font-size:13px;color:var(--text-secondary);">点击"分析关键路径"按钮，基于依赖关系计算项目关键路径</div>
            </div>
        `;

        renderDependencyEditor();
    }

    function renderDependencyEditor() {
        const plan = getCurrentPlan();
        const editor = document.getElementById('dependencyEditor');
        if (!editor) return;

        editor.innerHTML = plan.map((item, idx) => `
            <div style="padding:10px 12px;background:var(--bg-secondary);border-radius:var(--radius-md);border:1px solid var(--border);">
                <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:4px;">${item.index}. ${item.name}</div>
                <input type="text" placeholder="依赖节点序号，如：1,2" value="${(item.dependencies || []).join(',')}"
                       style="width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-card);color:var(--text-primary);"
                       onchange="PlanEnhancement.setDependency(${idx}, this.value)">
            </div>
        `).join('');
    }

    function setDependency(index, value) {
        const plan = getCurrentPlan();
        if (!plan[index]) return;
        const deps = value.split(/[,，]/).map(s => parseInt(s.trim())).filter(n => !isNaN(n) && n > 0 && n <= plan.length && n !== index + 1);
        plan[index].dependencies = deps;
        setCurrentPlan(plan);
    }

    function analyzeCriticalPath() {
        const plan = getCurrentPlan();
        if (plan.length === 0) {
            showToast('请先生成计划', 'warning');
            return;
        }

        // 计算每个节点的最早开始时间和最晚开始时间
        const nodes = plan.map((item, idx) => ({
            index: idx,
            name: item.name,
            duration: (item.duration || 1) * 7, // 转换为天数
            dependencies: (item.dependencies || []).map(d => d - 1),
            earlyStart: 0,
            earlyFinish: 0,
            lateStart: Infinity,
            lateFinish: Infinity,
            isCritical: false
        }));

        // 正向计算最早开始/完成时间
        const sorted = topologicalSort(nodes);
        if (!sorted) {
            document.getElementById('criticalPathResult').innerHTML =
                '<div style="padding:12px;background:rgba(255,59,48,0.1);border-radius:var(--radius-md);color:var(--error);">依赖关系存在循环，无法计算关键路径</div>';
            return;
        }

        sorted.forEach(idx => {
            const node = nodes[idx];
            const maxDepFinish = node.dependencies.length > 0
                ? Math.max(...node.dependencies.map(d => nodes[d].earlyFinish))
                : 0;
            node.earlyStart = maxDepFinish;
            node.earlyFinish = maxDepFinish + node.duration;
        });

        // 反向计算最晚开始/完成时间
        const maxFinish = Math.max(...nodes.map(n => n.earlyFinish));
        [...sorted].reverse().forEach(idx => {
            const node = nodes[idx];
            const successors = nodes.filter(n => n.dependencies.includes(idx));
            const minSuccStart = successors.length > 0
                ? Math.min(...successors.map(s => s.lateStart))
                : maxFinish;
            node.lateFinish = minSuccStart;
            node.lateStart = minSuccStart - node.duration;
        });

        // 标记关键路径
        nodes.forEach(n => {
            n.isCritical = Math.abs(n.earlyStart - n.lateStart) < 0.1;
        });

        const criticalNodes = nodes.filter(n => n.isCritical);
        const totalDuration = Math.ceil(maxFinish / 7);

        document.getElementById('criticalPathResult').innerHTML = `
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">
                <div style="text-align:center;padding:12px;background:var(--bg-secondary);border-radius:var(--radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--text-primary);">${criticalNodes.length}</div>
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">关键节点数</div>
                </div>
                <div style="text-align:center;padding:12px;background:var(--bg-secondary);border-radius:var(--radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--text-primary);">${totalDuration}</div>
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">总工期（周）</div>
                </div>
                <div style="text-align:center;padding:12px;background:var(--bg-secondary);border-radius:var(--radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--error);">${criticalNodes.filter(n => n.dependencies.length === 0).length > 0 ? '有' : '无'}</div>
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">并行任务</div>
                </div>
            </div>
            <div style="font-size:13px;line-height:1.8;">
                <div style="font-weight:600;color:var(--text-primary);margin-bottom:6px;">关键路径：</div>
                <div style="padding:10px 14px;background:rgba(255,59,48,0.08);border-left:3px solid var(--error);border-radius:0 var(--radius-md) var(--radius-md) 0;">
                    ${criticalNodes.map(n => `<span style="display:inline-block;margin:2px 4px;padding:2px 8px;background:var(--bg-card);border-radius:var(--radius-sm);font-size:12px;">${n.index + 1}. ${n.name}</span>`).join(' → ')}
                </div>
                <div style="margin-top:10px;color:var(--text-secondary);font-size:12px;">关键路径上的节点延期将直接影响项目总工期，需重点关注</div>
            </div>
        `;

        showToast('关键路径分析完成', 'success');
    }

    function topologicalSort(nodes) {
        const inDegree = nodes.map(n => n.dependencies.length);
        const queue = [];
        const result = [];
        inDegree.forEach((d, i) => { if (d === 0) queue.push(i); });
        while (queue.length > 0) {
            const idx = queue.shift();
            result.push(idx);
            nodes.forEach((n, i) => {
                if (n.dependencies.includes(idx)) {
                    inDegree[i]--;
                    if (inDegree[i] === 0) queue.push(i);
                }
            });
        }
        return result.length === nodes.length ? result : null;
    }

    // ============ 功能2：资源分配 ============

    function initResourceAllocation() {
        const container = document.getElementById('resourceSection');
        if (!container) return;

        container.innerHTML = `
            <div style="padding:20px;background:var(--bg-card);border-radius:var(--radius-lg);border:1px solid var(--border);margin-bottom:20px;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--text-primary)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                    <h3 style="margin:0;font-size:16px;font-weight:600;color:var(--text-primary);">资源分配与负载</h3>
                    <button class="action-btn" onclick="PlanEnhancement.analyzeResourceLoad()" style="margin-left:auto;padding:6px 14px;font-size:12px;">分析负载</button>
                </div>
                <div style="margin-bottom:12px;">
                    <label style="font-size:13px;font-weight:500;color:var(--text-secondary);display:block;margin-bottom:6px;">为每个节点分配负责人</label>
                    <div id="resourceEditor" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px;"></div>
                </div>
                <div id="resourceLoadResult" style="font-size:13px;color:var(--text-secondary);">点击"分析负载"按钮，查看研发人员工作量分布</div>
            </div>
        `;

        renderResourceEditor();
    }

    function renderResourceEditor() {
        const plan = getCurrentPlan();
        const editor = document.getElementById('resourceEditor');
        if (!editor) return;

        editor.innerHTML = plan.map((item, idx) => `
            <div style="padding:10px 12px;background:var(--bg-secondary);border-radius:var(--radius-md);border:1px solid var(--border);">
                <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:4px;">${item.index}. ${item.name}</div>
                <input type="text" placeholder="负责人姓名" value="${item.assignee || ''}"
                       style="width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-card);color:var(--text-primary);"
                       onchange="PlanEnhancement.setAssignee(${idx}, this.value)">
            </div>
        `).join('');
    }

    function setAssignee(index, value) {
        const plan = getCurrentPlan();
        if (!plan[index]) return;
        plan[index].assignee = value.trim();
        setCurrentPlan(plan);
    }

    function analyzeResourceLoad() {
        const plan = getCurrentPlan();
        if (plan.length === 0) {
            showToast('请先生成计划', 'warning');
            return;
        }

        const devStats = {};
        plan.forEach(item => {
            const dev = item.assignee || '未分配';
            if (!devStats[dev]) {
                devStats[dev] = { total: 0, weeks: 0, milestones: 0, nodes: [] };
            }
            devStats[dev].total++;
            devStats[dev].weeks += (item.duration || 1);
            if (item.isMilestone) devStats[dev].milestones++;
            devStats[dev].nodes.push(item.name);
        });

        const devList = Object.entries(devStats).map(([name, stats]) => ({
            name, ...stats,
            loadScore: stats.weeks * 1 + stats.milestones * 2
        })).sort((a, b) => b.loadScore - a.loadScore);

        const maxLoad = Math.max(...devList.map(d => d.loadScore), 1);
        const OVERLOAD_THRESHOLD = 8; // 超过8周算过载

        document.getElementById('resourceLoadResult').innerHTML = `
            <div style="margin-bottom:16px;">
                <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-secondary);margin-bottom:6px;">
                    <span>工作量分布（负载分数 = 总周数×1 + 里程碑×2）</span>
                    <span>过载阈值：${OVERLOAD_THRESHOLD} 周</span>
                </div>
                <div style="display:flex;flex-direction:column;gap:8px;">
                    ${devList.map(d => {
                        const isOverload = d.weeks > OVERLOAD_THRESHOLD;
                        const barWidth = (d.loadScore / maxLoad * 100).toFixed(1);
                        return `
                            <div style="display:flex;align-items:center;gap:10px;">
                                <div style="width:100px;font-size:12px;color:var(--text-primary);text-align:right;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${d.name}">${d.name}</div>
                                <div style="flex:1;height:20px;background:var(--bg-secondary);border-radius:4px;overflow:hidden;position:relative;">
                                    <div style="height:100%;width:${barWidth}%;background:${isOverload ? 'var(--error)' : 'var(--text-primary)'};border-radius:4px;"></div>
                                    <span style="position:absolute;right:6px;top:50%;transform:translateY(-50%);font-size:11px;color:${isOverload ? '#fff' : 'var(--text-primary)'};">${d.loadScore}</span>
                                </div>
                                <div style="width:100px;font-size:11px;color:var(--text-secondary);flex-shrink:0;">
                                    ${d.weeks}周 / ${d.total}节点
                                    ${isOverload ? '<span style="color:var(--error);font-weight:600;"> 过载</span>' : ''}
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead><tr style="border-bottom:1px solid var(--border);">
                    <th style="padding:6px 8px;text-align:left;color:var(--text-secondary);font-weight:500;">负责人</th>
                    <th style="padding:6px 8px;text-align:center;color:var(--text-secondary);font-weight:500;">节点数</th>
                    <th style="padding:6px 8px;text-align:center;color:var(--text-secondary);font-weight:500;">总周数</th>
                    <th style="padding:6px 8px;text-align:center;color:var(--text-secondary);font-weight:500;">里程碑</th>
                    <th style="padding:6px 8px;text-align:center;color:var(--text-secondary);font-weight:500;">负载分</th>
                    <th style="padding:6px 8px;text-align:left;color:var(--text-secondary);font-weight:500;">负责节点</th>
                </tr></thead>
                <tbody>
                    ${devList.map(d => `
                        <tr style="border-bottom:1px solid var(--border);">
                            <td style="padding:6px 8px;color:var(--text-primary);">${d.name}</td>
                            <td style="padding:6px 8px;text-align:center;color:var(--text-secondary);">${d.total}</td>
                            <td style="padding:6px 8px;text-align:center;color:${d.weeks > OVERLOAD_THRESHOLD ? 'var(--error)' : 'var(--text-secondary)'};">${d.weeks}</td>
                            <td style="padding:6px 8px;text-align:center;color:var(--text-secondary);">${d.milestones}</td>
                            <td style="padding:6px 8px;text-align:center;font-weight:600;color:var(--text-primary);">${d.loadScore}</td>
                            <td style="padding:6px 8px;color:var(--text-secondary);font-size:11px;">${d.nodes.join('、')}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;

        showToast('资源负载分析完成', 'success');
    }

    // ============ 功能3：里程碑管理（增强） ============

    function initMilestoneManagement() {
        const container = document.getElementById('milestoneSection');
        if (!container) return;

        container.innerHTML = `
            <div style="padding:20px;background:var(--bg-card);border-radius:var(--radius-lg);border:1px solid var(--border);margin-bottom:20px;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--text-primary)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/><path d="M18 10a4 4 0 0 0-4-4H6l2 2-2 2h8a4 4 0 0 1 4 4z"/></svg>
                    <h3 style="margin:0;font-size:16px;font-weight:600;color:var(--text-primary);">里程碑管理</h3>
                    <button class="action-btn" onclick="PlanEnhancement.checkMilestoneStatus()" style="margin-left:auto;padding:6px 14px;font-size:12px;">检查里程碑状态</button>
                </div>
                <div id="milestoneResult" style="font-size:13px;color:var(--text-secondary);">点击"检查里程碑状态"按钮，查看里程碑延期情况</div>
            </div>
        `;
    }

    function checkMilestoneStatus() {
        const plan = getCurrentPlan();
        if (plan.length === 0) {
            showToast('请先生成计划', 'warning');
            return;
        }

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        const milestones = plan.filter(item => item.isMilestone);
        const delayed = [];
        const upcoming = [];
        const completed = [];

        milestones.forEach(item => {
            const milestoneDate = parseDate(item.date);
            if (!milestoneDate) return;
            const status = item.status || 'pending';
            if (status === 'completed' || status === 'done') {
                completed.push(item);
            } else if (milestoneDate < today) {
                delayed.push({ ...item, delayDays: Math.ceil((today - milestoneDate) / (1000 * 60 * 60 * 24)) });
            } else {
                const daysLeft = Math.ceil((milestoneDate - today) / (1000 * 60 * 60 * 24));
                upcoming.push({ ...item, daysLeft });
            }
        });

        document.getElementById('milestoneResult').innerHTML = `
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">
                <div style="text-align:center;padding:12px;background:rgba(255,59,48,0.08);border-radius:var(--radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--error);">${delayed.length}</div>
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">已延期</div>
                </div>
                <div style="text-align:center;padding:12px;background:rgba(255,149,0,0.08);border-radius:var(--radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--warning);">${upcoming.length}</div>
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">即将到来</div>
                </div>
                <div style="text-align:center;padding:12px;background:rgba(52,199,89,0.08);border-radius:var(--radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--success);">${completed.length}</div>
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">已完成</div>
                </div>
            </div>
            ${delayed.length > 0 ? `
                <div style="margin-bottom:12px;">
                    <div style="font-weight:600;color:var(--error);margin-bottom:6px;font-size:13px;">延期里程碑（需重点关注）：</div>
                    ${delayed.map(m => `
                        <div style="padding:8px 12px;background:rgba(255,59,48,0.06);border-left:3px solid var(--error);border-radius:0 var(--radius-sm) var(--radius-sm) 0;margin-bottom:4px;font-size:12px;display:flex;justify-content:space-between;align-items:center;">
                            <span style="color:var(--text-primary);font-weight:500;">${m.index}. ${m.name}</span>
                            <span style="color:var(--error);">计划 ${m.date}，已延期 ${m.delayDays} 天</span>
                        </div>
                    `).join('')}
                </div>
            ` : ''}
            ${upcoming.length > 0 ? `
                <div>
                    <div style="font-weight:600;color:var(--warning);margin-bottom:6px;font-size:13px;">即将到来的里程碑：</div>
                    ${upcoming.slice(0, 5).map(m => `
                        <div style="padding:8px 12px;background:rgba(255,149,0,0.06);border-left:3px solid var(--warning);border-radius:0 var(--radius-sm) var(--radius-sm) 0;margin-bottom:4px;font-size:12px;display:flex;justify-content:space-between;align-items:center;">
                            <span style="color:var(--text-primary);font-weight:500;">${m.index}. ${m.name}</span>
                            <span style="color:var(--warning);">${m.date}（还有 ${m.daysLeft} 天）</span>
                        </div>
                    `).join('')}
                </div>
            ` : ''}
        `;

        showToast('里程碑状态检查完成', 'success');
    }

    // ============ 功能4：基线对比 ============

    const BASELINE_KEY = getStorageKey('plan_baselines');

    function initBaselineComparison() {
        const container = document.getElementById('baselineSection');
        if (!container) return;

        container.innerHTML = `
            <div style="padding:20px;background:var(--bg-card);border-radius:var(--radius-lg);border:1px solid var(--border);margin-bottom:20px;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--text-primary)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
                    <h3 style="margin:0;font-size:16px;font-weight:600;color:var(--text-primary);">基线对比</h3>
                    <div style="margin-left:auto;display:flex;gap:8px;">
                        <button class="action-btn" onclick="PlanEnhancement.saveBaseline()" style="padding:6px 14px;font-size:12px;">保存基线</button>
                        <button class="action-btn" onclick="PlanEnhancement.compareWithBaseline()" style="padding:6px 14px;font-size:12px;">对比基线</button>
                    </div>
                </div>
                <div id="baselineList" style="margin-bottom:12px;"></div>
                <div id="baselineCompareResult" style="font-size:13px;color:var(--text-secondary);">保存计划基线后，可与当前计划对比，显示进度偏差</div>
            </div>
        `;

        renderBaselineList();
    }

    function getBaselines() {
        try {
            return JSON.parse(localStorage.getItem(BASELINE_KEY) || '[]');
        } catch (e) {
            return [];
        }
    }

    function saveBaselines(baselines) {
        localStorage.setItem(BASELINE_KEY, JSON.stringify(baselines));
    }

    function renderBaselineList() {
        const listEl = document.getElementById('baselineList');
        if (!listEl) return;
        const baselines = getBaselines();
        if (baselines.length === 0) {
            listEl.innerHTML = '<div style="font-size:12px;color:var(--text-secondary);">暂无保存的基线</div>';
            return;
        }
        listEl.innerHTML = `
            <div style="font-size:12px;color:var(--text-secondary);margin-bottom:6px;">已保存的基线：</div>
            <div style="display:flex;flex-wrap:wrap;gap:6px;">
                ${baselines.map((b, idx) => `
                    <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;background:var(--bg-secondary);border-radius:var(--radius-sm);font-size:12px;">
                        ${b.name} (${b.date})
                        <button onclick="PlanEnhancement.deleteBaseline(${idx})" style="background:none;border:none;cursor:pointer;color:var(--text-secondary);padding:0;font-size:14px;line-height:1;">×</button>
                    </span>
                `).join('')}
            </div>
        `;
    }

    function saveBaseline() {
        const plan = getCurrentPlan();
        if (plan.length === 0) {
            showToast('请先生成计划', 'warning');
            return;
        }
        const name = prompt('请输入基线名称：', '基线 ' + new Date().toLocaleDateString());
        if (!name) return;
        const baselines = getBaselines();
        baselines.push({
            name,
            date: formatDate(new Date()),
            plan: JSON.parse(JSON.stringify(plan))
        });
        saveBaselines(baselines);
        renderBaselineList();
        showToast('基线保存成功', 'success');
    }

    function deleteBaseline(index) {
        const baselines = getBaselines();
        baselines.splice(index, 1);
        saveBaselines(baselines);
        renderBaselineList();
        showToast('基线已删除', 'success');
    }

    function compareWithBaseline() {
        const plan = getCurrentPlan();
        const baselines = getBaselines();
        if (plan.length === 0) {
            showToast('请先生成计划', 'warning');
            return;
        }
        if (baselines.length === 0) {
            showToast('请先保存基线', 'warning');
            return;
        }

        // 使用最新的基线
        const baseline = baselines[baselines.length - 1];
        const baselinePlan = baseline.plan;

        // 对比每个节点的日期和状态
        const comparisons = [];
        const maxLen = Math.max(plan.length, baselinePlan.length);
        for (let i = 0; i < maxLen; i++) {
            const current = plan[i];
            const base = baselinePlan[i];
            if (!current || !base) {
                comparisons.push({
                    name: (current || base).name,
                    status: current ? '新增' : '已删除',
                    currentDate: current ? current.date : '-',
                    baselineDate: base ? base.date : '-',
                    diff: '-'
                });
                continue;
            }
            const currentDate = parseDate(current.date);
            const baselineDate = parseDate(base.date);
            let diff = '-';
            let status = '正常';
            if (currentDate && baselineDate) {
                const diffDays = Math.ceil((currentDate - baselineDate) / (1000 * 60 * 60 * 24));
                diff = (diffDays > 0 ? '+' : '') + diffDays + '天';
                if (diffDays > 0) status = '延期';
                else if (diffDays < 0) status = '提前';
            }
            comparisons.push({
                name: current.name,
                status,
                currentDate: current.date,
                baselineDate: base.date,
                diff
            });
        }

        const delayed = comparisons.filter(c => c.status === '延期').length;
        const advanced = comparisons.filter(c => c.status === '提前').length;

        document.getElementById('baselineCompareResult').innerHTML = `
            <div style="margin-bottom:12px;font-size:12px;color:var(--text-secondary);">
                对比基线：<strong style="color:var(--text-primary);">${baseline.name}</strong>（${baseline.date}）
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">
                <div style="text-align:center;padding:12px;background:rgba(255,59,48,0.08);border-radius:var(--radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--error);">${delayed}</div>
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">延期节点</div>
                </div>
                <div style="text-align:center;padding:12px;background:rgba(52,199,89,0.08);border-radius:var(--radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--success);">${advanced}</div>
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">提前节点</div>
                </div>
                <div style="text-align:center;padding:12px;background:var(--bg-secondary);border-radius:var(--radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--text-primary);">${comparisons.length}</div>
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">对比节点</div>
                </div>
            </div>
            <div style="max-height:300px;overflow-y:auto;border:1px solid var(--border);border-radius:var(--radius-md);">
                <table style="width:100%;border-collapse:collapse;font-size:12px;">
                    <thead style="position:sticky;top:0;background:var(--bg-primary);z-index:1;">
                        <tr style="border-bottom:1px solid var(--border);">
                            <th style="padding:8px;text-align:left;color:var(--text-secondary);font-weight:500;">节点</th>
                            <th style="padding:8px;text-align:center;color:var(--text-secondary);font-weight:500;">基线日期</th>
                            <th style="padding:8px;text-align:center;color:var(--text-secondary);font-weight:500;">当前日期</th>
                            <th style="padding:8px;text-align:center;color:var(--text-secondary);font-weight:500;">偏差</th>
                            <th style="padding:8px;text-align:center;color:var(--text-secondary);font-weight:500;">状态</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${comparisons.map(c => `
                            <tr style="border-bottom:1px solid var(--border);">
                                <td style="padding:6px 8px;color:var(--text-primary);">${c.name}</td>
                                <td style="padding:6px 8px;text-align:center;color:var(--text-secondary);">${c.baselineDate}</td>
                                <td style="padding:6px 8px;text-align:center;color:var(--text-secondary);">${c.currentDate}</td>
                                <td style="padding:6px 8px;text-align:center;font-weight:600;color:${c.status === '延期' ? 'var(--error)' : c.status === '提前' ? 'var(--success)' : 'var(--text-secondary)'};">${c.diff}</td>
                                <td style="padding:6px 8px;text-align:center;">
                                    <span style="padding:2px 8px;border-radius:var(--radius-sm);font-size:11px;background:${c.status === '延期' ? 'rgba(255,59,48,0.1)' : c.status === '提前' ? 'rgba(52,199,89,0.1)' : 'var(--bg-secondary)'};color:${c.status === '延期' ? 'var(--error)' : c.status === '提前' ? 'var(--success)' : 'var(--text-secondary)'};">${c.status}</span>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;

        showToast('基线对比完成', 'success');
    }

    // ============ 子 Tab 切换 ============

    function switchSubTab(tab) {
        ['dependency', 'resource', 'milestone', 'baseline'].forEach(t => {
            const section = document.getElementById(t + 'Section');
            const btn = document.getElementById('subtab-' + t);
            if (section) section.style.display = t === tab ? 'block' : 'none';
            if (btn) btn.classList.toggle('active', t === tab);
        });
    }

    // ============ 初始化 ============

    function init() {
        initDependencyManagement();
        initResourceAllocation();
        initMilestoneManagement();
        initBaselineComparison();
    }

    // 在生成计划后重新渲染编辑器
    const originalGeneratePlan = window.generatePlan;
    if (originalGeneratePlan) {
        window.generatePlan = function() {
            originalGeneratePlan.apply(this, arguments);
            setTimeout(() => {
                renderDependencyEditor();
                renderResourceEditor();
            }, 100);
        };
    }

    // 暴露到全局
    window.PlanEnhancement = {
        init,
        switchSubTab,
        setDependency,
        analyzeCriticalPath,
        setAssignee,
        analyzeResourceLoad,
        checkMilestoneStatus,
        saveBaseline,
        deleteBaseline,
        compareWithBaseline
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
