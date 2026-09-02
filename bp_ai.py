"""
AI 相关路由 Blueprint
从 app.py 提取的 AI 配置管理、模型列表、对话、测试路由
依赖：ai_utils（AI 调用）、auth（认证）、db（数据库）
"""
from flask import Blueprint, request, jsonify, Response, stream_with_context
import logging

import auth
import db
import ai_utils
from ttl_cache import ttl_cache, invalidate as ttl_invalidate

bp = Blueprint('ai', __name__)
logger = logging.getLogger(__name__)


# ==================== AI 对话助手（SSE 流式） ====================
@bp.route('/api/ai-chat', methods=['POST'])
def api_ai_chat():
    """AI 对话助手 — SSE 流式输出"""
    user = auth.get_current_user()
    if not user and not auth.ALLOW_GUEST:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json(silent=True) or {}
    messages = data.get('messages', [])
    model = data.get('model')

    if not messages or not isinstance(messages, list):
        return jsonify({'error': '消息不能为空'}), 400

    system_prompt = {
        'role': 'system',
        'content': '你是工具集内置的AI助手。你可以帮助用户回答问题、编写文案、分析数据、生成代码等。请用中文回复，回答要简洁实用。'
    }
    full_messages = [system_prompt] + messages[-20:]

    ai_config = ai_utils.get_ai_config()
    if not ai_config.get('enabled'):
        return jsonify({'error': 'AI功能未配置，请在设置中配置API Key'}), 503

    return Response(
        stream_with_context(ai_utils.call_ai_stream(full_messages, model=model)),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


# ==================== 模型列表 ====================
@ttl_cache(ttl_seconds=120, key_prefix='ai_models_list')
def _get_models_list(base_url):
    """根据 base_url 返回模型列表（缓存 120 秒，配置变更时主动失效）"""
    base_url_lower = base_url.lower()

    # 豆包（字节跳动）
    if 'volces.com' in base_url_lower or 'ark.cn-beijing' in base_url_lower:
        return [
            {'id': 'doubao-pro-32k', 'name': 'Doubao Pro 32K', 'desc': '通用场景，平衡性能与成本'},
            {'id': 'doubao-lite-32k', 'name': 'Doubao Lite 32K', 'desc': '轻量快速，适合简单任务'},
            {'id': 'doubao-1.5-pro-32k', 'name': 'Doubao 1.5 Pro 32K', 'desc': '最新版本，更强理解能力'},
            {'id': 'ep-20240101-xxxxx', 'name': '自定义推理接入点', 'desc': '在火山引擎控制台创建接入点后替换'},
        ], 'doubao-pro-32k'

    # DeepSeek
    if 'deepseek.com' in base_url_lower:
        return [
            {'id': 'deepseek-chat', 'name': 'DeepSeek Chat', 'desc': '通用对话模型'},
            {'id': 'deepseek-reasoner', 'name': 'DeepSeek Reasoner', 'desc': '推理模型，适合复杂逻辑'},
        ], 'deepseek-chat'

    # 小米 MiMo
    if 'xiaomi.com' in base_url_lower:
        return [
            {'id': 'MiMo-7B', 'name': 'MiMo 7B', 'desc': '小米开源模型'},
            {'id': 'MiMo-VL-7B', 'name': 'MiMo VL 7B', 'desc': '多模态模型'},
        ], 'MiMo-7B'

    # OpenAI
    if 'openai.com' in base_url_lower:
        return [
            {'id': 'gpt-4o', 'name': 'GPT-4o', 'desc': '旗舰模型，多模态'},
            {'id': 'gpt-4o-mini', 'name': 'GPT-4o Mini', 'desc': '轻量快速，成本低'},
            {'id': 'gpt-4-turbo', 'name': 'GPT-4 Turbo', 'desc': '高速推理'},
        ], 'gpt-4o-mini'

    # 通义千问（阿里云）
    if 'dashscope' in base_url_lower or 'aliyuncs.com' in base_url_lower:
        return [
            {'id': 'qwen-turbo', 'name': '通义千问 Turbo', 'desc': '快速响应，日常使用'},
            {'id': 'qwen-plus', 'name': '通义千问 Plus', 'desc': '均衡质量与速度'},
            {'id': 'qwen-max', 'name': '通义千问 Max', 'desc': '最强推理能力'},
        ], 'qwen-turbo'

    # 智谱清言（GLM）
    if 'bigmodel.cn' in base_url_lower or 'zhipu' in base_url_lower:
        return [
            {'id': 'glm-4-plus', 'name': 'GLM-4 Plus', 'desc': '旗舰模型，长上下文'},
            {'id': 'glm-4-flash', 'name': 'GLM-4 Flash', 'desc': '轻量快速，免费额度'},
            {'id': 'glm-4-air', 'name': 'GLM-4 Air', 'desc': '均衡性能'},
            {'id': 'glm-4-long', 'name': 'GLM-4 Long', 'desc': '超长上下文'},
        ], 'glm-4-flash'

    # 月之暗面（Kimi）
    if 'moonshot.cn' in base_url_lower:
        return [
            {'id': 'moonshot-v1-8k', 'name': 'Moonshot V1 8K', 'desc': '标准上下文'},
            {'id': 'moonshot-v1-32k', 'name': 'Moonshot V1 32K', 'desc': '长上下文，适合长文档'},
            {'id': 'moonshot-v1-128k', 'name': 'Moonshot V1 128K', 'desc': '超长上下文'},
        ], 'moonshot-v1-8k'

    # 腾讯混元
    if 'hunyuan' in base_url_lower or 'tencent' in base_url_lower:
        return [
            {'id': 'hunyuan-lite', 'name': 'Hunyuan Lite', 'desc': '轻量快速'},
            {'id': 'hunyuan-pro', 'name': 'Hunyuan Pro', 'desc': '专业版，更强能力'},
        ], 'hunyuan-lite'

    # 默认：OpenAI 兼容格式，返回通用模型
    return [
        {'id': 'gpt-4o-mini', 'name': 'GPT-4o Mini（兼容）', 'desc': 'OpenAI 兼容格式'},
        {'id': 'gpt-3.5-turbo', 'name': 'GPT-3.5 Turbo（兼容）', 'desc': 'OpenAI 兼容格式'},
    ], 'gpt-4o-mini'

@bp.route('/api/ai-models', methods=['GET'])
def api_ai_models():
    """获取可用模型列表（根据 API 提供商自动适配，TTL 缓存 120 秒）"""
    user = auth.get_current_user()
    if not user and not auth.ALLOW_GUEST:
        return jsonify({'error': '请先登录'}), 401

    ai_config = ai_utils.get_ai_config()
    base_url = ai_config.get('base_url', 'https://dashscope.aliyuncs.com/api/v1')
    models, default_model = _get_models_list(base_url)
    current = ai_config.get('model', default_model)

    return jsonify({
        'models': models,
        'current': current
    })


# ==================== AI 配置管理 ====================
@bp.route('/api/ai-config', methods=['GET'])
def api_get_ai_config():
    """获取当前用户的 AI 配置状态"""
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录', 'need_login': True}), 401

    user_config = db.get_user_ai_config(user['id'])
    has_user_config = bool(user_config and user_config.get('api_key', '').strip())
    # 自动迁移全局配置到用户级
    if not has_user_config:
        global_config = db.get_config('ai_config', {}) or {}
        if isinstance(global_config, dict) and global_config.get('api_key', '').strip():
            # 迁移时加密 API Key
            import crypto_utils
            if not crypto_utils.is_encrypted(global_config['api_key']):
                global_config['api_key'] = crypto_utils.encrypt(global_config['api_key'])
            db.set_user_ai_config(user['id'], global_config)
            user_config = global_config
            has_user_config = True
            logger.info(f"用户 {user['id']} 的 AI 配置已从全局迁移到用户级")

    config = ai_utils.get_ai_config(user['id'])

    # 判断配置来源
    config_source = 'user'
    if not has_user_config:
        global_config = db.get_config('ai_config', {}) or {}
        if isinstance(global_config, dict) and global_config.get('api_key', '').strip():
            config_source = 'global'
        elif os.environ.get('AI_API_KEY', '').strip():
            config_source = 'environment'
        else:
            config_source = 'none'

    return jsonify({
        'status': 'success',
        'data': {
            'enabled': config['enabled'],
            'has_key': bool(config.get('api_key', '').strip()),
            'has_user_config': has_user_config,
            'config_source': config_source,
            'key_masked': (config.get('api_key', '')[:3] + '****') if config.get('api_key', '').strip() else '',
            'base_url': config.get('base_url', ''),
            'model': config.get('model', ''),
        }
    })


@bp.route('/api/ai-config', methods=['POST'])
def api_save_ai_config():
    """保存用户的 AI 配置"""
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录', 'need_login': True}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': '无效的配置数据'}), 400

    config = db.get_user_ai_config(user['id'])
    if not isinstance(config, dict):
        config = {}
    if 'api_key' in data and data['api_key'].strip():
        # 只有当用户输入了新的 API Key 时才更新并加密
        config['api_key'] = data['api_key'].strip()
        need_encrypt = True
    else:
        need_encrypt = False
    if 'base_url' in data:
        config['base_url'] = data['base_url'].strip()
    if 'model' in data:
        config['model'] = data['model'].strip()
    # api_key 为空视为删除用户配置
    if not config.get('api_key', '').strip():
        config = {}
    else:
        # 只有新输入的 API Key 才需要加密，避免双重加密
        if need_encrypt:
            import crypto_utils
            config['api_key'] = crypto_utils.encrypt(config['api_key'])
    try:
        db.set_user_ai_config(user['id'], config)
        # 阶段五：配置变更后主动失效模型列表缓存
        ttl_invalidate('ai_models_list')
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"保存 AI 配置失败: {e}", exc_info=True)
        return jsonify({'error': f'保存配置失败: {str(e)}'}), 500


