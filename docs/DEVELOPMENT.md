# Potential Tools 开发者文档

## 项目概述

Potential Tools 是基于 Flask 的研发效率工具平台，采用 Blueprint 模块化架构，前端使用原生 JavaScript（无框架依赖），支持本地运行和云端部署。

- 版本：v7.0.0
- 线上地址：https://wangys666.top
- GitHub：https://github.com/wangys38-cyber/Potential-tools

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Flask + Gunicorn + Blueprint 模块化 |
| 数据库 | SQLite（默认）/ PostgreSQL（自动切换） |
| ORM | SQLAlchemy |
| 前端 | HTML5 / CSS3 / Vanilla JavaScript |
| 图表 | Chart.js + 原生 SVG |
| PDF 生成 | Playwright (Chromium headless) |
| Excel 解析 | openpyxl / pandas / xlrd / BeautifulSoup4 |
| AI 集成 | OpenAI 兼容 API |
| 认证 | 账号密码 + 微信 OAuth + 访客模式 |
| 部署 | Docker / Railway |

## 项目结构

```
.
├── app.py                      # Flask 主应用入口
├── auth.py                     # 认证模块（账号密码/微信 OAuth/访客）
├── db.py                       # 数据库模块（SQLite/PostgreSQL）
├── ai_utils.py                 # AI 调用封装（多模型兼容，流式输出）
├── feishu_push.py              # 飞书推送模块
├── security.py                 # 安全工具（密码强度、加密、CSRF）
├── crypto_utils.py             # 加密工具
├── rate_limiter.py             # 限流中间件
├── request_logger.py           # 请求日志
├── performance_middleware.py   # 性能监控中间件
├── compression_middleware.py   # gzip 压缩中间件
├── system_metrics.py           # 系统指标采集
├── alerting.py                 # 告警系统
├── backup_scheduler.py         # 自动备份调度器
├── task_queue.py               # 任务队列
├── ttl_cache.py                # TTL 缓存
├── bp_ai.py                    # AI 相关 Blueprint
├── bp_user.py                  # 用户管理 Blueprint（数据导出/改密/注销）
├── gunicorn.conf.py            # Gunicorn 生产配置
├── routes/                     # Blueprint 模块化路由
│   ├── pages.py                # 页面渲染路由
│   ├── api.py                  # 通用 API
│   ├── tools.py                # 工具类 API
│   ├── analysis.py             # 数据分析 API
│   ├── sync.py                 # 云端同步 API
│   ├── collab.py               # 协作功能 API（v1）
│   ├── collab_v2.py            # 协作功能 API（v2）
│   ├── visualization.py        # 数据可视化 API
│   ├── translator.py           # IT 翻译器 API
│   ├── notes.py                # 牛马笔记 REST API
│   ├── admin.py                # 管理员 API（用户管理/性能监控/告警）
│   ├── knowledge_graph.py      # 研发知识图谱 API
│   ├── hld_generator.py        # HLD 生成器 API
│   ├── teams.py                # 团队管理 API
│   ├── versions.py             # 版本管理 API
│   └── notifications.py        # 通知 API
├── templates/                  # HTML 模板（30+ 页面）
│   ├── _navbar.html            # 统一导航栏
│   ├── index.html              # 首页
│   ├── settings.html           # 系统设置（含账号与数据管理）
│   ├── admin_performance.html  # 管理员性能监控看板
│   ├── admin_users.html        # 用户管理
│   ├── privacy.html            # 隐私政策
│   └── ...                     # 其他工具页面
├── static/                     # 静态资源
│   ├── css/                    # 样式文件
│   └── js/                     # JavaScript
│       └── workers/            # Web Worker
├── docs/                       # 项目文档
├── Dockerfile                  # Docker 构建配置
├── railway.toml                # Railway 部署配置
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
├── CHANGELOG.md                # 更新日志
└── README.md                   # 项目说明
```

## 本地开发环境搭建

### 前置要求

- Python 3.11+
- pip
- Git

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/wangys38-cyber/Potential-tools.git
cd Potential-tools

# 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright Chromium（PDF 生成需要）
playwright install chromium

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入配置

