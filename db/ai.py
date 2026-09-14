"""db.ai - v8.0 AI 原生相关数据库操作"""
import os
import json
import time
import logging
from sqlalchemy import text
from .base import engine, DB_TYPE, _row_to_dict

logger = logging.getLogger(__name__)


# ==================== AI 配置 ====================

def get_ai_config(user_id):
    """获取用户的 AI 配置（返回激活的配置）"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM ai_configs WHERE user_id = :user_id AND is_active = 1 LIMIT 1"),
            {'user_id': user_id}
        ).fetchone()
        return _row_to_dict(row)


def save_ai_config(user_id, provider, api_key, base_url='', model='gpt-3.5-turbo',
                   temperature=0.7, max_tokens=2000):
    """保存 AI 配置（upsert）"""
    now = time.time()
    with engine.begin() as conn:
        # 先停用其他配置
        conn.execute(
            text("UPDATE ai_configs SET is_active = 0 WHERE user_id = :user_id"),
            {'user_id': user_id}
        )
        # 插入或更新
        result = conn.execute(
            text("""
                INSERT INTO ai_configs (user_id, provider, api_key, base_url, model, temperature, max_tokens, is_active, created_at, updated_at)
                VALUES (:user_id, :provider, :api_key, :base_url, :model, :temperature, :max_tokens, 1, :now, :now)
                ON CONFLICT(user_id, provider) DO UPDATE SET
                    api_key = :api_key,
                    base_url = :base_url,
                    model = :model,
                    temperature = :temperature,
                    max_tokens = :max_tokens,
                    is_active = 1,
                    updated_at = :now
            """),
            {
                'user_id': user_id,
                'provider': provider,
                'api_key': api_key,
                'base_url': base_url,
                'model': model,
                'temperature': temperature,
                'max_tokens': max_tokens,
                'now': now,
            }
        )
        return result.rowcount > 0


def delete_ai_config(user_id, provider):
    """删除 AI 配置"""
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM ai_configs WHERE user_id = :user_id AND provider = :provider"),
            {'user_id': user_id, 'provider': provider}
        )
        return result.rowcount > 0


def list_ai_configs(user_id):
    """列出用户所有 AI 配置"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, user_id, provider, base_url, model, temperature, max_tokens, is_active, created_at, updated_at FROM ai_configs WHERE user_id = :user_id ORDER BY is_active DESC, created_at DESC"),
            {'user_id': user_id}
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


# ==================== AI 对话历史 ====================

def save_ai_message(user_id, session_id, role, content, tokens_used=0, model=''):
    """保存一条 AI 对话消息"""
    with engine.begin() as conn:
        result = conn.execute(
            text("""
                INSERT INTO ai_conversations (user_id, session_id, role, content, tokens_used, model, created_at)
                VALUES (:user_id, :session_id, :role, :content, :tokens_used, :model, :now)
            """),
            {
                'user_id': user_id,
                'session_id': session_id,
                'role': role,
                'content': content,
                'tokens_used': tokens_used,
                'model': model,
                'now': time.time(),
            }
        )
        return result.lastrowid


def get_ai_conversation(user_id, session_id, limit=50):
    """获取某个会话的对话历史"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT role, content, tokens_used, model, created_at
                FROM ai_conversations
                WHERE user_id = :user_id AND session_id = :session_id
                ORDER BY created_at ASC
                LIMIT :limit
            """),
            {'user_id': user_id, 'session_id': session_id, 'limit': limit}
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def list_ai_sessions(user_id, limit=20):
    """列出用户的 AI 会话列表"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT session_id, MAX(created_at) as last_active, COUNT(*) as msg_count
                FROM ai_conversations
                WHERE user_id = :user_id
                GROUP BY session_id
                ORDER BY last_active DESC
                LIMIT :limit
            """),
            {'user_id': user_id, 'limit': limit}
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def delete_ai_conversation(user_id, session_id):
    """删除某个会话的所有消息"""
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM ai_conversations WHERE user_id = :user_id AND session_id = :session_id"),
            {'user_id': user_id, 'session_id': session_id}
        )
        return result.rowcount


def get_ai_usage_stats(user_id, days=30):
    """获取 AI 使用统计"""
    cutoff = time.time() - days * 86400
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT COUNT(*) as total_messages,
                       COALESCE(SUM(tokens_used), 0) as total_tokens,
                       COUNT(DISTINCT session_id) as total_sessions
                FROM ai_conversations
                WHERE user_id = :user_id AND created_at > :cutoff
            """),
            {'user_id': user_id, 'cutoff': cutoff}
        ).fetchone()
        return _row_to_dict(row)


# ==================== AI 报告 ====================

def save_ai_report(user_id, report_type, title, content, data_ref='', tokens_used=0):
    """保存 AI 生成的报告"""
    with engine.begin() as conn:
        result = conn.execute(
            text("""
                INSERT INTO ai_reports (user_id, report_type, title, content, data_ref, tokens_used, created_at)
                VALUES (:user_id, :report_type, :title, :content, :data_ref, :tokens_used, :now)
            """),
            {
                'user_id': user_id,
                'report_type': report_type,
                'title': title,
                'content': content,
                'data_ref': data_ref,
                'tokens_used': tokens_used,
                'now': time.time(),
            }
        )
        return result.lastrowid


def get_ai_report(report_id):
    """获取 AI 报告"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM ai_reports WHERE id = :id"),
            {'id': report_id}
        ).fetchone()
        return _row_to_dict(row)


def list_ai_reports(user_id, report_type=None, limit=20):
    """列出用户的 AI 报告"""
    with engine.connect() as conn:
        if report_type:
            rows = conn.execute(
                text("""
                    SELECT id, user_id, report_type, title, data_ref, tokens_used, created_at
                    FROM ai_reports
                    WHERE user_id = :user_id AND report_type = :report_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {'user_id': user_id, 'report_type': report_type, 'limit': limit}
            ).fetchall()
        else:
            rows = conn.execute(
                text("""
                    SELECT id, user_id, report_type, title, data_ref, tokens_used, created_at
                    FROM ai_reports
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {'user_id': user_id, 'limit': limit}
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def delete_ai_report(user_id, report_id):
    """删除 AI 报告"""
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM ai_reports WHERE id = :id AND user_id = :user_id"),
            {'id': report_id, 'user_id': user_id}
        )
        return result.rowcount > 0
