"""研发知识图谱 Blueprint — 节点管理、关系构建、智能查询、数据导入"""
import os
import json
import time
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, g

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

@bp.route('/api/kg/query', methods=['POST'])
def intelligent_query():
    """智能问答"""
    user_id = getattr(g, 'user_id', None)
    data = request.json or {}
    question = data.get('question', '')
    if not question:
        return jsonify({'error': '问题不能为空'}), 400

    graph = load_graph(user_id)

    # 构建图谱摘要
    nodes_summary = '\n'.join([f"- [{n['type']}] {n['name']}: {n.get('description', '')[:100]}" for n in graph['nodes'][:100]])
    relations_summary = '\n'.join([
        f"- {next((n['name'] for n in graph['nodes'] if n['id'] == r['source']), r['source'])} "
        f"--[{r['type']}]--> "
        f"{next((n['name'] for n in graph['nodes'] if n['id'] == r['target']), r['target'])}"
        for r in graph['relations'][:100]
    ])

    prompt = f"""你是一位研发知识图谱智能助手。请根据以下知识图谱数据回答用户问题。

【图谱统计】
- 总节点数: {len(graph['nodes'])}
- 总关系数: {len(graph['relations'])}
- 节点类型分布: {', '.join([f'{t}:{len([n for n in graph["nodes"] if n["type"] == t])}' for t in NODE_TYPES])}

【节点列表（前100个）】
{nodes_summary if nodes_summary else '无节点数据'}

【关系列表（前100个）】
{relations_summary if relations_summary else '无关系数据'}

【用户问题】
{question}

请根据图谱数据回答用户问题，要求：
1. 基于图谱中的真实数据回答，不要编造不存在的信息
2. 如果图谱中没有相关数据，明确告知用户
3. 回答简洁专业，突出关键信息
4. 可以给出相关节点和关系的引用
5. 语言简洁，不要AI味"""

    messages = [
        {'role': 'system', 'content': '你是一位研发知识图谱智能助手，擅长从图谱数据中提取信息并回答用户问题。'},
        {'role': 'user', 'content': prompt}
    ]

    try:
        ai_config = get_ai_config()
        result = _call_ai(messages, model=ai_config.get('model'), max_tokens=2000, temperature=0.3, timeout=60)
        return jsonify({'answer': result or '（无回答）'})
    except Exception as e:
        logger.error(f'知识图谱智能问答失败: {e}')
        return jsonify({'error': f'AI 问答失败: {str(e)}'}), 500


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
