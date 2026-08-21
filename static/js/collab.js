/* ===== Potential-tools v5.3 协作功能前端组件 =====
 * 包含：分享面板、评论面板、实时轮询、工作空间管理
 * 用法：在页面中引入 <script src="/static/js/collab.js?v=..."></script>
 */

window.PTCollab = (function() {
    'use strict';

    var _shareCode = null;
    var _pollTimer = null;
    var _lastPollTime = 0;
    var _comments = [];
    var _members = [];

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
        div.textContent = str;
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
            console.log('[PTCollab]', msg);
        }
    }

    // ==================== 分享面板 ====================
    function openSharePanel(options) {
        options = options || {};
        var title = options.title || document.title || '未命名';
        var toolType = options.tool_type || '';
        var dataRef = options.data_ref || '';

        // 创建遮罩
        var overlay = document.createElement('div');
        overlay.className = 'pt-share-overlay';
        overlay.id = 'ptShareOverlay';
        overlay.onclick = function(e) {
            if (e.target === overlay) closeSharePanel();
        };

        // 创建面板
        var panel = document.createElement('div');
        panel.className = 'pt-share-panel';
        panel.id = 'ptSharePanel';
        panel.innerHTML =
            '<div class="pt-share-title">🔗 分享工作空间</div>' +
            '<div style="margin-bottom:12px;">' +
            '  <label class="tb-form-label" style="font-size:13px;font-weight:500;color:#1a1a1a;margin-bottom:6px;display:block;">工作空间名称</label>' +
            '  <input type="text" id="ptShareTitle" class="tb-form-input" value="' + _escapeHtml(title) + '" style="width:100%;padding:10px 14px;border:1px solid rgba(0,0,0,0.1);border-radius:8px;font-size:14px;font-family:inherit;box-sizing:border-box;">' +
            '</div>' +
            '<div class="pt-share-permissions">' +
            '  <div class="pt-share-perm-label">权限设置</div>' +
            '  <label class="pt-share-perm-option selected" data-perm="view">' +
            '    <input type="radio" name="ptSharePerm" value="view" checked>' +
            '    <div><div class="pt-share-perm-name">仅查看</div><div class="pt-share-perm-desc">协作者可查看内容和评论</div></div>' +
            '  </label>' +
            '  <label class="pt-share-perm-option" data-perm="edit">' +
            '    <input type="radio" name="ptSharePerm" value="edit">' +
            '    <div><div class="pt-share-perm-name">可编辑</div><div class="pt-share-perm-desc">协作者可编辑内容和添加评论</div></div>' +
            '  </label>' +
            '</div>' +
            '<div id="ptShareLinkRow" class="pt-share-link-row" style="display:none;">' +
            '  <input type="text" id="ptShareLink" class="pt-share-link-input" readonly>' +
            '  <button class="pt-share-copy-btn" onclick="PTCollab.copyShareLink()">复制</button>' +
            '</div>' +
            '<div class="pt-share-actions">' +
            '  <button class="pt-share-close-btn" onclick="PTCollab.closeSharePanel()">取消</button>' +
            '  <button class="pt-share-copy-btn" id="ptShareCreateBtn" onclick="PTCollab._createWorkspace(\'' + _escapeHtml(toolType) + '\', \'' + _escapeHtml(dataRef) + '\')">创建分享链接</button>' +
            '</div>';

        document.body.appendChild(overlay);
        document.body.appendChild(panel);

        // 权限选择交互
        panel.querySelectorAll('.pt-share-perm-option').forEach(function(opt) {
            opt.onclick = function() {
                panel.querySelectorAll('.pt-share-perm-option').forEach(function(o) {
                    o.classList.remove('selected');
                    o.querySelector('input').checked = false;
                });
                opt.classList.add('selected');
                opt.querySelector('input').checked = true;
            };
        });

        // 动画显示
        requestAnimationFrame(function() {
            overlay.classList.add('show');
            panel.classList.add('show');
        });
    }

    function closeSharePanel() {
        var overlay = document.getElementById('ptShareOverlay');
        var panel = document.getElementById('ptSharePanel');
        if (overlay) overlay.classList.remove('show');
        if (panel) panel.classList.remove('show');
        setTimeout(function() {
            if (overlay) overlay.remove();
            if (panel) panel.remove();
        }, 200);
    }

    function _createWorkspace(toolType, dataRef) {
        var titleEl = document.getElementById('ptShareTitle');
        var permEl = document.querySelector('input[name="ptSharePerm"]:checked');
        var title = titleEl ? titleEl.value.trim() : '未命名';
        var permission = permEl ? permEl.value : 'view';

        if (!title) {
            _toast('请输入工作空间名称', 'error');
            return;
        }

        var btn = document.getElementById('ptShareCreateBtn');
        if (btn) { btn.disabled = true; btn.textContent = '创建中...'; }

        _api('/api/collab/workspace/create', {
            method: 'POST',
            body: {
                title: title,
                tool_type: toolType,
                data_ref: dataRef,
                permission: permission,
                expires_days: 7
            }
        }).then(function(data) {
            if (data.status === 'success') {
                var shareUrl = window.location.origin + data.share_url;
                var linkRow = document.getElementById('ptShareLinkRow');
                var linkInput = document.getElementById('ptShareLink');
                if (linkRow && linkInput) {
                    linkInput.value = shareUrl;
                    linkRow.style.display = 'flex';
                }
                if (btn) { btn.textContent = '已创建 ✓'; btn.style.background = '#34c759'; }
                _toast('分享链接已创建', 'success');
                _shareCode = data.share_code;
            }
        }).catch(function(err) {
            _toast('创建失败: ' + err.message, 'error');
            if (btn) { btn.disabled = false; btn.textContent = '创建分享链接'; }
        });
    }

    function copyShareLink() {
        var linkInput = document.getElementById('ptShareLink');
        var url = linkInput ? linkInput.value : (window.location.origin + '/share/' + _shareCode);
        if (navigator.clipboard) {
            navigator.clipboard.writeText(url).then(function() {
                _toast('链接已复制到剪贴板', 'success');
            }).catch(function() {
                _fallbackCopy(url);
            });
        } else {
            _fallbackCopy(url);
        }
    }

    function _fallbackCopy(text) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); _toast('链接已复制', 'success'); }
        catch(e) { _toast('复制失败，请手动复制', 'error'); }
        document.body.removeChild(ta);
    }

    // ==================== 评论面板 ====================
    function toggleComments() {
        var panel = document.getElementById('commentsPanel');
        if (!panel) return;
        if (panel.classList.contains('show')) {
            panel.classList.remove('show');
            _stopPolling();
        } else {
            panel.classList.add('show');
            loadComments();
            _startPolling();
        }
    }

    function loadComments() {
        if (!_shareCode) return;
        _api('/api/collab/workspace/' + _shareCode + '/comments').then(function(data) {
            if (data.status === 'success') {
                _comments = data.comments;
                _renderComments();
            }
        }).catch(function(err) {
            console.warn('加载评论失败:', err);
        });
    }

    function _renderComments() {
        var list = document.getElementById('commentsList');
        if (!list) return;
        if (_comments.length === 0) {
            list.innerHTML = '<div class="pt-comments-empty">暂无评论，来发表第一条吧</div>';
            return;
        }
        list.innerHTML = _comments.map(function(c) {
            var avatarHtml = c.user_avatar
                ? '<img src="' + _escapeHtml(c.user_avatar) + '" style="width:100%;height:100%;object-fit:cover;">'
                : '<span>' + _escapeHtml((c.user_name || '?')[0]) + '</span>';
            return '<div class="pt-comment-item">' +
                '<div class="pt-comment-header">' +
                '  <div class="pt-comment-avatar">' + avatarHtml + '</div>' +
                '  <span class="pt-comment-author">' + _escapeHtml(c.user_name || '匿名用户') + '</span>' +
                '  <span class="pt-comment-time">' + _formatTime(c.created_at) + '</span>' +
                '</div>' +
                '<div class="pt-comment-content">' + _escapeHtml(c.content) + '</div>' +
                '</div>';
        }).join('');
        list.scrollTop = list.scrollHeight;
    }

    function sendComment() {
        if (!_shareCode) return;
        var input = document.getElementById('commentInput');
        var btn = document.getElementById('commentSendBtn');
        var content = input ? input.value.trim() : '';
        if (!content) return;

        if (btn) btn.disabled = true;
        _api('/api/collab/workspace/' + _shareCode + '/comments', {
            method: 'POST',
            body: { content: content }
        }).then(function(data) {
            if (data.status === 'success') {
                _comments.push(data.comment);
                _renderComments();
                if (input) input.value = '';
                _updateCommentBadge();
            }
        }).catch(function(err) {
            _toast('发送失败: ' + err.message, 'error');
        }).finally(function() {
            if (btn) btn.disabled = false;
        });
    }

    function _updateCommentBadge() {
        var badge = document.getElementById('commentBadge');
        if (badge) {
            if (_comments.length > 0) {
                badge.style.display = 'inline-block';
                badge.textContent = _comments.length;
            } else {
                badge.style.display = 'none';
            }
        }
    }

    // ==================== 工作空间管理 ====================
    function joinWorkspace(shareCode) {
        shareCode = shareCode || _shareCode;
        if (!shareCode) return;
        _api('/api/collab/workspace/' + shareCode + '/join', { method: 'POST' }).then(function(data) {
            if (data.status === 'success') {
                _toast('已加入工作空间', 'success');
                loadWorkspaceInfo(shareCode);
            }
        }).catch(function(err) {
            _toast('加入失败: ' + err.message, 'error');
        });
    }

    function loadWorkspaceInfo(shareCode) {
        shareCode = shareCode || _shareCode;
        if (!shareCode) return;
        _api('/api/collab/workspace/' + shareCode).then(function(data) {
            if (data.status === 'success') {
                _members = data.members || [];
                _renderMembers();
                var countEl = document.getElementById('memberCount');
                if (countEl) countEl.textContent = data.member_count;
            }
        }).catch(function(err) {
            console.warn('加载工作空间信息失败:', err);
        });
    }

    function _renderMembers() {
        var list = document.getElementById('membersList');
        if (!list) return;
        if (_members.length === 0) {
            list.innerHTML = '<div class="empty-state">暂无协作者</div>';
            return;
        }
        list.innerHTML = _members.map(function(m) {
            var avatarHtml = m.avatar
                ? '<img src="' + _escapeHtml(m.avatar) + '" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">'
                : '<span>' + _escapeHtml((m.name || '?')[0]) + '</span>';
            var roleLabel = m.role === 'owner' ? '所有者' : (m.role === 'editor' ? '编辑者' : '查看者');
            return '<div class="member-chip">' +
                '<div class="member-avatar">' + avatarHtml + '</div>' +
                '<span>' + _escapeHtml(m.name || '匿名用户') + '</span>' +
                '<span class="member-role">' + roleLabel + '</span>' +
                '</div>';
        }).join('');
    }

    // ==================== 实时轮询 ====================
    function _startPolling() {
        if (_pollTimer) return;
        _lastPollTime = Date.now() / 1000;
        _pollTimer = setInterval(function() {
            if (!_shareCode) return;
            _api('/api/collab/workspace/' + _shareCode + '/poll?since=' + _lastPollTime).then(function(data) {
                if (data.status === 'success') {
                    _lastPollTime = Date.now() / 1000;
                    if (data.new_comments && data.new_comments.length > 0) {
                        _comments = _comments.concat(data.new_comments);
                        _renderComments();
                        _updateCommentBadge();
                    }
                    if (data.members) {
                        _members = data.members;
                        _renderMembers();
                        var countEl = document.getElementById('memberCount');
                        if (countEl) countEl.textContent = data.member_count;
                    }
                }
            }).catch(function() {});
        }, 5000);
    }

    function _stopPolling() {
        if (_pollTimer) {
            clearInterval(_pollTimer);
            _pollTimer = null;
        }
    }

    // ==================== 共享页面初始化 ====================
    function initSharePage(shareCode) {
        _shareCode = shareCode;
        loadWorkspaceInfo(shareCode);
        loadComments();
        _startPolling();

        // 评论输入框自适应高度
        var input = document.getElementById('commentInput');
        if (input) {
            input.addEventListener('input', function() {
                this.style.height = 'auto';
                this.style.height = Math.min(this.scrollHeight, 120) + 'px';
            });
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    sendComment();
                }
            });
        }
    }

    // ==================== 在工具页面添加分享按钮 ====================
    function injectShareButton(containerId, options) {
        var container = containerId ? document.getElementById(containerId) : document.querySelector('.page-header, .tb-header, header');
        if (!container) return;
        if (container.querySelector('.pt-collab-btn')) return;

        var btn = document.createElement('button');
        btn.className = 'pt-collab-btn';
        btn.innerHTML = '🔗 分享';
        btn.onclick = function() {
            openSharePanel(options || {});
        };
        container.appendChild(btn);
    }

    // ==================== 我的工作空间 ====================
    function getMyWorkspaces() {
        return _api('/api/collab/my-workspaces');
    }

    // ==================== 公开 API ====================
    return {
        openSharePanel: openSharePanel,
        closeSharePanel: closeSharePanel,
        _createWorkspace: _createWorkspace,
        copyShareLink: copyShareLink,
        toggleComments: toggleComments,
        loadComments: loadComments,
        sendComment: sendComment,
        joinWorkspace: joinWorkspace,
        loadWorkspaceInfo: loadWorkspaceInfo,
        initSharePage: initSharePage,
        injectShareButton: injectShareButton,
        getMyWorkspaces: getMyWorkspaces,
        getShareCode: function() { return _shareCode; }
    };
})();
