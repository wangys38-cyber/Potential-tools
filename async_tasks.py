"""
Potential-tools 9.0 - 异步任务框架
轻量级后台线程池任务队列，用于耗时操作（文件解析、AI分析、报告生成等）
- 任务提交后立即返回 task_id，不阻塞请求
- 支持任务状态查询、结果获取、任务取消
- 线程安全，基于 queue.Queue + threading
"""
import queue
import threading
import time
import uuid
import traceback
from typing import Optional, Callable, Any, Dict

# 任务状态
STATUS_PENDING = 'pending'
STATUS_RUNNING = 'running'
STATUS_COMPLETED = 'completed'
STATUS_FAILED = 'failed'
STATUS_CANCELLED = 'cancelled'

# 全局任务存储
_tasks: Dict[str, Dict[str, Any]] = {}
_tasks_lock = threading.Lock()

# 任务队列
_task_queue: queue.Queue = queue.Queue()

# 工作线程
_workers: list = []
_worker_count = 4
_running = False


def _worker_loop(worker_id: int):
    """工作线程主循环"""
    while _running:
        try:
            task_id = _task_queue.get(timeout=1)
        except queue.Empty:
            continue

        with _tasks_lock:
            task = _tasks.get(task_id)
            if not task or task['status'] == STATUS_CANCELLED:
                _task_queue.task_done()
                continue
            task['status'] = STATUS_RUNNING
            task['started_at'] = time.time()

        try:
            result = task['func'](*task['args'], **task['kwargs'])
            with _tasks_lock:
                task['status'] = STATUS_COMPLETED
                task['result'] = result
                task['completed_at'] = time.time()
        except Exception as e:
            with _tasks_lock:
                task['status'] = STATUS_FAILED
                task['error'] = str(e)
                task['traceback'] = traceback.format_exc()
                task['completed_at'] = time.time()
        finally:
            _task_queue.task_done()


def init_workers(count: int = 4):
    """初始化工作线程池"""
    global _running, _workers, _worker_count
    if _running:
        return
    _worker_count = count
    _running = True
    for i in range(count):
        t = threading.Thread(target=_worker_loop, args=(i,), daemon=True, name=f'async-worker-{i}')
        t.start()
        _workers.append(t)


def shutdown_workers():
    """关闭工作线程池"""
    global _running
    _running = False
    for t in _workers:
        t.join(timeout=5)
    _workers.clear()


def submit_task(func: Callable, *args, **kwargs) -> str:
    """
    提交异步任务
    :param func: 要执行的函数
    :param args: 位置参数
    :param kwargs: 关键字参数
    :return: task_id
    """
    if not _running:
        init_workers()

    task_id = str(uuid.uuid4())[:8]
    with _tasks_lock:
        _tasks[task_id] = {
            'id': task_id,
            'func': func,
            'args': args,
            'kwargs': kwargs,
            'status': STATUS_PENDING,
            'created_at': time.time(),
            'started_at': None,
            'completed_at': None,
            'result': None,
            'error': None,
            'traceback': None
        }
    _task_queue.put(task_id)
    return task_id


def get_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """获取任务状态（不包含 func 等内部字段）"""
    with _tasks_lock:
        task = _tasks.get(task_id)
        if not task:
            return None
        return {
            'id': task['id'],
            'status': task['status'],
            'created_at': task['created_at'],
            'started_at': task['started_at'],
            'completed_at': task['completed_at'],
            'error': task['error'],
            'duration': (task['completed_at'] - task['started_at']) if task['completed_at'] and task['started_at'] else None
        }


def get_task_result(task_id: str, timeout: float = 0) -> Optional[Any]:
    """
    获取任务结果
    :param task_id: 任务ID
    :param timeout: 等待超时时间（秒），0表示不等待直接返回
    :return: 任务结果，如果任务未完成返回 None
    """
    start = time.time()
    while True:
        with _tasks_lock:
            task = _tasks.get(task_id)
            if not task:
                return None
            if task['status'] in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED):
                if task['status'] == STATUS_FAILED:
                    raise Exception(task['error'])
                return task['result']
        if timeout <= 0 or (time.time() - start) >= timeout:
            return None
        time.sleep(0.1)


def cancel_task(task_id: str) -> bool:
    """取消任务（仅对 pending 状态的任务有效）"""
    with _tasks_lock:
        task = _tasks.get(task_id)
        if not task or task['status'] != STATUS_PENDING:
            return False
        task['status'] = STATUS_CANCELLED
        return True


def cleanup_old_tasks(max_age: int = 3600):
    """清理已完成/失败的旧任务（默认保留1小时）"""
    now = time.time()
    with _tasks_lock:
        expired = [tid for tid, t in _tasks.items()
                   if t['status'] in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)
                   and t['completed_at'] and (now - t['completed_at']) > max_age]
        for tid in expired:
            del _tasks[tid]
    return len(expired)


def get_queue_stats() -> Dict[str, Any]:
    """获取任务队列统计信息"""
    with _tasks_lock:
        pending = sum(1 for t in _tasks.values() if t['status'] == STATUS_PENDING)
        running = sum(1 for t in _tasks.values() if t['status'] == STATUS_RUNNING)
        completed = sum(1 for t in _tasks.values() if t['status'] == STATUS_COMPLETED)
        failed = sum(1 for t in _tasks.values() if t['status'] == STATUS_FAILED)
        total = len(_tasks)
    return {
        'total': total,
        'pending': pending,
        'running': running,
        'completed': completed,
        'failed': failed,
        'workers': _worker_count,
        'queue_size': _task_queue.qsize()
    }
