"""云端同步路由 Blueprint — /api/sync/*"""
import time
import logging
from flask import Blueprint, request, jsonify

import auth
import db
from error_utils import safe_error

logger = logging.getLogger(__name__)


def create_sync_blueprint():
    """创建同步路由 Blueprint"""
    bp = Blueprint('sync', __name__)

    @bp.route('/api/sync/pull', methods=['GET'])
    def api_sync_pull():
        """拉取云端同步数据"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'status': 'error', 'error': '请先登录'}), 401
        try:
            data = db.get_all_sync_states(user['id'])
            return jsonify({'status': 'success', 'data': data, 'server_time': time.time()})
        except Exception as e:
            logger.error(f'同步拉取异常: {e}')
            return jsonify(safe_error(e)), 500

    @bp.route('/api/sync/push', methods=['POST'])
    def api_sync_push():
        """推送本地数据到云端（支持多类型批量，带冲突检测）

        请求体:
        {
            "items": {
                "favorites": { "data": {...}, "client_updated_at": 1234567890.0 }
            }
        }
        兼容旧格式: { "items": { "favorites": {...} } }
        """
        user = auth.get_current_user()
        if not user:
            return jsonify({'status': 'error', 'error': '请先登录'}), 401
        data = request.get_json(silent=True) or {}
        items = data.get('items', {})
        if not isinstance(items, dict) or not items:
            return jsonify({'status': 'error', 'error': '无效的同步数据'}), 400

        results = {}
        for dtype, payload in items.items():
            if dtype not in db.SYNC_TYPES:
                results[dtype] = {'status': 'error', 'error': '不支持的同步类型'}
                continue

            try:
                # 兼容新旧格式
                if isinstance(payload, dict) and 'data' in payload:
                    content = payload['data']
                    client_ts = payload.get('client_updated_at', 0)
                else:
                    content = payload
                    client_ts = 0

                # 冲突检测：如果客户端时间戳早于服务端，返回冲突
                if client_ts > 0:
                    server_state = db.get_sync_state(user['id'], dtype)
                    server_ts = server_state['updated_at'] if server_state else 0
                    if server_ts > client_ts:
                        results[dtype] = {
                            'status': 'conflict',
                            'server_data': server_state['data'] if server_state else None,
                            'server_updated_at': server_ts,
                            'message': '服务端数据更新，已拒绝覆盖'
                        }
                        continue

                ts = db.set_sync_state(user['id'], dtype, content)
                results[dtype] = {'status': 'success', 'updated_at': ts}
            except Exception as e:
                logger.error(f'同步推送失败 [{dtype}]: {e}')
                results[dtype] = {'status': 'error', 'error': '同步失败'}
        return jsonify({'status': 'success', 'results': results, 'server_time': time.time()})

    @bp.route('/api/sync/status', methods=['GET'])
    def api_sync_status():
        """获取同步状态（各类型最新更新时间）"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'status': 'error', 'error': '请先登录'}), 401
        try:
            status = db.get_sync_status(user['id'])
            return jsonify({'status': 'success', 'sync_status': status, 'server_time': time.time()})
        except Exception as e:
            logger.error(f'同步状态查询异常: {e}')
            return jsonify(safe_error(e)), 500

    return bp
