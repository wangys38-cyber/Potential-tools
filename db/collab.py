
import os
import json
import time
import logging
from sqlalchemy import text
"""db.collab - collab 相关数据库操作"""
from .base import engine, DB_TYPE, _row_to_dict

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



