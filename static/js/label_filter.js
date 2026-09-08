// Labels 筛选分析工具
let allIssues = [];
let allLabels = [];
let selectedLabels = new Set();
let filteredIssues = [];
let currentPage = 1;
const pageSize = 20;
let charts = {};

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    initUpload();
    document.addEventListener('click', function(e) {
        const dropdown = document.getElementById('dropdownMenu');
        const toggle = document.getElementById('labelDropdownToggle');
        if (dropdown && !dropdown.contains(e.target) && !toggle.contains(e.target)) {
            dropdown.style.display = 'none';
        }
    });
});

// 初始化上传
function initUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');

    uploadArea.addEventListener('click', () => fileInput.click());
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#000';
        uploadArea.style.background = '#fafafa';
    });
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.style.borderColor = '#d0d0d0';
        uploadArea.style.background = '#fff';
    });
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#d0d0d0';
        uploadArea.style.background = '#fff';
        if (e.dataTransfer.files.length > 0) {
            handleFile(e.dataTransfer.files[0]);
        }
    });
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFile(e.target.files[0]);
        }
    });
}

// 处理文件
async function handleFile(file) {
    document.getElementById('fileName').textContent = file.name;
    document.getElementById('fileInfo').style.display = 'flex';
    document.getElementById('uploadSection').style.display = 'none';
    document.getElementById('progressSection').style.display = 'block';

    try {
        updateProgress(20, '正在读取文件...');
        const data = await readFile(file);
        updateProgress(50, '正在解析数据...');
        allIssues = parseIssues(data);
        updateProgress(80, '正在提取 Labels...');
        extractLabels();
        updateProgress(100, '分析完成');

        setTimeout(() => {
            document.getElementById('progressSection').style.display = 'none';
            document.getElementById('resultSection').style.display = 'block';
            renderLabelList();
            applyFilter();
        }, 500);
    } catch (error) {
        alert('文件解析失败: ' + error.message);
        resetUpload();
    }
}

// 读取文件
function readFile(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const data = new Uint8Array(e.target.result);
                const workbook = XLSX.read(data, { type: 'array' });
                const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
                const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1, defval: '' });
                resolve(jsonData);
            } catch (err) {
                reject(err);
            }
        };
        reader.onerror = () => reject(new Error('文件读取失败'));
        reader.readAsArrayBuffer(file);
    });
}

// 编码修复：检测并修复 UTF-8 双重编码乱码
function fixEncoding(str) {
    if (!str || typeof str !== 'string') return str;
    // 检测乱码特征字符（Latin-1 范围的特殊字符）
    const hasMojibake = /[ÃÂâäåæçèéêëìíîïðñòóôõöøùúûüýþÿ]/.test(str);
    if (!hasMojibake) return str;

    try {
        // 将乱码字符串按 Latin-1 编码回字节，再用 UTF-8 解码
        const bytes = new Uint8Array(str.length);
        for (let i = 0; i < str.length; i++) {
            bytes[i] = str.charCodeAt(i) & 0xff;
        }
        const decoder = new TextDecoder('utf-8');
        const fixed = decoder.decode(bytes);
        // 验证修复后包含中文字符才认为修复成功
        if (/[\u4e00-\u9fa5]/.test(fixed)) {
            return fixed;
        }
        return str;
    } catch (e) {
        return str;
    }
}

// 动态加载 SheetJS
if (typeof XLSX === 'undefined') {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js';
    document.head.appendChild(script);
}

