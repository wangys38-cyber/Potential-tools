# -*- coding: utf-8 -*-
"""
Potential-tools 9.0 - Agent 2.0 核心引擎
自主任务规划与多工具调用框架

核心概念：
- Agent：智能体，接收自然语言指令，自主规划并执行任务
- Tool：工具，Agent 可调用的原子操作（查询状态、发送邮件、创建笔记等）
- ExecutionContext：执行上下文，保存执行过程中的状态和数据
- ExecutionStep：执行步骤，每个工具调用为一个步骤
"""
import json
import time
import uuid
import logging
import traceback
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    SKIPPED = 'skipped'
    NEEDS_CONFIRMATION = 'needs_confirmation'


class AgentStatus(Enum):
    IDLE = 'idle'
    PLANNING = 'planning'
    EXECUTING = 'executing'
    WAITING_CONFIRMATION = 'waiting_confirmation'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


@dataclass
class Tool:
    """工具定义"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema 格式
    handler: Callable
    requires_confirmation: bool = False  # 是否需要用户确认（如发送邮件、删除数据）
    category: str = 'general'


@dataclass
class ExecutionStep:
    """执行步骤"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    tool_name: str = ''
    tool_input: Dict[str, Any] = field(default_factory=dict)
    status: str = StepStatus.PENDING.value
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    reasoning: str = ''  # AI 为什么选择这个步骤


@dataclass
class ExecutionContext:
    """执行上下文"""
    agent_id: str
    task: str
    status: str = AgentStatus.IDLE.value
    steps: List[ExecutionStep] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)  # 步骤间共享的数据
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None
    current_step_index: int = -1

    def to_dict(self) -> Dict[str, Any]:
        return {
            'agent_id': self.agent_id,
            'task': self.task,
            'status': self.status,
            'steps': [
                {
                    'id': s.id,
                    'tool_name': s.tool_name,
                    'tool_input': s.tool_input,
                    'status': s.status,
                    'result': str(s.result)[:500] if s.result else None,
                    'error': s.error,
                    'started_at': s.started_at,
                    'completed_at': s.completed_at,
                    'reasoning': s.reasoning,
                    'duration': (s.completed_at - s.started_at) if (s.completed_at and s.started_at) else None
                }
                for s in self.steps
            ],
            'data_keys': list(self.data.keys()),
            'created_at': self.created_at,
            'completed_at': self.completed_at,
            'error': self.error,
            'duration': (self.completed_at - self.created_at) if self.completed_at else None
        }


class ToolRegistry:
    """工具注册表 — 单例"""
    _instance = None
    _tools: Dict[str, Tool] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, tool: Tool):
        """注册工具"""
        self._tools[tool.name] = tool
        logger.info(f"Agent工具已注册: {tool.name} ({tool.category})")

    def get(self, name: str) -> Optional[Tool]:
        """获取工具"""
        return self._tools.get(name)

    def list_tools(self, category: Optional[str] = None) -> List[Tool]:
        """列出所有工具"""
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """获取所有工具的 JSON Schema（用于 AI 函数调用）"""
        return [
            {
                'type': 'function',
                'function': {
                    'name': t.name,
                    'description': t.description,
                    'parameters': t.parameters
                }
            }
            for t in self._tools.values()
        ]


# 全局工具注册表实例
tool_registry = ToolRegistry()


