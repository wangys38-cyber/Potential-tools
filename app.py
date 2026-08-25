from flask import Flask, request, render_template, redirect, url_for, session, jsonify, make_response, g
import os
import sys
import logging
import traceback
import time
import hashlib
from datetime import timedelta
from functools import wraps
from jinja2 import BytecodeCache

# 认证模块
import auth
import db
import rate_limiter
import request_logger
import security
import performance_middleware
from routes.pages import create_pages_blueprint

# 共享工具模块（v5.0 从 app.py 拆分）
from routes.api import create_api_blueprint
from routes.tools import create_tools_blueprint
from routes.analysis import create_analysis_blueprint
from routes.sync import create_sync_blueprint
from routes.collab import create_collab_blueprint
from routes.collab_v2 import create_collab_v2_blueprint
from routes.visualization import create_visualization_blueprint
from routes.translator import bp_translator
from routes.notes import create_notes_blueprint
from routes.admin import create_admin_blueprint
from routes.knowledge_graph import bp as kg_bp
from routes.teams import create_teams_blueprint
from routes.versions import create_versions_blueprint
from routes.notifications import create_notifications_blueprint

# 性能优化：Whitenoise直接服务静态文件，Flask-Compress启用gzip
from whitenoise import WhiteNoise
from flask_compress import Compress
# 实时语音识别：flask-sock 提供 WebSocket 支持
from flask_sock import Sock

import datetime as _dt

def _get_static_version():
    """静态资源版本号：优先用 git commit hash，其次用 app.py mtime，避免每分钟变化导致缓存失效"""
    _base = os.path.abspath(os.path.dirname(__file__))
    # 1. Railway 注入的 git commit
    sha = os.environ.get('RAILWAY_GIT_COMMIT_SHA', '')
    if sha:
        return sha[:8]
    # 2. 尝试读取本地 git HEAD
    try:
        import subprocess
        result = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                              capture_output=True, text=True, timeout=2, cwd=_base)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # 3. 回退到 app.py 修改时间（仅代码变更时才变）
    try:
        mtime = os.path.getmtime(os.path.join(_base, 'app.py'))
        return _dt.datetime.fromtimestamp(mtime).strftime('%Y%m%d%H%M')
    except Exception:
        return _dt.datetime.now().strftime('%Y%m%d%H%M')

_STATIC_VERSION = _get_static_version()

# 应用版本号
APP_VERSION = '7.0.0'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.abspath(os.path.dirname(__file__))

template_dir = os.path.join(base_dir, 'templates')
static_dir = os.path.join(base_dir, 'static')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

# 初始化数据库（确保 Railway/gunicorn 启动时自动创建表）
try:
    db.init_db()
    logger.info("数据库初始化完成")
except Exception as e:
    logger.error(f"数据库初始化失败: {e}")

# 实时语音识别 WebSocket 支持
sock = Sock(app)

# 启用 gzip 压缩（HTML/JSON/CSS/JS 响应自动压缩，减少传输量 60-80%）
Compress(app)
app.config['COMPRESS_MIMETYPES'] = [
    'text/html', 'text/css', 'text/xml',
    'application/json', 'application/javascript',
    'application/xml', 'image/svg+xml',
]
app.config['COMPRESS_LEVEL'] = 6
app.config['COMPRESS_MIN_SIZE'] = 500  # 仅压缩大于500B的响应，避免小响应压缩开销

# 生产环境检测（需在 WhiteNoise 配置前定义）
_is_production = bool(os.environ.get('RAILWAY_STATIC_URL') or os.environ.get('PORT'))

# Whitenoise: 直接服务静态文件，跳过Flask请求处理（性能提升10倍+）
# 静态资源都带 ?v=版本号 做 cache busting，生产环境可安全长期缓存
app.wsgi_app = WhiteNoise(
    app.wsgi_app,
    root=static_dir,
    prefix='/static/',
    max_age=31536000 if _is_production else 0,  # 生产环境缓存1年，开发环境不缓存
)

# 生产环境优化：关闭模板自动重载（避免每次请求检查文件修改时间）
app.config['TEMPLATES_AUTO_RELOAD'] = not _is_production
app.config['DEBUG'] = not _is_production
app.secret_key = auth.SESSION_SECRET

# Session 配置 — 确保登录状态持久化、跨页面共享
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = _is_production  # HTTPS环境下启用Secure

# 静态文件缓存 — 生产环境长期缓存（带版本号cache busting），开发环境不缓存
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000 if _is_production else 0

