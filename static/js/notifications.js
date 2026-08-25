/**
 * 通知系统 — v12.0
 * 导航栏铃铛图标 + 未读数量 + 通知列表面板
 */
(function () {
  'use strict';

  let unreadCount = 0;
  let panelOpen = false;
  let bellEl = null;
  let panelEl = null;
  let badgeEl = null;

  function init() {
    bellEl = document.getElementById('notification-bell');
    if (!bellEl) return;

    // 创建未读徽标
    badgeEl = document.createElement('span');
    badgeEl.id = 'notification-badge';
    badgeEl.className = 'notif-badge';
    badgeEl.style.display = 'none';
    bellEl.appendChild(badgeEl);

    // 创建通知面板
    createPanel();

    // 绑定事件
    bellEl.addEventListener('click', togglePanel);
    document.addEventListener('click', function (e) {
      if (panelOpen && !panelEl.contains(e.target) && !bellEl.contains(e.target)) {
        closePanel();
      }
    });

    // 加载未读数量
    refreshUnreadCount();
    // 每60秒刷新一次
    setInterval(refreshUnreadCount, 60000);
  }

  function createPanel() {
    panelEl = document.createElement('div');
    panelEl.id = 'notification-panel';
    panelEl.className = 'notif-panel';
    panelEl.style.display = 'none';
    panelEl.innerHTML = `
      <div class="notif-panel-header">
        <span class="notif-panel-title">通知</span>
        <button class="notif-mark-all" id="notif-mark-all">全部已读</button>
      </div>
      <div class="notif-panel-list" id="notif-list">
        <div class="notif-loading">加载中...</div>
      </div>
    `;
    document.body.appendChild(panelEl);

    panelEl.querySelector('#notif-mark-all').addEventListener('click', markAllRead);
  }

  function positionPanel() {
    if (!bellEl || !panelEl) return;
    const rect = bellEl.getBoundingClientRect();
    panelEl.style.top = (rect.bottom + 8) + 'px';
    panelEl.style.right = (window.innerWidth - rect.right) + 'px';
  }

  function togglePanel(e) {
    e.stopPropagation();
    if (panelOpen) {
      closePanel();
    } else {
      openPanel();
    }
  }

  function openPanel() {
    panelOpen = true;
    positionPanel();
    panelEl.style.display = 'block';
    loadNotifications();
  }

  function closePanel() {
    panelOpen = false;
    panelEl.style.display = 'none';
  }

  function refreshUnreadCount() {
    fetch('/api/notifications/unread-count')
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success') {
          unreadCount = data.unread_count || 0;
          updateBadge();
        }
      })
      .catch(() => {});
  }

  function updateBadge() {
    if (!badgeEl) return;
    if (unreadCount > 0) {
      badgeEl.textContent = unreadCount > 99 ? '99+' : unreadCount;
      badgeEl.style.display = 'flex';
    } else {
      badgeEl.style.display = 'none';
    }
  }

  function loadNotifications() {
    const listEl = panelEl.querySelector('#notif-list');
    listEl.innerHTML = '<div class="notif-loading">加载中...</div>';

    fetch('/api/notifications?limit=50')
      .then(r => r.json())
      .then(data => {
        if (data.status !== 'success') {
          listEl.innerHTML = '<div class="notif-empty">加载失败</div>';
          return;
        }
        renderNotifications(data.notifications || []);
      })
      .catch(() => {
        listEl.innerHTML = '<div class="notif-empty">加载失败</div>';
      });
  }

  function renderNotifications(notifications) {
    const listEl = panelEl.querySelector('#notif-list');
    if (!notifications.length) {
      listEl.innerHTML = '<div class="notif-empty">暂无通知</div>';
      return;
    }

    listEl.innerHTML = notifications.map(n => {
      const time = formatTime(n.created_at);
      const unreadClass = n.is_read ? '' : 'notif-unread';
      const typeIcon = getTypeIcon(n.type);
      return `
        <div class="notif-item ${unreadClass}" data-id="${n.id}" data-link="${n.link || ''}">
          <div class="notif-item-icon">${typeIcon}</div>
          <div class="notif-item-body">
            <div class="notif-item-title">${escapeHtml(n.title || '')}</div>
            <div class="notif-item-content">${escapeHtml(n.content || '')}</div>
            <div class="notif-item-time">${time}</div>
          </div>
        </div>
      `;
    }).join('');

    // 绑定点击事件
    listEl.querySelectorAll('.notif-item').forEach(item => {
      item.addEventListener('click', function () {
        const id = this.dataset.id;
        const link = this.dataset.link;
        markRead(id);
        if (link) {
          window.location.href = link;
        }
      });
    });
  }

  function getTypeIcon(type) {
    const icons = {
      mention: '@',
      reply: '↩',
      team_invite: '👥',
      data_share: '📤',
      system: 'ℹ'
    };
    return icons[type] || '•';
  }

  function markRead(id) {
    fetch(`/api/notifications/${id}/read`, { method: 'PUT' })
      .then(() => {
        if (unreadCount > 0) unreadCount--;
        updateBadge();
        const item = panelEl.querySelector(`.notif-item[data-id="${id}"]`);
        if (item) item.classList.remove('notif-unread');
      })
      .catch(() => {});
  }

  function markAllRead() {
    fetch('/api/notifications/read-all', { method: 'PUT' })
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success') {
          unreadCount = 0;
          updateBadge();
          panelEl.querySelectorAll('.notif-item').forEach(item => {
            item.classList.remove('notif-unread');
          });
        }
      })
      .catch(() => {});
  }

  function formatTime(timestamp) {
    if (!timestamp) return '';
    const now = Date.now() / 1000;
    const diff = now - timestamp;
    if (diff < 60) return '刚刚';
    if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
    if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
    if (diff < 604800) return Math.floor(diff / 86400) + '天前';
    const d = new Date(timestamp * 1000);
    return d.getMonth() + 1 + '/' + d.getDate();
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // 暴露全局方法
  window.Notifications = {
    refresh: refreshUnreadCount,
    open: openPanel,
    close: closePanel
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
