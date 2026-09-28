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
            
            # 构建项目风险评估部分（基于项目快照数据）
            _risk_assessment_md = ''
            _snap = ctx.data.get('project_snapshot')
            if _snap:
                # 从项目快照中提取关键指标
                _total_cr = _snap.get('total_cr', 0) or _snap.get('cr_total', 0) or 0
                _open_cr = _snap.get('open_cr', 0) or _snap.get('unresolved_cr', 0) or 0
                _blocker_count = _snap.get('blocker_count', 0) or _snap.get('blocker', 0) or 0
                _critical_count = _snap.get('critical_count', 0) or _snap.get('critical', 0) or 0
                _fail_modules = _snap.get('fail_modules', 0) or _snap.get('fail_count', 0) or 0
                _pass_modules = _snap.get('pass_modules', 0) or _snap.get('pass_count', 0) or 0
                _total_modules = _fail_modules + _pass_modules
                
                # 风险等级判断逻辑
                _risk_level = '低'
                _risk_color = '#22c55e'
                _risk_desc = '项目整体健康，风险可控'
                _risk_factors = []
                
                # 判断依据1：Blocker数量
                if _blocker_count >= 5:
                    _risk_factors.append(f'存在 {_blocker_count} 个 Blocker 级缺陷，严重阻塞项目进度')
                elif _blocker_count >= 2:
                    _risk_factors.append(f'存在 {_blocker_count} 个 Blocker 级缺陷，需重点关注')
                elif _blocker_count > 0:
                    _risk_factors.append(f'存在 {_blocker_count} 个 Blocker 级缺陷，建议及时处理')
                
                # 判断依据2：Critical数量
                if _critical_count >= 10:
                    _risk_factors.append(f'存在 {_critical_count} 个 Critical 级缺陷，质量风险较高')
                elif _critical_count >= 5:
                    _risk_factors.append(f'存在 {_critical_count} 个 Critical 级缺陷，需持续跟踪')
                
                # 判断依据3：失败模块比例
                if _total_modules > 0:
                    _fail_rate = (_fail_modules / _total_modules) * 100
                    if _fail_rate >= 50:
                        _risk_factors.append(f'{_fail_modules}/{_total_modules} 个模块未通过（{_fail_rate:.0f}%），整体质量堪忧')
                    elif _fail_rate >= 30:
                        _risk_factors.append(f'{_fail_modules}/{_total_modules} 个模块未通过（{_fail_rate:.0f}%），存在一定质量风险')
                
                # 判断依据4：未解决CR占比
                if _total_cr > 0:
                    _open_rate = (_open_cr / _total_cr) * 100
                    if _open_rate >= 50:
                        _risk_factors.append(f'未解决 CR 占比 {_open_rate:.0f}%（{_open_cr}/{_total_cr}），修复压力较大')
                
                # 综合风险等级判断
                if _blocker_count >= 5 or _critical_count >= 10 or (_total_modules > 0 and _fail_modules / _total_modules >= 0.5):
                    _risk_level = '高'
                    _risk_color = '#ef4444'
                    _risk_desc = '项目存在严重风险，需立即采取措施'
                elif _blocker_count >= 2 or _critical_count >= 5 or (_total_modules > 0 and _fail_modules / _total_modules >= 0.3):
                    _risk_level = '中'
                    _risk_color = '#f59e0b'
                    _risk_desc = '项目存在一定风险，需重点关注并及时处理'
                
                # 构建风险评估Markdown
                if _risk_factors:
                    _risk_assessment_md = f'''
## 📊 项目风险综合评估

**风险等级：{_risk_level}** （{_risk_desc}）

### 风险判断依据

'''
                    for i, factor in enumerate(_risk_factors, 1):
                        _risk_assessment_md += f'{i}. {factor}\n'
                    
                    _risk_assessment_md += f'''
### 关键指标概览

| 指标 | 数值 | 状态 |
|------|------|------|
| CR 总数 | {_total_cr} | - |
| 未解决 CR | {_open_cr} | {"⚠️ 偏高" if _total_cr > 0 and _open_cr / _total_cr >= 0.3 else "✅ 正常"} |
| Blocker 缺陷 | {_blocker_count} | {"🔴 严重" if _blocker_count >= 5 else "🟡 关注" if _blocker_count >= 2 else "✅ 正常"} |
| Critical 缺陷 | {_critical_count} | {"🔴 严重" if _critical_count >= 10 else "🟡 关注" if _critical_count >= 5 else "✅ 正常"} |
| 通过模块 | {_pass_modules}/{_total_modules} | {"✅ 良好" if _total_modules > 0 and _pass_modules / _total_modules >= 0.7 else "🟡 一般" if _total_modules > 0 and _pass_modules / _total_modules >= 0.5 else "🔴 较差"} |

### 综合评估与建议

'''
                    if _risk_level == '高':
                        _risk_assessment_md += '''- **立即行动**：优先解决所有 Blocker 级缺陷，确保关键路径畅通
- **资源倾斜**：增加测试和开发资源，集中处理高优先级问题
- **每日跟进**：建立每日风险跟进机制，及时同步进展和阻塞点
- **风险上报**：将高风险项上报至项目管理层，争取支持和资源
'''
                    elif _risk_level == '中':
                        _risk_assessment_md += '''- **重点关注**：持续跟踪 Blocker 和 Critical 级缺陷的修复进度
- **定期复盘**：每周进行质量复盘，识别趋势和潜在风险
- **优化流程**：分析问题根因，优化开发和测试流程，预防同类问题
- **资源协调**：根据模块风险情况，合理调配测试和开发资源
'''
                    else:
                        _risk_assessment_md += '''- **保持现状**：继续保持良好的质量管控流程
- **持续优化**：关注长尾问题，持续提升产品质量
- **经验沉淀**：总结优秀实践，形成可复用的质量保障机制
- **预防为主**：加强前期设计评审和代码审查，预防问题引入
'''
                    _risk_assessment_md += '\n---\n'
            
            # 将风险评估插入到报告内容之后（如果有风险评估）
            if _risk_assessment_md:
                body = body + '\n' + _risk_assessment_md
            
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
            
            # 构建专业的邮件HTML模板（美化版）
            from datetime import datetime
            _today = datetime.now().strftime('%Y年%m月%d日')
            _project_name = ''
            _snap = ctx.data.get('project_snapshot')
            if _snap:
                _project_name = _snap.get('project_name') or _snap.get('name') or ''
            
            # 构建邮件头部
            _email_header = f'''
<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 28px 32px; border-radius: 12px 12px 0 0; color: #ffffff;">
  <div style="font-size: 12px; opacity: 0.85; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 8px;">Potential Tools · 项目状态报告</div>
  <div style="font-size: 24px; font-weight: 700; margin-bottom: 6px;">{_project_name or '项目状态日报'}</div>
  <div style="font-size: 13px; opacity: 0.9;">{_today} · 自动生成</div>
</div>'''
            
            # 构建邮件尾部
            _email_footer = '''
<div style="background-color: #f8f9fa; padding: 20px 32px; border-radius: 0 0 12px 12px; border-top: 1px solid #e9ecef;">
  <div style="font-size: 12px; color: #6c757d; line-height: 1.6;">
    <div style="margin-bottom: 6px; font-weight: 600; color: #495057;">关于本报告</div>
    <div>本报告由 Potential Tools AI Agent 自动生成，数据来源于项目管理系统实时同步。</div>
    <div style="margin-top: 8px;">如有疑问，请联系项目团队或回复本邮件。</div>
  </div>
  <div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid #e9ecef; font-size: 11px; color: #adb5bd; text-align: center;">
    Potential Tools v9.0 · 让研发更高效 · 本邮件由系统自动发送，请勿直接回复
  </div>
</div>'''
            
            # 组合完整的邮件内容
            html_content = f'''<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; font-size: 14px; line-height: 1.7; color: #1d1d1f; max-width: 800px; margin: 0 auto; padding: 20px; background-color: #f5f5f7;">
  <div style="background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); overflow: hidden;">
    {_email_header}
    <div style="padding: 28px 32px;">
{html_body}
    </div>
    {_email_footer}
  </div>
</div>'''
            
            # 为HTML标签添加内联样式（确保转发时样式不丢失）
            # 只给没有style属性的标签添加内联样式（避免覆盖报告中已有的内联样式）
            # 使用负向先行断言，只匹配没有style属性的标签
            _style_map = [
                # 表格样式：更现代、更专业
                ('<table(?![^>]*style)', '<table style="border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 13px; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08);"'),
                ('<thead(?![^>]*style)', '<thead style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);"'),
                ('<th(?![^>]*style)', '<th style="border: none; padding: 12px 14px; text-align: left; color: #ffffff; font-weight: 600; font-size: 12px; letter-spacing: 0.5px; text-transform: uppercase;"'),
                ('<td(?![^>]*style)', '<td style="border: 1px solid #f0f0f0; padding: 10px 14px; text-align: left; vertical-align: top; color: #333333;"'),
                ('<tr(?![^>]*style)', '<tr style="transition: background-color 0.2s;"'),
                # 标题样式：更有层次
                ('<h1(?![^>]*style)', '<h1 style="font-size: 22px; font-weight: 700; color: #1d1d1f; border-left: 4px solid #667eea; padding-left: 12px; margin-top: 28px; margin-bottom: 16px; line-height: 1.3;"'),
                ('<h2(?![^>]*style)', '<h2 style="font-size: 18px; font-weight: 600; color: #2d3748; margin-top: 24px; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 2px solid #e2e8f0;"'),
                ('<h3(?![^>]*style)', '<h3 style="font-size: 16px; font-weight: 600; color: #4a5568; margin-top: 20px; margin-bottom: 10px;"'),
                # 段落和列表样式
                ('<p(?![^>]*style)', '<p style="margin: 10px 0; color: #4a5568; line-height: 1.7;"'),
                ('<ul(?![^>]*style)', '<ul style="margin: 10px 0; padding-left: 24px; color: #4a5568;"'),
                ('<ol(?![^>]*style)', '<ol style="margin: 10px 0; padding-left: 24px; color: #4a5568;"'),
                ('<li(?![^>]*style)', '<li style="margin: 6px 0; line-height: 1.6;"'),
                # 强调文本样式
                ('<strong(?![^>]*style)', '<strong style="color: #2d3748; font-weight: 600;"'),
                ('<em(?![^>]*style)', '<em style="color: #667eea; font-style: italic;"'),
                # 引用块样式
                ('<blockquote(?![^>]*style)', '<blockquote style="margin: 16px 0; padding: 12px 20px; background-color: #f7fafc; border-left: 4px solid #667eea; color: #4a5568; border-radius: 0 8px 8px 0;"'),
                # 代码块样式
                ('<code(?![^>]*style)', '<code style="background-color: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 12px; color: #e53e3e; font-family: Monaco, Consolas, monospace;"'),
                ('<pre(?![^>]*style)', '<pre style="background-color: #1a202c; color: #e2e8f0; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 12px; line-height: 1.6;"'),
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
