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
import re
import queue
import threading
import traceback

from flask import Blueprint, request, jsonify, Response, current_app

from auth import login_required_or_guest
from routes.common import background_tasks, save_task_meta
from services import project_assistant as pa
from services import jira_client as jc
from services import cr_rca as rca

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

    # ---------------- CR 单根因分析（RCA） ----------------
    RCA_INTENT = re.compile(
        r'根因|日志|为什么|崩溃|重启|卡死|闪退|黑屏|无响应|不响应|死机|复位|重置|'
        r'分析|rca|crash|reboot|root ?cause|tombstone|trace|异常|起不来|打不开', re.I)

    def _bundle_meta(b):
        i = b['issue']
        ev = b.get('evidence') or {}
        return {
            'type': 'meta', 'issue_key': i.get('key'), 'summary': i.get('summary'),
            'status': i.get('status'), 'severity': i.get('severity'),
            'components': i.get('components'), 'assignee': i.get('assignee'),
            'url': i.get('url'), 'counts': ev.get('counts', {}),
            'boot_reasons': ev.get('boot_reasons', []),
            'report_meta': ev.get('report_meta', {}),
            'files': (ev.get('files') or [])[:50],
            'downloaded': [a.get('filename') for a in b.get('log_attachments', [])],
            'download_errors': b.get('download_errors', []),
            'embedded_logs': b.get('embedded_logs', []),
            'downloaded_kb': round(b.get('downloaded_bytes', 0) / 1024),
            'fetched_at': b.get('fetched_at'), 'cached': bool(b.get('_cached')),
        }

    def _rca_sse_response(issue_key, question, history, force=False):
        def sse(obj):
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        def generate():
            q = queue.Queue()

            def work():
                try:
                    def onp(stage, msg):
                        q.put(('progress', stage, msg))
                    bundle = rca.fetch_issue_bundle(
                        issue_key, on_progress=onp, force=bool(force))
                    q.put(('bundle', bundle))
                except Exception as e:
                    logger.error('RCA 拉取失败: %s', traceback.format_exc())
                    q.put(('error', f'{type(e).__name__}: {e}'))

            threading.Thread(target=work, daemon=True).start()
            bundle = None
            while True:
                item = q.get()
                if item[0] == 'progress':
                    yield sse({'type': 'progress', 'stage': item[1], 'message': item[2]})
                elif item[0] == 'error':
                    yield sse({'type': 'error', 'message': item[1]})
                    return
                else:
                    bundle = item[1]
                    break
            yield sse(_bundle_meta(bundle))
            got = False
            try:
                for text in rca.analyze_stream(bundle, history, question):
                    if text:
                        got = True
                        yield sse({'type': 'token', 'content': text})
                if not got:
                    yield sse({'type': 'token',
                               'content': '（模型未返回内容，请检查 AI 配置或稍后重试）'})
                yield sse({'type': 'done', 'issue_key': bundle['issue'].get('key')})
            except Exception as e:
                logger.error('RCA 分析失败: %s', traceback.format_exc())
                yield sse({'type': 'error', 'message': f'{type(e).__name__}: {e}'})

        return Response(generate(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache, no-transform',
                                 'X-Accel-Buffering': 'no',
                                 'Connection': 'keep-alive'})

    @bp.route('/api/cr/rca/analyze', methods=['POST'])
    @login_required_or_guest
    def cr_rca_analyze():
        data = request.get_json(silent=True) or {}
        question = (data.get('question') or '').strip()
        history = data.get('history') or []
        force = bool(data.get('force'))
        raw_key = (data.get('issue_key') or '').strip()
        keys = rca.extract_issue_keys(raw_key) or rca.extract_issue_keys(question)
        if not keys:
            return jsonify({'status': 'error',
                            'error': '请提供有效的 CR 单号，如 EKSANTOS-9047'}), 400
        return _rca_sse_response(keys[0], question, history, force)

    @bp.route('/api/cr/rca/bundle/<path:issue_key>', methods=['GET'])
    @login_required_or_guest
    def cr_rca_bundle(issue_key):
        b = rca.load_cached_bundle(issue_key)
        if not b:
            return jsonify({'status': 'error',
                            'error': '该单尚未分析，暂无缓存证据'}), 404
        meta = _bundle_meta(b)
        meta['status_code'] = 'success'
        return jsonify({'status': 'success', 'data': meta})

    # ---------------- 多轮对话（SSE） ----------------
    @bp.route('/api/project/chat', methods=['POST'])
    @login_required_or_guest
    def project_chat():
        data = request.get_json(silent=True) or {}
        key = (data.get('project_key') or '').strip()
        question = (data.get('question') or '').strip()
        history = data.get('history') or []
        rca_keys = rca.extract_issue_keys(question or '')
        if rca_keys and RCA_INTENT.search(question or ''):
            return _rca_sse_response(rca_keys[0], question, history)
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
