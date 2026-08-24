"""简单后台任务队列 — 基于线程池，无需额外依赖

v6.0 性能优化：
- 线程池管理（默认4个worker）
- 任务状态跟踪（pending/running/done/error/cancelled）
- 任务取消支持
- 结果缓存（1小时）
- 进度回调
"""
import time
import logging
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, Future

logger = logging.getLogger(__name__)


class TaskQueue:
    """简单的后台任务队列

    使用 ThreadPoolExecutor 管理任务，支持：
    - 提交任务并获取 task_id
    - 查询任务状态和进度
    - 取消任务
    - 结果缓存（默认1小时）
    """

    def __init__(self, max_workers=4, result_ttl=3600):
        """
        Args:
            max_workers: 最大并发线程数
            result_ttl: 结果缓存时间（秒），默认1小时
        """
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='task-queue')
        self._tasks = {}  # task_id -> task info dict
        self._lock = threading.Lock()
        self._result_ttl = result_ttl
        self._shutdown = False

        # 启动清理线程
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def submit(self, task_id, func, *args, **kwargs):
        """提交任务到队列

        Args:
            task_id: 任务ID
            func: 要执行的函数
            *args, **kwargs: 函数参数

        Returns:
            str: task_id
        """
        if self._shutdown:
            raise RuntimeError("TaskQueue已关闭")

        with self._lock:
            if task_id in self._tasks:
                # 任务已存在，检查状态
                task = self._tasks[task_id]
                if task['status'] in ('pending', 'running'):
                    logger.info(f"任务 {task_id} 已在队列中，状态: {task['status']}")
                    return task_id
                # 已完成的任务，重新提交

            task_info = {
                'task_id': task_id,
                'status': 'pending',
                'progress': 0,
                'progress_msg': '等待执行...',
                'result': None,
                'error': None,
                'created_at': time.time(),
                'started_at': None,
                'completed_at': None,
                'future': None,
                'cancel_event': threading.Event(),
            }
            self._tasks[task_id] = task_info

        # 定义包装函数，更新状态
        def _wrapper():
            with self._lock:
                task = self._tasks.get(task_id)
                if not task:
                    return
                task['status'] = 'running'
                task['started_at'] = time.time()
                task['progress_msg'] = '正在执行...'

            try:
                # 检查是否已取消
                if task_info['cancel_event'].is_set():
                    with self._lock:
                        task_info['status'] = 'cancelled'
                        task_info['completed_at'] = time.time()
                        task_info['progress_msg'] = '已取消'
                    return

                # 注入进度回调和取消事件到 kwargs
                progress_cb = lambda p, msg='': self._update_progress(task_id, p, msg)
                kwargs['_progress_cb'] = progress_cb
                kwargs['_cancel_event'] = task_info['cancel_event']

                result = func(*args, **kwargs)

                if task_info['cancel_event'].is_set():
                    with self._lock:
                        task_info['status'] = 'cancelled'
                        task_info['completed_at'] = time.time()
                        task_info['progress_msg'] = '已取消'
                    return

                with self._lock:
                    task_info['status'] = 'done'
                    task_info['result'] = result
                    task_info['progress'] = 100
                    task_info['progress_msg'] = '完成'
                    task_info['completed_at'] = time.time()

            except Exception as e:
                logger.error(f"任务 {task_id} 执行失败: {e}", exc_info=True)
                with self._lock:
                    task_info['status'] = 'error'
                    task_info['error'] = str(e)
                    task_info['completed_at'] = time.time()
                    task_info['progress_msg'] = f'失败: {e}'

        # 提交到线程池
        future = self._executor.submit(_wrapper)
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]['future'] = future

        return task_id

    def _update_progress(self, task_id, progress, msg=''):
        """更新任务进度"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task['status'] == 'running':
                task['progress'] = max(0, min(100, progress))
                if msg:
                    task['progress_msg'] = msg

    def get_status(self, task_id):
        """获取任务状态

        Returns:
            dict: { status, progress, progress_msg, result, error, ... }
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            # 返回副本，避免外部修改
            return {
                'task_id': task['task_id'],
                'status': task['status'],
                'progress': task['progress'],
                'progress_msg': task['progress_msg'],
                'result': task['result'],
                'error': task['error'],
                'created_at': task['created_at'],
                'started_at': task['started_at'],
                'completed_at': task['completed_at'],
            }

    def cancel(self, task_id):
        """取消任务

        Returns:
            bool: 是否成功发起取消
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task['status'] in ('done', 'error', 'cancelled'):
                return False
            task['cancel_event'].set()
            task['status'] = 'cancelled'
            task['progress_msg'] = '正在取消...'
            task['completed_at'] = time.time()
            return True

    def _cleanup_loop(self):
        """定期清理过期的已完成任务"""
        while not self._shutdown:
            try:
                time.sleep(60)  # 每分钟检查一次
                now = time.time()
                with self._lock:
                    expired = []
                    for task_id, task in self._tasks.items():
                        if task['status'] in ('done', 'error', 'cancelled'):
                            if task['completed_at'] and (now - task['completed_at'] > self._result_ttl):
                                expired.append(task_id)
                    for task_id in expired:
                        del self._tasks[task_id]
                    if expired:
                        logger.info(f"清理了 {len(expired)} 个过期任务")
            except Exception as e:
                logger.error(f"清理线程异常: {e}")

    def shutdown(self, wait=True):
        """关闭任务队列"""
        self._shutdown = True
        self._executor.shutdown(wait=wait)

    def get_stats(self):
        """获取队列统计信息"""
        with self._lock:
            stats = {
                'total': len(self._tasks),
                'pending': 0,
                'running': 0,
                'done': 0,
                'error': 0,
                'cancelled': 0,
            }
            for task in self._tasks.values():
                status = task['status']
                if status in stats:
                    stats[status] += 1
            return stats


# 全局单例
_task_queue_instance = None
_task_queue_lock = threading.Lock()


def get_task_queue():
    """获取全局任务队列单例"""
    global _task_queue_instance
    if _task_queue_instance is None:
        with _task_queue_lock:
            if _task_queue_instance is None:
                _task_queue_instance = TaskQueue(max_workers=4, result_ttl=3600)
    return _task_queue_instance