// 解析问题数据
function parseIssues(data) {
    if (!data || data.length < 2) return [];

    const headers = data[0].map(h => fixEncoding(String(h).trim().toLowerCase()));
    const issues = [];

    // 自动识别字段
    const fieldMap = {
        id: findColumn(headers, ['key', 'id', '问题编号', '编号', 'issue key']),
        title: findColumn(headers, ['summary', 'title', '标题', '问题标题', 'subject']),
        module: findColumn(headers, ['component', 'module', '模块', '组件', 'components']),
        developer: findColumn(headers, ['assignee', 'developer', '负责人', '处理人', '经办人']),
        status: findColumn(headers, ['status', '状态', '问题状态']),
        severity: findColumn(headers, ['priority', 'severity', '严重级别', '优先级', '严重程度']),
        labels: findColumn(headers, ['labels', 'label', '标签', 'tag', 'tags']),
        created: findColumn(headers, ['created', 'create date', '创建时间', '创建日期']),
        resolved: findColumn(headers, ['resolved', 'resolve date', '解决时间', '解决日期', 'updated'])
    };

    for (let i = 1; i < data.length; i++) {
        const row = data[i];
        if (!row || row.length === 0) continue;

        const issue = {
            id: getValue(row, fieldMap.id, 'ISSUE-' + i),
            title: getValue(row, fieldMap.title, ''),
            module: getValue(row, fieldMap.module, ''),
            developer: getValue(row, fieldMap.developer, ''),
            status: getValue(row, fieldMap.status, ''),
            severity: getValue(row, fieldMap.severity, ''),
            labels: parseLabels(getValue(row, fieldMap.labels, '')),
            created: getValue(row, fieldMap.created, ''),
            resolved: getValue(row, fieldMap.resolved, '')
        };

        if (issue.title || issue.id !== 'ISSUE-' + i) {
            issues.push(issue);
        }
    }

    return issues;
}

function findColumn(headers, keywords) {
    for (let i = 0; i < headers.length; i++) {
        for (const kw of keywords) {
            if (headers[i] && headers[i].includes(kw.toLowerCase())) {
                return i;
            }
        }
    }
    return -1;
}

function getValue(row, index, defaultValue) {
    if (index >= 0 && index < row.length) {
        return fixEncoding(String(row[index]).trim());
    }
    return defaultValue;
}

function parseLabels(labelStr) {
    if (!labelStr) return [];
    return labelStr.split(/[,;，；\s]+/).filter(l => l.trim()).map(l => l.trim());
}

// 提取所有 Labels
function extractLabels() {
    const labelSet = new Set();
    allIssues.forEach(issue => {
        issue.labels.forEach(label => labelSet.add(label));
    });
    allLabels = Array.from(labelSet).sort();
}

// 渲染 Label 列表
function renderLabelList() {
    const list = document.getElementById('labelList');
    const searchTerm = document.getElementById('labelSearch').value.toLowerCase();
    const filtered = allLabels.filter(l => l.toLowerCase().includes(searchTerm));

    list.innerHTML = filtered.map(label => `
        <label class="dropdown-item">
            <input type="checkbox" value="${escapeHtml(label)}" ${selectedLabels.has(label) ? 'checked' : ''} onchange="toggleLabel('${escapeHtml(label)}', this.checked)">
            <span>${escapeHtml(label)}</span>
            <span style="margin-left:auto;color:#86868b;font-size:11px;">${countByLabel(label)}</span>
        </label>
    `).join('');
}

function countByLabel(label) {
    return allIssues.filter(i => i.labels.includes(label)).length;
}

// 切换下拉菜单
function toggleDropdown() {
    const menu = document.getElementById('dropdownMenu');
    const toggle = document.getElementById('labelDropdownToggle');

    if (!toggle || !menu) return;

    if (menu.style.display === 'none' || !menu.style.display) {
        // 先显示菜单以获取正确高度
        menu.style.display = 'flex';
        menu.style.visibility = 'hidden';

        // 使用 requestAnimationFrame 确保布局完成后再计算位置
        requestAnimationFrame(() => {
            const rect = toggle.getBoundingClientRect();
            const menuHeight = menu.offsetHeight || 300;

            menu.style.left = rect.left + 'px';
            menu.style.width = rect.width + 'px';

            // 计算是否需要向上展开
            const spaceBelow = window.innerHeight - rect.bottom;
            if (spaceBelow < menuHeight + 10 && rect.top > menuHeight + 10) {
                menu.style.top = (rect.top - menuHeight - 4) + 'px';
            } else {
                menu.style.top = (rect.bottom + 4) + 'px';
            }

            menu.style.visibility = 'visible';
            document.getElementById('labelSearch').focus();
        });
    } else {
        menu.style.display = 'none';
    }
}

// 窗口滚动或调整大小时重新定位下拉菜单
function repositionDropdown() {
    const menu = document.getElementById('dropdownMenu');
    const toggle = document.getElementById('labelDropdownToggle');
    if (menu && toggle && menu.style.display === 'flex') {
        const rect = toggle.getBoundingClientRect();
        menu.style.left = rect.left + 'px';
        menu.style.top = (rect.bottom + 4) + 'px';
        menu.style.width = rect.width + 'px';
    }
}

