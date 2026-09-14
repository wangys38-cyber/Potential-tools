"""
NL2SQL 服务 v8.0
将自然语言转换为 SQL 查询，并执行和解释结果
安全限制：只允许 SELECT，限制表和字段，自动用户隔离
"""
import re
import json
import time
import logging
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy import text

from .base import ChatMessage, AIError
from .prompts import render_prompt

logger = logging.getLogger(__name__)

# ==================== 可查询的表 Schema 定义 ====================
# 只暴露这些表给 NL2SQL，其他表不可查询
QUERYABLE_TABLES = {
    'user_activity': {
        'description': '用户活动日志，记录用户访问了哪些工具',
        'columns': {
            'id': 'INTEGER - 活动ID',
            'user_id': 'INTEGER - 用户ID',
            'tool_id': 'TEXT - 工具ID（如 cr-analysis, bug-trend）',
            'tool_name': 'TEXT - 工具名称',
            'action': 'TEXT - 动作（view, click, export）',
            'path': 'TEXT - 访问路径',
            'method': 'TEXT - HTTP方法',
            'duration_ms': 'INTEGER - 耗时（毫秒）',
            'created_at': 'REAL - 时间戳（Unix时间）',
        },
        'user_id_column': 'user_id',
    },
    'user_data': {
        'description': '用户上传的数据（CR分析、测试报告等）',
        'columns': {
            'id': 'INTEGER - 数据ID',
            'user_id': 'INTEGER - 用户ID',
            'data_type': 'TEXT - 数据类型（cr_analysis, test_report等）',
            'title': 'TEXT - 数据标题',
            'content': 'TEXT - 数据内容（JSON）',
            'created_at': 'REAL - 时间戳',
        },
        'user_id_column': 'user_id',
    },
    'notes': {
        'description': '用户笔记',
        'columns': {
            'id': 'INTEGER - 笔记ID',
            'user_id': 'INTEGER - 用户ID',
            'note_uid': 'TEXT - 笔记唯一ID',
            'title': 'TEXT - 笔记标题',
            'content': 'TEXT - 笔记内容',
            'category': 'TEXT - 分类',
            'tags': 'TEXT - 标签（JSON数组）',
            'pinned': 'INTEGER - 是否置顶',
            'created_at': 'REAL - 创建时间',
            'updated_at': 'REAL - 更新时间',
        },
        'user_id_column': 'user_id',
    },
    'audit_logs': {
        'description': '审计日志（仅管理员可查全部，普通用户只能查自己的）',
        'columns': {
            'id': 'INTEGER - 日志ID',
            'user_id': 'INTEGER - 用户ID',
            'action': 'TEXT - 操作类型',
            'target_type': 'TEXT - 目标类型',
            'target_id': 'TEXT - 目标ID',
            'ip': 'TEXT - IP地址',
            'user_agent': 'TEXT - User Agent',
            'details': 'TEXT - 详情',
            'created_at': 'REAL - 时间戳',
        },
        'user_id_column': 'user_id',
    },
    'notifications': {
        'description': '用户通知',
        'columns': {
            'id': 'INTEGER - 通知ID',
            'user_id': 'INTEGER - 用户ID',
            'type': 'TEXT - 通知类型',
            'title': 'TEXT - 标题',
            'content': 'TEXT - 内容',
            'link': 'TEXT - 链接',
            'is_read': 'INTEGER - 是否已读（0/1）',
            'created_at': 'REAL - 时间戳',
        },
        'user_id_column': 'user_id',
    },
    'ai_conversations': {
        'description': 'AI 对话记录',
        'columns': {
            'id': 'INTEGER - 记录ID',
            'user_id': 'INTEGER - 用户ID',
            'session_id': 'TEXT - 会话ID',
            'role': 'TEXT - 角色（user/assistant）',
            'content': 'TEXT - 消息内容',
            'tokens_used': 'INTEGER - Token用量',
            'model': 'TEXT - 模型',
            'created_at': 'REAL - 时间戳',
        },
        'user_id_column': 'user_id',
    },
}

