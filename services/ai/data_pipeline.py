"""
跨工具数据管道服务 v8.0
实现 CR分析 → 趋势看板 → 邮件 → 任务 的完整工作流
"""
import time
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 定义可用的工作流
PIPELINES = {
    'cr_to_trend': {
        'name': 'CR 分析 → 趋势看板',
        'description': '将 CR 分析结果导入趋势看板，自动生成趋势图表',
        'source': 'excel-analysis',
        'target': 'bug-trend',
        'icon': '📊',
    },
    'cr_to_email': {
        'name': 'CR 分析 → 邮件助手',
        'description': '将 CR 分析结果和趋势图一键生成邮件',
        'source': 'excel-analysis',
        'target': 'email-assistant',
        'icon': '📧',
    },
    'cr_to_task': {
        'name': 'CR 分析 → 任务管理',
        'description': '将未解决 Bug 自动创建为修复任务',
        'source': 'excel-analysis',
        'target': 'task-manager',
        'icon': '✅',
    },
    'trend_to_email': {
        'name': '趋势看板 → 邮件助手',
        'description': '将趋势看板数据和图表生成邮件报告',
        'source': 'bug-trend',
        'target': 'email-assistant',
        'icon': '📈',
    },
    'cr_full_workflow': {
        'name': 'CR 分析完整工作流',
        'description': 'CR分析 → 趋势看板 → 邮件 → 任务，一键完成',
        'source': 'excel-analysis',
        'target': 'multi',
        'icon': '🔄',
        'steps': ['cr_to_trend', 'cr_to_email', 'cr_to_task'],
    },
}


def get_available_pipelines() -> List[Dict]:
    """获取所有可用的工作流定义"""
    return [{'key': k, **v} for k, v in PIPELINES.items()]


def push_to_pipeline(user_id: int, pipeline_key: str, data: Dict,
                     title: str = '', metadata: Dict = None) -> Dict:
    """
    将数据推送到指定的工作流管道
    """
    from db import pipeline as pipeline_db

    pipeline = PIPELINES.get(pipeline_key)
    if not pipeline:
        return {'status': 'error', 'error': f'未知的工作流: {pipeline_key}'}

    # 如果是多步骤工作流，分别推送到每个步骤
    if pipeline.get('steps'):
        results = []
        for step_key in pipeline['steps']:
            step = PIPELINES.get(step_key)
            if step:
                pipeline_id = pipeline_db.save_pipeline_data(
                    user_id=user_id,
                    pipeline_key=step_key,
                    source_tool=step['source'],
                    target_tool=step['target'],
                    data_type='workflow_data',
                    title=title or step['name'],
                    data_content=data,
                    metadata=metadata or {},
                )
                results.append({'pipeline_key': step_key, 'pipeline_id': pipeline_id})
        return {'status': 'success', 'pipeline_id': 0, 'steps': results}

    # 单步骤工作流
    # 对于特定工作流，先进行数据转换
    processed_data = data
    if pipeline_key == 'cr_to_email':
        # CR → 邮件：自动生成邮件内容
        trend_image = data.get('trend_image')
        email_result = transform_cr_to_email(data, trend_image)
        processed_data = {
            'subject': email_result['subject'],
            'body': email_result['body'],
            'body_text': email_result['body_text'],
            'is_html': True,
            'recipients': email_result.get('recipients', []),
            'source_data': {
                'issues_count': len(data.get('issues') or []),
                'has_ai_analysis': bool(data.get('aiAnalysis') and data['aiAnalysis'].get('full_analysis')),
            }
        }

    pipeline_id = pipeline_db.save_pipeline_data(
        user_id=user_id,
        pipeline_key=pipeline_key,
        source_tool=pipeline['source'],
        target_tool=pipeline['target'],
        data_type='workflow_data',
        title=title or pipeline['name'],
        data_content=processed_data,
        metadata=metadata or {},
    )

    return {
        'status': 'success',
        'pipeline_id': pipeline_id,
        'pipeline_key': pipeline_key,
        'target_tool': pipeline['target'],
        'message': f'数据已推送到 {pipeline["name"]}',
    }


