/* ===== Potential-tools 阶段五性能优化：虚拟滚动列表 =====
 * 适用于大数据量列表（Bug 列表、日志列表、搜索结果）
 * 仅渲染可视区域内的 DOM 节点，大幅减少内存占用和渲染开销
 *
 * 用法:
 *   var vs = new VirtualScroll(container, {
 *       items: [...],          // 数据数组
 *       itemHeight: 48,        // 每行高度（px），固定高度模式
 *       renderItem: function(item, index) { return htmlString or DOM },
 *       overscan: 5,           // 上下额外渲染的行数
 *   });
 *   vs.updateItems(newItems);  // 更新数据
 *   vs.destroy();              // 销毁，清理事件监听
 */
(function(global) {
    'use strict';

    function VirtualScroll(container, options) {
        this.container = container;
        this.items = options.items || [];
        this.itemHeight = options.itemHeight || 40;
        this.renderItem = options.renderItem || function(item) { return ''; };
        this.overscan = options.overscan || 3;
        this.className = options.className || 'vs-row';

        // 容器必须是可滚动的，且 position 非 static
        var cs = getComputedStyle(container);
        if (cs.position === 'static') {
            container.style.position = 'relative';
        }
        container.style.overflowY = container.style.overflowY || 'auto';

        // 创建内容垫片（撑开滚动高度）
        this.spacer = document.createElement('div');
        this.spacer.style.position = 'relative';
        this.spacer.style.width = '100%';
        container.appendChild(this.spacer);

        // 创建可视区域容器
        this.viewport = document.createElement('div');
        this.viewport.style.position = 'absolute';
        this.viewport.style.top = '0';
        this.viewport.style.left = '0';
        this.viewport.style.width = '100%';
        this.spacer.appendChild(this.viewport);

        this._scrollHandler = this._onScroll.bind(this);
        this._rafId = null;
        container.addEventListener('scroll', this._scrollHandler, { passive: true });

        this._render();
    }

    VirtualScroll.prototype._onScroll = function() {
        var self = this;
        if (this._rafId) return;
        this._rafId = requestAnimationFrame(function() {
            self._rafId = null;
            self._render();
        });
    };

    VirtualScroll.prototype._render = function() {
        var total = this.items.length;
        var scrollTop = this.container.scrollTop;
        var viewportHeight = this.container.clientHeight;

        // 计算可见范围
        var startIndex = Math.max(0, Math.floor(scrollTop / this.itemHeight) - this.overscan);
        var endIndex = Math.min(total, Math.ceil((scrollTop + viewportHeight) / this.itemHeight) + this.overscan);

        // 设置垫片总高度
        this.spacer.style.height = (total * this.itemHeight) + 'px';

        // 定位可视区域
        this.viewport.style.transform = 'translateY(' + (startIndex * this.itemHeight) + 'px)';

        // 批量构建 DOM（使用 DocumentFragment 减少重排）
        var fragment = document.createDocumentFragment();
        for (var i = startIndex; i < endIndex; i++) {
            var item = this.items[i];
            var row = document.createElement('div');
            row.className = this.className;
            row.style.height = this.itemHeight + 'px';
            row.style.boxSizing = 'border-box';
            row.dataset.index = i;

            var content = this.renderItem(item, i);
            if (typeof content === 'string') {
                row.innerHTML = content;
            } else if (content instanceof Node) {
                row.appendChild(content);
            }
            fragment.appendChild(row);
        }

        // 清空并替换（比逐个 remove 快）
        while (this.viewport.firstChild) {
            this.viewport.removeChild(this.viewport.firstChild);
        }
        this.viewport.appendChild(fragment);

        this._startIndex = startIndex;
        this._endIndex = endIndex;
    };

    VirtualScroll.prototype.updateItems = function(items) {
        this.items = items || [];
        this._render();
    };

    VirtualScroll.prototype.scrollToIndex = function(index) {
        this.container.scrollTop = index * this.itemHeight;
    };

    VirtualScroll.prototype.refresh = function() {
        this._render();
    };

    VirtualScroll.prototype.destroy = function() {
        this.container.removeEventListener('scroll', this._scrollHandler);
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
        }
        if (this.spacer && this.spacer.parentNode) {
            this.spacer.parentNode.removeChild(this.spacer);
        }
        this.container = null;
        this.items = null;
        this.renderItem = null;
    };

    // 导出
    global.VirtualScroll = VirtualScroll;

})(window);