# 启动开发服务器
python app.py
# 默认运行在 http://localhost:5000
```

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `PORT` | 否 | `5000` | 服务监听端口 |
| `ALLOW_GUEST` | 否 | `true` | 访客模式开关 |
| `SESSION_SECRET` | 是 | — | Session 加密密钥 |
| `DATABASE_URL` | 否 | — | PostgreSQL 连接字符串，留空用 SQLite |
| `DATA_DIR` | 否 | `/app/data` | SQLite 数据文件目录 |
| `AI_API_KEY` | 否 | — | AI 服务 API Key |
| `AI_BASE_URL` | 否 | — | AI 服务 API 地址 |
| `AI_MODEL` | 否 | — | 默认 AI 模型 ID |
| `WECHAT_APP_ID` | 否 | — | 微信开放平台 AppID |
| `WECHAT_APP_SECRET` | 否 | — | 微信开放平台 AppSecret |
| `FEISHU_WEBHOOK_URL` | 否 | — | 飞书机器人 Webhook |
| `FEISHU_SECRET` | 否 | — | 飞书机器人签名密钥 |

## 开发规范

### 代码风格

- Python：遵循 PEP 8，使用 4 空格缩进
- JavaScript：ES6+，2 空格缩进，使用 `const`/`let`
- HTML/CSS：语义化标签，CSS 变量统一主题色
- 注释：关键逻辑必须有中文注释

### 主题规范

- 主色调：黑色系（黑色按钮白字）
- 强调色：通过 CSS 变量 `--accent-color` 控制
- 暗色模式：所有 CSS 文件必须覆盖 `[data-theme="dark"]`
- 禁止使用紫色/靛色主题

### 新增工具页面

1. 在 `routes/pages.py` 中添加页面路由
2. 在 `templates/` 中创建 HTML 模板，继承导航栏
3. 在 `index.html` 首页添加工具入口卡片
4. 如需后端 API，在对应 Blueprint 中添加路由
5. 更新 `README.md` 和 `docs/USER_GUIDE.md`

### 新增 Blueprint

1. 在 `routes/` 中创建新文件，使用 `Blueprint`
2. 在 `app.py` 中注册 Blueprint
3. 路由统一使用 `/api/` 前缀 for API，页面路由直接注册

### 数据库迁移

- 项目使用 SQLAlchemy，表结构在 `db.py` 的 `init_db()` 中定义
- 新增表使用 `CREATE TABLE IF NOT EXISTS`
- 新增列使用 `ALTER TABLE ADD COLUMN` 并捕获异常
- 索引使用 `CREATE INDEX IF NOT EXISTS`

## 核心模块说明

### 认证系统 (auth.py)

- 支持账号密码、微信 OAuth、访客模式三种登录方式
- 注册时需同意隐私政策
- Session 管理，支持多设备登录
- 密码使用 werkzeug.security 哈希存储

### 用户数据管理 (bp_user.py)

- `/api/user/export`：导出用户全部数据（GDPR 合规）
- `/api/user/change-password`：修改密码（验证旧密码+强度校验）
- `/api/user/delete`：软删除账号（30天可恢复）
- 所有操作记录审计日志

### 性能监控 (performance_middleware.py)

- 记录每个请求的响应时间
- 统计总请求数、慢请求数、平均响应时间、P50/P95/P99
- 慢查询日志（默认阈值 1000ms）
- 提供 `/api/performance-metrics` 端点

### 告警系统 (alerting.py)

- 5 分钟滑动窗口统计请求量和 5xx 错误率
- 支持错误率告警和异常流量告警
- 告警历史存储，管理员可查看
- 启动时通过 `alerting.start_alerting()` 初始化

### 系统指标 (system_metrics.py)

- 采集 CPU、内存、磁盘、网络指标
- 历史数据存储（最近 60 个采样点）
- 提供摘要和历史数据 API
- 启动时通过 `system_metrics.start_collector()` 初始化

### 自动备份 (backup_scheduler.py)

- 定时备份 SQLite 数据库
- 备份文件保留策略
- 管理员可手动触发备份
- 启动时通过 `backup_scheduler.start_scheduler()` 初始化

### 限流 (rate_limiter.py)

- 基于 IP 和用户 ID 的限流
- 支持不同路由配置不同限流策略
- 超出限制返回 429 状态码

## 测试

### 语法检查

```bash
# 检查所有 Python 文件语法
python -c "import ast, glob; [ast.parse(open(f, encoding='utf-8').read()) for f in glob.glob('**/*.py', recursive=True)]; print('All Python files syntax OK')"
```

### 模板检查

```bash
# 检查 Jinja2 模板语法
python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
for t in env.list_templates():
    env.get_template(t)
print('All templates OK')
"
```

### 启动测试

```bash
# 启动应用并检查健康检查端点
python app.py &
curl http://localhost:5000/health
```

## 调试技巧

### 查看日志

- 开发模式：日志输出到控制台
- 生产模式：Gunicorn 日志输出到 stdout，可通过 Railway 日志查看

### 数据库调试

- 默认 SQLite 数据库文件在 `DATA_DIR` 目录
- 可使用 SQLite 客户端直接查看数据
- PostgreSQL 模式通过 `DATABASE_URL` 连接

### 常见错误

- `ModuleNotFoundError`：检查 Dockerfile 是否遗漏 COPY，或本地是否安装依赖
- `TemplateNotFound`：检查模板文件名和路径
- 数据库锁定：SQLite 并发写入限制，生产环境建议使用 PostgreSQL

## 版本发布流程

1. 完成功能开发和测试
2. 更新 `CHANGELOG.md`，添加新版本条目
3. 更新 `README.md` 中的版本号和功能列表
4. 更新 `Dockerfile` 中的 `CACHE_BUST` 值
5. 提交代码并 push 到 main 分支
6. Railway 自动触发部署
7. 验证线上环境功能正常
