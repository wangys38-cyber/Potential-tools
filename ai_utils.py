"""
AI 工具函数共享模块
从 app.py 提取，供 app.py 和 bp_ai.py 共同使用
"""
import os
import json
import logging
import requests
import crypto_utils

logger = logging.getLogger(__name__)


def get_ai_config(user_id=None):
    """获取 AI 配置 — 优先读取用户级配置，其次全局配置，最后环境变量

    API Key 在数据库中加密存储，读取时自动解密
    """
    import auth
    import db

    # 0. 未指定 user_id 时，尝试从 session 获取当前用户
    if user_id is None:
        try:
            user = auth.get_current_user()
            if user and user.get('id'):
                user_id = user['id']
        except Exception:
            pass
    # 1. 优先读取用户级配置
    if user_id:
        user_config = db.get_user_ai_config(user_id)
        if user_config and user_config.get('api_key', '').strip():
            # 解密存储的 API Key
            user_config['api_key'] = crypto_utils.decrypt(user_config['api_key'])
            config = user_config
        else:
            config = db.get_config('ai_config', {}) or {}
            # 全局配置也需解密
            if isinstance(config, dict) and config.get('api_key'):
                config['api_key'] = crypto_utils.decrypt(config['api_key'])
    else:
        config = db.get_config('ai_config', {}) or {}
        if isinstance(config, dict) and config.get('api_key'):
            config['api_key'] = crypto_utils.decrypt(config['api_key'])
    if not isinstance(config, dict):
        config = {}
    # 2. 环境变量覆盖（最高优先级，主要用于部署时全局配置）
    config['api_key'] = os.environ.get('AI_API_KEY', config.get('api_key', ''))
    config['base_url'] = os.environ.get('AI_BASE_URL', config.get('base_url', 'https://dashscope.aliyuncs.com/api/v1'))
    config['model'] = os.environ.get('AI_MODEL', config.get('model', 'qwen-turbo'))
    config['enabled'] = bool(config.get('api_key', '').strip())
    return config


def call_ai(messages, model=None, max_tokens=2000, temperature=0.7, timeout=60):
    """统一的 AI 文本生成调用（非流式），支持 DashScope 和 OpenAI 兼容格式"""
    ai_config = get_ai_config()
    if not ai_config.get('enabled'):
        raise ValueError('AI功能未配置')

    base_url = ai_config.get('base_url', 'https://dashscope.aliyuncs.com/api/v1')
    api_key = ai_config.get('api_key', '')
    use_model = model or ai_config.get('model', 'qwen-turbo')
    is_openai = 'dashscope' not in base_url

    if is_openai:
        # OpenAI 兼容格式（火山引擎/豆包等）
        response = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': use_model,
                'messages': messages,
                'max_tokens': max_tokens,
                'temperature': temperature
            },
            timeout=timeout
        )
        if response.status_code == 200:
            result = response.json()
            return result.get('choices', [{}])[0].get('message', {}).get('content', '')
        else:
            raise RuntimeError(f'AI服务返回错误({response.status_code}): {response.text[:300]}')
    else:
        # DashScope 格式（阿里云百炼）
        response = requests.post(
            f"{base_url}/services/aigc/text-generation/generation",
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': use_model,
                'input': {'messages': messages},
                'parameters': {
                    'result_format': 'message',
                    'max_tokens': max_tokens,
                    'temperature': temperature
                }
            },
            timeout=timeout
        )
        if response.status_code == 200:
            result = response.json()
            return result.get('output', {}).get('choices', [{}])[0].get('message', {}).get('content', '')
        else:
            raise RuntimeError(f'AI服务返回错误({response.status_code}): {response.text[:300]}')


def call_ai_stream(messages, model=None, max_tokens=2000, temperature=0.7):
    """统一的 AI 文本生成调用（流式 SSE 生成器），支持 DashScope 和 OpenAI 兼容格式

    生成 SSE 格式数据：
        data: {"output": {"choices": [{"message": {"content": "..."}}]}}\\n\\n
    或错误：
        data: {"error": "..."}\\n\\n
    """
    ai_config = get_ai_config()
    if not ai_config.get('enabled'):
        yield 'data: {"error": "AI功能未配置"}\n\n'
        return

    base_url = ai_config.get('base_url', 'https://dashscope.aliyuncs.com/api/v1')
    api_key = ai_config.get('api_key', '')
    use_model = model or ai_config.get('model', 'qwen-turbo')
    is_openai = 'dashscope' not in base_url

    if is_openai:
        # OpenAI 兼容格式流式
        response = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': use_model,
                'messages': messages,
                'max_tokens': max_tokens,
                'temperature': temperature,
                'stream': True
            },
            stream=True,
            timeout=120
        )
        if response.status_code != 200:
            err_text = response.text[:200] if hasattr(response, 'text') else ''
            yield f'data: {json.dumps({"error": f"AI服务错误({response.status_code}): {err_text}"})}\n\n'
            return
        for line in response.iter_lines():
            if not line:
                continue
            line_str = line.decode('utf-8') if isinstance(line, bytes) else line
            if not line_str.startswith('data:'):
                continue
            json_str = line_str[5:].strip()
            if json_str == '[DONE]':
                break
            try:
                data = json.loads(json_str)
                choices = data.get('choices', [])
                if choices:
                    delta = choices[0].get('delta', {})
                    content = delta.get('content', '')
                    if content:
                        normalized = {'output': {'choices': [{'message': {'content': content}}]}}
                        yield f'data: {json.dumps(normalized, ensure_ascii=False)}\n\n'
            except json.JSONDecodeError:
                continue
    else:
        # DashScope 格式流式
        response = requests.post(
            f"{base_url}/services/aigc/text-generation/generation",
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'X-DashScope-SSE': 'enable'
            },
            json={
                'model': use_model,
                'input': {'messages': messages},
                'parameters': {
                    'result_format': 'message',
                    'max_tokens': max_tokens,
                    'temperature': temperature,
                    'incremental_output': True
                }
            },
            stream=True,
            timeout=120
        )
        if response.status_code != 200:
            yield f'data: {json.dumps({"error": f"AI服务错误({response.status_code})"})}\n\n'
            return
        for line in response.iter_lines():
            if not line:
                continue
            line_str = line.decode('utf-8') if isinstance(line, bytes) else line
            if line_str.startswith('data:'):
                yield line_str + '\n\n'
            elif line_str.startswith('{'):
                yield f'data: {line_str}\n\n'
