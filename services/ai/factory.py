"""
AI 服务工厂
创建和管理 AI 服务实例
"""
import logging
from typing import Dict, Any, Optional
from .base import AIServiceBase, AIError
from .providers import get_provider_class

logger = logging.getLogger(__name__)

# 全局 AI 服务实例缓存
_ai_service: Optional[AIServiceBase] = None
_current_config: Optional[Dict[str, Any]] = None


def create_ai_service(config: Dict[str, Any]) -> AIServiceBase:
    """
    创建 AI 服务实例
    Args:
        config: 配置字典，包含 provider, api_key, model 等
    Returns:
        AIServiceBase 实例
    """
    provider = config.get('provider', 'openai').lower()
    provider_class = get_provider_class(provider)
    return provider_class(config)


def get_ai_service(config: Optional[Dict[str, Any]] = None) -> Optional[AIServiceBase]:
    """
    获取全局 AI 服务实例（单例模式）
    Args:
        config: 配置，如果提供且与当前不同则重新创建
    Returns:
        AIServiceBase 实例，如果未配置则返回 None
    """
    global _ai_service, _current_config

    if config is not None:
        # 配置变化时重新创建
        if _current_config != config or _ai_service is None:
            _ai_service = create_ai_service(config)
            _current_config = config.copy()
    elif _ai_service is None:
        # 尝试从环境变量创建
        import os
        api_key = os.environ.get('AI_API_KEY', '')
        if api_key:
            config = {
                'provider': os.environ.get('AI_PROVIDER', 'openai'),
                'api_key': api_key,
                'model': os.environ.get('AI_MODEL', 'gpt-3.5-turbo'),
                'base_url': os.environ.get('AI_BASE_URL', ''),
            }
            _ai_service = create_ai_service(config)
            _current_config = config

    return _ai_service


def reset_ai_service():
    """重置 AI 服务实例（配置变更后调用）"""
    global _ai_service, _current_config
    _ai_service = None
    _current_config = None
    logger.info("AI 服务实例已重置")


def is_ai_configured() -> bool:
    """检查 AI 是否配置"""
    service = get_ai_service()
    return service is not None and service.validate_config()
