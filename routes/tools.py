"""工具类路由 Blueprint — 会议纪要、周报、OCR、MD2PDF、音频转写、Jira搜索、实时ASR"""
import os
import json
import time
import logging
import traceback
import threading
from functools import wraps

from flask import Blueprint, request, jsonify, Response, stream_with_context, g, current_app

import requests
import auth
import db
import ai_utils
from routes.common import MD2PDF_PREVIEW_CSS, render_pdf, _CST

logger = logging.getLogger(__name__)

get_ai_config = ai_utils.get_ai_config
_call_ai = ai_utils.call_ai
_call_ai_stream = ai_utils.call_ai_stream

# WebSocket 客户端（实时ASR用）
try:
    import websocket as _ws_client
except ImportError:
    _ws_client = None


# ==================== 认证装饰器 ====================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = auth.get_current_user()
        if not user:
            return jsonify({'error': '请先登录'}), 401
        g.user = user
        return f(*args, **kwargs)
    return decorated


def login_required_or_guest(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = auth.get_current_user()
        if not user and not auth.ALLOW_GUEST:
            return jsonify({'error': '请先登录'}), 401
        g.user = user
        return f(*args, **kwargs)
    return decorated


def create_tools_blueprint(sock=None):
    """创建工具类路由 Blueprint

    Args:
        sock: flask_sock.Sock 实例，用于注册 WebSocket 路由
    """
    bp = Blueprint('tools', __name__)

    # ==================== Jira 搜索 ====================

    @bp.route('/api/jira-search', methods=['POST'])
    def api_jira_search():
        """Jira 搜索代理 — 通过 JQL 或 Jira 链接获取 CR 数据"""
        data = request.get_json(force=True)
        domain = data.get('domain', '').strip().rstrip('/')
        email = data.get('email', '').strip()
        api_token = data.get('api_token', '').strip()
        jql = data.get('jql', '').strip()
        jira_url = data.get('jira_url', '').strip()
        max_results = min(int(data.get('max_results', 500)), 1000)

        if not domain:
            return jsonify({'error': '请填写 Jira 域名'}), 400
        if domain and not domain.startswith(('http://', 'https://')):
            domain = 'https://' + domain

        if jira_url and not jql:
            try:
                from urllib.parse import urlparse, parse_qs, unquote
                parsed = urlparse(jira_url)
                params = parse_qs(parsed.query)
                if 'jql' in params:
                    jql = unquote(params['jql'][0])
                elif 'filter' in params:
                    filter_id = params['filter'][0]
                    jql = f"filter={filter_id}"
                else:
                    import re
                    m = re.search(r'filter[=/](\d+)', jira_url)
                    if m:
                        jql = f"filter={m.group(1)}"
            except Exception:
                pass

        if not jql:
            return jsonify({'error': '请提供 JQL 或 Jira 搜索链接'}), 400

        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        payload = {
            'jql': jql,
            'maxResults': max_results,
            'fields': ['summary', 'status', 'created', 'resolutiondate',
                       'fixVersions', 'issuetype', 'priority', 'assignee', 'reporter']
        }

        is_cloud = '.atlassian.net' in domain
        api_versions = ['/rest/api/3/search', '/rest/api/2/search'] if is_cloud else ['/rest/api/2/search']

        auth_attempts = []
        if email and api_token:
            auth_attempts.append(('basic', (email, api_token)))
            if '@' in email:
                auth_attempts.append(('basic', (email.split('@')[0], api_token)))
            auth_attempts.append(('bearer', api_token))
        else:
            auth_attempts.append(('none', None))

        resp = None
        last_status = None
        try:
            for auth_type, auth_val in auth_attempts:
                req_headers = dict(headers)
                if auth_type == 'bearer':
                    req_headers['Authorization'] = f'Bearer {auth_val}'
                    auth_val = None
                for api_path in api_versions:
                    search_url = f"{domain}{api_path}"
                    resp = requests.post(search_url, json=payload, auth=auth_val,
                                         headers=req_headers, timeout=30)
                    last_status = resp.status_code
                    if resp.status_code == 200:
                        break
                    if resp.status_code == 429:
                        retry_after = resp.headers.get('Retry-After', '30')
                        return jsonify({'error': f'Jira 请求过于频繁(429)：服务器要求等待 {retry_after} 秒后重试'}), 429
                    if resp.status_code == 404:
                        continue
                    break
                if resp.status_code == 200:
                    break
                if resp.status_code == 404:
                    continue
                break

            if not resp or resp.status_code != 200:
                if last_status == 401:
                    return jsonify({'error': 'Jira 鉴权失败(401)：已尝试邮箱/短用户名/Bearer三种方式'}), 401
                if last_status == 403:
                    return jsonify({'error': 'Jira 无权限(403)：当前账号无权访问该 filter 或项目'}), 403
                if last_status == 404:
                    return jsonify({'error': f'Jira API 未找到(404)：请确认域名 {domain} 是否正确'}), 404
                return jsonify({'error': f'Jira API 返回 {last_status}: {resp.text[:200] if resp else "无响应"}'}), last_status or 502

            result = resp.json()
            issues = result.get('issues', [])
            total = result.get('total', len(issues))
            cr_data = []
            for issue in issues:
                fields = issue.get('fields', {})
                status = fields.get('status', {}).get('name', 'Unknown')
                created = fields.get('created', '')[:10] if fields.get('created') else ''
                resolved = fields.get('resolutiondate', '')[:10] if fields.get('resolutiondate') else ''
                fix_versions = [v.get('name', '') for v in fields.get('fixVersions', [])]
                version = fix_versions[0] if fix_versions else '未指定'
                issuetype = fields.get('issuetype', {}).get('name', '')
                priority = fields.get('priority', {}).get('name', '')
                assignee = fields.get('assignee', {}).get('displayName', '未分配') if fields.get('assignee') else '未分配'
                cr_data.append({
                    'key': issue.get('key', ''),
                    'summary': fields.get('summary', ''),
                    'status': status,
                    'created': created,
                    'resolved': resolved,
                    'version': version,
                    'issuetype': issuetype,
                    'priority': priority,
                    'assignee': assignee,
                    'is_resolved': 1 if resolved else 0,
                })
            return jsonify({'total': total, 'returned': len(cr_data), 'issues': cr_data, 'jql': jql})
        except requests.exceptions.Timeout:
            return jsonify({'error': 'Jira 请求超时，请检查网络或代理设置'}), 504
        except requests.exceptions.ConnectionError:
            return jsonify({'error': '无法连接到 Jira 服务器，请检查域名和网络'}), 502
        except Exception as e:
            return jsonify({'error': f'请求失败: {str(e)}'}), 500

    # ==================== 会议纪要 ====================

    @bp.route('/api/generate-minutes', methods=['POST'])
    @login_required
    def api_generate_minutes():
        """AI生成会议纪要"""
        data = request.get_json(silent=True) or {}
        transcript = data.get('transcript', '').strip()
        title = data.get('title', '未命名会议')
        attendees = data.get('attendees', '未填写')
        date = data.get('date', '')
        model = data.get('model')
        if not transcript or len(transcript) < 10:
            return jsonify({'error': '转写内容太少，无法生成纪要'}), 400
        ai_config = get_ai_config()
        if not ai_config.get('enabled'):
            return jsonify({'error': 'AI功能未配置，请联系管理员设置API Key'}), 503
        try:
            prompt = f"""请根据以下会议语音转写内容，生成一份结构化的会议纪要。

会议信息：
- 主题：{title}
- 日期：{date}
- 参会人员：{attendees}

会议转写内容：
{transcript[:16000]}

请生成会议纪要，使用HTML格式，包含以下部分：
1. <h2>会议概要</h2> - 简要说明会议目的和主要内容（2-3句话）
2. <h2>讨论要点</h2> - 列出讨论的主要议题和关键观点，使用<ul><li>格式
3. <h2>决议事项</h2> - 列出会议达成的决定，使用<ol><li>格式
4. <h2>待办事项</h2> - 列出需要后续跟进的任务，如有责任人请标注，使用<table>格式（列：序号、任务、责任人、截止时间）

要求：
- 直接输出HTML内容，不要包含```html标记
- 语言简洁专业
- 如果转写内容不清晰，合理推断并标注
- 只输出HTML，不要其他文字"""
            minutes_html = _call_ai(
                messages=[
                    {'role': 'system', 'content': '你是一个专业的会议纪要撰写助手。请根据会议转写内容生成结构清晰、内容准确的会议纪要。'},
                    {'role': 'user', 'content': prompt}
                ],
                model=model, max_tokens=3000, temperature=0.3, timeout=90
            )
            if '```html' in minutes_html:
                minutes_html = minutes_html.split('```html')[1].split('```')[0]
            elif '```' in minutes_html:
                minutes_html = minutes_html.split('```')[1].split('```')[0]
            minutes_html = minutes_html.strip()
            return jsonify({'status': 'success', 'minutes': minutes_html})
        except requests.exceptions.Timeout:
            return jsonify({'error': 'AI服务响应超时，请稍后重试'}), 504
        except Exception as e:
            logger.error(f"生成会议纪要失败: {traceback.format_exc()}")
            return jsonify({'error': str(e)}), 500

    @bp.route('/api/generate-minutes-stream', methods=['POST'])
    @login_required
    def api_generate_minutes_stream():
        """SSE 流式版：AI生成会议纪要"""
        data = request.get_json(silent=True) or {}
        transcript = data.get('transcript', '').strip()
        title = data.get('title', '未命名会议')
        attendees = data.get('attendees', '未填写')
        date = data.get('date', '')
        model = data.get('model')
        if not transcript or len(transcript) < 10:
            return jsonify({'error': '转写内容太少，无法生成纪要'}), 400
        ai_config = get_ai_config()
        if not ai_config.get('enabled'):
            return jsonify({'error': 'AI功能未配置，请联系管理员设置API Key'}), 503
        prompt = f"""请根据以下会议语音转写内容，生成一份结构化的会议纪要。

会议信息：
- 主题：{title}
- 日期：{date}
- 参会人员：{attendees}

会议转写内容：
{transcript[:16000]}

请生成会议纪要，使用Markdown格式，包含以下部分：

### 📋 会议概要
简要说明会议目的和主要内容（2-3句话）

### 💬 讨论要点
列出讨论的主要议题和关键观点

### ✅ 决议事项
列出会议达成的决定

### 📝 待办事项
列出需要后续跟进的任务，如有责任人请标注

要求：
- 语言简洁专业
- 如果转写内容不清晰，合理推断并标注
- 使用 Markdown 格式输出"""
        messages = [
            {'role': 'system', 'content': '你是一个专业的会议纪要撰写助手。请根据会议转写内容生成结构清晰、内容准确的会议纪要。'},
            {'role': 'user', 'content': prompt}
        ]
        return Response(
            stream_with_context(_call_ai_stream(messages, model=model, max_tokens=3000, temperature=0.3)),
            content_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
        )

    # ==================== OCR ====================

    @bp.route('/api/ocr', methods=['POST'])
    @login_required_or_guest
    def api_ocr():
        """OCR 图片文字识别 — 使用 qwen-vl 多模态模型"""
        import base64
        image_data_url = None
        prompt = '请识别图片中的所有文字内容，保持原有格式和排版。如果图片中包含表格，请用 Markdown 表格格式输出。只输出识别到的文字，不要其他说明。'
        if 'file' in request.files:
            file = request.files['file']
            img_bytes = file.read()
            if len(img_bytes) > 10 * 1024 * 1024:
                return jsonify({'error': '图片不能超过 10MB'}), 400
            b64 = base64.b64encode(img_bytes).decode('utf-8')
            mime = file.content_type or 'image/png'
            image_data_url = f'data:{mime};base64,{b64}'
        elif request.is_json:
            data = request.get_json(silent=True) or {}
            image_data_url = data.get('image')
            custom_prompt = data.get('prompt')
            if custom_prompt:
                prompt = custom_prompt
        else:
            return jsonify({'error': '请上传图片或提供 base64 图片数据'}), 400
        if not image_data_url:
            return jsonify({'error': '图片数据为空'}), 400
        ai_config = get_ai_config()
        if not ai_config.get('enabled'):
            return jsonify({'error': 'AI功能未配置'}), 503
        try:
            is_openai = 'dashscope' not in ai_config.get('base_url', '')
            if is_openai:
                response = requests.post(
                    f"{ai_config.get('base_url', '').rstrip('/')}/chat/completions",
                    headers={'Authorization': f'Bearer {ai_config.get("api_key", "")}', 'Content-Type': 'application/json'},
                    json={
                        'model': ai_config.get('vision_model', 'doubao-seed-1-6-250615'),
                        'messages': [{'role': 'user', 'content': [
                            {'type': 'image_url', 'image_url': {'url': image_data_url}},
                            {'type': 'text', 'text': prompt}
                        ]}],
                        'max_tokens': 2000
                    },
                    timeout=60
                )
                if response.status_code == 200:
                    result = response.json()
                    text = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                    return jsonify({'status': 'success', 'text': text.strip()})
                else:
                    logger.error(f"OCR失败: {response.status_code} - {response.text[:200]}")
                    return jsonify({'error': f'OCR服务错误({response.status_code}): {response.text[:100]}'}), 502
            else:
                response = requests.post(
                    f"{ai_config.get('base_url', 'https://dashscope.aliyuncs.com/api/v1')}/services/aigc/multimodal-generation/generation",
                    headers={'Authorization': f'Bearer {ai_config.get("api_key", "")}', 'Content-Type': 'application/json'},
                    json={
                        'model': 'qwen-vl-plus',
                        'input': {'messages': [{'role': 'user', 'content': [
                            {'image': image_data_url}, {'text': prompt}
                        ]}]}
                    },
                    timeout=60
                )
                if response.status_code == 200:
                    result = response.json()
                    text = result.get('output', {}).get('choices', [{}])[0].get('message', {}).get('content', [{}])
                    if isinstance(text, list):
                        text = ''.join(item.get('text', '') if isinstance(item, dict) else str(item) for item in text)
                    return jsonify({'status': 'success', 'text': text.strip()})
                else:
                    logger.error(f"OCR失败: {response.status_code} - {response.text[:200]}")
                    return jsonify({'error': f'OCR服务错误({response.status_code})'}), 502
        except requests.exceptions.Timeout:
            return jsonify({'error': 'OCR服务响应超时'}), 504
        except Exception as e:
            logger.error(f"OCR异常: {traceback.format_exc()}")
            return jsonify({'error': str(e)}), 500

    # ==================== 周报 ====================

    @bp.route('/api/weekly-report', methods=['POST'])
    @login_required_or_guest
    def api_weekly_report():
        """AI 智能周报生成"""
        data = request.get_json(silent=True) or {}
        notes = data.get('notes', '').strip()
        meetings = data.get('meetings', '').strip()
        cr_issues = data.get('cr_issues', '').strip()
        extra = data.get('extra', '').strip()
        model = data.get('model')
        name = data.get('name', '')
        week_range = data.get('week_range', '')
        if not any([notes, meetings, cr_issues, extra]):
            return jsonify({'error': '请至少填写一项本周工作内容'}), 400
        ai_config = get_ai_config()
        if not ai_config.get('enabled'):
            return jsonify({'error': 'AI功能未配置'}), 503
        sections = []
        if name:
            sections.append(f'汇报人：{name}')
        if week_range:
            sections.append(f'汇报周期：{week_range}')
        if notes:
            sections.append(f'【工作笔记/记录】\n{notes[:3000]}')
        if meetings:
            sections.append(f'【会议内容摘要】\n{meetings[:3000]}')
        if cr_issues:
            sections.append(f'【问题/CR记录】\n{cr_issues[:3000]}')
        if extra:
            sections.append(f'【其他补充】\n{extra[:2000]}')
        content_block = '\n\n'.join(sections)
        prompt = f"""请根据以下本周工作素材，生成一份结构化的周报。

素材内容：
{content_block}

请生成周报，使用 HTML 格式，包含以下部分：
1. <h2>本周工作总结</h2> — 概括本周主要工作内容（3-5 条要点）
2. <h2>关键成果</h2> — 本周取得的关键成果或进展
3. <h2>问题与风险</h2> — 遇到的问题、风险及应对措施
4. <h2>下周计划</h2> — 下周工作重点和计划安排

要求：
- 直接输出 HTML，不要 ```html 标记
- 语言简洁专业
- 合理归纳整理，不要简单罗列原文
- 只输出 HTML 内容"""
        try:
            result = _call_ai(
                messages=[
                    {'role': 'system', 'content': '你是一个专业的项目汇报助手。请根据用户提供的素材，生成结构清晰、内容准确的周报。'},
                    {'role': 'user', 'content': prompt}
                ],
                model=model, max_tokens=3000, temperature=0.3, timeout=90
            )
            if '```html' in result:
                result = result.split('```html')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]
            result = result.strip()
            return jsonify({'status': 'success', 'report': result})
        except Exception as e:
            logger.error(f"周报生成失败: {traceback.format_exc()}")
            return jsonify({'error': str(e)}), 500

    @bp.route('/api/weekly-report-stream', methods=['POST'])
    @login_required
    def api_weekly_report_stream():
        """SSE 流式版：AI 智能周报生成"""
        data = request.get_json(silent=True) or {}
        notes = data.get('notes', '').strip()
        meetings = data.get('meetings', '').strip()
        cr_issues = data.get('cr_issues', '').strip()
        extra = data.get('extra', '').strip()
        model = data.get('model')
        name = data.get('name', '')
        week_range = data.get('week_range', '')
        if not any([notes, meetings, cr_issues, extra]):
            return jsonify({'error': '请至少填写一项本周工作内容'}), 400
        ai_config = get_ai_config()
        if not ai_config.get('enabled'):
            return jsonify({'error': 'AI功能未配置'}), 503
        sections = []
        if name:
            sections.append(f'汇报人：{name}')
        if week_range:
            sections.append(f'汇报周期：{week_range}')
        if notes:
            sections.append(f'【工作笔记/记录】\n{notes[:3000]}')
        if meetings:
            sections.append(f'【会议内容摘要】\n{meetings[:3000]}')
        if cr_issues:
            sections.append(f'【问题/CR记录】\n{cr_issues[:3000]}')
        if extra:
            sections.append(f'【其他补充】\n{extra[:2000]}')
        content_block = '\n\n'.join(sections)
        prompt = f"""请根据以下本周工作素材，生成一份结构化的周报。

素材内容：
{content_block}

请生成周报，使用 Markdown 格式，包含以下部分：

## 本周工作总结
概括本周主要工作内容（3-5 条要点）

## 关键成果
本周取得的关键成果或进展

## 问题与风险
遇到的问题、风险及应对措施

## 下周计划
下周工作重点和计划安排

要求：
- 语言简洁专业
- 合理归纳整理，不要简单罗列原文
- 使用 Markdown 格式输出"""
        messages = [
            {'role': 'system', 'content': '你是一个专业的项目汇报助手。请根据用户提供的素材，生成结构清晰、内容准确的周报。'},
            {'role': 'user', 'content': prompt}
        ]
        return Response(
            stream_with_context(_call_ai_stream(messages, model=model, max_tokens=3000, temperature=0.3)),
            content_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
        )

    # ==================== MD2PDF ====================

    @bp.route('/api/md2pdf', methods=['POST'])
    def api_md2pdf():
        data = request.json or {}
        markdown_content = data.get('content', '')
        if not markdown_content:
            return jsonify({'error': '内容不能为空'}), 400
        try:
            import markdown
            import tempfile as tf
            html_content = markdown.markdown(
                markdown_content,
                extensions=['extra', 'codehilite', 'tables', 'fenced_code']
            )
            with tf.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
                f.write(f'''<!DOCTYPE html><html><head><meta charset="utf-8"><style>{MD2PDF_PREVIEW_CSS}</style></head><body>{html_content}</body></html>''')
                html_path = f.name
            pdf_path = os.path.join(current_app.config['PDF_FOLDER'], f"md2pdf_{int(time.time())}.pdf")
            render_pdf(html_path, pdf_path)
            return jsonify({'filename': os.path.basename(pdf_path)})
        except Exception as e:
            logger.error(f"PDF生成失败: {traceback.format_exc()}")
            return jsonify({'error': str(e)}), 500

    # ==================== 音频上传转写 ====================

    @bp.route('/api/upload-audio', methods=['POST'])
    @login_required
    def api_upload_audio():
        """上传音频文件 — 异步处理：先保存文件，后台线程上传DashScope并提交转写"""
        ai_config = get_ai_config()
        if not ai_config.get('enabled'):
            return jsonify({'error': 'AI功能未配置，请联系管理员设置API Key'}), 503
        if 'audio' not in request.files:
            return jsonify({'error': '未收到音频文件'}), 400
        audio_file = request.files['audio']
        if not audio_file.filename:
            return jsonify({'error': '文件名为空'}), 400
        audio_file.seek(0, 2)
        file_size = audio_file.tell()
        audio_file.seek(0)
        if file_size > 200 * 1024 * 1024:
            return jsonify({'error': '文件过大，最大支持200MB'}), 400
        allowed_extensions = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.wma', '.webm'}
        ext = os.path.splitext(audio_file.filename)[1].lower()
        if ext not in allowed_extensions:
            return jsonify({'error': f'不支持的文件格式: {ext}，支持: {", ".join(allowed_extensions)}'}), 400
        try:
            import uuid as _uuid
            task_id = f"asr_{_uuid.uuid4().hex[:16]}"
            saved_filename = f"{task_id}{ext}"
            saved_path = os.path.join(current_app.config['UPLOAD_FOLDER'], saved_filename)
            audio_file.save(saved_path)
            logger.info(f"音频文件已保存: {saved_filename}, {file_size} bytes, task={task_id}")
            db.create_task(task_id, 'audio_transcription')
            db.update_task(task_id, status='uploading', progress=10)
            api_key = ai_config.get('api_key', '')
            orig_filename = audio_file.filename

            def _background_process():
                try:
                    import requests as req
                    db.update_task(task_id, status='uploading', progress=20)
                    logger.info(f"[后台] 开始上传到DashScope: {task_id}")
                    with open(saved_path, 'rb') as f:
                        upload_resp = req.post(
                            'https://dashscope.aliyuncs.com/api/v1/uploads',
                            headers={'Authorization': f'Bearer {api_key}'},
                            files={'file': (orig_filename, f, 'application/octet-stream'),
                                   'model': (None, 'paraformer-v2'), 'action': (None, 'put')},
                            timeout=300
                        )
                    if upload_resp.status_code != 200:
                        logger.error(f"[后台] DashScope上传失败: {upload_resp.status_code} - {upload_resp.text[:300]}")
                        db.update_task(task_id, status='failed', error=f'文件上传失败({upload_resp.status_code})')
                        return
                    upload_data = upload_resp.json()
                    file_url = upload_data.get('output', {}).get('upload_url', '')
                    if not file_url:
                        file_url = upload_data.get('data', {}).get('url', '')
                    if not file_url:
                        logger.error(f"[后台] DashScope上传返回异常: {upload_data}")
                        db.update_task(task_id, status='failed', error='文件上传返回异常')
                        return
                    logger.info(f"[后台] 文件上传成功: {file_url[:80]}...")
                    db.update_task(task_id, status='submitting', progress=50)
                    transcription_resp = req.post(
                        'https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription',
                        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json', 'X-DashScope-Async': 'enable'},
                        json={'model': 'paraformer-v2', 'input': {'file_urls': [file_url]},
                              'parameters': {'language_hints': ['zh', 'en'], 'disfluency_removal': False, 'paragraph': True}},
                        timeout=30
                    )
                    if transcription_resp.status_code != 200:
                        logger.error(f"[后台] 转写提交失败: {transcription_resp.status_code} - {transcription_resp.text[:300]}")
                        db.update_task(task_id, status='failed', error=f'转写任务提交失败({transcription_resp.status_code})')
                        return
                    task_data = transcription_resp.json()
                    dashscope_task_id = task_data.get('output', {}).get('task_id', '')
                    if not dashscope_task_id:
                        logger.error(f"[后台] 转写任务提交返回异常: {task_data}")
                        db.update_task(task_id, status='failed', error='转写任务提交返回异常')
                        return
                    logger.info(f"[后台] 转写任务已提交: {dashscope_task_id}")
                    db.update_task(task_id, status='transcribing', progress=60,
                                   result={'dashscope_task_id': dashscope_task_id})
                except req.exceptions.Timeout:
                    logger.error(f"[后台] DashScope上传超时: {task_id}")
                    db.update_task(task_id, status='failed', error='文件上传超时，请尝试较小的文件')
                except Exception as e:
                    logger.error(f"[后台] 音频处理失败: {traceback.format_exc()}")
                    db.update_task(task_id, status='failed', error=str(e))
                finally:
                    try:
                        if os.path.exists(saved_path):
                            os.remove(saved_path)
                    except Exception:
                        pass

            thread = threading.Thread(target=_background_process, daemon=True)
            thread.start()
            return jsonify({'status': 'success', 'task_id': task_id})
        except Exception as e:
            logger.error(f"音频上传失败: {traceback.format_exc()}")
            return jsonify({'error': str(e)}), 500

    @bp.route('/api/transcription-status/<task_id>')
    @login_required
    def api_transcription_status(task_id):
        """查询转写任务状态"""
        ai_config = get_ai_config()
        if not ai_config.get('enabled'):
            return jsonify({'error': 'AI功能未配置'}), 503
        try:
            local_task = db.get_task(task_id)
            if not local_task:
                return jsonify({'error': '任务不存在'}), 404
            local_status = local_task.get('status', 'unknown')
            local_progress = local_task.get('progress', 0)
            local_error = local_task.get('error')
            if local_status == 'failed':
                return jsonify({'status': 'FAILED', 'task_id': task_id, 'error': local_error or '处理失败'})
            if local_status in ('uploading', 'submitting', 'pending'):
                status_map = {'pending': 'UPLOADING', 'uploading': 'UPLOADING', 'submitting': 'SUBMITTING'}
                return jsonify({'status': status_map.get(local_status, 'PENDING'), 'task_id': task_id, 'progress': local_progress})
            if local_status == 'transcribing':
                result_data = local_task.get('result', {})
                if isinstance(result_data, str):
                    try:
                        result_data = json.loads(result_data)
                    except (json.JSONDecodeError, TypeError):
                        result_data = {}
                dashscope_task_id = result_data.get('dashscope_task_id', '')
                if not dashscope_task_id:
                    return jsonify({'status': 'PENDING', 'task_id': task_id, 'progress': 60})
                import requests as req
                resp = req.get(
                    f'https://dashscope.aliyuncs.com/api/v1/tasks/{dashscope_task_id}',
                    headers={'Authorization': f'Bearer {ai_config.get("api_key", "")}'},
                    timeout=15
                )
                if resp.status_code != 200:
                    return jsonify({'error': f'查询失败({resp.status_code})'}), 502
                data = resp.json()
                task_status = data.get('output', {}).get('task_status', 'UNKNOWN')
                result = {'status': task_status, 'task_id': task_id, 'progress': 80}
                if task_status == 'SUCCEEDED':
                    results = data.get('output', {}).get('results', [])
                    transcript_text = ''
                    for r in results:
                        transcription_url = r.get('transcription_url', '')
                        if transcription_url:
                            try:
                                tr_resp = req.get(transcription_url, timeout=15)
                                if tr_resp.status_code == 200:
                                    tr_data = tr_resp.json()
                                    transcripts = tr_data.get('transcripts', [])
                                    for t in transcripts:
                                        transcript_text += t.get('text', '') + '\n'
                                    if not transcript_text:
                                        sentences = tr_data.get('sentences', [])
                                        for s in sentences:
                                            transcript_text += s.get('text', '') + '\n'
                                    if not transcript_text and tr_data.get('text'):
                                        transcript_text = tr_data['text']
                            except Exception as e:
                                logger.warning(f"获取转写结果失败: {e}")
                    result['transcript'] = transcript_text.strip()
                    result['progress'] = 100
                    db.update_task(task_id, status='completed', progress=100,
                                   result={'dashscope_task_id': dashscope_task_id, 'transcript': transcript_text.strip()})
                    logger.info(f"转写完成，文本长度: {len(transcript_text)}")
                elif task_status == 'FAILED':
                    result['error'] = data.get('output', {}).get('message', '转写失败')
                    db.update_task(task_id, status='failed', error=result['error'])
                return jsonify(result)
            if local_status == 'completed':
                result_data = local_task.get('result', {})
                if isinstance(result_data, str):
                    try:
                        result_data = json.loads(result_data)
                    except (json.JSONDecodeError, TypeError):
                        result_data = {}
                return jsonify({'status': 'SUCCEEDED', 'task_id': task_id, 'progress': 100,
                                'transcript': result_data.get('transcript', '')})
            return jsonify({'status': 'UNKNOWN', 'task_id': task_id})
        except Exception as e:
            logger.error(f"查询转写状态失败: {traceback.format_exc()}")
            return jsonify({'error': str(e)}), 500

    # ==================== 实时语音识别 WebSocket ====================

    if sock is not None and _ws_client is not None:
        @sock.route('/ws/realtime-asr')
        def realtime_asr_proxy(ws):
            """WebSocket 代理：浏览器 ↔ 后端 ↔ DashScope Paraformer 实时ASR"""
            import uuid as _uuid
            user = auth.get_current_user()
            if not user:
                try:
                    ws.send(json.dumps({'type': 'error', 'message': '请先登录'}))
                except Exception:
                    pass
                ws.close()
                return
            ai_config = get_ai_config()
            if not ai_config.get('enabled'):
                try:
                    ws.send(json.dumps({'type': 'error', 'message': 'AI功能未配置，请联系管理员'}))
                except Exception:
                    pass
                ws.close()
                return
            api_key = ai_config.get('api_key', '')
            task_id = str(_uuid.uuid4())
            ds_url = 'wss://dashscope.aliyuncs.com/api-ws/v1/inference/'
            try:
                ds_ws = _ws_client.create_connection(
                    ds_url, header=[f'Authorization: Bearer {api_key}'],
                    timeout=15, enable_multithread=True,
                )
            except Exception as e:
                logger.error(f"连接DashScope WebSocket失败: {e}")
                try:
                    ws.send(json.dumps({'type': 'error', 'message': f'连接AI服务失败: {str(e)}'}))
                except Exception:
                    pass
                ws.close()
                return
            run_task_msg = {
                'header': {'action': 'run-task', 'task_id': task_id, 'streaming': 'duplex'},
                'payload': {
                    'task_group': 'audio', 'task': 'asr', 'function': 'recognition',
                    'model': 'paraformer-realtime-v2', 'input': {},
                    'parameters': {
                        'format': 'pcm', 'sample_rate': 16000, 'language_hints': ['zh', 'en'],
                        'semantic_punctuation_enabled': False, 'disfluency_removal_enabled': False,
                        'punctuation_prediction_enabled': True, 'inverse_text_normalization_enabled': True,
                        'heartbeat': True,
                    }
                }
            }
            try:
                ds_ws.send(json.dumps(run_task_msg))
            except Exception as e:
                logger.error(f"发送run-task失败: {e}")
                try:
                    ws.send(json.dumps({'type': 'error', 'message': '启动识别任务失败'}))
                except Exception:
                    pass
                ds_ws.close()
                ws.close()
                return
            try:
                resp = ds_ws.recv()
                resp_data = json.loads(resp)
                event = resp_data.get('header', {}).get('event', '')
                if event != 'task-started':
                    err_msg = resp_data.get('header', {}).get('error_message', '任务启动失败')
                    logger.error(f"DashScope task-started 异常: {resp_data}")
                    try:
                        ws.send(json.dumps({'type': 'error', 'message': err_msg}))
                    except Exception:
                        pass
                    ds_ws.close()
                    ws.close()
                    return
            except Exception as e:
                logger.error(f"等待task-started失败: {e}")
                try:
                    ws.send(json.dumps({'type': 'error', 'message': '等待AI服务响应超时'}))
                except Exception:
                    pass
                ds_ws.close()
                ws.close()
                return
            try:
                ws.send(json.dumps({'type': 'ready', 'message': '实时识别已就绪'}))
            except Exception:
                ds_ws.close()
                return
            logger.info(f"[实时ASR] 任务已启动: {task_id}")
            ws_closed = threading.Event()

            def _dashscope_receiver():
                try:
                    while not ws_closed.is_set():
                        try:
                            resp = ds_ws.recv()
                        except _ws_client.WebSocketTimeoutException:
                            continue
                        except _ws_client.WebSocketConnectionClosedException:
                            break
                        except Exception:
                            break
                        if isinstance(resp, bytes):
                            continue
                        try:
                            data = json.loads(resp)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        event = data.get('header', {}).get('event', '')
                        if event == 'result-generated':
                            sentence = data.get('payload', {}).get('output', {}).get('sentence', {})
                            text = sentence.get('text', '')
                            is_final = sentence.get('sentence_end', False)
                            if sentence.get('heartbeat'):
                                continue
                            try:
                                ws.send(json.dumps({
                                    'type': 'transcript', 'text': text, 'is_final': is_final,
                                    'begin_time': sentence.get('begin_time', 0),
                                    'end_time': sentence.get('end_time', 0),
                                }))
                            except Exception:
                                break
                        elif event == 'task-finished':
                            try:
                                ws.send(json.dumps({'type': 'finished'}))
                            except Exception:
                                pass
                            break
                        elif event == 'task-failed':
                            err_msg = data.get('header', {}).get('error_message', '识别失败')
                            logger.error(f"[实时ASR] 任务失败: {err_msg}")
                            try:
                                ws.send(json.dumps({'type': 'error', 'message': err_msg}))
                            except Exception:
                                pass
                            break
                except Exception as e:
                    logger.error(f"[实时ASR] 接收线程异常: {e}")
                finally:
                    ws_closed.set()

            receiver_thread = threading.Thread(target=_dashscope_receiver, daemon=True)
            receiver_thread.start()
            try:
                while not ws_closed.is_set():
                    try:
                        message = ws.receive()
                    except Exception:
                        break
                    if message is None:
                        break
                    if isinstance(message, bytes):
                        try:
                            ds_ws.send_binary(message)
                        except Exception:
                            logger.warning("[实时ASR] 转发音频失败，连接可能已断开")
                            break
                    elif isinstance(message, str):
                        try:
                            data = json.loads(message)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if data.get('type') == 'stop':
                            finish_msg = {
                                'header': {'action': 'finish-task', 'task_id': task_id, 'streaming': 'duplex'},
                                'payload': {'input': {}}
                            }
                            try:
                                ds_ws.send(json.dumps(finish_msg))
                            except Exception:
                                break
                            break
            except Exception as e:
                logger.error(f"[实时ASR] 主循环异常: {e}")
            finally:
                ws_closed.set()
                try:
                    ds_ws.close()
                except Exception:
                    pass
                logger.info(f"[实时ASR] 任务结束: {task_id}")

    return bp
