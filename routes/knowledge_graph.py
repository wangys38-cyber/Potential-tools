"""研发知识图谱 Blueprint — 节点管理、关系构建、智能查询、数据导入、知识抽取、推理、导出"""
import os
import re
import csv
import io
import json
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from collections import defaultdict, deque

from flask import Blueprint, request, jsonify, g, Response

import db
import ai_utils

logger = logging.getLogger(__name__)

bp = Blueprint('knowledge_graph', __name__)

get_ai_config = ai_utils.get_ai_config
_call_ai = ai_utils.call_ai

# 节点类型定义
NODE_TYPES = {
    'bug': {'label': 'Bug/问题', 'color': '#ff3b30', 'icon': '🐛'},
    'requirement': {'label': '需求/Feature', 'color': '#007aff', 'icon': '📋'},
    'module': {'label': '模块', 'color': '#34c759', 'icon': '📦'},
    'person': {'label': '人员/研发', 'color': '#af52de', 'icon': '👤'},
    'version': {'label': '版本', 'color': '#ff9500', 'icon': '🏷️'},
    'testcase': {'label': '测试用例', 'color': '#5ac8fa', 'icon': '✅'},
    'risk': {'label': '风险', 'color': '#ff2d55', 'icon': '⚠️'}
}

# 关系类型定义
RELATION_TYPES = {
    'related': {'label': '关联', 'color': '#8e8e93'},
    'assigned': {'label': '负责', 'color': '#af52de'},
    'depends': {'label': '依赖', 'color': '#ff9500'},
    'blocks': {'label': '阻塞', 'color': '#ff3b30'},
    'caused': {'label': '导致', 'color': '#ff2d55'},
    'fixed': {'label': '修复', 'color': '#34c759'},
    'tested': {'label': '测试', 'color': '#5ac8fa'},
    'part_of': {'label': '属于', 'color': '#007aff'}
}


def get_graph_db_path():
    """获取知识图谱数据库路径"""
    data_dir = os.environ.get('DATA_DIR', '/app/data')
    if not os.path.exists(data_dir):
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, 'knowledge_graph.json')


def load_graph(user_id=None):
    """加载知识图谱数据"""
    path = get_graph_db_path()
    if not os.path.exists(path):
        return {'nodes': [], 'relations': [], 'metadata': {'created_at': datetime.now().isoformat()}}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if user_id:
            # 按用户过滤
            data['nodes'] = [n for n in data.get('nodes', []) if n.get('user_id') == user_id or not n.get('user_id')]
            data['relations'] = [r for r in data.get('relations', []) if r.get('user_id') == user_id or not r.get('user_id')]
        return data
    except Exception as e:
        logger.error(f'加载知识图谱失败: {e}')
        return {'nodes': [], 'relations': [], 'metadata': {'created_at': datetime.now().isoformat()}}


def save_graph(graph_data):
    """保存知识图谱数据"""
    path = get_graph_db_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f'保存知识图谱失败: {e}')
        return False


def generate_node_id():
    """生成节点 ID"""
    return f"node_{int(time.time() * 1000)}_{os.urandom(2).hex()}"


def generate_relation_id():
    """生成关系 ID"""
    return f"rel_{int(time.time() * 1000)}_{os.urandom(2).hex()}"


# ==================== 节点管理 ====================

@bp.route('/api/kg/nodes', methods=['GET'])
def get_nodes():
    """获取所有节点"""
    user_id = getattr(g, 'user_id', None)
    graph = load_graph(user_id)
    node_type = request.args.get('type')
    if node_type:
        nodes = [n for n in graph['nodes'] if n.get('type') == node_type]
    else:
        nodes = graph['nodes']
    return jsonify({'nodes': nodes, 'total': len(nodes)})


