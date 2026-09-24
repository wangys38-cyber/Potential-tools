/* ============================================
   页面过渡动画 JS
   - 页面加载完成后淡出遮罩
   - 页面内容淡入
   - 链接点击时显示遮罩（防止跳转白屏）
   ============================================ */

(function() {
  'use strict';

  var OVERLAY_ID = 'page-transition-overlay';
  var CONTENT_CLASS = 'pt-page-content';
  var HIDDEN_CLASS = 'pt-hidden';
  var VISIBLE_CLASS = 'pt-visible';

  // 创建遮罩元素（如果不存在）
  function createOverlay() {
    if (document.getElementById(OVERLAY_ID)) return;
    var overlay = document.createElement('div');
    overlay.id = OVERLAY_ID;
    overlay.innerHTML = '<div class="pt-loader"></div>';
    document.body.appendChild(overlay);
  }

  // 隐藏遮罩
  function hideOverlay() {
    var overlay = document.getElementById(OVERLAY_ID);
    if (!overlay) return;
    if (overlay.classList.contains(HIDDEN_CLASS)) return;

    overlay.classList.add(HIDDEN_CLASS);

    // 动画结束后移除元素
    setTimeout(function() {
      if (overlay && overlay.parentNode) {
        overlay.parentNode.removeChild(overlay);
      }
    }, 600);
  }

  // 显示遮罩
  function showOverlay() {
    createOverlay();
    var overlay = document.getElementById(OVERLAY_ID);
    if (overlay) {
      overlay.classList.remove(HIDDEN_CLASS);
    }
  }

  // 显示页面内容
  function showContent() {
    var content = document.querySelector('.' + CONTENT_CLASS);
    if (content) {
      content.classList.add(VISIBLE_CLASS);
    }
  }

  // 页面加载完成
  function onPageLoad() {
    // 延迟一点，让用户看到过渡效果
    setTimeout(function() {
      hideOverlay();
      showContent();
    }, 100);
  }

  // 监听页面加载
  if (document.readyState === 'complete') {
    onPageLoad();
  } else {
    window.addEventListener('load', onPageLoad);
    // DOMContentLoaded 时也尝试隐藏（如果资源加载太慢）
    document.addEventListener('DOMContentLoaded', function() {
      setTimeout(onPageLoad, 300);
    });
  }

  // 兜底：2秒后强制隐藏（防止某些资源加载失败导致遮罩一直显示）
  setTimeout(function() {
    hideOverlay();
    showContent();
  }, 2000);

  // 监听所有链接点击，显示遮罩（防止跳转白屏）
  document.addEventListener('click', function(e) {
    var link = e.target.closest('a');
    if (!link) return;

    var href = link.getAttribute('href');
    if (!href) return;

    // 跳过锚点链接、javascript链接、外链、新窗口打开
    if (href.charAt(0) === '#' ||
        href.indexOf('javascript:') === 0 ||
        link.target === '_blank' ||
        link.hasAttribute('download') ||
        e.defaultPrevented) {
      return;
    }

    // 只处理同域链接
    try {
      var url = new URL(href, window.location.origin);
      if (url.origin !== window.location.origin) return;
    } catch (e) {
      return;
    }

    // 显示遮罩
    showOverlay();
  }, true);

  // 监听表单提交
  document.addEventListener('submit', function(e) {
    var form = e.target;
    if (!form || form.method.toLowerCase() !== 'get') return;
    showOverlay();
  }, true);

  // 监听 pageshow（bfcache 恢复时）
  window.addEventListener('pageshow', function(e) {
    if (e.persisted) {
      // 从 bfcache 恢复时，立即隐藏遮罩
      hideOverlay();
      showContent();
    }
  });

  // 暴露全局函数（供其他脚本调用）
  window.PageTransition = {
    show: showOverlay,
    hide: hideOverlay,
    create: createOverlay
  };

})();
