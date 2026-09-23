# -*- coding: utf-8 -*-
"""
Potential-tools 9.0 - 团队协作空间
工作空间管理、成员权限、评论@提及、操作审计
"""
import os
import json
import time
import logging
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
_WORKSPACE_PATH = os.path.join(_DATA_DIR, 'workspaces.json')
_COMMENTS_PATH = os.path.join(_DATA_DIR, 'comments.json')
_LOCK = threading.Lock()


class WorkspaceRole(Enum):
    OWNER = 'owner'        # 所有者：全部权限
    ADMIN = 'admin'        # 管理员：管理成员、配置
    EDITOR = 'editor'      # 编辑者：创建/编辑内容
    VIEWER = 'viewer'      # 查看者：只读


# 权限矩阵
PERMISSIONS = {
    WorkspaceRole.OWNER.value: ['*'],
    WorkspaceRole.ADMIN.value: ['manage_members', 'manage_settings', 'create_content', 'edit_content', 'delete_content', 'comment', 'view_audit'],
    WorkspaceRole.EDITOR.value: ['create_content', 'edit_content', 'comment'],
    WorkspaceRole.VIEWER.value: ['comment'],
}


@dataclass
class WorkspaceMember:
    """工作空间成员"""
    user_id: str
    username: str
    role: str = WorkspaceRole.VIEWER.value
    joined_at: float = field(default_factory=time.time)


@dataclass
class Workspace:
    """工作空间"""
    id: str
    name: str
    description: str = ''
    owner_id: str = ''
    members: List[WorkspaceMember] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    settings: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'owner_id': self.owner_id,
            'members': [
                {'user_id': m.user_id, 'username': m.username, 'role': m.role, 'joined_at': m.joined_at}
                for m in self.members
            ],
            'member_count': len(self.members),
            'created_at': self.created_at,
            'settings': self.settings
        }

    def get_member_role(self, user_id: str) -> Optional[str]:
        """获取用户在工作空间中的角色"""
        for m in self.members:
            if m.user_id == user_id:
                return m.role
        return None

    def has_permission(self, user_id: str, permission: str) -> bool:
        """检查用户是否有权限"""
        role = self.get_member_role(user_id)
        if not role:
            return False
        perms = PERMISSIONS.get(role, [])
        return '*' in perms or permission in perms


@dataclass
class Comment:
    """评论"""
    id: str
    workspace_id: str
    target_type: str  # note, cr, report, document
    target_id: str
    user_id: str
    username: str
    content: str
    mentions: List[str] = field(default_factory=list)  # @提及的用户ID
    created_at: float = field(default_factory=time.time)
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'workspace_id': self.workspace_id,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'user_id': self.user_id,
            'username': self.username,
            'content': self.content,
            'mentions': self.mentions,
            'created_at': self.created_at,
            'resolved': self.resolved
        }


