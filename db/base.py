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


from werkzeug.security import generate_password_hash, check_password_hash


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


SYNC_TYPES = {'favorites', 'recent', 'notes', 'merit', 'projects', 'plans', 'theme', 'form_drafts', 'settings'}


import secrets as _secrets


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

        # 迁移：添加 completed 字段（兼容已有数据）
        try:
            conn.execute(text("ALTER TABLE notes ADD COLUMN completed INTEGER DEFAULT 0"))
        except Exception:
            pass  # 字段已存在

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

        # ==================== v12.0 文档版本历史表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS document_versions (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                doc_type TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                version_number INTEGER DEFAULT 1,
                content TEXT DEFAULT '',
                name TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_by INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_doc_versions_doc ON document_versions(user_id, doc_type, doc_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_doc_versions_created ON document_versions(created_at)"))

        # ==================== v12.0 通知系统表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS notifications (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                title TEXT DEFAULT '',
                content TEXT DEFAULT '',
                link TEXT DEFAULT '',
                is_read INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id, is_read)"))

        # ==================== 阶段四 安全加固：登录尝试表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS login_attempts (
                id {_PK_TYPE},
                user_id INTEGER,
                ip TEXT DEFAULT '',
                success INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_login_attempts_user ON login_attempts(user_id, created_at)"))

        # ==================== 阶段四 安全加固：审计日志表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id {_PK_TYPE},
                user_id INTEGER,
                action TEXT NOT NULL,
                target_type TEXT DEFAULT '',
                target_id TEXT DEFAULT '',
                ip TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                details TEXT DEFAULT '',
                created_at REAL DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action, created_at)"))

        # ==================== 阶段四 安全加固：用户活跃会话表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                session_token TEXT NOT NULL UNIQUE,
                ip TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                created_at REAL DEFAULT 0,
                last_active REAL DEFAULT 0,
                expires_at REAL DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id, last_active)"))

        # v13.0: 软删除字段（用户数据删除后30天可恢复）
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN deleted_at REAL DEFAULT 0"))
        except Exception:
            pass

        # ==================== v8.0 AI 原生：AI 配置表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS ai_configs (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                provider TEXT DEFAULT 'openai',
                api_key TEXT DEFAULT '',
                base_url TEXT DEFAULT '',
                model TEXT DEFAULT 'gpt-3.5-turbo',
                temperature REAL DEFAULT 0.7,
                max_tokens INTEGER DEFAULT 2000,
                is_active INTEGER DEFAULT 1,
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0,
                UNIQUE(user_id, provider)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ai_configs_user ON ai_configs(user_id, is_active)"))

        # ==================== v8.0 AI 原生：AI 对话历史表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT DEFAULT '',
                tokens_used INTEGER DEFAULT 0,
                model TEXT DEFAULT '',
                created_at REAL DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ai_conv_user_session ON ai_conversations(user_id, session_id, created_at)"))

        # ==================== v8.0 AI 原生：AI 报告表 ====================
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS ai_reports (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                report_type TEXT DEFAULT 'custom',
                title TEXT DEFAULT '',
                content TEXT DEFAULT '',
                data_ref TEXT DEFAULT '',
                tokens_used INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ai_reports_user ON ai_reports(user_id, report_type, created_at DESC)"))

        # ==================== v8.0 AI Agent 表 ====================
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_agent_configs (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                name TEXT DEFAULT 'default',
                enabled INTEGER DEFAULT 0,
                schedule_type TEXT DEFAULT 'daily',
                schedule_time TEXT DEFAULT '09:00',
                monitor_metrics TEXT DEFAULT '[]',
                alert_threshold TEXT DEFAULT '{{}}',
                auto_report INTEGER DEFAULT 1,
                alert_enabled INTEGER DEFAULT 1,
                data_sources TEXT DEFAULT '[]',
                last_run_at REAL DEFAULT 0,
                next_run_at REAL DEFAULT 0,
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0,
                UNIQUE(user_id, name)
            )
        """.format(_PK_TYPE=_PK_TYPE)))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_configs_user ON ai_agent_configs(user_id, enabled)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_agent_runs (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                config_id INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                trigger_type TEXT DEFAULT 'scheduled',
                metrics_summary TEXT DEFAULT '{{}}',
                anomalies_found TEXT DEFAULT '[]',
                report_id INTEGER DEFAULT 0,
                error_message TEXT DEFAULT '',
                started_at REAL DEFAULT 0,
                completed_at REAL DEFAULT 0,
                duration_ms INTEGER DEFAULT 0
            )
        """.format(_PK_TYPE=_PK_TYPE)))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_runs_user ON ai_agent_runs(user_id, started_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON ai_agent_runs(status, started_at)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_alerts (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                run_id INTEGER DEFAULT 0,
                alert_type TEXT DEFAULT 'anomaly',
                severity TEXT DEFAULT 'medium',
                title TEXT DEFAULT '',
                description TEXT DEFAULT '',
                metric_name TEXT DEFAULT '',
                metric_value REAL DEFAULT 0,
                threshold REAL DEFAULT 0,
                is_read INTEGER DEFAULT 0,
                is_resolved INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0,
                resolved_at REAL DEFAULT 0
            )
        """.format(_PK_TYPE=_PK_TYPE)))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_alerts_user ON ai_alerts(user_id, is_read, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_alerts_severity ON ai_alerts(severity, created_at DESC)"))

        # ==================== v8.0 智能报告表 ====================
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_report_templates (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                name TEXT DEFAULT '',
                template_type TEXT DEFAULT 'daily',
                title_format TEXT DEFAULT '',
                content_template TEXT DEFAULT '',
                include_metrics TEXT DEFAULT '[]',
                include_charts INTEGER DEFAULT 1,
                include_ai_analysis INTEGER DEFAULT 1,
                is_default INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0
            )
        """.format(_PK_TYPE=_PK_TYPE)))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_report_templates_user ON ai_report_templates(user_id, template_type)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_report_schedules (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                name TEXT DEFAULT '',
                enabled INTEGER DEFAULT 0,
                template_id INTEGER DEFAULT 0,
                schedule_type TEXT DEFAULT 'daily',
                schedule_time TEXT DEFAULT '09:00',
                recipients TEXT DEFAULT '[]',
                subject_format TEXT DEFAULT '',
                email_body_format TEXT DEFAULT '',
                attach_pdf INTEGER DEFAULT 0,
                last_sent_at REAL DEFAULT 0,
                next_send_at REAL DEFAULT 0,
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0
            )
        """.format(_PK_TYPE=_PK_TYPE)))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_report_schedules_user ON ai_report_schedules(user_id, enabled)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_report_push_logs (
                id {_PK_TYPE},
                user_id INTEGER NOT NULL,
                schedule_id INTEGER DEFAULT 0,
                template_id INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                recipients TEXT DEFAULT '[]',
                subject TEXT DEFAULT '',
                content_preview TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                sent_at REAL DEFAULT 0,
                duration_ms INTEGER DEFAULT 0
            )
        """.format(_PK_TYPE=_PK_TYPE)))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_push_logs_user ON ai_report_push_logs(user_id, sent_at DESC)"))

        # ==================== 阶段五性能优化：补充复合索引 ====================
        # user_data: 按用户+类型+创建时间排序查询（笔记列表、CR数据列表等）
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_data_created ON user_data(user_id, data_type, created_at)"))
        # notes: 按用户+创建时间排序（首页最近笔记、笔记列表分页）
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(user_id, created_at)"))
        # notes: 按用户+置顶+更新时间（笔记列表排序）
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notes_pinned ON notes(user_id, pinned, updated_at DESC)"))
        # document_versions: 按用户+创建时间排序（版本历史列表）
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_doc_versions_user_created ON document_versions(user_id, created_at DESC)"))
        # user_activity: 按用户+工具+时间（活动统计）
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_activity_user_tool ON user_activity(user_id, tool_id, created_at)"))
        # collab_activity: 按工作空间+时间排序（活动流）
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collab_activity_ws_time ON collab_activity(workspace_id, created_at DESC)"))
        # notifications: 按用户+已读+时间（通知列表）— 已有复合索引，补充纯时间索引用于管理员查询
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at)"))
        # audit_logs: 按用户+时间（已有），补充按目标类型查询
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_logs(target_type, created_at)"))
        # background_tasks: 按状态+创建时间（任务队列轮询）
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON background_tasks(status, created_at)"))
        # login_attempts: 按IP+时间（已有），补充按成功状态
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_login_attempts_success ON login_attempts(success, created_at)"))
        # team_data: 按团队+类型+时间（团队数据列表）
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_team_data_created ON team_data(team_id, data_type, created_at)"))
        # shared_workspaces: 按所有者+时间（我的共享列表）
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_workspace_owner_created ON shared_workspaces(owner_id, created_at DESC)"))

    logger.info(f"数据库 v3.0 初始化完成 ({DB_TYPE})")


# ==================== 用户相关 ====================



