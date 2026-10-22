# Agent Plugin Development Guide

## Overview

The Potential-tools Agent Plugin SDK allows you to extend the AI Agent system with custom tools, agents, and workflows. This guide covers everything you need to know to develop, test, and deploy your own plugins.

## Quick Start

### 1. Create a Plugin Directory

Create a new directory under `plugins/` with your plugin name:

```
plugins/
  my_plugin/
    plugin.py          # Main plugin file (required)
    requirements.txt   # Python dependencies (optional)
    README.md          # Plugin documentation (optional)
```

### 2. Implement the Plugin

Create `plugin.py` with your plugin class:

```python
from services.plugin_sdk import AgentPlugin, PluginTool, PluginContext

class MyPlugin(AgentPlugin):
    name = "my_plugin"
    version = "1.0.0"
    description = "My custom plugin"
    author = "Your Name"

    def get_tools(self) -> list[PluginTool]:
        return [
            PluginTool(
                name="my_custom_tool",
                description="Description of my custom tool",
                parameters={
                    "type": "object",
                    "properties": {
                        "param1": {"type": "string", "description": "Parameter 1"}
                    },
                    "required": ["param1"]
                },
                handler=self._my_tool_handler
            )
        ]

    def _my_tool_handler(self, params: dict, ctx: PluginContext) -> dict:
        """Handle the tool call"""
        param1 = params.get('param1', '')
        return {
            'success': True,
            'result': f'Processed: {param1}'
        }
```

### 3. Register the Plugin

The plugin system automatically discovers plugins in the `plugins/` directory. Just place your plugin directory there and it will be loaded on startup.

## API Reference

### AgentPlugin Base Class

All plugins must inherit from `AgentPlugin` and implement the following:

| Method | Required | Description |
|--------|----------|-------------|
| `get_tools()` | Yes | Return list of PluginTool objects |
| `on_load()` | No | Called when plugin is loaded |
| `on_unload()` | No | Called when plugin is unloaded |

### PluginTool Class

Represents a tool that can be called by the AI Agent.

**Parameters:**
- `name` (str): Unique tool name
- `description` (str): Tool description for AI planning
- `parameters` (dict): JSON Schema for tool parameters
- `handler` (callable): Function to execute the tool
- `requires_confirmation` (bool): Whether to ask user confirmation before execution

### PluginContext Class

Provides context to tool handlers:
- `user_id`: Current user ID
- `agent_id`: Current agent ID
- `task`: Current task being executed
- `data`: Shared data dictionary for passing data between tools
- `execution_id`: Current execution ID

## Best Practices

1. **Keep tools focused**: Each tool should do one thing well
2. **Provide clear descriptions**: The AI planner relies on good descriptions
3. **Handle errors gracefully**: Return error dictionaries, don't raise exceptions
4. **Use context data**: Pass data between tools using `ctx.data`
5. **Document your plugin**: Include a README.md with usage examples

## Example Plugin

See `plugins/custom_data_query/plugin.py` for a complete example plugin with multiple tools.

## Troubleshooting

### Plugin not loading
- Check that the directory is under `plugins/`
- Check that `plugin.py` exists and has a class inheriting from `AgentPlugin`
- Check the server logs for import errors

### Tool not found
- Verify the tool name is unique
- Check that `get_tools()` returns the tool
- Restart the server to reload plugins