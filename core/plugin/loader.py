"""
插件加载器 v8.1
负责扫描、加载、校验、管理插件
"""
import os
import sys
import json
import time
import logging
import importlib
import importlib.util
from typing import Dict, List, Optional, Any

from .base import PluginBase
from .api import PluginAPI

logger = logging.getLogger(__name__)

# 插件目录
PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'plugins')

# 必需的 plugin.json 字段
REQUIRED_FIELDS = ['id', 'name', 'version', 'entry']

# 支持的权限
VALID_PERMISSIONS = ['database', 'database_write', 'routes', 'pages', 'tools', 'network', 'filesystem']


class PluginLoader:
    """插件加载器（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.plugins: Dict[str, PluginBase] = {}  # 已加载的插件实例
        self.plugin_metas: Dict[str, Dict] = {}   # 插件元数据
        self.disabled_plugins: set = set()        # 已禁用的插件 ID
        self._app = None

    def init_app(self, app):
        """初始化 Flask 应用"""
        self._app = app

    def discover_plugins(self) -> List[Dict]:
        """扫描插件目录，发现所有插件"""
        plugins = []
        if not os.path.exists(PLUGINS_DIR):
            os.makedirs(PLUGINS_DIR, exist_ok=True)
            return plugins

        for item in os.listdir(PLUGINS_DIR):
            plugin_path = os.path.join(PLUGINS_DIR, item)
            if not os.path.isdir(plugin_path):
                continue

            manifest_path = os.path.join(plugin_path, 'plugin.json')
            if not os.path.exists(manifest_path):
                continue

            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)

                # 校验必需字段
                missing = [f for f in REQUIRED_FIELDS if f not in meta]
                if missing:
                    logger.warning(f"插件 {item} 缺少必需字段: {missing}")
                    continue

                meta['_path'] = plugin_path
                plugins.append(meta)
            except Exception as e:
                logger.error(f"加载插件清单失败 {item}: {e}")

        return plugins

    def load_plugin(self, plugin_id: str) -> Optional[PluginBase]:
        """加载单个插件"""
        if plugin_id in self.plugins:
            return self.plugins[plugin_id]

        if plugin_id in self.disabled_plugins:
            logger.info(f"插件 {plugin_id} 已禁用，跳过加载")
            return None

        # 查找插件
        meta = None
        for p in self.discover_plugins():
            if p['id'] == plugin_id:
                meta = p
                break

        if not meta:
            logger.error(f"未找到插件: {plugin_id}")
            return None

        # 校验权限
        permissions = meta.get('permissions', [])
        invalid_perms = [p for p in permissions if p not in VALID_PERMISSIONS]
        if invalid_perms:
            logger.warning(f"插件 {plugin_id} 包含无效权限: {invalid_perms}")

        try:
            # 创建 API 实例
            api = PluginAPI(plugin_id, self._app)
            api.set_permissions(permissions)

            # 动态导入插件后端
            entry = meta.get('entry', {})
            backend_entry = entry.get('backend', '')

            plugin_instance = None
            if backend_entry:
                module_path, class_name = backend_entry.split(':') if ':' in backend_entry else (backend_entry, 'Plugin')

                # 将插件目录加入 sys.path
                plugin_path = meta['_path']
                if plugin_path not in sys.path:
                    sys.path.insert(0, plugin_path)

                try:
                    spec = importlib.util.spec_from_file_location(
                        f"plugin_{plugin_id}",
                        os.path.join(plugin_path, module_path.replace('.', '/') + '.py')
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        plugin_class = getattr(module, class_name, None)
                        if plugin_class and issubclass(plugin_class, PluginBase):
                            plugin_instance = plugin_class(meta, api)
                except Exception as e:
                    logger.error(f"导入插件后端失败 {plugin_id}: {e}")
                    import traceback
                    traceback.print_exc()

            # 如果没有后端入口或导入失败，使用基类
            if not plugin_instance:
                plugin_instance = PluginBase(meta, api)

            # 调用 on_activate
            if plugin_instance.on_activate():
                self.plugins[plugin_id] = plugin_instance
                self.plugin_metas[plugin_id] = meta
                logger.info(f"插件加载成功: {plugin_id} v{meta.get('version')}")
                return plugin_instance
            else:
                logger.error(f"插件激活失败: {plugin_id}")
                return None

        except Exception as e:
            logger.error(f"加载插件失败 {plugin_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def load_all_plugins(self) -> int:
        """加载所有启用的插件"""
        count = 0
        for meta in self.discover_plugins():
            plugin_id = meta['id']
            if plugin_id not in self.disabled_plugins:
                if self.load_plugin(plugin_id):
                    count += 1
        logger.info(f"已加载 {count} 个插件")
        return count

    def unload_plugin(self, plugin_id: str) -> bool:
        """卸载插件"""
        if plugin_id not in self.plugins:
            return False
        try:
            self.plugins[plugin_id].on_deactivate()
        except Exception as e:
            logger.error(f"插件停用异常 {plugin_id}: {e}")
        del self.plugins[plugin_id]
        return True

    def enable_plugin(self, plugin_id: str) -> bool:
        """启用插件"""
        self.disabled_plugins.discard(plugin_id)
        return self.load_plugin(plugin_id) is not None

    def disable_plugin(self, plugin_id: str) -> bool:
        """禁用插件"""
        self.disabled_plugins.add(plugin_id)
        return self.unload_plugin(plugin_id)

    def get_plugin(self, plugin_id: str) -> Optional[PluginBase]:
        """获取插件实例"""
        return self.plugins.get(plugin_id)

    def get_all_plugins(self) -> List[Dict]:
        """获取所有插件信息（包括未加载的）"""
        result = []
        for meta in self.discover_plugins():
            plugin_id = meta['id']
            result.append({
                'id': plugin_id,
                'name': meta.get('name', ''),
                'version': meta.get('version', ''),
                'description': meta.get('description', ''),
                'author': meta.get('author', ''),
                'permissions': meta.get('permissions', []),
                'enabled': plugin_id in self.plugins,
                'loaded': plugin_id in self.plugins,
                'settings_schema': meta.get('settings', []),
            })
        return result

    def register_routes(self, app) -> int:
        """将所有插件的路由和页面注册到 Flask 应用"""
        count = 0
        for plugin_id, plugin in self.plugins.items():
            api = plugin.api
            # 注册 API 路由
            for route in api._routes:
                try:
                    app.add_url_rule(
                        route['path'],
                        f"plugin_{plugin_id}_{route['path']}",
                        route['handler'],
                        methods=route['methods']
                    )
                    count += 1
                except Exception as e:
                    logger.error(f"注册插件路由失败 {plugin_id}: {e}")

            # 注册页面路由
            for page in api._pages:
                try:
                    page_html = page.get('html', '')
                    page_path = page['path']

                    def make_page_handler(html_content):
                        def page_handler():
                            from flask import Response
                            return Response(html_content, mimetype='text/html')
                        return page_handler

                    app.add_url_rule(
                        page_path,
                        f"plugin_page_{plugin_id}_{page_path}",
                        make_page_handler(page_html),
                        methods=['GET']
                    )
                    count += 1
                except Exception as e:
                    logger.error(f"注册插件页面失败 {plugin_id}: {e}")

        return count


def get_plugin_loader() -> PluginLoader:
    """获取插件加载器单例"""
    return PluginLoader()
