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
        # 尝试从数据库读取配置（v8.0 新格式 + 旧格式兼容）
        db_config = _load_config_from_db()
        if db_config:
            _ai_service = create_ai_service(db_config)
            _current_config = db_config
        else:
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


def _load_config_from_db() -> Optional[Dict[str, Any]]:
    """从数据库加载 AI 配置（兼容 v8.0 新格式和旧格式）"""
    try:
        import os
        os.environ.setdefault('DB_DIR', r'D:\app\data')
        from db import ai as ai_db
        from db.base import engine
        from sqlalchemy import text

        # 1. 优先从 v8.0 ai_configs 表读取
        try:
            with engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT * FROM ai_configs WHERE is_active = 1 LIMIT 1"
                )).fetchone()
                if row:
                    d = dict(row._mapping)
                    if d.get('api_key'):
                        # 解密 API Key
                        try:
                            import crypto_utils
                            d['api_key'] = crypto_utils.decrypt(d['api_key'])
                        except:
                            pass
                        return {
                            'provider': d.get('provider', 'openai'),
                            'api_key': d['api_key'],
                            'model': d.get('model', ''),
                            'base_url': d.get('base_url', ''),
                            'temperature': d.get('temperature', 0.7),
                            'max_tokens': d.get('max_tokens', 2000),
                        }
        except Exception as e:
            logger.debug(f"从 ai_configs 表读取失败: {e}")

        # 2. 兼容旧格式：从 user_preferences 表读取
        try:
            import json
            with engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT ai_config FROM user_preferences WHERE user_id = 1 LIMIT 1"
                )).fetchone()
                if row and row[0]:
                    old_config = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    if old_config and old_config.get('api_key'):
                        # 解密
                        try:
                            import crypto_utils
                            old_config['api_key'] = crypto_utils.decrypt(old_config['api_key'])
                        except:
                            pass
                        base_url = old_config.get('base_url', '')
                        if 'dashscope' in base_url or 'aliyuncs' in base_url:
                            provider = 'doubao'
                        elif 'bigmodel' in base_url or 'zhipu' in base_url:
                            provider = 'openai'
                        elif 'deepseek' in base_url:
                            provider = 'deepseek'
                        elif 'localhost' in base_url or '127.0.0.1' in base_url:
                            provider = 'ollama'
                        else:
                            provider = 'openai'
                        return {
                            'provider': provider,
                            'api_key': old_config['api_key'],
                            'model': old_config.get('model', ''),
                            'base_url': base_url,
                            'temperature': old_config.get('temperature', 0.7),
                            'max_tokens': old_config.get('max_tokens', 2000),
                        }
        except Exception as e:
            logger.debug(f"从旧配置读取失败: {e}")

    except Exception as e:
        logger.debug(f"加载数据库配置失败: {e}")

    return None


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
