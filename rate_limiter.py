"""
API 速率限制器 — 滑动窗口算法

设计：
1. 基于内存的滑动窗口计数，无需 Redis 依赖
2. 区分已登录用户（高配额）和访客（低配额）
3. 按 IP + user_id 组合键限流
4. 自动清理过期窗口，防止内存泄漏
5. 返回标准 429 状态码 + Retry-After 头
"""
import time
import threading
import logging
from collections import defaultdict, deque
from flask import request, jsonify, g

logger = logging.getLogger(__name__)

# ==================== 配置 ====================

# 限流配额：每分钟最大请求数
RATE_LIMITS = {
    'authenticated': 120,   # 已登录用户：120 次/分钟
    'guest': 30,             # 访客：30 次/分钟
    'ai_api': 20,            # AI 相关 API：20 次/分钟（成本控制）
}

# AI 相关 API 路径前缀（更严格限流）
AI_API_PREFIXES = (
    '/api/translate',
    '/api/excel-analyze-ai',
    '/api/test-report-ai',
    '/api/jira-search',
    '/api/generate-minutes',
    '/api/weekly-report',
    '/api/ai-chat',
    '/hld/api/generate',
    '/hld/api/preview',
)

# 不限流的路径前缀
EXEMPT_PREFIXES = (
    '/static/',
    '/health',
    '/favicon.ico',
    '/manifest.json',
    '/sw.js',
)

_WINDOW_SIZE = 60  # 滑动窗口大小（秒）
_CLEANUP_INTERVAL = 300  # 清理间隔（5分钟）
_MAX_KEYS = 10000  # 最大键数，防止内存爆炸

# ==================== 滑动窗口限流器 ====================

class SlidingWindowLimiter:
    """线程安全的滑动窗口速率限制器"""

    def __init__(self, window_size=_WINDOW_SIZE):
        self._window = window_size
        self._buckets = defaultdict(deque)  # key -> deque of timestamps
        self._lock = threading.Lock()
        self._last_cleanup = time.time()
        self._key_count = 0

    def _cleanup(self, now):
        """定期清理过期的窗口数据"""
        if now - self._last_cleanup < _CLEANUP_INTERVAL:
            return
        self._last_cleanup = now
        expired_keys = []
        for key, timestamps in self._buckets.items():
            # 移除过期时间戳
            while timestamps and timestamps[0] <= now - self._window:
                timestamps.popleft()
            if not timestamps:
                expired_keys.append(key)
        for key in expired_keys:
            del self._buckets[key]
        self._key_count = len(self._buckets)
        if expired_keys:
            logger.debug(f"限流器清理: 移除 {len(expired_keys)} 个过期键, 剩余 {self._key_count}")

    def check(self, key, limit):
        """检查是否允许请求

        Returns:
            (allowed: bool, remaining: int, retry_after: int)
        """
        now = time.time()
        with self._lock:
            self._cleanup(now)

            # 防止键数爆炸
            if self._key_count >= _MAX_KEYS and key not in self._buckets:
                logger.warning(f"限流器键数达到上限 {_MAX_KEYS}，拒绝新键")
                return False, 0, self._window

            bucket = self._buckets[key]

            # 移除窗口外的旧时间戳
            while bucket and bucket[0] <= now - self._window:
                bucket.popleft()

            current_count = len(bucket)
            if current_count >= limit:
                # 计算重试等待时间
                oldest = bucket[0] if bucket else now
                retry_after = max(1, int(self._window - (now - oldest)) + 1)
                return False, 0, retry_after

            # 记录本次请求
            bucket.append(now)
            return True, limit - current_count - 1, 0


# 全局实例
_limiter = SlidingWindowLimiter()


def _get_client_ip():
    """获取客户端真实 IP（支持代理）"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers['X-Forwarded-For'].split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers['X-Real-IP'].strip()
    return request.remote_addr or 'unknown'


def _get_rate_limit_key():
    """获取限流键：已登录用 user_id，未登录用 IP"""
    user = getattr(g, 'user', None)
    if user and user.get('id'):
        return f"u:{user['id']}"
    return f"ip:{_get_client_ip()}"


def _get_rate_limit():
    """根据请求路径和用户状态获取限流配额"""
    path = request.path
    # AI API 更严格限流
    if any(path.startswith(prefix) for prefix in AI_API_PREFIXES):
        return RATE_LIMITS['ai_api']
    # 已登录用户
    user = getattr(g, 'user', None)
    if user and user.get('id'):
        return RATE_LIMITS['authenticated']
    # 访客
    return RATE_LIMITS['guest']


def check_rate_limit():
    """检查速率限制

    在 before_request 中调用，返回 None 表示通过，返回 response 表示被限流。

    用法:
        result = check_rate_limit()
        if result:
            return result
    """
    path = request.path

    # 豁免路径直接放行
    if any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
        return None

    key = _get_rate_limit_key()
    limit = _get_rate_limit()

    allowed, remaining, retry_after = _limiter.check(key, limit)

    if not allowed:
        logger.warning(f"速率限制触发: key={key}, path={path}, limit={limit}/min")
        resp = jsonify({
            'error': '请求过于频繁，请稍后重试',
            'retry_after': retry_after,
        })
        resp.status_code = 429
        resp.headers['Retry-After'] = str(retry_after)
        resp.headers['X-RateLimit-Limit'] = str(limit)
        resp.headers['X-RateLimit-Remaining'] = '0'
        return resp

    # 在 g 中存储剩余配额，after_request 时写入响应头
    g.rate_limit_limit = limit
    g.rate_limit_remaining = remaining

    return None


def add_rate_limit_headers(response):
    """在 after_request 中添加限流响应头"""
    if hasattr(g, 'rate_limit_limit'):
        response.headers['X-RateLimit-Limit'] = str(g.rate_limit_limit)
        response.headers['X-RateLimit-Remaining'] = str(g.rate_limit_remaining)
    return response
