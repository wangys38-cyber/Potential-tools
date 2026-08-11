"""
用户数据库模块 - SQLite
管理用户账户和用户数据（分析记录、设置等）
"""
import os
import sqlite3
import json
import time
import hashlib
import logging

logger = logging.getLogger(__name__)

# 数据库路径
_RUNTIME_DIR = os.environ.get('DB_DIR', '/tmp/toolbox')
os.makedirs(_RUNTIME_DIR, exist_ok=True)
DB_PATH = os.path.join(_RUNTIME_DIR, 'users.db')


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    try:
        # 用户表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,          -- 'feishu' or 'google'
                provider_uid TEXT NOT NULL,      -- 第三方平台的用户ID
                name TEXT,
                email TEXT,
                avatar TEXT,
                created_at REAL DEFAULT 0,
                last_login REAL DEFAULT 0,
                UNIQUE(provider, provider_uid)
            )
        ''')

        # 用户数据表（存储分析记录、设置等）
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                data_type TEXT NOT NULL,         -- 'test_report', 'settings', etc.
                title TEXT,
                content TEXT,                    -- JSON string
                created_at REAL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')

        # 创建索引
        conn.execute('CREATE INDEX IF NOT EXISTS idx_user_data ON user_data(user_id, data_type)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_users_provider ON users(provider, provider_uid)')

        conn.commit()
        logger.info("数据库初始化完成")
    finally:
        conn.close()


def upsert_user(provider, provider_uid, name, email, avatar):
    """创建或更新用户，返回用户ID"""
    conn = get_db()
    try:
        now = time.time()
        cursor = conn.execute(
            'SELECT id FROM users WHERE provider=? AND provider_uid=?',
            (provider, provider_uid)
        )
        row = cursor.fetchone()

        if row:
            # 更新已有用户
            user_id = row['id']
            conn.execute(
                'UPDATE users SET name=?, email=?, avatar=?, last_login=? WHERE id=?',
                (name, email, avatar, now, user_id)
            )
        else:
            # 创建新用户
            conn.execute(
                'INSERT INTO users (provider, provider_uid, name, email, avatar, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (provider, provider_uid, name, email, avatar, now, now)
            )
            user_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

        conn.commit()
        return user_id
    finally:
        conn.close()


def get_user_by_id(user_id):
    """根据ID获取用户信息"""
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_user_data(user_id, data_type, title, content):
    """保存用户数据"""
    conn = get_db()
    try:
        now = time.time()
        content_str = json.dumps(content, ensure_ascii=False) if isinstance(content, (dict, list)) else str(content)
        conn.execute(
            'INSERT INTO user_data (user_id, data_type, title, content, created_at) VALUES (?, ?, ?, ?, ?)',
            (user_id, data_type, title, content_str, now)
        )
        conn.commit()
        return conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    finally:
        conn.close()


def get_user_data_list(user_id, data_type=None, limit=20):
    """获取用户数据列表"""
    conn = get_db()
    try:
        if data_type:
            cursor = conn.execute(
                'SELECT * FROM user_data WHERE user_id=? AND data_type=? ORDER BY created_at DESC LIMIT ?',
                (user_id, data_type, limit)
            )
        else:
            cursor = conn.execute(
                'SELECT * FROM user_data WHERE user_id=? ORDER BY created_at DESC LIMIT ?',
                (user_id, limit)
            )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item['content'] = json.loads(item['content'])
            except (json.JSONDecodeError, TypeError):
                pass
            result.append(item)
        return result
    finally:
        conn.close()


def get_user_data_by_id(user_id, data_id):
    """获取单条用户数据"""
    conn = get_db()
    try:
        row = conn.execute(
            'SELECT * FROM user_data WHERE id=? AND user_id=?',
            (data_id, user_id)
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item['content'] = json.loads(item['content'])
        except (json.JSONDecodeError, TypeError):
            pass
        return item
    finally:
        conn.close()


def delete_user_data(user_id, data_id):
    """删除用户数据"""
    conn = get_db()
    try:
        conn.execute('DELETE FROM user_data WHERE id=? AND user_id=?', (data_id, user_id))
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


# 启动时初始化
init_db()
