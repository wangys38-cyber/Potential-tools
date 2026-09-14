"""
自定义仪表盘插件 v1.2.0
支持自定义卡片、布局、数据指标
"""
import json
import time
from core.plugin.base import PluginBase


class CustomDashboardPlugin(PluginBase):
    """自定义仪表盘插件"""

    def on_activate(self) -> bool:
        self.log("自定义仪表盘插件激活")
        self.api.add_route('/dashboard', self.get_dashboard, methods=['GET'])
        self.api.add_route('/dashboard', self.save_dashboard, methods=['POST'])
        self.api.add_route('/widgets', self.get_widgets, methods=['GET'])
        self.api.add_route('/stats', self.get_stats, methods=['GET'])
        self.api.add_page('/dashboard', html=self._get_page_html())
        return True

    def get_dashboard(self):
        """获取仪表盘配置"""
        from flask import jsonify
        settings = self.get_settings()
        dashboard = settings.get('dashboard_config', {
            'layout': 'grid',
            'widgets': [
                {'id': 'total_bugs', 'type': 'stat', 'title': '总Bug数', 'size': 'small'},
                {'id': 'open_bugs', 'type': 'stat', 'title': '未解决Bug', 'size': 'small'},
                {'id': 'active_users', 'type': 'stat', 'title': '活跃用户', 'size': 'small'},
                {'id': 'recent_activity', 'type': 'list', 'title': '最近活动', 'size': 'large'},
            ]
        })
        return jsonify({'status': 'success', 'dashboard': dashboard})

    def save_dashboard(self):
        """保存仪表盘配置"""
        from flask import request, jsonify
        data = request.get_json(silent=True) or {}
        settings = self.get_settings()
        settings['dashboard_config'] = data
        self.save_settings(settings)
        return jsonify({'status': 'success', 'message': '仪表盘已保存'})

    def get_widgets(self):
        """获取可用组件列表"""
        from flask import jsonify
        widgets = [
            {'id': 'total_bugs', 'name': '总Bug数', 'type': 'stat', 'icon': '🐛'},
            {'id': 'open_bugs', 'name': '未解决Bug', 'type': 'stat', 'icon': '⚠️'},
            {'id': 'resolved_bugs', 'name': '已解决Bug', 'type': 'stat', 'icon': '✅'},
            {'id': 'active_users', 'name': '活跃用户', 'type': 'stat', 'icon': '👥'},
            {'id': 'recent_activity', 'name': '最近活动', 'type': 'list', 'icon': '📋'},
            {'id': 'bug_trend', 'name': 'Bug趋势', 'type': 'chart', 'icon': '📈'},
            {'id': 'module_health', 'name': '模块健康度', 'type': 'chart', 'icon': '💊'},
            {'id': 'quick_actions', 'name': '快捷入口', 'type': 'actions', 'icon': '⚡'},
        ]
        return jsonify({'status': 'success', 'widgets': widgets})

    def get_stats(self):
        """获取统计数据"""
        from flask import jsonify
        try:
            users = self.api.query("SELECT COUNT(*) as cnt FROM users")
            activities = self.api.query("SELECT COUNT(*) as cnt FROM user_activity")
            notes = self.api.query("SELECT COUNT(*) as cnt FROM notes")
            return jsonify({
                'status': 'success',
                'stats': {
                    'total_users': users[0]['cnt'] if users else 0,
                    'total_notes': notes[0]['cnt'] if notes else 0,
                    'total_activities': activities[0]['cnt'] if activities else 0,
                }
            })
        except Exception as e:
            return jsonify({'status': 'error', 'error': str(e)}), 500

    def _get_page_html(self) -> str:
        return '''
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>自定义仪表盘</title>
            <style>
                body { font-family: -apple-system, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f7; }
                h1 { color: #1d1d1f; }
                .dashboard { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 16px; margin-top: 20px; }
                .widget { background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
                .widget-title { font-size: 13px; color: #86868b; margin-bottom: 8px; }
                .widget-value { font-size: 32px; font-weight: 700; color: #1d1d1f; }
                .widget-large { grid-column: span 2; }
                .toolbar { display: flex; gap: 10px; margin-bottom: 16px; }
                button { padding: 8px 16px; background: #007aff; color: #fff; border: none; border-radius: 8px; cursor: pointer; }
                .btn-secondary { background: #e5e5ea; color: #1d1d1f; }
            </style>
        </head>
        <body>
            <h1>📊 自定义仪表盘</h1>
            <div class="toolbar">
                <button onclick="loadStats()">🔄 刷新数据</button>
                <button class="btn-secondary" onclick="showWidgets()">➕ 添加组件</button>
            </div>
            <div class="dashboard" id="dashboard"></div>
            <script>
                function loadStats(){
                    fetch('/api/plugin/custom-dashboard/stats').then(r=>r.json()).then(d=>{
                        if(d.status==='success'){
                            document.getElementById('dashboard').innerHTML = `
                                <div class="widget"><div class="widget-title">总用户数</div><div class="widget-value">${d.stats.total_users}</div></div>
                                <div class="widget"><div class="widget-title">笔记数</div><div class="widget-value">${d.stats.total_notes}</div></div>
                                <div class="widget"><div class="widget-title">活动记录</div><div class="widget-value">${d.stats.total_activities}</div></div>
                                <div class="widget widget-large"><div class="widget-title">系统状态</div><div style="color:#34c759;font-size:18px;">✅ 运行正常</div></div>
                            `;
                        }
                    });
                }
                function showWidgets(){
                    fetch('/api/plugin/custom-dashboard/widgets').then(r=>r.json()).then(d=>{
                        alert('可用组件: ' + d.widgets.map(w=>w.name).join(', '));
                    });
                }
                loadStats();
            </script>
        </body>
        </html>
        '''
