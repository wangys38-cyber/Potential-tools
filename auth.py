"""
认证模块 - 飞书OAuth + Google OAuth

设计原则：
1. 用户信息（name/email/avatar/provider）直接存入 session，避免每次请求都查数据库
2. session 持久化（7天有效期），关闭浏览器不丢失
3. 数据库仅在登录/退出时操作，不影响日常请求性能
"""
import os
import json
import secrets
import logging
import requests
from urllib.parse import urlencode
from flask import session, redirect, request, url_for, jsonify
import db

logger = logging.getLogger(__name__)

# ==================== 配置加载 ====================

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config_oauth.json')
_RUNTIME_DIR = os.environ.get('DB_DIR', '/tmp/toolbox')
_RUNTIME_CONFIG = os.path.join(_RUNTIME_DIR, 'config_oauth.json')


def _load_config():
    """加载OAuth配置，优先运行时目录"""
    for path in [_RUNTIME_CONFIG, _CONFIG_PATH]:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


_config = _load_config()

# 安全：Session Secret — 如果未配置，生成随机密钥并警告
_default_secret = _config.get('session_secret', '')
SESSION_SECRET = os.environ.get('SESSION_SECRET', _default_secret)
if not SESSION_SECRET or SESSION_SECRET == 'default_secret_change_me':
    import secrets as _secrets
    SESSION_SECRET = _secrets.token_hex(32)
    import warnings
    warnings.warn(
        "SESSION_SECRET 未配置！已生成临时随机密钥，但重启后所有用户会话将失效。"
        "请在环境变量中设置 SESSION_SECRET。",
        stacklevel=2
    )
ALLOW_GUEST = os.environ.get('ALLOW_GUEST', 'true').lower() in ('1', 'true', 'yes') or _config.get('allow_guest', True)

# 访客白名单：仅允许访问这些路径（CR分析功能 + 登录/静态资源/健康检查）
GUEST_ALLOWED_PATHS = [
    '/',                    # 首页
    '/login',               # 登录页
    '/excel-analysis',      # CR分析页面
    '/auth/',               # 认证回调（飞书/Google）
    '/static/',             # 静态资源
    '/health',              # 健康检查
    '/api/excel-analyze',   # CR分析API（前缀匹配）
    '/api/task-status',     # 分析任务状态
    '/api/upload-init',     # 分片上传-初始化
    '/api/upload-chunk',    # 分片上传-上传块
    '/api/upload-complete', # 分片上传-完成
]


def is_guest_allowed(path):
    """检查访客是否允许访问该路径"""
    if not ALLOW_GUEST:
        return False
    for allowed in GUEST_ALLOWED_PATHS:
        if path == allowed or path.startswith(allowed + '/') or path.startswith(allowed + '?'):
            return True
    return False

FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', _config.get('feishu', {}).get('app_id', ''))
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', _config.get('feishu', {}).get('app_secret', ''))
FEISHU_REDIRECT_URI = os.environ.get('FEISHU_REDIRECT_URI', _config.get('feishu', {}).get('redirect_uri', ''))

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', _config.get('google', {}).get('client_id', ''))
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', _config.get('google', {}).get('client_secret', ''))
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', _config.get('google', {}).get('redirect_uri', ''))

WECHAT_APP_ID = os.environ.get('WECHAT_APP_ID', _config.get('wechat', {}).get('app_id', ''))
WECHAT_APP_SECRET = os.environ.get('WECHAT_APP_SECRET', _config.get('wechat', {}).get('app_secret', ''))
WECHAT_REDIRECT_URI = os.environ.get('WECHAT_REDIRECT_URI', _config.get('wechat', {}).get('redirect_uri', ''))


# ==================== 核心认证函数 ====================

def is_configured(provider):
    """检查OAuth提供商是否已配置"""
    if provider == 'feishu':
        return bool(FEISHU_APP_ID and FEISHU_APP_SECRET and 'YOUR_' not in FEISHU_APP_ID and 'FROM_ENV' not in FEISHU_APP_ID)
    elif provider == 'google':
        return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and 'YOUR_' not in GOOGLE_CLIENT_ID and 'FROM_ENV' not in GOOGLE_CLIENT_ID)
    elif provider == 'wechat':
        return bool(WECHAT_APP_ID and WECHAT_APP_SECRET and 'FROM_ENV' not in WECHAT_APP_ID)
    return False


