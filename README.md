# Potential Tools

> 一站式研发效率工具平台，为智能硬件研发团队而生。

集成 CR 分析、日志根因定位、知识图谱、HLD 生成、项目计划、测试报告、会议纪要等 **20+ 工具**，支持本地运行与云端部署，开箱即用。

[![Version](https://img.shields.io/badge/version-v7.0.0-blue.svg)](https://github.com/wangys38-cyber/Potential-tools/releases)
[![Python](https://img.shields.io/badge/python-3.9%2B-green.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)
[![Commits](https://img.shields.io/github/commit-activity/m/wangys38-cyber/Potential-tools)](https://github.com/wangys38-cyber/Potential-tools/commits/main)

**线上体验**：[https://wangys666.top](https://wangys666.top)

---

## 目录

- [核心亮点](#核心亮点)
- [功能矩阵](#功能矩阵)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [部署方式](#部署方式)
- [项目结构](#项目结构)
- [文档索引](#文档索引)
- [更新日志](#更新日志)
- [贡献指南](#贡献指南)
- [License](#license)

---

## 核心亮点

- **研发全流程覆盖** — 从需求分析（HLD）、开发排期（软件计划）、质量把控（CR/测试报告/MTTF）到团队协作（会议纪要/站会/周报），一个平台搞定。
- **AI 深度赋能** — 支持豆包、DeepSeek、小米、OpenAI、通义千问、智谱、Kimi、混元 **8 大 AI 服务商**，提供根因分析、文档生成、智能翻译、邮件助手等能力。
- **大文件无忧** — 2MB 分块上传 + 断点续传 + Web Worker 后台处理 + pandas 向量化计算，轻松应对 **200MB** 级日志与 Excel 文件。
- **数据安全隔离** — 多用户数据按账号隔离存储，支持微信 OAuth 登录、访客模式、CSRF 防护、限流、审计日志，GDPR 合规。
- **零前端框架** — 纯 Vanilla JavaScript 构建，无构建步骤，clone 即跑，二次开发门槛低。
- **多端自适应** — 桌面 / 平板 / 手机全适配，iOS 安全区域优化，暗色模式跟随系统，可访问性（WCAG）友好。

---

## 功能矩阵

### 研发分析与数据基础

| 工具 | 核心能力 |
|------|----------|
| **CR 问题分析** | Jira Excel/CSV 多维分析（模块/研发/严重度/状态）、AI 根因分析、研发效率排名、模块健康度、Bug 趋势曲线、飞书推送、PDF 导出 |
| **日志智能根因分析** | 设备日志异常模式识别、构建错误链追踪、历史问题匹配、AI 深度推理，输出根因 + 修复建议 + 风险等级 |
| **研发知识图谱** | Bug/需求/模块/人员关联网络、力导向可视化、智能问答、CR 数据一键导入、节点关系手动管理 |
| **测试报告分析** | 测试项自动提取、分类风险评估、AI 深度分析、大文件 pandas 优化、PDF 导出 |
| **Bug 趋势看板** | 多版本对比、周对比表、模块×周热力图、研发堆叠面积图、每日新增/解决曲线 |
| **MTTF 可靠性看板** | 设备挂测日志分析、失败事件聚类、MTTF/MTBF 计算、失败分布条形图、事件时间线 |
| **Dashboard 研发健康度** | Bug 趋势 + MTTF 指标 + 版本进度 + 个人效能 + 项目概览，统一仪表盘 |
| **用户数据隔离** | localStorage 按用户 ID 前缀隔离，登录数据自动同步后端，换设备无缝恢复 |

### 文档生成与协作

| 工具 | 核心能力 |
|------|----------|
| **HLD 生成器** | 基于 OD Excel 需求文档自动生成 Feature 级 HLD（含 LLD 接口/数据结构/算法）、Mermaid 时序图/状态机、批量 ZIP 下载 |
| **软件计划生成器** | 一键生成完整软件计划时间节点表、甘特图展示、AI 调整建议、飞书推送、会议纪要待办自动流转 |
| **会议纪要** | 语音转写 + AI 结构化纪要、待办事项流转到项目计划、PDF 下载 |
| **智能周报** | 多素材 AI 生成结构化周报、站会助手数据自动流转 |
| **每日站会助手** | 三段式输入（昨日/今日/阻塞）、Jira 导入、AI 润色、飞书推送、一键全自动、定时提醒 |
| **项目信息收集** | 软件项目完整技术规格管理、按账号隔离存储 |
| **协作工作空间** | 8 位分享码、查看/编辑权限、7 天过期、评论系统、5 秒轮询实时同步、匿名访问 |
| **团队管理** | 创建团队、邀请成员、所有权转让、团队数据共享、版本历史与恢复 |

### 效率工具与系统管理

| 工具 | 核心能力 |
|------|----------|
| **IT 翻译器** | 技术文档专用翻译、代码块保护、术语库强制映射、流式输出、Markdown 保留、12 种语言 |
| **邮件助手** | 8 种英文技术邮件模板（Bug 报告/进度同步/问题升级等）、变量填充、中英切换、AI 智能回复 |
| **PDF 快转** | Markdown / Word / Excel 转 PDF、公式渲染、Mermaid 图表支持、实时预览 |
| **数据可视化 Builder** | Excel 自选 X/Y 轴生成 6 种图表（柱状/折线/饼/散点/雷达/热力）、双 Y 轴、标注线、PNG/SVG/CSV 导出、模板保存 |
| **牛马笔记** | Markdown 编辑 + 实时预览、分类标签、全文搜索、模板、待办勾选、导出、后端同步、快捷键 |
| **用户管理平台** | 用户列表/搜索/状态管理/角色分配/数据统计，管理员专属 |
| **系统设置** | AI 配置、飞书机器人配置（HMAC-SHA256 签名校验）、主题定制、API 连接测试、系统诊断、推送历史 |
| **账号与数据管理** | 个人数据导出（GDPR）、密码强度校验、账号注销（软删除 30 天可恢复）、全操作审计日志 |
| **性能监控看板** | 请求统计（P50/P95/P99）、系统指标（CPU/内存/磁盘）、慢查询日志、告警窗口统计 |
| **告警系统** | 5 分钟滑动窗口监控请求量与 5xx 错误率、超阈值自动告警、告警历史可查 |
| **自动备份调度** | 定时备份 SQLite、手动触发备份下载、备份文件保留策略 |

### 全局能力

- **Apple 风格导航栏** — 全站统一白色导航栏，SVG 线条图标，黑色按钮白字，搜索/同步/主题/设置入口
- **飞书推送** — 一键推送到飞书群，HMAC-SHA256 签名校验，失败自动重试，推送历史记录
- **暗色模式** — 全站统一暗色主题，图表自动适配，支持跟随系统
- **统一组件库** — 上传组件、历史记录、Toast、Loading、骨架屏全局复用
- **性能优化** — gzip 响应压缩、请求性能统计中间件、慢查询日志、TTL 缓存
- **安全加固** — CSRF 防护、限流中间件、请求日志、密码强度校验、审计日志、隐私政策
- **可访问性** — 跳过导航链接、ARIA 标签、键盘操作、减少动画偏好、焦点可见状态

---

## 技术栈

| 层级 | 技术选型 |
|------|----------|
| **后端框架** | Flask + SQLAlchemy + Gunicorn + Blueprint 模块化架构 |
| **数据库** | SQLite（默认）/ PostgreSQL（自动切换） |
| **前端** | HTML5 / CSS3 / Vanilla JavaScript（无框架依赖） |
| **图表** | Chart.js + 原生 SVG（甘特图 / 知识图谱力导向布局） |
| **PDF 生成** | Playwright（Chromium headless） |
| **Excel 解析** | openpyxl / pandas / xlrd / BeautifulSoup4 |
| **文档处理** | python-docx / markdown / Mermaid |
| **AI 集成** | OpenAI 兼容 API（豆包 / DeepSeek / 小米 / OpenAI / 通义千问 / 智谱 / Kimi / 混元） |
| **认证** | 账号密码 + 微信 OAuth + 访客模式 |
| **大文件** | 分块上传 + Web Worker + pandas 向量化 |
| **部署** | Docker / Railway / 本地 Gunicorn |

---

## 快速开始

### 环境要求

- Python 3.9+
- pip
- （可选）Playwright Chromium — PDF 生成功能需要

### 本地运行

```bash
# 1. 克隆仓库
git clone https://github.com/wangys38-cyber/Potential-tools.git
cd Potential-tools

# 2. 创建并激活虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装 Playwright Chromium（PDF 快转功能需要，可跳过）
playwright install chromium

# 5. 配置环境变量（可选，默认支持访客模式）
cp .env.example .env
# 编辑 .env，填入 AI_API_KEY 等配置

# 6. 启动服务
python app.py
```

服务启动后访问 **http://localhost:5000** 即可使用。

> 默认开启访客模式，无需注册即可体验全部工具；配置 `SESSION_SECRET` 后可启用账号注册登录。

---

## 环境变量

完整配置模板见 [`.env.example`](.env.example)。

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `PORT` | 否 | `5000` | 服务监听端口（Railway 自动注入） |
| `ALLOW_GUEST` | 否 | `true` | 访客模式开关 |
| `SESSION_SECRET` | 是（生产） | — | Session 加密密钥，生产环境必须设置 |
| `DATABASE_URL` | 否 | — | PostgreSQL 连接字符串，留空使用 SQLite |
| `DATA_DIR` | 否 | `/app/data` | SQLite 数据文件目录 |
| `AI_API_KEY` | 否 | — | AI 服务 API Key |
| `AI_BASE_URL` | 否 | — | AI 服务 API 地址 |
| `AI_MODEL` | 否 | — | 默认 AI 模型 ID |
| `WECHAT_APP_ID` | 否 | — | 微信开放平台 AppID |
| `WECHAT_APP_SECRET` | 否 | — | 微信开放平台 AppSecret |
| `FEISHU_WEBHOOK_URL` | 否 | — | 飞书机器人 Webhook 地址 |
| `FEISHU_SECRET` | 否 | — | 飞书机器人签名密钥 |

---

## 部署方式

### Railway 部署（推荐）

1. Fork 本仓库到你的 GitHub
2. Railway → New Project → Deploy from GitHub repo
3. 选择仓库，Railway 自动识别 Dockerfile 并构建
4. （推荐）添加 Volume 挂载到 `/app/data`，持久化 SQLite 数据库
5. 在 Variables 中配置 `AI_API_KEY`、`SESSION_SECRET` 等环境变量
6. push 到 main 分支自动触发重新部署

> 配置文件见 [`railway.toml`](railway.toml)，健康检查路径为 `/health`。

### Docker 部署

```bash
# 构建镜像
docker build -t potential-tools .

# 运行容器
docker run -d \
  --name potential-tools \
  -p 5000:5000 \
  -e PORT=5000 \
  -e SESSION_SECRET=your-secret-key \
  -v /path/to/data:/app/data \
  --restart unless-stopped \
  potential-tools
```

生产环境使用 [`gunicorn.conf.py`](gunicorn.conf.py) 启动：gthread 模式，1 worker + 16 线程，超时 300 秒。

### 云服务器部署

详细的腾讯云等云服务器部署指南见 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)。

---

## 项目结构

```
Potential-tools/
├── app.py                      # Flask 主应用入口
├── auth.py                     # 认证模块（账号密码 / 微信 OAuth / 访客模式）
├── db.py                       # 数据库模块（SQLite / PostgreSQL 自动切换）
├── security.py                 # 安全工具（密码强度 / 加密 / CSRF）
├── ai_utils.py                 # AI 调用封装（8 服务商兼容，流式输出）
├── feishu_push.py              # 飞书推送模块（签名校验 / 重试 / 历史记录）
├── bp_user.py                  # 用户管理 Blueprint（数据导出 / 改密 / 注销）
├── bp_ai.py                    # AI 配置 Blueprint
├── excel_analyzers.py          # Excel 分析引擎（流式读取 / 向量化计算）
├── report_builders.py          # PDF 报告生成器
├── date_utils.py               # 日期工具
├── crypto_utils.py             # 加密工具
├── error_utils.py              # 错误处理
├── task_queue.py               # 任务队列
├── ttl_cache.py                # TTL 缓存
├── rate_limiter.py             # API 限流
├── request_logger.py           # 请求日志
├── compression_middleware.py   # gzip 压缩中间件
├── performance_middleware.py   # 性能监控中间件
├── system_metrics.py           # 系统指标采集
├── alerting.py                 # 告警系统
├── backup_scheduler.py         # 自动备份调度器
├── gunicorn.conf.py            # Gunicorn 生产配置
├── routes/                     # Blueprint 模块化路由（18 个蓝图）
├── templates/                  # HTML 模板（30+ 页面）
├── static/                     # 静态资源（CSS / JS / Web Worker）
├── glossaries/                 # 术语库（IT 翻译器外部化术语映射）
├── docs/                       # 项目文档
├── Dockerfile                  # Docker 构建配置
├── railway.toml                # Railway 部署配置
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
├── CHANGELOG.md                # 更新日志
└── README.md                   # 项目说明
```

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [用户手册](docs/USER_GUIDE.md) | 工具使用指南、账号管理、飞书配置、常见问题 |
| [开发者文档](docs/DEVELOPMENT.md) | 项目结构、本地开发环境、代码规范、核心模块说明、版本发布流程 |
| [API 文档](docs/API.md) | 所有 API 接口说明、请求/响应格式、认证方式 |
| [部署文档](docs/DEPLOYMENT.md) | Railway / Docker / 云服务器部署、环境变量、数据库配置、监控告警、常见问题 |

---

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)。

### v7.0.0 — 2026-08-25

- **移动端体验优化** — 300+ 行适配规则，图表/表单/导航栏全端适配
- **数据可视化增强** — 数据标签插件、数字格式化工具（千分位/万/亿缩写）、Y 轴刻度自动缩写
- **工作流自动化修复** — 站会→周报、会议纪要→项目计划数据流转修复验证
- **可访问性优化** — 跳过导航、ARIA 标签、键盘操作、减少动画偏好
- **安全与合规** — 账号数据导出、修改密码强度校验、注销账号软删除、审计日志
- **部署与运维** — Gunicorn 配置文件、性能监控看板、告警系统、自动备份调度
- **文档完善** — 用户手册、开发者文档、API 文档、部署文档

### 历史版本

- **v6.0.0** — UI/UX 统一（黑色系主题）、Bug 修复与验证
- **v5.3.0** — 移动端响应式适配、协作工作空间（分享码/评论/实时同步）
- **v5.0.0** — 飞书推送模板化、推送历史记录、失败重试
- 更多版本见 [CHANGELOG.md](CHANGELOG.md)

---

## 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m 'feat: add your feature'`
4. 推送分支：`git push origin feature/your-feature`
5. 发起 Pull Request

提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：`feat:` / `fix:` / `docs:` / `perf:` / `refactor:` / `security:` 等。

---

## License

[MIT](LICENSE) © wangys38-cyber
