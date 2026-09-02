/**
 * 管理员性能监控看板 JS
 * - 实时性能指标展示
 * - CPU/内存趋势图表（Canvas 绘制）
 * - 慢查询列表
 * - 告警历史
 * - 告警配置管理
 */
(function () {
    'use strict';

    var refreshTimer = null;
    var currentTab = 'realtime';

    // ==================== Tab 切换 ====================
    function switchTab(tab) {
        currentTab = tab;
        var tabs = ['realtime', 'alerts', 'config'];
        tabs.forEach(function (t) {
            var btn = document.getElementById('tab' + t.charAt(0).toUpperCase() + t.slice(1));
            var content = document.getElementById('tabContent' + t.charAt(0).toUpperCase() + t.slice(1));
            if (btn) {
                if (t === tab) {
                    btn.classList.add('active');
                    btn.style.color = '#1d1d1f';
                    btn.style.borderBottomColor = '#0071e3';
                } else {
                    btn.classList.remove('active');
                    btn.style.color = '#86868b';
                    btn.style.borderBottomColor = 'transparent';
                }
            }
            if (content) {
                content.style.display = (t === tab) ? 'block' : 'none';
            }
        });

        if (tab === 'alerts') loadAlerts();
        if (tab === 'config') loadConfig();
    }

    // ==================== 性能数据加载 ====================
    function loadPerformance() {
        fetch('/api/admin/performance')
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (data.status !== 'success') return;
                updateMetrics(data);
                drawCharts(data.system_history || []);
                renderSlowLogs(data.slow_logs || []);
            })
            .catch(function (e) { console.warn('加载性能数据失败:', e); });
    }

    function updateMetrics(data) {
        var rs = data.request_stats || {};
        var aw = data.alert_window || {};
        var sys = (data.system && data.system.current) || {};

        // 总请求数
        document.getElementById('metricTotalRequests').textContent = formatNumber(rs.total_requests || 0);

        // P95/P50/P99
        var p95 = rs.p95_ms || 0;
        var p95El = document.getElementById('metricP95');
        p95El.textContent = p95 + 'ms';
        p95El.className = 'value' + (p95 > 3000 ? ' critical' : p95 > 1000 ? ' warning' : '');
        document.getElementById('metricP50').textContent = (rs.p50_ms || 0) + 'ms';
        document.getElementById('metricP99').textContent = (rs.p99_ms || 0) + 'ms';

        // 5xx 错误率
        var errRate = aw.error_rate_pct || 0;
        var errEl = document.getElementById('metricErrorRate');
        errEl.textContent = errRate + '%';
        errEl.className = 'value' + (errRate > 1 ? ' critical' : errRate > 0.5 ? ' warning' : '');
        document.getElementById('metricErrorCount').textContent = aw.error_5xx || 0;
        document.getElementById('metricWindowTotal').textContent = aw.total || 0;

        // 慢查询
        document.getElementById('metricSlowCount').textContent = rs.slow_requests || 0;
        document.getElementById('metricSlowRate').textContent = (rs.slow_rate_pct || 0) + '%';

        // CPU
        var cpu = sys.cpu_percent || 0;
        var cpuEl = document.getElementById('metricCPU');
        cpuEl.textContent = cpu + '%';
        cpuEl.className = 'value' + (cpu > 80 ? ' critical' : cpu > 60 ? ' warning' : '');
        document.getElementById('metricLoad').textContent = sys.load_avg_1m || 0;

        // 内存
        var mem = sys.mem_percent || 0;
        var memEl = document.getElementById('metricMemory');
        memEl.textContent = mem + '%';
        memEl.className = 'value' + (mem > 85 ? ' critical' : mem > 70 ? ' warning' : '');
        document.getElementById('metricMemUsed').textContent = formatNumber(sys.mem_used_mb || 0);
        document.getElementById('metricMemTotal').textContent = formatNumber(sys.mem_total_mb || 0);
    }

    // ==================== Canvas 图表绘制 ====================
    function drawCharts(history) {
        drawLineChart('cpuChart', history, 'cpu_percent', '#ef4444', 80);
        drawLineChart('memChart', history, 'mem_percent', '#f59e0b', 85);
    }

    function drawLineChart(canvasId, data, key, color, threshold) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var ctx = canvas.getContext('2d');
        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);

        var w = rect.width;
        var h = rect.height;
        var padding = { top: 10, right: 10, bottom: 24, left: 40 };
        var chartW = w - padding.left - padding.right;
        var chartH = h - padding.top - padding.bottom;

        ctx.clearRect(0, 0, w, h);

        if (!data || data.length < 2) {
            ctx.fillStyle = '#86868b';
            ctx.font = '12px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('数据采集中...', w / 2, h / 2);
            return;
        }

        var values = data.map(function (d) { return d[key] || 0; });
        var maxVal = Math.max(100, Math.max.apply(null, values) + 10);
        var minVal = 0;

        // 网格线
        ctx.strokeStyle = '#f0f0f0';
        ctx.lineWidth = 1;
        ctx.fillStyle = '#86868b';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'right';
        for (var i = 0; i <= 4; i++) {
            var y = padding.top + chartH * (1 - i / 4);
            var val = Math.round(minVal + (maxVal - minVal) * i / 4);
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(w - padding.right, y);
            ctx.stroke();
            ctx.fillText(val + '%', padding.left - 6, y + 3);
        }

        // 阈值线
        if (threshold) {
            var ty = padding.top + chartH * (1 - threshold / maxVal);
            ctx.strokeStyle = '#ef4444';
            ctx.setLineDash([4, 4]);
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(padding.left, ty);
            ctx.lineTo(w - padding.right, ty);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = '#ef4444';
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText('阈值 ' + threshold + '%', w - padding.right - 60, ty - 4);
        }

        // 数据线
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        data.forEach(function (d, i) {
            var x = padding.left + chartW * (i / (data.length - 1));
            var y = padding.top + chartH * (1 - (d[key] || 0) / maxVal);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // 填充区域
        ctx.lineTo(padding.left + chartW, padding.top + chartH);
        ctx.lineTo(padding.left, padding.top + chartH);
        ctx.closePath();
        ctx.fillStyle = color + '15';
        ctx.fill();

        // 时间标签
        ctx.fillStyle = '#86868b';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        var labelStep = Math.max(1, Math.floor(data.length / 5));
        for (var j = 0; j < data.length; j += labelStep) {
            var lx = padding.left + chartW * (j / (data.length - 1));
            ctx.fillText(data[j].time_str || '', lx, h - 6);
        }
    }

    // ==================== 慢查询渲染 ====================
    function renderSlowLogs(logs) {
        var tbody = document.getElementById('slowLogsBody');
        if (!tbody) return;
        if (!logs || logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#86868b;padding:20px;">暂无慢查询记录</td></tr>';
            return;
        }
        tbody.innerHTML = logs.map(function (log) {
            var statusClass = log.status >= 500 ? 'color:#ef4444;font-weight:600;' : '';
            return '<tr>' +
                '<td>' + (log.time || '') + '</td>' +
                '<td><code>' + (log.method || '') + '</code></td>' +
                '<td style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + (log.path || '') + '">' + (log.path || '') + '</td>' +
                '<td style="color:#f59e0b;font-weight:600;">' + (log.duration_ms || 0) + 'ms</td>' +
                '<td style="' + statusClass + '">' + (log.status || '') + '</td>' +
                '</tr>';
        }).join('');
    }

    // ==================== 告警历史 ====================
    function loadAlerts() {
        fetch('/api/admin/alerts?limit=100')
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (data.status !== 'success') return;
                renderAlerts(data.alerts || []);
                if (data.summary) {
                    document.getElementById('alert24h').textContent = data.summary.alerts_last_24h || 0;
                    document.getElementById('alertTotal').textContent = data.summary.total_alerts || 0;
                }
            })
            .catch(function (e) { console.warn('加载告警历史失败:', e); });
    }

    function renderAlerts(alerts) {
        var tbody = document.getElementById('alertsBody');
        if (!tbody) return;
        if (!alerts || alerts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#86868b;padding:20px;">暂无告警记录</td></tr>';
            return;
        }
        tbody.innerHTML = alerts.map(function (a) {
            var levelClass = a.level === 'critical' ? 'critical' : 'warning';
            var details = '';
            if (a.metrics && typeof a.metrics === 'object') {
                details = Object.keys(a.metrics).map(function (k) {
                    return k + ': ' + a.metrics[k];
                }).join(' | ');
            }
            return '<tr>' +
                '<td>' + (a.time_str || '') + '</td>' +
                '<td>' + (a.type_name || a.type || '') + '</td>' +
                '<td><span class="alert-badge ' + levelClass + '">' + (a.level || '').toUpperCase() + '</span></td>' +
                '<td style="font-weight:600;">' + (a.current_value || '') + '</td>' +
                '<td>' + (a.threshold || '') + '</td>' +
                '<td style="font-size:12px;color:#86868b;max-width:300px;">' + (details || '-') + '</td>' +
                '</tr>';
        }).join('');
    }

    // ==================== 告警配置 ====================
    function loadConfig() {
        fetch('/api/admin/alerts/config')
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (data.status !== 'success') return;
                document.getElementById('cfgEnabled').checked = !!data.enabled;
                document.getElementById('cfgAlertErrorRate').checked = data.alert_types ? !!data.alert_types.error_rate : true;
                document.getElementById('cfgAlertLatency').checked = data.alert_types ? !!data.alert_types.latency_p95 : true;
                document.getElementById('cfgAlertCPU').checked = data.alert_types ? !!data.alert_types.cpu_high : true;
                document.getElementById('cfgAlertMemory').checked = data.alert_types ? !!data.alert_types.memory_high : true;

                var t = data.thresholds || {};
                document.getElementById('cfgThresholdErrorRate').value = t.error_rate_pct || 1;
                document.getElementById('cfgThresholdLatency').value = t.latency_p95_ms || 3000;
                document.getElementById('cfgThresholdCPU').value = t.cpu_percent || 80;
                document.getElementById('cfgThresholdMemory').value = t.memory_percent || 85;

                // Webhook 不回显完整 URL（安全），只显示是否已配置
                var webhookInput = document.getElementById('cfgWebhook');
                webhookInput.placeholder = data.feishu_webhook_configured ? '已配置（留空不修改）' : 'https://open.feishu.cn/open-apis/bot/v2/hook/xxx';
            })
            .catch(function (e) { console.warn('加载告警配置失败:', e); });
    }

    function saveConfig() {
        var payload = {
            enabled: document.getElementById('cfgEnabled').checked,
            thresholds: {
                error_rate_pct: parseFloat(document.getElementById('cfgThresholdErrorRate').value) || 1,
                latency_p95_ms: parseInt(document.getElementById('cfgThresholdLatency').value) || 3000,
                cpu_percent: parseInt(document.getElementById('cfgThresholdCPU').value) || 80,
                memory_percent: parseInt(document.getElementById('cfgThresholdMemory').value) || 85,
            },
            alert_types: {
                error_rate: document.getElementById('cfgAlertErrorRate').checked,
                latency_p95: document.getElementById('cfgAlertLatency').checked,
                cpu_high: document.getElementById('cfgAlertCPU').checked,
                memory_high: document.getElementById('cfgAlertMemory').checked,
            }
        };

        var webhook = document.getElementById('cfgWebhook').value.trim();
        if (webhook) payload.feishu_webhook = webhook;

        var secret = document.getElementById('cfgSecret').value.trim();
        if (secret) payload.feishu_secret = secret;

        var msgEl = document.getElementById('configMsg');
        fetch('/api/admin/alerts/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (data.status === 'success') {
                    msgEl.textContent = '✓ 配置已保存';
                    msgEl.style.color = '#34c759';
                    document.getElementById('cfgWebhook').value = '';
                    document.getElementById('cfgSecret').value = '';
                } else {
                    msgEl.textContent = '✗ 保存失败: ' + (data.error || '未知错误');
                    msgEl.style.color = '#ef4444';
                }
                setTimeout(function () { msgEl.textContent = ''; }, 3000);
            })
            .catch(function (e) {
                msgEl.textContent = '✗ 保存失败: ' + e.message;
                msgEl.style.color = '#ef4444';
            });
    }

    function testAlert() {
        var msgEl = document.getElementById('configMsg');
        msgEl.textContent = '发送中...';
        msgEl.style.color = '#86868b';
        fetch('/api/admin/alerts/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'error_rate' })
        })
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (data.status === 'success') {
                    msgEl.textContent = '✓ ' + (data.message || '测试告警发送成功');
                    msgEl.style.color = '#34c759';
                } else {
                    msgEl.textContent = '✗ ' + (data.error || '发送失败');
                    msgEl.style.color = '#ef4444';
                }
            })
            .catch(function (e) {
                msgEl.textContent = '✗ 发送失败: ' + e.message;
                msgEl.style.color = '#ef4444';
            });
    }

    // ==================== 工具函数 ====================
    function formatNumber(n) {
        if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
        return n.toString();
    }

    function refresh() {
        if (currentTab === 'realtime') loadPerformance();
        if (currentTab === 'alerts') loadAlerts();
    }

    function startAutoRefresh() {
        if (refreshTimer) clearInterval(refreshTimer);
        refreshTimer = setInterval(refresh, 10000);
    }

    // ==================== 初始化 ====================
    function init() {
        switchTab('realtime');
        loadPerformance();
        startAutoRefresh();
    }

    // 页面加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // 暴露全局接口
    window.AdminPerf = {
        switchTab: switchTab,
        refresh: refresh,
        loadPerformance: loadPerformance,
        loadAlerts: loadAlerts,
        loadConfig: loadConfig,
        saveConfig: saveConfig,
        testAlert: testAlert,
    };
})();
