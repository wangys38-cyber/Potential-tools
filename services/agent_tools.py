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
        from services.project_assistant import generate_report_markdown
        snap = ctx.data.get('project_snapshot')
        if not snap:
            return {'error': '请先查询项目状态'}
        report = generate_report_markdown(snap)
        ctx.data['last_report'] = report
        return {'format': 'markdown', 'length': len(report), 'preview': report[:500]}

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
        body = params.get('body', '') or ctx.data.get('last_report', '')
        if not to or to == 'AUTO_DETECT':
            return {'error': '未指定收件人，请在任务中明确收件人邮箱'}
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            from db import get_config
            # 从系统配置获取SMTP
            cfg = get_config('smtp_mail_config') or {}
            smtp_host = cfg.get('smtp_host', '')
            smtp_port = int(cfg.get('smtp_port', 587))
            username = cfg.get('username', '')
            password = cfg.get('password', '')
            use_tls = cfg.get('use_tls', True)
            if not smtp_host or not username:
                return {'sent': False, 'error': 'SMTP未配置，请先在设置中配置邮箱'}
            # 构建邮件
            msg = MIMEMultipart()
            msg['From'] = username
            msg['To'] = to
            msg['Subject'] = subject or 'Potential Tools 通知'
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            # 发送
            if use_tls:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
            server.login(username, password)
            server.sendmail(username, [to], msg.as_string())
            server.quit()
            return {'sent': True, 'to': to, 'subject': subject}
        except Exception as e:
            return {'sent': False, 'error': f'邮件发送失败: {str(e)}'}

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