class WorkspaceManager:
    """工作空间管理器 — 单例"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def __init__(self):
        self._workspaces: Dict[str, Workspace] = {}
        self._comments: Dict[str, Comment] = {}

    def _load(self):
        """加载工作空间和评论数据"""
        try:
            if os.path.exists(_WORKSPACE_PATH):
                with open(_WORKSPACE_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for wid, wdata in data.items():
                    members = [
                        WorkspaceMember(
                            user_id=m.get('user_id', ''),
                            username=m.get('username', ''),
                            role=m.get('role', 'viewer'),
                            joined_at=m.get('joined_at', time.time())
                        )
                        for m in wdata.get('members', [])
                    ]
                    self._workspaces[wid] = Workspace(
                        id=wid,
                        name=wdata.get('name', ''),
                        description=wdata.get('description', ''),
                        owner_id=wdata.get('owner_id', ''),
                        members=members,
                        created_at=wdata.get('created_at', time.time()),
                        settings=wdata.get('settings', {})
                    )
                logger.info(f"已加载 {len(self._workspaces)} 个工作空间")
        except Exception as e:
            logger.error(f"加载工作空间失败: {e}")

        try:
            if os.path.exists(_COMMENTS_PATH):
                with open(_COMMENTS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for cid, cdata in data.items():
                    self._comments[cid] = Comment(
                        id=cid,
                        workspace_id=cdata.get('workspace_id', ''),
                        target_type=cdata.get('target_type', ''),
                        target_id=cdata.get('target_id', ''),
                        user_id=cdata.get('user_id', ''),
                        username=cdata.get('username', ''),
                        content=cdata.get('content', ''),
                        mentions=cdata.get('mentions', []),
                        created_at=cdata.get('created_at', time.time()),
                        resolved=cdata.get('resolved', False)
                    )
        except Exception as e:
            logger.error(f"加载评论失败: {e}")

    def _save_workspaces(self):
        try:
            os.makedirs(_DATA_DIR, exist_ok=True)
            data = {wid: w.to_dict() for wid, w in self._workspaces.items()}
            with open(_WORKSPACE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存工作空间失败: {e}")

    def _save_comments(self):
        try:
            os.makedirs(_DATA_DIR, exist_ok=True)
            data = {cid: c.to_dict() for cid, c in self._comments.items()}
            with open(_COMMENTS_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存评论失败: {e}")

    # ===== 工作空间管理 =====
    def list_workspaces(self, user_id: Optional[str] = None) -> List[Workspace]:
        """列出工作空间（可按用户过滤）"""
        workspaces = list(self._workspaces.values())
        if user_id:
            workspaces = [w for w in workspaces if w.get_member_role(user_id)]
        return sorted(workspaces, key=lambda w: w.created_at, reverse=True)

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        return self._workspaces.get(workspace_id)

    def create_workspace(self, name: str, owner_id: str, owner_username: str,
                         description: str = '') -> Workspace:
        """创建工作空间"""
        with _LOCK:
            wid = f"ws_{int(time.time())}_{len(self._workspaces)}"
            ws = Workspace(
                id=wid,
                name=name,
                description=description,
                owner_id=owner_id,
                members=[WorkspaceMember(user_id=owner_id, username=owner_username, role=WorkspaceRole.OWNER.value)]
            )
            self._workspaces[wid] = ws
            self._save_workspaces()
            logger.info(f"创建工作空间: {name} ({wid})")
            return ws

    def add_member(self, workspace_id: str, user_id: str, username: str,
                   role: str = WorkspaceRole.VIEWER.value) -> bool:
        """添加成员"""
        with _LOCK:
            ws = self._workspaces.get(workspace_id)
            if not ws:
                return False
            # 检查是否已存在
            if ws.get_member_role(user_id):
                return False
            ws.members.append(WorkspaceMember(user_id=user_id, username=username, role=role))
            self._save_workspaces()
            return True

    def update_member_role(self, workspace_id: str, user_id: str, role: str) -> bool:
        """更新成员角色"""
        with _LOCK:
            ws = self._workspaces.get(workspace_id)
            if not ws:
                return False
            for m in ws.members:
                if m.user_id == user_id:
                    m.role = role
                    self._save_workspaces()
                    return True
            return False

    def remove_member(self, workspace_id: str, user_id: str) -> bool:
        """移除成员"""
        with _LOCK:
            ws = self._workspaces.get(workspace_id)
            if not ws:
                return False
            ws.members = [m for m in ws.members if m.user_id != user_id]
            self._save_workspaces()
            return True

    def delete_workspace(self, workspace_id: str) -> bool:
        """删除工作空间"""
        with _LOCK:
            if workspace_id in self._workspaces:
                del self._workspaces[workspace_id]
                self._save_workspaces()
                return True
            return False

    # ===== 评论管理 =====
    def add_comment(self, workspace_id: str, target_type: str, target_id: str,
                    user_id: str, username: str, content: str) -> Comment:
        """添加评论（自动解析@提及）"""
        with _LOCK:
            # 解析 @提及
            mentions = []
            import re
            for match in re.finditer(r'@(\w+)', content):
                mentions.append(match.group(1))

            cid = f"cm_{int(time.time())}_{len(self._comments)}"
            comment = Comment(
                id=cid,
                workspace_id=workspace_id,
                target_type=target_type,
                target_id=target_id,
                user_id=user_id,
                username=username,
                content=content,
                mentions=mentions
            )
            self._comments[cid] = comment
            self._save_comments()

            # 记录审计日志
            try:
                import db
                db.add_audit_log(user_id, 'comment_create', target_type=target_type, target_id=target_id,
                                  details=f'在{target_type}中添加评论: {content[:50]}')
            except Exception:
                pass

            return comment

    def list_comments(self, workspace_id: str, target_type: Optional[str] = None,
                      target_id: Optional[str] = None) -> List[Comment]:
        """列出评论"""
        comments = [c for c in self._comments.values() if c.workspace_id == workspace_id]
        if target_type:
            comments = [c for c in comments if c.target_type == target_type]
        if target_id:
            comments = [c for c in comments if c.target_id == target_id]
        return sorted(comments, key=lambda c: c.created_at)

    def resolve_comment(self, comment_id: str, resolved: bool = True) -> bool:
        """标记评论已解决/未解决"""
        with _LOCK:
            comment = self._comments.get(comment_id)
            if not comment:
                return False
            comment.resolved = resolved
            self._save_comments()
            return True

    def delete_comment(self, comment_id: str) -> bool:
        """删除评论"""
        with _LOCK:
            if comment_id in self._comments:
                del self._comments[comment_id]
                self._save_comments()
                return True
            return False


# 全局管理器实例
workspace_manager = WorkspaceManager()
