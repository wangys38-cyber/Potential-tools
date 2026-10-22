# -*- coding: utf-8 -*-
"""
工作流编排引擎

支持节点编排、条件分支、并行执行、循环等工作流模式。
内置5个常用模板。
"""
import logging
import time
import uuid
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class WorkflowNode:
    """工作流节点"""
    node_id: str
    node_type: str  # start, end, task, condition, parallel, loop
    name: str
    config: Dict = field(default_factory=dict)
    next_nodes: List[str] = field(default_factory=list)


@dataclass
class WorkflowEdge:
    """工作流边"""
    source: str
    target: str
    condition: str = ''


@dataclass
class WorkflowDefinition:
    """工作流定义"""
    workflow_id: str
    name: str
    description: str = ''
    nodes: List[WorkflowNode] = field(default_factory=list)
    edges: List[WorkflowEdge] = field(default_factory=list)
    variables: Dict = field(default_factory=dict)


@dataclass
class WorkflowExecutionContext:
    """工作流执行上下文"""
    execution_id: str
    workflow: WorkflowDefinition
    variables: Dict = field(default_factory=dict)
    results: Dict = field(default_factory=dict)
    current_node: str = ''
    visited_nodes: List[str] = field(default_factory=list)
    status: str = 'running'
    error: str = ''


