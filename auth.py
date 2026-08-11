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

SESSION_SECRET = os.environ.get('SESSION_SECRET', _config.get('session_secret', 'default_secret_change_me'))
ALLOW_GUEST = os.environ.get('ALLOW_GUEST', '').lower() in ('1', 'true', 'yes') or _config.get('allow_guest', False)

FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', _config.get('feishu', {}).get('app_id', ''))
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', _config.get('feishu', {}).get('app_secret', ''))
FEISHU_REDIRECT_URI = os.environ.get('FEISHU_REDIRECT_URI', _config.get('feishu', {}).get('redirect_uri', ''))

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', _config.get('google', {}).get('client_id', ''))
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', _config.get('google', {}).get('client_secret', ''))
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', _config.get('google', {}).get('redirect_uri', ''))


# ==================== 核心认证函数 ====================

def is_configured(provider):
    """检查OAuth提供商是否已配置"""
    if provider == 'feishu':
        return bool(FEISHU_APP_ID and FEISHU_APP_SECRET and 'YOUR_' not in FEISHU_APP_ID and 'FROM_ENV' not in FEISHU_APP_ID)
    elif provider == 'google':
        return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and 'YOUR_' not in GOOGLE_CLIENT_ID and 'FROM_ENV' not in GOOGLE_CLIENT_ID)
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
            # 用 open_id 的哈希作为备用 user_id
            user_id = abs(hash(f"feishu:{open_id}")) % (2**31)

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
            user_id = abs(hash(f"google:{google_id}")) % (2**31)

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
