/* eDart / Jira 直连数据源：配置 -> 测试连接 -> JQL 分页拉取 -> 复用 CR 分析全流程 */
(function () {
    'use strict';

    // ---- 样式注入（苹果风弹窗） ----
    var css = [
        '.edart-mask{position:fixed;inset:0;background:rgba(0,0,0,.42);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;}',
        '.edart-dialog{width:580px;max-width:96vw;max-height:92vh;overflow:auto;background:#fff;border-radius:16px;box-shadow:0 24px 70px rgba(0,0,0,.28);display:flex;flex-direction:column;}',
        '.edart-head{display:flex;justify-content:space-between;align-items:center;padding:18px 20px;border-bottom:1px solid #ececef;font-weight:600;font-size:15px;color:#1d1d1f;}',
        '.edart-x{background:none;border:none;font-size:22px;line-height:1;color:#86868b;cursor:pointer;}',
        '.edart-body{padding:16px 20px;display:flex;flex-direction:column;gap:6px;}',
        '.edart-body label{font-size:12px;color:#6e6e73;margin-top:8px;font-weight:600;}',
        '.edart-body input,.edart-body select{padding:9px 11px;border:1px solid #d2d2d7;border-radius:9px;font-size:13px;width:100%;box-sizing:border-box;background:#fff;color:#1d1d1f;}',
        '.edart-body input:focus,.edart-body select:focus{outline:none;border-color:#0071e3;box-shadow:0 0 0 3px rgba(0,113,227,.12);}',
        '.edart-row{display:flex;gap:12px;}.edart-row>div{flex:1;display:flex;flex-direction:column;}',
        '.edart-test-result{margin-top:12px;font-size:12px;border-radius:9px;padding:9px 11px;background:#f5f5f7;color:#6e6e73;white-space:pre-wrap;word-break:break-word;min-height:18px;}',
        '.edart-test-result.ok{background:rgba(52,199,89,.12);color:#1d7a35;}',
        '.edart-test-result.bad{background:rgba(255,59,48,.10);color:#c4271f;}',
        '.edart-foot{padding:14px 20px;border-top:1px solid #ececef;display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;}',
        '.edart-foot .btn{font-size:13px;}'
    ].join('\n');
    var styleEl = document.createElement('style');
    styleEl.textContent = css;
    document.head.appendChild(styleEl);

    var $ = function (id) { return document.getElementById(id); };
    function setTest(msg, ok) {
        var el = $('edtTestResult');
        if (!el) return;
        el.textContent = msg;
        el.className = 'edart-test-result ' + (ok === true ? 'ok' : ok === false ? 'bad' : '');
    }
    function collect() {
        return {
            base_url: $('edtBase').value.trim(),
            auth_mode: $('edtMode').value,
            project_key: $('edtProject').value.trim(),
            email: $('edtEmail').value.trim(),
            token: $('edtToken').value,
            incremental_days: parseInt($('edtDays').value || '7', 10) || 7,
            verify_ssl: !$('edtInsecure').checked,
            default_jql: $('edtJql').value.trim()
        };
    }
    function postJSON(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {})
        }).then(function (r) { return r.json(); });
    }
    function toggleEmail() {
        var row = $('edtEmailRow');
        if (row) row.style.display = $('edtMode').value === 'cloud' ? 'flex' : 'none';
    }

    window.edartOpen = async function () {
        $('edartModal').style.display = 'flex';
        setTest('', null);
        try {
            var r = await fetch('/api/edart/config');
            var j = await r.json();
            if (j.status === 'success') {
                var d = j.data || {};
                $('edtBase').value = d.base_url || '';
                $('edtMode').value = d.auth_mode || 'dc';
                $('edtProject').value = d.project_key || '';
                $('edtEmail').value = d.email || '';
                $('edtDays').value = d.incremental_days || 7;
                $('edtInsecure').checked = !d.verify_ssl;
                $('edtJql').value = d.default_jql || '';
                $('edtToken').value = '';
                $('edtToken').placeholder = d.has_token ? '已保存 Token，留空表示不修改' : 'Data Center 填 PAT；Cloud 填 API Token';
                toggleEmail();
            }
        } catch (e) { setTest('加载配置失败：' + e.message, false); }
    };
    window.edartClose = function () { $('edartModal').style.display = 'none'; };

    document.addEventListener('change', function (e) {
        if (e.target && e.target.id === 'edtMode') toggleEmail();
    });

    window.edartSave = async function () {
        var c = collect();
        if (!c.base_url) { setTest('请先填写站点地址', false); return; }
        try {
            var j = await postJSON('/api/edart/config', c);
            if (j.status === 'success') {
                setTest(j.message || '配置已保存', true);
                $('edtToken').value = '';
            } else { setTest('✗ ' + (j.error || '保存失败'), false); }
        } catch (e) { setTest('保存失败：' + e.message, false); }
    };

    window.edartTest = async function () {
        var c = collect();
        if (!c.base_url) { setTest('请先填写站点地址', false); return; }
        setTest('正在测试连接并探测字段…', null);
        try {
            var j = await postJSON('/api/edart/test', c);
            if (j.status === 'success') {
                var d = j.data || {};
                var sev = d.severity_field ? d.severity_field : '未探测到（严重度将为空，可在高级 JQL 旁联系管理员确认自定义字段）';
                setTest('连接成功：' + (d.user || '未知用户') +
                    '\nJira ' + (d.version || '?') + ' / ' + (d.deployment || '未知部署') +
                    '\nSeverity 字段：' + sev, true);
            } else { setTest('✗ ' + (j.error || '连接失败'), false); }
        } catch (e) { setTest('连接失败：' + e.message, false); }
    };

    window.edartFetch = async function (mode) {
        var c = collect();
        if (!c.base_url) { setTest('请先填写站点地址', false); return; }
        setTest(mode === 'full' ? '正在全量拉取并分析…' : '正在增量拉取（近 ' + c.incremental_days + ' 天）…', null);

        var body = { mode: mode, days: c.incremental_days };
        var j;
        try {
            j = await postJSON('/api/edart/fetch', body);
            // 配置尚未保存（400）时，先保存当前表单再重试一次
            if (j.status === 'error' && (j.error || '').indexOf('配置') >= 0) {
                await postJSON('/api/edart/config', c);
                j = await postJSON('/api/edart/fetch', body);
            }
        } catch (e) { setTest('拉取失败：' + e.message, false); return; }

        if (j.status !== 'success' || !j.data || !j.data.task_id) {
            setTest('✗ ' + (j.error || '拉取失败'), false);
            return;
        }
        $('edartModal').style.display = 'none';
        prepareAnalyzeUI(mode === 'full' ? '全量' : '增量');
        pollTask(j.data.task_id);
    };

    function prepareAnalyzeUI(label) {
        try {
            var uploadArea = $('uploadArea'), fileInfo = $('fileInfo'),
                fileName = $('fileName'), analyzing = $('analyzing');
            if (uploadArea) uploadArea.style.display = 'none';
            if (fileInfo) fileInfo.classList.add('show');
            if (fileName) fileName.textContent = 'eDart 直连（' + label + '拉取）';
            if (analyzing) {
                analyzing.classList.add('show');
                var p = analyzing.querySelector('p');
                if (p) p.textContent = '正在从 eDart 拉取数据…';
            }
            if (typeof hideError === 'function') hideError();
        } catch (e) { /* 忽略 UI 细节错误 */ }
    }

    function pollTask(taskId) {
        var analyzing = $('analyzing');
        var times = 0;
        var timer = setInterval(function () {
            times++;
            if (times > 900) { clearInterval(timer); failAnalyze('拉取超时'); return; }
            fetch('/api/task-status', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId })
            }).then(function (r) { return r.json(); }).then(function (t) {
                if (t.status === 'processing') {
                    if (analyzing) {
                        var p = analyzing.querySelector('p');
                        var msg = t.progress_msg || '正在拉取…';
                        if (p) p.textContent = msg;
                    }
                } else if (t.status === 'done') {
                    clearInterval(timer);
                    handoffToAnalysis(t.data);
                } else if (t.status === 'error') {
                    clearInterval(timer);
                    failAnalyze(t.error || '拉取失败');
                }
            }).catch(function () { /* 单次轮询失败继续 */ });
        }, 1000);
    }

    function handoffToAnalysis(data) {
        data = data || {};
        try {
            // Labels 筛选分析页面适配：下载CSV文件后走现有解析流程
            if (window.location.pathname.indexOf('/label-filter') >= 0) {
                handoffToLabelFilter(data);
                return;
            }
            // 这些绑定由 excel_analysis.js 在全局词法环境声明
            currentFileId = data.file_id;
            currentFileName = data.file_name || 'eDart CR';
            sheetNames = (data.sheet_names && data.sheet_names.length) ? data.sheet_names : ['Sheet1'];
            currentSheet = sheetNames[0];
            var fn = $('fileName');
            if (fn) fn.textContent = currentFileName;
            if (typeof runAnalysis === 'function') {
                runAnalysis(); // 后端按标准 Jira 列名自行探测字段，直接进入分析/轮询/渲染
            } else if (typeof showToast === 'function') {
                showToast('已拉取 ' + (data.total || 0) + ' 条，请点击「开始分析」', 'success');
            }
        } catch (e) {
            failAnalyze('接入分析失败：' + e.message);
        }
    }

    function handoffToLabelFilter(data) {
        var fileId = data.file_id;
        var fileName = data.file_name || ('eDart_CR_' + fileId + '.csv');
        var total = data.total || 0;
        try {
            // 更新UI
            var uploadArea = $('uploadArea');
            var fileInfo = $('fileInfo');
            var fn = $('fileName');
            var fs = $('fileSize');
            if (uploadArea) uploadArea.style.display = 'none';
            if (fileInfo) fileInfo.style.display = 'flex';
            if (fn) fn.textContent = fileName + '（eDart直连）';
            if (fs) fs.textContent = ' · 共 ' + total + ' 条';

            // 显示进度
            var progressSection = $('progressSection');
            if (progressSection) {
                progressSection.style.display = 'block';
                updateLabelProgress(10, '正在从 eDart 拉取数据…');
            }

            // 下载CSV文件
            fetch('/download/excel_' + fileId + '.csv')
                .then(function (r) {
                    if (!r.ok) throw new Error('下载失败: ' + r.status);
                    return r.blob();
                })
                .then(function (blob) {
                    // 转换为File对象
                    var file = new File([blob], fileName, { type: 'text/csv' });
                    updateLabelProgress(30, '数据下载完成，正在解析…');
                    // 调用label_filter.js的handleFile函数
                    if (typeof handleFile === 'function') {
                        handleFile(file);
                    } else {
                        failAnalyze('Label筛选页面未找到 handleFile 函数');
                    }
                })
                .catch(function (e) {
                    failAnalyze('下载CSV失败：' + e.message);
                });
        } catch (e) {
            failAnalyze('接入Label筛选失败：' + e.message);
        }
    }

    function updateLabelProgress(percent, text) {
        var fill = $('progressFill');
        var txt = $('progressText');
        if (fill) fill.style.width = percent + '%';
        if (txt) txt.textContent = text;
    }

    function failAnalyze(msg) {
        var analyzing = $('analyzing');
        if (analyzing) analyzing.classList.remove('show');
        if (typeof showError === 'function') {
            showError('eDart 拉取失败：' + msg);
        } else {
            alert('eDart 拉取失败：' + msg);
        }
    }
})();
