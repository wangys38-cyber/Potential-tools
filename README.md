# Potential Tools — 研发效率工具集

一站式研发效率工具平台，面向智能硬件研发团队，集成 CR 分析、日志根因定位、知识图谱、HLD 生成、项目计划、测试报告、会议纪要等 20+ 工具，支持本地运行和云端部署。

## 功能概览

### 研发分析类

| 工具 | 说明 |
|------|------|
| **CR 问题分析** | 上传 Jira 导出 Excel/CSV，按模块/研发/严重度/状态多维分析，AI 根因分析，研发效率排名，模块健康度，Bug 趋势曲线，飞书推送，导出 PDF |
| **日志智能根因分析** | 上传/粘贴设备日志，自动识别异常模式、构建错误链、匹配相似历史问题、AI 深度根因推理，输出根因+修复建议+风险等级 |
| **研发知识图谱** | 关联 Bug、需求、模块、人员构建知识网络，力导向可视化，智能问答，CR 分析数据一键导入，核心节点分析 |
| **测试报告分析** | 上传测试报告 Excel，自动提取测试项、分类风险评估，AI 深度分析，大文件 pandas 优化，导出 PDF |
| **Bug 趋势看板** | 多版本 Bug 对比，周对比表，模块×周热力图，研发堆叠面积图，每日新增/解决曲线 |
| **MTTF 可靠性看板** | 设备挂测日志分析，失败事件聚类，MTTF/MTBF 计算，失败分布条形图，事件时间线 |
| **Dashboard 研发健康度** | Bug 趋势、MTTF 指标、版本进度、个人效能、项目概览，对接后端 API |

### 文档生成类

| 工具 | 说明 |
|------|------|
| **HLD 生成器** | 基于 OD Excel 需求文档，自动生成每个 Feature 的 HLD（含 LLD 级接口/数据结构/算法细节），GPS/Fitness 增强，Mermaid 时序图/状态机，批量 ZIP 下载 |
| **软件计划生成器** | 输入项目类型和起始节点，一键生成完整软件计划时间节点表，甘特图展示，AI 调整建议，飞书推送，会议纪要待办自动流转 |
| **项目信息收集** | 收集和管理软件项目的完整技术规格信息，按账号隔离存储 |
| **会议纪要** | 语音转写 + AI 自动生成结构化会议纪要，待办事项可流转到项目计划，下载 PDF |
| **智能周报** | 基于多种工作素材 AI 生成结构化周报，站会助手数据自动流转 |
| **每日站会助手** | 三段式输入（昨日完成/今日计划/阻塞项），Jira 导入，AI 润色，飞书推送，一键全自动，定时提醒 |

### 工具效率类

| 工具 | 说明 |
|------|------|
| **IT 翻译器** | IT 技术文档专用翻译，代码块保护，术语库强制映射，流式输出，Markdown 格式保留，12 种语言 |
| **邮件助手** | 英文技术邮件模板生成，8 种模板覆盖 Bug 报告/进度同步/问题升级，变量填充，中英切换，AI 智能回复 |
| **PDF 快转** | Markdown / Word / Excel 转 PDF，公式渲染，Mermaid 图表支持，实时预览 |
| **数据可视化 Builder** | 上传 Excel 自选 X/Y 轴生成柱状图/折线图/饼图/散点/雷达/热力图，双 Y 轴，标注线，导出 PNG/SVG/CSV，图表模板保存 |
| **牛马笔记** | Markdown 编辑+实时预览，分类标签，全文搜索，模板，待办勾选，导出，后端同步，快捷键 |
| **电子木鱼** | 极简风格敲击木鱼，功德计数，自动保存 |

### 系统管理类

| 工具 | 说明 |
|------|------|
| **用户管理平台** | 用户列表、搜索、状态管理、角色分配、数据统计，管理员专属 |
| **系统设置** | AI 配置、飞书机器人配置（含签名校验）、主题定制、API 连接测试、系统诊断、推送历史记录 |
| **协作功能** | 共享工作空间，8 位分享码，查看/编辑权限，评论系统，实时同步 |

