"""
Potential-tools v8.1 鏁版嵁鍙鍖?Blueprint
- 鍥捐〃妯℃澘瀛樺偍锛堜娇鐢ㄤ富鏁版嵁搴撳紩鎿庯紝鏀寔 PostgreSQL / SQLite锛?
- Dashboard 閰嶇疆瀛樺偍
- 鍥捐〃鏁版嵁 API

v8.1 鍙樻洿锛?
- 浠庣嫭绔?SQLite 杩佺Щ鍒颁富鏁版嵁搴撳紩鎿庯紙db.py SQLAlchemy锛?
- 瑙ｅ喅 Railway 閲嶆柊閮ㄧ讲鍚庢暟鎹涪澶遍棶棰?
- 淇寮傚父淇℃伅娉勯湶锛坰tr(e) 鈫?safe_error锛?
"""
import os
import json
import time
import logging
from flask import Blueprint, request, jsonify, session
from sqlalchemy import text
from error_utils import safe_error

logger = logging.getLogger(__name__)

bp_viz = Blueprint('visualization', __name__)


def _get_user_id():
    """鑾峰彇褰撳墠鐢ㄦ埛ID"""
    return str(session.get('user_id', 'guest'))


# ========== 鍥捐〃妯℃澘 API ==========

@bp_viz.route('/api/chart-templates', methods=['GET'])
def list_templates():
    """鑾峰彇褰撳墠鐢ㄦ埛鐨勫浘琛ㄦā鏉垮垪琛?""
    try:
        import db
        user_id = _get_user_id()
        chart_type = request.args.get('type', '')

        query = "SELECT id, name, chart_type, config, created_at, updated_at FROM chart_templates WHERE user_id = :user_id"
        params = {'user_id': user_id}
        if chart_type:
            query += " AND chart_type = :chart_type"
            params['chart_type'] = chart_type
        query += " ORDER BY updated_at DESC"

        with db.engine.connect() as conn:
            rows = conn.execute(text(query), params).fetchall()

        templates = []
        for r in rows:
            try:
                config = json.loads(r['config']) if r['config'] else {}
            except Exception:
                config = {}
            templates.append({
                'id': r['id'],
                'name': r['name'],
                'chart_type': r['chart_type'],
                'config': config,
                'created_at': r['created_at'],
                'updated_at': r['updated_at']
            })
        return jsonify({'status': 'success', 'templates': templates})
    except Exception as e:
        logger.error(f"鑾峰彇鍥捐〃妯℃澘澶辫触: {e}")
        return jsonify(safe_error(e)), 500


@bp_viz.route('/api/chart-templates', methods=['POST'])
def save_template():
    """淇濆瓨鍥捐〃妯℃澘"""
    try:
        import db
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        chart_type = data.get('chart_type', 'bar')
        config = data.get('config', {})
        if not name:
            return jsonify({'status': 'error', 'error': '妯℃澘鍚嶇О涓嶈兘涓虹┖'}), 400

        user_id = _get_user_id()
        now = time.time()
        config_str = json.dumps(config, ensure_ascii=False)

        with db.engine.begin() as conn:
            result = conn.execute(
                text("INSERT INTO chart_templates (user_id, name, chart_type, config, created_at, updated_at) VALUES (:user_id, :name, :chart_type, :config, :created_at, :updated_at)"),
                {'user_id': user_id, 'name': name, 'chart_type': chart_type, 'config': config_str, 'created_at': now, 'updated_at': now}
            )
            template_id = result.lastrowid

        return jsonify({'status': 'success', 'id': template_id})
    except Exception as e:
        logger.error(f"淇濆瓨鍥捐〃妯℃澘澶辫触: {e}")
        return jsonify(safe_error(e)), 500


@bp_viz.route('/api/chart-templates/<int:tpl_id>', methods=['PUT'])
def update_template(tpl_id):
    """鏇存柊鍥捐〃妯℃澘"""
    try:
        import db
        data = request.get_json(silent=True) or {}
        user_id = _get_user_id()
        now = time.time()

        with db.engine.begin() as conn:
            row = conn.execute(
                text("SELECT id FROM chart_templates WHERE id = :id AND user_id = :user_id"),
                {'id': tpl_id, 'user_id': user_id}
            ).fetchone()
            if not row:
                return jsonify({'status': 'error', 'error': '妯℃澘涓嶅瓨鍦?}), 404

            name = data.get('name')
            config = data.get('config')
            if name:
                conn.execute(
                    text("UPDATE chart_templates SET name = :name, updated_at = :updated_at WHERE id = :id AND user_id = :user_id"),
                    {'name': name, 'updated_at': now, 'id': tpl_id, 'user_id': user_id}
                )
            if config is not None:
                conn.execute(
                    text("UPDATE chart_templates SET config = :config, updated_at = :updated_at WHERE id = :id AND user_id = :user_id"),
                    {'config': json.dumps(config, ensure_ascii=False), 'updated_at': now, 'id': tpl_id, 'user_id': user_id}
                )
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"鏇存柊鍥捐〃妯℃澘澶辫触: {e}")
        return jsonify(safe_error(e)), 500


@bp_viz.route('/api/chart-templates/<int:tpl_id>', methods=['DELETE'])
def delete_template(tpl_id):
    """鍒犻櫎鍥捐〃妯℃澘"""
    try:
        import db
        user_id = _get_user_id()
        with db.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM chart_templates WHERE id = :id AND user_id = :user_id"),
                {'id': tpl_id, 'user_id': user_id}
            )
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"鍒犻櫎鍥捐〃妯℃澘澶辫触: {e}")
        return jsonify(safe_error(e)), 500


# ========== Dashboard 閰嶇疆 API ==========

@bp_viz.route('/api/dashboard/config', methods=['GET'])
def get_dashboard_config():
    """鑾峰彇 Dashboard 閰嶇疆"""
    try:
        import db
        user_id = _get_user_id()
        key = request.args.get('key', 'default')

        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT config_value FROM dashboard_config WHERE user_id = :user_id AND config_key = :config_key"),
                {'user_id': user_id, 'config_key': key}
            ).fetchone()

        if row:
            return jsonify({'status': 'success', 'config': json.loads(row['config_value'])})
        return jsonify({'status': 'success', 'config': None})
    except Exception as e:
        logger.error(f"鑾峰彇 Dashboard 閰嶇疆澶辫触: {e}")
        return jsonify(safe_error(e)), 500


@bp_viz.route('/api/dashboard/config', methods=['POST'])
def save_dashboard_config():
    """淇濆瓨 Dashboard 閰嶇疆"""
    try:
        import db
        data = request.get_json(silent=True) or {}
        key = data.get('key', 'default')
        config = data.get('config', {})
        user_id = _get_user_id()
        now = time.time()
        config_str = json.dumps(config, ensure_ascii=False)

        with db.engine.begin() as conn:
            # 浣跨敤 UPSERT 璇硶锛圥ostgreSQL 鍜?SQLite 鍧囨敮鎸?ON CONFLICT锛?
            conn.execute(
                text("""
                    INSERT INTO dashboard_config (user_id, config_key, config_value, updated_at)
                    VALUES (:user_id, :config_key, :config_value, :updated_at)
                    ON CONFLICT(user_id, config_key)
                    DO UPDATE SET config_value = excluded.config_value, updated_at = excluded.updated_at
                """),
                {'user_id': user_id, 'config_key': key, 'config_value': config_str, 'updated_at': now}
            )
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"淇濆瓨 Dashboard 閰嶇疆澶辫触: {e}")
        return jsonify(safe_error(e)), 500


# ========== Dashboard 缁熻鏁版嵁 API ==========

@bp_viz.route('/api/dashboard/stats', methods=['GET'])
def dashboard_stats():
    """鑾峰彇 Dashboard 缁熻鏁版嵁锛堜粠 localStorage 涓浆锛屽悗绔彁渚涜仛鍚堬級"""
    try:
        return jsonify({
            'status': 'success',
            'data': {
                'bug_trend': None,
                'mttf': None,
                'version_progress': None,
                'personal_efficiency': None,
                'project_overview': None,
                'rd_efficiency': None
            }
        })
    except Exception as e:
        logger.error(f"鑾峰彇 Dashboard 缁熻澶辫触: {e}")
        return jsonify(safe_error(e)), 500


def create_visualization_blueprint():
    """鍒涘缓鍙鍖?Blueprint"""
    return bp_viz
