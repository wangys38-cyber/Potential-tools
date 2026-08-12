"""
数据库模块 v2.0 - SQLite
统一管理所有数据存储：用户、配置、功德、上传会话、后台任务

升级说明：
- 新增 app_config 表：替代 ai_config.json 文件存储
- 新增 merit_records 表：功德计数持久化（替代 localStorage）
- 新增 upload_sessions 表：分块上传元数据（替代 JSON 文件 + 文件锁）
- 新增 background_tasks 表：后台任务元数据（替代 JSON 文件）
- 新增 user_preferences 表：用户偏好（主题模式等）
- 保留原有 users 和 user_data 表，完全向下兼容
"""
import os
import sqlite3
import json
import time
import logging

logger = logging.getLogger(__name__)

# 数据库路径
_RUNTIME_DIR = os.environ.get('DB_DIR', '/tmp/toolbox')
os.makedirs(_RUNTIME_DIR, exist_ok=True)
DB_PATH = os.path.join(_RUNTIME_DIR, 'users.db')

# 连接级线程安全：每个请求/线程获取独立连接
_db_local = None


def get_db():
    """获取数据库连接（WAL模式，支持并发读）"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    """初始化所有数据库表"""
    conn = get_db()
    try:
        # ==================== 原有表 ====================

        # 用户表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                provider_uid TEXT NOT NULL,
                name TEXT,
                email TEXT,
                avatar TEXT,
                created_at REAL DEFAULT 0,
                last_login REAL DEFAULT 0,
                UNIQUE(provider, provider_uid)
            )
        ''')

        # 用户数据表（分析记录、设置等）
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                data_type TEXT NOT NULL,
                title TEXT,
                content TEXT,
                created_at REAL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')

        # ==================== v2.0 新增表 ====================

        # 应用配置表（替代 ai_config.json）
        conn.execute('''
            CREATE TABLE IF NOT EXISTS app_config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at REAL DEFAULT 0
            )
        ''')

        # 功德记录表（替代 localStorage）
        conn.execute('''
            CREATE TABLE IF NOT EXISTS merit_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                total_count INTEGER DEFAULT 0,
                today_count INTEGER DEFAULT 0,
                today_date TEXT,
                updated_at REAL DEFAULT 0,
                UNIQUE(user_id)
            )
        ''')

        # 上传会话表（替代 {upload_id}.json + 文件锁）
        conn.execute('''
            CREATE TABLE IF NOT EXISTS upload_sessions (
                upload_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                total_chunks INTEGER NOT NULL,
                chunk_size INTEGER NOT NULL,
                file_size INTEGER NOT NULL,
                received_chunks TEXT DEFAULT '[]',
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0
            )
        ''')

        # 后台任务表（替代 {task_id}.json）
        conn.execute('''
            CREATE TABLE IF NOT EXISTS background_tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                progress REAL DEFAULT 0,
                result TEXT,
                error TEXT,
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0
            )
        ''')

        # 用户偏好表（主题模式、语言等）
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                theme TEXT DEFAULT 'auto',
                language TEXT DEFAULT 'zh-CN',
                updated_at REAL DEFAULT 0
            )
        ''')

        # 创建索引
        conn.execute('CREATE INDEX IF NOT EXISTS idx_user_data ON user_data(user_id, data_type)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_users_provider ON users(provider, provider_uid)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_merit_user ON merit_records(user_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON background_tasks(status)')

        conn.commit()
        logger.info("数据库 v2.0 初始化完成")
    finally:
        conn.close()


# ==================== 用户相关（原有，保持兼容） ====================

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
            user_id = row['id']
            conn.execute(
                'UPDATE users SET name=?, email=?, avatar=?, last_login=? WHERE id=?',
                (name, email, avatar, now, user_id)
            )
        else:
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


# ==================== 应用配置（替代 ai_config.json） ====================

def get_config(key, default=None):
    """读取应用配置"""
    conn = get_db()
    try:
        row = conn.execute('SELECT value FROM app_config WHERE key=?', (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row['value'])
        except (json.JSONDecodeError, TypeError):
            return row['value']
    finally:
        conn.close()


def set_config(key, value):
    """写入应用配置（自动序列化 dict/list）"""
    conn = get_db()
    try:
        now = time.time()
        value_str = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        conn.execute(
            'INSERT INTO app_config (key, value, updated_at) VALUES (?, ?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
            (key, value_str, now)
        )
        conn.commit()
    finally:
        conn.close()


def delete_config(key):
    """删除应用配置"""
    conn = get_db()
    try:
        conn.execute('DELETE FROM app_config WHERE key=?', (key,))
        conn.commit()
    finally:
        conn.close()


# ==================== 功德计数（替代 localStorage） ====================

def get_merit(user_id):
    """获取用户功德数据"""
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM merit_records WHERE user_id=?', (user_id,)).fetchone()
        if not row:
            return {'total_count': 0, 'today_count': 0, 'today_date': ''}
        return dict(row)
    finally:
        conn.close()


def increment_merit(user_id):
    """功德+1（原子操作，自动处理日期切换）"""
    conn = get_db()
    try:
        now = time.time()
        today = time.strftime('%Y-%m-%d', time.localtime(now))

        # 尝试更新已有记录
        row = conn.execute('SELECT * FROM merit_records WHERE user_id=?', (user_id,)).fetchone()
        if row:
            # 日期切换：今日计数归零
            if row['today_date'] != today:
                conn.execute(
                    'UPDATE merit_records SET total_count=total_count+1, today_count=1, today_date=?, updated_at=? WHERE user_id=?',
                    (today, now, user_id)
                )
            else:
                conn.execute(
                    'UPDATE merit_records SET total_count=total_count+1, today_count=today_count+1, updated_at=? WHERE user_id=?',
                    (now, user_id)
                )
        else:
            conn.execute(
                'INSERT INTO merit_records (user_id, total_count, today_count, today_date, updated_at) VALUES (?, 1, 1, ?, ?)',
                (user_id, today, now)
            )

        conn.commit()

        # 返回更新后的数据
        row = conn.execute('SELECT * FROM merit_records WHERE user_id=?', (user_id,)).fetchone()
        return dict(row) if row else {'total_count': 1, 'today_count': 1, 'today_date': today}
    finally:
        conn.close()


# ==================== 上传会话（替代 {upload_id}.json + 文件锁） ====================

def create_upload_session(upload_id, filename, total_chunks, chunk_size, file_size):
    """创建上传会话"""
    conn = get_db()
    try:
        now = time.time()
        conn.execute(
            'INSERT OR REPLACE INTO upload_sessions (upload_id, filename, total_chunks, chunk_size, file_size, received_chunks, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (upload_id, filename, total_chunks, chunk_size, file_size, '[]', now, now)
        )
        conn.commit()
    finally:
        conn.close()


def get_upload_session(upload_id):
    """获取上传会话"""
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM upload_sessions WHERE upload_id=?', (upload_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data['received_chunks'] = json.loads(data.get('received_chunks', '[]'))
        except (json.JSONDecodeError, TypeError):
            data['received_chunks'] = []
        data['received_set'] = set(data['received_chunks'])
        return data
    finally:
        conn.close()


def add_received_chunk(upload_id, chunk_index):
    """添加已接收分块（原子操作，替代文件锁）"""
    conn = get_db()
    try:
        now = time.time()
        # SQLite 原子读取-修改-写入：使用事务
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT received_chunks FROM upload_sessions WHERE upload_id=?', (upload_id,)).fetchone()
        if not row:
            conn.execute('ROLLBACK')
            return None

        try:
            chunks = json.loads(row['received_chunks'])
        except (json.JSONDecodeError, TypeError):
            chunks = []

        if chunk_index not in chunks:
            chunks.append(chunk_index)

        conn.execute(
            'UPDATE upload_sessions SET received_chunks=?, updated_at=? WHERE upload_id=?',
            (json.dumps(chunks), now, upload_id)
        )
        conn.execute('COMMIT')

        # 返回完整会话信息
        return get_upload_session(upload_id)
    except Exception:
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        return None
    finally:
        conn.close()


def delete_upload_session(upload_id):
    """删除上传会话"""
    conn = get_db()
    try:
        conn.execute('DELETE FROM upload_sessions WHERE upload_id=?', (upload_id,))
        conn.commit()
    finally:
        conn.close()


# ==================== 后台任务（替代 {task_id}.json） ====================

def create_task(task_id, task_type):
    """创建后台任务"""
    conn = get_db()
    try:
        now = time.time()
        conn.execute(
            'INSERT OR REPLACE INTO background_tasks (task_id, task_type, status, progress, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (task_id, task_type, 'pending', 0, now, now)
        )
        conn.commit()
    finally:
        conn.close()


def update_task(task_id, status=None, progress=None, result=None, error=None):
    """更新后台任务状态"""
    conn = get_db()
    try:
        now = time.time()
        updates = ['updated_at=?']
        params = [now]

        if status is not None:
            updates.append('status=?')
            params.append(status)
        if progress is not None:
            updates.append('progress=?')
            params.append(progress)
        if result is not None:
            result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
            updates.append('result=?')
            params.append(result_str)
        if error is not None:
            updates.append('error=?')
            params.append(error)

        params.append(task_id)
        conn.execute(
            f'UPDATE background_tasks SET {", ".join(updates)} WHERE task_id=?',
            params
        )
        conn.commit()
    finally:
        conn.close()


def get_task(task_id):
    """获取后台任务"""
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM background_tasks WHERE task_id=?', (task_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        if data.get('result'):
            try:
                data['result'] = json.loads(data['result'])
            except (json.JSONDecodeError, TypeError):
                pass
        return data
    finally:
        conn.close()


def delete_task(task_id):
    """删除后台任务"""
    conn = get_db()
    try:
        conn.execute('DELETE FROM background_tasks WHERE task_id=?', (task_id,))
        conn.commit()
    finally:
        conn.close()


def cleanup_old_tasks(max_age_hours=24):
    """清理过期任务"""
    conn = get_db()
    try:
        cutoff = time.time() - max_age_hours * 3600
        conn.execute('DELETE FROM background_tasks WHERE updated_at < ? AND status IN (?, ?)', (cutoff, 'done', 'error'))
        conn.execute('DELETE FROM upload_sessions WHERE updated_at < ?', (cutoff,))
        conn.commit()
    finally:
        conn.close()


# ==================== 用户偏好（主题模式等） ====================

def get_user_preferences(user_id):
    """获取用户偏好"""
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM user_preferences WHERE user_id=?', (user_id,)).fetchone()
        if not row:
            return {'theme': 'auto', 'language': 'zh-CN'}
        return dict(row)
    finally:
        conn.close()


def set_user_preferences(user_id, theme=None, language=None):
    """更新用户偏好"""
    conn = get_db()
    try:
        now = time.time()
        # 先检查是否存在
        row = conn.execute('SELECT user_id FROM user_preferences WHERE user_id=?', (user_id,)).fetchone()
        if row:
            updates = ['updated_at=?']
            params = [now]
            if theme is not None:
                updates.append('theme=?')
                params.append(theme)
            if language is not None:
                updates.append('language=?')
                params.append(language)
            params.append(user_id)
            conn.execute(
                f'UPDATE user_preferences SET {", ".join(updates)} WHERE user_id=?',
                params
            )
        else:
            conn.execute(
                'INSERT INTO user_preferences (user_id, theme, language, updated_at) VALUES (?, ?, ?, ?)',
                (user_id, theme or 'auto', language or 'zh-CN', now)
            )
        conn.commit()
    finally:
        conn.close()


# ==================== JSON 文件迁移 ====================

def migrate_json_config(config_path, config_key):
    """将 JSON 配置文件迁移到数据库（仅首次启动时执行）"""
    if not os.path.exists(config_path):
        return False

    # 检查数据库是否已有该配置
    existing = get_config(config_key)
    if existing is not None:
        return False  # 已迁移过

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        set_config(config_key, data)
        logger.info(f"配置 {config_key} 已从 {config_path} 迁移到数据库")
        return True
    except Exception as e:
        logger.warning(f"迁移配置 {config_key} 失败: {e}")
        return False


# 启动时初始化
init_db()

# 执行 JSON 文件迁移（静默失败，不影响启动）
_runtime_config_path = os.path.join(_RUNTIME_DIR, 'ai_config.json')
if not os.path.exists(_runtime_config_path):
    _runtime_config_path = os.path.join(os.path.dirname(__file__), 'ai_config.json')
migrate_json_config(_runtime_config_path, 'ai_config')

# 清理过期任务
try:
    cleanup_old_tasks()
except Exception as e:
    logger.warning(f"清理过期任务失败: {e}")