# Jinja2 字节码缓存 — 避免每次请求重新解析模板文件（解析速度提升5-10倍）
_jinja_cache_dir = '/dev/shm/jinja_cache' if _is_production else os.path.join(base_dir, '.jinja_cache')
os.makedirs(_jinja_cache_dir, exist_ok=True)

class _ShmBytecodeCache(BytecodeCache):
    """基于内存文件系统的Jinja2字节码缓存"""
    def __init__(self, directory):
        self.directory = directory
    def load_bytecode(self, bucket):
        f = os.path.join(self.directory, bucket.key)
        if os.path.exists(f):
            with open(f, 'rb') as fp:
                bucket.load_bytecode(fp)
    def dump_bytecode(self, bucket):
        f = os.path.join(self.directory, bucket.key)
        with open(f, 'wb') as fp:
            bucket.write_bytecode(fp)

app.jinja_env.bytecode_cache = _ShmBytecodeCache(_jinja_cache_dir)

# 阶段五性能优化：注册 API 响应时间统计 + 慢查询日志中间件
performance_middleware.register_performance_middleware(app)

# 配置 - Railway等云平台使用 /tmp 作为可写目录
if os.environ.get('RAILWAY_STATIC_URL') or os.environ.get('PORT'):
    _runtime_dir = '/tmp/toolbox'
else:
    _runtime_dir = base_dir

app.config['UPLOAD_FOLDER'] = os.path.join(_runtime_dir, 'uploads')
app.config['PDF_FOLDER'] = os.path.join(_runtime_dir, 'pdfs')
app.config['AI_CONFIG_FILE'] = os.path.join(_runtime_dir, 'ai_config.json')
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB - 音频文件上传限制

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PDF_FOLDER'], exist_ok=True)

# 注入模板上下文：当前用户信息（仅对模板渲染生效）
@app.context_processor
def inject_user():
    # 快速检查 session，避免无谓的字典构造
    csrf_token = security.generate_csrf_token()
    if not session.get('user_id'):
        return dict(current_user=None, is_logged_in=False, STATIC_VERSION=_STATIC_VERSION,
                    APP_VERSION=APP_VERSION, csrf_token=csrf_token)
    return dict(
        current_user={
            'id': session.get('user_id'),
            'name': session.get('user_name', ''),
            'email': session.get('user_email', ''),
            'avatar': session.get('user_avatar', ''),
            'provider': session.get('user_provider', ''),
            'is_admin': session.get('user_is_admin', False),
            'nickname': session.get('user_nickname', ''),
            'department': session.get('user_department', ''),
            'role': session.get('user_role', 'member'),
            'skills': session.get('user_skills', []),
        },
        is_logged_in=True,
        STATIC_VERSION=_STATIC_VERSION,
        APP_VERSION=APP_VERSION,
        csrf_token=csrf_token,
    )


# ==================== 登录拦截 ====================
# 允许无需登录即可访问的路径前缀（按频率排序，命中即返回）
_PUBLIC_PATHS = (
    '/static/',
    '/assets/',
    '/login',
    '/auth/',
    '/health',
    '/favicon.ico',
    '/api/merit',          # v2.0: 功德查询允许匿名访问
    '/api/user/preferences', # v2.0: 偏好查询允许匿名访问
    '/api/upload-audio',     # API端点自行检查认证，避免302重定向导致JSON解析失败
    '/api/transcription-status', # 同上
    '/api/ai-models',        # 模型列表允许匿名查看（端点内部检查认证）
    '/api/ai-config',        # 同上
    '/api/ai-test',          # 同上
    '/api/ai-chat',          # AI 对话 SSE 自行检查认证
    '/api/test-report-ai-stream',  # 测试报告 AI 流式分析自行检查认证
    '/api/excel-analyze-ai-stream', # CR 分析 AI 流式自行检查认证
    '/api/generate-minutes-stream', # 会议纪要 AI 流式自行检查认证
    '/api/weekly-report-stream',    # 周报 AI 流式自行检查认证
    '/api/translate',         # 翻译器 API 自行检查认证
    '/api/translate/stream',  # 翻译器流式 SSE 自行检查认证
    '/api/notes/sync',       # 笔记同步API自行检查认证
    '/api/docs',             # 文档仓库API自行检查认证
    '/api/docs/<int:doc_id>', # 文档详情API自行检查认证
    '/api/upload-init',      # 上传API自行检查认证，返回JSON 401
    '/api/upload-chunk',     # 同上
    '/api/upload-complete',  # 同上
    '/ws/',                  # WebSocket端点自行检查认证
    '/share/',               # v5.3: 共享工作空间允许匿名查看
    '/privacy',               # 隐私政策页（公开访问）
)

