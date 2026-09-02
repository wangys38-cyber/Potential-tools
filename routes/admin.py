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
        'app_config', 'audit_logs', 'login_attempts', 'user_sessions',
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

    # ==================== 阶段四 安全加固：审计日志 ====================

    @bp.route('/api/admin/audit-logs', methods=['GET'])
    @auth.admin_required
    def api_audit_logs():
        """获取审计日志（分页、筛选）"""
        try:
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 50))
            user_id = request.args.get('user_id', '').strip()
            action = request.args.get('action', '').strip()
            search = request.args.get('search', '').strip()
            page = max(1, page)
            per_page = max(1, min(200, per_page))
            uid = int(user_id) if user_id.isdigit() else None
            result = db.get_audit_logs(page=page, per_page=per_page,
                                       user_id=uid, action=action or None,
                                       search=search)
            return jsonify({'status': 'success', **result})
        except Exception as e:
            logger.error(f"获取审计日志失败: {e}")
            return jsonify({'status': 'error', 'error': '获取审计日志失败'}), 500

    # ==================== 阶段四 安全加固：自动备份 ====================

    @bp.route('/api/admin/auto-backup', methods=['POST'])
    @auth.admin_required
    def api_auto_backup():
        """触发自动备份（管理员手动触发，返回备份文件信息）"""
        import os as _os
        import json as _json
        import time as _time
        try:
            backup_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), 'backups')
            _os.makedirs(backup_dir, exist_ok=True)

            # 恢复前自动快照
            backup = {
                'version': 1,
                'exported_at': _time.time(),
                'db_type': db.DB_TYPE,
                'tables': {},
            }
            with db.engine.connect() as conn:
                for table in _BACKUP_TABLES:
                    try:
                        rows = conn.execute(db.text(f"SELECT * FROM {table}")).fetchall()
                        backup['tables'][table] = [dict(r._mapping) for r in rows]
                    except Exception:
                        backup['tables'][table] = []

            timestamp = _time.strftime('%Y%m%d_%H%M%S')
            filename = f'backup_{timestamp}.json'
            filepath = _os.path.join(backup_dir, filename)

            # 加密备份（使用 crypto_utils）
            try:
                import crypto_utils
                backup_str = _json.dumps(backup, ensure_ascii=False)
                encrypted = crypto_utils.encrypt(backup_str)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(encrypted)
            except Exception:
                with open(filepath, 'w', encoding='utf-8') as f:
                    _json.dump(backup, f, ensure_ascii=False)

            # 清理旧备份（保留7天每日 + 4周每周）
            _cleanup_old_backups(backup_dir)

            current = auth.get_current_user()
            db.add_audit_log(
                current['id'] if current else None, 'backup_create',
                target_type='system', target_id=filename,
                ip=request.remote_addr or '',
                user_agent=request.headers.get('User-Agent', ''),
                details=f'管理员创建备份: {filename}'
            )

            return jsonify({'status': 'success', 'filename': filename, 'records': sum(len(v) for v in backup['tables'].values())})
        except Exception as e:
            logger.error(f"自动备份失败: {e}")
            return jsonify({'status': 'error', 'error': str(e)}), 500


    # ==================== 管理员性能监控看板 ====================

    @bp.route('/admin/performance')
    @auth.admin_required
    def admin_performance_page():
        """管理员性能监控看板页面"""
        return render_template('admin_performance.html', nav_title='性能监控')

    @bp.route('/api/admin/performance', methods=['GET'])
    @auth.admin_required
    def api_admin_performance():
        """获取实时性能指标（请求统计 + 系统指标 + 慢查询）"""
        try:
            import performance_middleware
            import system_metrics
            import alerting

            # 请求性能指标
            perf = performance_middleware._get_metrics_snapshot() if hasattr(performance_middleware, '_get_metrics_snapshot') else {}

            # 直接从 performance_middleware 获取统计
            with performance_middleware._lock:
                times = sorted(performance_middleware._response_times)
                count = len(times)
                def _pct(p):
                    if count == 0:
                        return 0
                    idx = min(int(count * p / 100), count - 1)
                    return round(times[idx], 1)
                request_stats = {
                    'total_requests': performance_middleware._total_requests,
                    'slow_requests': performance_middleware._slow_requests,
                    'slow_rate_pct': round(performance_middleware._slow_requests / performance_middleware._total_requests * 100, 2) if performance_middleware._total_requests else 0,
                    'avg_ms': round(performance_middleware._total_response_time / performance_middleware._total_requests, 1) if performance_middleware._total_requests else 0,
                    'p50_ms': _pct(50),
                    'p95_ms': _pct(95),
                    'p99_ms': _pct(99),
                    'max_ms': round(times[-1], 1) if times else 0,
                    'min_ms': round(times[0], 1) if times else 0,
                    'sample_count': count,
                }

            # 告警窗口统计（5分钟滑动窗口，含5xx错误率）
            alert_stats = alerting.get_request_stats()

            # 系统指标
            sys_summary = system_metrics.get_summary()
            sys_history = system_metrics.get_history(limit=60)

            # 慢查询日志
            slow_logs = performance_middleware.get_slow_logs(limit=20)

            return jsonify({
                'status': 'success',
                'request_stats': request_stats,
                'alert_window': alert_stats,
                'system': sys_summary,
                'system_history': sys_history,
                'slow_logs': slow_logs,
                'threshold_ms': performance_middleware.SLOW_QUERY_THRESHOLD_MS,
            })
        except Exception as e:
            logger.error(f"获取性能指标失败: {e}")
            return jsonify({'status': 'error', 'error': str(e)}), 500

    # ==================== 告警管理 API ====================

    @bp.route('/api/admin/alerts', methods=['GET'])
    @auth.admin_required
    def api_admin_alerts():
        """获取告警历史"""
        try:
            import alerting
            limit = int(request.args.get('limit', 50))
            alert_type = request.args.get('type', '').strip() or None
            level = request.args.get('level', '').strip() or None
            history = alerting.get_alert_history(limit=limit, alert_type=alert_type, level=level)
            summary = alerting.get_alert_summary()
            return jsonify({'status': 'success', 'alerts': history, 'summary': summary})
        except Exception as e:
            logger.error(f"获取告警历史失败: {e}")
            return jsonify({'status': 'error', 'error': str(e)}), 500

    @bp.route('/api/admin/alerts/config', methods=['GET'])
    @auth.admin_required
    def api_admin_alert_config():
        """获取告警配置"""
        try:
            import alerting
            config = alerting.get_config()
            return jsonify({'status': 'success', **config})
        except Exception as e:
            logger.error(f"获取告警配置失败: {e}")
            return jsonify({'status': 'error', 'error': str(e)}), 500

    @bp.route('/api/admin/alerts/config', methods=['POST'])
    @auth.admin_required
    def api_admin_update_alert_config():
        """更新告警配置"""
        try:
            import alerting
            data = request.get_json(silent=True) or {}
            alerting.update_config(
                enabled=data.get('enabled'),
                feishu_webhook=data.get('feishu_webhook'),
                feishu_secret=data.get('feishu_secret'),
                thresholds=data.get('thresholds'),
                alert_types=data.get('alert_types'),
            )
            current = auth.get_current_user()
            db.add_audit_log(
                current['id'] if current else None, 'alert_config_update',
                target_type='system', target_id='alerting',
                ip=request.remote_addr or '',
                user_agent=request.headers.get('User-Agent', ''),
                details='管理员更新告警配置'
            )
            return jsonify({'status': 'success', 'message': '告警配置已更新'})
        except Exception as e:
            logger.error(f"更新告警配置失败: {e}")
            return jsonify({'status': 'error', 'error': str(e)}), 500

    @bp.route('/api/admin/alerts/test', methods=['POST'])
    @auth.admin_required
    def api_admin_test_alert():
        """发送测试告警（验证飞书 Webhook）"""
        try:
            import alerting
            data = request.get_json(silent=True) or {}
            alert_type = data.get('type', 'error_rate')
            ok, msg = alerting.test_alert(alert_type)
            if ok:
                return jsonify({'status': 'success', 'message': msg})
            return jsonify({'status': 'error', 'error': msg}), 400
        except Exception as e:
            logger.error(f"测试告警失败: {e}")
            return jsonify({'status': 'error', 'error': str(e)}), 500

    return bp


