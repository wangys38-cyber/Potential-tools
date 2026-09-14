"""
插件管理路由 v8.1
"""
import os
import json
import time
import logging
from flask import Blueprint, request, jsonify, render_template, g

from core.plugin import get_plugin_loader

logger = logging.getLogger(__name__)

bp = Blueprint('plugins', __name__, url_prefix='/api/plugins')


def _require_login():
    """简易登录检查"""
    user = getattr(g, 'user', None)
    if not user or not user.get('id'):
        return None, (jsonify({'error': '未登录'}), 401)
    return user['id'], None


@bp.route('/list', methods=['GET'])
def list_plugins():
    """获取所有插件列表"""
    loader = get_plugin_loader()
    plugins = loader.get_all_plugins()
    return jsonify({'status': 'success', 'plugins': plugins, 'count': len(plugins)})


@bp.route('/<plugin_id>/enable', methods=['POST'])
def enable_plugin(plugin_id):
    """启用插件"""
    user_id, err = _require_login()
    if err:
        return err

    loader = get_plugin_loader()
    if loader.enable_plugin(plugin_id):
        # 注册插件路由
        from app import app
        loader.register_routes(app)
        return jsonify({'status': 'success', 'message': f'插件 {plugin_id} 已启用'})
    return jsonify({'status': 'error', 'error': '启用失败'}), 500


@bp.route('/<plugin_id>/disable', methods=['POST'])
def disable_plugin(plugin_id):
    """禁用插件"""
    user_id, err = _require_login()
    if err:
        return err

    loader = get_plugin_loader()
    if loader.disable_plugin(plugin_id):
        return jsonify({'status': 'success', 'message': f'插件 {plugin_id} 已禁用'})
    return jsonify({'status': 'error', 'error': '禁用失败'}), 500


@bp.route('/<plugin_id>/settings', methods=['GET'])
def get_plugin_settings(plugin_id):
    """获取插件配置"""
    loader = get_plugin_loader()
    plugin = loader.get_plugin(plugin_id)
    if not plugin:
        return jsonify({'status': 'error', 'error': '插件未加载'}), 404

    settings = plugin.get_settings()
    schema = plugin.meta.get('settings', [])
    return jsonify({'status': 'success', 'settings': settings, 'schema': schema})


@bp.route('/<plugin_id>/settings', methods=['POST'])
def save_plugin_settings(plugin_id):
    """保存插件配置"""
    user_id, err = _require_login()
    if err:
        return err

    loader = get_plugin_loader()
    plugin = loader.get_plugin(plugin_id)
    if not plugin:
        return jsonify({'status': 'error', 'error': '插件未加载'}), 404

    data = request.get_json(silent=True) or {}
    if plugin.save_settings(data):
        plugin.on_settings_change(data)
        return jsonify({'status': 'success', 'message': '配置已保存'})
    return jsonify({'status': 'error', 'error': '保存失败'}), 500


@bp.route('/<plugin_id>/info', methods=['GET'])
def get_plugin_info(plugin_id):
    """获取插件详细信息"""
    loader = get_plugin_loader()
    plugin = loader.get_plugin(plugin_id)
    if plugin:
        return jsonify({'status': 'success', 'plugin': plugin.get_info()})

    # 尝试从元数据获取
    for meta in loader.discover_plugins():
        if meta['id'] == plugin_id:
            return jsonify({
                'status': 'success',
                'plugin': {
                    'id': meta['id'],
                    'name': meta.get('name', ''),
                    'version': meta.get('version', ''),
                    'description': meta.get('description', ''),
                    'author': meta.get('author', ''),
                    'permissions': meta.get('permissions', []),
                    'enabled': False,
                }
            })
    return jsonify({'status': 'error', 'error': '插件不存在'}), 404


@bp.route('/reload', methods=['POST'])
def reload_plugins():
    """重新加载所有插件"""
    user_id, err = _require_login()
    if err:
        return err

    loader = get_plugin_loader()
    # 卸载所有
    for pid in list(loader.plugins.keys()):
        loader.unload_plugin(pid)
    # 重新加载
    count = loader.load_all_plugins()
    # 重新注册路由
    from app import app
    loader.register_routes(app)
    return jsonify({'status': 'success', 'message': f'已重新加载 {count} 个插件', 'count': count})


