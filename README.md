# 🛠️ Potential Tools - 个人工具集

一站式工具平台，集成多种实用工具，支持本地运行和云端部署（Railway）。

## ✨ 功能概览

| 工具 | 说明 |
|------|------|
| 📝 牛马笔记 | Markdown 编辑器，支持标签管理、主题切换、完成时间管理 |
| 📄 PDF快转 | Markdown / Word 转 PDF，自动添加自定义水印，支持公式渲染 |
| 📅 软件计划生成器 | 输入项目类型和起始节点，一键生成完整软件计划时间节点表 |
| 📊 项目信息收集 | 收集和管理软件项目的完整技术规格信息 |
| 📊 CR问题分析 | 上传问题清单 Excel，按模块/研发/日期分析，生成带水印 PDF 报告 |
| 🔔 功德+1 | 敲击木鱼积攒功德，自动保存进度 |
| 📋 测试报告分析 | 上传测试报告 Excel，自动提取版本、测试内容、结论等关键字段 |

## 🚀 快速开始

### 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 安装 Playwright Chromium（PDF 生成需要）
playwright install chromium

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
4. 环境变量 `PORT` 由 Railway 自动注入，无需手动配置

## 📋 技术栈

- **后端**: Flask + Gunicorn
- **前端**: HTML5 / CSS3 / Vanilla JavaScript
- **PDF生成**: Playwright (Chromium)
- **Excel解析**: openpyxl / xlrd / BeautifulSoup4
- **文档处理**: python-docx / markdown
- **部署**: Docker / Railway

## 📁 项目结构

```
.
├── app.py                  # Flask 主应用（所有路由和业务逻辑）
├── templates/              # HTML 模板
│   ├── index.html          # 首页（工具导航）
│   ├── excel_analysis.html # CR问题分析页面
│   ├── md2pdf.html         # PDF转换页面
│   ├── merit.html          # 功德+1页面
│   ├── plan_generator.html # 软件计划生成器页面
│   ├── project_info.html   # 项目信息收集页面
│   └── test_report.html    # 测试报告分析页面
├── static/                 # 静态资源
│   ├── md2pdf/             # PDF转换前端
│   └── noteNB/             # 牛马笔记前端（Vue构建）
├── Dockerfile              # Docker 构建配置
├── railway.toml            # Railway 部署配置
├── requirements.txt        # Python 依赖
└── .dockerignore           # Docker 构建忽略文件
```

## 🔧 配置说明

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `PORT` | `5001` | 服务监听端口（Railway 自动注入） |

运行时产生的上传文件和 PDF 存储在 `/tmp/toolbox/` 目录（云平台）或项目根目录（本地）。

## 📌 关键特性

- **分块上传**: 大文件分块上传，突破代理/网关请求体大小限制
- **异步处理**: Excel 分析采用后台任务 + 轮询机制，避免请求超时
- **内存优化**: HTML 格式 Excel 使用流式正则解析，避免 OOM
- **时区处理**: PDF 报告时间统一使用北京时间 (CST, UTC+8)
- **缓存穿透**: Dockerfile 使用 commit SHA 实现缓存失效，确保部署最新代码

## 📄 License

MIT
