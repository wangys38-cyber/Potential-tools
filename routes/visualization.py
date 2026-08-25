"""
Potential-tools v8.1 数据可视化 Blueprint
- 图表模板存储（使用主数据库引擎，支持 PostgreSQL / SQLite）
- Dashboard 配置存储
- 图表数据 API

v8.1 变更：
- 从独立 SQLite 迁移到主数据库引擎（db.py SQLAlchemy）
- 解决 Railway 重新部署后数据丢失问题
- 修复异常信息泄露（str(e) → safe_error）
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
    """获取当前用户ID"""
    return str(session.get('user_id', 'guest'))


# ========== 图表模板 API ==========

@bp_viz.route('/api/chart-templates', methods=['GET'])
def list_templates():
    """获取当前用户的图表模板列表"""
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
        logger.error(f"获取图表模板失败: {e}")
        return jsonify(safe_error(e)), 500


@bp_viz.route('/api/chart-templates', methods=['POST'])
def save_template():
    """保存图表模板"""
    try:
        import db
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        chart_type = data.get('chart_type', 'bar')
        config = data.get('config', {})
        if not name:
            return jsonify({'status': 'error', 'error': '模板名称不能为空'}), 400

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
        logger.error(f"保存图表模板失败: {e}")
        return jsonify(safe_error(e)), 500


@bp_viz.route('/api/chart-templates/<int:tpl_id>', methods=['PUT'])
def update_template(tpl_id):
    """更新图表模板"""
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
                return jsonify({'status': 'error', 'error': '模板不存在'}), 404

            name = data.get('name')
            config = data.get('config')
            if name:
                conn.execute(
                    text("UPDATE chart_templates SET name = :name, updated_at = :updated_at WHERE id = :id"),
                    {'name': name, 'updated_at': now, 'id': tpl_id}
                )
            if config is not None:
                conn.execute(
                    text("UPDATE chart_templates SET config = :config, updated_at = :updated_at WHERE id = :id"),
                    {'config': json.dumps(config, ensure_ascii=False), 'updated_at': now, 'id': tpl_id}
                )
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"更新图表模板失败: {e}")
        return jsonify(safe_error(e)), 500


@bp_viz.route('/api/chart-templates/<int:tpl_id>', methods=['DELETE'])
def delete_template(tpl_id):
    """删除图表模板"""
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
        logger.error(f"删除图表模板失败: {e}")
        return jsonify(safe_error(e)), 500


# ========== Dashboard 配置 API ==========

@bp_viz.route('/api/dashboard/config', methods=['GET'])
def get_dashboard_config():
    """获取 Dashboard 配置"""
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
        logger.error(f"获取 Dashboard 配置失败: {e}")
        return jsonify(safe_error(e)), 500


@bp_viz.route('/api/dashboard/config', methods=['POST'])
def save_dashboard_config():
    """保存 Dashboard 配置"""
    try:
        import db
        data = request.get_json(silent=True) or {}
        key = data.get('key', 'default')
        config = data.get('config', {})
        user_id = _get_user_id()
        now = time.time()
        config_str = json.dumps(config, ensure_ascii=False)

        with db.engine.begin() as conn:
            # 使用 UPSERT 语法（PostgreSQL 和 SQLite 均支持 ON CONFLICT）
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
        logger.error(f"保存 Dashboard 配置失败: {e}")
        return jsonify(safe_error(e)), 500


# ========== Dashboard 统计数据 API ==========

@bp_viz.route('/api/dashboard/stats', methods=['GET'])
def dashboard_stats():
    """获取 Dashboard 统计数据（从 localStorage 中转，后端提供聚合）"""
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
        logger.error(f"获取 Dashboard 统计失败: {e}")
        return jsonify(safe_error(e)), 500


def create_visualization_blueprint():
    """创建可视化 Blueprint"""
    return bp_viz
