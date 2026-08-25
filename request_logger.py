"""
结构化请求日志 — 记录每个 HTTP 请求的详细信息

输出 JSON 格式日志，包含：
- timestamp, method, path, status_code, response_time_ms
- user_id, ip, user_agent
- request_size, response_size
"""
import time
import logging
import json
from flask import request, g

logger = logging.getLogger('request_logger')

# 不记录日志的路径前缀
_SKIP_PREFIXES = (
    '/static/',
    '/favicon.ico',
    '/manifest.json',
    '/sw.js',
    '/health',
)

# 请求开始时间存储键
_REQ_START_KEY = '_req_start_time'


def before_request_log():
    """在 before_request 中记录请求开始时间"""
    g._req_start = time.time()


def after_request_log(response):
    """在 after_request 中记录请求日志"""
    path = request.path

    # 跳过静态资源
    if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return response

    start = getattr(g, '_req_start', None)
    if start is None:
        return response

    duration_ms = round((time.time() - start) * 1000, 2)

    # 获取用户信息
    user = getattr(g, 'user', None)
    user_id = user.get('id') if user else None

    # 获取客户端 IP
    ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
    if not ip:
        ip = request.headers.get('X-Real-IP', '').strip()
    if not ip:
        ip = request.remote_addr or '-'

    # 构建日志条目
    log_entry = {
        'method': request.method,
        'path': path,
        'status': response.status_code,
        'duration_ms': duration_ms,
        'ip': ip,
        'user_id': user_id,
    }

    # 慢请求标记（>3秒）
    if duration_ms > 3000:
        log_entry['slow'] = True
        logger.warning(json.dumps(log_entry, ensure_ascii=False))
    # 错误请求标记
    elif response.status_code >= 500:
        log_entry['error'] = True
        logger.error(json.dumps(log_entry, ensure_ascii=False))
    elif response.status_code >= 400:
        log_entry['client_error'] = True
        logger.warning(json.dumps(log_entry, ensure_ascii=False))
    else:
        logger.info(json.dumps(log_entry, ensure_ascii=False))

    # 异步记录用户活动到数据库（仅记录有 tool_id 的路径）
    if user_id:
        try:
            import db as _db
            tool_id, tool_name = _db.resolve_tool_id(path)
            if tool_id:
                action = 'api_call' if path.startswith('/api/') else 'view'
                _db.log_user_activity(
                    user_id=user_id,
                    tool_id=tool_id,
                    tool_name=tool_name,
                    action=action,
                    path=path,
                    method=request.method,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    ip=ip,
                )
        except Exception:
            pass  # 活动记录失败不影响请求

    return response
