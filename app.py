from flask import Flask, request, render_template, redirect, url_for, session, jsonify, make_response, g
import os
from dotenv import load_dotenv
load_dotenv()  # 加载 .env 配置
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
import ttl_cache
import async_tasks
from services.agent_engine import agent_engine, AgentStatus, StepStatus
import services.agent_tools  # 触发工具注册
import request_logger
import security
import performance_middleware
import compression_middleware
import system_metrics
import alerting
import backup_scheduler
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
from routes.ai import bp as ai_bp
from routes.plugins import bp as plugins_bp
from routes.knowledge_base import kb_bp
from routes.project_assistant import create_project_blueprint

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
APP_VERSION = '9.0.0-dev'
_app_start_time = __import__('time').time()

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
Compress(app)  # 静态文件由WhiteNoise在WSGI层处理，不会到达Flask-Compress
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

# 性能优化：注册 gzip 响应压缩中间件
# compression_middleware.register_compression_middleware(app) # 禁用，与Flask-Compress冲突

# 配置 - Railway等云平台使用 /tmp 作为可写目录
if os.environ.get('RAILWAY_STATIC_URL') or os.environ.get('PORT'):
    _runtime_dir = '/tmp/toolbox'
else:
    _runtime_dir = base_dir

app.config['UPLOAD_FOLDER'] = os.path.join(_runtime_dir, 'uploads')
app.config['PDF_FOLDER'] = os.path.join(_runtime_dir, 'pdfs')
app.config['AI_CONFIG_FILE'] = os.path.join(_runtime_dir, 'ai_config.json')
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB - 大文件(含截图的Excel/CR CSV)上传限制

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
_PUBLIC_EXACT_PATHS = frozenset({'/login', '/health', '/favicon.ico', '/privacy'})
_PUBLIC_PREFIX_PATHS = (
    '/static/', '/assets/', '/auth/', '/api/merit', '/api/user/preferences',
    '/api/upload-audio', '/api/transcription-status', '/api/ai-models',
    '/api/ai-config', '/api/ai-test', '/api/ai-chat', '/api/test-report-ai-stream',
    '/api/excel-analyze-ai-stream', '/api/generate-minutes-stream',
    '/api/weekly-report-stream', '/api/translate', '/api/translate/stream',
    '/api/notes/sync', '/api/docs', '/api/upload-init', '/api/upload-chunk',
    '/api/upload-complete', '/ws/', '/share/',
)

@app.before_request
def require_login():
    """P1优化：统一前置中间件（登录+游客+安全+限流+日志，5合1）"""
    path = request.path
    _maybe_cleanup()
    request_logger.before_request_log()
    is_public = path in _PUBLIC_EXACT_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIX_PATHS)

    if not is_public and not session.get('user_id') and not auth.ALLOW_GUEST:
        session['next_url'] = path if (path != '/' and not path.startswith('/api/')) else '/'
        if path.startswith('/api/'):
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        return redirect(url_for('login_page'))

    user = auth.get_current_user()
    if user:
        g.user = user
    elif not is_public and not auth.is_guest_allowed(path):
        if path.startswith('/api/'):
            return jsonify({'error': '请先登录', 'need_login': True}), 401
        return redirect('/login')

    if session.get('user_id') and auth.check_session_timeout():
        token = session.get('session_token')
        if token: db.delete_user_session(token)
        uid = session.get('user_id')
        db.add_audit_log(uid, 'session_timeout', target_type='user', target_id=uid,
                         ip=request.remote_addr or '', user_agent=request.headers.get('User-Agent', ''),
                         details='会话空闲超时自动登出')
        session.clear()
        if path.startswith('/api/'):
            return jsonify({'error': '会话已超时，请重新登录', 'need_login': True}), 401
        return redirect(url_for('login_page'))

    csrf_result = security.csrf_protect()
    if csrf_result is not None:
        return csrf_result
    return rate_limiter.check_rate_limit()


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


