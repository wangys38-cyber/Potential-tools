/**
 * Potential-tools v8.0 CR分析图表增强
 * 依赖：chart-library.js (PTChart), Chart.js
 * 在 CR 分析完成后自动渲染增强图表：
 * - 模块问题柱状图
 * - 严重程度堆叠柱状图（模块×严重度）
 * - 研发解决效率散点图
 * - 每日趋势与累计Bug曲线
 */
(function() {
    'use strict';

    var charts = {
        moduleBar: null,
        severityStacked: null,
        rdEfficiency: null,
        dailyCumulative: null
    };

    var SEVERITY_COLORS = {
        'blocker': '#ff3b30', 'critical': '#ff7433', 'major': '#ff9500',
        'minor': '#ffcc00', 'trivial': '#34c759',
        'high': '#ff3b30', 'medium': '#ff9500', 'low': '#34c759',
        'p0': '#ff3b30', 'p1': '#ff7433', 'p2': '#ff9500', 'p3': '#ffcc00', 'p4': '#34c759',
        '严重': '#ff3b30', '高': '#ff7433', '中': '#ff9500', '低': '#34c759',
        'unknown': '#8e8e93'
    };

    function getSeverityColor(sev) {
        if (!sev) return SEVERITY_COLORS.unknown;
        var key = String(sev).toLowerCase().trim();
        return SEVERITY_COLORS[key] || SEVERITY_COLORS.unknown;
    }

    function normalizeSeverity(sev) {
        if (!sev) return 'Unknown';
        var s = String(sev).toLowerCase().trim();
        var map = {
            'blocker': 'Blocker', 'critical': 'Critical', 'major': 'Major',
            'minor': 'Minor', 'trivial': 'Trivial',
            'high': 'High', 'medium': 'Medium', 'low': 'Low',
            'p0': 'P0', 'p1': 'P1', 'p2': 'P2', 'p3': 'P3', 'p4': 'P4',
            '严重': '严重', '高': '高', '中': '中', '低': '低'
        };
        return map[s] || String(sev);
    }

    // ========== 模块问题柱状图 ==========
    function renderModuleBar(moduleStats) {
        var canvas = document.getElementById('moduleBarChart');
        if (!canvas || !moduleStats) return;
        charts.moduleBar = PTChart.destroy(charts.moduleBar);

        var data = Object.entries(moduleStats)
            .sort(function(a, b) { return b[1].total - a[1].total; })
            .slice(0, 12);

        if (data.length === 0) {
            PTChart.showEmpty('moduleBarWrap', '暂无模块数据');
            return;
        }

        charts.moduleBar = PTChart.create('moduleBarChart', {
            type: 'bar',
            data: {
                labels: data.map(function(d) { return d[0]; }),
                datasets: [{
                    label: '问题总数',
                    data: data.map(function(d) { return d[1].total; }),
                    backgroundColor: '#000000',
                    borderRadius: 4,
                    borderSkipped: false
                }, {
                    label: '已解决',
                    data: data.map(function(d) { return d[1].resolved || 0; }),
                    backgroundColor: '#34c759',
                    borderRadius: 4,
                    borderSkipped: false
                }]
            },
            options: {
                indexAxis: 'y',
                plugins: {
                    legend: { position: 'top' },
                    title: { display: false }
                },
                scales: {
                    x: { beginAtZero: true, stacked: false },
                    y: { stacked: false }
                }
            }
        });
    }

    // ========== 严重程度堆叠柱状图（模块×严重度） ==========
    function renderSeverityStacked(allIssues, moduleStats) {
        var canvas = document.getElementById('severityStackedChart');
        if (!canvas) return;
        charts.severityStacked = PTChart.destroy(charts.severityStacked);

        if (!allIssues || allIssues.length === 0) {
            PTChart.showEmpty('severityStackedWrap', '暂无问题明细数据');
            return;
        }

        // 按模块聚合
        var moduleMap = {};
        var severitySet = {};
        allIssues.forEach(function(item) {
            var mod = item.module || item.component || item.Module || '未分类';
            var sev = normalizeSeverity(item.severity || item.priority || item.Severity || item.Priority);
            if (!moduleMap[mod]) moduleMap[mod] = {};
            moduleMap[mod][sev] = (moduleMap[mod][sev] || 0) + 1;
            severitySet[sev] = true;
        });

        var modules = Object.keys(moduleMap).sort(function(a, b) {
            var ta = Object.values(moduleMap[a]).reduce(function(s, v) { return s + v; }, 0);
            var tb = Object.values(moduleMap[b]).reduce(function(s, v) { return s + v; }, 0);
            return tb - ta;
        }).slice(0, 10);

        var severities = Object.keys(severitySet);
        if (modules.length === 0 || severities.length === 0) {
            PTChart.showEmpty('severityStackedWrap', '暂无严重程度数据');
            return;
        }

        var datasets = severities.map(function(sev) {
            return {
                label: sev,
                data: modules.map(function(mod) { return moduleMap[mod][sev] || 0; }),
                backgroundColor: getSeverityColor(sev),
                borderRadius: 2,
                borderSkipped: false
            };
        });

        charts.severityStacked = PTChart.create('severityStackedChart', {
            type: 'bar',
            data: { labels: modules, datasets: datasets },
            options: {
                plugins: { legend: { position: 'top' } },
                scales: {
                    x: { stacked: true },
                    y: { stacked: true, beginAtZero: true }
                }
            }
        });
    }

    // ========== 研发解决效率散点图 ==========
    function renderRdEfficiency(allIssues, devStats) {
        var canvas = document.getElementById('rdEfficiencyChart');
        if (!canvas) return;
        charts.rdEfficiency = PTChart.destroy(charts.rdEfficiency);

        var devData = {};

        if (allIssues && allIssues.length > 0) {
            allIssues.forEach(function(item) {
                var dev = item.developer || item.assignee || item.owner || item.Developer || item.Assignee || '';
                if (!dev) return;
                if (!devData[dev]) {
                    devData[dev] = { resolved: 0, totalDuration: 0, count: 0, reopened: 0, total: 0 };
                }
                devData[dev].total++;
                var status = String(item.status || '').toLowerCase();
                var isResolved = /resolved|closed|fixed|done|已解决|已关闭|关闭/i.test(status);
                if (isResolved) {
                    devData[dev].resolved++;
                    var cd = item.create_date || item.created || item.date || '';
                    var rd = item.resolved_date || item.closed_date || item.fixed_date || '';
                    if (cd && rd) {
                        var start = new Date(cd), end = new Date(rd);
                        if (!isNaN(start) && !isNaN(end) && end >= start) {
                            var days = (end - start) / 86400000;
                            devData[dev].totalDuration += days;
                            devData[dev].count++;
                        }
                    }
                }
                // reopen 检测
                if (item.reopen_count || item.reopened || /reopen|重开/i.test(String(item.status || '') + String(item.comments || ''))) {
                    devData[dev].reopened++;
                }
            });
        }

        // 合并 dev_stats 中的数据
        if (devStats) {
            Object.entries(devStats).forEach(function(_ref) {
                var dev = _ref[0], stats = _ref[1];
                if (!devData[dev]) {
                    devData[dev] = { resolved: stats.resolved || 0, totalDuration: 0, count: 0, reopened: 0, total: stats.total || 0 };
                } else {
                    if (stats.resolved) devData[dev].resolved = Math.max(devData[dev].resolved, stats.resolved);
                    if (stats.total) devData[dev].total = Math.max(devData[dev].total, stats.total);
                }
            });
        }

        var points = Object.entries(devData)
            .filter(function(d) { return d[1].resolved > 0; })
            .map(function(d) {
                var stats = d[1];
                var avgDuration = stats.count > 0 ? stats.totalDuration / stats.count : 0;
                var reopenRate = stats.total > 0 ? (stats.reopened / stats.total * 100) : 0;
                return {
                    x: stats.resolved,
                    y: parseFloat(avgDuration.toFixed(1)),
                    r: Math.max(5, Math.min(20, 5 + reopenRate * 0.5)),
                    name: d[0],
                    reopenRate: parseFloat(reopenRate.toFixed(1)),
                    total: stats.total
                };
            });

        if (points.length === 0) {
            PTChart.showEmpty('rdEfficiencyWrap', '暂无研发效率数据');
            return;
        }

        charts.rdEfficiency = PTChart.create('rdEfficiencyChart', {
            type: 'bubble',
            data: {
                datasets: [{
                    label: '研发人员',
                    data: points,
                    backgroundColor: 'rgba(0,0,0,0.6)',
                    borderColor: '#000000',
                    borderWidth: 1
                }]
            },
            options: {
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                var p = ctx.raw;
                                return [
                                    p.name + '',
                                    '解决数: ' + p.x,
                                    '平均解决时长: ' + p.y + ' 天',
                                    'Reopen率: ' + p.reopenRate + '%',
                                    '总问题数: ' + p.total
                                ];
                            }
                        }
                    }
                },
                scales: {
                    x: { title: { display: true, text: '解决问题数' }, beginAtZero: true },
                    y: { title: { display: true, text: '平均解决时长（天）' }, beginAtZero: true }
                }
            }
        });
    }

    // ========== 每日趋势与累计Bug曲线 ==========
    function renderDailyCumulative(dailyStats) {
        var canvas = document.getElementById('dailyCumulativeChart');
        if (!canvas || !dailyStats || dailyStats.length === 0) {
            PTChart.showEmpty('dailyCumulativeWrap', '暂无每日趋势数据');
            return;
        }
        charts.dailyCumulative = PTChart.destroy(charts.dailyCumulative);

        var displayData = dailyStats.slice(-30);
        var cumNew = 0, cumResolved = 0;
        var cumulativeOpen = displayData.map(function(d) {
            cumNew += d.new_count || 0;
            cumResolved += d.resolved_count || 0;
            return cumNew - cumResolved;
        });

        charts.dailyCumulative = PTChart.create('dailyCumulativeChart', {
            type: 'line',
            data: {
                labels: displayData.map(function(d) { return (d.date || '').substring(5); }),
                datasets: [
                    {
                        label: '每日新增',
                        data: displayData.map(function(d) { return d.new_count || 0; }),
                        borderColor: '#ff3b30',
                        backgroundColor: 'rgba(255,59,48,0.08)',
                        fill: true, tension: 0.3, borderWidth: 2,
                        pointRadius: 3, yAxisID: 'y'
                    },
                    {
                        label: '每日解决',
                        data: displayData.map(function(d) { return d.resolved_count || 0; }),
                        borderColor: '#34c759',
                        backgroundColor: 'rgba(52,199,89,0.08)',
                        fill: true, tension: 0.3, borderWidth: 2,
                        pointRadius: 3, yAxisID: 'y'
                    },
                    {
                        label: '累计未解决',
                        data: cumulativeOpen,
                        borderColor: '#ff9500',
                        backgroundColor: 'rgba(255,149,0,0.05)',
                        fill: false, tension: 0.3, borderWidth: 2.5,
                        borderDash: [5, 3], pointRadius: 2, yAxisID: 'y1'
                    }
                ]
            },
            options: {
                plugins: { legend: { position: 'top' } },
                scales: {
                    y: { type: 'linear', position: 'left', beginAtZero: true, title: { display: true, text: '每日数量' } },
                    y1: { type: 'linear', position: 'right', beginAtZero: true, title: { display: true, text: '累计未解决' }, grid: { drawOnChartArea: false } },
                    x: { grid: { display: false } }
                }
            }
        });
    }

    // ========== 主渲染函数 ==========
    function renderAllEnhancedCharts() {
        var d = window.currentAnalysisData;
        if (!d) return;

        try { renderModuleBar(d.module_stats); } catch(e) { console.warn('Module bar chart failed:', e); }
        try { renderSeverityStacked(d.all_issues, d.module_stats); } catch(e) { console.warn('Severity stacked failed:', e); }
        try { renderRdEfficiency(d.all_issues, d.dev_stats); } catch(e) { console.warn('RD efficiency failed:', e); }
        try { renderDailyCumulative(d.daily_stats); } catch(e) { console.warn('Daily cumulative failed:', e); }
    }

    // ========== 监听分析完成 ==========
    var _rendered = false;
    function checkAndRender() {
        if (_rendered) return;
        if (window.currentAnalysisData && document.getElementById('moduleBarChart')) {
            _rendered = true;
            // 延迟一帧确保 DOM 就绪
            setTimeout(renderAllEnhancedCharts, 100);
        }
    }

    // 轮询检测（最多 30 秒）
    var _pollCount = 0;
    var _pollTimer = setInterval(function() {
        _pollCount++;
        checkAndRender();
        if (_rendered || _pollCount > 60) clearInterval(_pollTimer);
    }, 500);

    // 也监听 resultCard 显示
    document.addEventListener('DOMContentLoaded', function() {
        var resultCard = document.getElementById('resultCard');
        if (resultCard) {
            var observer = new MutationObserver(function() {
                if (resultCard.style.display !== 'none' && resultCard.classList.contains('show')) {
                    checkAndRender();
                }
            });
            observer.observe(resultCard, { attributes: true, childList: true, subtree: true });
        }
        // 立即检查一次
        checkAndRender();
    });

    // 暴露手动渲染接口
    window.CRVizEnhancement = {
        renderAll: renderAllEnhancedCharts,
        rerender: function() { _rendered = false; renderAllEnhancedCharts(); _rendered = true; }
    };
})();
