"""
告警系统模块 — 实时监控系统指标并通过飞书推送告警

告警类型：
1. error_rate   — 5xx 错误率 > 1%（5分钟滑动窗口）
2. latency_p95  — P95 响应延迟 > 3000ms（5分钟滑动窗口）
3. cpu_high     — CPU 使用率 > 80%
4. memory_high  — 内存使用率 > 85%

特性：
- 10 分钟告警去重（同一类型告警 10 分钟内只推送一次）
- 飞书交互卡片告警（含指标详情、时间、阈值）
- 告警历史记录（内存保留最近 200 条）
- 可配置阈值和 Webhook（JSON 文件持久化）
- 后台巡检线程（每 60 秒检查一次）
"""
import os
import json
import time
import logging
import threading
from collections import deque

logger = logging.getLogger(__name__)

# ==================== 配置 ====================
CHECK_INTERVAL = 60             # 巡检间隔（秒）
ALERT_WINDOW_SECONDS = 300      # 告警统计窗口（5分钟）
DEDUP_INTERVAL = 600            # 告警去重间隔（10分钟）
MAX_ALERT_HISTORY = 200         # 告警历史保留条数
MIN_REQUESTS_FOR_ALERT = 20     # 触发错误率告警的最小请求数（避免小样本误报）

# 默认阈值
DEFAULT_THRESHOLDS = {
    'error_rate_pct': 1.0,      # 5xx 错误率阈值（%）
    'latency_p95_ms': 3000,     # P95 延迟阈值（ms）
    'cpu_percent': 80,           # CPU 使用率阈值（%）
    'memory_percent': 85,        # 内存使用率阈值（%）
}

# 告警类型元数据
ALERT_TYPES = {
    'error_rate': {
        'name': '5xx 错误率过高',
        'level': 'critical',
        'color': 'red',
        'icon': '🚨',
    },
    'latency_p95': {
        'name': 'P95 响应延迟过高',
        'level': 'warning',
        'color': 'orange',
        'icon': '⚠️',
    },
    'cpu_high': {
        'name': 'CPU 使用率过高',
        'level': 'warning',
        'color': 'orange',
        'icon': '🔥',
    },
    'memory_high': {
        'name': '内存使用率过高',
        'level': 'warning',
        'color': 'orange',
        'icon': '💾',
    },
}

# ==================== 全局状态 ====================
_lock = threading.Lock()
_request_window = deque()       # 请求滑动窗口：[(timestamp, status_code, duration_ms)]
_alert_history = deque(maxlen=MAX_ALERT_HISTORY)
_last_alert_time = {}           # 各类型上次告警时间：{alert_type: timestamp}
_checker_thread = None
_stop_event = threading.Event()
_initialized = False

# 配置（运行时可修改）
_config = {
    'enabled': True,
    'feishu_webhook': '',
    'feishu_secret': '',
    'thresholds': DEFAULT_THRESHOLDS.copy(),
    'alert_types': {k: True for k in ALERT_TYPES},  # 各类型开关
}

# 配置文件路径
_CONFIG_DIR = os.environ.get('DB_DIR', '/tmp/toolbox')
_CONFIG_PATH = os.path.join(_CONFIG_DIR, 'alert_config.json')


# ==================== 配置持久化 ====================

def load_config():
    """从 JSON 文件加载告警配置"""
    global _config
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            _config.update(saved)
            # 确保 thresholds 完整
            for k, v in DEFAULT_THRESHOLDS.items():
                _config['thresholds'].setdefault(k, v)
            logger.info(f"告警配置已加载: enabled={_config['enabled']}, webhook={'已配置' if _config['feishu_webhook'] else '未配置'}")
    except Exception as e:
        logger.warning(f"加载告警配置失败: {e}")


