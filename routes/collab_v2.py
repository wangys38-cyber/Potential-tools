"""协作功能深化 Blueprint — v7.0
实时协作状态、增强评论系统、权限管理、协作历史、团队工作空间
"""
import time
import json
import hashlib
import secrets
from flask import Blueprint, request, jsonify, session

import db

# 密码哈希前缀，用于区分哈希存储与旧版明文存储
_HASH_PREFIX = 'sha256:'


def _hash_password(password):
    """对密码进行加盐 SHA-256 哈希

    Returns:
        str: 格式为 'sha256:<salt_hex>:<hash_hex>'
    """
    if not password:
        return ''
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f'{salt}:{password}'.encode('utf-8')).hexdigest()
    return f'{_HASH_PREFIX}{salt}:{h}'


def _verify_password(stored_password, provided_password):
    """安全地验证密码

    - 哈希存储的密码：使用 secrets.compare_digest 比较，防时序攻击
    - 旧版明文密码：同样使用 secrets.compare_digest，保持向后兼容

    Args:
        stored_password: 数据库中存储的密码（可能是哈希或明文）
        provided_password: 用户输入的密码

    Returns:
        bool: 密码是否匹配
    """
    if not stored_password:
        return True  # 无密码保护
    if not provided_password:
        return False

    if stored_password.startswith(_HASH_PREFIX):
        # 新版哈希格式: sha256:<salt>:<hash>
        parts = stored_password[len(_HASH_PREFIX):].split(':', 1)
        if len(parts) != 2:
            return False
        salt, expected_hash = parts
        actual_hash = hashlib.sha256(f'{salt}:{provided_password}'.encode('utf-8')).hexdigest()
        return secrets.compare_digest(expected_hash, actual_hash)
    else:
        # 旧版明文格式 — 仍用 compare_digest 防时序攻击
        return secrets.compare_digest(stored_password, provided_password)


