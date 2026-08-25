/**
 * v6.0 多设备数据同步客户端
 * - 拉取云端数据合并到 localStorage（基于时间戳冲突解决）
 * - 推送本地变更到云端（带客户端时间戳，服务端冲突检测）
 * - 自动同步（页面加载 + 数据变更防抖 + 定时）
 * - 同步失败指数退避重试（最多3次）
 * - 离线检测与数据暂存
 * - 同步状态指示器（同步中/已同步/失败/离线）
 */
(function() {
    'use strict';
    if (window.__V5_SYNC_LOADED__) return;
    window.__V5_SYNC_LOADED__ = true;

    var META_KEY = 'v5_sync_meta';
    var PENDING_KEY = 'v5_sync_pending';
    var SYNC_INTERVAL = 5 * 60 * 1000;
    var DEBOUNCE_DELAY = 2000;
    var MAX_RETRIES = 3;
    var _USER_PREFIX = window._USER_PREFIX || '';

    // 同步类别定义
    var CATEGORIES = {
        favorites: {
            keys: [_USER_PREFIX + 'toolbox_favorites', 'toolbox_favorites_v2', 'toolbox_favorites'],
            name: '收藏工具'
        },
        recent: {
            keys: [_USER_PREFIX + 'toolbox_recent_tools', 'toolbox_recent_tools'],
            name: '最近使用'
        },
        merit: {
            keys: ['merit_total', 'merit_history', 'merit_achievements',
                   'STORAGE_KEY_TOTAL', 'STORAGE_KEY_HISTORY', 'STORAGE_KEY_ACH'],
            name: '功德数据'
        },
        projects: {
            keys: [_USER_PREFIX + 'projectInfoData', 'projectInfoData', 'PROJECT_STORAGE_KEY'],
            name: '项目信息'
        },
        plans: {
            keys: [_USER_PREFIX + 'saved_plans', 'saved_plans'],
            name: '项目计划'
        },
        notes: {
            keys: [_USER_PREFIX + 'niuma_notes', 'niuma_notes'],
            name: '牛马笔记'
        },
        theme: {
            keys: ['toolbox_theme'],
            name: '主题设置'
        },
        form_drafts: {
            keys: ['form_draft_'],
            name: '表单草稿',
            prefix: true
        },
        settings: {
            keys: ['toolbox_settings', 'user_settings', 'ai_config', 'feishu_webhook', 'feishu_secret'],
            name: '用户设置'
        }
    };

    var state = {
        syncing: false,
        lastSync: 0,
        status: 'idle', // idle | syncing | success | error | offline
        error: null,
        enabled: true,
        online: navigator.onLine,
        retryCount: 0,
        pendingCategories: []
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

    // ===== 待同步队列（离线暂存）=====
    function getPending() {
        try { return JSON.parse(localStorage.getItem(PENDING_KEY)) || {}; }
        catch(e) { return {}; }
    }
    function setPending(pending) {
        try { localStorage.setItem(PENDING_KEY, JSON.stringify(pending)); } catch(e) {}
    }
    function addPending(catKey, data) {
        var pending = getPending();
        pending[catKey] = { data: data, ts: Date.now() / 1000 };
        setPending(pending);
    }
    function clearPending(catKey) {
        var pending = getPending();
        if (pending[catKey]) {
            delete pending[catKey];
            setPending(pending);
        }
    }
    function getPendingCount() {
        return Object.keys(getPending()).length;
    }

    // ===== 读取本地数据 =====
    function readCategory(catKey) {
        var cat = CATEGORIES[catKey];
        if (!cat) return null;
        var data = {};
        var hasData = false;
        if (cat.prefix) {
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

    function _hasRealData(dataObj) {
        if (!dataObj) return false;
        return Object.keys(dataObj).some(function(k) {
            try {
                var v = JSON.parse(dataObj[k]);
                return Array.isArray(v) ? v.length > 0 : !!v;
            } catch(e) { return !!dataObj[k]; }
        });
    }

    // ===== 网络请求（带重试）=====
    async function fetchWithRetry(url, options, maxRetries) {
        var retries = 0;
        var delay = 1000;
        while (true) {
            try {
                var resp = await fetch(url, options);
                if (resp.status === 401) {
                    state.enabled = false;
                    return { ok: false, status: 401, data: null };
                }
                var data = await resp.json();
                return { ok: resp.ok, status: resp.status, data: data };
            } catch(e) {
                retries++;
                if (retries > maxRetries) {
                    return { ok: false, status: 0, data: null, error: e.message };
                }
                await _sleep(delay);
                delay *= 2; // 指数退避
            }
        }
    }

    function _sleep(ms) {
        return new Promise(function(resolve) { setTimeout(resolve, ms); });
    }

    // ===== 拉取 =====
    async function pull() {
        if (!state.online) return null;
        var result = await fetchWithRetry('/api/sync/pull', { credentials: 'same-origin' }, MAX_RETRIES);
        if (!result.ok || !result.data || result.data.status !== 'success') return null;
        return result.data.data || {};
    }

    // ===== 推送（带时间戳和冲突处理）=====
    async function push(categories) {
        if (!state.online) return false;
        var items = {};
        var meta = getMeta();
        (categories || Object.keys(CATEGORIES)).forEach(function(catKey) {
            var data = readCategory(catKey);
            if (data) {
                var catMeta = meta.categories[catKey] || {};
                items[catKey] = {
                    data: data,
                    client_updated_at: catMeta.updated_at || 0
                };
            }
        });

        // 合并离线暂存数据
        var pending = getPending();
        Object.keys(pending).forEach(function(catKey) {
            if (!items[catKey]) {
                items[catKey] = { data: pending[catKey].data, client_updated_at: pending[catKey].ts };
            }
        });

        if (Object.keys(items).length === 0) return true;

        var result = await fetchWithRetry('/api/sync/push', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({ items: items })
        }, MAX_RETRIES);

        if (!result.ok || !result.data) return false;

        var results = result.data.results || {};
        var allOk = true;
        Object.keys(results).forEach(function(catKey) {
            var r = results[catKey];
            if (r.status === 'success') {
                clearPending(catKey);
                var m = getMeta();
                if (!m.categories[catKey]) m.categories[catKey] = {};
                m.categories[catKey].updated_at = r.updated_at;
                setMeta(m);
            } else if (r.status === 'conflict') {
                // 服务端数据更新，合并到本地
                if (r.server_data) {
                    writeCategory(catKey, r.server_data);
                    var m2 = getMeta();
                    if (!m2.categories[catKey]) m2.categories[catKey] = {};
                    m2.categories[catKey].updated_at = r.server_updated_at;
                    setMeta(m2);
                }
                clearPending(catKey);
            } else {
                allOk = false;
                // 推送失败，加入暂存
                if (items[catKey] && items[catKey].data) {
                    addPending(catKey, items[catKey].data);
                }
            }
        });
        return allOk;
    }

    // ===== 全量同步（拉取合并 + 推送）=====
    async function sync(showToast) {
        if (state.syncing || !state.enabled) return;
        if (!state.online) {
            state.status = 'offline';
            updateUI();
            return;
        }
        state.syncing = true;
        state.status = 'syncing';
        state.retryCount = 0;
        updateUI();

        try {
            // 1. 拉取云端数据并合并
            var serverData = await pull();
            if (serverData) {
                var meta = getMeta();
                var merged = 0;
                Object.keys(serverData).forEach(function(catKey) {
                    var serverItem = serverData[catKey];
                    if (!serverItem || !serverItem.data) return;
                    var localTs = (meta.categories[catKey] || {}).updated_at || 0;
                    if (serverItem.updated_at > localTs) {
                        var localData = readCategory(catKey);
                        var serverHasData = _hasRealData(serverItem.data);
                        var localHasData = _hasRealData(localData);
                        if (localHasData && !serverHasData) return;
                        writeCategory(catKey, serverItem.data);
                        if (!meta.categories[catKey]) meta.categories[catKey] = {};
                        meta.categories[catKey].updated_at = serverItem.updated_at;
                        merged++;
                    }
                });
                if (merged > 0) {
                    setMeta(meta);
                    window.dispatchEvent(new CustomEvent('v5-synced', { detail: { merged: merged } }));
                }
            }

            // 2. 推送本地变更
            var pushOk = await push();
            if (pushOk) {
                var meta2 = getMeta();
                meta2.lastSync = Date.now();
                setMeta(meta2);
                state.lastSync = Date.now();
            }

            state.status = pushOk ? 'success' : 'error';
            state.error = pushOk ? null : '部分数据同步失败';
        } catch(e) {
            state.status = 'error';
            state.error = e.message;
        }

        state.syncing = false;
        updateUI();
        if (showToast) {
            if (state.status === 'success') showToastMsg('同步完成', 'success');
            else if (state.status === 'error') showToastMsg('同步失败: ' + (state.error || '未知错误'), 'error');
        }
    }

    // ===== 防抖推送 =====
    var debounceTimer = null;
    function schedulePush() {
        if (!state.enabled) return;
        if (!state.online) {
            // 离线时直接暂存
            Object.keys(CATEGORIES).forEach(function(catKey) {
                var data = readCategory(catKey);
                if (data) addPending(catKey, data);
            });
            state.status = 'offline';
            updateUI();
            return;
        }
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function() {
            push().then(function(ok) {
                if (ok) {
                    var meta = getMeta();
                    meta.lastSync = Date.now();
                    setMeta(meta);
                    state.lastSync = Date.now();
                    state.status = 'success';
                } else {
                    state.status = 'error';
                }
                updateUI();
            });
        }, DEBOUNCE_DELAY);
    }

    // 监听 localStorage 变更（跨标签页）
    window.addEventListener('storage', function(e) {
        if (e.key && e.key !== META_KEY && e.key !== PENDING_KEY && !e.key.startsWith('v5_')) {
            schedulePush();
        }
    });

    // 监听自定义事件（页面内数据变更）
    window.addEventListener('v5-data-changed', function() { schedulePush(); });

    // ===== 离线/在线检测 =====
    window.addEventListener('online', function() {
        state.online = true;
        state.status = 'syncing';
        updateUI();
        // 联网后自动同步暂存数据
        setTimeout(function() { sync(false); }, 1000);
    });
    window.addEventListener('offline', function() {
        state.online = false;
        state.status = 'offline';
        updateUI();
    });

    // ===== UI 更新（通过事件通知导航栏）=====
    function updateUI() {
        // 派发状态变更事件，供导航栏监听
        window.dispatchEvent(new CustomEvent('v5-sync-status', {
            detail: {
                status: state.status,
                lastSync: state.lastSync,
                error: state.error,
                online: state.online,
                pendingCount: getPendingCount()
            }
        }));
    }

    // ===== Toast =====
    function showToastMsg(msg, type) {
        if (typeof showToast === 'function') {
            showToast(msg, type);
        }
    }

    // ===== 初始化 =====
    function init() {
        state.online = navigator.onLine;
        if (!state.online) state.status = 'offline';
        updateUI();

        // 页面加载后延迟同步
        setTimeout(function() { sync(false); }, 1500);
        // 定时自动同步
        setInterval(function() { if (state.online) sync(false); }, SYNC_INTERVAL);
        // 页面可见时同步
        document.addEventListener('visibilitychange', function() {
            if (!document.hidden && state.online) sync(false);
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
        getState: function() {
            return {
                status: state.status,
                lastSync: state.lastSync,
                error: state.error,
                online: state.online,
                pendingCount: getPendingCount(),
                syncing: state.syncing
            };
        },
        schedulePush: schedulePush,
        getPendingCount: getPendingCount
    };
})();
