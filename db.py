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
# 默认使用本地 SQLite，数据持久化存储在 /app/data 目录（Railway Volume 挂载点）
# 如需使用 PostgreSQL，设置环境变量 DATABASE_URL（以 postgres:// 或 postgresql:// 开头）
# Railway 平台会自动注入 DATABASE_URL，无需额外设置 USE_POSTGRES

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
USE_POSTGRES = os.environ.get('USE_POSTGRES', '').lower() == 'true' or bool(DATABASE_URL)

# 连接池配置（可通过环境变量覆盖）
PG_POOL_SIZE = int(os.environ.get('PG_POOL_SIZE', '5'))
PG_MAX_OVERFLOW = int(os.environ.get('PG_MAX_OVERFLOW', '10'))
PG_POOL_RECYCLE = int(os.environ.get('PG_POOL_RECYCLE', '300'))

if USE_POSTGRES and DATABASE_URL:
    # PostgreSQL（生产环境，Railway 自动注入 DATABASE_URL）
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=PG_POOL_SIZE,
        max_overflow=PG_MAX_OVERFLOW,
        pool_recycle=PG_POOL_RECYCLE,
        pool_use_lifo=True,
    )
    DB_TYPE = 'postgresql'
    logger.info(f"数据库: PostgreSQL (生产模式) pool_size={PG_POOL_SIZE} max_overflow={PG_MAX_OVERFLOW}")
