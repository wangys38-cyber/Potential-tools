"""协作功能 Blueprint — v5.3
共享工作空间、评论、实时协作
"""
import time
import json
from flask import Blueprint, request, jsonify, session, g
import auth
import db


def create_collab_blueprint():
    bp = Blueprint('collab', __name__, url_prefix='/api/collab')

    def _current_user_id():
        return session.get('user_id')

    def _require_login():
        uid = _current_user_id()
        if not uid:
            return None, (jsonify({'error': '请先登录', 'need_login': True}), 401)
        return uid, None

    # ==================== 共享工作空间 ====================

    @bp.route('/workspace/create', methods=['POST'])
    def create_workspace():
        """创建共享工作空间"""
        uid, err = _require_login()
        if err:
            return err

        data = request.get_json(silent=True) or {}
        title = data.get('title', '').strip()
        tool_type = data.get('tool_type', '').strip()
        data_ref = data.get('data_ref', '').strip()
        permission = data.get('permission', 'view')
        expires_days = int(data.get('expires_days', 0) or 0)

        if not title:
            return jsonify({'error': '标题不能为空'}), 400

        expires_at = 0
        if expires_days > 0:
            expires_at = time.time() + expires_days * 86400

        try:
            share_code = db.create_workspace(
                owner_id=uid, title=title, tool_type=tool_type,
                data_ref=data_ref, permission=permission, expires_at=expires_at
            )
            return jsonify({
                'status': 'success',
                'share_code': share_code,
                'share_url': f'/share/{share_code}'
            })
        except Exception as e:
            return jsonify({'error': f'创建失败: {str(e)}'}), 500

    @bp.route('/workspace/<share_code>', methods=['GET'])
    def get_workspace(share_code):
        """获取工作空间信息"""
        ws = db.get_workspace_by_code(share_code)
        if not ws:
            return jsonify({'error': '工作空间不存在或已过期'}), 404

        uid = _current_user_id()
        is_owner = uid and ws['owner_id'] == uid
        members = db.get_workspace_members(ws['id'])

        return jsonify({
            'status': 'success',
            'workspace': {
                'id': ws['id'],
                'share_code': ws['share_code'],
                'title': ws['title'],
                'tool_type': ws['tool_type'],
                'data_ref': ws['data_ref'],
                'permission': ws['permission'],
                'owner_id': ws['owner_id'],
                'is_owner': is_owner,
                'created_at': ws['created_at'],
                'expires_at': ws.get('expires_at', 0),
            },
            'members': [{'user_id': m['user_id'], 'name': m.get('name', ''),
                         'avatar': m.get('avatar', ''), 'role': m['role']} for m in members],
            'member_count': len(members),
        })

    @bp.route('/workspace/<share_code>/join', methods=['POST'])
    def join_workspace(share_code):
        """加入工作空间"""
        uid, err = _require_login()
        if err:
            return err

        ws = db.get_workspace_by_code(share_code)
        if not ws:
            return jsonify({'error': '工作空间不存在或已过期'}), 404

        db.join_workspace(ws['id'], uid)
        return jsonify({'status': 'success', 'message': '已加入工作空间'})

    @bp.route('/workspace/<share_code>/update', methods=['POST'])
    def update_workspace(share_code):
        """更新工作空间（仅所有者）"""
        uid, err = _require_login()
        if err:
            return err

        ws = db.get_workspace_by_code(share_code)
        if not ws:
            return jsonify({'error': '工作空间不存在'}), 404
        if ws['owner_id'] != uid:
            return jsonify({'error': '仅所有者可修改'}), 403

        data = request.get_json(silent=True) or {}
        db.update_workspace(
            ws['id'],
            title=data.get('title'),
            permission=data.get('permission'),
            expires_at=data.get('expires_at'),
            data_ref=data.get('data_ref'),
        )
        return jsonify({'status': 'success'})

    @bp.route('/workspace/<share_code>/delete', methods=['POST'])
    def delete_workspace(share_code):
        """删除工作空间（仅所有者）"""
        uid, err = _require_login()
        if err:
            return err

        ws = db.get_workspace_by_code(share_code)
        if not ws:
            return jsonify({'error': '工作空间不存在'}), 404
        if ws['owner_id'] != uid:
            return jsonify({'error': '仅所有者可删除'}), 403

        db.delete_workspace(ws['id'], uid)
        return jsonify({'status': 'success'})

    @bp.route('/my-workspaces', methods=['GET'])
    def my_workspaces():
        """获取我的工作空间列表"""
        uid, err = _require_login()
        if err:
            return err

        workspaces = db.get_user_workspaces(uid, limit=30)
        return jsonify({
            'status': 'success',
            'workspaces': [{
                'id': w['id'],
                'share_code': w['share_code'],
                'title': w['title'],
                'tool_type': w['tool_type'],
                'permission': w['permission'],
                'is_owner': w['owner_id'] == uid,
                'updated_at': w['updated_at'],
            } for w in workspaces]
        })

    # ==================== 评论 ====================

    @bp.route('/workspace/<share_code>/comments', methods=['GET'])
    def get_comments(share_code):
        """获取工作空间评论"""
        ws = db.get_workspace_by_code(share_code)
        if not ws:
            return jsonify({'error': '工作空间不存在'}), 404

        comments = db.get_comments(ws['id'], limit=200)
        return jsonify({
            'status': 'success',
            'comments': [{
                'id': c['id'],
                'user_id': c['user_id'],
                'user_name': c.get('name', '匿名用户'),
                'user_avatar': c.get('avatar', ''),
                'content': c['content'],
                'parent_id': c.get('parent_id', 0),
                'created_at': c['created_at'],
            } for c in comments]
        })

    @bp.route('/workspace/<share_code>/comments', methods=['POST'])
    def add_comment(share_code):
        """添加评论"""
        uid, err = _require_login()
        if err:
            return err

        ws = db.get_workspace_by_code(share_code)
        if not ws:
            return jsonify({'error': '工作空间不存在'}), 404

        data = request.get_json(silent=True) or {}
        content = data.get('content', '').strip()
        parent_id = int(data.get('parent_id', 0) or 0)

        if not content:
            return jsonify({'error': '评论内容不能为空'}), 400
        if len(content) > 2000:
            return jsonify({'error': '评论内容过长（最多2000字）'}), 400

        comment_id = db.add_comment(ws['id'], uid, content, parent_id)
        user = db.get_user_by_id(uid)
        return jsonify({
            'status': 'success',
            'comment': {
                'id': comment_id,
                'user_id': uid,
                'user_name': user.get('name', '匿名用户') if user else '匿名用户',
                'user_avatar': user.get('avatar', '') if user else '',
                'content': content,
                'parent_id': parent_id,
                'created_at': time.time(),
            }
        })

    @bp.route('/comments/<int:comment_id>/delete', methods=['POST'])
    def delete_comment(comment_id):
        """删除评论"""
        uid, err = _require_login()
        if err:
            return err

        success = db.delete_comment(comment_id, uid)
        if not success:
            return jsonify({'error': '删除失败或无权限'}), 403
        return jsonify({'status': 'success'})

    # ==================== 实时同步（轮询） ====================

    @bp.route('/workspace/<share_code>/poll', methods=['GET'])
    def poll_workspace(share_code):
        """轮询工作空间更新（用于实时协作）"""
        ws = db.get_workspace_by_code(share_code)
        if not ws:
            return jsonify({'error': '工作空间不存在'}), 404

        since = float(request.args.get('since', 0) or 0)
        comments = db.get_comments(ws['id'], limit=200)
        new_comments = [c for c in comments if c['created_at'] > since]
        members = db.get_workspace_members(ws['id'])

        return jsonify({
            'status': 'success',
            'updated_at': ws['updated_at'],
            'new_comments': [{
                'id': c['id'],
                'user_id': c['user_id'],
                'user_name': c.get('name', '匿名用户'),
                'user_avatar': c.get('avatar', ''),
                'content': c['content'],
                'created_at': c['created_at'],
            } for c in new_comments],
            'member_count': len(members),
            'members': [{'user_id': m['user_id'], 'name': m.get('name', ''),
                         'role': m['role']} for m in members],
        })

    return bp
