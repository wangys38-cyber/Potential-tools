"""
智能报告数据访问层 v8.0
管理报告模板、推送计划、推送日志
"""
import time
import json
import logging
from sqlalchemy import text

from .base import engine

logger = logging.getLogger(__name__)


# ==================== 报告模板 ====================

def list_report_templates(user_id: int) -> list:
    """列出用户的报告模板"""
    with engine.connect() as conn:
        results = conn.execute(text("""
            SELECT * FROM ai_report_templates
            WHERE user_id = :user_id
            ORDER BY is_default DESC, created_at DESC
        """), {'user_id': user_id}).fetchall()
    templates = []
    for r in results:
        t = dict(r._mapping)
        for field in ['include_metrics']:
            if t.get(field):
                try:
                    t[field] = json.loads(t[field])
                except:
                    t[field] = []
        templates.append(t)
    return templates


def get_report_template(template_id: int) -> dict:
    """获取报告模板"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM ai_report_templates WHERE id = :id"), {'id': template_id}).fetchone()
    if result:
        t = dict(result._mapping)
        if t.get('include_metrics'):
            try:
                t['include_metrics'] = json.loads(t['include_metrics'])
            except:
                t['include_metrics'] = []
        return t
    return None


def save_report_template(user_id: int, template_data: dict) -> int:
    """保存报告模板"""
    now = time.time()
    include_metrics = json.dumps(template_data.get('include_metrics', []), ensure_ascii=False)

    with engine.connect() as conn:
        if template_data.get('id'):
            conn.execute(text("""
                UPDATE ai_report_templates SET
                    name = :name, template_type = :template_type,
                    title_format = :title_format, content_template = :content_template,
                    include_metrics = :include_metrics, include_charts = :include_charts,
                    include_ai_analysis = :include_ai_analysis, updated_at = :updated_at
                WHERE id = :id AND user_id = :user_id
            """), {
                'name': template_data.get('name', ''),
                'template_type': template_data.get('template_type', 'daily'),
                'title_format': template_data.get('title_format', ''),
                'content_template': template_data.get('content_template', ''),
                'include_metrics': include_metrics,
                'include_charts': int(template_data.get('include_charts', 1)),
                'include_ai_analysis': int(template_data.get('include_ai_analysis', 1)),
                'updated_at': now,
                'id': template_data['id'],
                'user_id': user_id,
            })
            template_id = template_data['id']
        else:
            result = conn.execute(text("""
                INSERT INTO ai_report_templates
                    (user_id, name, template_type, title_format, content_template,
                     include_metrics, include_charts, include_ai_analysis, is_default,
                     created_at, updated_at)
                VALUES
                    (:user_id, :name, :template_type, :title_format, :content_template,
                     :include_metrics, :include_charts, :include_ai_analysis, :is_default,
                     :created_at, :updated_at)
            """), {
                'user_id': user_id,
                'name': template_data.get('name', ''),
                'template_type': template_data.get('template_type', 'daily'),
                'title_format': template_data.get('title_format', ''),
                'content_template': template_data.get('content_template', ''),
                'include_metrics': include_metrics,
                'include_charts': int(template_data.get('include_charts', 1)),
                'include_ai_analysis': int(template_data.get('include_ai_analysis', 1)),
                'is_default': int(template_data.get('is_default', 0)),
                'created_at': now,
                'updated_at': now,
            })
            template_id = result.lastrowid
        conn.commit()
    return template_id


def delete_report_template(user_id: int, template_id: int) -> bool:
    """删除报告模板"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            DELETE FROM ai_report_templates WHERE id = :id AND user_id = :user_id
        """), {'id': template_id, 'user_id': user_id})
        conn.commit()
    return result.rowcount > 0


# ==================== 推送计划 ====================

def list_report_schedules(user_id: int) -> list:
    """列出用户的推送计划"""
    with engine.connect() as conn:
        results = conn.execute(text("""
            SELECT * FROM ai_report_schedules
            WHERE user_id = :user_id
            ORDER BY created_at DESC
        """), {'user_id': user_id}).fetchall()
    schedules = []
    for r in results:
        s = dict(r._mapping)
        for field in ['recipients']:
            if s.get(field):
                try:
                    s[field] = json.loads(s[field])
                except:
                    s[field] = []
        schedules.append(s)
    return schedules


def get_report_schedule(schedule_id: int) -> dict:
    """获取推送计划"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM ai_report_schedules WHERE id = :id"), {'id': schedule_id}).fetchone()
    if result:
        s = dict(result._mapping)
        if s.get('recipients'):
            try:
                s['recipients'] = json.loads(s['recipients'])
            except:
                s['recipients'] = []
        return s
    return None


