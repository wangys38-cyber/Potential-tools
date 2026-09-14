/**
 * 插件管理页面 JS v8.1
 * 包含已安装插件管理、插件市场、更新检查
 */
(function() {
    'use strict';

    let currentSettingsPlugin = null;
    let currentCategory = '';
    let marketPlugins = [];
    let categories = [];
    let selectedTemplate = 'basic';
    let selectedPermissions = [];

    document.addEventListener('DOMContentLoaded', function() {
        loadPlugins();
        loadMarket();
        checkUpdates();
    });

    // ==================== 标签页切换 ====================

    window.switchTab = function(tab) {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelector(`.tab[data-tab="${tab}"]`).classList.add('active');
        document.getElementById('tab-installed').style.display = tab === 'installed' ? 'block' : 'none';
        document.getElementById('tab-market').style.display = tab === 'market' ? 'block' : 'none';
        document.getElementById('tab-updates').style.display = tab === 'updates' ? 'block' : 'none';
    };

    // ==================== 已安装插件 ====================

    window.loadPlugins = function() {
        fetch('/api/plugins/list')
            .then(r => r.json())
            .then(data => {
                const plugins = data.plugins || [];
                renderPlugins(plugins);
                updateStats(plugins);
                document.getElementById('installedBadge').textContent = plugins.length;
            })
            .catch(err => {
                document.getElementById('pluginsGrid').innerHTML =
                    '<div class="empty-state">加载失败: ' + err.message + '</div>';
            });
    };

    function renderPlugins(plugins) {
        const grid = document.getElementById('pluginsGrid');
        if (plugins.length === 0) {
            grid.innerHTML = '<div class="empty-state">暂无插件，将插件放入 plugins/ 目录或前往插件市场安装</div>';
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
            html += '<button class="btn btn-secondary" onclick="runSecurityAudit(\'' + p.id + '\')">🔒 审计</button>';
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
                    loadMarket();
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
                    loadMarket();
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
                    loadMarket();
                    checkUpdates();
                } else {
                    showToast('❌ 重新加载失败');
                }
            });
    };

    // ==================== 插件市场 ====================

    function loadMarket() {
        fetch('/api/plugins/market')
            .then(r => r.json())
            .then(data => {
                marketPlugins = data.plugins || [];
                categories = data.categories || [];
                renderCategories();
                renderMarket();
                document.getElementById('marketBadge').textContent = marketPlugins.length;
            })
            .catch(err => {
                document.getElementById('marketGrid').innerHTML =
                    '<div class="empty-state">市场加载失败: ' + err.message + '</div>';
            });
    }

    function renderCategories() {
        let html = '<div class="category-filter active" onclick="filterCategory(\'\')">全部</div>';
        categories.forEach(cat => {
            html += '<div class="category-filter" data-cat="' + cat.id + '" onclick="filterCategory(\'' + cat.id + '\')">' +
                cat.icon + ' ' + escapeHtml(cat.name) + '</div>';
        });
        document.getElementById('categoryFilters').innerHTML = html;
    }

    window.filterCategory = function(cat) {
        currentCategory = cat;
        document.querySelectorAll('.category-filter').forEach(f => f.classList.remove('active'));
        if (cat === '') {
            document.querySelector('.category-filter').classList.add('active');
        } else {
            document.querySelector(`.category-filter[data-cat="${cat}"]`).classList.add('active');
        }
        renderMarket();
    };

    window.searchMarket = function() {
        renderMarket();
    };

    function renderMarket() {
        const keyword = document.getElementById('marketSearch').value.trim().toLowerCase();
        let plugins = marketPlugins;

        if (currentCategory) {
            plugins = plugins.filter(p => p.category === currentCategory);
        }
        if (keyword) {
            plugins = plugins.filter(p =>
                p.name.toLowerCase().includes(keyword) ||
                p.description.toLowerCase().includes(keyword) ||
                (p.tags || []).some(t => t.toLowerCase().includes(keyword))
            );
        }

        const grid = document.getElementById('marketGrid');
        if (plugins.length === 0) {
            grid.innerHTML = '<div class="empty-state">没有找到匹配的插件</div>';
            return;
        }

        let html = '';
        plugins.forEach(p => {
            const installed = p.installed;
            const hasUpdate = p.has_update;
            html += '<div class="plugin-card">';
            html += '<div class="plugin-icon">' + (p.icon || '🔌') + '</div>';
            html += '<div class="plugin-header">';
            html += '<div>';
            html += '<div class="plugin-name">' + escapeHtml(p.name) + '</div>';
            html += '<div style="font-size:11px;color:#aeaeb2;margin-top:2px;">v' + escapeHtml(p.version) + ' · ' + escapeHtml(p.author || '未知') + '</div>';
            html += '</div>';
            if (installed) {
                html += '<span class="installed-badge">已安装</span>';
            }
            html += '</div>';
            html += '<div class="plugin-description">' + escapeHtml(p.description || '暂无描述') + '</div>';
            html += '<div class="plugin-stats">';
            html += '<span>⬇️ ' + (p.downloads || 0) + '</span>';
            html += '<span>⭐ ' + (p.rating || 0) + '</span>';
            if (p.permissions) {
                html += '<span>🔐 ' + p.permissions.length + ' 权限</span>';
            }
            html += '</div>';
            if (p.tags && p.tags.length > 0) {
                html += '<div class="plugin-tags">';
                p.tags.forEach(tag => {
                    html += '<span class="plugin-tag">' + escapeHtml(tag) + '</span>';
                });
                html += '</div>';
            }
            html += '<div class="plugin-actions">';
            if (hasUpdate) {
                html += '<button class="btn update-btn" onclick="updatePlugin(\'' + p.id + '\')">⬆️ 更新到 v' + escapeHtml(p.version) + '</button>';
            } else if (installed) {
                html += '<button class="btn btn-secondary" disabled style="opacity:0.5;">✓ 已安装</button>';
            } else {
                html += '<button class="btn install-btn" onclick="installFromMarket(\'' + p.id + '\')">📦 安装</button>';
            }
            html += '</div></div>';
        });
        grid.innerHTML = html;
    }

    window.installFromMarket = function(pluginId) {
        showToast('⏳ 正在安装...');
        fetch('/api/plugins/market/' + pluginId + '/install', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    if (data.install_url) {
                        showToast('📦 请下载后解压到 plugins/ 目录');
                        window.open(data.install_url, '_blank');
                    } else {
                        showToast('✅ ' + data.message);
                    }
                    loadPlugins();
                    loadMarket();
                    checkUpdates();
                } else {
                    showToast('❌ ' + (data.error || '安装失败'));
                }
            })
            .catch(err => {
                showToast('❌ 安装失败: ' + err.message);
            });
    };

    window.updatePlugin = function(pluginId) {
        showToast('⏳ 正在更新...');
        fetch('/api/plugins/market/' + pluginId + '/update', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    showToast('✅ ' + data.message);
                    loadPlugins();
                    loadMarket();
                    checkUpdates();
                } else {
                    showToast('❌ ' + (data.error || '更新失败'));
                }
            });
    };

    // ==================== 更新检查 ====================

    function checkUpdates() {
        fetch('/api/plugins/market/check-updates')
            .then(r => r.json())
            .then(data => {
                const updates = data.updates || [];
                const badge = document.getElementById('updatesBadge');
                if (updates.length > 0) {
                    badge.style.display = 'inline';
                    badge.textContent = updates.length;
                } else {
                    badge.style.display = 'none';
                }
                renderUpdates(updates);
            })
            .catch(() => {
                document.getElementById('updatesGrid').innerHTML =
                    '<div class="empty-state">更新检查失败</div>';
            });
    }

    function renderUpdates(updates) {
        const grid = document.getElementById('updatesGrid');
        if (updates.length === 0) {
            grid.innerHTML = '<div class="empty-state">🎉 所有插件都是最新版本</div>';
            return;
        }

        let html = '';
        updates.forEach(u => {
            html += '<div class="plugin-card">';
            html += '<div class="plugin-header">';
            html += '<div>';
            html += '<div class="plugin-name">' + escapeHtml(u.name) + '</div>';
            html += '<div style="font-size:11px;color:#aeaeb2;margin-top:2px;">' + escapeHtml(u.id) + '</div>';
            html += '</div>';
            html += '<span class="status-badge" style="background:#ff9500;">可更新</span>';
            html += '</div>';
            html += '<div class="plugin-description">';
            html += '当前版本: v' + escapeHtml(u.current_version) + ' → 最新版本: v' + escapeHtml(u.latest_version);
            html += '</div>';
            html += '<div class="plugin-actions">';
            html += '<button class="btn update-btn" onclick="updatePlugin(\'' + u.id + '\')">⬆️ 立即更新</button>';
            html += '</div></div>';
        });
        grid.innerHTML = html;
    }

    // ==================== 插件配置 ====================

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

    // ==================== 安装弹窗 ====================

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
        showToast('⚠️ URL 安装功能开发中，请使用本地目录安装');
    };

    // ==================== 工具函数 ====================

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

    // ==================== 插件模板生成器 ====================

    window.showGeneratorModal = function() {
        document.getElementById('generatorModal').style.display = 'flex';
        loadTemplates();
    };

    window.closeGeneratorModal = function() {
        document.getElementById('generatorModal').style.display = 'none';
    };

    function loadTemplates() {
        fetch('/api/plugins/generator/templates')
            .then(r => r.json())
            .then(data => {
                const list = document.getElementById('templateList');
                list.innerHTML = '';
                (data.templates || []).forEach(t => {
                    const div = document.createElement('div');
                    div.className = 'template-card' + (t.id === selectedTemplate ? ' active' : '');
                    div.style.cssText = 'padding:12px;border:1px solid #d2d2d7;border-radius:8px;cursor:pointer;transition:all 0.2s;';
                    if (t.id === selectedTemplate) {
                        div.style.borderColor = '#007aff';
                        div.style.background = '#f0f7ff';
                    }
                    div.innerHTML = `<div style="font-size:20px;">${t.icon}</div><div style="font-weight:600;font-size:13px;margin-top:4px;">${escapeHtml(t.name)}</div><div style="font-size:11px;color:#86868b;margin-top:2px;">${escapeHtml(t.description)}</div>`;
                    div.onclick = () => {
                        selectedTemplate = t.id;
                        selectedPermissions = [...t.permissions];
                        loadTemplates();
                        renderPermissions();
                    };
                    list.appendChild(div);
                });
                // 初始化权限
                const first = (data.templates || [])[0];
                if (first && selectedPermissions.length === 0) {
                    selectedPermissions = [...first.permissions];
                }
                renderPermissions();
            });
    }

    function renderPermissions() {
        const allPerms = ['database', 'database_write', 'routes', 'pages', 'tools', 'network', 'filesystem'];
        const permNames = {
            'database': '数据库只读',
            'database_write': '数据库读写',
            'routes': 'API路由',
            'pages': '前端页面',
            'tools': '工具调用',
            'network': '网络访问',
            'filesystem': '文件系统'
        };
        const list = document.getElementById('permList');
        list.innerHTML = '';
        allPerms.forEach(p => {
            const label = document.createElement('label');
            label.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:12px;cursor:pointer;';
            label.innerHTML = `<input type="checkbox" ${selectedPermissions.includes(p) ? 'checked' : ''} onchange="togglePerm('${p}')"> ${permNames[p]}`;
            list.appendChild(label);
        });
    }

    window.togglePerm = function(perm) {
        if (selectedPermissions.includes(perm)) {
            selectedPermissions = selectedPermissions.filter(p => p !== perm);
        } else {
            selectedPermissions.push(perm);
        }
    };

    window.generatePlugin = function() {
        const id = document.getElementById('genId').value.trim();
        const name = document.getElementById('genName').value.trim();
        const desc = document.getElementById('genDesc').value.trim();
        const author = document.getElementById('genAuthor').value.trim() || 'Anonymous';

        if (!id || !name) {
            showToast('❌ 请填写插件ID和名称');
            return;
        }

        showToast('⏳ 正在生成插件...');
        fetch('/api/plugins/generator/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id, name, description: desc, author,
                template: selectedTemplate,
                permissions: selectedPermissions
            })
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                showToast('✅ ' + data.message);
                closeGeneratorModal();
                reloadPlugins();
                // 清空表单
                document.getElementById('genId').value = '';
                document.getElementById('genName').value = '';
                document.getElementById('genDesc').value = '';
            } else {
                showToast('❌ ' + (data.error || '生成失败'));
            }
        })
        .catch(err => {
            showToast('❌ 生成失败: ' + err.message);
        });
    };

    // ==================== 安全审计 ====================

    window.runSecurityAudit = function(pluginId) {
        document.getElementById('auditTitle').textContent = '🔒 安全审计 - ' + pluginId;
        document.getElementById('auditBody').innerHTML = '<div class="empty-state">正在审计...</div>';
        document.getElementById('auditModal').style.display = 'flex';

        fetch('/api/plugins/security/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plugin_id: pluginId })
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                renderAuditResult(data);
            } else {
                document.getElementById('auditBody').innerHTML =
                    '<div class="empty-state">审计失败: ' + (data.error || '') + '</div>';
            }
        });
    };

    function renderAuditResult(data) {
        const riskColors = { high: '#ff3b30', medium: '#ff9500', low: '#34c759' };
        const color = riskColors[data.risk_level] || '#86868b';

        let html = `<div style="text-align:center;margin-bottom:20px;">
            <div style="font-size:48px;">${data.risk_level === 'high' ? '🚨' : data.risk_level === 'medium' ? '⚠️' : '✅'}</div>
            <div style="font-size:20px;font-weight:700;color:${color};">${data.risk_desc}</div>
            <div style="font-size:13px;color:#86868b;margin-top:4px;">${data.summary}</div>
        </div>`;

        if (data.findings && data.findings.length > 0) {
            html += '<div style="margin-bottom:16px;"><div style="font-weight:600;color:#ff3b30;margin-bottom:8px;">❌ 问题 (' + data.findings.length + ')</div>';
            data.findings.forEach(f => {
                html += '<div style="padding:8px 12px;background:#fff5f5;border-left:3px solid #ff3b30;margin-bottom:6px;font-size:13px;border-radius:4px;">' + escapeHtml(f) + '</div>';
            });
            html += '</div>';
        }

        if (data.warnings && data.warnings.length > 0) {
            html += '<div style="margin-bottom:16px;"><div style="font-weight:600;color:#ff9500;margin-bottom:8px;">⚠️ 警告 (' + data.warnings.length + ')</div>';
            data.warnings.forEach(w => {
                html += '<div style="padding:8px 12px;background:#fffaf0;border-left:3px solid #ff9500;margin-bottom:6px;font-size:13px;border-radius:4px;">' + escapeHtml(w) + '</div>';
            });
            html += '</div>';
        }

        if (data.info && data.info.length > 0) {
            html += '<div><div style="font-weight:600;color:#007aff;margin-bottom:8px;">ℹ️ 信息</div>';
            data.info.forEach(i => {
                html += '<div style="padding:6px 12px;font-size:12px;color:#86868b;">' + escapeHtml(i) + '</div>';
            });
            html += '</div>';
        }

        document.getElementById('auditBody').innerHTML = html;
    }

    window.closeAuditModal = function() {
        document.getElementById('auditModal').style.display = 'none';
    };

})();
