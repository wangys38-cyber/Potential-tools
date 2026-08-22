/* ===== Potential-tools v7.0 协作功能深化前端组件 =====
 * 实时协作状态、增强评论（@提及/线程/已解决）、权限管理、活动历史、团队工作空间
 * 用法：<script src="/static/js/collab-v2.js?v=..."></script>
 * 依赖：无（原生 JS），图标全部使用 SVG 线条
 */
window.PTCollabV2 = (function() {
    'use strict';

    var _shareCode = null;
    var _pollTimer = null;
    var _heartbeatTimer = null;
    var _lastReadAt = 0;
    var _comments = [];
    var _onlineMembers = [];
    var _allMembers = [];
    var _currentUser = null;

    // ==================== 工具函数 ====================
    function _api(url, options) {
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

    function _escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str == null ? '' : String(str);
        return div.innerHTML;
    }

    function _formatTime(ts) {
        if (!ts) return '';
        var d = new Date(ts * 1000);
        var now = new Date();
        var diff = (now - d) / 1000;
        if (diff < 60) return '刚刚';
        if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
        if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
        return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'});
    }

    function _toast(msg, type) {
        if (window.ToolboxToast) {
            ToolboxToast.show(msg, type || 'info');
        } else {
            console.log('[PTCollabV2]', msg);
        }
    }

    function _svgIcon(name, size) {
        size = size || 16;
        var icons = {
            users: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
            message: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
            edit: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
            trash: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
            check: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
            reply: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>',
            clock: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
            shield: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
            history: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/></svg>',
            team: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
            lock: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
            link: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
            plus: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
            send: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>',
            at: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94"/></svg>',
            dot: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="4"/></svg>'
        };
        return icons[name] || '';
    }

    function _avatarHtml(user, size) {
        size = size || 32;
        var name = user.name || '?';
        var letter = name.charAt(0).toUpperCase();
        if (user.avatar) {
            return '<img src="' + _escapeHtml(user.avatar) + '" alt="' + _escapeHtml(name) + '" style="width:' + size + 'px;height:' + size + 'px;border-radius:50%;object-fit:cover;">';
        }
        return '<div style="width:' + size + 'px;height:' + size + 'px;border-radius:50%;background:#1a1a1a;color:#fff;display:flex;align-items:center;justify-content:center;font-size:' + Math.floor(size * 0.4) + 'px;font-weight:600;">' + _escapeHtml(letter) + '</div>';
    }

    function _roleLabel(role) {
        var map = {owner: '所有者', admin: '管理者', editor: '编辑者', viewer: '查看者', member: '成员'};
        return map[role] || role;
    }

    function _actionLabel(type) {
        var map = {
            comment: '发表评论',
            edit: '编辑内容',
            permission_change: '修改权限',
            member_remove: '移除成员',
            member_join: '加入工作空间',
            security_update: '更新安全设置',
            resolve: '解决评论',
            version_restore: '恢复版本'
        };
        return map[type] || type;
    }

    // ==================== 7.1 实时协作状态 ====================

    function startHeartbeat(shareCode, viewingArea) {
        _shareCode = shareCode;
        _sendHeartbeat(viewingArea);
        if (_heartbeatTimer) clearInterval(_heartbeatTimer);
        _heartbeatTimer = setInterval(function() {
            _sendHeartbeat(viewingArea);
        }, 10000);
    }

    function _sendHeartbeat(viewingArea, isEditing, editingArea) {
        if (!_shareCode) return;
        _api('/api/collab-v2/workspace/' + _shareCode + '/heartbeat', {
            method: 'POST',
            body: {
                viewing_area: viewingArea || '',
                is_editing: isEditing ? 1 : 0,
                editing_area: editingArea || ''
            }
        }).catch(function() {});
    }

    function setEditingState(isEditing, editingArea) {
        _sendHeartbeat('', isEditing, editingArea);
    }

    function startPresencePolling(shareCode, callback) {
        _shareCode = shareCode;
        _fetchPresence(callback);
        if (_pollTimer) clearInterval(_pollTimer);
        _pollTimer = setInterval(function() {
            _fetchPresence(callback);
        }, 5000);
    }

    function _fetchPresence(callback) {
        if (!_shareCode) return;
        _api('/api/collab-v2/workspace/' + _shareCode + '/presence').then(function(data) {
            if (data.status === 'success') {
                _onlineMembers = data.members || [];
                if (callback) callback(_onlineMembers, data.online_count);
                _renderPresenceAvatars();
            }
        }).catch(function() {});
    }

    function _renderPresenceAvatars() {
        var container = document.getElementById('ptOnlineAvatars');
        if (!container) return;
        if (_onlineMembers.length === 0) {
            container.innerHTML = '<span style="font-size:12px;color:#86868b;">暂无在线协作者</span>';
            return;
        }
        var html = '<div style="display:flex;align-items:center;gap:-6px;">';
        _onlineMembers.slice(0, 5).forEach(function(m, i) {
            html += '<div style="position:relative;z-index:' + (10 - i) + ';" title="' + _escapeHtml(m.name) + (m.is_editing ? ' (正在编辑)' : '') + '">' +
                _avatarHtml(m, 28) +
                (m.is_editing ? '<span style="position:absolute;bottom:-2px;right:-2px;width:10px;height:10px;background:#34c759;border-radius:50%;border:2px solid #fff;"></span>' : '') +
                '</div>';
        });
        if (_onlineMembers.length > 5) {
            html += '<div style="width:28px;height:28px;border-radius:50%;background:#f5f5f7;display:flex;align-items:center;justify-content:center;font-size:11px;color:#86868b;font-weight:600;margin-left:-6px;">+' + (_onlineMembers.length - 5) + '</div>';
        }
        html += '<span style="margin-left:8px;font-size:12px;color:#86868b;">' + _onlineMembers.length + ' 人在线</span></div>';
        container.innerHTML = html;
    }

    function renderEditingStatus(containerId) {
        var container = document.getElementById(containerId);
        if (!container) return;
        var editing = _onlineMembers.filter(function(m) { return m.is_editing; });
        if (editing.length === 0) {
            container.innerHTML = '';
            return;
        }
        container.innerHTML = editing.map(function(m) {
            return '<div style="display:flex;align-items:center;gap:6px;padding:4px 10px;background:#f5f5f7;border-radius:980px;font-size:12px;">' +
                _avatarHtml(m, 18) +
                '<span style="color:#1a1a1a;">' + _escapeHtml(m.name) + ' 正在编辑' + (m.editing_area ? '：' + _escapeHtml(m.editing_area) : '') + '</span>' +
                '</div>';
        }).join('');
    }

    // ==================== 7.2 增强评论系统 ====================

    function loadCommentsV2(shareCode) {
        _shareCode = shareCode;
        return _api('/api/collab-v2/workspace/' + shareCode + '/comments').then(function(data) {
            if (data.status === 'success') {
                _comments = data.comments || [];
                _renderCommentsV2();
            }
            return data;
        });
    }

    function _renderCommentsV2() {
        var list = document.getElementById('ptCommentsListV2');
        if (!list) return;
        if (_comments.length === 0) {
            list.innerHTML = '<div style="text-align:center;padding:32px;color:#86868b;font-size:13px;">暂无评论，来发表第一条吧</div>';
            return;
        }
        // 构建线程：parent_id=0 为顶级评论
        var topLevel = _comments.filter(function(c) { return !c.parent_id; });
        var replies = {};
        _comments.forEach(function(c) {
            if (c.parent_id) {
                if (!replies[c.parent_id]) replies[c.parent_id] = [];
                replies[c.parent_id].push(c);
            }
        });

        list.innerHTML = topLevel.map(function(c) {
            return _renderCommentItem(c, replies[c.id] || []);
        }).join('');
    }

    function _renderCommentItem(c, replyList) {
        var isOwner = _currentUser && c.user_id === _currentUser.id;
        var resolvedClass = c.is_resolved ? 'pt-comment-resolved' : '';
        var html = '<div class="pt-comment-item-v2 ' + resolvedClass + '" data-id="' + c.id + '" style="padding:12px 0;border-bottom:1px solid #f0f0f0;">';
        html += '<div style="display:flex;gap:10px;">';
        html += _avatarHtml(c, 32);
        html += '<div style="flex:1;min-width:0;">';
        html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">';
        html += '<span style="font-size:13px;font-weight:600;color:#1a1a1a;">' + _escapeHtml(c.user_name) + '</span>';
        html += '<span style="font-size:11px;color:#86868b;">' + _formatTime(c.created_at) + '</span>';
        if (c.edited_at) {
            html += '<span style="font-size:11px;color:#86868b;">(已编辑)</span>';
        }
        if (c.is_resolved) {
            html += '<span style="display:inline-flex;align-items:center;gap:3px;padding:1px 8px;background:#e8f5e9;color:#2e7d32;border-radius:980px;font-size:11px;font-weight:500;">' + _svgIcon('check', 12) + '已解决</span>';
        }
        html += '</div>';
        // 内容（处理 @提及 高亮）
        var contentHtml = _escapeHtml(c.content);
        if (c.mentions && c.mentions.length > 0) {
            c.mentions.forEach(function(m) {
                var name = m.name || m;
                contentHtml = contentHtml.replace(new RegExp('@' + name, 'g'), '<span style="color:#0066cc;font-weight:500;">@' + _escapeHtml(name) + '</span>');
            });
        }
        html += '<div style="font-size:14px;color:#3c3c43;line-height:1.6;word-break:break-word;">' + contentHtml + '</div>';
        // 操作栏
        html += '<div style="display:flex;align-items:center;gap:12px;margin-top:6px;">';
        html += '<button class="pt-comment-action-btn" onclick="PTCollabV2._toggleReplyForm(' + c.id + ')" style="display:inline-flex;align-items:center;gap:4px;background:none;border:none;color:#86868b;font-size:12px;cursor:pointer;padding:2px 4px;">' + _svgIcon('reply', 13) + '回复</button>';
        if (!c.is_resolved) {
            html += '<button class="pt-comment-action-btn" onclick="PTCollabV2.resolveComment(' + c.id + ')" style="display:inline-flex;align-items:center;gap:4px;background:none;border:none;color:#86868b;font-size:12px;cursor:pointer;padding:2px 4px;">' + _svgIcon('check', 13) + '标记已解决</button>';
        } else {
            html += '<button class="pt-comment-action-btn" onclick="PTCollabV2.unresolveComment(' + c.id + ')" style="display:inline-flex;align-items:center;gap:4px;background:none;border:none;color:#86868b;font-size:12px;cursor:pointer;padding:2px 4px;">取消解决</button>';
        }
        if (isOwner) {
            html += '<button class="pt-comment-action-btn" onclick="PTCollabV2._startEditComment(' + c.id + ')" style="display:inline-flex;align-items:center;gap:4px;background:none;border:none;color:#86868b;font-size:12px;cursor:pointer;padding:2px 4px;">' + _svgIcon('edit', 13) + '编辑</button>';
            html += '<button class="pt-comment-action-btn" onclick="PTCollabV2.deleteComment(' + c.id + ')" style="display:inline-flex;align-items:center;gap:4px;background:none;border:none;color:#86868b;font-size:12px;cursor:pointer;padding:2px 4px;">' + _svgIcon('trash', 13) + '删除</button>';
        }
        html += '</div>';
        // 回复表单（默认隐藏）
        html += '<div id="ptReplyForm_' + c.id + '" style="display:none;margin-top:8px;">';
        html += '<div style="display:flex;gap:8px;">';
        html += '<input type="text" id="ptReplyInput_' + c.id + '" placeholder="写下回复..." style="flex:1;padding:8px 12px;border:1px solid #e0e0e0;border-radius:8px;font-size:13px;font-family:inherit;outline:none;" onfocus="this.style.borderColor=\'#333\'" onblur="this.style.borderColor=\'#e0e0e0\'">';
        html += '<button onclick="PTCollabV2._submitReply(' + c.id + ')" style="padding:8px 16px;background:#1a1a1a;color:#fff;border:none;border-radius:8px;font-size:13px;cursor:pointer;font-family:inherit;">发送</button>';
        html += '</div></div>';
        // 编辑表单（默认隐藏）
        html += '<div id="ptEditForm_' + c.id + '" style="display:none;margin-top:8px;">';
        html += '<div style="display:flex;gap:8px;">';
        html += '<input type="text" id="ptEditInput_' + c.id + '" value="' + _escapeHtml(c.content) + '" style="flex:1;padding:8px 12px;border:1px solid #e0e0e0;border-radius:8px;font-size:13px;font-family:inherit;outline:none;" onfocus="this.style.borderColor=\'#333\'" onblur="this.style.borderColor=\'#e0e0e0\'">';
        html += '<button onclick="PTCollabV2._submitEdit(' + c.id + ')" style="padding:8px 16px;background:#1a1a1a;color:#fff;border:none;border-radius:8px;font-size:13px;cursor:pointer;font-family:inherit;">保存</button>';
        html += '<button onclick="PTCollabV2._cancelEdit(' + c.id + ')" style="padding:8px 12px;background:#fff;color:#333;border:1px solid #e0e0e0;border-radius:8px;font-size:13px;cursor:pointer;font-family:inherit;">取消</button>';
        html += '</div></div>';
        // 回复列表
        if (replyList && replyList.length > 0) {
            html += '<div style="margin-top:8px;padding-left:12px;border-left:2px solid #f0f0f0;">';
            replyList.forEach(function(r) {
                html += _renderReplyItem(r);
            });
            html += '</div>';
        }
        html += '</div></div></div>';
        return html;
    }

    function _renderReplyItem(r) {
        var isOwner = _currentUser && r.user_id === _currentUser.id;
        var html = '<div style="padding:8px 0;display:flex;gap:8px;">';
        html += _avatarHtml(r, 24);
        html += '<div style="flex:1;min-width:0;">';
        html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">';
        html += '<span style="font-size:12px;font-weight:600;color:#1a1a1a;">' + _escapeHtml(r.user_name) + '</span>';
        html += '<span style="font-size:11px;color:#86868b;">' + _formatTime(r.created_at) + '</span>';
        html += '</div>';
        html += '<div style="font-size:13px;color:#3c3c43;line-height:1.5;">' + _escapeHtml(r.content) + '</div>';
        if (isOwner) {
            html += '<div style="margin-top:4px;"><button onclick="PTCollabV2.deleteComment(' + r.id + ')" style="background:none;border:none;color:#86868b;font-size:11px;cursor:pointer;padding:0;">删除</button></div>';
        }
        html += '</div></div>';
        return html;
    }

    function sendCommentV2(content, parentId) {
        if (!_shareCode) return Promise.reject(new Error('no share code'));
        // 解析 @提及
        var mentions = [];
        var mentionRegex = /@(\S+)/g;
        var match;
        while ((match = mentionRegex.exec(content)) !== null) {
            var name = match[1];
            var found = _allMembers.find(function(m) { return m.name === name; });
            if (found) {
                mentions.push({user_id: found.user_id, name: found.name});
            }
        }
        return _api('/api/collab-v2/workspace/' + _shareCode + '/comments', {
            method: 'POST',
            body: {content: content, parent_id: parentId || 0, mentions: mentions}
        }).then(function(data) {
            if (data.status === 'success') {
                _comments.push(data.comment);
                _renderCommentsV2();
            }
            return data;
        });
    }

    function _toggleReplyForm(commentId) {
        var form = document.getElementById('ptReplyForm_' + commentId);
        if (form) {
            form.style.display = form.style.display === 'none' ? 'block' : 'none';
            if (form.style.display === 'block') {
                var input = document.getElementById('ptReplyInput_' + commentId);
                if (input) input.focus();
            }
        }
    }

    function _submitReply(commentId) {
        var input = document.getElementById('ptReplyInput_' + commentId);
        var content = input ? input.value.trim() : '';
        if (!content) return;
        sendCommentV2(content, commentId).then(function() {
            if (input) input.value = '';
            _toggleReplyForm(commentId);
        }).catch(function(err) {
            _toast('回复失败: ' + err.message, 'error');
        });
    }

    function _startEditComment(commentId) {
        var editForm = document.getElementById('ptEditForm_' + commentId);
        var replyForm = document.getElementById('ptReplyForm_' + commentId);
        if (editForm) editForm.style.display = 'block';
        if (replyForm) replyForm.style.display = 'none';
        var input = document.getElementById('ptEditInput_' + commentId);
        if (input) input.focus();
    }

    function _submitEdit(commentId) {
        var input = document.getElementById('ptEditInput_' + commentId);
        var content = input ? input.value.trim() : '';
        if (!content) return;
        _api('/api/collab-v2/comments/' + commentId + '/edit', {
            method: 'POST',
            body: {content: content}
        }).then(function(data) {
            if (data.status === 'success') {
                var c = _comments.find(function(x) { return x.id === commentId; });
                if (c) { c.content = content; c.edited_at = data.edited_at; }
                _renderCommentsV2();
                _toast('编辑成功', 'success');
            }
        }).catch(function(err) {
            _toast('编辑失败: ' + err.message, 'error');
        });
    }

    function _cancelEdit(commentId) {
        var editForm = document.getElementById('ptEditForm_' + commentId);
        if (editForm) editForm.style.display = 'none';
    }

    function deleteComment(commentId) {
        if (!confirm('确定删除这条评论吗？')) return;
        _api('/api/collab-v2/comments/' + commentId + '/delete', {method: 'POST'}).then(function(data) {
            if (data.status === 'success') {
                _comments = _comments.filter(function(c) { return c.id !== commentId && c.parent_id !== commentId; });
                _renderCommentsV2();
                _toast('已删除', 'success');
            }
        }).catch(function(err) {
            _toast('删除失败: ' + err.message, 'error');
        });
    }

    function resolveComment(commentId) {
        _api('/api/collab-v2/comments/' + commentId + '/resolve', {method: 'POST'}).then(function(data) {
            if (data.status === 'success') {
                var c = _comments.find(function(x) { return x.id === commentId; });
                if (c) { c.is_resolved = true; c.resolved_at = data.resolved_at; }
                _renderCommentsV2();
            }
        }).catch(function(err) {
            _toast('操作失败: ' + err.message, 'error');
        });
    }

    function unresolveComment(commentId) {
        _api('/api/collab-v2/comments/' + commentId + '/unresolve', {method: 'POST'}).then(function(data) {
            if (data.status === 'success') {
                var c = _comments.find(function(x) { return x.id === commentId; });
                if (c) { c.is_resolved = false; }
                _renderCommentsV2();
            }
        }).catch(function(err) {
            _toast('操作失败: ' + err.message, 'error');
        });
    }

    function getUnreadCount(shareCode, since) {
        return _api('/api/collab-v2/workspace/' + shareCode + '/comments/unread?since=' + (since || 0)).then(function(data) {
            return data.unread_count || 0;
        });
    }

    // ==================== 7.3 权限管理 ====================

    function loadMembersV2(shareCode) {
        _shareCode = shareCode;
        return _api('/api/collab-v2/workspace/' + shareCode + '/members').then(function(data) {
            if (data.status === 'success') {
                _allMembers = data.members || [];
                _renderMembersV2();
            }
            return data;
        });
    }

    function _renderMembersV2() {
        var container = document.getElementById('ptMembersListV2');
        if (!container) return;
        if (_allMembers.length === 0) {
            container.innerHTML = '<div style="text-align:center;padding:24px;color:#86868b;font-size:13px;">暂无成员</div>';
            return;
        }
        container.innerHTML = _allMembers.map(function(m) {
            var canManage = _currentUser && (_currentUser.id === m.user_id || _currentUser.role === 'admin' || _currentUser.is_owner);
            var html = '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid #f5f5f7;">';
            html += '<div style="display:flex;align-items:center;gap:10px;">';
            html += _avatarHtml(m, 32);
            html += '<div>';
            html += '<div style="font-size:14px;font-weight:500;color:#1a1a1a;">' + _escapeHtml(m.name) + '</div>';
            html += '<div style="font-size:11px;color:#86868b;">' + _formatTime(m.joined_at) + '加入</div>';
            html += '</div></div>';
            html += '<div style="display:flex;align-items:center;gap:8px;">';
            html += '<select onchange="PTCollabV2.changeMemberRole(' + m.user_id + ', this.value)" ' + (canManage ? '' : 'disabled') + ' style="padding:4px 8px;border:1px solid #e0e0e0;border-radius:6px;font-size:12px;font-family:inherit;background:#fff;cursor:' + (canManage ? 'pointer' : 'not-allowed') + ';">';
            ['viewer', 'editor', 'admin'].forEach(function(r) {
                html += '<option value="' + r + '"' + (m.role === r ? ' selected' : '') + '>' + _roleLabel(r) + '</option>';
            });
            html += '</select>';
            if (canManage && m.role !== 'owner') {
                html += '<button onclick="PTCollabV2.removeMember(' + m.user_id + ')" style="background:none;border:none;color:#86868b;cursor:pointer;padding:4px;" title="移除">' + _svgIcon('trash', 15) + '</button>';
            }
            html += '</div></div>';
            return html;
        }).join('');
    }

    function changeMemberRole(userId, role) {
        if (!_shareCode) return;
        _api('/api/collab-v2/workspace/' + _shareCode + '/members/' + userId + '/role', {
            method: 'POST',
            body: {role: role}
        }).then(function(data) {
            if (data.status === 'success') {
                _toast('权限已更新', 'success');
                loadMembersV2(_shareCode);
            }
        }).catch(function(err) {
            _toast('更新失败: ' + err.message, 'error');
        });
    }

    function removeMember(userId) {
        if (!confirm('确定移除该成员吗？')) return;
        if (!_shareCode) return;
        _api('/api/collab-v2/workspace/' + _shareCode + '/members/' + userId + '/remove', {method: 'POST'}).then(function(data) {
            if (data.status === 'success') {
                _toast('已移除成员', 'success');
                loadMembersV2(_shareCode);
            }
        }).catch(function(err) {
            _toast('移除失败: ' + err.message, 'error');
        });
    }

    function updateSecurity(password, accessLimit) {
        if (!_shareCode) return Promise.reject(new Error('no share code'));
        return _api('/api/collab-v2/workspace/' + _shareCode + '/security', {
            method: 'POST',
            body: {password: password || '', access_limit: accessLimit || 0}
        });
    }

    // ==================== 7.4 协作历史记录 ====================

    function loadActivity(shareCode, actionType) {
        var url = '/api/collab-v2/workspace/' + shareCode + '/activity';
        if (actionType) url += '?type=' + encodeURIComponent(actionType);
        return _api(url).then(function(data) {
            if (data.status === 'success') {
                _renderActivity(data.activities || []);
            }
            return data;
        });
    }

    function _renderActivity(activities) {
        var container = document.getElementById('ptActivityList');
        if (!container) return;
        if (activities.length === 0) {
            container.innerHTML = '<div style="text-align:center;padding:24px;color:#86868b;font-size:13px;">暂无活动记录</div>';
            return;
        }
        container.innerHTML = '<div style="position:relative;padding-left:20px;">' +
            '<div style="position:absolute;left:5px;top:8px;bottom:8px;width:2px;background:#e8e8ed;"></div>' +
            activities.map(function(a) {
                return '<div style="position:relative;padding:8px 0 16px;">' +
                    '<div style="position:absolute;left:-20px;top:10px;width:12px;height:12px;border-radius:50%;background:#1a1a1a;border:2px solid #fff;"></div>' +
                    '<div style="display:flex;align-items:center;gap:8px;margin-bottom:2px;">' +
                    _avatarHtml(a, 20) +
                    '<span style="font-size:13px;font-weight:500;color:#1a1a1a;">' + _escapeHtml(a.user_name) + '</span>' +
                    '<span style="font-size:12px;color:#86868b;">' + _actionLabel(a.action_type) + '</span>' +
                    '</div>' +
                    (a.action_detail ? '<div style="font-size:12px;color:#86868b;margin-left:28px;">' + _escapeHtml(a.action_detail) + '</div>' : '') +
                    '<div style="font-size:11px;color:#c7c7cc;margin-left:28px;">' + _formatTime(a.created_at) + '</div>' +
                    '</div>';
            }).join('') + '</div>';
    }

    // ==================== 7.5 团队工作空间 ====================

    function createTeam(name, description) {
        return _api('/api/collab-v2/teams/create', {
            method: 'POST',
            body: {name: name, description: description || ''}
        });
    }

    function getMyTeams() {
        return _api('/api/collab-v2/teams/my');
    }

    function getTeam(teamCode) {
        return _api('/api/collab-v2/teams/' + teamCode);
    }

    function joinTeam(teamCode) {
        return _api('/api/collab-v2/teams/' + teamCode + '/join', {method: 'POST'});
    }

    function renderTeamList(containerId, teams) {
        var container = document.getElementById(containerId);
        if (!container) return;
        if (!teams || teams.length === 0) {
            container.innerHTML = '<div style="text-align:center;padding:32px;color:#86868b;font-size:13px;">暂无团队，创建一个开始协作</div>';
            return;
        }
        container.innerHTML = teams.map(function(t) {
            return '<a href="/teams/' + t.team_code + '" style="display:block;background:#fff;border:1px solid rgba(0,0,0,0.06);border-radius:12px;padding:16px;margin-bottom:10px;text-decoration:none;color:inherit;transition:box-shadow 0.15s;" onmouseover="this.style.boxShadow=\'0 4px 12px rgba(0,0,0,0.08)\'" onmouseout="this.style.boxShadow=\'none\'">' +
                '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">' +
                '<div style="width:36px;height:36px;border-radius:10px;background:#1a1a1a;color:#fff;display:flex;align-items:center;justify-content:center;">' + _svgIcon('team', 18) + '</div>' +
                '<div style="flex:1;">' +
                '<div style="font-size:15px;font-weight:600;color:#1a1a1a;">' + _escapeHtml(t.name) + '</div>' +
                (t.description ? '<div style="font-size:12px;color:#86868b;">' + _escapeHtml(t.description) + '</div>' : '') +
                '</div>' +
                (t.is_owner ? '<span style="font-size:11px;padding:2px 8px;background:#f5f5f7;border-radius:980px;color:#86868b;">所有者</span>' : '') +
                '</div></a>';
        }).join('');
    }

    function renderTeamMembers(containerId, members) {
        var container = document.getElementById(containerId);
        if (!container) return;
        if (!members || members.length === 0) {
            container.innerHTML = '<div style="text-align:center;padding:24px;color:#86868b;font-size:13px;">暂无成员</div>';
            return;
        }
        container.innerHTML = members.map(function(m) {
            return '<div style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid #f5f5f7;">' +
                _avatarHtml(m, 32) +
                '<div style="flex:1;">' +
                '<div style="font-size:14px;font-weight:500;color:#1a1a1a;">' + _escapeHtml(m.name) + '</div>' +
                '<div style="font-size:11px;color:#86868b;">' + _formatTime(m.joined_at) + '加入</div>' +
                '</div>' +
                '<span style="font-size:11px;padding:2px 8px;background:#f5f5f7;border-radius:980px;color:#86868b;">' + _roleLabel(m.role) + '</span>' +
                '</div>';
        }).join('');
    }

    // ==================== 页面初始化 ====================

    function initWorkspacePage(shareCode, userInfo) {
        _shareCode = shareCode;
        _currentUser = userInfo || null;
        _lastReadAt = Date.now() / 1000;

        // 启动心跳和在线状态轮询
        startHeartbeat(shareCode);
        startPresencePolling(shareCode);

        // 加载评论和成员
        loadCommentsV2(shareCode);
        loadMembersV2(shareCode);

        // 评论输入框
        var input = document.getElementById('ptCommentInputV2');
        if (input) {
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    _submitTopComment();
                }
            });
        }
        var sendBtn = document.getElementById('ptCommentSendV2');
        if (sendBtn) {
            sendBtn.onclick = _submitTopComment;
        }
    }

    function _submitTopComment() {
        var input = document.getElementById('ptCommentInputV2');
        var content = input ? input.value.trim() : '';
        if (!content) return;
        var btn = document.getElementById('ptCommentSendV2');
        if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
        sendCommentV2(content).then(function() {
            if (input) input.value = '';
            _lastReadAt = Date.now() / 1000;
        }).catch(function(err) {
            _toast('发送失败: ' + err.message, 'error');
        }).finally(function() {
            if (btn) { btn.disabled = false; btn.style.opacity = ''; }
        });
    }

    function stopPolling() {
        if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
        if (_heartbeatTimer) { clearInterval(_heartbeatTimer); _heartbeatTimer = null; }
    }

    // ==================== 公开 API ====================
    return {
        // 实时状态
        startHeartbeat: startHeartbeat,
        setEditingState: setEditingState,
        startPresencePolling: startPresencePolling,
        renderEditingStatus: renderEditingStatus,
        // 评论
        initWorkspacePage: initWorkspacePage,
        loadCommentsV2: loadCommentsV2,
        sendCommentV2: sendCommentV2,
        deleteComment: deleteComment,
        resolveComment: resolveComment,
        unresolveComment: unresolveComment,
        getUnreadCount: getUnreadCount,
        _toggleReplyForm: _toggleReplyForm,
        _submitReply: _submitReply,
        _startEditComment: _startEditComment,
        _submitEdit: _submitEdit,
        _cancelEdit: _cancelEdit,
        // 权限
        loadMembersV2: loadMembersV2,
        changeMemberRole: changeMemberRole,
        removeMember: removeMember,
        updateSecurity: updateSecurity,
        // 活动历史
        loadActivity: loadActivity,
        // 团队
        createTeam: createTeam,
        getMyTeams: getMyTeams,
        getTeam: getTeam,
        joinTeam: joinTeam,
        renderTeamList: renderTeamList,
        renderTeamMembers: renderTeamMembers,
        // 工具
        stopPolling: stopPolling,
        getOnlineMembers: function() { return _onlineMembers; },
        getAllMembers: function() { return _allMembers; }
    };
})();