window.addEventListener('scroll', repositionDropdown, true);
window.addEventListener('resize', function() {
    const menu = document.getElementById('dropdownMenu');
    if (menu && menu.style.display === 'flex') {
        toggleDropdown();
        toggleDropdown();
    }
});

// 筛选 Labels
function filterLabels() {
    renderLabelList();
}

// 切换 Label 选中
function toggleLabel(label, checked) {
    if (checked) {
        selectedLabels.add(label);
    } else {
        selectedLabels.delete(label);
    }
    updateSelectedLabelsDisplay();
    applyFilter();
}

// 更新选中 Labels 显示
function updateSelectedLabelsDisplay() {
    const container = document.getElementById('selectedLabels');
    const text = document.getElementById('selectedLabelsText');

    if (selectedLabels.size === 0) {
        text.textContent = '选择 Labels...';
        container.innerHTML = '';
    } else {
        text.textContent = `已选 ${selectedLabels.size} 个`;
        container.innerHTML = Array.from(selectedLabels).map(label => `
            <span class="label-tag">
                ${escapeHtml(label)}
                <button onclick="removeLabel('${escapeHtml(label)}')">&times;</button>
            </span>
        `).join('');
    }
}

function removeLabel(label) {
    selectedLabels.delete(label);
    updateSelectedLabelsDisplay();
    renderLabelList();
    applyFilter();
}

// 清除筛选
function clearFilter() {
    selectedLabels.clear();
    updateSelectedLabelsDisplay();
    renderLabelList();
    applyFilter();
}

// 应用筛选
function applyFilter() {
    const mode = document.querySelector('input[name="filterMode"]:checked').value;

    if (selectedLabels.size === 0) {
        filteredIssues = [...allIssues];
    } else {
        filteredIssues = allIssues.filter(issue => {
            if (mode === 'any') {
                return issue.labels.some(l => selectedLabels.has(l));
            } else {
                return Array.from(selectedLabels).every(l => issue.labels.includes(l));
            }
        });
    }

    currentPage = 1;
    updateStats();
    updateCharts();
    updateTrendAnalysis();
    renderTable();
}

// 更新统计
function updateStats() {
    const total = filteredIssues.length;
    const resolved = filteredIssues.filter(isResolved).length;
    const unresolved = total - resolved;
    const rate = total > 0 ? Math.round((resolved / total) * 100) : 0;

    document.getElementById('statTotal').textContent = total;
    document.getElementById('statResolved').textContent = resolved;
    document.getElementById('statUnresolved').textContent = unresolved;
    document.getElementById('statRate').textContent = rate + '%';
}

function isResolved(issue) {
    const resolvedStatuses = ['resolved', 'closed', 'done', '已解决', '已关闭', '已完成', 'fixed'];
    return resolvedStatuses.some(s => issue.status.toLowerCase().includes(s));
}

// 更新图表
function updateCharts() {
    updateSeverityChart();
    updateModuleChart();
    updateDeveloperChart();
    updateStatusChart();
}

function updateSeverityChart() {
    const counts = {};
    filteredIssues.forEach(issue => {
        const sev = issue.severity || '未设置';
        counts[sev] = (counts[sev] || 0) + 1;
    });

    const labels = Object.keys(counts);
    const data = Object.values(counts);
    const colors = ['#ff3b30', '#ff9500', '#ffcc00', '#34c759', '#86868b', '#007aff', '#af52de', '#ff2d55'];

    if (charts.severity) charts.severity.destroy();
    charts.severity = new Chart(document.getElementById('severityChart'), {
        type: 'doughnut',
        data: { labels, datasets: [{ data, backgroundColor: colors.slice(0, labels.length), borderWidth: 2, borderColor: '#fff' }] },
        options: { responsive: true, maintainAspectRatio: true, plugins: { legend: { position: 'right', labels: { font: { size: 11 }, usePointStyle: true } } } }
    });
}

