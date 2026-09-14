
import os
import json
import time
import logging
from sqlalchemy import text
"""db.config - config 相关数据库操作"""
from .base import engine, DB_TYPE, _row_to_dict, SYNC_TYPES

logger = logging.getLogger(__name__)

def get_config(key, default=None):
    """读取应用配置"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT value FROM app_config WHERE key = :key"),
            {'key': key}
        ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return row[0]




def set_config(key, value):
    """写入应用配置（自动序列化 dict/list）"""
    with engine.begin() as conn:
        now = time.time()
        value_str = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        conn.execute(
            text("""
                INSERT INTO app_config (key, value, updated_at) VALUES (:key, :value, :updated_at)
                ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
            """),
            {'key': key, 'value': value_str, 'updated_at': now}
        )




def delete_config(key):
    """删除应用配置"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM app_config WHERE key = :key"), {'key': key})


# ==================== 功德计数 ====================



def get_user_preferences(user_id):
    """获取用户偏好"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT theme, language, accent_color FROM user_preferences WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()
        if not row:
            return {'theme': 'auto', 'language': 'zh-CN', 'accent_color': ''}
        m = row._mapping
        return {'theme': m['theme'], 'language': m['language'], 'accent_color': m['accent_color'] or ''}




def set_user_preferences(user_id, theme=None, language=None, accent_color=None):
    """更新用户偏好"""
    with engine.begin() as conn:
        now = time.time()
        row = conn.execute(
            text("SELECT user_id FROM user_preferences WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()

        if row:
            updates = ['updated_at = :updated_at']
            params = {'updated_at': now, 'user_id': user_id}
            if theme is not None:
                updates.append('theme = :theme')
                params['theme'] = theme
            if language is not None:
                updates.append('language = :language')
                params['language'] = language
            if accent_color is not None:
                updates.append('accent_color = :accent_color')
                params['accent_color'] = accent_color
            conn.execute(
                text(f"UPDATE user_preferences SET {', '.join(updates)} WHERE user_id = :user_id"),
                params
            )
        else:
            conn.execute(
                text("INSERT INTO user_preferences (user_id, theme, language, accent_color, updated_at) VALUES (:user_id, :theme, :language, :accent_color, :updated_at)"),
                {'user_id': user_id, 'theme': theme or 'auto', 'language': language or 'zh-CN', 'accent_color': accent_color or '', 'updated_at': now}
            )


# ==================== 牛马笔记同步 ====================



def get_user_ai_config(user_id):
    """读取用户级 AI 配置（JSON 字符串存储在 user_preferences.ai_config 列）"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT ai_config FROM user_preferences WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()
        if not row or not row[0]:
            return {}
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return {}




