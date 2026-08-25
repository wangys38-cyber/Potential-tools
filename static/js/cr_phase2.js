/**
 * CR 分析 v7.0 阶段二功能增强
 * 功能：
 * 1. Bug 根因自动归类（AI）
 * 2. 研发效率预测（前端计算）
 * 3. 模块风险预警（前端规则）
 * 4. 智能修复建议增强（AI）
 */
(function () {
    'use strict';

    var _prefix = (window._USER_PREFIX || '') + 'cr_phase2_';

    // ============ 工具函数 ============

    function _getIssues() {
        return (window.currentAnalysisData && window.currentAnalysisData.all_issues) || [];
    }

    function _getModuleStats() {
        return (window.currentAnalysisData && window.currentAnalysisData.module_stats) || {};
    }

    function _parseDate(s) {
        if (!s) return null;
        var d = new Date(s);
        if (!isNaN(d.getTime())) return d;
        var m = String(s).match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
        if (m) return new Date(parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3]));
        return null;
    }

    function _isResolved(status) {
        if (!status) return false;
        var s = String(status).toLowerCase();
        return s.indexOf('resolved') >= 0 || s.indexOf('closed') >= 0 ||
            s.indexOf('done') >= 0 || s.indexOf('已解决') >= 0 || s.indexOf('已关闭') >= 0;
    }

    function _isReopen(resolution, status) {
        var r = String(resolution || '').toLowerCase();
        var s = String(status || '').toLowerCase();
        return r.indexOf('reopen') >= 0 || s.indexOf('reopen') >= 0 || r.indexOf('重新打开') >= 0;
    }

    function _isSevere(severity) {
        if (!severity) return false;
        var s = String(severity).toLowerCase();
        return s.indexOf('blocker') >= 0 || s.indexOf('critical') >= 0 ||
            s.indexOf('fatal') >= 0 || s.indexOf('致命') >= 0 || s.indexOf('严重') >= 0 ||
            s.indexOf('p0') >= 0 || s.indexOf('p1') >= 0;
    }

    function _esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _showToast(msg, type) {
        if (window.showToast) {
            window.showToast(msg, type);
        } else if (window.ToolboxToast) {
            window.ToolboxToast.show(msg, type);
        }
    }

    function _cacheGet(key) {
        try {
            var raw = localStorage.getItem(_prefix + key);
            return raw ? JSON.parse(raw) : null;
        } catch (e) { return null; }
    }

    function _cacheSet(key, val) {
        try { localStorage.setItem(_prefix + key, JSON.stringify(val)); } catch (e) {}
    }

    function _cacheKey() {
        var fn = window.currentFileName || 'default';
        return 'data_' + fn;
    }

    // ============ 功能1：Bug 根因自动归类 ============

    var _rootCauseData = null;

    function _injectRootCauseTab() {
        var tabsContainer = document.querySelector('.tabs');
        if (!tabsContainer || document.querySelector('[data-tab="root-cause"]')) return;
        var btn = document.createElement('button');
        btn.className = 'tab';
        btn.dataset.tab = 'root-cause';
        btn.onclick = function () { if (window.switchTab) window.switchTab('root-cause'); };
        btn.textContent = '根因归类';
        tabsContainer.appendChild(btn);

        var tabLoad = document.getElementById('tab-developer-load');
        if (tabLoad && tabLoad.parentNode) {
            var div = document.createElement('div');
            div.className = 'tab-content';
            div.id = 'tab-root-cause';
            div.innerHTML = '<div id="rootCauseSection"></div>';
            tabLoad.parentNode.insertBefore(div, tabLoad.nextSibling);
        }
    }

    function _initRootCauseSection() {
        var container = document.getElementById('rootCauseSection');
        if (!container) return;
        var issues = _getIssues();
        if (!issues.length) {
            container.innerHTML = '<div style="text-align:center;padding:40px;color:var(--ds-text-tertiary);">请先完成 CR 分析</div>';
            return;
        }
        var unresolved = issues.filter(function (i) { return !_isResolved(i.status); });
        container.innerHTML =
            '<div style="padding:20px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);">' +
            '<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">' +
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--ds-text)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 1v6m0 10v6m11-11h-6M7 12H1m15.5-7.5l-4.2 4.2m-4.6 4.6l-4.2 4.2m0-13l4.2 4.2m4.6 4.6l4.2 4.2"/></svg>' +
            '<h3 style="margin:0;font-size:16px;font-weight:600;color:var(--ds-text);">AI 根因归类</h3>' +
            '<span style="font-size:12px;color:var(--ds-text-tertiary);">未解决 Bug 共 ' + unresolved.length + ' 条</span>' +
            '<button class="btn btn-primary" onclick="CRPhase2.classifyRootCause()" style="margin-left:auto;padding:6px 16px;font-size:12px;">AI 批量归类</button>' +
            '</div>' +
            '<div id="rootCauseResult" style="font-size:13px;color:var(--ds-text-secondary);">点击"AI 批量归类"按钮，对所有未解决 Bug 进行根因自动归类</div>' +
            '</div>';

        // 尝试加载缓存
        var cached = _cacheGet('root_cause_' + _cacheKey());
        if (cached && cached.categories) {
            _rootCauseData = cached;
            _renderRootCauseResult();
        }
    }

    function classifyRootCause() {
        var issues = _getIssues();
        if (!issues.length) { _showToast('请先完成 CR 分析', 'warning'); return; }
        var resultEl = document.getElementById('rootCauseResult');
        if (!resultEl) return;
        resultEl.innerHTML =
            '<div style="text-align:center;padding:30px;">' +
            '<span style="display:inline-block;width:18px;height:18px;border:2px solid var(--ds-accent);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;vertical-align:middle;margin-right:8px;"></span>' +
            'AI 正在分析根因归类...' +
            '</div><style>@keyframes spin{to{transform:rotate(360deg)}}</style>';

        fetch('/api/cr/root-cause-classify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ issues: issues })
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.status === 'success') {
                _rootCauseData = data;
                _cacheSet('root_cause_' + _cacheKey(), data);
                _renderRootCauseResult();
                _showToast('根因归类完成', 'success');
            } else {
                resultEl.innerHTML = '<div style="color:var(--ds-error);padding:16px;">归类失败：' + _esc(data.error || '未知错误') + '</div>';
            }
        }).catch(function (err) {
            resultEl.innerHTML = '<div style="color:var(--ds-error);padding:16px;">网络错误：' + _esc(err.message) + '</div>';
        });
    }

    function _renderRootCauseResult() {
        var resultEl = document.getElementById('rootCauseResult');
        if (!resultEl || !_rootCauseData) return;
        var cats = _rootCauseData.categories || [];
        if (!cats.length) {
            resultEl.innerHTML = '<div style="text-align:center;padding:20px;color:var(--ds-text-tertiary);">没有未解决的 Bug</div>';
            return;
        }
        var total = _rootCauseData.total || cats.reduce(function (a, c) { return a + (c.count || 0); }, 0);

        var html = '';
        // 概览卡片
        html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:20px;">';
        cats.forEach(function (c) {
            html += '<div style="padding:12px;background:var(--ds-bg);border-radius:var(--ds-radius-md);text-align:center;border:1px solid var(--ds-border-light);cursor:pointer;" onclick="CRPhase2.filterRootCause(\'' + _esc(c.category) + '\')">' +
                '<div style="font-size:20px;font-weight:700;color:var(--ds-text);">' + (c.count || 0) + '</div>' +
                '<div style="font-size:11px;color:var(--ds-text-secondary);margin-top:2px;">' + _esc(c.category_name || c.category) + '</div>' +
                '<div style="font-size:10px;color:var(--ds-text-tertiary);">' + (c.percentage || 0) + '%</div>' +
                '</div>';
        });
        html += '</div>';

        // 筛选状态
        html += '<div id="rootCauseFilterBar" style="display:none;margin-bottom:12px;padding:8px 12px;background:var(--ds-bg);border-radius:var(--ds-radius-md);font-size:12px;">' +
            '<span id="rootCauseFilterText"></span>' +
            '<button class="btn btn-secondary" onclick="CRPhase2.clearRootCauseFilter()" style="padding:2px 10px;font-size:11px;margin-left:8px;">清除筛选</button>' +
            '</div>';

        // 各类别详情
        html += '<div id="rootCauseDetailList" style="display:flex;flex-direction:column;gap:12px;">';
        cats.forEach(function (c) {
            var typical = c.typical_issues || [];
            html += '<div class="root-cause-card" data-category="' + _esc(c.category) + '" style="padding:16px;background:var(--ds-bg);border-radius:var(--ds-radius-md);border:1px solid var(--ds-border-light);">' +
                '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">' +
                '<span style="font-weight:600;font-size:14px;color:var(--ds-text);">' + _esc(c.category_name || c.category) + '</span>' +
                '<span style="font-size:12px;color:var(--ds-text-secondary);">' + (c.count || 0) + ' 条 · ' + (c.percentage || 0) + '%</span>' +
                '</div>';
            if (c.description) {
                html += '<div style="font-size:12px;color:var(--ds-text-secondary);line-height:1.6;margin-bottom:8px;">' + _esc(c.description) + '</div>';
            }
            if (typical.length) {
                html += '<div style="font-size:11px;color:var(--ds-text-tertiary);margin-bottom:4px;">典型 Bug：</div>';
                typical.forEach(function (t) {
                    html += '<div style="font-size:12px;color:var(--ds-text);padding:3px 0;">' + _esc(t) + '</div>';
                });
            }
            html += '</div>';
        });
        html += '</div>';

        // 操作按钮
        html += '<div style="display:flex;gap:8px;margin-top:16px;">' +
            '<button class="btn btn-secondary" onclick="CRPhase2.exportRootCauseCSV()" style="padding:6px 14px;font-size:12px;">导出 CSV</button>' +
            '<button class="btn btn-secondary" onclick="CRPhase2.pushRootCauseFeishu()" style="padding:6px 14px;font-size:12px;">推送到飞书</button>' +
            '</div>';

        resultEl.innerHTML = html;
    }

    function filterRootCause(category) {
        var cards = document.querySelectorAll('.root-cause-card');
        var bar = document.getElementById('rootCauseFilterBar');
        var text = document.getElementById('rootCauseFilterText');
        cards.forEach(function (card) {
            card.style.display = (card.dataset.category === category) ? '' : 'none';
        });
        if (bar) bar.style.display = 'block';
        if (text && _rootCauseData) {
            var cat = _rootCauseData.categories.find(function (c) { return c.category === category; });
            text.textContent = '当前筛选：' + (cat ? (cat.category_name || cat.category) : category);
        }
    }

    function clearRootCauseFilter() {
        var cards = document.querySelectorAll('.root-cause-card');
        var bar = document.getElementById('rootCauseFilterBar');
        cards.forEach(function (card) { card.style.display = ''; });
        if (bar) bar.style.display = 'none';
    }

    function exportRootCauseCSV() {
        if (!_rootCauseData || !_rootCauseData.categories) { _showToast('暂无归类数据', 'warning'); return; }
        var headers = ['根因类别', 'Bug数量', '占比(%)', '典型Bug', '描述'];
        var rows = _rootCauseData.categories.map(function (c) {
            return [
                c.category_name || c.category,
                c.count || 0,
                c.percentage || 0,
                (c.typical_issues || []).join('; '),
                (c.description || '').replace(/,/g, '，')
            ];
        });
        var csv = '\uFEFF' + [headers].concat(rows).map(function (r) { return r.join(','); }).join('\n');
        var blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        var link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = (window.currentFileName || 'CR分析') + '_根因归类.csv';
        link.click();
        URL.revokeObjectURL(link.href);
        _showToast('CSV 导出成功', 'success');
    }

    function pushRootCauseFeishu() {
        if (!_rootCauseData || !_rootCauseData.categories) { _showToast('暂无归类数据', 'warning'); return; }
        var md = '**CR 根因归类报告**\n\n';
        md += '未解决 Bug 总数：' + (_rootCauseData.total || 0) + '\n\n';
        _rootCauseData.categories.forEach(function (c, i) {
            md += (i + 1) + '. **' + (c.category_name || c.category) + '**：' + (c.count || 0) + ' 条（' + (c.percentage || 0) + '%）\n';
            if (c.description) md += '   ' + c.description + '\n';
        });
        fetch('/api/feishu/push', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'card', title: 'CR根因归类 - ' + (window.currentFileName || ''), content: md, url: window.location.href })
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.status === 'success') _showToast('已推送到飞书', 'success');
            else _showToast('推送失败：' + (data.error || '未知错误'), 'error');
        }).catch(function (err) { _showToast('推送失败：' + err.message, 'error'); });
    }

    // ============ 功能2：研发效率预测 ============

    function _injectEfficiencyPrediction() {
        var container = document.getElementById('efficiencyRanking');
        if (!container || document.getElementById('effPredictionSection')) return;
        var predDiv = document.createElement('div');
        predDiv.id = 'effPredictionSection';
        predDiv.style.marginBottom = '20px';
        container.insertBefore(predDiv, container.firstChild);
    }

    function renderEfficiencyPrediction() {
        var container = document.getElementById('effPredictionSection');
        if (!container) return;
        var issues = _getIssues();
        if (!issues.length) {
            container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--ds-text-tertiary);font-size:13px;">暂无数据</div>';
            return;
        }

        // 按研发统计历史解决数据
        var devMap = {};
        var now = new Date();
        var twoWeeksAgo = new Date(now.getTime() - 14 * 86400000);

        issues.forEach(function (issue) {
            var dev = (issue.assignee || issue.developer || issue['研发'] || '未分配').trim() || '未分配';
            if (!devMap[dev]) {
                devMap[dev] = { total: 0, resolved: 0, open: 0, reopen: 0, resolveTimes: [], recentResolved: 0, recentDates: [] };
            }
            var d = devMap[dev];
            d.total++;
            var created = _parseDate(issue.created_date || issue.create_date);
            var resolved = _parseDate(issue.resolved_date || issue.resolve_date);
            if (_isResolved(issue.status)) {
                d.resolved++;
                if (created && resolved && resolved >= created) {
                    var days = (resolved - created) / 86400000;
                    if (days >= 0 && days < 365) d.resolveTimes.push(days);
                }
                if (resolved && resolved >= twoWeeksAgo) {
                    d.recentResolved++;
                    d.recentDates.push(resolved);
                }
            } else {
                d.open++;
            }
            if (_isReopen(issue.resolution, issue.status)) d.reopen++;
        });

        var predictions = [];
        Object.keys(devMap).forEach(function (name) {
            var d = devMap[name];
            // 线性回归预测未来2周解决数
            var predictedResolve = 0;
            var confidence = '低';
            if (d.recentDates.length >= 3) {
                // 按天统计近14天解决数
                var dailyCounts = {};
                d.recentDates.forEach(function (dt) {
                    var key = dt.toISOString().slice(0, 10);
                    dailyCounts[key] = (dailyCounts[key] || 0) + 1;
                });
                var datesArr = Object.keys(dailyCounts).sort();
                var vals = datesArr.map(function (k) { return dailyCounts[k]; });
                // 简单线性回归
                var n = vals.length;
                var sumX = (n * (n - 1)) / 2;
                var sumY = vals.reduce(function (a, b) { return a + b; }, 0);
                var sumXY = vals.reduce(function (acc, y, i) { return acc + i * y; }, 0);
                var sumX2 = vals.reduce(function (acc, _, i) { return acc + i * i; }, 0);
                var denom = n * sumX2 - sumX * sumX;
                var slope = denom !== 0 ? (n * sumXY - sumX * sumY) / denom : 0;
                var avgDaily = sumY / n;
                // 预测14天：均值 + 趋势外推
                predictedResolve = Math.max(0, Math.round(avgDaily * 14 + slope * 14 * 3));
                // 置信度
                if (n >= 7 && d.resolveTimes.length >= 5) confidence = '高';
                else if (n >= 4) confidence = '中';
                else confidence = '低';
            } else if (d.resolved > 0) {
                // 用整体平均速率估算
                var avgRate = d.resolved / Math.max(1, d.resolveTimes.length || 1);
                predictedResolve = Math.round(avgRate * 2);
                confidence = d.resolveTimes.length >= 3 ? '中' : '低';
            }

            // 预计 reopen 率
            var reopenRate = d.resolved > 0 ? (d.reopen / d.resolved * 100) : 0;
            var predictedReopenRate = Math.min(100, Math.round(reopenRate * 1.1));

            // 预计平均解决时长
            var avgResolveTime = d.resolveTimes.length ?
                d.resolveTimes.reduce(function (a, b) { return a + b; }, 0) / d.resolveTimes.length : 0;

            // 是否可能延期
            var mayDelay = predictedResolve < d.open;

            predictions.push({
                name: name,
                open: d.open,
                resolved: d.resolved,
                predictedResolve: predictedResolve,
                predictedReopenRate: predictedReopenRate,
                predictedAvgTime: avgResolveTime.toFixed(1),
                confidence: confidence,
                mayDelay: mayDelay
            });
        });

        // 按可能延期优先，再按待解决数排序
        predictions.sort(function (a, b) {
            if (a.mayDelay !== b.mayDelay) return a.mayDelay ? -1 : 1;
            return b.open - a.open;
        });

        var delayCount = predictions.filter(function (p) { return p.mayDelay; }).length;
        var confColor = { '高': 'var(--ds-success)', '中': 'var(--ds-warning)', '低': 'var(--ds-text-tertiary)' };

        var html = '<div style="padding:20px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);">' +
            '<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">' +
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--ds-text)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>' +
            '<h3 style="margin:0;font-size:16px;font-weight:600;color:var(--ds-text);">研发效率预测（未来2周）</h3>' +
            '<span style="font-size:12px;color:var(--ds-text-tertiary);">基于历史解决速率线性回归预测</span>' +
            '</div>';

        if (delayCount > 0) {
            html += '<div style="margin-bottom:14px;padding:10px 14px;background:rgba(239,68,68,0.08);border-radius:var(--ds-radius-md);border-left:3px solid var(--ds-error);font-size:13px;color:var(--ds-text);">' +
                '<strong>预警：</strong>' + delayCount + ' 位研发预计无法在2周内完成当前待解决 Bug，建议关注资源分配' +
                '</div>';
        }

        html += '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:13px;">' +
            '<thead><tr style="border-bottom:1px solid var(--ds-border-light);background:var(--ds-bg);">' +
            '<th style="padding:10px 12px;text-align:left;color:var(--ds-text-secondary);font-weight:500;">研发</th>' +
            '<th style="padding:10px 12px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">待解决</th>' +
            '<th style="padding:10px 12px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">预计解决</th>' +
            '<th style="padding:10px 12px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">预计Reopen率</th>' +
            '<th style="padding:10px 12px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">预计均解决时长</th>' +
            '<th style="padding:10px 12px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">置信度</th>' +
            '<th style="padding:10px 12px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">状态</th>' +
            '</tr></thead><tbody>';

        predictions.forEach(function (p) {
            html += '<tr style="border-bottom:1px solid var(--ds-border-light);' + (p.mayDelay ? 'background:rgba(239,68,68,0.04);' : '') + '">' +
                '<td style="padding:10px 12px;color:var(--ds-text);font-weight:500;">' + _esc(p.name) + '</td>' +
                '<td style="padding:10px 12px;text-align:center;color:var(--ds-text-secondary);">' + p.open + '</td>' +
                '<td style="padding:10px 12px;text-align:center;font-weight:600;color:' + (p.mayDelay ? 'var(--ds-error)' : 'var(--ds-text)') + ';">' + p.predictedResolve + '</td>' +
                '<td style="padding:10px 12px;text-align:center;color:var(--ds-text-secondary);">' + p.predictedReopenRate + '%</td>' +
                '<td style="padding:10px 12px;text-align:center;color:var(--ds-text-secondary);">' + p.predictedAvgTime + ' 天</td>' +
                '<td style="padding:10px 12px;text-align:center;"><span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;color:#fff;background:' + confColor[p.confidence] + ';">' + p.confidence + '</span></td>' +
                '<td style="padding:10px 12px;text-align:center;">' + (p.mayDelay ?
                    '<span style="color:var(--ds-error);font-weight:600;font-size:12px;">可能延期</span>' :
                    '<span style="color:var(--ds-success);font-size:12px;">正常</span>') + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div></div>';
        container.innerHTML = html;
    }

    // ============ 功能3：模块风险预警 ============

    function _injectModuleRiskWarning() {
        var container = document.getElementById('moduleHealth');
        if (!container || document.getElementById('moduleRiskSection')) return;
        var riskDiv = document.createElement('div');
        riskDiv.id = 'moduleRiskSection';
        riskDiv.style.marginBottom = '20px';
        container.insertBefore(riskDiv, container.firstChild);
    }

    function renderModuleRiskWarning() {
        var container = document.getElementById('moduleRiskSection');
        if (!container) return;
        var issues = _getIssues();
        if (!issues.length) {
            container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--ds-text-tertiary);font-size:13px;">暂无数据</div>';
            return;
        }

        var now = new Date();
        var weekAgo = new Date(now.getTime() - 7 * 86400000);
        var twoWeeksAgo = new Date(now.getTime() - 14 * 86400000);

        // 按模块统计
        var modMap = {};
        issues.forEach(function (issue) {
            var mod = (issue.module || issue['模块'] || '未分类').trim() || '未分类';
            if (!modMap[mod]) {
                modMap[mod] = { total: 0, unresolved: 0, severe: 0, recentNew: 0, prevNew: 0, issues: [] };
            }
            var m = modMap[mod];
            m.total++;
            m.issues.push(issue);
            if (!_isResolved(issue.status)) m.unresolved++;
            if (_isSevere(issue.severity)) m.severe++;
            var created = _parseDate(issue.created_date || issue.create_date);
            if (created) {
                if (created >= weekAgo) m.recentNew++;
                if (created >= twoWeeksAgo && created < weekAgo) m.prevNew++;
            }
        });

        var modCount = Object.keys(modMap).length;
        var avgTotal = issues.length / Math.max(1, modCount);

        var riskList = [];
        Object.keys(modMap).forEach(function (name) {
            var m = modMap[name];
            var unresRate = m.total ? m.unresolved / m.total * 100 : 0;
            var severeRate = m.total ? m.severe / m.total * 100 : 0;
            var growthRate = m.prevNew > 0 ? (m.recentNew - m.prevNew) / m.prevNew * 100 : (m.recentNew > 0 ? 100 : 0);

            // 风险评分
            var score = 0;
            var reasons = [];
            if (m.total > avgTotal * 1.5) { score += 2; reasons.push('Bug 数量高于平均水平 ' + (m.total / avgTotal).toFixed(1) + ' 倍'); }
            if (unresRate > 50) { score += 2; reasons.push('未解决率高达 ' + unresRate.toFixed(0) + '%'); }
            else if (unresRate > 30) { score += 1; reasons.push('未解决率 ' + unresRate.toFixed(0) + '%'); }
            if (severeRate > 30) { score += 2; reasons.push('严重 Bug 占比 ' + severeRate.toFixed(0) + '%'); }
            else if (severeRate > 15) { score += 1; reasons.push('严重 Bug 占比 ' + severeRate.toFixed(0) + '%'); }
            if (growthRate > 50) { score += 2; reasons.push('近期 Bug 增长 ' + growthRate.toFixed(0) + '%'); }
            else if (growthRate > 0) { score += 1; reasons.push('近期 Bug 呈增长趋势'); }

            var level, label, color, bgColor, suggestion;
            if (score >= 5) {
                level = 'high'; label = '高风险'; color = '#ef4444';
                bgColor = 'rgba(239,68,68,0.08)';
                suggestion = '建议立即投入专项资源，优先解决严重 Bug，安排代码审查和回归测试';
            } else if (score >= 3) {
                level = 'medium'; label = '中风险'; color = '#f59e0b';
                bgColor = 'rgba(245,158,11,0.08)';
                suggestion = '建议关注该模块进展，适当增加测试覆盖，提前分配修复资源';
            } else {
                level = 'low'; label = '低风险'; color = '#10b981';
                bgColor = 'rgba(16,185,129,0.08)';
                suggestion = '保持当前研发节奏，持续监控';
            }

            riskList.push({
                name: name, total: m.total, unresolved: m.unresolved, severe: m.severe,
                unresRate: unresRate.toFixed(0), severeRate: severeRate.toFixed(0),
                recentNew: m.recentNew, growthRate: growthRate.toFixed(0),
                score: score, level: level, label: label, color: color, bgColor: bgColor,
                reasons: reasons, suggestion: suggestion
            });
        });

        // 高风险排顶部
        var levelOrder = { high: 0, medium: 1, low: 2 };
        riskList.sort(function (a, b) {
            if (levelOrder[a.level] !== levelOrder[b.level]) return levelOrder[a.level] - levelOrder[b.level];
            return b.score - a.score;
        });

        var highCount = riskList.filter(function (r) { return r.level === 'high'; }).length;
        var medCount = riskList.filter(function (r) { return r.level === 'medium'; }).length;

        var html = '<div style="padding:20px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);">' +
            '<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">' +
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--ds-text)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' +
            '<h3 style="margin:0;font-size:16px;font-weight:600;color:var(--ds-text);">模块风险预警</h3>' +
            '<span style="font-size:12px;color:var(--ds-text-tertiary);">基于 Bug 数量、未解决率、严重度、增长趋势综合评估</span>' +
            '<button class="btn btn-secondary" onclick="CRPhase2.pushRiskFeishu()" style="margin-left:auto;padding:6px 14px;font-size:12px;">推送到飞书</button>' +
            '</div>';

        if (highCount > 0) {
            html += '<div style="margin-bottom:14px;padding:10px 14px;background:rgba(239,68,68,0.08);border-radius:var(--ds-radius-md);border-left:3px solid #ef4444;font-size:13px;color:var(--ds-text);">' +
                '<strong>高风险模块 ' + highCount + ' 个</strong>，中风险 ' + medCount + ' 个，建议优先处理高风险模块' +
                '</div>';
        }

        html += '<div style="display:flex;flex-direction:column;gap:10px;">';
        riskList.forEach(function (m) {
            html += '<div style="padding:14px 16px;background:' + m.bgColor + ';border-radius:var(--ds-radius-md);border-left:3px solid ' + m.color + ';">' +
                '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:8px;">' +
                '<span style="font-weight:600;font-size:14px;color:var(--ds-text);">' + _esc(m.name) + '</span>' +
                '<span style="display:inline-block;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:600;color:#fff;background:' + m.color + ';">' + m.label + '</span>' +
                '</div>' +
                '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(80px,1fr));gap:8px;margin-bottom:8px;font-size:12px;">' +
                '<div><span style="color:var(--ds-text-tertiary);">总数</span> <strong style="color:var(--ds-text);">' + m.total + '</strong></div>' +
                '<div><span style="color:var(--ds-text-tertiary);">未解决</span> <strong style="color:var(--ds-error);">' + m.unresolved + '</strong></div>' +
                '<div><span style="color:var(--ds-text-tertiary);">严重</span> <strong style="color:#dc2626;">' + m.severe + '</strong></div>' +
                '<div><span style="color:var(--ds-text-tertiary);">近7天新增</span> <strong style="color:var(--ds-text);">' + m.recentNew + '</strong></div>' +
                '</div>';
            if (m.reasons.length) {
                html += '<div style="font-size:12px;color:var(--ds-text-secondary);line-height:1.6;margin-bottom:6px;">' +
                    '<strong style="color:var(--ds-text);">风险原因：</strong>' + m.reasons.join('；') + '</div>';
            }
            html += '<div style="font-size:12px;color:var(--ds-text-secondary);line-height:1.6;">' +
                '<strong style="color:var(--ds-text);">建议：</strong>' + m.suggestion + '</div>' +
                (m.level === 'high' ? '<button class="btn btn-primary" onclick="CRPhase2.generateFixSuggestion(\'' + _esc(m.name).replace(/'/g, "\\'") + '\')" style="margin-top:8px;padding:4px 12px;font-size:11px;">生成修复建议</button>' : '') +
                '</div>';
        });
        html += '</div></div>';
        container.innerHTML = html;
        window._riskData = riskList;
    }

    function pushRiskFeishu() {
        if (!window._riskData || !window._riskData.length) { _showToast('暂无风险数据', 'warning'); return; }
        var md = '**CR 模块风险预警**\n\n';
        window._riskData.forEach(function (m, i) {
            if (m.level === 'low' && i > 5) return;
            md += (i + 1) + '. **' + m.name + '** [' + m.label + ']\n';
            md += '   总数' + m.total + '，未解决' + m.unresolved + '，严重' + m.severe + '\n';
            if (m.reasons.length) md += '   原因：' + m.reasons.join('；') + '\n';
            md += '   建议：' + m.suggestion + '\n\n';
        });
        fetch('/api/feishu/push', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'card', title: 'CR模块风险预警 - ' + (window.currentFileName || ''), content: md, url: window.location.href })
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.status === 'success') _showToast('已推送到飞书', 'success');
            else _showToast('推送失败：' + (data.error || '未知错误'), 'error');
        }).catch(function (err) { _showToast('推送失败：' + err.message, 'error'); });
    }

    // ============ 功能4：智能修复建议增强 ============

    function _injectFixSuggestions() {
        var suggestionsList = document.getElementById('suggestionsList');
        if (!suggestionsList || document.getElementById('smartFixSection')) return;
        var section = document.createElement('div');
        section.id = 'smartFixSection';
        section.style.marginTop = '20px';
        suggestionsList.parentNode.insertBefore(section, suggestionsList.nextSibling);
    }

    function _initFixSuggestions() {
        var section = document.getElementById('smartFixSection');
        if (!section) return;
        var issues = _getIssues();
        if (!issues.length) {
            section.innerHTML = '';
            return;
        }
        section.innerHTML =
            '<div style="padding:20px;background:var(--ds-bg-elevated);border-radius:var(--ds-radius-lg);border:1px solid var(--ds-border-light);">' +
            '<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">' +
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--ds-text)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>' +
            '<h3 style="margin:0;font-size:16px;font-weight:600;color:var(--ds-text);">智能修复建议</h3>' +
            '<span style="font-size:12px;color:var(--ds-text-tertiary);">针对高风险模块生成具体修复方案</span>' +
            '</div>' +
            '<div id="smartFixModuleSelect" style="margin-bottom:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
            '<label style="font-size:13px;color:var(--ds-text);">选择模块：</label>' +
            '<select id="smartFixModuleSel" style="padding:6px 10px;border:1px solid var(--ds-border);border-radius:var(--ds-radius-md);font-size:13px;background:var(--ds-bg);color:var(--ds-text);min-width:180px;"></select>' +
            '<button class="btn btn-primary" onclick="CRPhase2.generateFixSuggestionForSelected()" style="padding:6px 14px;font-size:12px;">生成修复建议</button>' +
            '</div>' +
            '<div id="smartFixResult" style="font-size:13px;color:var(--ds-text-secondary);">选择模块后点击生成，AI 将给出具体可执行的修复建议</div>' +
            '</div>';

        // 填充模块下拉
        var modStats = _getModuleStats();
        var sel = document.getElementById('smartFixModuleSel');
        if (sel) {
            var mods = Object.keys(modStats).sort(function (a, b) {
                return (modStats[b].unresolved || 0) - (modStats[a].unresolved || 0);
            });
            mods.forEach(function (m) {
                var opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m + '（未解决 ' + (modStats[m].unresolved || 0) + '）';
                sel.appendChild(opt);
            });
        }

        // 加载知识库缓存
        var kb = _cacheGet('fix_kb_' + _cacheKey());
        if (kb && kb.length) {
            _renderFixKB(kb);
        }
    }

    function generateFixSuggestionForSelected() {
        var sel = document.getElementById('smartFixModuleSel');
        if (!sel || !sel.value) { _showToast('请选择模块', 'warning'); return; }
        generateFixSuggestion(sel.value);
    }

    function generateFixSuggestion(moduleName) {
        var issues = _getIssues();
        if (!issues.length) { _showToast('请先完成 CR 分析', 'warning'); return; }
        var resultEl = document.getElementById('smartFixResult');
        if (!resultEl) return;

        resultEl.innerHTML =
            '<div style="text-align:center;padding:30px;">' +
            '<span style="display:inline-block;width:18px;height:18px;border:2px solid var(--ds-accent);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;vertical-align:middle;margin-right:8px;"></span>' +
            'AI 正在生成修复建议...' +
            '</div><style>@keyframes spin{to{transform:rotate(360deg)}}</style>';

        fetch('/api/cr/smart-fix-suggestions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_type: 'module',
                target_name: moduleName,
                issues: issues,
                module_stats: _getModuleStats()
            })
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.status === 'success' && data.data) {
                _renderFixSuggestion(moduleName, data.data);
                _saveToKB(moduleName, data.data);
                _showToast('修复建议生成完成', 'success');
            } else {
                resultEl.innerHTML = '<div style="color:var(--ds-error);padding:16px;">生成失败：' + _esc(data.error || '未知错误') + '</div>';
            }
        }).catch(function (err) {
            resultEl.innerHTML = '<div style="color:var(--ds-error);padding:16px;">网络错误：' + _esc(err.message) + '</div>';
        });
    }

    function _renderFixSuggestion(moduleName, data) {
        var resultEl = document.getElementById('smartFixResult');
        if (!resultEl) return;
        var suggestions = data.suggestions || [];
        var priColor = { '高': '#ef4444', '中': '#f59e0b', '低': '#10b981' };

        var html = '';
        if (data.summary) {
            html += '<div style="padding:12px 14px;background:var(--ds-bg);border-radius:var(--ds-radius-md);margin-bottom:14px;font-size:13px;line-height:1.7;color:var(--ds-text-secondary);border-left:3px solid var(--ds-accent);">' +
                '<strong style="color:var(--ds-text);">模块分析：</strong>' + _esc(data.summary) + '</div>';
        }

        html += '<div style="display:flex;flex-direction:column;gap:10px;">';
        suggestions.forEach(function (s, idx) {
            var color = priColor[s.priority] || 'var(--ds-text-secondary)';
            html += '<div style="padding:14px 16px;background:var(--ds-bg);border-radius:var(--ds-radius-md);border:1px solid var(--ds-border-light);border-left:3px solid ' + color + ';">' +
                '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:6px;">' +
                '<span style="font-weight:600;font-size:14px;color:var(--ds-text);">' + (idx + 1) + '. ' + _esc(s.title || '建议') + '</span>' +
                '<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;color:#fff;background:' + color + ';">优先级：' + _esc(s.priority || '中') + '</span>' +
                '</div>' +
                '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px;margin-bottom:8px;font-size:12px;">' +
                '<div><span style="color:var(--ds-text-tertiary);">预计时间：</span><strong style="color:var(--ds-text);">' + _esc(s.estimated_time || '-') + '</strong></div>' +
                '<div><span style="color:var(--ds-text-tertiary);">所需资源：</span><strong style="color:var(--ds-text);">' + _esc(s.resources || '-') + '</strong></div>' +
                '</div>';
            if (s.solution) {
                html += '<div style="font-size:12px;color:var(--ds-text-secondary);line-height:1.6;margin-bottom:6px;"><strong style="color:var(--ds-text);">方案：</strong>' + _esc(s.solution) + '</div>';
            }
            if (s.reference) {
                html += '<div style="font-size:12px;color:var(--ds-text-tertiary);line-height:1.6;"><strong>参考：</strong>' + _esc(s.reference) + '</div>';
            }
            html += '<div style="margin-top:8px;display:flex;gap:6px;">' +
                '<button class="btn btn-secondary" onclick="CRPhase2.copyFixTask(\'' + idx + '\')" style="padding:3px 10px;font-size:11px;">复制任务</button>' +
                '<button class="btn btn-secondary" onclick="CRPhase2.pushFixTask(\'' + idx + '\')" style="padding:3px 10px;font-size:11px;">推送飞书</button>' +
                '</div></div>';
        });
        html += '</div>';

        if (data.risk_assessment) {
            html += '<div style="margin-top:12px;padding:10px 14px;background:rgba(239,68,68,0.06);border-radius:var(--ds-radius-md);font-size:12px;color:var(--ds-text-secondary);line-height:1.6;">' +
                '<strong style="color:var(--ds-error);">风险评估：</strong>' + _esc(data.risk_assessment) + '</div>';
        }

        resultEl.innerHTML = html;
        window._currentFixData = { module: moduleName, data: data };
    }

    function _saveToKB(moduleName, data) {
        var kb = _cacheGet('fix_kb_' + _cacheKey()) || [];
        // 去重
        kb = kb.filter(function (item) { return item.module !== moduleName; });
        kb.unshift({ module: moduleName, data: data, time: new Date().toISOString() });
        if (kb.length > 20) kb = kb.slice(0, 20);
        _cacheSet('fix_kb_' + _cacheKey(), kb);
        _renderFixKB(kb);
    }

    function _renderFixKB(kb) {
        // 知识库展示区域（在结果下方）
        var section = document.getElementById('smartFixSection');
        if (!section) return;
        var kbEl = document.getElementById('fixKBSection');
        if (!kbEl) {
            kbEl = document.createElement('div');
            kbEl.id = 'fixKBSection';
            kbEl.style.marginTop = '14px';
            section.appendChild(kbEl);
        }
        if (!kb.length) { kbEl.innerHTML = ''; return; }
        var html = '<div style="padding:12px 14px;background:var(--ds-bg);border-radius:var(--ds-radius-md);border:1px solid var(--ds-border-light);">' +
            '<div style="font-size:12px;font-weight:600;color:var(--ds-text);margin-bottom:8px;">已保存的修复建议（本地知识库）</div>' +
            '<div style="display:flex;flex-wrap:wrap;gap:6px;">';
        kb.forEach(function (item, idx) {
            html += '<button class="btn btn-secondary" onclick="CRPhase2.loadFixKB(' + idx + ')" style="padding:3px 10px;font-size:11px;">' + _esc(item.module) + '</button>';
        });
        html += '<button class="btn btn-secondary" onclick="CRPhase2.clearFixKB()" style="padding:3px 10px;font-size:11px;color:var(--ds-error);">清空</button>';
        html += '</div></div>';
        kbEl.innerHTML = html;
    }

    function loadFixKB(idx) {
        var kb = _cacheGet('fix_kb_' + _cacheKey()) || [];
        if (kb[idx]) {
            var sel = document.getElementById('smartFixModuleSel');
            if (sel) sel.value = kb[idx].module;
            _renderFixSuggestion(kb[idx].module, kb[idx].data);
        }
    }

    function clearFixKB() {
        _cacheSet('fix_kb_' + _cacheKey(), []);
        var kbEl = document.getElementById('fixKBSection');
        if (kbEl) kbEl.innerHTML = '';
        _showToast('知识库已清空', 'success');
    }

    function copyFixTask(idx) {
        if (!window._currentFixData) return;
        var s = window._currentFixData.data.suggestions[idx];
        if (!s) return;
        var text = '【修复任务】' + (s.title || '') + '\n' +
            '模块：' + window._currentFixData.module + '\n' +
            '优先级：' + (s.priority || '中') + '\n' +
            '预计时间：' + (s.estimated_time || '-') + '\n' +
            '所需资源：' + (s.resources || '-') + '\n' +
            '修复方案：' + (s.solution || '') + '\n' +
            '参考：' + (s.reference || '');
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(function () { _showToast('已复制到剪贴板', 'success'); });
        } else {
            var ta = document.createElement('textarea');
            ta.value = text; document.body.appendChild(ta); ta.select();
            document.execCommand('copy'); document.body.removeChild(ta);
            _showToast('已复制到剪贴板', 'success');
        }
    }

    function pushFixTask(idx) {
        if (!window._currentFixData) return;
        var s = window._currentFixData.data.suggestions[idx];
        if (!s) return;
        var md = '**修复任务：' + (s.title || '') + '**\n\n' +
            '模块：' + window._currentFixData.module + '\n' +
            '优先级：' + (s.priority || '中') + '\n' +
            '预计时间：' + (s.estimated_time || '-') + '\n' +
            '所需资源：' + (s.resources || '-') + '\n\n' +
            '**修复方案：**\n' + (s.solution || '') + '\n\n' +
            '**参考：**\n' + (s.reference || '');
        fetch('/api/feishu/push', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'card', title: '修复任务 - ' + window._currentFixData.module, content: md, url: window.location.href })
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.status === 'success') _showToast('已推送到飞书', 'success');
            else _showToast('推送失败：' + (data.error || '未知错误'), 'error');
        }).catch(function (err) { _showToast('推送失败：' + err.message, 'error'); });
    }

    // ============ 初始化与钩子 ============

    function _hookDisplayResults() {
        if (typeof window.displayResults !== 'function') return;
        var orig = window.displayResults;
        window.displayResults = function () {
            orig.apply(this, arguments);
            setTimeout(function () {
                _initRootCauseSection();
                _injectEfficiencyPrediction();
                renderEfficiencyPrediction();
                _injectModuleRiskWarning();
                renderModuleRiskWarning();
                _injectFixSuggestions();
                _initFixSuggestions();
            }, 150);
        };
    }

    function init() {
        _injectRootCauseTab();
        _hookDisplayResults();
        // 如果已有数据（页面刷新后），直接初始化
        if (window.currentAnalysisData && window.currentAnalysisData.all_issues) {
            setTimeout(function () {
                _initRootCauseSection();
                _injectEfficiencyPrediction();
                renderEfficiencyPrediction();
                _injectModuleRiskWarning();
                renderModuleRiskWarning();
                _injectFixSuggestions();
                _initFixSuggestions();
            }, 200);
        }
    }

    // 暴露到全局
    window.CRPhase2 = {
        init: init,
        classifyRootCause: classifyRootCause,
        filterRootCause: filterRootCause,
        clearRootCauseFilter: clearRootCauseFilter,
        exportRootCauseCSV: exportRootCauseCSV,
        pushRootCauseFeishu: pushRootCauseFeishu,
        renderEfficiencyPrediction: renderEfficiencyPrediction,
        renderModuleRiskWarning: renderModuleRiskWarning,
        pushRiskFeishu: pushRiskFeishu,
        generateFixSuggestion: generateFixSuggestion,
        generateFixSuggestionForSelected: generateFixSuggestionForSelected,
        loadFixKB: loadFixKB,
        clearFixKB: clearFixKB,
        copyFixTask: copyFixTask,
        pushFixTask: pushFixTask
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
