# 🧰 Potential Tools — 效率工具集

一站式效率工具平台，集成笔记、PDF 转换、测试报告分析、AI 对话、会议纪要等功能，支持本地运行和云端部署。

## ✨ 功能概览

| 工具 | 说明 |
|------|------|
| 📝 牛马笔记 | Markdown 编辑器，支持双向链接 `[[页面名]]`、关系图谱、标签管理、主题切换 |
| 📄 PDF 快转 | Markdown / Word 转 PDF，自动添加水印，支持公式渲染 |
| 📅 软件计划生成器 | 输入项目类型和起始节点，一键生成完整软件计划时间节点表 |
| 📊 项目信息收集 | 收集和管理软件项目的完整技术规格信息 |
| 📊 CR 问题分析 | 上传问题清单 Excel，按模块/研发/日期分析，AI 根因分析，生成带水印 PDF 报告 |
| 📋 测试报告分析 | 上传测试报告 Excel，自动提取测试项、分类风险评估，AI 深度分析，导出高质感 PDF |
| 🎙️ 会议纪要 | 语音转写 + AI 自动生成结构化会议纪要，支持多模型选择 |
| 📋 智能周报 | 基于多种工作素材，AI 生成结构化周报 |
| 🔔 功德+1 | 敲击木鱼积攒功德，自动保存进度 |
| ⚙️ 系统设置 | AI 配置、主题定制、API 连接测试、系统诊断 |

### 全局增强功能

- **🤖 全局 AI 对话助手** — 浮窗式 AI 聊天，支持多模型切换、SSE 流式输出
- **🔍 OCR 图片识别** — 剪贴板粘贴图片即可识别文字
- **⌘ 命令面板 (Cmd+K)** — VS Code 风格全局命令面板，快速搜索工具和执行命令
- **📱 PWA 离线支持** — Service Worker 缓存核心资源，笔记和功德+1 离线可用
- **⭐ 工具收藏夹** — 收藏常用工具，个性化导航
- **🎨 主题系统** — 浅色/深色/自动三种模式，全站统一切换
- **📱 响应式设计** — 适配桌面、平板、手机多种设备

## 🚀 快速开始

### 本地运行

```bash
# 克隆仓库
git clone https://github.com/wangys38-cyber/Potential-tools.git
cd Potential-tools

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright Chromium（PDF 生成需要）
playwright install chromium

# 配置环境变量（可选，默认支持访客模式）
cp .env.example .env
# 编辑 .env 填入 AI API Key、OAuth 等配置

# 启动服务
python app.py
# 默认运行在 http://localhost:5001
```

### Docker 部署

```bash
docker build -t potential-tools .
docker run -p 5001:5001 -e PORT=5001 potential-tools
```

### Railway 部署

