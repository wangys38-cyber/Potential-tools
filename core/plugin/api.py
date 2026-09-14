"""
插件 API v8.1
提供给插件调用的核心功能接口
"""
import json
import logging
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)


class PluginAPI:
    """
    插件 API 接口
    插件通过此接口访问核心功能
    """

    def __init__(self, plugin_id: str, app=None):
        self.plugin_id = plugin_id
        self.app = app
        self._routes = []
        self._pages = []

    # ==================== 数据库 ====================

    def get_db_engine(self):
        """获取数据库引擎"""
        from db.base import engine
        return engine

    def query(self, sql: str, params: Dict = None) -> List[Dict]:
        """执行查询（只读）"""
        from db.base import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            return [dict(row._mapping) for row in result.fetchall()]

    def execute(self, sql: str, params: Dict = None) -> bool:
        """执行写操作（需要 database_write 权限）"""
        if not self._has_permission('database_write'):
            raise PermissionError("插件缺少 database_write 权限")
        from db.base import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text(sql), params or {})
            conn.commit()
        return True

    # ==================== 路由和页面 ====================

    def add_route(self, path: str, handler: Callable, methods: List[str] = None) -> bool:
        """注册 API 路由（需要 routes 权限）"""
        if not self._has_permission('routes'):
            raise PermissionError("插件缺少 routes 权限")
        if not path.startswith(f'/api/plugin/{self.plugin_id}'):
            path = f'/api/plugin/{self.plugin_id}{path}'
        self._routes.append({'path': path, 'handler': handler, 'methods': methods or ['GET']})
        return True

    def add_page(self, path: str, template_name: str = None, html: str = None) -> bool:
        """注册前端页面（需要 pages 权限）"""
        if not self._has_permission('pages'):
            raise PermissionError("插件缺少 pages 权限")
        if not path.startswith(f'/plugin/{self.plugin_id}'):
            path = f'/plugin/{self.plugin_id}{path}'
        self._pages.append({'path': path, 'template': template_name, 'html': html})
        return True

    # ==================== 工具调用 ====================

    def call_tool(self, tool_name: str, params: Dict = None) -> Dict:
        """调用内置工具（需要 tools 权限）"""
        if not self._has_permission('tools'):
            raise PermissionError("插件缺少 tools 权限")
        # TODO: 实现工具调用
        return {'status': 'error', 'error': '工具调用暂未实现'}

    # ==================== 配置 ====================

    def get_settings(self) -> Dict[str, Any]:
        """获取插件配置"""
        from db.base import engine
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT settings FROM plugin_settings WHERE plugin_id = :pid"
                ), {'pid': self.plugin_id}).fetchone()
                if result and result[0]:
                    return json.loads(result[0])
        except Exception as e:
            logger.debug(f"获取插件配置失败: {e}")
        return {}

    def save_settings(self, settings: Dict[str, Any]) -> bool:
        """保存插件配置"""
        from db.base import engine
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT OR REPLACE INTO plugin_settings (plugin_id, settings, updated_at)
                    VALUES (:pid, :settings, :now)
                """), {
                    'pid': self.plugin_id,
                    'settings': json.dumps(settings, ensure_ascii=False),
                    'now': __import__('time').time(),
                })
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"保存插件配置失败: {e}")
            return False

    # ==================== 日志 ====================

    def log(self, message: str, level: str = 'info') -> None:
        """记录日志"""
        logger.log(getattr(logging, level.upper(), logging.INFO),
                   f"[插件:{self.plugin_id}] {message}")

    # ==================== 权限检查 ====================

    def _has_permission(self, permission: str) -> bool:
        """检查插件是否有权限"""
        # 从 meta 中获取权限列表（由加载器设置）
        permissions = getattr(self, '_permissions', [])
        return permission in permissions

    def set_permissions(self, permissions: List[str]) -> None:
        """设置插件权限（由加载器调用）"""
        self._permissions = permissions