@app.before_request
def require_login():
    """全局登录拦截：未登录用户自动跳转到登录页"""
    path = request.path

    # 定期清理过期任务（非阻塞，不影响请求处理）
    _maybe_cleanup()

    # 公开路径 — 最先检查，快速放行（静态文件、登录、OAuth回调等）
    for prefix in _PUBLIC_PATHS:
        if path.startswith(prefix):
            return None

    # 已登录 — 放行（仅检查 session，不查数据库）
    if session.get('user_id'):
        return None

    # 如果允许游客模式 — 放行
    if auth.ALLOW_GUEST:
        return None

    # 记录用户原始请求路径，登录后跳回
    if path != '/' and not path.startswith('/api/'):
        session['next_url'] = path
    else:
        session['next_url'] = '/'

    # API 请求返回 401，页面请求 302 跳转
    if path.startswith('/api/'):
        return jsonify({'error': '请先登录', 'need_login': True}), 401
    return redirect(url_for('login_page'))


# ==================== 定期清理 ====================
_last_cleanup_time = 0
_CLEANUP_INTERVAL = 3600  # 1小时清理一次

def _maybe_cleanup():
    """定期清理过期的后台任务和上传会话"""
    global _last_cleanup_time
    now = time.time()
    if now - _last_cleanup_time < _CLEANUP_INTERVAL:
        return
    _last_cleanup_time = now
    try:
        db.cleanup_old_tasks(max_age_hours=6)
        db.cleanup_old_activity(max_age_days=90)
        # 阶段四安全加固：清理登录尝试（24h）、审计日志（90天）、过期会话、软删除用户（30天）
        db.cleanup_old_login_attempts(max_age_hours=24)
        db.cleanup_old_audit_logs(max_age_days=90)
        db.cleanup_expired_sessions()
        db.purge_expired_deleted_users(grace_days=30)
        logger.info("清理过期任务、活动记录和安全数据完成")
    except Exception as e:
        logger.error(f"清理过期任务失败: {e}")


# ==================== 全局错误处理 ====================
@app.errorhandler(413)
def request_entity_too_large(error):
    """文件超过 MAX_CONTENT_LENGTH 时返回 JSON 而非默认 HTML 页面"""
    return jsonify({'error': f'文件过大，最大支持 {app.config["MAX_CONTENT_LENGTH"] // 1024 // 1024}MB'}), 413

@app.errorhandler(429)
def too_many_requests(error):
    """速率限制触发时返回 JSON"""
    return jsonify({'error': '请求过于频繁，请稍后重试'}), 429

@app.errorhandler(500)
def internal_server_error(error):
    """服务器内部错误返回 JSON 而非默认 HTML 页面"""
    logger.error(f"500错误: {traceback.format_exc()}")
    return jsonify({'error': '服务器内部错误，请稍后重试'}), 500

@app.errorhandler(Exception)
def handle_exception(error):
    """捕获所有未处理异常，返回 JSON（不泄露内部错误详情）"""
    logger.error(f"未处理异常: {traceback.format_exc()}")
    # 安全：生产环境不返回详细错误信息，仅记录日志
    return jsonify({'error': '服务器内部错误，请稍后重试'}), 500


@app.before_request
def guest_access_control():
    """游客访问控制：未登录用户只能访问白名单内的路径"""
    user = auth.get_current_user()
    if user:
        g.user = user  # 存入 g 供后续中间件使用
        return None  # 已登录用户不限制
    # 未登录用户（游客）检查白名单
    if not auth.is_guest_allowed(request.path):
        # API 请求返回 401，页面请求重定向到登录页
        if request.path.startswith('/api/'):
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        return redirect('/login')
    return None


@app.before_request
def api_rate_limit():
    """API 速率限制检查"""
    return rate_limiter.check_rate_limit()


@app.before_request
def log_request_start():
    """记录请求开始时间（用于结构化请求日志）"""
    request_logger.before_request_log()


@app.before_request
def security_middleware():
    """阶段四安全加固：CSRF 防护 + 会话空闲超时"""
    # 1. 会话空闲超时检查
    if session.get('user_id'):
        if auth.check_session_timeout():
            # 会话超时，清理并跳转登录
            token = session.get('session_token')
            if token:
                db.delete_user_session(token)
            user_id = session.get('user_id')
            db.add_audit_log(user_id, 'session_timeout', target_type='user',
                             target_id=user_id, ip=request.remote_addr or '',
                             user_agent=request.headers.get('User-Agent', ''),
                             details='会话空闲超时自动登出')
            session.clear()
            if request.path.startswith('/api/'):
                return jsonify({'error': '会话已超时，请重新登录', 'need_login': True}), 401
            return redirect(url_for('login_page'))

    # 2. CSRF 防护（仅对非 GET 请求，已登录用户）
    csrf_result = security.csrf_protect()
    if csrf_result is not None:
        return csrf_result

    return None


