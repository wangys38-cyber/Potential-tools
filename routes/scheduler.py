"""
V9.2 定时任务路由
"""
from flask import Blueprint, request, jsonify
from services import scheduler as sched

bp = Blueprint('scheduler', __name__, url_prefix='/api/scheduler')


@bp.route('/status', methods=['GET'])
def scheduler_status():
    """获取调度器状态"""
    try:
        status = sched.get_scheduler_status()
        return jsonify({'status': 'success', 'data': status})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/start', methods=['POST'])
def start_scheduler():
    """启动调度器"""
    try:
        sched.start_scheduler()
        return jsonify({'status': 'success', 'message': '调度器已启动'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/stop', methods=['POST'])
def stop_scheduler():
    """停止调度器"""
    try:
        sched.stop_scheduler()
        return jsonify({'status': 'success', 'message': '调度器已停止'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/tasks', methods=['GET'])
def list_tasks():
    """获取所有定时任务"""
    try:
        tasks = sched.get_all_tasks()
        return jsonify({'status': 'success', 'data': {'tasks': tasks}})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/tasks', methods=['POST'])
def create_task():
    """创建定时任务"""
    try:
        data = request.get_json(silent=True) or {}
        task_type = data.get('type', '')
        project_key = data.get('project_key', '')
        freq = data.get('freq', 'daily')
        time_str = data.get('time', '18:00')
        weekday = int(data.get('weekday', 4))
        interval_minutes = int(data.get('interval_minutes', 60))
        email_recipients = data.get('email_recipients', [])
        name = data.get('name', '')
        
        if not task_type or not project_key:
            return jsonify({'status': 'error', 'error': '任务类型和项目Key不能为空'}), 400
        
        task = sched.create_task(
            task_type=task_type,
            project_key=project_key,
            freq=freq,
            time_str=time_str,
            weekday=weekday,
            interval_minutes=interval_minutes,
            email_recipients=email_recipients,
            name=name,
        )
        return jsonify({'status': 'success', 'data': {'task': task}})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/tasks/<task_id>', methods=['GET'])
def get_task(task_id):
    """获取单个定时任务"""
    try:
        task = sched.get_task(task_id)
        if not task:
            return jsonify({'status': 'error', 'error': '任务不存在'}), 404
        return jsonify({'status': 'success', 'data': {'task': task}})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/tasks/<task_id>', methods=['PUT'])
def update_task(task_id):
    """更新定时任务"""
    try:
        data = request.get_json(silent=True) or {}
        task = sched.update_task(task_id, **data)
        if not task:
            return jsonify({'status': 'error', 'error': '任务不存在'}), 404
        return jsonify({'status': 'success', 'data': {'task': task}})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    """删除定时任务"""
    try:
        sched.delete_task(task_id)
        return jsonify({'status': 'success', 'message': '任务已删除'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/tasks/<task_id>/run', methods=['POST'])
def run_task_now(task_id):
    """立即执行任务"""
    try:
        task, msg = sched.run_task_now(task_id)
        if not task:
            return jsonify({'status': 'error', 'error': msg}), 404
        return jsonify({'status': 'success', 'message': msg})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/tasks/<task_id>/toggle', methods=['POST'])
def toggle_task(task_id):
    """启用/禁用任务"""
    try:
        task = sched.get_task(task_id)
        if not task:
            return jsonify({'status': 'error', 'error': '任务不存在'}), 404
        new_enabled = not task.get('enabled', True)
        task = sched.update_task(task_id, enabled=new_enabled)
        return jsonify({'status': 'success', 'data': {'task': task, 'enabled': new_enabled}})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/logs', methods=['GET'])
def get_logs():
    """获取执行日志"""
    try:
        task_id = request.args.get('task_id')
        limit = int(request.args.get('limit', 20))
        logs = sched.get_task_logs(task_id=task_id, limit=limit)
        return jsonify({'status': 'success', 'data': {'logs': logs}})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200


@bp.route('/stats', methods=['GET'])
def get_stats():
    """获取执行统计数据（折线图用）"""
    try:
        days = int(request.args.get('days', 30))
        stats = sched.get_execution_stats(days=days)
        return jsonify({'status': 'success', 'data': stats})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 200
