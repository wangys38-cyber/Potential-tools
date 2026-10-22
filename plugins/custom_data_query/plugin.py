# -*- coding: utf-8 -*-
"""
Custom Data Query Plugin

Example plugin demonstrating the Agent Plugin SDK.
Provides custom data query and statistics tools.
"""
from services.plugin_sdk import AgentPlugin, PluginTool, PluginContext


class CustomDataQueryPlugin(AgentPlugin):
    """Custom data query plugin"""
    name = "custom_data_query"
    version = "1.0.0"
    description = "Custom data query and statistics tools"
    author = "Potential-tools"

    def get_tools(self):
        return [
            PluginTool(
                name="custom_query",
                description="Execute a custom data query with specified parameters",
                parameters={
                    "type": "object",
                    "properties": {
                        "query_type": {
                            "type": "string",
                            "description": "Type of query (daily/weekly/monthly)"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date (YYYY-MM-DD)"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date (YYYY-MM-DD)"
                        }
                    },
                    "required": ["query_type"]
                },
                handler=self._custom_query
            ),
            PluginTool(
                name="data_statistics",
                description="Generate data statistics for a specified project and time period",
                parameters={
                    "type": "object",
                    "properties": {
                        "project_key": {
                            "type": "string",
                            "description": "Project key (e.g., EKSANTOS)"
                        },
                        "metric": {
                            "type": "string",
                            "description": "Metric to calculate (cr_count/unresolved/risk_level)"
                        }
                    },
                    "required": ["project_key"]
                },
                handler=self._data_statistics
            ),
            PluginTool(
                name="export_data",
                description="Export data to a specified format (CSV/JSON/Excel)",
                parameters={
                    "type": "object",
                    "properties": {
                        "format": {
                            "type": "string",
                            "description": "Export format (csv/json/excel)"
                        },
                        "data_type": {
                            "type": "string",
                            "description": "Type of data to export"
                        }
                    },
                    "required": ["format"]
                },
                handler=self._export_data
            )
        ]

    def _custom_query(self, params: dict, ctx: PluginContext) -> dict:
        """Execute custom data query"""
        query_type = params.get('query_type', 'daily')
        start_date = params.get('start_date', '')
        end_date = params.get('end_date', '')

        return {
            'success': True,
            'query_type': query_type,
            'start_date': start_date,
            'end_date': end_date,
            'results': [],
            'message': f'Custom {query_type} query executed successfully'
        }

    def _data_statistics(self, params: dict, ctx: PluginContext) -> dict:
        """Generate data statistics"""
        project_key = params.get('project_key', '')
        metric = params.get('metric', 'cr_count')

        return {
            'success': True,
            'project_key': project_key,
            'metric': metric,
            'value': 0,
            'message': f'Statistics for {project_key} calculated successfully'
        }

    def _export_data(self, params: dict, ctx: PluginContext) -> dict:
        """Export data"""
        export_format = params.get('format', 'csv')
        data_type = params.get('data_type', '')

        return {
            'success': True,
            'format': export_format,
            'data_type': data_type,
            'file_path': f'/tmp/export_{data_type}.{export_format}',
            'message': f'Data exported to {export_format} format successfully'
        }


def create_plugin():
    """Plugin factory function"""
    return CustomDataQueryPlugin()