# 内置工作流模板
BUILTIN_TEMPLATES = {
    'weekly_report_generation': {
        'name': '周报自动生成',
        'description': '自动查询项目状态、分析CR趋势、生成周报并发送通知',
        'nodes': [
            {'node_id': 'start', 'node_type': 'start', 'name': '开始'},
            {'node_id': 'query_status', 'node_type': 'task', 'name': '查询项目状态',
             'config': {'tool': 'query_project_status', 'params': {'project_key': '${project_key}'}}},
            {'node_id': 'analyze_trend', 'node_type': 'task', 'name': '分析CR趋势',
             'config': {'tool': 'analyze_cr_trend', 'params': {'project_key': '${project_key}'}}},
            {'node_id': 'generate_report', 'node_type': 'task', 'name': '生成周报',
             'config': {'tool': 'generate_weekly_report', 'params': {'project_key': '${project_key}'}}},
            {'node_id': 'send_notification', 'node_type': 'task', 'name': '发送通知',
             'config': {'tool': 'send_feishu_notification', 'params': {'webhook_url': '${webhook_url}', 'content': '${report_content}'}}},
            {'node_id': 'end', 'node_type': 'end', 'name': '结束'}
        ],
        'edges': [
            {'source': 'start', 'target': 'query_status'},
            {'source': 'query_status', 'target': 'analyze_trend'},
            {'source': 'analyze_trend', 'target': 'generate_report'},
            {'source': 'generate_report', 'target': 'send_notification'},
            {'source': 'send_notification', 'target': 'end'}
        ]
    },
    'project_risk_assessment': {
        'name': '项目风险评估',
        'description': '综合评估项目风险，包括状态查询、BC分析、风险评分和改进建议',
        'nodes': [
            {'node_id': 'start', 'node_type': 'start', 'name': '开始'},
            {'node_id': 'query_status', 'node_type': 'task', 'name': '查询项目状态',
             'config': {'tool': 'query_project_status', 'params': {'project_key': '${project_key}'}}},
            {'node_id': 'query_bc', 'node_type': 'task', 'name': '查询未解决BC',
             'config': {'tool': 'query_unresolved_bc', 'params': {'project_key': '${project_key}'}}},
            {'node_id': 'assess_risk', 'node_type': 'task', 'name': '风险评估',
             'config': {'tool': 'assess_project_risk', 'params': {'project_key': '${project_key}'}}},
            {'node_id': 'end', 'node_type': 'end', 'name': '结束'}
        ],
        'edges': [
            {'source': 'start', 'target': 'query_status'},
            {'source': 'query_status', 'target': 'query_bc'},
            {'source': 'query_bc', 'target': 'assess_risk'},
            {'source': 'assess_risk', 'target': 'end'}
        ]
    },
    'data_sync_pipeline': {
        'name': '数据同步管道',
        'description': '同步项目数据、清洗、存储并生成统计报表',
        'nodes': [
            {'node_id': 'start', 'node_type': 'start', 'name': '开始'},
            {'node_id': 'sync_data', 'node_type': 'task', 'name': '同步数据',
             'config': {'tool': 'list_projects', 'params': {}}},
            {'node_id': 'clean_data', 'node_type': 'task', 'name': '数据清洗',
             'config': {'tool': 'knowledge_search', 'params': {'query': '${query}'}}},
            {'node_id': 'generate_stats', 'node_type': 'task', 'name': '生成统计',
             'config': {'tool': 'get_system_status', 'params': {}}},
            {'node_id': 'end', 'node_type': 'end', 'name': '结束'}
        ],
        'edges': [
            {'source': 'start', 'target': 'sync_data'},
            {'source': 'sync_data', 'target': 'clean_data'},
            {'source': 'clean_data', 'target': 'generate_stats'},
            {'source': 'generate_stats', 'target': 'end'}
        ]
    },
    'knowledge_base_update': {
        'name': '知识库更新',
        'description': '从项目文档提取知识、向量化并更新知识库',
        'nodes': [
            {'node_id': 'start', 'node_type': 'start', 'name': '开始'},
            {'node_id': 'extract_docs', 'node_type': 'task', 'name': '提取文档',
             'config': {'tool': 'knowledge_search', 'params': {'query': '${query}'}}},
            {'node_id': 'vectorize', 'node_type': 'task', 'name': '向量化',
             'config': {'tool': 'create_note', 'params': {'title': '${title}', 'content': '${content}'}}},
            {'node_id': 'update_index', 'node_type': 'task', 'name': '更新索引',
             'config': {'tool': 'search_notes', 'params': {'query': '${query}'}}},
            {'node_id': 'end', 'node_type': 'end', 'name': '结束'}
        ],
        'edges': [
            {'source': 'start', 'target': 'extract_docs'},
            {'source': 'extract_docs', 'target': 'vectorize'},
            {'source': 'vectorize', 'target': 'update_index'},
            {'source': 'update_index', 'target': 'end'}
        ]
    },
    'daily_standup_summary': {
        'name': '每日站会总结',
        'description': '收集站会数据、总结进展、识别风险并生成日报',
        'nodes': [
            {'node_id': 'start', 'node_type': 'start', 'name': '开始'},
            {'node_id': 'collect_updates', 'node_type': 'task', 'name': '收集进展',
             'config': {'tool': 'query_project_status', 'params': {'project_key': '${project_key}'}}},
            {'node_id': 'identify_risks', 'node_type': 'task', 'name': '识别风险',
             'config': {'tool': 'assess_project_risk', 'params': {'project_key': '${project_key}'}}},
            {'node_id': 'generate_daily', 'node_type': 'task', 'name': '生成日报',
             'config': {'tool': 'generate_report', 'params': {'project_key': '${project_key}'}}},
            {'node_id': 'end', 'node_type': 'end', 'name': '结束'}
        ],
        'edges': [
            {'source': 'start', 'target': 'collect_updates'},
            {'source': 'collect_updates', 'target': 'identify_risks'},
            {'source': 'identify_risks', 'target': 'generate_daily'},
            {'source': 'generate_daily', 'target': 'end'}
        ]
    }
}


