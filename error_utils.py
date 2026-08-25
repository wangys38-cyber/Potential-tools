"""
错误处理工具模块 — 防止内部异常信息泄露到客户端

使用方式:
    from error_utils import safe_error
    except Exception as e:
        logger.error(f"操作失败: {e}")
        return jsonify(safe_error(e)), 500
"""
import logging

logger = logging.getLogger(__name__)

# 通用安全错误消息（不泄露内部细节）
_GENERIC_ERROR = '服务器内部错误，请稍后重试'
_BAD_REQUEST = '请求参数有误'


def safe_error(e, custom_message=None):
    """生成安全的错误响应

    完整错误信息记录到日志，返回给客户端的是通用消息。

    Args:
        e: 异常对象
        custom_message: 自定义用户可见消息（可选）

    Returns:
        dict: {'status': 'error', 'error': <安全消息>}
    """
    # 完整异常记录到服务端日志
    logger.error(f"异常: {type(e).__name__}: {e}", exc_info=True)
    # 返回给客户端的是通用安全消息
    return {'status': 'error', 'error': custom_message or _GENERIC_ERROR}