def save_config():
    """保存告警配置到 JSON 文件"""
    try:
        os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
        with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(_config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存告警配置失败: {e}")


def get_config():
    """获取当前告警配置（副本）"""
    with _lock:
        return {
            'enabled': _config['enabled'],
            'feishu_webhook_configured': bool(_config['feishu_webhook']),
            'thresholds': _config['thresholds'].copy(),
            'alert_types': _config['alert_types'].copy(),
        }


def update_config(enabled=None, feishu_webhook=None, feishu_secret=None,
                  thresholds=None, alert_types=None):
    """更新告警配置"""
    with _lock:
        if enabled is not None:
            _config['enabled'] = bool(enabled)
        if feishu_webhook is not None:
            _config['feishu_webhook'] = feishu_webhook.strip()
        if feishu_secret is not None:
            _config['feishu_secret'] = feishu_secret.strip()
        if thresholds and isinstance(thresholds, dict):
            for k, v in thresholds.items():
                if k in DEFAULT_THRESHOLDS and v is not None:
                    try:
                        _config['thresholds'][k] = float(v)
                    except (ValueError, TypeError):
                        pass
        if alert_types and isinstance(alert_types, dict):
            for k, v in alert_types.items():
                if k in ALERT_TYPES:
                    _config['alert_types'][k] = bool(v)
    save_config()
    logger.info("告警配置已更新")


# ==================== 请求数据记录 ====================

def record_request(status_code, duration_ms):
    """记录一次请求到滑动窗口（供告警计算使用）

    Args:
        status_code: HTTP 状态码
        duration_ms: 响应时间（毫秒）
    """
    now = time.time()
    with _lock:
        _request_window.append((now, int(status_code), float(duration_ms)))
        # 清理过期数据
        cutoff = now - ALERT_WINDOW_SECONDS
        while _request_window and _request_window[0][0] < cutoff:
            _request_window.popleft()


def _get_window_stats():
    """计算当前滑动窗口的统计数据（内部调用，需持锁）"""
    now = time.time()
    cutoff = now - ALERT_WINDOW_SECONDS

    # 清理过期
    while _request_window and _request_window[0][0] < cutoff:
        _request_window.popleft()

    if not _request_window:
        return {
            'total': 0, 'error_5xx': 0, 'error_rate_pct': 0,
            'p50_ms': 0, 'p95_ms': 0, 'p99_ms': 0, 'avg_ms': 0,
            'window_seconds': ALERT_WINDOW_SECONDS,
        }

    total = len(_request_window)
    error_5xx = sum(1 for _, s, _ in _request_window if s >= 500)
    durations = sorted([d for _, _, d in _request_window])

    def _percentile(p):
        idx = min(int(total * p / 100), total - 1)
        return round(durations[idx], 1)

    return {
        'total': total,
        'error_5xx': error_5xx,
        'error_rate_pct': round(error_5xx / total * 100, 2) if total else 0,
        'p50_ms': _percentile(50),
        'p95_ms': _percentile(95),
        'p99_ms': _percentile(99),
        'avg_ms': round(sum(durations) / total, 1),
        'window_seconds': ALERT_WINDOW_SECONDS,
    }


def get_request_stats():
    """获取当前请求统计（对外接口）"""
    with _lock:
        return _get_window_stats()


# ==================== 告警检测与推送 ====================

def _should_dedup(alert_type):
    """检查是否需要去重（True 表示应跳过本次告警）"""
    now = time.time()
    last = _last_alert_time.get(alert_type, 0)
    if now - last < DEDUP_INTERVAL:
        return True
    _last_alert_time[alert_type] = now
    return False


def _send_feishu_alert(alert_type, metrics, current_value, threshold):
    """发送飞书告警卡片

    Args:
        alert_type: 告警类型
        metrics: 相关指标详情
        current_value: 当前触发值
        threshold: 阈值
    """
    webhook = _config.get('feishu_webhook', '')
    if not webhook:
        logger.warning(f"告警未推送：飞书 Webhook 未配置 ({alert_type})")
        return False

    try:
        import feishu_push

        meta = ALERT_TYPES[alert_type]
        time_str = time.strftime('%Y-%m-%d %H:%M:%S')

        # 构建 Markdown 内容
        md_lines = [
            f"**{meta['icon']} {meta['name']}**",
            f"",
            f"**触发时间：** {time_str}",
            f"**告警级别：** {meta['level'].upper()}",
            f"**当前值：** {current_value}",
            f"**阈值：** {threshold}",
        ]

        # 添加详细指标
        if metrics:
            md_lines.append("")
            md_lines.append("**详细指标：**")
            for k, v in metrics.items():
                md_lines.append(f"- {k}: {v}")

        md_lines.append("")
        md_lines.append("---")
        md_lines.append("*此告警由 Potential-tools 自动监控系统发送，10分钟内同类告警不重复推送*")

        markdown_content = "\n".join(md_lines)

        result = feishu_push.send_feishu_card(
            webhook_url=webhook,
            title=f"{meta['icon']} [{meta['level'].upper()}] {meta['name']}",
            markdown_content=markdown_content,
            header_color=meta['color'],
            secret=_config.get('feishu_secret') or None,
        )

        if result.get('ok'):
            logger.info(f"飞书告警推送成功: {alert_type}")
            return True
        else:
            logger.warning(f"飞书告警推送失败: {alert_type}, {result.get('error')}")
            return False
    except Exception as e:
        logger.error(f"飞书告警推送异常: {e}")
        return False


def _trigger_alert(alert_type, current_value, threshold, metrics=None):
    """触发告警（去重 + 记录历史 + 飞书推送）"""
    # 去重检查
    if _should_dedup(alert_type):
        logger.debug(f"告警去重跳过: {alert_type}")
        return

    meta = ALERT_TYPES[alert_type]
    time_str = time.strftime('%Y-%m-%d %H:%M:%S')

    # 记录历史
    alert_record = {
        'id': f"{alert_type}_{int(time.time()*1000)}",
        'type': alert_type,
        'type_name': meta['name'],
        'level': meta['level'],
        'current_value': str(current_value),
        'threshold': str(threshold),
        'metrics': metrics or {},
        'timestamp': time.time(),
        'time_str': time_str,
        'status': 'fired',
    }

    with _lock:
        _alert_history.append(alert_record)

    logger.warning(f"🚨 告警触发: {meta['name']} 当前={current_value} 阈值={threshold}")

    # 飞书推送（不阻塞，失败不影响主流程）
    if _config['enabled'] and _config.get('feishu_webhook'):
        threading.Thread(
            target=_send_feishu_alert,
            args=(alert_type, metrics, current_value, threshold),
            daemon=True,
        ).start()


def _check_alerts():
    """执行一次告警检查（由后台线程调用）"""
    if not _config['enabled']:
        return

    thresholds = _config['thresholds']
    alert_types_enabled = _config['alert_types']

    # 1. 检查请求指标（错误率 + P95 延迟）
    with _lock:
        stats = _get_window_stats()

    if stats['total'] >= MIN_REQUESTS_FOR_ALERT:
        # 错误率告警
        if alert_types_enabled.get('error_rate', True):
            if stats['error_rate_pct'] >= thresholds['error_rate_pct']:
                _trigger_alert(
                    'error_rate',
                    current_value=f"{stats['error_rate_pct']}%",
                    threshold=f"{thresholds['error_rate_pct']}%",
                    metrics={
                        '总请求数': stats['total'],
                        '5xx 错误数': stats['error_5xx'],
                        '统计窗口': f"{stats['window_seconds']}秒",
                        'P50 延迟': f"{stats['p50_ms']}ms",
                        'P95 延迟': f"{stats['p95_ms']}ms",
                    },
                )

        # P95 延迟告警
        if alert_types_enabled.get('latency_p95', True):
            if stats['p95_ms'] >= thresholds['latency_p95_ms']:
                _trigger_alert(
                    'latency_p95',
                    current_value=f"{stats['p95_ms']}ms",
                    threshold=f"{thresholds['latency_p95_ms']}ms",
                    metrics={
                        '总请求数': stats['total'],
                        'P50 延迟': f"{stats['p50_ms']}ms",
                        'P99 延迟': f"{stats['p99_ms']}ms",
                        '平均延迟': f"{stats['avg_ms']}ms",
                        '统计窗口': f"{stats['window_seconds']}秒",
                    },
                )

    # 2. 检查系统指标（CPU + 内存）
    try:
        import system_metrics
        sys_metrics = system_metrics.get_current()
        if sys_metrics:
            # CPU 告警
            if alert_types_enabled.get('cpu_high', True):
                if sys_metrics['cpu_percent'] >= thresholds['cpu_percent']:
                    _trigger_alert(
                        'cpu_high',
                        current_value=f"{sys_metrics['cpu_percent']}%",
                        threshold=f"{thresholds['cpu_percent']}%",
                        metrics={
                            '内存使用率': f"{sys_metrics['mem_percent']}%",
                            '1分钟负载': sys_metrics['load_avg_1m'],
                            '进程数': sys_metrics['process_count'],
                        },
                    )

            # 内存告警
            if alert_types_enabled.get('memory_high', True):
                if sys_metrics['mem_percent'] >= thresholds['memory_percent']:
                    _trigger_alert(
                        'memory_high',
                        current_value=f"{sys_metrics['mem_percent']}%",
                        threshold=f"{thresholds['memory_percent']}%",
                        metrics={
                            '已用内存': f"{sys_metrics['mem_used_mb']}MB",
                            '总内存': f"{sys_metrics['mem_total_mb']}MB",
                            '可用内存': f"{sys_metrics['mem_available_mb']}MB",
                            'CPU 使用率': f"{sys_metrics['cpu_percent']}%",
                        },
                    )
    except Exception as e:
        logger.debug(f"系统指标告警检查跳过: {e}")


# ==================== 后台巡检线程 ====================

def _checker_loop():
    """后台巡检线程循环"""
    logger.info("告警巡检线程启动")
    while not _stop_event.is_set():
        try:
            _check_alerts()
        except Exception as e:
            logger.error(f"告警巡检异常: {e}")
        _stop_event.wait(CHECK_INTERVAL)
    logger.info("告警巡检线程停止")


def start_alerting():
    """启动告警系统（加载配置 + 启动巡检线程，幂等）"""
    global _checker_thread, _initialized
    if _initialized:
        return
    load_config()
    _initialized = True
    _stop_event.clear()
    _checker_thread = threading.Thread(target=_checker_loop, daemon=True, name='alert-checker')
    _checker_thread.start()
    logger.info("告警系统已启动")


def stop_alerting():
    """停止告警系统"""
    _stop_event.set()


# ==================== 告警历史查询 ====================

def get_alert_history(limit=50, alert_type=None, level=None):
    """获取告警历史

    Args:
        limit: 返回条数
        alert_type: 按类型过滤
        level: 按级别过滤
    """
    with _lock:
        history = list(_alert_history)

    if alert_type:
        history = [h for h in history if h['type'] == alert_type]
    if level:
        history = [h for h in history if h['level'] == level]

    return history[-limit:][::-1]  # 最新的在前


def get_alert_summary():
    """获取告警摘要统计"""
    with _lock:
        history = list(_alert_history)
        stats = _get_window_stats()

    type_counts = {}
    for h in history:
        t = h['type']
        type_counts[t] = type_counts.get(t, 0) + 1

    # 最近24小时告警数
    now = time.time()
    last_24h = [h for h in history if now - h['timestamp'] < 86400]

    return {
        'total_alerts': len(history),
        'alerts_last_24h': len(last_24h),
        'alerts_by_type': type_counts,
        'last_alert': history[-1] if history else None,
        'request_stats': stats,
        'dedup_interval_minutes': DEDUP_INTERVAL // 60,
        'check_interval_seconds': CHECK_INTERVAL,
    }


def test_alert(alert_type='error_rate'):
    """手动触发测试告警（用于验证飞书 Webhook 配置）"""
    if alert_type not in ALERT_TYPES:
        return False, f"未知告警类型: {alert_type}"

    meta = ALERT_TYPES[alert_type]
    # 测试告警不走去重，直接发送
    webhook = _config.get('feishu_webhook', '')
    if not webhook:
        return False, "飞书 Webhook 未配置"

    time_str = time.strftime('%Y-%m-%d %H:%M:%S')
    md_content = (
        f"**{meta['icon']} 测试告警**\n\n"
        f"**告警类型：** {meta['name']}\n"
        f"**触发时间：** {time_str}\n"
        f"**告警级别：** {meta['level'].upper()}\n\n"
        f"这是一条测试告警，用于验证飞书 Webhook 配置是否正常。\n\n"
        f"---\n*Potential-tools 监控系统测试*"
    )

    try:
        import feishu_push
        result = feishu_push.send_feishu_card(
            webhook_url=webhook,
            title=f"{meta['icon']} [TEST] {meta['name']}",
            markdown_content=md_content,
            header_color='blue',
            secret=_config.get('feishu_secret') or None,
        )
        if result.get('ok'):
            return True, "测试告警发送成功"
        return False, f"发送失败: {result.get('error')}"
    except Exception as e:
        return False, f"发送异常: {e}"