def get_current_user():
    """
    从 session 获取当前登录用户。
    用户信息在登录时一次性写入 session，后续不再查数据库。
    """
    user_id = session.get('user_id')
    if not user_id:
        return None
    # 直接从 session 读取用户信息（登录时已存入）
    return {
        'id': user_id,
        'name': session.get('user_name', ''),
        'email': session.get('user_email', ''),
        'avatar': session.get('user_avatar', ''),
        'provider': session.get('user_provider', ''),
    }


def is_logged_in():
    """检查是否已登录"""
    return session.get('user_id') is not None


def _set_session_user(user_id, name, email, avatar, provider):
    """将用户信息写入 session（登录成功时调用）"""
    session.permanent = True
    session['user_id'] = user_id
    session['user_name'] = name
    session['user_email'] = email
    session['user_avatar'] = avatar
    session['user_provider'] = provider


def login_required(func):
    """登录验证装饰器（已废弃，保留兼容）"""
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            if ALLOW_GUEST:
                return func(*args, **kwargs)
            return redirect(url_for('login_page'))
        return func(*args, **kwargs)
    return wrapper


# ==================== 飞书 OAuth ====================

def feishu_login():
    """发起飞书OAuth登录"""
    if not is_configured('feishu'):
        return jsonify({'error': '飞书登录未配置'}), 503

    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state

    # 保存用户原始请求路径，登录后跳回
    next_url = request.args.get('next') or session.get('next_url') or '/'
    session['next_url'] = next_url

    params = urlencode({
        'app_id': FEISHU_APP_ID,
        'redirect_uri': FEISHU_REDIRECT_URI,
        'state': state,
    })
    auth_url = f"https://open.feishu.cn/open-apis/authen/v1/index?{params}"
    return redirect(auth_url)


def feishu_callback():
    """飞书OAuth回调"""
    code = request.args.get('code')
    state = request.args.get('state', '')

    # 验证state
    if state != session.get('oauth_state'):
        return redirect(url_for('login_page', error='state_mismatch'))
    session.pop('oauth_state', None)

    if not code:
        return redirect(url_for('login_page', error='no_code'))

    try:
        # Step 1: 获取 app_access_token
        token_resp = requests.post(
            'https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal',
            json={'app_id': FEISHU_APP_ID, 'app_secret': FEISHU_APP_SECRET},
            timeout=10
        )
        token_data = token_resp.json()
        app_access_token = token_data.get('app_access_token')
        if not app_access_token:
            logger.error(f"飞书获取app_access_token失败: {token_data}")
            return redirect(url_for('login_page', error='token_failed'))

        # Step 2: 获取用户 access_token
        user_token_resp = requests.post(
            'https://open.feishu.cn/open-apis/authen/v1/oidc/access_token',
            headers={'Authorization': f'Bearer {app_access_token}'},
            json={'grant_type': 'authorization_code', 'code': code},
            timeout=10
        )
        user_token_data = user_token_resp.json().get('data', {})
        access_token = user_token_data.get('access_token')
        if not access_token:
            logger.error(f"飞书获取用户token失败: {user_token_resp.json()}")
            return redirect(url_for('login_page', error='user_token_failed'))

        # Step 3: 获取用户信息
        user_resp = requests.get(
            'https://open.feishu.cn/open-apis/authen/v1/user_info',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10
        )
        user_data = user_resp.json().get('data', {})

        name = user_data.get('name', '飞书用户')
        email = user_data.get('email', '')
        avatar = user_data.get('avatar_url', '')
        open_id = user_data.get('open_id', '')

        if not open_id:
            logger.error(f"飞书获取用户信息失败: {user_data}")
            return redirect(url_for('login_page', error='user_info_failed'))

        # 创建或更新用户记录（数据库可能因容器回收而丢失，所以用 try 容错）
        try:
            user_id = db.upsert_user('feishu', open_id, name, email, avatar)
        except Exception as e:
            logger.warning(f"数据库写入用户失败（不影响登录）: {e}")
            # 安全：使用 hashlib 生成确定性 user_id（hash() 受 PYTHONHASHSEED 影响不稳定）
            import hashlib
            user_id = int(hashlib.md5(f"feishu:{open_id}".encode()).hexdigest()[:8], 16)

        # 用户信息写入 session — 后续不再查数据库
        _set_session_user(user_id, name, email, avatar, 'feishu')

        logger.info(f"飞书用户登录成功: {name} (ID: {user_id})")
        next_url = session.pop('next_url', None) or '/'
        return redirect(next_url)

    except Exception as e:
        logger.error(f"飞书OAuth回调异常: {e}")
        return redirect(url_for('login_page', error='callback_exception'))