@app.after_request
def record_for_alerting(response):
    """记录请求指标供告警系统使用（错误率、延迟统计）"""
    try:
        start = getattr(g, '_perf_start_time', None)
        if start is not None:
            duration_ms = (time.perf_counter() - start) * 1000
        else:
            duration_ms = 0
        alerting.record_request(response.status_code, duration_ms)
    except Exception:
        pass
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
@app.route('/agent')
def agent_page():
    """AI Agent 2.0 页面"""
    return render_template('agent.html')


@app.route('/health')
def health_check():
    """健康检查端点 — 无需认证，返回应用状态详情"""
    import os, time, psutil
    try:
        db_status = 'ok'
        try:
            if hasattr(db, 'check_db'):
                db.check_db()
            else:
                with db.contextmanager() as conn:
                    conn.execute('SELECT 1').fetchone()
        except Exception:
            db_status = 'error'
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        return jsonify({
            'status': 'ok',
            'service': 'potential-tools',
            'version': APP_VERSION,
            'uptime_seconds': int(time.time() - _app_start_time),
            'database': db_status,
            'memory_mb': round(mem_info.rss / 1024 / 1024, 1),
            'cpu_percent': process.cpu_percent(interval=0.1),
            'cache_entries': len(ttl_cache._cache) if 'ttl_cache' in dir() else 0,
            'timestamp': int(time.time())
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'service': 'potential-tools', 'error': str(e)}), 500


# ==================== 异步任务 API ====================
@app.route('/api/async/status/<task_id>')
def async_task_status(task_id):
    """查询异步任务状态"""
    status = async_tasks.get_task_status(task_id)
    if not status:
        return jsonify({'error': '任务不存在'}), 404
    return jsonify(status)


@app.route('/api/async/result/<task_id>')
def async_task_result(task_id):
    """获取异步任务结果（支持等待 timeout 秒）"""
    timeout = float(request.args.get('timeout', 0))
    try:
        result = async_tasks.get_task_result(task_id, timeout=timeout)
        status = async_tasks.get_task_status(task_id)
        return jsonify({'status': status['status'] if status else 'unknown', 'result': result})
    except Exception as e:
        return jsonify({'status': 'failed', 'error': str(e)}), 500


@app.route('/api/async/stats')
def async_task_stats():
    """获取异步任务队列统计"""
    return jsonify(async_tasks.get_queue_stats())


# ==================== Agent 2.0 API ====================
@app.route('/api/agent/tools')
def agent_list_tools():
    """列出所有可用的Agent工具"""
    from services.agent_engine import tool_registry
    tools = tool_registry.list_tools()
    return jsonify([
        {'name': t.name, 'description': t.description, 'category': t.category,
         'requires_confirmation': t.requires_confirmation, 'parameters': t.parameters}
        for t in tools
    ])


@app.route('/api/agent/run', methods=['POST'])
def agent_run():
    """运行Agent任务（同步执行，返回完整执行结果）"""
    data = request.get_json(force=True, silent=True) or {}
    task = data.get('task', '').strip()
    if not task:
        return jsonify({'error': '请输入任务描述'}), 400

    # 创建执行上下文
    ctx = agent_engine.create_context(task)

    # 任务规划
    steps = agent_engine.plan(ctx)
    if not steps:
        return jsonify({'error': '无法规划任务，请检查任务描述', 'context': ctx.to_dict()}), 400

    # 执行所有步骤
    def on_step(ctx, step):
        pass  # 可以在这里添加进度回调

    ctx = agent_engine.execute_all(ctx, on_step_complete=on_step)

    return jsonify(ctx.to_dict())