else:
    # SQLite（默认，本地存储）
    _RUNTIME_DIR = os.environ.get('DB_DIR', '/app/data')
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
                username TEXT DEFAULT '',
                password_hash TEXT DEFAULT '',
                is_admin INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0,
                last_login REAL DEFAULT 0,
                UNIQUE(provider, provider_uid)
            )
        """))

        # v9.0: 账号密码登录 — 为旧表迁移新增 username / password_hash 列
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN username TEXT DEFAULT ''"))
        except Exception:
            pass  # 列已存在
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''"))
        except Exception:
            pass  # 列已存在

        # v9.1: 添加 is_admin 字段（管理员权限）
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0"))
        except Exception:
            pass  # 列已存在

        # v10.0: 用户系统增强 — 新增昵称、部门、角色、技能标签
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN nickname TEXT DEFAULT ''"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN department TEXT DEFAULT ''"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'member'"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN skills TEXT DEFAULT '[]'"))
        except Exception:
            pass

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

        # v5.1: 添加 feishu_secret 列用于飞书签名校验
        try:
            conn.execute(text("ALTER TABLE user_preferences ADD COLUMN feishu_secret TEXT DEFAULT ''"))
        except Exception:
            pass  # 列已存在

        # ==================== 索引 ====================
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_data ON user_data(user_id, data_type)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_provider ON users(provider, provider_uid)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_merit_user ON merit_records(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_status ON background_tasks(status)"))

        # ==================== v5.3 协作：共享工作空间表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS shared_workspaces (
                id {_PK_TYPE},
                share_code TEXT NOT NULL UNIQUE,
                owner_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                tool_type TEXT DEFAULT '',
                data_ref TEXT DEFAULT '',
                permission TEXT DEFAULT 'view',
                expires_at REAL DEFAULT 0,
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0,
                FOREIGN KEY (owner_id) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_workspace_owner ON shared_workspaces(owner_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_workspace_code ON shared_workspaces(share_code)"))

        # ==================== v5.3 协作：评论表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS workspace_comments (
                id {_PK_TYPE},
                workspace_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                parent_id INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0,
                FOREIGN KEY (workspace_id) REFERENCES shared_workspaces(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_comments_workspace ON workspace_comments(workspace_id)"))

        # ==================== v5.3 协作：协作者表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS workspace_members (
                id {_PK_TYPE},
                workspace_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT DEFAULT 'viewer',
                joined_at REAL DEFAULT 0,
                UNIQUE(workspace_id, user_id),
                FOREIGN KEY (workspace_id) REFERENCES shared_workspaces(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))

        # v7.0: 为 shared_workspaces 添加密码保护和访问次数限制列
        try:
            conn.execute(text("ALTER TABLE shared_workspaces ADD COLUMN password TEXT DEFAULT ''"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE shared_workspaces ADD COLUMN access_limit INTEGER DEFAULT 0"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE shared_workspaces ADD COLUMN access_count INTEGER DEFAULT 0"))
        except Exception:
            pass

        # ==================== v7.0 协作深化：增强协作者状态表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS collab_members (
                id {_PK_TYPE},
                workspace_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT DEFAULT 'viewer',
                last_active REAL DEFAULT 0,
                viewing_area TEXT DEFAULT '',
                is_editing INTEGER DEFAULT 0,
                editing_area TEXT DEFAULT '',
                joined_at REAL DEFAULT 0,
                UNIQUE(workspace_id, user_id),
                FOREIGN KEY (workspace_id) REFERENCES shared_workspaces(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collab_members_ws ON collab_members(workspace_id)"))

        # ==================== v7.0 协作深化：增强评论表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS collab_comments (
                id {_PK_TYPE},
                workspace_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                parent_id INTEGER DEFAULT 0,
                mentions TEXT DEFAULT '[]',
                is_resolved INTEGER DEFAULT 0,
                resolved_by INTEGER DEFAULT 0,
                resolved_at REAL DEFAULT 0,
                edited_at REAL DEFAULT 0,
                created_at REAL DEFAULT 0,
                FOREIGN KEY (workspace_id) REFERENCES shared_workspaces(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collab_comments_ws ON collab_comments(workspace_id)"))

        # ==================== v7.0 协作深化：活动记录表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS collab_activity (
                id {_PK_TYPE},
                workspace_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                action_detail TEXT DEFAULT '',
                created_at REAL DEFAULT 0,
                FOREIGN KEY (workspace_id) REFERENCES shared_workspaces(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collab_activity_ws ON collab_activity(workspace_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collab_activity_type ON collab_activity(action_type)"))

        # ==================== v7.0 协作深化：团队工作空间表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS team_spaces (
                id {_PK_TYPE},
                team_code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                description TEXT DEFAULT '',
                config TEXT DEFAULT '{{}}',
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0,
                FOREIGN KEY (owner_id) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_team_owner ON team_spaces(owner_id)"))

        # ==================== v7.0 协作深化：团队成员表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS team_members (
                id {_PK_TYPE},
                team_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT DEFAULT 'member',
                joined_at REAL DEFAULT 0,
                UNIQUE(team_id, user_id),
                FOREIGN KEY (team_id) REFERENCES team_spaces(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_team_members_team ON team_members(team_id)"))

        # v11.0: 团队设置列（兼容旧表）
        try:
            conn.execute(text("ALTER TABLE team_spaces ADD COLUMN settings TEXT DEFAULT '{}'"))
        except Exception:
            pass

        # ==================== v11.0 团队数据共享表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS team_data (
                id {_PK_TYPE},
                team_id INTEGER NOT NULL,
                data_type TEXT NOT NULL,
                data_ref TEXT DEFAULT '',
                title TEXT DEFAULT '',
                shared_by INTEGER NOT NULL,
                permissions TEXT DEFAULT '{{}}',
                created_at REAL DEFAULT 0,
                FOREIGN KEY (team_id) REFERENCES team_spaces(id),
                FOREIGN KEY (shared_by) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_team_data_team ON team_data(team_id, data_type)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_team_data_shared_by ON team_data(shared_by)"))

        # ==================== v8.0 牛马笔记：独立笔记表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS notes (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                note_uid TEXT NOT NULL,
                title TEXT DEFAULT '',
                content TEXT DEFAULT '',
                category TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                is_todo INTEGER DEFAULT 0,
                pinned INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0,
                UNIQUE(user_id, note_uid),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(user_id, updated_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(user_id, category)"))

        # ==================== v8.0 数据可视化：图表模板表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS chart_templates (
                id {_PK_TYPE},
                user_id TEXT NOT NULL DEFAULT 'guest',
                name TEXT NOT NULL,
                chart_type TEXT NOT NULL,
                config TEXT NOT NULL,
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chart_templates_user ON chart_templates(user_id)"))

        # ==================== v8.0 数据可视化：Dashboard 配置表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS dashboard_config (
                id {_PK_TYPE},
                user_id TEXT NOT NULL DEFAULT 'guest',
                config_key TEXT NOT NULL,
                config_value TEXT NOT NULL,
                updated_at REAL DEFAULT 0,
                UNIQUE(user_id, config_key)
            )
        """))

        # ==================== v9.2 用户活动追踪表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS user_activity (
                id {_PK_TYPE},
                user_id INTEGER,
                tool_id TEXT NOT NULL,
                tool_name TEXT,
                action TEXT DEFAULT 'view',
                path TEXT,
                method TEXT DEFAULT 'GET',
                status_code INTEGER DEFAULT 200,
                duration_ms REAL DEFAULT 0,
                ip TEXT,
                created_at REAL DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_activity_user ON user_activity(user_id, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_activity_tool ON user_activity(tool_id, created_at)"))

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
            # 第一个注册的用户自动成为管理员
            count_row = conn.execute(text("SELECT COUNT(*) as cnt FROM users")).fetchone()
            is_admin = 1 if (count_row and count_row[0] == 0) else 0
            result = conn.execute(
                text("""
                    INSERT INTO users (provider, provider_uid, name, email, avatar, created_at, last_login, is_admin)
                    VALUES (:provider, :provider_uid, :name, :email, :avatar, :created_at, :last_login, :is_admin)
                    RETURNING id
                """),
                {'provider': provider, 'provider_uid': provider_uid, 'name': name, 'email': email,
                 'avatar': avatar, 'created_at': now, 'last_login': now, 'is_admin': is_admin}
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


def get_user_profile(user_id):
    """获取用户完整资料（含昵称、部门、角色、技能标签）"""
    user = get_user_by_id(user_id)
    if not user:
        return None
    # 解析 skills JSON
    skills_raw = user.get('skills') or '[]'
    try:
        user['skills'] = json.loads(skills_raw) if isinstance(skills_raw, str) else skills_raw
    except (json.JSONDecodeError, TypeError):
        user['skills'] = []
    return user


def update_user_profile(user_id, profile_data):
    """更新用户资料，返回是否成功。
    profile_data 可包含: name, nickname, avatar, department, role, skills(list)
    """
    if not profile_data:
        return False
    allowed_fields = {'name', 'nickname', 'avatar', 'department', 'role'}
    sets = []
    params = {'id': user_id}
    for key, value in profile_data.items():
        if key in allowed_fields and value is not None:
            sets.append(f"{key} = :{key}")
            params[key] = str(value)
    # skills 单独处理（JSON 序列化）
    if 'skills' in profile_data and profile_data['skills'] is not None:
        skills_val = profile_data['skills']
        if isinstance(skills_val, str):
            try:
                json.loads(skills_val)  # 验证是合法 JSON
                params['skills'] = skills_val
            except (json.JSONDecodeError, TypeError):
                params['skills'] = json.dumps([], ensure_ascii=False)
        else:
            params['skills'] = json.dumps(skills_val, ensure_ascii=False)
        sets.append("skills = :skills")
    if not sets:
        return False
    with engine.begin() as conn:
        result = conn.execute(
            text(f"UPDATE users SET {', '.join(sets)} WHERE id = :id"),
            params
        )
        return result.rowcount > 0


# ==================== v9.0 账号密码登录 ====================

from werkzeug.security import generate_password_hash, check_password_hash


def create_user_with_password(username, email, password):
    """创建账号密码用户，返回用户ID；用户名或邮箱已存在返回 None"""
    username = (username or '').strip()
    email = (email or '').strip().lower()
    if not username or not password:
        return None
    with engine.begin() as conn:
        now = time.time()
        # 唯一性校验：用户名或邮箱已存在则拒绝
        existing = conn.execute(
            text("SELECT id FROM users WHERE username = :username OR (email = :email AND email != '')"),
            {'username': username, 'email': email}
        ).fetchone()
        if existing:
            return None
        # 第一个注册的用户自动成为管理员
        count_row = conn.execute(text("SELECT COUNT(*) as cnt FROM users")).fetchone()
        is_admin = 1 if (count_row and count_row[0] == 0) else 0
        pw_hash = generate_password_hash(password)
        result = conn.execute(
            text("""
                INSERT INTO users (provider, provider_uid, name, email, username, password_hash, created_at, last_login, is_admin)
                VALUES ('local', :provider_uid, :name, :email, :username, :password_hash, :created_at, :last_login, :is_admin)
                RETURNING id
            """),
            {
                'provider_uid': f'local:{username}',
                'name': username,
                'email': email,
                'username': username,
                'password_hash': pw_hash,
                'created_at': now,
                'last_login': now,
                'is_admin': is_admin,
            }
        )
        return result.scalar()


def get_user_by_username(username):
    """根据用户名获取用户"""
    if not username:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM users WHERE username = :username"),
            {'username': username.strip()}
        ).fetchone()
        return _row_to_dict(row)


def get_user_by_email(email):
    """根据邮箱获取用户"""
    if not email:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM users WHERE email = :email"),
            {'email': email.strip().lower()}
        ).fetchone()
        return _row_to_dict(row)


def verify_user_password(username_or_email, password):
    """验证用户名/邮箱 + 密码，返回用户 dict 或 None"""
    if not username_or_email or not password:
        return None
    key = username_or_email.strip()
    user = get_user_by_username(key)
    if not user and '@' in key:
        user = get_user_by_email(key)
    if not user:
        return None
    pw_hash = user.get('password_hash') or ''
    if not pw_hash:
        return None
    if check_password_hash(pw_hash, password):
        return user
    return None


