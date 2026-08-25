"""通知系统 Blueprint — v12.0
简化版通知系统：@提及、评论回复、团队邀请、数据共享通知。
"""
import time
from flask import Blueprint, request, jsonify, session

import db


def create_notifications_blueprint():
    bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')

    def _current_user_id():
        return session.get('user_id')

    def _require_login():
        uid = _current_user_id()
        if not uid:
            return None, (jsonify({'error': '请先登录', 'need_login': True}), 401)
        return uid, None

    @bp.route('', methods=['GET'])
    def list_notifications():
        """获取通知列表（未读优先）"""
        uid, err = _require_login()
        if err:
            return err

        limit = int(request.args.get('limit', 50) or 50)
        limit = min(limit, 200)

        notifications = db.get_notifications(uid, limit=limit, unread_first=True)
        return jsonify({
            'status': 'success',
            'notifications': [{
                'id': n['id'],
                'type': n['type'],
                'title': n.get('title', ''),
                'content': n.get('content', ''),
                'link': n.get('link', ''),
                'is_read': bool(n.get('is_read', 0)),
                'created_at': n['created_at'],
            } for n in notifications],
            'total': len(notifications)
        })

    @bp.route('/unread-count', methods=['GET'])
    def unread_count():
        """获取未读通知数量"""
        uid, err = _require_login()
        if err:
            return err

        count = db.get_unread_notification_count(uid)
        return jsonify({'status': 'success', 'unread_count': count})

    @bp.route('/<int:notification_id>/read', methods=['PUT'])
    def mark_read(notification_id):
        """标记单条通知为已读"""
        uid, err = _require_login()
        if err:
            return err

        success = db.mark_notification_read(notification_id, uid)
        if not success:
            return jsonify({'error': '通知不存在或无权限'}), 404
        return jsonify({'status': 'success'})

    @bp.route('/read-all', methods=['PUT'])
    def mark_all_read():
        """标记所有通知为已读"""
        uid, err = _require_login()
        if err:
            return err

        count = db.mark_all_notifications_read(uid)
        return jsonify({'status': 'success', 'marked_count': count})

    return bp