@app.route('/api/agent/run_async', methods=['POST'])
def agent_run_async():
    """异步运行Agent任务，返回task_id，用轮询获取结果"""
    data = request.get_json(force=True, silent=True) or {}
    task = data.get('task', '').strip()
    if not task:
        return jsonify({'error': '请输入任务描述'}), 400

    def _run_agent(task_desc):
        ctx = agent_engine.create_context(task_desc)
        agent_engine.plan(ctx)
        agent_engine.execute_all(ctx)
        return ctx.to_dict()

    task_id = async_tasks.submit_task(_run_agent, task)
    return jsonify({'task_id': task_id, 'status': 'pending'})


@app.route('/api/agent/status/<agent_id>')
def agent_status(agent_id):
    """查询Agent执行状态"""
    ctx = agent_engine.contexts.get(agent_id)
    if not ctx:
        return jsonify({'error': 'Agent不存在'}), 404
    return jsonify(ctx.to_dict())


@app.route('/api/agent/confirm/<agent_id>/<int:step_index>', methods=['POST'])
def agent_confirm_step(agent_id, step_index):
    """用户确认/拒绝某个步骤"""
    data = request.get_json(force=True, silent=True) or {}
    confirmed = data.get('confirmed', True)
    ctx = agent_engine.contexts.get(agent_id)
    if not ctx:
        return jsonify({'error': 'Agent不存在'}), 404

    step = agent_engine.confirm_step(ctx, step_index, confirmed)
    if not step:
        return jsonify({'error': '步骤不存在'}), 404

    # 如果还有后续步骤，继续执行
    if step.status in (StepStatus.COMPLETED.value, StepStatus.SKIPPED.value):
        remaining = ctx.steps[step_index + 1:]
        if remaining and ctx.status == AgentStatus.EXECUTING.value:
            for i in range(step_index + 1, len(ctx.steps)):
                s = agent_engine.execute_step(ctx, i)
                if s.status in (StepStatus.NEEDS_CONFIRMATION.value, StepStatus.FAILED.value):
                    break
            if all(s.status == StepStatus.COMPLETED.value for s in ctx.steps):
                ctx.status = AgentStatus.COMPLETED.value
                ctx.completed_at = __import__('time').time()

    return jsonify(ctx.to_dict())


# ==================== Pipeline 临时数据存储（替代 localStorage，突破 5MB 限制）====================
import time as _time
import uuid as _uuid
_PIPELINE_STORE = {}  # {id: {data, expire_at}}
_PIPELINE_TTL = 600  # 10分钟过期

def _cleanup_pipeline():
    """清理过期的临时数据"""
    now = _time.time()
    expired = [k for k, v in _PIPELINE_STORE.items() if v['expire_at'] < now]
    for k in expired:
        del _PIPELINE_STORE[k]

@app.route('/api/pipeline/store', methods=['POST'])
def pipeline_store():
    """存储临时数据，返回 ID。用于跨页面大数据传递（替代 localStorage）"""
    _cleanup_pipeline()
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': '无效数据'}), 400
    pid = _uuid.uuid4().hex[:16]
    _PIPELINE_STORE[pid] = {
        'data': data,
        'expire_at': _time.time() + _PIPELINE_TTL
    }
    return jsonify({'id': pid, 'expires_in': _PIPELINE_TTL})

@app.route('/api/pipeline/get/<pid>')
def pipeline_get(pid):
    """获取临时数据（一次性，获取后删除）"""
    _cleanup_pipeline()
    item = _PIPELINE_STORE.pop(pid, None)
    if not item:
        return jsonify({'error': '数据不存在或已过期'}), 404
    return jsonify(item['data'])


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
_template_cache = {}  # P0待修复：无界缓存
from collections import OrderedDict
_TEMPLATE_CACHE_MAX = 500
_TEMPLATE_CACHE_TTL = 3600
_template_cache = OrderedDict()
def _tc_get(key):
    e = _template_cache.get(key)
    if e is None: return None
    ct, mt, etag, html = e
    if time.time() - ct > _TEMPLATE_CACHE_TTL:
        del _template_cache[key]; return None
    _template_cache.move_to_end(key)
    return (mt, etag, html)
