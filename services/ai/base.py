"""
AI 服务基类
定义统一的接口，所有提供商都必须实现这些方法
"""
import time
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Generator, Any

logger = logging.getLogger(__name__)


@dataclass
class AIResponse:
    """AI 响应数据结构"""
    content: str
    model: str
    provider: str
    tokens_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # system, user, assistant
    content: str
    name: Optional[str] = None


class AIError(Exception):
    """AI 服务错误"""
    def __init__(self, message: str, code: str = "unknown", provider: str = ""):
        super().__init__(message)
        self.code = code
        self.provider = provider


class AIServiceBase:
    """AI 服务基类"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get('api_key', '')
        self.model = config.get('model', 'gpt-3.5-turbo')
        self.temperature = config.get('temperature', 0.7)
        self.max_tokens = config.get('max_tokens', 2000)
        self.timeout = config.get('timeout', 60)
        self.provider_name = self.__class__.__name__.replace('Provider', '').lower()

    def chat(self, messages: List[ChatMessage], **kwargs) -> AIResponse:
        """
        非流式聊天
        Args:
            messages: 消息列表
            **kwargs: 额外参数
        Returns:
            AIResponse
        """
        raise NotImplementedError

    def chat_stream(self, messages: List[ChatMessage], **kwargs) -> Generator[str, None, None]:
        """
        流式聊天
        Args:
            messages: 消息列表
            **kwargs: 额外参数
        Yields:
            内容片段
        """
        raise NotImplementedError

    def embed(self, text: str) -> List[float]:
        """
        文本向量化
        Args:
            text: 输入文本
        Returns:
            向量
        """
        raise NotImplementedError

    def _build_messages(self, messages: List[ChatMessage]) -> List[Dict]:
        """构建 API 消息格式"""
        result = []
        for msg in messages:
            item = {"role": msg.role, "content": msg.content}
            if msg.name:
                item["name"] = msg.name
            result.append(item)
        return result

    def _measure_latency(self, start_time: float) -> int:
        """计算延迟（毫秒）"""
        return int((time.time() - start_time) * 1000)

    def validate_config(self) -> bool:
        """验证配置是否有效"""
        return bool(self.api_key)