def update_user_password(user_id, new_password):
    """更新用户密码，返回是否成功"""
    if not new_password:
        return False
    pw_hash = generate_password_hash(new_password)
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE users SET password_hash = :password_hash WHERE id = :id"),
            {'password_hash': pw_hash, 'id': user_id}
        )
        return result.rowcount > 0


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
_TOOL_PATH_MAP = {
    '/': ('home', '首页'),
    '/excel-analysis': ('cr-analysis', 'CR问题分析'),
    '/log-analyzer': ('log-analyzer', '日志根因分析'),
    '/knowledge-graph': ('knowledge-graph', '知识图谱'),
    '/test-report': ('test-report', '测试报告分析'),
    '/bug-trend': ('bug-trend', 'Bug趋势看板'),
    '/mttf-dashboard': ('mttf-dashboard', 'MTTF可靠性看板'),
    '/dashboard': ('dashboard', '研发健康度'),
    '/hld': ('hld-generator', 'HLD生成器'),
    '/plan-generator': ('plan-generator', '计划生成器'),
    '/project-info': ('project-info', '项目信息收集'),
    '/meeting-minutes': ('meeting-minutes', '会议纪要'),
    '/weekly-report': ('weekly-report', '智能周报'),
    '/daily-standup': ('daily-standup', '每日站会'),
    '/translator': ('translator', 'IT翻译器'),
    '/email-assistant': ('email-assistant', '邮件助手'),
    '/md2pdf': ('md2pdf', 'PDF快转'),
    '/data-viz': ('data-viz', '数据可视化'),
    '/notes': ('notes', '牛马笔记'),
    '/merit': ('merit', '电子木鱼'),
    '/settings': ('settings', '系统设置'),
    '/my-activity': ('my-activity', '我的活动'),
    '/admin/users': ('admin-users', '用户管理'),
    '/teams': ('teams', '团队空间'),
}


def resolve_tool_id(path):
    """从请求路径解析工具 ID 和名称"""
    # 精确匹配
    if path in _TOOL_PATH_MAP:
        return _TOOL_PATH_MAP[path]
    # 前缀匹配（如 /hld/api/generate -> hld-generator）
    for prefix, (tool_id, tool_name) in _TOOL_PATH_MAP.items():
        if path.startswith(prefix + '/') or path.startswith(prefix + '?'):
            return tool_id, tool_name
    # API 路径映射
    if path.startswith('/api/excel-analyze'):
        return 'cr-analysis', 'CR问题分析'
    if path.startswith('/api/translate'):
        return 'translator', 'IT翻译器'
    if path.startswith('/hld/'):
        return 'hld-generator', 'HLD生成器'
    if path.startswith('/api/notes'):
        return 'notes', '牛马笔记'
    if path.startswith('/api/jira-search'):
        return 'cr-analysis', 'CR问题分析'
    return None, None


def log_user_activity(user_id, tool_id, tool_name=None, action='view',
                      path=None, method='GET', status_code=200, duration_ms=0, ip=None):
    """记录用户活动（非阻塞，失败不影响请求）"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO user_activity
                        (user_id, tool_id, tool_name, action, path, method, status_code, duration_ms, ip, created_at)
                    VALUES
                        (:user_id, :tool_id, :tool_name, :action, :path, :method, :status_code, :duration_ms, :ip, :created_at)
                """),
                {
                    'user_id': user_id,
                    'tool_id': tool_id,
                    'tool_name': tool_name or '',
                    'action': action,
                    'path': path or '',
                    'method': method,
                    'status_code': status_code,
                    'duration_ms': duration_ms,
                    'ip': ip or '',
                    'created_at': time.time(),
                }
            )
    except Exception as e:
        logger.debug(f"记录用户活动失败（不影响请求）: {e}")


def get_user_activity_stats(user_id, days=30):
    """获取用户活动统计

    Returns:
        {
            'total_requests': int,
            'tools_used': [{tool_id, tool_name, count, last_used}],
            'daily_activity': [{date, count}],
            'top_tools': [{tool_id, tool_name, count, percentage}],
        }
    """
    now = time.time()
    since = now - days * 86400
    try:
        with engine.connect() as conn:
            # 总请求数
            total = conn.execute(
                text("SELECT COUNT(*) FROM user_activity WHERE user_id = :uid AND created_at >= :since"),
                {'uid': user_id, 'since': since}
            ).scalar() or 0

            # 工具使用统计
            tools = conn.execute(
                text("""
                    SELECT tool_id, tool_name, COUNT(*) as cnt, MAX(created_at) as last_used
                    FROM user_activity
                    WHERE user_id = :uid AND created_at >= :since AND tool_id IS NOT NULL
                    GROUP BY tool_id, tool_name
                    ORDER BY cnt DESC
                """),
                {'uid': user_id, 'since': since}
            ).fetchall()

            tools_used = []
            for row in tools:
                tools_used.append({
                    'tool_id': row[0],
                    'tool_name': row[1] or row[0],
                    'count': row[2],
                    'last_used': row[3],
                })

            # 每日活动（跨数据库兼容日期格式化）
            if DB_TYPE == 'postgresql':
                date_expr = "to_char(to_timestamp(created_at), 'YYYY-MM-DD')"
            else:
                date_expr = "DATE(created_at, 'unixepoch', 'localtime')"
            daily = conn.execute(
                text(f"""
                    SELECT {date_expr} as d, COUNT(*) as cnt
                    FROM user_activity
                    WHERE user_id = :uid AND created_at >= :since
                    GROUP BY d
                    ORDER BY d
                """),
                {'uid': user_id, 'since': since}
            ).fetchall()

            daily_activity = [{'date': row[0], 'count': row[1]} for row in daily]

            # Top 工具（百分比）
            top_tools = []
            if total > 0:
                for t in tools_used[:5]:
                    top_tools.append({
                        'tool_id': t['tool_id'],
                        'tool_name': t['tool_name'],
                        'count': t['count'],
                        'percentage': round(t['count'] * 100 / total, 1),
                    })

            return {
                'total_requests': total,
                'tools_used': tools_used,
                'daily_activity': daily_activity,
                'top_tools': top_tools,
                'days': days,
            }
    except Exception as e:
        logger.error(f"获取用户活动统计失败: {e}")
        return {
            'total_requests': 0,
            'tools_used': [],
            'daily_activity': [],
            'top_tools': [],
            'days': days,
        }


def cleanup_old_activity(max_age_days=90):
    """清理过期的活动记录"""
    try:
        cutoff = time.time() - max_age_days * 86400
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM user_activity WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
    except Exception as e:
        logger.error(f"清理活动记录失败: {e}")


