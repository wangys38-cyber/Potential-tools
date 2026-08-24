/* ============================================================
   UX Enhancements JS — Toast / Loading / Drag-Drop 工具
   通用交互增强，适用于所有工具页面
   ============================================================ */

(function() {
    'use strict';

    // ===== Toast 通知（兼容 components.js 的 ToolboxToast） =====
    window.showToast = function(msg, type) {
        type = type || 'info';
        if (typeof ToolboxToast !== 'undefined' && ToolboxToast.show) {
            ToolboxToast.show(msg, type);
            return;
        }
        // Fallback: 简单 toast
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container';
            document.body.appendChild(container);
        }
        const toast = document.createElement('div');
        toast.className = 'toast ' + type;
        toast.textContent = msg;
        container.appendChild(toast);
        setTimeout(function() {
            toast.style.animation = 'toastOut 0.3s ease forwards';
            setTimeout(function() { toast.remove(); }, 300);
        }, 3000);
    };

    // ===== Loading 遮罩 =====
    window.showLoading = function(text) {
        const overlay = document.createElement('div');
        overlay.className = 'loading-overlay';
        overlay.id = 'global-loading-overlay';
        overlay.innerHTML = '<div style="text-align:center;">' +
            '<div class="spinner-large"></div>' +
            '<div class="loading-text">' + (text || '处理中...') + '</div></div>';
        document.body.appendChild(overlay);
        return overlay;
    };

    window.hideLoading = function() {
        const overlay = document.getElementById('global-loading-overlay');
        if (overlay) overlay.remove();
    };

    // ===== 拖拽上传增强 =====
    window.enableDragDrop = function(selector, onFile) {
        const elements = document.querySelectorAll(selector);
        elements.forEach(function(el) {
            if (el.dataset.dragDropEnabled) return;
            el.dataset.dragDropEnabled = 'true';

            el.addEventListener('dragover', function(e) {
                e.preventDefault();
                e.stopPropagation();
                el.classList.add('drag-over');
            });

            el.addEventListener('dragleave', function(e) {
                e.preventDefault();
                e.stopPropagation();
                el.classList.remove('drag-over');
            });

            el.addEventListener('drop', function(e) {
                e.preventDefault();
                e.stopPropagation();
                el.classList.remove('drag-over');
                const files = e.dataTransfer.files;
                if (files.length > 0 && onFile) {
                    onFile(files[0], e);
                }
            });
        });
    };

    // ===== 快捷键支持 =====
    window.registerShortcut = function(key, callback, opts) {
        opts = opts || {};
        document.addEventListener('keydown', function(e) {
            const ctrl = e.ctrlKey || e.metaKey;
            if (opts.ctrl && !ctrl) return;
            if (opts.shift && !e.shiftKey) return;
            if (e.key.toLowerCase() === key.toLowerCase()) {
                if (opts.ctrl || opts.shift) e.preventDefault();
                callback(e);
            }
        });
    };

    // ===== 自动为所有 file input 区域启用拖拽 =====
    document.addEventListener('DOMContentLoaded', function() {
        // 为包含 type=file 的表单区域启用拖拽
        const fileInputs = document.querySelectorAll('input[type="file"]');
        fileInputs.forEach(function(input) {
            const form = input.closest('form, .upload-area, .dropzone, .input-section, section, div[class*="upload"]');
            if (form) {
                enableDragDrop(form, function(file) {
                    // 创建 DataTransfer 来设置文件
                    try {
                        const dt = new DataTransfer();
                        dt.items.add(file);
                        input.files = dt.files;
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                        showToast('已选择文件: ' + file.name, 'success');
                    } catch(err) {
                        // 回退：触发点击
                    }
                });
            }
        });
    });

    // ===== 全局 Fetch 拦截器：自动 loading + 错误 toast =====
    const originalFetch = window.fetch;
    let loadingTimer = null;
    let activeRequests = 0;

    window.fetch = function(url, options) {
        activeRequests++;
        const isAPI = typeof url === 'string' && url.startsWith('/api/');
        const isUpload = isAPI && (url.includes('upload') || url.includes('analyze') || url.includes('generate'));
        // 支持通过 X-Skip-Loading header 跳过全局 loading（页面有自己的进度显示时使用）
        const skipLoading = options && options.headers && options.headers['X-Skip-Loading'] === 'true';

        if (isUpload && !loadingTimer && !skipLoading) {
            loadingTimer = setTimeout(function() {
                if (activeRequests > 0) showLoading('处理中...');
            }, 500);
        }

        return originalFetch.apply(this, arguments).then(function(resp) {
            activeRequests--;
            if (activeRequests <= 0 && loadingTimer) {
                clearTimeout(loadingTimer);
                loadingTimer = null;
                hideLoading();
            }
            if (isAPI && !resp.ok && resp.status >= 400) {
                resp.clone().json().then(function(data) {
                    showToast(data.error || ('请求失败 (' + resp.status + ')'), 'error');
                }).catch(function() {
                    showToast('请求失败 (' + resp.status + ')', 'error');
                });
            }
            return resp;
        }).catch(function(err) {
            activeRequests--;
            if (activeRequests <= 0 && loadingTimer) {
                clearTimeout(loadingTimer);
                loadingTimer = null;
                hideLoading();
            }
            if (isAPI) {
                showToast('网络错误: ' + err.message, 'error');
            }
            throw err;
        });
    };

    // ===== 全局未处理 Promise 错误 =====
    window.addEventListener('unhandledrejection', function(e) {
        console.error('Unhandled rejection:', e.reason);
        if (e.reason && e.reason.message && !e.reason.message.includes('abort')) {
            showToast('操作失败: ' + e.reason.message, 'error');
        }
    });

})();
