"""
加密工具模块 — 用于敏感数据（如 API Key）的加密存储

使用 Fernet 对称加密（AES-128-CBC + HMAC-SHA256）
密钥从环境变量 ENCRYPTION_KEY 读取，未设置时自动生成并警告
"""
import os
import base64
import hashlib
import logging

logger = logging.getLogger(__name__)

# 加密前缀，用于标识已加密的值
_ENCRYPTED_PREFIX = 'enc:'

# 从环境变量获取主密钥，或使用默认值（仅开发环境）
_MASTER_KEY = os.environ.get('ENCRYPTION_KEY', '')

if not _MASTER_KEY:
    # 开发环境自动生成固定密钥（基于机器信息），生产环境必须设置 ENCRYPTION_KEY
    import platform
    _fallback = f'potential-tools:{platform.node()}'
    _MASTER_KEY = _fallback
    logger.warning(
        "ENCRYPTION_KEY 未设置，使用回退密钥（仅限开发环境）。"
        "生产环境请设置环境变量 ENCRYPTION_KEY 为一个随机字符串（>=32字符）。"
    )


def _get_fernet():
    """获取 Fernet 实例"""
    from cryptography.fernet import Fernet
    # 从主密钥派生 Fernet 兼容的 key（32 bytes → base64）
    key = hashlib.sha256(_MASTER_KEY.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext):
    """加密明文

    Args:
        plaintext: 待加密的字符串

    Returns:
        str: 加密后的字符串（格式 'enc:<base64>'），若输入为空则返回空字符串
    """
    if not plaintext:
        return ''
    try:
        f = _get_fernet()
        encrypted = f.encrypt(plaintext.encode('utf-8'))
        return f'{_ENCRYPTED_PREFIX}{encrypted.decode("utf-8")}'
    except Exception as e:
        logger.error(f"加密失败: {e}")
        # 加密失败时返回原始值，避免阻断业务流程
        return plaintext


def decrypt(ciphertext):
    """解密密文

    Args:
        ciphertext: 加密的字符串（格式 'enc:<base64>'）或明文

    Returns:
        str: 解密后的明文。若输入不是加密格式则原样返回（向后兼容）
    """
    if not ciphertext:
        return ''
    if not ciphertext.startswith(_ENCRYPTED_PREFIX):
        # 旧版明文数据，直接返回（向后兼容）
        return ciphertext
    try:
        f = _get_fernet()
        encrypted = ciphertext[len(_ENCRYPTED_PREFIX):].encode('utf-8')
        return f.decrypt(encrypted).decode('utf-8')
    except Exception as e:
        logger.error(f"解密失败: {e}")
        # 解密失败返回空字符串，避免泄露
        return ''


def is_encrypted(value):
    """检查值是否已加密"""
    return bool(value) and value.startswith(_ENCRYPTED_PREFIX)
