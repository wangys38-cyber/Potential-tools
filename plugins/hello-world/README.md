# Hello World 示例插件

这是一个 Potential-tools 插件开发示例，演示插件的基本结构和开发流程。

## 功能
- 提供问候 API：`GET /api/plugin/hello-world/greet?name=xxx`
- 提供插件信息 API：`GET /api/plugin/hello-world/info`
- 提供自定义页面：`/plugin/hello-world/hello`
- 支持配置问候语和是否显示时间

## 目录结构
```
hello-world/
├── plugin.json          # 插件描述文件（必需）
├── backend/
│   ├── __init__.py
│   └── main.py          # 后端入口
├── frontend/
│   └── index.js         # 前端脚本（可选）
└── README.md
```

## 开发要点

### 1. plugin.json
插件描述文件，包含插件元数据、权限声明、入口配置。

### 2. 后端入口
继承 `PluginBase`，实现生命周期方法：
- `on_activate()`: 插件激活时调用，注册路由和页面
- `on_deactivate()`: 插件停用时调用
- `on_install()`: 首次安装时调用
- `on_uninstall()`: 卸载时调用

### 3. 插件 API
通过 `self.api` 访问核心功能：
- `api.add_route(path, handler, methods)`: 注册 API 路由
- `api.add_page(path, html)`: 注册前端页面
- `api.get_settings()` / `api.save_settings()`: 读写配置
- `api.query(sql)` / `api.execute(sql)`: 数据库操作
- `api.log(message)`: 记录日志

### 4. 权限声明
在 plugin.json 的 `permissions` 字段声明所需权限：
- `routes`: 注册 API 路由
- `pages`: 注册前端页面
- `database`: 数据库只读
- `database_write`: 数据库读写
- `tools`: 调用内置工具
