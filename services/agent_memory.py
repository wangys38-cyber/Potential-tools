# -*- coding: utf-8 -*-
"""
Agent 记忆服务
保存用户的常用指令、偏好设置、常用收件人等，供Agent规划时参考
"""
import json
import time
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# 内存中的记忆存储（生产环境可改为数据库）
_memory_store: Dict[str, List[Dict[str, Any]]] = {}

# 记忆类型常量
MEMORY_TYPE_INSTRUCTION = 'instruction'  # 常用指令
MEMORY_TYPE_PREFERENCE = 'preference'    # 偏好设置
MEMORY_TYPE_CONTACT = 'contact'          # 常用联系人
MEMORY_TYPE_PROJECT = 'project'          # 项目相关
MEMORY_TYPE_OTHER = 'other'              # 其他


def get_memory_key(user_id: Optional[str] = None) -> str:
    """获取记忆存储的key"""
    return f"user_{user_id or 'default'}"


def load_memories(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """加载用户的所有记忆"""
    key = get_memory_key(user_id)
    if key not in _memory_store:
        # 尝试从文件加载
        try:
            import os
            memory_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'agent_memory')
            os.makedirs(memory_dir, exist_ok=True)
            memory_file = os.path.join(memory_dir, f'{key}.json')
            if os.path.exists(memory_file):
                with open(memory_file, 'r', encoding='utf-8') as f:
                    _memory_store[key] = json.load(f)
            else:
                _memory_store[key] = []
        except Exception as e:
            logger.warning(f"加载记忆失败: {e}")
            _memory_store[key] = []
    return _memory_store[key]


def save_memories(memories: List[Dict[str, Any]], user_id: Optional[str] = None):
    """保存用户的记忆"""
    key = get_memory_key(user_id)
    _memory_store[key] = memories
    # 持久化到文件
    try:
        import os
        memory_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'agent_memory')
        os.makedirs(memory_dir, exist_ok=True)
        memory_file = os.path.join(memory_dir, f'{key}.json')
        with open(memory_file, 'w', encoding='utf-8') as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存记忆失败: {e}")


def add_memory(content: str, memory_type: str = MEMORY_TYPE_OTHER,
               title: Optional[str] = None, user_id: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """添加一条记忆"""
    memories = load_memories(user_id)
    memory = {
        'id': f'mem_{int(time.time())}_{len(memories)}',
        'content': content.strip(),
        'type': memory_type,
        'title': title or content[:50],
        'created_at': time.time(),
        'updated_at': time.time(),
        'usage_count': 0,
        'metadata': metadata or {}
    }
    memories.append(memory)
    save_memories(memories, user_id)
    logger.info(f"添加记忆: {memory['title']} (类型: {memory_type})")
    return memory


def delete_memory(memory_id: str, user_id: Optional[str] = None) -> bool:
    """删除一条记忆"""
    memories = load_memories(user_id)
    original_len = len(memories)
    memories = [m for m in memories if m['id'] != memory_id]
    if len(memories) < original_len:
        save_memories(memories, user_id)
        logger.info(f"删除记忆: {memory_id}")
        return True
    return False


def update_memory(memory_id: str, content: Optional[str] = None,
                  title: Optional[str] = None, memory_type: Optional[str] = None,
                  user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """更新一条记忆"""
    memories = load_memories(user_id)
    for m in memories:
        if m['id'] == memory_id:
            if content is not None:
                m['content'] = content.strip()
            if title is not None:
                m['title'] = title
            if memory_type is not None:
                m['type'] = memory_type
            m['updated_at'] = time.time()
            save_memories(memories, user_id)
            return m
    return None


def search_memories(query: str, memory_type: Optional[str] = None,
                    user_id: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """搜索记忆（简单的关键词匹配）"""
    memories = load_memories(user_id)
    query_lower = query.lower()
    
    # 按相关度排序
    scored = []
    for m in memories:
        if memory_type and m['type'] != memory_type:
            continue
        score = 0
        content_lower = m['content'].lower()
        title_lower = m['title'].lower()
        # 标题匹配权重更高
        if query_lower in title_lower:
            score += 10
        if query_lower in content_lower:
            score += 5
        # 词频匹配
        for word in query_lower.split():
            if word in content_lower:
                score += 2
        # 使用次数加权
        score += m.get('usage_count', 0) * 0.5
        if score > 0:
            scored.append((score, m))
    
    # 按分数降序排列
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:limit]]


def get_memory_context(user_id: Optional[str] = None, max_items: int = 20) -> str:
    """获取记忆的上下文文本（供Agent规划时使用）"""
    memories = load_memories(user_id)
    if not memories:
        return ''
    
    # 按类型分组
    by_type = {}
    for m in memories:
        mtype = m['type']
        if mtype not in by_type:
            by_type[mtype] = []
        by_type[mtype].append(m)
    
    lines = ['【用户记忆与偏好】']
    type_names = {
        MEMORY_TYPE_INSTRUCTION: '常用指令',
        MEMORY_TYPE_PREFERENCE: '偏好设置',
        MEMORY_TYPE_CONTACT: '常用联系人',
        MEMORY_TYPE_PROJECT: '项目相关',
        MEMORY_TYPE_OTHER: '其他记忆'
    }
    
    for mtype, items in by_type.items():
        if not items:
            continue
        lines.append(f'\n{type_names.get(mtype, mtype)}：')
        for m in items[:max_items // len(by_type) + 2]:
            lines.append(f'- {m["content"]}')
    
    return '\n'.join(lines)


def increment_usage(memory_id: str, user_id: Optional[str] = None):
    """增加记忆的使用次数"""
    memories = load_memories(user_id)
    for m in memories:
        if m['id'] == memory_id:
            m['usage_count'] = m.get('usage_count', 0) + 1
            save_memories(memories, user_id)
            break


# 免确认设置
_skip_confirmation_tools = set()


def set_skip_confirmation(tool_name: str, skip: bool = True):
    """设置某个工具是否跳过确认"""
    if skip:
        _skip_confirmation_tools.add(tool_name)
    else:
        _skip_confirmation_tools.discard(tool_name)
    # 持久化设置
    try:
        import os
        config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'agent_config')
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, 'skip_confirmation.json')
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(list(_skip_confirmation_tools), f)
    except Exception as e:
        logger.warning(f"保存免确认设置失败: {e}")


def should_skip_confirmation(tool_name: str) -> bool:
    """检查某个工具是否应该跳过确认"""
    # 懒加载
    if not _skip_confirmation_tools:
        try:
            import os
            config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'agent_config')
            config_file = os.path.join(config_dir, 'skip_confirmation.json')
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    tools = json.load(f)
                    _skip_confirmation_tools.update(tools)
        except Exception as e:
            logger.warning(f"加载免确认设置失败: {e}")
    return tool_name in _skip_confirmation_tools


def get_skip_confirmation_tools() -> List[str]:
    """获取所有跳过确认的工具列表"""
    should_skip_confirmation('')  # 触发懒加载
    return list(_skip_confirmation_tools)
