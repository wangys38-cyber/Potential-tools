
import os
import json
import time
import logging
from sqlalchemy import text
"""db.notes - notes 相关数据库操作"""
from .base import engine, DB_TYPE, _row_to_dict

def get_notes(user_id):
    """获取用户所有笔记，按 pinned 优先、updated_at 降序排列"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, note_uid, title, content, category, tags, is_todo, pinned, completed, created_at, updated_at
                FROM notes WHERE user_id = :user_id
                ORDER BY pinned DESC, updated_at DESC
            """),
            {'user_id': user_id}
        ).fetchall()
        result = []
        for row in rows:
            item = _row_to_dict(row)
            try:
                item['tags'] = json.loads(item.get('tags', '[]') or '[]')
            except (json.JSONDecodeError, TypeError):
                item['tags'] = []
            item['is_todo'] = bool(item.get('is_todo', 0))
            item['pinned'] = bool(item.get('pinned', 0))
            result.append(item)
        return result




def get_note_by_uid(user_id, note_uid):
    """根据 note_uid 获取单条笔记"""
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT id, note_uid, title, content, category, tags, is_todo, pinned, completed, created_at, updated_at
                FROM notes WHERE user_id = :user_id AND note_uid = :note_uid
            """),
            {'user_id': user_id, 'note_uid': note_uid}
        ).fetchone()
        if not row:
            return None
        item = _row_to_dict(row)
        try:
            item['tags'] = json.loads(item.get('tags', '[]') or '[]')
        except (json.JSONDecodeError, TypeError):
            item['tags'] = []
        item['is_todo'] = bool(item.get('is_todo', 0))
        item['pinned'] = bool(item.get('pinned', 0))
        item['completed'] = bool(item.get('completed', 0))
        return item




def create_note(user_id, note_uid, title='', content='', category='', tags=None, is_todo=False, pinned=False, completed=False):
    """创建笔记，返回笔记字典"""
    with engine.begin() as conn:
        now = time.time()
        tags_str = json.dumps(tags or [], ensure_ascii=False)
        conn.execute(
            text("""
                INSERT INTO notes (user_id, note_uid, title, content, category, tags, is_todo, pinned, completed, created_at, updated_at)
                VALUES (:user_id, :note_uid, :title, :content, :category, :tags, :is_todo, :pinned, :completed, :created_at, :updated_at)
            """),
            {
                'user_id': user_id, 'note_uid': note_uid, 'title': title, 'content': content,
                'category': category, 'tags': tags_str, 'is_todo': 1 if is_todo else 0,
                'pinned': 1 if pinned else 0, 'completed': 1 if completed else 0,
                'created_at': now, 'updated_at': now
            }
        )
    return get_note_by_uid(user_id, note_uid)




def update_note(user_id, note_uid, title=None, content=None, category=None, tags=None, is_todo=None, pinned=None, completed=None):
    """更新笔记字段，返回是否成功"""
    with engine.begin() as conn:
        sets = ['updated_at = :updated_at']
        params = {'updated_at': time.time(), 'user_id': user_id, 'note_uid': note_uid}
        if title is not None:
            sets.append('title = :title'); params['title'] = title
        if content is not None:
            sets.append('content = :content'); params['content'] = content
        if category is not None:
            sets.append('category = :category'); params['category'] = category
        if completed is not None:
            sets.append('completed = :completed'); params['completed'] = 1 if completed else 0
        if tags is not None:
            sets.append('tags = :tags'); params['tags'] = json.dumps(tags, ensure_ascii=False)
        if is_todo is not None:
            sets.append('is_todo = :is_todo'); params['is_todo'] = 1 if is_todo else 0
        if pinned is not None:
            sets.append('pinned = :pinned'); params['pinned'] = 1 if pinned else 0
        result = conn.execute(
            text(f"UPDATE notes SET {', '.join(sets)} WHERE user_id = :user_id AND note_uid = :note_uid"),
            params
        )
        return result.rowcount > 0




def delete_note(user_id, note_uid):
    """删除笔记，返回是否成功"""
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM notes WHERE user_id = :user_id AND note_uid = :note_uid"),
            {'user_id': user_id, 'note_uid': note_uid}
        )
        return result.rowcount > 0




def get_note_categories(user_id):
    """获取用户所有笔记的分类列表（去重）"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT category FROM notes WHERE user_id = :user_id AND category != '' ORDER BY category"),
            {'user_id': user_id}
        ).fetchall()
        return [row[0] for row in rows if row[0]]


# ==================== v9.1 用户管理：管理员功能 ====================