@app.after_request
def apply_rate_limit_headers(response):
    """添加限流响应头"""
    return rate_limiter.add_rate_limit_headers(response)


@app.after_request
def log_request_end(response):
    """记录结构化请求日志"""
    return request_logger.after_request_log(response)


@app.after_request
def add_cache_headers(response):
    """为静态资源添加缓存头，减少重复下载，并添加安全响应头"""
    path = request.path
    has_version = request.args.get('v') is not None
    # JS/CSS 文件：带版本号时缓存1年（immutable），否则缓存1小时
    if path.startswith('/static/') and (path.endswith('.js') or path.endswith('.css')):
        if has_version:
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        else:
            response.headers['Cache-Control'] = 'public, max-age=3600, must-revalidate'
    # 其他静态文件：带版本号缓存1年，否则缓存1天
    elif path.startswith('/static/') or path.startswith('/assets/'):
        if has_version:
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        else:
            response.headers['Cache-Control'] = 'public, max-age=86400'
    # API 响应不缓存
    elif path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    # HTML页面 — 确保ETag与压缩正确配合，短缓存
    elif response.headers.get('Content-Type', '').startswith('text/html'):
        response.headers['Cache-Control'] = 'public, max-age=60'
        response.headers['Vary'] = 'Accept-Encoding'
    elif response.headers.get('ETag'):
        response.headers['Vary'] = 'Accept-Encoding'

    # 安全响应头（适用于所有响应）
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    # HSTS — 仅在 HTTPS 环境下生效
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

    return response


# Register Blueprints (v5.0 之前的旧 Blueprint)
try:
    from bp_ai import register as register_ai_bp
    register_ai_bp(app)
except ImportError as e:
    logger.warning(f"bp_ai Blueprint 加载失败: {e}")

try:
    from bp_user import register as register_user_bp
    register_user_bp(app)
except ImportError as e:
    logger.warning(f"bp_user Blueprint 加载失败: {e}")


# 认证装饰器统一从 auth 模块导入（供旧代码引用）
from auth import login_required, login_required_or_guest


# ==================== 认证路由 ====================

@app.route('/login')
def login_page():
    """登录页面"""
    error = request.args.get('error', '')
    return render_template('login.html',
                           error=error,
                           allow_guest=auth.ALLOW_GUEST,
                           wechat_configured=auth.is_configured('wechat'))


@app.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    """账号密码注册 API"""
    return auth.register()


@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """账号密码登录 API"""
    return auth.login()


@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    """退出登录 API"""
    return auth.logout_api()


@app.route('/auth/wechat')
def auth_wechat():
    """发起微信OAuth登录"""
    return auth.wechat_login()


@app.route('/auth/wechat/callback')
def auth_wechat_callback():
    """微信OAuth回调"""
    return auth.wechat_callback()


@app.route('/auth/feishu')
def auth_feishu():
    """发起飞书OAuth登录"""
    return auth.feishu_login()


@app.route('/auth/feishu/callback')
def auth_feishu_callback():
    """飞书OAuth回调"""
    return auth.feishu_callback()


@app.route('/auth/google')
def auth_google():
    """发起Google OAuth登录"""
    return auth.google_login()


@app.route('/auth/google/callback')
def auth_google_callback():
    """Google OAuth回调"""
    return auth.google_callback()


@app.route('/auth/logout')
def auth_logout():
    """退出登录"""
    return auth.logout()


# ==================== 健康检查（供 Railway/K8s 使用） ====================
@app.route('/health')
def health_check():
    """健康检查端点 — 无需认证，返回 200"""
    return jsonify({'status': 'ok', 'service': 'potential-tools'}), 200


# ==================== 隐私政策页 ====================
@app.route('/privacy')
def privacy_page():
    """隐私政策页面 — 公开访问"""
    return render_template('privacy.html', nav_title='隐私政策')


# ==================== 协作：共享页面 ====================
@app.route('/share/<share_code>')
def share_page(share_code):
    """共享工作空间页面"""
    import db as _db
    ws = _db.get_workspace_by_code(share_code)
    if not ws:
        return render_template('share_expired.html'), 404
    return render_template('share.html', share_code=share_code, workspace=ws,
                           nav_title=ws.get('title', '共享工作空间'))


