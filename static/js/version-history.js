/**
 * 文档版本历史 — v12.0
 * 可复用模块：在任意页面调用 VersionHistory.open(docType, docId, onRollback) 打开版本面板
 */
(function () {
  'use strict';

  let modalEl = null;
  let currentDocType = '';
  let currentDocId = '';
  let currentVersions = [];
  let selectedVersionId = null;
  let onRollbackCallback = null;

  function ensureModal() {
    if (modalEl) return;
    modalEl = document.createElement('div');
    modalEl.className = 'version-modal-overlay';
    modalEl.style.display = 'none';
    modalEl.innerHTML = `
      <div class="version-modal">
        <div class="version-modal-header">
          <span class="version-modal-title">历史版本</span>
          <button class="version-modal-close" id="vh-close">&times;</button>
        </div>
        <div class="version-compare-bar" id="vh-compare-bar" style="display:none;">
          <span>对比：</span>
          <select id="vh-compare-v1"></select>
          <span>vs</span>
          <select id="vh-compare-v2"></select>
          <button class="version-btn" id="vh-compare-btn" style="padding:4px 10px;">对比</button>
          <button class="version-btn" id="vh-compare-cancel" style="padding:4px 10px;">取消</button>
        </div>
        <div class="version-modal-body">
          <div class="version-list-panel" id="vh-list"></div>
          <div class="version-detail-panel" id="vh-detail">
            <div class="version-empty">选择左侧版本查看详情</div>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modalEl);

    modalEl.querySelector('#vh-close').addEventListener('click', close);
    modalEl.addEventListener('click', function (e) {
      if (e.target === modalEl) close();
    });
    modalEl.querySelector('#vh-compare-btn').addEventListener('click', doCompare);
    modalEl.querySelector('#vh-compare-cancel').addEventListener('click', function () {
      modalEl.querySelector('#vh-compare-bar').style.display = 'none';
      if (selectedVersionId) showDetail(selectedVersionId);
    });
  }

  function open(docType, docId, onRollback) {
    ensureModal();
    currentDocType = docType;
    currentDocId = docId;
    onRollbackCallback = onRollback || null;
    selectedVersionId = null;
    modalEl.style.display = 'flex';
    modalEl.querySelector('#vh-compare-bar').style.display = 'none';
    loadVersions();
  }

  function close() {
    if (modalEl) modalEl.style.display = 'none';
  }

  function loadVersions() {
    const listEl = modalEl.querySelector('#vh-list');
    listEl.innerHTML = '<div class="version-empty">加载中...</div>';

    fetch(`/api/versions?doc_type=${encodeURIComponent(currentDocType)}&doc_id=${encodeURIComponent(currentDocId)}&limit=200`)
      .then(r => r.json())
      .then(data => {
        if (data.status !== 'success') {
          listEl.innerHTML = '<div class="version-empty">加载失败</div>';
          return;
        }
        currentVersions = data.versions || [];
        renderList();
        populateCompareSelects();
        if (currentVersions.length > 0) {
          showDetail(currentVersions[0].id);
        } else {
          modalEl.querySelector('#vh-detail').innerHTML = '<div class="version-empty">暂无历史版本</div>';
        }
      })
      .catch(() => {
        listEl.innerHTML = '<div class="version-empty">加载失败</div>';
      });
  }

  function renderList() {
    const listEl = modalEl.querySelector('#vh-list');
    if (!currentVersions.length) {
      listEl.innerHTML = '<div class="version-empty">暂无历史版本</div>';
      return;
    }
    listEl.innerHTML = currentVersions.map(v => {
      const time = formatTime(v.created_at);
      const name = v.name || `v${v.version_number}`;
      const active = v.id === selectedVersionId ? 'active' : '';
      return `
        <div class="version-item ${active}" data-id="${v.id}">
          <div class="version-item-number">v${v.version_number} ${v.name ? '· ' + escapeHtml(v.name) : ''}</div>
          <div class="version-item-meta">${v.creator_name || '未知'} · ${time}</div>
          ${v.note ? '<div class="version-item-meta" style="color:#666;">' + escapeHtml(v.note) + '</div>' : ''}
        </div>
      `;
    }).join('');

    listEl.querySelectorAll('.version-item').forEach(item => {
      item.addEventListener('click', function () {
        showDetail(parseInt(this.dataset.id));
      });
    });
  }

  function populateCompareSelects() {
    const s1 = modalEl.querySelector('#vh-compare-v1');
    const s2 = modalEl.querySelector('#vh-compare-v2');
    if (!s1 || !s2) return;
    const opts = currentVersions.map(v => `<option value="${v.id}">v${v.version_number} ${v.name ? '(' + escapeHtml(v.name) + ')' : ''}</option>`).join('');
    s1.innerHTML = opts;
    s2.innerHTML = opts;
    if (currentVersions.length >= 2) {
      s1.value = currentVersions[1].id;
      s2.value = currentVersions[0].id;
    }
  }

  function showDetail(versionId) {
    selectedVersionId = versionId;
    renderList();

    const v = currentVersions.find(x => x.id === versionId);
    if (!v) return;

    const detailEl = modalEl.querySelector('#vh-detail');
    const time = formatTime(v.created_at);

    detailEl.innerHTML = `
      <div class="version-detail-label">版本号</div>
      <div class="version-detail-value">v${v.version_number}</div>

      <div class="version-detail-label">名称</div>
      <div class="version-detail-value" id="vh-detail-name">${escapeHtml(v.name || '')}</div>
      <input type="text" id="vh-edit-name" value="${escapeHtml(v.name || '')}" style="display:none;width:100%;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;box-sizing:border-box;margin-top:4px;" placeholder="版本名称">

      <div class="version-detail-label">备注</div>
      <div class="version-detail-value" id="vh-detail-note">${escapeHtml(v.note || '')}</div>
      <input type="text" id="vh-edit-note" value="${escapeHtml(v.note || '')}" style="display:none;width:100%;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;box-sizing:border-box;margin-top:4px;" placeholder="版本备注">

      <div class="version-detail-label">操作者</div>
      <div class="version-detail-value">${escapeHtml(v.creator_name || '未知')}</div>

      <div class="version-detail-label">时间</div>
      <div class="version-detail-value">${time}</div>

      <div class="version-detail-label">内容预览</div>
      <div class="version-detail-content" id="vh-detail-content">加载中...</div>

      <div class="version-actions">
        <button class="version-btn primary" id="vh-rollback">回滚到此版本</button>
        <button class="version-btn" id="vh-edit-meta">编辑名称/备注</button>
        <button class="version-btn" id="vh-save-meta" style="display:none;">保存</button>
        <button class="version-btn" id="vh-compare-open">对比版本</button>
      </div>
    `;

    // 加载完整内容
    fetch(`/api/versions/${versionId}`)
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success' && data.version) {
          detailEl.querySelector('#vh-detail-content').textContent = data.version.content || '(空内容)';
        }
      })
      .catch(() => {
        detailEl.querySelector('#vh-detail-content').textContent = '加载失败';
      });

    // 绑定操作
    detailEl.querySelector('#vh-rollback').addEventListener('click', function () {
      if (!confirm('确定回滚到此版本？将创建新版本，原历史保留。')) return;
      rollback(versionId);
    });

    detailEl.querySelector('#vh-edit-meta').addEventListener('click', function () {
      detailEl.querySelector('#vh-detail-name').style.display = 'none';
      detailEl.querySelector('#vh-detail-note').style.display = 'none';
      detailEl.querySelector('#vh-edit-name').style.display = 'block';
      detailEl.querySelector('#vh-edit-note').style.display = 'block';
      this.style.display = 'none';
      detailEl.querySelector('#vh-save-meta').style.display = 'inline-block';
    });

    detailEl.querySelector('#vh-save-meta').addEventListener('click', function () {
      const name = detailEl.querySelector('#vh-edit-name').value.trim();
      const note = detailEl.querySelector('#vh-edit-note').value.trim();
      saveMeta(versionId, name, note);
    });

    detailEl.querySelector('#vh-compare-open').addEventListener('click', function () {
      modalEl.querySelector('#vh-compare-bar').style.display = 'flex';
    });
  }

  function rollback(versionId) {
    fetch(`/api/versions/${versionId}/rollback`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success') {
          if (onRollbackCallback && typeof onRollbackCallback === 'function') {
            onRollbackCallback(data.content || '');
          }
          close();
          // 刷新列表
          setTimeout(function () {
            open(currentDocType, currentDocId, onRollbackCallback);
          }, 300);
        } else {
          alert(data.error || '回滚失败');
        }
      })
      .catch(() => alert('网络错误'));
  }

  function saveMeta(versionId, name, note) {
    fetch(`/api/versions/${versionId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, note: note })
    })
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success') {
          loadVersions();
        } else {
          alert(data.error || '保存失败');
        }
      })
      .catch(() => alert('网络错误'));
  }

  function doCompare() {
    const v1 = modalEl.querySelector('#vh-compare-v1').value;
    const v2 = modalEl.querySelector('#vh-compare-v2').value;
    if (!v1 || !v2 || v1 === v2) {
      alert('请选择两个不同的版本');
      return;
    }

    const detailEl = modalEl.querySelector('#vh-detail');
    detailEl.innerHTML = '<div class="version-empty">对比中...</div>';

    fetch(`/api/versions/diff?v1=${v1}&v2=${v2}`)
      .then(r => r.json())
      .then(data => {
        if (data.status !== 'success') {
          detailEl.innerHTML = '<div class="version-empty">对比失败</div>';
          return;
        }
        const diffLines = (data.diff || []).map(line => {
          if (line.startsWith('+')) return `<span class="version-diff-add">${escapeHtml(line)}</span>`;
          if (line.startsWith('-')) return `<span class="version-diff-del">${escapeHtml(line)}</span>`;
          if (line.startsWith('@@') || line.startsWith('---') || line.startsWith('+++')) return `<span class="version-diff-info">${escapeHtml(line)}</span>`;
          return escapeHtml(line);
        }).join('\n');

        detailEl.innerHTML = `
          <div class="version-detail-label">版本对比</div>
          <div class="version-detail-value">v${data.v1.version_number} → v${data.v2.version_number}</div>
          <div class="version-diff-view" style="margin-top:12px;">${diffLines || '(无差异)'}</div>
          <div class="version-actions">
            <button class="version-btn" onclick="VersionHistory._backToList()">返回列表</button>
          </div>
        `;
      })
      .catch(() => {
        detailEl.innerHTML = '<div class="version-empty">对比失败</div>';
      });
  }

  function _backToList() {
    if (selectedVersionId) showDetail(selectedVersionId);
  }

  function formatTime(timestamp) {
    if (!timestamp) return '';
    const d = new Date(timestamp * 1000);
    const now = Date.now() / 1000;
    const diff = now - timestamp;
    if (diff < 60) return '刚刚';
    if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
    if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
    if (diff < 604800) return Math.floor(diff / 86400) + '天前';
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0') + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  // 暴露全局
  window.VersionHistory = {
    open: open,
    close: close,
    _backToList: _backToList
  };

  // v12 便捷方法
  window.V12 = {
    saveVersion: function (docType, docId, content, name, note) {
      fetch('/api/versions/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_type: docType, doc_id: docId, content: content || '', name: name || '', note: note || '' })
      })
        .then(r => r.json())
        .then(data => {
          if (data.status === 'success') {
            alert('版本已保存（v' + data.version_number + '）');
          } else {
            alert(data.error || '保存失败');
          }
        })
        .catch(() => alert('网络错误'));
    },
    openHistory: function (docType, docId, onRollback) {
      open(docType, docId, onRollback);
    }
  };
})();
