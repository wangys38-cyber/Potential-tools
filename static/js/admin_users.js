/**
 * v9.1 用户管理前端逻辑
 */
(function() {
    'use strict';

    var state = {
        page: 1,
        perPage: 20,
        search: '',
        total: 0,
        totalPages: 1,
        users: [],
        editingUserId: null,
        resettingUserId: null,
        deletingUserId: null
    };

    var API_BASE = '/api/admin/users';

    function formatDate(ts) {
        if (!ts || ts === 0) return '—';
        try {
            var d = new Date(ts * 1000);
            return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
                String(d.getDate()).padStart(2, '0') + ' ' + String(d.getHours()).padStart(2, '0') + ':' +
                String(d.getMinutes()).padStart(2, '0');
        } catch (e) { return '—'; }
    }

    function escapeHtml(str) {
        if (!str) return '';
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function showToast(msg, type) {
        type = type || 'success';
        var c = document.getElementById('toastContainer');
        if (!c) return;
        var t = document.createElement('div');
        t.className = 'toast toast-' + type;
        t.textContent = msg;
        c.appendChild(t);
        setTimeout(function() { t.classList.add('toast-show'); }, 10);
        setTimeout(function() {
            t.classList.remove('toast-show');
            setTimeout(function() { if (t.parentNode) t.parentNode.removeChild(t); }, 300);
        }, 3000);
    }

    function genRandomPwd() {
        var chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
        var p = '';
        for (var i = 0; i < 10; i++) p += chars.charAt(Math.floor(Math.random() * chars.length));
        return p;
    }

    function loadUsers() {
        var tbody = document.getElementById('usersTbody');
        tbody.innerHTML = '<tr class="loading-row"><td colspan="9">加载中...</td></tr>';
        var url = API_BASE + '?page=' + state.page + '&per_page=' + state.perPage;
        if (state.search) url += '&search=' + encodeURIComponent(state.search);
        fetch(url, { credentials: 'same-origin' })
            .then(function(r) { return r.json(); })
            .then(function(res) {
                if (res.status === 'success') {
                    state.users = res.users || [];
                    state.total = res.total || 0;
                    state.totalPages = Math.ceil(state.total / state.perPage) || 1;
                    renderTable();
                    renderPagination();
                    document.getElementById('totalUsers').textContent = state.total;
                } else {
                    tbody.innerHTML = '<tr class="empty-row"><td colspan="9">加载失败: ' + escapeHtml(res.error || '未知错误') + '</td></tr>';
                }
            })
            .catch(function() {
                tbody.innerHTML = '<tr class="empty-row"><td colspan="9">网络错误，请重试</td></tr>';
            });
    }

    function renderTable() {
        var tbody = document.getElementById('usersTbody');
        if (!state.users.length) {
            tbody.innerHTML = '<tr class="empty-row"><td colspan="9">暂无用户</td></tr>';
            return;
        }
        var html = '';
        state.users.forEach(function(u) {
            var isAdmin = u.is_admin === 1 || u.is_admin === true;
            var avatarHtml = u.avatar
                ? '<img src="' + escapeHtml(u.avatar) + '" class="user-avatar" alt="">'
                : '<span class="user-avatar-letter">' + escapeHtml((u.name || u.username || '?').charAt(0).toUpperCase()) + '</span>';
            var adminBadge = isAdmin ? '<span class="badge badge-admin">管理员</span>' : '<span class="badge badge-user">普通</span>';
            var providerLabel = { feishu: '飞书', google: 'Google', wechat: '微信', local: '密码' }[u.provider] || u.provider;
            var displayName = u.name || u.username || '';
            html += '<tr data-id="' + u.id + '">' +
                '<td>' + u.id + '</td>' +
                '<td>' + avatarHtml + '</td>' +
                '<td class="cell-name">' + escapeHtml(displayName) + (u.username ? '<br><span class="cell-sub">' + escapeHtml(u.username) + '</span>' : '') + '</td>' +
                '<td class="cell-email">' + escapeHtml(u.email || '') + '</td>' +
                '<td><span class="badge badge-provider">' + escapeHtml(providerLabel) + '</span></td>' +
                '<td>' + formatDate(u.created_at) + '</td>' +
                '<td>' + formatDate(u.last_login) + '</td>' +
                '<td>' + adminBadge + '</td>' +
                '<td class="cell-actions">' +
                    '<button class="btn-icon" title="编辑" onclick="AdminUsers.openEdit(' + u.id + ')">' +
                        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>' +
                    '</button>' +
                    '<button class="btn-icon" title="重置密码" onclick="AdminUsers.openReset(' + u.id + ', \'' + escapeHtml(displayName) + '\')">' +
                        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>' +
                    '</button>' +
                    '<button class="btn-icon ' + (isAdmin ? 'btn-icon-active' : '') + '" title="' + (isAdmin ? '取消管理员' : '设为管理员') + '" onclick="AdminUsers.toggleAdmin(' + u.id + ')">' +
                        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>' +
                    '</button>' +
                    '<button class="btn-icon btn-icon-danger" title="删除" onclick="AdminUsers.openDelete(' + u.id + ', \'' + escapeHtml(displayName) + '\')">' +
                        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>' +
                    '</button>' +
                '</td>' +
            '</tr>';
        });
        tbody.innerHTML = html;
    }

    function renderPagination() {
        document.getElementById('prevPage').disabled = state.page <= 1;
        document.getElementById('nextPage').disabled = state.page >= state.totalPages;
        document.getElementById('pageInfo').textContent = '第 ' + state.page + ' / ' + state.totalPages + ' 页（共 ' + state.total + ' 条）';
    }

    function closeModal(id) {
        var m = document.getElementById(id);
        if (m) m.style.display = 'none';
    }

    function openEdit(userId) {
        var user = state.users.find(function(u) { return u.id === userId; });
        if (!user) return;
        state.editingUserId = userId;
        document.getElementById('editUsername').value = user.username || '';
        document.getElementById('editName').value = user.name || '';
        document.getElementById('editEmail').value = user.email || '';
        document.getElementById('editIsAdmin').checked = user.is_admin === 1 || user.is_admin === true;
        document.getElementById('editModal').style.display = 'flex';
    }

    function saveEdit() {
        if (!state.editingUserId) return;
        var btn = document.getElementById('saveEditBtn');
        btn.disabled = true; btn.textContent = '保存中...';
        var data = {
            username: document.getElementById('editUsername').value.trim(),
            name: document.getElementById('editName').value.trim(),
            email: document.getElementById('editEmail').value.trim(),
            is_admin: document.getElementById('editIsAdmin').checked
        };
        fetch(API_BASE + '/' + state.editingUserId, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin', body: JSON.stringify(data)
        })
        .then(function(r) { return r.json(); })
        .then(function(res) {
            if (res.status === 'success') {
                showToast('用户信息已更新', 'success');
                closeModal('editModal');
                loadUsers();
            } else {
                showToast(res.error || '保存失败', 'error');
            }
        })
        .catch(function() { showToast('网络错误，请重试', 'error'); })
        .finally(function() { btn.disabled = false; btn.textContent = '保存'; });
    }

    function openReset(userId, name) {
        state.resettingUserId = userId;
        document.getElementById('resetDesc').textContent = '为用户「' + (name || '') + '」重置密码';
        document.getElementById('resetPassword').value = '';
        document.getElementById('resetResult').style.display = 'none';
        document.getElementById('resetModal').style.display = 'flex';
    }

    function genRandomPassword() {
        document.getElementById('resetPassword').value = genRandomPwd();
    }

    function confirmReset() {
        if (!state.resettingUserId) return;
        var btn = document.getElementById('confirmResetBtn');
        btn.disabled = true; btn.textContent = '重置中...';
        var pwd = document.getElementById('resetPassword').value.trim();
        fetch(API_BASE + '/' + state.resettingUserId + '/reset-password', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin', body: JSON.stringify({ password: pwd })
        })
        .then(function(r) { return r.json(); })
        .then(function(res) {
            if (res.status === 'success') {
                showToast('密码已重置', 'success');
                document.getElementById('newPasswordDisplay').textContent = res.new_password || pwd;
                document.getElementById('resetResult').style.display = 'block';
                btn.textContent = '完成';
                btn.onclick = function() { closeModal('resetModal'); btn.onclick = null; };
            } else {
                showToast(res.error || '重置失败', 'error');
                btn.disabled = false; btn.textContent = '确认重置';
            }
        })
        .catch(function() { showToast('网络错误，请重试', 'error'); btn.disabled = false; btn.textContent = '确认重置'; });
    }

    function copyPassword() {
        var pwd = document.getElementById('newPasswordDisplay').textContent;
        if (navigator.clipboard) {
            navigator.clipboard.writeText(pwd).then(function() { showToast('密码已复制', 'success'); });
        } else {
            var ta = document.createElement('textarea');
            ta.value = pwd; document.body.appendChild(ta); ta.select();
            document.execCommand('copy'); document.body.removeChild(ta);
            showToast('密码已复制', 'success');
        }
    }

    function toggleAdmin(userId) {
        fetch(API_BASE + '/' + userId + '/toggle-admin', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin'
        })
        .then(function(r) { return r.json(); })
        .then(function(res) {
            if (res.status === 'success') {
                showToast(res.is_admin ? '已设为管理员' : '已取消管理员', 'success');
                loadUsers();
            } else {
                showToast(res.error || '操作失败', 'error');
            }
        })
        .catch(function() { showToast('网络错误，请重试', 'error'); });
    }

    function openDelete(userId, name) {
        state.deletingUserId = userId;
        document.getElementById('deleteWarning').textContent =
            '确定删除用户「' + (name || '') + '」？此操作不可恢复，用户的所有数据（笔记、分析记录、设置等）将被一并删除。';
        document.getElementById('deleteModal').style.display = 'flex';
    }

    function confirmDelete() {
        if (!state.deletingUserId) return;
        var btn = document.getElementById('confirmDeleteBtn');
        btn.disabled = true; btn.textContent = '删除中...';
        fetch(API_BASE + '/' + state.deletingUserId, { method: 'DELETE', credentials: 'same-origin' })
        .then(function(r) { return r.json(); })
        .then(function(res) {
            if (res.status === 'success') {
                showToast('用户已删除', 'success');
                closeModal('deleteModal');
                if (state.users.length === 1 && state.page > 1) state.page--;
                loadUsers();
            } else {
                showToast(res.error || '删除失败', 'error');
            }
        })
        .catch(function() { showToast('网络错误，请重试', 'error'); })
        .finally(function() { btn.disabled = false; btn.textContent = '确认删除'; });
    }

    var searchTimer = null;
    function onSearchInput() {
        var val = document.getElementById('searchInput').value.trim();
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function() { state.search = val; state.page = 1; loadUsers(); }, 300);
    }

    function init() {
        document.getElementById('searchInput').addEventListener('input', onSearchInput);
        document.getElementById('refreshBtn').addEventListener('click', function() { loadUsers(); showToast('已刷新', 'success'); });
        document.getElementById('prevPage').addEventListener('click', function() { if (state.page > 1) { state.page--; loadUsers(); } });
        document.getElementById('nextPage').addEventListener('click', function() { if (state.page < state.totalPages) { state.page++; loadUsers(); } });
        document.querySelectorAll('.modal-overlay').forEach(function(overlay) {
            overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.style.display = 'none'; });
        });
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') document.querySelectorAll('.modal-overlay').forEach(function(m) { m.style.display = 'none'; });
        });
        loadUsers();
    }

    window.AdminUsers = {
        openEdit: openEdit, saveEdit: saveEdit,
        openReset: openReset, genRandomPassword: genRandomPassword, confirmReset: confirmReset, copyPassword: copyPassword,
        toggleAdmin: toggleAdmin, openDelete: openDelete, confirmDelete: confirmDelete, closeModal: closeModal
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
