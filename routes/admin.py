"""
v9.1 用户管理 Blueprint — 管理员后台
提供用户列表、编辑、删除、重置密码、切换管理员权限等功能
"""
import secrets
import logging
from flask import Blueprint, request, jsonify, render_template, session

import db
import auth
from error_utils import safe_error

logger = logging.getLogger(__name__)


def create_admin_blueprint():
    """创建用户管理 Blueprint"""
    bp = Blueprint('admin', __name__)

    # ==================== 页面路由 ====================

    @bp.route('/admin/users')
    @auth.admin_required
    def admin_users_page():
        """用户管理页面"""
        return render_template('admin_users.html', nav_title='用户管理')

    # ==================== API 路由 ====================

    @bp.route('/api/admin/users', methods=['GET'])
    @auth.admin_required
    def api_get_users():
        """获取用户列表（分页、搜索）"""
        try:
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 20))
            search = request.args.get('search', '').strip()
            page = max(1, page)
            per_page = max(1, min(100, per_page))
            result = db.get_all_users(page=page, per_page=per_page, search=search)
            return jsonify({'status': 'success', **result})
        except Exception as e:
            logger.error(f"获取用户列表失败: {e}")
            return jsonify({'status': 'error', 'error': '获取用户列表失败'}), 500

    @bp.route('/api/admin/users/<int:user_id>', methods=['PUT'])
    @auth.admin_required
    def api_update_user(user_id):
        """更新用户信息"""
        try:
            data = request.get_json(silent=True) or {}
            updates = {}
            if 'name' in data:
                updates['name'] = data['name']
            if 'email' in data:
                updates['email'] = data['email']
            if 'username' in data:
                updates['username'] = data['username']
            if 'avatar' in data:
                updates['avatar'] = data['avatar']
            if 'is_admin' in data:
                updates['is_admin'] = 1 if data['is_admin'] else 0
            if not updates:
                return jsonify({'status': 'error', 'error': '没有需要更新的字段'}), 400
            success = db.update_user(user_id, **updates)
            if success:
                current = auth.get_current_user()
                if current and current['id'] == user_id and 'is_admin' in updates:
                    session['user_is_admin'] = bool(updates['is_admin'])
                return jsonify({'status': 'success', 'message': '用户信息已更新'})
            return jsonify({'status': 'error', 'error': '用户不存在'}), 404
        except Exception as e:
            logger.error(f"更新用户失败: {e}")
            return jsonify(safe_error(e)), 500

    @bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
    @auth.admin_required
    def api_delete_user(user_id):
        """删除用户（同时清理相关数据）"""
        try:
            current = auth.get_current_user()
            if current and current['id'] == user_id:
                return jsonify({'status': 'error', 'error': '不能删除当前登录用户'}), 400
            success = db.delete_user(user_id)
            if success:
                return jsonify({'status': 'success', 'message': '用户已删除'})
            return jsonify({'status': 'error', 'error': '用户不存在'}), 404
        except Exception as e:
            logger.error(f"删除用户失败: {e}")
            return jsonify(safe_error(e)), 500

    @bp.route('/api/admin/users/<int:user_id>/reset-password', methods=['POST'])
    @auth.admin_required
    def api_reset_password(user_id):
        """重置用户密码"""
        try:
            data = request.get_json(silent=True) or {}
            new_password = data.get('password', '').strip()
            if not new_password:
                new_password = secrets.token_urlsafe(8)
            if len(new_password) < 6:
                return jsonify({'status': 'error', 'error': '密码至少6位'}), 400
            success = db.update_user_password(user_id, new_password)
            if success:
                return jsonify({
                    'status': 'success',
                    'message': '密码已重置',
                    'new_password': new_password
                })
            return jsonify({'status': 'error', 'error': '用户不存在'}), 404
        except Exception as e:
            logger.error(f"重置密码失败: {e}")
            return jsonify(safe_error(e)), 500

    @bp.route('/api/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
    @auth.admin_required
    def api_toggle_admin(user_id):
        """切换用户管理员权限"""
        try:
            user = db.get_user_by_id(user_id)
            if not user:
                return jsonify({'status': 'error', 'error': '用户不存在'}), 404
            current_is_admin = bool(user.get('is_admin', 0))
            new_is_admin = not current_is_admin
            current = auth.get_current_user()
            if current and current['id'] == user_id and not new_is_admin:
                return jsonify({'status': 'error', 'error': '不能取消自己的管理员权限'}), 400
            success = db.set_user_admin(user_id, new_is_admin)
            if success:
                if current and current['id'] == user_id:
                    session['user_is_admin'] = new_is_admin
                return jsonify({
                    'status': 'success',
                    'message': '管理员权限已更新',
                    'is_admin': new_is_admin
                })
            return jsonify({'status': 'error', 'error': '操作失败'}), 500
        except Exception as e:
            logger.error(f"切换管理员权限失败: {e}")
            return jsonify(safe_error(e)), 500

    @bp.route('/api/admin/users/<int:user_id>/stats', methods=['GET'])
    @auth.admin_required
    def api_user_stats(user_id):
        """获取用户数据统计"""
        try:
            stats = db.get_user_stats(user_id)
            return jsonify({'status': 'success', **stats})
        except Exception as e:
            logger.error(f"获取用户统计失败: {e}")
            return jsonify(safe_error(e)), 500

    # ==================== 数据备份 / 恢复 ====================

    # 需要备份的用户相关表（按依赖顺序排列，恢复时按此顺序清空+重建）
    _BACKUP_TABLES = [
        'users', 'user_preferences', 'user_data', 'notes',
        'merit_records', 'chart_templates', 'dashboard_config',
        'app_config',
    ]

    @bp.route('/api/admin/backup', methods=['GET'])
    @auth.admin_required
    def api_backup():
        """导出全量数据为 JSON（管理员）"""
        import time as _time
        try:
            backup = {
                'version': 1,
                'exported_at': _time.time(),
                'db_type': db.DB_TYPE,
                'tables': {},
            }
            with db.engine.connect() as conn:
                for table in _BACKUP_TABLES:
                    rows = conn.execute(db.text(f"SELECT * FROM {table}")).fetchall()
                    backup['tables'][table] = [dict(r._mapping) for r in rows]
            return jsonify({'status': 'success', 'backup': backup})
        except Exception as e:
            logger.error(f"数据备份失败: {e}")
            return jsonify({'status': 'error', 'error': str(e)}), 500

    @bp.route('/api/admin/restore', methods=['POST'])
    @auth.admin_required
    def api_restore():
        """从 JSON 恢复全量数据（管理员，覆盖式）"""
        import time as _time
        try:
            data = request.get_json(silent=True) or {}
            backup = data.get('backup')
            if not backup or not isinstance(backup, dict) or 'tables' not in backup:
                return jsonify({'status': 'error', 'error': '无效的备份数据格式'}), 400

            tables = backup.get('tables', {})
            restored = {}
            with db.engine.begin() as conn:
                # 按逆序清空（先清子表再清父表，避免外键约束）
                for table in reversed(_BACKUP_TABLES):
                    if table in tables:
                        conn.execute(db.text(f"DELETE FROM {table}"))
                # 按正序恢复
                for table in _BACKUP_TABLES:
                    rows = tables.get(table, [])
                    if not rows:
                        restored[table] = 0
                        continue
                    # 获取列名
                    cols = list(rows[0].keys())
                    placeholders = ', '.join([f':{c}' for c in cols])
                    col_list = ', '.join(cols)
                    for row in rows:
                        conn.execute(
                            db.text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"),
                            row
                        )
                    restored[table] = len(rows)
            return jsonify({'status': 'success', 'restored': restored, 'message': '数据恢复成功'})
        except Exception as e:
            logger.error(f"数据恢复失败: {e}")
            return jsonify({'status': 'error', 'error': str(e)}), 500

    return bp
