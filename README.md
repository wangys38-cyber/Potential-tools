# Potential Tools

> 一站式研发效率工具平台，为智能硬件研发团队而生。

集成 CR 分析、智能知识库、邮件助手、知识图谱、HLD 生成、项目计划、测试报告等 **20+ 工具**，本地运行，数据不出内网。

[![Version](https://img.shields.io/badge/version-v9.1.0-blue.svg)](https://github.com/wangys38-cyber/Potential-tools/releases)
[![Python](https://img.shields.io/badge/python-3.13-green.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)

---

## 🎉 v9.0 重磅更新 — 研发智能体平台

从"工具集合"进化为"研发智能体平台"，6大核心升级：

### 🤖 Agent 2.0 自主任务执行
- 自然语言指令 → 自动任务规划 → 多工具调用 → 结果输出
- 内置5个工具：查询项目状态、生成报告、发送邮件、创建笔记、知识库搜索
- 敏感操作（发送邮件）需用户确认，安全可控
- 访问：`/agent`

### 🔗 统一数据源管理
- 支持 Jira/eDart、Git、CI/CD、通用数据源
- 连接测试、手动同步、同步状态跟踪
- 配置持久化，敏感字段不返回前端
- 访问：`/data-sources`

### 👥 团队协作空间
- 工作空间管理，多成员协作
- 4种角色：所有者/管理员/编辑者/查看者，细粒度权限
- 评论区支持 @提及，已解决/未解决状态
- 访问：`/workspaces`

### 🚨 智能预警与预测
- **趋势预测**：线性回归 + 移动平均，预测未来CR趋势
- **异常检测**：Z-Score 算法，自动识别CR数量异常波动
- **过点风险评估**：基于未解决BC/Blocker/时间的风险评分和建议
- 预警记录管理：创建/确认/解决/统计
- 访问：`/alerts`

### 🔍 全局搜索
- 跨工具统一搜索：项目、笔记、知识库、CR、文档
- 多源加权排序，搜索建议
- API：`/api/search?q=关键词`

### 🔌 开放 API v1
- 第三方系统可通过 REST API 集成
- 端点：`/api/v1/health`、`/api/v1/projects`、`/api/v1/search`
- 健康检查增强：版本、运行时间、DB状态、内存、CPU

### 📊 项目状态助手（Project Assistant）
- 输入项目名称，一键拉取 eDart/Jira 最新 CR 数据
- 项目健康度评分（0-100分），圆形可视化，健康/关注/风险三档
- KPI 趋势指示：CR总数、未解决、未解决BC、FAIL/PASS模块，对比昨日增减
- 模块状态列表：FAIL优先，支持按状态/BC数/名称排序，展开查看Top BC单
- 每日趋势与累计BUG曲线图表
- 智能对话：自然语言追问，支持标签筛选、经办人统计、blocker问题分析
- 自动刷新：每天 00:00 / 12:00 / 18:00 自动拉取最新状态
- 一键复制状态报告，支持邮件发送
- 访问：`/project-assistant`

### 🔬 CR 智能分析 v2.0
- eDart/Jira 直连拉取，无需手动上传Excel
- 标签筛选分析：支持关键字模糊匹配，智能推荐labels
- 根因分析（RCA）：从CR单获取log，AI分析找到root cause
- 项目状态看板：KPI卡片、趋势图表、模块状态热力图
- 日报自动生成：趋势、结论、阻塞问题、用户无法忍受问题、影响过点问题
- 访问：`/cr-analysis`

### 🎨 暗黑科技风 UI 全面升级
- 全局深色主题（#0D0E12），所有页面统一暗黑风格
- 首页扇形卡片布局，悬停抬起+邻位让位动效
- 3D 卡通角色（Three.js），应用到五张主要工具卡片
- 导航栏毛玻璃效果，完全贴顶无留白
- 健康度圆形评分卡片，6个KPI卡片紧凑一行
- 所有页面添加 theme-color 元标签，浏览器标题栏深色适配
- PWA 支持：可安装为桌面应用，深色启动画面

### 🤖 AI Agent 增强
- 邮件输出美化：专业HTML模板，项目风险综合评估（风险等级+判断依据+建议）
- 记忆功能：输入的指令自动记住，发邮件无需再次确认
- 对话交互优化：关键字匹配智能推荐，输出精简减少token使用
- 访问：`/agent`

### ⚡ 架构升级
- 异步任务框架（4工作线程），耗时操作不阻塞
- ttl_cache 缓存集成，项目状态秒级响应
- 健康检查端点 `/health`
- Three.js 3D 可视化集成（static/js/vendor/three/）

---

## 核心能力

### 智能知识库 v4.0
- **混合检索**：向量语义 + BM25 关键词 + 语义触发三路召回，Rerank 精排
- **中文优化**：bge-small-zh-v1.5 embedding，CrossEncoder 重排序
- **多模态**：图片识别（GLM-4V）、Excel/CSV/Word/PDF 结构化解析
- **甘特图解析**：自动识别项目排期表，提取 Plan/CWV 日期
- **学习闭环**：点赞/点踩反馈驱动检索权重调整
- **Multi-hop 推理**：复杂问题自动拆子问题，分步检索再综合
- **知识洞察**：自动分析文档覆盖、缺失、建议
- **知识图谱**：自动提取人-模块-项目实体关系
- **每日简报**：自动生成 CR 分析摘要

### 项目状态助手
- 输入项目名称，eDart/Jira 直连拉取最新 CR 数据
- 项目健康度评分（0-100分），圆形可视化
- KPI 趋势指示，对比昨日数据增减
- 模块状态列表，FAIL优先，支持排序和展开Top BC
- 智能对话追问，自然语言查询
- 自动刷新：每天 00:00 / 12:00 / 18:00
- 一键复制状态报告，支持邮件发送

### CR 智能分析 v2.0
- eDart/Jira 直连拉取，无需手动上传Excel
- 标签筛选分析，智能推荐labels
- 根因分析（RCA）：AI分析log找到root cause
- 项目状态看板：KPI卡片、趋势图表、模块热力图
- 日报自动生成：趋势、结论、阻塞问题、无法忍受问题、影响过点问题
- Excel 上传兼容：自动解析，趋势图表（每日新增/累计/周对比）
- AI 根因分类、智能归因、趋势预测
- 未解决问题汇总，一键生成周报邮件
- 严重/性能/MTTF 剩余问题统计

### 其他工具
- **邮件助手**：SMTP 发送，CR 周报模板自动生成
- **研发知识图谱**：开发者-模块-问题关联分析
- **HLD 生成器**：AI 自动生成高层设计文档
- **牛马笔记**：本地笔记，完成状态持久化
- **插件系统**：v8.1 插件化架构，支持热加载

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Flask 3.x + SQLite + SQLAlchemy |
| 前端 | Vanilla JS + ECharts + Three.js + Jinja2 |
| AI | 智谱 GLM-4-Plus / GLM-4V-Plus（多模态） |
| 向量 | ChromaDB + bge-small-zh-v1.5 + CrossEncoder |
| 部署 | Python venv + pythonw 后台运行 |

---

## 快速开始

```bash
# 克隆
git clone https://github.com/wangys38-cyber/Potential-tools.git
cd Potential-tools

# 创建虚拟环境（Python 3.13）
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置 AI（必须）
# 在系统设置里配置智谱 GLM API Key，或编辑 ai_configs 表

# 启动
python app.py
# 访问 http://127.0.0.1:5000
```

### 后台运行（Windows）
```powershell
.\.venv\Scripts\pythonw.exe app.py
```

---

## 项目结构

```
Potential-tools/
├── app.py                 # 入口
├── routes/                # 路由
│   ├── knowledge_base.py   # 智能知识库
│   ├── analysis.py         # CR 分析
│   ├── tools.py           # 其他工具
│   └── ...
├── services/ai/           # AI 服务
│   ├── knowledge_base.py  # 知识库核心 v4.0
│   └── factory.py          # AI 服务抽象层
├── templates/              # Jinja2 模板
├── static/                 # 前端资源
├── db/                     # 数据库
└── data/                   # 用户数据（知识库 ChromaDB）
```

---

## 智能知识库 API

| API | 方法 | 说明 |
|-----|------|------|
| `/knowledge-base/api/documents` | GET/POST | 文档列表/上传 |
| `/knowledge-base/api/ask` | POST | 智能问答 |
| `/knowledge-base/api/search` | GET | 全文精确搜索 |
| `/knowledge-base/api/insights` | GET | 知识洞察 |
| `/knowledge-base/api/graph` | GET | 知识图谱 |
| `/knowledge-base/api/feedback` | POST | 点赞/点踩学习 |
| `/knowledge-base/api/feedback-report` | GET | 学习报告 |
| `/knowledge-base/api/cr-summary` | GET | CR 周报摘要 |
| `/knowledge-base/api/daily-brief` | GET | 每日简报 |
| `/knowledge-base/api/chat-history` | GET | 问答历史 |
| `/knowledge-base/api/export` | GET | 导出对话 |
| `/knowledge-base/api/sync-cr` | POST | CR 数据同步 |

---

## 更新日志

- **v9.1.0** — 项目状态助手（健康度圆形评分/KPI趋势/智能对话/自动刷新）、CR智能分析v2.0（eDart直连/标签筛选/根因分析）、暗黑科技风UI全面升级、AI Agent邮件美化与记忆功能、Three.js 3D可视化、全局深色主题色适配
- **v9.0.0** — 研发智能体平台：Agent 2.0自主任务执行、统一数据源管理、团队协作空间、智能预警与预测、全局搜索、开放API v1
- **v8.1.0** — 插件化生态，插件市场，智能知识库 v4.0（学习闭环/Multi-hop/知识图谱/每日简报）
- **v8.0.0** — AI 原生架构，6 个 Phase（AI 对话/NL2SQL/CR 智能归因/Agent 自动分析/智能报告推送/跨工具联动）
- **v7.x** — CR 分析、邮件助手、知识图谱、HLD 生成

---

## License

MIT
