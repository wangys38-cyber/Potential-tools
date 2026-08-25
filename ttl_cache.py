"""
阶段五性能优化：轻量级 TTL 内存缓存
- 用于不常变化的 API 响应（模型列表、系统配置、静态数据）
- 支持主动失效（数据变更时调用 invalidate）
- 线程安全，基于 dict + 时间戳
"""
import time
import threading
from functools import wraps

_cache = {}
_lock = threading.Lock()


def ttl_cache(ttl_seconds=60, key_prefix=''):
    """
    装饰器：缓存函数返回值，TTL 过期后自动刷新。
    适用于无副作用的查询函数（如获取模型列表、系统配置）。
    
    用法:
        @ttl_cache(ttl_seconds=300, key_prefix='ai_models')
        def get_ai_models():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 构造缓存键：前缀 + 函数名 + 参数
            key_parts = [key_prefix or func.__name__]
            if args:
                key_parts.append(str(args))
            if kwargs:
                key_parts.append(str(sorted(kwargs.items())))
            cache_key = ':'.join(key_parts)

            now = time.time()
            with _lock:
                entry = _cache.get(cache_key)
                if entry and (now - entry['time']) < ttl_seconds:
                    return entry['value']

            # 缓存未命中或已过期，执行函数
            value = func(*args, **kwargs)

            with _lock:
                _cache[cache_key] = {'value': value, 'time': time.time()}

            return value
        return wrapper
    return decorator


def invalidate(prefix):
    """主动失效所有以 prefix 开头的缓存键。
    数据变更时调用，例如更新 AI 配置后 invalidate('ai_models')。
    """
    with _lock:
        keys_to_delete = [k for k in _cache if k.startswith(prefix)]
        for k in keys_to_delete:
            del _cache[k]


def invalidate_all():
    """清空所有缓存。"""
    with _lock:
        _cache.clear()


def get_cache_stats():
    """返回缓存统计信息。"""
    with _lock:
        now = time.time()
        total = len(_cache)
        expired = sum(1 for e in _cache.values() if (now - e['time']) > 3600)
        return {'total_entries': total, 'expired_over_1h': expired}
