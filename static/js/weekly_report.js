// ==================== 全局状态 ====================
        let reportHTML = '';
        let isGenerating = false;

        // ==================== 工具函数 ====================
        function fmt(d) {
            const y = d.getFullYear();
            const m = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            return y + '-' + m + '-' + day;
        }

        // 计算当前周（周一 ~ 周日）
        function getCurrentWeekRange() {
            const today = new Date();
            const day = today.getDay(); // 0=周日 ... 6=周六
            const diffToMonday = (day === 0 ? -6 : 1 - day); // 回到本周一
            const monday = new Date(today);
            monday.setDate(today.getDate() + diffToMonday);
            const sunday = new Date(monday);
            sunday.setDate(monday.getDate() + 6);
            return fmt(monday) + ' ~ ' + fmt(sunday);
        }

        function escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str == null ? '' : String(str);
            return div.innerHTML;
        }

        function showToast(msg, type, duration) {
            if (window.ToolboxToast) {
                ToolboxToast.show(msg, type || 'info', duration || 3000);
                return;
            }
            // 兜底：使用浏览器原生提示
            alert(msg);
        }

        // ==================== 生成周报 ====================
        async function generateReport() {
            if (isGenerating) return;

            const name = document.getElementById('name').value.trim();
            const weekRange = document.getElementById('weekRange').value.trim();
            const notes = document.getElementById('notes').value.trim();
            const meetings = document.getElementById('meetings').value.trim();
            const crIssues = document.getElementById('crIssues').value.trim();
            const extra = document.getElementById('extra').value.trim();
            const model = document.getElementById('model').value;

            // 校验
            if (!name) {
                showToast('请填写汇报人', 'warning');
                document.getElementById('name').focus();
                return;
            }
            if (!notes && !meetings && !crIssues && !extra) {
                showToast('请至少填写一项周报素材内容', 'warning');
                document.getElementById('notes').focus();
                return;
            }

            // 进入加载状态
            isGenerating = true;
            const btn = document.getElementById('generateBtn');
            btn.disabled = true;
            btn.classList.add('loading');
            btn.querySelector('.btn-text').textContent = '生成中...';

            const area = document.getElementById('reportArea');
            area.innerHTML = '<div class="loading-text">AI 正在整理你的周报...</div>';
            document.getElementById('resultBadge').classList.remove('show');

            try {
                let fullText = '';
                await ToolboxSSE.postStream('/api/weekly-report-stream', {
                    name: name,
                    week_range: weekRange,
                    notes: notes,
                    meetings: meetings,
                    cr_issues: crIssues,
                    extra: extra,
                    model: model
                }, {
                    onChunk: function(chunk, allText) {
                        fullText = allText;
                        // 使用统一 Markdown 渲染器实时渲染
                        var html = (typeof ToolboxMarkdown !== 'undefined')
                            ? ToolboxMarkdown.renderSafe(allText)
                            : escapeHtml(allText).replace(/\n/g, '<br>');
                        area.innerHTML = html;
                    },
                    onDone: function(finalText) {
                        fullText = finalText;
                        var html = (typeof ToolboxMarkdown !== 'undefined')
                            ? ToolboxMarkdown.renderSafe(finalText)
                            : escapeHtml(finalText).replace(/\n/g, '<br>');
                        area.innerHTML = html;
                        reportHTML = html;
                        document.getElementById('resultBadge').classList.add('show');
                        showToast('周报已生成', 'success');
                        area.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    },
                    onError: function(err) {
                        throw new Error(err);
                    }
                });
            } catch (err) {
                reportHTML = '';
                area.innerHTML =
                    '<div class="error-state">' +
                        '<div class="error-state-icon">⚠️</div>' +
                        '<div class="error-state-text">生成失败：' + escapeHtml(err.message) + '</div>' +
                        '<div class="error-state-hint">请检查网络或稍后重试</div>' +
                    '</div>';
                showToast('生成失败：' + err.message, 'error', 5000);
            } finally {
                isGenerating = false;
                btn.disabled = false;
                btn.classList.remove('loading');
                btn.querySelector('.btn-text').textContent = '✨ 生成周报';
            }
        }

        // ==================== 复制周报 ====================
        function copyReport() {
            if (!reportHTML) {
                showToast('暂无周报内容可复制', 'warning');
                return;
            }
            const temp = document.createElement('div');
            temp.innerHTML = reportHTML;
            const text = temp.innerText;
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text)
                    .then(() => showToast('已复制周报内容', 'success'))
                    .catch(() => showToast('复制失败', 'error'));
            } else {
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                try { document.execCommand('copy'); showToast('已复制周报内容', 'success'); }
                catch (e) { showToast('复制失败', 'error'); }
                document.body.removeChild(ta);
            }
        }

        // ==================== 导出（浏览器打印） ====================
        function exportReport() {
            if (!reportHTML) {
                showToast('暂无周报内容，请先生成', 'warning');
                return;
            }
            window.print();
        }

        // ==================== 推送到飞书 ====================
        async function pushToFeishu() {
            if (!reportHTML) {
                showToast('暂无周报内容，请先生成', 'warning');
                return;
            }
            const temp = document.createElement('div');
            temp.innerHTML = reportHTML;
            const text = temp.innerText;
            try {
                showToast('正在推送到飞书...', 'info');
                const resp = await fetch('/api/feishu/push', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        type: 'weekly',
                        title: '📊 周报 - ' + new Date().toLocaleDateString('zh-CN'),
                        content: text,
                        summary: text.substring(0, 500),
                        url: window.location.href
                    })
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    showToast('✅ 已推送到飞书群', 'success');
                } else {
                    showToast('❌ ' + (data.error || '推送失败'), 'error');
                }
            } catch (e) {
                showToast('❌ 推送失败: ' + e.message, 'error');
            }
        }

        // ==================== 快捷键 ====================
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                generateReport();
            }
        });

        // ==================== 初始化 ====================
        document.addEventListener('DOMContentLoaded', () => {
            // 默认填充当前周（周一 ~ 周日）
            document.getElementById('weekRange').value = getCurrentWeekRange();

            // 记录最近使用（由 components.js 提供）
            if (window.ToolboxRecent) {
                ToolboxRecent.record('weekly_report', '智能周报生成', '📋');
            }

            // 动态加载 AI 模型列表
            fetch('/api/ai-models').then(r => {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            }).then(data => {
                const sel = document.getElementById('model');
                sel.innerHTML = '';
                if (data.error) throw new Error(data.error);
                if (!data.models || data.models.length === 0) {
                    sel.innerHTML = '<option value="">无可用模型，请先在设置中配置 API Key</option>';
                    return;
                }
                (data.models || []).forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m.id;
                    opt.textContent = `${m.name} — ${m.desc}`;
                    if (m.id === data.current) opt.selected = true;
                    sel.appendChild(opt);
                });
            }).catch((err) => {
                document.getElementById('model').innerHTML = '<option value="">模型加载失败: ' + err.message + '</option>';
            });
        });

        // 草稿恢复
        var draftMgr = ToolboxDraft.init('weekly_report', {
            name: 'name',
            weekRange: 'weekRange',
            notes: 'notes',
            meetings: 'meetings',
            crIssues: 'crIssues',
            extra: 'extra'
        }, 3000);
