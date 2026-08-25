/* ===== Potential-tools v11.0 团队数据共享 =====
 * 用法：<script src="/static/js/team-share.js?v=..."></script>
 * 调用：PTTeamShare.open(dataType, dataRef, title)
 * 依赖：无（原生 JS）
 */
window.PTTeamShare = (function() {
    'use strict';

    var _modal = null;
    var _currentData = null;
    var _teams = [];

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

    function _escapeHtml(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function _toast(msg) {
        var el = document.getElementById('ptTeamShareToast');
        if (!el) {
            el = document.createElement('div');
            el.id = 'ptTeamShareToast';
            el.style.cssText = 'position:fixed;top:80px;left:50%;transform:translateX(-50%);background:#1a1a1a;color:#fff;padding:10px 20px;border-radius:10px;font-size:14px;z-index:10001;opacity:0;transition:opacity 0.2s;pointer-events:none;font-family:inherit;';
            document.body.appendChild(el);
        }
        el.textContent = msg;
        el.style.opacity = '1';
        setTimeout(function() { el.style.opacity = '0'; }, 2000);
    }

    function _ensureModal() {
        if (_modal) return _modal;
        _modal = document.createElement('div');
        _modal.id = 'ptTeamShareModal';
        _modal.style.cssText = 'display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:10000;justify-content:center;align-items:center;';
        _modal.innerHTML = '<div style="background:#fff;border-radius:16px;padding:24px;width:90%;max-width:440px;box-shadow:0 20px 60px rgba(0,0,0,0.3);max-height:90vh;overflow-y:auto;">' +
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">' +
            '<span style="font-size:18px;font-weight:600;color:#1a1a1a;">分享到团队</span>' +
            '<button onclick="PTTeamShare.close()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#999;padding:0;width:28px;height:28px;display:flex;align-items:center;justify-content:center;border-radius:50%;" onmouseover="this.style.background=\'#f0f0f0\'" onmouseout="this.style.background=\'none\'">×</button>' +
            '</div>' +
            '<div id="ptShareDataInfo" style="background:#f5f5f7;border-radius:10px;padding:12px 14px;margin-bottom:16px;font-size:13px;color:#1a1a1a;"></div>' +
            '<div style="margin-bottom:14px;"><label style="display:block;font-size:13px;font-weight:500;color:#1a1a1a;margin-bottom:6px;">选择团队</label>' +
            '<div id="ptShareTeamList" style="max-height:200px;overflow-y:auto;border:1px solid #e0e0e0;border-radius:10px;"></div></div>' +
            '<div style="margin-bottom:16px;"><label style="display:block;font-size:13px;font-weight:500;color:#1a1a1a;margin-bottom:6px;">权限</label>' +
            '<div style="display:flex;gap:8px;">' +
            '<label style="flex:1;display:flex;align-items:center;gap:8px;padding:10px 14px;border:1px solid #e0e0e0;border-radius:10px;cursor:pointer;font-size:13px;" onclick="document.getElementById(\'ptPermView\').checked=true">' +
            '<input type="radio" name="ptSharePerm" id="ptPermView" value="view" checked style="accent-color:#1a1a1a;"> 只读</label>' +
            '<label style="flex:1;display:flex;align-items:center;gap:8px;padding:10px 14px;border:1px solid #e0e0e0;border-radius:10px;cursor:pointer;font-size:13px;" onclick="document.getElementById(\'ptPermEdit\').checked=true">' +
            '<input type="radio" name="ptSharePerm" id="ptPermEdit" value="edit" style="accent-color:#1a1a1a;"> 可编辑</label>' +
            '</div></div>' +
            '<div style="display:flex;gap:10px;">' +
            '<button onclick="PTTeamShare.close()" style="flex:1;padding:10px;border-radius:10px;font-size:14px;cursor:pointer;font-family:inherit;border:none;background:#f5f5f7;color:#1a1a1a;transition:opacity 0.15s;" onmouseover="this.style.opacity=\'0.85\'" onmouseout="this.style.opacity=\'1\'">取消</button>' +
            '<button id="ptShareConfirmBtn" onclick="PTTeamShare.submit()" style="flex:1;padding:10px;border-radius:10px;font-size:14px;cursor:pointer;font-family:inherit;border:none;background:#1a1a1a;color:#fff;transition:opacity 0.15s;" onmouseover="this.style.opacity=\'0.85\'" onmouseout="this.style.opacity=\'1\'">分享</button>' +
            '</div></div>';
        document.body.appendChild(_modal);
        _modal.addEventListener('click', function(e) {
            if (e.target === _modal) close();
        });
        return _modal;
    }

    function _typeLabel(type) {
        var map = {
            cr_analysis: 'CR分析', project_plan: '项目计划',
            knowledge_graph: '知识图谱', report: '报告',
            test_report: '测试报告', general: '其他'
        };
        return map[type] || type;
    }

    function open(dataType, dataRef, title) {
        if (!dataRef) {
            _toast('没有可分享的数据');
            return;
        }
        _ensureModal();
        _currentData = { data_type: dataType || 'general', data_ref: dataRef, title: title || '' };

        document.getElementById('ptShareDataInfo').innerHTML =
            '<div style="font-weight:500;margin-bottom:2px;">' + _escapeHtml(_currentData.title || _currentData.data_ref) + '</div>' +
            '<div style="font-size:11px;color:#86868b;">类型: ' + _typeLabel(_currentData.data_type) + '</div>';

        _modal.style.display = 'flex';
        _loadTeams();
    }

    function _loadTeams() {
        var listEl = document.getElementById('ptShareTeamList');
        listEl.innerHTML = '<div style="padding:20px;text-align:center;color:#86868b;font-size:13px;">加载中...</div>';
        _api('/api/teams').then(function(res) {
            _teams = res.teams || [];
            if (_teams.length === 0) {
                listEl.innerHTML = '<div style="padding:20px;text-align:center;color:#86868b;font-size:13px;">暂无团队，<a href="/teams" style="color:#1a1a1a;text-decoration:underline;">去创建</a></div>';
                return;
            }
            listEl.innerHTML = _teams.map(function(t, i) {
                return '<label style="display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;border-bottom:1px solid #f0f0f0;transition:background 0.1s;" onmouseover="this.style.background=\'#f9f9fb\'" onmouseout="this.style.background=\'none\'">' +
                    '<input type="radio" name="ptShareTeam" value="' + t.id + '" ' + (i === 0 ? 'checked' : '') + ' style="accent-color:#1a1a1a;">' +
                    '<div style="flex:1;min-width:0;">' +
                    '<div style="font-size:14px;font-weight:500;color:#1a1a1a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + _escapeHtml(t.name) + '</div>' +
                    '<div style="font-size:11px;color:#86868b;">' + t.member_count + ' 成员</div>' +
                    '</div></label>';
            }).join('');
        }).catch(function(err) {
            listEl.innerHTML = '<div style="padding:20px;text-align:center;color:#ff3b30;font-size:13px;">加载失败: ' + _escapeHtml(err.message) + '</div>';
        });
    }

    function submit() {
        var teamEl = document.querySelector('input[name="ptShareTeam"]:checked');
        if (!teamEl) { _toast('请选择团队'); return; }
        var teamId = teamEl.value;
        var permEl = document.querySelector('input[name="ptSharePerm"]:checked');
        var access = permEl ? permEl.value : 'view';

        var btn = document.getElementById('ptShareConfirmBtn');
        btn.disabled = true; btn.textContent = '分享中...';
        _api('/api/teams/' + teamId + '/share', {
            method: 'POST',
            body: {
                data_type: _currentData.data_type,
                data_ref: _currentData.data_ref,
                title: _currentData.title,
                permissions: { access: access }
            }
        }).then(function(res) {
            if (res.status === 'success') {
                _toast(res.already_shared ? '已分享过该数据' : '分享成功');
                close();
            } else {
                alert(res.error || '分享失败');
            }
        }).catch(function(err) {
            alert('分享失败: ' + err.message);
        }).finally(function() {
            btn.disabled = false; btn.textContent = '分享';
        });
    }

    function close() {
        if (_modal) _modal.style.display = 'none';
    }

    // 自动注入分享按钮到工具页面
    function _autoInject() {
        if (window.location.pathname === '/' || window.location.pathname === '/login' ||
            window.location.pathname === '/settings' || window.location.pathname === '/teams') {
            return;
        }
        // 查找页面标题区域
        var header = document.querySelector('.page-header, .tb-header, .hero, .tool-header');
        if (!header) return;
        if (header.querySelector('.pt-team-share-btn')) return;

        var btn = document.createElement('button');
        btn.className = 'pt-team-share-btn';
        btn.style.cssText = 'display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:980px;border:1px solid rgba(0,0,0,0.1);background:#fff;color:#1a1a1a;font-size:13px;font-weight:500;cursor:pointer;transition:all 0.15s;font-family:inherit;';
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg> 分享到团队';
        btn.onmouseover = function() { this.style.background = '#f5f5f7'; };
        btn.onmouseout = function() { this.style.background = '#fff'; };
        btn.onclick = function() {
            var title = document.title.replace(/ - Potential Tools.*$/, '') || document.title;
            var dataRef = window.location.pathname + '_' + Date.now();
            var dataType = 'general';
            var path = window.location.pathname;
            if (path.indexOf('excel-analysis') !== -1) dataType = 'cr_analysis';
            else if (path.indexOf('plan-generator') !== -1) dataType = 'project_plan';
            else if (path.indexOf('knowledge-graph') !== -1) dataType = 'knowledge_graph';
            else if (path.indexOf('test-report') !== -1) dataType = 'test_report';
            else if (path.indexOf('weekly-report') !== -1 || path.indexOf('meeting-minutes') !== -1) dataType = 'report';
            open(dataType, dataRef, title);
        };
        header.appendChild(btn);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { setTimeout(_autoInject, 600); });
    } else {
        setTimeout(_autoInject, 600);
    }

    return { open: open, close: close, submit: submit };
})();
