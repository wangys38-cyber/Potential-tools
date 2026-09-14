"""
插件核心框架 v8.1
提供插件加载、生命周期管理、API 访问
"""
from .loader import PluginLoader, get_plugin_loader
from .base import PluginBase
from .api import PluginAPI

__all__ = ['PluginLoader', 'get_plugin_loader', 'PluginBase', 'PluginAPI']
