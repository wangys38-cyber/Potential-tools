"""
AI Agent 核心服务 v8.0
定时自动分析、异常检测、自动报告生成、告警通知
"""
import time
import json
import math
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

from .base import ChatMessage, AIError
from . import cr_enhancer

logger = logging.getLogger(__name__)

# 全局 Agent 调度器实例
_agent_scheduler = None
_scheduler_lock = threading.Lock()


# ==================== 异常检测算法 ====================

def detect_anomalies(metrics_history: List[Dict], thresholds: Dict = None) -> List[Dict]:
    """
    检测指标异常
    支持：突增检测、趋势偏离、阈值超限
    """
    anomalies = []
    thresholds = thresholds or {}

    if not metrics_history or len(metrics_history) < 3:
        return anomalies

    # 按指标名分组
    metrics_by_name = defaultdict(list)
    for point in metrics_history:
        name = point.get('name', 'unknown')
        metrics_by_name[name].append(point)

    for metric_name, points in metrics_by_name.items():
        if len(points) < 3:
            continue

        values = [p.get('value', 0) for p in points]
        latest = values[-1]
        previous = values[-2] if len(values) >= 2 else 0

        # 1. 阈值超限检测
        threshold = thresholds.get(metric_name)
        if threshold is not None and latest > threshold:
            anomalies.append({
                'type': 'threshold_exceeded',
                'metric': metric_name,
                'value': latest,
                'threshold': threshold,
                'severity': 'high' if latest > threshold * 1.5 else 'medium',
                'message': f'{metric_name} 当前值 {latest} 超过阈值 {threshold}',
            })

        # 2. 突增检测（环比增长超过 50%）
        if previous > 0:
            growth_rate = (latest - previous) / previous
            if growth_rate > 0.5:
                anomalies.append({
                    'type': 'spike',
                    'metric': metric_name,
                    'value': latest,
                    'previous': previous,
                    'growth_rate': round(growth_rate * 100, 1),
                    'severity': 'high' if growth_rate > 1.0 else 'medium',
                    'message': f'{metric_name} 环比增长 {growth_rate*100:.1f}%（{previous} → {latest}）',
                })

        # 3. 趋势偏离检测（超过均值+2倍标准差）
        if len(values) >= 5:
            mean = sum(values[:-1]) / (len(values) - 1)
            variance = sum((v - mean) ** 2 for v in values[:-1]) / (len(values) - 1)
            std = math.sqrt(variance)
            if std > 0 and latest > mean + 2 * std:
                anomalies.append({
                    'type': 'trend_deviation',
                    'metric': metric_name,
                    'value': latest,
                    'mean': round(mean, 2),
                    'std': round(std, 2),
                    'severity': 'medium',
                    'message': f'{metric_name} 偏离历史均值（均值 {mean:.1f}，当前 {latest}）',
                })

    return anomalies


def calculate_metrics(issues: List[Dict], daily_data: List[Dict]) -> Dict:
    """
    从 CR 数据中计算关键指标
    """
    metrics = {
        'total_bugs': len(issues),
        'unresolved_bugs': 0,
        'critical_bugs': 0,
        'high_bugs': 0,
        'new_today': 0,
        'resolved_today': 0,
        'avg_resolution_days': 0,
        'modules_at_risk': 0,
    }

    # 统计未解决和严重度
    module_unresolved = defaultdict(int)
    resolution_days = []

    for issue in issues:
        status = (issue.get('status') or '').lower()
        severity = (issue.get('severity') or '').lower()
        is_resolved = any(k in status for k in ('resolved', 'closed', 'done', '已解决', '已关闭'))

        if not is_resolved:
            metrics['unresolved_bugs'] += 1
            module = issue.get('module') or issue.get('模块') or '未知'
            module_unresolved[module] += 1

        if 'critical' in severity or '致命' in severity or 'blocker' in severity:
            metrics['critical_bugs'] += 1
        elif 'high' in severity or '严重' in severity or 'major' in severity:
            metrics['high_bugs'] += 1

        # 计算修复时长
        if is_resolved:
            created = issue.get('created_at') or issue.get('创建时间')
            resolved = issue.get('resolved_at') or issue.get('解决时间')
            if created and resolved:
                try:
                    if isinstance(created, (int, float)):
                        days = (resolved - created) / 86400
                    else:
                        c = datetime.fromisoformat(str(created))
                        r = datetime.fromisoformat(str(resolved))
                        days = (r - c).total_seconds() / 86400
                    if 0 < days < 365:
                        resolution_days.append(days)
                except:
                    pass

    if resolution_days:
        metrics['avg_resolution_days'] = round(sum(resolution_days) / len(resolution_days), 1)

    # 高风险模块（未解决 >= 3）
    metrics['modules_at_risk'] = sum(1 for v in module_unresolved.values() if v >= 3)

    # 今日新增/解决
    today = datetime.now().strftime('%Y-%m-%d')
    for d in daily_data:
        if d.get('date') == today:
            metrics['new_today'] = d.get('new_bugs', 0)
            metrics['resolved_today'] = d.get('resolved', 0)

    return metrics


