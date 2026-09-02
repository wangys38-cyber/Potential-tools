# Potential Tools API 文档

## 概述

Base URL：`https://wangys666.top`（本地开发：`http://localhost:5000`）

所有 API 返回 JSON 格式。需要登录的接口在未登录时返回 `401` 状态码和 `need_login: true`。

## 通用约定

### 请求格式

- GET 请求：参数通过 query string 传递
- POST/PUT 请求：参数通过 JSON body 传递，`Content-Type: application/json`
- 文件上传：`multipart/form-data`

### 响应格式

成功响应：
```json
{
  "status": "success",
  "data": {}
}
```

错误响应：
```json
{
  "error": "错误描述",
  "need_login": true
}
```

### 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 |
| 401 | 未登录或认证失败 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 429 | 请求过于频繁（限流） |
| 500 | 服务器内部错误 |

## 认证相关

### 登录

`POST /api/login`

请求体：
```json
{
  "username": "用户名",
  "password": "密码"
}
```

响应：
```json
{
  "status": "success",
  "user": {
    "id": 1,
    "name": "用户名",
    "nickname": "昵称",
    "role": "user"
  }
}
```

### 注册

`POST /api/register`

请求体：
```json
{
  "username": "用户名",
  "password": "密码",
  "email": "邮箱（可选）",
  "agree_privacy": true
}
```

### 登出

`POST /api/logout`

### 获取当前用户

`GET /api/user/current`

响应：
```json
{
  "status": "success",
  "user": {
    "id": 1,
    "name": "用户名",
    "nickname": "昵称",
    "provider": "local",
    "role": "user",
    "is_admin": false
  }
}
```

## 用户数据管理

### 导出个人数据

`GET /api/user/export`

需要登录。导出用户全部数据为 JSON，包含用户信息、笔记、分析记录、文档、偏好设置、活动统计。

响应：
```json
{
  "status": "success",
  "data": {
    "exported_at": 1234567890,
    "version": 1,
    "user": {},
    "notes": [],
    "analysis_records": [],
    "documents": [],
    "preferences": {},
    "activity_summary": {}
  }
}
```

### 修改密码

`POST /api/user/change-password`

需要登录，仅本地账号支持。

请求体：
```json
{
  "old_password": "当前密码",
  "new_password": "新密码（至少8位，含字母和数字）"
}
```

响应：
```json
{
  "status": "success",
  "message": "密码修改成功，其他设备已下线"
}
```

### 注销账号

`POST /api/user/delete`

需要登录。软删除账号，30 天内可恢复。

请求体：
```json
{
  "confirm": true,
  "password": "当前密码（本地账号必填）"
}
```

响应：
```json
{
  "status": "success",
  "message": "账号已标记删除，30天内可联系管理员恢复"
}
```

## 系统设置

### 获取设置

`GET /api/settings`

需要登录。返回用户的 AI 配置、飞书配置、主题偏好等。

### 保存设置

`POST /api/settings`

需要登录。

请求体：
```json
{
  "ai_api_key": "AI API Key",
  "ai_base_url": "AI API 地址",
  "ai_model": "默认模型",
  "feishu_webhook_url": "飞书 Webhook",
  "feishu_secret": "飞书签名密钥",
  "theme": "light"
}
```

### 测试 AI 连接

`POST /api/settings/test-ai`

### 测试飞书连接

`POST /api/settings/test-feishu`

### 获取推送历史

`GET /api/settings/push-history`

## 笔记 API

### 获取笔记列表

`GET /api/notes`

需要登录。支持 query 参数：`category`、`tag`、`search`、`page`、`per_page`。

### 创建笔记

`POST /api/notes`

请求体：
```json
{
  "title": "笔记标题",
  "content": "笔记内容（Markdown）",
  "category": "分类",
  "tags": ["标签1", "标签2"],
  "is_todo": false
}
```

### 获取笔记详情

`GET /api/notes/<note_uid>`

### 更新笔记

`PUT /api/notes/<note_uid>`

### 删除笔记

`DELETE /api/notes/<note_uid>`

## 数据分析 API

### CR 分析

`POST /api/analysis/cr`

需要登录。上传 Excel/CSV 文件进行 CR 分析。

请求：`multipart/form-data`，字段 `file`。

### 日志分析

`POST /api/analysis/log`

请求体：
```json
{
  "log_content": "日志内容",
  "device_type": "设备类型（可选）"
}
```

### AI 根因分析

`POST /api/analysis/ai-root-cause`

