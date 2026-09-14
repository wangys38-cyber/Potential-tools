
import os
import json
import time
import logging
from sqlalchemy import text
"""db.uploads - uploads 相关数据库操作"""
from .base import engine, DB_TYPE, _row_to_dict

def create_upload_session(upload_id, filename, total_chunks, chunk_size, file_size):
    """创建上传会话"""
    with engine.begin() as conn:
        now = time.time()
        conn.execute(
            text("""
                INSERT INTO upload_sessions (upload_id, filename, total_chunks, chunk_size, file_size, received_chunks, created_at, updated_at)
                VALUES (:upload_id, :filename, :total_chunks, :chunk_size, :file_size, :received_chunks, :created_at, :updated_at)
                ON CONFLICT (upload_id) DO UPDATE SET
                    filename = EXCLUDED.filename,
                    total_chunks = EXCLUDED.total_chunks,
                    chunk_size = EXCLUDED.chunk_size,
                    file_size = EXCLUDED.file_size,
                    received_chunks = EXCLUDED.received_chunks,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at
            """),
            {'upload_id': upload_id, 'filename': filename, 'total_chunks': total_chunks,
             'chunk_size': chunk_size, 'file_size': file_size, 'received_chunks': '[]',
             'created_at': now, 'updated_at': now}
        )




def get_upload_session(upload_id):
    """获取上传会话"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM upload_sessions WHERE upload_id = :upload_id"),
            {'upload_id': upload_id}
        ).fetchone()
        if not row:
            return None
        data = _row_to_dict(row)
        try:
            data['received_chunks'] = json.loads(data.get('received_chunks', '[]'))
        except (json.JSONDecodeError, TypeError):
            data['received_chunks'] = []
        data['received_set'] = set(data['received_chunks'])
        return data




def add_received_chunk(upload_id, chunk_index):
    """添加已接收分块（事务保护，替代文件锁）"""
    with engine.begin() as conn:
        now = time.time()
        row = conn.execute(
            text("SELECT received_chunks FROM upload_sessions WHERE upload_id = :upload_id"),
            {'upload_id': upload_id}
        ).fetchone()
        if not row:
            return None

        try:
            chunks = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            chunks = []

        if chunk_index not in chunks:
            chunks.append(chunk_index)

        conn.execute(
            text("UPDATE upload_sessions SET received_chunks = :chunks, updated_at = :updated_at WHERE upload_id = :upload_id"),
            {'chunks': json.dumps(chunks), 'updated_at': now, 'upload_id': upload_id}
        )

    # 返回完整会话信息（事务已提交）
    return get_upload_session(upload_id)




def delete_upload_session(upload_id):
    """删除上传会话"""
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM upload_sessions WHERE upload_id = :upload_id"),
            {'upload_id': upload_id}
        )


# ==================== 后台任务 ====================



def create_task(task_id, task_type):
    """创建后台任务"""
    with engine.begin() as conn:
        now = time.time()
        conn.execute(
            text("""
                INSERT INTO background_tasks (task_id, task_type, status, progress, created_at, updated_at)
                VALUES (:task_id, :task_type, 'pending', 0, :created_at, :updated_at)
                ON CONFLICT (task_id) DO UPDATE SET
                    task_type = EXCLUDED.task_type,
                    status = 'pending',
                    progress = 0,
                    result = NULL,
                    error = NULL,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at
            """),
            {'task_id': task_id, 'task_type': task_type, 'created_at': now, 'updated_at': now}
        )




def update_task(task_id, status=None, progress=None, result=None, error=None):
    """更新后台任务状态"""
    with engine.begin() as conn:
        now = time.time()
        updates = ['updated_at = :updated_at']
        params = {'updated_at': now, 'task_id': task_id}

        if status is not None:
            updates.append('status = :status')
            params['status'] = status
        if progress is not None:
            updates.append('progress = :progress')
            params['progress'] = progress
        if result is not None:
            result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
            updates.append('result = :result')
            params['result'] = result_str
        if error is not None:
            updates.append('error = :error')
            params['error'] = error

        conn.execute(
            text(f"UPDATE background_tasks SET {', '.join(updates)} WHERE task_id = :task_id"),
            params
        )




def get_task(task_id):
    """获取后台任务"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM background_tasks WHERE task_id = :task_id"),
            {'task_id': task_id}
        ).fetchone()
        if not row:
            return None
        data = _row_to_dict(row)
        if data.get('result'):
            try:
                data['result'] = json.loads(data['result'])
            except (json.JSONDecodeError, TypeError):
                pass
        return data




def delete_task(task_id):
    """删除后台任务"""
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM background_tasks WHERE task_id = :task_id"),
            {'task_id': task_id}
        )




def cleanup_old_tasks(max_age_hours=24):
    """清理过期任务"""
    with engine.begin() as conn:
        cutoff = time.time() - max_age_hours * 3600
        conn.execute(
            text("DELETE FROM background_tasks WHERE updated_at < :cutoff AND status IN ('done', 'error')"),
            {'cutoff': cutoff}
        )
        conn.execute(
            text("DELETE FROM upload_sessions WHERE updated_at < :cutoff"),
            {'cutoff': cutoff}
        )


# ==================== 用户偏好 ====================



