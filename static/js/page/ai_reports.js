/**
 * 智能报告中心 JS v8.0
 */
(function() {
    'use strict';

    let editingScheduleId = null;

    document.addEventListener('DOMContentLoaded', function() {
        loadSchedules();
        loadLogs();
        loadTemplates();
    });

    // ==================== 推送计划 ====================
    window.loadSchedules = function() {
        fetch('/api/ai/report/schedules')
            .then(r => r.json())
            .then(data => {
                const panel = document.getElementById('schedulesPanel');
                const schedules = data.schedules || [];

                if (schedules.length === 0) {
                    panel.innerHTML = '<div class="empty-state">暂无推送计划，点击右上角「新建推送计划」创建</div>';
                    return;
                }

                let html = '';
                schedules.forEach(s => {
                    const disabled = !s.enabled;
                    const recipients = Array.isArray(s.recipients) ? s.recipients.join(', ') : (s.recipients || '');
                    html += '<div class="schedule-card' + (disabled ? ' disabled' : '') + '">';
                    html += '<div class="schedule-header">';
                    html += '<span class="schedule-name">' + escapeHtml(s.name || '未命名') + '</span>';
                    html += '<span class="schedule-status' + (disabled ? ' disabled' : '') + '">' + (s.enabled ? '已启用' : '已停用') + '</span>';
                    html += '</div>';
                    html += '<div class="schedule-info">';
                    html += '📅 ' + (s.schedule_type === 'daily' ? '每天' : s.schedule_type === 'weekly' ? '每周' : '每月') + ' ' + (s.schedule_time || '09:00') + '<br>';
                    html += '📧 收件人: ' + escapeHtml(recipients || '未设置') + '<br>';
                    if (s.last_sent_at) html += '🕐 上次发送: ' + formatTime(s.last_sent_at);
                    if (s.next_send_at) html += ' | 下次: ' + formatTime(s.next_send_at);
                    html += '</div>';
                    html += '<div class="schedule-actions">';
                    html += '<button class="btn btn-primary btn-sm" onclick="runSchedule(' + s.id + ')">▶️ 立即推送</button>';
                    html += '<button class="btn btn-secondary btn-sm" onclick="editSchedule(' + s.id + ')">✏️ 编辑</button>';
                    html += '<button class="btn btn-secondary btn-sm" onclick="deleteSchedule(' + s.id + ')">🗑️ 删除</button>';
                    html += '</div></div>';
                });
                panel.innerHTML = html;
            })
            .catch(err => {
                document.getElementById('schedulesPanel').innerHTML = '<div class="empty-state">加载失败: ' + err.message + '</div>';
            });
    };

    window.showScheduleModal = function() {
        editingScheduleId = null;
        document.getElementById('scheduleModalTitle').textContent = '新建推送计划';
        document.getElementById('scheduleName').value = '';
        document.getElementById('scheduleEnabled').checked = true;
        document.getElementById('scheduleType').value = 'daily';
        document.getElementById('scheduleTime').value = '09:00';
        document.getElementById('scheduleSubject').value = '质量日报 - {date}';
        document.getElementById('scheduleRecipients').value = '';
        document.getElementById('scheduleAIAnalysis').checked = true;
        document.getElementById('scheduleModal').style.display = 'flex';
    };

    window.editSchedule = function(id) {
        fetch('/api/ai/report/schedules')
            .then(r => r.json())
            .then(data => {
                const s = (data.schedules || []).find(x => x.id === id);
                if (!s) return;
                editingScheduleId = id;
                document.getElementById('scheduleModalTitle').textContent = '编辑推送计划';
                document.getElementById('scheduleName').value = s.name || '';
                document.getElementById('scheduleEnabled').checked = !!s.enabled;
                document.getElementById('scheduleType').value = s.schedule_type || 'daily';
                document.getElementById('scheduleTime').value = s.schedule_time || '09:00';
                document.getElementById('scheduleSubject').value = s.subject_format || '质量日报 - {date}';
                const recipients = Array.isArray(s.recipients) ? s.recipients.join(', ') : (s.recipients || '');
                document.getElementById('scheduleRecipients').value = recipients;
                document.getElementById('scheduleModal').style.display = 'flex';
            });
    };

    window.closeScheduleModal = function() {
        document.getElementById('scheduleModal').style.display = 'none';
    };

    window.saveSchedule = function() {
        const recipients = document.getElementById('scheduleRecipients').value
            .split(',').map(r => r.trim()).filter(r => r);

        const data = {
            name: document.getElementById('scheduleName').value || '未命名',
            enabled: document.getElementById('scheduleEnabled').checked ? 1 : 0,
            schedule_type: document.getElementById('scheduleType').value,
            schedule_time: document.getElementById('scheduleTime').value,
            subject_format: document.getElementById('scheduleSubject').value,
            recipients: recipients,
            template_id: 0,
        };

        if (editingScheduleId) {
            data.id = editingScheduleId;
        }

        fetch('/api/ai/report/schedules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(r => r.json())
        .then(res => {
            if (res.status === 'success') {
                showToast('保存成功');
                closeScheduleModal();
                loadSchedules();
            } else {
                showToast('保存失败: ' + (res.error || '未知错误'));
            }
        })
        .catch(err => showToast('保存失败: ' + err.message));
    };

    window.deleteSchedule = function(id) {
        if (!confirm('确定要删除这个推送计划吗？')) return;
        fetch('/api/ai/report/schedules/' + id, { method: 'DELETE' })
            .then(r => r.json())
            .then(() => {
                showToast('已删除');
                loadSchedules();
            });
    };

    window.runSchedule = function(id) {
        if (!confirm('确定要立即推送报告吗？')) return;
        showToast('正在推送...');
        fetch('/api/ai/report/schedules/' + id + '/run', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success' || data.status === 'partial') {
                    showToast('推送完成，发送 ' + (data.sent_count || 0) + ' 封');
                    showPreview(data.report);
                } else {
                    showToast('推送失败: ' + (data.error || '未知错误'));
                }
                loadLogs();
                loadSchedules();
            })
            .catch(err => showToast('推送失败: ' + err.message));
    };

    // ==================== 推送历史 ====================
    window.loadLogs = function() {
        fetch('/api/ai/report/logs?limit=15')
            .then(r => r.json())
            .then(data => {
                const panel = document.getElementById('logsPanel');
                const logs = data.logs || [];

                if (logs.length === 0) {
                    panel.innerHTML = '<div class="empty-state">暂无推送记录</div>';
                    return;
                }

                let html = '';
                logs.forEach(log => {
                    const recipients = Array.isArray(log.recipients) ? log.recipients.join(', ') : (log.recipients || '');
                    html += '<div class="log-item">';
                    html += '<div class="log-status ' + log.status + '"></div>';
                    html += '<div class="log-info">';
                    html += '<div class="log-subject">' + escapeHtml(log.subject || '无主题') + '</div>';
                    html += '<div class="log-meta">' + formatTime(log.sent_at) + ' | ' + escapeHtml(recipients) + ' | ' + (log.duration_ms / 1000).toFixed(1) + 's</div>';
                    html += '</div></div>';
                });
                panel.innerHTML = html;
            })
            .catch(err => {
                document.getElementById('logsPanel').innerHTML = '<div class="empty-state">加载失败</div>';
            });
    };

    // ==================== 模板 ====================
    window.loadTemplates = function() {
        fetch('/api/ai/report/templates')
            .then(r => r.json())
            .then(data => {
                const panel = document.getElementById('templatesPanel');
                let html = '';

                // 内置模板
                (data.builtin_templates || []).forEach(t => {
                    html += '<div class="template-item">';
                    html += '<span class="template-icon">📄</span>';
                    html += '<div class="template-info">';
                    html += '<div class="template-name">' + escapeHtml(t.name) + '</div>';
                    html += '<div class="template-type">' + t.template_type + ' | ' + (t.include_metrics || []).length + ' 个指标</div>';
                    html += '</div>';
                    html += '<span class="template-badge">内置</span>';
                    html += '</div>';
                });

                // 自定义模板
                (data.templates || []).forEach(t => {
                    html += '<div class="template-item">';
                    html += '<span class="template-icon">📝</span>';
                    html += '<div class="template-info">';
                    html += '<div class="template-name">' + escapeHtml(t.name || '未命名') + '</div>';
                    html += '<div class="template-type">' + t.template_type + ' | 自定义</div>';
                    html += '</div></div>';
                });

                panel.innerHTML = html || '<div class="empty-state">暂无模板</div>';
            })
            .catch(err => {
                document.getElementById('templatesPanel').innerHTML = '<div class="empty-state">加载失败</div>';
            });
    };

    // ==================== 预览 ====================
    function showPreview(report) {
        if (!report) return;
        document.getElementById('previewContent').innerHTML = report.html_content || '<pre>' + escapeHtml(report.content || '') + '</pre>';
        document.getElementById('previewModal').style.display = 'flex';
    }

    window.closePreviewModal = function() {
        document.getElementById('previewModal').style.display = 'none';
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
