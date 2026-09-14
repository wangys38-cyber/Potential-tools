
import os
import json
import time
import logging
from sqlalchemy import text
"""db.security - security 相关数据库操作"""
from .base import engine, DB_TYPE, _row_to_dict

def record_login_attempt(user_id=None, ip='', success=False):
    """记录一次登录尝试"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO login_attempts (user_id, ip, success, created_at)
                    VALUES (:user_id, :ip, :success, :created_at)
                """),
                {'user_id': user_id, 'ip': ip, 'success': 1 if success else 0, 'created_at': time.time()}
            )
    except Exception as e:
        logger.debug(f"记录登录尝试失败: {e}")




def count_recent_failed_attempts(ip='', user_id=None, window_seconds=900):
    """统计指定时间窗口内的失败登录次数（默认15分钟）"""
    try:
        cutoff = time.time() - window_seconds
        with engine.connect() as conn:
            if user_id:
                row = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM login_attempts
                        WHERE user_id = :uid AND success = 0 AND created_at >= :cutoff
                    """),
                    {'uid': user_id, 'cutoff': cutoff}
                ).fetchone()
            else:
                row = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM login_attempts
                        WHERE ip = :ip AND success = 0 AND created_at >= :cutoff
                    """),
                    {'ip': ip, 'cutoff': cutoff}
                ).fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.debug(f"统计失败登录次数失败: {e}")
        return 0




def cleanup_old_login_attempts(max_age_hours=24):
    """清理24小时前的登录尝试记录"""
    try:
        cutoff = time.time() - max_age_hours * 3600
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM login_attempts WHERE created_at < :cutoff"), {'cutoff': cutoff})
    except Exception as e:
        logger.error(f"清理登录尝试记录失败: {e}")


# ==================== 阶段四 安全加固：审计日志 ====================



def add_audit_log(user_id, action, target_type='', target_id='', ip='', user_agent='', details=''):
    """记录审计日志（非阻塞，失败不影响请求）"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO audit_logs (user_id, action, target_type, target_id, ip, user_agent, details, created_at)
                    VALUES (:user_id, :action, :target_type, :target_id, :ip, :user_agent, :details, :created_at)
                """),
                {
                    'user_id': user_id,
                    'action': action,
                    'target_type': target_type,
                    'target_id': str(target_id) if target_id is not None else '',
                    'ip': ip or '',
                    'user_agent': (user_agent or '')[:500],
                    'details': (details or '')[:2000],
                    'created_at': time.time(),
                }
            )
    except Exception as e:
        logger.debug(f"记录审计日志失败: {e}")




def get_audit_logs(page=1, per_page=50, user_id=None, action=None, search=''):
    """分页获取审计日志，支持按用户/操作/关键词筛选"""
    try:
        with engine.connect() as conn:
            offset = (page - 1) * per_page
            params = {'limit': per_page, 'offset': offset}
            where = []
            if user_id:
                where.append("a.user_id = :uid")
                params['uid'] = user_id
            if action:
                where.append("a.action = :action")
                params['action'] = action
            if search:
                where.append("(a.details LIKE :search OR a.target_type LIKE :search OR u.name LIKE :search)")
                params['search'] = f'%{search}%'
            where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''

            rows = conn.execute(
                text(f"""
                    SELECT a.*, u.name as user_name, u.email as user_email
                    FROM audit_logs a
                    LEFT JOIN users u ON a.user_id = u.id
                    {where_sql}
                    ORDER BY a.created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params
            ).fetchall()

            count_params = {k: v for k, v in params.items() if k not in ('limit', 'offset')}
            count_row = conn.execute(
                text(f"SELECT COUNT(*) as cnt FROM audit_logs a LEFT JOIN users u ON a.user_id = u.id {where_sql}"),
                count_params
            ).fetchone()
            total = count_row[0] if count_row else 0

            logs = [_row_to_dict(r) for r in rows]
            return {'logs': logs, 'total': total, 'page': page, 'per_page': per_page}
    except Exception as e:
        logger.error(f"获取审计日志失败: {e}")
        return {'logs': [], 'total': 0, 'page': page, 'per_page': per_page}




def cleanup_old_audit_logs(max_age_days=90):
    """清理90天前的审计日志"""
    try:
        cutoff = time.time() - max_age_days * 86400
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_logs WHERE created_at < :cutoff"), {'cutoff': cutoff})
    except Exception as e:
        logger.error(f"清理审计日志失败: {e}")


# ==================== 阶段四 安全加固：用户会话管理 ====================



def create_user_session(user_id, session_token, ip='', user_agent='', expires_at=0):
    """创建用户会话记录"""
    try:
        with engine.begin() as conn:
            now = time.time()
            conn.execute(
                text("""
                    INSERT INTO user_sessions (user_id, session_token, ip, user_agent, created_at, last_active, expires_at)
                    VALUES (:user_id, :session_token, :ip, :user_agent, :created_at, :last_active, :expires_at)
                """),
                {
                    'user_id': user_id,
                    'session_token': session_token,
                    'ip': ip or '',
                    'user_agent': (user_agent or '')[:500],
                    'created_at': now,
                    'last_active': now,
                    'expires_at': expires_at,
                }
            )
    except Exception as e:
        logger.debug(f"创建用户会话失败: {e}")




def get_active_sessions(user_id, max_sessions=3):
    """获取用户的活跃会话列表（按最后活跃时间降序）"""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, session_token, ip, user_agent, created_at, last_active, expires_at
                    FROM user_sessions
                    WHERE user_id = :uid AND (expires_at = 0 OR expires_at > :now)
                    ORDER BY last_active DESC
                """),
                {'uid': user_id, 'now': time.time()}
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"获取活跃会话失败: {e}")
        return []




def remove_oldest_sessions(user_id, keep_count=3):
    """超出最大会话数时，删除最老的会话，返回被删除的 session_token 列表"""
    removed = []
    try:
        sessions = get_active_sessions(user_id)
        if len(sessions) <= keep_count:
            return removed
        to_remove = sessions[keep_count:]
        with engine.begin() as conn:
            for s in to_remove:
                conn.execute(
                    text("DELETE FROM user_sessions WHERE session_token = :token"),
                    {'token': s['session_token']}
                )
                removed.append(s['session_token'])
    except Exception as e:
        logger.debug(f"清理旧会话失败: {e}")
    return removed




def update_session_activity(session_token):
    """更新会话最后活跃时间"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE user_sessions SET last_active = :now WHERE session_token = :token"),
                {'now': time.time(), 'token': session_token}
            )
    except Exception as e:
        logger.debug(f"更新会话活跃时间失败: {e}")




def delete_user_session(session_token):
    """删除指定会话（登出时调用）"""
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM user_sessions WHERE session_token = :token"), {'token': session_token})
    except Exception as e:
        logger.debug(f"删除会话失败: {e}")




def delete_all_user_sessions(user_id):
    """删除用户的所有会话（改密/删除账号时调用）"""
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM user_sessions WHERE user_id = :uid"), {'uid': user_id})
    except Exception as e:
        logger.debug(f"删除所有用户会话失败: {e}")




def cleanup_expired_sessions():
    """清理已过期的会话"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM user_sessions WHERE expires_at > 0 AND expires_at < :now"),
                {'now': time.time()}
            )
    except Exception as e:
        logger.debug(f"清理过期会话失败: {e}")


# ==================== 阶段四 安全加固：用户软删除 ====================



