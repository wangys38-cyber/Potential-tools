"""
阶段五性能优化：API 响应时间统计中间件 + 慢查询日志
- before_request: 记录请求开始时间
- after_request: 计算响应时间，超过阈值记录慢查询日志
- 提供 /api/performance-metrics 端点返回统计数据
- 内存中保留最近 N 条慢查询记录，支持滚动窗口
"""
import time
import logging
import threading
from collections import deque
from flask import request, jsonify, g

logger = logging.getLogger(__name__)

# ==================== 配置 ====================
SLOW_QUERY_THRESHOLD_MS = 500  # 超过 500ms 视为慢查询
MAX_SLOW_LOGS = 200  # 内存中保留最近 200 条慢查询
MAX_METRICS_SAMPLES = 1000  # 响应时间采样数（用于计算百分位）

# ==================== 全局统计（线程安全）====================
_lock = threading.Lock()
_slow_logs = deque(maxlen=MAX_SLOW_LOGS)
_response_times = deque(maxlen=MAX_METRICS_SAMPLES)
_total_requests = 0
_slow_requests = 0
_total_response_time = 0.0


def register_performance_middleware(app):
    """注册性能监控中间件到 Flask app"""

    @app.before_request
    def _perf_before_request():
        g._perf_start_time = time.perf_counter()

    @app.after_request
    def _perf_after_request(response):
        start = getattr(g, '_perf_start_time', None)
        if start is None:
            return response
        elapsed_ms = (time.perf_counter() - start) * 1000

        global _total_requests, _slow_requests, _total_response_time
        with _lock:
            _total_requests += 1
            _total_response_time += elapsed_ms
            _response_times.append(elapsed_ms)

            if elapsed_ms >= SLOW_QUERY_THRESHOLD_MS:
                _slow_requests += 1
                entry = {
                    'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'method': request.method,
                    'path': request.path,
                    'duration_ms': round(elapsed_ms, 1),
                    'status': response.status_code,
                    'ip': request.remote_addr or '',
                }
                _slow_logs.append(entry)
                # 同时输出到日志（便于排查）
                logger.warning(
                    f"[慢查询] {request.method} {request.path} "
                    f"{elapsed_ms:.1f}ms status={response.status_code}"
                )

        # 在响应头中添加服务器处理时间（仅开发环境，避免泄露信息）
        if not app.config.get('PRODUCTION', False):
            response.headers['X-Response-Time'] = f'{elapsed_ms:.1f}ms'

        return response

    # 注册性能指标端点
    @app.route('/api/performance-metrics')
    def _perf_metrics():
        """返回性能统计指标（需登录，由全局登录拦截器处理）"""
        with _lock:
            times = sorted(_response_times)
            count = len(times)
            if count == 0:
                return jsonify({
                    'total_requests': 0,
                    'slow_requests': 0,
                    'avg_ms': 0,
                    'p50_ms': 0,
                    'p95_ms': 0,
                    'p99_ms': 0,
                    'slow_logs': [],
                })

            def _percentile(p):
                idx = min(int(count * p / 100), count - 1)
                return round(times[idx], 1)

            return jsonify({
                'total_requests': _total_requests,
                'slow_requests': _slow_requests,
                'slow_rate_pct': round(_slow_requests / _total_requests * 100, 2) if _total_requests else 0,
                'avg_ms': round(_total_response_time / _total_requests, 1) if _total_requests else 0,
                'p50_ms': _percentile(50),
                'p95_ms': _percentile(95),
                'p99_ms': _percentile(99),
                'max_ms': round(times[-1], 1),
                'min_ms': round(times[0], 1),
                'sample_count': count,
                'slow_logs': list(_slow_logs)[-50:],  # 返回最近 50 条
                'threshold_ms': SLOW_QUERY_THRESHOLD_MS,
            })

    # 阶段五：前端性能指标接收端点（静默接收，不存储，仅日志记录）
    @app.route('/api/frontend-metrics', methods=['POST'])
    def _frontend_metrics():
        """接收前端 Navigation Timing 指标，仅记录日志，不影响响应"""
        try:
            data = request.get_json(silent=True)
            if data and data.get('pageLoad'):
                pl = data['pageLoad']
                logger.info(
                    f"[前端性能] url={data.get('url', '?')} "
                    f"ttfb={pl.get('ttfb', 0)}ms "
                    f"fcp={pl.get('fcp', 0)}ms "
                    f"load={pl.get('pageLoad', 0)}ms "
                    f"resources={pl.get('resources', {}).get('total', 0)}"
                )
        except Exception:
            pass  # 静默失败
        return jsonify({'status': 'ok'}), 204


def get_slow_logs(limit=50):
    """供其他模块调用：获取最近的慢查询日志"""
    with _lock:
        return list(_slow_logs)[-limit:]


def reset_metrics():
    """重置统计数据（用于测试）"""
    global _total_requests, _slow_requests, _total_response_time
    with _lock:
        _total_requests = 0
        _slow_requests = 0
        _total_response_time = 0.0
        _slow_logs.clear()
        _response_times.clear()
