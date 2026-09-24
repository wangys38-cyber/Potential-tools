# -*- coding: utf-8 -*-
"""
Potential-tools 9.0 - Agent 工具注册
将平台内核心功能注册为 Agent 可调用的工具
"""
import logging
from services.agent_engine import Tool, tool_registry

logger = logging.getLogger(__name__)


def register_builtin_tools():
    """注册所有内置工具"""

    # ===== 项目助手工具 =====
    def _query_project_status(params, ctx):
        """查询项目状态"""
        from services.project_assistant import load_snapshot
        project_key = params.get('project_key', '')
        if not project_key or project_key == 'AUTO_DETECT':
            # 从上下文中获取项目 key
            project_key = ctx.data.get('project_key', '')
        if not project_key:
            return {'error': '未指定项目名称，请在任务中包含项目Key（如 EKSANTOS），或先在项目助手页面同步项目状态', 'available': True}
        snap = load_snapshot(project_key)
        # 如果快照不存在，尝试自动加 EK 前缀（用户常输入 SANTOS 而不是 EKSANTOS）
        if not snap and not project_key.startswith('EK'):
            try_key = 'EK' + project_key
            snap = load_snapshot(try_key)
            if snap:
                project_key = try_key
        if snap:
            ctx.data['project_snapshot'] = snap
            ctx.data['project_key'] = project_key
            # 快照统计数据在 snap['stats'] 中
            st = snap.get('stats', {}) or {}
            # 模块统计直接从 stats 读取
            fail_count = st.get('fail', 0)
            pass_count = st.get('pass', 0)
            bc_unresolved = st.get('bc_unresolved', 0)
            # 未解决 BC 列表
            unresolved_bc_list = snap.get('unresolved_bc', [])
            bc_count = len(unresolved_bc_list) if isinstance(unresolved_bc_list, list) else bc_unresolved
            # 估算风险等级（基于未解决BC数量，与报告生成逻辑一致）
            if bc_count >= 15:
                risk_level = 'High-risk'
            elif bc_count >= 5:
                risk_level = 'Mid-risk'
            else:
                risk_level = 'Low-risk'
            return {
                'project': snap.get('project_name') or snap.get('name') or project_key,
                'total_cr': st.get('total', 0),
                'unresolved': st.get('unresolved', 0),
                'unresolved_bc': bc_count,
                'fail_modules': fail_count,
                'pass_modules': pass_count,
                'risk_level': risk_level
            }
        return {'error': f'项目 {project_key} 的状态快照不存在，请先在「项目助手」页面同步该项目的CR数据'}

    tool_registry.register(Tool(
        name='query_project_status',
        description='查询项目的CR状态、未解决问题、模块风险等数据',
        parameters={
            'type': 'object',
            'properties': {
                'project_key': {'type': 'string', 'description': '项目Key，如 EKSANTOS'}
            },
            'required': ['project_key']
        },
        handler=_query_project_status,
        category='project'
    ))

    # ===== 生成报告工具 =====
    def _generate_report(params, ctx):
        """生成项目状态报告"""
        import traceback
        from services.project_assistant import generate_report_markdown
        snap = ctx.data.get('project_snapshot')
        if not snap:
            return {'error': '请先查询项目状态'}
        try:
            report = generate_report_markdown(snap)
            ctx.data['last_report'] = report
            return {'format': 'markdown', 'length': len(report), 'report': report, 'preview': report[:500]}
        except Exception as e:
            err_detail = f'{type(e).__name__}: {e}\n{traceback.format_exc()}'
            try:
                with open(r'D:\Potential-tools\data\agent_error.log', 'a', encoding='utf-8') as f:
                    f.write(f'=== generate_report 错误 ===\n{err_detail}\n\n')
            except Exception:
                pass
            return {'error': f'生成报告失败: {e}', 'detail': err_detail}

    tool_registry.register(Tool(
        name='generate_report',
        description='基于项目状态数据生成Markdown格式的状态报告',
        parameters={
            'type': 'object',
            'properties': {
                'format': {'type': 'string', 'enum': ['markdown', 'html'], 'default': 'markdown'}
            }
        },
        handler=_generate_report,
        category='project'
    ))

    # ===== 发送邮件工具（需要确认） =====
    def _send_email(params, ctx):
        """发送邮件（使用SMTP配置）"""
        to = params.get('to', '')
        subject = params.get('subject', '')
        body = params.get('body', '')
        # 处理 AUTO_DETECT 占位符
        if not to or to == 'AUTO_DETECT':
            return {'error': '未指定收件人，请在任务中明确收件人邮箱'}
        # body 为 AUTO_DETECT 或空时，使用上下文中的报告
        if not body or body == 'AUTO_DETECT':
            body = ctx.data.get('last_report', '')
        if not body:
            body = '（无正文内容）'
        # subject 为 AUTO_DETECT 或空时，自动生成主题
        if not subject or subject == 'AUTO_DETECT':
            from datetime import datetime
            project_name = ''
            snap = ctx.data.get('project_snapshot')
            if snap:
                project_name = snap.get('project_name') or snap.get('name') or ''
            today = datetime.now().strftime('%Y-%m-%d')
            if project_name:
                subject = f'{project_name} 项目状态日报 - {today}'
            else:
                subject = f'项目状态日报 - {today}'
        try:
            import smtplib
            import ssl
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            from db import get_config
            # 从系统配置获取SMTP
            cfg = get_config('smtp_mail_config') or {}
            smtp_host = cfg.get('smtp_host', '')
            smtp_port = int(cfg.get('smtp_port', 587))
            username = cfg.get('username', '')
            # 密码是base64编码保存的，需要解码
            import base64
            password_encoded = cfg.get('password', '')
            password = ''
            if password_encoded:
                try:
                    password = base64.b64decode(password_encoded).decode('utf-8')
                except Exception:
                    password = password_encoded  # 如果解码失败，可能是明文密码
            use_tls = cfg.get('use_tls', True)
            if not smtp_host or not username:
                return {'sent': False, 'error': 'SMTP未配置，请先在设置中配置邮箱'}
            if not password:
                return {'sent': False, 'error': 'SMTP密码未配置，请在设置中填写邮箱密码/授权码'}
            # 构建邮件（优化版：确保转发时格式稳定）
            import markdown as md_lib
            import re as _re_mail
            
            # 检测内容是否包含HTML表格
            _has_html_table = '<table' in body.lower()
            
            if _has_html_table:
                # 包含HTML表格时，不使用nl2br扩展（避免在HTML标签内添加<br>）
                html_body = md_lib.markdown(
                    body,
                    extensions=['tables', 'fenced_code', 'sane_lists'],
                    output_format='html5'
                )
            else:
                # 纯Markdown内容，使用nl2br扩展
                html_body = md_lib.markdown(
                    body,
                    extensions=['tables', 'fenced_code', 'nl2br', 'sane_lists'],
                    output_format='html5'
                )
            
            # 使用内联样式包裹内容，确保转发时样式不丢失
            html_content = f'''<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; font-size: 14px; line-height: 1.7; color: #1d1d1f; max-width: 800px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
{html_body}
</div>'''
            
            # 为HTML标签添加内联样式（确保转发时样式不丢失）
            # 只给没有style属性的标签添加内联样式（避免覆盖报告中已有的内联样式）
            # 使用负向先行断言，只匹配没有style属性的标签
            _style_map = [
                ('<table(?![^>]*style)', '<table style="border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; border: 1px solid #e0e0e0;"'),
                ('<th(?![^>]*style)', '<th style="border: 1px solid #e0e0e0; padding: 8px 12px; text-align: left; background-color: #f5f5f7; font-weight: 600;"'),
                ('<td(?![^>]*style)', '<td style="border: 1px solid #e0e0e0; padding: 8px 12px; text-align: left; vertical-align: top;"'),
                ('<h1(?![^>]*style)', '<h1 style="font-size: 22px; font-weight: 700; color: #1d1d1f; border-bottom: 2px solid #0071e3; padding-bottom: 8px; margin-top: 24px;"'),
                ('<h2(?![^>]*style)', '<h2 style="font-size: 18px; font-weight: 600; color: #1d1d1f; margin-top: 20px;"'),
                ('<h3(?![^>]*style)', '<h3 style="font-size: 16px; font-weight: 600; color: #1d1d1f; margin-top: 16px;"'),
                ('<p(?![^>]*style)', '<p style="margin: 8px 0;"'),
                ('<ul(?![^>]*style)', '<ul style="margin: 8px 0; padding-left: 24px;"'),
                ('<ol(?![^>]*style)', '<ol style="margin: 8px 0; padding-left: 24px;"'),
                ('<li(?![^>]*style)', '<li style="margin: 4px 0;"'),
            ]
            for _pattern, _replacement in _style_map:
                html_content = _re_mail.sub(_pattern, _replacement, html_content)
            # 使用 alternative 同时包含纯文本和HTML版本
            msg = MIMEMultipart('alternative')
            msg['From'] = username
            msg['To'] = to
            msg['Subject'] = subject or 'Potential Tools 通知'
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))
            # 智能选择连接方式：根据端口自动判断
            # 465端口 → SSL直接连接；587端口 → STARTTLS；其他按配置
            context = ssl.create_default_context()
            server = None
            try:
                if smtp_port == 465:
                    # 465端口使用SSL直接连接
                    server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30, context=context)
                elif smtp_port == 587:
                    # 587端口使用STARTTLS
                    server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                else:
                    # 其他端口按配置
                    if use_tls:
                        server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                        server.ehlo()
                        server.starttls(context=context)
                        server.ehlo()
                    else:
                        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30, context=context)
                server.login(username, password)
                server.sendmail(username, [to], msg.as_string())
                return {'sent': True, 'to': to, 'subject': subject}
            finally:
                if server:
                    try:
                        server.quit()
                    except Exception:
                        pass
        except Exception as e:
            err_msg = str(e)
            # 友好的错误提示
            if 'WRONG_VERSION_NUMBER' in err_msg or 'wrong version' in err_msg.lower():
                err_msg = 'SSL/TLS版本不匹配，请检查SMTP端口（465用SSL，587用STARTTLS）和加密设置'
            elif 'authentication' in err_msg.lower() or '535' in err_msg:
                err_msg = '邮箱认证失败，请检查用户名和密码/授权码'
            elif 'timed out' in err_msg.lower() or 'timeout' in err_msg.lower():
                err_msg = '连接SMTP服务器超时，请检查服务器地址和端口'
            return {'sent': False, 'error': f'邮件发送失败: {err_msg}'}

    tool_registry.register(Tool(
        name='send_email',
        description='发送邮件给指定收件人，支持发送状态报告',
        parameters={
            'type': 'object',
            'properties': {
                'to': {'type': 'string', 'description': '收件人邮箱'},
                'subject': {'type': 'string', 'description': '邮件主题'},
                'body': {'type': 'string', 'description': '邮件正文，默认为上次生成的报告'}
            },
            'required': ['to']
        },
        handler=_send_email,
        requires_confirmation=True,  # 发送邮件需要用户确认
        category='communication'
    ))

    # ===== 创建笔记工具 =====
    def _create_note(params, ctx):
        """创建牛马笔记"""
        title = params.get('title', '未命名笔记')
        content = params.get('content', '') or ctx.data.get('last_report', '')
        try:
            from services.notes_service import create_note as _create
            note = _create(title=title, content=content)
            return {'created': True, 'id': note.get('id'), 'title': title}
        except Exception as e:
            return {'created': False, 'error': str(e)}

    tool_registry.register(Tool(
        name='create_note',
        description='创建牛马笔记，可将项目状态报告同步到笔记',
        parameters={
            'type': 'object',
            'properties': {
                'title': {'type': 'string', 'description': '笔记标题'},
                'content': {'type': 'string', 'description': '笔记内容，默认为上次生成的报告'}
            }
        },
        handler=_create_note,
        category='notes'
    ))

    # ===== 知识库搜索工具 =====
    def _knowledge_search(params, ctx):
        """在知识库中搜索"""
        query = params.get('query', '')
        if not query:
            return {'error': '未指定搜索关键词'}
        try:
            from services.knowledge_base_service import search as _kb_search
            results = _kb_search(query, top_k=5)
            ctx.data['last_search_results'] = results
            return {'query': query, 'results_count': len(results), 'results': results[:3]}
        except Exception as e:
            return {'error': str(e)}

    tool_registry.register(Tool(
        name='knowledge_search',
        description='在智能知识库中搜索相关文档和信息',
        parameters={
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': '搜索关键词'}
            },
            'required': ['query']
        },
        handler=_knowledge_search,
        category='knowledge'
    ))

    logger.info(f"Agent内置工具注册完成，共 {len(tool_registry.list_tools())} 个工具")


# 自动注册
register_builtin_tools()
