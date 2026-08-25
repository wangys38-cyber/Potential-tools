"""
安全模块 - CSRF 防护、输入校验、文件上传安全

设计原则：
1. CSRF Token 存在 Session 中，前端从 Meta 标签读取，API 请求带 X-CSRF-Token Header
2. 登录页和公开 API 豁免 CSRF 校验
3. 所有入参校验类型/长度/格式
4. 文件上传校验扩展名+MIME+文件头魔数
"""
import os
import re
import secrets
import logging
from flask import session, request, jsonify, g

logger = logging.getLogger(__name__)

# ==================== CSRF 防护 ====================

CSRF_HEADER = 'X-CSRF-Token'
CSRF_SESSION_KEY = '_csrf_token'

# 豁免 CSRF 校验的路径前缀（登录页、公开 API、健康检查）
_CSRF_EXEMPT_PREFIXES = (
    '/login',
    '/auth/',
    '/api/auth/login',
    '/api/auth/register',
    '/health',
    '/static/',
    '/assets/',
    '/share/',
    '/ws/',
    '/api/merit',
    '/api/user/preferences',
)

# 需要豁免的具体路径（精确匹配）
_CSRF_EXEMPT_PATHS = {
    '/api/ai-models',
    '/api/ai-config',
}


def generate_csrf_token():
    """生成 CSRF Token 并存入 Session（幂等：已存在则返回现有）"""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def get_csrf_token():
    """获取当前 CSRF Token（不生成）"""
    return session.get(CSRF_SESSION_KEY, '')


def _is_csrf_exempt(path):
    """检查路径是否豁免 CSRF 校验"""
    if path in _CSRF_EXEMPT_PATHS:
        return True
    for prefix in _CSRF_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def csrf_protect():
    """CSRF 防护中间件（在 before_request 中调用）

    对 POST/PUT/DELETE 请求校验 X-CSRF-Token Header。
    登录页和公开 API 豁免。
    """
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None

    path = request.path
    if _is_csrf_exempt(path):
        return None

    # 游客模式下不强制 CSRF（避免影响公开功能）
    if not session.get('user_id'):
        return None

    token = request.headers.get(CSRF_HEADER, '')
    session_token = session.get(CSRF_SESSION_KEY, '')

    if not token or not session_token or token != session_token:
        logger.warning(f"CSRF 校验失败: path={path}, ip={request.remote_addr}")
        return jsonify({'error': 'CSRF 校验失败，请刷新页面重试'}), 403

    return None


# ==================== 输入校验 ====================

# 用户名：3-32位，字母数字下划线中文
_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_\u4e00-\u9fa5]{3,32}$')
# 邮箱格式
_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
# URL 格式（http/https）
_URL_RE = re.compile(r'^https?://[^\s/$.?#].[^\s]*$', re.IGNORECASE)


def validate_username(username):
    """校验用户名，返回 (is_valid, error_message)"""
    if not username or not username.strip():
        return False, '用户名不能为空'
    username = username.strip()
    if len(username) < 3:
        return False, '用户名至少 3 个字符'
    if len(username) > 32:
        return False, '用户名最多 32 个字符'
    if not _USERNAME_RE.match(username):
        return False, '用户名只能包含字母、数字、下划线和中文'
    return True, ''


def validate_email(email):
    """校验邮箱（可选），返回 (is_valid, error_message)"""
    if not email or not email.strip():
        return True, ''  # 邮箱可选
    email = email.strip().lower()
    if len(email) > 254:
        return False, '邮箱长度超出限制'
    if not _EMAIL_RE.match(email):
        return False, '邮箱格式不正确'
    return True, ''