class AgentEngine:
    """Agent 执行引擎"""

    def __init__(self, ai_service=None):
        self.ai_service = ai_service
        self.contexts: Dict[str, ExecutionContext] = {}

    def create_context(self, task: str, agent_id: Optional[str] = None) -> ExecutionContext:
        """创建执行上下文"""
        ctx = ExecutionContext(
            agent_id=agent_id or str(uuid.uuid4())[:8],
            task=task
        )
        self.contexts[ctx.agent_id] = ctx
        return ctx

    def plan(self, ctx: ExecutionContext) -> List[ExecutionStep]:
        """
        任务规划 — 将自然语言任务拆解为工具调用步骤
        如果有 AI 服务，用 AI 规划；否则用简单的规则匹配
        """
        ctx.status = AgentStatus.PLANNING.value

        if self.ai_service:
            return self._plan_with_ai(ctx)
        else:
            return self._plan_with_rules(ctx)

    def _plan_with_ai(self, ctx: ExecutionContext) -> List[ExecutionStep]:
        """用 AI 进行任务规划"""
        try:
            tools_schema = tool_registry.get_tools_schema()
            prompt = f"""你是一个任务规划助手。请将用户的任务拆解为一系列工具调用步骤。

可用工具：
{json.dumps(tools_schema, ensure_ascii=False, indent=2)}

用户任务：{ctx.task}

请输出 JSON 格式的步骤列表，每个步骤包含：
- tool_name: 工具名称
- tool_input: 工具输入参数（JSON对象）
- reasoning: 为什么选择这个步骤

输出格式：
{{"steps": [{{"tool_name": "...", "tool_input": {{...}}, "reasoning": "..."}}]}}
"""
            # 调用 AI 服务获取规划
            if hasattr(self.ai_service, 'chat'):
                response = self.ai_service.chat([
                    {'role': 'system', 'content': '你是一个专业的任务规划助手，只输出JSON格式的步骤列表。'},
                    {'role': 'user', 'content': prompt}
                ])
                text = response if isinstance(response, str) else str(response)
            else:
                text = ''

            # 解析 AI 返回的 JSON
            steps = self._parse_plan_response(text)
            if steps:
                ctx.steps = steps
                return steps

        except Exception as e:
            logger.warning(f"AI规划失败，降级到规则规划: {e}")

        return self._plan_with_rules(ctx)

    def _parse_plan_response(self, text: str) -> List[ExecutionStep]:
        """解析 AI 返回的规划响应"""
        try:
            # 尝试提取 JSON
            start = text.find('{')
            end = text.rfind('}')
            if start >= 0 and end > start:
                json_str = text[start:end + 1]
                data = json.loads(json_str)
                steps_data = data.get('steps', [])
                steps = []
                for sd in steps_data:
                    step = ExecutionStep(
                        tool_name=sd.get('tool_name', ''),
                        tool_input=sd.get('tool_input', {}),
                        reasoning=sd.get('reasoning', '')
                    )
                    steps.append(step)
                return steps
        except Exception as e:
            logger.warning(f"解析规划响应失败: {e}")
        return []

    @staticmethod
    def _extract_project_key(task: str) -> Optional[str]:
        """从用户输入中提取项目名称（如 EKSANTOS、SANTOS、Santos 等）"""
        import re
        # 使用 lookaround 代替 \b（\b 在中英文边界处不可靠）
        # 模式1：以 EK 开头的全大写项目名（如 EKSANTOS、EKHORIZON）
        m = re.search(r'(?<![A-Za-z])(EK[A-Z]{2,})(?![A-Za-z])', task)
        if m:
            return m.group(1)
        # 模式2：连续 5-15 个大写字母（如 SANTOS、HORIZON）
        m = re.search(r'(?<![A-Za-z])([A-Z]{5,15})(?![A-Za-z])', task)
        if m:
            return m.group(1)
        # 模式3：首字母大写 + 4-14个小写字母（如 Santos、Horizon、Andes）
        m = re.search(r'(?<![A-Za-z])([A-Z][a-z]{4,14})(?![A-Za-z])', task)
        if m:
            return m.group(1).upper()
        # 模式4：中文"项目"前面的英文/数字组合
        m = re.search(r'([A-Za-z0-9]+)\s*项目', task)
        if m:
            return m.group(1).upper()
        return None

    def _plan_with_rules(self, ctx: ExecutionContext) -> List[ExecutionStep]:
        """基于规则的简单任务规划（无 AI 时的降级方案）"""
        task = ctx.task
        task_lower = task.lower()
        steps = []

        # 提取项目名称
        project_key = self._extract_project_key(task)

        # 规则1：生成报告类任务
        if any(kw in task_lower for kw in ['报告', '日报', '周报', '状态']):
            if '项目' in task_lower or 'cr' in task_lower or project_key:
                steps.append(ExecutionStep(
                    tool_name='query_project_status',
                    tool_input={'project_key': project_key or 'AUTO_DETECT'},
                    reasoning=f'查询项目状态数据' + (f'（{project_key}）' if project_key else '')
                ))
            steps.append(ExecutionStep(
                tool_name='generate_report',
                tool_input={'format': 'markdown'},
                reasoning='生成状态报告'
            ))

        # 规则2：发送邮件类任务
        if any(kw in task_lower for kw in ['邮件', '发送', 'email']):
            steps.append(ExecutionStep(
                tool_name='send_email',
                tool_input={'to': 'AUTO_DETECT', 'subject': 'AUTO_DETECT', 'body': 'AUTO_DETECT'},
                reasoning='发送邮件',
            ))

        # 规则3：笔记类任务
        if any(kw in task_lower for kw in ['笔记', '记录', 'note']):
            steps.append(ExecutionStep(
                tool_name='create_note',
                tool_input={'title': 'AUTO_DETECT', 'content': 'AUTO_DETECT'},
                reasoning='创建笔记'
            ))

        # 如果没有匹配到任何规则，添加一个通用查询步骤
        if not steps:
            steps.append(ExecutionStep(
                tool_name='knowledge_search',
                tool_input={'query': ctx.task},
                reasoning='在知识库中搜索相关信息'
            ))

        ctx.steps = steps
        return steps

    def execute_step(self, ctx: ExecutionContext, step_index: int) -> ExecutionStep:
        """执行单个步骤"""
        if step_index >= len(ctx.steps):
            return None

        step = ctx.steps[step_index]
        ctx.current_step_index = step_index

        tool = tool_registry.get(step.tool_name)
        if not tool:
            step.status = StepStatus.FAILED.value
            step.error = f"工具不存在: {step.tool_name}"
            return step

        # 检查是否需要用户确认
        if tool.requires_confirmation and step.status != StepStatus.COMPLETED.value:
            step.status = StepStatus.NEEDS_CONFIRMATION.value
            ctx.status = AgentStatus.WAITING_CONFIRMATION.value
            return step

        step.status = StepStatus.RUNNING.value
        step.started_at = time.time()
        ctx.status = AgentStatus.EXECUTING.value

        try:
            # 执行工具
            result = tool.handler(step.tool_input, ctx)
            step.result = result
            step.status = StepStatus.COMPLETED.value
            step.completed_at = time.time()
            logger.info(f"Agent步骤完成: {step.tool_name} ({step.id})")
        except Exception as e:
            step.status = StepStatus.FAILED.value
            step.error = str(e)
            step.completed_at = time.time()
            logger.error(f"Agent步骤失败: {step.tool_name} - {e}\n{traceback.format_exc()}")

        return step

    def execute_all(self, ctx: ExecutionContext, on_step_complete: Optional[Callable] = None) -> ExecutionContext:
        """执行所有步骤"""
        ctx.status = AgentStatus.EXECUTING.value

        for i in range(len(ctx.steps)):
            step = self.execute_step(ctx, i)

            if on_step_complete:
                on_step_complete(ctx, step)

            # 如果步骤需要确认，暂停执行
            if step.status == StepStatus.NEEDS_CONFIRMATION.value:
                return ctx

            # 如果步骤失败，停止执行
            if step.status == StepStatus.FAILED.value:
                ctx.status = AgentStatus.FAILED.value
                ctx.error = step.error
                ctx.completed_at = time.time()
                return ctx

        ctx.status = AgentStatus.COMPLETED.value
        ctx.completed_at = time.time()
        return ctx

    def confirm_step(self, ctx: ExecutionContext, step_index: int, confirmed: bool) -> ExecutionStep:
        """用户确认/拒绝步骤"""
        if step_index >= len(ctx.steps):
            return None

        step = ctx.steps[step_index]
        if confirmed:
            # 用户确认，继续执行（跳过确认检查）
            step.status = StepStatus.RUNNING.value
            tool = tool_registry.get(step.tool_name)
            if tool:
                try:
                    result = tool.handler(step.tool_input, ctx)
                    step.result = result
                    step.status = StepStatus.COMPLETED.value
                except Exception as e:
                    step.status = StepStatus.FAILED.value
                    step.error = str(e)
            step.completed_at = time.time()
        else:
            step.status = StepStatus.SKIPPED.value
            step.completed_at = time.time()

        ctx.status = AgentStatus.EXECUTING.value
        return step

    def cancel(self, ctx: ExecutionContext):
        """取消执行"""
        ctx.status = AgentStatus.CANCELLED.value
        ctx.completed_at = time.time()


# 全局 Agent 引擎实例
agent_engine = AgentEngine()
