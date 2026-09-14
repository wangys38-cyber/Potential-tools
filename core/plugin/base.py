"""
插件基类 v8.1
所有插件必须继承此类
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class PluginBase:
    """插件基类，定义插件生命周期和基本接口"""

    # 插件元数据（由 plugin.json 加载）
    meta: Dict[str, Any] = {}

    # 插件 API（由加载器注入）
    api: Optional['PluginAPI'] = None

    def __init__(self, meta: Dict[str, Any], api: 'PluginAPI'):
        self.meta = meta
        self.api = api
        self.logger = logging.getLogger(f"plugin.{meta.get('id', 'unknown')}")

    @property
    def id(self) -> str:
        return self.meta.get('id', '')

    @property
    def name(self) -> str:
        return self.meta.get('name', '')

    @property
    def version(self) -> str:
        return self.meta.get('version', '0.0.0')

    # ==================== 生命周期方法 ====================

    def on_install(self) -> bool:
        """
        插件安装时调用（首次安装）
        返回 True 表示安装成功，False 表示失败
        """
        return True

    def on_activate(self) -> bool:
        """
        插件激活时调用（每次启动或启用时）
        返回 True 表示激活成功，False 表示失败
        """
        return True

    def on_deactivate(self) -> None:
        """插件停用时调用"""
        pass

    def on_uninstall(self) -> None:
        """插件卸载时调用（清理资源）"""
        pass

    def on_settings_change(self, settings: Dict[str, Any]) -> None:
        """插件配置变更时调用"""
        pass

    # ==================== 工具方法 ====================

    def get_settings(self) -> Dict[str, Any]:
        """获取插件配置"""
        if self.api:
            return self.api.get_settings()
        return {}

    def save_settings(self, settings: Dict[str, Any]) -> bool:
        """保存插件配置"""
        if self.api:
            return self.api.save_settings(settings)
        return False

    def log(self, message: str, level: str = 'info') -> None:
        """记录日志"""
        if hasattr(self.logger, level):
            getattr(self.logger, level)(message)

    def get_info(self) -> Dict[str, Any]:
        """获取插件信息"""
        return {
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'description': self.meta.get('description', ''),
            'author': self.meta.get('author', ''),
            'permissions': self.meta.get('permissions', []),
        }
