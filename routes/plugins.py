"""
插件管理路由 v8.1
"""
import os
import json
import time
import logging
from flask import Blueprint, request, jsonify, render_template, g

from core.plugin import get_plugin_loader

logger = logging.getLogger(__name__)

bp = Blueprint('plugins', __name__, url_prefix='/api/plugins')


def _require_login():
    """简易登录检查"""
    user = getattr(g, 'user', None)
    if not user or not user.get('id'):
        return None, (jsonify({'error': '未登录'}), 401)
    return user['id'], None


@bp.route('/list', methods=['GET'])
def list_plugins():
    """获取所有插件列表"""
    loader = get_plugin_loader()
    plugins = loader.get_all_plugins()
    return jsonify({'status': 'success', 'plugins': plugins, 'count': len(plugins)})


@bp.route('/<plugin_id>/enable', methods=['POST'])
def enable_plugin(plugin_id):
    """启用插件"""
    user_id, err = _require_login()
    if err:
        return err

    loader = get_plugin_loader()
    if loader.enable_plugin(plugin_id):
        # 注册插件路由
        from app import app
        loader.register_routes(app)
        return jsonify({'status': 'success', 'message': f'插件 {plugin_id} 已启用'})
    return jsonify({'status': 'error', 'error': '启用失败'}), 500


@bp.route('/<plugin_id>/disable', methods=['POST'])
def disable_plugin(plugin_id):
    """禁用插件"""
    user_id, err = _require_login()
    if err:
        return err

    loader = get_plugin_loader()
    if loader.disable_plugin(plugin_id):
        return jsonify({'status': 'success', 'message': f'插件 {plugin_id} 已禁用'})
    return jsonify({'status': 'error', 'error': '禁用失败'}), 500


@bp.route('/<plugin_id>/settings', methods=['GET'])
def get_plugin_settings(plugin_id):
    """获取插件配置"""
    loader = get_plugin_loader()
    plugin = loader.get_plugin(plugin_id)
    if not plugin:
        return jsonify({'status': 'error', 'error': '插件未加载'}), 404

    settings = plugin.get_settings()
    schema = plugin.meta.get('settings', [])
    return jsonify({'status': 'success', 'settings': settings, 'schema': schema})


@bp.route('/<plugin_id>/settings', methods=['POST'])
def save_plugin_settings(plugin_id):
    """保存插件配置"""
    user_id, err = _require_login()
    if err:
        return err

    loader = get_plugin_loader()
    plugin = loader.get_plugin(plugin_id)
    if not plugin:
        return jsonify({'status': 'error', 'error': '插件未加载'}), 404

    data = request.get_json(silent=True) or {}
    if plugin.save_settings(data):
        plugin.on_settings_change(data)
        return jsonify({'status': 'success', 'message': '配置已保存'})
    return jsonify({'status': 'error', 'error': '保存失败'}), 500


@bp.route('/<plugin_id>/info', methods=['GET'])
def get_plugin_info(plugin_id):
    """获取插件详细信息"""
    loader = get_plugin_loader()
    plugin = loader.get_plugin(plugin_id)
    if plugin:
        return jsonify({'status': 'success', 'plugin': plugin.get_info()})

    # 尝试从元数据获取
    for meta in loader.discover_plugins():
        if meta['id'] == plugin_id:
            return jsonify({
                'status': 'success',
                'plugin': {
                    'id': meta['id'],
                    'name': meta.get('name', ''),
                    'version': meta.get('version', ''),
                    'description': meta.get('description', ''),
                    'author': meta.get('author', ''),
                    'permissions': meta.get('permissions', []),
                    'enabled': False,
                }
            })
    return jsonify({'status': 'error', 'error': '插件不存在'}), 404


@bp.route('/reload', methods=['POST'])
def reload_plugins():
    """重新加载所有插件"""
    user_id, err = _require_login()
    if err:
        return err

    loader = get_plugin_loader()
    # 卸载所有
    for pid in list(loader.plugins.keys()):
        loader.unload_plugin(pid)
    # 重新加载
    count = loader.load_all_plugins()
    # 重新注册路由
    from app import app
    loader.register_routes(app)
    return jsonify({'status': 'success', 'message': f'已重新加载 {count} 个插件', 'count': count})
