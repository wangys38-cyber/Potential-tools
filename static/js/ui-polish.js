/* ===== UI/UX 打磨增强脚本 =====
 * 增强Toast通知、骨架屏管理、平滑过渡、空状态
 */
(function(global) {
    'use strict';

    // ========== 增强 Toast 通知系统 ==========
    var toastContainer = null;

    function ensureToastContainer() {
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'toast-container';
            document.body.appendChild(toastContainer);
        }
        return toastContainer;
    }

    function showToast(message, type, duration) {
        type = type || 'info';
        duration = duration || 3000;

        var container = ensureToastContainer();
        var toast = document.createElement('div');
        toast.className = 'toast ' + type;

        var icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };

        toast.innerHTML =
            '<span class="toast-icon">' + (icons[type] || 'ℹ') + '</span>' +
            '<span class="toast-content">' + escapeHtml(message) + '</span>' +
            '<button class="toast-close" aria-label="关闭">&times;</button>';

        container.appendChild(toast);

        var closeBtn = toast.querySelector('.toast-close');
        closeBtn.addEventListener('click', function() {
            dismissToast(toast);
        });

        if (duration > 0) {
            setTimeout(function() {
                dismissToast(toast);
            }, duration);
        }

        return toast;
    }

    function dismissToast(toast) {
        if (!toast || toast.classList.contains('toast-exit')) return;
        toast.classList.add('toast-exit');
        setTimeout(function() {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 300);
    }

    // 覆盖全局 showToast
    global.showToast = showToast;

    // ========== 骨架屏管理 ==========
    function createSkeleton(type, count) {
        count = count || 3;
        var html = '';
        for (var i = 0; i < count; i++) {
            if (type === 'card') {
                html += '<div class="skeleton skeleton-card"></div>';
            } else if (type === 'list') {
                html += '<div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;">' +
                    '<div class="skeleton skeleton-circle"></div>' +
                    '<div style="flex:1;">' +
                    '<div class="skeleton skeleton-text" style="width:70%;"></div>' +
                    '<div class="skeleton skeleton-text" style="width:40%;"></div>' +
                    '</div></div>';
            } else {
                html += '<div class="skeleton skeleton-text"></div>';
            }
        }
        return html;
    }

    function showSkeleton(container, type, count) {
        if (!container) return;
        container.dataset.originalContent = container.innerHTML;
        container.innerHTML = createSkeleton(type, count);
    }

    function hideSkeleton(container, content) {
        if (!container) return;
        if (content !== undefined) {
            container.innerHTML = content;
        } else if (container.dataset.originalContent) {
            container.innerHTML = container.dataset.originalContent;
        }
    }

    // ========== 空状态 ==========
    function createEmptyState(options) {
        options = options || {};
        var div = document.createElement('div');
        div.className = 'empty-state';
        div.innerHTML =
            (options.icon ? '<div class="empty-state-icon">' + options.icon + '</div>' : '') +
            '<div class="empty-state-title">' + escapeHtml(options.title || '暂无数据') + '</div>' +
            (options.description ? '<div class="empty-state-desc">' + escapeHtml(options.description) + '</div>' : '') +
            (options.actionHtml ? '<div class="empty-state-action">' + options.actionHtml + '</div>' : '');
        return div;
    }

    // ========== 页面平滑过渡 ==========
    function initPageTransitions() {
        document.addEventListener('DOMContentLoaded', function() {
            var main = document.querySelector('.container, #main-content, main');
            if (main) {
                main.classList.add('page-fade');
            }
        });

        // 链接点击时的淡出效果（仅内部链接）
        document.addEventListener('click', function(e) {
            var link = e.target.closest('a[href]');
            if (!link) return;
            var href = link.getAttribute('href');
            if (!href || href.startsWith('#') || href.startsWith('http') || href.startsWith('mailto:')) return;
            if (link.target === '_blank') return;

            var main = document.querySelector('.container, #main-content, main');
            if (main) {
                main.style.transition = 'opacity 0.15s ease-out';
                main.style.opacity = '0';
            }
        });
    }

    // ========== 工具函数 ==========
    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    // ========== 知识图谱加载骨架屏 ==========
    function initKGSkeleton() {
        var graphCanvas = document.getElementById('graphCanvas');
        if (!graphCanvas) return;

        // 在图谱加载时显示骨架
        var container = graphCanvas.parentElement;
        if (container && !container.querySelector('.kg-skeleton')) {
            var skeleton = document.createElement('div');
            skeleton.className = 'kg-skeleton';
            skeleton.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:var(--ds-bg);z-index:10;';
            skeleton.innerHTML = '<div style="text-align:center;"><div class="loading-spinner" style="width:32px;height:32px;border-width:3px;"></div><div style="margin-top:12px;font-size:13px;color:var(--ds-text-secondary);">图谱加载中...</div></div>';
            container.appendChild(skeleton);

            // 3秒后自动隐藏（兜底）
            setTimeout(function() {
                if (skeleton.parentNode) skeleton.parentNode.removeChild(skeleton);
            }, 5000);
        }
    }

    // 初始化
    initPageTransitions();

    // 导出
    global.UIPolish = {
        showToast: showToast,
        dismissToast: dismissToast,
        createSkeleton: createSkeleton,
        showSkeleton: showSkeleton,
        hideSkeleton: hideSkeleton,
        createEmptyState: createEmptyState,
        initKGSkeleton: initKGSkeleton
    };

})(window);
