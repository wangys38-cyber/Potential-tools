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

        const editor = document.getElementById('editor');
        const preview = document.getElementById('preview');
        const convertBtn = document.getElementById('convertBtn');
        const uploadBtn = document.getElementById('uploadBtn');
        const wordBtn = document.getElementById('wordBtn');
        const downloadBtn = document.getElementById('downloadBtn');
        const convertSpinner = document.getElementById('convertSpinner');
        const uploadSpinner = document.getElementById('uploadSpinner');
        const convertText = document.getElementById('convertText');
        const uploadText = document.getElementById('uploadText');
        const watermark = document.getElementById('watermark');
        const watermarkInput = document.getElementById('watermarkInput');
        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('fileInput');
        const wordFileInput = document.createElement('input');
        wordFileInput.type = 'file';
        wordFileInput.accept = '.docx';
        wordFileInput.style.display = 'none';

        const batchFileInput = document.createElement('input');
        batchFileInput.type = 'file';
        batchFileInput.id = 'batchFileInput';
        batchFileInput.accept = '.md,.docx';
        batchFileInput.multiple = true;
        batchFileInput.style.display = 'none';

        document.body.appendChild(wordFileInput);
        document.body.appendChild(batchFileInput);

        const batchBtn = document.getElementById('batchBtn');
        const progressContainer = document.getElementById('progressContainer');
        const progressInfo = document.getElementById('progressInfo');
        const progressFill = document.getElementById('progressFill');
        const fileList = document.getElementById('fileList');
        const downloadAllBtn = document.getElementById('downloadAllBtn');

        let previewTimeout;
        let currentFilename = '';
        let successFiles = [];

        function getWatermarkText() {
            const custom = watermarkInput.value.trim();
            if (custom) {
                return custom;
            }
            const today = new Date();
            const year = today.getFullYear();
            const month = String(today.getMonth() + 1).padStart(2, '0');
            const day = String(today.getDate()).padStart(2, '0');
            return `Motorola ${year}年${month}月${day}日`;
        }

        function updateDate() {
            watermark.textContent = getWatermarkText();
        }

        updateDate();

        watermarkInput.addEventListener('input', () => {
            updateDate();
            clearTimeout(previewTimeout);
            previewTimeout = setTimeout(updatePreview, 300);
        });

        async function updatePreview() {
            const content = editor.value;
            const watermarkText = getWatermarkText();

            if (!content.trim()) {
                preview.innerHTML = '<p style="text-align: center; color: #999; margin-top: 50px;">输入内容后将在这里显示预览效果</p>';
                return;
            }

            try {
                const response = await fetch('/preview', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ content, watermark: watermarkText }),
                });

                const data = await response.json();
                preview.innerHTML = data.html;

                // 渲染 Mermaid 图表
                if (data.has_mermaid && window.mermaid) {
                    try {
                        const mermaidElements = preview.querySelectorAll('.mermaid');
                        mermaidElements.forEach((el, idx) => {
                            if (!el.getAttribute('data-processed')) {
                                el.id = 'mermaid-' + Date.now() + '-' + idx;
                                mermaid.run({ nodes: [el] }).catch(() => {});
                            }
                        });
                    } catch (e) {
                        console.error('Mermaid render error:', e);
                    }
                }
            } catch (error) {
                console.error('Preview error:', error);
            }
        }

        editor.addEventListener('input', () => {
            clearTimeout(previewTimeout);
            previewTimeout = setTimeout(updatePreview, 300);
        });

        convertBtn.addEventListener('click', async () => {
            const content = editor.value;
            const watermarkText = getWatermarkText();

            if (!content.trim()) {
                showToast('请输入内容', 'info');
                return;
            }

            convertBtn.disabled = true;
            convertSpinner.style.display = 'block';
            convertText.textContent = '转换中...';

            try {
                const response = await fetch('/convert', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ content, filename: currentFilename, watermark: watermarkText }),
                });

                const data = await response.json();

                if (data.error) {
                    showToast('转换失败：' + data.error, 'error');
                } else if (data.status === 'success' && data.data && data.data.task_id) {
                    // 轮询后台 PDF 渲染任务
                    const taskId = data.data.task_id;
                    let pollCount = 0;
                    const maxPolls = 280;
                    let pdfFilename = null;
                    while (pollCount < maxPolls) {
                        await new Promise(r => setTimeout(r, 1000));
                        const statusResp = await fetch('/api/task-status', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ task_id: taskId })
                        });
                        const statusResult = await statusResp.json();
                        if (statusResult.status === 'done') {
                            pdfFilename = statusResult.data.filename;
                            break;
                        } else if (statusResult.status === 'error') {
                            throw new Error(statusResult.error || 'PDF渲染失败');
                        }
                        pollCount++;
                        convertText.textContent = `转换中... (${pollCount}s)`;
                    }
                    if (!pdfFilename) {
                        throw new Error('转换超时，请重试');
                    }
                    downloadBtn.disabled = false;
                    downloadBtn.onclick = () => {
                        const a = document.createElement('a');
                        a.href = `/download/${pdfFilename}`;
                        a.download = pdfFilename;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    };
                    showToast('转换成功！点击下载按钮获取PDF', 'success');
                }
            } catch (error) {
                showToast('转换失败：' + error.message, 'error');
            } finally {
                convertBtn.disabled = false;
                convertSpinner.style.display = 'none';
                convertText.textContent = '转换为PDF';
            }
        });

        wordBtn.addEventListener('click', () => {
            wordFileInput.click();
        });

        wordFileInput.addEventListener('change', async (e) => {
            const files = e.target.files;
            if (files.length === 0) return;

            const file = files[0];

            if (!file.name.toLowerCase().endsWith('.docx')) {
                showToast('只支持Word文件(.docx)', 'info');
                return;
            }

            const watermarkText = getWatermarkText();

            uploadBtn.disabled = true;
            uploadSpinner.style.display = 'block';
            uploadText.textContent = 'Word转换中...';

            const formData = new FormData();
            formData.append('file', file);
            formData.append('watermark', watermarkText);

            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData,
                });

                const data = await response.json();

                if (data.error) {
                    showToast('转换失败：' + data.error, 'error');
                } else {
                    downloadBtn.disabled = false;
                    downloadBtn.onclick = () => {
                        const a = document.createElement('a');
                        a.href = `/download/${data.filename}`;
                        a.download = `${data.filename}`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    };
                    showToast(`文件 "${data.original_name}.docx" 转换成功！点击下载按钮获取PDF`, 'success');
                }
            } catch (error) {
                showToast('转换失败：' + error.message, 'error');
            } finally {
                uploadBtn.disabled = false;
                uploadSpinner.style.display = 'none';
                uploadText.textContent = 'markdown转PDF';
                wordFileInput.value = '';
            }
        });

        uploadArea.addEventListener('click', () => {
            fileInput.click();
        });

        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('active');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('active');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('active');

            const files = e.dataTransfer.files;
            if (files.length > 0) {
                if (files.length === 1) {
                    handleFile(files[0]);
                } else {
                    const validFiles = Array.from(files).filter(f =>
                        f.name.toLowerCase().endsWith('.md') || f.name.toLowerCase().endsWith('.docx')
                    );
                    if (validFiles.length > 0) {
                        startBatchConvert(validFiles);
                    } else {
                        showToast('请选择Markdown文件(.md)或Word文件(.docx)', 'info');
                    }
                }
            }
        });

        let pendingDirectConvert = false;

        fileInput.addEventListener('change', async (e) => {
            const files = e.target.files;
            if (files.length === 0) return;
            const file = files[0];

            if (pendingDirectConvert) {
                pendingDirectConvert = false;
                await directConvertFile(file);
            } else {
                handleFile(file);
            }
        });

        async function directConvertFile(file) {
            const ext = file.name.toLowerCase();

            if (isExcelFile(file)) {
                handleExcelFile(file);
                fileInput.value = '';
                return;
            }

            if (!ext.endsWith('.md') && !ext.endsWith('.docx')) {
                showToast('只支持Markdown文件(.md)和Word文件(.docx)', 'info');
                return;
            }

            const watermarkText = getWatermarkText();

            uploadBtn.disabled = true;
            uploadSpinner.style.display = 'block';
            uploadText.textContent = '上传转换中...';

            const formData = new FormData();
            formData.append('file', file);
            formData.append('watermark', watermarkText);

            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData,
                });

                const data = await response.json();

                if (data.error) {
                    showToast('转换失败：' + data.error, 'error');
                } else {
                    downloadBtn.disabled = false;
                    downloadBtn.onclick = () => {
                        const a = document.createElement('a');
                        a.href = `/download/${data.filename}`;
                        a.download = `${data.filename}`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    };
                    showToast(`文件 "${data.original_name}.${ext.endsWith('.md') ? 'md' : 'docx'}" 转换成功！点击下载按钮获取PDF`, 'success');
                }
            } catch (error) {
                showToast('转换失败：' + error.message, 'error');
            } finally {
                uploadBtn.disabled = false;
                uploadSpinner.style.display = 'none';
                uploadText.textContent = 'markdown转PDF';
                fileInput.value = '';
            }
        }

        function handleFile(file) {
            const ext = file.name.toLowerCase();
            if (isExcelFile(file)) {
                handleExcelFile(file);
                return;
            }

            if (!ext.endsWith('.md') && !ext.endsWith('.docx')) {
                showToast('只支持Markdown文件(.md)、Word文件(.docx)和Excel文件(.xlsx/.xls)', 'info');
                return;
            }

            currentFilename = file.name.replace(/\.(md|docx)$/i, '');

            if (ext.endsWith('.md')) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    editor.value = e.target.result;
                    updatePreview();
                };
                reader.readAsText(file, 'utf-8');
            } else {
                showToast('Word文件已加载，请点击"Word转PDF"按钮进行转换', 'success');
            }
        }

        uploadBtn.addEventListener('click', () => {
            pendingDirectConvert = true;
            fileInput.click();
        });

        batchBtn.addEventListener('click', () => {
            batchFileInput.click();
        });

        batchFileInput.addEventListener('change', async (e) => {
            const files = e.target.files;
            if (files.length === 0) return;

            const validFiles = Array.from(files).filter(f => 
                f.name.toLowerCase().endsWith('.md') || f.name.toLowerCase().endsWith('.docx')
            );

            if (validFiles.length === 0) {
                showToast('请选择Markdown文件(.md)或Word文件(.docx)', 'info');
                return;
            }

            startBatchConvert(validFiles);
        });

        async function startBatchConvert(files) {
            const watermarkText = getWatermarkText();
            
            progressContainer.classList.add('show');
            fileList.innerHTML = '';
            successFiles = [];
            downloadAllBtn.classList.remove('show');

            files.forEach((file, index) => {
                const fileItem = document.createElement('div');
                fileItem.className = 'file-item';
                fileItem.id = `file-${index}`;
                fileItem.innerHTML = `
                    <div class="file-info">
                        <span class="file-icon">${file.name.toLowerCase().endsWith('.md') ? '' : ''}</span>
                        <span class="file-name">${escapeHtml(file.name)}</span>
                    </div>
                    <span class="file-status processing">处理中...</span>
                `;
                fileList.appendChild(fileItem);
            });

            progressInfo.textContent = `0/${files.length} 文件`;
            progressFill.style.width = '0%';

            const formData = new FormData();
            files.forEach(file => {
                formData.append('files[]', file);
            });
            formData.append('watermark', watermarkText);

            batchBtn.disabled = true;
            convertBtn.disabled = true;
            uploadBtn.disabled = true;
            wordBtn.disabled = true;

            try {
                const response = await fetch('/batch-upload', {
                    method: 'POST',
                    body: formData,
                });

                const data = await response.json();

                data.results.forEach((result, index) => {
                    const fileItem = document.getElementById(`file-${index}`);
                    if (fileItem) {
                        if (result.status === 'success') {
                            fileItem.classList.add('success');
                            fileItem.innerHTML = `
                                <div class="file-info">
                                    <span class="file-icon">${result.original_name.toLowerCase().endsWith('.md') ? '' : ''}</span>
                                    <span class="file-name">${escapeHtml(result.original_name)}</span>
                                </div>
                                <span class="file-status success">✓ 成功</span>
                            `;
                            successFiles.push(result.pdf_filename);
                        } else {
                            fileItem.classList.add('failed');
                            fileItem.innerHTML = `
                                <div class="file-info">
                                    <span class="file-icon">${result.original_name.toLowerCase().endsWith('.md') ? '' : ''}</span>
                                    <span class="file-name">${escapeHtml(result.original_name)}</span>
                                </div>
                                <span class="file-status failed">✗ 失败</span>
                            `;
                        }
                    }
                });

                progressInfo.textContent = `${data.success_count}/${files.length} 文件`;
                progressFill.style.width = `${(data.success_count / files.length) * 100}%`;

                if (successFiles.length > 0) {
                    downloadAllBtn.classList.add('show');
                    showToast(`批量转换完成！成功: ${data.success_count}, 失败: ${data.fail_count}`, 'success');
                } else {
                    showToast('所有文件转换失败，请检查文件格式', 'error');
                }
            } catch (error) {
                showToast('批量转换失败：' + error.message, 'error');
            } finally {
                batchBtn.disabled = false;
                convertBtn.disabled = false;
                uploadBtn.disabled = false;
                wordBtn.disabled = false;
                batchFileInput.value = '';
            }
        }

        downloadAllBtn.addEventListener('click', () => {
            successFiles.forEach((filename, index) => {
                setTimeout(() => {
                    const a = document.createElement('a');
                    a.href = `/download/${filename}`;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                }, index * 500);
            });
        });

        let excelFileData = null;
        let structuredData = null;
        let selectedSheets = new Set();

        const excelActions = document.getElementById('excelActions');
        const excelParseBtn = document.getElementById('excelParseBtn');
        const excelParseText = document.getElementById('excelParseText');
        const excelCancelBtn = document.getElementById('excelCancelBtn');
        const excelPanel = document.getElementById('excelPanel');
        const excelSummary = document.getElementById('excelSummary');
        const excelSheets = document.getElementById('excelSheets');
        const excelGenerateBtn = document.getElementById('excelGenerateBtn');
        const excelGenerateText = document.getElementById('excelGenerateText');
        const excelSpinner = document.getElementById('excelSpinner');
        const excelSelectedInfo = document.getElementById('excelSelectedInfo');

        function isExcelFile(file) {
            const name = file.name.toLowerCase();
            return name.endsWith('.xlsx') || name.endsWith('.xls');
        }

        function handleExcelFile(file) {
            excelFileData = file;
            excelActions.style.display = 'flex';
            excelPanel.style.display = 'none';
            excelModeSwitch.style.display = 'none';
            excelSelectArea.style.display = 'none';
            excelOrganizeArea.classList.remove('show');
            excelPreviewArea.classList.remove('show');
            // 滚动到按钮位置，确保用户可见
            setTimeout(() => {
                excelActions.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 100);
            showToast('Excel文件已加载，点击"解析Excel文件"按钮开始分析', 'success');
        }

        excelCancelBtn.addEventListener('click', () => {
            excelFileData = null;
            structuredData = null;
            organizedData = null;
            selectedSheets.clear();
            excelActions.style.display = 'none';
            excelPanel.style.display = 'none';
            excelOrganizeArea.classList.remove('show');
            excelPreviewArea.classList.remove('show');
            excelOrganizeInput.value = '';
            fileInput.value = '';
        });

        excelParseBtn.addEventListener('click', async () => {
            if (!excelFileData) return;

            excelParseBtn.disabled = true;
            excelParseText.textContent = '解析中...';

            const watermarkText = getWatermarkText();
            const formData = new FormData();
            formData.append('file', excelFileData);

            try {
                const response = await fetch('/excel-parse', {
                    method: 'POST',
                    body: formData,
                });

                const result = await response.json();

                if (result.error) {
                    showToast('Excel解析失败：' + result.error, 'error');
                } else {
                    structuredData = result.data;
                    renderExcelPanel(structuredData);
                    excelPanel.style.display = 'block';
                }
            } catch (error) {
                showToast('Excel解析失败：' + error.message, 'error');
            } finally {
                excelParseBtn.disabled = false;
                excelParseText.textContent = '重新解析';
            }
        });

        function renderExcelPanel(data) {
            selectedSheets.clear();

            const fileStats = document.createElement('div');
            fileStats.className = 'excel-summary';
            const totalRows = data.sheets.reduce((sum, s) => sum + s.row_count, 0);
            const totalCols = data.sheets.reduce((sum, s) => sum + s.column_count, 0);
            fileStats.innerHTML = `
                <div class="excel-summary-item">
                    <span class="label">文件</span>
                    <span class="value" style="font-size: 14px;">${escapeHtml(data.file_name)}</span>
                </div>
                <div class="excel-summary-item">
                    <span class="label">工作表</span>
                    <span class="value">${data.total_sheets}</span>
                </div>
                <div class="excel-summary-item">
                    <span class="label">数据行</span>
                    <span class="value">${totalRows}</span>
                </div>
                <div class="excel-summary-item">
                    <span class="label">数据列</span>
                    <span class="value">${totalCols}</span>
                </div>
            `;
            excelSummary.innerHTML = '';
            excelSummary.appendChild(fileStats);

            excelSheets.innerHTML = '';
            data.sheets.forEach((sheet, index) => {
                const card = document.createElement('div');
                card.className = 'excel-sheet-card';
                card.dataset.sheetName = sheet.name;

                const categoriesHtml = Object.entries(sheet.categories).map(([label, cols]) => {
                    const colNames = cols.map(c => c.name).join('、');
                    return `<span class="excel-category-tag">${label}<span class="cols"> · ${colNames}</span></span>`;
                }).join('');

                let previewHtml = '';
                if (sheet.data_preview && sheet.data_preview.length > 0) {
                    const headersHtml = sheet.headers.map(h => `<th>${h}</th>`).join('');
                    const rowsHtml = sheet.data_preview.slice(0, 5).map(row => {
                        return `<tr>${row.map(cell => `<td>${String(cell).substring(0, 30)}</td>`).join('')}</tr>`;
                    }).join('');
                    const moreRows = sheet.row_count - sheet.data_preview.length;
                    previewHtml = `
                        <div class="excel-data-preview">
                            <table>
                                <thead><tr>${headersHtml}</tr></thead>
                                <tbody>${rowsHtml}</tbody>
                            </table>
                            ${moreRows > 0 ? `<div class="more-rows">... 还有 ${moreRows} 行数据</div>` : ''}
                        </div>
                    `;
                }

                card.innerHTML = `
                    <div class="excel-sheet-header">
                        <div class="excel-sheet-check"></div>
                        <div class="excel-sheet-info">
                            <div class="excel-sheet-name"> ${sheet.name}</div>
                            <div class="excel-sheet-meta">${sheet.row_count} 行 × ${sheet.column_count} 列 · ${sheet.summary}</div>
                        </div>
                        <div class="excel-sheet-toggle">▶</div>
                    </div>
                    <div class="excel-sheet-detail">
                        <div class="excel-categories">${categoriesHtml}</div>
                        ${previewHtml}
                    </div>
                `;

                const header = card.querySelector('.excel-sheet-header');
                header.addEventListener('click', (e) => {
                    if (e.target.closest('.excel-sheet-check')) return;
                    card.classList.toggle('expanded');
                });

                const check = card.querySelector('.excel-sheet-check');
                check.addEventListener('click', (e) => {
                    e.stopPropagation();
                    toggleSheetSelection(sheet.name, card);
                });

                card.querySelector('.excel-sheet-info').addEventListener('click', () => {
                    toggleSheetSelection(sheet.name, card);
                });

                excelSheets.appendChild(card);

                if (index === 0) {
                    card.classList.add('selected');
                    selectedSheets.add(sheet.name);
                    card.classList.add('expanded');
                }
            });

            updateSelectedInfo();
            excelOrganizeArea.classList.add('show');
            initManualSelectMode();
        }

        function toggleSheetSelection(sheetName, card) {
            if (selectedSheets.has(sheetName)) {
                selectedSheets.delete(sheetName);
                card.classList.remove('selected');
            } else {
                selectedSheets.add(sheetName);
                card.classList.add('selected');
            }
            updateSelectedInfo();
        }

        function updateSelectedInfo() {
            excelSelectedInfo.innerHTML = `已选择 <strong>${selectedSheets.size}</strong> 个工作表`;
        }

        let organizedData = null;

        const excelOrganizeArea = document.getElementById('excelOrganizeArea');
        const excelOrganizeInput = document.getElementById('excelOrganizeInput');
        const excelOrganizeBtn = document.getElementById('excelOrganizeBtn');
        const excelOrganizeSpinner = document.getElementById('excelOrganizeSpinner');
        const excelOrganizeText = document.getElementById('excelOrganizeText');
        const excelPreviewArea = document.getElementById('excelPreviewArea');
        const excelPreviewContent = document.getElementById('excelPreviewContent');
        const excelPreviewSummary = document.getElementById('excelPreviewSummary');
        const excelPreviewBackBtn = document.getElementById('excelPreviewBackBtn');
        const excelPreviewGenerateBtn = document.getElementById('excelPreviewGenerateBtn');
        const excelPreviewSpinner = document.getElementById('excelPreviewSpinner');
        const excelPreviewGenerateText = document.getElementById('excelPreviewGenerateText');

        document.querySelectorAll('.tip-item').forEach(item => {
            item.addEventListener('click', () => {
                const text = item.dataset.text;
                const current = excelOrganizeInput.value;
                excelOrganizeInput.value = current ? current + '\n' + text : text;
            });
        });

        excelOrganizeBtn.addEventListener('click', async () => {
            if (!structuredData) {
                showToast('请先解析Excel文件', 'info');
                return;
            }

            const userRequest = excelOrganizeInput.value.trim();
            if (!userRequest) {
                showToast('请输入您想要整理的内容', 'info');
                excelOrganizeInput.focus();
                return;
            }

            excelOrganizeBtn.disabled = true;
            excelOrganizeSpinner.style.display = 'block';
            excelOrganizeText.textContent = '整理中...';

            try {
                const response = await fetch('/excel-organize', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        structured_data: structuredData,
                        user_request: userRequest,
                        selected_sheets: Array.from(selectedSheets)
                    }),
                });

                const result = await response.json();

                if (result.error) {
                    showToast('整理失败：' + result.error, 'error');
                } else {
                    organizedData = result.data;
                    organizedData.user_request = userRequest;
                    renderPreview(organizedData);
                    excelPreviewArea.classList.add('show');
                    excelPreviewArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            } catch (error) {
                showToast('整理失败：' + error.message, 'error');
            } finally {
                excelOrganizeBtn.disabled = false;
                excelOrganizeSpinner.style.display = 'none';
                excelOrganizeText.textContent = ' 智能整理预览';
            }
        });

        function renderPreview(data) {
            excelPreviewSummary.textContent = data.summary || '';
            excelPreviewContent.innerHTML = data.html || '<p style="text-align:center; color:#999;">暂无预览内容</p>';
        }

        excelPreviewBackBtn.addEventListener('click', () => {
            excelPreviewArea.classList.remove('show');
            excelOrganizeArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });

        excelPreviewGenerateBtn.addEventListener('click', async () => {
            if (!organizedData) {
                showToast('请先整理预览', 'info');
                return;
            }

            const watermarkText = getWatermarkText();

            excelPreviewGenerateBtn.disabled = true;
            excelPreviewSpinner.style.display = 'block';
            excelPreviewGenerateText.textContent = '生成中...';

            try {
                const response = await fetch('/excel-organize-pdf', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        organized_data: {
                            sections: organizedData.sections,
                            user_request: organizedData.user_request,
                            summary: organizedData.summary
                        },
                        watermark: watermarkText
                    }),
                });

                const data = await response.json();

                if (data.error) {
                    showToast('PDF生成失败：' + data.error, 'error');
                } else {
                    const a = document.createElement('a');
                    a.href = `/download/${data.filename}`;
                    a.download = data.filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    showToast('PDF报告生成成功！已开始下载', 'success');
                }
            } catch (error) {
                showToast('PDF生成失败：' + error.message, 'error');
            } finally {
                excelPreviewGenerateBtn.disabled = false;
                excelPreviewSpinner.style.display = 'none';
                excelPreviewGenerateText.textContent = '✓ 确认生成PDF';
            }
        });

        excelGenerateBtn.addEventListener('click', async () => {
            if (!structuredData || selectedSheets.size === 0) {
                showToast('请先解析Excel文件并选择至少一个工作表', 'info');
                return;
            }

            const watermarkText = getWatermarkText();
            const customTitle = document.getElementById('excelCustomTitle').value.trim();

            excelGenerateBtn.disabled = true;
            excelSpinner.style.display = 'block';
            excelGenerateText.textContent = '生成中...';

            try {
                const response = await fetch('/excel-pdf', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        structured_data: structuredData,
                        selected_sheets: Array.from(selectedSheets),
                        watermark: watermarkText,
                        custom_title: customTitle
                    }),
                });

                const data = await response.json();

                if (data.error) {
                    showToast('PDF生成失败：' + data.error, 'error');
                } else {
                    const a = document.createElement('a');
                    a.href = `/download/${data.filename}`;
                    a.download = data.download_name || data.filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    showToast('PDF报告生成成功！已开始下载', 'success');
                }
            } catch (error) {
                showToast('PDF生成失败：' + error.message, 'error');
            } finally {
                excelGenerateBtn.disabled = false;
                excelSpinner.style.display = 'none';
                excelGenerateText.textContent = '生成PDF报告';
            }
        });

        const excelModeSwitch = document.getElementById('excelModeSwitch');
        const modeAIBtn = document.getElementById('modeAI');
        const modeManualBtn = document.getElementById('modeManual');
        const excelSelectArea = document.getElementById('excelSelectArea');
        const excelSelectTabs = document.getElementById('excelSelectTabs');
        const excelSelectTable = document.getElementById('excelSelectTable');
        const selectedRowCount = document.getElementById('selectedRowCount');
        const excelSelectSummary = document.getElementById('excelSelectSummary');
        const excelSelectGenerateBtn = document.getElementById('excelSelectGenerateBtn');
        const excelSelectSpinner = document.getElementById('excelSelectSpinner');
        const excelSelectGenerateText = document.getElementById('excelSelectGenerateText');
        const selectAllRowsBtn = document.getElementById('selectAllRows');
        const deselectAllRowsBtn = document.getElementById('deselectAllRows');
        const invertSelectionBtn = document.getElementById('invertSelection');

        let currentMode = 'ai';
        let currentTabSheet = null;
        let selectedRowsMap = {};
        let selectedColsMap = {};
        let sheetFullData = {};

        function initManualSelectMode() {
            if (!structuredData) return;

            excelModeSwitch.style.display = 'flex';

            structuredData.sheets.forEach(sheet => {
                // 使用完整数据 (sheet.rows) 或 data_preview 作为备选
                const fullRows = sheet.rows || sheet.data_preview || [];
                sheetFullData[sheet.name] = {
                    headers: sheet.headers,
                    rows: sheet.data_preview || [],
                    all_rows: fullRows,
                    header_merges: sheet.header_merges || [],
                    data_merges: sheet.data_merges || []
                };
                selectedRowsMap[sheet.name] = new Set();
                selectedColsMap[sheet.name] = new Set(sheet.headers.map((_, i) => i));
            });

            renderSelectTabs();
            switchMode('ai');
        }

        function renderSelectTabs() {
            excelSelectTabs.innerHTML = '';
            structuredData.sheets.forEach((sheet, index) => {
                const tab = document.createElement('div');
                tab.className = 'excel-select-tab' + (index === 0 ? ' active' : '');
                tab.dataset.sheetName = sheet.name;
                const totalRows = sheet.all_data ? sheet.all_data.length : (sheet.data_preview ? sheet.data_preview.length : 0);
                tab.innerHTML = ` ${sheet.name}<span class="row-count">${totalRows}行</span>`;
                tab.addEventListener('click', () => {
                    document.querySelectorAll('.excel-select-tab').forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    renderSelectTable(sheet.name);
                });
                excelSelectTabs.appendChild(tab);

                if (index === 0) {
                    currentTabSheet = sheet.name;
                    renderSelectTable(sheet.name);
                }
            });
        }

        function renderSelectTable(sheetName) {
            const sheetData = sheetFullData[sheetName];
            if (!sheetData) return;

            const headers = sheetData.headers;
            const rows = sheetData.all_rows.length > 0 ? sheetData.all_rows : sheetData.rows;
            const selectedCols = selectedColsMap[sheetName];
            const headerMerges = sheetData.header_merges || [];
            const dataMerges = sheetData.data_merges || [];

            const headerMergedMap = buildMergeMap(headerMerges, headers.length, 1);
            const dataMergedMap = buildMergeMap(dataMerges, headers.length, rows.length);

            let html = '<thead><tr><th rowspan="2" style="width:40px;"><input type="checkbox" class="excel-checkbox" id="selectAllCheckbox"></th>';
            
            const renderedHeaderCells = new Set();
            headers.forEach((h, colIdx) => {
                if (renderedHeaderCells.has(colIdx)) return;
                
                const mergeInfo = headerMergedMap[colIdx];
                const isColSelected = selectedCols.has(colIdx);
                
                if (mergeInfo) {
                    for (let c = colIdx; c < colIdx + mergeInfo.colspan; c++) {
                        renderedHeaderCells.add(c);
                    }
                    html += `<th colspan="${mergeInfo.colspan}"><div style="display:flex;align-items:center;gap:4px;"><input type="checkbox" class="excel-checkbox col-checkbox" data-col-idx="${colIdx}" ${isColSelected ? 'checked' : ''} style="width:14px;height:14px;"><span>${h}</span></div></th>`;
                } else {
                    renderedHeaderCells.add(colIdx);
                    html += `<th><div style="display:flex;align-items:center;gap:4px;"><input type="checkbox" class="excel-checkbox col-checkbox" data-col-idx="${colIdx}" ${isColSelected ? 'checked' : ''} style="width:14px;height:14px;"><span>${h}</span></div></th>`;
                }
            });
            html += '</tr></thead><tbody>';

            const renderedCells = new Set();
            rows.forEach((row, rowIdx) => {
                const isSelected = selectedRowsMap[sheetName].has(rowIdx);
                html += `<tr data-row-idx="${rowIdx}" class="${isSelected ? 'selected' : ''}">`;
                html += `<td class="row-checkbox-cell"><input type="checkbox" class="excel-checkbox row-checkbox" data-row-idx="${rowIdx}" ${isSelected ? 'checked' : ''}></td>`;
                
                for (let colIdx = 0; colIdx < headers.length; colIdx++) {
                    const cellKey = `${rowIdx}_${colIdx}`;
                    if (renderedCells.has(cellKey)) continue;
                    
                    const mergeInfo = dataMergedMap[colIdx] ? dataMergedMap[colIdx][rowIdx] : null;
                    const cellVal = row[colIdx] !== null && row[colIdx] !== undefined ? String(row[colIdx]) : '';
                    
                    if (mergeInfo) {
                        for (let r = rowIdx; r < rowIdx + mergeInfo.rowspan; r++) {
                            for (let c = colIdx; c < colIdx + mergeInfo.colspan; c++) {
                                renderedCells.add(`${r}_${c}`);
                            }
                        }
                        html += `<td rowspan="${mergeInfo.rowspan}" colspan="${mergeInfo.colspan}">${cellVal.substring(0, 100)}</td>`;
                    } else {
                        renderedCells.add(cellKey);
                        html += `<td>${cellVal.substring(0, 100)}</td>`;
                    }
                }
                html += '</tr>';
            });

            html += '</tbody>';
            excelSelectTable.innerHTML = html;

            const selectAllCheckbox = document.getElementById('selectAllCheckbox');
            if (selectAllCheckbox) {
                const selectedCount = selectedRowsMap[sheetName].size;
                selectAllCheckbox.checked = selectedCount === rows.length && rows.length > 0;
                selectAllCheckbox.addEventListener('change', (e) => {
                    const checked = e.target.checked;
                    document.querySelectorAll('.row-checkbox').forEach(cb => {
                        cb.checked = checked;
                        const rowIdx = parseInt(cb.dataset.rowIdx);
                        const tr = cb.closest('tr');
                        if (checked) {
                            selectedRowsMap[sheetName].add(rowIdx);
                            tr.classList.add('selected');
                        } else {
                            selectedRowsMap[sheetName].delete(rowIdx);
                            tr.classList.remove('selected');
                        }
                    });
                    updateSelectedRowCount();
                });
            }

            document.querySelectorAll('.col-checkbox').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    const colIdx = parseInt(e.target.dataset.colIdx);
                    if (e.target.checked) {
                        selectedColsMap[sheetName].add(colIdx);
                    } else {
                        selectedColsMap[sheetName].delete(colIdx);
                    }
                    renderSelectTable(sheetName);
                    updateSelectedRowCount();
                });
            });

            document.querySelectorAll('.row-checkbox').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    const rowIdx = parseInt(e.target.dataset.rowIdx);
                    const tr = e.target.closest('tr');
                    if (e.target.checked) {
                        selectedRowsMap[sheetName].add(rowIdx);
                        tr.classList.add('selected');
                    } else {
                        selectedRowsMap[sheetName].delete(rowIdx);
                        tr.classList.remove('selected');
                    }
                    updateSelectedRowCount();
                });
            });

            excelSelectTable.querySelectorAll('tbody tr').forEach(tr => {
                tr.addEventListener('click', (e) => {
                    if (e.target.classList.contains('excel-checkbox')) return;
                    const cb = tr.querySelector('.row-checkbox');
                    if (cb) {
                        cb.checked = !cb.checked;
                        cb.dispatchEvent(new Event('change'));
                    }
                });
            });
        }

        function buildMergeMap(merges, maxCols, maxRows) {
            const mergeMap = {};
            for (const merge of merges) {
                const { row, col, rowspan, colspan } = merge;
                if (row < 0 || col < 0) continue;
                if (!mergeMap[col]) mergeMap[col] = {};
                mergeMap[col][row] = { rowspan, colspan };
            }
            return mergeMap;
        }

        function updateSelectedRowCount() {
            let totalRows = 0;
            let totalCols = 0;
            Object.values(selectedRowsMap).forEach(set => totalRows += set.size);
            Object.values(selectedColsMap).forEach(set => totalCols += set.size);
            selectedRowCount.textContent = `${totalRows}行 / ${totalCols}列`;
            
            const activeSheets = Object.keys(selectedRowsMap).filter(k => selectedRowsMap[k].size > 0);
            const activeColSheets = Object.keys(selectedColsMap).filter(k => selectedColsMap[k].size > 0 && selectedColsMap[k].size === sheetFullData[k]?.headers?.length);
            
            if (totalRows > 0 && totalCols > 0) {
                excelSelectSummary.textContent = `已从 ${activeSheets.length} 个工作表中选择了 ${totalRows} 行 × ${totalCols} 列数据`;
            } else if (totalRows > 0) {
                excelSelectSummary.textContent = `已选择 ${totalRows} 行数据`;
            } else if (totalCols > 0) {
                excelSelectSummary.textContent = `已选择 ${totalCols} 列数据`;
            } else {
                excelSelectSummary.textContent = '请选择需要导出的数据行和列';
            }
        }

        function switchMode(mode) {
            currentMode = mode;
            if (mode === 'ai') {
                modeAIBtn.classList.add('active');
                modeManualBtn.classList.remove('active');
                excelSelectArea.classList.remove('show');
                excelPanel.style.display = 'block';
                excelOrganizeArea.classList.add('show');
                excelPreviewArea.classList.remove('show');
            } else {
                modeManualBtn.classList.add('active');
                modeAIBtn.classList.remove('active');
                excelPanel.style.display = 'none';
                excelOrganizeArea.classList.remove('show');
                excelPreviewArea.classList.remove('show');
                excelSelectArea.classList.add('show');
            }
        }

        modeAIBtn.addEventListener('click', () => switchMode('ai'));
        modeManualBtn.addEventListener('click', () => switchMode('manual'));

        selectAllRowsBtn.addEventListener('click', () => {
            if (!currentTabSheet) return;
            const sheetData = sheetFullData[currentTabSheet];
            if (!sheetData) return;
            const rows = sheetData.all_rows.length > 0 ? sheetData.all_rows : sheetData.rows;
            for (let i = 0; i < rows.length; i++) {
                selectedRowsMap[currentTabSheet].add(i);
            }
            for (let i = 0; i < sheetData.headers.length; i++) {
                selectedColsMap[currentTabSheet].add(i);
            }
            renderSelectTable(currentTabSheet);
            updateSelectedRowCount();
        });

        deselectAllRowsBtn.addEventListener('click', () => {
            if (!currentTabSheet) return;
            selectedRowsMap[currentTabSheet].clear();
            selectedColsMap[currentTabSheet].clear();
            renderSelectTable(currentTabSheet);
            updateSelectedRowCount();
        });

        invertSelectionBtn.addEventListener('click', () => {
            if (!currentTabSheet) return;
            const sheetData = sheetFullData[currentTabSheet];
            if (!sheetData) return;
            const rows = sheetData.all_rows.length > 0 ? sheetData.all_rows : sheetData.rows;
            const newRowSet = new Set();
            for (let i = 0; i < rows.length; i++) {
                if (!selectedRowsMap[currentTabSheet].has(i)) {
                    newRowSet.add(i);
                }
            }
            selectedRowsMap[currentTabSheet] = newRowSet;

            const newColSet = new Set();
            for (let i = 0; i < sheetData.headers.length; i++) {
                if (!selectedColsMap[currentTabSheet].has(i)) {
                    newColSet.add(i);
                }
            }
            selectedColsMap[currentTabSheet] = newColSet;

            renderSelectTable(currentTabSheet);
            updateSelectedRowCount();
        });

        excelSelectGenerateBtn.addEventListener('click', async () => {
            const selectedSheetsData = {};
            const selectedColumnsData = {};
            let hasSelection = false;
            Object.entries(selectedRowsMap).forEach(([sheetName, rowSet]) => {
                if (rowSet.size > 0) {
                    selectedSheetsData[sheetName] = Array.from(rowSet).sort((a, b) => a - b);
                    hasSelection = true;
                }
            });
            Object.entries(selectedColsMap).forEach(([sheetName, colSet]) => {
                if (colSet.size > 0) {
                    selectedColumnsData[sheetName] = Array.from(colSet).sort((a, b) => a - b);
                }
            });

            if (!hasSelection) {
                showToast('请至少选择一行数据', 'info');
                return;
            }

            const watermarkText = getWatermarkText();
            const customTitle = document.getElementById('excelSelectCustomTitle').value.trim();

            excelSelectGenerateBtn.disabled = true;
            excelSelectSpinner.style.display = 'block';
            excelSelectGenerateText.textContent = '生成中...';

            try {
                const response = await fetch('/excel-select-pdf', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        structured_data: structuredData,
                        selected_data: selectedSheetsData,
                        selected_columns: selectedColumnsData,
                        watermark: watermarkText,
                        custom_title: customTitle
                    }),
                });

                const data = await response.json();

                if (data.error) {
                    showToast('PDF生成失败：' + data.error, 'error');
                } else {
                    const a = document.createElement('a');
                    a.href = `/download/${data.filename}`;
                    a.download = data.download_name || data.filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    showToast('PDF报告生成成功！已开始下载', 'success');
                }
            } catch (error) {
                showToast('PDF生成失败：' + error.message, 'error');
            } finally {
                excelSelectGenerateBtn.disabled = false;
                excelSelectSpinner.style.display = 'none';
                excelSelectGenerateText.textContent = '生成PDF报告';
            }
        });

        updatePreview();
