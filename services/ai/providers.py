"""
AI 提供商实现
支持 OpenAI 兼容 API（OpenAI、Doubao、DeepSeek、本地 Ollama 等）
"""
import json
import time
import logging
import requests
from typing import List, Dict, Optional, Generator, Any
from .base import AIServiceBase, AIResponse, ChatMessage, AIError

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(AIServiceBase):
    """OpenAI 兼容 API 提供商（支持 OpenAI/Doubao/DeepSeek/本地模型等）"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://api.openai.com/v1')
        self.api_key = config.get('api_key', '')
        self.provider_name = config.get('provider_name', 'openai')

    def _get_headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

    def chat(self, messages: List[ChatMessage], **kwargs) -> AIResponse:
        """非流式聊天"""
        start_time = time.time()
        url = f"{self.base_url}/chat/completions"

        payload = {
            'model': kwargs.get('model', self.model),
            'messages': self._build_messages(messages),
            'temperature': kwargs.get('temperature', self.temperature),
            'max_tokens': kwargs.get('max_tokens', self.max_tokens),
            'stream': False,
        }

        try:
            resp = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            choice = data['choices'][0]
            usage = data.get('usage', {})

            return AIResponse(
                content=choice['message']['content'],
                model=data.get('model', self.model),
                provider=self.provider_name,
                tokens_used=usage.get('total_tokens', 0),
                prompt_tokens=usage.get('prompt_tokens', 0),
                completion_tokens=usage.get('completion_tokens', 0),
                latency_ms=self._measure_latency(start_time),
            )
        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"AI 调用失败: {error_msg}")
            raise AIError(error_msg, code=f"http_{e.response.status_code}", provider=self.provider_name)
        except requests.exceptions.RequestException as e:
            logger.error(f"AI 网络错误: {e}")
            raise AIError(f"网络错误: {str(e)}", code="network_error", provider=self.provider_name)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"AI 响应解析错误: {e}")
            raise AIError(f"响应解析错误: {str(e)}", code="parse_error", provider=self.provider_name)

    def chat_stream(self, messages: List[ChatMessage], **kwargs) -> Generator[str, None, None]:
        """流式聊天"""
        url = f"{self.base_url}/chat/completions"

        payload = {
            'model': kwargs.get('model', self.model),
            'messages': self._build_messages(messages),
            'temperature': kwargs.get('temperature', self.temperature),
            'max_tokens': kwargs.get('max_tokens', self.max_tokens),
            'stream': True,
        }

        try:
            resp = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=self.timeout,
                stream=True,
            )
            resp.raise_for_status()

            for line in resp.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk['choices'][0].get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except requests.exceptions.RequestException as e:
            logger.error(f"AI 流式调用失败: {e}")
            raise AIError(f"流式请求错误: {str(e)}", code="stream_error", provider=self.provider_name)

    def embed(self, text: str) -> List[float]:
        """文本向量化"""
        url = f"{self.base_url}/embeddings"
        payload = {
            'model': kwargs.get('model', 'text-embedding-ada-002'),
            'input': text,
        }

        try:
            resp = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data['data'][0]['embedding']
        except Exception as e:
            logger.error(f"Embedding 失败: {e}")
            raise AIError(f"向量化失败: {str(e)}", code="embed_error", provider=self.provider_name)


class DoubaoProvider(OpenAICompatibleProvider):
    """豆包（字节跳动）提供商"""

    def __init__(self, config: Dict[str, Any]):
        config['base_url'] = config.get('base_url', 'https://ark.cn-beijing.volces.com/api/v3')
        config['provider_name'] = 'doubao'
        super().__init__(config)


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek 提供商"""

    def __init__(self, config: Dict[str, Any]):
        config['base_url'] = config.get('base_url', 'https://api.deepseek.com/v1')
        config['provider_name'] = 'deepseek'
        super().__init__(config)


class OllamaProvider(OpenAICompatibleProvider):
    """本地 Ollama 提供商"""

    def __init__(self, config: Dict[str, Any]):
        config['base_url'] = config.get('base_url', 'http://localhost:11434/v1')
        config['api_key'] = config.get('api_key', 'ollama')
        config['provider_name'] = 'ollama'
        super().__init__(config)

    def validate_config(self) -> bool:
        """Ollama 不需要 API Key"""
        return True


# 提供商注册表
PROVIDER_REGISTRY = {
    'openai': OpenAICompatibleProvider,
    'doubao': DoubaoProvider,
    'deepseek': DeepSeekProvider,
    'ollama': OllamaProvider,
}


def get_provider_class(provider: str) -> type:
    """获取提供商类"""
    return PROVIDER_REGISTRY.get(provider.lower(), OpenAICompatibleProvider)