def consume_pipeline_data(user_id: int, target_tool: str) -> List[Dict]:
    """
    目标工具消费流转数据（获取并标记为已消费）
    """
    from db import pipeline as pipeline_db

    data_list = pipeline_db.get_pipeline_data(
        user_id=user_id,
        target_tool=target_tool,
        status='pending',
        limit=5,
    )

    # 标记为已消费
    for item in data_list:
        pipeline_db.update_pipeline_status(item['id'], 'consumed')

    return data_list


def peek_pipeline_data(user_id: int, target_tool: str) -> List[Dict]:
    """
    查看待消费的流转数据（不标记）
    """
    from db import pipeline as pipeline_db

    return pipeline_db.get_pipeline_data(
        user_id=user_id,
        target_tool=target_tool,
        status='pending',
        limit=5,
    )


# ==================== 数据转换函数 ====================

def transform_cr_to_trend(cr_data: Dict) -> Dict:
    """
    将 CR 分析数据转换为趋势看板格式
    """
    issues = cr_data.get('issues') or cr_data.get('bugs') or []
    daily_trend = cr_data.get('dailyTrend') or cr_data.get('daily_data') or []

    # 提取模块统计
    module_stats = {}
    for issue in issues:
        module = issue.get('module') or issue.get('模块') or '未知'
        if module not in module_stats:
            module_stats[module] = {'total': 0, 'unresolved': 0, 'critical': 0}
        module_stats[module]['total'] += 1
        status = (issue.get('status') or '').lower()
        if not any(k in status for k in ('resolved', 'closed', 'done', '已解决', '已关闭')):
            module_stats[module]['unresolved'] += 1
        severity = (issue.get('severity') or '').lower()
        if 'critical' in severity or '致命' in severity:
            module_stats[module]['critical'] += 1

    return {
        'source': 'cr-analysis',
        'issues': issues,
        'daily_trend': daily_trend,
        'module_stats': module_stats,
        'summary': {
            'total': len(issues),
            'unresolved': sum(1 for i in issues if not any(k in (i.get('status') or '').lower() for k in ('resolved', 'closed', 'done', '已解决', '已关闭'))),
            'modules': len(module_stats),
        },
        'imported_at': time.time(),
    }