def save_report_schedule(user_id: int, schedule_data: dict) -> int:
    """保存推送计划"""
    now = time.time()
    recipients = json.dumps(schedule_data.get('recipients', []), ensure_ascii=False)

    with engine.connect() as conn:
        if schedule_data.get('id'):
            conn.execute(text("""
                UPDATE ai_report_schedules SET
                    name = :name, enabled = :enabled, template_id = :template_id,
                    schedule_type = :schedule_type, schedule_time = :schedule_time,
                    recipients = :recipients, subject_format = :subject_format,
                    email_body_format = :email_body_format, attach_pdf = :attach_pdf,
                    updated_at = :updated_at
                WHERE id = :id AND user_id = :user_id
            """), {
                'name': schedule_data.get('name', ''),
                'enabled': int(schedule_data.get('enabled', 0)),
                'template_id': schedule_data.get('template_id', 0),
                'schedule_type': schedule_data.get('schedule_type', 'daily'),
                'schedule_time': schedule_data.get('schedule_time', '09:00'),
                'recipients': recipients,
                'subject_format': schedule_data.get('subject_format', ''),
                'email_body_format': schedule_data.get('email_body_format', ''),
                'attach_pdf': int(schedule_data.get('attach_pdf', 0)),
                'updated_at': now,
                'id': schedule_data['id'],
                'user_id': user_id,
            })
            schedule_id = schedule_data['id']
        else:
            result = conn.execute(text("""
                INSERT INTO ai_report_schedules
                    (user_id, name, enabled, template_id, schedule_type, schedule_time,
                     recipients, subject_format, email_body_format, attach_pdf,
                     created_at, updated_at)
                VALUES
                    (:user_id, :name, :enabled, :template_id, :schedule_type, :schedule_time,
                     :recipients, :subject_format, :email_body_format, :attach_pdf,
                     :created_at, :updated_at)
            """), {
                'user_id': user_id,
                'name': schedule_data.get('name', ''),
                'enabled': int(schedule_data.get('enabled', 0)),
                'template_id': schedule_data.get('template_id', 0),
                'schedule_type': schedule_data.get('schedule_type', 'daily'),
                'schedule_time': schedule_data.get('schedule_time', '09:00'),
                'recipients': recipients,
                'subject_format': schedule_data.get('subject_format', ''),
                'email_body_format': schedule_data.get('email_body_format', ''),
                'attach_pdf': int(schedule_data.get('attach_pdf', 0)),
                'created_at': now,
                'updated_at': now,
            })
            schedule_id = result.lastrowid
        conn.commit()
    return schedule_id


def delete_report_schedule(user_id: int, schedule_id: int) -> bool:
    """删除推送计划"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            DELETE FROM ai_report_schedules WHERE id = :id AND user_id = :user_id
        """), {'id': schedule_id, 'user_id': user_id})
        conn.commit()
    return result.rowcount > 0


def get_due_report_schedules(current_time: float) -> list:
    """获取到期需要推送的计划"""
    with engine.connect() as conn:
        results = conn.execute(text("""
            SELECT * FROM ai_report_schedules
            WHERE enabled = 1 AND next_send_at <= :current_time
        """), {'current_time': current_time}).fetchall()
    return [dict(r._mapping) for r in results]


def update_schedule_send_time(schedule_id: int, last_sent_at: float, next_send_at: float):
    """更新推送计划的发送时间"""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_report_schedules SET last_sent_at = :last_sent_at, next_send_at = :next_send_at
            WHERE id = :id
        """), {'last_sent_at': last_sent_at, 'next_send_at': next_send_at, 'id': schedule_id})
        conn.commit()


# ==================== 推送日志 ====================

def create_push_log(user_id: int, schedule_id: int, template_id: int,
                    recipients: list, subject: str, content_preview: str) -> int:
    """创建推送日志"""
    now = time.time()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO ai_report_push_logs
                (user_id, schedule_id, template_id, status, recipients,
                 subject, content_preview, sent_at)
            VALUES
                (:user_id, :schedule_id, :template_id, 'sending', :recipients,
                 :subject, :content_preview, :sent_at)
        """), {
            'user_id': user_id,
            'schedule_id': schedule_id,
            'template_id': template_id,
            'recipients': json.dumps(recipients, ensure_ascii=False),
            'subject': subject,
            'content_preview': content_preview[:500],
            'sent_at': now,
        })
        log_id = result.lastrowid
        conn.commit()
    return log_id


def update_push_log(log_id: int, status: str, error_message: str = '', duration_ms: int = 0):
    """更新推送日志状态"""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_report_push_logs SET status = :status, error_message = :error_message, duration_ms = :duration_ms
            WHERE id = :id
        """), {'status': status, 'error_message': error_message, 'duration_ms': duration_ms, 'id': log_id})
        conn.commit()


def list_push_logs(user_id: int, limit: int = 20) -> list:
    """列出推送日志"""
    with engine.connect() as conn:
        results = conn.execute(text("""
            SELECT * FROM ai_report_push_logs
            WHERE user_id = :user_id
            ORDER BY sent_at DESC
            LIMIT :limit
        """), {'user_id': user_id, 'limit': limit}).fetchall()
    logs = []
    for r in results:
        log = dict(r._mapping)
        if log.get('recipients'):
            try:
                log['recipients'] = json.loads(log['recipients'])
            except:
                log['recipients'] = []
        logs.append(log)
    return logs
