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
from services.ai import agent as ai_agent_service
from db import agent as agent_db
from db import report as report_db
from services.ai import report_generator, report_pusher
from services.ai import data_pipeline
from db import pipeline as pipeline_db

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


# ==================== v8.0 AI Agent 自动分析 ====================

@bp.route('/agent/config', methods=['GET'])
def get_agent_config():
    """获取 Agent 配置"""
    user_id, err = _require_login()
    if err:
        return err

    name = request.args.get('name', 'default')
    config = agent_db.get_agent_config(user_id, name)
    if not config:
        # 返回默认配置
        config = {
            'user_id': user_id,
            'name': name,
            'enabled': 0,
            'schedule_type': 'daily',
            'schedule_time': '09:00',
            'monitor_metrics': ['unresolved_bugs', 'critical_bugs', 'new_today'],
            'alert_threshold': {'critical_bugs': 5, 'new_today': 10, 'unresolved_bugs': 50},
            'auto_report': 1,
            'alert_enabled': 1,
            'data_sources': [],
        }
    return jsonify({'status': 'success', 'config': config})


@bp.route('/agent/config', methods=['POST'])
def save_agent_config():
    """保存 Agent 配置"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    name = data.get('name', 'default')

    config_id = agent_db.save_agent_config(user_id, name, data)

    # 如果启用了，计算下次运行时间
    if data.get('enabled'):
        config = agent_db.get_agent_config(user_id, name)
        if config:
            scheduler = ai_agent_service.get_agent_scheduler()
            next_run = scheduler._calculate_next_run(config)
            agent_db.update_agent_run_time(config_id, 0, next_run)

    return jsonify({'status': 'success', 'config_id': config_id})


@bp.route('/agent/run', methods=['POST'])
def run_agent_manually():
    """手动触发 Agent 运行"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    name = data.get('name', 'default')

    config = agent_db.get_agent_config(user_id, name)
    if not config:
        return jsonify({'status': 'error', 'error': 'Agent 配置不存在'}), 404

    # 创建运行记录
    run_id = agent_db.create_agent_run(user_id, config['id'], 'manual')

    try:
        # 获取 AI 服务
        service = None
        try:
            service, _ = _get_user_ai_config(user_id)
        except:
            pass

        # 执行分析
        result = ai_agent_service.run_agent_analysis(user_id, config, service)

        # 更新运行记录
        agent_db.update_agent_run(
            run_id=run_id,
            status='completed' if result['status'] == 'success' else result['status'],
            metrics_summary=result.get('metrics', {}),
            anomalies=result.get('anomalies', []),
            report_id=result.get('report_id', 0),
        )

        return jsonify({
            'status': 'success',
            'run_id': run_id,
            'result': result,
        })
    except Exception as e:
        logger.error(f'Agent 手动运行失败: {e}')
        agent_db.update_agent_run(run_id, 'failed', error_message=str(e))
        return jsonify({'status': 'error', 'error': str(e)}), 500


@bp.route('/agent/runs', methods=['GET'])
def list_agent_runs():
    """获取 Agent 运行历史"""
    user_id, err = _require_login()
    if err:
        return err

    limit = int(request.args.get('limit', 20))
    runs = agent_db.list_agent_runs(user_id, limit)
    return jsonify({'status': 'success', 'runs': runs})


@bp.route('/agent/alerts', methods=['GET'])
def list_agent_alerts():
    """获取告警列表"""
    user_id, err = _require_login()
    if err:
        return err

    only_unread = request.args.get('unread', '0') == '1'
    limit = int(request.args.get('limit', 50))
    alerts = agent_db.list_alerts(user_id, only_unread, limit)
    unread_count = agent_db.get_unread_alert_count(user_id)
    return jsonify({'status': 'success', 'alerts': alerts, 'unread_count': unread_count})


@bp.route('/agent/alerts/<int:alert_id>/read', methods=['POST'])
def mark_alert_read(alert_id):
    """标记告警已读"""
    user_id, err = _require_login()
    if err:
        return err

    success = agent_db.mark_alert_read(user_id, alert_id)
    return jsonify({'status': 'success' if success else 'error'})


@bp.route('/agent/alerts/read-all', methods=['POST'])
def mark_all_alerts_read():
    """标记所有告警已读"""
    user_id, err = _require_login()
    if err:
        return err

    count = agent_db.mark_all_alerts_read(user_id)
    return jsonify({'status': 'success', 'marked_count': count})


@bp.route('/agent/alerts/<int:alert_id>/resolve', methods=['POST'])
def resolve_alert(alert_id):
    """解决告警"""
    user_id, err = _require_login()
    if err:
        return err

    success = agent_db.resolve_alert(user_id, alert_id)
    return jsonify({'status': 'success' if success else 'error'})


