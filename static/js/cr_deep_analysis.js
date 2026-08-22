/**
 * CR 分析深度增强模块
 * 功能：版本对比、Bug预测、责任人负载分析、导出增强
 */

(function() {
    'use strict';

    // ============ 工具函数 ============

    function getIssues() {
        return (window.currentAnalysisData && window.currentAnalysisData.all_issues) || [];
    }

    function getSummary() {
        return (window.currentAnalysisData && window.currentAnalysisData.summary) || {};
    }

    function formatDate(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr;
        return d.toISOString().split('T')[0];
    }

    function parseDate(dateStr) {
        if (!dateStr) return null;
        const d = new Date(dateStr);
        return isNaN(d.getTime()) ? null : d;
    }

    function showToast(msg, type) {
        if (window.showToast) {
            window.showToast(msg, type || 'success');
        } else {
            alert(msg);
        }
    }

    // ============ 功能1：版本对比 ============

    let versionCompareData = { v1: null, v2: null };

    function initVersionCompare() {
        const container = document.getElementById('versionCompareSection');
        if (!container) return;

        container.innerHTML = `
            <div style="padding:20px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);margin-bottom:20px;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--ds-text)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
                    <h3 style="margin:0;font-size:16px;font-weight:600;color:var(--ds-text);">版本对比</h3>
                    <span style="font-size:12px;color:var(--ds-text-tertiary);">上传两个版本的 CR 数据，自动对比差异</span>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
                    <div>
                        <label style="font-size:13px;font-weight:500;color:var(--ds-text);display:block;margin-bottom:6px;">版本1（旧版本）</label>
                        <input type="file" id="versionFile1" accept=".xlsx,.xls,.csv" style="width:100%;padding:8px;border:1px solid var(--ds-border);border-radius:var(--ds-radius-md);font-size:13px;background:var(--ds-bg);color:var(--ds-text);" onchange="CRDeepAnalysis.loadVersion(1, this.files[0])">
                        <div id="versionInfo1" style="font-size:12px;color:var(--ds-text-tertiary);margin-top:4px;">未选择文件</div>
                    </div>
                    <div>
                        <label style="font-size:13px;font-weight:500;color:var(--ds-text);display:block;margin-bottom:6px;">版本2（新版本）</label>
                        <input type="file" id="versionFile2" accept=".xlsx,.xls,.csv" style="width:100%;padding:8px;border:1px solid var(--ds-border);border-radius:var(--ds-radius-md);font-size:13px;background:var(--ds-bg);color:var(--ds-text);" onchange="CRDeepAnalysis.loadVersion(2, this.files[0])">
                        <div id="versionInfo2" style="font-size:12px;color:var(--ds-text-tertiary);margin-top:4px;">未选择文件</div>
                    </div>
                </div>
                <div style="display:flex;gap:8px;">
                    <button class="btn btn-primary" onclick="CRDeepAnalysis.compareVersions()" style="padding:8px 20px;font-size:13px;">开始对比</button>
                    <button class="btn btn-secondary" onclick="CRDeepAnalysis.useCurrentAsVersion(1)" style="padding:8px 16px;font-size:13px;">当前分析作为版本1</button>
                    <button class="btn btn-secondary" onclick="CRDeepAnalysis.useCurrentAsVersion(2)" style="padding:8px 16px;font-size:13px;">当前分析作为版本2</button>
                </div>
            </div>
            <div id="versionCompareResult"></div>
        `;
    }

    function useCurrentAsVersion(versionNum) {
        const issues = getIssues();
        if (issues.length === 0) {
            showToast('当前没有分析数据，请先完成 CR 分析', 'warning');
            return;
        }
        versionCompareData['v' + versionNum] = {
            issues: JSON.parse(JSON.stringify(issues)),
            fileName: window.currentFileName || '当前分析'
        };
        document.getElementById('versionInfo' + versionNum).textContent =
            '已加载：' + (window.currentFileName || '当前分析') + '（' + issues.length + ' 条）';
        showToast('已将当前分析数据设为版本' + versionNum, 'success');
    }

    function loadVersion(versionNum, file) {
        if (!file) return;
        const reader = new FileReader();
        reader.onload = function(e) {
            try {
                // 简单的 CSV 解析（Excel 文件需要后端解析，这里简化处理）
                const text = e.target.result;
                const lines = text.split(/\r?\n/);
                if (lines.length < 2) {
                    showToast('文件内容为空或格式不正确', 'error');
                    return;
                }
                const headers = lines[0].split(',').map(h => h.trim().toLowerCase());
                const issues = [];
                for (let i = 1; i < lines.length; i++) {
                    if (!lines[i].trim()) continue;
                    const values = lines[i].split(',');
                    const issue = {};
                    headers.forEach((h, idx) => {
                        issue[h] = (values[idx] || '').trim();
                    });
                    // 标准化字段名
                    issue.module = issue.module || issue['模块'] || issue['component'] || '';
                    issue.status = issue.status || issue['状态'] || '';
                    issue.severity = issue.severity || issue['严重性'] || issue['优先级'] || '';
                    issue.assignee = issue.assignee || issue['研发'] || issue['负责人'] || issue['owner'] || '';
                    issue.created_date = issue.created_date || issue['创建日期'] || issue['创建时间'] || '';
                    issue.resolved_date = issue.resolved_date || issue['解决日期'] || issue['解决时间'] || '';
                    issue.summary = issue.summary || issue['标题'] || issue['问题描述'] || '';
                    issue.key = issue.key || issue['id'] || issue['issue key'] || ('CSV-' + i);
                    issues.push(issue);
                }
                versionCompareData['v' + versionNum] = { issues: issues, fileName: file.name };
                document.getElementById('versionInfo' + versionNum).textContent =
                    '已加载：' + file.name + '（' + issues.length + ' 条）';
                showToast('版本' + versionNum + ' 加载成功，共 ' + issues.length + ' 条', 'success');
            } catch (err) {
                showToast('文件解析失败：' + err.message, 'error');
            }
        };
        reader.readAsText(file);
    }

    function compareVersions() {
        if (!versionCompareData.v1 || !versionCompareData.v2) {
            showToast('请先加载两个版本的数据', 'warning');
            return;
        }

        const v1 = versionCompareData.v1.issues;
        const v2 = versionCompareData.v2.issues;

        // 用 key 作为唯一标识
        const v1Keys = new Set(v1.map(i => (i.key || i.summary || '').toString()));
        const v2Keys = new Set(v2.map(i => (i.key || i.summary || '').toString()));

        const newIssues = v2.filter(i => !v1Keys.has((i.key || i.summary || '').toString()));
        const resolvedIssues = v1.filter(i => !v2Keys.has((i.key || i.summary || '').toString()));
        const remainingIssues = v2.filter(i => v1Keys.has((i.key || i.summary || '').toString()));

        // 模块变化统计
        const v1Modules = {};
        const v2Modules = {};
        v1.forEach(i => { const m = i.module || '未分类'; v1Modules[m] = (v1Modules[m] || 0) + 1; });
        v2.forEach(i => { const m = i.module || '未分类'; v2Modules[m] = (v2Modules[m] || 0) + 1; });

        const allModules = new Set([...Object.keys(v1Modules), ...Object.keys(v2Modules)]);
        const moduleChanges = [];
        allModules.forEach(m => {
            const old = v1Modules[m] || 0;
            const now = v2Modules[m] || 0;
            moduleChanges.push({ module: m, old, now, diff: now - old });
        });
        moduleChanges.sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff));

        // 负责人变化统计
        const v1Devs = {};
        const v2Devs = {};
        v1.forEach(i => { const d = i.assignee || '未分配'; v1Devs[d] = (v1Devs[d] || 0) + 1; });
        v2.forEach(i => { const d = i.assignee || '未分配'; v2Devs[d] = (v2Devs[d] || 0) + 1; });

        const resultEl = document.getElementById('versionCompareResult');
        resultEl.innerHTML = `
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;">
                <div style="padding:16px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);text-align:center;">
                    <div style="font-size:24px;font-weight:700;color:var(--ds-error);">${newIssues.length}</div>
                    <div style="font-size:12px;color:var(--ds-text-secondary);margin-top:4px;">新增 Bug</div>
                </div>
                <div style="padding:16px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);text-align:center;">
                    <div style="font-size:24px;font-weight:700;color:var(--ds-success);">${resolvedIssues.length}</div>
                    <div style="font-size:12px;color:var(--ds-text-secondary);margin-top:4px;">已解决</div>
                </div>
                <div style="padding:16px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);text-align:center;">
                    <div style="font-size:24px;font-weight:700;color:var(--ds-warning);">${remainingIssues.length}</div>
                    <div style="font-size:12px;color:var(--ds-text-secondary);margin-top:4px;">遗留 Bug</div>
                </div>
                <div style="padding:16px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);text-align:center;">
                    <div style="font-size:24px;font-weight:700;color:var(--ds-text);">${v2.length}</div>
                    <div style="font-size:12px;color:var(--ds-text-secondary);margin-top:4px;">当前总数</div>
                </div>
            </div>

            <div style="padding:20px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);margin-bottom:20px;">
                <h4 style="margin:0 0 12px 0;font-size:14px;font-weight:600;color:var(--ds-text);">模块变化 TOP10</h4>
                <table style="width:100%;border-collapse:collapse;font-size:13px;">
                    <thead><tr style="border-bottom:1px solid var(--ds-border-light);">
                        <th style="padding:8px;text-align:left;color:var(--ds-text-secondary);font-weight:500;">模块</th>
                        <th style="padding:8px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">版本1</th>
                        <th style="padding:8px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">版本2</th>
                        <th style="padding:8px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">变化</th>
                    </tr></thead>
                    <tbody>
                        ${moduleChanges.slice(0, 10).map(m => `
                            <tr style="border-bottom:1px solid var(--ds-border-light);">
                                <td style="padding:8px;color:var(--ds-text);">${m.module}</td>
                                <td style="padding:8px;text-align:center;color:var(--ds-text-secondary);">${m.old}</td>
                                <td style="padding:8px;text-align:center;color:var(--ds-text-secondary);">${m.now}</td>
                                <td style="padding:8px;text-align:center;font-weight:600;color:${m.diff > 0 ? 'var(--ds-error)' : m.diff < 0 ? 'var(--ds-success)' : 'var(--ds-text-secondary)'};">${m.diff > 0 ? '+' : ''}${m.diff}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div style="padding:20px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);">
                    <h4 style="margin:0 0 12px 0;font-size:14px;font-weight:600;color:var(--ds-error);">新增 Bug 列表（${newIssues.length}）</h4>
                    <div style="max-height:300px;overflow-y:auto;">
                        ${newIssues.length === 0 ? '<div style="text-align:center;padding:20px;color:var(--ds-text-tertiary);font-size:13px;">无新增 Bug</div>' :
                        newIssues.slice(0, 20).map(i => `
                            <div style="padding:8px 0;border-bottom:1px solid var(--ds-border-light);font-size:12px;">
                                <div style="color:var(--ds-text);font-weight:500;">${i.key || ''} ${i.summary || ''}</div>
                                <div style="color:var(--ds-text-tertiary);margin-top:2px;">${i.module || ''} · ${i.assignee || ''} · ${i.severity || ''}</div>
                            </div>
                        `).join('')}
                        ${newIssues.length > 20 ? '<div style="text-align:center;padding:8px;color:var(--ds-text-tertiary);font-size:12px;">仅显示前20条</div>' : ''}
                    </div>
                </div>
                <div style="padding:20px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);">
                    <h4 style="margin:0 0 12px 0;font-size:14px;font-weight:600;color:var(--ds-success);">已解决 Bug 列表（${resolvedIssues.length}）</h4>
                    <div style="max-height:300px;overflow-y:auto;">
                        ${resolvedIssues.length === 0 ? '<div style="text-align:center;padding:20px;color:var(--ds-text-tertiary);font-size:13px;">无已解决 Bug</div>' :
                        resolvedIssues.slice(0, 20).map(i => `
                            <div style="padding:8px 0;border-bottom:1px solid var(--ds-border-light);font-size:12px;">
                                <div style="color:var(--ds-text);font-weight:500;">${i.key || ''} ${i.summary || ''}</div>
                                <div style="color:var(--ds-text-tertiary);margin-top:2px;">${i.module || ''} · ${i.assignee || ''} · ${i.severity || ''}</div>
                            </div>
                        `).join('')}
                        ${resolvedIssues.length > 20 ? '<div style="text-align:center;padding:8px;color:var(--ds-text-tertiary);font-size:12px;">仅显示前20条</div>' : ''}
                    </div>
                </div>
            </div>
        `;

        showToast('版本对比完成', 'success');
    }

    // ============ 功能2：Bug 预测 ============

    function initBugPrediction() {
        const container = document.getElementById('bugPredictionSection');
        if (!container) return;

        container.innerHTML = `
            <div style="padding:20px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--ds-text)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
                    <h3 style="margin:0;font-size:16px;font-weight:600;color:var(--ds-text);">Bug 趋势预测</h3>
                    <span style="font-size:12px;color:var(--ds-text-tertiary);">基于历史数据预测未来趋势</span>
                    <button class="btn btn-primary" onclick="CRDeepAnalysis.predictBugs()" style="margin-left:auto;padding:6px 14px;font-size:12px;">生成预测</button>
                </div>
                <div id="bugPredictionResult" style="font-size:13px;color:var(--ds-text-secondary);">点击"生成预测"按钮，基于当前分析数据预测未来 Bug 趋势</div>
            </div>
        `;
    }

    function predictBugs() {
        const issues = getIssues();
        if (issues.length === 0) {
            showToast('请先完成 CR 分析', 'warning');
            return;
        }

        // 按日期统计新增和解决
        const dailyNew = {};
        const dailyResolved = {};
        issues.forEach(issue => {
            const created = parseDate(issue.created_date);
            if (created) {
                const key = formatDate(created);
                dailyNew[key] = (dailyNew[key] || 0) + 1;
            }
            const resolved = parseDate(issue.resolved_date);
            if (resolved) {
                const key = formatDate(resolved);
                dailyResolved[key] = (dailyResolved[key] || 0) + 1;
            }
        });

        const dates = Object.keys(dailyNew).sort();
        if (dates.length < 3) {
            document.getElementById('bugPredictionResult').innerHTML =
                '<div style="text-align:center;padding:20px;color:var(--ds-text-tertiary);">历史数据不足（至少需要3天数据），无法生成预测</div>';
            return;
        }

        // 简单移动平均预测
        const recentNew = dates.slice(-7).map(d => dailyNew[d] || 0);
        const recentResolved = dates.slice(-7).map(d => dailyResolved[d] || 0);
        const avgNew = recentNew.reduce((a, b) => a + b, 0) / recentNew.length;
        const avgResolved = recentResolved.reduce((a, b) => a + b, 0) / recentResolved.length;

        // 线性回归斜率
        const n = recentNew.length;
        const sumX = (n * (n - 1)) / 2;
        const sumY = recentNew.reduce((a, b) => a + b, 0);
        const sumXY = recentNew.reduce((acc, y, i) => acc + i * y, 0);
        const sumX2 = recentNew.reduce((acc, _, i) => acc + i * i, 0);
        const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);

        const predictedNewNextWeek = Math.round(avgNew * 7 + slope * 7 * 3);
        const predictedResolvedNextWeek = Math.round(avgResolved * 7);
        const netChange = predictedNewNextWeek - predictedResolvedNextWeek;

        let riskLevel = '低';
        let riskColor = 'var(--ds-success)';
        if (netChange > 10 || slope > 2) {
            riskLevel = '高';
            riskColor = 'var(--ds-error)';
        } else if (netChange > 0 || slope > 0) {
            riskLevel = '中';
            riskColor = 'var(--ds-warning)';
        }

        document.getElementById('bugPredictionResult').innerHTML = `
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;">
                <div style="text-align:center;padding:12px;background:var(--ds-bg);border-radius:var(--ds-radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--ds-text);">${avgNew.toFixed(1)}</div>
                    <div style="font-size:11px;color:var(--ds-text-tertiary);margin-top:2px;">日均新增</div>
                </div>
                <div style="text-align:center;padding:12px;background:var(--ds-bg);border-radius:var(--ds-radius-md);">
                    <div style="font-size:20px;font-weight:700;color:var(--ds-text);">${avgResolved.toFixed(1)}</div>
                    <div style="font-size:11px;color:var(--ds-text-tertiary);margin-top:2px;">日均解决</div>
                </div>
                <div style="text-align:center;padding:12px;background:var(--ds-bg);border-radius:var(--ds-radius-md);">
                    <div style="font-size:20px;font-weight:700;color:${slope > 0 ? 'var(--ds-error)' : 'var(--ds-success)'};">${slope > 0 ? '+' : ''}${slope.toFixed(2)}</div>
                    <div style="font-size:11px;color:var(--ds-text-tertiary);margin-top:2px;">新增趋势（斜率）</div>
                </div>
                <div style="text-align:center;padding:12px;background:var(--ds-bg);border-radius:var(--ds-radius-md);">
                    <div style="font-size:20px;font-weight:700;color:${riskColor};">${riskLevel}</div>
                    <div style="font-size:11px;color:var(--ds-text-tertiary);margin-top:2px;">风险等级</div>
                </div>
            </div>
            <div style="padding:14px;background:var(--ds-bg);border-radius:var(--ds-radius-md);font-size:13px;line-height:1.8;">
                <div><strong style="color:var(--ds-text);">未来一周预测：</strong></div>
                <div style="color:var(--ds-text-secondary);">• 预计新增 Bug：<strong style="color:var(--ds-error);">${predictedNewNextWeek}</strong> 条</div>
                <div style="color:var(--ds-text-secondary);">• 预计解决 Bug：<strong style="color:var(--ds-success);">${predictedResolvedNextWeek}</strong> 条</div>
                <div style="color:var(--ds-text-secondary);">• 净变化：<strong style="color:${netChange > 0 ? 'var(--ds-error)' : 'var(--ds-success)'};">${netChange > 0 ? '+' : ''}${netChange}</strong> 条</div>
                <div style="margin-top:8px;color:var(--ds-text-secondary);">
                    <strong>建议：</strong>${
                        riskLevel === '高' ? 'Bug 增长趋势明显，建议增加测试资源和研发投入，优先解决高严重度问题' :
                        riskLevel === '中' ? 'Bug 数量稳中有升，建议关注重灾模块，提前分配修复资源' :
                        'Bug 趋势稳定，保持当前研发节奏即可'
                    }
                </div>
            </div>
        `;

        showToast('Bug 预测生成完成', 'success');
    }

    // ============ 功能3：责任人负载分析 ============

    function initDeveloperLoad() {
        const container = document.getElementById('developerLoadSection');
        if (!container) return;

        container.innerHTML = `
            <div style="padding:20px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--ds-text)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                    <h3 style="margin:0;font-size:16px;font-weight:600;color:var(--ds-text);">责任人负载分析</h3>
                    <span style="font-size:12px;color:var(--ds-text-tertiary);">识别过载研发人员</span>
                    <button class="btn btn-primary" onclick="CRDeepAnalysis.analyzeDeveloperLoad()" style="margin-left:auto;padding:6px 14px;font-size:12px;">分析负载</button>
                </div>
                <div id="developerLoadResult" style="font-size:13px;color:var(--ds-text-secondary);">点击"分析负载"按钮，查看研发人员负载分布</div>
            </div>
        `;
    }

    function analyzeDeveloperLoad() {
        const issues = getIssues();
        if (issues.length === 0) {
            showToast('请先完成 CR 分析', 'warning');
            return;
        }

        const devStats = {};
        issues.forEach(issue => {
            const dev = issue.assignee || '未分配';
            if (!devStats[dev]) {
                devStats[dev] = { total: 0, open: 0, resolved: 0, high: 0, critical: 0 };
            }
            devStats[dev].total++;
            const status = (issue.status || '').toLowerCase();
            if (status.includes('resolved') || status.includes('closed') || status.includes('已解决') || status.includes('已关闭')) {
                devStats[dev].resolved++;
            } else {
                devStats[dev].open++;
            }
            const severity = (issue.severity || '').toLowerCase();
            if (severity.includes('high') || severity.includes('高') || severity.includes('major')) {
                devStats[dev].high++;
            }
            if (severity.includes('critical') || severity.includes('严重') || severity.includes('blocker') || severity.includes('致命')) {
                devStats[dev].critical++;
            }
        });

        const devList = Object.entries(devStats).map(([name, stats]) => ({
            name,
            ...stats,
            loadScore: stats.open * 1 + stats.high * 2 + stats.critical * 3
        })).sort((a, b) => b.loadScore - a.loadScore);

        const maxLoad = Math.max(...devList.map(d => d.loadScore), 1);
        const OVERLOAD_THRESHOLD = 10;

        document.getElementById('developerLoadResult').innerHTML = `
            <div style="margin-bottom:16px;">
                <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--ds-text-tertiary);margin-bottom:6px;">
                    <span>负载分布（负载分数 = 待解决×1 + 高严重×2 + 致命×3）</span>
                    <span>过载阈值：${OVERLOAD_THRESHOLD}</span>
                </div>
                <div style="display:flex;flex-direction:column;gap:8px;">
                    ${devList.slice(0, 15).map(d => {
                        const isOverload = d.open > OVERLOAD_THRESHOLD;
                        const barWidth = (d.loadScore / maxLoad * 100).toFixed(1);
                        return `
                            <div style="display:flex;align-items:center;gap:10px;">
                                <div style="width:100px;font-size:12px;color:var(--ds-text);text-align:right;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${d.name}">${d.name}</div>
                                <div style="flex:1;height:20px;background:var(--ds-bg);border-radius:4px;overflow:hidden;position:relative;">
                                    <div style="height:100%;width:${barWidth}%;background:${isOverload ? 'var(--ds-error)' : 'var(--ds-accent)'};border-radius:4px;transition:width 0.3s;"></div>
                                    <span style="position:absolute;right:6px;top:50%;transform:translateY(-50%);font-size:11px;color:${isOverload ? '#fff' : 'var(--ds-text)'};">${d.loadScore}</span>
                                </div>
                                <div style="width:80px;font-size:11px;color:var(--ds-text-tertiary);flex-shrink:0;">
                                    待解决 ${d.open}
                                    ${isOverload ? '<span style="color:var(--ds-error);font-weight:600;"> 过载</span>' : ''}
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead><tr style="border-bottom:1px solid var(--ds-border-light);">
                    <th style="padding:6px 8px;text-align:left;color:var(--ds-text-secondary);font-weight:500;">研发</th>
                    <th style="padding:6px 8px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">总数</th>
                    <th style="padding:6px 8px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">待解决</th>
                    <th style="padding:6px 8px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">已解决</th>
                    <th style="padding:6px 8px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">高严重</th>
                    <th style="padding:6px 8px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">致命</th>
                    <th style="padding:6px 8px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">负载分</th>
                </tr></thead>
                <tbody>
                    ${devList.map(d => `
                        <tr style="border-bottom:1px solid var(--ds-border-light);">
                            <td style="padding:6px 8px;color:var(--ds-text);">${d.name}</td>
                            <td style="padding:6px 8px;text-align:center;color:var(--ds-text-secondary);">${d.total}</td>
                            <td style="padding:6px 8px;text-align:center;color:${d.open > OVERLOAD_THRESHOLD ? 'var(--ds-error)' : 'var(--ds-text-secondary)'};">${d.open}</td>
                            <td style="padding:6px 8px;text-align:center;color:var(--ds-text-secondary);">${d.resolved}</td>
                            <td style="padding:6px 8px;text-align:center;color:var(--ds-text-secondary);">${d.high}</td>
                            <td style="padding:6px 8px;text-align:center;color:var(--ds-text-secondary);">${d.critical}</td>
                            <td style="padding:6px 8px;text-align:center;font-weight:600;color:var(--ds-text);">${d.loadScore}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;

        showToast('责任人负载分析完成', 'success');
    }

    // ============ 功能4：导出增强 ============

    function initExportEnhancement() {
        // 在结果区域的按钮组中添加导出按钮
        const btnGroup = document.querySelector('#resultCard .btn-group') ||
                          document.querySelector('#resultCard > div:first-child > div:last-child');
        if (!btnGroup) return;

        const exportBtn = document.createElement('button');
        exportBtn.className = 'btn btn-secondary';
        exportBtn.style.cssText = 'padding:8px 16px;font-size:13px;display:none;';
        exportBtn.id = 'exportEnhancedBtn';
        exportBtn.innerHTML = '导出';
        exportBtn.onclick = function(e) {
            e.stopPropagation();
            const menu = document.getElementById('exportMenu');
            if (menu) {
                const rect = exportBtn.getBoundingClientRect();
                menu.style.top = (rect.bottom + window.scrollY + 4) + 'px';
                menu.style.left = (rect.right + window.scrollX - 160) + 'px';
                menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
            }
        };
        btnGroup.appendChild(exportBtn);

        // 导出菜单
        const menu = document.createElement('div');
        menu.id = 'exportMenu';
        menu.style.cssText = 'display:none;position:absolute;background:var(--ds-bg-elevated);border:1px solid var(--ds-border-light);border-radius:var(--ds-radius-md);box-shadow:var(--ds-shadow-lg);padding:6px;z-index:1000;min-width:160px;';
        menu.innerHTML = `
            <div onclick="CRDeepAnalysis.exportToCSV()" style="padding:8px 12px;cursor:pointer;font-size:13px;color:var(--ds-text);border-radius:4px;" onmouseover="this.style.background='var(--ds-bg-secondary)'" onmouseout="this.style.background=''">导出 Excel 明细</div>
            <div onclick="CRDeepAnalysis.exportToMarkdown()" style="padding:8px 12px;cursor:pointer;font-size:13px;color:var(--ds-text);border-radius:4px;" onmouseover="this.style.background='var(--ds-bg-secondary)'" onmouseout="this.style.background=''">导出 Markdown 报告</div>
            <div onclick="CRDeepAnalysis.exportToPDF()" style="padding:8px 12px;cursor:pointer;font-size:13px;color:var(--ds-text);border-radius:4px;" onmouseover="this.style.background='var(--ds-bg-secondary)'" onmouseout="this.style.background=''">导出 PDF 报告</div>
        `;
        document.body.appendChild(menu);

        // 点击外部关闭菜单
        document.addEventListener('click', function(e) {
            if (!e.target.closest('#exportEnhancedBtn') && !e.target.closest('#exportMenu')) {
                if (menu) menu.style.display = 'none';
            }
        });
    }

    function showExportButtons() {
        const btn = document.getElementById('exportEnhancedBtn');
        if (btn) btn.style.display = '';
    }

    function exportToCSV() {
        const issues = getIssues();
        if (issues.length === 0) {
            showToast('没有可导出的数据', 'warning');
            return;
        }

        const headers = ['Key', '标题', '模块', '研发', '状态', '严重性', '创建日期', '解决日期'];
        const rows = issues.map(i => [
            i.key || '',
            (i.summary || '').replace(/,/g, '，'),
            i.module || '',
            i.assignee || '',
            i.status || '',
            i.severity || '',
            formatDate(i.created_date),
            formatDate(i.resolved_date)
        ]);

        const csv = '\uFEFF' + [headers, ...rows].map(r => r.join(',')).join('\n');
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = (window.currentFileName || 'CR分析') + '_明细.csv';
        link.click();
        URL.revokeObjectURL(link.href);
        document.getElementById('exportMenu').style.display = 'none';
        showToast('Excel 明细导出成功', 'success');
    }

    function exportToMarkdown() {
        const issues = getIssues();
        const summary = getSummary();
        if (issues.length === 0) {
            showToast('没有可导出的数据', 'warning');
            return;
        }

        let md = '# CR 分析报告\n\n';
        md += '**生成时间：** ' + new Date().toLocaleString() + '\n\n';
        md += '**文件：** ' + (window.currentFileName || '未知') + '\n\n';

        if (summary && summary.total_issues) {
            md += '## 概览\n\n';
            md += '- 问题总数：' + (summary.total_issues || issues.length) + '\n';
            md += '- 未解决：' + (summary.open_issues || '-') + '\n';
            md += '- 已解决：' + (summary.resolved_issues || '-') + '\n\n';
        }

        // 模块统计
        const modules = {};
        issues.forEach(i => { const m = i.module || '未分类'; modules[m] = (modules[m] || 0) + 1; });
        md += '## 模块分布\n\n';
        md += '| 模块 | 数量 |\n|------|------|\n';
        Object.entries(modules).sort((a, b) => b[1] - a[1]).forEach(([m, c]) => {
            md += '| ' + m + ' | ' + c + ' |\n';
        });
        md += '\n';

        // 问题列表
        md += '## 问题列表\n\n';
        md += '| Key | 标题 | 模块 | 研发 | 状态 | 严重性 |\n';
        md += '|-----|------|------|------|------|--------|\n';
        issues.slice(0, 100).forEach(i => {
            md += '| ' + (i.key || '') + ' | ' + (i.summary || '').replace(/\|/g, '／') + ' | ' + (i.module || '') + ' | ' + (i.assignee || '') + ' | ' + (i.status || '') + ' | ' + (i.severity || '') + ' |\n';
        });
        if (issues.length > 100) {
            md += '\n*仅显示前100条，完整数据请导出 Excel 明细*\n';
        }

        const blob = new Blob([md], { type: 'text/markdown;charset=utf-8;' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = (window.currentFileName || 'CR分析') + '_报告.md';
        link.click();
        URL.revokeObjectURL(link.href);
        document.getElementById('exportMenu').style.display = 'none';
        showToast('Markdown 报告导出成功', 'success');
    }

    function exportToPDF() {
        const issues = getIssues();
        if (issues.length === 0) {
            showToast('没有可导出的数据', 'warning');
            return;
        }

        // 生成 Markdown 内容，然后跳转到 PDF 快转页面
        let md = '# CR 分析报告\n\n';
        md += '生成时间：' + new Date().toLocaleString() + '\n\n';
        md += '文件：' + (window.currentFileName || '未知') + '\n\n';
        md += '问题总数：' + issues.length + '\n\n';
        md += '## 问题列表\n\n';
        issues.slice(0, 50).forEach((i, idx) => {
            md += (idx + 1) + '. **' + (i.key || '') + '** ' + (i.summary || '') + '\n';
            md += '   - 模块：' + (i.module || '') + ' | 研发：' + (i.assignee || '') + ' | 状态：' + (i.status || '') + ' | 严重性：' + (i.severity || '') + '\n\n';
        });

        // 存储到 localStorage，跳转到 PDF 转换页面
        try {
            localStorage.setItem('pdf_convert_content', md);
            localStorage.setItem('pdf_convert_title', (window.currentFileName || 'CR分析') + '_报告');
            window.location.href = '/md2pdf?autoconvert=1';
        } catch (e) {
            showToast('PDF 导出失败：' + e.message, 'error');
        }
        document.getElementById('exportMenu').style.display = 'none';
    }

    // ============ 初始化 ============

    function init() {
        initVersionCompare();
        initBugPrediction();
        initDeveloperLoad();
        initExportEnhancement();
    }

    // 暴露到全局
    window.CRDeepAnalysis = {
        init,
        loadVersion,
        useCurrentAsVersion,
        compareVersions,
        predictBugs,
        analyzeDeveloperLoad,
        showExportButtons,
        exportToCSV,
        exportToMarkdown,
        exportToPDF
    };

    // DOM 加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