# ==================== Agent 运行核心流程 ====================

def run_agent_analysis(user_id: int, config: Dict, ai_service=None) -> Dict:
    """
    执行一次 Agent 分析
    1. 收集数据
    2. 计算指标
    3. 异常检测
    4. AI 分析
    5. 生成报告
    6. 创建告警
    """
    from db import agent as agent_db
    from db import ai as ai_db

    result = {
        'status': 'success',
        'metrics': {},
        'anomalies': [],
        'report': None,
        'report_id': 0,
        'alerts_created': 0,
    }

    # 1. 收集数据（从用户最近的 CR 分析数据中）
    issues, daily_data = _collect_user_data(user_id, config)
    if not issues:
        result['status'] = 'no_data'
        result['message'] = '没有可分析的 CR 数据，请先上传 CR 数据'
        return result

    # 2. 计算指标
    metrics = calculate_metrics(issues, daily_data)
    result['metrics'] = metrics

    # 3. 异常检测
    metrics_history = _build_metrics_history(user_id)
    thresholds = config.get('alert_threshold', {})
    anomalies = detect_anomalies(metrics_history, thresholds)
    result['anomalies'] = anomalies

    # 4. AI 深度分析（如果配置了 AI）
    ai_analysis = None
    if ai_service and config.get('auto_report', 1):
        try:
            ai_analysis = cr_enhancer.enhanced_root_cause_analysis(issues, ai_service)
            prediction = cr_enhancer.predict_bug_trend(daily_data)
            if prediction.get('status') == 'success':
                prediction['explanation'] = cr_enhancer.explain_prediction(prediction, ai_service)
            improvement = cr_enhancer.generate_improvement_plan(ai_analysis, ai_service)
            result['ai_analysis'] = ai_analysis
            result['prediction'] = prediction
            result['improvement'] = improvement
        except Exception as e:
            logger.warning(f'Agent AI 分析失败: {e}')

    # 5. 生成报告
    if config.get('auto_report', 1):
        report_content = _generate_agent_report(metrics, anomalies, ai_analysis, result.get('prediction'), result.get('improvement'))
        report_id = ai_db.save_ai_report(
            user_id=user_id,
            report_type='agent_daily',
            title=f'AI Agent 日报 - {datetime.now().strftime("%Y-%m-%d")}',
            content=report_content,
            data_ref=json.dumps({'metrics': metrics, 'anomaly_count': len(anomalies)}, ensure_ascii=False),
        )
        result['report_id'] = report_id
        result['report'] = report_content

    # 6. 创建告警
    if config.get('alert_enabled', 1) and anomalies:
        for anomaly in anomalies:
            agent_db.create_alert(
                user_id=user_id,
                run_id=0,  # 会在路由层更新
                alert_type=anomaly['type'],
                severity=anomaly['severity'],
                title=f"[{anomaly['severity'].upper()}] {anomaly['metric']} 异常",
                description=anomaly['message'],
                metric_name=anomaly['metric'],
                metric_value=anomaly.get('value', 0),
                threshold=anomaly.get('threshold', 0),
            )
            result['alerts_created'] += 1

    return result


