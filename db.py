"""
数据库模块 v3.0 - 双数据库支持
支持 PostgreSQL（生产环境）和 SQLite（本地开发）
通过 DATABASE_URL 环境变量自动切换

升级说明（v3.0）：
- 从 sqlite3 原生驱动迁移到 SQLAlchemy 引擎
- 支持 PostgreSQL（生产）和 SQLite（本地）双模式
- 所有 SQL 使用命名参数（:param），跨数据库兼容
- 连接池管理，提升并发性能
- 保持 v2.0 全部 API 不变，向下兼容
"""
import os
import json
import time
import logging
from sqlalchemy import create_engine, text
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ==================== 数据库引擎初始化 ====================

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()

if DATABASE_URL:
    # PostgreSQL（生产环境 — Railway / Heroku 等）
    # Railway 提供 postgres:// 前缀，SQLAlchemy 需要 postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,      # 连接前检查有效性，防止使用已断开的连接
        pool_size=5,             # 连接池大小
        max_overflow=10,         # 允许超出连接池的临时连接数
        pool_recycle=300,        # 5 分钟回收连接，防止数据库端超时断开
    )
    DB_TYPE = 'postgresql'
    logger.info("数据库: PostgreSQL (生产模式)")
else:
    # SQLite（本地开发）
    _RUNTIME_DIR = os.environ.get('DB_DIR', '/tmp/toolbox')
    os.makedirs(_RUNTIME_DIR, exist_ok=True)
    _SQLITE_PATH = os.path.join(_RUNTIME_DIR, 'users.db')
    engine = create_engine(
        f'sqlite:///{_SQLITE_PATH}',
        pool_pre_ping=True,
        connect_args={'timeout': 10, 'check_same_thread': False},
    )
    DB_TYPE = 'sqlite'
    logger.info(f"数据库: SQLite (本地模式) — {_SQLITE_PATH}")

# 自增主键类型（数据库差异）
_PK_TYPE = 'SERIAL PRIMARY KEY' if DB_TYPE == 'postgresql' else 'INTEGER PRIMARY KEY AUTOINCREMENT'


def _row_to_dict(row):
    """将 SQLAlchemy Row 转为 dict"""
    if row is None:
        return None
    return dict(row._mapping)


def check_db():
    """检查数据库连接是否正常"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {'status': 'ok', 'type': DB_TYPE}
    except Exception as e:
        return {'status': 'error', 'type': DB_TYPE, 'error': str(e)}


def init_db():
    """初始化所有数据库表"""
    with engine.begin() as conn:
        # SQLite 专属优化
        if DB_TYPE == 'sqlite':
            conn.execute(text("PRAGMA journal_mode = WAL"))
            conn.execute(text("PRAGMA busy_timeout = 5000"))

        # ==================== 用户表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS users (
                id {_PK_TYPE},
                provider TEXT NOT NULL,
                provider_uid TEXT NOT NULL,
                name TEXT,
                email TEXT,
                avatar TEXT,
                created_at REAL DEFAULT 0,
                last_login REAL DEFAULT 0,
                UNIQUE(provider, provider_uid)
            )
        """))

        # ==================== 用户数据表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS user_data (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                data_type TEXT NOT NULL,
                title TEXT,
                content TEXT,
                created_at REAL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))

        # ==================== 应用配置表 ====================
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at REAL DEFAULT 0
            )
        """))

        # ==================== 功德记录表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS merit_records (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                total_count INTEGER DEFAULT 0,
                today_count INTEGER DEFAULT 0,
                today_date TEXT,
                updated_at REAL DEFAULT 0,
                UNIQUE(user_id)
            )
        """))

        # ==================== 上传会话表 ====================
        conn.execute(text("""
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
        """))

        # ==================== 后台任务表 ====================
        conn.execute(text("""
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
        """))

        # ==================== 用户偏好表 ====================
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                theme TEXT DEFAULT 'auto',
                language TEXT DEFAULT 'zh-CN',
                accent_color TEXT DEFAULT '',
                updated_at REAL DEFAULT 0
            )
        """))
        # v3.0: 确保 accent_color 列存在（兼容旧表）
        try:
            conn.execute(text("ALTER TABLE user_preferences ADD COLUMN accent_color TEXT DEFAULT ''"))
        except Exception:
            pass  # 列已存在

        # v3.1: 添加 ai_config 列用于存储用户级 AI 配置
        try:
            conn.execute(text("ALTER TABLE user_preferences ADD COLUMN ai_config TEXT DEFAULT ''"))
        except Exception:
            pass  # 列已存在

        # v5.0: 添加 feishu_webhook 列用于飞书推送
        try:
            conn.execute(text("ALTER TABLE user_preferences ADD COLUMN feishu_webhook TEXT DEFAULT ''"))
        except Exception:
            pass  # 列已存在

        # ==================== 索引 ====================
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_data ON user_data(user_id, data_type)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_provider ON users(provider, provider_uid)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_merit_user ON merit_records(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_status ON background_tasks(status)"))

    logger.info(f"数据库 v3.0 初始化完成 ({DB_TYPE})")


# ==================== 用户相关 ====================

def upsert_user(provider, provider_uid, name, email, avatar):
    """创建或更新用户，返回用户ID"""
    with engine.begin() as conn:
        now = time.time()
        row = conn.execute(
            text("SELECT id FROM users WHERE provider = :provider AND provider_uid = :provider_uid"),
            {'provider': provider, 'provider_uid': provider_uid}
        ).fetchone()

        if row:
            user_id = row[0]
            conn.execute(
                text("UPDATE users SET name = :name, email = :email, avatar = :avatar, last_login = :last_login WHERE id = :id"),
                {'name': name, 'email': email, 'avatar': avatar, 'last_login': now, 'id': user_id}
            )
            return user_id
        else:
            result = conn.execute(
                text("""
                    INSERT INTO users (provider, provider_uid, name, email, avatar, created_at, last_login)
                    VALUES (:provider, :provider_uid, :name, :email, :avatar, :created_at, :last_login)
                    RETURNING id
                """),
                {'provider': provider, 'provider_uid': provider_uid, 'name': name, 'email': email,
                 'avatar': avatar, 'created_at': now, 'last_login': now}
            )
            return result.scalar()


def get_user_by_id(user_id):
    """根据ID获取用户信息"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM users WHERE id = :id"),
            {'id': user_id}
        ).fetchone()
        return _row_to_dict(row)


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


