"""通用 API 路由 Blueprint — 系统信息、设置、飞书、健康检查、上传、下载、静态资源"""
import os
import sys
import json
import time
import secrets
import logging
import traceback
from functools import wraps

from flask import Blueprint, request, jsonify, make_response, send_file, send_from_directory, redirect, render_template, g, current_app

import auth
import db
import feishu_push
import ai_utils
from routes.common import (
    ExcelReader, background_tasks, load_task_meta, save_task_meta, delete_task_meta,
    _CST,
)

logger = logging.getLogger(__name__)

get_ai_config = ai_utils.get_ai_config


# ==================== 认证装饰器 ====================

def login_required(f):
    """严格登录装饰器：未登录返回401，登录用户存入 g.user"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = auth.get_current_user()
        if not user:
            return jsonify({'error': '请先登录'}), 401
        g.user = user
        return f(*args, **kwargs)
    return decorated


def login_required_or_guest(f):
    """登录或访客装饰器：ALLOW_GUEST=true 时允许访客访问，否则要求登录"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = auth.get_current_user()
        if not user and not auth.ALLOW_GUEST:
            return jsonify({'error': '请先登录'}), 401
        g.user = user
        return f(*args, **kwargs)
    return decorated


def _is_production_env():
    return bool(os.environ.get('RAILWAY_STATIC_URL') or os.environ.get('PORT'))


