/**
 * 插件管理页面 JS v8.1
 */
(function() {
    'use strict';

    let currentSettingsPlugin = null;

    document.addEventListener('DOMContentLoaded', function() {
        loadPlugins();
    });

    window.loadPlugins = function() {
        fetch('/api/plugins/list')
            .then(r => r.json())
            .then(data => {
                const plugins = data.plugins || [];
                renderPlugins(plugins);
                updateStats(plugins);
            })
            .catch(err => {
                document.getElementById('pluginsGrid').innerHTML =
                    '<div class="empty-state">加载失败: ' + err.message + '</div>';
            });
    };

    function renderPlugins(plugins) {
        const grid = document.getElementById('pluginsGrid');
        if (plugins.length === 0) {
            grid.innerHTML = '<div class="empty-state">暂无插件，将插件放入 plugins/ 目录即可自动发现</div>';
            return;
        }

        let html = '';
        plugins.forEach(p => {
            const enabled = p.enabled;
            html += '<div class="plugin-card' + (enabled ? '' : ' disabled') + '">';
            html += '<div class="plugin-header">';
            html += '<div>';
            html += '<div class="plugin-name">' + escapeHtml(p.name) + '</div>';
            html += '<div style="font-size:11px;color:#aeaeb2;margin-top:2px;">' + escapeHtml(p.id) + '</div>';
            html += '</div>';
            html += '<span class="status-badge ' + (enabled ? 'enabled' : 'disabled') + '">' + (enabled ? '已启用' : '已禁用') + '</span>';
            html += '</div>';
            html += '<div class="plugin-description">' + escapeHtml(p.description || '暂无描述') + '</div>';
            html += '<div class="plugin-meta">';
            html += '<span>v' + escapeHtml(p.version) + '</span>';
            html += '<span>👤 ' + escapeHtml(p.author || '未知') + '</span>';
            html += '</div>';
            if (p.permissions && p.permissions.length > 0) {
                html += '<div class="plugin-permissions">';
                p.permissions.forEach(perm => {
                    html += '<span class="permission-tag">' + escapeHtml(perm) + '</span>';
                });
                html += '</div>';
            }
            html += '<div class="plugin-actions">';
            if (enabled) {
                html += '<button class="btn btn-secondary" onclick="disablePlugin(\'' + p.id + '\')">⏸ 禁用</button>';
            } else {
                html += '<button class="btn btn-primary" onclick="enablePlugin(\'' + p.id + '\')">▶ 启用</button>';
            }
            if (p.settings_schema && p.settings_schema.length > 0) {
                html += '<button class="btn btn-secondary" onclick="openSettings(\'' + p.id + '\')">⚙️ 配置</button>';
            }
            html += '</div></div>';
        });
        grid.innerHTML = html;
    }

    function updateStats(plugins) {
        const enabled = plugins.filter(p => p.enabled).length;
        document.getElementById('totalCount').textContent = plugins.length;
        document.getElementById('enabledCount').textContent = enabled;
        document.getElementById('disabledCount').textContent = plugins.length - enabled;
    }

    window.enablePlugin = function(pluginId) {
        fetch('/api/plugins/' + pluginId + '/enable', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    showToast('✅ ' + data.message);
                    loadPlugins();
                } else {
                    showToast('❌ ' + (data.error || '启用失败'));
                }
            });
    };

    window.disablePlugin = function(pluginId) {
        fetch('/api/plugins/' + pluginId + '/disable', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    showToast('✅ ' + data.message);
                    loadPlugins();
                } else {
                    showToast('❌ ' + (data.error || '禁用失败'));
                }
            });
    };

    window.reloadPlugins = function() {
        fetch('/api/plugins/reload', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    showToast('✅ ' + data.message);
                    loadPlugins();
                } else {
                    showToast('❌ 重新加载失败');
                }
            });
    };

    window.openSettings = function(pluginId) {
        currentSettingsPlugin = pluginId;
        document.getElementById('settingsTitle').textContent = '插件配置 - ' + pluginId;
        document.getElementById('settingsBody').innerHTML = '<div class="empty-state">加载中...</div>';
        document.getElementById('settingsModal').style.display = 'flex';

        fetch('/api/plugins/' + pluginId + '/settings')
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    renderSettingsForm(data.schema, data.settings);
                } else {
                    document.getElementById('settingsBody').innerHTML =
                        '<div class="empty-state">加载失败</div>';
                }
            });
    };

    function renderSettingsForm(schema, values) {
        let html = '';
        (schema || []).forEach(field => {
            const value = values[field.key] || field.default || '';
            html += '<div class="form-group">';
            html += '<label>' + escapeHtml(field.name || field.key) + '</label>';
            if (field.type === 'textarea') {
                html += '<textarea id="setting_' + field.key + '" rows="3">' + escapeHtml(value) + '</textarea>';
            } else if (field.type === 'select' && field.options) {
                html += '<select id="setting_' + field.key + '">';
                field.options.forEach(opt => {
                    html += '<option value="' + escapeHtml(opt.value) + '"' + (opt.value == value ? ' selected' : '') + '>' + escapeHtml(opt.label) + '</option>';
                });
                html += '</select>';
            } else if (field.type === 'boolean') {
                html += '<select id="setting_' + field.key + '">';
                html += '<option value="true"' + (value === true || value === 'true' ? ' selected' : '') + '>是</option>';
                html += '<option value="false"' + (!value || value === 'false' ? ' selected' : '') + '>否</option>';
                html += '</select>';
            } else {
                html += '<input type="' + (field.type || 'text') + '" id="setting_' + field.key + '" value="' + escapeHtml(value) + '"' + (field.required ? ' required' : '') + '>';
            }
            if (field.description) {
                html += '<div style="font-size:11px;color:#86868b;margin-top:4px;">' + escapeHtml(field.description) + '</div>';
            }
            html += '</div>';
        });
        document.getElementById('settingsBody').innerHTML = html || '<div class="empty-state">此插件无需配置</div>';
    }

    window.saveSettings = function() {
        if (!currentSettingsPlugin) return;
        const settings = {};
        document.querySelectorAll('#settingsBody [id^="setting_"]').forEach(el => {
            const key = el.id.replace('setting_', '');
            settings[key] = el.value;
        });
        fetch('/api/plugins/' + currentSettingsPlugin + '/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                showToast('✅ 配置已保存');
                closeSettingsModal();
            } else {
                showToast('❌ 保存失败');
            }
        });
    };

    window.closeSettingsModal = function() {
        document.getElementById('settingsModal').style.display = 'none';
        currentSettingsPlugin = null;
    };

    window.showInstallModal = function() {
        document.getElementById('installModal').style.display = 'flex';
    };

    window.closeInstallModal = function() {
        document.getElementById('installModal').style.display = 'none';
    };

    window.switchInstallSource = function() {
        const source = document.getElementById('installSource').value;
        document.getElementById('localInstall').style.display = source === 'local' ? 'block' : 'none';
        document.getElementById('urlInstall').style.display = source === 'url' ? 'block' : 'none';
        document.getElementById('marketInstall').style.display = source === 'market' ? 'block' : 'none';
    };

    window.installFromUrl = function() {
        const url = document.getElementById('pluginUrl').value.trim();
        if (!url) {
            showToast('请输入下载地址');
            return;
        }
        showToast('⏳ 正在下载安装...');
        // TODO: 实现 URL 安装
        setTimeout(() => {
            showToast('⚠️ URL 安装功能开发中，请使用本地目录安装');
        }, 1000);
    };

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