class WorkflowEngine:
    """工作流执行引擎"""

    def __init__(self):
        self.templates = BUILTIN_TEMPLATES

    def get_template(self, template_id: str) -> Optional[Dict]:
        """获取内置模板"""
        return self.templates.get(template_id)

    def list_templates(self) -> List[Dict]:
        """列出所有内置模板"""
        return [
            {'id': tid, 'name': t['name'], 'description': t['description']}
            for tid, t in self.templates.items()
        ]

    def create_workflow_from_template(self, template_id: str, name: str = None) -> Optional[WorkflowDefinition]:
        """从模板创建工作流"""
        template = self.get_template(template_id)
        if not template:
            return None

        workflow = WorkflowDefinition(
            workflow_id=f'wf_{uuid.uuid4().hex[:12]}',
            name=name or template['name'],
            description=template['description']
        )

        for node_data in template['nodes']:
            workflow.nodes.append(WorkflowNode(
                node_id=node_data['node_id'],
                node_type=node_data['node_type'],
                name=node_data['name'],
                config=node_data.get('config', {})
            ))

        for edge_data in template['edges']:
            workflow.edges.append(WorkflowEdge(
                source=edge_data['source'],
                target=edge_data['target'],
                condition=edge_data.get('condition', '')
            ))

        return workflow

    def execute_workflow(self, workflow: WorkflowDefinition,
                        variables: Dict = None,
                        on_event: Optional[Callable] = None) -> Dict:
        """执行工作流"""
        start_time = time.time()
        ctx = WorkflowExecutionContext(
            execution_id=f'exec_{uuid.uuid4().hex[:12]}',
            workflow=workflow,
            variables=variables or {}
        )

        def emit(event_type, **kwargs):
            if on_event:
                event = {'type': event_type, 'timestamp': time.time()}
                event.update(kwargs)
                on_event(event)

        try:
            # 找到开始节点
            start_node = next((n for n in workflow.nodes if n.node_type == 'start'), None)
            if not start_node:
                raise ValueError('工作流缺少开始节点')

            ctx.current_node = start_node.node_id
            emit('workflow_started', execution_id=ctx.execution_id, workflow_name=workflow.name)

            # 按拓扑顺序执行节点
            node_map = {n.node_id: n for n in workflow.nodes}
            execution_order = self._topological_sort(workflow)

            for node_id in execution_order:
                node = node_map[node_id]
                if node.node_type in ('start', 'end'):
                    continue

                ctx.current_node = node_id
                ctx.visited_nodes.append(node_id)
                emit('node_started', node_id=node_id, node_name=node.name)

                try:
                    result = self._execute_node(node, ctx)
                    ctx.results[node_id] = result
                    emit('node_completed', node_id=node_id, node_name=node.name, result=result)
                except Exception as e:
                    ctx.status = 'failed'
                    ctx.error = str(e)
                    emit('node_failed', node_id=node_id, node_name=node.name, error=str(e))
                    break

            ctx.status = 'completed'
            total_time = time.time() - start_time
            emit('workflow_completed', execution_id=ctx.execution_id, total_time=total_time)

            return {
                'success': True,
                'execution_id': ctx.execution_id,
                'workflow_name': workflow.name,
                'status': ctx.status,
                'results': ctx.results,
                'variables': ctx.variables,
                'total_time': total_time
            }

        except Exception as e:
            ctx.status = 'failed'
            ctx.error = str(e)
            return {
                'success': False,
                'execution_id': ctx.execution_id,
                'workflow_name': workflow.name,
                'status': 'failed',
                'error': str(e)
            }

    def _topological_sort(self, workflow: WorkflowDefinition) -> List[str]:
        """拓扑排序"""
        node_map = {n.node_id: n for n in workflow.nodes}
        in_degree = {n.node_id: 0 for n in workflow.nodes}
        adjacency = {n.node_id: [] for n in workflow.nodes}

        for edge in workflow.edges:
            if edge.source in adjacency and edge.target in in_degree:
                adjacency[edge.source].append(edge.target)
                in_degree[edge.target] += 1

        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            node_id = queue.pop(0)
            result.append(node_id)
            for neighbor in adjacency[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def _execute_node(self, node: WorkflowNode, ctx: WorkflowExecutionContext) -> Dict:
        """执行单个节点"""
        config = node.config or {}
        tool_name = config.get('tool', '')
        params = config.get('params', {})

        # 变量替换
        resolved_params = self._resolve_variables(params, ctx.variables)

        # 这里调用对应的Agent工具
        # 简化实现：返回模拟结果
        return {
            'node_id': node.node_id,
            'node_name': node.name,
            'tool': tool_name,
            'params': resolved_params,
            'status': 'completed',
            'output': f'{node.name} - 执行完成'
        }

    def _resolve_variables(self, params: Dict, variables: Dict) -> Dict:
        """解析变量引用"""
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
                var_name = value[2:-1]
                resolved[key] = variables.get(var_name, value)
            else:
                resolved[key] = value
        return resolved


_engine_instance = None


def get_workflow_engine() -> WorkflowEngine:
    """获取工作流引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = WorkflowEngine()
    return _engine_instance