# ==================== AI 连接测试 ====================
@bp.route('/api/ai-test', methods=['POST'])
def api_ai_test():
    """测试 AI 连接"""
    user = auth.get_current_user()
    if not user and not auth.ALLOW_GUEST:
        return jsonify({'error': '请先登录'}), 401

    ai_config = ai_utils.get_ai_config()
    if not ai_config.get('enabled'):
        return jsonify({'error': 'AI功能未配置，请先设置 API Key'}), 503

    try:
        reply = ai_utils.call_ai(
            [{'role': 'user', 'content': '请回复"连接成功"四个字'}],
            max_tokens=20,
            temperature=0.1,
            timeout=15
        )
        return jsonify({
            'status': 'success',
            'reply': reply.strip(),
            'model': ai_config.get('model', ''),
            'base_url': ai_config.get('base_url', '')
        })
    except Exception as e:
        err_msg = str(e)
        logger.error(f'AI连接测试失败: {e}')
        if '401' in err_msg or '403' in err_msg:
            return jsonify({'error': 'API Key 认证失败（401），请检查 API Key 是否正确，或重新配置'}), 401
        elif '429' in err_msg:
            return jsonify({'error': 'API 限流（429），请稍后重试'}), 429
        elif 'timeout' in err_msg.lower() or '超时' in err_msg:
            return jsonify({'error': '连接超时，请检查网络或 base_url 配置'}), 504
        return jsonify({'error': f'连接失败: {err_msg}'}), 502


# ==================== 注册函数 ====================
def register(app):
    """注册 Blueprint 到 Flask app"""
    app.register_blueprint(bp)
