"""用户数据、功德、笔记同步 Blueprint"""
from flask import Blueprint, request, jsonify
import logging
import json
from datetime import datetime, timezone, timedelta

bp = Blueprint('user', __name__)
logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


def register(app):
    """Register the blueprint with the app"""
    app.register_blueprint(bp)


# ==================== 用户信息 ====================

@bp.route('/api/user/info')
def api_user_info():
    """获取当前用户信息"""
    import auth
    user = auth.get_current_user()
    if not user:
        return jsonify({'logged_in': False})
    return jsonify({
        'logged_in': True,
        'user': {
            'id': user['id'],
            'name': user['name'],
            'email': user['email'],
            'avatar': user['avatar'],
            'provider': user['provider']
        }
    })


# ==================== 用户偏好 ====================

@bp.route('/api/user/preferences', methods=['GET', 'POST'])
def api_user_preferences():
    """用户偏好设置（主题模式等）"""
    import auth
    import db
    user = auth.get_current_user()

    if request.method == 'GET':
        if not user:
            return jsonify({'theme': 'auto', 'language': 'zh-CN'})
        prefs = db.get_user_preferences(user['id'])
        return jsonify(prefs)

    if request.method == 'POST':
        if not user:
            return jsonify({'error': '请先登录'}), 401
        data = request.get_json(silent=True) or {}
        theme = data.get('theme')
        language = data.get('language')
        try:
            db.set_user_preferences(user['id'], theme=theme, language=language)
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


# ==================== 功德 ====================

