# -*- coding: utf-8 -*-
"""
AI 任务规划器

使用大模型进行任务分解、动态规划、自我反思。
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """计划步骤"""
    id: str
    description: str
    tool_name: str
    tool_input: Dict = field(default_factory=dict)
    reasoning: str = ''
    depends_on: List[str] = field(default_factory=list)


@dataclass
class TaskPlan:
    """任务计划"""
    task: str
    steps: List[PlanStep] = field(default_factory=list)
    summary: str = ''
    reasoning: str = ''
    created_at: float = field(default_factory=time.time)
    is_ai_generated: bool = False


class AIPlanner:
    """AI任务规划器"""

    def __init__(self):
        self.max_retries = 2
        self.planning_prompt = """你是一个专业的任务规划专家，负责将用户的复杂任务分解为可执行的步骤。

## 可用工具列表及参数要求
{tools_list}

## 重要参数说明
- **project_key**: 项目标识，如 EKSANTOS、EKPASHA 等。如果用户任务中提到了项目名（如 Santos、Pasha），请自动转换为 EK+大写形式（如 EKSANTOS）。
- **query_project_status** 必须提供 project_key 参数
- **analyze_cr_trend**、**query_unresolved_bc**、**query_module_status**、**generate_report**、**generate_weekly_report**、**assess_project_risk** 等工具依赖 query_project_status 的输出，必须在 query_project_status 之后执行
- **send_email** 必须提供 to_emails（收件人邮箱数组）、subject（邮件标题）、content（邮件内容）参数
- **send_feishu_notification** 必须提供 webhook_url 和 content 参数
- **knowledge_search** 必须提供 query 参数
- **create_note** 必须提供 title 和 content 参数

## 规划规则
1. 仔细分析用户任务，确定需要哪些工具来完成
2. 每个步骤必须使用上面列出的工具之一
3. 第一个步骤通常是 query_project_status（如果任务涉及项目数据）
4. 步骤之间可以有依赖关系（depends_on），依赖的步骤必须先执行
5. 如果任务简单，一个步骤即可
6. 如果任务复杂，分解为多个串行步骤
7. 每个步骤需要说明推理过程（reasoning）
8. **必须为每个工具提供正确的 tool_input 参数，不能为空对象**
9. 如果用户任务中没有明确提到项目名，默认使用 EKSANTOS

## 输出格式
请严格输出JSON格式，不要输出其他内容：
{{
  "summary": "任务计划的简要说明",
  "reasoning": "整体规划思路",
  "steps": [
    {{
      "id": "step_1",
      "description": "步骤描述",
      "tool_name": "工具名称",
      "tool_input": {{"project_key": "EKSANTOS"}},
      "reasoning": "为什么需要这个步骤",
      "depends_on": []
    }}
  ]
}}

## 用户任务
{task}
"""

    def generate_plan(self, task: str, tools_info: List[Dict] = None) -> TaskPlan:
        """生成任务计划"""
        tools_list = self._format_tools_list(tools_info or [])
        prompt = self.planning_prompt.format(tools_list=tools_list, task=task)

        try:
            from services.ai_client import get_ai_client
            client = get_ai_client()
            response = client.chat([{'role': 'user', 'content': prompt}])
            content = getattr(response, 'content', None) or str(response)
            plan = self._parse_plan_response(content, task)
            if plan and plan.steps:
                plan.is_ai_generated = True
                return plan
        except Exception as e:
            logger.warning(f'AI规划失败，使用兜底规划: {e}')

        return self._fallback_plan(task)

    def _format_tools_list(self, tools_info: List[Dict]) -> str:
        """格式化工具列表"""
        if not tools_info:
            return '（工具列表为空）'
        lines = []
        for tool in tools_info:
            name = tool.get('name', '')
            desc = tool.get('description', '')
            params = tool.get('parameters', {})
            lines.append(f'- **{name}**: {desc}')
            if params and params.get('properties'):
                required = params.get('required', [])
                for param_name, param_info in params['properties'].items():
                    req_mark = '（必填）' if param_name in required else ''
                    lines.append(f'  - {param_name}{req_mark}: {param_info.get("description", "")}')
        return '\n'.join(lines)

    def _parse_plan_response(self, content: str, task: str) -> Optional[TaskPlan]:
        """解析AI返回的计划"""
        try:
            # 提取JSON部分
            json_start = content.find('{')
            json_end = content.rfind('}')
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end + 1]
                data = json.loads(json_str)

                steps = []
                for i, step_data in enumerate(data.get('steps', [])):
                    step = PlanStep(
                        id=step_data.get('id', f'step_{i + 1}'),
                        description=step_data.get('description', ''),
                        tool_name=step_data.get('tool_name', ''),
                        tool_input=step_data.get('tool_input', {}),
                        reasoning=step_data.get('reasoning', ''),
                        depends_on=step_data.get('depends_on', [])
                    )
                    steps.append(step)

                return TaskPlan(
                    task=task,
                    steps=steps,
                    summary=data.get('summary', ''),
                    reasoning=data.get('reasoning', '')
                )
        except Exception as e:
            logger.warning(f'解析AI计划失败: {e}')
        return None

    def _fallback_plan(self, task: str) -> TaskPlan:
        """兜底规划：简单任务直接用通用助手"""
        return TaskPlan(
            task=task,
            steps=[
                PlanStep(
                    id='step_1',
                    description='执行任务',
                    tool_name='knowledge_search',
                    tool_input={'query': task},
                    reasoning='使用知识库搜索相关信息'
                )
            ],
            summary='简单任务，直接执行',
            reasoning='任务较简单，无需复杂分解'
        )


_planner_instance = None


def get_planner() -> AIPlanner:
    """获取规划器单例"""
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = AIPlanner()
    return _planner_instance