def global_search(user_id, query, limit=20):
    """全局搜索：跨笔记、用户数据、图表模板搜索

    Args:
        user_id: 用户 ID
        query: 搜索关键词
        limit: 每类最大结果数

    Returns:
        {
            'notes': [{id, title, content_preview, category, created_at}],
            'user_data': [{id, data_type, title, content_preview, created_at}],
            'charts': [{id, name, chart_type, created_at}],
            'total': int,
        }
    """
    if not query or len(query.strip()) < 1:
        return {'notes': [], 'user_data': [], 'charts': [], 'total': 0}

    q = f"%{query.strip()}%"
    results = {'notes': [], 'user_data': [], 'charts': [], 'total': 0}

    try:
        with engine.connect() as conn:
            # 搜索笔记
            note_rows = conn.execute(
                text("""
                    SELECT id, title, content, category, tags, created_at
                    FROM notes
                    WHERE user_id = :uid
                      AND (title LIKE :q OR content LIKE :q OR tags LIKE :q)
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {'uid': user_id, 'q': q, 'limit': limit}
            ).fetchall()
            for row in note_rows:
                content = row[2] or ''
                results['notes'].append({
                    'id': row[0],
                    'title': row[1] or '无标题',
                    'content_preview': content[:200] + ('...' if len(content) > 200 else ''),
                    'category': row[3] or '',
                    'created_at': row[5],
                })

            # 搜索用户数据（CR分析、HLD等）
            data_rows = conn.execute(
                text("""
                    SELECT id, data_type, title, content, created_at
                    FROM user_data
                    WHERE user_id = :uid
                      AND (title LIKE :q OR content LIKE :q)
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {'uid': user_id, 'q': q, 'limit': limit}
            ).fetchall()
            for row in data_rows:
                content_str = str(row[3] or '')
                results['user_data'].append({
                    'id': row[0],
                    'data_type': row[1] or '',
                    'title': row[2] or '无标题',
                    'content_preview': content_str[:200] + ('...' if len(content_str) > 200 else ''),
                    'created_at': row[4],
                })

            # 搜索图表模板
            chart_rows = conn.execute(
                text("""
                    SELECT id, name, chart_type, created_at
                    FROM chart_templates
                    WHERE user_id = :uid AND name LIKE :q
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {'uid': str(user_id), 'q': q, 'limit': limit}
            ).fetchall()
            for row in chart_rows:
                results['charts'].append({
                    'id': row[0],
                    'name': row[1],
                    'chart_type': row[2],
                    'created_at': row[3],
                })

            results['total'] = len(results['notes']) + len(results['user_data']) + len(results['charts'])
            return results

    except Exception as e:
        logger.error(f"全局搜索失败: {e}")
        return results


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


# ==================== v5.2 多设备数据同步 ====================

# 同步数据类型白名单
SYNC_TYPES = {'favorites', 'recent', 'notes', 'merit', 'projects', 'plans', 'theme', 'form_drafts', 'settings'}


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

import secrets as _secrets

def _generate_share_code():
    """生成 8 位唯一分享码"""
    return _secrets.token_urlsafe(6)[:8].replace('-', 'a').replace('_', 'b')

def create_workspace(owner_id, title, tool_type='', data_ref='', permission='view', expires_at=0):
    """创建共享工作空间，返回分享码"""
    with engine.begin() as conn:
        now = time.time()
        # 生成唯一分享码（最多重试 5 次）
        for _ in range(5):
            share_code = _generate_share_code()
            existing = conn.execute(
                text("SELECT id FROM shared_workspaces WHERE share_code = :code"),
                {'code': share_code}
            ).fetchone()
            if not existing:
                break
        result = conn.execute(
            text("""
                INSERT INTO shared_workspaces (share_code, owner_id, title, tool_type, data_ref, permission, expires_at, created_at, updated_at)
                VALUES (:share_code, :owner_id, :title, :tool_type, :data_ref, :permission, :expires_at, :created_at, :updated_at)
                RETURNING id
            """),
            {'share_code': share_code, 'owner_id': owner_id, 'title': title,
             'tool_type': tool_type, 'data_ref': data_ref, 'permission': permission,
             'expires_at': expires_at, 'created_at': now, 'updated_at': now}
        )
        ws_id = result.scalar()
        # 所有者自动加入成员
        conn.execute(
            text("""
                INSERT INTO workspace_members (workspace_id, user_id, role, joined_at)
                VALUES (:ws_id, :user_id, 'owner', :joined_at)
                ON CONFLICT(workspace_id, user_id) DO UPDATE SET role = 'owner'
            """),
            {'ws_id': ws_id, 'user_id': owner_id, 'joined_at': now}
        )
        return share_code

def get_workspace_by_code(share_code):
    """根据分享码获取工作空间"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM shared_workspaces WHERE share_code = :code"),
            {'code': share_code}
        ).fetchone()
        if not row:
            return None
        ws = _row_to_dict(row)
        # 检查是否过期
        if ws.get('expires_at', 0) and ws['expires_at'] < time.time():
            return None
        return ws

def get_workspace_by_id(ws_id):
    """根据 ID 获取工作空间"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM shared_workspaces WHERE id = :id"),
            {'id': ws_id}
        ).fetchone()
        return _row_to_dict(row) if row else None

def get_user_workspaces(user_id, limit=20):
    """获取用户拥有或加入的工作空间"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT DISTINCT w.* FROM shared_workspaces w
                LEFT JOIN workspace_members m ON w.id = m.workspace_id
                WHERE w.owner_id = :user_id OR m.user_id = :user_id
                ORDER BY w.updated_at DESC LIMIT :limit
            """),
            {'user_id': user_id, 'limit': limit}
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

def update_workspace(ws_id, title=None, permission=None, expires_at=None, data_ref=None):
    """更新工作空间"""
    with engine.begin() as conn:
        now = time.time()
        sets = ['updated_at = :updated_at']
        params = {'updated_at': now, 'id': ws_id}
        if title is not None:
            sets.append('title = :title'); params['title'] = title
        if permission is not None:
            sets.append('permission = :permission'); params['permission'] = permission
        if expires_at is not None:
            sets.append('expires_at = :expires_at'); params['expires_at'] = expires_at
        if data_ref is not None:
            sets.append('data_ref = :data_ref'); params['data_ref'] = data_ref
        result = conn.execute(
            text(f"UPDATE shared_workspaces SET {', '.join(sets)} WHERE id = :id"),
            params
        )
        return result.rowcount > 0

def delete_workspace(ws_id, owner_id):
    """删除工作空间（仅所有者）"""
    with engine.begin() as conn:
        # 删除评论
        conn.execute(text("DELETE FROM workspace_comments WHERE workspace_id = :id"), {'id': ws_id})
        # 删除成员
        conn.execute(text("DELETE FROM workspace_members WHERE workspace_id = :id"), {'id': ws_id})
        # 删除工作空间
        result = conn.execute(
            text("DELETE FROM shared_workspaces WHERE id = :id AND owner_id = :owner_id"),
            {'id': ws_id, 'owner_id': owner_id}
        )
        return result.rowcount > 0

def join_workspace(ws_id, user_id):
    """用户加入工作空间"""
    with engine.begin() as conn:
        now = time.time()
        conn.execute(
            text("""
                INSERT INTO workspace_members (workspace_id, user_id, role, joined_at)
                VALUES (:ws_id, :user_id, 'viewer', :joined_at)
                ON CONFLICT(workspace_id, user_id) DO NOTHING
            """),
            {'ws_id': ws_id, 'user_id': user_id, 'joined_at': now}
        )
        # 更新工作空间时间戳
        conn.execute(
            text("UPDATE shared_workspaces SET updated_at = :now WHERE id = :id"),
            {'now': now, 'id': ws_id}
        )
        return True

def get_workspace_members(ws_id):
    """获取工作空间成员列表"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT m.*, u.name, u.email, u.avatar FROM workspace_members m
                JOIN users u ON m.user_id = u.id
                WHERE m.workspace_id = :ws_id ORDER BY m.joined_at ASC
            """),
            {'ws_id': ws_id}
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


# ==================== v5.3 协作：评论 ====================

def add_comment(ws_id, user_id, content, parent_id=0):
    """添加评论"""
    with engine.begin() as conn:
        now = time.time()
        result = conn.execute(
            text("""
                INSERT INTO workspace_comments (workspace_id, user_id, content, parent_id, created_at)
                VALUES (:ws_id, :user_id, :content, :parent_id, :created_at)
                RETURNING id
            """),
            {'ws_id': ws_id, 'user_id': user_id, 'content': content,
             'parent_id': parent_id, 'created_at': now}
        )
        comment_id = result.scalar()
        # 更新工作空间时间戳
        conn.execute(
            text("UPDATE shared_workspaces SET updated_at = :now WHERE id = :id"),
            {'now': now, 'id': ws_id}
        )
        return comment_id

def get_comments(ws_id, limit=100):
    """获取工作空间评论列表"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT c.*, u.name, u.avatar FROM workspace_comments c
                JOIN users u ON c.user_id = u.id
                WHERE c.workspace_id = :ws_id
                ORDER BY c.created_at ASC LIMIT :limit
            """),
            {'ws_id': ws_id, 'limit': limit}
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

def delete_comment(comment_id, user_id):
    """删除评论（仅作者或工作空间所有者）"""
    with engine.begin() as conn:
        # 先获取评论信息
        row = conn.execute(
            text("SELECT c.*, w.owner_id FROM workspace_comments c JOIN shared_workspaces w ON c.workspace_id = w.id WHERE c.id = :id"),
            {'id': comment_id}
        ).fetchone()
        if not row:
            return False
        data = _row_to_dict(row)
        if data['user_id'] != user_id and data['owner_id'] != user_id:
            return False
        result = conn.execute(
            text("DELETE FROM workspace_comments WHERE id = :id"),
            {'id': comment_id}
        )
        return result.rowcount > 0


# ==================== v7.0 协作深化：增强协作者状态 ====================

def upsert_collab_member(ws_id, user_id, role='viewer'):
    """创建或更新协作成员（v2 表）"""
    with engine.begin() as conn:
        now = time.time()
        conn.execute(
            text("""
                INSERT INTO collab_members (workspace_id, user_id, role, last_active, joined_at)
                VALUES (:ws_id, :user_id, :role, :now, :now)
                ON CONFLICT(workspace_id, user_id) DO UPDATE SET last_active = :now
            """),
            {'ws_id': ws_id, 'user_id': user_id, 'role': role, 'now': now}
        )
        return True

def update_member_presence(ws_id, user_id, viewing_area='', is_editing=0, editing_area=''):
    """更新成员在线状态和编辑区域"""
    with engine.begin() as conn:
        now = time.time()
        conn.execute(
            text("""
                UPDATE collab_members SET last_active = :now, viewing_area = :viewing_area,
                is_editing = :is_editing, editing_area = :editing_area
                WHERE workspace_id = :ws_id AND user_id = :user_id
            """),
            {'now': now, 'viewing_area': viewing_area, 'is_editing': 1 if is_editing else 0,
             'editing_area': editing_area, 'ws_id': ws_id, 'user_id': user_id}
        )
        return True

def get_active_members(ws_id, active_threshold=30):
    """获取当前在线协作者（last_active 在阈值内）"""
    with engine.connect() as conn:
        cutoff = time.time() - active_threshold
        rows = conn.execute(
            text("""
                SELECT m.*, u.name, u.avatar FROM collab_members m
                JOIN users u ON m.user_id = u.id
                WHERE m.workspace_id = :ws_id AND m.last_active > :cutoff
                ORDER BY m.last_active DESC
            """),
            {'ws_id': ws_id, 'cutoff': cutoff}
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

def update_member_role(ws_id, user_id, role):
    """更新成员角色（viewer/editor/admin）"""
    if role not in ('viewer', 'editor', 'admin'):
        return False
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE collab_members SET role = :role WHERE workspace_id = :ws_id AND user_id = :user_id"),
            {'role': role, 'ws_id': ws_id, 'user_id': user_id}
        )
        return result.rowcount > 0

def remove_member(ws_id, user_id):
    """移除成员"""
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM collab_members WHERE workspace_id = :ws_id AND user_id = :user_id"),
            {'ws_id': ws_id, 'user_id': user_id}
        )
        return result.rowcount > 0


# ==================== v7.0 协作深化：增强评论 ====================

def add_collab_comment(ws_id, user_id, content, parent_id=0, mentions=None):
    """添加增强评论（支持 @提及）"""
    with engine.begin() as conn:
        now = time.time()
        mentions_str = json.dumps(mentions or [], ensure_ascii=False)
        result = conn.execute(
            text("""
                INSERT INTO collab_comments (workspace_id, user_id, content, parent_id, mentions, created_at)
                VALUES (:ws_id, :user_id, :content, :parent_id, :mentions, :created_at)
                RETURNING id
            """),
            {'ws_id': ws_id, 'user_id': user_id, 'content': content,
             'parent_id': parent_id, 'mentions': mentions_str, 'created_at': now}
        )
        comment_id = result.scalar()
        conn.execute(
            text("UPDATE shared_workspaces SET updated_at = :now WHERE id = :id"),
            {'now': now, 'id': ws_id}
        )
        # 记录活动
        conn.execute(
            text("""
                INSERT INTO collab_activity (workspace_id, user_id, action_type, action_detail, created_at)
                VALUES (:ws_id, :user_id, 'comment', :detail, :now)
            """),
            {'ws_id': ws_id, 'user_id': user_id, 'detail': content[:100], 'now': now}
        )
        return comment_id

def get_collab_comments(ws_id, limit=200):
    """获取增强评论列表"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT c.*, u.name, u.avatar FROM collab_comments c
                JOIN users u ON c.user_id = u.id
                WHERE c.workspace_id = :ws_id
                ORDER BY c.created_at ASC LIMIT :limit
            """),
            {'ws_id': ws_id, 'limit': limit}
        ).fetchall()
        result = []
        for r in rows:
            item = _row_to_dict(r)
            try:
                item['mentions'] = json.loads(item.get('mentions', '[]'))
            except (json.JSONDecodeError, TypeError):
                item['mentions'] = []
            result.append(item)
        return result

def get_collab_comment_by_id(comment_id):
    """根据 ID 获取评论"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT c.*, u.name, u.avatar FROM collab_comments c JOIN users u ON c.user_id = u.id WHERE c.id = :id"),
            {'id': comment_id}
        ).fetchone()
        if not row:
            return None
        item = _row_to_dict(row)
        try:
            item['mentions'] = json.loads(item.get('mentions', '[]'))
        except (json.JSONDecodeError, TypeError):
            item['mentions'] = []
        return item

