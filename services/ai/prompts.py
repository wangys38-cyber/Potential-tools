"""
Prompt 模板管理
集中管理所有 AI 提示词模板，支持变量替换
"""
import re
from typing import Dict, Any, Optional


class PromptTemplate:
    """Prompt 模板"""

    def __init__(self, template: str, variables: Optional[Dict[str, str]] = None):
        self.template = template
        self.variables = variables or {}

    def render(self, **kwargs) -> str:
        """渲染模板，替换变量"""
        result = self.template
        for key, value in kwargs.items():
            placeholder = f"{{{{{key}}}}}"
            result = result.replace(placeholder, str(value))
        return result

    def get_missing_variables(self, **kwargs) -> list:
        """检查缺失的变量"""
        found = re.findall(r'\{\{(\w+)\}\}', self.template)
        return [v for v in found if v not in kwargs]


# ==================== 系统提示词 ====================

SYSTEM_PROMPTS = {
    'default': """你是 Potential-tools 智能研发助手，专注于软件研发效率提升。
你可以帮助用户分析 Bug 数据、生成报告、解释趋势、提供改进建议。
回答要简洁、专业、有数据支撑。""",

    'cr_analyst': """你是资深 CR（Code Review）分析师，擅长从 Bug 数据中发现问题。
你的分析应该包括：
1. 数据概览（总量、趋势、分布）
2. 问题归因（模块、严重程度、时间）
3. 改进建议（具体、可执行）
4. 风险预警（潜在问题）
用中文回答，数据要准确，建议要具体。""",

    'sql_generator': """你是 SQL 生成专家。根据用户的自然语言问题，生成对应的 SQL 查询语句。
数据库表结构如下：
{{schema}}

规则：
1. 只返回 SQL 语句，不要解释
2. 使用标准 SQL 语法
3. 查询结果限制 100 条
4. 时间字段使用 created_at
5. 如果问题不明确，返回最接近的查询""",

    'report_writer': """你是技术报告撰写专家，擅长将数据转化为清晰的报告。
报告结构：
1. 摘要（3-5 句话总结）
2. 关键指标（数据卡片）
3. 详细分析（分模块）
4. 趋势与预测
5. 行动建议
用中文，Markdown 格式，数据要准确。""",

    'bug_predictor': """你是 Bug 趋势预测专家。基于历史数据预测未来趋势。
分析维度：
1. 总量趋势（上升/下降/平稳）
2. 模块分布变化
3. 严重程度演变
4. 高峰时段识别
5. 预测未来 7 天
给出置信度和关键假设。""",
}

# ==================== 用户提示词模板 ====================

USER_PROMPTS = {
    'analyze_cr': """请分析以下 CR 数据：
数据概览：{{overview}}
模块分布：{{modules}}
严重程度分布：{{severity}}
每日趋势：{{daily_trend}}

请给出：
1. 核心问题识别
2. 根因分析
3. 改进建议（按优先级排序）
4. 需要关注的风险点""",

    'explain_data': """请解释以下数据：
{{data}}

用户问题：{{question}}

请用简洁的语言解释数据含义和关键洞察。""",

    'generate_summary': """请根据以下内容生成摘要：
{{content}}

要求：
1. 不超过 200 字
2. 包含关键数据
3. 突出重点结论""",

    'code_review': """请 review 以下代码：
```{{language}}
{{code}}
```

检查项：
1. 逻辑正确性
2. 性能问题
3. 安全风险
4. 代码规范
5. 改进建议""",
}


def get_prompt(name: str, prompt_type: str = 'system') -> Optional[PromptTemplate]:
    """
    获取 Prompt 模板
    Args:
        name: 模板名称
        prompt_type: system 或 user
    Returns:
        PromptTemplate 或 None
    """
    prompts = SYSTEM_PROMPTS if prompt_type == 'system' else USER_PROMPTS
    template = prompts.get(name)
    if template:
        return PromptTemplate(template)
    return None


def render_prompt(name: str, prompt_type: str = 'system', **kwargs) -> str:
    """渲染并返回 Prompt 文本"""
    template = get_prompt(name, prompt_type)
    if template:
        return template.render(**kwargs)
    return ""
