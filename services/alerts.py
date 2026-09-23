# -*- coding: utf-8 -*-
"""
Potential-tools 9.0 - 智能预警与预测
CR趋势预测、异常检测、过点风险评估、自定义预警规则
"""
import os
import json
import time
import math
import logging
import threading
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
_ALERTS_PATH = os.path.join(_DATA_DIR, 'alerts.json')
_RULES_PATH = os.path.join(_DATA_DIR, 'alert_rules.json')
_LOCK = threading.Lock()


class AlertSeverity(Enum):
    INFO = 'info'        # 信息
    WARNING = 'warning'  # 警告
    CRITICAL = 'critical'  # 严重


class AlertStatus(Enum):
    ACTIVE = 'active'      # 活跃
    ACKNOWLEDGED = 'acknowledged'  # 已确认
    RESOLVED = 'resolved'  # 已解决


@dataclass
class AlertRule:
    """预警规则"""
    id: str
    name: str
    type: str  # cr_spike, trend_direction, milestone_risk, custom
    condition: Dict[str, Any] = field(default_factory=dict)
    severity: str = AlertSeverity.WARNING.value
    enabled: bool = True
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id, 'name': self.name, 'type': self.type,
            'condition': self.condition, 'severity': self.severity,
            'enabled': self.enabled, 'created_at': self.created_at
        }


@dataclass
class Alert:
    """预警记录"""
    id: str
    rule_id: str
    rule_name: str
    severity: str
    project_key: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    status: str = AlertStatus.ACTIVE.value
    created_at: float = field(default_factory=time.time)
    acknowledged_at: Optional[float] = None
    resolved_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id, 'rule_id': self.rule_id, 'rule_name': self.rule_name,
            'severity': self.severity, 'project_key': self.project_key,
            'message': self.message, 'details': self.details, 'status': self.status,
            'created_at': self.created_at, 'acknowledged_at': self.acknowledged_at,
            'resolved_at': self.resolved_at
        }


class TrendPredictor:
    """趋势预测器 — 简单线性回归 + 移动平均"""

    @staticmethod
    def linear_regression(points: List[Tuple[float, float]]) -> Dict[str, Any]:
        """
        简单线性回归
        points: [(x1, y1), (x2, y2), ...]
        返回: slope, intercept, r_squared, predictions
        """
        if len(points) < 2:
            return {'error': '至少需要2个数据点'}

        n = len(points)
        sum_x = sum(p[0] for p in points)
        sum_y = sum(p[1] for p in points)
        sum_xy = sum(p[0] * p[1] for p in points)
        sum_x2 = sum(p[0] ** 2 for p in points)

        denominator = n * sum_x2 - sum_x ** 2
        if denominator == 0:
            return {'error': '无法计算回归（x值相同）'}

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        # 计算 R²
        mean_y = sum_y / n
        ss_tot = sum((p[1] - mean_y) ** 2 for p in points)
        ss_res = sum((p[1] - (slope * p[0] + intercept)) ** 2 for p in points)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        return {
            'slope': slope,
            'intercept': intercept,
            'r_squared': r_squared,
            'direction': '上升' if slope > 0 else '下降' if slope < 0 else '平稳',
            'equation': f'y = {slope:.4f}x + {intercept:.4f}'
        }

    @staticmethod
    def moving_average(values: List[float], window: int = 3) -> List[float]:
        """移动平均"""
        if len(values) < window:
            return values
        result = []
        for i in range(len(values) - window + 1):
            result.append(sum(values[i:i + window]) / window)
        return result

    @staticmethod
    def predict_next(values: List[float], steps: int = 1) -> List[float]:
        """预测下一个值（基于线性回归）"""
        if len(values) < 2:
            return values
        points = [(i, v) for i, v in enumerate(values)]
        reg = TrendPredictor.linear_regression(points)
        if 'error' in reg:
            return values
        predictions = []
        for i in range(steps):
            x = len(values) + i
            predictions.append(reg['slope'] * x + reg['intercept'])
        return predictions


