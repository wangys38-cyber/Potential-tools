/* ============================================================
   牛马笔记 v8.0 主逻辑
   支持：Markdown 编辑/预览、搜索、分类、模板、待办、导出、自动保存、云端同步
   ============================================================ */
(function() {
    'use strict';

    // ==================== 配置与状态 ====================
    var CONFIG = window.NB_CONFIG || { isLoggedIn: false, userId: 0 };
    var STORAGE_KEY = 'niuma_notes_v8' + (CONFIG.userId ? '_u' + CONFIG.userId : '');

    var state = {
        notes: [],
        currentNoteId: null,
        searchQuery: '',
        activeCategory: '',
        sortBy: 'updated',
        mode: 'edit', // edit | preview | split
        saveTimer: null,
        isSaving: false,
        pendingDeleteId: null
    };

    // ==================== 模板定义 ====================
    var TEMPLATES = {
        meeting: {
            title: '会议纪要 - ' + formatDate(new Date()),
            content: '# 会议纪要\n\n**日期：** ' + formatDate(new Date()) + '\n**参会人：** \n**会议主题：** \n\n---\n\n## 议程\n\n1. \n2. \n3. \n\n## 讨论内容\n\n### 议题一\n\n- \n\n### 议题二\n\n- \n\n## 决议\n\n- [ ] \n- [ ] \n\n## 下一步行动\n\n| 事项 | 负责人 | 截止日期 |\n|------|--------|----------|\n|      |        |          |\n'
        },
        todo: {
            title: '待办清单 - ' + formatDate(new Date()),
            content: '# 待办清单\n\n**日期：** ' + formatDate(new Date()) + '\n\n## 今日待办\n\n- [ ] \n- [ ] \n- [ ] \n\n## 进行中\n\n- [ ] \n\n## 已完成\n\n- [x] \n\n## 备忘\n\n- \n'
        },
        project: {
            title: '项目笔记 - ',
            content: '# 项目笔记\n\n## 项目概述\n\n**项目名称：** \n**负责人：** \n**开始日期：** \n**目标：** \n\n## 背景\n\n\n\n## 关键节点\n\n- [ ] 节点一\n- [ ] 节点二\n- [ ] 节点三\n\n## 风险与问题\n\n| 问题 | 影响 | 解决方案 | 状态 |\n|------|------|----------|------|\n|      |      |          |      |\n\n## 会议记录\n\n### YYYY-MM-DD\n\n- \n\n## 参考资料\n\n- \n'
        },
        study: {
            title: '学习笔记 - ',
            content: '# 学习笔记\n\n## 主题\n\n\n\n## 核心概念\n\n### 概念一\n\n**定义：** \n\n**要点：**\n- \n- \n\n### 概念二\n\n**定义：** \n\n**要点：**\n- \n- \n\n## 示例代码\n\n```\n\n```\n\n## 常见问题\n\n**Q: **\n\n**A: **\n\n## 总结\n\n- \n- \n\n## 参考链接\n\n- \n'
        }
    };

    // ==================== 工具函数 ====================
    function generateId() {
        return 'note_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }

    function formatDate(d) {
        var y = d.getFullYear();
        var m = String(d.getMonth() + 1).padStart(2, '0');
        var day = String(d.getDate()).padStart(2, '0');
        return y + '-' + m + '-' + day;
    }

    function formatTime(ts) {
        if (!ts) return '';
        var d = new Date(ts * 1000);
        var now = new Date();
        var diff = (now - d) / 1000;
        if (diff < 60) return '刚刚';
        if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
        if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
        if (diff < 604800) return Math.floor(diff / 86400) + '天前';
        return formatDate(d);
    }

    function debounce(fn, delay) {
        var timer = null;
        return function() {
            var args = arguments;
            var ctx = this;
            clearTimeout(timer);
            timer = setTimeout(function() { fn.apply(ctx, args); }, delay);
        };
    }

    // ==================== 数据持久化 ====================
    function loadNotes() {
        if (CONFIG.isLoggedIn) {
            // 登录用户：从 API 加载
            fetch('/api/notes', { credentials: 'same-origin' })
                .then(function(r) { return r.json(); })
                .then(function(res) {
                    if (res.status === 'success' && res.notes) {
                        state.notes = res.notes.map(function(n) {
                            return normalizeNote(n);
                        });
                        saveToLocal(); // 缓存到本地
                        renderAll();
                    }
                })
                .catch(function() {
                    // API 失败，回退到本地缓存
                    loadFromLocal();
                });
        } else {
            loadFromLocal();
        }
    }

    function loadFromLocal() {
        try {
            var data = localStorage.getItem(STORAGE_KEY);
            state.notes = data ? JSON.parse(data) : [];
        } catch(e) {
            state.notes = [];
        }
        renderAll();
    }

    function saveToLocal() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state.notes));
        } catch(e) {}
    }

    function normalizeNote(n) {
        return {
            id: n.note_uid || n.id,
            note_uid: n.note_uid || n.id,
            title: n.title || '',
            content: n.content || '',
            category: n.category || '',
            tags: Array.isArray(n.tags) ? n.tags : (n.tags ? JSON.parse(n.tags) : []),
            is_todo: !!n.is_todo,
            pinned: !!n.pinned,
            created_at: n.created_at || (Date.now() / 1000),
            updated_at: n.updated_at || (Date.now() / 1000)
        };
    }

    function syncToServer(note, method) {
        if (!CONFIG.isLoggedIn) return;
        var url = '/api/notes' + (method === 'POST' ? '' : '/' + note.id);
        var body = {
            id: note.id,
            title: note.title,
            content: note.content,
            category: note.category,
            tags: note.tags,
            is_todo: note.is_todo,
            pinned: note.pinned
        };
        fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(body)
        }).catch(function() {});
    }

    function deleteFromServer(noteId) {
        if (!CONFIG.isLoggedIn) return;
        fetch('/api/notes/' + noteId, {
            method: 'DELETE',
            credentials: 'same-origin'
        }).catch(function() {});
    }

    // ==================== 笔记操作 ====================
    function createNote(template) {
        var id = generateId();
        var now = Date.now() / 1000;
        var note = {
            id: id,
            note_uid: id,
            title: template ? template.title : '',
            content: template ? template.content : '',
            category: '',
            tags: [],
            is_todo: false,
            pinned: false,
            completed: false,
            created_at: now,
            updated_at: now
        };
        state.notes.unshift(note);
        state.currentNoteId = id;
        saveToLocal();
        if (CONFIG.isLoggedIn) syncToServer(note, 'POST');
        renderAll();
        setTimeout(function() {
            var titleInput = document.getElementById('nbTitleInput');
            if (titleInput) titleInput.focus();
        }, 50);
    }

    function updateCurrentNote(field, value) {
        var note = getCurrentNote();
        if (!note) return;
        note[field] = value;
        note.updated_at = Date.now() / 1000;
        saveToLocal();
        updateSaveStatus('saving');
        debouncedSync(note);
        updateStats();
        renderNotesList();
        updateUpdatedTime();
    }

    var debouncedSync = debounce(function(note) {
        if (CONFIG.isLoggedIn) syncToServer(note, 'PUT');
        updateSaveStatus('saved');
    }, 800);

    function deleteNote(noteId) {
        state.notes = state.notes.filter(function(n) { return n.id !== noteId; });
        if (state.currentNoteId === noteId) state.currentNoteId = null;
        saveToLocal();
        if (CONFIG.isLoggedIn) deleteFromServer(noteId);
        renderAll();
    }

    function getCurrentNote() {
        return state.notes.find(function(n) { return n.id === state.currentNoteId; });
    }

    function getFilteredNotes() {
        var list = state.notes.slice();
        // 分类筛选
        if (state.activeCategory) {
            list = list.filter(function(n) { return n.category === state.activeCategory; });
        }
        // 搜索
        if (state.searchQuery) {
            var q = state.searchQuery.toLowerCase();
            list = list.filter(function(n) {
                return (n.title || '').toLowerCase().indexOf(q) >= 0 ||
                       (n.content || '').toLowerCase().indexOf(q) >= 0;
            });
        }
        // 排序
        list.sort(function(a, b) {
            if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
            if (state.sortBy === 'title') {
                return (a.title || '').localeCompare(b.title || '', 'zh-CN');
            } else if (state.sortBy === 'created') {
                return (b.created_at || 0) - (a.created_at || 0);
            }
            return (b.updated_at || 0) - (a.updated_at || 0);
        });
        return list;
    }

    function getAllCategories() {
        var cats = {};
        state.notes.forEach(function(n) {
            if (n.category) cats[n.category] = true;
        });
        return Object.keys(cats).sort();
    }

    // ==================== 渲染 ====================
    function renderAll() {
        renderCategories();
        renderNotesList();
        renderEditor();
    }

    function renderCategories() {
        var container = document.getElementById('nbCategoryList');
        if (!container) return;
        var cats = getAllCategories();
        var html = '<span class="nb-category-chip nb-category-chip-all ' + (!state.activeCategory ? 'active' : '') + '" onclick="NB.setCategory(\'\')">全部</span>';
        cats.forEach(function(cat) {
            html += '<span class="nb-category-chip ' + (state.activeCategory === cat ? 'active' : '') + '" onclick="NB.setCategory(\'' + escapeHtml(cat) + '\')">' + escapeHtml(cat) + '</span>';
        });
        container.innerHTML = html;
    }

    function renderNotesList() {
        var container = document.getElementById('nbNotesList');
        if (!container) return;
        var list = getFilteredNotes();
        if (list.length === 0) {
            container.innerHTML = '<div class="nb-empty-list">' + (state.searchQuery ? '没有找到匹配的笔记' : '暂无笔记<br>点击上方新建') + '</div>';
            return;
        }
        var html = '';
        list.forEach(function(n) {
            var preview = (n.content || '').replace(/[#*`>\-\[\]]/g, '').replace(/\n/g, ' ').trim().slice(0, 60);
            var completedClass = n.completed ? ' completed' : '';
            var titleStyle = n.completed ? ' style="text-decoration:line-through;opacity:0.6;"' : '';
            var previewStyle = n.completed ? ' style="text-decoration:line-through;opacity:0.6;"' : '';
            html += '<div class="nb-note-item' + (n.id === state.currentNoteId ? ' active' : '') + completedClass + '" onclick="NB.openNote(\'' + n.id + '\')">' +
                '<div class="nb-note-complete-btn" onclick="event.stopPropagation();NB.toggleNoteComplete(\'' + n.id + '\')" title="' + (n.completed ? '标记为未完成' : '标记为完成') + '">' +
                    (n.completed ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>' : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8e8e93" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/></svg>') +
                '</div>' +
                '<div class="nb-note-item-header">' +
                    (n.pinned ? '<svg class="nb-note-pin" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg>' : '') +
                    '<span class="nb-note-title"' + titleStyle + '>' + escapeHtml(n.title || '无标题') + '</span>' +
                '</div>' +
                (preview ? '<div class="nb-note-preview"' + previewStyle + '>' + escapeHtml(preview) + '</div>' : '') +
                '<div class="nb-note-meta">' +
                    (n.category ? '<span class="nb-note-category-tag">' + escapeHtml(n.category) + '</span>' : '') +
                    '<span>' + formatTime(n.updated_at) + '</span>' +
                '</div>' +
            '</div>';
        });
        container.innerHTML = html;
    }

    function renderEditor() {
        var empty = document.getElementById('nbEditorEmpty');
        var content = document.getElementById('nbEditorContent');
        var note = getCurrentNote();
        if (!note) {
            if (empty) empty.style.display = 'flex';
            if (content) content.style.display = 'none';
            return;
        }
        if (empty) empty.style.display = 'none';
        if (content) content.style.display = 'flex';

        var titleInput = document.getElementById('nbTitleInput');
        var contentTextarea = document.getElementById('nbContentTextarea');
        var categoryInput = document.getElementById('nbCategoryInput');
        var tagsInput = document.getElementById('nbTagsInput');
        var pinBtn = document.getElementById('nbPinBtn');

        if (titleInput && titleInput.value !== note.title) titleInput.value = note.title;
        if (contentTextarea && contentTextarea.value !== note.content) contentTextarea.value = note.content;
        if (categoryInput && categoryInput.value !== note.category) categoryInput.value = note.category;
        if (tagsInput) tagsInput.value = (note.tags || []).join(', ');
        if (pinBtn) {
            if (note.pinned) {
                pinBtn.classList.add('active');
                pinBtn.style.color = 'var(--ds-warning)';
            } else {
                pinBtn.classList.remove('active');
                pinBtn.style.color = '';
            }
        }

        updateStats();
        updateUpdatedTime();
        updatePreview();
        applyMode();
    }

    function updateStats() {
        var note = getCurrentNote();
        var el = document.getElementById('nbStats');
        if (!el || !note) return;
        var content = note.content || '';
        var chars = content.replace(/\s/g, '').length;
        var lines = content ? content.split('\n').length : 0;
        el.textContent = chars + ' 字 · ' + lines + ' 行';
    }

    function updateUpdatedTime() {
        var note = getCurrentNote();
        var el = document.getElementById('nbUpdatedTime');
        if (!el || !note) return;
        el.textContent = '更新于 ' + formatTime(note.updated_at);
    }

    function updateSaveStatus(status) {
        var el = document.getElementById('nbSaveStatus');
        if (!el) return;
        el.className = 'nb-save-status ' + status;
        if (status === 'saving') el.textContent = '保存中...';
        else if (status === 'saved') el.textContent = '已保存';
        else el.textContent = '已保存';
    }

    // ==================== Markdown 预览 ====================
    function updatePreview() {
        var note = getCurrentNote();
        var previewEl = document.getElementById('nbPreviewContent');
        if (!previewEl || !note) return;
        var html = '';
        if (typeof marked !== 'undefined') {
            try {
                html = marked.parse(note.content || '');
            } catch(e) {
                html = '<pre>' + escapeHtml(note.content || '') + '</pre>';
            }
        } else {
            html = '<pre>' + escapeHtml(note.content || '') + '</pre>';
        }
        previewEl.innerHTML = html;
        // 绑定 checkbox 切换
        var checkboxes = previewEl.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(function(cb, idx) {
            cb.addEventListener('change', function() {
                toggleTodoCheckbox(idx, cb.checked);
            });
        });
    }

    function toggleTodoCheckbox(index, checked) {
        var note = getCurrentNote();
        if (!note) return;
        var lines = note.content.split('\n');
        var todoCount = 0;
        for (var i = 0; i < lines.length; i++) {
            if (lines[i].match(/^\s*-\s*\[[ xX]\]/)) {
                if (todoCount === index) {
                    lines[i] = lines[i].replace(/\[[ xX]\]/, checked ? '[x]' : '[ ]');
                    break;
                }
                todoCount++;
            }
        }
        note.content = lines.join('\n');
        note.updated_at = Date.now() / 1000;
        var textarea = document.getElementById('nbContentTextarea');
        if (textarea) textarea.value = note.content;
        saveToLocal();
        updateSaveStatus('saving');
        debouncedSync(note);
        updateStats();
        renderNotesList();
    }

    // ==================== 模式切换 ====================
    function setMode(mode) {
        state.mode = mode;
        var editBtn = document.getElementById('nbEditModeBtn');
        var previewBtn = document.getElementById('nbPreviewModeBtn');
        var splitBtn = document.getElementById('nbSplitModeBtn');
        [editBtn, previewBtn, splitBtn].forEach(function(b) { if (b) b.classList.remove('active'); });
        if (mode === 'edit' && editBtn) editBtn.classList.add('active');
        if (mode === 'preview' && previewBtn) previewBtn.classList.add('active');
        if (mode === 'split' && splitBtn) splitBtn.classList.add('active');
        applyMode();
    }

    function applyMode() {
        var body = document.getElementById('nbEditorBody');
        var editPane = document.getElementById('nbEditPane');
        var previewPane = document.getElementById('nbPreviewPane');
        var doneBtn = document.getElementById('nbDoneBtn');
        var editBtn = document.getElementById('nbEditBtn');
        if (!body) return;
        body.classList.remove('split', 'preview-only');
        if (state.mode === 'edit') {
            if (editPane) editPane.classList.remove('hidden');
            if (previewPane) previewPane.style.display = 'none';
            if (doneBtn) doneBtn.style.display = 'inline-flex';
            if (editBtn) editBtn.style.display = 'none';
        } else if (state.mode === 'preview') {
            body.classList.add('preview-only');
            if (editPane) editPane.classList.add('hidden');
            if (previewPane) previewPane.style.display = 'block';
            if (doneBtn) doneBtn.style.display = 'none';
            if (editBtn) editBtn.style.display = 'inline-flex';
            updatePreview();
        } else if (state.mode === 'split') {
            body.classList.add('split');
            if (editPane) editPane.classList.remove('hidden');
            if (previewPane) previewPane.style.display = 'block';
            if (doneBtn) doneBtn.style.display = 'inline-flex';
            if (editBtn) editBtn.style.display = 'none';
            updatePreview();
        }
    }

    function doneEditing() {
        var note = getCurrentNote();
        if (note) {
            saveToLocal();
            if (CONFIG.isLoggedIn) syncToServer(note, 'PUT');
            updateSaveStatus('saved');
        }
        setMode('preview');
    }

    function startEditing() {
        setMode('edit');
        setTimeout(function() {
            var textarea = document.getElementById('nbContentTextarea');
            if (textarea) textarea.focus();
        }, 50);
    }

    // ==================== 工具栏操作 ====================
    function insertFormat(before, after) {
        var textarea = document.getElementById('nbContentTextarea');
        if (!textarea) return;
        var start = textarea.selectionStart;
        var end = textarea.selectionEnd;
        var value = textarea.value;
        var selected = value.substring(start, end);
        var newText = before + selected + after;
        textarea.value = value.substring(0, start) + newText + value.substring(end);
        var newPos = start + before.length + selected.length;
        textarea.focus();
        textarea.setSelectionRange(start + before.length, newPos);
        onContentInput(textarea.value);
    }

    function insertLine(prefix) {
        var textarea = document.getElementById('nbContentTextarea');
        if (!textarea) return;
        var start = textarea.selectionStart;
        var value = textarea.value;
        var lineStart = value.lastIndexOf('\n', start - 1) + 1;
        var newText = value.substring(0, lineStart) + prefix + value.substring(lineStart);
        textarea.value = newText;
        textarea.focus();
        textarea.setSelectionRange(start + prefix.length, start + prefix.length);
        onContentInput(textarea.value);
    }

    // ==================== 导出 ====================
    function exportMarkdown() {
        var note = getCurrentNote();
        if (!note) return;
        var content = '# ' + (note.title || '无标题') + '\n\n' + (note.content || '');
        var blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = (note.title || 'note') + '.md';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    // ==================== 删除确认 ====================
    function showDeleteModal(noteId) {
        state.pendingDeleteId = noteId;
        var modal = document.getElementById('nbDeleteModal');
        if (modal) modal.style.display = 'flex';
    }

    function closeDeleteModal() {
        state.pendingDeleteId = null;
        var modal = document.getElementById('nbDeleteModal');
        if (modal) modal.style.display = 'none';
    }

    function confirmDelete() {
        if (state.pendingDeleteId) {
            deleteNote(state.pendingDeleteId);
        }
        closeDeleteModal();
    }

    // ==================== 移动端 ====================
    function toggleSidebar() {
        var sidebar = document.getElementById('nbSidebar');
        var overlay = document.getElementById('nbSidebarOverlay');
        if (sidebar) sidebar.classList.toggle('open');
        if (overlay) overlay.classList.toggle('open');
    }

    // ==================== 模板菜单 ====================
    function toggleTemplateMenu() {
        var menu = document.getElementById('nbTemplateMenu');
        if (menu) menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
    }

    function useTemplate(type) {
        var tpl = TEMPLATES[type];
        if (!tpl) return;
        var menu = document.getElementById('nbTemplateMenu');
        if (menu) menu.style.display = 'none';
        createNote(tpl);
    }

    // ==================== 事件处理 ====================
    function onTitleInput(value) {
        updateCurrentNote('title', value);
    }

    function onContentInput(value) {
        updateCurrentNote('content', value);
        if (state.mode !== 'edit') updatePreview();
    }

    function onCategoryInput(value) {
        updateCurrentNote('category', value);
        renderCategories();
    }

    function onTagsInput(value) {
        var tags = value.split(/[,，]/).map(function(t) { return t.trim(); }).filter(function(t) { return t; });
        updateCurrentNote('tags', tags);
    }

    function onSearch(value) {
        state.searchQuery = value;
        renderNotesList();
    }

    function setSort(value) {
        state.sortBy = value;
        renderNotesList();
    }

    function setCategory(cat) {
        state.activeCategory = cat;
        renderCategories();
        renderNotesList();
    }

    function openNote(noteId) {
        state.currentNoteId = noteId;
        renderNotesList();
        renderEditor();
        // 移动端关闭侧边栏
        if (window.innerWidth <= 768) {
            toggleSidebar();
        }
    }

    function toggleNoteComplete(noteId) {
        var note = state.notes.find(function(n) { return n.id === noteId; });
        if (!note) return;
        note.completed = !note.completed;
        note.updated_at = Date.now() / 1000;
        saveToLocal();
        updateSaveStatus('saving');
        debouncedSync(note);
        renderAll();
    }

    function toggleComplete() {
        var note = getCurrentNote();
        if (!note) return;
        note.completed = !note.completed;
        note.updated_at = Date.now() / 1000;
        saveToLocal();
        updateSaveStatus('saving');
        debouncedSync(note);
        renderAll();
    }

    function togglePin() {
        var note = getCurrentNote();
        if (!note) return;
        note.pinned = !note.pinned;
        note.updated_at = Date.now() / 1000;
        saveToLocal();
        if (CONFIG.isLoggedIn) syncToServer(note, 'PUT');
        renderAll();
    }

    function deleteCurrentNote() {
        var note = getCurrentNote();
        if (!note) return;
        showDeleteModal(note.id);
    }

    function newNote() {
        createNote(null);
    }

    // ==================== 初始化 ====================
    function init() {
        // marked 配置
        if (typeof marked !== 'undefined') {
            marked.setOptions({ breaks: true, gfm: true });
        }
        loadNotes();

        // 点击外部关闭模板菜单
        document.addEventListener('click', function(e) {
            var menu = document.getElementById('nbTemplateMenu');
            var btn = document.getElementById('nbTemplateBtn');
            if (menu && menu.style.display !== 'none' && !menu.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
                menu.style.display = 'none';
            }
        });

        // 键盘快捷键
        document.addEventListener('keydown', function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                var note = getCurrentNote();
                if (note) {
                    saveToLocal();
                    if (CONFIG.isLoggedIn) syncToServer(note, 'PUT');
                    updateSaveStatus('saved');
                }
            }
            if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
                e.preventDefault();
                newNote();
            }
        });

        // 粘贴图片功能
        document.addEventListener('paste', function(e) {
            var textarea = document.getElementById('nbContentTextarea');
            if (!textarea || document.activeElement !== textarea) return;

            var items = e.clipboardData && e.clipboardData.items;
            if (!items) return;

            for (var i = 0; i < items.length; i++) {
                if (items[i].type.indexOf('image') !== -1) {
                    e.preventDefault();
                    var file = items[i].getAsFile();
                    if (file) {
                        handleImagePaste(file, textarea);
                    }
                    break;
                }
            }
        });
    }

    // 处理粘贴的图片
    function handleImagePaste(file, textarea) {
        var reader = new FileReader();
        reader.onload = function(e) {
            var base64 = e.target.result;
            var imgMarkdown = '\n![图片](' + base64 + ')\n';

            var start = textarea.selectionStart;
            var end = textarea.selectionEnd;
            var value = textarea.value;

            textarea.value = value.substring(0, start) + imgMarkdown + value.substring(end);
            textarea.focus();
            textarea.setSelectionRange(start + imgMarkdown.length, start + imgMarkdown.length);

            onContentInput(textarea.value);
        };
        reader.readAsDataURL(file);
    }

    // 通过文件选择器插入图片
    function insertImageFromFile() {
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/*';
        input.onchange = function(e) {
            var file = e.target.files[0];
            if (file) {
                var textarea = document.getElementById('nbContentTextarea');
                if (textarea) {
                    handleImagePaste(file, textarea);
                }
            }
        };
        input.click();
    }

    // ==================== 公开 API ====================
    window.NB = {
        newNote: newNote,
        openNote: openNote,
        deleteCurrentNote: deleteCurrentNote,
        togglePin: togglePin,
        toggleComplete: toggleComplete,
        toggleNoteComplete: toggleNoteComplete,
        onTitleInput: onTitleInput,
        onContentInput: onContentInput,
        onCategoryInput: onCategoryInput,
        onTagsInput: onTagsInput,
        onSearch: onSearch,
        setSort: setSort,
        setCategory: setCategory,
        setMode: setMode,
        doneEditing: doneEditing,
        startEditing: startEditing,
        insertFormat: insertFormat,
        insertLine: insertLine,
        exportMarkdown: exportMarkdown,
        insertImageFromFile: insertImageFromFile,
        toggleSidebar: toggleSidebar,
        toggleTemplateMenu: toggleTemplateMenu,
        useTemplate: useTemplate,
        closeDeleteModal: closeDeleteModal,
        confirmDelete: confirmDelete
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