def set_user_ai_config(user_id, config):
    """保存用户级 AI 配置"""
    with engine.begin() as conn:
        now = time.time()
        config_str = json.dumps(config, ensure_ascii=False) if isinstance(config, dict) else str(config)
        row = conn.execute(
            text("SELECT user_id FROM user_preferences WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()
        if row:
            conn.execute(
                text("UPDATE user_preferences SET ai_config = :ai_config, updated_at = :updated_at WHERE user_id = :user_id"),
                {'ai_config': config_str, 'updated_at': now, 'user_id': user_id}
            )
        else:
            conn.execute(
                text("INSERT INTO user_preferences (user_id, theme, language, accent_color, ai_config, updated_at) VALUES (:user_id, 'auto', 'zh-CN', '', :ai_config, :updated_at)"),
                {'user_id': user_id, 'ai_config': config_str, 'updated_at': now}
            )


# ==================== 飞书推送配置 ====================



def get_feishu_webhook(user_id):
    """读取用户飞书 Webhook URL"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT feishu_webhook FROM user_preferences WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()
        if not row:
            return ''
        return row[0] or ''




def set_feishu_webhook(user_id, webhook_url):
    """保存用户飞书 Webhook URL"""
    with engine.begin() as conn:
        now = time.time()
        row = conn.execute(
            text("SELECT user_id FROM user_preferences WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()
        if row:
            conn.execute(
                text("UPDATE user_preferences SET feishu_webhook = :feishu_webhook, updated_at = :updated_at WHERE user_id = :user_id"),
                {'feishu_webhook': webhook_url, 'updated_at': now, 'user_id': user_id}
            )
        else:
            conn.execute(
                text("INSERT INTO user_preferences (user_id, theme, language, accent_color, feishu_webhook, updated_at) VALUES (:user_id, 'auto', 'zh-CN', '', :feishu_webhook, :updated_at)"),
                {'user_id': user_id, 'feishu_webhook': webhook_url, 'updated_at': now}
            )




def get_feishu_secret(user_id):
    """读取用户飞书签名密钥"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT feishu_secret FROM user_preferences WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()
        if not row:
            return ''
        return row[0] or ''




def set_feishu_secret(user_id, secret):
    """保存用户飞书签名密钥"""
    with engine.begin() as conn:
        now = time.time()
        row = conn.execute(
            text("SELECT user_id FROM user_preferences WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()
        if row:
            conn.execute(
                text("UPDATE user_preferences SET feishu_secret = :feishu_secret, updated_at = :updated_at WHERE user_id = :user_id"),
                {'feishu_secret': secret, 'updated_at': now, 'user_id': user_id}
            )
        else:
            conn.execute(
                text("INSERT INTO user_preferences (user_id, theme, language, accent_color, feishu_secret, updated_at) VALUES (:user_id, 'auto', 'zh-CN', '', :feishu_secret, :updated_at)"),
                {'user_id': user_id, 'feishu_secret': secret, 'updated_at': now}
            )


# ==================== JSON 文件迁移 ====================



def migrate_json_config(config_path, config_key):
    """将 JSON 配置文件迁移到数据库（仅首次启动时执行）"""
    if not os.path.exists(config_path):
        return False

    existing = get_config(config_key)
    if existing is not None:
        return False

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        set_config(config_key, data)
        logger.info(f"配置 {config_key} 已从 {config_path} 迁移到数据库")
        return True
    except Exception as e:
        logger.warning(f"迁移配置 {config_key} 失败: {e}")
        return False


# ==================== v5.3 协作：共享工作空间 ====================



def get_note_state(user_id):
    """获取用户的牛马笔记数据（整个 state JSON）"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT content, created_at FROM user_data WHERE user_id = :user_id AND data_type = 'notenb_state' ORDER BY created_at DESC LIMIT 1"),
            {'user_id': user_id}
        ).fetchone()
        if not row:
            return None
        m = row._mapping
        try:
            data = json.loads(m['content']) if m['content'] else None
        except (json.JSONDecodeError, TypeError):
            data = None
        return {'data': data, 'server_updated_at': m.get('created_at', 0)}




def save_note_state(user_id, state_data):
    """保存用户的牛马笔记数据（原子 upsert，防止并发竞态）"""
    with engine.begin() as conn:
        now = time.time()
        content_str = json.dumps(state_data, ensure_ascii=False) if isinstance(state_data, (dict, list)) else str(state_data)

        # 尝试先更新（最常见路径）
        result = conn.execute(
            text("UPDATE user_data SET content = :content, created_at = :created_at WHERE user_id = :user_id AND data_type = 'notenb_state' AND id = (SELECT id FROM user_data WHERE user_id = :user_id AND data_type = 'notenb_state' ORDER BY created_at DESC LIMIT 1)"),
            {'content': content_str, 'created_at': now, 'user_id': user_id}
        )
        # 如果没有更新到行，则插入
        if result.rowcount == 0:
            try:
                conn.execute(
                    text("INSERT INTO user_data (user_id, data_type, title, content, created_at) VALUES (:user_id, 'notenb_state', '牛马笔记', :content, :created_at)"),
                    {'user_id': user_id, 'content': content_str, 'created_at': now}
                )
            except Exception:
                # 并发插入：再次尝试更新
                conn.execute(
                    text("UPDATE user_data SET content = :content, created_at = :created_at WHERE user_id = :user_id AND data_type = 'notenb_state' AND id = (SELECT id FROM user_data WHERE user_id = :user_id AND data_type = 'notenb_state' ORDER BY created_at DESC LIMIT 1)"),
                    {'content': content_str, 'created_at': now, 'user_id': user_id}
                )
        return now


# ==================== v5.2 多设备数据同步 ====================

# 同步数据类型白名单


def get_sync_state(user_id, data_type):
    """获取某类同步数据的最新状态"""
    if data_type not in SYNC_TYPES:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT content, created_at FROM user_data WHERE user_id = :user_id AND data_type = :data_type ORDER BY created_at DESC LIMIT 1"),
            {'user_id': user_id, 'data_type': data_type}
        ).fetchone()
        if not row:
            return None
        m = row._mapping
        try:
            data = json.loads(m['content']) if m['content'] else None
        except (json.JSONDecodeError, TypeError):
            data = None
        return {'data': data, 'updated_at': m.get('created_at', 0)}




def set_sync_state(user_id, data_type, content):
    """保存某类同步数据（upsert，单记录模式），返回时间戳"""
    if data_type not in SYNC_TYPES:
        return 0
    with engine.begin() as conn:
        now = time.time()
        content_str = json.dumps(content, ensure_ascii=False) if isinstance(content, (dict, list)) else str(content)
        # 先尝试更新最新记录
        result = conn.execute(
            text("UPDATE user_data SET content = :content, created_at = :created_at WHERE user_id = :user_id AND data_type = :data_type AND id = (SELECT id FROM user_data WHERE user_id = :user_id AND data_type = :data_type ORDER BY created_at DESC LIMIT 1)"),
            {'content': content_str, 'created_at': now, 'user_id': user_id, 'data_type': data_type}
        )
        if result.rowcount == 0:
            try:
                conn.execute(
                    text("INSERT INTO user_data (user_id, data_type, title, content, created_at) VALUES (:user_id, :data_type, :title, :content, :created_at)"),
                    {'user_id': user_id, 'data_type': data_type, 'title': data_type, 'content': content_str, 'created_at': now}
                )
            except Exception:
                conn.execute(
                    text("UPDATE user_data SET content = :content, created_at = :created_at WHERE user_id = :user_id AND data_type = :data_type AND id = (SELECT id FROM user_data WHERE user_id = :user_id AND data_type = :data_type ORDER BY created_at DESC LIMIT 1)"),
                    {'content': content_str, 'created_at': now, 'user_id': user_id, 'data_type': data_type}
                )
        return now




def get_all_sync_states(user_id):
    """获取用户所有同步数据（用于全量拉取）"""
    result = {}
    for dtype in SYNC_TYPES:
        state = get_sync_state(user_id, dtype)
        if state:
            result[dtype] = state
    return result




def get_sync_status(user_id):
    """获取同步状态：各类型最新更新时间"""
    status = {}
    for dtype in SYNC_TYPES:
        state = get_sync_state(user_id, dtype)
        status[dtype] = state['updated_at'] if state else 0
    return status


# ==================== 用户级 AI 配置 ====================



