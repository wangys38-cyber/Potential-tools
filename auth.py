"""
认证模块 - 飞书OAuth + Google OAuth
"""
import os
import json
import hashlib
import secrets
import time
import logging
import requests
from flask import session, redirect, request, url_for, jsonify
import db

logger = logging.getLogger(__name__)

# 加载OAuth配置
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config_oauth.json')

# 运行时可写目录
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
ALLOW_GUEST = _config.get('allow_guest', True)

# 优先使用环境变量（安全），回退到配置文件
FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', _config.get('feishu', {}).get('app_id', ''))
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', _config.get('feishu', {}).get('app_secret', ''))
FEISHU_REDIRECT_URI = os.environ.get('FEISHU_REDIRECT_URI', _config.get('feishu', {}).get('redirect_uri', ''))

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', _config.get('google', {}).get('client_id', ''))
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', _config.get('google', {}).get('client_secret', ''))
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', _config.get('google', {}).get('redirect_uri', ''))


def is_configured(provider):
    """检查OAuth提供商是否已配置"""
    if provider == 'feishu':
        return bool(FEISHU_APP_ID and FEISHU_APP_SECRET and 'YOUR_' not in FEISHU_APP_ID)
    elif provider == 'google':
        return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and 'YOUR_' not in GOOGLE_CLIENT_ID)
    return False


def get_current_user():
    """从session获取当前登录用户"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    user = db.get_user_by_id(user_id)
    if not user:
        session.pop('user_id', None)
        return None
    return user


def is_logged_in():
    """检查是否已登录"""
    return get_current_user() is not None


def login_required(func):
    """登录验证装饰器"""
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
        return jsonify({'error': '飞书登录未配置，请在 config_oauth.json 中设置 app_id 和 app_secret'}), 503

    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state

    auth_url = (
        f"https://open.feishu.cn/open-apis/authen/v1/index"
        f"?app_id={FEISHU_APP_ID}"
        f"&redirect_uri={FEISHU_REDIRECT_URI}"
        f"&state={state}"
    )
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
            json={
                'app_id': FEISHU_APP_ID,
                'app_secret': FEISHU_APP_SECRET
            },
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

        # 创建或更新用户
        user_id = db.upsert_user('feishu', open_id, name, email, avatar)
        session['user_id'] = user_id
        session['provider'] = 'feishu'

        logger.info(f"飞书用户登录成功: {name} (ID: {user_id})")
        return redirect(url_for('index'))

    except Exception as e:
        logger.error(f"飞书OAuth回调异常: {e}")
        return redirect(url_for('login_page', error='callback_exception'))


# ==================== Google OAuth ====================

def google_login():
    """发起Google OAuth登录"""
    if not is_configured('google'):
        return jsonify({'error': 'Google登录未配置，请在 config_oauth.json 中设置 client_id 和 client_secret'}), 503

    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state

    scope = 'openid email profile'
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&state={state}"
    )
    return redirect(auth_url)


def google_callback():
    """Google OAuth回调"""
    code = request.args.get('code')
    state = request.args.get('state', '')
    error = request.args.get('error', '')

    if error:
        return redirect(url_for('login_page', error=error))

    # 验证state
    if state != session.get('oauth_state'):
        return redirect(url_for('login_page', error='state_mismatch'))
    session.pop('oauth_state', None)

    if not code:
        return redirect(url_for('login_page', error='no_code'))

    try:
        # Step 1: 用 code 换取 access_token
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

        # Step 2: 获取用户信息
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

        # 创建或更新用户
        user_id = db.upsert_user('google', google_id, name, email, avatar)
        session['user_id'] = user_id
        session['provider'] = 'google'

        logger.info(f"Google用户登录成功: {name} (ID: {user_id})")
        return redirect(url_for('index'))

    except Exception as e:
        logger.error(f"Google OAuth回调异常: {e}")
        return redirect(url_for('login_page', error='callback_exception'))


def logout():
    """退出登录"""
    user = get_current_user()
    if user:
        logger.info(f"用户退出登录: {user.get('name')} (ID: {user.get('id')})")
    session.clear()
    return redirect(url_for('index'))