@bp.route('/agent/status', methods=['GET'])
def get_agent_status():
    """获取 Agent 运行状态"""
    user_id, err = _require_login()
    if err:
        return err

    config = agent_db.get_agent_config(user_id)
    recent_runs = agent_db.list_agent_runs(user_id, limit=5)
    unread_count = agent_db.get_unread_alert_count(user_id)

    scheduler = ai_agent_service.get_agent_scheduler()

    return jsonify({
        'status': 'success',
        'enabled': bool(config and config.get('enabled')),
        'scheduler_running': scheduler.running,
        'last_run_at': config.get('last_run_at', 0) if config else 0,
        'next_run_at': config.get('next_run_at', 0) if config else 0,
        'recent_runs': recent_runs,
        'unread_alerts': unread_count,
    })


# ==================== v8.0 智能报告生成与推送 ====================

@bp.route('/report/templates', methods=['GET'])
def list_report_templates():
    """列出报告模板"""
    user_id, err = _require_login()
    if err:
        return err

    templates = report_db.list_report_templates(user_id)
    # 加上内置模板
    builtin = []
    for t_type, t_data in report_generator.BUILTIN_TEMPLATES.items():
        builtin.append({
            'id': 0,
            'name': t_data['name'],
            'template_type': t_type,
            'is_builtin': True,
            'title_format': t_data['title_format'],
            'include_metrics': t_data['include_metrics'],
        })
    return jsonify({'status': 'success', 'templates': templates, 'builtin_templates': builtin})


@bp.route('/report/templates', methods=['POST'])
def save_report_template():
    """保存报告模板"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    template_id = report_db.save_report_template(user_id, data)
    return jsonify({'status': 'success', 'template_id': template_id})


@bp.route('/report/templates/<int:template_id>', methods=['DELETE'])
def delete_report_template(template_id):
    """删除报告模板"""
    user_id, err = _require_login()
    if err:
        return err

    success = report_db.delete_report_template(user_id, template_id)
    return jsonify({'status': 'success' if success else 'error'})


@bp.route('/report/generate', methods=['POST'])
def generate_report():
    """生成报告（预览）"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    issues = data.get('issues', [])
    daily_data = data.get('daily_data', [])
    template_type = data.get('template_type', 'daily')

    if not issues:
        return jsonify({'status': 'error', 'error': '缺少问题数据'}), 400

    template = report_generator.get_builtin_template(template_type)
    if data.get('template_id'):
        custom = report_db.get_report_template(data['template_id'])
        if custom:
            template = custom

    service = None
    try:
        service, _ = _get_user_ai_config(user_id)
    except:
        pass

    report = report_generator.generate_report(issues, daily_data, template, service)
    return jsonify({'status': 'success', 'report': report})


@bp.route('/report/schedules', methods=['GET'])
def list_report_schedules():
    """列出推送计划"""
    user_id, err = _require_login()
    if err:
        return err

    schedules = report_db.list_report_schedules(user_id)
    return jsonify({'status': 'success', 'schedules': schedules})