class AnomalyDetector:
    """异常检测器 — 基于标准差的 Z-Score 检测"""

    @staticmethod
    def detect(values: List[float], threshold: float = 2.0) -> List[Dict[str, Any]]:
        """
        检测异常值
        threshold: Z-Score 阈值，默认2.0（约95%置信度）
        返回: 异常点列表 [{index, value, z_score, type}]
        """
        if len(values) < 3:
            return []

        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return []

        anomalies = []
        for i, v in enumerate(values):
            z_score = (v - mean) / std_dev
            if abs(z_score) > threshold:
                anomalies.append({
                    'index': i,
                    'value': v,
                    'z_score': round(z_score, 2),
                    'type': '偏高' if z_score > 0 else '偏低'
                })
        return anomalies

    @staticmethod
    def detect_spike(current: float, history: List[float], threshold: float = 1.5) -> Dict[str, Any]:
        """
        检测当前值是否为尖峰（相比历史均值）
        返回: {is_spike, ratio, mean, std_dev}
        """
        if not history:
            return {'is_spike': False, 'ratio': 1.0, 'mean': current, 'std_dev': 0}

        mean = sum(history) / len(history)
        variance = sum((v - mean) ** 2 for v in history) / len(history)
        std_dev = math.sqrt(variance) if variance > 0 else 1

        ratio = current / mean if mean > 0 else float('inf')
        is_spike = ratio > threshold or (mean > 0 and (current - mean) / std_dev > 2)

        return {
            'is_spike': is_spike,
            'ratio': round(ratio, 2),
            'mean': round(mean, 2),
            'std_dev': round(std_dev, 2),
            'current': current
        }


class MilestoneRiskAssessor:
    """过点风险评估器"""

    @staticmethod
    def assess(unresolved_bc: int, blocker_count: int, critical_count: int,
               days_to_milestone: int, daily_fix_rate: float = 5.0) -> Dict[str, Any]:
        """
        评估过点风险
        unresolved_bc: 未解决的BC数量
        blocker_count: Blocker数量
        critical_count: Critical数量
        days_to_milestone: 距离过点天数
        daily_fix_rate: 每日修复率（默认5个/天）
        """
        # 计算预计修复时间
        estimated_days = unresolved_bc / daily_fix_rate if daily_fix_rate > 0 else float('inf')

        # 风险评分（0-100，越高越危险）
        risk_score = 0

        # 未解决BC占比
        if days_to_milestone > 0:
            bc_ratio = estimated_days / days_to_milestone
            if bc_ratio > 1.5:
                risk_score += 40
            elif bc_ratio > 1.0:
                risk_score += 25
            elif bc_ratio > 0.7:
                risk_score += 10

        # Blocker权重
        risk_score += min(blocker_count * 10, 30)

        # Critical权重
        risk_score += min(critical_count * 5, 20)

        # 时间紧迫度
        if days_to_milestone <= 1:
            risk_score += 10
        elif days_to_milestone <= 3:
            risk_score += 5

        risk_score = min(risk_score, 100)

        # 风险等级
        if risk_score >= 70:
            level = '高风险'
            recommendation = '建议立即增加资源，优先解决Blocker问题，考虑推迟过点'
        elif risk_score >= 40:
            level = '中风险'
            recommendation = '建议关注高优先级问题，确保每日修复率达标'
        else:
            level = '低风险'
            recommendation = '当前进度可控，继续保持每日修复节奏'

        return {
            'risk_score': risk_score,
            'risk_level': level,
            'estimated_days': round(estimated_days, 1),
            'days_to_milestone': days_to_milestone,
            'can_make_milestone': estimated_days <= days_to_milestone,
            'unresolved_bc': unresolved_bc,
            'blocker_count': blocker_count,
            'critical_count': critical_count,
            'recommendation': recommendation
        }


