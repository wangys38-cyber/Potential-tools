"""
自动备份调度模块 — 每日凌晨 2 点自动创建加密备份

特性：
- 后台线程每日定时执行（默认凌晨 2:00）
- 备份内容：用户、偏好、数据、笔记、审计日志、登录尝试、会话等 12 张表
- 加密存储（使用 crypto_utils Fernet 加密）
- 保留策略：最近 7 天每日 + 最近 4 周每周
- 备份失败时记录日志，不影响主服务
"""
import os
import json
import time
import logging
import threading

logger = logging.getLogger(__name__)

# ==================== 配置 ====================
BACKUP_HOUR = 2                # 每日备份小时（24小时制，默认凌晨2点）
BACKUP_MINUTE = 0              # 备份分钟
BACKUP_DIR_NAME = 'backups'

# 需要备份的表（按依赖顺序）
BACKUP_TABLES = [
    'users', 'user_preferences', 'user_data', 'notes',
    'merit_records', 'chart_templates', 'dashboard_config',
    'app_config', 'audit_logs', 'login_attempts', 'user_sessions',
]

# ==================== 全局状态 ====================
_scheduler_thread = None
_stop_event = threading.Event()
_initialized = False


def _get_backup_dir():
    """获取备份目录路径"""
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, BACKUP_DIR_NAME)


def create_backup():
    """创建一次全量加密备份

    Returns:
        dict: {success, filename, records, error}
    """
    try:
        import db
        import crypto_utils

        backup_dir = _get_backup_dir()
        os.makedirs(backup_dir, exist_ok=True)

        # 导出数据
        backup = {
            'version': 1,
            'exported_at': time.time(),
            'exported_at_str': time.strftime('%Y-%m-%d %H:%M:%S'),
            'db_type': getattr(db, 'DB_TYPE', 'unknown'),
            'tables': {},
        }

        total_records = 0
        with db.engine.connect() as conn:
            for table in BACKUP_TABLES:
                try:
                    rows = conn.execute(db.text(f"SELECT * FROM {table}")).fetchall()
                    backup['tables'][table] = [dict(r._mapping) for r in rows]
                    total_records += len(rows)
                except Exception as e:
                    logger.warning(f"备份表 {table} 失败: {e}")
                    backup['tables'][table] = []

        # 生成文件名
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        filename = f'backup_{timestamp}.json'
        filepath = os.path.join(backup_dir, filename)

        # 加密并写入
        backup_str = json.dumps(backup, ensure_ascii=False)
        try:
            encrypted = crypto_utils.encrypt(backup_str)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(encrypted)
        except Exception as e:
            logger.warning(f"备份加密失败，使用明文存储: {e}")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(backup, f, ensure_ascii=False)

        # 清理旧备份
        cleanup_old_backups(backup_dir)

        logger.info(f"自动备份完成: {filename}, 共 {total_records} 条记录")
        return {'success': True, 'filename': filename, 'records': total_records}

    except Exception as e:
        logger.error(f"自动备份失败: {e}")
        return {'success': False, 'error': str(e)}


def cleanup_old_backups(backup_dir=None):
    """清理旧备份文件：保留最近7天每日 + 最近4周每周"""
    if backup_dir is None:
        backup_dir = _get_backup_dir()
    try:
        if not os.path.isdir(backup_dir):
            return
        now = time.time()
        files = []
        for f in os.listdir(backup_dir):
            if f.startswith('backup_') and f.endswith('.json'):
                filepath = os.path.join(backup_dir, f)
                mtime = os.path.getmtime(filepath)
                files.append((filepath, mtime, f))

        files.sort(key=lambda x: x[1], reverse=True)

        keep = set()
        seen_weeks = set()

        for filepath, mtime, fname in files:
            age_days = (now - mtime) / 86400
            if age_days <= 7:
                keep.add(filepath)  # 7天内全部保留
            elif age_days <= 28:
                week_num = int((now - mtime) / (7 * 86400))
                if week_num not in seen_weeks:
                    seen_weeks.add(week_num)
                    keep.add(filepath)

        removed = 0
        for filepath, _, _ in files:
            if filepath not in keep:
                try:
                    os.remove(filepath)
                    removed += 1
                except Exception:
                    pass

        if removed > 0:
            logger.info(f"清理旧备份: 删除 {removed} 个文件")
    except Exception as e:
        logger.debug(f"清理旧备份失败: {e}")


def list_backups():
    """列出所有备份文件"""
    backup_dir = _get_backup_dir()
    if not os.path.isdir(backup_dir):
        return []
    result = []
    for f in os.listdir(backup_dir):
        if f.startswith('backup_') and f.endswith('.json'):
            filepath = os.path.join(backup_dir, f)
            try:
                stat = os.stat(filepath)
                result.append({
                    'filename': f,
                    'size_kb': round(stat.st_size / 1024, 1),
                    'created_at': stat.st_mtime,
                    'created_at_str': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime)),
                })
            except Exception:
                pass
    result.sort(key=lambda x: x['created_at'], reverse=True)
    return result


def _get_seconds_until_backup():
    """计算距离下一次备份时间的秒数"""
    now = time.localtime()
    next_backup = time.mktime((
        now.tm_year, now.tm_mon, now.tm_mday,
        BACKUP_HOUR, BACKUP_MINUTE, 0,
        0, 0, -1
    ))
    if next_backup <= time.time():
        next_backup += 86400  # 明天同一时间
    return next_backup - time.time()


def _scheduler_loop():
    """后台调度线程循环"""
    logger.info(f"自动备份调度线程启动，每日 {BACKUP_HOUR:02d}:{BACKUP_MINUTE:02d} 执行")
    while not _stop_event.is_set():
        try:
            wait_seconds = _get_seconds_until_backup()
            logger.info(f"下一次自动备份将在 {int(wait_seconds // 3600)}小时{int((wait_seconds % 3600) // 60)}分钟后执行")

            # 分段等待，以便能及时响应停止信号
            waited = 0
            while waited < wait_seconds and not _stop_event.is_set():
                sleep_chunk = min(60, wait_seconds - waited)
                _stop_event.wait(sleep_chunk)
                waited += sleep_chunk

            if _stop_event.is_set():
                break

            # 执行备份
            logger.info("开始执行每日自动备份...")
            result = create_backup()
            if result['success']:
                logger.info(f"每日自动备份成功: {result['filename']} ({result['records']} 条记录)")
            else:
                logger.error(f"每日自动备份失败: {result.get('error')}")

        except Exception as e:
            logger.error(f"备份调度线程异常: {e}")
            _stop_event.wait(300)  # 出错后等待5分钟再重试

    logger.info("自动备份调度线程停止")


def start_scheduler():
    """启动自动备份调度线程（幂等）"""
    global _scheduler_thread, _initialized
    if _initialized:
        return
    _initialized = True
    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        daemon=True,
        name='backup-scheduler'
    )
    _scheduler_thread.start()
    logger.info("自动备份调度器已启动")


def stop_scheduler():
    """停止自动备份调度线程"""
    _stop_event.set()
