"""
跨工具数据联动数据访问层 v8.0
管理工具间数据流转的存储和查询
"""
import time
import json
import logging
from typing import Any
from sqlalchemy import text

from .base import engine

logger = logging.getLogger(__name__)


def save_pipeline_data(user_id: int, pipeline_key: str, source_tool: str,
                       target_tool: str, data_type: str, title: str,
                       data_content: Any, metadata: dict = None,
                       expires_in: int = 86400) -> int:
    """
    保存流转数据
    expires_in: 过期时间（秒），默认 24 小时
    """
    now = time.time()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO ai_pipeline_data
                (user_id, pipeline_key, source_tool, target_tool,
                 data_type, title, data_content, metadata,
                 status, expires_at, created_at)
            VALUES
                (:user_id, :pipeline_key, :source_tool, :target_tool,
                 :data_type, :title, :data_content, :metadata,
                 'pending', :expires_at, :created_at)
        """), {
            'user_id': user_id,
            'pipeline_key': pipeline_key,
            'source_tool': source_tool,
            'target_tool': target_tool,
            'data_type': data_type,
            'title': title,
            'data_content': json.dumps(data_content, ensure_ascii=False) if not isinstance(data_content, str) else data_content,
            'metadata': json.dumps(metadata or {}, ensure_ascii=False),
            'expires_at': now + expires_in,
            'created_at': now,
        })
        pipeline_id = result.lastrowid
        conn.commit()
    return pipeline_id


def get_pipeline_data(user_id: int, pipeline_key: str = None,
                      target_tool: str = None, status: str = 'pending',
                      limit: int = 10) -> list:
    """
    获取流转数据（自动过滤过期）
    """
    now = time.time()
    query = "SELECT * FROM ai_pipeline_data WHERE user_id = :user_id AND expires_at > :now"
    params = {'user_id': user_id, 'now': now}

    if pipeline_key:
        query += " AND pipeline_key = :pipeline_key"
        params['pipeline_key'] = pipeline_key
    if target_tool:
        query += " AND target_tool = :target_tool"
        params['target_tool'] = target_tool
    if status:
        query += " AND status = :status"
        params['status'] = status

    query += " ORDER BY created_at DESC LIMIT :limit"
    params['limit'] = limit

    with engine.connect() as conn:
        results = conn.execute(text(query), params).fetchall()

    data = []
    for r in results:
        item = dict(r._mapping)
        if item.get('data_content'):
            try:
                item['data_content'] = json.loads(item['data_content'])
            except:
                pass
        if item.get('metadata'):
            try:
                item['metadata'] = json.loads(item['metadata'])
            except:
                pass
        data.append(item)
    return data


def get_pipeline_by_id(pipeline_id: int) -> dict:
    """根据 ID 获取流转数据"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM ai_pipeline_data WHERE id = :id"),
                              {'id': pipeline_id}).fetchone()
    if result:
        item = dict(result._mapping)
        if item.get('data_content'):
            try:
                item['data_content'] = json.loads(item['data_content'])
            except:
                pass
        if item.get('metadata'):
            try:
                item['metadata'] = json.loads(item['metadata'])
            except:
                pass
        return item
    return None


def update_pipeline_status(pipeline_id: int, status: str) -> bool:
    """更新流转状态"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE ai_pipeline_data SET status = :status WHERE id = :id
        """), {'status': status, 'id': pipeline_id})
        conn.commit()
    return result.rowcount > 0


def delete_pipeline_data(pipeline_id: int, user_id: int) -> bool:
    """删除流转数据"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            DELETE FROM ai_pipeline_data WHERE id = :id AND user_id = :user_id
        """), {'id': pipeline_id, 'user_id': user_id})
        conn.commit()
    return result.rowcount > 0


def cleanup_expired_pipeline_data() -> int:
    """清理过期的流转数据"""
    now = time.time()
    with engine.connect() as conn:
        result = conn.execute(text("""
            DELETE FROM ai_pipeline_data WHERE expires_at < :now
        """), {'now': now})
        conn.commit()
    return result.rowcount


def list_pipeline_history(user_id: int, limit: int = 20) -> list:
    """列出流转历史（包含所有状态）"""
    with engine.connect() as conn:
        results = conn.execute(text("""
            SELECT id, pipeline_key, source_tool, target_tool, data_type,
                   title, status, created_at
            FROM ai_pipeline_data
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit
        """), {'user_id': user_id, 'limit': limit}).fetchall()
    return [dict(r._mapping) for r in results]
