# -*- coding: utf-8 -*-
"""项目状态定时自动刷新。

每天 12:00 / 18:00 / 00:00 自动刷新所有已缓存快照的项目。
刷新日志写入 data/project_cache/_auto_refresh.log（JSON Lines）。
"""
import os
import json
import time
import logging
import traceback
from datetime import datetime

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'project_cache')
LOG_FILE = os.path.join(CACHE_DIR, '_auto_refresh.log')

# 触发时间（每天）
SCHEDULE_HOURS = [0, 12, 18]

_scheduler = None
_last_run = None
_last_result = None


def _cached_project_keys():
    """扫描已缓存快照的项目 key 列表。"""
    if not os.path.isdir(CACHE_DIR):
        return []
    keys = []
    for fn in os.listdir(CACHE_DIR):
        if fn.endswith('.json') and not fn.startswith('_'):
            keys.append(fn[:-5])
    return sorted(keys)


def _append_log(entry):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        logger.warning('写入自动刷新日志失败: %s', traceback.format_exc())


def refresh_all_projects():
    """刷新所有已缓存项目的快照。供定时任务调用。"""
    global _last_run, _last_result
    start = time.time()
    _last_run = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    keys = _cached_project_keys()
    results = []
    logger.info('自动刷新开始，共 %d 个项目: %s', len(keys), keys)

    # 延迟导入，避免循环依赖
    try:
        from services import project_assistant as pa
    except Exception:
        logger.error('导入 project_assistant 失败: %s', traceback.format_exc())
        _last_result = {'status': 'error', 'error': 'import failed', 'projects': []}
        _append_log({'ts': _last_run, 'status': 'error', 'error': 'import failed'})
        return _last_result

    for key in keys:
        t0 = time.time()
        try:
            snap = pa.build_project_snapshot(key, force=True)
            ok = True
            err = None
            total = snap.get('total')
        except Exception as e:
            ok = False
            err = f'{type(e).__name__}: {e}'
            total = None
            logger.error('自动刷新 %s 失败: %s', key, err)
        results.append({
            'key': key,
            'ok': ok,
            'total': total,
            'error': err,
            'duration_sec': round(time.time() - t0, 1),
        })
        # 项目间间隔，避免 eDart 限流
        time.sleep(2)

    elapsed = round(time.time() - start, 1)
    success = sum(1 for r in results if r['ok'])
    _last_result = {
        'status': 'done',
        'run_at': _last_run,
        'total_projects': len(keys),
        'success': success,
        'failed': len(keys) - success,
        'elapsed_sec': elapsed,
        'projects': results,
    }
    _append_log({'ts': _last_run, 'elapsed_sec': elapsed,
                 'total': len(keys), 'success': success, 'failed': len(keys) - success})
    logger.info('自动刷新完成：%d/%d 成功，耗时 %ds', success, len(keys), elapsed)
    return _last_result


def start_scheduler():
    """启动定时调度器。在 app.py 启动时调用一次。"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning('APScheduler 未安装，自动刷新未启用')
        return None

    _scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Shanghai')
    for hour in SCHEDULE_HOURS:
        _scheduler.add_job(
            refresh_all_projects,
            trigger=CronTrigger(hour=hour, minute=0, second=0),
            id=f'pa_refresh_{hour:02d}',
            name=f'项目状态自动刷新 {hour:02d}:00',
            misfire_grace_time=300,
            coalesce=True,
        )
    _scheduler.start()
    logger.info('项目状态自动刷新已启动：每天 %s',
                ', '.join(f'{h:02d}:00' for h in SCHEDULE_HOURS))
    return _scheduler


def get_status():
    """获取定时任务状态，供 API 返回。"""
    jobs = []
    if _scheduler is not None:
        try:
            for job in _scheduler.get_jobs():
                nxt = job.next_run_time
                jobs.append({
                    'id': job.id,
                    'name': job.name,
                    'next_run': nxt.strftime('%Y-%m-%d %H:%M:%S') if nxt else None,
                })
        except Exception:
            pass
    return {
        'enabled': _scheduler is not None,
        'schedule': [f'{h:02d}:00' for h in SCHEDULE_HOURS],
        'jobs': jobs,
        'last_run': _last_run,
        'last_result': _last_result,
        'cached_projects': _cached_project_keys(),
    }
