# -*- coding: utf-8 -*-
"""
Agent 插件 SDK

提供插件开发的基类、工具定义、上下文和插件管理器。
"""
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PluginTool:
    """插件工具定义"""
    name: str
    description: str
    parameters: Dict = field(default_factory=dict)
    handler: Callable = None
    requires_confirmation: bool = False


@dataclass
class PluginContext:
    """插件执行上下文"""
    user_id: str = ''
    agent_id: str = ''
    task: str = ''
    execution_id: str = ''
    data: Dict = field(default_factory=dict)


class AgentPlugin:
    """Agent插件基类"""

    name: str = 'base_plugin'
    version: str = '1.0.0'
    description: str = 'Base plugin'
    author: str = ''

    def get_tools(self) -> List[PluginTool]:
        """返回插件提供的工具列表"""
        return []

    def on_load(self):
        """插件加载时调用"""
        pass

    def on_unload(self):
        """插件卸载时调用"""
        pass

    def get_info(self) -> Dict:
        """获取插件信息"""
        return {
            'name': self.name,
            'version': self.version,
            'description': self.description,
            'author': self.author,
            'tools': [{'name': t.name, 'description': t.description} for t in self.get_tools()]
        }


class PluginManager:
    """插件管理器"""

    def __init__(self):
        self.plugins: Dict[str, AgentPlugin] = {}
        self._loaded = False

    def load_plugins(self, plugins_dir: str = 'plugins'):
        """加载所有插件"""
        import os
        import importlib.util

        if not os.path.exists(plugins_dir):
            logger.info(f'插件目录不存在: {plugins_dir}')
            return

        for plugin_name in os.listdir(plugins_dir):
            plugin_path = os.path.join(plugins_dir, plugin_name)
            if not os.path.isdir(plugin_path):
                continue

            plugin_file = os.path.join(plugin_path, 'plugin.py')
            if not os.path.exists(plugin_file):
                continue

            try:
                # 动态加载插件模块
                spec = importlib.util.spec_from_file_location(f'plugins.{plugin_name}.plugin', plugin_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # 查找插件类或工厂函数
                plugin_instance = None
                if hasattr(module, 'create_plugin'):
                    plugin_instance = module.create_plugin()
                else:
                    # 查找继承自AgentPlugin的类
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and
                            issubclass(attr, AgentPlugin) and
                            attr is not AgentPlugin):
                            plugin_instance = attr()
                            break

                if plugin_instance:
                    self.register_plugin(plugin_instance)
                    logger.info(f'插件加载成功: {plugin_instance.name} v{plugin_instance.version}')

            except Exception as e:
                logger.error(f'插件加载失败 {plugin_name}: {e}')

        self._loaded = True

    def register_plugin(self, plugin: AgentPlugin):
        """注册插件"""
        plugin.on_load()
        self.plugins[plugin.name] = plugin

    def unregister_plugin(self, plugin_name: str):
        """注销插件"""
        if plugin_name in self.plugins:
            plugin = self.plugins[plugin_name]
            plugin.on_unload()
            del self.plugins[plugin_name]

    def get_all_tools(self) -> List[PluginTool]:
        """获取所有插件的工具"""
        tools = []
        for plugin in self.plugins.values():
            tools.extend(plugin.get_tools())
        return tools

    def get_tool(self, tool_name: str) -> Optional[PluginTool]:
        """根据名称获取工具"""
        for plugin in self.plugins.values():
            for tool in plugin.get_tools():
                if tool.name == tool_name:
                    return tool
        return None

    def execute_tool(self, tool_name: str, params: Dict, ctx: PluginContext) -> Dict:
        """执行插件工具"""
        tool = self.get_tool(tool_name)
        if not tool:
            return {'error': f'工具 {tool_name} 不存在'}

        if tool.requires_confirmation:
            return {'needs_confirmation': True, 'tool_name': tool_name}

        try:
            result = tool.handler(params, ctx)
            return result
        except Exception as e:
            logger.error(f'工具执行失败 {tool_name}: {e}')
            return {'error': str(e)}

    def list_plugins(self) -> List[Dict]:
        """列出所有插件"""
        return [plugin.get_info() for plugin in self.plugins.values()]


_plugin_manager_instance = None


def get_plugin_manager() -> PluginManager:
    """获取插件管理器单例"""
    global _plugin_manager_instance
    if _plugin_manager_instance is None:
        _plugin_manager_instance = PluginManager()
    return _plugin_manager_instance