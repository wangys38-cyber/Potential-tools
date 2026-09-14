"""
智能报告生成服务 v8.0
根据模板和数据生成报告内容
"""
import time
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from . import cr_enhancer
from .base import ChatMessage

logger = logging.getLogger(__name__)

# 内置报告模板
BUILTIN_TEMPLATES = {
    'daily': {
        'name': '每日质量日报',
        'title_format': '质量日报 - {date}',
        'include_metrics': ['total_bugs', 'unresolved_bugs', 'critical_bugs', 'high_bugs', 'new_today', 'avg_resolution_days'],
        'include_charts': True,
        'include_ai_analysis': True,
    },
    'weekly': {
        'name': '每周质量周报',
        'title_format': '质量周报 - {week_start} ~ {week_end}',
        'include_metrics': ['total_bugs', 'unresolved_bugs', 'critical_bugs', 'new_this_week', 'resolved_this_week', 'avg_resolution_days'],
        'include_charts': True,
        'include_ai_analysis': True,
    },
    'monthly': {
        'name': '每月质量月报',
        'title_format': '质量月报 - {year}年{month}月',
        'include_metrics': ['total_bugs', 'unresolved_bugs', 'critical_bugs', 'new_this_month', 'resolved_this_month', 'avg_resolution_days', 'bug_reduction_rate'],
        'include_charts': True,
        'include_ai_analysis': True,
    },
}


def generate_report(issues: List[Dict], daily_data: List[Dict],
                    template: Dict = None, ai_service=None) -> Dict[str, Any]:
    """
    生成智能报告
    Returns: {title, content, html_content, metrics, ai_analysis, prediction}
    """
    template = template or BUILTIN_TEMPLATES['daily']
    template_type = template.get('template_type', 'daily')

    # 1. 计算指标
    metrics = cr_enhancer.calculate_metrics(issues, daily_data)

    # 2. 趋势预测
    prediction = cr_enhancer.predict_bug_trend(daily_data)
    prediction_explanation = ''
    if prediction.get('status') == 'success' and ai_service:
        try:
            prediction_explanation = cr_enhancer.explain_prediction(prediction, ai_service)
        except:
            pass

    # 3. AI 分析
    ai_analysis = None
    if template.get('include_ai_analysis', True) and ai_service and issues:
        try:
            ai_analysis = cr_enhancer.enhanced_root_cause_analysis(issues, ai_service)
        except Exception as e:
            logger.warning(f'报告 AI 分析失败: {e}')

    # 4. 改进建议
    improvement = None
    if ai_analysis and ai_service:
        try:
            improvement = cr_enhancer.generate_improvement_plan(ai_analysis, ai_service)
        except:
            pass

    # 5. 生成标题
    now = datetime.now()
    title_vars = {
        'date': now.strftime('%Y-%m-%d'),
        'year': now.year,
        'month': now.month,
        'week_start': (now - __import__('datetime').timedelta(days=now.weekday())).strftime('%Y-%m-%d'),
        'week_end': (now + __import__('datetime').timedelta(days=6 - now.weekday())).strftime('%Y-%m-%d'),
    }
    title = template.get('title_format', '质量报告').format(**title_vars)

    # 6. 生成 Markdown 内容
    content = _build_markdown_content(title, metrics, prediction, prediction_explanation,
                                       ai_analysis, improvement, template)

    # 7. 生成 HTML 内容（用于邮件）
    html_content = _build_html_content(title, metrics, prediction, prediction_explanation,
                                        ai_analysis, improvement, template)

    return {
        'title': title,
        'content': content,
        'html_content': html_content,
        'metrics': metrics,
        'prediction': prediction,
        'prediction_explanation': prediction_explanation,
        'ai_analysis': ai_analysis,
        'improvement': improvement,
        'generated_at': time.time(),
    }