def transform_cr_to_email(cr_data: Dict, trend_image: str = None) -> Dict:
    """
    将 CR 分析数据转换为邮件内容
    """
    issues = cr_data.get('issues') or []
    daily_trend = cr_data.get('dailyTrend') or []
    ai_analysis = cr_data.get('aiAnalysis') or {}
    module_stats = cr_data.get('moduleStats') or cr_data.get('module_stats') or {}

    # 统计
    total = len(issues)
    # 已解决状态关键词（与后端 excel_analyzers.py 保持一致）
    resolved_keywords = ('resolved', 'fixed', 'closed', 'done', '已解决', '已关闭')
    unresolved_list = [i for i in issues if not any(k in (i.get('status') or '').lower() for k in resolved_keywords)]
    resolved_list = [i for i in issues if i not in unresolved_list]
    
    # 严重程度分布
    blocker = [i for i in issues if 'blocker' in (i.get('severity') or '').lower() or '阻塞' in (i.get('severity') or '')]
    critical = [i for i in issues if 'critical' in (i.get('severity') or '').lower() or '严重' in (i.get('severity') or '')]
    major = [i for i in issues if 'major' in (i.get('severity') or '').lower() or '重要' in (i.get('severity') or '')]
    minor = [i for i in issues if 'minor' in (i.get('severity') or '').lower() or '次要' in (i.get('severity') or '')]
    trivial = [i for i in issues if 'trivial' in (i.get('severity') or '').lower() or '微不足道' in (i.get('severity') or '')]
    
    resolved_count = len(resolved_list)
    resolution_rate = f"{resolved_count/total*100:.1f}%" if total > 0 else "0%"
    bc_resolved = len([i for i in (blocker + critical) if i in resolved_list])
    bc_total = len(blocker) + len(critical)
    bc_rate = f"{bc_resolved/bc_total*100:.1f}%" if bc_total > 0 else "0%"

    # 计算周维度统计（直接从 issues 的 create_date/resolved_date 计算）
    weekly_stats = []
    try:
        import logging
        logging.info(f"[WeeklyStats] issues count: {len(issues)}")
        if issues:
            logging.info(f"[WeeklyStats] first issue keys: {list(issues[0].keys())}")
            logging.info(f"[WeeklyStats] first issue create_date: {issues[0].get('create_date', 'MISSING')}")
        
        from collections import defaultdict
        from datetime import datetime as dt
        weekly_data = defaultdict(lambda: {'new': 0, 'resolved': 0})
        
        # 日期解析：支持 "06/Sep/26 8:56 PM" 格式
        def parse_date(date_str):
            if not date_str:
                return None
            date_str = str(date_str).strip()
            # 尝试多种格式
            formats = ['%d/%b/%y %I:%M %p', '%d/%b/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']
            for fmt in formats:
                try:
                    return dt.strptime(date_str, fmt)
                except:
                    continue
            return None
        
        for issue in issues:
            # 新增：create_date（兼容多种字段名）
            create_date_str = (issue.get('create_date') or issue.get('created') or 
                              issue.get('created_date') or issue.get('Created') or 
                              issue.get('createTime') or '')
            create_d = parse_date(create_date_str)
            if create_d:
                week_num = create_d.isocalendar()[1]
                year = create_d.isocalendar()[0]
                week_key = f"{year}年第{week_num}周"
                weekly_data[week_key]['new'] += 1
            
            # 解决：resolved_date（兼容多种字段名）
            resolved_date_str = (issue.get('resolved_date') or issue.get('resolved') or 
                                issue.get('resolved_time') or issue.get('Resolved') or 
                                issue.get('closed_date') or '')
            resolved_d = parse_date(resolved_date_str)
            if resolved_d:
                week_num = resolved_d.isocalendar()[1]
                year = resolved_d.isocalendar()[0]
                week_key = f"{year}年第{week_num}周"
                weekly_data[week_key]['resolved'] += 1
        
        logging.info(f"[WeeklyStats] weekly_data keys: {list(weekly_data.keys())}")
        
        cumulative = 0
        for week_key in sorted(weekly_data.keys()):
            w = weekly_data[week_key]
            net = w['new'] - w['resolved']
            cumulative += net
            weekly_stats.append({
                'week': week_key,
                'new': w['new'],
                'resolved': w['resolved'],
                'net': net,
                'cumulative': cumulative,
            })
        weekly_stats = weekly_stats[-12:]
    except Exception as e:
        import logging
        logging.warning(f"计算周维度统计失败: {e}")

    # 生成周维度图表（Bug增长vs解决 + 累计未解决趋势）
    weekly_chart_image = None
    cumulative_chart_image = None
    if weekly_stats and len(weekly_stats) > 1:
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import base64
            from io import BytesIO
            
            # 设置中文字体
            plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            
            weeks = [w['week'].replace('2026年第', '第').replace('周', '周') for w in weekly_stats]
            new_counts = [w['new'] for w in weekly_stats]
            resolved_counts = [w['resolved'] for w in weekly_stats]
            cumulative_counts = [w['cumulative'] for w in weekly_stats]
            
            # 图1: Bug 增长 vs 解决曲线
            fig, ax = plt.subplots(figsize=(10, 4), dpi=100)
            ax.plot(range(len(weeks)), new_counts, 'o-', color='#ff3b30', linewidth=2, markersize=5, label='新增')
            ax.plot(range(len(weeks)), resolved_counts, 's--', color='#34c759', linewidth=2, markersize=5, label='解决')
            ax.fill_between(range(len(weeks)), new_counts, alpha=0.1, color='#ff3b30')
            # 数据点数值标签
            for i, v in enumerate(new_counts):
                ax.annotate(str(v), (i, v), textcoords="offset points", xytext=(0, 8), ha='center', fontsize=7, color='#ff3b30')
            for i, v in enumerate(resolved_counts):
                ax.annotate(str(v), (i, v), textcoords="offset points", xytext=(0, -12), ha='center', fontsize=7, color='#34c759')
            ax.set_xticks(range(len(weeks)))
            ax.set_xticklabels(weeks, rotation=45, ha='right', fontsize=8)
            ax.set_ylabel('Bug 数量', fontsize=10)
            ax.set_title('Bug 增长 vs 解决曲线', fontsize=12, fontweight='bold')
            ax.legend(fontsize=9)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            buf = BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight', facecolor='white')
            buf.seek(0)
            weekly_chart_image = 'data:image/png;base64,' + base64.b64encode(buf.read()).decode()
            plt.close()
            
            # 图2: 累计未解决 Bug 趋势
            fig, ax = plt.subplots(figsize=(10, 3.5), dpi=100)
            ax.fill_between(range(len(weeks)), cumulative_counts, alpha=0.3, color='#007aff')
            ax.plot(range(len(weeks)), cumulative_counts, 'o-', color='#007aff', linewidth=2, markersize=5)
            # 数据点数值标签
            for i, v in enumerate(cumulative_counts):
                ax.annotate(str(v), (i, v), textcoords="offset points", xytext=(0, 8), ha='center', fontsize=7, color='#007aff')
            ax.set_xticks(range(len(weeks)))
            ax.set_xticklabels(weeks, rotation=45, ha='right', fontsize=8)
            ax.set_ylabel('未解决数', fontsize=10)
            ax.set_title('累计未解决 Bug 趋势', fontsize=12, fontweight='bold')
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            buf = BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight', facecolor='white')
            buf.seek(0)
            cumulative_chart_image = 'data:image/png;base64,' + base64.b64encode(buf.read()).decode()
            plt.close()
        except Exception as e:
            logging.warning(f"生成周维度图表失败: {e}")

    # 构建邮件主题
    today = datetime.now().strftime('%Y-%m-%d')
    subject = f'CR 分析日报 - {today}（共{total}个，未解决{len(unresolved_list)}个，解决率{resolution_rate}）'

    # 构建邮件正文
    body = f'''<div style="font-family: sans-serif; max-width: 700px; margin: 0 auto;">
<h2 style="color: #1d1d1f;">CR 问题分析报告</h2>
<p style="color: #86868b; font-size: 13px;">生成时间: {today}</p>

<h3 style="color: #1d1d1f; margin-top: 20px;">📊 概览</h3>
<table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
<tr>
<td style="padding: 8px 6px; background: #f5f5f7; border-radius: 6px; text-align: center;">
<div style="font-size: 18px; font-weight: 600; color: #1d1d1f;">{total}</div>
<div style="font-size: 11px; color: #86868b;">问题总数</div>
</td>
<td style="padding: 8px 6px; background: #d4edda; border-radius: 6px; text-align: center;">
<div style="font-size: 18px; font-weight: 600; color: #155724;">{resolved_count}</div>
<div style="font-size: 11px; color: #155724;">已解决</div>
</td>
<td style="padding: 8px 6px; background: #fff3cd; border-radius: 6px; text-align: center;">
<div style="font-size: 18px; font-weight: 600; color: #856404;">{len(unresolved_list)}</div>
<div style="font-size: 11px; color: #856404;">未解决</div>
</td>
<td style="padding: 8px 6px; background: #f5f5f7; border-radius: 6px; text-align: center;">
<div style="font-size: 18px; font-weight: 600; color: #1d1d1f;">{resolution_rate}</div>
<div style="font-size: 11px; color: #86868b;">解决率</div>
</td>
</tr>
</table>

<h3 style="color: #1d1d1f;">⚠️ 严重程度分布</h3>
<table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
<tr>
<td style="padding: 6px 4px; background: #f8d7da; border-radius: 6px; text-align: center;">
<div style="font-size: 16px; font-weight: 600; color: #721c24;">{len(blocker)}</div>
<div style="font-size: 10px; color: #721c24;">Blocker</div>
</td>
<td style="padding: 6px 4px; background: #f8d7da; border-radius: 6px; text-align: center;">
<div style="font-size: 16px; font-weight: 600; color: #721c24;">{len(critical)}</div>
<div style="font-size: 10px; color: #721c24;">Critical</div>
</td>
<td style="padding: 6px 4px; background: #fff3cd; border-radius: 6px; text-align: center;">
<div style="font-size: 16px; font-weight: 600; color: #856404;">{len(major)}</div>
<div style="font-size: 10px; color: #856404;">Major</div>
</td>
<td style="padding: 6px 4px; background: #d4edda; border-radius: 6px; text-align: center;">
<div style="font-size: 16px; font-weight: 600; color: #155724;">{len(minor)}</div>
<div style="font-size: 10px; color: #155724;">Minor</div>
</td>
<td style="padding: 6px 4px; background: #d4edda; border-radius: 6px; text-align: center;">
<div style="font-size: 16px; font-weight: 600; color: #155724;">{len(trivial)}</div>
<div style="font-size: 10px; color: #155724;">Trivial</div>
</td>
</tr>
</table>
<p style="font-size: 12px; color: #86868b; margin-bottom: 20px;">B+C 解决率: {bc_rate}（{bc_resolved}/{bc_total}）</p>
'''

    # 模块问题分布（Top 10）
    if module_stats or issues:
        # 转换为列表并排序
        modules = []
        if isinstance(module_stats, dict):
            for name, stats in module_stats.items():
                if isinstance(stats, dict):
                    modules.append({
                        'name': name,
                        'total': stats.get('total', 0),
                        'unresolved': stats.get('unresolved', 0),
                    })
        elif isinstance(module_stats, list):
            modules = module_stats
        
        # 从 issues 数据中计算每个模块的未解决 blocker+critical 数量
        if issues and modules:
            from collections import defaultdict
            mod_bc = defaultdict(int)
            for issue in issues:
                mod = issue.get('module', '')
                sev = (issue.get('severity') or '').lower()
                status = (issue.get('status') or '').lower()
                resolved_keywords = ['resolved', 'fixed', 'closed', 'done', '已解决', '已关闭']
                is_resolved = any(kw in status for kw in resolved_keywords)
                if mod and ('blocker' in sev or 'critical' in sev) and not is_resolved:
                    mod_bc[mod] += 1
            for m in modules:
                m['critical'] = mod_bc.get(m['name'], 0)
        
        if modules:
            modules.sort(key=lambda x: x.get('total', 0), reverse=True)
            body += '<h3 style="color: #1d1d1f;">📦 模块问题分布（Top 10）</h3>'
            body += '<table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 13px;">'
            body += '<thead><tr style="background: #f5f5f7;">'
            body += '<th style="padding: 8px 12px; text-align: left; color: #86868b;">模块</th>'
            body += '<th style="padding: 8px 12px; text-align: center; color: #86868b;">总数</th>'
            body += '<th style="padding: 8px 12px; text-align: center; color: #86868b;">未解决</th>'
            body += '<th style="padding: 8px 12px; text-align: center; color: #86868b;">致命/严重</th>'
            body += '</tr></thead><tbody>'
            for m in modules[:10]:
                body += '<tr style="border-bottom: 1px solid #e5e5ea;">'
                body += f'<td style="padding: 8px 12px; color: #1d1d1f;">{m["name"]}</td>'
                body += f'<td style="padding: 8px 12px; text-align: center; color: #1d1d1f;">{m["total"]}</td>'
                body += f'<td style="padding: 8px 12px; text-align: center; color: #ff9500;">{m["unresolved"]}</td>'
                body += f'<td style="padding: 8px 12px; text-align: center; color: #ff3b30;">{m["critical"]}</td>'
                body += '</tr>'
            body += '</tbody></table>'

    # 每周对比表
    if weekly_stats:
        body += '<h3 style="color: #1d1d1f;">📅 每周对比表（近12周）</h3>'
        body += '<table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 13px;">'
        body += '<thead><tr style="background: #f5f5f7;">'
        body += '<th style="padding: 8px 12px; text-align: left; color: #86868b;">周</th>'
        body += '<th style="padding: 8px 12px; text-align: center; color: #86868b;">新增</th>'
        body += '<th style="padding: 8px 12px; text-align: center; color: #86868b;">解决</th>'
        body += '<th style="padding: 8px 12px; text-align: center; color: #86868b;">净增</th>'
        body += '<th style="padding: 8px 12px; text-align: center; color: #86868b;">累计未解决</th>'
        body += '</tr></thead><tbody>'
        for w in weekly_stats:
            net_color = '#ff3b30' if w['net'] > 0 else '#34c759'
            net_sign = '+' if w['net'] > 0 else ''
            body += '<tr style="border-bottom: 1px solid #e5e5ea;">'
            body += f'<td style="padding: 8px 12px; color: #1d1d1f;">{w["week"]}</td>'
            body += f'<td style="padding: 8px 12px; text-align: center; color: #1d1d1f;">{w["new"]}</td>'
            body += f'<td style="padding: 8px 12px; text-align: center; color: #1d1d1f;">{w["resolved"]}</td>'
            body += f'<td style="padding: 8px 12px; text-align: center; color: {net_color}; font-weight: 600;">{net_sign}{w["net"]}</td>'
            body += f'<td style="padding: 8px 12px; text-align: center; color: #1d1d1f; font-weight: 600;">{w["cumulative"]}</td>'
            body += '</tr>'
        body += '</tbody></table>'

    # 周维度图表（Bug增长vs解决 + 累计未解决趋势）
    if weekly_chart_image:
        body += '<h3 style="color: #1d1d1f; margin-top: 24px;">📊 Bug 增长 vs 解决曲线</h3>'
        body += f'<img src="{weekly_chart_image}" style="max-width: 100%; border-radius: 8px; margin-bottom: 16px;">'
    if cumulative_chart_image:
        body += '<h3 style="color: #1d1d1f;">📈 累计未解决 Bug 趋势</h3>'
        body += f'<img src="{cumulative_chart_image}" style="max-width: 100%; border-radius: 8px;">'

    # 每日趋势与累计Bug曲线（放在AI智能分析前面）
    if trend_image:
        body += f'<h3 style="color: #1d1d1f; margin-top: 24px;">📈 每日趋势与累计Bug曲线</h3><img src="{trend_image}" style="max-width: 100%; border-radius: 8px;">'

    # 分析摘要内容（去掉AI感，改成自然周报风格）
    full_analysis = ai_analysis.get('full_analysis') or {}
    if full_analysis:
        body += '<h3 style="color: #1d1d1f; margin-top: 24px;">分析摘要</h3>'

        # 根因分析
        root_cause = full_analysis.get('root_cause') or {}
        rc_ai = root_cause.get('ai_analysis') or {}
        if rc_ai:
            body += '<div style="margin-bottom: 16px; padding: 12px 16px; background: #f5f5f7; border-radius: 8px;">'
            body += '<div style="font-weight: 600; font-size: 14px; color: #1d1d1f; margin-bottom: 8px;">关键发现</div>'
            if rc_ai.get('risk_assessment'):
                body += f'<div style="font-size: 13px; color: #1d1d1f; margin-bottom: 8px; line-height: 1.6;">{rc_ai["risk_assessment"]}</div>'
            if rc_ai.get('key_findings'):
                body += '<ul style="margin: 0; padding-left: 20px; font-size: 12px; color: #48484a; line-height: 1.8;">'
                for finding in rc_ai['key_findings'][:5]:
                    body += f'<li>{finding}</li>'
                body += '</ul>'
            body += '</div>'

        # 趋势预测
        prediction = full_analysis.get('prediction') or {}
        if prediction.get('status') == 'success':
            body += '<div style="margin-bottom: 16px; padding: 12px 16px; background: #f5f5f7; border-radius: 8px;">'
            body += '<div style="font-weight: 600; font-size: 14px; color: #1d1d1f; margin-bottom: 8px;">趋势判断</div>'
            body += '<table style="width: 100%; border-collapse: collapse;">'
            body += '<tr>'
            body += f'<td style="text-align: center; padding: 8px;"><div style="font-size: 11px; color: #86868b;">趋势</div><div style="font-size: 16px; font-weight: 600;">{prediction.get("trend", "-")}</div></td>'
            body += f'<td style="text-align: center; padding: 8px;"><div style="font-size: 11px; color: #86868b;">未来7天预计新增</div><div style="font-size: 16px; font-weight: 600;">{prediction.get("total_predicted_new", 0)}</div></td>'
            body += f'<td style="text-align: center; padding: 8px;"><div style="font-size: 11px; color: #86868b;">置信度</div><div style="font-size: 16px; font-weight: 600;">{prediction.get("confidence", 0)}%</div></td>'
            body += '</tr></table></div>'

        # 改进计划
        improvement = full_analysis.get('improvement') or {}
        imp_plan = improvement.get('plan') or {}
        if imp_plan.get('short_term'):
            body += '<div style="margin-bottom: 16px; padding: 12px 16px; background: #f5f5f7; border-radius: 8px;">'
            body += '<div style="font-weight: 600; font-size: 14px; color: #1d1d1f; margin-bottom: 8px;">改进建议</div>'
            body += '<div style="font-size: 12px; font-weight: 600; color: #86868b; margin-bottom: 4px;">短期（1-2周）</div>'
            body += '<ul style="margin: 0 0 8px; padding-left: 20px; font-size: 12px; color: #1d1d1f; line-height: 1.8;">'
            for item in imp_plan['short_term'][:3]:
                action = item.get('action', '')
                impact = item.get('expected_impact', '')
                body += f'<li><strong>{action}</strong>'
                if impact:
                    body += f' - <span style="color: #86868b;">{impact}</span>'
                body += '</li>'
            body += '</ul>'
            if imp_plan.get('medium_term'):
                body += '<div style="font-size: 12px; font-weight: 600; color: #86868b; margin-bottom: 4px;">中期（1-2月）</div>'
                body += '<ul style="margin: 0; padding-left: 20px; font-size: 12px; color: #1d1d1f; line-height: 1.8;">'
                for item in imp_plan['medium_term'][:2]:
                    action = item.get('action', '')
                    body += f'<li>{action}</li>'
                body += '</ul>'
            body += '</div>'

    # 未解决问题列表（只显示概览，不展示具体问题）
    body += f'<p style="font-size: 13px; color: #86868b; margin-top: 20px;">共 {len(unresolved_list)} 个未解决问题，详见 CR 分析页面。</p>'

    body += '</div>'

    # 构建纯文本版本
    body_text = f'CR 分析日报 - {today}\n'
    body_text += f'问题总数: {total}\n'
    body_text += f'已解决: {resolved_count} ({resolution_rate})\n'
    body_text += f'未解决: {len(unresolved_list)}\n'
    body_text += f'Blocker: {len(blocker)}, Critical: {len(critical)}, Major: {len(major)}, Minor: {len(minor)}, Trivial: {len(trivial)}\n'
    body_text += f'B+C 解决率: {bc_rate} ({bc_resolved}/{bc_total})\n'
    
    if module_stats:
        body_text += '\n模块问题分布 Top 10:\n'
        modules = []
        if isinstance(module_stats, dict):
            for name, stats in module_stats.items():
                if isinstance(stats, dict):
                    modules.append({'name': name, 'total': stats.get('total', 0), 'unresolved': stats.get('unresolved', 0)})
        elif isinstance(module_stats, list):
            modules = module_stats
        modules.sort(key=lambda x: x.get('total', 0), reverse=True)
        for m in modules[:10]:
            body_text += f'  {m["name"]}: {m["total"]}个 (未解决{m["unresolved"]}个)\n'
    
    if weekly_stats:
        body_text += '\n每周对比表（近12周）:\n'
        for w in weekly_stats:
            net_sign = '+' if w['net'] > 0 else ''
            body_text += f'  {w["week"]}: 新增{w["new"]}, 解决{w["resolved"]}, 净增{net_sign}{w["net"]}, 累计{w["cumulative"]}\n'
    
    if full_analysis:
        body_text += '\n=== AI 智能分析 ===\n'
        rc_ai = (full_analysis.get('root_cause') or {}).get('ai_analysis') or {}
        if rc_ai.get('risk_assessment'):
            body_text += f'风险评估: {rc_ai["risk_assessment"]}\n'
        if rc_ai.get('key_findings'):
            body_text += '关键发现:\n'
            for f in rc_ai['key_findings'][:5]:
                body_text += f'  - {f}\n'
        pred = full_analysis.get('prediction') or {}
        if pred.get('status') == 'success':
            body_text += f'趋势预测: {pred.get("trend", "-")}, 未来7天新增{pred.get("total_predicted_new", 0)}个, 置信度{pred.get("confidence", 0)}%\n'
        imp = (full_analysis.get('improvement') or {}).get('plan') or {}
        if imp.get('short_term'):
            body_text += '短期改进建议:\n'
            for item in imp['short_term'][:3]:
                body_text += f'  - {item.get("action", "")}\n'

    return {
        'subject': subject,
        'body': body,
        'body_text': body_text,
        'recipients': [],
    }


