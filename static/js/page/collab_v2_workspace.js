window.__PD__ = window.__PD__ || {};
(function() {
    var shareCode = 'window.__PD__.share_code';
    var currentUser = {{ current_user | tojson if current_user else 'null' }};

    PTCollabV2.initWorkspacePage(shareCode, currentUser);

    // Tab 切换
    PTCollabV2._switchTab = function(tabName) {
        document.querySelectorAll('.cv2-tab').forEach(function(t) { t.classList.remove('active'); });
        document.querySelectorAll('.cv2-tab-panel').forEach(function(p) { p.classList.remove('active'); });
        var tabMap = {comments: 'cv2PanelComments', members: 'cv2PanelMembers', activity: 'cv2PanelActivity', security: 'cv2PanelSecurity'};
        event.target.closest('.cv2-tab').classList.add('active');
        document.getElementById(tabMap[tabName]).classList.add('active');
        if (tabName === 'activity') {
            PTCollabV2.loadActivity(shareCode);
        }
    };

    // 活动筛选
    PTCollabV2._filterActivity = function(btn, type) {
        document.querySelectorAll('.cv2-filter-btn').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        PTCollabV2.loadActivity(shareCode, type);
    };

    // 复制链接
    PTCollabV2._copyLink = function() {
        var url = window.location.origin + '/collab/' + shareCode;
        if (navigator.clipboard) {
            navigator.clipboard.writeText(url).then(function() {
                alert('链接已复制');
            }).catch(function() { fallback(); });
        } else { fallback(); }
        function fallback() {
            var ta = document.createElement('textarea');
            ta.value = url; document.body.appendChild(ta); ta.select();
            try { document.execCommand('copy'); alert('链接已复制'); } catch(e) { alert('复制失败'); }
            document.body.removeChild(ta);
        }
    };

    // 保存安全设置
    PTCollabV2._saveSecurity = function() {
        var password = document.getElementById('cv2Password').value.trim();
        var accessLimit = parseInt(document.getElementById('cv2AccessLimit').value) || 0;
        PTCollabV2.updateSecurity(password, accessLimit).then(function(data) {
            if (data.status === 'success') {
                alert('设置已保存');
            } else {
                alert(data.error || '保存失败');
            }
        }).catch(function(err) {
            alert('保存失败: ' + err.message);
        });
    };
})();