"""db - 数据库操作包（从 db.py 拆分而来，保持向后兼容）"""
from .base import *
from .users import *
from .user_data import *
from .config import *
from .activity import *
from .uploads import *
from .collab import *
from .notes import *
from .documents import *
from .notifications import *
from .security import *
from .ai import *

# 初始化数据库
init_db()

# 执行 JSON 文件迁移（静默失败，不影响启动）
import os as _os
_runtime_dir = _os.environ.get('DB_DIR', '/tmp/toolbox')
_runtime_config_path = _os.path.join(_runtime_dir, 'ai_config.json')
if not _os.path.exists(_runtime_config_path):
    _runtime_config_path = _os.path.join(_os.path.dirname(__file__), 'ai_config.json')
try:
    migrate_json_config(_runtime_config_path, 'ai_config')
except Exception as _e:
    import logging as _logging
    _logging.getLogger(__name__).warning(f"JSON配置迁移失败: {_e}")

# 清理过期任务
try:
    cleanup_old_tasks()
except Exception as _e:
    import logging as _logging
    _logging.getLogger(__name__).warning(f"清理过期任务失败: {_e}")