# ==================== 模板渲染缓存 + ETag ====================
# 内存缓存已渲染的模板，配合ETag实现304 Not Modified
# 静态模板（不含current_user）全量缓存；含current_user的按用户缓存
_template_cache = {}

# 不含动态用户信息的模板 — 可全局缓存
_STATIC_TEMPLATES = frozenset({
    'excel_analysis.html', 'md2pdf.html',
    'plan_generator.html',
})

def _get_template_mtime(template_name):
    """获取模板文件的修改时间，用于缓存失效检测"""
    try:
        tpl_path = os.path.join(app.template_folder, template_name)
        if os.path.isfile(tpl_path):
            return int(os.path.getmtime(tpl_path))
    except Exception:
        pass
    return 0

def cached_render(template_name, **context):
    """渲染模板并缓存结果，支持ETag/304。
    
    - 静态模板：全局缓存，首次渲染后后续请求直接返回304或缓存内容
    - 动态模板：按用户缓存，同一用户重复访问直接返回304
    - 模板文件修改后自动失效缓存
    """
    if template_name in _STATIC_TEMPLATES:
        cache_key = template_name
    else:
        uid = session.get('user_id', 0)
        cache_key = f'{template_name}:{uid}'

    mtime = _get_template_mtime(template_name)
    cached = _template_cache.get(cache_key)
    if cached is not None:
        cached_mtime, etag, html = cached
        # 模板文件未修改且缓存存在 — 使用缓存
        if cached_mtime == mtime:
            # 浏览器发送 If-None-Match — 内容未变，返回304（无body，瞬时响应）
            if request.headers.get('If-None-Match') == etag:
                resp = make_response('', 304)
                resp.headers['ETag'] = etag
                resp.headers['Cache-Control'] = 'no-cache'  # 必须验证，但304省带宽
                return resp
            resp = make_response(html)
            resp.headers['ETag'] = etag
            resp.headers['Cache-Control'] = 'no-cache'
            return resp
        # 模板文件已修改 — 清除旧缓存，重新渲染

    # 首次渲染或缓存失效后重新渲染
    html = render_template(template_name, **context)
    etag = hashlib.md5(html.encode('utf-8')).hexdigest()[:16]
    _template_cache[cache_key] = (mtime, etag, html)

    resp = make_response(html)
    resp.headers['ETag'] = etag
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


# ==================== v5.0 Blueprint 注册 ====================
# 页面路由（15个简单模板渲染路由）
app.register_blueprint(create_pages_blueprint(cached_render))

# 通用 API（系统信息、设置、飞书、健康检查、分片上传、下载、静态资源）
app.register_blueprint(create_api_blueprint(base_dir, _STATIC_VERSION))

# 工具类（会议纪要、周报、OCR、MD2PDF、音频转写、Jira搜索、实时ASR）
app.register_blueprint(create_tools_blueprint(sock=sock))

# 数据分析（测试报告、Excel CR分析、Excel智能整理、PDF生成）
app.register_blueprint(create_analysis_blueprint())

# 云端同步
app.register_blueprint(create_sync_blueprint())

# 协作功能（v5.3）
app.register_blueprint(create_collab_blueprint())

# 协作功能深化（v7.0）
app.register_blueprint(create_collab_v2_blueprint())

# 数据可视化增强（v8.0）
app.register_blueprint(create_visualization_blueprint())

# IT 技术文档翻译器（v9.0）
app.register_blueprint(bp_translator)

# 牛马笔记全面重构（v8.0）
app.register_blueprint(create_notes_blueprint())

# v9.1 用户管理平台
app.register_blueprint(create_admin_blueprint())

# 研发知识图谱（v10.0）
app.register_blueprint(kg_bp)

# 团队管理与数据共享（v11.0）
app.register_blueprint(create_teams_blueprint())

# 文档版本历史（v12.0）
app.register_blueprint(create_versions_blueprint())

# 通知系统（v12.0）
app.register_blueprint(create_notifications_blueprint())

# HLD 生成器
try:
    from routes.hld_generator import bp_hld
    app.register_blueprint(bp_hld)
except ImportError as e:
    logger.warning(f"HLD Blueprint 加载失败: {e}")

logger.info(f"v5.0 Blueprint 注册完成: pages, api, tools, analysis, sync, collab, collab_v2, hld, notes")
logger.info(f"静态资源版本: {_STATIC_VERSION}, 生产环境: {_is_production}")


# ==================== 应用入口 ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"启动 Potential-tools v5.0，端口: {port}")
    app.run(host='0.0.0.0', port=port, debug=not _is_production)