function updateModuleChart() {
    const counts = {};
    filteredIssues.forEach(issue => {
        const mod = issue.module || '未设置';
        counts[mod] = (counts[mod] || 0) + 1;
    });

    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
    const labels = sorted.map(s => s[0]);
    const data = sorted.map(s => s[1]);

    if (charts.module) charts.module.destroy();
    charts.module = new Chart(document.getElementById('moduleChart'), {
        type: 'bar',
        data: { labels, datasets: [{ data, backgroundColor: '#000', borderRadius: 4 }] },
        options: { responsive: true, maintainAspectRatio: true, indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { font: { size: 10 } } }, y: { ticks: { font: { size: 10 } } } } }
    });
}

function updateDeveloperChart() {
    const counts = {};
    filteredIssues.forEach(issue => {
        const dev = issue.developer || '未分配';
        counts[dev] = (counts[dev] || 0) + 1;
    });

    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
    const labels = sorted.map(s => s[0]);
    const data = sorted.map(s => s[1]);

    if (charts.developer) charts.developer.destroy();
    charts.developer = new Chart(document.getElementById('developerChart'), {
        type: 'bar',
        data: { labels, datasets: [{ data, backgroundColor: '#34c759', borderRadius: 4 }] },
        options: { responsive: true, maintainAspectRatio: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { font: { size: 10 } } }, x: { ticks: { font: { size: 10 }, maxRotation: 45 } } } }
    });
}

function updateStatusChart() {
    const counts = {};
    filteredIssues.forEach(issue => {
        const status = issue.status || '未设置';
        counts[status] = (counts[status] || 0) + 1;
    });

    const labels = Object.keys(counts);
    const data = Object.values(counts);

    if (charts.status) charts.status.destroy();
    charts.status = new Chart(document.getElementById('statusChart'), {
        type: 'pie',
        data: { labels, datasets: [{ data, backgroundColor: ['#34c759', '#ff3b30', '#ff9500', '#007aff', '#86868b', '#af52de', '#ffcc00', '#ff2d55'], borderWidth: 2, borderColor: '#fff' }] },
        options: { responsive: true, maintainAspectRatio: true, plugins: { legend: { position: 'right', labels: { font: { size: 11 }, usePointStyle: true } } } }
    });
}

// 趋势分析数据
let trendData = [];

// 解析日期
function parseDate(dateStr) {
    if (!dateStr) return null;
    
    // 支持 Excel 日期序列号（如 45292.33383101852）
    const num = Number(dateStr);
    if (!isNaN(num) && num > 20000 && num < 80000) {
        // Excel 序列号转日期：1900-01-01 为序列号 1（含1900闰年bug）
        // 转换公式：(serial - 25569) * 86400 * 1000
        const jsDate = new Date((num - 25569) * 86400 * 1000);
        if (!isNaN(jsDate.getTime())) return jsDate;
    }
    
    // 尝试多种格式
    const formats = [
        /^(\d{4})-(\d{1,2})-(\d{1,2})/,
        /^(\d{1,2})\/(\d{1,2})\/(\d{4})/,
        /^(\d{1,2})\/(\d{1,2})\/(\d{2})/,
        /^(\d{4})年(\d{1,2})月(\d{1,2})日/
    ];
    for (const fmt of formats) {
        const m = String(dateStr).match(fmt);
        if (m) {
            let y, mo, d;
            if (fmt === formats[0]) {
                y = parseInt(m[1]); mo = parseInt(m[2]); d = parseInt(m[3]);
            } else if (fmt === formats[1]) {
                mo = parseInt(m[1]); d = parseInt(m[2]); y = parseInt(m[3]);
            } else if (fmt === formats[2]) {
                mo = parseInt(m[1]); d = parseInt(m[2]); y = 2000 + parseInt(m[3]);
            } else {
                y = parseInt(m[1]); mo = parseInt(m[2]); d = parseInt(m[3]);
            }
            if (y > 2000 && mo >= 1 && mo <= 12 && d >= 1 && d <= 31) {
                return new Date(y, mo - 1, d);
            }
        }
    }
    // 尝试 Date 解析
    const d = new Date(dateStr);
    if (!isNaN(d.getTime())) return d;
    return null;
}

function formatDate(date) {
    return (date.getMonth() + 1) + '月' + date.getDate() + '日';
}

