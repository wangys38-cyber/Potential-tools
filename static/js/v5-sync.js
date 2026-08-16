/**
 * v5.2 多设备数据同步客户端
 * - 拉取云端数据合并到 localStorage
 * - 推送本地变更到云端
 * - 自动同步（页面加载 + 数据变更防抖）
 * - 同步状态指示器
 */
(function() {
    'use strict';

    var META_KEY = 'v5_sync_meta';
    var SYNC_INTERVAL = 5 * 60 * 1000; // 5分钟自动同步
    var DEBOUNCE_DELAY = 2000; // 变更后2秒防抖推送

    // 同步类别定义：sync_type → { keys: [localStorage keys], name, icon }
    var CATEGORIES = {
        favorites: {
            keys: ['toolbox_favorites_v2', 'toolbox_favorites'],
            name: '收藏工具', icon: '⭐'
        },
        merit: {
            keys: ['merit_total', 'merit_history', 'merit_achievements',
                   'STORAGE_KEY_TOTAL', 'STORAGE_KEY_HISTORY', 'STORAGE_KEY_ACH'],
            name: '功德数据', icon: '🔔'
        },
        projects: {
            keys: ['projectInfoData_v2', 'projectInfoData', 'PROJECT_STORAGE_KEY'],
            name: '项目信息', icon: '📊'
        },
        theme: {
            keys: ['toolbox_theme'],
            name: '主题设置', icon: '🎨'
        },
        form_drafts: {
            keys: ['form_draft_'],
            name: '表单草稿', icon: '📝',
            prefix: true // keys 是前缀匹配
        },
        settings: {
            keys: ['toolbox_settings', 'user_settings'],
            name: '用户设置', icon: '⚙️'
        }
    };

    var state = {
        syncing: false,
        lastSync: 0,
        status: 'idle', // idle | syncing | success | error
        error: null,
        enabled: true
    };

    // ===== 元数据管理 =====
    function getMeta() {
        try {
            return JSON.parse(localStorage.getItem(META_KEY)) || { lastSync: 0, categories: {} };
        } catch(e) { return { lastSync: 0, categories: {} }; }
    }
    function setMeta(meta) {
        try { localStorage.setItem(META_KEY, JSON.stringify(meta)); } catch(e) {}
    }

    // ===== 读取本地数据 =====
    function readCategory(catKey) {
        var cat = CATEGORIES[catKey];
        if (!cat) return null;
        var data = {};
        var hasData = false;
        if (cat.prefix) {
            // 前缀匹配
            for (var i = 0; i < localStorage.length; i++) {
                var k = localStorage.key(i);
                if (k && cat.keys.some(function(prefix) { return k.indexOf(prefix) === 0; })) {
                    data[k] = localStorage.getItem(k);
                    hasData = true;
                }
            }
        } else {
            cat.keys.forEach(function(k) {
                var v = localStorage.getItem(k);
                if (v !== null) { data[k] = v; hasData = true; }
            });
        }
        return hasData ? data : null;
    }

    function writeCategory(catKey, data) {
        var cat = CATEGORIES[catKey];
        if (!cat || !data) return;
        if (cat.prefix) {
            // 先清除旧的前缀数据
            var toRemove = [];
            for (var i = 0; i < localStorage.length; i++) {
                var k = localStorage.key(i);
                if (k && cat.keys.some(function(prefix) { return k.indexOf(prefix) === 0; })) {
                    toRemove.push(k);
                }
            }
            toRemove.forEach(function(k) { localStorage.removeItem(k); });
        }
        Object.keys(data).forEach(function(k) {
            try { localStorage.setItem(k, data[k]); } catch(e) {}
        });
    }

    // ===== 拉取 =====
    async function pull() {
        try {
            var resp = await fetch('/api/sync/pull', { credentials: 'same-origin' });
            if (resp.status === 401) { state.enabled = false; return null; }
            var result = await resp.json();
            if (result.status !== 'success') return null;
            return result.data || {};
        } catch(e) {
            console.warn('Sync pull failed:', e);
            return null;
        }
    }

    // ===== 推送 =====
    async function push(categories) {
        var items = {};
        (categories || Object.keys(CATEGORIES)).forEach(function(catKey) {
            var data = readCategory(catKey);
            if (data) items[catKey] = data;
        });
        if (Object.keys(items).length === 0) return true;
        try {
            var resp = await fetch('/api/sync/push', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({ items: items })
            });
            if (resp.status === 401) { state.enabled = false; return false; }
            var result = await resp.json();
            return result.status === 'success';
        } catch(e) {
            console.warn('Sync push failed:', e);
            return false;
        }
    }

    // ===== 全量同步（拉取合并 + 推送）=====
    async function sync(showToast) {
        if (state.syncing || !state.enabled) return;
        state.syncing = true;
        state.status = 'syncing';
        updateUI();

        try {
            // 1. 拉取云端数据
            var serverData = await pull();
            if (serverData) {
                var meta = getMeta();
                var merged = 0;
                Object.keys(serverData).forEach(function(catKey) {
                    var serverItem = serverData[catKey];
                    if (!serverItem || !serverItem.data) return;
                    var localTs = (meta.categories[catKey] || {}).updated_at || 0;
                    // 云端更新则合并到本地
                    if (serverItem.updated_at > localTs) {
                        writeCategory(catKey, serverItem.data);
                        meta.categories[catKey] = { updated_at: serverItem.updated_at };
                        merged++;
                    }
                });
                if (merged > 0) {
                    setMeta(meta);
                    if (showToast) showToastMsg('📥 已从云端同步 ' + merged + ' 类数据', 'info');
                    // 触发页面刷新以应用新数据
                    window.dispatchEvent(new CustomEvent('v5-synced', { detail: { merged: merged } }));
                }
            }

            // 2. 推送本地变更
            var pushOk = await push();
            if (pushOk) {
                var meta2 = getMeta();
                meta2.lastSync = Date.now();
                Object.keys(CATEGORIES).forEach(function(k) {
                    if (!meta2.categories[k]) meta2.categories[k] = {};
                    meta2.categories[k].updated_at = Date.now() / 1000;
                });
                setMeta(meta2);
                state.lastSync = Date.now();
            }

            state.status = pushOk ? 'success' : 'error';
            state.error = pushOk ? null : '推送失败';
        } catch(e) {
            state.status = 'error';
            state.error = e.message;
        }

        state.syncing = false;
        updateUI();
        if (showToast && state.status === 'success') {
            showToastMsg('✅ 同步完成', 'success');
        } else if (showToast && state.status === 'error') {
            showToastMsg('❌ 同步失败: ' + (state.error || '未知错误'), 'error');
        }
    }

    // ===== 防抖推送（数据变更时触发）=====
    var debounceTimer = null;
    function schedulePush() {
        if (!state.enabled) return;
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function() {
            push().then(function(ok) {
                if (ok) {
                    var meta = getMeta();
                    meta.lastSync = Date.now();
                    setMeta(meta);
                }
            });
        }, DEBOUNCE_DELAY);
    }

    // 监听 localStorage 变更（跨标签页）
    window.addEventListener('storage', function(e) {
        if (e.key && e.key !== META_KEY && !e.key.startsWith('v5_')) {
            schedulePush();
        }
    });

    // 监听自定义事件（页面内数据变更）
    window.addEventListener('v5-data-changed', function() { schedulePush(); });

    // ===== UI 注入 =====
    function createUI() {
        if (document.getElementById('v5-sync-btn')) return;

        var btn = document.createElement('button');
        btn.id = 'v5-sync-btn';
        btn.title = '云端同步';
        btn.style.cssText =
            'display:inline-flex;align-items:center;gap:6px;padding:6px 12px;' +
            'border-radius:10px;border:1px solid rgba(255,255,255,0.6);' +
            'background:rgba(255,255,255,0.5);backdrop-filter:blur(10px);' +
            'cursor:pointer;font-size:13px;color:var(--text-primary);' +
            'transition:all 0.25s;font-family:inherit;';
        btn.innerHTML = '<span id="v5-sync-icon">☁️</span><span id="v5-sync-label">同步</span>';
        btn.onmouseenter = function() { this.style.transform = 'translateY(-1px)'; this.style.boxShadow = '0 4px 12px rgba(102,126,234,0.15)'; };
        btn.onmouseleave = function() { this.style.transform = 'none'; this.style.boxShadow = 'none'; };
        btn.onclick = function() { sync(true); };

        // 插入到 header 区域
        var header = document.querySelector('.header') || document.querySelector('.nav') || document.querySelector('header');
        if (header) {
            // 尝试插入到 header 的右侧
            var existingRight = header.querySelector('.header-right, .nav-right, .header-actions');
            if (existingRight) {
                existingRight.appendChild(btn);
            } else {
                header.style.position = 'relative';
                btn.style.position = 'absolute';
                btn.style.top = '50%';
                btn.style.right = '20px';
                btn.style.transform = 'translateY(-50%)';
                header.appendChild(btn);
            }
        }

        // 暗色模式适配
        if (document.documentElement.getAttribute('data-theme') === 'dark') {
            btn.style.background = 'rgba(30,30,40,0.5)';
            btn.style.borderColor = 'rgba(255,255,255,0.08)';
        }
    }

    function updateUI() {
        var icon = document.getElementById('v5-sync-icon');
        var label = document.getElementById('v5-sync-label');
        var btn = document.getElementById('v5-sync-btn');
        if (!icon || !label) return;

        if (state.status === 'syncing') {
            icon.textContent = '🔄';
            icon.style.animation = 'v5spin 1s linear infinite';
            label.textContent = '同步中';
        } else if (state.status === 'success') {
            icon.textContent = '✅';
            icon.style.animation = 'none';
            label.textContent = '已同步';
            setTimeout(function() {
                if (state.status === 'success') {
                    icon.textContent = '☁️';
                    label.textContent = '同步';
                }
            }, 2000);
        } else if (state.status === 'error') {
            icon.textContent = '⚠️';
            icon.style.animation = 'none';
            label.textContent = '同步失败';
        } else {
            icon.textContent = '☁️';
            icon.style.animation = 'none';
            label.textContent = '同步';
        }
    }

    // 旋转动画
    var style = document.createElement('style');
    style.textContent = '@keyframes v5spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}';
    document.head.appendChild(style);

    // ===== Toast 提示（兼容各页面）=====
    function showToastMsg(msg, type) {
        if (typeof showToast === 'function') {
            showToast(msg, type);
        } else {
            console.log('[Sync]', msg);
        }
    }

    // ===== 初始化 =====
    function init() {
        createUI();
        // 页面加载后延迟同步（等待页面初始化完成）
        setTimeout(function() { sync(false); }, 1500);
        // 定时自动同步
        setInterval(function() { sync(false); }, SYNC_INTERVAL);
        // 页面可见时同步
        document.addEventListener('visibilitychange', function() {
            if (!document.hidden) sync(false);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // 暴露全局 API
    window.V5Sync = {
        sync: sync,
        pull: pull,
        push: push,
        getState: function() { return state; },
        schedulePush: schedulePush
    };
})();
