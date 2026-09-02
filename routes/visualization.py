"""
Potential-tools v8.0 数据可视化 Blueprint
- 图表模板存储（SQLite）
- Dashboard 配置存储
- 图表数据 API
"""
import os
import json
import sqlite3
from flask import Blueprint, request, jsonify, session, g

bp_viz = Blueprint('visualization', __name__)

# ========== 数据库初始化 ==========
def _get_db_path():
    """获取可视化数据库路径"""
    if os.environ.get('RAILWAY_STATIC_URL') or os.environ.get('PORT'):
        return '/tmp/toolbox/visualization.db'
    base = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base, 'visualization.db')

def _get_db():
    """获取数据库连接（请求级缓存）"""
    if 'viz_db' not in g:
        db_path = _get_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        g.viz_db = sqlite3.connect(db_path)
        g.viz_db.row_factory = sqlite3.Row
        g.viz_db.execute("PRAGMA journal_mode=WAL")
    return g.viz_db

def _init_db():
    """初始化数据库表"""
    db_path = _get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chart_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT 'guest',
            name TEXT NOT NULL,
            chart_type TEXT NOT NULL,
            config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT 'guest',
            config_key TEXT NOT NULL,
            config_value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, config_key)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_templates_user ON chart_templates(user_id)")
    conn.commit()
    conn.close()

# 模块加载时初始化
_init_db()

def _get_user_id():
    """获取当前用户ID"""
    return str(session.get('user_id', 'guest'))


# ========== 图表模板 API ==========

@bp_viz.route('/api/chart-templates', methods=['GET'])
def list_templates():
    """获取当前用户的图表模板列表"""
    try:
        db = _get_db()
        user_id = _get_user_id()
        chart_type = request.args.get('type', '')
        query = "SELECT id, name, chart_type, config, created_at, updated_at FROM chart_templates WHERE user_id = ?"
        params = [user_id]
        if chart_type:
            query += " AND chart_type = ?"
            params.append(chart_type)
        query += " ORDER BY updated_at DESC"
        rows = db.execute(query, params).fetchall()
        templates = []
        for r in rows:
            try:
                config = json.loads(r['config'])
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
        return jsonify({'status': 'error', 'error': str(e)}), 500


@bp_viz.route('/api/chart-templates', methods=['POST'])
def save_template():
    """保存图表模板"""
    try:
        data = request.get_json(force=True)
        name = (data.get('name') or '').strip()
        chart_type = data.get('chart_type', 'bar')
        config = data.get('config', {})
        if not name:
            return jsonify({'status': 'error', 'error': '模板名称不能为空'}), 400
        db = _get_db()
        user_id = _get_user_id()
        cursor = db.execute(
            "INSERT INTO chart_templates (user_id, name, chart_type, config) VALUES (?, ?, ?, ?)",
            (user_id, name, chart_type, json.dumps(config, ensure_ascii=False))
        )
        db.commit()
        return jsonify({'status': 'success', 'id': cursor.lastrowid})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@bp_viz.route('/api/chart-templates/<int:tpl_id>', methods=['PUT'])
def update_template(tpl_id):
    """更新图表模板"""
    try:
        data = request.get_json(force=True)
        db = _get_db()
        user_id = _get_user_id()
        row = db.execute("SELECT id FROM chart_templates WHERE id = ? AND user_id = ?", (tpl_id, user_id)).fetchone()
        if not row:
            return jsonify({'status': 'error', 'error': '模板不存在'}), 404
        name = data.get('name')
        config = data.get('config')
        if name:
            db.execute("UPDATE chart_templates SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, tpl_id))
        if config is not None:
            db.execute("UPDATE chart_templates SET config = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                       (json.dumps(config, ensure_ascii=False), tpl_id))
        db.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@bp_viz.route('/api/chart-templates/<int:tpl_id>', methods=['DELETE'])
def delete_template(tpl_id):
    """删除图表模板"""
    try:
        db = _get_db()
        user_id = _get_user_id()
        db.execute("DELETE FROM chart_templates WHERE id = ? AND user_id = ?", (tpl_id, user_id))
        db.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ========== Dashboard 配置 API ==========

@bp_viz.route('/api/dashboard/config', methods=['GET'])
def get_dashboard_config():
    """获取 Dashboard 配置"""
    try:
        db = _get_db()
        user_id = _get_user_id()
        key = request.args.get('key', 'default')
        row = db.execute(
            "SELECT config_value FROM dashboard_config WHERE user_id = ? AND config_key = ?",
            (user_id, key)
        ).fetchone()
        if row:
            return jsonify({'status': 'success', 'config': json.loads(row['config_value'])})
        return jsonify({'status': 'success', 'config': None})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@bp_viz.route('/api/dashboard/config', methods=['POST'])
def save_dashboard_config():
    """保存 Dashboard 配置"""
    try:
        data = request.get_json(force=True)
        key = data.get('key', 'default')
        config = data.get('config', {})
        db = _get_db()
        user_id = _get_user_id()
        db.execute(
            """INSERT INTO dashboard_config (user_id, config_key, config_value) VALUES (?, ?, ?)
               ON CONFLICT(user_id, config_key) DO UPDATE SET config_value = excluded.config_value, updated_at = CURRENT_TIMESTAMP""",
            (user_id, key, json.dumps(config, ensure_ascii=False))
        )
        db.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ========== Dashboard 统计数据 API ==========

@bp_viz.route('/api/dashboard/stats', methods=['GET'])
def dashboard_stats():
    """获取 Dashboard 统计数据（从 localStorage 中转，后端提供聚合）"""
    try:
        # 从 session 或共享存储获取 CR 分析历史
        # 由于数据主要存在前端 localStorage，这里提供基础结构
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
        return jsonify({'status': 'error', 'error': str(e)}), 500


def create_visualization_blueprint():
    """创建可视化 Blueprint"""
    return bp_viz
