
import os
import json
import time
import logging
from sqlalchemy import text
"""db.activity - activity 相关数据库操作"""
from .base import engine, DB_TYPE, _row_to_dict

def resolve_tool_id(path):
    """从请求路径解析工具 ID 和名称"""
    # 精确匹配
    if path in _TOOL_PATH_MAP:
        return _TOOL_PATH_MAP[path]
    # 前缀匹配（如 /hld/api/generate -> hld-generator）
    for prefix, (tool_id, tool_name) in _TOOL_PATH_MAP.items():
        if path.startswith(prefix + '/') or path.startswith(prefix + '?'):
            return tool_id, tool_name
    # API 路径映射
    if path.startswith('/api/excel-analyze'):
        return 'cr-analysis', 'CR问题分析'
    if path.startswith('/api/translate'):
        return 'translator', 'IT翻译器'
    if path.startswith('/hld/'):
        return 'hld-generator', 'HLD生成器'
    if path.startswith('/api/notes'):
        return 'notes', '牛马笔记'
    if path.startswith('/api/jira-search'):
        return 'cr-analysis', 'CR问题分析'
    return None, None




def log_user_activity(user_id, tool_id, tool_name=None, action='view',
                      path=None, method='GET', status_code=200, duration_ms=0, ip=None):
    """记录用户活动（非阻塞，失败不影响请求）"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO user_activity
                        (user_id, tool_id, tool_name, action, path, method, status_code, duration_ms, ip, created_at)
                    VALUES
                        (:user_id, :tool_id, :tool_name, :action, :path, :method, :status_code, :duration_ms, :ip, :created_at)
                """),
                {
                    'user_id': user_id,
                    'tool_id': tool_id,
                    'tool_name': tool_name or '',
                    'action': action,
                    'path': path or '',
                    'method': method,
                    'status_code': status_code,
                    'duration_ms': duration_ms,
                    'ip': ip or '',
                    'created_at': time.time(),
                }
            )
    except Exception as e:
        logger.debug(f"记录用户活动失败（不影响请求）: {e}")




def get_user_activity_stats(user_id, days=30):
    """获取用户活动统计

    Returns:
        {
            'total_requests': int,
            'tools_used': [{tool_id, tool_name, count, last_used}],
            'daily_activity': [{date, count}],
            'top_tools': [{tool_id, tool_name, count, percentage}],
        }
    """
    now = time.time()
    since = now - days * 86400
    try:
        with engine.connect() as conn:
            # 总请求数
            total = conn.execute(
                text("SELECT COUNT(*) FROM user_activity WHERE user_id = :uid AND created_at >= :since"),
                {'uid': user_id, 'since': since}
            ).scalar() or 0

            # 工具使用统计
            tools = conn.execute(
                text("""
                    SELECT tool_id, tool_name, COUNT(*) as cnt, MAX(created_at) as last_used
                    FROM user_activity
                    WHERE user_id = :uid AND created_at >= :since AND tool_id IS NOT NULL
                    GROUP BY tool_id, tool_name
                    ORDER BY cnt DESC
                """),
                {'uid': user_id, 'since': since}
            ).fetchall()

            tools_used = []
            for row in tools:
                tools_used.append({
                    'tool_id': row[0],
                    'tool_name': row[1] or row[0],
                    'count': row[2],
                    'last_used': row[3],
                })

            # 每日活动（跨数据库兼容日期格式化）
            if DB_TYPE == 'postgresql':
                date_expr = "to_char(to_timestamp(created_at), 'YYYY-MM-DD')"
            else:
                date_expr = "DATE(created_at, 'unixepoch', 'localtime')"
            daily = conn.execute(
                text(f"""
                    SELECT {date_expr} as d, COUNT(*) as cnt
                    FROM user_activity
                    WHERE user_id = :uid AND created_at >= :since
                    GROUP BY d
                    ORDER BY d
                """),
                {'uid': user_id, 'since': since}
            ).fetchall()

            daily_activity = [{'date': row[0], 'count': row[1]} for row in daily]

            # Top 工具（百分比）
            top_tools = []
            if total > 0:
                for t in tools_used[:5]:
                    top_tools.append({
                        'tool_id': t['tool_id'],
                        'tool_name': t['tool_name'],
                        'count': t['count'],
                        'percentage': round(t['count'] * 100 / total, 1),
                    })

            return {
                'total_requests': total,
                'tools_used': tools_used,
                'daily_activity': daily_activity,
                'top_tools': top_tools,
                'days': days,
            }
    except Exception as e:
        logger.error(f"获取用户活动统计失败: {e}")
        return {
            'total_requests': 0,
            'tools_used': [],
            'daily_activity': [],
            'top_tools': [],
            'days': days,
        }