## 全局增强

- **Apple 风格导航栏** — 全站统一白色导航栏，SVG 线条图标，黑色按钮白字，搜索/同步/主题/设置入口
- **用户数据隔离** — 所有 localStorage 数据按用户 ID 前缀隔离，换设备登录自动同步
- **飞书推送** — CR 分析、站会、项目计划等支持一键推送到飞书群，签名校验，推送历史记录
- **大文件处理** — 分块上传突破网关限制，Web Worker 后台线程不阻塞页面，pandas 向量化计算
- **暗色模式** — 全站统一暗色主题，图表自动适配
- **响应式设计** — 适配桌面、平板、手机，iOS 安全区域适配
- **统一组件库** — 上传组件、历史记录组件、Toast、Loading 全局复用

## 快速开始

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
# 编辑 .env 填入 AI API Key 等配置

# 启动服务
python app.py
# 默认运行在 http://localhost:5000
```

### Docker 部署

```bash
docker build -t potential-tools .
docker run -p 5000:5000 -e PORT=5000 -v /path/to/data:/app/data potential-tools
```

### Railway 部署

1. Fork 本仓库到你的 GitHub
2. 在 Railway 中 New Project → Deploy from GitHub repo
3. 选择本仓库，Railway 会自动识别 Dockerfile 并构建
4. （推荐）添加 Volume 挂载到 `/app/data`，持久化 SQLite 数据库
5. 在 Variables 中配置 `AI_API_KEY`、`SESSION_SECRET` 等环境变量

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Flask + Gunicorn + Blueprint 模块化架构 |
| 数据库 | SQLite（默认）/ PostgreSQL（自动切换） |
| 前端 | HTML5 / CSS3 / Vanilla JavaScript（无框架依赖） |
| 图表 | Chart.js + 原生 SVG（甘特图/知识图谱力导向） |
| PDF 生成 | Playwright (Chromium headless) |
| Excel 解析 | openpyxl / pandas / xlrd / BeautifulSoup4 |
| 文档处理 | python-docx / markdown / Mermaid |
| AI 集成 | OpenAI 兼容 API（DashScope / 火山引擎 ARK 等） |
| 认证 | 账号密码注册登录 + 微信 OAuth + 访客模式 |
| 大文件 | 分块上传 + Web Worker + pandas 向量化 |
| 部署 | Docker / Railway |

## 环境变量配置

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `PORT` | 否 | `5000` | 服务监听端口（Railway 自动注入） |
| `ALLOW_GUEST` | 否 | `true` | 访客模式开关 |
| `SESSION_SECRET` | 是 | — | Session 加密密钥 |
| `DATABASE_URL` | 否 | — | PostgreSQL 连接字符串，留空则使用 SQLite |
| `DATA_DIR` | 否 | `/app/data` | SQLite 数据文件目录 |
| `AI_API_KEY` | 否 | — | AI 服务 API Key |
| `AI_BASE_URL` | 否 | — | AI 服务 API 地址 |
| `AI_MODEL` | 否 | — | 默认 AI 模型 ID |
| `WECHAT_APP_ID` | 否 | — | 微信开放平台 AppID |
| `WECHAT_APP_SECRET` | 否 | — | 微信开放平台 AppSecret |
| `FEISHU_WEBHOOK_URL` | 否 | — | 飞书机器人 Webhook 地址 |
| `FEISHU_SECRET` | 否 | — | 飞书机器人签名密钥 |

> 完整配置模板见 `.env.example`

## 项目结构

```
.
├── app.py                      # Flask 主应用入口
├── auth.py                     # 认证模块（账号密码/微信 OAuth/访客模式）
├── db.py                       # 数据库模块（SQLite/PostgreSQL，用户/笔记/设置等表）
├── ai_utils.py                 # AI 调用封装（多模型兼容，流式输出）
├── feishu_push.py              # 飞书推送模块（卡片模板，签名校验，自动重试）
├── routes/                     # Blueprint 模块化路由
│   ├── pages.py                # 页面渲染路由（20+ 工具页面）
│   ├── api.py                  # 通用 API（上传/下载/设置/健康检查）
│   ├── tools.py                # 工具类 API（会议纪要/周报/OCR/MD2PDF/日志AI）
│   ├── analysis.py             # 数据分析 API（CR分析/测试报告/Excel处理）
│   ├── sync.py                 # 云端同步 API
│   ├── collab.py               # 协作功能 API（v1）
│   ├── collab_v2.py            # 协作功能深化 API（v2）
│   ├── visualization.py        # 数据可视化 API（图表模板存储）
│   ├── translator.py           # IT 翻译器 API
│   ├── notes.py                # 牛马笔记 REST API
│   ├── admin.py                # 用户管理平台 API
│   ├── knowledge_graph.py      # 研发知识图谱 API
│   └── hld_generator.py        # HLD 生成器 API
├── templates/                  # HTML 模板（30+ 页面）
│   ├── _navbar.html            # 统一 Apple 风格导航栏
│   ├── index.html              # 首页（工具导航+收藏+统计）
│   ├── knowledge_graph.html    # 研发知识图谱
│   ├── log_analyzer.html       # 日志智能根因分析
│   ├── excel_analysis.html     # CR 问题分析
│   ├── hld_generator.html      # HLD 生成器
│   ├── plan_generator.html     # 软件计划生成器
│   ├── dashboard.html          # 研发健康度 Dashboard
│   └── ...                     # 其他 20+ 工具页面
├── static/                     # 静态资源
│   ├── css/                    # 样式文件（design-system/theme/components/mobile 等）
│   ├── js/                     # JavaScript（components/knowledge_graph/log_root_cause_ai 等）
│   │   └── workers/            # Web Worker（日志/Excel 大文件后台处理）
│   └── manifest.json           # PWA Manifest
├── Dockerfile                  # Docker 构建配置
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
└── README.md                   # 项目说明
```

## 关键特性

### 日志智能根因分析

- 8 类内置历史问题库（内存/看门狗/崩溃/GPS/蓝牙/功耗/传感器/屏幕）
- 3 种异常模式自动识别（连续错误爆发/周期性异常/错误级联）
- 错误链构建（30 秒内错误自动关联因果链）
- AI 深度根因推理（结合统计+模式+错误链+历史匹配，结构化输出）
- 相似历史问题匹配（基于关键词匹配度排序）

### 研发知识图谱

- 7 种节点类型（Bug/需求/模块/人员/版本/测试用例/风险）
- 8 种关系类型（关联/负责/依赖/阻塞/导致/修复/测试/属于）
- Canvas 力导向布局可视化，自动计算节点位置
- 鼠标拖拽平移、滚轮缩放、点击节点查看详情
- CR 分析数据一键导入，自动创建节点和关联关系
- 智能问答：自然语言查询图谱数据
- 核心节点分析：度数最高的节点排名

### CR 分析大文件优化

- 分块上传（2MB 分块，并发上传，断点续传）
- Web Worker 后台线程解析（不阻塞 UI）
- pandas 向量化计算（替代逐行循环，性能提升 10x+）
- 自动分隔符检测（逗号/分号/制表符/竖线）
- 多编码支持（utf-8-sig/utf-8/gbk/gb2312/latin1）
- 200MB 文件支持，真实进度条展示

### 用户数据隔离与同步

- 所有 localStorage 数据按 `u{user_id}_` 前缀隔离
- 登录用户数据自动同步到后端 SQLite/PostgreSQL
- 飞书配置、AI 配置、推送历史随账号保存，换设备自动同步
- 牛马笔记支持后端 REST API，多设备同步

### 飞书推送

- 统一卡片模板（标题+正文+按钮+详情链接）
- HMAC-SHA256 签名校验（解决 sign match fail）
- 失败自动重试（指数退避）
- 推送历史记录（最近 20 条，支持重发）
- CR 分析/站会/项目计划/测试报告均支持推送

## License

MIT