请求体：
```json
{
  "analysis_data": {},
  "model": "AI 模型（可选）"
}
```

## 知识图谱 API

### 获取图谱数据

`GET /api/knowledge-graph`

需要登录。

### 导入 CR 分析数据

`POST /api/knowledge-graph/import-cr`

### 创建节点

`POST /api/knowledge-graph/nodes`

请求体：
```json
{
  "name": "节点名称",
  "type": "Bug|需求|模块|人员|版本|测试用例|风险",
  "properties": {}
}
```

### 更新节点

`PUT /api/knowledge-graph/nodes/<node_id>`

### 删除节点

`DELETE /api/knowledge-graph/nodes/<node_id>`

### 创建关系

`POST /api/knowledge-graph/relations`

### 智能问答

`POST /api/knowledge-graph/query`

请求体：
```json
{
  "question": "自然语言问题"
}
```

## 协作 API

### 创建共享工作空间

`POST /api/collab/create`

请求体：
```json
{
  "title": "标题",
  "content_type": "工具类型",
  "content_data": {},
  "permission": "view|edit",
  "expires_in_days": 7
}
```

响应：
```json
{
  "status": "success",
  "share_code": "ABC12345",
  "share_url": "https://wangys666.top/share/ABC12345"
}
```

### 获取共享内容

`GET /api/collab/<share_code>`

### 添加评论

`POST /api/collab/<share_code>/comments`

### 获取评论

`GET /api/collab/<share_code>/comments`

### 轮询同步

`GET /api/collab/<share_code>/poll?since=<timestamp>`

## 管理员 API

所有管理员接口需要管理员权限（`@auth.admin_required`）。

### 用户管理

#### 获取用户列表

`GET /api/admin/users?page=1&per_page=20&search=关键词`

#### 更新用户状态

`PUT /api/admin/users/<user_id>/status`

请求体：
```json
{
  "status": "active|disabled"
}
```

#### 分配角色

`PUT /api/admin/users/<user_id>/role`

请求体：
```json
{
  "role": "user|admin"
}
```

### 性能监控

#### 获取性能指标

`GET /api/admin/performance`

响应：
```json
{
  "status": "success",
  "request_stats": {
    "total_requests": 1000,
    "slow_requests": 10,
    "slow_rate_pct": 1.0,
    "avg_ms": 120.5,
    "p50_ms": 80,
    "p95_ms": 350,
    "p99_ms": 800,
    "max_ms": 2000,
    "min_ms": 5,
    "sample_count": 1000
  },
  "alert_window": {
    "requests_5m": 100,
    "errors_5m": 2,
    "error_rate_pct": 2.0
  },
  "system": {
    "cpu_percent": 25.5,
    "memory_percent": 60.2,
    "disk_percent": 45.0,
    "uptime_seconds": 86400
  },
  "system_history": [],
  "slow_logs": [],
  "threshold_ms": 1000
}
```

### 告警管理

#### 获取告警历史

`GET /api/admin/alerts?limit=50&type=告警类型`

#### 标记告警已读

`PUT /api/admin/alerts/<alert_id>/read`

### 备份管理

#### 手动触发备份

`POST /api/admin/backup`

#### 获取备份列表

`GET /api/admin/backups`

#### 下载备份

`GET /api/admin/backups/<backup_id>/download`

### 审计日志

#### 获取审计日志

`GET /api/admin/audit-logs?page=1&per_page=50&user_id=1&action=login`

## 通用 API

### 健康检查

`GET /health`

响应：
```json
{
  "status": "ok",
  "timestamp": 1234567890
}
```

### 文件上传

`POST /api/upload`

需要登录。支持分块上传（大文件）。

### 文件下载

`GET /api/download/<file_id>`

### 数据同步

`GET /api/sync`

需要登录。获取用户云端同步数据。

`POST /api/sync`

需要登录。上传本地数据到云端。

## 性能指标

### 获取性能指标

`GET /api/performance-metrics`

返回请求性能统计数据。

## 限流说明

- API 接口默认限流：60 次/分钟（基于 IP）
- 登录接口：10 次/分钟（基于 IP+用户名）
- AI 相关接口：30 次/分钟（基于用户 ID）
- 超出限制返回 429 状态码

## 错误处理

所有 API 错误统一格式：
```json
{
  "error": "人类可读的错误描述",
  "code": "错误代码（可选）"
}
```

客户端应根据 HTTP 状态码和 `error` 字段展示错误信息。
