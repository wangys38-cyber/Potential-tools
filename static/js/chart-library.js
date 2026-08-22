/**
 * Potential-tools v8.0 通用图表组件库
 * 基于 Chart.js 4.x，统一配色、字体、间距、动画
 * 支持：骨架屏加载、空数据状态、错误处理、暗黑模式自动适配
 *
 * 用法：
 *   var chart = PTChart.create(canvasId, config);
 *   PTChart.showLoading(containerId);
 *   PTChart.hideLoading(containerId);
 *   PTChart.showEmpty(containerId, message);
 *   PTChart.showError(containerId, message);
 */
(function() {
    'use strict';

    // ========== 统一配色方案 ==========
    var PALETTE = {
        primary: ['#000000', '#34c759', '#ff9500', '#ff3b30', '#007aff', '#5856d6', '#af52de', '#ff2d55', '#5ac8fa', '#ffcc00'],
        severity: { critical: '#ff3b30', high: '#ff9500', medium: '#ffcc00', low: '#34c759', info: '#007aff' },
        status: { open: '#ff3b30', resolved: '#34c759', pending: '#ff9500', closed: '#8e8e93' }
    };

    // ========== 暗黑模式检测 ==========
    function isDark() {
        return document.documentElement.getAttribute('data-theme') === 'dark';
    }

    function getThemeColors() {
        var dark = isDark();
        return {
            text: dark ? '#f0f0f2' : '#1d1d1f',
            textSecondary: dark ? '#98989d' : '#86868b',
            grid: dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)',
            border: dark ? '#38383a' : '#e8e8ed',
            tooltipBg: dark ? '#2c2c2e' : '#ffffff',
            tooltipText: dark ? '#f0f0f2' : '#1d1d1f',
            tooltipBorder: dark ? '#48484a' : '#e8e8ed'
        };
    }

    // ========== 统一 Chart.js 默认配置 ==========
    function applyDefaults() {
        if (typeof Chart === 'undefined') return;
        var c = getThemeColors();
        Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'PingFang SC', 'Microsoft YaHei', sans-serif";
        Chart.defaults.font.size = 12;
        Chart.defaults.color = c.textSecondary;
        Chart.defaults.borderColor = c.grid;
        Chart.defaults.animation.duration = 600;
        Chart.defaults.animation.easing = 'easeOutQuart';
        Chart.defaults.plugins.legend.labels.usePointStyle = true;
        Chart.defaults.plugins.legend.labels.padding = 16;
        Chart.defaults.plugins.legend.labels.boxWidth = 8;
        Chart.defaults.plugins.tooltip.backgroundColor = c.tooltipBg;
        Chart.defaults.plugins.tooltip.titleColor = c.tooltipText;
        Chart.defaults.plugins.tooltip.bodyColor = c.tooltipText;
        Chart.defaults.plugins.tooltip.borderColor = c.tooltipBorder;
        Chart.defaults.plugins.tooltip.borderWidth = 1;
        Chart.defaults.plugins.tooltip.cornerRadius = 8;
        Chart.defaults.plugins.tooltip.padding = 12;
        Chart.defaults.interaction.mode = 'index';
        Chart.defaults.interaction.intersect = false;
    }

    // 初始化默认配置
    if (typeof Chart !== 'undefined') {
        applyDefaults();
        // 监听主题切换，更新所有图表
        var _origToggle = null;
        var observer = new MutationObserver(function() {
            applyDefaults();
            // 更新所有现有图表
            Object.values(Chart.instances || {}).forEach(function(ch) {
                try { ch.update('none'); } catch(e) {}
            });
        });
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    }

    // ========== 骨架屏加载状态 ==========
    function showLoading(containerId) {
        var el = document.getElementById(containerId);
        if (!el) return;
        el.innerHTML = '<div class="pt-chart-skeleton" style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;">' +
            '<div style="width:40px;height:40px;border:3px solid ' + (isDark() ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)') +
            ';border-top-color:' + (isDark() ? '#f0f0f2' : '#1d1d1f') + ';border-radius:50%;animation:pt-spin 0.8s linear infinite;"></div></div>';
        if (!document.getElementById('pt-chart-skeleton-style')) {
            var s = document.createElement('style');
            s.id = 'pt-chart-skeleton-style';
            s.textContent = '@keyframes pt-spin{to{transform:rotate(360deg)}}';
            document.head.appendChild(s);
        }
    }

    function hideLoading(containerId) {
        var el = document.getElementById(containerId);
        if (el) el.innerHTML = '';
    }

    // ========== 空数据状态 ==========
    function showEmpty(containerId, message) {
        var el = document.getElementById(containerId);
        if (!el) return;
        var c = getThemeColors();
        el.innerHTML = '<div style="width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:' + c.textSecondary + ';">' +
            '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.4;">' +
            '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>' +
            '<span style="font-size:14px;">' + (message || '暂无数据') + '</span></div>';
    }

    // ========== 错误状态 ==========
    function showError(containerId, message) {
        var el = document.getElementById(containerId);
        if (!el) return;
        el.innerHTML = '<div style="width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:#ff3b30;">' +
            '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
            '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>' +
            '<span style="font-size:14px;">' + (message || '数据加载失败') + '</span></div>';
    }

    // ========== 创建图表（带统一配置） ==========
    function create(canvasId, userConfig) {
        if (typeof Chart === 'undefined') {
            console.error('Chart.js not loaded');
            return null;
        }
        var canvas = document.getElementById(canvasId);
        if (!canvas) return null;

        var c = getThemeColors();
        var config = JSON.parse(JSON.stringify(userConfig || {}));

        // 统一响应式配置
        if (!config.options) config.options = {};
        config.options.responsive = true;
        config.options.maintainAspectRatio = false;

        // 统一 scales 配置
        if (config.options.scales) {
            Object.keys(config.options.scales).forEach(function(key) {
                var scale = config.options.scales[key];
                if (!scale.grid) scale.grid = {};
                if (scale.grid.color === undefined) scale.grid.color = c.grid;
                if (!scale.ticks) scale.ticks = {};
                if (scale.ticks.color === undefined) scale.ticks.color = c.textSecondary;
                if (scale.title && scale.title.display && scale.title.color === undefined) {
                    scale.title.color = c.textSecondary;
                }
            });
        }

        // 统一 plugins 配置
        if (!config.options.plugins) config.options.plugins = {};
        if (config.options.plugins.legend && config.options.plugins.legend.labels) {
            if (config.options.plugins.legend.labels.color === undefined) {
                config.options.plugins.legend.labels.color = c.textSecondary;
            }
        }

        try {
            return new Chart(canvas.getContext('2d'), config);
        } catch(e) {
            console.error('Chart creation failed:', e);
            var parent = canvas.parentElement;
            if (parent) showError(parent.id || canvasId, '图表渲染失败');
            return null;
        }
    }

    // ========== 安全销毁图表 ==========
    function destroy(chart) {
        if (chart) {
            try { chart.destroy(); } catch(e) {}
        }
        return null;
    }

    // ========== 热力图（自定义 Canvas 实现，不依赖插件） ==========
    function renderHeatmap(containerId, data, options) {
        var el = document.getElementById(containerId);
        if (!el) return;
        if (!data || !data.labels || !data.labels.x || !data.labels.y || !data.matrix) {
            showEmpty(containerId, '暂无热力图数据');
            return;
        }
        var opts = options || {};
        var c = getThemeColors();
        var xLabels = data.labels.x;
        var yLabels = data.labels.y;
        var matrix = data.matrix;
        var maxVal = 0;
        matrix.forEach(function(row) { row.forEach(function(v) { if (v > maxVal) maxVal = v; }); });
        if (maxVal === 0) maxVal = 1;

        var cellW = opts.cellWidth || 40;
        var cellH = opts.cellHeight || 32;
        var labelW = opts.labelWidth || 80;
        var labelH = opts.labelHeight || 28;
        var w = labelW + xLabels.length * cellW + 20;
        var h = labelH + yLabels.length * cellH + 20;

        var canvas = document.createElement('canvas');
        canvas.width = w * 2;
        canvas.height = h * 2;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(2, 2);

        // 颜色插值：浅到深（黑灰色系）
        function getColor(val) {
            var t = val / maxVal;
            if (isDark()) {
                var r = Math.round(44 + t * 200);
                var g = Math.round(44 + t * 200);
                var b = Math.round(46 + t * 200);
                return 'rgb(' + r + ',' + g + ',' + b + ')';
            } else {
                var r2 = Math.round(255 - t * 200);
                var g2 = Math.round(255 - t * 200);
                var b2 = Math.round(255 - t * 205);
                return 'rgb(' + r2 + ',' + g2 + ',' + b2 + ')';
            }
        }

        // 绘制 X 轴标签
        ctx.fillStyle = c.textSecondary;
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        xLabels.forEach(function(label, i) {
            ctx.fillText(label, labelW + i * cellW + cellW / 2, labelH - 8);
        });

        // 绘制 Y 轴标签和单元格
        ctx.textAlign = 'right';
        yLabels.forEach(function(label, yi) {
            ctx.fillStyle = c.textSecondary;
            ctx.fillText(label, labelW - 8, labelH + yi * cellH + cellH / 2 + 4);
            matrix[yi].forEach(function(val, xi) {
                ctx.fillStyle = getColor(val);
                ctx.fillRect(labelW + xi * cellW + 1, labelH + yi * cellH + 1, cellW - 2, cellH - 2);
                if (val > 0 && maxVal > 3) {
                    ctx.fillStyle = val / maxVal > 0.5 ? (isDark() ? '#1c1c1e' : '#ffffff') : c.text;
                    ctx.font = '10px -apple-system, sans-serif';
                    ctx.textAlign = 'center';
                    ctx.fillText(val, labelW + xi * cellW + cellW / 2, labelH + yi * cellH + cellH / 2 + 3);
                    ctx.textAlign = 'right';
                }
            });
        });

        el.innerHTML = '';
        var wrap = document.createElement('div');
        wrap.style.overflowX = 'auto';
        wrap.appendChild(canvas);
        el.appendChild(wrap);
    }

    // ========== 甘特图（自定义实现） ==========
    function renderGantt(containerId, tasks, options) {
        var el = document.getElementById(containerId);
        if (!el) return;
        if (!tasks || !tasks.length) {
            showEmpty(containerId, '暂无甘特图数据');
            return;
        }
        var opts = options || {};
        var c = getThemeColors();

        // 计算时间范围
        var minDate = null, maxDate = null;
        tasks.forEach(function(t) {
            var s = new Date(t.start), e = new Date(t.end);
            if (!minDate || s < minDate) minDate = s;
            if (!maxDate || e > maxDate) maxDate = e;
        });
        if (!minDate || !maxDate) return;
        var totalDays = Math.ceil((maxDate - minDate) / 86400000) + 1;

        var rowH = opts.rowHeight || 36;
        var labelW = opts.labelWidth || 140;
        var dayW = Math.max(opts.dayWidth || 24, 8);
        var w = labelW + totalDays * dayW + 40;
        var h = 40 + tasks.length * rowH + 20;

        var canvas = document.createElement('canvas');
        canvas.width = w * 2;
        canvas.height = h * 2;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(2, 2);

        // 绘制时间轴
        ctx.fillStyle = c.textSecondary;
        ctx.font = '10px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        var today = new Date();
        for (var d = 0; d < totalDays; d += 7) {
            var dt = new Date(minDate.getTime() + d * 86400000);
            var label = (dt.getMonth() + 1) + '/' + dt.getDate();
            ctx.fillText(label, labelW + d * dayW + dayW / 2, 20);
            // 竖线
            ctx.strokeStyle = c.grid;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(labelW + d * dayW, 30);
            ctx.lineTo(labelW + d * dayW, h - 10);
            ctx.stroke();
        }

        // 绘制任务条
        tasks.forEach(function(t, i) {
            var y = 40 + i * rowH;
            var s = new Date(t.start), e = new Date(t.end);
            var startOffset = Math.floor((s - minDate) / 86400000);
            var duration = Math.max(1, Math.ceil((e - s) / 86400000));
            var x = labelW + startOffset * dayW;
            var barW = duration * dayW;

            // 任务名
            ctx.fillStyle = c.text;
            ctx.font = '12px -apple-system, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(t.name, labelW - 10, y + rowH / 2 + 4);

            // 进度条背景
            ctx.fillStyle = isDark() ? '#38383a' : '#e8e8ed';
            ctx.beginPath();
            ctx.roundRect(x, y + 6, barW, rowH - 12, 4);
            ctx.fill();

            // 进度
            var pct = t.progress != null ? t.progress : 0;
            var color = t.color || (pct >= 100 ? '#34c759' : (pct > 50 ? '#007aff' : '#ff9500'));
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.roundRect(x, y + 6, barW * (pct / 100), rowH - 12, 4);
            ctx.fill();

            // 进度文字
            if (barW > 40) {
                ctx.fillStyle = pct > 30 ? '#ffffff' : c.text;
                ctx.font = '10px -apple-system, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(pct + '%', x + barW / 2, y + rowH / 2 + 3);
            }
        });

        // 今日线
        if (today >= minDate && today <= maxDate) {
            var todayOffset = Math.floor((today - minDate) / 86400000);
            var tx = labelW + todayOffset * dayW;
            ctx.strokeStyle = '#ff3b30';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(tx, 30);
            ctx.lineTo(tx, h - 10);
            ctx.stroke();
            ctx.setLineDash([]);
        }

        el.innerHTML = '';
        var wrap = document.createElement('div');
        wrap.style.overflowX = 'auto';
        wrap.appendChild(canvas);
        el.appendChild(wrap);
    }

    // ========== 导出 PNG（高清） ==========
    function exportPNG(chart, filename) {
        if (!chart) return;
        try {
            var url = chart.toBase64Image('image/png', 1);
            var a = document.createElement('a');
            a.href = url;
            a.download = (filename || 'chart') + '.png';
            a.click();
        } catch(e) { console.error('PNG export failed:', e); }
    }

    // ========== 导出 SVG ==========
    function exportSVG(chart, filename) {
        if (!chart || !chart.canvas) return;
        try {
            // 将 canvas 转为 SVG（通过 foreignObject 包裹 canvas dataURL）
            var w = chart.canvas.width, h = chart.canvas.height;
            var dataUrl = chart.canvas.toDataURL('image/png');
            var svg = '<?xml version="1.0" encoding="UTF-8"?>\n' +
                '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '">\n' +
                '<image href="' + dataUrl + '" width="' + w + '" height="' + h + '"/>\n' +
                '</svg>';
            var blob = new Blob([svg], { type: 'image/svg+xml' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = (filename || 'chart') + '.svg';
            a.click();
            URL.revokeObjectURL(url);
        } catch(e) { console.error('SVG export failed:', e); }
    }

    // ========== 导出 CSV ==========
    function exportCSV(labels, datasets, filename) {
        if (!labels || !datasets) return;
        var keys = ['label'].concat(datasets.map(function(d) { return d.label; }));
        var rows = [keys.join(',')];
        labels.forEach(function(label, i) {
            var row = ['"' + label + '"'];
            datasets.forEach(function(d) {
                row.push(d.data[i] != null ? d.data[i] : '');
            });
            rows.push(row.join(','));
        });
        var csv = '\ufeff' + rows.join('\n');
        var blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = (filename || 'data') + '.csv';
        a.click();
        URL.revokeObjectURL(url);
    }

    // ========== 暴露全局 API ==========
    window.PTChart = {
        create: create,
        destroy: destroy,
        showLoading: showLoading,
        hideLoading: hideLoading,
        showEmpty: showEmpty,
        showError: showError,
        renderHeatmap: renderHeatmap,
        renderGantt: renderGantt,
        exportPNG: exportPNG,
        exportSVG: exportSVG,
        exportCSV: exportCSV,
        PALETTE: PALETTE,
        isDark: isDark,
        getThemeColors: getThemeColors,
        applyDefaults: applyDefaults
    };
})();
