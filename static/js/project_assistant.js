/* ============================================================
   项目状态助手  project_assistant.js
   流程：输入项目 -> /api/project/load 后台拉取分析 -> 轮询 task-status
        -> /api/project/snapshot 渲染概览/趋势/模块表 -> /api/project/chat 多轮对话(SSE)
   ============================================================ */
(function () {
  'use strict';

  var PREFIX = window._USER_PREFIX || '';
  var LS_LAST = PREFIX + 'pa_last_project';
  var lsChatKey = function (key) { return PREFIX + 'pa_chat_' + key; };

  var state = {
    key: '', name: '', snap: null,
    history: [], rangeDays: 30, chart: null,
    loading: false
  };

  var $ = function (id) { return document.getElementById(id); };
  var page = $('paPage'), input = $('paProjectInput'), loadBtn = $('paLoadBtn'),
      refreshBtn = $('paRefreshBtn'), progress = $('paProgress'),
      progressMsg = $('paProgressMsg'), bar = $('paBar'), errorBox = $('paError'),
      result = $('paResult'), msgs = $('paMsgs'), chatInput = $('paInput'),
      sendBtn = $('paSend'), modTable = $('paModTable');

  /* ---------------- 工具 ---------------- */
  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.classList.add('show');
  }
  function clearError() { errorBox.classList.remove('show'); errorBox.textContent = ''; }
  function setProgress(pct, msg) {
    progress.classList.add('show');
    if (msg) progressMsg.textContent = msg;
    bar.style.width = Math.max(3, Math.min(100, pct)) + '%';
  }
  function hideProgress() { progress.classList.remove('show'); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function copyText(text, okMsg) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { toast(okMsg || '已复制'); },
        function () { fallbackCopy(text, okMsg); });
    } else { fallbackCopy(text, okMsg); }
  }
  function fallbackCopy(text, okMsg) {
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); toast(okMsg || '已复制'); } catch (e) { toast('复制失败'); }
    document.body.removeChild(ta);
  }
  var toastTimer = null;
  function toast(msg) {
    var t = document.createElement('div');
    t.textContent = msg;
    t.style.cssText = 'position:fixed;left:50%;bottom:36px;transform:translateX(-50%);background:rgba(20,20,28,.9);color:#fff;padding:10px 18px;border-radius:12px;font-size:13px;z-index:99999;box-shadow:0 8px 30px rgba(0,0,0,.3);';
    document.body.appendChild(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.remove(); }, 1800);
  }

  /* ---------------- 项目列表 ---------------- */
  function loadProjectList() {
    fetch('/api/project/list', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.status === 'success' && Array.isArray(j.data)) {
          $('paProjectList').innerHTML = j.data.map(function (p) {
            return '<option value="' + esc(p.key) + '">' + esc(p.name) + '</option>';
          }).join('');
        }
      })
      .catch(function () { /* 静默：用户仍可手输 Key */ });
  }

  /* ---------------- 加载 / 生成状态 ---------------- */
  function startLoad(force) {
    var proj = (input.value || '').trim();
    if (!proj) { showError('请输入 Project Key 或项目名称'); return; }
    if (state.loading) return;
    state.loading = true;
    clearError();
    loadBtn.disabled = true; refreshBtn.style.display = 'none';
    setProgress(3, '正在提交任务…');

    fetch('/api/project/load', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: proj, force: !!force })
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.status !== 'success' || !j.data || !j.data.task_id) {
          throw new Error(j.error || '启动任务失败');
        }
        return pollTask(j.data.task_id);
      })
      .then(function (data) {
        return fetchSnapshot(data.project_key);
      })
      .then(function (snap) {
        applySnapshot(snap);
        localStorage.setItem(LS_LAST, snap.project_key);
        hideProgress(); state.loading = false;
        loadBtn.disabled = false; refreshBtn.style.display = '';
      })
      .catch(function (e) {
        hideProgress(); state.loading = false;
        loadBtn.disabled = false; refreshBtn.style.display = '';
        showError(e.message || '生成失败');
      });
  }

  function pollTask(taskId) {
    return new Promise(function (resolve, reject) {
      var start = Date.now();
      var timer = setInterval(function () {
        fetch('/api/task-status', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: taskId })
        })
          .then(function (r) { return r.json(); })
          .then(function (t) {
            if (t.status === 'processing') {
              setProgress(t.progress || 5, t.progress_msg || '正在处理…');
              if (Date.now() - start > 15 * 60 * 1000) {
                clearInterval(timer); reject(new Error('任务超时，请重试'));
              }
            } else if (t.status === 'done') {
              clearInterval(timer); resolve(t.data || {});
            } else {
              clearInterval(timer); reject(new Error(t.error || '任务失败'));
            }
          })
          .catch(function () { /* 单次轮询失败不立即终止 */ });
      }, 900);
    });
  }

  function fetchSnapshot(key) {
    return fetch('/api/project/snapshot/' + encodeURIComponent(key), { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('快照不存在，请重新生成');
        return r.json();
      })
      .then(function (j) {
        if (j.status !== 'success') throw new Error(j.error || '读取快照失败');
        return j.data;
      });
  }

  /* ---------------- 渲染快照 ---------------- */
  function applySnapshot(snap) {
    state.snap = snap; state.key = snap.project_key;
    state.name = snap.project_name || snap.project_key;
    input.value = snap.project_key;
    page.classList.add('ready');
    result.classList.add('show');
    refreshBtn.style.display = '';

    var st = snap.stats || {};
    $('paProjTitle').textContent = snap.project_name
      ? snap.project_name + '（' + snap.project_key + '）' : snap.project_key;
    var cached = snap.age_hours != null ? ' · 快照生成于 ' + snap.generated_at +
      '（' + snap.age_hours + ' 小时前）' : '';
    $('paProjMeta').textContent = '共 ' + (st.total != null ? st.total : snap.total) +
      ' 个 CR · JQL: ' + (snap.jql || '') + cached;

    $('paStatTotal').textContent = st.total != null ? st.total : '–';
    $('paStatUnresolved').textContent = st.unresolved != null ? st.unresolved : '–';
    $('paStatBC').textContent = st.bc_unresolved != null ? st.bc_unresolved : '–';
    $('paStatFail').textContent = st.fail != null ? st.fail : '–';
    $('paStatPass').textContent = st.pass != null ? st.pass : '–';

    renderModules();
    renderChart();
    loadChatHistory();
  }

  /* ---------------- 模块表 ---------------- */
  function sevCN(s) {
    return { blocker: 'Blocker', critical: 'Critical', major: 'Major',
      minor: 'Minor', trivial: 'Trivial' }[s] || s || '未知';
  }
  function renderModules() {
    var snap = state.snap; if (!snap) return;
    var kw = ($('paModFilter').value || '').trim().toLowerCase();
    var statusF = $('paModStatus').value;
    var base = snap.source_base_url || '';
    var rows = (snap.modules || []).filter(function (m) {
      if (statusF === 'fail' && !m.fail) return false;
      if (statusF === 'pass' && m.fail) return false;
      if (kw && m.module.toLowerCase().indexOf(kw) < 0) return false;
      return true;
    });
    if (!rows.length) {
      modTable.innerHTML = '<div class="pa-empty-tip">没有符合条件的模块</div>';
      return;
    }
    modTable.innerHTML = rows.map(function (m) {
      var top = (m.top_list || []).map(function (it) {
        var href = base ? ('<a class="id" href="' + esc(base + '/browse/' + it.id) +
          '" target="_blank" rel="noopener">' + esc(it.id) + '</a>') : ('<span class="id">' + esc(it.id) + '</span>');
        return '<div class="pa-bc-item">' +
          '<span class="sev-tag ' + esc(it.sev) + '">' + sevCN(it.sev) + '</span>' +
          href +
          '<div class="t">' + esc(it.title) + '</div>' +
          '<div class="m">' + esc(it.status) + ' · @' + esc(it.developer || '未指派') + '</div></div>';
      }).join('');
      var more = m.open_bc_count > (m.top_list || []).length
        ? '<div class="pa-bc-item m">另有 ' + (m.open_bc_count - m.top_list.length) + ' 条未解决 BC，可在对话中追问完整清单</div>' : '';
      return '<div class="pa-mod-row' + (m.fail ? '' : '') + '" data-mod="' + esc(m.module) + '">' +
        '<div class="pa-mod-line">' +
          '<div><div class="pa-mod-name">' + esc(m.module) + '</div>' +
          '<div class="pa-mod-sub">未解决 ' + m.unresolved + ' / 共 ' + m.total + '</div></div>' +
          '<span class="pa-pill ' + (m.fail ? 'fail' : 'pass') + '">' + (m.fail ? 'FAIL' : 'PASS') + '</span>' +
          '<span class="pa-bc-num">' +
            (m.b ? '<span class="b">B ' + m.b + '</span> ' : '') +
            (m.c ? '<span class="c">C ' + m.c + '</span>' : (!m.b && !m.c) ? '—' : '') +
          '</span>' +
          '<span class="pa-caret">▶</span>' +
        '</div>' +
        '<div class="pa-toplist">' + (top || '<div class="pa-bc-item m">无未解决 BC 单</div>') + more + '</div>' +
      '</div>';
    }).join('');

    Array.prototype.forEach.call(modTable.querySelectorAll('.pa-mod-line'), function (line) {
      line.addEventListener('click', function () {
        line.parentNode.classList.toggle('open');
      });
    });
  }

  /* ---------------- 趋势图（Chart.js，口径同 CR 分析 daily_stats） ---------------- */
  function chartData() {
    var daily = (state.snap && state.snap.daily_stats) || [];
    var d = daily;
    if (state.rangeDays && state.rangeDays > 0 && daily.length > state.rangeDays) {
      d = daily.slice(daily.length - state.rangeDays);
    }
    var labels = d.map(function (x) { return String(x.date || '').slice(5); });
    var add = d.map(function (x) { return x.new_count || 0; });
    var res = d.map(function (x) { return x.resolved_count || 0; });
    var cum = [], run = 0;
    add.forEach(function (v) { run += v; cum.push(run); });
    return { labels: labels, add: add, res: res, cum: cum };
  }
  function renderChart() {
    var whenChart = (window.PTLoader && window.PTLoader.load)
      ? window.PTLoader.load('https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js')
      : (window.Chart ? Promise.resolve() : Promise.reject(new Error('no loader')));
    whenChart.then(function () {
      var cv = $('paTrendChart');
      var cd = chartData();
      var dense = cd.labels.length > 31;
      if (state.chart) { state.chart.destroy(); state.chart = null; }
      state.chart = new Chart(cv.getContext('2d'), {
        data: {
          labels: cd.labels,
          datasets: [
            { type: 'bar', label: '每日新增', data: cd.add, backgroundColor: 'rgba(10,132,255,.55)',
              borderRadius: 3, order: 2, maxBarThickness: 14 },
            { type: 'bar', label: '每日解决', data: cd.res, backgroundColor: 'rgba(52,199,89,.5)',
              borderRadius: 3, order: 2, maxBarThickness: 14 },
            { type: 'line', label: '累计 BUG', data: cd.cum, yAxisID: 'y1',
              borderColor: '#ff9500', backgroundColor: '#ff9500', tension: .3,
              pointRadius: dense ? 0 : 3, pointHoverRadius: 5, borderWidth: 2, order: 1 }
          ]
        },
        options: {
          maintainAspectRatio: false, responsive: true,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { labels: { boxWidth: 12, font: { size: 12 } } },
            tooltip: { enabled: true }
          },
          scales: {
            y: { beginAtZero: true, title: { display: true, text: '每日', font: { size: 11 } },
              grid: { color: 'rgba(120,120,128,.15)' } },
            y1: { position: 'right', beginAtZero: true, title: { display: true, text: '累计', font: { size: 11 } },
              grid: { drawOnChartArea: false } },
            x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
              grid: { display: false } }
          }
        }
      });
    }).catch(function () {
      var box = document.querySelector('.pa-chart-box');
      if (box) box.innerHTML = '<div class="pa-empty-tip">图表引擎加载失败（可能离线），数据仍可在模块表与对话中使用</div>';
    });
  }

  /* ---------------- 轻量 Markdown 渲染 ---------------- */
  function inlineMD(s) {
    s = esc(s);
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener" style="color:var(--pa-accent)">$1</a>');
    return s;
  }
  function renderMD(src) {
    if (!src) return '';
    var lines = String(src).replace(/\r\n/g, '\n').split('\n');
    var html = [], i = 0, inList = null;
    function closeList() { if (inList) { html.push(inList === 'ul' ? '</ul>' : '</ol>'); inList = null; } }
    while (i < lines.length) {
      var line = lines[i];
      // 代码块
      if (/^\s*```/.test(line)) {
        closeList();
        var lang = line.replace(/```/, '').trim();
        var buf = []; i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) { buf.push(lines[i]); i++; }
        i++;
        html.push('<pre><code>' + esc(buf.join('\n')) + '</code></pre>');
        continue;
      }
      // 表格
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
        closeList();
        var head = line.trim().replace(/^\||\|$/g, '').split('|').map(function (c) { return c.trim(); });
        i += 2; var body = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          body.push(lines[i].trim().replace(/^\||\|$/g, '').split('|').map(function (c) { return c.trim(); }));
          i++;
        }
        var t = '<table><thead><tr>' + head.map(function (h) { return '<th>' + inlineMD(h) + '</th>'; }).join('') + '</tr></thead><tbody>';
        body.forEach(function (r) {
          t += '<tr>' + head.map(function (h, idx) { return '<td>' + inlineMD(r[idx] != null ? r[idx] : '') + '</td>'; }).join('') + '</tr>';
        });
        t += '</tbody></table>'; html.push(t);
        continue;
      }
      var hm = line.match(/^(#{1,6})\s+(.*)$/);
      if (hm) { closeList(); html.push('<h' + hm[1].length + '>' + inlineMD(hm[2]) + '</h' + hm[1].length + '>'); i++; continue; }
      if (/^\s*>\s?/.test(line)) { closeList(); html.push('<blockquote>' + inlineMD(line.replace(/^\s*>\s?/, '')) + '</blockquote>'); i++; continue; }
      var ul = line.match(/^\s*[-*]\s+(.*)$/);
      var ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if (ul || ol) {
        var kind = ul ? 'ul' : 'ol', content = ul ? ul[1] : ol[1];
        if (inList !== kind) { closeList(); html.push(kind === 'ul' ? '<ul>' : '<ol>'); inList = kind; }
        html.push('<li>' + inlineMD(content) + '</li>'); i++; continue;
      }
      if (!line.trim()) { closeList(); i++; continue; }
      closeList();
      html.push('<p>' + inlineMD(line) + '</p>'); i++;
    }
    closeList();
    return html.join('\n');
  }

  /* ---------------- 对话 ---------------- */
  function loadChatHistory() {
    state.history = [];
    try { state.history = JSON.parse(localStorage.getItem(lsChatKey(state.key)) || '[]'); } catch (e) { state.history = []; }
    msgs.innerHTML = '';
    if (!state.history.length) {
      msgs.innerHTML = '<div class="pa-empty-tip">已基于 ' + esc(state.name) + ' 实时数据，可直接提问，或点击上方快捷问题。</div>';
      return;
    }
    state.history.forEach(function (m) { appendMessage(m.role, m.content, false); });
    msgs.scrollTop = msgs.scrollHeight;
  }
  function saveChatHistory() {
    try { localStorage.setItem(lsChatKey(state.key), JSON.stringify(state.history.slice(-40))); } catch (e) {}
  }
  function appendMessage(role, content, asMarkdown) {
    var empty = msgs.querySelector('.pa-empty-tip');
    if (empty) empty.remove();
    var wrap = document.createElement('div');
    wrap.className = 'pa-msg ' + (role === 'user' ? 'user' : 'bot');
    var bubble = document.createElement('div');
    bubble.className = 'pa-bubble';
    bubble.innerHTML = role === 'user' ? esc(content) : (asMarkdown ? renderMD(content) : esc(content));
    wrap.appendChild(bubble);
    if (role === 'assistant') {
      var cp = document.createElement('button');
      cp.className = 'pa-copy'; cp.textContent = '复制';
      cp.addEventListener('click', function () { copyText(content, '已复制回复'); });
      wrap.appendChild(cp);
    }
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;
    return bubble;
  }

  function sendQuestion(q) {
    var question = (q != null ? q : chatInput.value).trim();
    if (!question || !state.key) { if (!state.key) showError('请先生成项目状态'); return; }
    if (!q) chatInput.value = '';
    appendMessage('user', question, false);
    state.history.push({ role: 'user', content: question });
    var botBubble = appendMessage('assistant', '', false);
    botBubble.classList.add('loading');
    botBubble.textContent = '正在分析…';
    sendBtn.disabled = true;
    var acc = '';

    fetch('/api/project/chat', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_key: state.key, question: question, history: state.history.slice(0, -1) })
    }).then(function (resp) {
      if (!resp.ok || !resp.body) return resp.json().then(function (j) { throw new Error(j.error || '请求失败'); });
      var reader = resp.body.getReader(), dec = new TextDecoder(), buf = '';
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) { finish(); return; }
          buf += dec.decode(r.value, { stream: true });
          var idx;
          while ((idx = buf.indexOf('\n\n')) >= 0) {
            var frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
            var line = frame.split('\n').filter(function (l) { return l.indexOf('data:') === 0; })[0];
            if (!line) continue;
            var obj;
            try { obj = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }
            if (obj.type === 'token') { acc += obj.content; botBubble.classList.remove('loading'); botBubble.innerHTML = renderMD(acc); msgs.scrollTop = msgs.scrollHeight; }
            else if (obj.type === 'error') { botBubble.classList.remove('loading'); botBubble.textContent = '⚠️ ' + (obj.message || '生成失败'); }
            else if (obj.type === 'done') { finish(); return; }
          }
          return pump();
        });
      }
      function finish() {
        botBubble.classList.remove('loading');
        if (!acc) { botBubble.textContent = '（未返回内容）'; }
        if (acc) { state.history.push({ role: 'assistant', content: acc }); saveChatHistory(); }
        sendBtn.disabled = false;
        msgs.scrollTop = msgs.scrollHeight;
      }
      return pump();
    }).catch(function (e) {
      botBubble.classList.remove('loading');
      botBubble.textContent = '⚠️ ' + (e.message || '请求失败');
      sendBtn.disabled = false;
    });
  }

  /* ---------------- 复制状态报告 ---------------- */
  function buildReportMD() {
    var snap = state.snap, st = snap.stats || {};
    var lines = [];
    lines.push('# ' + (snap.project_name || snap.project_key) + ' 项目 CR 状态报告（' + snap.generated_at + '）');
    lines.push('');
    lines.push('- CR 总数：' + st.total + '；未解决：' + st.unresolved + '；未解决 BC：' + st.bc_unresolved);
    lines.push('- 模块：' + st.modules + ' 个，FAIL ' + st.fail + ' / PASS ' + st.pass);
    lines.push('');
    lines.push(snap.module_md || '');
    return lines.join('\n');
  }

  /* ---------------- 事件绑定 ---------------- */
  loadBtn.addEventListener('click', function () { startLoad(false); });
  refreshBtn.addEventListener('click', function () { startLoad(true); });
  $('paForceReload').addEventListener('click', function () { startLoad(true); });
  input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); startLoad(false); } });
  sendBtn.addEventListener('click', function () { sendQuestion(); });
  chatInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendQuestion(); }
  });
  chatInput.addEventListener('input', function () {
    chatInput.style.height = 'auto'; chatInput.style.height = Math.min(140, chatInput.scrollHeight) + 'px';
  });
  Array.prototype.forEach.call(document.querySelectorAll('#paChips .pa-chip'), function (c) {
    c.addEventListener('click', function () { sendQuestion(c.getAttribute('data-q')); });
  });
  $('paModFilter').addEventListener('input', renderModules);
  $('paModStatus').addEventListener('change', renderModules);
  Array.prototype.forEach.call(document.querySelectorAll('#paRangeToggle button'), function (b) {
    b.addEventListener('click', function () {
      Array.prototype.forEach.call(document.querySelectorAll('#paRangeToggle button'), function (x) { x.classList.remove('on'); });
      b.classList.add('on');
      state.rangeDays = parseInt(b.getAttribute('data-days'), 10);
      renderChart();
    });
  });
  $('paCopyReport').addEventListener('click', function () {
    if (state.snap) copyText(buildReportMD(), '状态报告 Markdown 已复制');
  });

  /* ---------------- 启动：项目列表 + 恢复上次快照 ---------------- */
  loadProjectList();
  var lastKey = localStorage.getItem(LS_LAST);
  if (lastKey) {
    input.value = lastKey;
    fetchSnapshot(lastKey).then(applySnapshot).catch(function () {
      page.classList.remove('ready'); result.classList.remove('show'); input.value = '';
    });
  }
})();
