// Task3: 项目计划甘特图
(function() {
    var ganttContainer = null;
    var ganttViewMode = 'week'; // week or month
    var ganttData = [];
    var ganttEditing = null;

    // 注入甘特图切换按钮和容器
    function injectGanttUI() {
        var actionBtns = document.querySelector('.action-buttons');
        if (!actionBtns || document.getElementById('ganttToggleBtn')) return;

        var ganttBtn = document.createElement('button');
        ganttBtn.className = 'action-btn';
        ganttBtn.id = 'ganttToggleBtn';
        ganttBtn.textContent = ' 甘特图';
        ganttBtn.onclick = toggleGanttView;
        actionBtns.insertBefore(ganttBtn, actionBtns.firstChild);

        // 创建甘特图容器
        var timelineSection = document.getElementById('timelineSection');
        if (!timelineSection) return;

        ganttContainer = document.createElement('div');
        ganttContainer.id = 'ganttSection';
        ganttContainer.style.display = 'none';
        ganttContainer.style.marginTop = '16px';
        ganttContainer.innerHTML = '' +
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">' +
                '<h3 style="font-size:16px;font-weight:700;margin:0;"> 项目甘特图</h3>' +
                '<div style="display:flex;gap:6px;align-items:center;">' +
                    '<span style="font-size:12px;color:var(--text-tertiary);">视图：</span>' +
                    '<button id="ganttWeekBtn" onclick="window.setGanttMode(\'week\')" style="padding:4px 12px;font-size:12px;border-radius:6px;border:1px solid var(--border);background:#000;color:#fff;cursor:pointer;">周</button>' +
                    '<button id="ganttMonthBtn" onclick="window.setGanttMode(\'month\')" style="padding:4px 12px;font-size:12px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text-primary);cursor:pointer;">月</button>' +
                    '<button onclick="window.exportGanttSVG()" style="padding:4px 12px;font-size:12px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text-primary);cursor:pointer;margin-left:8px;"> 导出</button>' +
                '</div>' +
            '</div>' +
            '<div style="background:var(--bg-card);border-radius:12px;border:1px solid var(--border);padding:16px;overflow-x:auto;">' +
                '<div id="ganttChartWrap" style="min-width:600px;"></div>' +
            '</div>' +
            '<div id="ganttLegend" style="display:flex;gap:16px;margin-top:12px;font-size:12px;color:var(--text-tertiary);flex-wrap:wrap;"></div>';
        timelineSection.parentNode.insertBefore(ganttContainer, timelineSection.nextSibling);
    }

    function toggleGanttView() {
        if (!ganttContainer) return;
        var planTable = document.getElementById('planTable');
        var timelineSec = document.getElementById('timelineSection');
        if (ganttContainer.style.display === 'none') {
            ganttContainer.style.display = 'block';
            if (planTable) planTable.style.display = 'none';
            if (timelineSec) timelineSec.style.display = 'none';
            renderGantt();
        } else {
            ganttContainer.style.display = 'none';
            if (planTable) planTable.style.display = '';
            if (timelineSec && window.currentPlan && window.currentPlan.length > 0) timelineSec.style.display = 'block';
        }
    }

    window.setGanttMode = function(mode) {
        ganttViewMode = mode;
        var weekBtn = document.getElementById('ganttWeekBtn');
        var monthBtn = document.getElementById('ganttMonthBtn');
        if (weekBtn) { weekBtn.style.background = mode === 'week' ? '#000' : 'var(--bg-card)'; weekBtn.style.color = mode === 'week' ? '#fff' : 'var(--text-primary)'; }
        if (monthBtn) { monthBtn.style.background = mode === 'month' ? '#000' : 'var(--bg-card)'; monthBtn.style.color = mode === 'month' ? '#fff' : 'var(--text-primary)'; }
        renderGantt();
    };

    // 准备甘特图数据
    function prepareGanttData() {
        if (!window.currentPlan || window.currentPlan.length === 0) return [];
        var today = new Date();
        today.setHours(0,0,0,0);
        var data = [];
        for (var i = 0; i < window.currentPlan.length; i++) {
            var item = window.currentPlan[i];
            var startDate = item.dateObj ? new Date(item.dateObj) : new Date(item.date);
            var durationWeeks = item.duration || 0;
            var endDate = new Date(startDate);
            endDate.setDate(endDate.getDate() + durationWeeks * 7);
            // 计算状态
            var status = 'not_started';
            var statusLabel = '未开始';
            var statusColor = '#9ca3af';
            if (today >= endDate) {
                status = 'completed'; statusLabel = '已完成'; statusColor = '#10b981';
            } else if (today >= startDate) {
                status = 'in_progress'; statusLabel = '进行中'; statusColor = '#3b82f6';
            }
            // 检查是否延期（如果有进度字段且未完成但已过结束日期）
            if (item.status === 'delayed' || (item.progress !== undefined && item.progress < 100 && today > endDate)) {
                status = 'delayed'; statusLabel = '延期'; statusColor = '#ef4444';
            }
            var progress = item.progress !== undefined ? item.progress : (status === 'completed' ? 100 : (status === 'in_progress' ? 50 : 0));
            data.push({
                index: item.index,
                name: item.name,
                startDate: startDate,
                endDate: endDate,
                durationWeeks: durationWeeks,
                isMilestone: item.isMilestone,
                status: status,
                statusLabel: statusLabel,
                statusColor: statusColor,
                progress: progress,
                dateStr: item.date
            });
        }
        return data;
    }

    function renderGantt() {
        var wrap = document.getElementById('ganttChartWrap');
        if (!wrap) return;
        ganttData = prepareGanttData();
        if (ganttData.length === 0) {
            wrap.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-tertiary);">请先生成项目计划</div>';
            return;
        }

        // 计算时间范围
        var minDate = new Date(ganttData[0].startDate);
        var maxDate = new Date(ganttData[0].endDate);
        for (var i = 1; i < ganttData.length; i++) {
            if (ganttData[i].startDate < minDate) minDate = new Date(ganttData[i].startDate);
            if (ganttData[i].endDate > maxDate) maxDate = new Date(ganttData[i].endDate);
        }
        // 扩展边界
        minDate.setDate(minDate.getDate() - 3);
        maxDate.setDate(maxDate.getDate() + 3);

        var rowHeight = 40;
        var labelWidth = 160;
        var headerHeight = 50;
        var totalDays = Math.ceil((maxDate - minDate) / 86400000);
        var daysPerUnit = ganttViewMode === 'week' ? 7 : 30;
        var unitWidth = ganttViewMode === 'week' ? 60 : 80;
        var totalUnits = Math.ceil(totalDays / daysPerUnit);
        var chartWidth = labelWidth + totalUnits * unitWidth + 20;
        var chartHeight = headerHeight + ganttData.length * rowHeight + 20;

        var svg = '<svg width="' + chartWidth + '" height="' + chartHeight + '" xmlns="http://www.w3.org/2000/svg" style="font-family:-apple-system,sans-serif;">';
        svg += '<style>';
        svg += '.gantt-bar{cursor:pointer;transition:opacity 0.2s;}';
        svg += '.gantt-bar:hover{opacity:0.8;}';
        svg += '.gantt-label{font-size:12px;fill:var(--text-primary);}';
        svg += '.gantt-header{font-size:11px;fill:var(--text-tertiary);}';
        svg += '.gantt-today{stroke:#ef4444;stroke-width:2;stroke-dasharray:4,4;}';
        svg += '</style>';

        // 背景
        svg += '<rect width="' + chartWidth + '" height="' + chartHeight + '" fill="var(--bg-card)"/>';

        // 表头 - 时间刻度
        svg += '<rect x="0" y="0" width="' + chartWidth + '" height="' + headerHeight + '" fill="var(--bg-secondary)"/>';
        svg += '<text x="' + (labelWidth/2) + '" y="30" text-anchor="middle" class="gantt-header" style="font-weight:600;">节点</text>';

        for (var u = 0; u <= totalUnits; u++) {
            var x = labelWidth + u * unitWidth;
            var unitDate = new Date(minDate);
            unitDate.setDate(unitDate.getDate() + u * daysPerUnit);
            var label = '';
            if (ganttViewMode === 'week') {
                label = (unitDate.getMonth()+1) + '/' + unitDate.getDate();
            } else {
                label = unitDate.getFullYear() + '-' + (unitDate.getMonth()+1);
            }
            svg += '<line x1="' + x + '" y1="' + headerHeight + '" x2="' + x + '" y2="' + (chartHeight - 20) + '" stroke="var(--border)" stroke-width="0.5"/>';
            if (u < totalUnits) {
                svg += '<text x="' + (x + unitWidth/2) + '" y="30" text-anchor="middle" class="gantt-header">' + label + '</text>';
            }
        }

        // 今天线
        var today = new Date();
        today.setHours(0,0,0,0);
        if (today >= minDate && today <= maxDate) {
            var todayX = labelWidth + ((today - minDate) / 86400000) / daysPerUnit * unitWidth;
            svg += '<line x1="' + todayX + '" y1="' + headerHeight + '" x2="' + todayX + '" y2="' + (chartHeight - 20) + '" class="gantt-today"/>';
            svg += '<text x="' + (todayX + 4) + '" y="' + (headerHeight + 14) + '" class="gantt-header" fill="#ef4444">今天</text>';
        }

        // 行和条形
        for (var j = 0; j < ganttData.length; j++) {
            var item = ganttData[j];
            var y = headerHeight + j * rowHeight;
            // 行背景
            if (j % 2 === 0) {
                svg += '<rect x="0" y="' + y + '" width="' + chartWidth + '" height="' + rowHeight + '" fill="var(--bg-secondary)" opacity="0.3"/>';
            }
            // 标签
            svg += '<text x="10" y="' + (y + rowHeight/2 + 4) + '" class="gantt-label">' + (item.isMilestone ? ' ' : '') + item.name + '</text>';

            // 条形
            var barX = labelWidth + ((item.startDate - minDate) / 86400000) / daysPerUnit * unitWidth;
            var barW = Math.max(20, ((item.endDate - item.startDate) / 86400000) / daysPerUnit * unitWidth);
            var barY = y + 8;
            var barH = rowHeight - 16;

            if (item.isMilestone) {
                // 里程碑用菱形
                var cx = barX + barW/2;
                var cy = barY + barH/2;
                var sz = 10;
                svg += '<polygon points="' + cx + ',' + (cy-sz) + ' ' + (cx+sz) + ',' + cy + ' ' + cx + ',' + (cy+sz) + ' ' + (cx-sz) + ',' + cy + '" fill="' + item.statusColor + '" class="gantt-bar" onclick="window.showGanttDetail(' + j + ')" data-index="' + j + '"/>';
            } else {
                // 普通条形
                svg += '<rect x="' + barX + '" y="' + barY + '" width="' + barW + '" height="' + barH + '" rx="4" fill="' + item.statusColor + '" class="gantt-bar" opacity="0.3" onclick="window.showGanttDetail(' + j + ')" data-index="' + j + '"/>';
                // 进度
                var progressW = barW * (item.progress / 100);
                svg += '<rect x="' + barX + '" y="' + barY + '" width="' + progressW + '" height="' + barH + '" rx="4" fill="' + item.statusColor + '" class="gantt-bar" onclick="window.showGanttDetail(' + j + ')" data-index="' + j + '"/>';
                // 进度文字
                if (barW > 40) {
                    svg += '<text x="' + (barX + barW/2) + '" y="' + (barY + barH/2 + 4) + '" text-anchor="middle" fill="#fff" font-size="11px" font-weight="600" pointer-events="none">' + item.progress + '%</text>';
                }
            }
        }

        svg += '</svg>';
        wrap.innerHTML = svg;

        // 图例
        var legend = document.getElementById('ganttLegend');
        if (legend) {
            legend.innerHTML =
                '<span style="display:flex;align-items:center;gap:4px;"><span style="display:inline-block;width:12px;height:12px;background:#9ca3af;border-radius:2px;"></span>未开始</span>' +
                '<span style="display:flex;align-items:center;gap:4px;"><span style="display:inline-block;width:12px;height:12px;background:#3b82f6;border-radius:2px;"></span>进行中</span>' +
                '<span style="display:flex;align-items:center;gap:4px;"><span style="display:inline-block;width:12px;height:12px;background:#10b981;border-radius:2px;"></span>已完成</span>' +
                '<span style="display:flex;align-items:center;gap:4px;"><span style="display:inline-block;width:12px;height:12px;background:#ef4444;border-radius:2px;"></span>延期</span>' +
                '<span style="display:flex;align-items:center;gap:4px;"><span style="display:inline-block;width:12px;height:12px;background:#ef4444;border-left:2px dashed #ef4444;"></span>今天</span>' +
                '<span style="margin-left:auto;color:var(--text-tertiary);">点击条形查看详情</span>';
        }
    }

    window.showGanttDetail = function(index) {
        var item = ganttData[index];
        if (!item) return;
        var modal = document.getElementById('ganttDetailModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'ganttDetailModal';
            modal.style.cssText = 'display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:10001;align-items:center;justify-content:center;';
            document.body.appendChild(modal);
        }
        modal.style.display = 'flex';
        modal.innerHTML =
            '<div style="background:var(--bg-card);border-radius:16px;width:90%;max-width:420px;box-shadow:0 12px 40px rgba(0,0,0,0.2);">' +
            '<div style="padding:18px 22px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;">' +
            '<h3 style="margin:0;font-size:16px;font-weight:700;">' + (item.isMilestone ? ' ' : '') + item.name + '</h3>' +
            '<button onclick="document.getElementById(\'ganttDetailModal\').style.display=\'none\'" style="background:none;border:none;cursor:pointer;font-size:20px;color:var(--text-tertiary);">×</button>' +
            '</div>' +
            '<div style="padding:18px 22px;">' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px;">' +
            '<div><span style="color:var(--text-tertiary);">开始日期：</span><br><strong>' + item.dateStr + '</strong></div>' +
            '<div><span style="color:var(--text-tertiary);">结束日期：</span><br><strong>' + formatDateStr(item.endDate) + '</strong></div>' +
            '<div><span style="color:var(--text-tertiary);">持续时间：</span><br><strong>' + item.durationWeeks + ' 周</strong></div>' +
            '<div><span style="color:var(--text-tertiary);">状态：</span><br><strong style="color:' + item.statusColor + ';">' + item.statusLabel + '</strong></div>' +
            '<div style="grid-column:1/-1;"><span style="color:var(--text-tertiary);">进度：</span><strong>' + item.progress + '%</strong>' +
            '<div style="margin-top:6px;height:8px;background:var(--bg-secondary);border-radius:4px;overflow:hidden;"><div style="height:100%;width:' + item.progress + '%;background:' + item.statusColor + ';border-radius:4px;"></div></div></div>' +
            '</div>' +
            '<div style="margin-top:16px;display:flex;gap:8px;">' +
            '<button onclick="window.adjustGanttProgress(' + index + ')" style="flex:1;padding:8px 16px;background:#000;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:13px;">调整进度</button>' +
            '<button onclick="document.getElementById(\'ganttDetailModal\').style.display=\'none\'" style="flex:1;padding:8px 16px;background:var(--bg-card);color:var(--text-primary);border:1px solid var(--border);border-radius:8px;cursor:pointer;font-size:13px;">关闭</button>' +
            '</div></div></div>';
    };

    window.adjustGanttProgress = function(index) {
        var item = ganttData[index];
        if (!item) return;
        var newProgress = prompt('请输入 ' + item.name + ' 的进度（0-100）：', item.progress);
        if (newProgress === null) return;
        newProgress = parseInt(newProgress);
        if (isNaN(newProgress) || newProgress < 0 || newProgress > 100) { showToast('请输入0-100之间的数字', 'warning'); return; }
        // 更新currentPlan
        if (window.currentPlan && window.currentPlan[index]) {
            window.currentPlan[index].progress = newProgress;
        }
        document.getElementById('ganttDetailModal').style.display = 'none';
        renderGantt();
    };

    window.exportGanttSVG = function() {
        var wrap = document.getElementById('ganttChartWrap');
        if (!wrap || !wrap.querySelector('svg')) { showToast('请先生成甘特图', 'warning'); return; }
        var svgData = new XMLSerializer().serializeToString(wrap.querySelector('svg'));
        var blob = new Blob([svgData], {type: 'image/svg+xml;charset=utf-8'});
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'gantt_chart_' + Date.now() + '.svg';
        a.click();
        URL.revokeObjectURL(url);
    };

    function formatDateStr(d) {
        var y = d.getFullYear();
        var m = String(d.getMonth()+1).padStart(2,'0');
        var day = String(d.getDate()).padStart(2,'0');
        return y + '-' + m + '-' + day;
    }

    // Hook into renderTable to auto-update gantt
    function hookRenderTable() {
        if (typeof window.renderTable !== 'function') return;
        var orig = window.renderTable;
        window.renderTable = function() {
            orig.apply(this, arguments);
            if (ganttContainer && ganttContainer.style.display !== 'none') {
                setTimeout(renderGantt, 50);
            }
        };
    }

    // Init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { injectGanttUI(); hookRenderTable(); });
    } else {
        injectGanttUI();
        hookRenderTable();
    }
})();