def edit_collab_comment(comment_id, user_id, content):
    """编辑评论（仅作者）"""
    with engine.begin() as conn:
        now = time.time()
        result = conn.execute(
            text("UPDATE collab_comments SET content = :content, edited_at = :now WHERE id = :id AND user_id = :user_id"),
            {'content': content, 'now': now, 'id': comment_id, 'user_id': user_id}
        )
        return result.rowcount > 0

def delete_collab_comment(comment_id, user_id):
    """删除增强评论（仅作者或工作空间所有者）"""
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT c.*, w.owner_id FROM collab_comments c JOIN shared_workspaces w ON c.workspace_id = w.id WHERE c.id = :id"),
            {'id': comment_id}
        ).fetchone()
        if not row:
            return False
        data = _row_to_dict(row)
        if data['user_id'] != user_id and data['owner_id'] != user_id:
            return False
        # 同时删除子回复
        conn.execute(text("DELETE FROM collab_comments WHERE parent_id = :id"), {'id': comment_id})
        result = conn.execute(text("DELETE FROM collab_comments WHERE id = :id"), {'id': comment_id})
        return result.rowcount > 0

def resolve_collab_comment(comment_id, user_id):
    """标记评论为已解决"""
    with engine.begin() as conn:
        now = time.time()
        result = conn.execute(
            text("UPDATE collab_comments SET is_resolved = 1, resolved_by = :user_id, resolved_at = :now WHERE id = :id"),
            {'user_id': user_id, 'now': now, 'id': comment_id}
        )
        return result.rowcount > 0