def validate_password_strength(password):
    """校验密码强度，返回 (is_valid, strength_level, message)

    strength_level: 'weak' | 'medium' | 'strong'
    规则：至少8位，必须包含字母和数字
    """
    if not password:
        return False, 'weak', '密码不能为空'
    if len(password) < 8:
        return False, 'weak', '密码至少 8 位'
    if len(password) > 128:
        return False, 'weak', '密码最多 128 位'
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not has_letter or not has_digit:
        return False, 'weak', '密码必须包含字母和数字'

    # 评估强度等级
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_special = any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?~' for c in password)

    if len(password) >= 12 and has_upper and has_lower and has_digit and has_special:
        return True, 'strong', ''
    if len(password) >= 10 and (has_upper or has_lower) and has_digit and has_special:
        return True, 'medium', ''
    return True, 'medium', ''


def sanitize_string(value, max_length=10000):
    """清理字符串输入：去除首尾空白、限制长度、过滤控制字符"""
    if value is None:
        return ''
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if len(value) > max_length:
        value = value[:max_length]
    # 过滤 NULL 字节和其他控制字符（保留换行和制表符）
    value = ''.join(c for c in value if c == '\n' or c == '\t' or ord(c) >= 32)
    return value


def validate_url(url):
    """校验 URL 格式，返回 (is_valid, normalized_url)"""
    if not url or not url.strip():
        return True, ''
    url = url.strip()
    if len(url) > 2048:
        return False, ''
    if not _URL_RE.match(url):
        return False, ''
    return True, url


# ==================== 文件上传安全 ====================

# 允许的文件扩展名（小写）
ALLOWED_EXTENSIONS = {
    # 文档
    'xlsx', 'xls', 'csv', 'txt', 'md', 'pdf', 'docx', 'doc',
    # 图片
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg',
    # 音频
    'wav', 'mp3', 'm4a', 'ogg', 'flac',
    # 数据
    'json', 'xml',
}

