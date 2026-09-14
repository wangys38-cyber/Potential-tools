"""
CR 分析 AI 增强服务 v8.0
提供智能归因、趋势预测、改进建议等增强功能
"""
import json
import time
import math
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

from .base import ChatMessage, AIError

logger = logging.getLogger(__name__)


# ==================== 趋势预测 ====================

def predict_bug_trend(daily_data: List[Dict], days_ahead: int = 7) -> Dict[str, Any]:
    """
    基于历史每日 Bug 数据预测未来趋势
    使用简单移动平均 + 线性回归，AI 负责解释
    """
    if not daily_data or len(daily_data) < 3:
        return {
            'status': 'error',
            'error': '历史数据不足，至少需要 3 天数据',
            'prediction': [],
            'confidence': 0
        }

    # 提取每日新增和累计
    dates = [d.get('date', '') for d in daily_data]
    new_bugs = [d.get('new_bugs', d.get('新增', 0)) for d in daily_data]
    cumulative = [d.get('cumulative', d.get('累计', 0)) for d in daily_data]

    # 计算移动平均（7天窗口）
    window = min(7, len(new_bugs))
    ma_values = []
    for i in range(len(new_bugs)):
        start = max(0, i - window + 1)
        ma_values.append(sum(new_bugs[start:i+1]) / (i - start + 1))

    # 线性回归预测新增 Bug
    n = len(new_bugs)
    x = list(range(n))
    x_mean = sum(x) / n
    y_mean = sum(new_bugs) / n
    numerator = sum((x[i] - x_mean) * (new_bugs[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
    slope = numerator / denominator if denominator != 0 else 0
    intercept = y_mean - slope * x_mean

    # 预测未来 days_ahead 天
    last_date = dates[-1] if dates else datetime.now().strftime('%Y-%m-%d')
    try:
        last_dt = datetime.strptime(last_date, '%Y-%m-%d')
    except:
        last_dt = datetime.now()

    predictions = []
    for i in range(1, days_ahead + 1):
        future_x = n + i - 1
        predicted_new = max(0, round(slope * future_x + intercept, 1))
        # 结合移动平均调整
        if ma_values:
            predicted_new = round(predicted_new * 0.6 + ma_values[-1] * 0.4, 1)
        future_date = (last_dt + timedelta(days=i)).strftime('%Y-%m-%d')
        predictions.append({
            'date': future_date,
            'predicted_new': predicted_new,
            'predicted_cumulative': cumulative[-1] + sum(p['predicted_new'] for p in predictions) if predictions else cumulative[-1] + predicted_new,
            'lower_bound': max(0, round(predicted_new * 0.7, 1)),
            'upper_bound': round(predicted_new * 1.3, 1),
        })

    # 计算置信度（基于数据量和波动）
    variance = sum((b - y_mean) ** 2 for b in new_bugs) / n
    cv = math.sqrt(variance) / y_mean if y_mean > 0 else 1
    confidence = max(30, min(95, int(100 - cv * 50 - max(0, 10 - n) * 3)))

    # 趋势判断
    if slope > 0.5:
        trend = '上升'
        trend_icon = '📈'
    elif slope < -0.5:
        trend = '下降'
        trend_icon = '📉'
    else:
        trend = '平稳'
        trend_icon = '➡️'

    return {
        'status': 'success',
        'predictions': predictions,
        'historical': {
            'dates': dates,
            'new_bugs': new_bugs,
            'cumulative': cumulative,
            'moving_average': [round(v, 1) for v in ma_values],
        },
        'trend': trend,
        'trend_icon': trend_icon,
        'slope': round(slope, 3),
        'confidence': confidence,
        'avg_daily_new': round(y_mean, 1),
        'total_predicted_new': round(sum(p['predicted_new'] for p in predictions), 1),
    }


def explain_prediction(prediction_result: Dict, ai_service) -> str:
    """用 AI 解释预测结果"""
    if prediction_result.get('status') != 'success':
        return prediction_result.get('error', '预测失败')

    preds = prediction_result['predictions']
    hist = prediction_result['historical']

    summary = f"""
历史数据（最近 {len(hist['dates'])} 天）：
- 平均每日新增: {prediction_result['avg_daily_new']} 个
- 趋势: {prediction_result['trend_icon']} {prediction_result['trend']} (斜率: {prediction_result['slope']})
- 预测置信度: {prediction_result['confidence']}%

未来 {len(preds)} 天预测：
- 预计新增总数: {prediction_result['total_predicted_new']} 个
- 每日预测: {', '.join(f"{p['date']}: {p['predicted_new']}" for p in preds[:5])}
"""

    system_prompt = """你是资深质量数据分析专家。根据 Bug 趋势预测数据，给出专业的分析和建议。

要求：
1. 先总结当前趋势（1-2句）
2. 分析预测结果的合理性和风险
3. 给出 2-3 条具体的应对建议
4. 不超过 300 字
5. 用 Markdown 格式，简洁明了"""

    messages = [
        ChatMessage(role='system', content=system_prompt),
        ChatMessage(role='user', content=summary),
    ]

    try:
        response = ai_service.chat(messages, max_tokens=500, temperature=0.3)
        return response.content
    except Exception as e:
        logger.error(f'预测解释失败: {e}')
        return f"**趋势分析**\n\n当前 Bug 趋势呈{prediction_result['trend']}状态，未来 {len(preds)} 天预计新增 {prediction_result['total_predicted_new']} 个 Bug。建议持续关注高风险模块，加强回归测试。"


# ==================== 智能归因增强 ====================

def enhanced_root_cause_analysis(issues: List[Dict], ai_service) -> Dict[str, Any]:
    """
    增强根因分析：多维度归因
    - 按模块归因
    - 按严重度归因
    - 按根因类型归因
    - 交叉分析
    """
    if not issues:
        return {'status': 'error', 'error': '没有问题数据'}

    # 基础统计
    module_stats = defaultdict(lambda: {'total': 0, 'unresolved': 0, 'critical': 0, 'high': 0})
    severity_stats = defaultdict(int)
    status_stats = defaultdict(int)

    for issue in issues:
        module = issue.get('module') or issue.get('模块') or '未知'
        severity = (issue.get('severity') or issue.get('严重性') or 'normal').lower()
        status = (issue.get('status') or issue.get('状态') or '').lower()

        module_stats[module]['total'] += 1
        if not any(k in status for k in ('resolved', 'closed', 'done', '已解决', '已关闭')):
            module_stats[module]['unresolved'] += 1
        if 'critical' in severity or '致命' in severity or 'blocker' in severity:
            module_stats[module]['critical'] += 1
        elif 'high' in severity or '严重' in severity or 'major' in severity:
            module_stats[module]['high'] += 1

        severity_stats[severity] += 1
        status_stats[status] += 1

    # 找出高风险模块（未解决多 + 严重度高）
    high_risk_modules = []
    for module, stats in module_stats.items():
        risk_score = stats['unresolved'] * 2 + stats['critical'] * 3 + stats['high']
        if risk_score > 0:
            high_risk_modules.append({
                'module': module,
                'total': stats['total'],
                'unresolved': stats['unresolved'],
                'critical': stats['critical'],
                'high': stats['high'],
                'risk_score': risk_score,
            })
    high_risk_modules.sort(key=lambda x: x['risk_score'], reverse=True)

    # 用 AI 做深度归因分析
    unresolved_issues = [i for i in issues if not any(k in (i.get('status') or '').lower() for k in ('resolved', 'closed', 'done', '已解决', '已关闭'))]

    issues_summary = '\n'.join([
        f"- [{i.get('key') or i.get('id') or '?'}] {i.get('summary') or i.get('标题') or ''[:80]} (模块:{i.get('module') or '?'}, 严重度:{i.get('severity') or '?'})"
        for i in unresolved_issues[:30]
    ])

    analysis_prompt = f"""你是资深质量分析专家。请对以下 Bug 数据进行深度归因分析。

## 模块统计
{json.dumps(high_risk_modules[:10], ensure_ascii=False, indent=2)}

## 未解决 Bug（共 {len(unresolved_issues)} 条，显示前30条）
{issues_summary}

## 严重度分布
{json.dumps(dict(severity_stats), ensure_ascii=False)}

请输出 JSON 格式，不要 markdown 代码块：
{{
  "root_causes": [
    {{
      "cause": "根因描述",
      "affected_modules": ["模块1", "模块2"],
      "severity": "high/medium/low",
      "evidence": "数据证据",
      "fix_priority": 1
    }}
  ],
  "key_findings": ["发现1", "发现2"],
  "risk_assessment": "整体风险评估"
}}

要求：
1. root_causes 列出 3-5 个主要根因，按 fix_priority 排序
2. 每个根因要有数据证据支撑
3. key_findings 列出 3-5 个关键发现
4. risk_assessment 用一句话总结整体风险"""

    try:
        messages = [ChatMessage(role='user', content=analysis_prompt)]
        response = ai_service.chat(messages, max_tokens=1500, temperature=0.2)
        reply = response.content.strip()
        # 清理 markdown
        if reply.startswith('```'):
            reply = reply.replace('```json', '').replace('```', '').strip()
        start = reply.find('{')
        end = reply.rfind('}')
        if start >= 0 and end > start:
            reply = reply[start:end+1]
        ai_analysis = json.loads(reply)
    except Exception as e:
        logger.error(f'AI 归因分析失败: {e}')
        ai_analysis = {
            'root_causes': [],
            'key_findings': [f'共 {len(issues)} 个 Bug，{len(unresolved_issues)} 个未解决'],
            'risk_assessment': 'AI 分析暂时不可用，请查看模块统计',
        }

    return {
        'status': 'success',
        'module_stats': high_risk_modules[:10],
        'severity_stats': dict(severity_stats),
        'status_stats': dict(status_stats),
        'total_issues': len(issues),
        'unresolved_count': len(unresolved_issues),
        'ai_analysis': ai_analysis,
    }


# ==================== 改进建议 ====================

def generate_improvement_plan(analysis_result: Dict, ai_service) -> Dict[str, Any]:
    """
    基于分析结果生成系统性改进计划
    """
    module_stats = analysis_result.get('module_stats', [])
    ai_analysis = analysis_result.get('ai_analysis', {})

    context = f"""
## 分析结果摘要
- 总 Bug 数: {analysis_result.get('total_issues', 0)}
- 未解决: {analysis_result.get('unresolved_count', 0)}
- 高风险模块: {', '.join(m['module'] for m in module_stats[:5])}

## AI 根因分析
{json.dumps(ai_analysis, ensure_ascii=False, indent=2)}

## 模块风险排名
{json.dumps(module_stats[:5], ensure_ascii=False, indent=2)}
"""

    plan_prompt = f"""你是资深研发效能顾问。根据以上 Bug 分析结果，制定一份系统性改进计划。

请输出 JSON 格式：
{{
  "short_term": [
    {{"action": "具体行动", "target": "目标", "deadline": "1周内", "expected_impact": "预期效果"}}
  ],
  "medium_term": [
    {{"action": "具体行动", "target": "目标", "deadline": "1个月内", "expected_impact": "预期效果"}}
  ],
  "long_term": [
    {{"action": "具体行动", "target": "目标", "deadline": "本季度", "expected_impact": "预期效果"}}
  ],
  "priority_modules": ["优先改进的模块1", "模块2"],
  "kpi_targets": {{
    "bug_reduction_rate": "目标降低百分比",
    "mttr_improvement": "平均修复时间改善目标"
  }}
}}

要求：
1. short_term 3-5 条，可立即执行
2. medium_term 2-3 条，需要流程改进
3. long_term 1-2 条，架构/文化层面
4. 每条建议都要具体可执行，不要空泛
5. priority_modules 列出 2-3 个最该优先改进的模块"""

    try:
        messages = [ChatMessage(role='user', content=plan_prompt)]
        response = ai_service.chat(messages, max_tokens=1500, temperature=0.3)
        reply = response.content.strip()
        if reply.startswith('```'):
            reply = reply.replace('```json', '').replace('```', '').strip()
        start = reply.find('{')
        end = reply.rfind('}')
        if start >= 0 and end > start:
            reply = reply[start:end+1]
        plan = json.loads(reply)
        return {'status': 'success', 'plan': plan}
    except Exception as e:
        logger.error(f'改进计划生成失败: {e}')
        return {
            'status': 'success',
            'plan': {
                'short_term': [
                    {'action': '优先处理高风险模块的未解决 Bug', 'target': '降低未解决数量', 'deadline': '1周内', 'expected_impact': '快速降低风险'},
                    {'action': '对严重/致命 Bug 建立专项跟踪', 'target': '严重 Bug 清零', 'deadline': '1周内', 'expected_impact': '提升质量底线'},
                ],
                'medium_term': [
                    {'action': '加强高风险模块的代码评审和测试覆盖', 'target': '减少新增 Bug', 'deadline': '1个月内', 'expected_impact': '从源头减少问题'},
                ],
                'long_term': [
                    {'action': '建立质量度量体系和持续改进机制', 'target': '质量文化建设', 'deadline': '本季度', 'expected_impact': '长期质量提升'},
                ],
                'priority_modules': [m['module'] for m in module_stats[:3]],
                'kpi_targets': {'bug_reduction_rate': '20%', 'mttr_improvement': '30%'},
            }
        }


# ==================== 一键 AI 全量分析 ====================

def full_ai_analysis(issues: List[Dict], daily_data: List[Dict], ai_service) -> Dict[str, Any]:
    """
    一键执行完整 AI 分析：归因 + 预测 + 建议
    """
    start_time = time.time()

    # 1. 增强根因分析
    root_cause = enhanced_root_cause_analysis(issues, ai_service)

    # 2. 趋势预测
    prediction = predict_bug_trend(daily_data)
    prediction_explanation = ''
    if prediction.get('status') == 'success':
        prediction_explanation = explain_prediction(prediction, ai_service)

    # 3. 改进计划
    improvement = generate_improvement_plan(root_cause, ai_service)

    latency_ms = int((time.time() - start_time) * 1000)

    return {
        'status': 'success',
        'root_cause': root_cause,
        'prediction': prediction,
        'prediction_explanation': prediction_explanation,
        'improvement': improvement,
        'latency_ms': latency_ms,
    }