class AlertManager:
    """预警管理器 — 单例"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def __init__(self):
        self._alerts: Dict[str, Alert] = {}
        self._rules: Dict[str, AlertRule] = {}

    def _load(self):
        try:
            if os.path.exists(_ALERTS_PATH):
                with open(_ALERTS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for aid, adata in data.items():
                    self._alerts[aid] = Alert(
                        id=aid, rule_id=adata.get('rule_id', ''),
                        rule_name=adata.get('rule_name', ''),
                        severity=adata.get('severity', 'warning'),
                        project_key=adata.get('project_key', ''),
                        message=adata.get('message', ''),
                        details=adata.get('details', {}),
                        status=adata.get('status', 'active'),
                        created_at=adata.get('created_at', time.time()),
                        acknowledged_at=adata.get('acknowledged_at'),
                        resolved_at=adata.get('resolved_at')
                    )
        except Exception as e:
            logger.error(f"加载预警失败: {e}")

        try:
            if os.path.exists(_RULES_PATH):
                with open(_RULES_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for rid, rdata in data.items():
                    self._rules[rid] = AlertRule(
                        id=rid, name=rdata.get('name', ''),
                        type=rdata.get('type', 'custom'),
                        condition=rdata.get('condition', {}),
                        severity=rdata.get('severity', 'warning'),
                        enabled=rdata.get('enabled', True),
                        created_at=rdata.get('created_at', time.time())
                    )
        except Exception as e:
            logger.error(f"加载预警规则失败: {e}")

    def _save_alerts(self):
        try:
            os.makedirs(_DATA_DIR, exist_ok=True)
            data = {aid: a.to_dict() for aid, a in self._alerts.items()}
            with open(_ALERTS_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存预警失败: {e}")

    def _save_rules(self):
        try:
            os.makedirs(_DATA_DIR, exist_ok=True)
            data = {rid: r.to_dict() for rid, r in self._rules.items()}
            with open(_RULES_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存预警规则失败: {e}")

    def create_alert(self, rule_id: str, rule_name: str, severity: str,
                     project_key: str, message: str, details: Dict = None) -> Alert:
        """创建预警"""
        with _LOCK:
            aid = f"alert_{int(time.time())}_{len(self._alerts)}"
            alert = Alert(
                id=aid, rule_id=rule_id, rule_name=rule_name,
                severity=severity, project_key=project_key,
                message=message, details=details or {}
            )
            self._alerts[aid] = alert
            self._save_alerts()
            logger.info(f"创建预警: {rule_name} - {message}")
            return alert

    def list_alerts(self, project_key: Optional[str] = None,
                     status: Optional[str] = None,
                     severity: Optional[str] = None) -> List[Alert]:
        """列出预警"""
        alerts = list(self._alerts.values())
        if project_key:
            alerts = [a for a in alerts if a.project_key == project_key]
        if status:
            alerts = [a for a in alerts if a.status == status]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return sorted(alerts, key=lambda a: a.created_at, reverse=True)

    def acknowledge_alert(self, alert_id: str) -> bool:
        """确认预警"""
        with _LOCK:
            alert = self._alerts.get(alert_id)
            if not alert:
                return False
            alert.status = AlertStatus.ACKNOWLEDGED.value
            alert.acknowledged_at = time.time()
            self._save_alerts()
            return True

    def resolve_alert(self, alert_id: str) -> bool:
        """解决预警"""
        with _LOCK:
            alert = self._alerts.get(alert_id)
            if not alert:
                return False
            alert.status = AlertStatus.RESOLVED.value
            alert.resolved_at = time.time()
            self._save_alerts()
            return True

    def get_alert_stats(self) -> Dict[str, Any]:
        """获取预警统计"""
        total = len(self._alerts)
        active = sum(1 for a in self._alerts.values() if a.status == AlertStatus.ACTIVE.value)
        critical = sum(1 for a in self._alerts.values() if a.severity == AlertSeverity.CRITICAL.value and a.status == AlertStatus.ACTIVE.value)
        warning = sum(1 for a in self._alerts.values() if a.severity == AlertSeverity.WARNING.value and a.status == AlertStatus.ACTIVE.value)
        return {
            'total': total, 'active': active,
            'critical_active': critical, 'warning_active': warning,
            'by_severity': {
                'critical': sum(1 for a in self._alerts.values() if a.severity == 'critical'),
                'warning': sum(1 for a in self._alerts.values() if a.severity == 'warning'),
                'info': sum(1 for a in self._alerts.values() if a.severity == 'info')
            }
        }

    # 规则管理
    def list_rules(self) -> List[AlertRule]:
        return list(self._rules.values())

    def add_rule(self, name: str, type: str, condition: Dict,
                  severity: str = 'warning') -> AlertRule:
        with _LOCK:
            rid = f"rule_{int(time.time())}_{len(self._rules)}"
            rule = AlertRule(id=rid, name=name, type=type, condition=condition, severity=severity)
            self._rules[rid] = rule
            self._save_rules()
            return rule

    def delete_rule(self, rule_id: str) -> bool:
        with _LOCK:
            if rule_id in self._rules:
                del self._rules[rule_id]
                self._save_rules()
                return True
            return False


# 全局实例
alert_manager = AlertManager()
trend_predictor = TrendPredictor()
anomaly_detector = AnomalyDetector()
milestone_risk_assessor = MilestoneRiskAssessor()