# ==================== Google OAuth ====================

def google_login():
    """发起Google OAuth登录"""
    if not is_configured('google'):
        return jsonify({'error': 'Google登录未配置'}), 503

    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state

    next_url = request.args.get('next') or session.get('next_url') or '/'
    session['next_url'] = next_url

    params = urlencode({
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': GOOGLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
    })
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    return redirect(auth_url)


def google_callback():
    """Google OAuth回调"""
    code = request.args.get('code')
    state = request.args.get('state', '')
    error = request.args.get('error', '')

    if error:
        return redirect(url_for('login_page', error=error))

    if state != session.get('oauth_state'):
        return redirect(url_for('login_page', error='state_mismatch'))
    session.pop('oauth_state', None)

    if not code:
        return redirect(url_for('login_page', error='no_code'))

    try:
        token_resp = requests.post(
            'https://oauth2.googleapis.com/token',
            data={
                'code': code,
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
                'redirect_uri': GOOGLE_REDIRECT_URI,
                'grant_type': 'authorization_code'
            },
            timeout=10
        )
        token_data = token_resp.json()
        access_token = token_data.get('access_token')
        if not access_token:
            logger.error(f"Google获取token失败: {token_data}")
            return redirect(url_for('login_page', error='token_failed'))

        user_resp = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10
        )
        user_data = user_resp.json()

        google_id = user_data.get('id', '')
        name = user_data.get('name', 'Google用户')
        email = user_data.get('email', '')
        avatar = user_data.get('picture', '')

        if not google_id:
            logger.error(f"Google获取用户信息失败: {user_data}")
            return redirect(url_for('login_page', error='user_info_failed'))

        try:
            user_id = db.upsert_user('google', google_id, name, email, avatar)
        except Exception as e:
            logger.warning(f"数据库写入用户失败（不影响登录）: {e}")
            # 安全：使用 hashlib 生成确定性 user_id
            import hashlib
            user_id = int(hashlib.md5(f"google:{google_id}".encode()).hexdigest()[:8], 16)

        _set_session_user(user_id, name, email, avatar, 'google')

        logger.info(f"Google用户登录成功: {name} (ID: {user_id})")
        next_url = session.pop('next_url', None) or '/'
        return redirect(next_url)

    except Exception as e:
        logger.error(f"Google OAuth回调异常: {e}")
        return redirect(url_for('login_page', error='callback_exception'))


# ==================== 退出登录 ====================

def logout():
    """退出登录 — 清除所有 session 数据"""
    user = get_current_user()
    if user:
        logger.info(f"用户退出登录: {user.get('name')} (ID: {user.get('id')})")
    session.clear()
    return redirect(url_for('login_page'))


# ==================== v9.0 账号密码注册/登录 API ====================

def register():
    """POST /api/auth/register — 账号密码注册"""
    data = request.get_json(silent=True) or request.form
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400
    if len(password) < 6:
        return jsonify({'error': '密码长度至少 6 位'}), 400

    # 唯一性校验
    if db.get_user_by_username(username):
        return jsonify({'error': '用户名已存在'}), 409
    if email and db.get_user_by_email(email):
        return jsonify({'error': '邮箱已被注册'}), 409

    user_id = db.create_user_with_password(username, email, password)
    if not user_id:
        return jsonify({'error': '注册失败，请重试'}), 500

    logger.info(f"新用户注册成功: {username} (ID: {user_id})")
    return jsonify({
        'status': 'success',
        'user': {'id': user_id, 'name': username, 'email': email}
    }), 201


