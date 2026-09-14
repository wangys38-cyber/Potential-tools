/**
 * AI Agent 管理页面 JS v8.0
 */
(function() {
    'use strict';

    // ==================== 初始化 ====================
    document.addEventListener('DOMContentLoaded', function() {
        loadConfig();
        loadStatus();
        loadAlerts();
        loadRuns();
    });

    // ==================== 配置管理 ====================
    window.loadConfig = function() {
        fetch('/api/ai/agent/config')
            .then(r => r.json())
            .then(data => {
                if (data.config) {
                    const c = data.config;
                    document.getElementById('agentEnabled').checked = !!c.enabled;
                    document.getElementById('scheduleType').value = c.schedule_type || 'daily';
                    document.getElementById('scheduleTime').value = c.schedule_time || '09:00';
                    document.getElementById('autoReport').checked = !!c.auto_report;
                    document.getElementById('alertEnabled').checked = !!c.alert_enabled;

                    // 监控指标
                    const metrics = c.monitor_metrics || [];
                    document.querySelectorAll('.checkbox-group input[value]').forEach(cb => {
                        if (cb.value && !cb.value.startsWith('auto') && !cb.value.startsWith('alert')) {
                            cb.checked = metrics.includes(cb.value);
                        }
                    });

                    // 阈值
                    const thresholds = c.alert_threshold || {};
                    document.getElementById('thresholdCritical').value = thresholds.critical_bugs || 5;
                    document.getElementById('thresholdNew').value = thresholds.new_today || 10;
                    document.getElementById('thresholdUnresolved').value = thresholds.unresolved_bugs || 50;
                }
            })
            .catch(err => console.error('加载配置失败:', err));
    };

    window.saveConfig = function() {
        const monitorMetrics = [];
        document.querySelectorAll('.checkbox-group input[value]:checked').forEach(cb => {
            if (cb.value && !cb.value.startsWith('auto') && !cb.value.startsWith('alert')) {
                monitorMetrics.push(cb.value);
            }
        });

        const config = {
            enabled: document.getElementById('agentEnabled').checked ? 1 : 0,
            schedule_type: document.getElementById('scheduleType').value,
            schedule_time: document.getElementById('scheduleTime').value,
            monitor_metrics: monitorMetrics,
            alert_threshold: {
                critical_bugs: parseInt(document.getElementById('thresholdCritical').value) || 5,
                new_today: parseInt(document.getElementById('thresholdNew').value) || 10,
                unresolved_bugs: parseInt(document.getElementById('thresholdUnresolved').value) || 50,
            },
            auto_report: document.getElementById('autoReport').checked ? 1 : 0,
            alert_enabled: document.getElementById('alertEnabled').checked ? 1 : 0,
        };

        fetch('/api/ai/agent/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                showToast('配置已保存');
                loadStatus();
            } else {
                showToast('保存失败: ' + (data.error || '未知错误'));
            }
        })
        .catch(err => showToast('保存失败: ' + err.message));
    };

    // ==================== 手动运行 ====================
    window.runAgentNow = function() {
        if (!confirm('确定要立即运行 Agent 分析吗？')) return;

        const btn = event.target;
        btn.disabled = true;
        btn.textContent = '运行中...';

        fetch('/api/ai/agent/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        })
        .then(r => r.json())
        .then(data => {
            btn.disabled = false;
            btn.textContent = '▶️ 立即运行';

            if (data.status === 'success') {
                showRunResult(data.result);
                loadStatus();
                loadAlerts();
                loadRuns();
            } else {
                showToast('运行失败: ' + (data.error || '未知错误'));
            }
        })
        .catch(err => {
            btn.disabled = false;
            btn.textContent = '▶️ 立即运行';
            showToast('运行失败: ' + err.message);
        });
    };

    function showRunResult(result) {
        const modal = document.getElementById('runResultModal');
        const content = document.getElementById('runResultContent');

        let html = '';

        if (result.status === 'no_data') {
            html = '<div style="text-align:center;padding:30px;color:#86868b;">' + (result.message || '没有可分析的数据') + '</div>';
        } else {
            // 指标概览
            const m = result.metrics || {};
            html += '<h4 style="margin:0 0 12px;font-size:15px;">📊 核心指标</h4>';
            html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:20px;">';
            html += metricCard('总 Bug', m.total_bugs);
            html += metricCard('未解决', m.unresolved_bugs, '#ff9500');
            html += metricCard('致命', m.critical_bugs, '#ff3b30');
            html += metricCard('严重', m.high_bugs, '#ff9500');
            html += metricCard('今日新增', m.new_today);
            html += metricCard('平均修复(天)', m.avg_resolution_days);
            html += '</div>';

            // 异常
            const anomalies = result.anomalies || [];
            html += '<h4 style="margin:0 0 12px;font-size:15px;">⚠️ 异常检测 (' + anomalies.length + ')</h4>';
            if (anomalies.length > 0) {
                html += '<div style="margin-bottom:20px;">';
                anomalies.forEach(a => {
                    const color = a.severity === 'high' ? '#ff3b30' : '#ff9500';
                    html += '<div style="padding:10px 14px;background:#f5f5f7;border-radius:8px;margin-bottom:6px;border-left:3px solid ' + color + ';">';
                    html += '<span style="font-weight:600;color:' + color + ';">' + a.metric + '</span>: ' + a.message;
                    html += '</div>';
                });
                html += '</div>';
            } else {
                html += '<div style="color:#34c759;margin-bottom:20px;">✅ 未检测到异常</div>';
            }

            // 报告
            if (result.report) {
                html += '<h4 style="margin:0 0 12px;font-size:15px;">📋 生成的报告</h4>';
                html += '<pre style="max-height:300px;overflow:auto;">' + escapeHtml(result.report) + '</pre>';
            }
        }

        content.innerHTML = html;
        modal.style.display = 'flex';
    }

    function metricCard(label, value, color) {
        return '<div style="background:#f5f5f7;padding:12px;border-radius:8px;text-align:center;">' +
            '<div style="font-size:11px;color:#86868b;margin-bottom:2px;">' + label + '</div>' +
            '<div style="font-size:18px;font-weight:600;color:' + (color || '#1d1d1f') + ';">' + (value || 0) + '</div>' +
            '</div>';
    }

    window.closeRunResult = function() {
        document.getElementById('runResultModal').style.display = 'none';
    };

    // ==================== 状态 ====================
    window.loadStatus = function() {
        fetch('/api/ai/agent/status')
            .then(r => r.json())
            .then(data => {
                // 状态指示器
                const dot = document.getElementById('statusDot');
                const text = document.getElementById('statusText');
                if (data.enabled && data.scheduler_running) {
                    dot.className = 'status-dot running';
                    text.textContent = '运行中';
                } else if (data.enabled) {
                    dot.className = 'status-dot';
                    dot.style.background = '#ff9500';
                    text.textContent = '已启用（调度器未运行）';
                } else {
                    dot.className = 'status-dot stopped';
                    text.textContent = '未启用';
                }

                // 详细状态
                document.getElementById('lastRunTime').textContent = data.last_run_at ? formatTime(data.last_run_at) : '从未运行';
                document.getElementById('nextRunTime').textContent = data.next_run_at ? formatTime(data.next_run_at) : '-';
                document.getElementById('schedulerStatus').textContent = data.scheduler_running ? '✅ 运行中' : '⏹️ 未运行';
                document.getElementById('unreadAlerts').textContent = data.unread_alerts || 0;
            })
            .catch(err => console.error('加载状态失败:', err));
    };

    window.refreshStatus = function() {
        loadStatus();
        showToast('已刷新');
    };

    // ==================== 告警 ====================
    window.loadAlerts = function() {
        fetch('/api/ai/agent/alerts?limit=20')
            .then(r => r.json())
            .then(data => {
                const panel = document.getElementById('alertsPanel');
                const alerts = data.alerts || [];

                if (alerts.length === 0) {
                    panel.innerHTML = '<div class="empty-state">暂无告警</div>';
                    return;
                }

                let html = '';
                alerts.forEach(alert => {
                    const icon = alert.severity === 'high' ? '🔴' : alert.severity === 'medium' ? '🟡' : '🟢';
                    const readClass = alert.is_read ? ' read' : '';
                    html += '<div class="alert-item ' + alert.severity + readClass + '" onclick="readAlert(' + alert.id + ')">';
                    html += '<div class="alert-icon">' + icon + '</div>';
                    html += '<div class="alert-content">';
                    html += '<div class="alert-title">' + escapeHtml(alert.title) + '</div>';
                    html += '<div class="alert-desc">' + escapeHtml(alert.description) + '</div>';
                    html += '</div>';
                    html += '<div class="alert-time">' + formatTime(alert.created_at) + '</div>';
                    html += '</div>';
                });
                panel.innerHTML = html;
            })
            .catch(err => console.error('加载告警失败:', err));
    };

    window.readAlert = function(alertId) {
        fetch('/api/ai/agent/alerts/' + alertId + '/read', { method: 'POST' })
            .then(() => {
                loadAlerts();
                loadStatus();
            });
    };

    window.markAllRead = function() {
        fetch('/api/ai/agent/alerts/read-all', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                showToast('已标记 ' + (data.marked_count || 0) + ' 条告警为已读');
                loadAlerts();
                loadStatus();
            });
    };

    window.refreshAlerts = function() {
        loadAlerts();
    };

    // ==================== 运行历史 ====================
    window.loadRuns = function() {
        fetch('/api/ai/agent/runs?limit=10')
            .then(r => r.json())
            .then(data => {
                const panel = document.getElementById('runsPanel');
                const runs = data.runs || [];

                if (runs.length === 0) {
                    panel.innerHTML = '<div class="empty-state">暂无运行记录</div>';
                    return;
                }

                let html = '';
                runs.forEach(run => {
                    const statusClass = run.status === 'completed' ? 'completed' : run.status === 'failed' ? 'failed' : 'running';
                    const triggerText = run.trigger_type === 'manual' ? '手动触发' : '定时运行';
                    const metrics = run.metrics_summary || {};
                    const metricText = metrics.total_bugs ? 'Bug:' + metrics.total_bugs + ' 未解决:' + metrics.unresolved_bugs : '';

                    html += '<div class="run-item" onclick="viewRunDetail(' + run.id + ')">';
                    html += '<div class="run-status ' + statusClass + '"></div>';
                    html += '<div class="run-info">';
                    html += '<div class="run-trigger">' + triggerText + ' - ' + run.status + '</div>';
                    html += '<div class="run-time">' + formatTime(run.started_at) + ' (' + (run.duration_ms / 1000).toFixed(1) + 's)</div>';
                    html += '</div>';
                    html += '<div class="run-metrics">' + metricText + '</div>';
                    html += '</div>';
                });
                panel.innerHTML = html;
            })
            .catch(err => console.error('加载运行历史失败:', err));
    };

    window.viewRunDetail = function(runId) {
        // 可以扩展为查看详细报告
        showToast('运行记录 #' + runId);
    };

    // ==================== 工具函数 ====================
    function formatTime(timestamp) {
        if (!timestamp) return '-';
        const d = new Date(timestamp * 1000);
        return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function showToast(msg) {
        const toast = document.createElement('div');
        toast.style.cssText = 'position:fixed;top:20px;left:50%;transform:translateX(-50%);background:#1d1d1f;color:#fff;padding:10px 20px;border-radius:10px;z-index:99999;font-size:13px;box-shadow:0 4px 12px rgba(0,0,0,0.15);';
        toast.textContent = msg;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2500);
    }

})();