# 时间范围辅助函数
TIME_RANGES = {
    '今天': "created_at >= strftime('%s', 'now', 'start of day')",
    '昨天': "created_at >= strftime('%s', 'now', '-1 day', 'start of day') AND created_at < strftime('%s', 'now', 'start of day')",
    '本周': "created_at >= strftime('%s', 'now', 'weekday 0', '-7 days')",
    '上周': "created_at >= strftime('%s', 'now', 'weekday 0', '-14 days') AND created_at < strftime('%s', 'now', 'weekday 0', '-7 days')",
    '本月': "created_at >= strftime('%s', 'now', 'start of month')",
    '近7天': "created_at >= strftime('%s', 'now', '-7 days')",
    '近30天': "created_at >= strftime('%s', 'now', '-30 days')",
}


def get_schema_description() -> str:
    """生成 Schema 描述文本，供 AI 参考"""
    lines = []
    for table_name, table_info in QUERYABLE_TABLES.items():
        lines.append(f"\n表名: {table_name}")
        lines.append(f"说明: {table_info['description']}")
        lines.append("字段:")
        for col_name, col_desc in table_info['columns'].items():
            lines.append(f"  - {col_name}: {col_desc}")
    return '\n'.join(lines)


def validate_sql(sql: str, user_id: int, is_admin: bool = False) -> Tuple[bool, str]:
    """
    验证 SQL 安全性
    Returns: (is_safe, reason)
    """
    sql_lower = sql.lower().strip()

    # 只允许 SELECT
    if not sql_lower.startswith('select'):
        return False, '只允许 SELECT 查询'

    # 禁止危险关键字
    dangerous_keywords = ['insert', 'update', 'delete', 'drop', 'alter', 'create', 'truncate', 'replace', 'attach', 'detach', 'pragma']
    for kw in dangerous_keywords:
        if re.search(rf'\b{kw}\b', sql_lower):
            return False, f'禁止使用 {kw.upper()} 语句'

    # 禁止子查询中的危险操作
    if ';' in sql:
        return False, '禁止多语句查询'

    # 检查查询的表是否在白名单中
    tables_in_query = re.findall(r'\bfrom\s+(\w+)|\bjoin\s+(\w+)', sql_lower)
    for match in tables_in_query:
        table = match[0] or match[1]
        if table and table not in QUERYABLE_TABLES:
            return False, f'不允许查询表: {table}'

    # 限制返回行数
    if 'limit' not in sql_lower:
        sql += ' LIMIT 100'

    return True, sql


def add_user_isolation(sql: str, user_id: int, is_admin: bool = False) -> str:
    """
    自动添加用户隔离条件
    普通用户只能查询自己的数据，管理员可以查全部
    """
    if is_admin:
        return sql

    # 找出查询的表，添加 WHERE user_id = :user_id
    for table_name, table_info in QUERYABLE_TABLES.items():
        if re.search(rf'\bfrom\s+{table_name}\b', sql, re.IGNORECASE):
            user_col = table_info.get('user_id_column', 'user_id')
            # 检查是否已有 WHERE
            if 'where' in sql.lower():
                # 在 WHERE 后添加用户条件
                sql = re.sub(
                    r'\bwhere\b',
                    f'WHERE {user_col} = :user_id AND ',
                    sql,
                    count=1,
                    flags=re.IGNORECASE
                )
            else:
                # 在 LIMIT/ORDER 前添加 WHERE
                sql = re.sub(
                    r'\b(order by|group by|limit)\b',
                    f'WHERE {user_col} = :user_id \\1',
                    sql,
                    count=1,
                    flags=re.IGNORECASE
                )
                # 如果没有 ORDER/LIMIT，就在末尾加
                if 'where' not in sql.lower():
                    sql += f' WHERE {user_col} = :user_id'
            break

    return sql