@bp.route('/api/kg/nodes', methods=['POST'])
def create_node():
    """创建节点"""
    user_id = getattr(g, 'user_id', None)
    data = request.json or {}
    node_type = data.get('type')
    name = data.get('name')
    if not node_type or not name:
        return jsonify({'error': '节点类型和名称不能为空'}), 400
    if node_type not in NODE_TYPES:
        return jsonify({'error': f'不支持的节点类型: {node_type}'}), 400

    graph = load_graph()
    node = {
        'id': generate_node_id(),
        'type': node_type,
        'name': name,
        'description': data.get('description', ''),
        'properties': data.get('properties', {}),
        'user_id': user_id,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    graph['nodes'].append(node)
    save_graph(graph)
    return jsonify({'node': node, 'message': '节点创建成功'})


@bp.route('/api/kg/nodes/<node_id>', methods=['PUT'])
def update_node(node_id):
    """更新节点"""
    user_id = getattr(g, 'user_id', None)
    data = request.json or {}
    graph = load_graph()
    for node in graph['nodes']:
        if node['id'] == node_id:
            if 'name' in data:
                node['name'] = data['name']
            if 'description' in data:
                node['description'] = data['description']
            if 'properties' in data:
                node['properties'].update(data['properties'])
            node['updated_at'] = datetime.now().isoformat()
            save_graph(graph)
            return jsonify({'node': node, 'message': '节点更新成功'})
    return jsonify({'error': '节点不存在'}), 404


@bp.route('/api/kg/nodes/<node_id>', methods=['DELETE'])
def delete_node(node_id):
    """删除节点"""
    graph = load_graph()
    original_count = len(graph['nodes'])
    graph['nodes'] = [n for n in graph['nodes'] if n['id'] != node_id]
    # 同时删除相关关系
    graph['relations'] = [r for r in graph['relations'] if r['source'] != node_id and r['target'] != node_id]
    if len(graph['nodes']) == original_count:
        return jsonify({'error': '节点不存在'}), 404
    save_graph(graph)
    return jsonify({'message': '节点删除成功'})


# ==================== 关系管理 ====================

@bp.route('/api/kg/relations', methods=['GET'])
def get_relations():
    """获取所有关系"""
    user_id = getattr(g, 'user_id', None)
    graph = load_graph(user_id)
    return jsonify({'relations': graph['relations'], 'total': len(graph['relations'])})


@bp.route('/api/kg/relations', methods=['POST'])
def create_relation():
    """创建关系"""
    user_id = getattr(g, 'user_id', None)
    data = request.json or {}
    source = data.get('source')
    target = data.get('target')
    rel_type = data.get('type')
    if not source or not target or not rel_type:
        return jsonify({'error': '源节点、目标节点和关系类型不能为空'}), 400
    if rel_type not in RELATION_TYPES:
        return jsonify({'error': f'不支持的关系类型: {rel_type}'}), 400

    graph = load_graph()
    # 检查节点是否存在
    source_exists = any(n['id'] == source for n in graph['nodes'])
    target_exists = any(n['id'] == target for n in graph['nodes'])
    if not source_exists or not target_exists:
        return jsonify({'error': '源节点或目标节点不存在'}), 400

    relation = {
        'id': generate_relation_id(),
        'source': source,
        'target': target,
        'type': rel_type,
        'description': data.get('description', ''),
        'user_id': user_id,
        'created_at': datetime.now().isoformat()
    }
    graph['relations'].append(relation)
    save_graph(graph)
    return jsonify({'relation': relation, 'message': '关系创建成功'})


@bp.route('/api/kg/relations/<relation_id>', methods=['DELETE'])
def delete_relation(relation_id):
    """删除关系"""
    graph = load_graph()
    original_count = len(graph['relations'])
    graph['relations'] = [r for r in graph['relations'] if r['id'] != relation_id]
    if len(graph['relations']) == original_count:
        return jsonify({'error': '关系不存在'}), 404
    save_graph(graph)
    return jsonify({'message': '关系删除成功'})


# ==================== 图谱查询 ====================

@bp.route('/api/kg/graph', methods=['GET'])
def get_full_graph():
    """获取完整图谱数据"""
    user_id = getattr(g, 'user_id', None)
    graph = load_graph(user_id)
    return jsonify({
        'nodes': graph['nodes'],
        'relations': graph['relations'],
        'nodeTypes': NODE_TYPES,
        'relationTypes': RELATION_TYPES,
        'stats': {
            'totalNodes': len(graph['nodes']),
            'totalRelations': len(graph['relations']),
            'nodesByType': {t: len([n for n in graph['nodes'] if n['type'] == t]) for t in NODE_TYPES}
        }
    })


@bp.route('/api/kg/node/<node_id>/neighbors', methods=['GET'])
def get_node_neighbors(node_id):
    """获取节点的邻居节点"""
    user_id = getattr(g, 'user_id', None)
    graph = load_graph(user_id)
    depth = int(request.args.get('depth', 1))

    # BFS 查找邻居
    visited = {node_id}
    current_level = {node_id}
    all_neighbors = []

    for _ in range(depth):
        next_level = set()
        for rel in graph['relations']:
            if rel['source'] in current_level and rel['target'] not in visited:
                next_level.add(rel['target'])
                all_neighbors.append({'node_id': rel['target'], 'relation': rel['type'], 'via': rel['source']})
            if rel['target'] in current_level and rel['source'] not in visited:
                next_level.add(rel['source'])
                all_neighbors.append({'node_id': rel['source'], 'relation': rel['type'], 'via': rel['target']})
        visited.update(next_level)
        current_level = next_level
        if not next_level:
            break

    # 获取节点详情
    neighbor_nodes = [n for n in graph['nodes'] if n['id'] in visited and n['id'] != node_id]
    return jsonify({'neighbors': neighbor_nodes, 'relations': all_neighbors, 'count': len(neighbor_nodes)})


# ==================== 数据导入 ====================

@bp.route('/api/kg/import/cr-analysis', methods=['POST'])
def import_cr_analysis():
    """从 CR 分析结果导入数据"""
    user_id = getattr(g, 'user_id', None)
    data = request.json or {}
    issues = data.get('issues', [])
    if not issues:
        return jsonify({'error': '问题数据不能为空'}), 400

    graph = load_graph()
    created_nodes = []
    created_relations = []

    for issue in issues[:50]:  # 限制最多导入50条
        # 创建 Bug 节点
        bug_node = {
            'id': generate_node_id(),
            'type': 'bug',
            'name': issue.get('key', issue.get('summary', 'Unknown Bug')),
            'description': issue.get('summary', ''),
            'properties': {
                'severity': issue.get('severity', ''),
                'status': issue.get('status', ''),
                'module': issue.get('module', ''),
                'assignee': issue.get('assignee', '')
            },
            'user_id': user_id,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        graph['nodes'].append(bug_node)
        created_nodes.append(bug_node)

        # 创建/关联模块节点
        module_name = issue.get('module', '')
        if module_name:
            module_node = next((n for n in graph['nodes'] if n['type'] == 'module' and n['name'] == module_name), None)
            if not module_node:
                module_node = {
                    'id': generate_node_id(),
                    'type': 'module',
                    'name': module_name,
                    'description': f'{module_name} 模块',
                    'properties': {},
                    'user_id': user_id,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                graph['nodes'].append(module_node)
                created_nodes.append(module_node)

            # 创建 Bug 属于模块的关系
            rel = {
                'id': generate_relation_id(),
                'source': bug_node['id'],
                'target': module_node['id'],
                'type': 'part_of',
                'description': f'Bug 属于 {module_name} 模块',
                'user_id': user_id,
                'created_at': datetime.now().isoformat()
            }
            graph['relations'].append(rel)
            created_relations.append(rel)

        # 创建/关联人员节点
        assignee = issue.get('assignee', '')
        if assignee:
            person_node = next((n for n in graph['nodes'] if n['type'] == 'person' and n['name'] == assignee), None)
            if not person_node:
                person_node = {
                    'id': generate_node_id(),
                    'type': 'person',
                    'name': assignee,
                    'description': f'{assignee} 研发人员',
                    'properties': {},
                    'user_id': user_id,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                graph['nodes'].append(person_node)
                created_nodes.append(person_node)

            # 创建人员负责 Bug 的关系
            rel = {
                'id': generate_relation_id(),
                'source': person_node['id'],
                'target': bug_node['id'],
                'type': 'assigned',
                'description': f'{assignee} 负责此 Bug',
                'user_id': user_id,
                'created_at': datetime.now().isoformat()
            }
            graph['relations'].append(rel)
            created_relations.append(rel)

    save_graph(graph)
    return jsonify({
        'message': f'成功导入 {len(issues[:50])} 条问题数据',
        'createdNodes': len(created_nodes),
        'createdRelations': len(created_relations)
    })


# ==================== 智能问答 ====================
# 注意：intelligent_query 的增强版定义在文件后部（支持多跳推理和答案溯源）


# ==================== 图谱统计 ====================

@bp.route('/api/kg/stats', methods=['GET'])
def get_graph_stats():
    """获取图谱统计信息"""
    user_id = getattr(g, 'user_id', None)
    graph = load_graph(user_id)

    # 节点度数统计
    node_degrees = {}
    for rel in graph['relations']:
        node_degrees[rel['source']] = node_degrees.get(rel['source'], 0) + 1
        node_degrees[rel['target']] = node_degrees.get(rel['target'], 0) + 1

    # 度数最高的节点（核心节点）
    top_nodes = sorted(node_degrees.items(), key=lambda x: x[1], reverse=True)[:10]
    core_nodes = []
    for node_id, degree in top_nodes:
        node = next((n for n in graph['nodes'] if n['id'] == node_id), None)
        if node:
            core_nodes.append({'name': node['name'], 'type': node['type'], 'degree': degree})

    return jsonify({
        'totalNodes': len(graph['nodes']),
        'totalRelations': len(graph['relations']),
        'nodesByType': {t: len([n for n in graph['nodes'] if n['type'] == t]) for t in NODE_TYPES},
        'relationsByType': {t: len([r for r in graph['relations'] if r['type'] == t]) for t in RELATION_TYPES},
        'coreNodes': core_nodes,
        'isolatedNodes': len([n for n in graph['nodes'] if node_degrees.get(n['id'], 0) == 0])
    })


# ==================== 自动知识抽取 ====================

@bp.route('/api/kg/extract', methods=['POST'])
def extract_knowledge():
    """从文本中自动抽取实体和关系，返回预览结果供用户确认"""
    user_id = getattr(g, 'user_id', None)
    data = request.json or {}
    text = data.get('text', '')
    source_type = data.get('source_type', 'general')  # cr_analysis / log / meeting / general

    if not text or len(text.strip()) < 10:
        return jsonify({'error': '文本内容不能为空或过短'}), 400

    # 根据来源类型构建抽取提示
    type_instructions = {
        'cr_analysis': """抽取以下类型实体和关系：
- Bug节点：问题编号、标题、严重程度、状态
- 模块节点：所属模块/组件
- 人员节点：负责人/开发/测试人员
- 版本节点：涉及版本号
- 关系：负责(assigned)、属于(part_of)、阻塞(blocks)、依赖(depends)""",
        'log': """抽取以下类型实体和关系：
- 异常事件节点：错误/异常描述
- 模块节点：出错模块/服务
- 错误类型节点：错误分类（如空指针、超时、越界等）
- 关系：导致(caused)、属于(part_of)、关联(related)""",
        'meeting': """抽取以下类型实体和关系：
- 待办事项节点：行动项/任务描述
- 负责人节点：任务负责人
- 项目节点：所属项目/模块
- 关系：负责(assigned)、属于(part_of)、关联(related)、阻塞(blocks)""",
        'general': """抽取研发相关的实体和关系：
- 节点类型：bug、requirement、module、person、version、testcase、risk
- 关系类型：assigned、part_of、blocks、depends、caused、fixed、tested、related"""
    }

    prompt = f"""你是一位研发知识图谱抽取专家。请从以下文本中抽取实体和关系，构建知识图谱。

{type_instructions.get(source_type, type_instructions['general'])}

【输入文本】
{text[:8000]}

【输出要求】
严格输出JSON格式，不要包含任何其他文字或markdown标记：
{{
  "nodes": [
    {{"type": "bug", "name": "节点名称", "description": "描述", "properties": {{"key": "value"}}}}
  ],
  "relations": [
    {{"source": "源节点名称", "target": "目标节点名称", "type": "关系类型", "description": "关系描述"}}
  ]
}}

注意：
1. relations中的source和target必须是nodes中已有的节点name
2. 只抽取文本中明确提到的实体和关系，不要编造
3. 节点名称要简洁准确
4. 如果文本中没有可抽取的内容，返回空的nodes和relations数组"""

    messages = [
        {'role': 'system', 'content': '你是一位专业的知识图谱抽取引擎，只输出JSON格式的抽取结果。'},
        {'role': 'user', 'content': prompt}
    ]

    try:
        ai_config = get_ai_config()
        result = _call_ai(messages, model=ai_config.get('model'), max_tokens=3000, temperature=0.2, timeout=90)

        # 解析JSON结果
        result = result.strip()
        # 去除可能的markdown代码块标记
        if result.startswith('```'):
            result = re.sub(r'^```(?:json)?\s*', '', result)
            result = re.sub(r'\s*```$', '', result)

        extracted = json.loads(result)
        nodes = extracted.get('nodes', [])
        relations = extracted.get('relations', [])

        # 校验关系引用的节点是否存在
        node_names = {n['name'] for n in nodes}
        valid_relations = [r for r in relations if r.get('source') in node_names and r.get('target') in node_names]

        return jsonify({
            'nodes': nodes,
            'relations': valid_relations,
            'totalNodes': len(nodes),
            'totalRelations': len(valid_relations),
            'source_type': source_type
        })
    except json.JSONDecodeError as e:
        logger.error(f'抽取结果JSON解析失败: {e}, result: {result[:500]}')
        return jsonify({'error': 'AI返回结果格式异常，请重试'}), 500
    except Exception as e:
        logger.error(f'知识抽取失败: {e}')
        return jsonify({'error': f'知识抽取失败: {str(e)}'}), 500


@bp.route('/api/kg/extract/confirm', methods=['POST'])
def confirm_extraction():
    """确认抽取结果并添加到图谱"""
    user_id = getattr(g, 'user_id', None)
    data = request.json or {}
    nodes = data.get('nodes', [])
    relations = data.get('relations', [])

    if not nodes:
        return jsonify({'error': '没有要添加的节点'}), 400

    graph = load_graph()
    created_nodes = []
    name_to_id = {}

    # 创建节点（去重：同类型同名节点复用）
    for n in nodes:
        node_type = n.get('type')
        name = n.get('name')
        if not node_type or not name or node_type not in NODE_TYPES:
            continue

        # 检查是否已存在同类型同名节点
        existing = next((x for x in graph['nodes']
                         if x.get('type') == node_type and x.get('name') == name
                         and (x.get('user_id') == user_id or not x.get('user_id'))), None)
        if existing:
            name_to_id[name] = existing['id']
            continue

        node = {
            'id': generate_node_id(),
            'type': node_type,
            'name': name,
            'description': n.get('description', ''),
            'properties': n.get('properties', {}),
            'user_id': user_id,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        graph['nodes'].append(node)
        created_nodes.append(node)
        name_to_id[name] = node['id']

    # 创建关系
    created_relations = []
    for r in relations:
        source_name = r.get('source')
        target_name = r.get('target')
        rel_type = r.get('type')
        if not source_name or not target_name or not rel_type:
            continue
        if rel_type not in RELATION_TYPES:
            continue
        source_id = name_to_id.get(source_name)
        target_id = name_to_id.get(target_name)
        if not source_id or not target_id or source_id == target_id:
            continue

        # 检查重复关系
        exists = any(x['source'] == source_id and x['target'] == target_id and x['type'] == rel_type
                     for x in graph['relations'])
        if exists:
            continue

        relation = {
            'id': generate_relation_id(),
            'source': source_id,
            'target': target_id,
            'type': rel_type,
            'description': r.get('description', ''),
            'user_id': user_id,
            'created_at': datetime.now().isoformat()
        }
        graph['relations'].append(relation)
        created_relations.append(relation)

    save_graph(graph)
    return jsonify({
        'message': f'成功添加 {len(created_nodes)} 个节点，{len(created_relations)} 个关系',
        'createdNodes': len(created_nodes),
        'createdRelations': len(created_relations)
    })


# ==================== 多跳推理问答 ====================

def _build_adjacency(graph):
    """构建邻接表（无向）"""
    adj = defaultdict(set)
    for rel in graph['relations']:
        adj[rel['source']].add(rel['target'])
        adj[rel['target']].add(rel['source'])
    return adj


def _bfs_paths(adj, start, end, max_depth=5):
    """BFS查找两节点间所有路径"""
    if start == end:
        return [[start]]
    paths = []
    queue = deque([(start, [start])])
    visited_paths = set()
    while queue:
        current, path = queue.popleft()
        if len(path) > max_depth:
            continue
        for neighbor in adj.get(current, set()):
            if neighbor in path:
                continue
            new_path = path + [neighbor]
            path_key = tuple(new_path)
            if path_key in visited_paths:
                continue
            visited_paths.add(path_key)
            if neighbor == end:
                paths.append(new_path)
                if len(paths) >= 10:
                    return paths
            else:
                queue.append((neighbor, new_path))
    return paths


def _multi_hop_reasoning(graph, question):
    """基于图谱的多跳推理，返回推理路径和依据"""
    node_map = {n['id']: n for n in graph['nodes']}
    adj = _build_adjacency(graph)

    # 识别问题中的实体关键词
    q_lower = question.lower()
    matched_nodes = []
    for node in graph['nodes']:
        name = node['name'].lower()
        if name and (name in q_lower or q_lower in name):
            matched_nodes.append(node)

    # 关键词匹配（更宽松）
    if not matched_nodes:
        keywords = re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]+', question)
        for kw in keywords:
            if len(kw) < 2:
                continue
            for node in graph['nodes']:
                if kw.lower() in node['name'].lower() and node not in matched_nodes:
                    matched_nodes.append(node)

    reasoning_steps = []
    evidence_nodes = set()
    evidence_relations = []

    # 分析问题类型
    is_count = any(w in question for w in ['多少', '几个', '最多', '统计', '数量', 'count'])
    is_who = any(w in question for w in ['谁', '哪个', '哪位', 'who'])
    is_relation = any(w in question for w in ['关系', '关联', '路径', '联系', '怎么到'])
    is_module = any(w in question for w in ['模块', 'module', '组件'])
    is_bug = any(w in question for w in ['bug', '问题', '缺陷', '故障'])

    # 对匹配到的节点进行多跳扩展
    for mn in matched_nodes[:3]:
        evidence_nodes.add(mn['id'])
        reasoning_steps.append(f"识别到实体: [{mn['type']}] {mn['name']}")

        # 一跳邻居
        one_hop = adj.get(mn['id'], set())
        for nid in one_hop:
            evidence_nodes.add(nid)
            for rel in graph['relations']:
                if (rel['source'] == mn['id'] and rel['target'] == nid) or \
                   (rel['target'] == mn['id'] and rel['source'] == nid):
                    evidence_relations.append(rel)

        # 二跳扩展（如果问题涉及多跳）
        if is_count or is_who or is_module:
            for nid in list(one_hop)[:10]:
                two_hop = adj.get(nid, set()) - one_hop - {mn['id']}
                for tid in list(two_hop)[:5]:
                    evidence_nodes.add(tid)
                    for rel in graph['relations']:
                        if (rel['source'] == nid and rel['target'] == tid) or \
                           (rel['target'] == nid and rel['source'] == tid):
                            evidence_relations.append(rel)
            reasoning_steps.append(f"执行二跳推理，扩展到 {len(evidence_nodes)} 个相关节点")

    # 统计分析
    analysis_result = {}
    if is_count and evidence_nodes:
        # 按类型统计
        type_count = defaultdict(int)
        for nid in evidence_nodes:
            node = node_map.get(nid)
            if node:
                type_count[node['type']] += 1
        analysis_result['typeDistribution'] = dict(type_count)

        # 人员-Bug统计
        if is_bug or is_who:
            person_bugs = defaultdict(list)
            for rel in graph['relations']:
                if rel['type'] == 'assigned':
                    person = node_map.get(rel['source'])
                    bug = node_map.get(rel['target'])
                    if person and bug and bug['type'] == 'bug':
                        person_bugs[person['name']].append(bug['name'])
            if person_bugs:
                sorted_persons = sorted(person_bugs.items(), key=lambda x: len(x[1]), reverse=True)
                analysis_result['personBugCount'] = [
                    {'person': p, 'count': len(bugs), 'bugs': bugs[:5]}
                    for p, bugs in sorted_persons[:10]
                ]

        # 模块-Bug统计
        if is_module:
            module_bugs = defaultdict(list)
            for rel in graph['relations']:
                if rel['type'] == 'part_of':
                    bug = node_map.get(rel['source'])
                    module = node_map.get(rel['target'])
                    if bug and module and bug['type'] == 'bug' and module['type'] == 'module':
                        module_bugs[module['name']].append(bug['name'])
            if module_bugs:
                sorted_modules = sorted(module_bugs.items(), key=lambda x: len(x[1]), reverse=True)
                analysis_result['moduleBugCount'] = [
                    {'module': m, 'count': len(bugs), 'bugs': bugs[:5]}
                    for m, bugs in sorted_modules[:10]
                ]

    # 路径分析
    if is_relation and len(matched_nodes) >= 2:
        paths = _bfs_paths(adj, matched_nodes[0]['id'], matched_nodes[1]['id'])
        if paths:
            path_names = []
            for p in paths[:3]:
                path_names.append([node_map.get(nid, {}).get('name', nid) for nid in p])
            analysis_result['paths'] = path_names
            reasoning_steps.append(f"找到 {len(paths)} 条连接路径")

    return {
        'matchedNodes': [{'id': n['id'], 'name': n['name'], 'type': n['type']} for n in matched_nodes[:5]],
        'reasoningSteps': reasoning_steps,
        'evidenceNodes': [{'id': nid, 'name': node_map.get(nid, {}).get('name', ''),
                           'type': node_map.get(nid, {}).get('type', '')} for nid in list(evidence_nodes)[:30]],
        'evidenceRelations': [{'source': node_map.get(r['source'], {}).get('name', r['source']),
                               'target': node_map.get(r['target'], {}).get('name', r['target']),
                               'type': r['type']} for r in evidence_relations[:30]],
        'analysis': analysis_result
    }


@bp.route('/api/kg/query', methods=['POST'])
def intelligent_query():
    """智能问答 - 支持多跳推理和答案溯源"""
    user_id = getattr(g, 'user_id', None)
    data = request.json or {}
    question = data.get('question', '')
    if not question:
        return jsonify({'error': '问题不能为空'}), 400

    graph = load_graph(user_id)

    if not graph['nodes']:
        return jsonify({'answer': '当前知识图谱为空，请先导入或添加节点数据。', 'reasoning': None})

    # 执行多跳推理
    reasoning = _multi_hop_reasoning(graph, question)

    # 构建图谱摘要（限制长度）
    nodes_summary = '\n'.join([
        f"- [{n['type']}] {n['name']}: {n.get('description', '')[:80]}"
        for n in graph['nodes'][:80]
    ])
    relations_summary = '\n'.join([
        f"- {next((n['name'] for n in graph['nodes'] if n['id'] == r['source']), r['source'])} "
        f"--[{r['type']}]--> "
        f"{next((n['name'] for n in graph['nodes'] if n['id'] == r['target']), r['target'])}"
        for r in graph['relations'][:80]
    ])

    # 构建推理分析摘要
    analysis_text = ''
    if reasoning.get('analysis'):
        a = reasoning['analysis']
        if 'personBugCount' in a:
            analysis_text += '\n【人员Bug统计】\n'
            for item in a['personBugCount'][:5]:
                analysis_text += f"- {item['person']}: {item['count']}个Bug\n"
        if 'moduleBugCount' in a:
            analysis_text += '\n【模块Bug统计】\n'
            for item in a['moduleBugCount'][:5]:
                analysis_text += f"- {item['module']}: {item['count']}个Bug\n"
        if 'paths' in a:
            analysis_text += '\n【路径分析】\n'
            for i, p in enumerate(a['paths'][:3]):
                analysis_text += f"路径{i+1}: {' -> '.join(p)}\n"
        if 'typeDistribution' in a:
            analysis_text += f"\n【相关节点类型分布】{json.dumps(a['typeDistribution'], ensure_ascii=False)}\n"

    prompt = f"""你是一位研发知识图谱智能助手。请根据以下知识图谱数据和推理分析结果回答用户问题。

【图谱统计】
- 总节点数: {len(graph['nodes'])}
- 总关系数: {len(graph['relations'])}
- 节点类型分布: {', '.join([f'{t}:{len([n for n in graph["nodes"] if n["type"] == t])}' for t in NODE_TYPES])}

【推理分析结果】
匹配实体: {', '.join([f"[{n['type']}]{n['name']}" for n in reasoning.get('matchedNodes', [])]) or '无'}
推理步骤: {'; '.join(reasoning.get('reasoningSteps', [])) or '无'}
{analysis_text}

【节点列表（前80个）】
{nodes_summary if nodes_summary else '无节点数据'}

【关系列表（前80个）】
{relations_summary if relations_summary else '无关系数据'}

【用户问题】
{question}

请根据图谱数据和推理分析回答用户问题，要求：
1. 基于图谱中的真实数据回答，不要编造不存在的信息
2. 如果图谱中没有相关数据，明确告知用户
3. 回答简洁专业，突出关键信息和数据
4. 可以引用具体的节点名称和关系
5. 语言简洁，不要AI味，不要客套话"""

    messages = [
        {'role': 'system', 'content': '你是一位研发知识图谱智能助手，擅长从图谱数据中提取信息并回答用户问题。'},
        {'role': 'user', 'content': prompt}
    ]

    try:
        ai_config = get_ai_config()
        result = _call_ai(messages, model=ai_config.get('model'), max_tokens=2000, temperature=0.3, timeout=60)
        return jsonify({
            'answer': result or '（无回答）',
            'reasoning': reasoning
        })
    except Exception as e:
        logger.error(f'知识图谱智能问答失败: {e}')
        # 降级：仅返回推理分析结果
        fallback = 'AI问答服务暂不可用。基于图谱推理分析：\n'
        if reasoning.get('analysis', {}).get('personBugCount'):
            for item in reasoning['analysis']['personBugCount'][:5]:
                fallback += f"- {item['person']}: {item['count']}个Bug\n"
        if reasoning.get('analysis', {}).get('moduleBugCount'):
            for item in reasoning['analysis']['moduleBugCount'][:5]:
                fallback += f"- {item['module']}: {item['count']}个Bug\n"
        return jsonify({'answer': fallback, 'reasoning': reasoning})


# ==================== 知识导出 ====================

@bp.route('/api/kg/export', methods=['POST'])
def export_graph():
    """导出知识图谱数据，支持JSON/GraphML/CSV格式"""
    user_id = getattr(g, 'user_id', None)
    data = request.json or {}
    fmt = data.get('format', 'json').lower()
    scope = data.get('scope', 'all')  # all / selected / subgraph
    selected_ids = data.get('selectedIds', [])
    center_node_id = data.get('centerNodeId')
    depth = int(data.get('depth', 2))

    graph = load_graph(user_id)

    # 根据范围筛选
    if scope == 'selected' and selected_ids:
        selected_set = set(selected_ids)
        nodes = [n for n in graph['nodes'] if n['id'] in selected_set]
        relations = [r for r in graph['relations']
                     if r['source'] in selected_set and r['target'] in selected_set]
    elif scope == 'subgraph' and center_node_id:
        # BFS获取子图
        adj = _build_adjacency(graph)
        visited = {center_node_id}
        current = {center_node_id}
        for _ in range(depth):
            next_level = set()
            for nid in current:
                for neighbor in adj.get(nid, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_level.add(neighbor)
            current = next_level
            if not current:
                break
        nodes = [n for n in graph['nodes'] if n['id'] in visited]
        relations = [r for r in graph['relations']
                     if r['source'] in visited and r['target'] in visited]
    else:
        nodes = graph['nodes']
        relations = graph['relations']

    node_map = {n['id']: n for n in nodes}

    if fmt == 'json':
        export_data = {
            'metadata': {
                'exportedAt': datetime.now().isoformat(),
                'totalNodes': len(nodes),
                'totalRelations': len(relations),
                'scope': scope
            },
            'nodes': nodes,
            'relations': relations,
            'nodeTypes': NODE_TYPES,
            'relationTypes': RELATION_TYPES
        }
        return jsonify(export_data)

    elif fmt == 'graphml':
        # 构建GraphML XML
        root = ET.Element('graphml')
        root.set('xmlns', 'http://graphml.graphdrawing.org/xmlns')

        # 定义键
        keys = [
            ('d0', 'node', 'name', 'string'),
            ('d1', 'node', 'type', 'string'),
            ('d2', 'node', 'description', 'string'),
            ('d3', 'edge', 'type', 'string'),
            ('d4', 'edge', 'description', 'string'),
        ]
        for kid, domain, attr_name, attr_type in keys:
            key_elem = ET.SubElement(root, 'key')
            key_elem.set('id', kid)
            key_elem.set('for', domain)
            key_elem.set('attr.name', attr_name)
            key_elem.set('attr.type', attr_type)

        graph_elem = ET.SubElement(root, 'graph')
        graph_elem.set('id', 'knowledge_graph')
        graph_elem.set('edgedefault', 'directed')

        for node in nodes:
            node_elem = ET.SubElement(graph_elem, 'node')
            node_elem.set('id', node['id'])
            ET.SubElement(node_elem, 'data', key='d0').text = node.get('name', '')
            ET.SubElement(node_elem, 'data', key='d1').text = node.get('type', '')
            ET.SubElement(node_elem, 'data', key='d2').text = node.get('description', '')

        for rel in relations:
            edge_elem = ET.SubElement(graph_elem, 'edge')
            edge_elem.set('id', rel['id'])
            edge_elem.set('source', rel['source'])
            edge_elem.set('target', rel['target'])
            ET.SubElement(edge_elem, 'data', key='d3').text = rel.get('type', '')
            ET.SubElement(edge_elem, 'data', key='d4').text = rel.get('description', '')

        xml_str = ET.tostring(root, encoding='unicode', xml_declaration=True)
        return Response(xml_str, mimetype='application/xml',
                        headers={'Content-Disposition': 'attachment; filename=knowledge_graph.graphml'})

    elif fmt == 'csv':
        # 节点CSV
        node_buf = io.StringIO()
        node_writer = csv.writer(node_buf)
        node_writer.writerow(['id', 'name', 'type', 'description', 'properties', 'created_at'])
        for node in nodes:
            node_writer.writerow([
                node['id'],
                node.get('name', ''),
                node.get('type', ''),
                node.get('description', ''),
                json.dumps(node.get('properties', {}), ensure_ascii=False),
                node.get('created_at', '')
            ])

        # 关系CSV
        rel_buf = io.StringIO()
        rel_writer = csv.writer(rel_buf)
        rel_writer.writerow(['id', 'source', 'source_name', 'target', 'target_name', 'type', 'description', 'created_at'])
        for rel in relations:
            rel_writer.writerow([
                rel['id'],
                rel['source'],
                node_map.get(rel['source'], {}).get('name', ''),
                rel['target'],
                node_map.get(rel['target'], {}).get('name', ''),
                rel.get('type', ''),
                rel.get('description', ''),
                rel.get('created_at', '')
            ])

        return jsonify({
            'nodes_csv': node_buf.getvalue(),
            'relations_csv': rel_buf.getvalue(),
            'totalNodes': len(nodes),
            'totalRelations': len(relations)
        })

    else:
        return jsonify({'error': f'不支持的导出格式: {fmt}'}), 400