def cleanup_old_activity(max_age_days=90):
    """清理过期的活动记录"""
    try:
        cutoff = time.time() - max_age_days * 86400
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM user_activity WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
    except Exception as e:
        logger.error(f"清理活动记录失败: {e}")




def global_search(user_id, query, limit=20):
    """全局搜索：跨笔记、用户数据、图表模板搜索

    Args:
        user_id: 用户 ID
        query: 搜索关键词
        limit: 每类最大结果数

    Returns:
        {
            'notes': [{id, title, content_preview, category, created_at}],
            'user_data': [{id, data_type, title, content_preview, created_at}],
            'charts': [{id, name, chart_type, created_at}],
            'total': int,
        }
    """
    if not query or len(query.strip()) < 1:
        return {'notes': [], 'user_data': [], 'charts': [], 'total': 0}

    q = f"%{query.strip()}%"
    results = {'notes': [], 'user_data': [], 'charts': [], 'total': 0}

    try:
        with engine.connect() as conn:
            # 搜索笔记
            note_rows = conn.execute(
                text("""
                    SELECT id, title, content, category, tags, created_at
                    FROM notes
                    WHERE user_id = :uid
                      AND (title LIKE :q OR content LIKE :q OR tags LIKE :q)
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {'uid': user_id, 'q': q, 'limit': limit}
            ).fetchall()
            for row in note_rows:
                content = row[2] or ''
                results['notes'].append({
                    'id': row[0],
                    'title': row[1] or '无标题',
                    'content_preview': content[:200] + ('...' if len(content) > 200 else ''),
                    'category': row[3] or '',
                    'created_at': row[5],
                })

            # 搜索用户数据（CR分析、HLD等）
            data_rows = conn.execute(
                text("""
                    SELECT id, data_type, title, content, created_at
                    FROM user_data
                    WHERE user_id = :uid
                      AND (title LIKE :q OR content LIKE :q)
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {'uid': user_id, 'q': q, 'limit': limit}
            ).fetchall()
            for row in data_rows:
                content_str = str(row[3] or '')
                results['user_data'].append({
                    'id': row[0],
                    'data_type': row[1] or '',
                    'title': row[2] or '无标题',
                    'content_preview': content_str[:200] + ('...' if len(content_str) > 200 else ''),
                    'created_at': row[4],
                })

            # 搜索图表模板
            chart_rows = conn.execute(
                text("""
                    SELECT id, name, chart_type, created_at
                    FROM chart_templates
                    WHERE user_id = :uid AND name LIKE :q
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {'uid': str(user_id), 'q': q, 'limit': limit}
            ).fetchall()
            for row in chart_rows:
                results['charts'].append({
                    'id': row[0],
                    'name': row[1],
                    'chart_type': row[2],
                    'created_at': row[3],
                })

            results['total'] = len(results['notes']) + len(results['user_data']) + len(results['charts'])
            return results

    except Exception as e:
        logger.error(f"全局搜索失败: {e}")
        return results


# ==================== 应用配置 ====================



def get_merit(user_id):
    """获取用户功德数据"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT total_count, today_count, today_date FROM merit_records WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()
        if not row:
            return {'total_count': 0, 'today_count': 0, 'today_date': ''}
        m = row._mapping
        return {'total_count': m['total_count'], 'today_count': m['today_count'], 'today_date': m['today_date']}




def increment_merit(user_id):
    """功德+1（原子操作，自动处理日期切换）"""
    with engine.begin() as conn:
        now = time.time()
        today = time.strftime('%Y-%m-%d', time.localtime(now))

        row = conn.execute(
            text("SELECT today_date FROM merit_records WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).fetchone()

        if row:
            if row[0] != today:
                conn.execute(
                    text("UPDATE merit_records SET total_count = total_count + 1, today_count = 1, today_date = :today, updated_at = :updated_at WHERE user_id = :user_id"),
                    {'today': today, 'updated_at': now, 'user_id': user_id}
                )
            else:
                conn.execute(
                    text("UPDATE merit_records SET total_count = total_count + 1, today_count = today_count + 1, updated_at = :updated_at WHERE user_id = :user_id"),
                    {'updated_at': now, 'user_id': user_id}
                )
        else:
            conn.execute(
                text("INSERT INTO merit_records (user_id, total_count, today_count, today_date, updated_at) VALUES (:user_id, 1, 1, :today, :updated_at)"),
                {'user_id': user_id, 'today': today, 'updated_at': now}
            )

    # 返回更新后的数据（事务已提交，新连接可见）
    return get_merit(user_id)


# ==================== 上传会话 ====================