def natural_language_to_sql(question: str, ai_service, user_id: int, is_admin: bool = False) -> str:
    """
    将自然语言转换为 SQL
    """
    schema = get_schema_description()

    system_prompt = f"""你是 SQL 生成专家。根据用户的自然语言问题，生成对应的 SQLite 查询语句。

可查询的表结构如下：
{schema}

规则：
1. 只返回 SQL 语句，不要任何解释、注释或 markdown 代码块
2. 使用标准 SQLite 语法
3. 时间字段 created_at 是 Unix 时间戳（秒），用 strftime('%s', ...) 比较
4. 查询结果限制 100 条（自动添加 LIMIT 100）
5. 如果问题不明确，返回最接近的查询
6. 统计数量用 COUNT(*)，求和用 SUM()，平均用 AVG()
7. 按时间分组用 date(created_at, 'unixepoch', 'localtime')"""

    messages = [
        ChatMessage(role='system', content=system_prompt),
        ChatMessage(role='user', content=question),
    ]

    response = ai_service.chat(messages, max_tokens=500, temperature=0.1)
    sql = response.content.strip()

    # 清理可能的 markdown 代码块
    sql = re.sub(r'^```sql\s*', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'^```\s*', '', sql)
    sql = re.sub(r'\s*```$', '', sql)
    sql = sql.strip()

    return sql


def execute_query(sql: str, user_id: int, is_admin: bool = False) -> Dict[str, Any]:
    """
    执行 SQL 查询（带安全验证和用户隔离）
    """
    from db.base import engine

    # 验证 SQL
    is_safe, result = validate_sql(sql, user_id, is_admin)
    if not is_safe:
        raise ValueError(f'SQL 验证失败: {result}')
    sql = result  # 可能添加了 LIMIT

    # 添加用户隔离
    sql = add_user_isolation(sql, user_id, is_admin)

    # 执行查询
    with engine.connect() as conn:
        params = {'user_id': user_id}
        result = conn.execute(text(sql), params)
        rows = result.fetchall()
        columns = result.keys()

    return {
        'columns': list(columns),
        'rows': [dict(row._mapping) for row in rows],
        'row_count': len(rows),
        'sql': sql,
    }


def explain_results(question: str, query_result: Dict[str, Any], ai_service) -> str:
    """
    用 AI 解释查询结果
    """
    if query_result['row_count'] == 0:
        return '查询结果为空，没有找到匹配的数据。'

    # 限制数据量，避免 token 过多
    rows_preview = query_result['rows'][:20]
    data_preview = json.dumps(rows_preview, ensure_ascii=False, indent=2)

    system_prompt = """你是数据分析专家。根据用户的问题和查询结果，用简洁的中文解释数据含义和关键洞察。

要求：
1. 先给出核心结论（1-2句话）
2. 列出关键数据点
3. 如果有趋势或异常，指出并解释
4. 不超过 200 字
5. 用 Markdown 格式"""

    row_count = query_result['row_count']
    user_prompt = f"""用户问题: {question}

查询结果（共 {row_count} 行，显示前 20 行）:
{data_preview}

请解释结果。"""

    messages = [
        ChatMessage(role='system', content=system_prompt),
        ChatMessage(role='user', content=user_prompt),
    ]

    response = ai_service.chat(messages, max_tokens=500, temperature=0.3)
    return response.content


def query(question: str, ai_service, user_id: int, is_admin: bool = False) -> Dict[str, Any]:
    """
    完整的 NL2SQL 查询流程
    1. 自然语言转 SQL
    2. 验证和执行 SQL
    3. AI 解释结果
    """
    start_time = time.time()

    # Step 1: NL2SQL
    sql = natural_language_to_sql(question, ai_service, user_id, is_admin)
    logger.info(f"NL2SQL 生成: {sql}")

    # Step 2: 执行查询
    query_result = execute_query(sql, user_id, is_admin)

    # Step 3: AI 解释
    explanation = explain_results(question, query_result, ai_service)

    latency_ms = int((time.time() - start_time) * 1000)

    return {
        'question': question,
        'sql': query_result['sql'],
        'columns': query_result['columns'],
        'rows': query_result['rows'][:100],  # 最多返回 100 行
        'row_count': query_result['row_count'],
        'explanation': explanation,
        'latency_ms': latency_ms,
    }
