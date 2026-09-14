/**
 * v8.0 跨工具数据联动 - 接收端
 * 在目标页面自动检测并导入流转数据
 * 使用方式：在目标页面引用此 JS，并设置 window.PIPELINE_TARGET_TOOL
 */
(function() {
    'use strict';

    // 目标工具标识（由页面设置）
    const TARGET_TOOL = window.PIPELINE_TARGET_TOOL || '';

    if (!TARGET_TOOL) return;

    // 页面加载后检查是否有待消费的数据
    document.addEventListener('DOMContentLoaded', function() {
        setTimeout(checkPipelineData, 500);
    });

    function checkPipelineData() {
        fetch('/api/ai/pipeline/peek?target_tool=' + encodeURIComponent(TARGET_TOOL))
            .then(r => r.json())
            .then(result => {
                const data = result.data || [];
                if (data.length > 0) {
                    showImportDialog(data);
                }
            })
            .catch(() => {});
    }

    function showImportDialog(dataList) {
        const item = dataList[0];

        // 创建通知
        const notification = document.createElement('div');
        notification.style.cssText = 'position:fixed;top:70px;right:20px;z-index:99998;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:16px 20px;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.2);max-width:380px;animation:slideIn 0.3s ease;';
        notification.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                <span style="font-size:22px;">📥</span>
                <div>
                    <div style="font-weight:600;font-size:14px;">检测到来自 ${item.source_tool || '其他工具'} 的数据</div>
                    <div style="font-size:11px;opacity:0.8;">${item.title || '未命名数据'}</div>
                </div>
            </div>
            <div style="font-size:12px;opacity:0.9;margin-bottom:12px;">
                ${dataList.length > 1 ? `共 ${dataList.length} 条数据待导入` : '点击下方按钮导入数据'}
            </div>
            <div style="display:flex;gap:8px;">
                <button id="pipelineImportBtn" style="flex:1;padding:8px 16px;background:#fff;color:#667eea;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">立即导入</button>
                <button id="pipelineIgnoreBtn" style="padding:8px 16px;background:rgba(255,255,255,0.2);color:#fff;border:none;border-radius:8px;font-size:13px;cursor:pointer;">忽略</button>
            </div>
        `;
        document.body.appendChild(notification);

        document.getElementById('pipelineImportBtn').onclick = function() {
            notification.remove();
            importData(dataList);
        };
        document.getElementById('pipelineIgnoreBtn').onclick = function() {
            notification.remove();
        };

        // 10秒后自动消失
        setTimeout(() => {
            if (notification.parentNode) notification.remove();
        }, 15000);
    }

    function importData(dataList) {
        // 消费数据（标记为已消费）
        fetch('/api/ai/pipeline/consume', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_tool: TARGET_TOOL })
        })
        .then(r => r.json())
        .then(result => {
            const data = result.data || dataList;

            // 触发页面自定义的导入回调
            if (window.onPipelineDataImport) {
                window.onPipelineDataImport(data);
            } else {
                // 默认行为：显示数据内容
                showToast('✅ 数据已导入，请查看页面内容');
                console.log('[Pipeline] 导入数据:', data);
            }
        })
        .catch(() => {
            if (window.onPipelineDataImport) {
                window.onPipelineDataImport(dataList);
            }
        });
    }

    function showToast(msg) {
        const toast = document.createElement('div');
        toast.style.cssText = 'position:fixed;top:20px;left:50%;transform:translateX(-50%);background:#1d1d1f;color:#fff;padding:10px 20px;border-radius:10px;z-index:99999;font-size:13px;box-shadow:0 4px 12px rgba(0,0,0,0.15);';
        toast.textContent = msg;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    // 添加动画样式
    const style = document.createElement('style');
    style.textContent = '@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }';
    document.head.appendChild(style);

})();