def _tc_set(key, mtime, etag, html):
    if key in _template_cache: _template_cache.move_to_end(key)
    _template_cache[key] = (time.time(), mtime, etag, html)
    while len(_template_cache) > _TEMPLATE_CACHE_MAX:
        _template_cache.popitem(last=False)

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
    cached = _tc_get(cache_key)
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
    _tc_set(cache_key, mtime, etag, html)

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

# v8.0 AI 原生
app.register_blueprint(ai_bp)
app.register_blueprint(plugins_bp)
app.register_blueprint(kb_bp)
app.register_blueprint(create_project_blueprint())

# HLD 生成器
try:
    from routes.hld_generator import bp_hld
    app.register_blueprint(bp_hld)
except ImportError as e:
    logger.warning(f"HLD Blueprint 加载失败: {e}")

logger.info(f"Blueprint 注册完成，应用版本 v{APP_VERSION}")
logger.info(f"静态资源版本: {_STATIC_VERSION}, 生产环境: {_is_production}")


# ==================== 启动后台服务（系统指标采集 + 告警巡检） ====================
try:
    system_metrics.start_collector()
    alerting.start_alerting()
    backup_scheduler.start_scheduler()
    # v8.0: 启动 AI Agent 调度器
    try:
        from services.ai.agent import start_agent_scheduler
        start_agent_scheduler()
        logger.info('AI Agent 调度器已启动')
    except Exception as e:
        logger.warning(f'AI Agent 调度器启动失败: {e}')
    # v8.0: 启动报告推送调度器
    try:
        from services.ai.report_pusher import start_report_scheduler
        start_report_scheduler()
        logger.info('报告推送调度器已启动')
    except Exception as e:
        logger.warning(f'报告推送调度器启动失败: {e}')
    logger.info('系统指标采集、告警巡检和自动备份服务已启动')
except Exception as e:
    logger.warning(f'后台服务启动失败: {e}')


# ==================== 插件初始化 ====================
try:
    from core.plugin import get_plugin_loader
    loader = get_plugin_loader()
    loader.init_app(app)
    plugin_count = loader.load_all_plugins()
    loader.register_routes(app)
    logger.info(f"已加载 {plugin_count} 个插件")
except Exception as e:
    logger.warning(f"插件加载失败: {e}")


# ==================== 应用入口 ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    async_tasks.init_workers(count=4)
    logger.info(f"异步任务框架已启动，4个工作线程")
    logger.info(f"启动 Potential-tools v{APP_VERSION}，端口: {port}")

    # 后台预热知识库模型（embedding + reranker），避免首次问答长时间加载超时
    def _warmup_kb():
        try:
            import threading as _th
            def _do():
                try:
                    import time as _t
                    _t.sleep(3)
                    from services.ai.knowledge_base import (
                        get_knowledge_base, get_embedding_func, get_rerank_model)
                    get_embedding_func()      # 预热embedding模型
                    get_rerank_model()        # 预热reranker模型
                    kb = get_knowledge_base(1)
                    kb.query('项目计划排期成员名单', top_k=3)  # 触发完整检索链路
                    logger.info("知识库模型预热完成(embedding+reranker)")
                except Exception as e:
                    logger.warning(f"知识库预热失败(可忽略): {e}")
            _th.Thread(target=_do, daemon=True).start()
        except Exception:
            pass
    _warmup_kb()

    # 启动项目状态定时自动刷新（每天 12:00 / 18:00 / 00:00）
    try:
        from services.pa_scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning(f'项目状态自动刷新启动失败(可忽略): {e}')

    # Windows 虚拟环境下 Werkzeug reloader 子进程会丢失 venv 的 site-packages（导致 playwright 等依赖找不到），
    # 因此本地开发保留 debug 错误页但关闭自动重载；生产环境用 WSGI 服务器
    app.run(host='0.0.0.0', port=port, debug=not _is_production, use_reloader=False)