def login():
    """POST /api/auth/login — 账号密码登录"""
    data = request.get_json(silent=True) or request.form
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400

    user = db.verify_user_password(username, password)
    if not user:
        # 区分用户不存在和密码错误
        existing = db.get_user_by_username(username) or (db.get_user_by_email(username) if '@' in username else None)
        if not existing:
            return jsonify({'error': '用户不存在'}), 404
        return jsonify({'error': '密码错误'}), 401

    # 更新最后登录时间
    try:
        import time as _time
        with db.engine.begin() as conn:
            conn.execute(
                db.text("UPDATE users SET last_login = :last_login WHERE id = :id"),
                {'last_login': _time.time(), 'id': user['id']}
            )
    except Exception:
        pass

    _set_session_user(
        user_id=user['id'],
        name=user.get('name') or user.get('username') or '',
        email=user.get('email') or '',
        avatar=user.get('avatar') or '',
        provider=user.get('provider') or 'local',
    )
    logger.info(f"用户登录成功: {user.get('name') or username} (ID: {user['id']})")
    return jsonify({
        'status': 'success',
        'user': {'id': user['id'], 'name': user.get('name') or username, 'email': user.get('email') or ''}
    })


def logout_api():
    """POST /api/auth/logout — API 退出登录"""
    user = get_current_user()
    if user:
        logger.info(f"用户退出登录: {user.get('name')} (ID: {user.get('id')})")
    session.clear()
    return jsonify({'status': 'success'})


def wechat_login():
    """发起微信OAuth登录（网站应用扫码授权）"""
    if not is_configured('wechat'):
        return jsonify({'error': '微信登录未配置'}), 503

    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state

    # 保存用户原始请求路径，登录后跳回
    next_url = request.args.get('next') or session.get('next_url') or '/'
    session['next_url'] = next_url

    from urllib.parse import quote
    auth_url = (
        f"https://open.weixin.qq.com/connect/qrconnect"
        f"?appid={WECHAT_APP_ID}"
        f"&redirect_uri={quote(WECHAT_REDIRECT_URI, safe='')}"
        f"&response_type=code"
        f"&scope=snsapi_login"
        f"&state={state}"
        f"#wechat_redirect"
    )
    return redirect(auth_url)


def wechat_callback():
    """微信OAuth回调"""
    code = request.args.get('code')
    state = request.args.get('state', '')

    # 验证state
    if state != session.get('oauth_state'):
        return redirect(url_for('login_page', error='state_mismatch'))
    session.pop('oauth_state', None)

    if not code:
        return redirect(url_for('login_page', error='no_code'))

    try:
        # Step 1: 用 code 换取 access_token
        token_resp = requests.get(
            'https://api.weixin.qq.com/sns/oauth2/access_token',
            params={
                'appid': WECHAT_APP_ID,
                'secret': WECHAT_APP_SECRET,
                'code': code,
                'grant_type': 'authorization_code',
            },
            timeout=10
        )
        token_data = token_resp.json()
        access_token = token_data.get('access_token')
        openid = token_data.get('openid')
        unionid = token_data.get('unionid', '')

        if not access_token or not openid:
            logger.error(f"微信获取access_token失败: {token_data}")
            return redirect(url_for('login_page', error='token_failed'))

        # Step 2: 用 access_token + openid 获取用户信息
        user_resp = requests.get(
            'https://api.weixin.qq.com/sns/userinfo',
            params={
                'access_token': access_token,
                'openid': openid,
            },
            timeout=10
        )
        # 微信返回可能是 GBK 编码，手动处理
        user_resp.encoding = 'utf-8'
        user_data = user_resp.json()

        nickname = user_data.get('nickname', '微信用户')
        headimgurl = user_data.get('headimgurl', '')
        # sex: 1=男, 2=女, 0=未知
        sex = user_data.get('sex', 0)
        country = user_data.get('country', '')
        province = user_data.get('province', '')
        city = user_data.get('city', '')

        # 优先使用 unionid（跨应用唯一），其次 openid
        provider_uid = unionid or openid

        # 创建或更新用户记录
        try:
            user_id = db.upsert_user('wechat', provider_uid, nickname, '', headimgurl)
        except Exception as e:
            logger.warning(f"数据库写入用户失败（不影响登录）: {e}")
            import hashlib
            user_id = int(hashlib.md5(f"wechat:{provider_uid}".encode()).hexdigest()[:8], 16)

        # 用户信息写入 session
        _set_session_user(user_id, nickname, '', headimgurl, 'wechat')

        logger.info(f"微信用户登录成功: {nickname} (ID: {user_id})")
        next_url = session.pop('next_url', None) or '/'
        return redirect(next_url)

    except Exception as e:
        logger.error(f"微信OAuth回调异常: {e}")
        return redirect(url_for('login_page', error='callback_exception'))