@bp.route('/api/merit')
def api_get_merit():
    """获取功德数据"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'total_count': 0, 'today_count': 0, 'today_date': ''})
    data = db.get_merit(user['id'])
    return jsonify({
        'total_count': data.get('total_count', 0),
        'today_count': data.get('today_count', 0),
        'today_date': data.get('today_date', '')
    })


@bp.route('/api/merit/increment', methods=['POST'])
def api_increment_merit():
    """功德+1"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    try:
        data = db.increment_merit(user['id'])
        return jsonify({
            'total_count': data.get('total_count', 0),
            'today_count': data.get('today_count', 0),
            'today_date': data.get('today_date', '')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== 用户报告存储 ====================

@bp.route('/api/user/save-report', methods=['POST'])
def api_user_save_report():
    """保存分析报告到用户账户"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json(silent=True) or {}
    report_data = data.get('report_data', {})
    title = data.get('title', f'分析报告_{datetime.now(_CST).strftime("%Y%m%d_%H%M%S")}')

    if not report_data:
        return jsonify({'error': '缺少报告数据'}), 400

    try:
        data_id = db.save_user_data(user['id'], 'test_report', title, report_data)
        return jsonify({'status': 'success', 'id': data_id, 'message': '报告已保存'})
    except Exception as e:
        logger.error(f"保存报告失败: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/user/reports')
def api_user_reports():
    """获取用户保存的报告列表"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    reports = db.get_user_data_list(user['id'], 'test_report', limit=50)
    result = [{
        'id': r['id'],
        'title': r.get('title', ''),
        'created_at': r.get('created_at', 0)
    } for r in reports]
    return jsonify({'reports': result})


@bp.route('/api/user/report/<int:report_id>')
def api_user_get_report(report_id):
    """获取用户保存的某份报告"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    report = db.get_user_data_by_id(user['id'], report_id)
    if not report:
        return jsonify({'error': '报告不存在'}), 404
    return jsonify({'report': report})


@bp.route('/api/user/report/<int:report_id>', methods=['DELETE'])
def api_user_delete_report(report_id):
    """删除用户保存的报告"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    success = db.delete_user_data(user['id'], report_id)
    if success:
        return jsonify({'status': 'success', 'message': '已删除'})
    return jsonify({'error': '删除失败'}), 404


# ==================== 笔记同步 ====================

@bp.route('/api/notes/sync', methods=['GET'])
def notes_sync_get():
    """获取服务端笔记数据（仅登录用户）"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录', 'need_login': True}), 401
    try:
        result = db.get_note_state(user['id'])
        if result and result['data']:
            return jsonify({
                'status': 'success',
                'data': result['data'],
                'server_updated_at': result['server_updated_at']
            })
        return jsonify({'status': 'success', 'data': None, 'server_updated_at': 0})
    except Exception as e:
        logger.error(f"获取笔记同步数据失败: {e}")
        return jsonify({'error': '服务器内部错误，请稍后重试'}), 500


@bp.route('/api/notes/sync', methods=['POST'])
def notes_sync_post():
    """保存笔记数据到服务端（仅登录用户）"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录', 'need_login': True}), 401
    try:
        data = request.get_json(silent=True)
        if not data or 'state' not in data:
            return jsonify({'error': '缺少 state 数据'}), 400
        # 限制数据大小（防止过大请求）
        state_str = json.dumps(data['state'], ensure_ascii=False)
        if len(state_str) > 5 * 1024 * 1024:  # 5MB 上限
            return jsonify({'error': '数据过大，请减少笔记数量或内容'}), 413
        server_time = db.save_note_state(user['id'], data['state'])
        return jsonify({'status': 'success', 'server_updated_at': server_time})
    except Exception as e:
        logger.error(f"保存笔记同步数据失败: {e}")
        return jsonify({'error': '服务器内部错误，请稍后重试'}), 500


# ==================== 文档仓库 ====================

_DOC_MAX_CONTENT = 500 * 1024  # 单篇文档 500KB 上限
_DOC_MAX_COUNT = 200  # 每用户最多 200 篇文档


@bp.route('/api/docs', methods=['GET'])
def docs_list():
    """获取文档列表"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录', 'need_login': True}), 401
    try:
        rows = db.get_user_data_list(user['id'], data_type='document', limit=500)
        # 列表只返回摘要，不返回完整内容
        docs = []
        for r in rows:
            content = r.get('content', '')
            if isinstance(content, dict):
                content = content.get('text', '')
            summary = (content[:200] + '...') if len(str(content)) > 200 else str(content)
            docs.append({
                'id': r['id'],
                'title': r.get('title', '未命名'),
                'summary': summary,
                'created_at': r.get('created_at', 0),
                'updated_at': r.get('created_at', 0),
            })
        total = db.count_user_data(user['id'], 'document')
        return jsonify({'status': 'success', 'docs': docs, 'total': total, 'max_count': _DOC_MAX_COUNT})
    except Exception as e:
        logger.error(f"获取文档列表失败: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@bp.route('/api/docs/<int:doc_id>', methods=['GET'])
def docs_get(doc_id):
    """获取单篇文档"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录', 'need_login': True}), 401
    try:
        doc = db.get_user_data_by_id(user['id'], doc_id)
        if not doc or doc.get('data_type') != 'document':
            return jsonify({'error': '文档不存在'}), 404
        content = doc.get('content', '')
        if isinstance(content, dict):
            content = content.get('text', '')
        return jsonify({
            'status': 'success',
            'doc': {
                'id': doc['id'],
                'title': doc.get('title', '未命名'),
                'content': content,
                'created_at': doc.get('created_at', 0),
                'updated_at': doc.get('created_at', 0),
            }
        })
    except Exception as e:
        logger.error(f"获取文档失败: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@bp.route('/api/docs', methods=['POST'])
def docs_create():
    """创建文档"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录', 'need_login': True}), 401
    try:
        data = request.get_json(silent=True) or {}
        title = (data.get('title') or '未命名文档').strip()[:200]
        content = data.get('content', '')

        if len(content) > _DOC_MAX_CONTENT:
            return jsonify({'error': f'文档内容过大（上限 {_DOC_MAX_CONTENT // 1024}KB）'}), 413

        count = db.count_user_data(user['id'], 'document')
        if count >= _DOC_MAX_COUNT:
            return jsonify({'error': f'文档数量已达上限（{_DOC_MAX_COUNT} 篇）'}), 413

        doc_id = db.save_user_data(user['id'], 'document', title, content)
        return jsonify({'status': 'success', 'id': doc_id, 'message': '文档已保存'})
    except Exception as e:
        logger.error(f"创建文档失败: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@bp.route('/api/docs/<int:doc_id>', methods=['PUT'])
def docs_update(doc_id):
    """更新文档"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录', 'need_login': True}), 401
    try:
        data = request.get_json(silent=True) or {}
        title = data.get('title')
        content = data.get('content')

        if content is not None and len(content) > _DOC_MAX_CONTENT:
            return jsonify({'error': f'文档内容过大（上限 {_DOC_MAX_CONTENT // 1024}KB）'}), 413

        if title is not None:
            title = title.strip()[:200]

        ok = db.update_user_data(user['id'], doc_id, title=title, content=content)
        if not ok:
            return jsonify({'error': '文档不存在或无更新'}), 404
        return jsonify({'status': 'success', 'message': '文档已更新'})
    except Exception as e:
        logger.error(f"更新文档失败: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@bp.route('/api/docs/<int:doc_id>', methods=['DELETE'])
def docs_delete(doc_id):
    """删除文档"""
    import auth
    import db
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录', 'need_login': True}), 401
    try:
        ok = db.delete_user_data(user['id'], doc_id)
        if not ok:
            return jsonify({'error': '文档不存在'}), 404
        return jsonify({'status': 'success', 'message': '文档已删除'})
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        return jsonify({'error': '服务器内部错误'}), 500