def create_collab_v2_blueprint():
    bp = Blueprint('collab_v2', __name__, url_prefix='/api/collab-v2')

    def _current_user_id():
        return session.get('user_id')

    def _require_login():
        uid = _current_user_id()
        if not uid:
            return None, (jsonify({'error': '请先登录', 'need_login': True}), 401)
        return uid, None

    def _get_workspace(share_code):
        """获取工作空间，检查过期和访问限制"""
        ws = db.get_workspace_by_code(share_code)
        if not ws:
            return None, (jsonify({'error': '工作空间不存在或已过期'}), 404)
        return ws, None

    def _check_password(ws, provided_password):
        """检查分享链接密码（使用安全比较）"""
        password = ws.get('password', '') or ''
        if not password:
            return True  # 无密码保护
        return _verify_password(password, provided_password or '')

    # ==================== 7.1 实时协作状态 ====================

    @bp.route('/workspace/<share_code>/presence', methods=['GET'])
    def get_presence(share_code):
        """获取当前在线协作者列表"""
        ws, err = _get_workspace(share_code)
        if err:
            return err

        members = db.get_active_members(ws['id'], active_threshold=30)
        return jsonify({
            'status': 'success',
            'online_count': len(members),
            'members': [{
                'user_id': m['user_id'],
                'name': m.get('name', '匿名用户'),
                'avatar': m.get('avatar', ''),
                'role': m.get('role', 'viewer'),
                'viewing_area': m.get('viewing_area', ''),
                'is_editing': bool(m.get('is_editing', 0)),
                'editing_area': m.get('editing_area', ''),
                'last_active': m.get('last_active', 0),
            } for m in members]
        })

    @bp.route('/workspace/<share_code>/heartbeat', methods=['POST'])
    def heartbeat(share_code):
        """心跳上报：更新在线状态和编辑区域"""
        uid, err = _require_login()
        if err:
            return err

        ws, err = _get_workspace(share_code)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        viewing_area = data.get('viewing_area', '')
        is_editing = int(data.get('is_editing', 0) or 0)
        editing_area = data.get('editing_area', '')

        # 确保用户在成员表中
        db.upsert_collab_member(ws['id'], uid)
        db.update_member_presence(ws['id'], uid, viewing_area, is_editing, editing_area)

        return jsonify({'status': 'success', 'server_time': time.time()})

    # ==================== 7.2 增强评论系统 ====================

    @bp.route('/workspace/<share_code>/comments', methods=['GET'])
    def get_comments_v2(share_code):
        """获取评论列表（含回复线程、解决状态，支持筛选排序）"""
        ws, err = _get_workspace(share_code)
        if err:
            return err

        uid = _current_user_id()
        status = request.args.get('status', '').strip()  # unresolved / resolved
        sort = request.args.get('sort', 'asc').strip()  # asc / desc / unresolved_first
        mentioned_me = request.args.get('mentioned_me', '').lower() == 'true'
        my_comments = request.args.get('my_comments', '').lower() == 'true'
        limit = int(request.args.get('limit', 300) or 300)

        comments = db.get_collab_comments(ws['id'], limit=limit)

        # 筛选
        filtered = []
        for c in comments:
            if status == 'unresolved' and c.get('is_resolved'):
                continue
            if status == 'resolved' and not c.get('is_resolved'):
                continue
            if my_comments and uid and c['user_id'] != uid:
                continue
            if mentioned_me and uid:
                mentions = c.get('mentions', []) or []
                if uid not in mentions:
                    continue
            filtered.append(c)

        # 排序
        if sort == 'desc':
            filtered.sort(key=lambda x: x['created_at'], reverse=True)
        elif sort == 'unresolved_first':
            filtered.sort(key=lambda x: (1 if x.get('is_resolved') else 0, x['created_at']))
        else:
            filtered.sort(key=lambda x: x['created_at'])

        return jsonify({
            'status': 'success',
            'comments': [{
                'id': c['id'],
                'user_id': c['user_id'],
                'user_name': c.get('name', '匿名用户'),
                'user_avatar': c.get('avatar', ''),
                'content': c['content'],
                'parent_id': c.get('parent_id', 0),
                'mentions': c.get('mentions', []),
                'is_resolved': bool(c.get('is_resolved', 0)),
                'resolved_by': c.get('resolved_by', 0),
                'resolved_at': c.get('resolved_at', 0),
                'edited_at': c.get('edited_at', 0),
                'created_at': c['created_at'],
            } for c in filtered],
            'total': len(filtered)
        })

    @bp.route('/workspace/<share_code>/comments', methods=['POST'])
    def add_comment_v2(share_code):
        """添加评论（支持 @提及 和 回复）"""
        uid, err = _require_login()
        if err:
            return err

        ws, err = _get_workspace(share_code)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        content = data.get('content', '').strip()
        parent_id = int(data.get('parent_id', 0) or 0)
        mentions = data.get('mentions', []) or []

        if not content:
            return jsonify({'error': '评论内容不能为空'}), 400
        if len(content) > 2000:
            return jsonify({'error': '评论内容过长（最多2000字）'}), 400

        # 确保用户在成员表中
        db.upsert_collab_member(ws['id'], uid)

        comment_id = db.add_collab_comment(ws['id'], uid, content, parent_id, mentions)
        user = db.get_user_by_id(uid)

        # 通知：@提及用户
        mentioned_users = mentions or []
        for mentioned_uid in mentioned_users:
            if mentioned_uid and mentioned_uid != uid:
                try:
                    db.create_notification(
                        user_id=mentioned_uid,
                        notif_type='mention',
                        title=f'{user.get("name", "有人")} 在评论中 @了你',
                        content=content[:100],
                        link=f'/share/{share_code}#comment-{comment_id}'
                    )
                except Exception:
                    pass

        # 通知：回复评论时通知原评论作者
        if parent_id and parent_id > 0:
            parent_comment = db.get_collab_comment_by_id(parent_id)
            if parent_comment and parent_comment['user_id'] != uid and parent_comment['user_id'] not in mentioned_users:
                try:
                    db.create_notification(
                        user_id=parent_comment['user_id'],
                        notif_type='reply',
                        title=f'{user.get("name", "有人")} 回复了你的评论',
                        content=content[:100],
                        link=f'/share/{share_code}#comment-{comment_id}'
                    )
                except Exception:
                    pass

        return jsonify({
            'status': 'success',
            'comment': {
                'id': comment_id,
                'user_id': uid,
                'user_name': user.get('name', '匿名用户') if user else '匿名用户',
                'user_avatar': user.get('avatar', '') if user else '',
                'content': content,
                'parent_id': parent_id,
                'mentions': mentions,
                'is_resolved': False,
                'edited_at': 0,
                'created_at': time.time(),
            }
        })

    @bp.route('/comments/<int:comment_id>/edit', methods=['POST'])
    def edit_comment_v2(comment_id):
        """编辑评论（仅作者）"""
        uid, err = _require_login()
        if err:
            return err

        data = request.get_json(silent=True) or {}
        content = data.get('content', '').strip()
        if not content:
            return jsonify({'error': '评论内容不能为空'}), 400
        if len(content) > 2000:
            return jsonify({'error': '评论内容过长（最多2000字）'}), 400

        success = db.edit_collab_comment(comment_id, uid, content)
        if not success:
            return jsonify({'error': '编辑失败或无权限'}), 403
        return jsonify({'status': 'success', 'edited_at': time.time()})

    @bp.route('/comments/<int:comment_id>/delete', methods=['POST'])
    def delete_comment_v2(comment_id):
        """删除评论（仅作者或工作空间所有者）"""
        uid, err = _require_login()
        if err:
            return err

        success = db.delete_collab_comment(comment_id, uid)
        if not success:
            return jsonify({'error': '删除失败或无权限'}), 403
        return jsonify({'status': 'success'})

    @bp.route('/comments/<int:comment_id>/resolve', methods=['POST'])
    def resolve_comment_v2(comment_id):
        """标记评论为已解决"""
        uid, err = _require_login()
        if err:
            return err

        success = db.resolve_collab_comment(comment_id, uid)
        if not success:
            return jsonify({'error': '操作失败'}), 400
        return jsonify({'status': 'success', 'resolved_at': time.time()})

    @bp.route('/comments/<int:comment_id>/unresolve', methods=['POST'])
    def unresolve_comment_v2(comment_id):
        """取消已解决状态"""
        uid, err = _require_login()
        if err:
            return err

        success = db.unresolve_collab_comment(comment_id, uid)
        if not success:
            return jsonify({'error': '操作失败'}), 400
        return jsonify({'status': 'success'})

    @bp.route('/workspace/<share_code>/comments/unread', methods=['GET'])
    def unread_comments(share_code):
        """获取未读评论计数"""
        uid, err = _require_login()
        if err:
            return err

        ws, err = _get_workspace(share_code)
        if err:
            return err

        last_read = float(request.args.get('since', 0) or 0)
        count = db.get_unread_comment_count(ws['id'], uid, last_read)
        return jsonify({'status': 'success', 'unread_count': count})

    # ==================== v12.0 评论 REST API 对齐 ====================

    @bp.route('/comments/<int:comment_id>/reply', methods=['POST'])
    def reply_comment(comment_id):
        """回复评论（REST 风格，等价于带 parent_id 的新增评论）"""
        uid, err = _require_login()
        if err:
            return err

        parent = db.get_collab_comment_by_id(comment_id)
        if not parent:
            return jsonify({'error': '评论不存在'}), 404

        data = request.get_json(silent=True) or {}
        content = data.get('content', '').strip()
        mentions = data.get('mentions', []) or []

        if not content:
            return jsonify({'error': '评论内容不能为空'}), 400
        if len(content) > 2000:
            return jsonify({'error': '评论内容过长（最多2000字）'}), 400

        ws_id = parent['workspace_id']
        db.upsert_collab_member(ws_id, uid)
        new_id = db.add_collab_comment(ws_id, uid, content, parent_id=comment_id, mentions=mentions)
        user = db.get_user_by_id(uid)

        # 通知原评论作者
        if parent['user_id'] != uid:
            try:
                db.create_notification(
                    user_id=parent['user_id'],
                    notif_type='reply',
                    title=f'{user.get("name", "有人")} 回复了你的评论',
                    content=content[:100],
                    link=f'#comment-{new_id}'
                )
            except Exception:
                pass

        return jsonify({
            'status': 'success',
            'comment': {
                'id': new_id, 'user_id': uid,
                'user_name': user.get('name', '匿名用户') if user else '匿名用户',
                'user_avatar': user.get('avatar', '') if user else '',
                'content': content, 'parent_id': comment_id,
                'mentions': mentions, 'is_resolved': False,
                'edited_at': 0, 'created_at': time.time(),
            }
        })

    @bp.route('/comments/<int:comment_id>/resolve', methods=['PUT'])
    def resolve_comment_rest(comment_id):
        """标记评论解决/未解决（REST PUT）"""
        uid, err = _require_login()
        if err:
            return err

        data = request.get_json(silent=True) or {}
        resolved = bool(data.get('resolved', True))

        if resolved:
            success = db.resolve_collab_comment(comment_id, uid)
        else:
            success = db.unresolve_collab_comment(comment_id, uid)

        if not success:
            return jsonify({'error': '操作失败'}), 400
        return jsonify({'status': 'success', 'is_resolved': resolved, 'resolved_at': time.time() if resolved else 0})

    @bp.route('/comments/<int:comment_id>', methods=['PUT'])
    def edit_comment_rest(comment_id):
        """编辑评论（REST PUT）"""
        uid, err = _require_login()
        if err:
            return err

        data = request.get_json(silent=True) or {}
        content = data.get('content', '').strip()
        if not content:
            return jsonify({'error': '评论内容不能为空'}), 400
        if len(content) > 2000:
            return jsonify({'error': '评论内容过长（最多2000字）'}), 400

        success = db.edit_collab_comment(comment_id, uid, content)
        if not success:
            return jsonify({'error': '编辑失败或无权限'}), 403
        return jsonify({'status': 'success', 'edited_at': time.time()})

    @bp.route('/comments/<int:comment_id>', methods=['DELETE'])
    def delete_comment_rest(comment_id):
        """删除评论（REST DELETE）"""
        uid, err = _require_login()
        if err:
            return err

        success = db.delete_collab_comment(comment_id, uid)
        if not success:
            return jsonify({'error': '删除失败或无权限'}), 403
        return jsonify({'status': 'success'})

    # ==================== v12.0 用户搜索（@提及自动补全） ====================

    @bp.route('/users/search', methods=['GET'])
    def search_users():
        """搜索用户（用于 @提及自动补全）"""
        uid, err = _require_login()
        if err:
            return err

        query = request.args.get('q', '').strip()
        if not query or len(query) < 1:
            return jsonify({'status': 'success', 'users': []})

        with db.engine.connect() as conn:
            rows = conn.execute(
                db.text("""
                    SELECT id, name, nickname, email, avatar, department, role
                    FROM users
                    WHERE name LIKE :q OR nickname LIKE :q OR email LIKE :q OR username LIKE :q
                    ORDER BY name ASC LIMIT 10
                """),
                {'q': f'%{query}%'}
            ).fetchall()
            users = [dict(r._mapping) for r in rows]

        return jsonify({'status': 'success', 'users': users})

    return bp

    @bp.route('/workspace/<share_code>/members', methods=['GET'])
    def get_members_v2(share_code):
        """获取工作空间成员列表（含角色）"""
        ws, err = _get_workspace(share_code)
        if err:
            return err

        # 使用 v2 成员表，同时兼容旧表
        with db.engine.connect() as conn:
            rows = conn.execute(
                db.text("""
                    SELECT m.*, u.name, u.avatar FROM collab_members m
                    JOIN users u ON m.user_id = u.id
                    WHERE m.workspace_id = :ws_id ORDER BY m.joined_at ASC
                """),
                {'ws_id': ws['id']}
            ).fetchall()
            members = [dict(r._mapping) for r in rows]

        # 如果 v2 表为空，回退到旧表
        if not members:
            old_members = db.get_workspace_members(ws['id'])
            for m in old_members:
                db.upsert_collab_member(ws['id'], m['user_id'], m.get('role', 'viewer'))
            members = db.get_active_members(ws['id'], active_threshold=999999999)

        return jsonify({
            'status': 'success',
            'members': [{
                'user_id': m['user_id'],
                'name': m.get('name', '匿名用户'),
                'avatar': m.get('avatar', ''),
                'role': m.get('role', 'viewer'),
                'joined_at': m.get('joined_at', 0),
                'last_active': m.get('last_active', 0),
            } for m in members],
            'member_count': len(members)
        })

    @bp.route('/workspace/<share_code>/members/<int:user_id>/role', methods=['POST'])
    def update_member_role_v2(share_code, user_id):
        """更新成员角色（viewer/editor/admin，仅管理者可操作）"""
        uid, err = _require_login()
        if err:
            return err

        ws, err = _get_workspace(share_code)
        if err:
            return err

        # 权限检查：所有者或 admin 角色
        if ws['owner_id'] != uid:
            with db.engine.connect() as conn:
                row = conn.execute(
                    db.text("SELECT role FROM collab_members WHERE workspace_id = :ws_id AND user_id = :uid"),
                    {'ws_id': ws['id'], 'uid': uid}
                ).fetchone()
                if not row or row[0] != 'admin':
                    return jsonify({'error': '仅管理者可修改成员权限'}), 403

        data = request.get_json(silent=True) or {}
        role = data.get('role', '').strip()
        if role not in ('viewer', 'editor', 'admin'):
            return jsonify({'error': '无效的角色'}), 400

        success = db.update_member_role(ws['id'], user_id, role)
        if success:
            db.add_activity(ws['id'], uid, 'permission_change',
                            f'将用户 {user_id} 的角色改为 {role}')
        return jsonify({'status': 'success' if success else 'error'})

    @bp.route('/workspace/<share_code>/members/<int:user_id>/remove', methods=['POST'])
    def remove_member_v2(share_code, user_id):
        """移除成员（仅管理者可操作）"""
        uid, err = _require_login()
        if err:
            return err

        ws, err = _get_workspace(share_code)
        if err:
            return err

        if ws['owner_id'] == user_id:
            return jsonify({'error': '不能移除所有者'}), 400

        if ws['owner_id'] != uid:
            with db.engine.connect() as conn:
                row = conn.execute(
                    db.text("SELECT role FROM collab_members WHERE workspace_id = :ws_id AND user_id = :uid"),
                    {'ws_id': ws['id'], 'uid': uid}
                ).fetchone()
                if not row or row[0] != 'admin':
                    return jsonify({'error': '仅管理者可移除成员'}), 403

        success = db.remove_member(ws['id'], user_id)
        if success:
            db.add_activity(ws['id'], uid, 'member_remove', f'移除用户 {user_id}')
        return jsonify({'status': 'success' if success else 'error'})

    @bp.route('/workspace/<share_code>/security', methods=['POST'])
    def update_security(share_code):
        """更新分享链接安全设置（密码、访问次数限制）"""
        uid, err = _require_login()
        if err:
            return err

        ws, err = _get_workspace(share_code)
        if err:
            return err

        if ws['owner_id'] != uid:
            return jsonify({'error': '仅所有者可修改安全设置'}), 403

        data = request.get_json(silent=True) or {}
        password = data.get('password', '')
        access_limit = int(data.get('access_limit', 0) or 0)

        # 密码哈希后存储，避免明文落库
        hashed_password = _hash_password(password) if password else ''
        db.update_workspace_security(ws['id'], password=hashed_password, access_limit=access_limit)
        db.add_activity(ws['id'], uid, 'security_update',
                        f'更新安全设置：密码={"有" if password else "无"}, 访问限制={access_limit}')
        return jsonify({'status': 'success'})

    # ==================== 7.4 协作历史记录 ====================

    @bp.route('/workspace/<share_code>/activity', methods=['GET'])
    def get_activity(share_code):
        """获取活动日志，支持按类型筛选"""
        ws, err = _get_workspace(share_code)
        if err:
            return err

        action_type = request.args.get('type', '').strip() or None
        limit = int(request.args.get('limit', 100) or 100)
        limit = min(limit, 500)

        activities = db.get_activity_log(ws['id'], action_type=action_type, limit=limit)
        return jsonify({
            'status': 'success',
            'activities': [{
                'id': a['id'],
                'user_id': a['user_id'],
                'user_name': a.get('name', '匿名用户'),
                'user_avatar': a.get('avatar', ''),
                'action_type': a['action_type'],
                'action_detail': a.get('action_detail', ''),
                'created_at': a['created_at'],
            } for a in activities],
            'total': len(activities)
        })

    # ==================== 7.5 团队工作空间 ====================

    @bp.route('/teams/create', methods=['POST'])
    def create_team():
        """创建团队工作空间"""
        uid, err = _require_login()
        if err:
            return err

        data = request.get_json(silent=True) or {}
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()

        if not name:
            return jsonify({'error': '团队名称不能为空'}), 400
        if len(name) > 100:
            return jsonify({'error': '团队名称过长（最多100字）'}), 400

        team_code = db.create_team_space(uid, name, description)
        return jsonify({
            'status': 'success',
            'team_code': team_code,
            'team_url': f'/teams/{team_code}'
        })

    @bp.route('/teams/my', methods=['GET'])
    def my_teams():
        """获取我的团队列表"""
        uid, err = _require_login()
        if err:
            return err

        teams = db.get_user_teams(uid, limit=30)
        return jsonify({
            'status': 'success',
            'teams': [{
                'id': t['id'],
                'team_code': t['team_code'],
                'name': t['name'],
                'description': t.get('description', ''),
                'owner_id': t['owner_id'],
                'is_owner': t['owner_id'] == uid,
                'created_at': t['created_at'],
                'updated_at': t['updated_at'],
            } for t in teams]
        })

    @bp.route('/teams/<team_code>', methods=['GET'])
    def get_team(team_code):
        """获取团队信息"""
        team = db.get_team_by_code(team_code)
        if not team:
            return jsonify({'error': '团队不存在'}), 404

        uid = _current_user_id()
        members = db.get_team_members(team['id'])
        is_member = any(m['user_id'] == uid for m in members) if uid else False

        return jsonify({
            'status': 'success',
            'team': {
                'id': team['id'],
                'team_code': team['team_code'],
                'name': team['name'],
                'description': team.get('description', ''),
                'owner_id': team['owner_id'],
                'is_owner': uid and team['owner_id'] == uid,
                'is_member': is_member,
                'created_at': team['created_at'],
                'updated_at': team['updated_at'],
            },
            'members': [{
                'user_id': m['user_id'],
                'name': m.get('name', '匿名用户'),
                'avatar': m.get('avatar', ''),
                'role': m.get('role', 'member'),
                'joined_at': m.get('joined_at', 0),
            } for m in members],
            'member_count': len(members)
        })

    @bp.route('/teams/<team_code>/join', methods=['POST'])
    def join_team(team_code):
        """加入团队"""
        uid, err = _require_login()
        if err:
            return err

        team = db.get_team_by_code(team_code)
        if not team:
            return jsonify({'error': '团队不存在'}), 404

        db.join_team(team['id'], uid)
        return jsonify({'status': 'success', 'message': '已加入团队'})

    @bp.route('/teams/<team_code>/members', methods=['GET'])
    def get_team_members_route(team_code):
        """获取团队成员列表"""
        team = db.get_team_by_code(team_code)
        if not team:
            return jsonify({'error': '团队不存在'}), 404

        members = db.get_team_members(team['id'])
        return jsonify({
            'status': 'success',
            'members': [{
                'user_id': m['user_id'],
                'name': m.get('name', '匿名用户'),
                'avatar': m.get('avatar', ''),
                'role': m.get('role', 'member'),
                'joined_at': m.get('joined_at', 0),
            } for m in members]
        })

    @bp.route('/teams/<team_code>/members/<int:user_id>/role', methods=['POST'])
    def update_team_member_role(team_code, user_id):
        """更新团队成员角色（admin/member，仅管理员可操作）"""
        uid, err = _require_login()
        if err:
            return err

        team = db.get_team_by_code(team_code)
        if not team:
            return jsonify({'error': '团队不存在'}), 404

        if team['owner_id'] != uid:
            with db.engine.connect() as conn:
                row = conn.execute(
                    db.text("SELECT role FROM team_members WHERE team_id = :team_id AND user_id = :uid"),
                    {'team_id': team['id'], 'uid': uid}
                ).fetchone()
                if not row or row[0] != 'admin':
                    return jsonify({'error': '仅管理员可修改成员角色'}), 403

        data = request.get_json(silent=True) or {}
        role = data.get('role', '').strip()
        if role not in ('admin', 'member'):
            return jsonify({'error': '无效的角色'}), 400

        success = db.update_team_member_role(team['id'], user_id, role)
        return jsonify({'status': 'success' if success else 'error'})

    @bp.route('/teams/<team_code>/members/<int:user_id>/remove', methods=['POST'])
    def remove_team_member(team_code, user_id):
        """移除团队成员（仅管理员可操作）"""
        uid, err = _require_login()
        if err:
            return err

        team = db.get_team_by_code(team_code)
        if not team:
            return jsonify({'error': '团队不存在'}), 404

        if team['owner_id'] == user_id:
            return jsonify({'error': '不能移除所有者'}), 400

        if team['owner_id'] != uid:
            with db.engine.connect() as conn:
                row = conn.execute(
                    db.text("SELECT role FROM team_members WHERE team_id = :team_id AND user_id = :uid"),
                    {'team_id': team['id'], 'uid': uid}
                ).fetchone()
                if not row or row[0] != 'admin':
                    return jsonify({'error': '仅管理员可移除成员'}), 403

        success = db.remove_team_member(team['id'], user_id)
        return jsonify({'status': 'success' if success else 'error'})

    @bp.route('/teams/<team_code>/update', methods=['POST'])
    def update_team(team_code):
        """更新团队信息（仅所有者）"""
        uid, err = _require_login()
        if err:
            return err

        team = db.get_team_by_code(team_code)
        if not team:
            return jsonify({'error': '团队不存在'}), 404
        if team['owner_id'] != uid:
            return jsonify({'error': '仅所有者可修改团队信息'}), 403

        data = request.get_json(silent=True) or {}
        name = data.get('name')
        description = data.get('description')
        config = data.get('config')

        db.update_team_space(team['id'], name=name, description=description, config=config)
        return jsonify({'status': 'success'})

    @bp.route('/teams/<team_code>/delete', methods=['POST'])
    def delete_team(team_code):
        """删除团队（仅所有者）"""
        uid, err = _require_login()
        if err:
            return err

        team = db.get_team_by_code(team_code)
        if not team:
            return jsonify({'error': '团队不存在'}), 404
        if team['owner_id'] != uid:
            return jsonify({'error': '仅所有者可删除团队'}), 403

        success = db.delete_team_space(team['id'], uid)
        return jsonify({'status': 'success' if success else 'error'})

    return bp
