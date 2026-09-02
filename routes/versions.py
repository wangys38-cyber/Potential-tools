"""文档版本历史 Blueprint — v12.0
为牛马笔记、会议纪要、项目计划提供版本历史、对比、回滚功能。
"""
import time
import difflib
from flask import Blueprint, request, jsonify, session

import db


def create_versions_blueprint():
    bp = Blueprint('versions', __name__, url_prefix='/api/versions')

    def _current_user_id():
        return session.get('user_id')

    def _require_login():
        uid = _current_user_id()
        if not uid:
            return None, (jsonify({'error': '请先登录', 'need_login': True}), 401)
        return uid, None

    @bp.route('', methods=['GET'])
    def list_versions():
        """获取文档版本列表
        Query: doc_type, doc_id, limit
        """
        uid, err = _require_login()
        if err:
            return err

        doc_type = request.args.get('doc_type', '').strip()
        doc_id = request.args.get('doc_id', '').strip()
        limit = int(request.args.get('limit', 100) or 100)
        limit = min(limit, 500)

        if not doc_type or not doc_id:
            return jsonify({'error': '缺少 doc_type 或 doc_id 参数'}), 400

        versions = db.get_document_versions(uid, doc_type, doc_id, limit=limit)
        return jsonify({
            'status': 'success',
            'versions': [{
                'id': v['id'],
                'version_number': v['version_number'],
                'name': v.get('name', ''),
                'note': v.get('note', ''),
                'created_by': v.get('created_by', 0),
                'creator_name': v.get('creator_name', ''),
                'creator_avatar': v.get('creator_avatar', ''),
                'created_at': v['created_at'],
                'content_preview': (v.get('content', '') or '')[:200],
            } for v in versions],
            'total': len(versions)
        })

    @bp.route('/<int:version_id>', methods=['GET'])
    def get_version(version_id):
        """获取版本详情（含完整内容）"""
        uid, err = _require_login()
        if err:
            return err

        v = db.get_document_version_by_id(version_id)
        if not v:
            return jsonify({'error': '版本不存在'}), 404
        if v['user_id'] != uid:
            return jsonify({'error': '无权限访问'}), 403

        return jsonify({
            'status': 'success',
            'version': {
                'id': v['id'],
                'doc_type': v['doc_type'],
                'doc_id': v['doc_id'],
                'version_number': v['version_number'],
                'content': v.get('content', ''),
                'name': v.get('name', ''),
                'note': v.get('note', ''),
                'created_by': v.get('created_by', 0),
                'creator_name': v.get('creator_name', ''),
                'creator_avatar': v.get('creator_avatar', ''),
                'created_at': v['created_at'],
            }
        })

    @bp.route('/<int:version_id>/rollback', methods=['POST'])
    def rollback_version(version_id):
        """回滚到指定版本（创建新版本，不删历史）"""
        uid, err = _require_login()
        if err:
            return err

        v = db.get_document_version_by_id(version_id)
        if not v:
            return jsonify({'error': '版本不存在'}), 404
        if v['user_id'] != uid:
            return jsonify({'error': '无权限操作'}), 403

        # 创建新版本（回滚快照）
        new_id, new_ver = db.create_document_version(
            user_id=uid,
            doc_type=v['doc_type'],
            doc_id=v['doc_id'],
            content=v.get('content', ''),
            name=f'回滚至 v{v["version_number"]}',
            note=f'从版本 {v["version_number"]} 回滚',
            created_by=uid
        )

        return jsonify({
            'status': 'success',
            'new_version_id': new_id,
            'new_version_number': new_ver,
            'content': v.get('content', '')
        })

    @bp.route('/<int:version_id>', methods=['PUT'])
    def update_version_meta(version_id):
        """更新版本名称/备注"""
        uid, err = _require_login()
        if err:
            return err

        data = request.get_json(silent=True) or {}
        name = data.get('name')
        note = data.get('note')

        if name is None and note is None:
            return jsonify({'error': '没有需要更新的字段'}), 400

        success = db.update_document_version_meta(version_id, uid, name=name, note=note)
        if not success:
            return jsonify({'error': '更新失败或无权限'}), 400
        return jsonify({'status': 'success'})

    @bp.route('/diff', methods=['GET'])
    def diff_versions():
        """对比两个版本的差异
        Query: v1, v2 (版本ID)
        """
        uid, err = _require_login()
        if err:
            return err

        v1_id = request.args.get('v1', type=int)
        v2_id = request.args.get('v2', type=int)

        if not v1_id or not v2_id:
            return jsonify({'error': '缺少 v1 或 v2 参数'}), 400

        v1 = db.get_document_version_by_id(v1_id)
        v2 = db.get_document_version_by_id(v2_id)

        if not v1 or not v2:
            return jsonify({'error': '版本不存在'}), 404
        if v1['user_id'] != uid or v2['user_id'] != uid:
            return jsonify({'error': '无权限访问'}), 403

        content1 = (v1.get('content', '') or '').splitlines(keepends=True)
        content2 = (v2.get('content', '') or '').splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            content1, content2,
            fromfile=f'v{v1["version_number"]}',
            tofile=f'v{v2["version_number"]}',
            lineterm=''
        ))

        return jsonify({
            'status': 'success',
            'diff': diff,
            'v1': {'id': v1['id'], 'version_number': v1['version_number'], 'name': v1.get('name', ''), 'created_at': v1['created_at']},
            'v2': {'id': v2['id'], 'version_number': v2['version_number'], 'name': v2.get('name', ''), 'created_at': v2['created_at']},
        })

    @bp.route('/save', methods=['POST'])
    def save_version():
        """手动保存版本快照（前端在保存文档时调用）"""
        uid, err = _require_login()
        if err:
            return err

        data = request.get_json(silent=True) or {}
        doc_type = data.get('doc_type', '').strip()
        doc_id = data.get('doc_id', '').strip()
        content = data.get('content', '')
        name = data.get('name', '')
        note = data.get('note', '')

        if not doc_type or not doc_id:
            return jsonify({'error': '缺少 doc_type 或 doc_id'}), 400

        version_id, version_number = db.create_document_version(
            user_id=uid, doc_type=doc_type, doc_id=doc_id,
            content=content, name=name, note=note, created_by=uid
        )
        return jsonify({
            'status': 'success',
            'version_id': version_id,
            'version_number': version_number
        })

    @bp.route('/<int:version_id>', methods=['DELETE'])
    def delete_version(version_id):
        """删除版本（仅作者，不能删除当前最新版本如果只有一个版本）"""
        uid, err = _require_login()
        if err:
            return err

        v = db.get_document_version_by_id(version_id)
        if not v:
            return jsonify({'error': '版本不存在'}), 404
        if v['user_id'] != uid:
            return jsonify({'error': '无权限操作'}), 403

        # 检查是否是唯一版本
        versions = db.get_document_versions(uid, v['doc_type'], v['doc_id'], limit=500)
        if len(versions) <= 1:
            return jsonify({'error': '至少保留一个版本，无法删除'}), 400

        with db.engine.connect() as conn:
            conn.execute(
                db.text("DELETE FROM document_versions WHERE id = :id AND user_id = :uid"),
                {'id': version_id, 'uid': uid}
            )
            conn.commit()
        return jsonify({'status': 'success'})

    @bp.route('/<int:version_id>/restore', methods=['POST'])
    def restore_version_content(version_id):
        """获取版本内容用于恢复（前端调用后替换编辑器内容）"""
        uid, err = _require_login()
        if err:
            return err

        v = db.get_document_version_by_id(version_id)
        if not v:
            return jsonify({'error': '版本不存在'}), 404
        if v['user_id'] != uid:
            return jsonify({'error': '无权限访问'}), 403

        return jsonify({
            'status': 'success',
            'content': v.get('content', ''),
            'version_number': v['version_number'],
            'name': v.get('name', '')
        })

    return bp
