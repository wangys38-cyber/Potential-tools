"""
Gunicorn 生产环境配置文件

适用于 Potential-tools Flask 应用：
- IO 密集型应用，使用 gthread 工作模式
- 单 worker + 多线程，避免内存中性能指标/告警状态多进程不一致
- 支持 Railway 等云平台（通过 $PORT 环境变量绑定端口）
"""
import os
import multiprocessing

# ==================== 网络配置 ====================
# 绑定地址和端口（Railway 等平台通过 $PORT 环境变量指定）
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# 保持连接超时（秒）
keepalive = 10

# ==================== 工作进程配置 ====================
# 工作模式：gthread（线程模式，适合 IO 密集型 Flask 应用）
worker_class = "gthread"

# 工作进程数：1（单进程避免内存中性能指标/告警状态多进程不一致）
# 如需多进程，需将性能指标和告警状态迁移到共享存储（Redis/数据库）
workers = int(os.environ.get('GUNICORN_WORKERS', 1))

# 每个工作进程的线程数
threads = int(os.environ.get('GUNICORN_THREADS', 16))

# 最大并发连接数（gthread 模式下 = workers * threads）
worker_connections = 1000

# ==================== 超时配置 ====================
# 工作进程超时时间（秒）- AI 请求可能耗时较长
timeout = int(os.environ.get('GUNICORN_TIMEOUT', 300))

# 优雅关闭超时（秒）
graceful_timeout = 30

# ==================== 进程管理 ====================
# 最大请求数后重启 worker（防止内存泄漏）
max_requests = 1000

# 最大请求数抖动（避免所有 worker 同时重启）
max_requests_jitter = 50

# 预加载应用代码（False：避免 playwright 等资源在 worker 间共享问题）
preload_app = False

# Worker 临时目录（使用 /dev/shm 内存文件系统提升性能）
worker_tmp_dir = "/dev/shm"

# ==================== 日志配置 ====================
# 访问日志格式
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'

# 访问日志输出（stdout 供 Railway 日志收集）
accesslog = "-"

# 错误日志输出
errorlog = "-"

# 日志级别
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')

# ==================== 进程命名 ====================
# 主进程名称
proc_name = "potential-tools"

# ==================== 服务器钩子 ====================
def on_starting(server):
    """Gunicorn 启动时调用（主进程，worker 启动前）"""
    server.log.info("Potential-tools 正在启动 (workers=%s, threads=%s, timeout=%ss)",
                    workers, threads, timeout)


def when_ready(server):
    """服务器就绪时调用"""
    server.log.info("Potential-tools 已就绪，监听 %s", bind)


def worker_int(worker):
    """worker 收到中断信号时调用"""
    worker.log.info("Worker %s 收到中断信号，正在关闭", worker.pid)


def post_fork(server, worker):
    """worker 进程 fork 后调用"""
    worker.log.info("Worker %s 已启动", worker.pid)