// 更新趋势分析
function updateTrendAnalysis() {
    if (filteredIssues.length === 0) {
        trendData = [];
        document.getElementById('trendTableBody').innerHTML = '<tr><td colspan="5" style="color:#86868b;padding:20px;">暂无数据</td></tr>';
        if (charts.trend) { charts.trend.destroy(); charts.trend = null; }
        return;
    }

    // 收集所有日期
    const dateSet = new Set();
    const dailyNew = {};
    const dailyResolved = {};

    filteredIssues.forEach(issue => {
        const created = parseDate(issue.created);
        if (created) {
            const key = created.toDateString();
            dateSet.add(key);
            dailyNew[key] = (dailyNew[key] || 0) + 1;
        }
        const resolved = parseDate(issue.resolved);
        if (resolved) {
            const key = resolved.toDateString();
            dateSet.add(key);
            dailyResolved[key] = (dailyResolved[key] || 0) + 1;
        }
    });

    if (dateSet.size === 0) {
        document.getElementById('trendTableBody').innerHTML = '<tr><td colspan="5" style="color:#86868b;padding:20px;">无法解析日期数据</td></tr>';
        return;
    }

    // 排序日期
    const sortedDates = Array.from(dateSet).map(d => new Date(d)).sort((a, b) => a - b);
    const startDate = sortedDates[0];
    const endDate = sortedDates[sortedDates.length - 1];

    // 生成完整日期范围
    const allDates = [];
    const current = new Date(startDate);
    while (current <= endDate) {
        allDates.push(new Date(current));
        current.setDate(current.getDate() + 1);
    }

    // 计算每日数据
    let cumulativeNew = 0;
    let cumulativeResolved = 0;
    const totalIssues = filteredIssues.length;

    trendData = allDates.map(date => {
        const key = date.toDateString();
        const newCount = dailyNew[key] || 0;
        const resolvedCount = dailyResolved[key] || 0;
        cumulativeNew += newCount;
        cumulativeResolved += resolvedCount;
        const cwv = cumulativeNew - cumulativeResolved;
        // CR fix Plan: 从总数线性下降到0的计划线
        const dayIndex = allDates.indexOf(date);
        const totalDays = allDates.length - 1;
        const plan = totalDays > 0 ? Math.round(totalIssues * (1 - dayIndex / totalDays)) : totalIssues;
        return {
            date: formatDate(date),
            cwv: cwv,
            plan: plan,
            new: newCount,
            resolved: resolvedCount
        };
    });

    // 渲染表格
    const tbody = document.getElementById('trendTableBody');
    tbody.innerHTML = trendData.map(row => `
        <tr>
            <td>${row.date}</td>
            <td class="cwv">${row.cwv}</td>
            <td class="plan">${row.plan}</td>
            <td>${row.new}</td>
            <td>${row.resolved}</td>
        </tr>
    `).join('');

    // 更新关键指标卡片
    const lastRow = trendData[trendData.length - 1];
    const totalNew = trendData.reduce((sum, r) => sum + r.new, 0);
    const totalResolved = trendData.reduce((sum, r) => sum + r.resolved, 0);
    document.getElementById('statCurrent').textContent = lastRow ? lastRow.cwv : 0;
    document.getElementById('statPlan').textContent = lastRow ? lastRow.plan : 0;
    document.getElementById('statNew').textContent = totalNew;
    document.getElementById('statTrendResolved').textContent = totalResolved;

    // 渲染折线图
    const ctx = document.getElementById('trendChart');
    if (charts.trend) charts.trend.destroy();
    charts.trend = new Chart(ctx, {
        type: 'line',
        data: {
            labels: trendData.map(d => d.date),
            datasets: [
                {
                    label: '实际未解决',
                    data: trendData.map(d => d.cwv),
                    borderColor: '#007aff',
                    backgroundColor: 'rgba(0,122,255,0.1)',
                    borderWidth: 2.5,
                    pointRadius: 4,
                    pointBackgroundColor: '#007aff',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    tension: 0.3,
                    fill: true
                },
                {
                    label: '修复计划',
                    data: trendData.map(d => d.plan),
                    borderColor: '#ff3b30',
                    backgroundColor: 'rgba(255,59,48,0.05)',
                    borderWidth: 2,
                    borderDash: [6, 4],
                    pointRadius: 3,
                    pointBackgroundColor: '#ff3b30',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 1.5,
                    tension: 0,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'bottom', labels: { font: { size: 13 }, usePointStyle: true, padding: 20 } },
                tooltip: {
                    backgroundColor: 'rgba(29,29,31,0.95)',
                    titleFont: { size: 13, weight: '600' },
                    bodyFont: { size: 12 },
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {
                        label: function(context) {
                            const label = context.dataset.label;
                            const value = context.parsed.y;
                            if (label === '实际未解决') return ` 还有 ${value} 个 Bug 未解决`;
                            if (label === '修复计划') return ` 按计划应剩余 ${value} 个`;
                            return ` ${label}: ${value}`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: { display: true, text: 'Bug 数量', font: { size: 12 } },
                    ticks: { font: { size: 11 } },
                    grid: { color: 'rgba(0,0,0,0.06)' }
                },
                x: {
                    ticks: { font: { size: 11 }, maxRotation: 45 },
                    grid: { display: false }
                }
            }
        }
    });
}

// 导出趋势 CSV
function exportTrendCSV() {
    if (trendData.length === 0) {
        alert('暂无数据可导出');
        return;
    }
    let csv = 'Date,CR CWV,CR fix Plan,NEW,Resolved\n';
    trendData.forEach(row => {
        csv += `${row.date},${row.cwv},${row.plan},${row.new},${row.resolved}\n`;
    });
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'CR趋势分析.csv';
    link.click();
}

// 渲染表格
function renderTable() {
    const tbody = document.getElementById('issueTableBody');
    const start = (currentPage - 1) * pageSize;
    const end = start + pageSize;
    const pageData = filteredIssues.slice(start, end);

    document.getElementById('tableCount').textContent = `共 ${filteredIssues.length} 条`;

    tbody.innerHTML = pageData.map(issue => `
        <tr>
            <td>${escapeHtml(issue.id)}</td>
            <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(issue.title)}">${escapeHtml(issue.title)}</td>
            <td>${escapeHtml(issue.module)}</td>
            <td>${escapeHtml(issue.developer)}</td>
            <td><span class="severity-badge severity-${getSeverityClass(issue.severity)}">${escapeHtml(issue.severity) || '-'}</span></td>
            <td class="${isResolved(issue) ? 'status-resolved' : 'status-unresolved'}">${escapeHtml(issue.status)}</td>
            <td>${issue.labels.map(l => `<span class="label-tag" style="margin:1px;">${escapeHtml(l)}</span>`).join('')}</td>
        </tr>
    `).join('');

    renderPagination();
}

function getSeverityClass(severity) {
    const s = severity.toLowerCase();
    if (s.includes('critical') || s.includes('致命') || s.includes('blocker')) return 'critical';
    if (s.includes('high') || s.includes('严重') || s.includes('major')) return 'high';
    if (s.includes('medium') || s.includes('中等') || s.includes('normal')) return 'medium';
    return 'low';
}

// 渲染分页
function renderPagination() {
    const totalPages = Math.ceil(filteredIssues.length / pageSize);
    const container = document.getElementById('pagination');

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = `<button onclick="changePage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>上一页</button>`;

    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);

    if (startPage > 1) {
        html += `<button onclick="changePage(1)">1</button>`;
        if (startPage > 2) html += `<span>...</span>`;
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `<button onclick="changePage(${i})" class="${i === currentPage ? 'active' : ''}">${i}</button>`;
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<span>...</span>`;
        html += `<button onclick="changePage(${totalPages})">${totalPages}</button>`;
    }

    html += `<button onclick="changePage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>下一页</button>`;
    container.innerHTML = html;
}

function changePage(page) {
    const totalPages = Math.ceil(filteredIssues.length / pageSize);
    if (page < 1 || page > totalPages) return;
    currentPage = page;
    renderTable();
    window.scrollTo({ top: document.querySelector('.table-container').offsetTop - 100, behavior: 'smooth' });
}

// 更新进度
function updateProgress(percent, text) {
    document.getElementById('progressFill').style.width = percent + '%';
    document.getElementById('progressText').textContent = text;
}

// 重置上传
function resetUpload() {
    allIssues = [];
    allLabels = [];
    selectedLabels.clear();
    filteredIssues = [];
    document.getElementById('fileInput').value = '';
    document.getElementById('fileInfo').style.display = 'none';
    document.getElementById('uploadSection').style.display = 'block';
    document.getElementById('progressSection').style.display = 'none';
    document.getElementById('resultSection').style.display = 'none';
    Object.values(charts).forEach(c => c && c.destroy());
    charts = {};
}

// 工具函数
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
