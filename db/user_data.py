
import os
import json
import time
import logging
from sqlalchemy import text
"""db.user_data - user_data 相关数据库操作"""
from .base import engine, DB_TYPE, _row_to_dict

def save_user_data(user_id, data_type, title, content):
    """保存用户数据，返回新记录ID"""
    with engine.begin() as conn:
        now = time.time()
        content_str = json.dumps(content, ensure_ascii=False) if isinstance(content, (dict, list)) else str(content)
        result = conn.execute(
            text("""
                INSERT INTO user_data (user_id, data_type, title, content, created_at)
                VALUES (:user_id, :data_type, :title, :content, :created_at)
                RETURNING id
            """),
            {'user_id': user_id, 'data_type': data_type, 'title': title,
             'content': content_str, 'created_at': now}
        )
        return result.scalar()




def get_user_data_list(user_id, data_type=None, limit=20):
    """获取用户数据列表"""
    with engine.connect() as conn:
        if data_type:
            rows = conn.execute(
                text("SELECT * FROM user_data WHERE user_id = :user_id AND data_type = :data_type ORDER BY created_at DESC LIMIT :limit"),
                {'user_id': user_id, 'data_type': data_type, 'limit': limit}
            ).fetchall()
        else:
            rows = conn.execute(
                text("SELECT * FROM user_data WHERE user_id = :user_id ORDER BY created_at DESC LIMIT :limit"),
                {'user_id': user_id, 'limit': limit}
            ).fetchall()

        result = []
        for row in rows:
            item = _row_to_dict(row)
            try:
                item['content'] = json.loads(item['content'])
            except (json.JSONDecodeError, TypeError):
                pass
            result.append(item)
        return result




def get_user_data_by_id(user_id, data_id):
    """获取单条用户数据"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM user_data WHERE id = :id AND user_id = :user_id"),
            {'id': data_id, 'user_id': user_id}
        ).fetchone()
        if not row:
            return None
        item = _row_to_dict(row)
        try:
            item['content'] = json.loads(item['content'])
        except (json.JSONDecodeError, TypeError):
            pass
        return item




def delete_user_data(user_id, data_id):
    """删除用户数据"""
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM user_data WHERE id = :id AND user_id = :user_id"),
            {'id': data_id, 'user_id': user_id}
        )
        return result.rowcount > 0




def update_user_data(user_id, data_id, title=None, content=None):
    """更新用户数据（标题和/或内容），返回是否成功"""
    with engine.begin() as conn:
        sets = []
        params = {'id': data_id, 'user_id': user_id}
        if title is not None:
            sets.append("title = :title")
            params['title'] = title
        if content is not None:
            content_str = json.dumps(content, ensure_ascii=False) if isinstance(content, (dict, list)) else str(content)
            sets.append("content = :content")
            params['content'] = content_str
        if not sets:
            return False
        sets.append("created_at = :created_at")
        params['created_at'] = time.time()
        result = conn.execute(
            text(f"UPDATE user_data SET {', '.join(sets)} WHERE id = :id AND user_id = :user_id"),
            params
        )
        return result.rowcount > 0




def count_user_data(user_id, data_type=None):
    """统计用户数据条数"""
    with engine.connect() as conn:
        if data_type:
            row = conn.execute(
                text("SELECT COUNT(*) as cnt FROM user_data WHERE user_id = :user_id AND data_type = :data_type"),
                {'user_id': user_id, 'data_type': data_type}
            ).fetchone()
        else:
            row = conn.execute(
                text("SELECT COUNT(*) as cnt FROM user_data WHERE user_id = :user_id"),
                {'user_id': user_id}
            ).fetchone()
        return row.cnt if row else 0


# ==================== 用户活动追踪 ====================

# 工具路径映射：URL 路径 -> tool_id


