"""
系统指标采集模块 — 使用 psutil 采集 CPU、内存、磁盘、网络指标

设计原则：
1. 轻量级采集，不影响主请求性能
2. 内存中保留最近 N 个采样点，支持时间序列查询
3. 后台线程定期采集（默认 10 秒间隔）
4. 提供 get_current() 和 get_history() 接口
"""
import time
import logging
import threading
from collections import deque

logger = logging.getLogger(__name__)

# ==================== 配置 ====================
COLLECT_INTERVAL = 10          # 采集间隔（秒）
MAX_HISTORY_SAMPLES = 360      # 保留最近 360 个采样点（10秒×360=1小时）
CPU_SAMPLE_INTERVAL = 1.0       # CPU 采样计算间隔（秒）

# ==================== 全局状态 ====================
_lock = threading.Lock()
_history = deque(maxlen=MAX_HISTORY_SAMPLES)
_collector_thread = None
_stop_event = threading.Event()
_initialized = False


def _collect_once():
    """采集一次系统指标"""
    try:
        import psutil

        # CPU 使用率（interval=1 会阻塞1秒，用非阻塞模式取上次值）
        cpu_percent = psutil.cpu_percent(interval=None)

        # 内存
        mem = psutil.virtual_memory()
        mem_percent = mem.percent
        mem_used_mb = round(mem.used / (1024 * 1024), 1)
        mem_total_mb = round(mem.total / (1024 * 1024), 1)
        mem_available_mb = round(mem.available / (1024 * 1024), 1)

        # 磁盘（根分区）
        try:
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            disk_used_gb = round(disk.used / (1024 ** 3), 1)
            disk_total_gb = round(disk.total / (1024 ** 3), 1)
        except Exception:
            disk_percent = 0
            disk_used_gb = 0
            disk_total_gb = 0

        # 负载（仅 Linux）
        load_avg = [0, 0, 0]
        try:
            load_avg = list(psutil.getloadavg())
        except Exception:
            pass

        # 进程数
        try:
            process_count = len(psutil.pids())
        except Exception:
            process_count = 0

        # 网络 I/O（累计值）
        try:
            net = psutil.net_io_counters()
            net_bytes_sent = net.bytes_sent
            net_bytes_recv = net.bytes_recv
        except Exception:
            net_bytes_sent = 0
            net_bytes_recv = 0

        sample = {
            'timestamp': time.time(),
            'time_str': time.strftime('%H:%M:%S'),
            'cpu_percent': round(cpu_percent, 1),
            'mem_percent': round(mem_percent, 1),
            'mem_used_mb': mem_used_mb,
            'mem_total_mb': mem_total_mb,
            'mem_available_mb': mem_available_mb,
            'disk_percent': round(disk_percent, 1),
            'disk_used_gb': disk_used_gb,
            'disk_total_gb': disk_total_gb,
            'load_avg_1m': round(load_avg[0], 2) if load_avg else 0,
            'load_avg_5m': round(load_avg[1], 2) if len(load_avg) > 1 else 0,
            'load_avg_15m': round(load_avg[2], 2) if len(load_avg) > 2 else 0,
            'process_count': process_count,
            'net_bytes_sent': net_bytes_sent,
            'net_bytes_recv': net_bytes_recv,
        }

        with _lock:
            _history.append(sample)

        return sample
    except Exception as e:
        logger.warning(f"系统指标采集失败: {e}")
        return None


def _collector_loop():
    """后台采集线程循环"""
    logger.info("系统指标采集线程启动")
    # 首次调用 cpu_percent(interval=None) 返回 0，需要先调用一次初始化
    try:
        import psutil
        psutil.cpu_percent(interval=None)
    except Exception:
        pass

    while not _stop_event.is_set():
        _collect_once()
        _stop_event.wait(COLLECT_INTERVAL)
    logger.info("系统指标采集线程停止")


def start_collector():
    """启动后台采集线程（幂等）"""
    global _collector_thread, _initialized
    if _initialized:
        return
    _initialized = True
    _stop_event.clear()
    _collector_thread = threading.Thread(target=_collector_loop, daemon=True, name='sys-metrics-collector')
    _collector_thread.start()


def stop_collector():
    """停止采集线程"""
    _stop_event.set()


def get_current():
    """获取最新一次系统指标"""
    with _lock:
        if _history:
            return _history[-1].copy()
    return None


def get_history(limit=60):
    """获取最近 N 个采样点的历史数据"""
    with _lock:
        samples = list(_history)[-limit:]
    return samples


def get_summary():
    """获取系统指标摘要（当前值 + 最近1小时均值/峰值）"""
    with _lock:
        samples = list(_history)
    if not samples:
        return {
            'current': None,
            'avg_cpu': 0, 'max_cpu': 0,
            'avg_mem': 0, 'max_mem': 0,
            'sample_count': 0,
        }

    current = samples[-1].copy()
    cpu_values = [s['cpu_percent'] for s in samples]
    mem_values = [s['mem_percent'] for s in samples]

    return {
        'current': current,
        'avg_cpu': round(sum(cpu_values) / len(cpu_values), 1),
        'max_cpu': round(max(cpu_values), 1),
        'avg_mem': round(sum(mem_values) / len(mem_values), 1),
        'max_mem': round(max(mem_values), 1),
        'sample_count': len(samples),
        'history_duration_sec': len(samples) * COLLECT_INTERVAL,
    }