def unresolve_collab_comment(comment_id, user_id):
    """取消已解决状态"""
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE collab_comments SET is_resolved = 0, resolved_by = 0, resolved_at = 0 WHERE id = :id"),
            {'id': comment_id}
        )
        return result.rowcount > 0

def get_unread_comment_count(ws_id, user_id, last_read_at=0):
    """获取未读评论数"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) as cnt FROM collab_comments WHERE workspace_id = :ws_id AND created_at > :since AND user_id != :user_id"),
            {'ws_id': ws_id, 'since': last_read_at, 'user_id': user_id}
        ).fetchone()
        return row.cnt if row else 0


# ==================== v7.0 协作深化：活动记录 ====================

def add_activity(ws_id, user_id, action_type, action_detail=''):
    """添加活动记录"""
    with engine.begin() as conn:
        now = time.time()
        conn.execute(
            text("""
                INSERT INTO collab_activity (workspace_id, user_id, action_type, action_detail, created_at)
                VALUES (:ws_id, :user_id, :action_type, :action_detail, :created_at)
            """),
            {'ws_id': ws_id, 'user_id': user_id, 'action_type': action_type,
             'action_detail': action_detail, 'created_at': now}
        )
        return True

def get_activity_log(ws_id, action_type=None, limit=100):
    """获取活动日志，支持按类型筛选"""
    with engine.connect() as conn:
        if action_type:
            rows = conn.execute(
                text("""
                    SELECT a.*, u.name, u.avatar FROM collab_activity a
                    JOIN users u ON a.user_id = u.id
                    WHERE a.workspace_id = :ws_id AND a.action_type = :action_type
                    ORDER BY a.created_at DESC LIMIT :limit
                """),
                {'ws_id': ws_id, 'action_type': action_type, 'limit': limit}
            ).fetchall()
        else:
            rows = conn.execute(
                text("""
                    SELECT a.*, u.name, u.avatar FROM collab_activity a
                    JOIN users u ON a.user_id = u.id
                    WHERE a.workspace_id = :ws_id
                    ORDER BY a.created_at DESC LIMIT :limit
                """),
                {'ws_id': ws_id, 'limit': limit}
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


# ==================== v7.0 协作深化：分享链接增强 ====================

def update_workspace_security(ws_id, password=None, access_limit=None):
    """更新工作空间安全设置（密码、访问次数限制）"""
    with engine.begin() as conn:
        now = time.time()
        sets = ['updated_at = :now']
        params = {'now': now, 'id': ws_id}
        if password is not None:
            sets.append('password = :password')
            params['password'] = password
        if access_limit is not None:
            sets.append('access_limit = :access_limit')
            params['access_limit'] = int(access_limit)
        result = conn.execute(
            text(f"UPDATE shared_workspaces SET {', '.join(sets)} WHERE id = :id"),
            params
        )
        return result.rowcount > 0

def increment_access_count(ws_id):
    """增加访问计数，返回是否超过限制"""
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT access_count, access_limit FROM shared_workspaces WHERE id = :id"),
            {'id': ws_id}
        ).fetchone()
        if not row:
            return False
        data = _row_to_dict(row)
        limit = data.get('access_limit', 0) or 0
        count = data.get('access_count', 0) or 0
        if limit > 0 and count >= limit:
            return False
        conn.execute(
            text("UPDATE shared_workspaces SET access_count = access_count + 1 WHERE id = :id"),
            {'id': ws_id}
        )
        return True


# ==================== v7.0 协作深化：团队工作空间 ====================

def create_team_space(owner_id, name, description=''):
    """创建团队工作空间，返回团队码"""
    with engine.begin() as conn:
        now = time.time()
        for _ in range(5):
            team_code = _secrets.token_urlsafe(6)[:8].replace('-', 'a').replace('_', 'b')
            existing = conn.execute(
                text("SELECT id FROM team_spaces WHERE team_code = :code"),
                {'code': team_code}
            ).fetchone()
            if not existing:
                break
        result = conn.execute(
            text("""
                INSERT INTO team_spaces (team_code, name, owner_id, description, created_at, updated_at)
                VALUES (:team_code, :name, :owner_id, :description, :created_at, :updated_at)
                RETURNING id
            """),
            {'team_code': team_code, 'name': name, 'owner_id': owner_id,
             'description': description, 'created_at': now, 'updated_at': now}
        )
        team_id = result.scalar()
        # 所有者自动加入
        conn.execute(
            text("""
                INSERT INTO team_members (team_id, user_id, role, joined_at)
                VALUES (:team_id, :user_id, 'admin', :joined_at)
            """),
            {'team_id': team_id, 'user_id': owner_id, 'joined_at': now}
        )
        return team_code

def get_team_by_code(team_code):
    """根据团队码获取团队"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM team_spaces WHERE team_code = :code"),
            {'code': team_code}
        ).fetchone()
        return _row_to_dict(row) if row else None

def get_team_by_id(team_id):
    """根据 ID 获取团队"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM team_spaces WHERE id = :id"),
            {'id': team_id}
        ).fetchone()
        return _row_to_dict(row) if row else None

def get_user_teams(user_id, limit=30):
    """获取用户所属的团队列表"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT DISTINCT t.* FROM team_spaces t
                LEFT JOIN team_members m ON t.id = m.team_id
                WHERE t.owner_id = :user_id OR m.user_id = :user_id
                ORDER BY t.updated_at DESC LIMIT :limit
            """),
            {'user_id': user_id, 'limit': limit}
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

def update_team_space(team_id, name=None, description=None, config=None):
    """更新团队信息"""
    with engine.begin() as conn:
        now = time.time()
        sets = ['updated_at = :now']
        params = {'now': now, 'id': team_id}
        if name is not None:
            sets.append('name = :name'); params['name'] = name
        if description is not None:
            sets.append('description = :description'); params['description'] = description
        if config is not None:
            sets.append('config = :config'); params['config'] = json.dumps(config, ensure_ascii=False)
        result = conn.execute(
            text(f"UPDATE team_spaces SET {', '.join(sets)} WHERE id = :id"),
            params
        )
        return result.rowcount > 0

def delete_team_space(team_id, owner_id):
    """删除团队（仅所有者）"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM team_data WHERE team_id = :id"), {'id': team_id})
        conn.execute(text("DELETE FROM team_members WHERE team_id = :id"), {'id': team_id})
        result = conn.execute(
            text("DELETE FROM team_spaces WHERE id = :id AND owner_id = :owner_id"),
            {'id': team_id, 'owner_id': owner_id}
        )
        return result.rowcount > 0

