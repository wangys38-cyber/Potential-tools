# -*- coding: utf-8 -*-
"""项目状态助手路由 Blueprint。

- GET  /api/project/list              列出可访问项目（datalist 自动补全）
- POST /api/project/load              输入项目 -> 后台拉取+分析生成状态快照（轮询 /api/task-status）
- GET  /api/project/snapshot/<key>    读取已缓存快照
- POST /api/project/chat              基于快照多轮对话（SSE 流式）
"""
import os
import json
import time
import hashlib
import logging
import threading
import traceback

from flask import Blueprint, request, jsonify, Response, current_app

from auth import login_required_or_guest
from routes.common import background_tasks, save_task_meta
from services import project_assistant as pa
from services import jira_client as jc

logger = logging.getLogger(__name__)


def create_project_blueprint():
    bp = Blueprint('project_assistant', __name__)

    # ---------------- 项目列表 ----------------
    @bp.route('/api/project/list', methods=['GET'])
    @login_required_or_guest
    def project_list():
        force = request.args.get('force', '0') == '1'
        try:
            projects = pa.list_projects(force=force)
            return jsonify({'status': 'success', 'data': projects})
        except jc.JiraError as e:
            return jsonify({'status': 'error', 'error': str(e)}), 200
        except Exception as e:
            logger.error('获取项目列表失败: %s', traceback.format_exc())
            return jsonify({'status': 'error',
                            'error': f'{type(e).__name__}: {e}'}), 200

    # ---------------- 加载 / 生成项目状态（后台任务） ----------------
    @bp.route('/api/project/load', methods=['POST'])
    @login_required_or_guest
    def project_load():
        data = request.get_json(silent=True) or {}
        project_text = (data.get('project') or data.get('project_key') or '').strip()
        force = bool(data.get('force'))
        if not project_text:
            return jsonify({'status': 'error', 'error': '请输入 Project Key 或项目名称'}), 400

        task_id = hashlib.md5(f'pa_{time.time()}'.encode()).hexdigest()[:16]
        task = {'status': 'processing', 'result': None, 'error': None,
                'created_at': time.time(), 'progress': 2,
                'progress_msg': '正在准备...'}
        background_tasks[task_id] = task
        save_task_meta(task_id, task)

        def _set(pct, msg):
            t = background_tasks.get(task_id)
            if t:
                t['progress'] = max(t.get('progress', 0), int(pct))
                t['progress_msg'] = msg
                save_task_meta(task_id, t)

        def _fail(msg):
            logger.error('项目状态生成失败: %s', msg)
            t = background_tasks.get(task_id)
            if t:
                t.update({'status': 'error', 'error': msg,
                          'completed_at': time.time()})
                save_task_meta(task_id, t)

        def _do():
            try:
                snap = pa.build_project_snapshot(project_text,
                                                 on_progress=_set, force=force)
                result = {
                    'project_key': snap['project_key'],
                    'project_name': snap.get('project_name', ''),
                    'total': snap.get('total'),
                    'stats': snap.get('stats'),
                    'generated_at': snap.get('generated_at'),
                    'cached': bool(snap.get('_cached', False)),
                }
                t = background_tasks.get(task_id)
                t.update({'status': 'done', 'result': result, 'progress': 100,
                          'progress_msg': '项目状态生成完成',
                          'completed_at': time.time()})
                save_task_meta(task_id, t)
            except jc.JiraError as e:
                _fail(str(e))
            except Exception as e:
                logger.error('项目状态任务异常: %s', traceback.format_exc())
                _fail(f'{type(e).__name__}: {e}')

        threading.Thread(target=_do, daemon=True).start()
        return jsonify({'status': 'success', 'data': {'task_id': task_id}})

    # ---------------- 读取快照 ----------------
    @bp.route('/api/project/snapshot/<path:project_key>', methods=['GET'])
    @login_required_or_guest
    def project_snapshot(project_key):
        snap = pa.load_snapshot(project_key)
        if not snap:
            return jsonify({'status': 'error',
                            'error': '该项目还没有生成状态，请先点击「生成项目状态」'}), 404
        snap.pop('_cached', None)
        snap['age_hours'] = pa.snapshot_age_hours(snap)
        return jsonify({'status': 'success', 'data': snap})

    # ---------------- 多轮对话（SSE） ----------------
    @bp.route('/api/project/chat', methods=['POST'])
    @login_required_or_guest
    def project_chat():
        data = request.get_json(silent=True) or {}
        key = (data.get('project_key') or '').strip()
        question = (data.get('question') or '').strip()
        history = data.get('history') or []
        if not key:
            return jsonify({'status': 'error', 'error': '缺少 project_key'}), 400
        if not question:
            return jsonify({'status': 'error', 'error': '问题不能为空'}), 400
        snap = pa.load_snapshot(key)
        if not snap:
            return jsonify({'status': 'error',
                            'error': '该项目还没有生成状态，请先生成'}), 404

        def sse(obj):
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        def generate():
            try:
                got = False
                for text in pa.answer_stream(snap, history, question):
                    if text:
                        got = True
                        yield sse({'type': 'token', 'content': text})
                if not got:
                    yield sse({'type': 'token',
                               'content': '（模型未返回内容，请检查 AI 配置或稍后重试）'})
                yield sse({'type': 'done'})
            except Exception as e:
                logger.error('项目助手对话失败: %s', traceback.format_exc())
                yield sse({'type': 'error',
                           'message': f'{type(e).__name__}: {e}'})

        return Response(generate(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache, no-transform',
                                 'X-Accel-Buffering': 'no',
                                 'Connection': 'keep-alive'})

    return bp
