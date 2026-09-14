/**
 * v8.0 跨工具数据联动 JS
 * 提供统一的推送、消费、查看功能
 */
(function() {
    'use strict';

    const API_BASE = '/api/ai/pipeline';

    // ==================== 推送数据 ====================
    window.pushToPipeline = function(pipelineKey, data, title, metadata) {
        return fetch(API_BASE + '/push', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pipeline_key: pipelineKey,
                data: data,
                title: title || '',
                metadata: metadata || {},
            })
        })
        .then(r => r.json())
        .then(result => {
            if (result.status === 'success') {
                showToast('✅ ' + (result.message || '数据已推送'));
            } else {
                showToast('❌ 推送失败: ' + (result.error || '未知错误'));
            }
            return result;
        })
        .catch(err => {
            showToast('❌ 推送失败: ' + err.message);
            return { status: 'error', error: err.message };
        });
    };

    // ==================== 消费数据 ====================
    window.consumePipelineData = function(targetTool) {
        return fetch(API_BASE + '/consume', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_tool: targetTool })
        })
        .then(r => r.json())
        .then(result => {
            if (result.status === 'success' && result.count > 0) {
                return result.data;
            }
            return [];
        })
        .catch(() => []);
    };

    // ==================== 查看待消费数据 ====================
    window.peekPipelineData = function(targetTool) {
        return fetch(API_BASE + '/peek?target_tool=' + encodeURIComponent(targetTool))
            .then(r => r.json())
            .then(result => result.data || [])
            .catch(() => []);
    };

    // ==================== 执行完整工作流 ====================
    window.executeFullWorkflow = function(crData, trendImage) {
        return fetch(API_BASE + '/full-workflow', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                cr_data: crData,
                trend_image: trendImage,
            })
        })
        .then(r => r.json())
        .then(result => {
            if (result.status === 'success') {
                const s = result.summary || {};
                showToast(`✅ 工作流完成：趋势${s.trend_pushed ? '✓' : '✗'} 邮件${s.email_pushed ? '✓' : '✗'} 任务${s.tasks_created}个`);
            } else {
                showToast('❌ 工作流执行失败: ' + (result.error || '未知错误'));
            }
            return result;
        })
        .catch(err => {
            showToast('❌ 执行失败: ' + err.message);
            return { status: 'error' };
        });
    };

    // ==================== 获取可用工作流 ====================
    window.getAvailablePipelines = function() {
        return fetch(API_BASE + '/list')
            .then(r => r.json())
            .then(result => result.pipelines || [])
            .catch(() => []);
    };

    // ==================== 显示联动通知 ====================
    window.showPipelineNotification = function(data, targetTool) {
        if (!data || data.length === 0) return;

        const item = data[0];
        const notification = document.createElement('div');
        notification.style.cssText = 'position:fixed;top:70px;right:20px;z-index:99998;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:16px 20px;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.2);max-width:360px;cursor:pointer;animation:slideIn 0.3s ease;';
        notification.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                <span style="font-size:20px;">📥</span>
                <span style="font-weight:600;font-size:14px;">收到来自 ${item.source_tool || '其他工具'} 的数据</span>
            </div>
            <div style="font-size:12px;opacity:0.9;margin-bottom:10px;">${item.title || '未命名数据'}</div>
            <div style="display:flex;gap:8px;">
                <button id="pipelineImportBtn" style="padding:6px 14px;background:#fff;color:#667eea;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;">立即导入</button>
                <button id="pipelineIgnoreBtn" style="padding:6px 14px;background:rgba(255,255,255,0.2);color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;">忽略</button>
            </div>
        `;
        document.body.appendChild(notification);

        document.getElementById('pipelineImportBtn').onclick = function() {
            notification.remove();
            if (window.onPipelineDataImport) {
                window.onPipelineDataImport(data);
            }
        };
        document.getElementById('pipelineIgnoreBtn').onclick = function() {
            notification.remove();
        };

        // 5秒后自动消失
        setTimeout(() => {
            if (notification.parentNode) notification.remove();
        }, 8000);
    };

    // ==================== 工具函数 ====================
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
