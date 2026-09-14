"""
AI Agent 数据访问层 v8.0
管理 Agent 配置、运行记录、告警
"""
import time
import json
import logging
from sqlalchemy import text

from .base import engine, _PK_TYPE

logger = logging.getLogger(__name__)


# ==================== Agent 配置 ====================

def get_agent_config(user_id: int, name: str = 'default') -> dict:
    """获取用户的 Agent 配置"""
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM ai_agent_configs WHERE user_id = :user_id AND name = :name"),
            {'user_id': user_id, 'name': name}
        ).fetchone()
    if result:
        config = dict(result._mapping)
        # 解析 JSON 字段
        for field in ['monitor_metrics', 'alert_threshold', 'data_sources']:
            if config.get(field):
                try:
                    config[field] = json.loads(config[field])
                except:
                    config[field] = {} if field == 'alert_threshold' else []
        return config
    return None


def list_agent_configs(user_id: int) -> list:
    """列出用户的所有 Agent 配置"""
    with engine.connect() as conn:
        results = conn.execute(
            text("SELECT * FROM ai_agent_configs WHERE user_id = :user_id ORDER BY created_at DESC"),
            {'user_id': user_id}
        ).fetchall()
    configs = []
    for r in results:
        config = dict(r._mapping)
        for field in ['monitor_metrics', 'alert_threshold', 'data_sources']:
            if config.get(field):
                try:
                    config[field] = json.loads(config[field])
                except:
                    config[field] = {} if field == 'alert_threshold' else []
        configs.append(config)
    return configs


def save_agent_config(user_id: int, name: str, config_data: dict) -> int:
    """保存 Agent 配置（存在则更新）"""
    now = time.time()
    monitor_metrics = json.dumps(config_data.get('monitor_metrics', []), ensure_ascii=False)
    alert_threshold = json.dumps(config_data.get('alert_threshold', {}), ensure_ascii=False)
    data_sources = json.dumps(config_data.get('data_sources', []), ensure_ascii=False)

    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT id FROM ai_agent_configs WHERE user_id = :user_id AND name = :name"),
            {'user_id': user_id, 'name': name}
        ).fetchone()

        if existing:
            conn.execute(text("""
                UPDATE ai_agent_configs SET
                    enabled = :enabled,
                    schedule_type = :schedule_type,
                    schedule_time = :schedule_time,
                    monitor_metrics = :monitor_metrics,
                    alert_threshold = :alert_threshold,
                    auto_report = :auto_report,
                    alert_enabled = :alert_enabled,
                    data_sources = :data_sources,
                    updated_at = :updated_at
                WHERE user_id = :user_id AND name = :name
            """), {
                'enabled': int(config_data.get('enabled', 0)),
                'schedule_type': config_data.get('schedule_type', 'daily'),
                'schedule_time': config_data.get('schedule_time', '09:00'),
                'monitor_metrics': monitor_metrics,
                'alert_threshold': alert_threshold,
                'auto_report': int(config_data.get('auto_report', 1)),
                'alert_enabled': int(config_data.get('alert_enabled', 1)),
                'data_sources': data_sources,
                'updated_at': now,
                'user_id': user_id,
                'name': name,
            })
            config_id = existing.id
        else:
            result = conn.execute(text("""
                INSERT INTO ai_agent_configs
                    (user_id, name, enabled, schedule_type, schedule_time,
                     monitor_metrics, alert_threshold, auto_report, alert_enabled,
                     data_sources, created_at, updated_at)
                VALUES
                    (:user_id, :name, :enabled, :schedule_type, :schedule_time,
                     :monitor_metrics, :alert_threshold, :auto_report, :alert_enabled,
                     :data_sources, :created_at, :updated_at)
            """), {
                'user_id': user_id,
                'name': name,
                'enabled': int(config_data.get('enabled', 0)),
                'schedule_type': config_data.get('schedule_type', 'daily'),
                'schedule_time': config_data.get('schedule_time', '09:00'),
                'monitor_metrics': monitor_metrics,
                'alert_threshold': alert_threshold,
                'auto_report': int(config_data.get('auto_report', 1)),
                'alert_enabled': int(config_data.get('alert_enabled', 1)),
                'data_sources': data_sources,
                'created_at': now,
                'updated_at': now,
            })
            config_id = result.lastrowid
        conn.commit()
    return config_id


def update_agent_run_time(config_id: int, last_run_at: float, next_run_at: float):
    """更新 Agent 运行时间"""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_agent_configs SET last_run_at = :last_run_at, next_run_at = :next_run_at
            WHERE id = :id
        """), {'last_run_at': last_run_at, 'next_run_at': next_run_at, 'id': config_id})
        conn.commit()


def get_due_agents(current_time: float) -> list:
    """获取所有到期需要运行的 Agent 配置"""
    with engine.connect() as conn:
        results = conn.execute(text("""
            SELECT * FROM ai_agent_configs
            WHERE enabled = 1 AND next_run_at <= :current_time
        """), {'current_time': current_time}).fetchall()
    return [dict(r._mapping) for r in results]


# ==================== Agent 运行记录 ====================

def create_agent_run(user_id: int, config_id: int, trigger_type: str = 'scheduled') -> int:
    """创建 Agent 运行记录"""
    now = time.time()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO ai_agent_runs
                (user_id, config_id, status, trigger_type, started_at)
            VALUES (:user_id, :config_id, 'running', :trigger_type, :started_at)
        """), {'user_id': user_id, 'config_id': config_id, 'trigger_type': trigger_type, 'started_at': now})
        run_id = result.lastrowid
        conn.commit()
    return run_id


