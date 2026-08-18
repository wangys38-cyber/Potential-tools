function showToast(msg, type) {
            if (typeof ToolboxToast !== 'undefined') {
                ToolboxToast.show(msg, type || 'info');
            } else {
                console.log(msg);
            }
        }

        function escapeHtml(str) {
            if (str === null || str === undefined) return '';
            return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
        }

        let isAnalyzing = false;

        // 初始化环境
        (function initAppConfig() {
            const cfg = window.__APP_CONFIG__ || { isCloudEnv: false, maxUploadMb: 200 };
            if (cfg.isCloudEnv) {
                const banner = document.getElementById('cloudEnvBanner');
                if (banner) banner.style.display = 'block';
            }
        })();

        let currentAnalysisData = null;
        let currentFileName = '';
        let currentHeaders = [];
        let columnMapping = {};
        let pendingFile = null;
        let sheetNames = [];
        let currentSheet = '';
        let currentFileId = '';

        function getDefaultWatermark() {
            const now = new Date();
            const y = now.getFullYear();
            const m = String(now.getMonth() + 1).padStart(2, '0');
            const d = String(now.getDate()).padStart(2, '0');
            return `Motorola ${y}-${m}-${d}`;
        }

        function resetWatermark() {
            document.getElementById('watermarkInput').value = getDefaultWatermark();
        }

        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('fileInput');
        const fileInfo = document.getElementById('fileInfo');
        const fileNameEl = document.getElementById('fileName');
        const errorMsg = document.getElementById('errorMsg');
        const analyzing = document.getElementById('analyzing');
        const columnConfigCard = document.getElementById('columnConfigCard');
        const resultCard = document.getElementById('resultCard');
        const sheetSelector = document.getElementById('sheetSelector');
        const sheetSelect = document.getElementById('sheetSelect');

        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragging');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragging');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragging');
            if (e.dataTransfer.files.length > 0) {
                onFileSelected(e.dataTransfer.files[0]);
            }
        });

        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                onFileSelected(e.target.files[0]);
            }
        });

        function onFileSelected(file) {
            if (!file.name.toLowerCase().match(/\.(xlsx|xls|csv)$/)) {
                showError('只支持 .xlsx、.xls 或 .csv 格式的文件');
                return;
            }

            const cfg = window.__APP_CONFIG__ || { isCloudEnv: false, maxUploadMb: 200 };
            const sizeMB = file.size / 1024 / 1024;

            // 绝对最大限制
            if (sizeMB > cfg.maxUploadMb) {
                showError(`文件过大（${sizeMB.toFixed(1)}MB），当前环境最大支持 ${cfg.maxUploadMb}MB。大文件请使用本地部署：https://github.com/wangys38-cyber/CR-tools`);
                return;
            }

            // 云端 > 20MB 警告
            if (cfg.isCloudEnv && sizeMB > 20) {
                const ok = confirm(
                    `⚠️ 文件较大（${sizeMB.toFixed(1)}MB）\n` +
                    `云端内存有限（512MB），分析大文件可能因内存不足失败。\n` +
                    `\n确认继续？（建议本地部署：git clone https://github.com/wangys38-cyber/CR-tools.git）`
                );
                if (!ok) {
                    removeFile();
                    return;
                }
            }

            hideError();
            pendingFile = file;
            currentFileName = file.name;
            fileNameEl.textContent = file.name;
            fileInfo.classList.add('show');
            uploadArea.style.display = 'none';

            analyzing.classList.add('show');
            analyzeFile(file);
        }

        function removeFile() {
            fileInput.value = '';
            fileInfo.classList.remove('show');
            uploadArea.style.display = '';
            analyzing.classList.remove('show');
            columnConfigCard.classList.remove('show');
            resultCard.classList.remove('show');
            document.getElementById('watermarkConfig').classList.remove('show');
            document.getElementById('suggestionsList').innerHTML = '';
            document.getElementById('unverifiedSection').innerHTML = '';
            hideError();
            currentAnalysisData = null;
            pendingFile = null;
        }

        function showError(msg) {
            errorMsg.innerHTML = '';
            errorMsg.textContent = msg;
            if (pendingFile) {
                const retryBtn = document.createElement('button');
                retryBtn.className = 'retry-btn';
                retryBtn.textContent = '重新分析';
                retryBtn.onclick = function() {
                    hideError();
                    if (pendingFile) {
                        analyzeFile(pendingFile);
                    }
                };
                errorMsg.appendChild(document.createElement('br'));
                errorMsg.appendChild(retryBtn);
            }
            errorMsg.classList.add('show');
        }

        function hideError() {
            errorMsg.classList.remove('show');
        }

        // 分块大小：2MB（平衡吞吐量与请求体大小限制）
        const CHUNK_SIZE = 2 * 1024 * 1024;
        // 并发上传数：2 路（降低并发避免竞态和服务器压力）
        const UPLOAD_CONCURRENCY = 2;
        // 单块最大重试次数
        const MAX_CHUNK_RETRIES = 3;

        async function uploadFileChunked(file) {
            const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

            // 1. 初始化分块上传
            const initResp = await fetch('/api/upload-init', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename: file.name,
                    total_size: file.size,
                    total_chunks: totalChunks
                })
            });
            const initResult = await initResp.json();
            if (!initResp.ok || initResult.status !== 'success') {
                throw new Error(initResult.error || '初始化上传失败');
            }
            const uploadId = initResult.data.upload_id;

            // 2. 上传单个分块（带重试）
            let uploadedCount = 0;
            const uploadSingleChunk = async (i) => {
                const start = i * CHUNK_SIZE;
                const end = Math.min(start + CHUNK_SIZE, file.size);
                const chunk = file.slice(start, end);

                let lastError;
                for (let attempt = 0; attempt < MAX_CHUNK_RETRIES; attempt++) {
                    try {
                        const formData = new FormData();
                        formData.append('upload_id', uploadId);
                        formData.append('chunk_index', i);
                        formData.append('offset', start);
                        formData.append('chunk', chunk, `chunk_${i}`);

                        const chunkResp = await fetch('/api/upload-chunk', {
                            method: 'POST',
                            body: formData
                        });
                        const chunkResult = await chunkResp.json();
                        if (!chunkResp.ok || chunkResult.status !== 'success') {
                            throw new Error(chunkResult.error || `分块 ${i} 上传失败`);
                        }
                        uploadedCount++;
                        const progress = Math.round(uploadedCount / totalChunks * 100);
                        analyzing.querySelector('p').textContent = `正在上传文件... ${progress}%`;
                        return; // 成功则退出重试循环
                    } catch (err) {
                        lastError = err;
                        // 等待后重试（指数退避：1s, 2s, 4s）
                        if (attempt < MAX_CHUNK_RETRIES - 1) {
                            await new Promise(r => setTimeout(r, 1000 * Math.pow(2, attempt)));
                        }
                    }
                }
                throw lastError || new Error(`分块 ${i} 上传失败（重试${MAX_CHUNK_RETRIES}次后仍失败）`);
            };

            // 分批并发：每批 UPLOAD_CONCURRENCY 个
            for (let i = 0; i < totalChunks; i += UPLOAD_CONCURRENCY) {
                const batch = [];
                for (let j = i; j < Math.min(i + UPLOAD_CONCURRENCY, totalChunks); j++) {
                    batch.push(uploadSingleChunk(j));
                }
                await Promise.all(batch);
            }

            // 3. 完成上传（支持自动补传缺失分块）
            let completeResp = await fetch('/api/upload-complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ upload_id: uploadId })
            });
            let completeResult = await completeResp.json();

            // 如果有缺失分块，自动补传后重试
            if (!completeResp.ok && completeResult.missing_chunks && completeResult.missing_chunks.length > 0) {
                analyzing.querySelector('p').textContent = `补传缺失分块... (${completeResult.missing_chunks.length}个)`;
                for (const idx of completeResult.missing_chunks) {
                    await uploadSingleChunk(idx);
                }
                // 重新完成
                completeResp = await fetch('/api/upload-complete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ upload_id: uploadId })
                });
                completeResult = await completeResp.json();
            }

            if (!completeResp.ok || completeResult.status !== 'success') {
                throw new Error(completeResult.error || '文件组装失败');
            }

            return completeResult.data;
        }

        async function uploadFileDirect(file) {
            const formData = new FormData();
            formData.append('file', file);
            const resp = await fetch('/api/excel-analyze', {
                method: 'POST',
                body: formData,
                headers: { 'X-Skip-Loading': 'true' }
            });
            const result = await resp.json();
            if (!resp.ok || result.status !== 'success') {
                throw new Error(result.error || '分析失败，请重试');
            }
            return result.data;
        }

        async function analyzeFile(file) {
            if (isAnalyzing) { showToast('正在分析中，请稍候...', 'info'); return; }
            isAnalyzing = true;
            try {
                let data;

                // 文件大于 1MB 时使用分块上传，否则直接上传
                if (file.size > 1024 * 1024) {
                    analyzing.querySelector('p').textContent = '正在上传文件... 0%';
                    data = await uploadFileChunked(file);
                } else {
                    analyzing.querySelector('p').textContent = '正在解析Excel数据...';
                    data = await uploadFileDirect(file);
                }

                const fileId = data.file_id;
                currentFileId = fileId;
                currentFileName = data.file_name || file.name;
                sheetNames = data.sheet_names || [];

                // 自动分析第一个 sheet
                if (sheetNames.length > 0) {
                    currentSheet = sheetNames[0];

                    // 更新 loading 提示文案
                    analyzing.querySelector('p').textContent = '正在分析字段映射...';

                    // 同步字段映射分析
                    try {
                        const fieldsResp = await fetch('/api/excel-analyze-fields', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', 'X-Skip-Loading': 'true' },
                            body: JSON.stringify({ file_id: fileId, sheet_name: currentSheet })
                        });
                        const fieldsResult = await fieldsResp.json();

                        if (fieldsResp.ok && fieldsResult.status === 'done') {
                            const aData = fieldsResult.data;
                            currentHeaders = aData.headers || [];
                            columnMapping = aData.detected_columns || {};
                            currentAnalysisData = {
                                ...aData,
                                sheet_names: sheetNames,
                                file_id: fileId,
                                file_name: currentFileName
                            };
                        } else {
                            throw new Error(fieldsResult.error || '字段映射失败');
                        }
                    } catch (err) {
                        console.error('字段映射失败:', err);
                        currentAnalysisData = { sheet_names: sheetNames };
                    }
                } else {
                    currentAnalysisData = { sheet_names: [] };
                }

                // 完成后隐藏 loading，显示字段配置页面
                analyzing.classList.remove('show');
                analyzing.querySelector('p').textContent = '正在解析Excel数据...';

                const hasIssues = currentAnalysisData &&
                                 currentAnalysisData.summary &&
                                 currentAnalysisData.summary.total_issues > 0;
                showColumnConfig(hasIssues);
            } catch (err) {
                analyzing.classList.remove('show');
                analyzing.querySelector('p').textContent = '正在解析Excel数据...';
                showError(err.message || '网络错误');
                uploadArea.style.display = '';
            } finally {
                isAnalyzing = false;
            }
        }

        function showColumnConfig(hasIssues) {
            const detectedInfo = document.getElementById('detectedInfo');
            const colGrid = document.getElementById('columnGrid');

            const fieldLabels = {
                module: '📦 Component/s（模块/组件）',
                developer: '👤 Assignee（研发/负责人）',
                status: '📊 Status（问题状态）',
                create_date: '📅 Created（创建日期）',
                resolve_date: '✅ Resolved（解决日期）',
                fixed_date: '🔧 Closed Date（fixed日期）',
                fixed_version: '🏷️ Fix Version/s（fixed版本）',
                issue_id: '🔢 Key（问题编号）',
                title: '📝 Summary（问题标题）',
                severity: '⚠️ Severity（严重性）',
            };

            // Handle sheet names
            sheetNames = currentAnalysisData.sheet_names || [];
            currentSheet = currentAnalysisData.current_sheet || '';
            if (sheetNames.length > 1) {
                sheetSelect.innerHTML = sheetNames.map(s => 
                    `<option value="${escapeHtml(s)}" ${s === currentSheet ? 'selected' : ''}>${escapeHtml(s)}</option>`
                ).join('');
                sheetSelector.style.display = 'block';
            } else {
                sheetSelector.style.display = 'none';
            }

            // Show detected columns
            const detectedFields = Object.keys(columnMapping);
            let infoHtml = '';
            
            if (!hasIssues) {
                infoHtml += '<div style="color:#d4380d;margin-bottom:8px;">⚠️ 未检测到有效问题数据，请确认文件格式或手动配置字段映射</div>';
            }
            
            if (detectedFields.length > 0) {
                infoHtml += '<div style="font-weight:600;color:var(--text);margin-bottom:8px;">✅ 自动识别到 ' + detectedFields.length + ' 个关键字段映射：</div>';
                const detectedText = detectedFields.map(f => 
                    `<span style="display:inline-block;background:rgba(0,113,227,0.08);color:var(--accent);padding:2px 8px;border-radius:6px;margin:2px;font-size:12px;font-weight:600;">${fieldLabels[f] || f} → 第${columnMapping[f] + 1}列</span>`
                ).join('');
                infoHtml += detectedText;
            } else {
                infoHtml += '<div style="color:#d4380d;margin:8px 0;">⚠️ 未能自动识别任何字段，请手动配置下方映射</div>';
            }
            
            // Show sample data if available
            const sampleData = currentAnalysisData.sample_data || [];
            if (sampleData.length > 0) {
                const maxCols = Math.min(currentHeaders.length, 8);
                infoHtml += '<div style="margin-top:14px;font-weight:600;color:var(--text);font-size:13px;">📋 数据预览（前3行 × ' + maxCols + '列）：</div>';
                infoHtml += '<div style="overflow-x:auto;margin-top:8px;"><table style="min-width:100%;">';
                infoHtml += '<tr>';
                for (let i = 0; i < maxCols; i++) {
                    infoHtml += `<th>${escapeHtml(currentHeaders[i] || '-')}</th>`;
                }
                infoHtml += '</tr>';
                sampleData.forEach(row => {
                    infoHtml += '<tr>';
                    for (let i = 0; i < maxCols; i++) {
                        const text = String(row[i] || '').substring(0, 25);
                        infoHtml += `<td>${escapeHtml(text || '-')}</td>`;
                    }
                    infoHtml += '</tr>';
                });
                infoHtml += '</table></div>';
            }
            
            detectedInfo.innerHTML = infoHtml;

            colGrid.innerHTML = '';
            for (const [field, label] of Object.entries(fieldLabels)) {
                const currentCol = columnMapping[field] !== undefined ? columnMapping[field] : -1;
                const detectedHeader = currentCol >= 0 ? (currentHeaders[currentCol] || '') : '';
                const isAutoDetected = field in columnMapping;
                const options = currentHeaders.map((h, idx) => 
                    `<option value="${idx}" ${idx === currentCol ? 'selected' : ''}>${escapeHtml(h || '列' + (idx + 1))}</option>`
                ).join('');

                colGrid.innerHTML += `
                    <div class="column-item" ${isAutoDetected ? 'title="自动检测到：' + escapeHtml(detectedHeader) + '"' : ''}>
                        <span class="label">${label}${field === 'create_date' ? '<span class="required">*</span>' : ''}</span>
                        <select data-field="${field}">
                            <option value="-1">-- 未设置 --</option>
                            ${options}
                        </select>
                    </div>
                `;
            }

            columnConfigCard.classList.add('show');
        }

        function confirmColumns() {
            const selects = document.querySelectorAll('#columnGrid select');
            const newMapping = {};

            selects.forEach(sel => {
                const field = sel.dataset.field;
                const val = parseInt(sel.value);
                if (val >= 0) {
                    newMapping[field] = val;
                }
            });

            columnMapping = newMapping;

            if (!columnMapping.hasOwnProperty('create_date')) {
                showError('必须设置「创建日期」字段才能进行分析');
                return;
            }

            // Get selected sheet if multi-sheet
            if (sheetNames.length > 1 && sheetSelect.value) {
                currentSheet = sheetSelect.value;
            }

            runAnalysis();
        }

        async function runAnalysis() {
            if (!currentFileId) {
                showError('请重新上传文件');
                uploadArea.style.display = '';
                return;
            }

            analyzing.querySelector('p').textContent = '正在生成分析报告...';
            analyzing.classList.add('show');
            columnConfigCard.classList.remove('show');

            try {
                // 启动后台分析，轮询结果
                const resp = await fetch('/api/excel-analyze-sheet', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Skip-Loading': 'true' },
                    body: JSON.stringify({ 
                        file_id: currentFileId, 
                        sheet_name: currentSheet 
                    })
                });
                const initResult = await resp.json();

                if (!resp.ok || initResult.status !== 'success') {
                    throw new Error(initResult.error || '启动分析失败');
                }

                const taskId = initResult.data.task_id;
                // 轮询任务状态（最多 900 次 = 15分钟，大文件需要更长时间）
                let pollCount = 0;
                const maxPolls = 900;
                while (pollCount < maxPolls) {
                    await new Promise(r => setTimeout(r, 1000));
                    const statusResp = await fetch('/api/task-status', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_id: taskId })
                    });
                    const statusResult = await statusResp.json();

                    if (statusResult.status === 'done') {
                        analyzing.classList.remove('show');
                        analyzing.querySelector('p').textContent = '正在解析Excel数据...';
                        const pb = document.getElementById('analysisProgressBar');
                        if (pb) pb.style.display = 'none';
                        currentAnalysisData = statusResult.data;
                        currentAnalysisData.file_name = currentFileName;
                        displayResults();
                        return;
                    } else if (statusResult.status === 'error') {
                        const pb = document.getElementById('analysisProgressBar');
                        if (pb) pb.style.display = 'none';
                        throw new Error(statusResult.error || '分析失败');
                    }
                    pollCount++;
                    // 显示服务器返回的进度信息
                    const progressBar = document.getElementById('analysisProgressBar');
                    const progressFill = document.getElementById('analysisProgressFill');
                    if (statusResult.progress !== undefined) {
                        if (progressBar) progressBar.style.display = 'block';
                        if (progressFill) progressFill.style.width = statusResult.progress + '%';
                        const pct = statusResult.progress || 0;
                        analyzing.querySelector('p').textContent = `${statusResult.progress_msg || '正在分析...'} (${pct}%)`;
                    } else {
                        if (progressBar) progressBar.style.display = 'none';
                        analyzing.querySelector('p').textContent = `正在生成分析报告... (${pollCount}s)`;
                    }
                }
                throw new Error('分析超时（超过15分钟），请重试或减少数据量');

            } catch (err) {
                analyzing.classList.remove('show');
                analyzing.querySelector('p').textContent = '正在解析Excel数据...';
                showError(err.message || '网络错误');
                uploadArea.style.display = '';
            }
        }

        function displayResults() {
            if (!currentAnalysisData) return;

            const d = currentAnalysisData;
            const s = d.summary || {};

            // 显示推送按钮和文件名
            const pushBtn = document.getElementById('pushFeishuBtn');
            if (pushBtn) pushBtn.style.display = 'inline-block';
            const fileNameEl = document.getElementById('reportFileName');
            if (fileNameEl) fileNameEl.textContent = d.file_name ? `— ${d.file_name}` : '';

            document.getElementById('summaryGrid').innerHTML = `
                <div class="summary-card">
                    <div class="num">${s.total_issues || 0}</div>
                    <div class="label">问题总数</div>
                </div>
                <div class="summary-card rate">
                    <div class="num">${s.total_resolved || 0}</div>
                    <div class="label">已解决</div>
                </div>
                <div class="summary-card unresolved">
                    <div class="num">${s.total_unresolved || 0}</div>
                    <div class="label">未解决</div>
                </div>
                <div class="summary-card">
                    <div class="num">${s.resolution_rate || 0}%</div>
                    <div class="label">解决率</div>
                </div>
            `;

            // 显示Severity分布
            const sevHtml = `
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:24px;">
                    <div class="summary-card blocker">
                        <div class="num">${s.blocker_total || 0}</div>
                        <div class="label">Blocker ${s.blocker_rate || 0}%</div>
                    </div>
                    <div class="summary-card critical">
                        <div class="num">${s.critical_total || 0}</div>
                        <div class="label">Critical ${s.critical_rate || 0}%</div>
                    </div>
                    <div class="summary-card major">
                        <div class="num">${s.major_total || 0}</div>
                        <div class="label">Major ${s.major_rate || 0}%</div>
                    </div>
                    <div class="summary-card minor">
                        <div class="num">${s.minor_total || 0}</div>
                        <div class="label">Minor ${s.minor_rate || 0}%</div>
                    </div>
                    <div class="summary-card trivial">
                        <div class="num">${s.trivial_total || 0}</div>
                        <div class="label">Trivial ${s.trivial_rate || 0}%</div>
                    </div>
                    <div class="summary-card bc-rate">
                        <div class="num">${s.blocker_critical_rate || 0}%</div>
                        <div class="label">B+C解决率 (${s.blocker_critical_total || 0})</div>
                    </div>
                </div>
            `;
            document.getElementById('summaryGrid').insertAdjacentHTML('afterend', sevHtml);

            // 显示severity检测信息
            const sevInfo = document.getElementById('severityInfo');
            if (sevInfo) {
                const sv = d.severity_values || [];
                const sd = d.severity_detected || false;
                const sw = d.severity_warning || '';
                let warningHtml = '';
                if (sw) {
                    warningHtml = `<div style="margin-top:8px;padding:8px 12px;background:#fff3cd;border:1px solid #ffc107;border-radius:8px;color:#856404;font-size:12px;">⚠️ ${sw}</div>`;
                }
                sevInfo.style.display = 'block';
                sevInfo.innerHTML = `
                    <div style="background:#f5f5f7;border-radius:12px;padding:16px 20px;margin-bottom:20px;font-size:13px;">
                        <div style="font-weight:600;margin-bottom:8px;">🔍 Severity检测</div>
                        <div style="color:#666;margin-bottom:6px;">字段: ${sd ? '<span style="color:#34c759;">✓ 已识别Severity</span>' : '<span style="color:#ff3b30;">✗ 未识别</span>'}</div>
                        <div style="color:#666;">实际值: <code style="background:#fff;padding:2px 6px;border-radius:4px;">${sv.length ? escapeHtml(sv.join(', ')) : '(无数据)'}</code></div>
                        ${warningHtml}
                    </div>
                `;
            }

            const moduleStats = d.module_stats || {};
            const moduleRows = Object.entries(moduleStats)
                .sort((a, b) => b[1].total - a[1].total)
                .map(([mod, stats]) => `
                    <tr>
                        <td>${escapeHtml(mod)}</td>
                        <td class="num">${stats.total}</td>
                        <td class="num resolved">${stats.resolved}</td>
                        <td class="num unresolved">${stats.unresolved}</td>
                        <td class="num">${stats.total > 0 ? (stats.resolved/stats.total*100).toFixed(1) : 0}%</td>
                    </tr>
                `).join('');

            document.getElementById('modulesTable').innerHTML = `
                <table>
                    <thead>
                        <tr>
                            <th>模块名称</th>
                            <th class="num">问题总数</th>
                            <th class="num">已解决</th>
                            <th class="num">未解决</th>
                            <th class="num">解决率</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${moduleRows || '<tr><td colspan="5" class="empty-state">暂无数据</td></tr>'}
                    </tbody>
                </table>
            `;

            // 稳定性模块统计 - 使用后端已筛选的 MTTF 模块
            window._allModuleStats = d.module_stats || {};
            filterStabilityModules();
            document.getElementById('stabilityKeywords').value = 'MTTF';

            const devStats = d.dev_stats || {};
            const devRows = Object.entries(devStats)
                .sort((a, b) => b[1].total - a[1].total)
                .map(([dev, stats]) => {
                    const mods = stats.modules || [];
                    const moduleList = mods.slice(0, 3).map(escapeHtml).join(', ');
                    const extra = mods.length > 3 ? ' 等' + mods.length + '个' : '';
                    return `
                        <tr>
                            <td>${escapeHtml(dev)}</td>
                            <td class="num">${stats.total}</td>
                            <td class="num resolved">${stats.resolved}</td>
                            <td class="num unresolved">${stats.unresolved}</td>
                            <td>${moduleList}${extra}</td>
                            <td class="num">${stats.total > 0 ? (stats.resolved/stats.total*100).toFixed(1) : 0}%</td>
                        </tr>
                    `;
                }).join('');

            // 填充研发名字下拉列表
            const devList = document.getElementById('developerList');
            if (devList && d.developers) {
                devList.innerHTML = d.developers.map(dev => `<option value="${escapeHtml(dev.name || dev)}">`).join('');
            }

            document.getElementById('developersTable').innerHTML = `
                <table>
                    <thead>
                        <tr>
                            <th>研发人员</th>
                            <th class="num">问题总数</th>
                            <th class="num">已解决</th>
                            <th class="num">未解决</th>
                            <th>负责模块</th>
                            <th class="num">解决率</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${devRows || '<tr><td colspan="6" class="empty-state">暂无数据</td></tr>'}
                    </tbody>
                </table>
            `;

            const dailyStats = d.daily_stats || [];
            const displayDaily = dailyStats.slice(-30);
            
            // Find max values for scaling
            let maxNew = 0, maxResolved = 0;
            displayDaily.forEach(d => {
                if (d.new_count > maxNew) maxNew = d.new_count;
                if (d.resolved_count > maxResolved) maxResolved = d.resolved_count;
            });
            const maxVal = Math.max(maxNew, maxResolved, 1);
            
            const dailyRows = displayDaily.map(d => {
                const net = d.new_count - d.resolved_count;
                const newWidth = maxNew > 0 ? (d.new_count / maxVal * 100) : 0;
                const resolvedWidth = maxResolved > 0 ? (d.resolved_count / maxVal * 100) : 0;
                return `
                <tr>
                    <td style="white-space:nowrap;font-weight:500;">${formatDate(d.date)}</td>
                    <td class="num new">+${d.new_count}</td>
                    <td style="min-width:120px;">
                        <div style="background:#f0f0f3;border-radius:4px;height:10px;overflow:hidden;">
                            <div style="background:linear-gradient(90deg,#ff3b30,#ff9500);height:100%;width:${newWidth}%;border-radius:4px;transition:width 0.3s;"></div>
                        </div>
                    </td>
                    <td class="num resolved">-${d.resolved_count}</td>
                    <td style="min-width:120px;">
                        <div style="background:#f0f0f3;border-radius:4px;height:10px;overflow:hidden;">
                            <div style="background:linear-gradient(90deg,#34c759,#5ac8fa);height:100%;width:${resolvedWidth}%;border-radius:4px;transition:width 0.3s;"></div>
                        </div>
                    </td>
                    <td class="num" style="color:${net > 0 ? '#ff3b30' : net < 0 ? '#34c759' : '#8e8e93'};font-weight:600;">${net >= 0 ? '+' : ''}${net}</td>
                </tr>`;
            }).join('');

            document.getElementById('dailyTable').innerHTML = `
                <div style="margin-bottom:16px;padding:12px 16px;background:#f0f7ff;border-radius:8px;font-size:13px;display:flex;gap:24px;align-items:center;">
                    <div><span style="display:inline-block;width:12px;height:12px;background:linear-gradient(90deg,#ff3b30,#ff9500);border-radius:3px;"></span> 新增问题 (最高 ${maxNew})</div>
                    <div><span style="display:inline-block;width:12px;height:12px;background:linear-gradient(90deg,#34c759,#5ac8fa);border-radius:3px;"></span> 解决问题 (最高 ${maxResolved})</div>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th style="width:120px;">日期</th>
                            <th class="num" style="width:70px;">新增</th>
                            <th style="width:140px;">新增趋势</th>
                            <th class="num" style="width:70px;">解决</th>
                            <th style="width:140px;">解决趋势</th>
                            <th class="num" style="width:70px;">净增</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${dailyRows || '<tr><td colspan="6" class="empty-state">暂无数据</td></tr>'}
                    </tbody>
                </table>
                ${dailyStats.length > 30 ? '<p style="text-align:center;color:var(--text-secondary);margin-top:12px;font-size:12px;">仅显示最近30天，完整数据请查看PDF报告</p>' : ''}
            `;

            // Display suggestions - 美化版
            const suggestions = d.suggestions || [];
            let sugHtml = '';
            
            if (suggestions.length > 0) {
                // 总体概览
                const overview = suggestions.find(s => s.type === 'overview');
                if (overview && overview.stats) {
                    const stats = overview.stats;
                    const rateColor = parseFloat(stats.rate) >= 80 ? '#34c759' : parseFloat(stats.rate) >= 60 ? '#ff9500' : '#ff3b30';
                    sugHtml += `
                        <div style="background:linear-gradient(135deg,#f8f9fa,#e8e8ed);border-radius:20px;padding:28px;margin-bottom:24px;border:1px solid #e5e5ea;">
                            <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
                                <span style="font-size:24px;">📊</span>
                                <h3 style="margin:0;color:var(--text);font-size:18px;font-weight:700;">问题总体概览</h3>
                            </div>
                            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;">
                                <div style="background:white;border-radius:14px;padding:20px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                                    <div style="font-size:28px;font-weight:800;color:var(--text);margin-bottom:4px;">${stats.total}</div>
                                    <div style="font-size:13px;color:var(--text-secondary);">问题总数</div>
                                </div>
                                <div style="background:white;border-radius:14px;padding:20px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                                    <div style="font-size:28px;font-weight:800;color:#34c759;margin-bottom:4px;">${stats.resolved}</div>
                                    <div style="font-size:13px;color:var(--text-secondary);">已解决</div>
                                </div>
                                <div style="background:white;border-radius:14px;padding:20px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                                    <div style="font-size:28px;font-weight:800;color:#ff3b30;margin-bottom:4px;">${stats.unresolved}</div>
                                    <div style="font-size:13px;color:var(--text-secondary);">未解决</div>
                                </div>
                                <div style="background:white;border-radius:14px;padding:20px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                                    <div style="font-size:28px;font-weight:800;color:${rateColor};margin-bottom:4px;">${stats.rate}</div>
                                    <div style="font-size:13px;color:var(--text-secondary);">解决率</div>
                                </div>
                            </div>
                        </div>
                    `;
                }
                
                // 其他建议卡片
                const otherSuggestions = suggestions.filter(s => s.type !== 'overview' && s.type !== 'advice');
                if (otherSuggestions.length > 0) {
                    sugHtml += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px;">';
                    otherSuggestions.forEach(sug => {
                        sugHtml += renderSuggestionCard(sug);
                    });
                    sugHtml += '</div>';
                }
                
                // 建议卡片
                const advice = suggestions.find(s => s.type === 'advice');
                if (advice) {
                    sugHtml += renderAdviceCard(advice);
                }
            } else {
                sugHtml = '<div style="text-align:center;color:var(--text-secondary);padding:40px;">暂无建议</div>';
            }
            
            document.getElementById('suggestionsList').innerHTML = sugHtml;

            // Display resolved-but-unverified issues
            const unverifiedList = d.resolved_unverified || [];
            let unvHtml = '';
            if (unverifiedList.length > 0) {
                let rowsHtml = '';
                unverifiedList.forEach(item => {
                    const sevColor = item.severity === 'Critical' || item.severity === 'Blocker' ? '#ff3b30' : 
                                     item.severity === 'Major' ? '#ff9500' : '#34c759';
                    rowsHtml += `<tr>
                        <td style="text-align:center;white-space:nowrap;">${escapeHtml(item.issue_id || '-')}</td>
                        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(item.title || '')}">${escapeHtml(item.title || '-')}</td>
                        <td>${escapeHtml(item.developer || '-')}</td>
                        <td>${escapeHtml(item.module || '-')}</td>
                        <td style="text-align:center;color:${sevColor};font-weight:600;">${escapeHtml(item.severity || '-')}</td>
                        <td style="text-align:center;">${escapeHtml(item.resolution || '-')}</td>
                        <td style="text-align:center;">${escapeHtml(item.status || '-')}</td>
                        <td style="text-align:center;">${escapeHtml(item.create_date || '-')}</td>
                    </tr>`;
                });
                unvHtml = `
                    <div style="margin-top:28px;background:linear-gradient(135deg,#fff,#f8f9fa);border-radius:16px;padding:24px;box-shadow:var(--shadow-md);border:1px solid var(--border);">
                        <h3 style="font-size:15px;font-weight:700;color:var(--warning);margin-bottom:8px;display:flex;align-items:center;gap:6px;">⚠️ 待验证问题（共 ${unverifiedList.length} 条）</h3>
                        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:16px;line-height:1.6;">以下问题的 Status 为 Verified，需要进行验证测试。</p>
                        <div style="max-height:400px;overflow-y:auto;">
                        <table>
                            <thead style="position:sticky;top:0;background:#f5f5f7;z-index:1;">
                                <tr>
                                    <th style="width:100px;text-align:center;">edartID</th>
                                    <th style="min-width:150px;">标题</th>
                                    <th>研发</th>
                                    <th>模块</th>
                                    <th style="width:80px;text-align:center;">严重性</th>
                                    <th style="width:100px;text-align:center;">Resolution</th>
                                    <th style="width:90px;text-align:center;">状态</th>
                                    <th style="width:110px;text-align:center;">创建日期</th>
                                </tr>
                            </thead>
                            <tbody>${rowsHtml}</tbody>
                        </table>
                        </div>
                    </div>
                `;
            }
            document.getElementById('unverifiedSection').innerHTML = unvHtml;

            // Draw charts
            drawModulePieChart(moduleStats);
            drawDailyLineChart(dailyStats);

            // Set default watermark
            document.getElementById('watermarkInput').value = getDefaultWatermark();

            document.getElementById('watermarkConfig').classList.add('show');
            resultCard.classList.add('show');
        }

        let modulePieChart = null;
        let dailyLineChart = null;

        function drawModulePieChart(moduleStats) {
            const ctx = document.getElementById('modulePieChart');
            if (!ctx) return;

            const data = Object.entries(moduleStats)
                .sort((a, b) => b[1].total - a[1].total)
                .slice(0, 10);

            const colors = [
                '#0071e3', '#34c759', '#ff9500', '#ff3b30', '#af52de',
                '#5856d6', '#ff2d55', '#5ac8fa', '#4cd964', '#ffcc00'
            ];

            if (modulePieChart) modulePieChart.destroy();
            modulePieChart = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: data.map(([mod]) => mod),
                    datasets: [{
                        data: data.map(([, stats]) => stats.total),
                        backgroundColor: colors,
                        borderWidth: 3,
                        borderColor: '#fff',
                        hoverOffset: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    cutout: '45%',
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: { font: { size: 11, family: '-apple-system, PingFang SC' }, padding: 10, usePointStyle: true, pointStyle: 'circle' }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(29,29,31,0.9)',
                            titleFont: { size: 13, weight: '600' },
                            bodyFont: { size: 12 },
                            padding: 12,
                            cornerRadius: 8,
                            callbacks: {
                                label: function(context) {
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const pct = ((context.raw / total) * 100).toFixed(1);
                                    return context.label + ': ' + context.raw + ' (' + pct + '%)';
                                }
                            }
                        }
                    }
                }
            });
        }

        function formatDate(d) {
            if (!d) return '';
            // YYYY-MM-DD -> MM-DD
            const m = d.match(/^(\d{4})-(\d{2})-(\d{2})/);
            if (m) return `${m[2]}-${m[3]}`;
            return d;
        }

        function drawDailyLineChart(dailyStats) {
            const ctx = document.getElementById('dailyLineChart');
            if (!ctx) return;

            const displayData = dailyStats.slice(-14);

            if (dailyLineChart) dailyLineChart.destroy();
            dailyLineChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: displayData.map(d => d.date.substring(5)),
                    datasets: [{
                        label: '新增问题',
                        data: displayData.map(d => d.new_count),
                        borderColor: '#ff3b30',
                        backgroundColor: 'rgba(255, 59, 48, 0.08)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#ff3b30',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        borderWidth: 2.5
                    }, {
                        label: '解决问题',
                        data: displayData.map(d => d.resolved_count),
                        borderColor: '#34c759',
                        backgroundColor: 'rgba(52, 199, 89, 0.08)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#34c759',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        borderWidth: 2.5
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: { font: { size: 11, family: '-apple-system, PingFang SC' }, padding: 12, usePointStyle: true, pointStyle: 'circle' }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(29,29,31,0.9)',
                            titleFont: { size: 13, weight: '600' },
                            bodyFont: { size: 12 },
                            padding: 12,
                            cornerRadius: 8
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: { color: 'rgba(0,0,0,0.04)' },
                            ticks: { font: { size: 10 } }
                        },
                        x: {
                            grid: { display: false },
                            ticks: { font: { size: 10 } }
                        }
                    }
                }
            });
        }

        function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            var tabBtn = document.querySelector('[data-tab="' + tab + '"]');
            var tabContent = document.getElementById('tab-' + tab);
            if (tabBtn) tabBtn.classList.add('active');
            if (tabContent) tabContent.classList.add('active');
        }

        async function generatePDF(btn) {
            if (!currentAnalysisData) return;

            const watermark = document.getElementById('watermarkInput').value.trim();
            const customTitle = document.getElementById('reportTitleInput').value.trim();
            const originalText = btn.textContent;
            btn.textContent = '生成中...';
            btn.disabled = true;

            // Fix: use original filename instead of temp filename
            currentAnalysisData.file_name = currentFileName;

            try {
                const resp = await fetch('/api/excel-analyze-pdf', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        analysis_data: currentAnalysisData,
                        watermark: watermark,
                        custom_title: customTitle
                    })
                });
                const result = await resp.json();

                if (resp.ok && result.filename) {
                    const a = document.createElement('a');
                    a.href = '/download/' + encodeURIComponent(result.filename);
                    // 使用自定义标题作为下载文件名
                    const downloadName = result.download_name || result.filename;
                    a.download = downloadName;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                } else {
                    showError(result.error || 'PDF生成失败');
                }
            } catch (err) {
                showError('网络错误：' + err.message);
            } finally {
                btn.textContent = originalText;
                btn.disabled = false;
            }
        }

        function resetAll() {
            removeFile();
            columnConfigCard.classList.remove('show');
            resultCard.classList.remove('show');
            document.getElementById('watermarkConfig').classList.remove('show');
            document.getElementById('suggestionsList').innerHTML = '';
            document.getElementById('unverifiedSection').innerHTML = '';
            document.getElementById('stabilitySection').innerHTML = '';
            document.getElementById('stabilityIssuesSection').innerHTML = '';
            // v3.0: 重置 AI 分析
            const aiContent = document.getElementById('aiContent');
            if (aiContent) {
                aiContent.innerHTML = `
                    <div style="text-align: center; padding: 20px;">
                        <button class="btn btn-primary" onclick="generateAIAnalysis()" style="background: var(--accent);">🤖 生成 AI 根因分析</button>
                        <div style="font-size: 12px; color: var(--text-tertiary); margin-top: 8px;">AI 将基于问题数据生成根因分析、高风险领域和改进建议</div>
                    </div>
                `;
            }
            currentAnalysisData = null;
        }

        // v3.0: AI 根因分析（SSE 流式）
        async function generateAIAnalysis() {
            if (!currentAnalysisData) {
                showToast('请先完成数据分析', 'success');
                return;
            }

            const content = document.getElementById('aiContent');
            content.innerHTML = `
                <div id="aiStreamArea" style="line-height: 1.8; font-size: 14px; color: var(--text-primary); min-height: 60px;"></div>
                <div id="aiStreamBar" style="text-align: center; padding: 8px 0; color: var(--text-tertiary); font-size: 12px;">
                    <span style="display:inline-block; width:14px; height:14px; border:2px solid var(--accent); border-top-color:transparent; border-radius:50%; animation:spin 0.8s linear infinite; vertical-align:middle; margin-right:6px;"></span>AI 正在分析问题数据...
                </div>
                <style>@keyframes spin { to { transform: rotate(360deg); } }</style>
            `;
            var streamArea = document.getElementById('aiStreamArea');
            var streamBar = document.getElementById('aiStreamBar');

            await ToolboxSSE.postStream('/api/excel-analyze-ai-stream', { analysis: currentAnalysisData }, {
                onChunk: function(chunk, fullText) {
                    var html = (typeof ToolboxMarkdown !== 'undefined')
                        ? ToolboxMarkdown.renderSafe(fullText)
                        : escapeHtml(fullText).replace(/\n/g, '<br>');
                    streamArea.innerHTML = html;
                },
                onDone: function(fullText) {
                    if (streamBar) streamBar.remove();
                    var html = (typeof ToolboxMarkdown !== 'undefined')
                        ? ToolboxMarkdown.renderSafe(fullText || '')
                        : escapeHtml(fullText || '').replace(/\n/g, '<br>');
                    content.innerHTML = `
                        <div style="line-height: 1.8; font-size: 14px; color: var(--text-primary);">${html}</div>
                        <div style="margin-top: 16px; text-align: right;">
                            <button class="btn btn-secondary" onclick="copyAIAnalysis()" style="font-size: 13px;">📋 复制</button>
                        </div>
                    `;
                },
                onError: function(err) {
                    var errMsg = (err || 'AI分析失败').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
                    content.innerHTML = `
                        <div style="padding: 20px; text-align: center;">
                            <div style="color: var(--danger); margin-bottom: 12px;">❌ ${errMsg}</div>
                            <button class="btn btn-primary" onclick="generateAIAnalysis()" style="background: var(--accent);">重试</button>
                        </div>
                    `;
                }
            });
        }

        function copyAIAnalysis() {
            const text = document.getElementById('aiContent').innerText;
            navigator.clipboard.writeText(text).then(() => {
                showToast('已复制到剪贴板', 'success');
            }).catch(() => {
                showToast('复制失败', 'error');
            });
        }

        function filterStabilityModules() {
            const allStats = window._allModuleStats || {};
            const keywordsInput = document.getElementById('stabilityKeywords');
            const keywordsStr = keywordsInput ? keywordsInput.value : '';
            const keywords = keywordsStr.split(/[,，]/).map(k => k.trim().toLowerCase()).filter(k => k);
            
            if (Object.keys(allStats).length === 0) {
                document.getElementById('stabilitySection').innerHTML = `
                    <div style="background:linear-gradient(135deg,#f5f5f7,#e8e8ed);border-radius:12px;padding:40px;text-align:center;">
                        <div style="font-size:48px;margin-bottom:12px;">📊</div>
                        <h3 style="margin:0 0 8px;color:var(--text);">暂无数据</h3>
                        <p style="margin:0;color:var(--text-secondary);font-size:13px;">请先上传文件并完成分析</p>
                    </div>
                `;
                return;
            }
            
            // 根据关键字筛选模块
            let filteredStats = allStats;
            if (keywords.length > 0) {
                filteredStats = {};
                Object.entries(allStats).forEach(([mod, stats]) => {
                    const modLower = mod.toLowerCase();
                    if (keywords.some(kw => modLower.includes(kw))) {
                        filteredStats[mod] = stats;
                    }
                });
            }
            
            const stabilityCount = Object.keys(filteredStats).length;
            let stabilityHtml = '';
            
            if (stabilityCount > 0) {
                const stabilityTotal = Object.values(filteredStats).reduce((sum, s) => sum + s.total, 0);
                const stabilityResolved = Object.values(filteredStats).reduce((sum, s) => sum + s.resolved, 0);
                const stabilityUnresolved = Object.values(filteredStats).reduce((sum, s) => sum + s.unresolved, 0);
                const resolutionRate = stabilityTotal > 0 ? (stabilityResolved / stabilityTotal * 100).toFixed(1) : 0;
                
                stabilityHtml += `
                    <div style="background:linear-gradient(135deg,#f0f7ff,#e8f1ff);border-radius:12px;padding:20px;margin-bottom:20px;border:1px solid #bae0ff;">
                        <h3 style="margin:0 0 12px;color:var(--text);display:flex;align-items:center;gap:8px;">🛡️ 稳定性模块问题统计</h3>
                        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:16px;">
                            <div style="background:white;padding:12px;border-radius:8px;text-align:center;">
                                <div style="font-size:24px;font-weight:700;color:var(--accent);">${stabilityCount}</div>
                                <div style="font-size:12px;color:var(--text-secondary);">匹配模块数</div>
                            </div>
                            <div style="background:white;padding:12px;border-radius:8px;text-align:center;">
                                <div style="font-size:24px;font-weight:700;color:#ff3b30;">${stabilityTotal}</div>
                                <div style="font-size:12px;color:var(--text-secondary);">问题总数</div>
                            </div>
                            <div style="background:white;padding:12px;border-radius:8px;text-align:center;">
                                <div style="font-size:24px;font-weight:700;color:#34c759;">${stabilityResolved}</div>
                                <div style="font-size:12px;color:var(--text-secondary);">已解决</div>
                            </div>
                            <div style="background:white;padding:12px;border-radius:8px;text-align:center;">
                                <div style="font-size:24px;font-weight:700;color:#ff9500;">${stabilityUnresolved}</div>
                                <div style="font-size:12px;color:var(--text-secondary);">未解决</div>
                            </div>
                            <div style="background:white;padding:12px;border-radius:8px;text-align:center;">
                                <div style="font-size:24px;font-weight:700;color:#0071e3;">${resolutionRate}%</div>
                                <div style="font-size:12px;color:var(--text-secondary);">解决率</div>
                            </div>
                        </div>
                        <div style="background:white;border-radius:8px;overflow:hidden;">
                            <table style="width:100%;border-collapse:collapse;">
                                <thead>
                                    <tr style="background:#f5f5f7;">
                                        <th style="padding:10px 14px;text-align:left;font-size:13px;color:var(--text);">模块名称</th>
                                        <th style="padding:10px 14px;text-align:right;font-size:13px;color:var(--text);">问题总数</th>
                                        <th style="padding:10px 14px;text-align:right;font-size:13px;color:var(--text);">已解决</th>
                                        <th style="padding:10px 14px;text-align:right;font-size:13px;color:var(--text);">未解决</th>
                                        <th style="padding:10px 14px;text-align:right;font-size:13px;color:var(--text);">解决率</th>
                                    </tr>
                                </thead>
                                <tbody>
                `;
                
                const stabilityRows = Object.entries(filteredStats)
                    .sort((a, b) => b[1].total - a[1].total)
                    .map(([mod, stats]) => {
                        const rate = stats.total > 0 ? (stats.resolved/stats.total*100).toFixed(1) : 0;
                        const rateColor = rate >= 80 ? '#34c759' : rate >= 60 ? '#ff9500' : '#ff3b30';
                        return `
                            <tr style="border-top:1px solid #f0f0f3;">
                                <td style="padding:10px 14px;font-size:13px;color:var(--text);">${escapeHtml(mod)}</td>
                                <td style="padding:10px 14px;text-align:right;font-size:13px;font-weight:600;color:var(--text);">${stats.total}</td>
                                <td style="padding:10px 14px;text-align:right;font-size:13px;color:#34c759;">${stats.resolved}</td>
                                <td style="padding:10px 14px;text-align:right;font-size:13px;color:#ff3b30;">${stats.unresolved}</td>
                                <td style="padding:10px 14px;text-align:right;font-size:13px;color:${rateColor};font-weight:600;">${rate}%</td>
                            </tr>
                        `;
                    }).join('');
                
                stabilityHtml += stabilityRows;
                stabilityHtml += '</tbody></table></div></div>';
            } else {
                const totalModules = Object.keys(allStats).length;
                stabilityHtml = `
                    <div style="background:linear-gradient(135deg,#f5f5f7,#e8e8ed);border-radius:12px;padding:40px;text-align:center;">
                        <div style="font-size:48px;margin-bottom:12px;">🔍</div>
                        <h3 style="margin:0 0 8px;color:var(--text);">没有匹配的模块</h3>
                        <p style="margin:0 0 8px;color:var(--text-secondary);font-size:13px;">
                            当前关键字 "${keywordsStr}" 没有匹配到任何模块
                        </p>
                        <p style="margin:0;color:var(--text-secondary);font-size:12px;">
                            共 ${totalModules} 个模块，请尝试其他关键字
                        </p>
                    </div>
                `;
            }
            
            document.getElementById('stabilitySection').innerHTML = stabilityHtml;
            
            // 筛选并显示稳定性问题列表
            const stabilityIssuesSection = document.getElementById('stabilityIssuesSection');
            if (stabilityIssuesSection && currentAnalysisData && currentAnalysisData.all_issues) {
                const allIssues = currentAnalysisData.all_issues;
                let filteredIssues = allIssues;
                
                // 根据关键字筛选问题
                if (keywords.length > 0) {
                    filteredIssues = allIssues.filter(issue => {
                        const modLower = (issue.module || '').toLowerCase();
                        return keywords.some(kw => modLower.includes(kw));
                    });
                }
                
                if (filteredIssues.length > 0) {
                    let issuesHtml = `
                        <div style="background:linear-gradient(135deg,#fff,#f8f9fa);border-radius:16px;padding:24px;margin-top:20px;box-shadow:0 4px 20px rgba(0,0,0,0.06);border:1px solid var(--border);">
                            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
                                <h3 style="margin:0;color:var(--text);font-size:16px;font-weight:700;display:flex;align-items:center;gap:8px;">
                                    📋 稳定性问题详情列表
                                </h3>
                                <div style="display:flex;gap:8px;">
                                    <select id="stabilityStatusFilter" onchange="filterStabilityIssues()" style="padding:6px 12px;border:1px solid #d2d2d7;border-radius:6px;font-size:12px;background:white;">
                                        <option value="">全部状态</option>
                                        <option value="open">未解决</option>
                                        <option value="resolved">已解决</option>
                                    </select>
                                    <span style="font-size:12px;color:var(--text-secondary);line-height:32px;">共 ${filteredIssues.length} 条</span>
                                </div>
                            </div>
                            <div style="max-height:500px;overflow-y:auto;border-radius:12px;border:1px solid #e5e5ea;">
                                <table style="width:100%;border-collapse:collapse;font-size:12px;">
                                    <thead style="position:sticky;top:0;background:#f5f5f7;z-index:1;">
                                        <tr>
                                            <th style="padding:10px 12px;text-align:left;color:var(--text);font-weight:600;white-space:nowrap;">🔗 eDART ID</th>
                                            <th style="padding:10px 12px;text-align:left;color:var(--text);font-weight:600;">标题</th>
                                            <th style="padding:10px 12px;text-align:left;color:var(--text);font-weight:600;white-space:nowrap;">模块</th>
                                            <th style="padding:10px 12px;text-align:left;color:var(--text);font-weight:600;white-space:nowrap;">👤 研发</th>
                                            <th style="padding:10px 12px;text-align:left;color:var(--text);font-weight:600;white-space:nowrap;">📅 创建时间</th>
                                            <th style="padding:10px 12px;text-align:left;color:var(--text);font-weight:600;white-space:nowrap;">🔴 严重性</th>
                                            <th style="padding:10px 12px;text-align:left;color:var(--text);font-weight:600;white-space:nowrap;">状态</th>
                                        </tr>
                                    </thead>
                                    <tbody id="stabilityIssuesBody">
                    `;
                    
                    const displayIssues = filteredIssues.slice(0, 100);
                    displayIssues.forEach((issue, idx) => {
                        const isOpen = !issue.resolved_date || issue.resolved_date === '-';
                        const statusColor = isOpen ? '#ff3b30' : '#34c759';
                        const severityColors = {
                            'blocker': '#ff3b30',
                            'critical': '#ff3b30',
                            'major': '#ff9500',
                            'minor': '#ffcc00',
                            'trivial': '#8e8e93'
                        };
                        const sev = (issue.severity || '').toLowerCase().trim();
                        const sevColor = severityColors[sev] || '#8e8e93';
                        
                        issuesHtml += `
                            <tr style="border-top:1px solid #f0f0f3;${idx % 2 === 1 ? 'background:#fafafa;' : ''}">
                                <td style="padding:8px 12px;white-space:nowrap;font-family:monospace;color:#0071e3;font-weight:600;">${escapeHtml(issue.issue_id || '-')}</td>
                                <td style="padding:8px 12px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(issue.title || '')}">${escapeHtml(issue.title || '-')}</td>
                                <td style="padding:8px 12px;white-space:nowrap;color:var(--text);">${escapeHtml(issue.module || '-')}</td>
                                <td style="padding:8px 12px;white-space:nowrap;color:var(--text);">${escapeHtml(issue.developer || '-')}</td>
                                <td style="padding:8px 12px;white-space:nowrap;color:var(--text-secondary);">${escapeHtml(issue.create_date || '-')}</td>
                                <td style="padding:8px 12px;white-space:nowrap;">
                                    <span style="background:${sevColor}20;color:${sevColor};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;">
                                        ${escapeHtml(issue.severity || '-')}
                                    </span>
                                </td>
                                <td style="padding:8px 12px;white-space:nowrap;">
                                    <span style="background:${statusColor}20;color:${statusColor};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;">
                                        ${isOpen ? '未解决' : '已解决'}
                                    </span>
                                </td>
                            </tr>
                        `;
                    });
                    
                    issuesHtml += '</tbody></table></div>';
                    if (filteredIssues.length > 100) {
                        issuesHtml += '<p style="text-align:center;color:var(--text-secondary);margin-top:12px;font-size:12px;">仅显示最近100条，共 ' + filteredIssues.length + ' 条</p>';
                    }
                    issuesHtml += '</div>';
                    stabilityIssuesSection.innerHTML = issuesHtml;
                    window._currentStabilityIssues = filteredIssues;
                } else {
                    stabilityIssuesSection.innerHTML = '';
                }
            }
        }

        function filterStabilityIssues() {
            const filter = document.getElementById('stabilityStatusFilter');
            const value = filter ? filter.value : '';
            const body = document.getElementById('stabilityIssuesBody');
            if (!body || !window._currentStabilityIssues) return;
            
            let issues = window._currentStabilityIssues;
            if (value === 'open') {
                issues = issues.filter(i => !i.resolved_date || i.resolved_date === '-');
            } else if (value === 'resolved') {
                issues = issues.filter(i => i.resolved_date && i.resolved_date !== '-');
            }
            
            const severityColors = {
                'blocker': '#ff3b30',
                'critical': '#ff3b30',
                'major': '#ff9500',
                'minor': '#ffcc00',
                'trivial': '#8e8e93'
            };
            
            let html = '';
            issues.forEach((issue, idx) => {
                const isOpen = !issue.resolved_date || issue.resolved_date === '-';
                const statusColor = isOpen ? '#ff3b30' : '#34c759';
                const sev = (issue.severity || '').toLowerCase().trim();
                const sevColor = severityColors[sev] || '#8e8e93';
                
                html += `
                    <tr style="border-top:1px solid #f0f0f3;${idx % 2 === 1 ? 'background:#fafafa;' : ''}">
                        <td style="padding:8px 12px;white-space:nowrap;font-family:monospace;color:#0071e3;font-weight:600;">${escapeHtml(issue.issue_id || '-')}</td>
                        <td style="padding:8px 12px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(issue.title || '')}">${escapeHtml(issue.title || '-')}</td>
                        <td style="padding:8px 12px;white-space:nowrap;color:var(--text);">${escapeHtml(issue.module || '-')}</td>
                        <td style="padding:8px 12px;white-space:nowrap;color:var(--text);">${escapeHtml(issue.developer || '-')}</td>
                        <td style="padding:8px 12px;white-space:nowrap;color:var(--text-secondary);">${escapeHtml(issue.create_date || '-')}</td>
                        <td style="padding:8px 12px;white-space:nowrap;">
                            <span style="background:${sevColor}20;color:${sevColor};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;">
                                ${escapeHtml(issue.severity || '-')}
                            </span>
                        </td>
                        <td style="padding:8px 12px;white-space:nowrap;">
                            <span style="background:${statusColor}20;color:${statusColor};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;">
                                ${isOpen ? '未解决' : '已解决'}
                            </span>
                        </td>
                    </tr>
                `;
            });
            body.innerHTML = html;
        }

        function renderSuggestionCard(sug) {
            const typeColors = {
                module: { bg: 'linear-gradient(135deg,#fff9e6,#fff4cc)', border: '#ffd666', text: '#8a6d00' },
                urgent: { bg: 'linear-gradient(135deg,#ffebe9,#ffd4d0)', border: '#ff6b6b', text: '#8a1f1f' },
                developer: { bg: 'linear-gradient(135deg,#e8f4ff,#d0e8ff)', border: '#4d9fff', text: '#1a4a8a' },
                warning: { bg: 'linear-gradient(135deg,#fff4e6,#ffe8cc)', border: '#ff9500', text: '#8a5a00' }
            };
            const theme = typeColors[sug.type] || typeColors.module;
            const stats = sug.stats || {};
            let statsHtml = '';
            
            if (sug.type === 'module') {
                statsHtml = `
                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px;">
                        <div style="background:rgba(255,255,255,0.7);border-radius:8px;padding:10px;text-align:center;">
                            <div style="font-size:20px;font-weight:700;color:var(--text);">${stats.total}</div>
                            <div style="font-size:11px;color:var(--text-secondary);">总数</div>
                        </div>
                        <div style="background:rgba(255,255,255,0.7);border-radius:8px;padding:10px;text-align:center;">
                            <div style="font-size:20px;font-weight:700;color:#34c759;">${stats.resolved}</div>
                            <div style="font-size:11px;color:var(--text-secondary);">已解决</div>
                        </div>
                        <div style="background:rgba(255,255,255,0.7);border-radius:8px;padding:10px;text-align:center;">
                            <div style="font-size:20px;font-weight:700;color:${parseFloat(stats.rate) >= 80 ? '#34c759' : parseFloat(stats.rate) >= 60 ? '#ff9500' : '#ff3b30'};">${stats.rate}</div>
                            <div style="font-size:11px;color:var(--text-secondary);">解决率</div>
                        </div>
                    </div>
                `;
            } else if (sug.type === 'urgent') {
                statsHtml = `
                    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:12px;">
                        <div style="background:rgba(255,255,255,0.7);border-radius:8px;padding:10px;text-align:center;">
                            <div style="font-size:20px;font-weight:700;color:var(--text);">${stats.total}</div>
                            <div style="font-size:11px;color:var(--text-secondary);">总数</div>
                        </div>
                        <div style="background:rgba(255,255,255,0.7);border-radius:8px;padding:10px;text-align:center;">
                            <div style="font-size:20px;font-weight:700;color:#ff3b30;">${stats.unresolved}</div>
                            <div style="font-size:11px;color:var(--text-secondary);">未解决</div>
                        </div>
                    </div>
                `;
            } else if (sug.type === 'developer') {
                const modules = stats.modules || [];
                statsHtml = `
                    <div style="background:rgba(255,255,255,0.7);border-radius:8px;padding:10px;margin-top:12px;">
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
                            <span style="font-size:11px;color:var(--text-secondary);">问题总数</span>
                            <span style="font-size:20px;font-weight:700;color:var(--text);">${stats.total}</span>
                        </div>
                        ${modules.length > 0 ? `
                            <div style="font-size:11px;color:var(--text-secondary);margin-bottom:4px;">涉及模块：</div>
                            <div style="display:flex;flex-wrap:wrap;gap:4px;">
                                ${modules.map(m => `<span style="background:white;border-radius:4px;padding:3px 8px;font-size:10px;color:var(--text);">${escapeHtml(m)}</span>`).join('')}
                            </div>
                        ` : ''}
                    </div>
                `;
            } else if (sug.type === 'warning') {
                statsHtml = `
                    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:12px;">
                        <div style="background:rgba(255,255,255,0.7);border-radius:8px;padding:10px;text-align:center;">
                            <div style="font-size:20px;font-weight:700;color:var(--text);">${stats.count}</div>
                            <div style="font-size:11px;color:var(--text-secondary);">模块数</div>
                        </div>
                        <div style="background:rgba(255,255,255,0.7);border-radius:8px;padding:10px;text-align:center;">
                            <div style="font-size:20px;font-weight:700;color:#ff3b30;">${stats.lowest}</div>
                            <div style="font-size:11px;color:var(--text-secondary);">最低解决率</div>
                        </div>
                    </div>
                `;
            }
            
            return `
                <div style="background:${theme.bg};border-radius:16px;padding:20px;border:1px solid ${theme.border};transition:transform 0.2s;cursor:default;">
                    <h4 style="margin:0 0 8px;color:${theme.text};font-size:14px;font-weight:700;line-height:1.4;">${escapeHtml(sug.title)}</h4>
                    <p style="margin:0;color:var(--text);font-size:13px;line-height:1.5;">${escapeHtml(sug.detail)}</p>
                    ${statsHtml}
                </div>
            `;
        }

        function renderAdviceCard(advice) {
            const adviceList = advice.advice_list || [];
            return `
                <div style="background:linear-gradient(135deg,#f0f7ff,#e6f0ff);border-radius:20px;padding:28px;border:1px solid #b3d4ff;">
                    <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
                        <span style="font-size:24px;">💡</span>
                        <h3 style="margin:0;color:#0040a0;font-size:18px;font-weight:700;">智能分析建议</h3>
                    </div>
                    <div style="display:flex;flex-direction:column;gap:12px;">
                        ${adviceList.map((item, i) => `
                            <div style="display:flex;align-items:flex-start;gap:12px;background:white;border-radius:12px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                                <div style="min-width:28px;height:28px;background:linear-gradient(135deg,#4d9fff,#0071e3);border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-size:13px;font-weight:700;">${i + 1}</div>
                                <div style="flex:1;color:var(--text);font-size:14px;line-height:1.5;">${escapeHtml(item)}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        // ===== 推送到飞书 =====
        async function pushToFeishu() {
            if (!currentAnalysisData) {
                alert('请先分析文件');
                return;
            }

            const btn = document.getElementById('pushFeishuBtn');
            const originalText = btn.innerHTML;
            btn.innerHTML = '⏳ 推送中...';
            btn.disabled = true;

            try {
                const d = currentAnalysisData;
                const s = d.summary || {};
                const fileName = d.file_name || 'CR分析报告';

                // 构建 Markdown 内容
                let md = `**📊 CR 分析报告**\n\n`;
                md += `📁 文件：${fileName}\n\n`;

                // 总览
                md += `**📈 总览**\n`;
                md += `- 问题总数：${s.total_issues || 0}\n`;
                md += `- 已解决：${s.total_resolved || 0}\n`;
                md += `- 未解决：${s.total_unresolved || 0}\n`;
                md += `- 解决率：${s.resolution_rate || 0}%\n\n`;

                // Severity 分布
                if (s.blocker_total !== undefined || s.critical_total !== undefined) {
                    md += `**⚠️ Severity 分布**\n`;
                    if (s.blocker_total !== undefined) md += `- 🔴 Blocker：${s.blocker_total} (${s.blocker_rate || 0}%)\n`;
                    if (s.critical_total !== undefined) md += `- 🟠 Critical：${s.critical_total} (${s.critical_rate || 0}%)\n`;
                    if (s.major_total !== undefined) md += `- 🟡 Major：${s.major_total} (${s.major_rate || 0}%)\n`;
                    if (s.minor_total !== undefined) md += `- 🔵 Minor：${s.minor_total} (${s.minor_rate || 0}%)\n`;
                    if (s.trivial_total !== undefined) md += `- ⚪ Trivial：${s.trivial_total} (${s.trivial_rate || 0}%)\n`;
                    if (s.blocker_critical_rate !== undefined) md += `- B+C 解决率：${s.blocker_critical_rate}% (${s.blocker_critical_total || 0})\n`;
                    md += `\n`;
                }

                // 模块统计 TOP 5
                const moduleStats = d.module_stats || {};
                const topModules = Object.entries(moduleStats)
                    .sort((a, b) => b[1].total - a[1].total)
                    .slice(0, 5);
                if (topModules.length > 0) {
                    md += `**📦 模块分布 TOP5**\n`;
                    topModules.forEach(([mod, stats], i) => {
                        const rate = stats.total > 0 ? (stats.resolved / stats.total * 100).toFixed(1) : 0;
                        md += `${i + 1}. ${mod}：${stats.total}个（已解决${stats.resolved}，解决率${rate}%）\n`;
                    });
                    md += `\n`;
                }

                // 问题遗留最多的研发 TOP10
                const devStats = d.dev_stats || {};
                const topDevs = Object.entries(devStats)
                    .sort((a, b) => (b[1].unresolved || 0) - (a[1].unresolved || 0))
                    .slice(0, 10);
                if (topDevs.length > 0) {
                    md += `**👤 问题遗留最多研发 TOP10**\n`;
                    topDevs.forEach(([dev, stats], i) => {
                        const rate = stats.total > 0 ? (stats.resolved / stats.total * 100).toFixed(1) : 0;
                        md += `${i + 1}. ${dev}：遗留${stats.unresolved || 0}个（总数${stats.total}，已解决${stats.resolved}，解决率${rate}%）\n`;
                    });
                    md += `\n`;
                }

                // 智能分析建议
                const suggestions = d.suggestions || d.analysis_suggestions || [];
                if (suggestions.length > 0) {
                    md += `**💡 智能分析建议**\n`;
                    suggestions.slice(0, 10).forEach((item, i) => {
                        let text;
                        if (typeof item === 'string') {
                            text = item;
                        } else if (item.title && item.detail) {
                            text = `${item.title}\n   ${item.detail}`;
                        } else if (item.title) {
                            text = item.title;
                        } else if (item.detail) {
                            text = item.detail;
                        } else if (item.text) {
                            text = item.text;
                        } else if (item.suggestion) {
                            text = item.suggestion;
                        } else {
                            text = JSON.stringify(item);
                        }
                        md += `${i + 1}. ${text}\n`;
                    });
                }

                // 调用飞书推送 API
                const resp = await fetch('/api/feishu/push', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        type: 'card',
                        title: `📊 CR分析报告 - ${fileName}`,
                        content: md,
                        url: window.location.href
                    })
                });

                const result = await resp.json();

                if (result.status === 'success') {
                    btn.innerHTML = '✅ 推送成功';
                    setTimeout(() => {
                        btn.innerHTML = originalText;
                        btn.disabled = false;
                    }, 2000);
                } else {
                    throw new Error(result.error || '推送失败');
                }

            } catch (err) {
                btn.innerHTML = '❌ 推送失败';
                alert(`推送失败：${err.message}`);
                setTimeout(() => {
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                }, 2000);
            }
        }

        // ===== 研发个人解单趋势 =====
        function renderDeveloperTrend() {
            const nameInput = document.getElementById('developerTrendInput');
            const name = nameInput.value.trim();
            if (!name) {
                alert('请输入研发名字');
                return;
            }
            if (!currentAnalysisData) {
                alert('请先分析文件');
                return;
            }

            const nameLower = name.toLowerCase();

            // 1. 从 dev_stats 获取准确的总数（和下方统计表一致）
            const devStats = currentAnalysisData.dev_stats || {};
            let matchedDev = null;
            let matchedStats = null;
            for (const [devName, stats] of Object.entries(devStats)) {
                const dn = devName.toLowerCase();
                if (dn === nameLower || dn.includes(nameLower) || nameLower.includes(dn)) {
                    matchedDev = devName;
                    matchedStats = stats;
                    break;
                }
            }

            // 2. 从 all_issues 筛选该研发的问题（用于趋势图）
            const issues = currentAnalysisData.all_issues || [];
            const devIssues = issues.filter(i => {
                const dev = (i.developer || '').toLowerCase();
                return dev === nameLower || dev.includes(nameLower) || nameLower.includes(dev);
            });

            if (!matchedStats && devIssues.length === 0) {
                document.getElementById('developerTrendStats').style.display = 'none';
                document.getElementById('developerTrendChart').style.display = 'none';
                document.getElementById('developerTrendEmpty').style.display = 'block';
                document.getElementById('developerTrendEmpty').innerHTML = `❌ 未找到研发「${escapeHtml(name)}」的问题记录`;
                return;
            }

            // 3. 统计总览（优先用 dev_stats 准确数据）
            let total, resolved, unresolved;
            if (matchedStats) {
                total = matchedStats.total || 0;
                resolved = matchedStats.resolved || 0;
                unresolved = matchedStats.unresolved || 0;
            } else {
                total = devIssues.length;
                resolved = 0; unresolved = 0;
                devIssues.forEach(i => {
                    const status = (i.status || '').toLowerCase();
                    const isResolved = ['resolved', 'fixed', 'closed', 'done', '已解决', '已关闭'].some(k => status.includes(k));
                    if (isResolved) resolved++; else unresolved++;
                });
            }

            // 统计 reopen 数（从 all_issues 中）
            let reopened = 0;
            devIssues.forEach(i => {
                const status = (i.status || '').toLowerCase();
                if (['reopen', 'reopened', '重新打开', '重新开启'].some(k => status.includes(k))) {
                    reopened++;
                }
            });

            // 4. 根据 all_issues 中的实际日期范围生成趋势数据（不限制30天）
            const dateSet = new Set();
            devIssues.forEach(i => {
                const resDate = normalizeDateStr((i.resolved_date || '').trim());
                const createDate = normalizeDateStr((i.create_date || '').trim());
                if (resDate) dateSet.add(resDate);
                if (createDate) dateSet.add(createDate);
            });

            let dailyData = [];
            if (dateSet.size > 0) {
                const sortedDates = Array.from(dateSet).sort();
                const startDate = new Date(sortedDates[0]);
                const endDate = new Date(sortedDates[sortedDates.length - 1]);
                const dateMap = {};
                for (let d = new Date(startDate); d <= endDate; d.setDate(d.getDate() + 1)) {
                    const dateStr = d.toISOString().split('T')[0];
                    const item = { date: dateStr, resolved: 0, reopened: 0, new: 0 };
                    dailyData.push(item);
                    dateMap[dateStr] = item;
                }

                devIssues.forEach(i => {
                    const resDate = normalizeDateStr((i.resolved_date || '').trim());
                    if (resDate && dateMap[resDate]) dateMap[resDate].resolved++;
                    const createDate = normalizeDateStr((i.create_date || '').trim());
                    if (createDate && dateMap[createDate]) dateMap[createDate].new++;
                    const status = (i.status || '').toLowerCase();
                    if (['reopen', 'reopened', '重新打开', '重新开启'].some(k => status.includes(k))) {
                        const reopenDate = normalizeDateStr((i.resolved_date || i.create_date || '').trim());
                        if (reopenDate && dateMap[reopenDate]) dateMap[reopenDate].reopened++;
                    }
                });
            }

            // 5. 渲染统计卡片
            const rate = total > 0 ? (resolved / total * 100).toFixed(1) : 0;
            const sampleWarning = (matchedStats && devIssues.length < total) ? `<div style="font-size:11px;color:var(--text-3);margin-top:8px;text-align:center;">⚠️ 趋势图基于样本数据（${devIssues.length}/${total}），完整统计以卡片数字为准</div>` : '';

            document.getElementById('developerTrendStats').style.display = 'grid';
            document.getElementById('developerTrendStats').innerHTML = `
                <div style="background:var(--bg);border-radius:12px;padding:16px;text-align:center;border:1px solid var(--border);">
                    <div style="font-size:12px;color:var(--text-3);margin-bottom:4px;">问题总数</div>
                    <div style="font-size:24px;font-weight:800;color:var(--text);">${total}</div>
                </div>
                <div style="background:rgba(52,199,89,0.1);border-radius:12px;padding:16px;text-align:center;border:1px solid rgba(52,199,89,0.2);">
                    <div style="font-size:12px;color:#34c759;margin-bottom:4px;">已解决</div>
                    <div style="font-size:24px;font-weight:800;color:#34c759;">${resolved}</div>
                </div>
                <div style="background:rgba(255,59,48,0.1);border-radius:12px;padding:16px;text-align:center;border:1px solid rgba(255,59,48,0.2);">
                    <div style="font-size:12px;color:#ff3b30;margin-bottom:4px;">未解决</div>
                    <div style="font-size:24px;font-weight:800;color:#ff3b30;">${unresolved}</div>
                </div>
                <div style="background:rgba(255,149,0,0.1);border-radius:12px;padding:16px;text-align:center;border:1px solid rgba(255,149,0,0.2);">
                    <div style="font-size:12px;color:#ff9500;margin-bottom:4px;">Reopen</div>
                    <div style="font-size:24px;font-weight:800;color:#ff9500;">${reopened}</div>
                </div>
                <div style="background:rgba(102,126,234,0.1);border-radius:12px;padding:16px;text-align:center;border:1px solid rgba(102,126,234,0.2);">
                    <div style="font-size:12px;color:#667eea;margin-bottom:4px;">解决率</div>
                    <div style="font-size:24px;font-weight:800;color:#667eea;">${rate}%</div>
                </div>
            `;

            // 渲染图表
            if (dailyData.length > 0) {
                document.getElementById('developerTrendChart').style.display = 'block';
                document.getElementById('developerTrendEmpty').style.display = 'none';
                drawDevTrendChart(dailyData, matchedDev || name);
                // 添加样本警告
                const chartEl = document.getElementById('developerTrendChart');
                const existingWarning = chartEl.querySelector('.sample-warning');
                if (existingWarning) existingWarning.remove();
                if (sampleWarning) {
                    const warningDiv = document.createElement('div');
                    warningDiv.className = 'sample-warning';
                    warningDiv.innerHTML = sampleWarning;
                    chartEl.appendChild(warningDiv);
                }
            } else {
                document.getElementById('developerTrendChart').style.display = 'none';
                document.getElementById('developerTrendEmpty').style.display = 'block';
                document.getElementById('developerTrendEmpty').innerHTML = `📊 已找到研发「${escapeHtml(matchedDev || name)}」的 ${total} 个问题，但样本数据中暂无日期信息可绘制趋势图${sampleWarning}`;
            }
        }

        function normalizeDateStr(dateStr) {
            if (!dateStr) return '';
            // 尝试多种格式
            const cleaned = dateStr.trim().replace(/[年月]/g, '-').replace(/[日]/g, '').replace(/\//g, '-').replace(/\./g, '-');
            const parts = cleaned.split(/[-T\s]/);
            if (parts.length >= 3) {
                const y = parts[0].padStart(4, '20');
                const m = parts[1].padStart(2, '0');
                const d = parts[2].padStart(2, '0');
                if (!isNaN(y) && !isNaN(m) && !isNaN(d)) {
                    return `${y}-${m}-${d}`;
                }
            }
            // 尝试 Date 解析
            const parsed = new Date(dateStr);
            if (!isNaN(parsed.getTime())) {
                return parsed.toISOString().split('T')[0];
            }
            return '';
        }

        function drawDevTrendChart(dailyData, name) {
            const canvas = document.getElementById('devTrendCanvas');
            const ctx = canvas.getContext('2d');
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width * dpr;
            canvas.height = 300 * dpr;
            ctx.scale(dpr, dpr);
            const W = rect.width;
            const H = 300;

            ctx.clearRect(0, 0, W, H);

            const padding = { top: 30, right: 20, bottom: 50, left: 50 };
            const chartW = W - padding.left - padding.right;
            const chartH = H - padding.top - padding.bottom;

            // 找最大值
            let maxVal = 1;
            dailyData.forEach(d => {
                maxVal = Math.max(maxVal, d.resolved, d.reopened, d.new);
            });
            maxVal = Math.ceil(maxVal * 1.2);

            // 画网格线
            ctx.strokeStyle = 'rgba(0,0,0,0.06)';
            ctx.lineWidth = 1;
            ctx.font = '11px sans-serif';
            ctx.fillStyle = 'rgba(0,0,0,0.4)';
            for (let i = 0; i <= 5; i++) {
                const y = padding.top + chartH - (i / 5) * chartH;
                ctx.beginPath();
                ctx.moveTo(padding.left, y);
                ctx.lineTo(W - padding.right, y);
                ctx.stroke();
                const val = Math.round((i / 5) * maxVal);
                ctx.textAlign = 'right';
                ctx.fillText(val, padding.left - 8, y + 4);
            }

            // X轴日期标签（每隔5天显示一个）
            ctx.textAlign = 'center';
            dailyData.forEach((d, i) => {
                if (i % 5 === 0 || i === dailyData.length - 1) {
                    const x = padding.left + (i / (dailyData.length - 1)) * chartW;
                    const label = d.date.slice(5); // MM-DD
                    ctx.fillText(label, x, H - padding.bottom + 20);
                }
            });

            // 画线函数
            function drawLine(data, color, fillColor) {
                ctx.beginPath();
                data.forEach((d, i) => {
                    const x = padding.left + (i / (data.length - 1)) * chartW;
                    const y = padding.top + chartH - (d / maxVal) * chartH;
                    if (i === 0) ctx.moveTo(x, y);
                    else ctx.lineTo(x, y);
                });
                ctx.strokeStyle = color;
                ctx.lineWidth = 2.5;
                ctx.stroke();

                // 填充区域
                ctx.lineTo(padding.left + chartW, padding.top + chartH);
                ctx.lineTo(padding.left, padding.top + chartH);
                ctx.closePath();
                ctx.fillStyle = fillColor;
                ctx.fill();

                // 画点
                data.forEach((d, i) => {
                    if (d > 0) {
                        const x = padding.left + (i / (data.length - 1)) * chartW;
                        const y = padding.top + chartH - (d / maxVal) * chartH;
                        ctx.beginPath();
                        ctx.arc(x, y, 3, 0, Math.PI * 2);
                        ctx.fillStyle = color;
                        ctx.fill();
                    }
                });
            }

            // 画三条线
            drawLine(dailyData.map(d => d.new), '#ff9500', 'rgba(255,149,0,0.08)');
            drawLine(dailyData.map(d => d.resolved), '#34c759', 'rgba(52,199,89,0.08)');
            drawLine(dailyData.map(d => d.reopened), '#ff3b30', 'rgba(255,59,48,0.08)');

            // 图例
            const legendY = 12;
            const legends = [
                { color: '#34c759', label: '每日解决' },
                { color: '#ff3b30', label: '每日Reopen' },
                { color: '#ff9500', label: '每日新增' }
            ];
            let legendX = padding.left;
            legends.forEach(l => {
                ctx.fillStyle = l.color;
                ctx.fillRect(legendX, legendY - 6, 12, 12);
                ctx.fillStyle = 'rgba(0,0,0,0.6)';
                ctx.font = '12px sans-serif';
                ctx.textAlign = 'left';
                ctx.fillText(l.label, legendX + 16, legendY + 4);
                legendX += 100;
            });
        }
