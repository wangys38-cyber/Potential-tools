
import os
import json
import time
import logging
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash
"""db.users - users 相关数据库操作"""
from .base import engine, DB_TYPE, _row_to_dict

logger = logging.getLogger(__name__)

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
            text("SELECT id, provider, provider_uid, name, email, avatar, username, is_admin, created_at, last_login FROM users WHERE id = :id"),
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
            text("SELECT id, provider, provider_uid, name, email, avatar, username, password_hash, is_admin, created_at, last_login FROM users WHERE username = :username"),
            {'username': username.strip()}
        ).fetchone()
        return _row_to_dict(row)




def get_user_by_email(email):
    """根据邮箱获取用户"""
    if not email:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, provider, provider_uid, name, email, avatar, username, password_hash, is_admin, created_at, last_login FROM users WHERE email = :email"),
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


# ==================== v12.0 文档版本历史 ====================



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




def soft_delete_user(user_id):
    """软删除用户（标记 deleted_at，30天内可恢复）"""
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text("UPDATE users SET deleted_at = :now WHERE id = :id AND (deleted_at = 0 OR deleted_at IS NULL)"),
                {'now': time.time(), 'id': user_id}
            )
            return result.rowcount > 0
    except Exception as e:
        logger.error(f"软删除用户失败: {e}")
        return False




def restore_user(user_id):
    """恢复被软删除的用户"""
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text("UPDATE users SET deleted_at = 0 WHERE id = :id AND deleted_at > 0"),
                {'id': user_id}
            )
            return result.rowcount > 0
    except Exception as e:
        logger.error(f"恢复用户失败: {e}")
        return False




def purge_expired_deleted_users(grace_days=30):
    """彻底删除超过宽限期的软删除用户及其数据"""
    try:
        cutoff = time.time() - grace_days * 86400
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id FROM users WHERE deleted_at > 0 AND deleted_at < :cutoff"),
                {'cutoff': cutoff}
            ).fetchall()
        for row in rows:
            delete_user(row[0])  # 复用硬删除逻辑
    except Exception as e:
        logger.error(f"清理过期软删除用户失败: {e}")




def is_user_deleted(user_id):
    """检查用户是否已被软删除"""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT deleted_at FROM users WHERE id = :id"),
                {'id': user_id}
            ).fetchone()
            return bool(row and row[0] and row[0] > 0)
    except Exception:
        return False




# ==================== v7.1 数据隔离辅助工具 ====================



def user_scope(table_alias=None):
    """生成用户隔离的 SQL 片段，避免遗漏 user_id 过滤。

    用法:
        where_frag, params = user_scope('t')
        sql = "SELECT * FROM user_data t WHERE 1=1" + where_frag
        conn.execute(text(sql), {**params, 'other': val})

    Returns:
        (sql_fragment, params_dict): 片段以 ' AND user_id = :_uid' 开头
    """
    prefix = table_alias + '.' if table_alias else ''
    return f" AND {prefix}user_id = :_uid", {'_uid': None}




def require_user_id(user_id):
    """校验 user_id 有效性，无效则抛出 ValueError。"""
    if user_id is None:
        raise ValueError("user_id 不能为空")
    try:
        uid = int(user_id)
        if uid <= 0:
            raise ValueError
        return uid
    except (TypeError, ValueError):
        raise ValueError(f"无效的 user_id: {user_id!r}")




def assert_resource_owner(user_id, resource_user_id, resource_name='资源'):
    """校验资源归属，非所有者抛出 PermissionError。"""
    if int(user_id) != int(resource_user_id):
        raise PermissionError(f"无权访问该{resource_name}")

# ==================== 启动时初始化 ====================