def _build_markdown_content(title, metrics, prediction, prediction_explanation,
                            ai_analysis, improvement, template) -> str:
    """构建 Markdown 格式报告"""
    lines = []
    lines.append(f'# {title}')
    lines.append(f'生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append('')

    # 核心指标
    lines.append('## 📊 核心指标')
    lines.append('| 指标 | 数值 |')
    lines.append('|------|------|')
    metric_names = {
        'total_bugs': '总 Bug 数',
        'unresolved_bugs': '未解决',
        'critical_bugs': '致命 Bug',
        'high_bugs': '严重 Bug',
        'new_today': '今日新增',
        'avg_resolution_days': '平均修复时长(天)',
        'modules_at_risk': '高风险模块数',
    }
    for key, name in metric_names.items():
        if key in metrics:
            lines.append(f'| {name} | **{metrics[key]}** |')
    lines.append('')

    # 趋势预测
    if prediction and prediction.get('status') == 'success':
        lines.append('## 📈 趋势预测')
        lines.append(f'- 当前趋势: **{prediction.get("trend_icon", "")} {prediction.get("trend", "-")}**')
        lines.append(f'- 未来 7 天预计新增: **{prediction.get("total_predicted_new", 0)}**')
        lines.append(f'- 预测置信度: **{prediction.get("confidence", 0)}%**')
        if prediction_explanation:
            lines.append(f'\n{prediction_explanation}')
        lines.append('')

    # AI 根因分析
    if ai_analysis and ai_analysis.get('ai_analysis'):
        ai = ai_analysis['ai_analysis']
        if ai.get('risk_assessment'):
            lines.append('## 🎯 风险评估')
            lines.append(ai['risk_assessment'])
            lines.append('')
        if ai.get('key_findings'):
            lines.append('## 🔍 关键发现')
            for f in ai['key_findings'][:5]:
                lines.append(f'- {f}')
            lines.append('')
        if ai.get('root_causes'):
            lines.append('## 📌 主要根因')
            for i, cause in enumerate(ai['root_causes'][:5], 1):
                lines.append(f'{i}. **{cause.get("cause", "")}**')
                if cause.get('evidence'):
                    lines.append(f'   - 证据: {cause["evidence"]}')
            lines.append('')

    # 改进建议
    if improvement and improvement.get('plan'):
        plan = improvement['plan']
        if plan.get('short_term'):
            lines.append('## 📋 改进建议')
            for item in plan['short_term'][:5]:
                lines.append(f'- **{item.get("action", "")}** - {item.get("expected_impact", "")}')
            lines.append('')

    return '\n'.join(lines)


def _build_html_content(title, metrics, prediction, prediction_explanation,
                        ai_analysis, improvement, template) -> str:
    """构建 HTML 格式报告（用于邮件）"""
    html = f'''
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 700px; margin: 0 auto; color: #1d1d1f;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 24px; border-radius: 12px 12px 0 0; color: white;">
        <h1 style="margin: 0; font-size: 22px;">{title}</h1>
        <p style="margin: 4px 0 0 0; opacity: 0.9; font-size: 13px;">生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
    </div>
    <div style="padding: 20px; background: #fff; border: 1px solid #e5e5ea; border-top: none;">
    '''

    # 核心指标
    html += '<h2 style="font-size: 16px; margin: 0 0 12px 0; color: #1d1d1f;">📊 核心指标</h2>'
    html += '<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 20px;">'
    metric_cards = [
        ('总 Bug', metrics.get('total_bugs', 0), '#1d1d1f'),
        ('未解决', metrics.get('unresolved_bugs', 0), '#ff9500'),
        ('致命', metrics.get('critical_bugs', 0), '#ff3b30'),
        ('严重', metrics.get('high_bugs', 0), '#ff9500'),
        ('今日新增', metrics.get('new_today', 0), '#1d1d1f'),
        ('平均修复(天)', metrics.get('avg_resolution_days', 0), '#34c759'),
    ]
    for name, value, color in metric_cards:
        html += f'''
        <div style="background: #f5f5f7; padding: 12px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: #86868b; margin-bottom: 2px;">{name}</div>
            <div style="font-size: 20px; font-weight: 600; color: {color};">{value}</div>
        </div>'''
    html += '</div>'

    # 趋势预测
    if prediction and prediction.get('status') == 'success':
        html += '<h2 style="font-size: 16px; margin: 0 0 12px 0;">📈 趋势预测</h2>'
        html += f'''
        <div style="background: #f5f5f7; padding: 14px; border-radius: 8px; margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-around; text-align: center;">
                <div>
                    <div style="font-size: 11px; color: #86868b;">当前趋势</div>
                    <div style="font-size: 16px; font-weight: 600;">{prediction.get("trend_icon", "")} {prediction.get("trend", "-")}</div>
                </div>
                <div>
                    <div style="font-size: 11px; color: #86868b;">未来7天新增</div>
                    <div style="font-size: 16px; font-weight: 600;">{prediction.get("total_predicted_new", 0)}</div>
                </div>
                <div>
                    <div style="font-size: 11px; color: #86868b;">置信度</div>
                    <div style="font-size: 16px; font-weight: 600;">{prediction.get("confidence", 0)}%</div>
                </div>
            </div>
        '''
        if prediction_explanation:
            html += f'<div style="margin-top: 10px; font-size: 13px; line-height: 1.6; color: #86868b;">{prediction_explanation.replace(chr(10), "<br>")}</div>'
        html += '</div>'

    # AI 分析
    if ai_analysis and ai_analysis.get('ai_analysis'):
        ai = ai_analysis['ai_analysis']
        if ai.get('risk_assessment'):
            html += '<h2 style="font-size: 16px; margin: 0 0 12px 0;">🎯 风险评估</h2>'
            html += f'<div style="background: #fff3cd; padding: 12px; border-radius: 8px; margin-bottom: 16px; font-size: 13px; color: #856404;">{ai["risk_assessment"]}</div>'
        if ai.get('key_findings'):
            html += '<h2 style="font-size: 16px; margin: 0 0 12px 0;">🔍 关键发现</h2><ul style="margin: 0 0 16px 0; padding-left: 20px;">'
            for f in ai['key_findings'][:5]:
                html += f'<li style="font-size: 13px; line-height: 1.8; color: #86868b;">{f}</li>'
            html += '</ul>'

    # 改进建议
    if improvement and improvement.get('plan', {}).get('short_term'):
        html += '<h2 style="font-size: 16px; margin: 0 0 12px 0;">📋 改进建议</h2>'
        for item in improvement['plan']['short_term'][:5]:
            html += f'''
            <div style="background: #f5f5f7; padding: 10px 14px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #34c759;">
                <div style="font-weight: 600; font-size: 13px;">{item.get("action", "")}</div>
                <div style="font-size: 12px; color: #86868b; margin-top: 2px;">{item.get("expected_impact", "")}</div>
            </div>'''

    html += '''
    </div>
    <div style="text-align: center; padding: 16px; color: #aeaeb2; font-size: 11px;">
        由 Potential-tools v8.0 AI Agent 自动生成
    </div>
</div>
    '''
    return html


def get_builtin_template(template_type: str) -> Dict:
    """获取内置模板"""
    return BUILTIN_TEMPLATES.get(template_type, BUILTIN_TEMPLATES['daily']).copy()