def transform_cr_to_tasks(cr_data: Dict) -> Dict:
    """
    将 CR 分析数据转换为任务列表
    """
    issues = cr_data.get('issues') or []

    # 筛选未解决的问题作为任务
    unresolved = []
    for issue in issues:
        status = (issue.get('status') or '').lower()
        if not any(k in status for k in ('resolved', 'closed', 'done', '已解决', '已关闭')):
            severity = (issue.get('severity') or '').lower()
            priority = 'high' if 'critical' in severity or '致命' in severity else \
                       'medium' if 'high' in severity or '严重' in severity else 'low'

            unresolved.append({
                'title': issue.get('summary') or issue.get('标题') or '未命名问题',
                'description': f"问题ID: {issue.get('key') or issue.get('id') or '?'}\n模块: {issue.get('module') or issue.get('模块') or '未知'}\n严重度: {issue.get('severity') or '未知'}",
                'priority': priority,
                'source': 'cr-analysis',
                'source_id': issue.get('key') or issue.get('id'),
                'module': issue.get('module') or issue.get('模块'),
            })

    # 按优先级排序
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    unresolved.sort(key=lambda x: priority_order.get(x['priority'], 3))

    return {
        'tasks': unresolved,
        'summary': {
            'total': len(unresolved),
            'high': sum(1 for t in unresolved if t['priority'] == 'high'),
            'medium': sum(1 for t in unresolved if t['priority'] == 'medium'),
            'low': sum(1 for t in unresolved if t['priority'] == 'low'),
        },
    }


