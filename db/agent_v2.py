# -*- coding: utf-8 -*-
"""
Agent 2.0 数据访问层

管理 Agent 执行记录、步骤、工作流、记忆、指标等数据。
"""
import sqlite3
import json
import time
import uuid
from typing import Dict, List, Optional, Any

from db.base import get_db_path, get_connection


def create_execution(user_id: str, task: str, agent_role: str = 'general',
                     session_id: str = '') -> str:
    """创建执行记录"""
    execution_id = f'exec_{uuid.uuid4().hex[:16]}'
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO agent_executions (execution_id, user_id, task, agent_role, session_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (execution_id, user_id, task, agent_role, session_id, 'pending', int(time.time())))
        conn.commit()
    finally:
        conn.close()
    return execution_id


def update_execution(execution_id: str, **kwargs) -> bool:
    """更新执行记录"""
    conn = get_connection()
    try:
        allowed_fields = ['status', 'total_steps', 'completed_steps', 'plan_summary',
                          'final_result', 'error_message', 'started_at', 'completed_at']
        updates = []
        params = []
        for key, value in kwargs.items():
            if key in allowed_fields:
                updates.append(f'{key} = ?')
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                params.append(value)
        if not updates:
            return False
        params.append(execution_id)
        conn.execute(f'UPDATE agent_executions SET {', '.join(updates)} WHERE execution_id = ?', params)
        conn.commit()
        return True
    finally:
        conn.close()


