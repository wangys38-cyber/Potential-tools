window.__PD__ = window.__PD__ || {};
window.TeamDetail = (function() {
    'use strict';
    var TEAM_CODE = 'window.__PD__.team_code';
    var teamId = null;
    var teamData = null;
    var currentTab = 'members';
    var currentFilter = 'all';

    function api(url, options) {
        options = options || {};
        options.credentials = 'same-origin';
        if (options.body && typeof options.body === 'object') {
            options.headers = options.headers || {};
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(options.body);
        }
        return fetch(url, options).then(function(r) {
            return r.json().then(function(data) {
                if (!r.ok && data.error) throw new Error(data.error);
                return data;
            });
        });
    }

    function escapeHtml(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function formatTime(ts) {
        if (!ts) return '';
        var d = new Date(ts * 1000);
        return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'});
    }

    function toast(msg) {
        var el = document.getElementById('tdToast');
        el.textContent = msg;
        el.classList.add('show');
        setTimeout(function() { el.classList.remove('show'); }, 2000);
    }

    function avatarHtml(user, size) {
        size = size || 36;
        var name = user.name || '?';
        var letter = name.charAt(0).toUpperCase();
        if (user.avatar) {
            return '<div class="td-avatar"><img src="' + escapeHtml(user.avatar) + '" alt="' + escapeHtml(name) + '"></div>';
        }
        return '<div class="td-avatar">' + escapeHtml(letter) + '</div>';
    }

    function typeLabel(type) {
        var map = {
            cr_analysis: 'CR分析', project_plan: '项目计划',
            knowledge_graph: '知识图谱', report: '报告',
            test_report: '测试报告', general: '其他'
        };
        return map[type] || type;
    }

    function loadTeam() {
        // 先通过 team_code 获取团队信息（用旧 API 兼容）
        api('/api/collab-v2/teams/' + TEAM_CODE).then(function(res) {
            if (res.status !== 'success') throw new Error(res.error || '加载失败');
            teamId = res.team.id;
            teamData = res;
            renderHeader(res);
            loadMembers();
            loadData();
            renderSettings();
        }).catch(function(err) {
            document.getElementById('tdTeamName').textContent = '加载失败';
            document.getElementById('tdTeamDesc').textContent = err.message;
        });
    }

    function renderHeader(res) {
        var team = res.team;
        document.getElementById('tdTeamName').textContent = team.name;
        document.getElementById('tdTeamDesc').textContent = team.description || '';
        document.getElementById('tdMemberCount').textContent = '(' + res.member_count + ')';

        var isAdmin = team.is_owner || (res.members || []).some(function(m) {
            return m.user_id === team.owner_id ? false : m.user_id == {{ current_user.id if current_user else 0 }} && m.role === 'admin';
        });
        // 简化：通过 my_role 判断
        var myRole = team.my_role || (team.is_owner ? 'owner' : 'member');
        var canManage = team.is_owner || myRole === 'admin';

        var actions = document.getElementById('tdHeaderActions');
        var html = '';
        if (canManage) {
            html += '<button class="td-btn secondary" onclick="TeamDetail.openEditModal()">编辑</button>';
        }
        if (team.is_owner) {
            html += '<button class="td-btn danger" onclick="TeamDetail.deleteTeam()">删除团队</button>';
        }
        actions.innerHTML = html;

        if (canManage) {
            document.getElementById('tdInviteBtn').style.display = 'inline-flex';
        }
    }

    function loadMembers() {
        if (!teamId) return;
        api('/api/teams/' + teamId).then(function(res) {
            if (res.status !== 'success') throw new Error('加载成员失败');
            renderMembers(res.members, res.team);
        }).catch(function(err) {
            document.getElementById('tdMemberList').innerHTML = '<div class="td-empty">加载失败: ' + escapeHtml(err.message) + '</div>';
        });
    }

    function renderMembers(members, team) {
        var container = document.getElementById('tdMemberList');
        if (!members || members.length === 0) {
            container.innerHTML = '<div class="td-empty">暂无成员</div>';
            return;
        }
        var myRole = team.my_role || (team.is_owner ? 'owner' : 'member');
        var canManage = team.is_owner || myRole === 'admin';
        var currentUid = {{ current_user.id if current_user else 0 }};

        container.innerHTML = members.map(function(m) {
            var isOwner = m.user_id === team.owner_id;
            var roleClass = isOwner ? 'owner' : (m.role === 'admin' ? 'admin' : '');
            var roleText = isOwner ? '所有者' : (m.role === 'admin' ? '管理员' : '成员');
            var actions = '';
            if (canManage && !isOwner && m.user_id !== currentUid) {
                var newRole = m.role === 'admin' ? 'member' : 'admin';
                var roleBtnText = m.role === 'admin' ? '降为成员' : '设为管理员';
                actions = '<div class="td-member-actions">' +
                    '<button class="td-icon-btn" title="' + roleBtnText + '" onclick="TeamDetail.changeRole(' + m.user_id + ',\'' + newRole + '\')">' +
                    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>' +
                    '</button>' +
                    '<button class="td-icon-btn danger" title="移除" onclick="TeamDetail.removeMember(' + m.user_id + ')">' +
                    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>' +
                    '</button></div>';
            }
            return '<div class="td-member-row">' +
                avatarHtml(m, 36) +
                '<div class="td-member-info">' +
                '<div class="td-member-name">' + escapeHtml(m.name) + '</div>' +
                (m.email ? '<div class="td-member-email">' + escapeHtml(m.email) + '</div>' : '') +
                '</div>' +
                '<span class="td-role-badge ' + roleClass + '">' + roleText + '</span>' +
                actions +
                '</div>';
        }).join('');
    }

    function loadData() {
        if (!teamId) return;
        api('/api/teams/' + teamId + '/data').then(function(res) {
            if (res.status !== 'success') throw new Error('加载数据失败');
            renderDataFilter(res.data);
            renderDataList(res.data);
            document.getElementById('tdDataCount').textContent = '(' + res.total + ')';
        }).catch(function(err) {
            document.getElementById('tdDataList').innerHTML = '<div class="td-empty">加载失败: ' + escapeHtml(err.message) + '</div>';
        });
    }

    function renderDataFilter(data) {
        var types = {};
        (data || []).forEach(function(d) { types[d.data_type] = (types[d.data_type] || 0) + 1; });
        var container = document.getElementById('tdDataFilter');
        var html = '<button class="td-filter-chip ' + (currentFilter === 'all' ? 'active' : '') + '" onclick="TeamDetail.filterData(\'all\')">全部 (' + (data || []).length + ')</button>';
        Object.keys(types).forEach(function(t) {
            html += '<button class="td-filter-chip ' + (currentFilter === t ? 'active' : '') + '" onclick="TeamDetail.filterData(\'' + t + '\')">' + typeLabel(t) + ' (' + types[t] + ')</button>';
        });
        container.innerHTML = html;
    }

    function renderDataList(data) {
        var container = document.getElementById('tdDataList');
        var filtered = currentFilter === 'all' ? (data || []) : (data || []).filter(function(d) { return d.data_type === currentFilter; });
        if (filtered.length === 0) {
            container.innerHTML = '<div class="td-empty">暂无共享数据</div>';
            return;
        }
        var currentUid = {{ current_user.id if current_user else 0 }};
        container.innerHTML = filtered.map(function(d) {
            var canDelete = d.shared_by === currentUid || (teamData && teamData.team && (teamData.team.is_owner || teamData.team.my_role === 'admin'));
            return '<div class="td-data-card" onclick="TeamDetail.viewData(' + d.id + ')">' +
                '<span class="td-data-type">' + typeLabel(d.data_type) + '</span>' +
                '<div class="td-data-title">' + escapeHtml(d.title || d.data_ref) + '</div>' +
                '<div class="td-data-meta">' +
                '<span>' + escapeHtml(d.shared_by_name || '未知用户') + ' 分享</span>' +
                '<span>' + formatTime(d.created_at) + '</span>' +
                (d.permissions && d.permissions.access === 'edit' ? '<span>可编辑</span>' : '<span>只读</span>') +
                (canDelete ? '<span style="margin-left:auto;cursor:pointer;color:#ff3b30;" onclick="event.stopPropagation();TeamDetail.unshareData(' + d.id + ')">取消分享</span>' : '') +
                '</div></div>';
        }).join('');
    }

    function renderSettings() {
        if (!teamData) return;
        var team = teamData.team;
        var container = document.getElementById('tdSettingsContent');
        var canManage = team.is_owner || team.my_role === 'admin';
        container.innerHTML = '<div style="margin-bottom:16px;">' +
            '<div style="font-size:13px;color:#86868b;margin-bottom:4px;">团队 ID</div>' +
            '<div style="font-size:14px;font-family:monospace;color:#1a1a1a;">' + team.id + '</div></div>' +
            '<div style="margin-bottom:16px;">' +
            '<div style="font-size:13px;color:#86868b;margin-bottom:4px;">团队邀请码</div>' +
            '<div style="font-size:14px;font-family:monospace;color:#1a1a1a;display:flex;align-items:center;gap:8px;">' +
            escapeHtml(team.team_code) +
            '<button class="td-icon-btn" onclick="TeamDetail.copyCode()" style="width:28px;height:28px;">' +
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
            '</button></div></div>' +
            '<div style="margin-bottom:16px;">' +
            '<div style="font-size:13px;color:#86868b;margin-bottom:4px;">创建时间</div>' +
            '<div style="font-size:14px;color:#1a1a1a;">' + formatTime(team.created_at) + '</div></div>' +
            (canManage ? '<div style="margin-top:20px;padding-top:16px;border-top:1px solid #f0f0f0;">' +
            '<button class="td-btn secondary" onclick="TeamDetail.openEditModal()">编辑团队信息</button>' +
            '</div>' : '');
    }

    function switchTab(tab) {
        currentTab = tab;
        document.querySelectorAll('.td-tab').forEach(function(el) {
            el.classList.toggle('active', el.dataset.tab === tab);
        });
        document.getElementById('tdTabMembers').style.display = tab === 'members' ? '' : 'none';
        document.getElementById('tdTabData').style.display = tab === 'data' ? '' : 'none';
        document.getElementById('tdTabSettings').style.display = tab === 'settings' ? '' : 'none';
    }

    function filterData(type) {
        currentFilter = type;
        loadData();
    }

    function openInviteModal() {
        document.getElementById('tdInviteModal').classList.add('show');
        document.getElementById('tdInviteEmail').focus();
    }
    function closeInviteModal() {
        document.getElementById('tdInviteModal').classList.remove('show');
        document.getElementById('tdInviteEmail').value = '';
        document.getElementById('tdInviteUserId').value = '';
    }
    function submitInvite() {
        var email = document.getElementById('tdInviteEmail').value.trim();
        var userId = document.getElementById('tdInviteUserId').value.trim();
        var role = document.getElementById('tdInviteRole').value;
        if (!email && !userId) { alert('请输入邮箱或用户 ID'); return; }
        var body = {role: role};
        if (email) body.email = email;
        if (userId) body.user_id = userId;
        var btn = document.getElementById('tdInviteConfirm');
        btn.disabled = true; btn.textContent = '邀请中...';
        api('/api/teams/' + teamId + '/members', {method: 'POST', body: body}).then(function(res) {
            if (res.status === 'success') {
                toast('邀请成功');
                closeInviteModal();
                loadMembers();
            } else {
                alert(res.error || '邀请失败');
            }
        }).catch(function(err) {
            alert('邀请失败: ' + err.message);
        }).finally(function() {
            btn.disabled = false; btn.textContent = '邀请';
        });
    }

    function changeRole(userId, role) {
        api('/api/teams/' + teamId + '/members/' + userId, {method: 'PUT', body: {role: role}}).then(function(res) {
            if (res.status === 'success') { toast('角色已更新'); loadMembers(); }
            else alert(res.error || '操作失败');
        }).catch(function(err) { alert('操作失败: ' + err.message); });
    }

    function removeMember(userId) {
        if (!confirm('确定移除该成员？')) return;
        api('/api/teams/' + teamId + '/members/' + userId, {method: 'DELETE'}).then(function(res) {
            if (res.status === 'success') { toast('已移除'); loadMembers(); }
            else alert(res.error || '操作失败');
        }).catch(function(err) { alert('操作失败: ' + err.message); });
    }

    function openEditModal() {
        if (!teamData) return;
        document.getElementById('tdEditName').value = teamData.team.name;
        document.getElementById('tdEditDesc').value = teamData.team.description || '';
        document.getElementById('tdEditModal').classList.add('show');
    }
    function closeEditModal() {
        document.getElementById('tdEditModal').classList.remove('show');
    }
    function submitEdit() {
        var name = document.getElementById('tdEditName').value.trim();
        var desc = document.getElementById('tdEditDesc').value.trim();
        if (!name) { alert('团队名称不能为空'); return; }
        api('/api/teams/' + teamId, {method: 'PUT', body: {name: name, description: desc}}).then(function(res) {
            if (res.status === 'success') {
                toast('已保存');
                closeEditModal();
                loadTeam();
            } else { alert(res.error || '保存失败'); }
        }).catch(function(err) { alert('保存失败: ' + err.message); });
    }

    function deleteTeam() {
        if (!confirm('确定删除该团队？此操作不可恢复。')) return;
        api('/api/teams/' + teamId, {method: 'DELETE'}).then(function(res) {
            if (res.status === 'success') { window.location.href = '/teams'; }
            else alert(res.error || '删除失败');
        }).catch(function(err) { alert('删除失败: ' + err.message); });
    }

    function viewData(dataId) {
        api('/api/teams/' + teamId + '/data/' + dataId).then(function(res) {
            if (res.status !== 'success') throw new Error('加载失败');
            var d = res.data;
            alert('数据类型: ' + typeLabel(d.data_type) + '\n标题: ' + (d.title || d.data_ref) + '\n分享者: ' + (d.shared_by_name || '') + '\n时间: ' + formatTime(d.created_at));
        }).catch(function(err) { alert('加载失败: ' + err.message); });
    }

    function unshareData(dataId) {
        if (!confirm('确定取消分享？')) return;
        api('/api/teams/' + teamId + '/data/' + dataId, {method: 'DELETE'}).then(function(res) {
            if (res.status === 'success') { toast('已取消分享'); loadData(); }
            else alert(res.error || '操作失败');
        }).catch(function(err) { alert('操作失败: ' + err.message); });
    }

    function copyCode() {
        if (!teamData) return;
        var code = teamData.team.team_code;
        if (navigator.clipboard) {
            navigator.clipboard.writeText(code).then(function() { toast('已复制邀请码'); });
        } else {
            var ta = document.createElement('textarea');
            ta.value = code; document.body.appendChild(ta); ta.select();
            document.execCommand('copy'); document.body.removeChild(ta);
            toast('已复制邀请码');
        }
    }

    // 弹窗外部点击关闭
    document.addEventListener('click', function(e) {
        if (e.target.id === 'tdInviteModal') closeInviteModal();
        if (e.target.id === 'tdEditModal') closeEditModal();
    });

    loadTeam();

    return {
        switchTab: switchTab, filterData: filterData,
        openInviteModal: openInviteModal, closeInviteModal: closeInviteModal, submitInvite: submitInvite,
        changeRole: changeRole, removeMember: removeMember,
        openEditModal: openEditModal, closeEditModal: closeEditModal, submitEdit: submitEdit,
        deleteTeam: deleteTeam, viewData: viewData, unshareData: unshareData, copyCode: copyCode
    };
})();