# 文件头魔数（用于真实文件类型检测）
_FILE_MAGIC_NUMBERS = {
    'png': [b'\x89PNG\r\n\x1a\n'],
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
    'gif': [b'GIF87a', b'GIF89a'],
    'webp': [b'RIFF', b'WEBP'],
    'pdf': [b'%PDF-'],
    'xlsx': [b'PK\x03\x04', b'PK\x05\x06'],
    'xls': [b'\xd0\xcf\x11\xe0'],
    'docx': [b'PK\x03\x04', b'PK\x05\x06'],
    'doc': [b'\xd0\xcf\x11\xe0'],
    'wav': [b'RIFF', b'WAVE'],
    'mp3': [b'ID3', b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'],
    'm4a': [b'\x00\x00\x00', b'ftyp'],
    'ogg': [b'OggS'],
    'flac': [b'fLaC'],
    'zip': [b'PK\x03\x04', b'PK\x05\x06'],
}

# 按类型设置文件大小上限（字节）
FILE_SIZE_LIMITS = {
    'xlsx': 50 * 1024 * 1024,
    'xls': 50 * 1024 * 1024,
    'csv': 50 * 1024 * 1024,
    'txt': 10 * 1024 * 1024,
    'md': 10 * 1024 * 1024,
    'pdf': 50 * 1024 * 1024,
    'docx': 50 * 1024 * 1024,
    'doc': 50 * 1024 * 1024,
    'png': 10 * 1024 * 1024,
    'jpg': 10 * 1024 * 1024,
    'jpeg': 10 * 1024 * 1024,
    'gif': 10 * 1024 * 1024,
    'webp': 10 * 1024 * 1024,
    'svg': 5 * 1024 * 1024,
    'wav': 200 * 1024 * 1024,
    'mp3': 100 * 1024 * 1024,
    'm4a': 100 * 1024 * 1024,
    'ogg': 100 * 1024 * 1024,
    'flac': 200 * 1024 * 1024,
    'json': 10 * 1024 * 1024,
    'xml': 10 * 1024 * 1024,
}

DEFAULT_FILE_SIZE_LIMIT = 50 * 1024 * 1024  # 默认 50MB


def get_file_extension(filename):
    """安全获取文件扩展名（小写）"""
    if not filename:
        return ''
    # 处理路径遍历：只取文件名部分
    filename = os.path.basename(filename)
    if '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def is_allowed_file(filename):
    """检查文件扩展名是否在白名单中"""
    ext = get_file_extension(filename)
    return ext in ALLOWED_EXTENSIONS


def verify_file_magic(file_storage, expected_ext=None):
    """通过文件头魔数验证真实文件类型

    Args:
        file_storage: Flask FileStorage 对象或文件路径
        expected_ext: 期望的扩展名（可选，用于精确匹配）

    Returns:
        (is_valid, detected_type)
    """
    try:
        if hasattr(file_storage, 'read'):
            # Flask FileStorage
            pos = file_storage.tell()
            file_storage.seek(0)
            header = file_storage.read(16)
            file_storage.seek(pos)
        elif isinstance(file_storage, str) and os.path.isfile(file_storage):
            with open(file_storage, 'rb') as f:
                header = f.read(16)
        else:
            return True, None  # 无法检测，放行

        if not header:
            return False, None

        # 文本文件（csv/txt/md/json/xml/svg）不做魔数检测
        text_exts = {'csv', 'txt', 'md', 'json', 'xml', 'svg'}
        if expected_ext and expected_ext in text_exts:
            return True, expected_ext

        detected = None
        for ext, magics in _FILE_MAGIC_NUMBERS.items():
            for magic in magics:
                if header.startswith(magic):
                    detected = ext
                    break
            if detected:
                break

        if expected_ext and detected:
            # 允许 xlsx/docx 检测为 zip（它们本质是 zip 包）
            if expected_ext in ('xlsx', 'docx') and detected == 'zip':
                return True, expected_ext
            if detected == expected_ext:
                return True, detected
            return False, detected

        return True, detected  # 未指定期望类型时，检测到即放行
    except Exception as e:
        logger.debug(f"文件魔数检测失败: {e}")
        return True, None


def sanitize_filename(filename):
    """清理文件名，防止路径遍历和特殊字符"""
    if not filename:
        return 'unnamed'
    # 只取文件名部分
    filename = os.path.basename(filename)
    # 移除路径分隔符和危险字符
    filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', filename)
    # 限制长度
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[:190] + ext
    return filename or 'unnamed'


def validate_upload(file_storage, filename=None):
    """综合校验上传文件：扩展名+大小+魔数

    Returns:
        (is_valid, error_message, sanitized_name)
    """
    if not file_storage:
        return False, '未收到文件', ''

    fname = filename or file_storage.filename
    if not fname:
        return False, '文件名为空', ''

    ext = get_file_extension(fname)
    if not ext:
        return False, '文件缺少扩展名', ''
    if ext not in ALLOWED_EXTENSIONS:
        return False, f'不支持的文件类型: .{ext}', ''

    # 大小校验
    size_limit = FILE_SIZE_LIMITS.get(ext, DEFAULT_FILE_SIZE_LIMIT)
    if hasattr(file_storage, 'content_length') and file_storage.content_length:
        if file_storage.content_length > size_limit:
            return False, f'文件过大，上限 {size_limit // 1024 // 1024}MB', ''

    # 魔数校验
    is_valid, detected = verify_file_magic(file_storage, expected_ext=ext)
    if not is_valid:
        return False, f'文件类型不匹配（声明 .{ext}，实际为 {detected or "未知"}）', ''

    safe_name = sanitize_filename(fname)
    return True, '', safe_name


def safe_join_path(base_dir, filename):
    """安全拼接路径，防止路径遍历

    Returns:
        绝对路径，如果检测到路径遍历返回 None
    """
    if not filename:
        return None
    safe_name = sanitize_filename(filename)
    full_path = os.path.abspath(os.path.join(base_dir, safe_name))
    base_abs = os.path.abspath(base_dir)
    if not full_path.startswith(base_abs + os.sep) and full_path != base_abs:
        return None
    return full_path


# ==================== 路径遍历防护 ====================

def is_safe_path(base_dir, target_path):
    """检查目标路径是否在 base_dir 内（防止路径遍历）"""
    try:
        base_abs = os.path.abspath(base_dir)
        target_abs = os.path.abspath(target_path)
        return target_abs.startswith(base_abs + os.sep) or target_abs == base_abs
    except Exception:
        return False