def get_execution(execution_id: str) -> Optional[Dict]:
    """获取执行记录"""
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM agent_executions WHERE execution_id = ?', (execution_id,)).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def list_executions(user_id: str, limit: int = 20, offset: int = 0) -> List[Dict]:
    """列出用户的执行记录"""
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT * FROM agent_executions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        ''', (user_id, limit, offset)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_step(execution_id: str, step_index: int, tool_name: str,
                tool_input: Dict = None, reasoning: str = '') -> str:
    """创建步骤记录"""
    step_id = f'step_{uuid.uuid4().hex[:16]}'
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO agent_execution_steps (step_id, execution_id, step_index, tool_name, tool_input, reasoning, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (step_id, execution_id, step_index, tool_name,
              json.dumps(tool_input or {}, ensure_ascii=False), reasoning, 'pending', int(time.time())))
        conn.commit()
    finally:
        conn.close()
    return step_id


def update_step(step_id: str, **kwargs) -> bool:
    """更新步骤记录"""
    conn = get_connection()
    try:
        allowed_fields = ['status', 'tool_output', 'error_message', 'started_at', 'completed_at']
        updates = []
        params = []
        for key, value in kwargs.items():
            if key in allowed_fields:
                updates.append(f'{key} = ?')
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                params.append(value)
        if not updates:
            return False
        params.append(step_id)
        conn.execute(f'UPDATE agent_execution_steps SET {', '.join(updates)} WHERE step_id = ?', params)
        conn.commit()
        return True
    finally:
        conn.close()


def get_execution_steps(execution_id: str) -> List[Dict]:
    """获取执行的所有步骤"""
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT * FROM agent_execution_steps
            WHERE execution_id = ?
            ORDER BY step_index ASC
        ''', (execution_id,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ============================ 工作流 ============================

def create_workflow(user_id: str, name: str, description: str = '',
                    nodes: List = None, edges: List = None) -> str:
    """创建工作流"""
    workflow_id = f'wf_{uuid.uuid4().hex[:16]}'
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO workflows (workflow_id, user_id, name, description, nodes, edges, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (workflow_id, user_id, name, description,
              json.dumps(nodes or [], ensure_ascii=False),
              json.dumps(edges or [], ensure_ascii=False),
              int(time.time()), int(time.time())))
        conn.commit()
    finally:
        conn.close()
    return workflow_id


def update_workflow(workflow_id: str, **kwargs) -> bool:
    """更新工作流"""
    conn = get_connection()
    try:
        allowed_fields = ['name', 'description', 'nodes', 'edges', 'is_active']
        updates = []
        params = []
        for key, value in kwargs.items():
            if key in allowed_fields:
                updates.append(f'{key} = ?')
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                params.append(value)
        if not updates:
            return False
        updates.append('updated_at = ?')
        params.append(int(time.time()))
        params.append(workflow_id)
        conn.execute(f'UPDATE workflows SET {', '.join(updates)} WHERE workflow_id = ?', params)
        conn.commit()
        return True
    finally:
        conn.close()


def get_workflow(workflow_id: str) -> Optional[Dict]:
    """获取工作流"""
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM workflows WHERE workflow_id = ?', (workflow_id,)).fetchone()
        if row:
            data = dict(row)
            if data.get('nodes'):
                data['nodes'] = json.loads(data['nodes'])
            if data.get('edges'):
                data['edges'] = json.loads(data['edges'])
            return data
        return None
    finally:
        conn.close()


def list_workflows(user_id: str) -> List[Dict]:
    """列出用户的工作流"""
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT workflow_id, name, description, is_active, created_at, updated_at
            FROM workflows
            WHERE user_id = ?
            ORDER BY updated_at DESC
        ''', (user_id,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_workflow(workflow_id: str) -> bool:
    """删除工作流"""
    conn = get_connection()
    try:
        conn.execute('DELETE FROM workflows WHERE workflow_id = ?', (workflow_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ============================ 工作流运行 ============================

def create_workflow_run(workflow_id: str, user_id: str,
                        trigger_type: str = 'manual') -> str:
    """创建工作流运行记录"""
    run_id = f'run_{uuid.uuid4().hex[:16]}'
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO workflow_runs (run_id, workflow_id, user_id, trigger_type, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (run_id, workflow_id, user_id, trigger_type, 'pending', int(time.time())))
        conn.commit()
    finally:
        conn.close()
    return run_id


def update_workflow_run(run_id: str, **kwargs) -> bool:
    """更新工作流运行记录"""
    conn = get_connection()
    try:
        allowed_fields = ['status', 'result', 'error_message', 'started_at', 'completed_at']
        updates = []
        params = []
        for key, value in kwargs.items():
            if key in allowed_fields:
                updates.append(f'{key} = ?')
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                params.append(value)
        if not updates:
            return False
        params.append(run_id)
        conn.execute(f'UPDATE workflow_runs SET {', '.join(updates)} WHERE run_id = ?', params)
        conn.commit()
        return True
    finally:
        conn.close()


def list_workflow_runs(workflow_id: str, limit: int = 20) -> List[Dict]:
    """列出工作流的运行记录"""
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT * FROM workflow_runs
            WHERE workflow_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (workflow_id, limit)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ============================ Agent 记忆 ============================

def save_memory(user_id: str, content: str, memory_type: str = 'general',
                metadata: Dict = None) -> str:
    """保存Agent记忆"""
    memory_id = f'mem_{uuid.uuid4().hex[:16]}'
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO agent_memories (memory_id, user_id, content, memory_type, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (memory_id, user_id, content, memory_type,
              json.dumps(metadata or {}, ensure_ascii=False), int(time.time())))
        conn.commit()
    finally:
        conn.close()
    return memory_id


def search_memories(user_id: str, query: str, limit: int = 10) -> List[Dict]:
    """搜索Agent记忆（简单的关键词匹配）"""
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT * FROM agent_memories
            WHERE user_id = ? AND content LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (user_id, f'%{query}%', limit)).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            if data.get('metadata'):
                data['metadata'] = json.loads(data['metadata'])
            results.append(data)
        return results
    finally:
        conn.close()


def list_memories(user_id: str, memory_type: str = None, limit: int = 50) -> List[Dict]:
    """列出Agent记忆"""
    conn = get_connection()
    try:
        if memory_type:
            rows = conn.execute('''
                SELECT * FROM agent_memories
                WHERE user_id = ? AND memory_type = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (user_id, memory_type, limit)).fetchall()
        else:
            rows = conn.execute('''
                SELECT * FROM agent_memories
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (user_id, limit)).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            if data.get('metadata'):
                data['metadata'] = json.loads(data['metadata'])
            results.append(data)
        return results
    finally:
        conn.close()


def delete_memory(memory_id: str) -> bool:
    """删除Agent记忆"""
    conn = get_connection()
    try:
        conn.execute('DELETE FROM agent_memories WHERE memory_id = ?', (memory_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ============================ Agent 指标 ============================

def record_metric(user_id: str, metric_name: str, value: float,
                  tags: Dict = None) -> str:
    """记录Agent指标"""
    metric_id = f'metric_{uuid.uuid4().hex[:16]}'
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO agent_metrics (metric_id, user_id, metric_name, value, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (metric_id, user_id, metric_name, value,
              json.dumps(tags or {}, ensure_ascii=False), int(time.time())))
        conn.commit()
    finally:
        conn.close()
    return metric_id


def get_metrics(user_id: str, metric_name: str = None,
                start_time: int = None, end_time: int = None) -> List[Dict]:
    """获取Agent指标"""
    conn = get_connection()
    try:
        query = 'SELECT * FROM agent_metrics WHERE user_id = ?'
        params = [user_id]
        if metric_name:
            query += ' AND metric_name = ?'
            params.append(metric_name)
        if start_time:
            query += ' AND created_at >= ?'
            params.append(start_time)
        if end_time:
            query += ' AND created_at <= ?'
            params.append(end_time)
        query += ' ORDER BY created_at DESC LIMIT 1000'
        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            if data.get('tags'):
                data['tags'] = json.loads(data['tags'])
            results.append(data)
        return results
    finally:
        conn.close()