# ==================== 插件市场 API ====================

MARKET_INDEX_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'plugins', 'market_index.json')


def _load_market_index():
    """加载市场索引"""
    try:
        with open(MARKET_INDEX_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载市场索引失败: {e}")
        return {'categories': [], 'plugins': []}


@bp.route('/market', methods=['GET'])
def market_list():
    """获取市场插件列表，支持搜索和分类筛选"""
    keyword = request.args.get('keyword', '').strip().lower()
    category = request.args.get('category', '').strip()

    index = _load_market_index()
    plugins = index.get('plugins', [])
    categories = index.get('categories', [])

    # 筛选
    if keyword:
        plugins = [p for p in plugins if
                   keyword in p.get('name', '').lower() or
                   keyword in p.get('description', '').lower() or
                   keyword in p.get('author', '').lower() or
                   any(keyword in t.lower() for t in p.get('tags', []))]
    if category:
        plugins = [p for p in plugins if p.get('category') == category]

    # 标记已安装状态和版本
    loader = get_plugin_loader()
    installed_ids = set(loader.plugins.keys())
    for p in plugins:
        p['installed'] = p['id'] in installed_ids
        if p['installed']:
            installed = loader.get_plugin(p['id'])
            if installed:
                p['installed_version'] = installed.version
                p['has_update'] = _compare_versions(p['version'], installed.version) > 0
            else:
                p['installed_version'] = None
                p['has_update'] = False
        else:
            p['installed_version'] = None
            p['has_update'] = False

    return jsonify({
        'status': 'success',
        'plugins': plugins,
        'categories': categories,
        'total': len(plugins),
    })


@bp.route('/market/<plugin_id>/install', methods=['POST'])
def market_install(plugin_id):
    """从市场安装插件"""
    user_id, err = _require_login()
    if err:
        return err

    index = _load_market_index()
    plugin_meta = None
    for p in index.get('plugins', []):
        if p['id'] == plugin_id:
            plugin_meta = p
            break

    if not plugin_meta:
        return jsonify({'status': 'error', 'error': '市场中未找到该插件'}), 404

    source = plugin_meta.get('source', {})
    source_type = source.get('type', 'local')

    try:
        if source_type == 'local':
            # 本地插件，直接启用
            loader = get_plugin_loader()
            if loader.enable_plugin(plugin_id):
                from app import app
                loader.register_routes(app)
                return jsonify({'status': 'success', 'message': f'插件 {plugin_id} 已安装并启用'})
            return jsonify({'status': 'error', 'error': '启用失败'}), 500

        elif source_type == 'github':
            # 从 GitHub 安装（简化实现：提示需要手动下载）
            return jsonify({
                'status': 'success',
                'message': f'插件 {plugin_id} 安装包准备中',
                'install_url': f'https://github.com/{source.get("repo", "")}/archive/refs/heads/main.zip',
                'note': '请下载后解压到 plugins/ 目录，然后点击重新加载'
            })

        elif source_type == 'url':
            # 从 URL 下载安装
            download_url = source.get('url', '')
            if not download_url:
                return jsonify({'status': 'error', 'error': '下载地址无效'}), 400
            return _install_from_url(plugin_id, download_url, plugin_meta)

        else:
            return jsonify({'status': 'error', 'error': f'不支持的安装类型: {source_type}'}), 400

    except Exception as e:
        logger.error(f"安装插件失败 {plugin_id}: {e}")
        return jsonify({'status': 'error', 'error': f'安装失败: {str(e)}'}), 500


@bp.route('/market/<plugin_id>/update', methods=['POST'])
def market_update(plugin_id):
    """更新已安装的插件"""
    user_id, err = _require_login()
    if err:
        return err

    loader = get_plugin_loader()
    if plugin_id not in loader.plugins:
        return jsonify({'status': 'error', 'error': '插件未安装'}), 404

    # 重新加载插件
    loader.unload_plugin(plugin_id)
    if loader.load_plugin(plugin_id):
        from app import app
        loader.register_routes(app)
        return jsonify({'status': 'success', 'message': f'插件 {plugin_id} 已更新'})
    return jsonify({'status': 'error', 'error': '更新失败'}), 500


@bp.route('/market/check-updates', methods=['GET'])
def market_check_updates():
    """检查所有已安装插件的更新"""
    loader = get_plugin_loader()
    index = _load_market_index()
    market_plugins = {p['id']: p for p in index.get('plugins', [])}

    updates = []
    for pid, plugin in loader.plugins.items():
        if pid in market_plugins:
            latest = market_plugins[pid]['version']
            current = plugin.version
            if _compare_versions(latest, current) > 0:
                updates.append({
                    'id': pid,
                    'name': plugin.name,
                    'current_version': current,
                    'latest_version': latest,
                })

    return jsonify({'status': 'success', 'updates': updates, 'count': len(updates)})


@bp.route('/market/<plugin_id>/detail', methods=['GET'])
def market_detail(plugin_id):
    """获取市场插件详情"""
    index = _load_market_index()
    for p in index.get('plugins', []):
        if p['id'] == plugin_id:
            return jsonify({'status': 'success', 'plugin': p})
    return jsonify({'status': 'error', 'error': '插件不存在'}), 404


def _install_from_url(plugin_id, url, plugin_meta):
    """从 URL 下载并安装插件（简化实现）"""
    import zipfile
    import tempfile
    import urllib.request

    plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'plugins')
    plugin_dir = os.path.join(plugins_dir, plugin_id)

    try:
        # 下载 ZIP
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            urllib.request.urlretrieve(url, tmp.name)
            zip_path = tmp.name

        # 解压
        os.makedirs(plugin_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(plugin_dir)

        os.unlink(zip_path)

        # 启用插件
        loader = get_plugin_loader()
        if loader.enable_plugin(plugin_id):
            from app import app
            loader.register_routes(app)
            return jsonify({'status': 'success', 'message': f'插件 {plugin_id} 安装成功'})
        return jsonify({'status': 'error', 'error': '插件下载成功但启用失败'}), 500

    except Exception as e:
        logger.error(f"从 URL 安装插件失败: {e}")
        return jsonify({'status': 'error', 'error': f'下载安装失败: {str(e)}'}), 500


def _compare_versions(v1, v2):
    """比较版本号，v1 > v2 返回 1，v1 < v2 返回 -1，相等返回 0"""
    try:
        parts1 = [int(x) for x in str(v1).split('.')]
        parts2 = [int(x) for x in str(v2).split('.')]
        # 补齐长度
        max_len = max(len(parts1), len(parts2))
        parts1.extend([0] * (max_len - len(parts1)))
        parts2.extend([0] * (max_len - len(parts2)))
        for a, b in zip(parts1, parts2):
            if a > b:
                return 1
            if a < b:
                return -1
        return 0
    except:
        return 0


# ==================== 插件模板生成器 ====================

@bp.route('/generator/templates', methods=['GET'])
def get_templates():
    """获取可用的插件模板列表"""
    templates = [
        {
            'id': 'basic',
            'name': '基础插件',
            'description': '最简单的插件模板，包含基本结构',
            'icon': '📦',
            'permissions': [],
        },
        {
            'id': 'api-plugin',
            'name': 'API 插件',
            'description': '包含自定义 API 路由的插件模板',
            'icon': '🔌',
            'permissions': ['routes'],
        },
        {
            'id': 'page-plugin',
            'name': '页面插件',
            'description': '包含自定义前端页面的插件模板',
            'icon': '📄',
            'permissions': ['routes', 'pages'],
        },
        {
            'id': 'data-plugin',
            'name': '数据插件',
            'description': '包含数据库访问的插件模板',
            'icon': '🗄️',
            'permissions': ['database', 'routes'],
        },
        {
            'id': 'full-plugin',
            'name': '完整插件',
            'description': '包含 API、页面、数据库的完整插件模板',
            'icon': '🚀',
            'permissions': ['database', 'database_write', 'routes', 'pages'],
        },
    ]
    return jsonify({'status': 'success', 'templates': templates})


@bp.route('/generator/generate', methods=['POST'])
def generate_plugin():
    """生成插件模板"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    plugin_id = data.get('id', '').strip()
    plugin_name = data.get('name', '').strip()
    description = data.get('description', '')
    author = data.get('author', 'Anonymous')
    template_id = data.get('template', 'basic')
    permissions = data.get('permissions', [])

    # 校验
    if not plugin_id or not plugin_name:
        return jsonify({'status': 'error', 'error': '插件ID和名称必填'}), 400

    import re
    if not re.match(r'^[a-z][a-z0-9-]*$', plugin_id):
        return jsonify({'status': 'error', 'error': '插件ID只能包含小写字母、数字和连字符，且以字母开头'}), 400

    plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'plugins')
    plugin_dir = os.path.join(plugins_dir, plugin_id)

    if os.path.exists(plugin_dir):
        return jsonify({'status': 'error', 'error': '插件ID已存在'}), 400

    try:
        # 创建目录结构
        os.makedirs(os.path.join(plugin_dir, 'backend'), exist_ok=True)
        os.makedirs(os.path.join(plugin_dir, 'frontend'), exist_ok=True)

        # 生成 plugin.json
        plugin_json = {
            'id': plugin_id,
            'name': plugin_name,
            'version': '1.0.0',
            'description': description,
            'author': author,
            'min_app_version': '8.1.0',
            'permissions': permissions,
            'entry': {
                'backend': 'backend.main:MyPlugin',
                'frontend': 'frontend/index.js'
            },
            'settings': []
        }
        with open(os.path.join(plugin_dir, 'plugin.json'), 'w', encoding='utf-8') as f:
            json.dump(plugin_json, f, ensure_ascii=False, indent=2)

        # 生成 backend/__init__.py
        with open(os.path.join(plugin_dir, 'backend', '__init__.py'), 'w') as f:
            f.write('')

        # 生成 backend/main.py
        backend_code = _generate_backend_code(template_id, plugin_name, permissions)
        with open(os.path.join(plugin_dir, 'backend', 'main.py'), 'w', encoding='utf-8') as f:
            f.write(backend_code)

        # 生成 frontend/index.js
        frontend_code = f'''/**
 * {plugin_name} 前端脚本
 */
(function() {{
    'use strict';
    console.log('[{plugin_name}] 已加载');
}})();
'''
        with open(os.path.join(plugin_dir, 'frontend', 'index.js'), 'w', encoding='utf-8') as f:
            f.write(frontend_code)

        # 生成 README.md
        readme = f'''# {plugin_name}

{description}

## 功能
- 待补充

## 开发
- 后端入口: backend/main.py
- 前端入口: frontend/index.js
- 配置文件: plugin.json

## 版本
- v1.0.0 初始版本
'''
        with open(os.path.join(plugin_dir, 'README.md'), 'w', encoding='utf-8') as f:
            f.write(readme)

        return jsonify({
            'status': 'success',
            'message': f'插件 {plugin_name} 已生成',
            'plugin_id': plugin_id,
            'path': plugin_dir,
        })

    except Exception as e:
        logger.error(f"生成插件失败: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


def _generate_backend_code(template_id, plugin_name, permissions):
    """根据模板生成后端代码"""
    has_routes = 'routes' in permissions
    has_pages = 'pages' in permissions
    has_database = 'database' in permissions or 'database_write' in permissions

    code = f'''"""
{plugin_name} v1.0.0
"""
from core.plugin.base import PluginBase


class MyPlugin(PluginBase):
    """{plugin_name}"""

    def on_activate(self) -> bool:
        """插件激活时调用"""
        self.log("{plugin_name} 激活")
'''

    if has_routes:
        code += '''
        # 注册 API 路由
        self.api.add_route('/hello', self.hello_handler, methods=['GET'])
'''

    if has_pages:
        code += '''
        # 注册前端页面
        self.api.add_page('/index', html=self._get_page_html())
'''

    if has_database:
        code += '''
        # 初始化数据库表（如需）
        # self._init_database()
'''

    code += '''
        return True

    def on_deactivate(self):
        """插件停用时调用"""
        self.log("插件已停用")
'''

    if has_routes:
        code += '''
    def hello_handler(self):
        """示例 API 处理函数"""
        from flask import jsonify
        return jsonify({
            'status': 'success',
            'message': 'Hello from plugin!',
            'plugin': self.name,
            'version': self.version,
        })
'''

    if has_pages:
        code += '''
    def _get_page_html(self) -> str:
        """生成插件页面 HTML"""
        return \'\'\'
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>''' + plugin_name + '''</title>
            <style>
                body { font-family: -apple-system, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
                h1 { color: #1d1d1f; }
            </style>
        </head>
        <body>
            <h1>''' + plugin_name + '''</h1>
            <p>这是插件页面，你可以在这里添加自定义内容。</p>
        </body>
        </html>
        \'\'\'
'''

    if has_database:
        code += '''
    def _init_database(self):
        """初始化插件数据表"""
        try:
            self.api.execute("""
                CREATE TABLE IF NOT EXISTS my_plugin_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT,
                    value TEXT,
                    created_at REAL
                )
            """)
            self.log("数据库表初始化完成")
        except Exception as e:
            self.log(f"数据库初始化失败: {e}", "error")
'''

    return code


# ==================== 插件安全审计 ====================

@bp.route('/security/audit', methods=['POST'])
def security_audit():
    """对指定插件进行安全审计"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    plugin_id = data.get('plugin_id', '')

    if not plugin_id:
        return jsonify({'status': 'error', 'error': '请指定插件ID'}), 400

    plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'plugins')
    plugin_dir = os.path.join(plugins_dir, plugin_id)

    if not os.path.exists(plugin_dir):
        return jsonify({'status': 'error', 'error': '插件不存在'}), 404

    findings = []
    warnings = []
    info = []

    # 1. 检查 plugin.json
    manifest_path = os.path.join(plugin_dir, 'plugin.json')
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

            # 检查权限
            perms = manifest.get('permissions', [])
            dangerous_perms = ['database_write', 'network', 'filesystem']
            for p in dangerous_perms:
                if p in perms:
                    warnings.append(f'插件声明了高风险权限: {p}')

            # 检查必需字段
            required = ['id', 'name', 'version', 'entry']
            for field in required:
                if field not in manifest:
                    findings.append(f'缺少必需字段: {field}')

            info.append(f'插件版本: {manifest.get("version", "unknown")}')
            info.append(f'声明权限: {", ".join(perms) if perms else "无"}')

        except Exception as e:
            findings.append(f'plugin.json 解析失败: {e}')
    else:
        findings.append('缺少 plugin.json 描述文件')

    # 2. 扫描后端代码中的危险操作
    backend_dir = os.path.join(plugin_dir, 'backend')
    if os.path.exists(backend_dir):
        for root, dirs, files in os.walk(backend_dir):
            for fname in files:
                if fname.endswith('.py'):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            content = f.read()

                        # 检查危险操作
                        danger_patterns = [
                            ('os.system', '执行系统命令'),
                            ('subprocess', '创建子进程'),
                            ('eval(', '动态代码执行'),
                            ('exec(', '动态代码执行'),
                            ('__import__', '动态导入'),
                            ('pickle.loads', '反序列化漏洞风险'),
                            ('shell=True', '命令注入风险'),
                        ]
                        for pattern, desc in danger_patterns:
                            if pattern in content:
                                findings.append(f'{fname}: 检测到危险操作 - {desc} ({pattern})')

                        # 检查 SQL 拼接
                        if 'execute(' in content and '%' in content:
                            warnings.append(f'{fname}: 可能存在 SQL 字符串拼接，建议使用参数化查询')

                        # 检查文件操作
                        if 'open(' in content and ('w' in content or 'a' in content):
                            warnings.append(f'{fname}: 检测到文件写操作')

                    except Exception as e:
                        warnings.append(f'无法读取 {fname}: {e}')

    # 3. 检查前端代码
    frontend_dir = os.path.join(plugin_dir, 'frontend')
    if os.path.exists(frontend_dir):
        for root, dirs, files in os.walk(frontend_dir):
            for fname in files:
                if fname.endswith('.js'):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        if 'innerHTML' in content or 'document.write' in content:
                            warnings.append(f'{fname}: 检测到 innerHTML/document.write，可能存在 XSS 风险')
                        if 'eval(' in content:
                            findings.append(f'{fname}: 检测到 eval() 调用')
                    except:
                        pass

    # 评级
    if findings:
        risk_level = 'high'
        risk_desc = '高风险'
    elif warnings:
        risk_level = 'medium'
        risk_desc = '中风险'
    else:
        risk_level = 'low'
        risk_desc = '低风险'

    return jsonify({
        'status': 'success',
        'plugin_id': plugin_id,
        'risk_level': risk_level,
        'risk_desc': risk_desc,
        'findings': findings,
        'warnings': warnings,
        'info': info,
        'summary': f'发现 {len(findings)} 个问题，{len(warnings)} 个警告',
    })