def execute_full_workflow(user_id: int, cr_data: Dict,
                          trend_image: str = None) -> Dict:
    """
    执行完整工作流：CR → 趋势 → 邮件 → 任务
    """
    results = {}

    # 1. CR → 趋势
    trend_data = transform_cr_to_trend(cr_data)
    results['trend'] = push_to_pipeline(
        user_id, 'cr_to_trend', trend_data,
        title='CR 分析趋势数据',
        metadata={'source': 'full_workflow'},
    )

    # 2. CR → 邮件
    email_data = transform_cr_to_email(cr_data, trend_image)
    results['email'] = push_to_pipeline(
        user_id, 'cr_to_email', email_data,
        title=email_data['subject'],
        metadata={'source': 'full_workflow'},
    )

    # 3. CR → 任务
    task_data = transform_cr_to_tasks(cr_data)
    results['tasks'] = push_to_pipeline(
        user_id, 'cr_to_task', task_data,
        title=f'CR 分析修复任务（{task_data["summary"]["total"]}个）',
        metadata={'source': 'full_workflow'},
    )

    return {
        'status': 'success',
        'message': '完整工作流执行完成',
        'results': results,
        'summary': {
            'trend_pushed': results['trend'].get('status') == 'success',
            'email_pushed': results['email'].get('status') == 'success',
            'tasks_created': task_data['summary']['total'],
        },
    }