# ==================== 应用配置 ====================

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

def get_merit(user_id):
    """获取用户功德数据"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT total_count, today_count, today_date FROM merit_records WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()
        if not row:
            return {'total_count': 0, 'today_count': 0, 'today_date': ''}
        m = row._mapping
        return {'total_count': m['total_count'], 'today_count': m['today_count'], 'today_date': m['today_date']}


def increment_merit(user_id):
    """功德+1（原子操作，自动处理日期切换）"""
    with engine.begin() as conn:
        now = time.time()
        today = time.strftime('%Y-%m-%d', time.localtime(now))

        row = conn.execute(
            text("SELECT today_date FROM merit_records WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()

        if row:
            if row[0] != today:
                conn.execute(
                    text("UPDATE merit_records SET total_count = total_count + 1, today_count = 1, today_date = :today, updated_at = :updated_at WHERE user_id = :user_id"),
                    {'today': today, 'updated_at': now, 'user_id': user_id}
                )
            else:
                conn.execute(
                    text("UPDATE merit_records SET total_count = total_count + 1, today_count = today_count + 1, updated_at = :updated_at WHERE user_id = :user_id"),
                    {'updated_at': now, 'user_id': user_id}
                )
        else:
            conn.execute(
                text("INSERT INTO merit_records (user_id, total_count, today_count, today_date, updated_at) VALUES (:user_id, 1, 1, :today, :updated_at)"),
                {'user_id': user_id, 'today': today, 'updated_at': now}
            )

    # 返回更新后的数据（事务已提交，新连接可见）
    return get_merit(user_id)


# ==================== 上传会话 ====================

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


# ==================== 用户级 AI 配置 ====================

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


# ==================== 启动时初始化 ====================

init_db()

# 执行 JSON 文件迁移（静默失败，不影响启动）
_runtime_dir = os.environ.get('DB_DIR', '/tmp/toolbox')
_runtime_config_path = os.path.join(_runtime_dir, 'ai_config.json')
if not os.path.exists(_runtime_config_path):
    _runtime_config_path = os.path.join(os.path.dirname(__file__), 'ai_config.json')
migrate_json_config(_runtime_config_path, 'ai_config')

# 清理过期任务
try:
    cleanup_old_tasks()
except Exception as e:
    logger.warning(f"清理过期任务失败: {e}")
