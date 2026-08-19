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
    var _USER_PREFIX = window._USER_PREFIX || '';

    // 同步类别定义：sync_type → { keys: [localStorage keys], name, icon, prefix: bool }
    var CATEGORIES = {
        favorites: {
            keys: [_USER_PREFIX + 'toolbox_favorites', 'toolbox_favorites_v2', 'toolbox_favorites'],
            name: '收藏工具', icon: '⭐'
        },
        recent: {
            keys: [_USER_PREFIX + 'toolbox_recent_tools', 'toolbox_recent_tools'],
            name: '最近使用', icon: '🕐'
        },
        merit: {
            keys: ['merit_total', 'merit_history', 'merit_achievements',
                   'STORAGE_KEY_TOTAL', 'STORAGE_KEY_HISTORY', 'STORAGE_KEY_ACH'],
            name: '功德数据', icon: '🔔'
        },
        projects: {
            keys: [_USER_PREFIX + 'projectInfoData', 'projectInfoData', 'PROJECT_STORAGE_KEY'],
            name: '项目信息', icon: '📊'
        },
        plans: {
            keys: [_USER_PREFIX + 'saved_plans', 'saved_plans'],
            name: '项目计划', icon: '📋'
        },
        notes: {
            keys: [_USER_PREFIX + 'niuma_notes', 'niuma_notes'],
            name: '牛马笔记', icon: '📝'
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

        var isMobile = window.innerWidth <= 480;

        var btn = document.createElement('button');
        btn.id = 'v5-sync-btn';
        btn.className = 'v5-sync-btn';
        btn.title = '云端同步';
        btn.innerHTML = '<span id="v5-sync-icon" class="v5-sync-icon">' +
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>' +
            '</span>' +
            (isMobile ? '' : '<span id="v5-sync-label" class="v5-sync-label">同步</span>');
        btn.onclick = function() { sync(true); };

        // 优先插入到全局导航栏右侧，其次插入到页面 header
        var navBar = document.getElementById('tb-nav-bar');
        if (navBar) {
            // 全局导航栏：插入到右侧 user-bar 之前
            var userBar = navBar.querySelector('.tb-user-bar, .user-bar');
            if (userBar) {
                userBar.parentNode.insertBefore(btn, userBar);
            } else {
                navBar.appendChild(btn);
            }
            btn.classList.add('v5-sync-btn-in-nav');
        } else {
            var header = document.querySelector('.header') || document.querySelector('.nav') || document.querySelector('header');
            if (header) {
                var existingRight = header.querySelector('.header-right, .nav-right, .header-actions');
                if (existingRight) {
                    existingRight.appendChild(btn);
                } else {
                    header.style.position = 'relative';
                    btn.classList.add('v5-sync-btn-absolute');
                    if (isMobile) {
                        btn.style.right = '10px';
                        btn.style.top = '50%';
                        btn.style.transform = 'translateY(-50%)';
                    } else {
                        btn.style.right = '20px';
                        btn.style.top = '50%';
                        btn.style.transform = 'translateY(-50%)';
                    }
                    header.appendChild(btn);
                }
            }
        }
    }

    function updateUI() {
        var icon = document.getElementById('v5-sync-icon');
        var label = document.getElementById('v5-sync-label');
        var btn = document.getElementById('v5-sync-btn');
        if (!icon || !label) return;

        var cloudOutline = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>';
        var cloudFilled = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>';

        if (state.status === 'syncing') {
            icon.innerHTML = cloudOutline;
            icon.style.animation = 'v5spin 1s linear infinite';
            label.textContent = '同步中';
        } else if (state.status === 'success') {
            icon.innerHTML = cloudFilled;
            icon.style.animation = 'none';
            label.textContent = '已同步';
        } else if (state.status === 'error') {
            icon.innerHTML = cloudOutline;
            icon.style.animation = 'none';
            icon.style.color = '#d44';
            label.textContent = '同步失败';
        } else {
            icon.innerHTML = cloudOutline;
            icon.style.animation = 'none';
            icon.style.color = '';
            label.textContent = '同步';
        }
    }

    // 样式注入
    var style = document.createElement('style');
    style.textContent =
        '@keyframes v5spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}' +
        '.v5-sync-btn{' +
            'display:inline-flex;align-items:center;gap:6px;padding:6px 10px;' +
            'border-radius:8px;border:none;' +
            'background:transparent;' +
            'cursor:pointer;font-size:13px;font-weight:500;color:rgba(0,0,0,0.7);' +
            'transition:all 0.2s;font-family:inherit;flex-shrink:0;white-space:nowrap;line-height:1;' +
        '}' +
        '.v5-sync-btn:hover{background:rgba(0,0,0,0.05)}' +
        '.v5-sync-btn:active{transform:translateY(0)}' +
        '.v5-sync-btn-absolute{position:absolute;z-index:10}' +
        '.v5-sync-btn-in-nav{margin-right:4px;padding:6px 8px;font-size:13px;background:transparent;border:none;color:rgba(0,0,0,0.7)}' +
        '.v5-sync-btn-in-nav:hover{background:rgba(0,0,0,0.05)}' +
        '.v5-sync-icon{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px}' +
        '.v5-sync-icon svg{display:block}' +
        '.v5-sync-label{font-size:13px;font-weight:500}' +
        '[data-theme="dark"] .v5-sync-btn{' +
            'background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.12);color:rgba(255,255,255,0.9)' +
        '}' +
        '[data-theme="dark"] .v5-sync-btn:hover{background:rgba(255,255,255,0.15)}' +
        '@media (max-width:480px){' +
            '.v5-sync-btn{padding:5px 10px;gap:4px}' +
            '.v5-sync-label{display:none}' +
            '.v5-sync-btn-absolute{right:10px!important}' +
        '}' +
        '@media (max-width:360px){' +
            '.v5-sync-btn{padding:4px 8px}' +
        '}';
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
