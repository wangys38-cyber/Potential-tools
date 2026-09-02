"""牛马笔记 Blueprint — v8.0 全面重构
提供页面路由和 REST API，支持登录用户云端同步、未登录用户 localStorage。
"""
from flask import Blueprint, request, jsonify, render_template, session
import auth
import db


def create_notes_blueprint():
    """创建牛马笔记 Blueprint"""
    bp = Blueprint('notes', __name__)

    # ==================== 页面路由 ====================

    @bp.route('/noteNB/')
    @bp.route('/notes')
    def notes_page():
        """牛马笔记页面"""
        return render_template('notes.html', nav_title='牛马笔记')

    # ==================== REST API ====================

    def _get_user_id():
        """从 session 获取当前用户 ID，未登录返回 None"""
        return session.get('user_id')

    @bp.route('/api/notes', methods=['GET'])
    def api_get_notes():
        """获取当前用户所有笔记"""
        user_id = _get_user_id()
        if not user_id:
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        try:
            notes = db.get_notes(user_id)
            return jsonify({'status': 'success', 'notes': notes})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @bp.route('/api/notes', methods=['POST'])
    def api_create_note():
        """创建笔记"""
        user_id = _get_user_id()
        if not user_id:
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        try:
            data = request.get_json(force=True, silent=True) or {}
            note_uid = data.get('id') or data.get('note_uid')
            if not note_uid:
                return jsonify({'error': '缺少笔记 ID'}), 400
            existing = db.get_note_by_uid(user_id, note_uid)
            if existing:
                return jsonify({'status': 'success', 'note': existing})
            note = db.create_note(
                user_id=user_id,
                note_uid=note_uid,
                title=data.get('title', ''),
                content=data.get('content', ''),
                category=data.get('category', ''),
                tags=data.get('tags', []),
                is_todo=data.get('is_todo', False),
                pinned=data.get('pinned', False),
                completed=data.get('completed', False),
            )
            return jsonify({'status': 'success', 'note': note})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @bp.route('/api/notes/<note_uid>', methods=['PUT'])
    def api_update_note(note_uid):
        """更新笔记"""
        user_id = _get_user_id()
        if not user_id:
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        try:
            data = request.get_json(force=True, silent=True) or {}

            # v12.0 自动保存版本快照（内容变更时）
            try:
                existing = db.get_note_by_uid(user_id, note_uid)
                new_content = data.get('content')
                if existing and new_content is not None and new_content != existing.get('content', ''):
                    db.create_document_version(
                        user_id=user_id, doc_type='note', doc_id=note_uid,
                        content=new_content, name='', note='自动保存', created_by=user_id
                    )
            except Exception:
                pass

            success = db.update_note(
                user_id=user_id,
                note_uid=note_uid,
                title=data.get('title'),
                content=data.get('content'),
                category=data.get('category'),
                tags=data.get('tags'),
                is_todo=data.get('is_todo'),
                pinned=data.get('pinned'),
                completed=data.get('completed'),
            )
            if not success:
                return jsonify({'error': '笔记不存在'}), 404
            note = db.get_note_by_uid(user_id, note_uid)
            return jsonify({'status': 'success', 'note': note})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @bp.route('/api/notes/<note_uid>', methods=['DELETE'])
    def api_delete_note(note_uid):
        """删除笔记"""
        user_id = _get_user_id()
        if not user_id:
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        try:
            success = db.delete_note(user_id, note_uid)
            if not success:
                return jsonify({'error': '笔记不存在'}), 404
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @bp.route('/api/notes/categories', methods=['GET'])
    def api_get_categories():
        """获取用户所有分类"""
        user_id = _get_user_id()
        if not user_id:
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        try:
            categories = db.get_note_categories(user_id)
            return jsonify({'status': 'success', 'categories': categories})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return bp
