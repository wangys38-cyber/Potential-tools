"""
数据导出插件 v1.0.0
支持导出用户数据、CR分析数据、配置等为 Excel/CSV/JSON
"""
import json
import time
from core.plugin.base import PluginBase


class DataExporterPlugin(PluginBase):
    """数据导出插件"""

    def on_activate(self) -> bool:
        self.log("数据导出插件激活")
        self.api.add_route('/export', self.export_handler, methods=['POST'])
        self.api.add_route('/tables', self.tables_handler, methods=['GET'])
        self.api.add_page('/export', html=self._get_page_html())
        return True

    def tables_handler(self):
        """获取可导出的表列表"""
        from flask import jsonify
        tables = [
            {'name': 'users', 'label': '用户表', 'description': '所有用户信息'},
            {'name': 'user_preferences', 'label': '用户偏好', 'description': '用户配置和偏好'},
            {'name': 'user_activity', 'label': '用户活动', 'description': '用户操作记录'},
            {'name': 'notes', 'label': '笔记', 'description': '用户笔记数据'},
            {'name': 'audit_logs', 'label': '审计日志', 'description': '系统审计日志'},
        ]
        return jsonify({'status': 'success', 'tables': tables})

    def export_handler(self):
        """导出数据"""
        from flask import request, jsonify, Response
        import io
        import csv

        data = request.get_json(silent=True) or {}
        table = data.get('table', '')
        fmt = data.get('format', 'json')
        limit = min(int(data.get('limit', 1000)), 10000)

        if not table:
            return jsonify({'status': 'error', 'error': '请指定表名'}), 400

        # 安全检查表名
        allowed_tables = ['users', 'user_preferences', 'user_activity', 'notes', 'audit_logs']
        if table not in allowed_tables:
            return jsonify({'status': 'error', 'error': '不允许导出此表'}), 403

        try:
            rows = self.api.query(f"SELECT * FROM {table} LIMIT :limit", {'limit': limit})

            if fmt == 'json':
                return jsonify({
                    'status': 'success',
                    'table': table,
                    'count': len(rows),
                    'data': rows,
                })

            elif fmt == 'csv':
                output = io.StringIO()
                if rows:
                    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                csv_content = output.getvalue()
                return Response(
                    csv_content,
                    mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={table}_{int(time.time())}.csv'}
                )

            elif fmt == 'excel':
                # 简化：返回 CSV 并提示用 Excel 打开
                output = io.StringIO()
                if rows:
                    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                return Response(
                    output.getvalue(),
                    mimetype='application/vnd.ms-excel',
                    headers={'Content-Disposition': f'attachment; filename={table}_{int(time.time())}.csv'}
                )

            else:
                return jsonify({'status': 'error', 'error': '不支持的格式'}), 400

        except Exception as e:
            self.log(f"导出失败: {e}", 'error')
            return jsonify({'status': 'error', 'error': str(e)}), 500

    def _get_page_html(self) -> str:
        return '''
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>数据导出</title>
            <style>
                body { font-family: -apple-system, sans-serif; max-width: 700px; margin: 50px auto; padding: 20px; }
                h1 { color: #1d1d1f; }
                .form-group { margin-bottom: 16px; }
                label { display: block; margin-bottom: 6px; font-weight: 500; }
                select, input { width: 100%; padding: 10px; border: 1px solid #d2d2d7; border-radius: 8px; box-sizing: border-box; }
                button { padding: 12px 24px; background: #007aff; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 15px; }
                .result { margin-top: 20px; padding: 16px; background: #f5f5f7; border-radius: 8px; white-space: pre-wrap; max-height: 400px; overflow: auto; font-size: 12px; }
            </style>
        </head>
        <body>
            <h1>📤 数据导出</h1>
            <div class="form-group">
                <label>选择数据表</label>
                <select id="tableSelect"><option>加载中...</option></select>
            </div>
            <div class="form-group">
                <label>导出格式</label>
                <select id="formatSelect">
                    <option value="json">JSON</option>
                    <option value="csv">CSV</option>
                    <option value="excel">Excel (CSV)</option>
                </select>
            </div>
            <div class="form-group">
                <label>最大行数 (最多10000)</label>
                <input type="number" id="limitInput" value="1000" min="1" max="10000">
            </div>
            <button onclick="doExport()">📥 导出数据</button>
            <div class="result" id="result" style="display:none;"></div>
            <script>
                fetch('/api/plugin/data-exporter/tables').then(r=>r.json()).then(d=>{
                    const sel = document.getElementById('tableSelect');
                    sel.innerHTML = d.tables.map(t=>`<option value="${t.name}">${t.label} - ${t.description}</option>`).join('');
                });
                function doExport(){
                    const table = document.getElementById('tableSelect').value;
                    const fmt = document.getElementById('formatSelect').value;
                    const limit = document.getElementById('limitInput').value;
                    fetch('/api/plugin/data-exporter/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({table,format:fmt,limit})})
                    .then(r=>{ if(fmt==='json') return r.json(); return r.text(); })
                    .then(d=>{
                        const res = document.getElementById('result');
                        res.style.display='block';
                        res.textContent = fmt==='json' ? JSON.stringify(d,null,2) : d.substring(0,2000)+'\\n...(已下载完整文件)';
                    });
                }
            </script>
        </body>
        </html>
        '''