def _cleanup_old_backups(backup_dir):
    """清理旧备份文件：保留最近7天每日 + 最近4周每周"""
    import os as _os
    import time as _time
    import re as _re
    try:
        if not _os.path.isdir(backup_dir):
            return
        now = _time.time()
        files = []
        for f in _os.listdir(backup_dir):
            if f.startswith('backup_') and f.endswith('.json'):
                filepath = _os.path.join(backup_dir, f)
                mtime = _os.path.getmtime(filepath)
                files.append((filepath, mtime, f))

        # 按时间倒序
        files.sort(key=lambda x: x[1], reverse=True)

        keep = set()
        daily_cutoff = now - 7 * 86400
        weekly_cutoff = now - 28 * 86400
        seen_weeks = set()

        for filepath, mtime, fname in files:
            age_days = (now - mtime) / 86400
            if age_days <= 7:
                keep.add(filepath)  # 7天内全部保留
            elif age_days <= 28:
                # 28天内每周保留一个
                week_num = int((now - mtime) / (7 * 86400))
                if week_num not in seen_weeks:
                    seen_weeks.add(week_num)
                    keep.add(filepath)

        # 删除不在保留列表中的
        for filepath, _, _ in files:
            if filepath not in keep:
                try:
                    _os.remove(filepath)
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"清理旧备份失败: {e}")
