"""
v8.0 AI 原生 - AI API 路由
提供 AI 对话、配置管理、自然语言查询等功能
"""
import os
import json
import time
import uuid
import logging
from flask import Blueprint, request, jsonify, session, Response, stream_with_context

from db import ai as ai_db
from services.ai import create_ai_service, get_ai_service, reset_ai_service, is_ai_configured
from services.ai.base import ChatMessage, AIError
from services.ai.prompts import get_prompt, render_prompt
from services.ai import nl2sql

logger = logging.getLogger(__name__)

bp = Blueprint('ai_native', __name__, url_prefix='/api/ai')


def _get_current_user():
    """获取当前用户"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return user_id


def _require_login():
    """要求登录"""
    user_id = _get_current_user()
    if not user_id:
        return None, (jsonify({'status': 'error', 'error': '未登录'}), 401)
    return user_id, None


def _get_user_ai_config(user_id):
    """获取用户的 AI 配置并创建服务"""
    config = ai_db.get_ai_config(user_id)
    if not config or not config.get('api_key'):
        return None, (jsonify({'status': 'error', 'error': 'AI 未配置，请先在设置中配置 API Key'}), 400)

    service_config = {
        'provider': config.get('provider', 'openai'),
        'api_key': config.get('api_key', ''),
        'base_url': config.get('base_url', ''),
        'model': config.get('model', 'gpt-3.5-turbo'),
        'temperature': config.get('temperature', 0.7),
        'max_tokens': config.get('max_tokens', 2000),
    }
    service = create_ai_service(service_config)
    return service, None


# ==================== AI 配置 ====================

@bp.route('/config', methods=['GET'])
def get_config():
    """获取 AI 配置"""
    user_id, err = _require_login()
    if err:
        return err

    configs = ai_db.list_ai_configs(user_id)
    active = ai_db.get_ai_config(user_id)
    # 不返回 api_key
    for c in configs:
        c.pop('api_key', None)
    if active:
        active.pop('api_key', None)

    return jsonify({
        'status': 'success',
        'configs': configs,
        'active': active,
        'is_configured': active is not None,
    })


@bp.route('/config', methods=['POST'])
def save_config():
    """保存 AI 配置"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    provider = data.get('provider', 'openai')
    api_key = data.get('api_key', '').strip()
    base_url = data.get('base_url', '').strip()
    model = data.get('model', 'gpt-3.5-turbo')
    temperature = float(data.get('temperature', 0.7))
    max_tokens = int(data.get('max_tokens', 2000))

    if not api_key and provider != 'ollama':
        return jsonify({'status': 'error', 'error': 'API Key 不能为空'}), 400

    # 简单的 API Key 加密（base64，生产环境建议用 AES）
    import base64
    encrypted_key = base64.b64encode(api_key.encode()).decode() if api_key else ''

    success = ai_db.save_ai_config(
        user_id=user_id,
        provider=provider,
        api_key=encrypted_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if success:
        reset_ai_service()
        return jsonify({'status': 'success', 'message': '配置已保存'})
    else:
        return jsonify({'status': 'error', 'error': '保存失败'}), 500


@bp.route('/config/test', methods=['POST'])
def test_config():
    """测试 AI 配置是否可用"""
    user_id, err = _require_login()
    if err:
        return err

    service, err = _get_user_ai_config(user_id)
    if err:
        return err

    try:
        response = service.chat([
            ChatMessage(role='system', content='你是一个测试助手'),
            ChatMessage(role='user', content='请回复"连接成功"'),
        ], max_tokens=20)
        return jsonify({
            'status': 'success',
            'message': '连接成功',
            'response': response.content,
            'latency_ms': response.latency_ms,
        })
    except AIError as e:
        return jsonify({'status': 'error', 'error': str(e), 'code': e.code}), 400
    except Exception as e:
        logger.error(f"AI 测试失败: {e}")
        return jsonify({'status': 'error', 'error': f'测试失败: {str(e)}'}), 500


# ==================== AI 对话 ====================

@bp.route('/chat', methods=['POST'])
def chat():
    """AI 对话（非流式）"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    message = data.get('message', '').strip()
    session_id = data.get('session_id') or str(uuid.uuid4())
    system_prompt = data.get('system_prompt', '')

    if not message:
        return jsonify({'status': 'error', 'error': '消息不能为空'}), 400

    service, err = _get_user_ai_config(user_id)
    if err:
        return err

    try:
        # 构建消息列表
        messages = []
        if system_prompt:
            messages.append(ChatMessage(role='system', content=system_prompt))
        else:
            default_system = render_prompt('default', 'system')
            messages.append(ChatMessage(role='system', content=default_system))

        # 获取历史消息
        history = ai_db.get_ai_conversation(user_id, session_id, limit=20)
        for msg in history:
            messages.append(ChatMessage(role=msg['role'], content=msg['content']))

        # 添加当前消息
        messages.append(ChatMessage(role='user', content=message))

        # 保存用户消息
        ai_db.save_ai_message(user_id, session_id, 'user', message)

        # 调用 AI
        response = service.chat(messages)

        # 保存 AI 回复
        ai_db.save_ai_message(
            user_id, session_id, 'assistant',
            response.content, response.tokens_used, response.model
        )

        return jsonify({
            'status': 'success',
            'response': response.content,
            'session_id': session_id,
            'tokens_used': response.tokens_used,
            'latency_ms': response.latency_ms,
        })
    except AIError as e:
        return jsonify({'status': 'error', 'error': str(e), 'code': e.code}), 400
    except Exception as e:
        logger.error(f"AI 对话失败: {e}")
        return jsonify({'status': 'error', 'error': f'对话失败: {str(e)}'}), 500


@bp.route('/chat/stream', methods=['POST'])
def chat_stream():
    """AI 对话（流式输出）"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    message = data.get('message', '').strip()
    session_id = data.get('session_id') or str(uuid.uuid4())
    system_prompt = data.get('system_prompt', '')

    if not message:
        return jsonify({'status': 'error', 'error': '消息不能为空'}), 400

    service, err = _get_user_ai_config(user_id)
    if err:
        return err

    # 保存用户消息
    ai_db.save_ai_message(user_id, session_id, 'user', message)

    # 构建消息
    messages = []
    if system_prompt:
        messages.append(ChatMessage(role='system', content=system_prompt))
    else:
        default_system = render_prompt('default', 'system')
        messages.append(ChatMessage(role='system', content=default_system))

    history = ai_db.get_ai_conversation(user_id, session_id, limit=20)
    for msg in history:
        messages.append(ChatMessage(role=msg['role'], content=msg['content']))
    messages.append(ChatMessage(role='user', content=message))

    def generate():
        full_content = ''
        try:
            for chunk in service.chat_stream(messages):
                full_content += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
            # 保存完整回复
            ai_db.save_ai_message(user_id, session_id, 'assistant', full_content)
            yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
        except AIError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        except Exception as e:
            logger.error(f"流式对话失败: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


# ==================== 对话历史 ====================

@bp.route('/conversations', methods=['GET'])
def list_conversations():
    """列出会话列表"""
    user_id, err = _require_login()
    if err:
        return err

    sessions = ai_db.list_ai_sessions(user_id)
    return jsonify({'status': 'success', 'sessions': sessions})


@bp.route('/conversations/<session_id>', methods=['GET'])
def get_conversation(session_id):
    """获取某个会话的历史"""
    user_id, err = _require_login()
    if err:
        return err

    messages = ai_db.get_ai_conversation(user_id, session_id)
    return jsonify({'status': 'success', 'messages': messages, 'session_id': session_id})


@bp.route('/conversations/<session_id>', methods=['DELETE'])
def delete_conversation(session_id):
    """删除会话"""
    user_id, err = _require_login()
    if err:
        return err

    count = ai_db.delete_ai_conversation(user_id, session_id)
    return jsonify({'status': 'success', 'deleted': count})


# ==================== 使用统计 ====================

@bp.route('/usage', methods=['GET'])
def get_usage():
    """获取 AI 使用统计"""
    user_id, err = _require_login()
    if err:
        return err

    days = int(request.args.get('days', 30))
    stats = ai_db.get_ai_usage_stats(user_id, days)
    return jsonify({'status': 'success', 'stats': stats, 'days': days})


# ==================== AI 报告 ====================

@bp.route('/reports', methods=['GET'])
def list_reports():
    """列出 AI 报告"""
    user_id, err = _require_login()
    if err:
        return err

    report_type = request.args.get('type')
    reports = ai_db.list_ai_reports(user_id, report_type)
    return jsonify({'status': 'success', 'reports': reports})


@bp.route('/reports/<int:report_id>', methods=['GET'])
def get_report(report_id):
    """获取 AI 报告详情"""
    user_id, err = _require_login()
    if err:
        return err

    report = ai_db.get_ai_report(report_id)
    if not report or report['user_id'] != user_id:
        return jsonify({'status': 'error', 'error': '报告不存在'}), 404
    return jsonify({'status': 'success', 'report': report})


@bp.route('/reports/<int:report_id>', methods=['DELETE'])
def delete_report(report_id):
    """删除 AI 报告"""
    user_id, err = _require_login()
    if err:
        return err

    success = ai_db.delete_ai_report(user_id, report_id)
    if success:
        return jsonify({'status': 'success'})
    else:
        return jsonify({'status': 'error', 'error': '删除失败'}), 400


# ==================== 自然语言查询 (NL2SQL) ====================

@bp.route('/query/schema', methods=['GET'])
def get_query_schema():
    """获取可查询的表结构"""
    user_id, err = _require_login()
    if err:
        return err

    from services.ai.nl2sql import QUERYABLE_TABLES
    tables = []
    for name, info in QUERYABLE_TABLES.items():
        tables.append({
            'name': name,
            'description': info['description'],
            'columns': list(info['columns'].keys()),
        })
    return jsonify({'status': 'success', 'tables': tables})


@bp.route('/query', methods=['POST'])
def natural_language_query():
    """自然语言查询数据"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    question = data.get('question', '').strip()

    if not question:
        return jsonify({'status': 'error', 'error': '问题不能为空'}), 400

    service, err = _get_user_ai_config(user_id)
    if err:
        return err

    try:
        # 判断是否管理员
        from db import get_user_by_id
        user = get_user_by_id(user_id)
        is_admin = bool(user and user.get('is_admin'))

        # 执行 NL2SQL 查询
        result = nl2sql.query(question, service, user_id, is_admin)

        # 保存到对话历史
        session_id = data.get('session_id') or 'nl2sql_' + str(int(time.time()))
        ai_db.save_ai_message(user_id, session_id, 'user', question)
        ai_db.save_ai_message(
            user_id, session_id, 'assistant',
            result['explanation'], 0, service.model
        )

        return jsonify({
            'status': 'success',
            'question': result['question'],
            'sql': result['sql'],
            'columns': result['columns'],
            'rows': result['rows'],
            'row_count': result['row_count'],
            'explanation': result['explanation'],
            'latency_ms': result['latency_ms'],
        })
    except ValueError as e:
        return jsonify({'status': 'error', 'error': str(e)}), 400
    except AIError as e:
        return jsonify({'status': 'error', 'error': str(e), 'code': e.code}), 400
    except Exception as e:
        logger.error(f'NL2SQL 查询失败: {e}')
        return jsonify({'status': 'error', 'error': f'查询失败: {str(e)}'}), 500
