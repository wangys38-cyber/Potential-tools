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
                err_msg = str(e)
                # 优化超时错误提示
                if 'ReadTimeout' in err_msg or 'read timeout' in err_msg or 'ConnectTimeout' in err_msg or 'connect timeout' in err_msg:
                    _fail('连接 eDart/Jira 超时，服务器响应较慢。请检查网络连接，或稍后重试。如果项目数据量较大，可能需要更长时间，请耐心等待。')
                elif 'ConnectionResetError' in err_msg or '远程主机强迫关闭' in err_msg or 'Connection broken' in err_msg or 'ChunkedEncodingError' in err_msg:
                    _fail('eDart/Jira 服务器主动断开了连接，可能是单次请求数据量过大或服务器负载较高。请稍后重试，或尝试使用缓存数据。')
                elif 'ConnectionError' in err_msg or 'Failed to establish' in err_msg:
                    _fail('无法连接到 eDart/Jira 服务器，请检查网络连接和站点地址配置是否正确。')
                elif '401' in err_msg or 'Unauthorized' in err_msg or '403' in err_msg or 'Forbidden' in err_msg:
                    _fail('eDart/Jira 认证失败，请检查 Token 是否正确，或是否有权限访问该项目。')
                elif '404' in err_msg or 'Not Found' in err_msg:
                    _fail('未找到该项目或资源，请检查 Project Key 是否正确。')
                else:
                    _fail(f'请求失败：{err_msg}')

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

    # ---------------- 多项目同时监控 ----------------
    @bp.route('/api/project/multi-monitor', methods=['POST'])
    @login_required_or_guest
    def multi_monitor():
        data = request.get_json(silent=True) or {}
        projects_text = (data.get('projects') or data.get('project_keys') or '').strip()
        force = bool(data.get('force'))

        if not projects_text:
            return jsonify({'status': 'error', 'error': '请输入至少一个 Project Key'}), 400

        # 解析多个项目Key（支持逗号、空格、分号分隔）
        project_keys = []
        for p in re.split(r'[,，;；\s]+', projects_text):
            p = p.strip()
            if p and p not in project_keys:
                project_keys.append(p)

        if not project_keys:
            return jsonify({'status': 'error', 'error': '未解析到有效的 Project Key'}), 400

        task_id = hashlib.md5(f'multi_{time.time()}'.encode()).hexdigest()[:16]
        task = {'status': 'processing', 'result': None, 'error': None,
                'created_at': time.time(), 'progress': 0,
                'progress_msg': f'正在加载 {len(project_keys)} 个项目...'}
        background_tasks[task_id] = task
        save_task_meta(task_id, task)

        def _set(pct, msg):
            t = background_tasks.get(task_id)
            if t:
                t['progress'] = max(t.get('progress', 0), int(pct))
                t['progress_msg'] = msg
                save_task_meta(task_id, t)

        def _fail(msg):
            t = background_tasks.get(task_id)
            if t:
                t.update({'status': 'error', 'error': msg, 'completed_at': time.time()})
                save_task_meta(task_id, t)

        def _do():
            try:
                results = []
                errors = []
                total = len(project_keys)
                completed = [0]
                lock = threading.Lock()

                def _load_one(proj_key):
                    try:
                        snap = pa.build_project_snapshot(proj_key, on_progress=lambda p, m: None, force=force)
                        stats = snap.get('stats', {})
                        total_count = snap.get('total', 0)
                        unresolved = stats.get('unresolved', 0)
                        # 修复字段名：使用正确的字段名
                        bc_count = stats.get('bc_unresolved', stats.get('bc_count', 0))
                        fail_modules = stats.get('fail', stats.get('fail_modules', 0))
                        pass_modules = stats.get('pass', stats.get('pass_modules', 0))
                        total_modules = fail_modules + pass_modules

                        # 计算blocker_count：从CR列表中统计（使用Severity字段）
                        blocker_count = 0
                        cr_list = snap.get('crs', []) or snap.get('cr_list', []) or []
                        if cr_list:
                            for cr in cr_list:
                                # 优先使用Severity字段判断
                                severity = (cr.get('severity') or cr.get('Severity') or '').upper()
                                # 备用：使用priority字段
                                priority = (cr.get('priority') or cr.get('Priority') or '').upper()
                                # 判断条件：Severity或Priority中包含Blocker/Block/P0/Critical等
                                if ('BLOCKER' in severity or 'BLOCK' in severity or 
                                    severity == 'B' or severity == 'P0' or 'P0' in severity or
                                    'CRITICAL' in severity or severity == 'C' or
                                    'BLOCKER' in priority or 'BLOCK' in priority or 
                                    priority == 'B' or priority == 'P0' or 'P0' in priority or
                                    'CRITICAL' in priority or priority == 'C'):
                                    blocker_count += 1
                        else:
                            # 如果没有CR列表，尝试从stats中获取
                            blocker_count = stats.get('blocker', stats.get('blocker_count', 0))
                            # 如果stats中也没有，尝试从critical_count获取
                            if blocker_count == 0:
                                blocker_count = stats.get('critical_count', 0)

                        # 计算健康度评分
                        health_score = 100
                        health_score -= min(bc_count * 5, 40)
                        if total_count > 0:
                            health_score -= min((unresolved / total_count) * 100 * 0.2, 20)
                        if total_modules > 0:
                            health_score -= min((fail_modules / total_modules) * 100 * 0.25, 25)
                        health_score -= min(blocker_count * 3, 15)
                        health_score = max(0, min(100, int(health_score)))

                        # 健康状态
                        if health_score >= 80:
                            health_status = 'good'
                        elif health_score >= 60:
                            health_status = 'warning'
                        else:
                            health_status = 'danger'

                        result = {
                            'project_key': snap['project_key'],
                            'project_name': snap.get('project_name', ''),
                            'total': total_count,
                            'unresolved': unresolved,
                            'resolved': total_count - unresolved,
                            'resolve_rate': round((total_count - unresolved) / total_count * 100, 1) if total_count > 0 else 0,
                            'bc_count': bc_count,
                            'blocker_count': blocker_count,
                            'critical_count': stats.get('critical_count', 0),
                            'fail_modules': fail_modules,
                            'pass_modules': pass_modules,
                            'total_modules': total_modules,
                            'pass_rate': round(pass_modules / total_modules * 100, 1) if total_modules > 0 else 0,
                            'health_score': health_score,
                            'health_status': health_status,
                            'generated_at': snap.get('generated_at'),
                            'cached': bool(snap.get('_cached', False)),
                        }
                        with lock:
                            results.append(result)
                            completed[0] += 1
                            _set(int((completed[0] / total) * 90), f'已加载 [{completed[0]}/{total}] {proj_key}')
                    except Exception as e:
                        with lock:
                            errors.append({'project_key': proj_key, 'error': str(e)})
                            completed[0] += 1
                            _set(int((completed[0] / total) * 90), f'加载失败 [{completed[0]}/{total}] {proj_key}')
                        logger.error(f'多项目监控 - 加载 {proj_key} 失败: {e}')

                # 并发加载（最多5个线程）
                from concurrent.futures import ThreadPoolExecutor
                max_workers = min(5, total)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(_load_one, pk) for pk in project_keys]
                    for f in futures:
                        f.result()

                _set(95, '正在聚合数据...')

                # 聚合统计
                total_projects = len(results)
                total_cr = sum(r['total'] for r in results)
                total_unresolved = sum(r['unresolved'] for r in results)
                total_bc = sum(r['bc_count'] for r in results)
                total_blocker = sum(r['blocker_count'] for r in results)
                avg_health = round(sum(r['health_score'] for r in results) / total_projects, 1) if total_projects > 0 else 0

                # 按健康度排序（风险高的排前面）
                results.sort(key=lambda x: x['health_score'])

                # 风险项目
                danger_projects = [r for r in results if r['health_status'] == 'danger']
                warning_projects = [r for r in results if r['health_status'] == 'warning']
                good_projects = [r for r in results if r['health_status'] == 'good']

                result_data = {
                    'projects': results,
                    'errors': errors,
                    'summary': {
                        'total_projects': total_projects,
                        'success_count': len(results),
                        'fail_count': len(errors),
                        'total_cr': total_cr,
                        'total_unresolved': total_unresolved,
                        'total_bc': total_bc,
                        'total_blocker': total_blocker,
                        'avg_health': avg_health,
                        'danger_count': len(danger_projects),
                        'warning_count': len(warning_projects),
                        'good_count': len(good_projects),
                    }
                }

                t = background_tasks.get(task_id)
                t.update({'status': 'done', 'result': result_data, 'progress': 100,
                          'progress_msg': f'已加载 {len(results)}/{total_projects} 个项目',
                          'completed_at': time.time()})
                save_task_meta(task_id, t)

            except Exception as e:
                logger.error('多项目监控任务异常: %s', traceback.format_exc())
                _fail(f'请求失败：{str(e)}')

        threading.Thread(target=_do, daemon=True).start()
        return jsonify({'status': 'success', 'data': {'task_id': task_id}})

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

    # ---------------- 自动刷新状态 ----------------
    @bp.route('/api/project/auto-refresh/status', methods=['GET'])
    @login_required_or_guest
    def auto_refresh_status():
        try:
            from services.pa_scheduler import get_status
            return jsonify({'status': 'success', 'data': get_status()})
        except Exception as e:
            return jsonify({'status': 'error', 'error': str(e)}), 500


    # ---------------- 生成项目日报 ----------------
    @bp.route('/api/project/daily-report', methods=['POST'])
    @login_required_or_guest
    def generate_daily_report():
        """生成项目日报并保存到牛马笔记"""
        data = request.get_json(silent=True) or {}
        project_key = (data.get('project') or data.get('project_key') or '').strip()
        reporter = (data.get('reporter') or '').strip()
        
        if not project_key:
            return jsonify({'status': 'error', 'error': '请输入 Project Key'}), 400
        
        try:
            # 获取用户ID
            user_id = 1
            try:
                from flask import session
                user_id = session.get('user_id', 1)
            except Exception:
                pass
            
            note, err = pa.save_daily_report_to_notes(project_key, reporter, user_id)
            if err:
                return jsonify({'status': 'error', 'error': err}), 200
            
            return jsonify({
                'status': 'success',
                'data': {
                    'note_id': note.get('note_uid') if note else '',
                    'title': note.get('title') if note else '',
                    'message': '项目日报已生成并保存到牛马笔记'
                }
            })
        except Exception as e:
            logger.error('生成项目日报失败: %s', traceback.format_exc())
            return jsonify({'status': 'error', 'error': f'生成日报失败: {e}'}), 200

    @bp.route('/api/project/weekly-report', methods=['POST'])
    @login_required_or_guest
    def generate_weekly_report_api():
        data = request.get_json(silent=True) or {}
        project_key = (data.get('project') or data.get('project_key') or '').strip()
        reporter = (data.get('reporter') or '').strip()
        if not project_key:
            return jsonify({'status': 'error', 'error': '请输入 Project Key'}), 400
        try:
            user_id = 1
            try:
                from flask import session
                user_id = session.get('user_id', 1)
            except Exception:
                pass
            note, err = pa.save_weekly_report_to_notes(project_key, reporter, user_id)
            if err:
                return jsonify({'status': 'error', 'error': err}), 200
            return jsonify({
                'status': 'success',
                'data': {
                    'note_id': note.get('note_uid') if note else '',
                    'title': note.get('title') if note else '',
                    'message': '项目周报已生成并保存到牛马笔记'
                }
            })
        except Exception as e:
            logger.error('生成项目周报失败: %s', traceback.format_exc())
            return jsonify({'status': 'error', 'error': f'生成周报失败: {e}'}), 200

    @bp.route('/api/project/aging-analysis', methods=['POST'])
    @login_required_or_guest
    def aging_analysis_api():
        data = request.get_json(silent=True) or {}
        project_key = (data.get('project') or data.get('project_key') or '').strip()
        if not project_key:
            return jsonify({'status': 'error', 'error': '请输入 Project Key'}), 400
        try:
            result, err = pa.analyze_issue_aging(project_key)
            if err:
                return jsonify({'status': 'error', 'error': err}), 200
            return jsonify({'status': 'success', 'data': result})
        except Exception as e:
            logger.error('问题老化分析失败: %s', traceback.format_exc())
            return jsonify({'status': 'error', 'error': f'老化分析失败: {e}'}), 200

    # ==================== 开发阶段配置 ====================
    @bp.route('/api/project/dev-stage/<project_key>', methods=['GET'])
    @login_required_or_guest
    def get_dev_stage(project_key):
        """获取项目的开发阶段配置"""
        try:
            stage = pa.get_project_dev_stage(project_key)
            return jsonify({'status': 'success', 'data': {'stage': stage}})
        except Exception as e:
            logger.error('获取开发阶段失败: %s', traceback.format_exc())
            return jsonify({'status': 'error', 'error': str(e)}), 200

    @bp.route('/api/project/dev-stage', methods=['POST'])
    @login_required_or_guest
    def save_dev_stage():
        """保存项目的开发阶段配置"""
        data = request.get_json(silent=True) or {}
        project_key = (data.get('project') or data.get('project_key') or '').strip()
        stage = (data.get('stage') or '').strip()
        if not project_key:
            return jsonify({'status': 'error', 'error': '请输入 Project Key'}), 400
        if not stage:
            return jsonify({'status': 'error', 'error': '请选择开发阶段'}), 400
        try:
            pa.save_project_dev_stage(project_key, stage)
            return jsonify({'status': 'success', 'data': {'stage': stage, 'message': '开发阶段已保存'}})
        except Exception as e:
            logger.error('保存开发阶段失败: %s', traceback.format_exc())
            return jsonify({'status': 'error', 'error': str(e)}), 200

    @bp.route('/api/project/aging-report', methods=['POST'])
    @login_required_or_guest
    def aging_report_api():
        data = request.get_json(silent=True) or {}
        project_key = (data.get('project') or data.get('project_key') or '').strip()
        if not project_key:
            return jsonify({'status': 'error', 'error': '请输入 Project Key'}), 400
        try:
            report, err = pa.generate_aging_report(project_key)
            if err:
                return jsonify({'status': 'error', 'error': err}), 200
            return jsonify({'status': 'success', 'data': {'report': report}})
        except Exception as e:
            logger.error('生成老化报告失败: %s', traceback.format_exc())
            return jsonify({'status': 'error', 'error': f'生成报告失败: {e}'}), 200

    @bp.route('/api/project/cache-info', methods=['POST'])
    @login_required_or_guest
    def cache_info_api():
        data = request.get_json(silent=True) or {}
        project_key = (data.get('project') or data.get('project_key') or '').strip()
        if not project_key:
            return jsonify({'status': 'error', 'error': '请输入 Project Key'}), 400
        try:
            info = pa.get_cache_info(project_key)
            return jsonify({'status': 'success', 'data': info})
        except Exception as e:
            return jsonify({'status': 'error', 'error': str(e)}), 200

    @bp.route('/api/project/clear-cache', methods=['POST'])
    @login_required_or_guest
    def clear_cache_api():
        data = request.get_json(silent=True) or {}
        project_key = (data.get('project') or data.get('project_key') or '').strip()
        try:
            pa.clear_cache(project_key or None)
            return jsonify({'status': 'success', 'message': '缓存已清除'})
        except Exception as e:
            return jsonify({'status': 'error', 'error': str(e)}), 200

    @bp.route('/api/project/compare', methods=['POST'])
    @login_required_or_guest
    def compare_projects_api():
        data = request.get_json(silent=True) or {}
        project_keys = data.get('projects') or data.get('project_keys') or []
        if not project_keys or len(project_keys) < 2:
            return jsonify({'status': 'error', 'error': '请输入至少2个项目Key'}), 400
        try:
            results = pa.compare_projects(project_keys)
            return jsonify({'status': 'success', 'data': {'projects': results}})
        except Exception as e:
            logger.error('多项目对比失败: %s', traceback.format_exc())
            return jsonify({'status': 'error', 'error': f'对比失败: {e}'}), 200

    @bp.route('/api/project/alerts', methods=['POST'])
    @login_required_or_guest
    def project_alerts_api():
        data = request.get_json(silent=True) or {}
        project_key = (data.get('project') or data.get('project_key') or '').strip()
        if not project_key:
            return jsonify({'status': 'error', 'error': '请输入 Project Key'}), 400
        try:
            result = pa.check_project_alerts(project_key)
            return jsonify({'status': 'success', 'data': result})
        except Exception as e:
            logger.error('预警检查失败: %s', traceback.format_exc())
            return jsonify({'status': 'error', 'error': f'预警检查失败: {e}'}), 200

    return bp
