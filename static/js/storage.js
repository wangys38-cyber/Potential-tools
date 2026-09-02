/**
 * Potential-tools v7.1 - 统一用户数据存储封装
 * 确保所有 localStorage key 自动带用户前缀，避免数据隔离遗漏
 *
 * 使用方式：
 *   UserStorage.set('my_key', value)        // 自动加 u{id}_ 前缀
 *   UserStorage.get('my_key', defaultVal)    // 自动加前缀读取
 *   UserStorage.getJSON('my_key', [])        // JSON 读取
 *   UserStorage.setJSON('my_key', obj)       // JSON 写入
 *   UserStorage.remove('my_key')
 *   UserStorage.has('my_key')
 *   UserStorage.clearAll()                    // 清除当前用户所有数据
 *
 * 全局（非用户隔离）存储，仅用于主题等设备级偏好：
 *   UserStorage.global.set('toolbox_theme', 'dark')
 *   UserStorage.global.get('toolbox_theme', 'auto')
 */
(function() {
    'use strict';

    function _prefix() {
        return (typeof window._USER_PREFIX !== 'undefined' && window._USER_PREFIX) ? window._USER_PREFIX : '';
    }

    function _fullKey(key) {
        return _prefix() + key;
    }

    var UserStorage = {
        /** 获取当前用户前缀 */
        prefix: function() { return _prefix(); },

        /** 构造带前缀的完整 key */
        key: function(k) { return _fullKey(k); },

        /** 读取字符串值 */
        get: function(k, defaultVal) {
            try {
                var v = localStorage.getItem(_fullKey(k));
                return (v === null || v === undefined) ? (defaultVal !== undefined ? defaultVal : null) : v;
            } catch(e) { return defaultVal !== undefined ? defaultVal : null; }
        },

        /** 写入字符串值 */
        set: function(k, v) {
            try { localStorage.setItem(_fullKey(k), v); return true; } catch(e) { return false; }
        },

        /** 删除 */
        remove: function(k) {
            try { localStorage.removeItem(_fullKey(k)); } catch(e) {}
        },

        /** 是否存在 */
        has: function(k) {
            try { return localStorage.getItem(_fullKey(k)) !== null; } catch(e) { return false; }
        },

        /** 读取 JSON 值 */
        getJSON: function(k, defaultVal) {
            try {
                var raw = localStorage.getItem(_fullKey(k));
                if (raw === null || raw === undefined) return defaultVal !== undefined ? defaultVal : null;
                return JSON.parse(raw);
            } catch(e) { return defaultVal !== undefined ? defaultVal : null; }
        },

        /** 写入 JSON 值 */
        setJSON: function(k, v) {
            try { localStorage.setItem(_fullKey(k), JSON.stringify(v)); return true; } catch(e) { return false; }
        },

        /** 清除当前用户所有带前缀的数据 */
        clearAll: function() {
            try {
                var p = _prefix();
                if (!p) return;
                var keysToRemove = [];
                for (var i = 0; i < localStorage.length; i++) {
                    var key = localStorage.key(i);
                    if (key && key.indexOf(p) === 0) keysToRemove.push(key);
                }
                keysToRemove.forEach(function(k) { localStorage.removeItem(k); });
            } catch(e) {}
        },

        /** 全局（非用户隔离）存储，仅用于设备级偏好如主题 */
        global: {
            get: function(k, defaultVal) {
                try {
                    var v = localStorage.getItem(k);
                    return (v === null || v === undefined) ? (defaultVal !== undefined ? defaultVal : null) : v;
                } catch(e) { return defaultVal !== undefined ? defaultVal : null; }
            },
            set: function(k, v) {
                try { localStorage.setItem(k, v); return true; } catch(e) { return false; }
            },
            remove: function(k) {
                try { localStorage.removeItem(k); } catch(e) {}
            },
            has: function(k) {
                try { return localStorage.getItem(k) !== null; } catch(e) { return false; }
            }
        }
    };

    window.UserStorage = UserStorage;
})();
