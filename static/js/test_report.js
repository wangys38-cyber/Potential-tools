let currentFileId = null;
        let currentFileName = null;
        let currentSheetName = null;
        let currentAnalysis = null;
        let loadingStepInterval = null;
        let currentUser = null;

        const fileInput = document.getElementById('fileInput');
        const uploadCard = document.getElementById('uploadCard');
        const uploadSection = document.getElementById('uploadSection');
        const sheetSection = document.getElementById('sheetSection');
        const sheetInfo = document.getElementById('sheetInfo');
        const resultSection = document.getElementById('resultSection');
        const loadingIndicator = document.getElementById('loadingIndicator');

        function showToast(msg, type) {
            if (typeof ToolboxToast !== 'undefined') {
                ToolboxToast.show(msg, type || 'info');
            } else {
                console.log(msg);
            }
        }

        // 上传区域拖拽
        uploadCard.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadCard.classList.add('dragover');
        });
        uploadCard.addEventListener('dragleave', () => uploadCard.classList.remove('dragover'));
        uploadCard.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadCard.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) {
                handleFile(e.dataTransfer.files[0]);
            }
        });

        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                handleFile(e.target.files[0]);
            }
        });

        async function handleFile(file) {
            if (!file.name.match(/\.(xlsx|xls)$/i)) {
                showToast('请选择Excel文件 (.xlsx, .xls)', 'info');
                return;
            }

            // 使用统一上传组件 ToolboxUpload.directUpload（带进度条）
            var progressContainer = document.createElement('div');
            progressContainer.id = 'tbUploadProgress';
            progressContainer.style.margin = '12px 0';
            uploadCard.parentNode.insertBefore(progressContainer, uploadCard.nextSibling);

            try {
                var data = await ToolboxUpload.directUpload(file, '/api/test-report-analyze', {
                    fieldName: 'file',
                    accept: '.xlsx,.xls',
                    progressContainer: progressContainer,
                    onProgress: function(loaded, total) {
                        // 进度条由组件内部渲染，此处可扩展
                    }
                });

                if (data.status === 'success') {
                    currentFileId = data.data.file_id;
                    currentFileName = data.data.file_basename || data.data.file_name || 'test_report';
                    loadingIndicator.classList.remove('show');
                    if (progressContainer.parentNode) progressContainer.parentNode.removeChild(progressContainer);
                    showSheetSelector(data.data);
                } else {
                    showToast('上传失败: ' + (data.error || '未知错误'), 'error');
                    showLoading(false);
                    uploadSection.classList.remove('hidden');
                }
            } catch (err) {
                showToast('请求失败: ' + err.message, 'error');
                showLoading(false);
                uploadSection.classList.remove('hidden');
            }
        }

        function showSheetSelector(data) {
            uploadSection.classList.add('hidden');
            sheetSection.classList.remove('hidden');
            resultSection.classList.add('hidden');

            sheetInfo.innerHTML = `
                <div class="file-icon"></div>
                <div class="file-details">
                    <div class="file-name">${escapeHtml(data.file_name)}</div>
                    <div class="file-meta">共 ${data.sheet_count} 个Sheet，请选择要分析的Sheet页</div>
                </div>
            `;

            const tabsContainer = document.getElementById('sheetTabs');
            tabsContainer.innerHTML = '';

            data.sheet_names.forEach((name) => {
                const tab = document.createElement('div');
                tab.className = 'sheet-tab';
                tab.textContent = name;
                tab.onclick = () => selectSheet(name);
                tabsContainer.appendChild(tab);
            });
        }

        async function selectSheet(sheetName) {
            currentSheetName = sheetName;

            document.querySelectorAll('.sheet-tab').forEach(tab => {
                tab.classList.toggle('active', tab.textContent === sheetName);
            });

            showLoading(true, '正在启动分析任务');

            try {
                const response = await fetch('/api/test-report-analyze-sheet', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        file_id: currentFileId,
                        sheet_name: sheetName
                    })
                });
                const data = await response.json();

                if (data.status !== 'success') {
                    throw new Error(data.error || '启动分析失败');
                }

                const taskId = data.data.task_id;
                startLoadingSteps();

                let pollCount = 0;
                const maxPolls = 600; // 15分钟（大文件需要更长时间）
                while (pollCount < maxPolls) {
                    await new Promise(r => setTimeout(r, 1500));
                    const statusResp = await fetch('/api/task-status', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_id: taskId })
                    });
                    const statusResult = await statusResp.json();

                    if (statusResult.status === 'done') {
                        currentAnalysis = statusResult.data;
                        stopLoadingSteps();
                        displayResults(statusResult.data);
                        return;
                    } else if (statusResult.status === 'error') {
                        throw new Error(statusResult.error || '分析失败');
                    }
                    // 显示服务器返回的进度
                    if (statusResult.progress_msg) {
                        const loadingText = document.querySelector('.loading-text, .loading-message, [class*="loading"] p');
                        if (loadingText) loadingText.textContent = statusResult.progress_msg;
                    }
                    pollCount++;
                }
                throw new Error('分析超时（超过15分钟），请重试或减少数据量');
            } catch (err) {
                stopLoadingSteps();
                showToast('分析失败: ' + (err.message || '未知错误'), 'error');
                showLoading(false);
                sheetSection.classList.remove('hidden');
            }
        }

        function startLoadingSteps() {
            const steps = document.querySelectorAll('.loading-step');
            let currentStep = 0;
            steps[0].classList.add('active');
            updateLoadingText('正在读取Excel文件...');

            loadingStepInterval = setInterval(() => {
                if (currentStep < steps.length - 1) {
                    steps[currentStep].classList.remove('active');
                    steps[currentStep].classList.add('done');
                    currentStep++;
                    steps[currentStep].classList.add('active');
                    updateLoadingTextByStep(currentStep);
                }
            }, 5000);

            // Progress bar animation
            let progress = 0;
            const progressInterval = setInterval(() => {
                progress = Math.min(progress + 2, 90);
                document.getElementById('loadingProgressFill').style.width = progress + '%';
                if (progress >= 90) clearInterval(progressInterval);
            }, 300);
        }

        function stopLoadingSteps() {
            if (loadingStepInterval) {
                clearInterval(loadingStepInterval);
                loadingStepInterval = null;
            }
            document.getElementById('loadingProgressFill').style.width = '100%';
            document.querySelectorAll('.loading-step').forEach(s => {
                s.classList.remove('active');
                s.classList.add('done');
            });
        }

        function updateLoadingText(text) {
            document.getElementById('loadingText').textContent = text;
        }

        function updateLoadingTextByStep(step) {
            const texts = [
                '正在读取Excel文件...',
                '正在识别测试项数据...',
                '正在进行分类与风险评估...',
                '正在生成智能分析报告...'
            ];
            const subtexts = [
                '解析Sheet中的行列数据',
                '提取测试项名称、模块、结果等信息',
                '按功能领域分类，评估各模块风险等级',
                '汇总关键发现和改进建议'
            ];
            if (texts[step]) updateLoadingText(texts[step]);
            if (subtexts[step]) document.getElementById('loadingSubtext').textContent = subtexts[step];
        }

        function displayResults(data) {
            sheetSection.classList.add('hidden');
            resultSection.classList.remove('hidden');
            loadingIndicator.classList.remove('show');

            renderProjectInfo(data.project_info);
            renderStats(data.stats);
            renderSummary(data);
            renderAnalysisSections(data.analysis);
            renderKeyFindings(data.analysis);
            renderRecommendations(data.analysis);
            renderTestItems(data.test_items);
        }

        function renderProjectInfo(info) {
            const grid = document.getElementById('infoGrid');
            grid.innerHTML = '';
            if (!info || Object.keys(info).length === 0) {
                grid.innerHTML = '<div style="color:var(--text-tertiary);">未识别到项目信息</div>';
                return;
            }
            Object.entries(info).forEach(([label, value]) => {
                const item = document.createElement('div');
                item.className = 'info-item';
                item.innerHTML = `<div class="label">${escapeHtml(label)}</div><div class="value">${escapeHtml(value)}</div>`;
                grid.appendChild(item);
            });
        }

        function renderStats(stats) {
            const grid = document.getElementById('statsGrid');
            grid.innerHTML = '';
            const total = stats.total || 0;
            const pass = stats.pass || 0;
            const fail = stats.fail || 0;
            const blocked = stats.blocked || 0;
            const delayed = stats.delayed || 0;
            const unknown = stats.unknown || 0;
            const executed = stats.executed || 0;
            const passRate = stats.pass_rate || '0%';
            const executedPassRate = stats.executed_pass_rate || '0%';

            const items = [
                { key: 'total', label: '总测试项', value: total, cls: 'total' },
                { key: 'executed', label: '已执行', value: executed, cls: 'total' },
                { key: 'pass', label: '通过', value: pass, cls: 'pass' },
                { key: 'fail', label: '不通过', value: fail, cls: 'fail' },
            ];
            if (blocked > 0) items.push({ key: 'blocked', label: '阻塞', value: blocked, cls: 'critical' });
            if (delayed > 0) items.push({ key: 'delayed', label: '已延期', value: delayed, cls: 'major' });
            if (unknown > 0) items.push({ key: 'unknown', label: '未识别', value: unknown, cls: 'trivial' });
            items.push({ key: 'rate', label: '通过率', value: passRate, cls: 'rate' });
            if (executed < total && executed > 0) {
                items.push({ key: 'exec_rate', label: '已执行通过率', value: executedPassRate, cls: 'rate' });
            }

            const severity = stats.severity || {};
            const severityLabels = { blocker: 'Blocker', critical: 'Critical', major: 'Major', minor: 'Minor', trivial: 'Trivial' };
            ['blocker', 'critical', 'major', 'minor', 'trivial'].forEach(level => {
                if (severity[level]) {
                    items.push({ key: level, label: severityLabels[level], value: severity[level], cls: level });
                }
            });

            items.forEach(item => {
                const card = document.createElement('div');
                card.className = 'stat-card ' + item.cls;
                card.innerHTML = `<div class="number">${item.value}</div><div class="label">${item.label}</div>`;
                grid.appendChild(card);
            });
        }

        function renderSummary(data) {
            const banner = document.getElementById('summaryBanner');
            const riskContainer = document.getElementById('riskBannerContainer');
            const stats = data.stats;
            const total = stats.total || 0;
            const analysis = data.analysis || {};

            if (total === 0) {
                riskContainer.innerHTML = '';
                banner.innerHTML = `<h4> 分析总结</h4><p>未找到测试项数据，请检查Excel文件格式是否正确。</p>`;
                return;
            }

            const overallRisk = analysis.overall_risk || '无';
            const riskClassMap = { '高': 'high', '中': 'medium', '低': 'low', '无': 'none' };
            const riskIconMap = { '高': '', '中': '', '低': '', '无': '' };
            const riskCls = riskClassMap[overallRisk] || 'none';
            riskContainer.innerHTML = `<div class="risk-banner ${riskCls}">${riskIconMap[overallRisk] || ''} 整体风险等级：${overallRisk}</div>`;

            const execSummary = analysis.executive_summary || '';
            banner.innerHTML = `<h4> 执行摘要</h4><p>${escapeHtml(execSummary)}</p>`;
        }

        function renderAnalysisSections(analysis) {
            const container = document.getElementById('analysisSections');
            container.innerHTML = '';
            if (!analysis || !analysis.sections || analysis.sections.length === 0) {
                container.innerHTML = '<div style="color:var(--text-tertiary);text-align:center;padding:20px;">无分类分析数据</div>';
                return;
            }
            const riskClassMap = { '高': 'high', '中': 'medium', '低': 'low', '无': 'none' };

            analysis.sections.forEach((section) => {
                const riskCls = riskClassMap[section.risk_level] || 'none';
                const sectionDiv = document.createElement('div');
                sectionDiv.className = 'analysis-section';

                let statsText = `通过率 ${section.pass_rate}`;
                if (section.fail > 0) statsText += ` · 不通过 ${section.fail}`;
                if (section.delayed > 0) statsText += ` · 延期 ${section.delayed}`;
                if (section.blocked > 0) statsText += ` · 阻塞 ${section.blocked}`;

                let bodyHtml = `<div class="analysis-section-summary">${escapeHtml(section.summary)}</div>`;
                if (section.problem_items && section.problem_items.length > 0) {
                    bodyHtml += '<ul class="problem-item-list">';
                    section.problem_items.forEach(pi => {
                        const statusLabel = getStatusLabel(pi.result);
                        const targetDisplay = formatValue(pi.target);
                        const actualDisplay = formatValue(pi.actual);
                        bodyHtml += `<li>
                            <span class="result-badge ${pi.result}" style="flex-shrink:0;">${statusLabel}</span>
                            <div style="flex:1;">
                                <div class="problem-item-name">${escapeHtml(pi.name)}</div>
                                ${pi.reason ? `<div class="problem-item-reason">${renderReason(pi.reason, true)}</div>` : ''}
                                <div class="problem-item-target">目标: ${targetDisplay} | 实测: ${actualDisplay}</div>
                            </div>
                        </li>`;
                    });
                    bodyHtml += '</ul>';
                } else if (section.pass === section.total) {
                    bodyHtml += '<div style="color:var(--success);font-size:13px;padding:8px 0;">✓ 全部通过</div>';
                }

                sectionDiv.innerHTML = `
                    <div class="analysis-section-header" onclick="this.nextElementSibling.classList.toggle('show')">
                        <div class="section-title">
                            <span class="risk-badge ${riskCls}">${section.risk_level}</span>
                            ${escapeHtml(section.category)}
                        </div>
                        <div class="section-stats">
                            <span>${statsText}</span>
                            <span style="color:var(--text-tertiary);">共 ${section.total} 项</span>
                        </div>
                    </div>
                    <div class="analysis-section-body">${bodyHtml}</div>
                `;

                if (section.risk_level === '高') {
                    sectionDiv.querySelector('.analysis-section-body').classList.add('show');
                }
                container.appendChild(sectionDiv);
            });
        }

        function renderKeyFindings(analysis) {
            const container = document.getElementById('keyFindings');
            container.innerHTML = '';
            if (!analysis || !analysis.key_findings || analysis.key_findings.length === 0) {
                container.innerHTML = '<div style="color:var(--text-tertiary);text-align:center;padding:20px;">无关键发现</div>';
                return;
            }
            analysis.key_findings.forEach(finding => {
                const item = document.createElement('div');
                let cls = 'info';
                if (finding.includes('【高风险】')) cls = 'high';
                else if (finding.includes('【中风险】')) cls = 'medium';
                else if (finding.includes('【达标项】')) cls = 'success';
                item.className = 'finding-item ' + cls;
                item.textContent = finding;
                container.appendChild(item);
            });
        }

        function renderRecommendations(analysis) {
            const container = document.getElementById('recommendations');
            container.innerHTML = '';
            if (!analysis || !analysis.recommendations || analysis.recommendations.length === 0) {
                container.innerHTML = '<div style="color:var(--text-tertiary);text-align:center;padding:20px;">暂无建议</div>';
                return;
            }
            analysis.recommendations.forEach(rec => {
                const item = document.createElement('div');
                item.className = 'recommendation-item';
                item.textContent = rec;
                container.appendChild(item);
            });
        }

        function getStatusLabel(result) {
            const labels = { 'pass': '通过', 'fail': '不通过', 'blocked': '阻塞', 'delayed': '已延期', 'n_a': '不适用', 'unknown': '未识别' };
            return labels[result] || result;
        }

        function formatValue(val) {
            if (!val || val === '' || val === '-' || val === 'None' || val === 'null') return '未设置';
            const s = String(val).trim();
            // 已带百分号，直接返回
            if (s.includes('%')) return s;
            // 纯数字判断
            const num = parseFloat(s.replace(/[>=≤<≥~≈约]/g, '').trim());
            if (!isNaN(num)) {
                // 1 或 1.0 → 100%（测试指标中1代表100%）
                if (num === 1) return '100%';
                // 0~1 之间的小数 → 百分比 (0.7027 → 70.27%)
                if (num > 0 && num < 1) return (num * 100).toFixed(2) + '%';
                // 大于1的数，如果像是百分比形式(如 90, 95)也加上%
                if (num >= 1 && num <= 100 && !s.includes('.') && s.length <= 3) return num + '%';
                // 其他数值原样返回
                return s;
            }
            return s;
        }

        function renderTestItems(items) {
            const container = document.getElementById('tableContainer');
            if (!items || items.length === 0) {
                container.innerHTML = `<div class="empty-state"><div class="icon"></div><p>未找到测试项数据</p><p style="font-size:12px;margin-top:8px;">请确保Excel文件包含测试项表格</p></div>`;
                return;
            }

            const resultOrder = { 'fail': 0, 'delayed': 1, 'blocked': 2, 'unknown': 3, 'n_a': 4, 'pass': 5 };
            const sorted = [...items].sort((a, b) => {
                const orderA = resultOrder[a.result] !== undefined ? resultOrder[a.result] : 3;
                const orderB = resultOrder[b.result] !== undefined ? resultOrder[b.result] : 3;
                if (orderA !== orderB) return orderA - orderB;
                if (a.result === 'fail' && b.result === 'fail') {
                    const severityOrder = { blocker: 0, critical: 1, major: 2, minor: 3, trivial: 4 };
                    return severityOrder[getSeverityLevel(a.severity)] - severityOrder[getSeverityLevel(b.severity)];
                }
                return 0;
            });

            let html = `<div class="table-wrapper"><table class="test-items-table"><thead><tr>
                <th style="width:50px;">#</th><th>测试项</th><th>模块</th><th>结果</th><th>目标</th><th>实测</th><th>原因/备注</th>
            </tr></thead><tbody>`;

            sorted.forEach((item, idx) => {
                const resultBadge = getResultBadge(item);
                const reason = item.reason || '';
                const isProblem = item.result === 'fail' || item.result === 'delayed' || item.result === 'blocked';
                const targetDisplay = formatValue(item.target);
                const actualDisplay = formatValue(item.actual);
                const actualColor = isProblem ? 'var(--danger)' : (item.result === 'pass' ? 'var(--success)' : 'var(--accent)');
                html += `<tr>
                    <td style="color:var(--text-tertiary);">${idx + 1}</td>
                    <td><span class="test-item-name">${escapeHtml(item.name)}</span></td>
                    <td><span class="test-item-module">${escapeHtml(item.module) || '-'}</span></td>
                    <td>${resultBadge}</td>
                    <td style="font-size:13px;color:var(--text-secondary);white-space:nowrap;">${escapeHtml(targetDisplay)}</td>
                    <td style="font-size:13px;font-weight:600;color:${actualColor};white-space:nowrap;">${escapeHtml(actualDisplay)}</td>
                    <td style="max-width:400px;">${renderReason(reason, isProblem)}</td>
                </tr>`;
            });

            html += '</tbody></table></div>';
            container.innerHTML = html;
        }

        function getResultBadge(item) {
            const result = item.result || 'unknown';
            const statusLabels = { 'pass': '通过', 'fail': '不通过', 'blocked': '阻塞', 'delayed': '已延期', 'n_a': '不适用', 'unknown': '未识别' };
            const label = statusLabels[result] || item.result_text || result;
            if (['pass', 'fail', 'blocked', 'delayed', 'n_a'].includes(result)) {
                return `<span class="result-badge ${result}">${label}</span>`;
            }
            return `<span class="result-badge unknown">${escapeHtml(item.result_text || label)}</span>`;
        }

        function getSeverityTag(severity) {
            if (!severity) return '<span style="color:var(--text-tertiary);">-</span>';
            const cls = getSeverityClass(severity);
            const label = severity.charAt(0).toUpperCase() + severity.slice(1);
            return `<span class="severity-tag ${cls}">${escapeHtml(label)}</span>`;
        }

        function getSeverityClass(severity) {
            if (!severity) return '';
            const sev = severity.toLowerCase();
            if (sev.includes('blocker')) return 'blocker';
            if (sev.includes('critical')) return 'critical';
            if (sev.includes('major')) return 'major';
            if (sev.includes('minor')) return 'minor';
            if (sev.includes('trivial')) return 'trivial';
            return '';
        }

        function getSeverityLevel(severity) {
            if (!severity) return 'trivial';
            const sev = severity.toLowerCase();
            if (sev.includes('blocker')) return 'blocker';
            if (sev.includes('critical')) return 'critical';
            if (sev.includes('major')) return 'major';
            if (sev.includes('minor')) return 'minor';
            if (sev.includes('trivial')) return 'trivial';
            return 'trivial';
        }

        function showLoading(show, text) {
            if (show) {
                loadingIndicator.classList.add('show');
                uploadSection.classList.add('hidden');
                sheetSection.classList.add('hidden');
                resultSection.classList.add('hidden');
                if (text) updateLoadingText(text);
                document.getElementById('loadingProgressFill').style.width = '0%';
                document.querySelectorAll('.loading-step').forEach(s => {
                    s.classList.remove('active', 'done');
                });
            } else {
                loadingIndicator.classList.remove('show');
                stopLoadingSteps();
            }
        }

        function resetAll() {
            currentFileId = null;
            currentFileName = null;
            currentSheetName = null;
            currentAnalysis = null;
            fileInput.value = '';
            uploadSection.classList.remove('hidden');
            sheetSection.classList.add('hidden');
            resultSection.classList.add('hidden');
        }

        // v3.0: AI 深度分析（SSE 流式）
        async function generateAIAnalysis() {
            if (!currentAnalysis) {
                showToast('请先完成测试报告分析', 'info');
                return;
            }

            const btn = document.getElementById('aiAnalysisBtn');
            const content = document.getElementById('aiAnalysisContent');
            if (btn) btn.style.display = 'none';

            // 流式渲染容器
            content.innerHTML = `
                <div id="aiStreamArea" style="line-height: 1.8; font-size: 14px; color: var(--text-primary); min-height: 60px;"></div>
                <div id="aiStreamBar" style="text-align: center; padding: 8px 0; color: var(--text-tertiary); font-size: 12px;">
                    <span class="loading-spinner" style="display:inline-block; width:14px; height:14px; vertical-align:middle; margin-right:6px;"></span>AI 正在分析测试数据...
                </div>
            `;
            var streamArea = document.getElementById('aiStreamArea');
            var streamBar = document.getElementById('aiStreamBar');

            await ToolboxSSE.postStream('/api/test-report-ai-stream', { analysis: currentAnalysis }, {
                onChunk: function(chunk, fullText) {
                    // 实时增量渲染 Markdown
                    var html = (typeof ToolboxMarkdown !== 'undefined')
                        ? ToolboxMarkdown.renderSafe(fullText)
                        : escapeHtml(fullText).replace(/\n/g, '<br>');
                    streamArea.innerHTML = html;
                    if (streamBar) streamBar.style.display = 'block';
                },
                onDone: function(fullText) {
                    if (streamBar) streamBar.remove();
                    var html = (typeof ToolboxMarkdown !== 'undefined')
                        ? ToolboxMarkdown.renderSafe(fullText || '')
                        : escapeHtml(fullText || '').replace(/\n/g, '<br>');
                    content.innerHTML = `
                        <div style="line-height: 1.8; font-size: 14px; color: var(--text-primary);">
                            ${html}
                        </div>
                        <div style="margin-top: 16px; text-align: right;">
                            <button class="btn btn-secondary" onclick="copyAIAnalysis()" style="font-size: 13px;"> 复制</button>
                        </div>
                    `;
                },
                onError: function(err) {
                    var errMsg = (err || 'AI分析失败').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
                    content.innerHTML = `
                        <div style="padding: 20px; text-align: center;">
                            <div style="color: var(--danger); margin-bottom: 12px;"> ${errMsg}</div>
                            <button class="btn btn-primary" onclick="generateAIAnalysis()" style="background: var(--accent);">重试</button>
                        </div>
                    `;
                }
            });
        }

        function copyAIAnalysis() {
            const text = document.getElementById('aiAnalysisContent').innerText;
            navigator.clipboard.writeText(text).then(() => {
                showToast('已复制到剪贴板', 'success');
            }).catch(() => {
                showToast('复制失败', 'error');
            });
        }

        async function downloadPdf() {
            if (!currentAnalysis) {
                showToast('请先完成分析后再下载PDF', 'info');
                return;
            }

            const btn = document.getElementById('downloadPdfBtn');
            const originalText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = ' 生成中...';

            try {
                // 收集 AI 分析内容（如果已生成）
                var aiContent = '';
                var aiEl = document.getElementById('aiAnalysisContent');
                if (aiEl) {
                    var aiText = aiEl.innerText || aiEl.textContent || '';
                    if (aiText && aiText.indexOf('生成 AI 深度分析') < 0 && aiText.indexOf('AI 正在分析') < 0) {
                        aiContent = aiText.trim();
                    }
                }

                const resp = await fetch('/api/test-report-pdf', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        analysis_data: currentAnalysis,
                        file_name: currentFileName || 'test_report',
                        sheet_name: currentSheetName || '',
                        ai_analysis: aiContent
                    })
                });

                const result = await resp.json();

                if (result.status === 'success') {
                    const downloadUrl = `/api/test-report-download/${result.filename}?download_name=${encodeURIComponent(result.download_name)}`;
                    const a = document.createElement('a');
                    a.href = downloadUrl;
                    a.download = result.download_name;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                } else {
                    showToast('PDF生成失败: ' + (result.error || '未知错误'), 'error');
                }
            } catch (err) {
                showToast('PDF生成请求失败: ' + err.message, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text || '';
            return div.innerHTML;
        }

        function renderReason(reason, isProblem) {
            if (!reason || !reason.trim()) return '<span class="reason-cell empty">-</span>';

            // 只显示待办事项
            const lines = reason.split('\n').map(l => l.trim()).filter(l => l);
            if (lines.length === 0) return '<span class="reason-cell empty">-</span>';

            let html = '<div class="action-items-section">';
            html += '<div class="action-items-header"> 待办事项</div>';
            lines.forEach((line, i) => {
                html += `<div class="action-item-line">${escapeHtml(line)}</div>`;
            });
            html += '</div>';
            return html;
        }

        // ==================== 用户认证 ====================

        async function loadUserInfo() {
            try {
                const resp = await fetch('/api/user/info');
                const data = await resp.json();
                if (data.logged_in && data.user) {
                    currentUser = data.user;
                    const saveBtn = document.getElementById('saveReportBtn');
                    const reportsBtn = document.getElementById('savedReportsBtnWrap');
                    if (saveBtn) saveBtn.style.display = '';
                    if (reportsBtn) reportsBtn.style.display = '';
                }
            } catch (e) {
                console.error('获取用户信息失败:', e);
            }
        }

        async function saveReport() {
            if (!currentAnalysis) {
                showToast('请先完成分析', 'info');
                return;
            }
            if (!currentUser) {
                showToast('请先登录', 'info');
                window.location.href = '/login';
                return;
            }

            const title = prompt('请输入报告名称：', `${currentFileName || '分析报告'}_${new Date().toLocaleDateString()}`);
            if (!title) return;

            const btn = document.getElementById('saveReportBtn');
            const originalText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = ' 保存中...';

            try {
                const resp = await fetch('/api/user/save-report', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        report_data: currentAnalysis,
                        title: title
                    })
                });
                const result = await resp.json();
                if (result.status === 'success') {
                    btn.innerHTML = ' 已保存';
                    setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
                } else {
                    showToast('保存失败: ' + (result.error || '未知错误'), 'error');
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                }
            } catch (e) {
                showToast('保存请求失败: ' + e.message, 'error');
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        }

        function toggleSavedReports() {
            const dropdown = document.getElementById('savedReportsDropdown');
            if (dropdown.classList.contains('show')) {
                dropdown.classList.remove('show');
            } else {
                loadSavedReports();
                dropdown.classList.add('show');
            }
        }

        async function loadSavedReports() {
            const dropdown = document.getElementById('savedReportsDropdown');
            dropdown.innerHTML = '<div class="saved-reports-empty">加载中...</div>';

            try {
                const resp = await fetch('/api/user/reports');
                const data = await resp.json();

                if (!data.reports || data.reports.length === 0) {
                    dropdown.innerHTML = '<div class="saved-reports-empty">暂无保存的报告</div>';
                    return;
                }

                dropdown.innerHTML = data.reports.map(r => {
                    const date = new Date((r.created_at || 0) * 1000).toLocaleString('zh-CN');
                    return `
                        <div class="saved-report-item" onclick="loadSavedReport(${r.id})">
                            <div>
                                <div class="report-title">${escapeHtml(r.title)}</div>
                                <div class="report-date">${date}</div>
                            </div>
                            <span class="delete-btn" onclick="deleteSavedReport(event, ${r.id})"></span>
                        </div>
                    `;
                }).join('');
            } catch (e) {
                dropdown.innerHTML = `<div class="saved-reports-empty">加载失败: ${e.message}</div>`;
            }
        }

        async function loadSavedReport(reportId) {
            try {
                const resp = await fetch(`/api/user/report/${reportId}`);
                const data = await resp.json();
                if (data.report) {
                    currentAnalysis = data.report.content;
                    displayResults(data.report.content);
                    document.getElementById('savedReportsDropdown').classList.remove('show');
                }
            } catch (e) {
                showToast('加载报告失败: ' + e.message, 'error');
            }
        }

        async function deleteSavedReport(event, reportId) {
            event.stopPropagation();
            if (!confirm('确定删除这份报告？')) return;

            try {
                const resp = await fetch(`/api/user/report/${reportId}`, { method: 'DELETE' });
                const data = await resp.json();
                if (data.status === 'success') {
                    loadSavedReports();
                } else {
                    showToast('删除失败: ' + (data.error || ''), 'error');
                }
            } catch (e) {
                showToast('删除请求失败: ' + e.message, 'error');
            }
        }

        // 点击外部关闭下拉
        document.addEventListener('click', (e) => {
            const dropdown = document.getElementById('savedReportsDropdown');
            const btnWrap = document.getElementById('savedReportsBtnWrap');
            if (dropdown && btnWrap && !btnWrap.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });

        // 页面加载时获取用户信息
        loadUserInfo();
