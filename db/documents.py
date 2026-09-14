
import os
import json
import time
import logging
from sqlalchemy import text
"""db.documents - documents 相关数据库操作"""
from .base import engine, DB_TYPE, _row_to_dict

def create_document_version(user_id, doc_type, doc_id, content, name='', note='', created_by=None):
    """创建文档版本快照，返回版本ID和版本号"""
    with engine.begin() as conn:
        now = time.time()
        # 获取当前最大版本号
        row = conn.execute(
            text("SELECT COALESCE(MAX(version_number), 0) as max_ver FROM document_versions WHERE user_id = :uid AND doc_type = :dtype AND doc_id = :did"),
            {'uid': user_id, 'dtype': doc_type, 'did': doc_id}
        ).fetchone()
        next_ver = (row[0] if row else 0) + 1
        result = conn.execute(
            text("""
                INSERT INTO document_versions (user_id, doc_type, doc_id, version_number, content, name, note, created_by, created_at)
                VALUES (:uid, :dtype, :did, :vnum, :content, :name, :note, :cby, :now)
                RETURNING id
            """),
            {'uid': user_id, 'dtype': doc_type, 'did': doc_id, 'vnum': next_ver,
             'content': content or '', 'name': name or '', 'note': note or '',
             'cby': created_by or user_id, 'now': now}
        )
        return result.scalar(), next_ver




def get_document_versions(user_id, doc_type, doc_id, limit=100):
    """获取文档的所有历史版本，时间倒序"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT v.*, u.name as creator_name, u.avatar as creator_avatar
                FROM document_versions v
                LEFT JOIN users u ON v.created_by = u.id
                WHERE v.user_id = :uid AND v.doc_type = :dtype AND v.doc_id = :did
                ORDER BY v.version_number DESC
                LIMIT :limit
            """),
            {'uid': user_id, 'dtype': doc_type, 'did': doc_id, 'limit': limit}
        ).fetchall()
        return [_row_to_dict(r) for r in rows]




def get_document_version_by_id(version_id):
    """根据ID获取版本详情"""
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT v.*, u.name as creator_name, u.avatar as creator_avatar
                FROM document_versions v
                LEFT JOIN users u ON v.created_by = u.id
                WHERE v.id = :id
            """),
            {'id': version_id}
        ).fetchone()
        return _row_to_dict(row) if row else None




def update_document_version_meta(version_id, user_id, name=None, note=None):
    """更新版本名称/备注"""
    with engine.begin() as conn:
        sets = []
        params = {'id': version_id, 'uid': user_id}
        if name is not None:
            sets.append('name = :name'); params['name'] = name
        if note is not None:
            sets.append('note = :note'); params['note'] = note
        if not sets:
            return False
        result = conn.execute(
            text(f"UPDATE document_versions SET {', '.join(sets)} WHERE id = :id AND user_id = :uid"),
            params
        )
        return result.rowcount > 0




def delete_document_versions(user_id, doc_type, doc_id):
    """删除某文档的所有版本（文档删除时调用）"""
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM document_versions WHERE user_id = :uid AND doc_type = :dtype AND doc_id = :did"),
            {'uid': user_id, 'dtype': doc_type, 'did': doc_id}
        )
        return True


# ==================== v12.0 通知系统 ====================