def join_team(team_id, user_id):
    """用户加入团队"""
    with engine.begin() as conn:
        now = time.time()
        conn.execute(
            text("""
                INSERT INTO team_members (team_id, user_id, role, joined_at)
                VALUES (:team_id, :user_id, 'member', :joined_at)
                ON CONFLICT(team_id, user_id) DO NOTHING
            """),
            {'team_id': team_id, 'user_id': user_id, 'joined_at': now}
        )
        conn.execute(
            text("UPDATE team_spaces SET updated_at = :now WHERE id = :id"),
            {'now': now, 'id': team_id}
        )
        return True

def get_team_members(team_id):
    """获取团队成员列表"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT m.*, u.name, u.email, u.avatar FROM team_members m
                JOIN users u ON m.user_id = u.id
                WHERE m.team_id = :team_id ORDER BY m.joined_at ASC
            """),
            {'team_id': team_id}
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

def update_team_member_role(team_id, user_id, role):
    """更新团队成员角色（admin/member）"""
    if role not in ('admin', 'member'):
        return False
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE team_members SET role = :role WHERE team_id = :team_id AND user_id = :user_id"),
            {'role': role, 'team_id': team_id, 'user_id': user_id}
        )
        return result.rowcount > 0

def remove_team_member(team_id, user_id):
    """移除团队成员"""
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM team_members WHERE team_id = :team_id AND user_id = :user_id"),
            {'team_id': team_id, 'user_id': user_id}
        )
        return result.rowcount > 0


def get_team_member_count(team_id):
    """获取团队成员数量"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) FROM team_members WHERE team_id = :team_id"),
            {'team_id': team_id}
        ).fetchone()
        return row[0] if row else 0


def get_team_data_count(team_id):
    """获取团队共享数据数量"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) FROM team_data WHERE team_id = :team_id"),
            {'team_id': team_id}
        ).fetchone()
        return row[0] if row else 0


def get_user_team_role(team_id, user_id):
    """获取用户在团队中的角色"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT role FROM team_members WHERE team_id = :team_id AND user_id = :user_id"),
            {'team_id': team_id, 'user_id': user_id}
        ).fetchone()
        return row[0] if row else None


def find_user_by_email(email):
    """根据邮箱查找用户"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, name, email, avatar FROM users WHERE email = :email LIMIT 1"),
            {'email': email}
        ).fetchone()
        return _row_to_dict(row) if row else None


def add_team_member(team_id, user_id, role='member'):
    """添加团队成员（邀请）"""
    with engine.begin() as conn:
        now = time.time()
        result = conn.execute(
            text("""
                INSERT INTO team_members (team_id, user_id, role, joined_at)
                VALUES (:team_id, :user_id, :role, :joined_at)
                ON CONFLICT(team_id, user_id) DO NOTHING
            """),
            {'team_id': team_id, 'user_id': user_id, 'role': role, 'joined_at': now}
        )
        if result.rowcount > 0:
            conn.execute(
                text("UPDATE team_spaces SET updated_at = :now WHERE id = :id"),
                {'now': now, 'id': team_id}
            )
        return True


def update_team_settings(team_id, settings):
    """更新团队设置"""
    with engine.begin() as conn:
        now = time.time()
        result = conn.execute(
            text("UPDATE team_spaces SET settings = :settings, updated_at = :now WHERE id = :id"),
            {'settings': json.dumps(settings, ensure_ascii=False), 'now': now, 'id': team_id}
        )
        return result.rowcount > 0


# ==================== v11.0 团队数据共享 ====================

def share_data_to_team(team_id, data_type, data_ref, title, shared_by, permissions=None):
    """分享数据到团队"""
    with engine.begin() as conn:
        now = time.time()
        perm_json = json.dumps(permissions or {'access': 'view'}, ensure_ascii=False)
        result = conn.execute(
            text("""
                INSERT INTO team_data (team_id, data_type, data_ref, title, shared_by, permissions, created_at)
                VALUES (:team_id, :data_type, :data_ref, :title, :shared_by, :permissions, :created_at)
                RETURNING id
            """),
            {'team_id': team_id, 'data_type': data_type, 'data_ref': data_ref or '',
             'title': title or '', 'shared_by': shared_by, 'permissions': perm_json, 'created_at': now}
        )
        return result.scalar()


def get_team_data_list(team_id, data_type=None, limit=100):
    """获取团队共享数据列表，支持按类型筛选"""
    with engine.connect() as conn:
        if data_type:
            rows = conn.execute(
                text("""
                    SELECT d.*, u.name as shared_by_name, u.avatar as shared_by_avatar
                    FROM team_data d
                    LEFT JOIN users u ON d.shared_by = u.id
                    WHERE d.team_id = :team_id AND d.data_type = :data_type
                    ORDER BY d.created_at DESC LIMIT :limit
                """),
                {'team_id': team_id, 'data_type': data_type, 'limit': limit}
            ).fetchall()
        else:
            rows = conn.execute(
                text("""
                    SELECT d.*, u.name as shared_by_name, u.avatar as shared_by_avatar
                    FROM team_data d
                    LEFT JOIN users u ON d.shared_by = u.id
                    WHERE d.team_id = :team_id
                    ORDER BY d.created_at DESC LIMIT :limit
                """),
                {'team_id': team_id, 'limit': limit}
            ).fetchall()
        result = []
        for row in rows:
            item = _row_to_dict(row)
            try:
                item['permissions'] = json.loads(item.get('permissions', '{}') or '{}')
            except (json.JSONDecodeError, TypeError):
                item['permissions'] = {}
            result.append(item)
        return result


def get_team_data_by_id(data_id):
    """根据 ID 获取共享数据详情"""
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT d.*, u.name as shared_by_name, u.avatar as shared_by_avatar
                FROM team_data d
                LEFT JOIN users u ON d.shared_by = u.id
                WHERE d.id = :id
            """),
            {'id': data_id}
        ).fetchone()
        if not row:
            return None
        item = _row_to_dict(row)
        try:
            item['permissions'] = json.loads(item.get('permissions', '{}') or '{}')
        except (json.JSONDecodeError, TypeError):
            item['permissions'] = {}
        return item


def delete_team_data(data_id, team_id=None):
    """取消分享（删除共享数据）"""
    with engine.begin() as conn:
        if team_id:
            result = conn.execute(
                text("DELETE FROM team_data WHERE id = :id AND team_id = :team_id"),
                {'id': data_id, 'team_id': team_id}
            )
        else:
            result = conn.execute(
                text("DELETE FROM team_data WHERE id = :id"),
                {'id': data_id}
            )
        return result.rowcount > 0


def is_data_shared_to_team(team_id, data_type, data_ref):
    """检查某数据是否已分享到团队"""
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT id FROM team_data
                WHERE team_id = :team_id AND data_type = :data_type AND data_ref = :data_ref
                LIMIT 1
            """),
            {'team_id': team_id, 'data_type': data_type, 'data_ref': data_ref}
        ).fetchone()
        return row[0] if row else None


# ==================== v8.0 牛马笔记：独立笔记 CRUD ====================