def _collect_user_data(user_id: int, config: Dict) -> Tuple[List, List]:
    """收集用户的 CR 分析数据"""
    from db import user_data as user_data_db

    try:
        # 从 user_data 表获取最近的 CR 分析数据
        records = user_data_db.list_user_data(user_id, data_type='cr_analysis', limit=1)
        if not records:
            records = user_data_db.list_user_data(user_id, limit=5)

        for record in records:
            content = record.get('content', '')
            if content:
                try:
                    data = json.loads(content) if isinstance(content, str) else content
                    issues = data.get('issues') or data.get('bugs') or data.get('rows') or []
                    daily = data.get('dailyTrend') or data.get('daily_data') or []
                    if issues:
                        return issues, daily
                except:
                    continue
    except Exception as e:
        logger.warning(f'收集用户数据失败: {e}')

    return [], []


def _build_metrics_history(user_id: int) -> List[Dict]:
    """从历史运行记录中构建指标历史"""
    from db import agent as agent_db

    history = []
    try:
        runs = agent_db.list_agent_runs(user_id, limit=14)
        for run in runs:
            metrics = run.get('metrics_summary', {})
            if metrics:
                for name, value in metrics.items():
                    if isinstance(value, (int, float)):
                        history.append({
                            'name': name,
                            'value': value,
                            'timestamp': run.get('started_at', 0),
                        })
    except Exception as e:
        logger.warning(f'构建指标历史失败: {e}')

    return history


