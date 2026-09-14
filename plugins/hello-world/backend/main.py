"""
Hello World 示例插件 v1.0.0
演示插件开发流程
"""
import time
from core.plugin.base import PluginBase


class HelloWorldPlugin(PluginBase):
    """Hello World 示例插件"""

    def on_activate(self) -> bool:
        """插件激活时注册路由和页面"""
        self.log("Hello World 插件激活中...")

        # 注册 API 路由
        self.api.add_route('/greet', self.greet_handler, methods=['GET'])
        self.api.add_route('/info', self.info_handler, methods=['GET'])

        # 注册前端页面
        self.api.add_page('/hello', html=self._get_page_html())

        self.log("Hello World 插件激活成功")
        return True

    def on_deactivate(self):
        """插件停用时"""
        self.log("Hello World 插件已停用")

    def greet_handler(self):
        """问候 API"""
        from flask import request, jsonify
        name = request.args.get('name', '世界')
        settings = self.get_settings()
        greeting = settings.get('greeting', '你好')
        show_time = settings.get('show_time', True)

        result = {
            'message': f'{greeting}，{name}！',
            'plugin': self.name,
            'version': self.version,
        }
        if show_time:
            result['time'] = time.strftime('%Y-%m-%d %H:%M:%S')

        return jsonify(result)

    def info_handler(self):
        """插件信息 API"""
        from flask import jsonify
        return jsonify({
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'description': self.meta.get('description', ''),
            'settings': self.get_settings(),
        })

    def _get_page_html(self) -> str:
        """生成插件页面 HTML"""
        return '''
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>Hello World 插件</title>
            <style>
                body { font-family: -apple-system, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
                h1 { color: #1d1d1f; }
                .greeting { font-size: 24px; color: #007aff; margin: 20px 0; }
                button { padding: 10px 20px; background: #007aff; color: #fff; border: none; border-radius: 8px; cursor: pointer; }
                input { padding: 8px 12px; border: 1px solid #d2d2d7; border-radius: 8px; margin-right: 10px; }
            </style>
        </head>
        <body>
            <h1>👋 Hello World 插件</h1>
            <p>这是一个示例插件页面，演示插件如何注册自定义页面。</p>
            <div>
                <input type="text" id="nameInput" placeholder="输入你的名字" value="王大锤">
                <button onclick="greet()">打招呼</button>
            </div>
            <div class="greeting" id="greetingResult"></div>
            <script>
                function greet() {
                    const name = document.getElementById('nameInput').value;
                    fetch('/api/plugin/hello-world/greet?name=' + encodeURIComponent(name))
                        .then(r => r.json())
                        .then(data => {
                            document.getElementById('greetingResult').textContent = data.message;
                            if (data.time) {
                                document.getElementById('greetingResult').textContent += ' (' + data.time + ')';
                            }
                        });
                }
            </script>
        </body>
        </html>
        '''
