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
        if snap:
            ctx.data['project_snapshot'] = snap
            ctx.data['project_key'] = project_key
            # 快照统计数据在 snap['stats'] 中
            st = snap.get('stats', {}) or {}
            summ = snap.get('summary', {}) or {}
            # 计算模块 PASS/FAIL 数量
            module_md = snap.get('module_md', '')
            fail_count = module_md.count('| FAIL |') + module_md.count('| ❌ |')
            pass_count = module_md.count('| PASS |') + module_md.count('| ✅ |')
            unresolved_bc_list = snap.get('unresolved_bc', [])
            return {
                'project': snap.get('project_name') or snap.get('name') or project_key,
                'total_cr': st.get('total', 0),
                'unresolved': st.get('unresolved', 0),
                'unresolved_bc': len(unresolved_bc_list) if isinstance(unresolved_bc_list, list) else st.get('unresolved_bc', 0),
                'fail_modules': fail_count,
                'pass_modules': pass_count,
                'risk_level': summ.get('risk_level', 'unknown')
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
        """发送邮件"""
        to = params.get('to', '')
        subject = params.get('subject', '')
        body = params.get('body', '') or ctx.data.get('last_report', '')
        if not to:
            return {'error': '未指定收件人'}
        # 调用邮件服务
        try:
            from services.email_service import send_email as _send
            result = _send(to=to, subject=subject, body=body)
            return {'sent': True, 'to': to, 'subject': subject}
        except Exception as e:
            return {'sent': False, 'error': str(e)}

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