1. Fork 本仓库到你的 GitHub
2. 在 [Railway](https://railway.app) 中 New Project → Deploy from GitHub repo
3. 选择本仓库，Railway 会自动识别 `Dockerfile` 并构建
4. 在 Railway 中添加 PostgreSQL 插件，`DATABASE_URL` 会自动注入
5. 在 Variables 中配置 `AI_API_KEY`、`SESSION_SECRET` 等环境变量

## 📋 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Flask + Gunicorn |
| 数据库 | SQLAlchemy ORM（PostgreSQL / SQLite 自动切换） |
| 前端 | HTML5 / CSS3 / Vanilla JavaScript |
| PDF 生成 | Playwright (Chromium headless) |
| Excel 解析 | openpyxl / xlrd / BeautifulSoup4 |
| 文档处理 | python-docx / markdown |
| AI 集成 | OpenAI 兼容 API（DashScope / 火山引擎 ARK 等） |
| 认证 | 飞书 OAuth + Google OAuth + 访客模式 |
| PWA | Service Worker + Web App Manifest |
| 部署 | Docker / Railway |

## ⚙️ 环境变量配置

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `PORT` | 否 | `5001` | 服务监听端口（Railway 自动注入） |
| `ALLOW_GUEST` | 否 | `true` | 访客模式，本地开发设为 true，生产环境建议 false |
| `SESSION_SECRET` | 是 | — | Session 加密密钥，`python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | 否 | — | PostgreSQL 连接字符串，留空则使用 SQLite |
| `AI_API_KEY` | 否 | — | AI 服务 API Key（DashScope / ARK 等） |
| `AI_BASE_URL` | 否 | — | AI 服务 API 地址 |
| `AI_MODEL` | 否 | — | 默认 AI 模型 ID |
| `FEISHU_APP_ID` | 否 | — | 飞书 OAuth 应用 ID |
| `FEISHU_APP_SECRET` | 否 | — | 飞书 OAuth 应用密钥 |
| `FEISHU_REDIRECT_URI` | 否 | — | 飞书 OAuth 回调地址 |
| `GOOGLE_CLIENT_ID` | 否 | — | Google OAuth 客户端 ID |
| `GOOGLE_CLIENT_SECRET` | 否 | — | Google OAuth 客户端密钥 |
| `GOOGLE_REDIRECT_URI` | 否 | — | Google OAuth 回调地址 |
| `DB_DIR` | 否 | `/tmp/toolbox` | SQLite 数据目录（仅 `DATABASE_URL` 为空时生效） |

> 完整配置模板见 `.env.example`

## 📁 项目结构

```
.
├── app.py                      # Flask 主应用（路由和业务逻辑）
├── auth.py                     # 认证模块（飞书/Google OAuth + 访客模式）
├── db.py                       # 数据库模块（SQLAlchemy ORM，PostgreSQL/SQLite）
├── templates/                  # HTML 模板
│   ├── index.html              # 首页（工具导航 + 收藏 + 统计）
│   ├── test_report.html        # 测试报告分析
│   ├── excel_analysis.html     # CR 问题分析
│   ├── meeting_minutes.html    # 会议纪要
│   ├── weekly_report.html      # 智能周报
│   ├── settings.html           # 系统设置
│   ├── md2pdf.html             # PDF 快转
│   ├── plan_generator.html     # 软件计划生成器
│   ├── project_info.html       # 项目信息收集
│   ├── merit.html              # 功德+1
│   └── login.html              # 登录页
├── static/                     # 静态资源
│   ├── css/theme.css           # 全站主题样式
│   ├── js/components.js        # 全局组件库（主题、Toast、AI对话、OCR、命令面板）
│   ├── manifest.json           # PWA Manifest
│   ├── sw.js                   # Service Worker（离线缓存）
│   ├── noteNB/                 # 牛马笔记前端（Vue 构建）
│   └── md2pdf/                 # PDF 转换前端
├── Dockerfile                  # Docker 构建配置
├── railway.toml                # Railway 部署配置
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
└── start_app.bat               # Windows 本地启动脚本
```

## 📌 关键特性

### PDF 报告生成

测试报告分析和 CR 问题分析均支持导出高质感 PDF：
- 深色渐变 Header + Motorola 水印
- 语义化卡片配色（通过/失败/阻塞/延期）
- 统计数据、分类分析、关键发现、改进建议完整呈现
- AI 深度分析内容同步导出
- 测试项表格按失败优先级排序，分页打印

### AI 集成

支持 OpenAI 兼容 API 格式，可对接多种 AI 服务：
- 全局 AI 对话助手（SSE 流式输出）
- 测试报告 AI 深度分析（总体评估、风险洞察、质量趋势、改进建议）
- CR 问题 AI 根因分析
- 会议纪要 AI 自动生成
- 智能周报 AI 生成
- OCR 图片文字识别

### 安全与数据库

- 敏感配置通过环境变量管理，不硬编码
- SQLAlchemy ORM 抽象层，PostgreSQL / SQLite 无缝切换
- 飞书 OAuth + Google OAuth 企业级认证
- Session 持久化（7 天有效期）

### 性能优化

- 分块上传大文件，突破代理/网关请求体大小限制
- Excel 分析采用后台任务 + 轮询机制，避免请求超时
- HTML 格式 Excel 使用流式正则解析，避免 OOM
- Service Worker 多级缓存策略（NetworkFirst / StaleWhileRevalidate / CacheFirst）
- PDF 报告时间统一使用北京时间 (CST, UTC+8)

## 📄 License

MIT
