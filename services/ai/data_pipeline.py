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
    pipeline_id = pipeline_db.save_pipeline_data(
        user_id=user_id,
        pipeline_key=pipeline_key,
        source_tool=pipeline['source'],
        target_tool=pipeline['target'],
        data_type='workflow_data',
        title=title or pipeline['name'],
        data_content=data,
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

    # 统计
    total = len(issues)
    unresolved = [i for i in issues if not any(k in (i.get('status') or '').lower() for k in ('resolved', 'closed', 'done', '已解决', '已关闭'))]
    critical = [i for i in issues if 'critical' in (i.get('severity') or '').lower() or '致命' in (i.get('severity') or '')]

    # 构建邮件主题
    today = datetime.now().strftime('%Y-%m-%d')
    subject = f'CR 分析日报 - {today}（共{total}个，未解决{len(unresolved)}个）'

    # 构建邮件正文
    body = f'''<div style="font-family: sans-serif; max-width: 700px; margin: 0 auto;">
<h2 style="color: #1d1d1f;">CR 问题分析报告</h2>
<p style="color: #86868b; font-size: 13px;">生成时间: {today}</p>

<h3 style="color: #1d1d1f; margin-top: 20px;">📊 概览</h3>
<table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
<tr>
<td style="padding: 10px; background: #f5f5f7; border-radius: 8px; text-align: center;">
<div style="font-size: 24px; font-weight: 600; color: #1d1d1f;">{total}</div>
<div style="font-size: 12px; color: #86868b;">总问题数</div>
</td>
<td style="padding: 10px; background: #fff3cd; border-radius: 8px; text-align: center;">
<div style="font-size: 24px; font-weight: 600; color: #856404;">{len(unresolved)}</div>
<div style="font-size: 12px; color: #856404;">未解决</div>
</td>
<td style="padding: 10px; background: #f8d7da; border-radius: 8px; text-align: center;">
<div style="font-size: 24px; font-weight: 600; color: #721c24;">{len(critical)}</div>
<div style="font-size: 12px; color: #721c24;">致命/严重</div>
</td>
</tr>
</table>
'''

    # 未解决问题列表
    if unresolved:
        body += '<h3 style="color: #1d1d1f;">⚠️ 未解决问题（前10条）</h3><ul style="font-size: 13px; line-height: 1.8;">'
        for issue in unresolved[:10]:
            key = issue.get('key') or issue.get('id') or '?'
            summary = issue.get('summary') or issue.get('标题') or ''
            module = issue.get('module') or issue.get('模块') or ''
            body += f'<li><strong>[{key}]</strong> {summary} <span style="color: #86868b;">({module})</span></li>'
        body += '</ul>'

    # 趋势图
    if trend_image:
        body += f'<h3 style="color: #1d1d1f;">📈 趋势图</h3><img src="{trend_image}" style="max-width: 100%; border-radius: 8px;">'

    body += '</div>'

    return {
        'subject': subject,
        'body': body,
        'body_text': f'CR 分析日报 - {today}\n总问题: {total}\n未解决: {len(unresolved)}\n致命/严重: {len(critical)}',
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
