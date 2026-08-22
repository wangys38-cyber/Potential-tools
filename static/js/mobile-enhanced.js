/**
 * Potential-tools v5.0 移动端体验增强
 * 功能：手势支持、触摸优化、PWA 安装提示、安全区域适配、下拉刷新
 */

(function() {
    'use strict';

    // 检测是否为移动设备
    const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ||
                     (window.innerWidth <= 768);
    const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;

    if (!isMobile && !isTouch) {
        console.log('[Mobile] 非移动设备，跳过移动端增强');
        return;
    }

    // ============ 1. 安全区域适配 ============
    function initSafeArea() {
        // 添加安全区域 CSS 变量
        const style = document.createElement('style');
        style.textContent = `
            :root {
                --safe-top: env(safe-area-inset-top, 0px);
                --safe-bottom: env(safe-area-inset-bottom, 0px);
                --safe-left: env(safe-area-inset-left, 0px);
                --safe-right: env(safe-area-inset-right, 0px);
            }
            /* 导航栏安全区域 */
            .pt-nav-bar {
                padding-top: calc(var(--safe-top) + 0px) !important;
                height: calc(52px + var(--safe-top)) !important;
            }
            /* 底部固定元素安全区域 */
            [style*="position:fixed"][style*="bottom"],
            [style*="position: fixed"][style*="bottom"] {
                padding-bottom: var(--safe-bottom) !important;
            }
            /* 页面内容底部安全区域 */
            .container, main, .main-content {
                padding-bottom: calc(var(--safe-bottom) + 20px) !important;
            }
            /* 防止 iOS 橡皮筋效果 */
            body {
                overscroll-behavior-y: none;
                -webkit-overflow-scrolling: touch;
            }
            /* 触摸目标最小尺寸 */
            button, a, input, select, textarea {
                min-height: 44px;
                min-width: 44px;
            }
            /* 移除移动端点击高亮 */
            * {
                -webkit-tap-highlight-color: transparent;
            }
            /* 禁止长按选择（除了输入框） */
            button, a, .no-select {
                -webkit-user-select: none;
                user-select: none;
            }
        `;
        document.head.appendChild(style);
    }

    // ============ 2. 手势支持 ============
    let touchStartX = 0;
    let touchStartY = 0;
    let touchStartTime = 0;
    let isSwiping = false;

    function initGestures() {
        // 左滑返回（从屏幕左边缘开始）
        document.addEventListener('touchstart', function(e) {
            if (e.touches.length !== 1) return;
            touchStartX = e.touches[0].clientX;
            touchStartY = e.touches[0].clientY;
            touchStartTime = Date.now();
            isSwiping = touchStartX < 30; // 只在左边缘30px内开始
        }, { passive: true });

        document.addEventListener('touchend', function(e) {
            if (!isSwiping) return;
            isSwiping = false;

            const touchEndX = e.changedTouches[0].clientX;
            const touchEndY = e.changedTouches[0].clientY;
            const deltaX = touchEndX - touchStartX;
            const deltaY = touchEndY - touchStartY;
            const deltaTime = Date.now() - touchStartTime;

            // 左滑返回：向右滑动超过100px，且水平位移大于垂直位移
            if (deltaX > 100 && Math.abs(deltaX) > Math.abs(deltaY) && deltaTime < 500) {
                // 不是首页时返回上一页
                if (window.location.pathname !== '/') {
                    e.preventDefault();
                    window.history.back();
                }
            }
        }, { passive: true });

        // 下拉刷新（从页面顶部开始）
        let pullStartY = 0;
        let isPulling = false;
        let pullDistance = 0;
        const PULL_THRESHOLD = 80;

        document.addEventListener('touchstart', function(e) {
            if (window.scrollY === 0 && e.touches.length === 1) {
                pullStartY = e.touches[0].clientY;
                isPulling = true;
            }
        }, { passive: true });

        document.addEventListener('touchmove', function(e) {
            if (!isPulling) return;
            pullDistance = e.touches[0].clientY - pullStartY;
            if (pullDistance > 0 && pullDistance < 150) {
                // 显示下拉提示
                let indicator = document.getElementById('pull-refresh-indicator');
                if (!indicator) {
                    indicator = document.createElement('div');
                    indicator.id = 'pull-refresh-indicator';
                    indicator.style.cssText = `
                        position:fixed;top:0;left:0;right:0;height:0;overflow:hidden;
                        background:var(--bg-primary,#f5f5f7);z-index:99999;
                        display:flex;align-items:center;justify-content:center;
                        font-size:13px;color:var(--text-secondary,#86868b);
                        transition:height 0.2s;
                    `;
                    document.body.appendChild(indicator);
                }
                indicator.style.height = Math.min(pullDistance, 60) + 'px';
                indicator.textContent = pullDistance > PULL_THRESHOLD ? '释放刷新' : '下拉刷新';
            }
        }, { passive: true });

        document.addEventListener('touchend', function() {
            if (!isPulling) return;
            isPulling = false;

            const indicator = document.getElementById('pull-refresh-indicator');
            if (pullDistance > PULL_THRESHOLD) {
                // 执行刷新
                if (indicator) {
                    indicator.style.height = '40px';
                    indicator.textContent = '刷新中...';
                }
                setTimeout(function() {
                    location.reload();
                }, 500);
            } else {
                if (indicator) {
                    indicator.style.height = '0';
                    setTimeout(function() {
                        if (indicator && indicator.parentNode) {
                            indicator.parentNode.removeChild(indicator);
                        }
                    }, 200);
                }
            }
            pullDistance = 0;
        }, { passive: true });
    }

    // ============ 3. 触摸反馈优化 ============
    function initTouchFeedback() {
        // 按钮按下效果
        document.addEventListener('touchstart', function(e) {
            const target = e.target.closest('button, .btn, .action-btn, .pt-nav-icon-btn, .tool-card');
            if (target) {
                target.style.transform = 'scale(0.96)';
                target.style.transition = 'transform 0.1s';
            }
        }, { passive: true });

        document.addEventListener('touchend', function(e) {
            const target = e.target.closest('button, .btn, .action-btn, .pt-nav-icon-btn, .tool-card');
            if (target) {
                target.style.transform = '';
            }
        }, { passive: true });

        // 防止双击缩放
        let lastTouchEnd = 0;
        document.addEventListener('touchend', function(e) {
            const now = Date.now();
            if (now - lastTouchEnd <= 300) {
                e.preventDefault();
            }
            lastTouchEnd = now;
        }, { passive: false });

        // 修复 iOS 输入框聚焦时页面缩放
        document.addEventListener('focusin', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
                // iOS 下字体小于16px会触发缩放，确保字体至少16px
                if (parseFloat(getComputedStyle(e.target).fontSize) < 16) {
                    e.target.style.fontSize = '16px';
                }
            }
        });
    }

    // ============ 4. PWA 安装提示 ============
    let deferredPrompt = null;

    function initPWAInstall() {
        // 监听 beforeinstallprompt 事件
        window.addEventListener('beforeinstallprompt', function(e) {
            e.preventDefault();
            deferredPrompt = e;
            showInstallBanner();
        });

        // 安装成功
        window.addEventListener('appinstalled', function() {
            console.log('[PWA] 应用已安装');
            deferredPrompt = null;
            hideInstallBanner();
        });

        // 检查是否已安装
        if (window.matchMedia('(display-mode: standalone)').matches) {
            console.log('[PWA] 已在独立模式运行');
            return;
        }
    }

    function showInstallBanner() {
        if (document.getElementById('pwa-install-banner')) return;

        const banner = document.createElement('div');
        banner.id = 'pwa-install-banner';
        banner.style.cssText = `
            position:fixed;bottom:calc(var(--safe-bottom,0px) + 16px);left:16px;right:16px;
            background:var(--bg-card,#fff);border-radius:16px;padding:16px;
            box-shadow:0 8px 32px rgba(0,0,0,0.15);z-index:100000;
            display:flex;align-items:center;gap:12px;
            border:1px solid var(--border,rgba(0,0,0,0.08));
            animation:slideUp 0.3s ease;
        `;
        banner.innerHTML = `
            <div style="font-size:32px;">📱</div>
            <div style="flex:1;min-width:0;">
                <div style="font-size:14px;font-weight:600;color:var(--text-primary,#1d1d1f);">添加到主屏幕</div>
                <div style="font-size:12px;color:var(--text-secondary,#86868b);margin-top:2px;">像原生应用一样使用工具集</div>
            </div>
            <button id="pwa-install-btn" style="padding:8px 16px;background:var(--text-primary,#1d1d1f);color:var(--bg-card,#fff);border:none;border-radius:8px;font-size:13px;cursor:pointer;white-space:nowrap;">安装</button>
            <button id="pwa-install-close" style="background:none;border:none;font-size:20px;color:var(--text-secondary,#86868b);cursor:pointer;padding:4px 8px;">×</button>
        `;

        document.body.appendChild(banner);

        document.getElementById('pwa-install-btn').addEventListener('click', function() {
            if (deferredPrompt) {
                deferredPrompt.prompt();
                deferredPrompt.userChoice.then(function(choice) {
                    if (choice.outcome === 'accepted') {
                        console.log('[PWA] 用户接受安装');
                    }
                    deferredPrompt = null;
                    hideInstallBanner();
                });
            }
        });

        document.getElementById('pwa-install-close').addEventListener('click', hideInstallBanner);

        // 3秒后自动隐藏
        setTimeout(hideInstallBanner, 8000);
    }

    function hideInstallBanner() {
        const banner = document.getElementById('pwa-install-banner');
        if (banner) {
            banner.style.transition = 'opacity 0.3s, transform 0.3s';
            banner.style.opacity = '0';
            banner.style.transform = 'translateY(20px)';
            setTimeout(function() {
                if (banner.parentNode) banner.parentNode.removeChild(banner);
            }, 300);
        }
    }

    // ============ 5. 移动端专用优化 ============
    function initMobileOptimizations() {
        // 修复 iOS 100vh 问题
        function setVH() {
            const vh = window.innerHeight * 0.01;
            document.documentElement.style.setProperty('--vh', vh + 'px');
        }
        setVH();
        window.addEventListener('resize', setVH);

        // 键盘弹出时调整布局
        if ('visualViewport' in window) {
            window.visualViewport.addEventListener('resize', function() {
                document.body.style.height = window.visualViewport.height + 'px';
            });
        }

        // 隐藏移动端地址栏（滚动时）
        let lastScroll = 0;
        window.addEventListener('scroll', function() {
            const currentScroll = window.scrollY;
            const navBar = document.getElementById('ptNavBar');
            if (navBar) {
                if (currentScroll > lastScroll && currentScroll > 50) {
                    navBar.style.transform = 'translateY(-100%)';
                } else {
                    navBar.style.transform = 'translateY(0)';
                }
                navBar.style.transition = 'transform 0.3s ease';
            }
            lastScroll = currentScroll;
        }, { passive: true });
    }

    // ============ 6. 移动端导航优化 ============
    function initMobileNav() {
        // 移动端隐藏导航栏中的用户名，只显示头像
        if (window.innerWidth <= 480) {
            const userName = document.querySelector('.pt-nav-user-name');
            if (userName) userName.style.display = 'none';

            const logoutBtn = document.querySelector('.pt-nav-logout');
            if (logoutBtn) {
                logoutBtn.style.display = 'none';
            }
        }
    }

    // ============ 初始化 ============
    function init() {
        initSafeArea();
        initGestures();
        initTouchFeedback();
        initPWAInstall();
        initMobileOptimizations();
        initMobileNav();

        console.log('[Mobile] 移动端体验增强已加载');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
