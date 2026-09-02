"""团队管理 Blueprint — v11.0
RESTful API: /api/teams
团队组织管理、成员邀请、角色管理、数据共享
"""
import json
import time
from flask import Blueprint, request, jsonify, session

import db


def create_teams_blueprint():
    bp = Blueprint('teams', __name__, url_prefix='/api/teams')

    def _uid():
        return session.get('user_id')

    def _require_login():
        uid = _uid()
        if not uid:
            return None, (jsonify({'error': '请先登录', 'need_login': True}), 401)
        return uid, None

    def _get_team_or_404(team_id):
        team = db.get_team_by_id(team_id)
        if not team:
            return None, (jsonify({'error': '团队不存在'}), 404)
        return team, None

    def _check_member(team_id, uid):
        """检查用户是否为团队成员，返回角色或 None"""
        return db.get_user_team_role(team_id, uid)

    def _is_admin(team, uid):
        """检查用户是否为团队管理员（owner 或 admin 角色）"""
        if team['owner_id'] == uid:
            return True
        role = db.get_user_team_role(team['id'], uid)
        return role == 'admin'

    # ==================== 1. 团队 CRUD ====================

    @bp.route('', methods=['POST'])
    def create_team():
        """创建团队"""
        uid, err = _require_login()
        if err:
            return err

        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        description = (data.get('description') or '').strip()
        settings = data.get('settings') or {}

        if not name:
            return jsonify({'error': '团队名称不能为空'}), 400
        if len(name) > 100:
            return jsonify({'error': '团队名称过长（最多100字）'}), 400

        team_code = db.create_team_space(uid, name, description)
        team = db.get_team_by_code(team_code)
        if team and settings:
            db.update_team_settings(team['id'], settings)

        return jsonify({
            'status': 'success',
            'team': {
                'id': team['id'],
                'team_code': team['team_code'],
                'name': team['name'],
                'description': team.get('description', ''),
                'owner_id': team['owner_id'],
                'created_at': team['created_at'],
            }
        }), 201

    @bp.route('', methods=['GET'])
    def list_teams():
        """获取我加入的团队列表"""
        uid, err = _require_login()
        if err:
            return err

        teams = db.get_user_teams(uid, limit=50)
        result = []
        for t in teams:
            member_count = db.get_team_member_count(t['id'])
            data_count = db.get_team_data_count(t['id'])
            role = db.get_user_team_role(t['id'], uid)
            result.append({
                'id': t['id'],
                'team_code': t['team_code'],
                'name': t['name'],
                'description': t.get('description', ''),
                'owner_id': t['owner_id'],
                'is_owner': t['owner_id'] == uid,
                'my_role': role or 'member',
                'member_count': member_count,
                'data_count': data_count,
                'created_at': t['created_at'],
                'updated_at': t.get('updated_at', 0),
            })
        return jsonify({'status': 'success', 'teams': result})

    @bp.route('/<int:team_id>', methods=['GET'])
    def get_team_detail(team_id):
        """获取团队详情（成员列表、设置、共享数据统计）"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err

        role = _check_member(team_id, uid)
        if not role and team['owner_id'] != uid:
            return jsonify({'error': '无权限访问该团队'}), 403

        members = db.get_team_members(team_id)
        try:
            settings = json.loads(team.get('settings', '{}') or '{}')
        except (json.JSONDecodeError, TypeError):
            settings = {}

        return jsonify({
            'status': 'success',
            'team': {
                'id': team['id'],
                'team_code': team['team_code'],
                'name': team['name'],
                'description': team.get('description', ''),
                'owner_id': team['owner_id'],
                'is_owner': team['owner_id'] == uid,
                'my_role': role or 'owner',
                'settings': settings,
                'member_count': len(members),
                'created_at': team['created_at'],
                'updated_at': team.get('updated_at', 0),
            },
            'members': [{
                'user_id': m['user_id'],
                'name': m.get('name', '匿名用户'),
                'email': m.get('email', ''),
                'avatar': m.get('avatar', ''),
                'role': m.get('role', 'member'),
                'joined_at': m.get('joined_at', 0),
            } for m in members],
        })

    @bp.route('/<int:team_id>', methods=['PUT'])
    def update_team(team_id):
        """更新团队信息（仅 owner）"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err
        if team['owner_id'] != uid:
            return jsonify({'error': '仅所有者可修改团队信息'}), 403

        data = request.get_json(silent=True) or {}
        name = data.get('name')
        description = data.get('description')
        settings = data.get('settings')

        if name is not None:
            name = name.strip()
            if not name:
                return jsonify({'error': '团队名称不能为空'}), 400
        db.update_team_space(team_id, name=name, description=description)
        if settings is not None:
            db.update_team_settings(team_id, settings)

        return jsonify({'status': 'success'})

    @bp.route('/<int:team_id>', methods=['DELETE'])
    def delete_team(team_id):
        """删除团队（仅 owner）"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err
        if team['owner_id'] != uid:
            return jsonify({'error': '仅所有者可删除团队'}), 403

        success = db.delete_team_space(team_id, uid)
        return jsonify({'status': 'success' if success else 'error'})

    # ==================== 2. 成员管理 ====================

    @bp.route('/<int:team_id>/members', methods=['POST'])
    def invite_member(team_id):
        """邀请成员（通过邮箱或用户ID）"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err
        if not _is_admin(team, uid):
            return jsonify({'error': '仅管理员可邀请成员'}), 403

        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip()
        user_id = data.get('user_id')
        role = (data.get('role') or 'member').strip()

        if role not in ('admin', 'member'):
            return jsonify({'error': '无效的角色'}), 400

        target_user = None
        if user_id:
            target_user = db.get_user_by_id(int(user_id))
        elif email:
            target_user = db.find_user_by_email(email)

        if not target_user:
            return jsonify({'error': '用户不存在'}), 404

        if target_user['id'] == team['owner_id']:
            return jsonify({'error': '所有者已是团队成员'}), 400

        db.add_team_member(team_id, target_user['id'], role)
        return jsonify({
            'status': 'success',
            'member': {
                'user_id': target_user['id'],
                'name': target_user.get('name', ''),
                'email': target_user.get('email', ''),
                'avatar': target_user.get('avatar', ''),
                'role': role,
            }
        }), 201

    @bp.route('/<int:team_id>/members/<int:user_id>', methods=['DELETE'])
    def remove_member(team_id, user_id):
        """移除成员"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err
        if not _is_admin(team, uid):
            return jsonify({'error': '仅管理员可移除成员'}), 403
        if user_id == team['owner_id']:
            return jsonify({'error': '不能移除所有者'}), 400

        success = db.remove_team_member(team_id, user_id)
        return jsonify({'status': 'success' if success else 'error'})

    @bp.route('/<int:team_id>/members/<int:user_id>', methods=['PUT'])
    def update_member_role(team_id, user_id):
        """更新成员角色"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err
        if not _is_admin(team, uid):
            return jsonify({'error': '仅管理员可修改成员角色'}), 403

        data = request.get_json(silent=True) or {}
        role = (data.get('role') or '').strip()
        if role not in ('admin', 'member'):
            return jsonify({'error': '无效的角色'}), 400

        success = db.update_team_member_role(team_id, user_id, role)
        return jsonify({'status': 'success' if success else 'error'})

    # ==================== 3. 团队数据共享 ====================

    @bp.route('/<int:team_id>/share', methods=['POST'])
    def share_data(team_id):
        """分享数据到团队"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err
        role = _check_member(team_id, uid)
        if not role and team['owner_id'] != uid:
            return jsonify({'error': '仅团队成员可分享数据'}), 403

        data = request.get_json(silent=True) or {}
        data_type = (data.get('data_type') or '').strip()
        data_ref = (data.get('data_ref') or '').strip()
        title = (data.get('title') or '').strip()
        permissions = data.get('permissions') or {'access': 'view'}

        valid_types = ('cr_analysis', 'project_plan', 'knowledge_graph', 'report', 'test_report', 'general')
        if data_type not in valid_types:
            return jsonify({'error': '无效的数据类型'}), 400
        if not data_ref:
            return jsonify({'error': '数据引用不能为空'}), 400

        # 防重复分享
        existing = db.is_data_shared_to_team(team_id, data_type, data_ref)
        if existing:
            return jsonify({'status': 'success', 'data_id': existing, 'already_shared': True})

        data_id = db.share_data_to_team(team_id, data_type, data_ref, title, uid, permissions)
        return jsonify({'status': 'success', 'data_id': data_id}), 201

    @bp.route('/<int:team_id>/data', methods=['GET'])
    def list_team_data(team_id):
        """获取团队共享数据列表（支持按类型筛选）"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err
        role = _check_member(team_id, uid)
        if not role and team['owner_id'] != uid:
            return jsonify({'error': '无权限访问'}), 403

        data_type = request.args.get('type', '').strip() or None
        limit = min(int(request.args.get('limit', 100) or 100), 500)
        data_list = db.get_team_data_list(team_id, data_type=data_type, limit=limit)

        return jsonify({
            'status': 'success',
            'data': [{
                'id': d['id'],
                'team_id': d['team_id'],
                'data_type': d['data_type'],
                'data_ref': d['data_ref'],
                'title': d.get('title', ''),
                'shared_by': d['shared_by'],
                'shared_by_name': d.get('shared_by_name', ''),
                'shared_by_avatar': d.get('shared_by_avatar', ''),
                'permissions': d.get('permissions', {}),
                'created_at': d['created_at'],
            } for d in data_list],
            'total': len(data_list),
        })

    @bp.route('/<int:team_id>/data/<int:data_id>', methods=['GET'])
    def get_team_data_detail(team_id, data_id):
        """获取共享数据详情"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err
        role = _check_member(team_id, uid)
        if not role and team['owner_id'] != uid:
            return jsonify({'error': '无权限访问'}), 403

        item = db.get_team_data_by_id(data_id)
        if not item or item['team_id'] != team_id:
            return jsonify({'error': '数据不存在'}), 404

        return jsonify({
            'status': 'success',
            'data': {
                'id': item['id'],
                'team_id': item['team_id'],
                'data_type': item['data_type'],
                'data_ref': item['data_ref'],
                'title': item.get('title', ''),
                'shared_by': item['shared_by'],
                'shared_by_name': item.get('shared_by_name', ''),
                'shared_by_avatar': item.get('shared_by_avatar', ''),
                'permissions': item.get('permissions', {}),
                'created_at': item['created_at'],
            }
        })

    @bp.route('/<int:team_id>/data/<int:data_id>', methods=['DELETE'])
    def unshare_data(team_id, data_id):
        """取消分享"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err

        item = db.get_team_data_by_id(data_id)
        if not item or item['team_id'] != team_id:
            return jsonify({'error': '数据不存在'}), 404

        # 分享者本人或管理员可取消
        if item['shared_by'] != uid and not _is_admin(team, uid):
            return jsonify({'error': '无权限取消分享'}), 403

        success = db.delete_team_data(data_id, team_id)
        return jsonify({'status': 'success' if success else 'error'})

    @bp.route('/<int:team_id>/leave', methods=['POST'])
    def leave_team(team_id):
        """退出团队（所有者不能退出，需先转让或删除团队）"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err

        if team['owner_id'] == uid:
            return jsonify({'error': '团队所有者不能退出，请先转让所有权或删除团队'}), 400

        role = _check_member(team_id, uid)
        if not role:
            return jsonify({'error': '你不是该团队成员'}), 400

        success = db.remove_team_member(team_id, uid)
        return jsonify({'status': 'success' if success else 'error'})

    @bp.route('/<int:team_id>/transfer', methods=['POST'])
    def transfer_ownership(team_id):
        """转让团队所有权（仅当前所有者）"""
        uid, err = _require_login()
        if err:
            return err

        team, err = _get_team_or_404(team_id)
        if err:
            return err

        if team['owner_id'] != uid:
            return jsonify({'error': '仅所有者可转让所有权'}), 403

        data = request.get_json(silent=True) or {}
        new_owner_id = data.get('new_owner_id')
        if not new_owner_id:
            return jsonify({'error': '请指定新所有者'}), 400

        new_owner_id = int(new_owner_id)
        role = _check_member(team_id, new_owner_id)
        if not role:
            return jsonify({'error': '新所有者必须是团队成员'}), 400

        with db.engine.connect() as conn:
            conn.execute(
                db.text("UPDATE team_spaces SET owner_id = :new_owner WHERE id = :tid"),
                {'new_owner': new_owner_id, 'tid': team_id}
            )
            # 原所有者降为admin
            conn.execute(
                db.text("UPDATE team_members SET role = 'admin' WHERE team_id = :tid AND user_id = :uid"),
                {'tid': team_id, 'uid': uid}
            )
            # 新所有者角色设为owner
            conn.execute(
                db.text("UPDATE team_members SET role = 'owner' WHERE team_id = :tid AND user_id = :new_owner"),
                {'tid': team_id, 'new_owner': new_owner_id}
            )
            conn.commit()

        return jsonify({'status': 'success', 'new_owner_id': new_owner_id})

    return bp