def get_notes(user_id):
    """获取用户所有笔记，按 pinned 优先、updated_at 降序排列"""
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, note_uid, title, content, category, tags, is_todo, pinned, created_at, updated_at
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
                SELECT id, note_uid, title, content, category, tags, is_todo, pinned, created_at, updated_at
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
        return item


def create_note(user_id, note_uid, title='', content='', category='', tags=None, is_todo=False, pinned=False):
    """创建笔记，返回笔记字典"""
    with engine.begin() as conn:
        now = time.time()
        tags_str = json.dumps(tags or [], ensure_ascii=False)
        conn.execute(
            text("""
                INSERT INTO notes (user_id, note_uid, title, content, category, tags, is_todo, pinned, created_at, updated_at)
                VALUES (:user_id, :note_uid, :title, :content, :category, :tags, :is_todo, :pinned, :created_at, :updated_at)
            """),
            {
                'user_id': user_id, 'note_uid': note_uid, 'title': title, 'content': content,
                'category': category, 'tags': tags_str, 'is_todo': 1 if is_todo else 0,
                'pinned': 1 if pinned else 0, 'created_at': now, 'updated_at': now
            }
        )
    return get_note_by_uid(user_id, note_uid)


def update_note(user_id, note_uid, title=None, content=None, category=None, tags=None, is_todo=None, pinned=None):
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

def get_all_users(page=1, per_page=20, search=''):
    """分页获取用户列表，支持按用户名/邮箱搜索"""
    with engine.connect() as conn:
        offset = (page - 1) * per_page
        params = {'limit': per_page, 'offset': offset}
        where = ''
        if search:
            where = "WHERE name LIKE :search OR email LIKE :search OR username LIKE :search"
            params['search'] = f'%{search}%'

        rows = conn.execute(
            text(f"""
                SELECT id, provider, provider_uid, name, email, avatar, username,
                       created_at, last_login, is_admin
                FROM users {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params
        ).fetchall()

        count_params = {'search': f'%{search}%'} if search else {}
        count_row = conn.execute(
            text(f"SELECT COUNT(*) as cnt FROM users {where}"),
            count_params
        ).fetchone()
        total = count_row[0] if count_row else 0

        users = [_row_to_dict(r) for r in rows]
        return {'users': users, 'total': total, 'page': page, 'per_page': per_page}


def update_user(user_id, **kwargs):
    """更新用户信息（name、email、avatar、username、is_admin 等）"""
    allowed = {'name', 'email', 'avatar', 'username', 'is_admin'}
    sets = []
    params = {'id': user_id}
    for key, value in kwargs.items():
        if key in allowed:
            sets.append(f"{key} = :{key}")
            params[key] = value
    if not sets:
        return False
    with engine.begin() as conn:
        result = conn.execute(
            text(f"UPDATE users SET {', '.join(sets)} WHERE id = :id"),
            params
        )
        return result.rowcount > 0


def delete_user(user_id):
    """删除用户及其所有相关数据（笔记、分析记录、偏好、协作数据等）"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM notes WHERE user_id = :uid"), {'uid': user_id})
        conn.execute(text("DELETE FROM user_data WHERE user_id = :uid"), {'uid': user_id})
        conn.execute(text("DELETE FROM user_preferences WHERE user_id = :uid"), {'uid': user_id})
        conn.execute(text("DELETE FROM merit_records WHERE user_id = :uid"), {'uid': user_id})
        conn.execute(text("DELETE FROM workspace_members WHERE user_id = :uid"), {'uid': user_id})
        conn.execute(text("DELETE FROM collab_members WHERE user_id = :uid"), {'uid': user_id})
        conn.execute(text("DELETE FROM team_members WHERE user_id = :uid"), {'uid': user_id})
        conn.execute(text("DELETE FROM workspace_comments WHERE user_id = :uid"), {'uid': user_id})
        conn.execute(text("DELETE FROM collab_comments WHERE user_id = :uid"), {'uid': user_id})
        conn.execute(text("DELETE FROM collab_activity WHERE user_id = :uid"), {'uid': user_id})
        # 删除用户拥有的工作空间
        ws_rows = conn.execute(
            text("SELECT id FROM shared_workspaces WHERE owner_id = :uid"),
            {'uid': user_id}
        ).fetchall()
        for ws_row in ws_rows:
            ws_id = ws_row[0]
            conn.execute(text("DELETE FROM workspace_comments WHERE workspace_id = :wid"), {'wid': ws_id})
            conn.execute(text("DELETE FROM workspace_members WHERE workspace_id = :wid"), {'wid': ws_id})
            conn.execute(text("DELETE FROM collab_comments WHERE workspace_id = :wid"), {'wid': ws_id})
            conn.execute(text("DELETE FROM collab_members WHERE workspace_id = :wid"), {'wid': ws_id})
            conn.execute(text("DELETE FROM collab_activity WHERE workspace_id = :wid"), {'wid': ws_id})
            conn.execute(text("DELETE FROM shared_workspaces WHERE id = :wid"), {'wid': ws_id})
        # 删除用户拥有的团队空间
        team_rows = conn.execute(
            text("SELECT id FROM team_spaces WHERE owner_id = :uid"),
            {'uid': user_id}
        ).fetchall()
        for team_row in team_rows:
            team_id = team_row[0]
            conn.execute(text("DELETE FROM team_data WHERE team_id = :tid"), {'tid': team_id})
            conn.execute(text("DELETE FROM team_members WHERE team_id = :tid"), {'tid': team_id})
            conn.execute(text("DELETE FROM team_spaces WHERE id = :tid"), {'tid': team_id})
        # 删除用户分享到其他团队的数据
        conn.execute(text("DELETE FROM team_data WHERE shared_by = :uid"), {'uid': user_id})
        result = conn.execute(text("DELETE FROM users WHERE id = :id"), {'id': user_id})
        return result.rowcount > 0


def set_user_admin(user_id, is_admin):
    """设置/取消管理员权限"""
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE users SET is_admin = :is_admin WHERE id = :id"),
            {'is_admin': 1 if is_admin else 0, 'id': user_id}
        )
        return result.rowcount > 0


def get_user_stats(user_id):
    """获取用户数据统计（笔记数、分析记录数、最后登录时间等）"""
    with engine.connect() as conn:
        notes_row = conn.execute(
            text("SELECT COUNT(*) as cnt FROM notes WHERE user_id = :uid"),
            {'uid': user_id}
        ).fetchone()
        data_row = conn.execute(
            text("SELECT COUNT(*) as cnt FROM user_data WHERE user_id = :uid"),
            {'uid': user_id}
        ).fetchone()
        user_row = conn.execute(
            text("SELECT last_login, created_at FROM users WHERE id = :uid"),
            {'uid': user_id}
        ).fetchone()
        return {
            'notes_count': notes_row[0] if notes_row else 0,
            'data_count': data_row[0] if data_row else 0,
            'last_login': user_row[0] if user_row else 0,
            'created_at': user_row[1] if user_row else 0,
        }


def is_admin_user(user_id):
    """判断用户是否为管理员"""
    if not user_id:
        return False
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT is_admin FROM users WHERE id = :id"),
            {'id': user_id}
        ).fetchone()
        return bool(row and row[0] == 1)


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