def _generate_agent_report(metrics: Dict, anomalies: List,
                           ai_analysis: Dict = None,
                           prediction: Dict = None,
                           improvement: Dict = None) -> str:
    """生成 Agent 日报内容"""
    lines = []
    lines.append(f'# AI Agent 质量日报')
    lines.append(f'生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append('')

    # 核心指标
    lines.append('## 📊 核心指标')
    lines.append(f'- 总 Bug 数: **{metrics.get("total_bugs", 0)}**')
    lines.append(f'- 未解决: **{metrics.get("unresolved_bugs", 0)}**')
    lines.append(f'- 致命 Bug: **{metrics.get("critical_bugs", 0)}**')
    lines.append(f'- 严重 Bug: **{metrics.get("high_bugs", 0)}**')
    lines.append(f'- 今日新增: **{metrics.get("new_today", 0)}**')
    lines.append(f'- 平均修复时长: **{metrics.get("avg_resolution_days", 0)} 天**')
    lines.append(f'- 高风险模块: **{metrics.get("modules_at_risk", 0)} 个**')
    lines.append('')

    # 异常告警
    if anomalies:
        lines.append('## ⚠️ 异常检测')
        for a in anomalies:
            icon = '🔴' if a['severity'] == 'high' else '🟡'
            lines.append(f'- {icon} **{a["metric"]}**: {a["message"]}')
        lines.append('')
    else:
        lines.append('## ✅ 异常检测')
        lines.append('- 未检测到异常，各项指标正常')
        lines.append('')

    # AI 根因分析
    if ai_analysis and ai_analysis.get('ai_analysis'):
        ai = ai_analysis['ai_analysis']
        if ai.get('risk_assessment'):
            lines.append('## 🎯 AI 风险评估')
            lines.append(ai['risk_assessment'])
            lines.append('')
        if ai.get('key_findings'):
            lines.append('## 🔍 关键发现')
            for f in ai['key_findings'][:5]:
                lines.append(f'- {f}')
            lines.append('')

    # 趋势预测
    if prediction and prediction.get('status') == 'success':
        lines.append('## 📈 趋势预测')
        lines.append(f'- 当前趋势: **{prediction.get("trend_icon", "")} {prediction.get("trend", "-")}**')
        lines.append(f'- 未来 7 天预计新增: **{prediction.get("total_predicted_new", 0)}**')
        lines.append(f'- 预测置信度: **{prediction.get("confidence", 0)}%**')
        if prediction.get('explanation'):
            lines.append(f'\n{prediction["explanation"]}')
        lines.append('')

    # 改进建议
    if improvement and improvement.get('plan'):
        plan = improvement['plan']
        if plan.get('short_term'):
            lines.append('## 📋 改进建议（短期）')
            for item in plan['short_term'][:3]:
                lines.append(f'- **{item["action"]}** - {item.get("expected_impact", "")}')
            lines.append('')

    return '\n'.join(lines)


# ==================== 定时调度器 ====================

class AgentScheduler:
    """AI Agent 定时调度器"""

    def __init__(self):
        self.running = False
        self.thread = None
        self.check_interval = 60  # 每分钟检查一次

    def start(self):
        """启动调度器"""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info('AI Agent 调度器已启动')

    def stop(self):
        """停止调度器"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info('AI Agent 调度器已停止')

    def _run_loop(self):
        """调度循环"""
        while self.running:
            try:
                self._check_and_run()
            except Exception as e:
                logger.error(f'Agent 调度循环异常: {e}')
            time.sleep(self.check_interval)

    def _check_and_run(self):
        """检查并运行到期的 Agent"""
        from db import agent as agent_db
        from services.ai import get_ai_service

        now = time.time()
        due_agents = agent_db.get_due_agents(now)

        for config in due_agents:
            user_id = config['user_id']
            config_id = config['id']

            # 计算下次运行时间
            next_run = self._calculate_next_run(config)
            agent_db.update_agent_run_time(config_id, now, next_run)

            # 在后台线程中运行分析
            threading.Thread(
                target=self._run_single_agent,
                args=(user_id, config_id, config),
                daemon=True
            ).start()

    def _run_single_agent(self, user_id: int, config_id: int, config: Dict):
        """运行单个 Agent"""
        from db import agent as agent_db
        from services.ai import get_ai_service

        run_id = agent_db.create_agent_run(user_id, config_id, 'scheduled')

        try:
            ai_service = None
            try:
                ai_service = get_ai_service()
            except:
                pass

            result = run_agent_analysis(user_id, config, ai_service)

            # 更新运行记录中的 run_id（告警关联）
            agent_db.update_agent_run(
                run_id=run_id,
                status='completed' if result['status'] == 'success' else result['status'],
                metrics_summary=result.get('metrics', {}),
                anomalies=result.get('anomalies', []),
                report_id=result.get('report_id', 0),
            )

            logger.info(f'Agent 运行完成: user={user_id}, run={run_id}, anomalies={len(result.get("anomalies", []))}')

        except Exception as e:
            logger.error(f'Agent 运行失败: {e}')
            agent_db.update_agent_run(
                run_id=run_id,
                status='failed',
                error_message=str(e),
            )

    def _calculate_next_run(self, config: Dict) -> float:
        """计算下次运行时间"""
        now = datetime.now()
        schedule_type = config.get('schedule_type', 'daily')
        schedule_time = config.get('schedule_time', '09:00')

        try:
            hour, minute = map(int, schedule_time.split(':'))
        except:
            hour, minute = 9, 0

        if schedule_type == 'daily':
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
        elif schedule_type == 'weekly':
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            days_ahead = 7 - now.weekday()
            if days_ahead == 0 and next_run <= now:
                days_ahead = 7
            next_run += timedelta(days=days_ahead)
        elif schedule_type == 'hourly':
            next_run = now + timedelta(hours=1)
        else:
            next_run = now + timedelta(days=1)

        return next_run.timestamp()


def get_agent_scheduler() -> AgentScheduler:
    """获取全局 Agent 调度器单例"""
    global _agent_scheduler
    with _scheduler_lock:
        if _agent_scheduler is None:
            _agent_scheduler = AgentScheduler()
        return _agent_scheduler


def start_agent_scheduler():
    """启动 Agent 调度器"""
    scheduler = get_agent_scheduler()
    scheduler.start()