def update_agent_run(run_id: int, status: str, metrics_summary: dict = None,
                     anomalies: list = None, report_id: int = 0, error_message: str = ''):
    """更新 Agent 运行记录"""
    now = time.time()
    with engine.connect() as conn:
        run = conn.execute(
            text("SELECT started_at FROM ai_agent_runs WHERE id = :id"),
            {'id': run_id}
        ).fetchone()
        duration_ms = int((now - run.started_at) * 1000) if run else 0

        conn.execute(text("""
            UPDATE ai_agent_runs SET
                status = :status,
                metrics_summary = :metrics_summary,
                anomalies_found = :anomalies,
                report_id = :report_id,
                error_message = :error_message,
                completed_at = :completed_at,
                duration_ms = :duration_ms
            WHERE id = :id
        """), {
            'status': status,
            'metrics_summary': json.dumps(metrics_summary or {}, ensure_ascii=False),
            'anomalies': json.dumps(anomalies or [], ensure_ascii=False),
            'report_id': report_id,
            'error_message': error_message,
            'completed_at': now,
            'duration_ms': duration_ms,
            'id': run_id,
        })
        conn.commit()


def list_agent_runs(user_id: int, limit: int = 20) -> list:
    """列出用户的 Agent 运行记录"""
    with engine.connect() as conn:
        results = conn.execute(text("""
            SELECT * FROM ai_agent_runs
            WHERE user_id = :user_id
            ORDER BY started_at DESC
            LIMIT :limit
        """), {'user_id': user_id, 'limit': limit}).fetchall()
    runs = []
    for r in results:
        run = dict(r._mapping)
        for field in ['metrics_summary', 'anomalies_found']:
            if run.get(field):
                try:
                    run[field] = json.loads(run[field])
                except:
                    run[field] = {} if field == 'metrics_summary' else []
        runs.append(run)
    return runs


# ==================== 告警 ====================

def create_alert(user_id: int, run_id: int, alert_type: str, severity: str,
                 title: str, description: str, metric_name: str = '',
                 metric_value: float = 0, threshold: float = 0) -> int:
    """创建告警"""
    now = time.time()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO ai_alerts
                (user_id, run_id, alert_type, severity, title, description,
                 metric_name, metric_value, threshold, created_at)
            VALUES
                (:user_id, :run_id, :alert_type, :severity, :title, :description,
                 :metric_name, :metric_value, :threshold, :created_at)
        """), {
            'user_id': user_id,
            'run_id': run_id,
            'alert_type': alert_type,
            'severity': severity,
            'title': title,
            'description': description,
            'metric_name': metric_name,
            'metric_value': metric_value,
            'threshold': threshold,
            'created_at': now,
        })
        alert_id = result.lastrowid
        conn.commit()
    return alert_id


def list_alerts(user_id: int, only_unread: bool = False, limit: int = 50) -> list:
    """列出用户的告警"""
    query = "SELECT * FROM ai_alerts WHERE user_id = :user_id"
    params = {'user_id': user_id}
    if only_unread:
        query += " AND is_read = 0"
    query += " ORDER BY created_at DESC LIMIT :limit"
    params['limit'] = limit

    with engine.connect() as conn:
        results = conn.execute(text(query), params).fetchall()
    return [dict(r._mapping) for r in results]


def mark_alert_read(user_id: int, alert_id: int) -> bool:
    """标记告警已读"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE ai_alerts SET is_read = 1
            WHERE id = :id AND user_id = :user_id
        """), {'id': alert_id, 'user_id': user_id})
        conn.commit()
    return result.rowcount > 0


def mark_all_alerts_read(user_id: int) -> int:
    """标记所有告警已读"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE ai_alerts SET is_read = 1
            WHERE user_id = :user_id AND is_read = 0
        """), {'user_id': user_id})
        conn.commit()
    return result.rowcount


def resolve_alert(user_id: int, alert_id: int) -> bool:
    """解决告警"""
    now = time.time()
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE ai_alerts SET is_resolved = 1, resolved_at = :resolved_at
            WHERE id = :id AND user_id = :user_id
        """), {'id': alert_id, 'user_id': user_id, 'resolved_at': now})
        conn.commit()
    return result.rowcount > 0


def get_unread_alert_count(user_id: int) -> int:
    """获取未读告警数量"""
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT COUNT(*) as cnt FROM ai_alerts WHERE user_id = :user_id AND is_read = 0"),
            {'user_id': user_id}
        ).fetchone()
    return result.cnt if result else 0
