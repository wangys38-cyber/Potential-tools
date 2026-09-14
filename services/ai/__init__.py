"""
AI 服务抽象层 v8.0
支持多提供商：OpenAI 兼容、Doubao、本地模型
"""
from .base import AIServiceBase, AIResponse, AIError, ChatMessage
from .factory import create_ai_service, get_ai_service, reset_ai_service, is_ai_configured
from .prompts import PromptTemplate, get_prompt, render_prompt
from . import nl2sql
from . import cr_enhancer
from . import agent as ai_agent
from . import report_generator
from . import report_pusher
from . import data_pipeline

__all__ = [
    'AIServiceBase', 'AIResponse', 'AIError', 'ChatMessage',
    'create_ai_service', 'get_ai_service', 'reset_ai_service', 'is_ai_configured',
    'PromptTemplate', 'get_prompt', 'render_prompt',
    'nl2sql', 'cr_enhancer', 'ai_agent',
    'report_generator', 'report_pusher', 'data_pipeline',
]
