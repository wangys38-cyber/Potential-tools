/**
 * v5.0 全局 UX 增强模块
 * - 动态渐变背景光晕
 * - 全局拖拽上传（自动识别文件类型跳转到对应工具）
 * 在所有子工具页 </body> 前引入
 */
(function() {
    'use strict';

    // ===== 1. 注入动态背景光晕 =====
    function injectBackground() {
        if (document.querySelector('.v5-bg-orbs')) return;
        var orbs = document.createElement('div');
        orbs.className = 'v5-bg-orbs';
        orbs.innerHTML =
            '<div class="v5-bg-orb v5-bg-orb-1"></div>' +
            '<div class="v5-bg-orb v5-bg-orb-2"></div>' +
            '<div class="v5-bg-orb v5-bg-orb-3"></div>';
        document.body.appendChild(orbs);
        // 确保 body 有透明背景让光晕可见
        document.body.style.background = 'var(--bg-primary)';
    }

    // ===== 2. 全局拖拽上传 =====
    var FILE_TOOL_MAP = [
        { exts: ['mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac', 'webm'], tool: '/meeting-minutes', name: '会议纪要', icon: '🎙️' },
        { exts: ['md', 'markdown'], tool: '/md2pdf', name: 'PDF快转', icon: '📄' },
        { exts: ['docx', 'doc'], tool: '/md2pdf', name: 'PDF快转', icon: '📄' },
        { exts: ['xlsx', 'xls'], tool: '/excel-analysis', name: 'CR问题分析', icon: '📊' },
        { exts: ['csv'], tool: '/excel-analysis', name: 'CR问题分析', icon: '📊' },
        { exts: ['pdf'], tool: '/md2pdf', name: 'PDF快转', icon: '📄' },
        { exts: ['txt'], tool: '/meeting-minutes', name: '会议纪要', icon: '🎙️' },
        { exts: ['pptx', 'ppt'], tool: '/md2pdf', name: 'PDF快转', icon: '📄' },
    ];

    var ALL_TOOLS = [
        { url: '/meeting-minutes', name: '会议纪要', icon: '🎙️' },
        { url: '/md2pdf', name: 'PDF快转', icon: '📄' },
        { url: '/excel-analysis', name: 'CR问题分析', icon: '📊' },
        { url: '/test-report', name: '测试报告分析', icon: '📋' },
        { url: '/plan-generator', name: '软件计划生成器', icon: '📅' },
        { url: '/project-info', name: '项目信息收集', icon: '📊' },
        { url: '/weekly-report', name: '智能周报', icon: '📋' },
        { url: '/noteNB/', name: '牛马笔记', icon: '📝' },
    ];

    var dragCounter = 0;
    var dropOverlay = null;

    function createOverlay() {
        if (dropOverlay) return dropOverlay;
        dropOverlay = document.createElement('div');
        dropOverlay.className = 'v5-drop-overlay';
        dropOverlay.innerHTML =
            '<div class="v5-drop-content">' +
            '</div>';
        document.body.appendChild(dropOverlay);
        return dropOverlay;
    }

    function getExt(filename) {
        var parts = filename.split('.');
        return parts.length > 1 ? parts.pop().toLowerCase() : '';
    }

    function matchTool(file) {
        var ext = getExt(file.name);
        for (var i = 0; i < FILE_TOOL_MAP.length; i++) {
            if (FILE_TOOL_MAP[i].exts.indexOf(ext) !== -1) {
                return FILE_TOOL_MAP[i];
            }
        }
        return null;
    }

    function showToolPicker(files) {
        // 简单实现：弹出自定义选择器
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.5);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;';
        var picker = document.createElement('div');
        picker.style.cssText = 'background:var(--bg-card);border-radius:16px;padding:24px;max-width:400px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.2);';
        picker.innerHTML = '<h3 style="margin:0 0 16px;font-size:18px;">选择要打开的工具</h3>';
        var grid = document.createElement('div');
        grid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:8px;';
        ALL_TOOLS.forEach(function(t) {
            var btn = document.createElement('button');
            btn.style.cssText = 'display:flex;align-items:center;gap:8px;padding:10px 14px;border-radius:10px;border:1px solid var(--border);background:var(--bg-primary);cursor:pointer;font-size:14px;color:var(--text-primary);transition:all 0.2s;';
            btn.innerHTML = '<span style="font-size:18px;">' + t.icon + '</span>' + t.name;
            btn.onmouseenter = function() { this.style.borderColor = '#7c3aed'; this.style.transform = 'translateY(-1px)'; };
            btn.onmouseleave = function() { this.style.borderColor = 'var(--border)'; this.style.transform = 'none'; };
            btn.onclick = function() {
                // 存储文件信息到 sessionStorage，目标页面可读取
                try {
                    sessionStorage.setItem('v5_dropped_files', JSON.stringify({
                        count: files.length,
                        names: Array.from(files).map(function(f) { return f.name; }),
                        tool: t.url
                    }));
                } catch(e) {}
                window.location.href = t.url;
            };
            grid.appendChild(btn);
        });
        picker.appendChild(grid);
        var cancel = document.createElement('button');
        cancel.textContent = '取消';
        cancel.style.cssText = 'margin-top:16px;width:100%;padding:10px;border-radius:10px;border:none;background:var(--bg-primary);color:var(--text-secondary);cursor:pointer;font-size:14px;';
        cancel.onclick = function() { document.body.removeChild(overlay); };
        picker.appendChild(cancel);
        overlay.appendChild(picker);
        overlay.onclick = function(e) { if (e.target === overlay) document.body.removeChild(overlay); };
        document.body.appendChild(overlay);
    }

    function handleDrop(e) {
        e.preventDefault();
        dragCounter = 0;
        var overlay = createOverlay();
        overlay.classList.remove('show');

        var files = e.dataTransfer && e.dataTransfer.files;
        if (!files || files.length === 0) return;

        var firstFile = files[0];
        var matched = matchTool(firstFile);

        if (matched) {
            // 存储文件信息后跳转
            try {
                sessionStorage.setItem('v5_dropped_files', JSON.stringify({
                    count: files.length,
                    names: Array.from(files).map(function(f) { return f.name; }),
                    tool: matched.tool
                }));
            } catch(e) {}
            // 显示简短提示后跳转
            var tip = document.createElement('div');
            tip.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:10000;background:var(--bg-card);padding:20px 32px;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.2);font-size:16px;font-weight:600;';
            tip.innerHTML = matched.icon + ' 正在打开「' + matched.name + '」...';
            document.body.appendChild(tip);
            setTimeout(function() { window.location.href = matched.tool; }, 400);
        } else {
            showToolPicker(files);
        }
    }

    function initDragDrop() {
        // 不在首页启用（首页有自己的布局），但所有子页面都启用
        if (window.location.pathname === '/' || window.location.pathname === '/index') return;

        createOverlay();

        window.addEventListener('dragenter', function(e) {
            e.preventDefault();
            dragCounter++;
            if (e.dataTransfer && Array.from(e.dataTransfer.types).indexOf('Files') !== -1) {
                createOverlay().classList.add('show');
            }
        });

        window.addEventListener('dragleave', function(e) {
            e.preventDefault();
            dragCounter--;
            if (dragCounter <= 0) {
                dragCounter = 0;
                var overlay = document.querySelector('.v5-drop-overlay');
                if (overlay) overlay.classList.remove('show');
            }
        });

        window.addEventListener('dragover', function(e) {
            e.preventDefault();
        });

        window.addEventListener('drop', handleDrop);
    }

    // ===== 3. 工具间数据流转：读取拖拽/传递的数据 =====
    function checkDroppedFiles() {
        try {
            var data = sessionStorage.getItem('v5_dropped_files');
            if (data) {
                var parsed = JSON.parse(data);
                if (parsed.tool && window.location.pathname.indexOf(parsed.tool.replace('/', '')) !== -1) {
                    // 在目标页面触发自定义事件，页面可监听处理文件
                    window.dispatchEvent(new CustomEvent('v5-files-dropped', { detail: parsed }));
                    sessionStorage.removeItem('v5_dropped_files');
                }
            }
        } catch(e) {}
    }

    // ===== 初始化 =====
    function init() {
        injectBackground();
        initDragDrop();
        checkDroppedFiles();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // 暴露全局 API
    window.V5UX = {
        injectBackground: injectBackground,
        showToolPicker: showToolPicker
    };
})();