@bp.route('/report/schedules', methods=['POST'])
def save_report_schedule():
    """保存推送计划"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    schedule_id = report_db.save_report_schedule(user_id, data)

    # 如果启用了，计算下次发送时间
    if data.get('enabled'):
        schedule = report_db.get_report_schedule(schedule_id)
        if schedule:
            next_send = report_pusher.calculate_next_send_time(schedule)
            report_db.update_schedule_send_time(schedule_id, 0, next_send)

    return jsonify({'status': 'success', 'schedule_id': schedule_id})


@bp.route('/report/schedules/<int:schedule_id>', methods=['DELETE'])
def delete_report_schedule(schedule_id):
    """删除推送计划"""
    user_id, err = _require_login()
    if err:
        return err

    success = report_db.delete_report_schedule(user_id, schedule_id)
    return jsonify({'status': 'success' if success else 'error'})


@bp.route('/report/schedules/<int:schedule_id>/run', methods=['POST'])
def run_report_schedule(schedule_id):
    """手动触发推送"""
    user_id, err = _require_login()
    if err:
        return err

    schedule = report_db.get_report_schedule(schedule_id)
    if not schedule or schedule['user_id'] != user_id:
        return jsonify({'status': 'error', 'error': '推送计划不存在'}), 404

    # 收集数据
    from db import user_data as user_data_db
    issues, daily_data = [], []
    try:
        records = user_data_db.list_user_data(user_id, data_type='cr_analysis', limit=1)
        if not records:
            records = user_data_db.list_user_data(user_id, limit=5)
        for record in records:
            content = record.get('content', '')
            if content:
                try:
                    data = json.loads(content) if isinstance(content, str) else content
                    issues = data.get('issues') or data.get('bugs') or data.get('rows') or []
                    daily_data = data.get('dailyTrend') or data.get('daily_data') or []
                    if issues:
                        break
                except:
                    continue
    except:
        pass

    if not issues:
        return jsonify({'status': 'error', 'error': '没有可分析的 CR 数据，请先上传 CR 数据'}), 400

    # 获取模板
    template = None
    if schedule.get('template_id'):
        template = report_db.get_report_template(schedule['template_id'])

    # 获取 AI 服务
    service = None
    try:
        service, _ = _get_user_ai_config(user_id)
    except:
        pass

    # 获取 SMTP 配置
    from db import get_config
    smtp_config = get_config('smtp_mail_config') or {}

    # 生成并推送
    result = report_pusher.generate_and_push_report(
        user_id=user_id,
        schedule=schedule,
        issues=issues,
        daily_data=daily_data,
        template=template,
        ai_service=service,
        smtp_config=smtp_config,
    )

    return jsonify(result)


@bp.route('/report/logs', methods=['GET'])
def list_report_logs():
    """列出推送日志"""
    user_id, err = _require_login()
    if err:
        return err

    limit = int(request.args.get('limit', 20))
    logs = report_db.list_push_logs(user_id, limit)
    return jsonify({'status': 'success', 'logs': logs})


# ==================== v8.0 跨工具数据联动 ====================

@bp.route('/pipeline/list', methods=['GET'])
def list_pipelines():
    """获取可用的工作流列表"""
    pipelines = data_pipeline.get_available_pipelines()
    return jsonify({'status': 'success', 'pipelines': pipelines})


@bp.route('/pipeline/push', methods=['POST'])
def push_to_pipeline():
    """推送数据到工作流管道"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    pipeline_key = data.get('pipeline_key', '')
    pipeline_data = data.get('data', {})
    title = data.get('title', '')
    metadata = data.get('metadata', {})

    if not pipeline_key:
        return jsonify({'status': 'error', 'error': '缺少 pipeline_key'}), 400

    if not pipeline_data:
        return jsonify({'status': 'error', 'error': '缺少数据'}), 400

    result = data_pipeline.push_to_pipeline(
        user_id=user_id,
        pipeline_key=pipeline_key,
        data=pipeline_data,
        title=title,
        metadata=metadata,
    )
    return jsonify(result)


@bp.route('/pipeline/consume', methods=['POST'])
def consume_pipeline():
    """消费流转数据（目标工具调用）"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    target_tool = data.get('target_tool', '')

    if not target_tool:
        return jsonify({'status': 'error', 'error': '缺少 target_tool'}), 400

    data_list = data_pipeline.consume_pipeline_data(user_id, target_tool)
    return jsonify({'status': 'success', 'data': data_list, 'count': len(data_list)})


@bp.route('/pipeline/peek', methods=['GET'])
def peek_pipeline():
    """查看待消费的流转数据（不标记）"""
    user_id, err = _require_login()
    if err:
        return err

    target_tool = request.args.get('target_tool', '')
    if not target_tool:
        return jsonify({'status': 'error', 'error': '缺少 target_tool'}), 400

    data_list = data_pipeline.peek_pipeline_data(user_id, target_tool)
    return jsonify({'status': 'success', 'data': data_list, 'count': len(data_list)})


@bp.route('/pipeline/history', methods=['GET'])
def pipeline_history():
    """获取流转历史"""
    user_id, err = _require_login()
    if err:
        return err

    limit = int(request.args.get('limit', 20))
    history = pipeline_db.list_pipeline_history(user_id, limit)
    return jsonify({'status': 'success', 'history': history})


@bp.route('/pipeline/<int:pipeline_id>/status', methods=['POST'])
def update_pipeline_status(pipeline_id):
    """更新流转状态"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    status = data.get('status', 'consumed')

    success = pipeline_db.update_pipeline_status(pipeline_id, status)
    return jsonify({'status': 'success' if success else 'error'})


@bp.route('/pipeline/full-workflow', methods=['POST'])
def execute_full_workflow():
    """执行完整工作流：CR → 趋势 → 邮件 → 任务"""
    user_id, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    cr_data = data.get('cr_data', {})
    trend_image = data.get('trend_image')

    if not cr_data:
        return jsonify({'status': 'error', 'error': '缺少 CR 数据'}), 400

    result = data_pipeline.execute_full_workflow(
        user_id=user_id,
        cr_data=cr_data,
        trend_image=trend_image,
    )
    return jsonify(result)