def create_api_blueprint(base_dir, static_version):
    """创建通用 API Blueprint

    Args:
        base_dir: 应用根目录（用于访问计数文件、静态资源）
        static_version: 静态资源版本号
    """
    bp = Blueprint('api_routes', __name__)
    static_dir = os.path.join(base_dir, 'static')
    notenb_dist = os.path.join(static_dir, 'noteNB')

    def _read_visit_count():
        """从数据库读取访问次数"""
        try:
            return int(db.get_config('visit_count', 0))
        except Exception:
            return 0

    def _write_visit_count(count):
        """将访问次数写入数据库"""
        try:
            db.set_config('visit_count', count)
        except Exception:
            pass

    # ==================== 健康检查 ====================

    @bp.route('/health')
    def health():
        """健康检查端点，供 Railway / 负载均衡使用"""
        return jsonify({'status': 'ok', 'version': static_version, 'pid': os.getpid()})

    # ==================== 访问计数 ====================

    @bp.route('/api/visit-count')
    def api_visit_count():
        """访问计数：返回当前次数并递增"""
        count = _read_visit_count() + 1
        _write_visit_count(count)
        return jsonify({'count': count})

    # ==================== Favicon ====================

    @bp.route('/favicon.ico')
    def favicon():
        """浏览器默认请求的favicon — 返回工具箱emoji SVG"""
        svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧰</text></svg>"
        resp = make_response(svg, 200)
        resp.headers['Content-Type'] = 'image/svg+xml'
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp

    # ==================== 系统诊断 ====================

    @bp.route('/api/system-info', methods=['GET'])
    @login_required_or_guest
    def api_system_info():
        """系统诊断信息"""
        import psutil
        p = psutil.Process()
        mem_info = p.memory_info()
        db_status = db.check_db()
        ai_config = get_ai_config()
        upload_dir = current_app.config.get('UPLOAD_FOLDER', '/tmp/toolbox/uploads')
        upload_size = 0
        upload_count = 0
        if os.path.exists(upload_dir):
            for fname in os.listdir(upload_dir):
                fpath = os.path.join(upload_dir, fname)
                if os.path.isfile(fpath):
                    upload_count += 1
                    upload_size += os.path.getsize(fpath)
        return jsonify({
            'status': 'ok',
            'version': '3.0',
            'python': sys.version.split()[0],
            'memory_mb': round(mem_info.rss / 1024 / 1024, 1),
            'cpu_percent': p.cpu_percent(interval=0.1),
            'threads': p.num_threads(),
            'db': db_status,
            'ai': {
                'enabled': ai_config.get('enabled', False),
                'base_url': ai_config.get('base_url', ''),
                'model': ai_config.get('model', ''),
                'has_key': bool(ai_config.get('api_key', '').strip()),
            },
            'uploads': {
                'count': upload_count,
                'size_mb': round(upload_size / 1024 / 1024, 1),
            },
            'uptime': time.time() - p.create_time(),
        })

    # ==================== Debug ====================

    @bp.route('/api/debug')
    @login_required
    def api_debug():
        """诊断端点（需登录，生产环境禁用）"""
        if _is_production_env():
            return jsonify({'error': 'debug endpoint disabled in production'}), 403
        import psutil
        p = psutil.Process()
        mem_info = p.memory_info()
        upload_dir = current_app.config['UPLOAD_FOLDER']
        uploaded_files = []
        total_upload_size = 0
        if os.path.exists(upload_dir):
            for fname in os.listdir(upload_dir):
                fpath = os.path.join(upload_dir, fname)
                if os.path.isfile(fpath):
                    fsize = os.path.getsize(fpath)
                    uploaded_files.append({'name': fname, 'size_kb': round(fsize / 1024, 1)})
                    total_upload_size += fsize
                elif os.path.isdir(fpath):
                    file_count = len(os.listdir(fpath))
                    uploaded_files.append({'name': f'{fname}/', 'files': file_count})
        active_tasks = {
            tid: {'status': t.get('status'), 'age_seconds': round(time.time() - t.get('created_at', time.time()), 0)}
            for tid, t in background_tasks.items()
        }
        return jsonify({
            'status': 'ok',
            'pid': os.getpid(),
            'memory': {
                'rss_mb': round(mem_info.rss / 1024 / 1024, 1),
                'vms_mb': round(mem_info.vms / 1024 / 1024, 1),
            },
            'background_tasks': {
                'total': len(background_tasks),
                'active': active_tasks,
            },
            'uploads': {
                'files': uploaded_files[:20],
                'total_size_mb': round(total_upload_size / 1024 / 1024, 2),
            },
            'config': {
                'upload_folder': upload_dir,
                'pdf_folder': current_app.config['PDF_FOLDER'],
                'is_cloud': bool(os.environ.get('RAILWAY_STATIC_URL') or os.environ.get('PORT')),
            },
            'database': db.check_db(),
        })

    # ==================== 主题设置 ====================

    @bp.route('/api/settings/theme', methods=['POST'])
    @login_required_or_guest
    def api_save_theme():
        """保存用户主题偏好"""
        user = g.user
        data = request.get_json(silent=True) or {}
        theme_mode = data.get('theme_mode', 'auto')
        accent_color = data.get('accent_color', '')
        if user:
            db.set_user_preferences(user['id'], theme=theme_mode,
                                    accent_color=accent_color if accent_color else None)
        return jsonify({'status': 'success', 'theme_mode': theme_mode, 'accent_color': accent_color})

    @bp.route('/api/settings/theme', methods=['GET'])
    def api_get_theme():
        """获取用户主题偏好"""
        user = auth.get_current_user()
        theme_mode = 'auto'
        accent_color = '#0071e3'
        if user:
            prefs = db.get_user_preferences(user['id']) or {}
            theme_mode = prefs.get('theme', 'auto')
            accent_color = prefs.get('accent_color', '') or '#0071e3'
        return jsonify({'status': 'success', 'theme_mode': theme_mode, 'accent_color': accent_color})

    # ==================== 飞书设置 ====================

    @bp.route('/api/settings/feishu', methods=['GET'])
    def api_get_feishu():
        """获取用户飞书 Webhook 配置"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'status': 'error', 'error': '请先登录'}), 401
        webhook = db.get_feishu_webhook(user['id'])
        secret = db.get_feishu_secret(user['id'])
        return jsonify({'status': 'success', 'webhook': webhook, 'secret': secret, 'configured': bool(webhook)})

    @bp.route('/api/settings/feishu', methods=['POST'])
    def api_set_feishu():
        """保存用户飞书 Webhook 配置"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'status': 'error', 'error': '请先登录'}), 401
        data = request.get_json(silent=True) or {}
        webhook = (data.get('webhook') or '').strip()
        secret = (data.get('secret') or '').strip()
        if webhook and not webhook.startswith('https://open.feishu.cn/open-apis/bot/v2/hook/'):
            return jsonify({'status': 'error', 'error': 'Webhook URL 格式不正确'}), 400
        db.set_feishu_webhook(user['id'], webhook)
        db.set_feishu_secret(user['id'], secret)
        return jsonify({'status': 'success', 'configured': bool(webhook)})

    @bp.route('/api/feishu/test', methods=['POST'])
    def api_feishu_test():
        """测试飞书 Webhook 连接"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'status': 'error', 'error': '请先登录'}), 401
        webhook = db.get_feishu_webhook(user['id'])
        secret = db.get_feishu_secret(user['id'])
        if not webhook:
            return jsonify({'status': 'error', 'error': '请先配置飞书 Webhook'}), 400
        result = feishu_push.send_feishu_text(webhook, '✅ 工具集 v5.0 飞书推送测试成功！', secret=secret)
        if result['ok']:
            return jsonify({'status': 'success', 'message': '测试消息已发送'})
        else:
            return jsonify({'status': 'error', 'error': result.get('error', '发送失败')}), 502

    # ==================== 用户信息 ====================

    @bp.route('/api/user/profile', methods=['GET'])
    def api_get_user_profile():
        """获取当前用户信息"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'status': 'error', 'error': '请先登录'}), 401
        return jsonify({
            'status': 'success',
            'id': user['id'],
            'name': user.get('name', ''),
            'email': user.get('email', ''),
            'avatar': user.get('avatar', ''),
            'provider': user.get('provider', ''),
            'created_at': user.get('created_at', 0)
        })

    @bp.route('/api/user/profile', methods=['POST'])
    def api_update_user_profile():
        """更新用户信息（姓名、头像）"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'status': 'error', 'error': '请先登录'}), 401
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        avatar = (data.get('avatar') or '').strip()

        # 验证姓名
        if name and len(name) > 50:
            return jsonify({'status': 'error', 'error': '姓名不能超过50个字符'}), 400

        # 验证头像（支持URL或base64）
        if avatar:
            if avatar.startswith('data:image/'):
                # base64头像，限制大小（约500KB）
                if len(avatar) > 700000:
                    return jsonify({'status': 'error', 'error': '头像图片过大，请压缩后再上传'}), 400
            elif not avatar.startswith('http://') and not avatar.startswith('https://'):
                return jsonify({'status': 'error', 'error': '头像URL格式不正确'}), 400

        # 更新数据库
        try:
            with db.engine.begin() as conn:
                updates = []
                params = {}
                if name:
                    updates.append('name = :name')
                    params['name'] = name
                if avatar:
                    updates.append('avatar = :avatar')
                    params['avatar'] = avatar
                if updates:
                    params['id'] = user['id']
                    conn.execute(db.text(f"UPDATE users SET {', '.join(updates)} WHERE id = :id"), params)
        except Exception as e:
            logger.error(f"更新用户信息失败: {e}")
            return jsonify({'status': 'error', 'error': '更新失败，请重试'}), 500

        # 更新session中的用户信息
        try:
            from flask import session
            if 'user' in session:
                if name:
                    session['user']['name'] = name
                if avatar:
                    session['user']['avatar'] = avatar
                session.modified = True
        except Exception:
            pass

        return jsonify({'status': 'success', 'message': '更新成功', 'name': name or user.get('name'), 'avatar': avatar or user.get('avatar')})

    @bp.route('/api/feishu/push', methods=['POST'])
    def api_feishu_push():
        """通用飞书推送接口"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'status': 'error', 'error': '请先登录'}), 401
        webhook = db.get_feishu_webhook(user['id'])
        secret = db.get_feishu_secret(user['id'])
        if not webhook:
            return jsonify({'status': 'error', 'error': '请先在设置中配置飞书 Webhook'}), 400
        data = request.get_json(silent=True) or {}
        msg_type = data.get('type', 'text')
        title = data.get('title', '工具集推送')
        source_url = data.get('url')
        try:
            if msg_type == 'text':
                content = data.get('content', '')
                result = feishu_push.send_feishu_text(webhook, content, secret=secret)
            elif msg_type == 'card':
                content = data.get('content', '')
                result = feishu_push.send_feishu_card(webhook, title, content, header_color='purple', link_url=source_url, secret=secret)
            elif msg_type == 'weekly':
                result = feishu_push.send_weekly_report(
                    webhook, title,
                    summary=data.get('summary', ''),
                    highlights=data.get('highlights', ''),
                    plans=data.get('plans', ''),
                    source_url=source_url,
                    secret=secret
                )
            elif msg_type == 'meeting':
                result = feishu_push.send_meeting_minutes(
                    webhook, title,
                    summary=data.get('summary', ''),
                    decisions=data.get('decisions', ''),
                    todos=data.get('todos', ''),
                    source_url=source_url,
                    secret=secret
                )
            else:
                return jsonify({'status': 'error', 'error': f'不支持的消息类型: {msg_type}'}), 400
            if result['ok']:
                return jsonify({'status': 'success', 'message': '推送成功'})
            else:
                return jsonify({'status': 'error', 'error': result.get('error', '推送失败')}), 502
        except Exception as e:
            logger.error(f'飞书推送异常: {e}')
            return jsonify({'status': 'error', 'error': f'推送异常: {str(e)}'}), 500

    # ==================== 分片上传 ====================

    def _load_chunk_meta(upload_id):
        session = db.get_upload_session(upload_id)
        if not session:
            return None
        filename = session['filename']
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ('.xlsx', '.xls', '.csv'):
            ext = '.xlsx'
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"excel_{upload_id}{ext}")
        return {
            'upload_id': upload_id,
            'filename': filename,
            'file_path': file_path,
            'ext': ext,
            'total_chunks': session['total_chunks'],
            'chunk_size': session['chunk_size'],
            'file_size': session['file_size'],
            'total_size': session['file_size'],
            'received_chunks': session.get('received_set', set()),
        }

    def _save_chunk_meta(upload_id, meta):
        db.create_upload_session(
            upload_id, meta.get('filename', ''),
            meta.get('total_chunks', 0),
            meta.get('chunk_size', 2 * 1024 * 1024),
            meta.get('total_size', meta.get('file_size', 0))
        )

    def _add_received_chunk(upload_id, chunk_index):
        return db.add_received_chunk(upload_id, chunk_index)

    def _delete_chunk_meta(upload_id):
        db.delete_upload_session(upload_id)

    @bp.route('/api/upload-init', methods=['POST'])
    def api_upload_init():
        """初始化分块上传，返回 upload_id"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        data = request.get_json(silent=True) or {}
        filename = data.get('filename', '')
        total_size = data.get('total_size', 0)
        total_chunks = data.get('total_chunks', 0)
        if not filename or total_chunks == 0:
            return jsonify({'error': '缺少必要参数: filename, total_chunks'}), 400
        filename_lower = filename.lower()
        if not (filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls') or filename_lower.endswith('.csv')):
            return jsonify({'error': '只支持Excel/CSV文件(.xlsx, .xls, .csv)'}), 400
        orig_ext = os.path.splitext(filename)[1].lower()
        if orig_ext not in ('.xlsx', '.xls', '.csv'):
            orig_ext = '.xlsx'
        upload_id = secrets.token_hex(8)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"excel_{upload_id}{orig_ext}")
        chunk_uploads = {
            'filename': filename, 'file_path': file_path, 'ext': orig_ext,
            'total_chunks': total_chunks, 'total_size': total_size,
            'received_chunks': set(), 'created_at': time.time()
        }
        _save_chunk_meta(upload_id, chunk_uploads)
        with open(file_path, 'wb') as f:
            if total_size > 0:
                f.truncate(total_size)
        logger.info(f"分块上传初始化: {filename}, upload_id={upload_id}, total_chunks={total_chunks}, total_size={total_size}")
        return jsonify({'status': 'success', 'data': {'upload_id': upload_id}})

    @bp.route('/api/upload-chunk', methods=['POST'])
    def api_upload_chunk():
        """上传单个分块"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        upload_id = request.form.get('upload_id', '')
        chunk_index = request.form.get('chunk_index', '')
        chunk_file = request.files.get('chunk', None)
        if not upload_id:
            return jsonify({'error': '无效的 upload_id'}), 400
        meta = _load_chunk_meta(upload_id)
        if meta is None:
            return jsonify({'error': '无效的 upload_id'}), 400
        if chunk_index == '' or chunk_file is None:
            return jsonify({'error': '缺少 chunk_index 或 chunk'}), 400
        chunk_index = int(chunk_index)
        if chunk_index in meta['received_chunks']:
            return jsonify({'status': 'success', 'data': {'chunk_index': chunk_index, 'duplicate': True, 'received': len(meta['received_chunks']), 'total': meta['total_chunks']}})
        chunk_data = chunk_file.read()
        offset = int(request.form.get('offset', -1))
        if offset < 0:
            return jsonify({'error': '缺少 offset 参数'}), 400
        with open(meta['file_path'], 'r+b') as f:
            f.seek(offset)
            f.write(chunk_data)
        updated_meta = _add_received_chunk(upload_id, chunk_index)
        if updated_meta is None:
            return jsonify({'error': '更新分块元数据失败'}), 500
        logger.info(f"分块上传: upload_id={upload_id}, chunk={chunk_index}/{updated_meta['total_chunks'] - 1}, size={len(chunk_data)}, received={len(updated_meta['received_chunks'])}")
        return jsonify({'status': 'success', 'data': {'chunk_index': chunk_index, 'received': len(updated_meta['received_chunks']), 'total': updated_meta['total_chunks']}})

    @bp.route('/api/upload-complete', methods=['POST'])
    def api_upload_complete():
        """分块上传完成，验证文件并返回 file_id"""
        user = auth.get_current_user()
        if not user:
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        data = request.get_json(silent=True) or {}
        upload_id = data.get('upload_id', '')
        if not upload_id:
            return jsonify({'error': '无效的 upload_id'}), 400
        meta = _load_chunk_meta(upload_id)
        if meta is None:
            return jsonify({'error': '无效的 upload_id'}), 400
        if len(meta['received_chunks']) != meta['total_chunks']:
            missing = sorted(set(range(meta['total_chunks'])) - meta['received_chunks'])
            return jsonify({
                'error': f'分块不完整: 已收到 {len(meta["received_chunks"])}/{meta["total_chunks"]}',
                'missing_chunks': missing,
                'total_chunks': meta['total_chunks'],
                'received_chunks': len(meta['received_chunks'])
            }), 400
        file_path = meta['file_path']
        filename = meta['filename']
        file_id = os.path.basename(file_path).replace('excel_', '').replace(meta['ext'], '')
        try:
            file_size = os.path.getsize(file_path)
            logger.info(f"========== 分块上传完成: {filename} (size={file_size / 1024 / 1024:.2f}MB) ==========")
            is_html = False
            with open(file_path, 'rb') as f:
                header = f.read(200)
            if b'<html' in header.lower() or b'<!doctype' in header.lower():
                is_html = True
            reader = ExcelReader(file_path)
            reader.open()
            sheet_names = reader.get_sheet_names()
            reader.close()
            _delete_chunk_meta(upload_id)
            logger.info(f"上传成功: file_id={file_id}, sheets={sheet_names}, is_html={is_html}")
            return jsonify({
                'status': 'success',
                'data': {
                    'file_id': file_id, 'file_name': filename,
                    'sheet_names': sheet_names,
                    'file_size_mb': round(file_size / 1024 / 1024, 2),
                    'is_html': is_html,
                }
            })
        except Exception as e:
            logger.error(f"分块上传文件分析失败: {traceback.format_exc()}")
            try:
                os.unlink(file_path)
            except Exception:
                pass
            _delete_chunk_meta(upload_id)
            return jsonify({'error': str(e)}), 500

    # ==================== 文件下载 ====================

    @bp.route('/download/<filename>')
    def download_file(filename):
        from werkzeug.utils import secure_filename
        safe_name = secure_filename(filename)
        if not safe_name or safe_name != filename:
            return jsonify({'error': '无效的文件名'}), 400
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_name)
        if os.path.exists(filepath):
            is_pdf = safe_name.lower().endswith('.pdf')
            return send_file(filepath, as_attachment=not is_pdf)
        filepath = os.path.join(current_app.config['PDF_FOLDER'], safe_name)
        if os.path.exists(filepath):
            is_pdf = safe_name.lower().endswith('.pdf')
            return send_file(filepath, as_attachment=not is_pdf)
        return jsonify({'error': '文件不存在'}), 404

    # ==================== NoteNB 笔记应用路由 ====================

    @bp.route('/noteNB')
    def notenb_redirect():
        return redirect('/noteNB/')

    @bp.route('/noteNB/')
    def notenb_index():
        return render_template('notes.html')

    @bp.route('/noteNB/assets/<path:filename>')
    def notenb_assets(filename):
        notenb_assets_dir = os.path.join(notenb_dist, 'assets')
        return send_from_directory(notenb_assets_dir, filename)

    @bp.route('/noteNB/<path:path>')
    def notenb_catch_all(path):
        file_path = os.path.join(notenb_dist, path)
        if os.path.isfile(file_path):
            return send_file(file_path)
        return notenb_index()

    # ==================== 静态资源路由 ====================

    @bp.route('/assets/<path:filename>')
    def serve_assets(filename):
        assets_dir = os.path.join(base_dir, 'assets')
        return send_from_directory(assets_dir, filename)

    # ==================== Dashboard 研发健康度数据 ====================

    @bp.route('/api/dashboard/stats', methods=['GET'])
    @login_required_or_guest
    def api_dashboard_stats():
        """Dashboard 研发健康度看板数据接口
        返回 bug_trend、mttf、version_progress、personal_efficiency、project_overview
        数据优先从数据库/缓存聚合，无真实数据源的字段返回合理默认值
        """
        # 访问计数（真实数据）
        visit_count = _read_visit_count()

        # Bug 趋势（近7天，占位数据 — 后续可对接 CR 分析结果表）
        bug_trend = {
            'days': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
            'values': [12, 8, 15, 6, 10, 3, 5],
            'total': 59,
            'avg': 8.4,
            'peak': 15
        }

        # MTTF 指标（占位数据 — 后续可对接挂测结果表）
        mttf = {
            'value': 128.5,
            'unit': 'h',
            'target': 120,
            'trend': 'up',
            'trend_pct': 12.3,
            'test_cycle': '7×24h 挂测',
            'major_failure': 'Malloc 失败 (3次)',
            'product': 'SR6'
        }

        # 版本进度（占位数据 — 后续可对接项目管理）
        version_progress = {
            'version': 'v5.0.0',
            'milestone': '迭代1',
            'items': [
                {'name': '后端 Blueprint 拆分', 'pct': 100, 'status': 'done'},
                {'name': '前端组件库统一', 'pct': 80, 'status': 'doing'},
                {'name': 'Dashboard 看板', 'pct': 60, 'status': 'doing'},
                {'name': '统一上传/历史组件', 'pct': 100, 'status': 'done'}
            ]
        }

        # 个人效能（占位数据 — 后续可对接 Jira/站会数据）
        personal_efficiency = {
            'today_todos': 3,
            'week_resolved': 7,
            'month_commits': 12,
            'on_time_rate': 89
        }

        # 项目概览
        project_overview = {
            'current_version': 'v5.0.0 (迭代1)',
            'status': '活跃开发中',
            'product_lines': 'E62 / SR5 / SR6 智能手表',
            'milestone': 'SR6 CP2 质量攻坚',
            'repo': 'github.com/wangys38-cyber/Potential-tools',
            'deploy_platform': 'Railway (wangys666.top)',
            'tech_stack': 'Flask + 原生前端 + Blueprint',
            'visit_count': visit_count
        }

        return jsonify({
            'status': 'success',
            'data': {
                'bug_trend': bug_trend,
                'mttf': mttf,
                'version_progress': version_progress,
                'personal_efficiency': personal_efficiency,
                'project_overview': project_overview,
                'generated_at': int(time.time())
            }
        })

    return bp
