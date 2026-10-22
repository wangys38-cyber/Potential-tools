# -*- coding: utf-8 -*-
"""
多Agent协作系统

定义6个Agent角色和协调器，支持复杂任务的多Agent协作执行。
"""
import logging
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AgentRole:
    """Agent角色定义"""
    role_id: str
    name: str
    icon: str
    description: str
    capabilities: List[str] = field(default_factory=list)


# 6个Agent角色定义
AGENT_ROLES = {
    'coordinator': AgentRole(
        role_id='coordinator',
        name='协调者',
        icon='🎯',
        description='任务分解、Agent调度、结果汇总',
        capabilities=['task_decomposition', 'agent_scheduling', 'result_aggregation']
    ),
    'project_manager': AgentRole(
        role_id='project_manager',
        name='项目管理专家',
        icon='📊',
        description='状态分析、风险识别、进度跟踪',
        capabilities=['status_analysis', 'risk_identification', 'progress_tracking']
    ),
    'cr_analyst': AgentRole(
        role_id='cr_analyst',
        name='CR分析专家',
        icon='🔍',
        description='数据分析、根因分析、趋势预测',
        capabilities=['data_analysis', 'root_cause_analysis', 'trend_prediction']
    ),
    'data_engineer': AgentRole(
        role_id='data_engineer',
        name='数据工程师',
        icon='⚙️',
        description='数据清洗、管道构建、报表生成',
        capabilities=['data_cleaning', 'pipeline_building', 'report_generation']
    ),
    'reporter': AgentRole(
        role_id='reporter',
        name='报告专家',
        icon='📝',
        description='撰写报告、高管摘要、周报日报',
        capabilities=['report_writing', 'executive_summary', 'weekly_daily_report']
    ),
    'general': AgentRole(
        role_id='general',
        name='通用助手',
        icon='🤖',
        description='通用任务处理',
        capabilities=['general_task_handling']
    )
}


@dataclass
class SubTask:
    """子任务"""
    task_id: str
    description: str
    assigned_agent: str
    status: str = 'pending'  # pending, running, completed, failed
    result: Dict = field(default_factory=dict)
    error: str = ''
    started_at: float = 0
    completed_at: float = 0


class MultiAgentOrchestrator:
    """多Agent协调器"""

    def __init__(self):
        self.agents = AGENT_ROLES

    def decompose_task(self, task: str) -> List[SubTask]:
        """任务分解"""
        # 简单的任务分解逻辑
        subtasks = []

        # 检查是否需要项目状态查询
        if any(kw in task.lower() for kw in ['项目', '状态', 'cr', '风险', 'bug', '问题']):
            subtasks.append(SubTask(
                task_id='sub_1',
                description='查询项目状态和CR数据',
                assigned_agent='project_manager'
            ))

        # 检查是否需要CR分析
        if any(kw in task.lower() for kw in ['趋势', '分析', '根因', '统计']):
            subtasks.append(SubTask(
                task_id='sub_2',
                description='分析CR趋势和根因',
                assigned_agent='cr_analyst'
            ))

        # 检查是否需要生成报告
        if any(kw in task.lower() for kw in ['报告', '周报', '日报', '总结', '汇报']):
            subtasks.append(SubTask(
                task_id='sub_3',
                description='生成综合报告',
                assigned_agent='reporter'
            ))

        # 如果没有分解出子任务，用通用助手
        if not subtasks:
            subtasks.append(SubTask(
                task_id='sub_1',
                description='执行通用任务',
                assigned_agent='general'
            ))

        return subtasks

    def execute_collaborative_task(self, task: str,
                                    on_event: Optional[Callable] = None) -> Dict:
        """执行协作任务"""
        start_time = time.time()

        def emit(event_type, **kwargs):
            if on_event:
                event = {'type': event_type, 'timestamp': time.time()}
                event.update(kwargs)
                on_event(event)

        # 1. 任务分解
        emit('thinking', content='协调者正在分解任务...')
        subtasks = self.decompose_task(task)
        emit('plan_created', subtasks=[
            {'id': st.task_id, 'description': st.description, 'agent': st.assigned_agent}
            for st in subtasks
        ])

        # 2. 执行子任务
        completed = 0
        results = {}

        for subtask in subtasks:
            agent_info = self.agents.get(subtask.assigned_agent, self.agents['general'])
            emit('agent_started', agent_id=subtask.assigned_agent,
                 agent_name=agent_info.name, agent_icon=agent_info.icon,
                 task=subtask.description)

            subtask.status = 'running'
            subtask.started_at = time.time()

            try:
                # 执行子任务（调用对应的工具）
                result = self._execute_subtask(subtask, task)
                subtask.result = result
                subtask.status = 'completed'
                completed += 1
                results[subtask.task_id] = result

                emit('agent_completed', agent_id=subtask.assigned_agent,
                     agent_name=agent_info.name, result=result)

            except Exception as e:
                subtask.status = 'failed'
                subtask.error = str(e)
                emit('agent_failed', agent_id=subtask.assigned_agent,
                     agent_name=agent_info.name, error=str(e))

            subtask.completed_at = time.time()

        # 3. 汇总结果
        emit('thinking', content='协调者正在汇总结果...')
        final_result = self._aggregate_results(task, subtasks, results)

        total_time = time.time() - start_time
        emit('final_result', result=final_result)

        return {
            'success': completed == len(subtasks),
            'task': task,
            'total_subtasks': len(subtasks),
            'completed_subtasks': completed,
            'failed_subtasks': len(subtasks) - completed,
            'subtasks': [{
                'id': st.task_id,
                'description': st.description,
                'agent': st.assigned_agent,
                'status': st.status,
                'duration': st.completed_at - st.started_at if st.completed_at else 0
            } for st in subtasks],
            'result': final_result,
            'total_time': total_time
        }

    def _execute_subtask(self, subtask: SubTask, original_task: str) -> Dict:
        """执行子任务"""
        # 这里调用对应的Agent工具
        # 简化实现：返回模拟结果
        return {
            'task_id': subtask.task_id,
            'agent': subtask.assigned_agent,
            'description': subtask.description,
            'status': 'completed',
            'output': f'{subtask.description} - 执行完成'
        }

    def _aggregate_results(self, task: str, subtasks: List[SubTask],
                           results: Dict) -> Dict:
        """汇总结果"""
        summary_parts = []
        for subtask in subtasks:
            if subtask.status == 'completed':
                agent_info = self.agents.get(subtask.assigned_agent, self.agents['general'])
                summary_parts.append(f"{agent_info.icon} {agent_info.name}: {subtask.description} ✓")
            else:
                summary_parts.append(f"❌ {subtask.description}: {subtask.error}")

        return {
            'summary': '\n'.join(summary_parts),
            'task': task,
            'subtask_results': results
        }


_orchestrator_instance = None


def get_orchestrator() -> MultiAgentOrchestrator:
    """获取协调器单例"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = MultiAgentOrchestrator()
    return _orchestrator_instance