
import os
import json
import time
import logging
from sqlalchemy import text
"""db.notifications - notifications 相关数据库操作"""
from .base import engine, DB_TYPE, _row_to_dict

def create_notification(user_id, notif_type, title, content='', link=''):
    """创建通知，返回通知ID"""
    with engine.begin() as conn:
        now = time.time()
        result = conn.execute(
            text("""
                INSERT INTO notifications (user_id, type, title, content, link, is_read, created_at)
                VALUES (:uid, :ntype, :title, :content, :link, 0, :now)
                RETURNING id
            """),
            {'uid': user_id, 'ntype': notif_type, 'title': title,
             'content': content or '', 'link': link or '', 'now': now}
        )
        return result.scalar()




def get_notifications(user_id, limit=50, unread_first=True):
    """获取通知列表，未读优先"""
    with engine.connect() as conn:
        if unread_first:
            rows = conn.execute(
                text("""
                    SELECT * FROM notifications WHERE user_id = :uid
                    ORDER BY is_read ASC, created_at DESC LIMIT :limit
                """),
                {'uid': user_id, 'limit': limit}
            ).fetchall()
        else:
            rows = conn.execute(
                text("""
                    SELECT * FROM notifications WHERE user_id = :uid
                    ORDER BY created_at DESC LIMIT :limit
                """),
                {'uid': user_id, 'limit': limit}
            ).fetchall()
        return [_row_to_dict(r) for r in rows]




def get_unread_notification_count(user_id):
    """获取未读通知数量"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) as cnt FROM notifications WHERE user_id = :uid AND is_read = 0"),
            {'uid': user_id}
        ).fetchone()
        return row[0] if row else 0




def mark_notification_read(notification_id, user_id):
    """标记单条通知为已读"""
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE notifications SET is_read = 1 WHERE id = :id AND user_id = :uid"),
            {'id': notification_id, 'uid': user_id}
        )
        return result.rowcount > 0




def mark_all_notifications_read(user_id):
    """标记所有通知为已读"""
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE notifications SET is_read = 1 WHERE user_id = :uid AND is_read = 0"),
            {'uid': user_id}
        )
        return result.rowcount


# ==================== 阶段四 安全加固：登录尝试 ====================



