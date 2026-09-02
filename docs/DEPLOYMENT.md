# Potential Tools 部署文档

## 概述

Potential Tools 支持多种部署方式：
- Railway 一键部署（推荐）
- Docker 容器部署
- 本地直接运行

线上地址：https://wangys666.top

## 环境要求

- Python 3.11+
- 内存：最低 512MB，推荐 1GB+（Playwright PDF 生成需要较多内存）
- 磁盘：最低 2GB（含 Chromium 浏览器）
- 网络：可访问 AI API 服务（如使用 AI 功能）

## 方式一：Railway 部署（推荐）

### 前置准备

1. GitHub 账号
2. Railway 账号（https://railway.app）
3. Fork 本仓库到你的 GitHub

### 部署步骤

1. 登录 Railway，点击「New Project」
2. 选择「Deploy from GitHub repo」
3. 选择 Fork 的 Potential-tools 仓库
4. Railway 自动识别 `Dockerfile` 并开始构建
5. 配置环境变量（见下方「环境变量配置」）
6. （推荐）添加 Volume 挂载到 `/app/data`，持久化 SQLite 数据库
7. 等待构建完成，点击「Generate Domain」生成公网域名
8. 访问域名验证部署成功

### 配置说明

项目根目录的 `railway.toml` 包含部署配置：

```toml
[deploy]
startCommand = "sh -c 'gunicorn -c gunicorn.conf.py app:app'"
healthcheckPath = "/health"
healthcheckTimeout = 300
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 10
```

- 健康检查路径：`/health`
- 健康检查超时：300 秒（首次启动 Playwright 可能较慢）
- 重启策略：失败时自动重启，最多 10 次
- 启动命令：使用 `gunicorn.conf.py` 配置文件

### 自动部署

- Railway 监听 GitHub `main` 分支，每次 push 自动触发重新构建
- 构建过程中服务不受影响，构建完成后自动切换
- 可在 Railway 部署日志中查看构建进度

## 方式二：Docker 部署

### 构建镜像

```bash
# 克隆仓库
git clone https://github.com/wangys38-cyber/Potential-tools.git
cd Potential-tools

# 构建 Docker 镜像
docker build -t potential-tools .
```

### 运行容器

```bash
# 基本运行
docker run -d \
  --name potential-tools \
  -p 5000:5000 \
  -e PORT=5000 \
  -e SESSION_SECRET=your-secret-key \
  -v /path/to/data:/app/data \
  potential-tools

# 完整配置运行
docker run -d \
  --name potential-tools \
  -p 5000:5000 \
  -e PORT=5000 \
  -e ALLOW_GUEST=true \
  -e SESSION_SECRET=your-secret-key \
  -e AI_API_KEY=your-ai-api-key \
  -e AI_BASE_URL=https://api.example.com/v1 \
  -e AI_MODEL=your-model \
  -e FEISHU_WEBHOOK_URL=https://open.feishu.cn/... \
  -e FEISHU_SECRET=your-feishu-secret \
  -v /path/to/data:/app/data \
  --restart unless-stopped \
  potential-tools
```

### Dockerfile 说明

- 基础镜像：`python:3.11-slim`
- 安装系统依赖：ca-certificates
- 安装 Python 依赖：`requirements.txt`
- 安装 Playwright Chromium（含系统依赖）
- 复制应用代码（显式 COPY 所有模块文件和目录）
- 暴露端口：5001（容器内部，通过 `-p` 映射到主机）
- 启动命令：`gunicorn -c gunicorn.conf.py app:app`

### Docker Compose（可选）

创建 `docker-compose.yml`：

```yaml
version: '3.8'
services:
  potential-tools:
    build: .
    container_name: potential-tools
    ports:
      - "5000:5000"
    environment:
      - PORT=5000
      - ALLOW_GUEST=true
      - SESSION_SECRET=${SESSION_SECRET}
      - AI_API_KEY=${AI_API_KEY}
      - AI_BASE_URL=${AI_BASE_URL}
      - AI_MODEL=${AI_MODEL}
      - FEISHU_WEBHOOK_URL=${FEISHU_WEBHOOK_URL}
      - FEISHU_SECRET=${FEISHU_SECRET}
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

运行：
```bash
docker-compose up -d
```

## 方式三：本地直接运行

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

# 安装 Playwright Chromium
playwright install chromium

# 配置环境变量
cp .env.example .env
# 编辑 .env

# 启动服务
python app.py
# 默认运行在 http://localhost:5000
```

### 生产环境本地运行

使用 Gunicorn：

```bash
gunicorn -c gunicorn.conf.py app:app
```

## 环境变量配置

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `PORT` | 否 | `5000` | 服务监听端口（Railway 自动注入） |
| `ALLOW_GUEST` | 否 | `true` | 访客模式开关 |
| `SESSION_SECRET` | 是 | — | Session 加密密钥，生产环境必须设置 |
| `DATABASE_URL` | 否 | — | PostgreSQL 连接字符串，留空使用 SQLite |
| `DATA_DIR` | 否 | `/app/data` | SQLite 数据文件目录 |
| `AI_API_KEY` | 否 | — | AI 服务 API Key |
| `AI_BASE_URL` | 否 | — | AI 服务 API 地址 |
| `AI_MODEL` | 否 | — | 默认 AI 模型 ID |
| `WECHAT_APP_ID` | 否 | — | 微信开放平台 AppID |
| `WECHAT_APP_SECRET` | 否 | — | 微信开放平台 AppSecret |
| `FEISHU_WEBHOOK_URL` | 否 | — | 飞书机器人 Webhook 地址 |
| `FEISHU_SECRET` | 否 | — | 飞书机器人签名密钥 |
| `GUNICORN_WORKERS` | 否 | `1` | Gunicorn 工作进程数 |
| `GUNICORN_THREADS` | 否 | `16` | 每个 worker 的线程数 |
| `GUNICORN_TIMEOUT` | 否 | `300` | 请求超时时间（秒） |
| `GUNICORN_LOG_LEVEL` | 否 | `info` | 日志级别 |

### 生成 SESSION_SECRET

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## 数据库配置

### SQLite（默认）

- 无需额外配置，数据文件存储在 `DATA_DIR` 目录
- Docker 部署时需挂载 Volume 到 `/app/data`
- Railway 部署时需添加 Volume 挂载

### PostgreSQL（推荐生产环境）

设置 `DATABASE_URL` 环境变量：

```
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

应用启动时自动检测并切换到 PostgreSQL。

## Gunicorn 配置说明

`gunicorn.conf.py` 包含生产环境优化配置：

- 工作模式：`gthread`（线程模式，适合 IO 密集型 Flask 应用）
- 工作进程：1（单进程避免内存中性能指标/告警状态多进程不一致）
- 线程数：16
- 超时：300 秒（AI 请求可能耗时较长）
- 最大请求：1000（防止内存泄漏，自动重启 worker）
- 预加载：False（避免 Playwright 资源在 worker 间共享问题）
- 临时目录：`/dev/shm`（内存文件系统提升性能）
- 日志：输出到 stdout（供 Railway 日志收集）

如需多进程部署，需将性能指标和告警状态迁移到共享存储（Redis/数据库）。

## 健康检查

- 健康检查路径：`GET /health`
- 正常响应：`{"status": "ok", "timestamp": ...}`
- Railway 配置超时 300 秒（首次启动较慢）

## 监控与告警

### 性能监控看板

- 管理员访问：`https://your-domain/admin/performance`
- 实时展示：请求统计（P50/P95/P99）、系统指标（CPU/内存/磁盘）、慢查询日志、告警窗口统计

### 告警系统

- 5 分钟滑动窗口监控请求量和 5xx 错误率
- 错误率超过阈值自动触发告警
- 告警历史可在管理员页面查看

### 自动备份

- 定时备份 SQLite 数据库
- 管理员可手动触发备份和下载备份文件
- 备份文件保留策略可配置

## 域名与 HTTPS

### Railway 自定义域名

1. 在 Railway 服务设置中添加自定义域名
2. 在域名 DNS 服务商添加 CNAME 记录指向 Railway 提供的域名
3. Railway 自动配置 HTTPS 证书（Let's Encrypt）

### 反向代理（Nginx）

如使用 Docker 本地部署，可配置 Nginx 反向代理：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        client_max_body_size 200m;
    }
}
```

使用 Certbot 配置 HTTPS：
```bash
certbot --nginx -d your-domain.com
```

## 常见问题

### 部署后健康检查失败

- 首次启动需要下载/初始化 Playwright Chromium，可能需要 3-5 分钟
- 检查 Railway 部署日志是否有错误
- 确认 `SESSION_SECRET` 已设置
- 确认内存至少 512MB

### AI 功能无响应

- 确认 `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL` 环境变量正确
- 在「设置」页面点击「测试连接」验证
- 检查 AI 服务是否可访问

### 数据丢失

- Docker 部署必须挂载 Volume 到 `/app/data`
- Railway 部署必须添加 Volume
- 定期使用管理员备份功能导出备份

### 大文件上传失败

- Nginx 反向代理需设置 `client_max_body_size 200m`
- Railway 默认支持大文件，如遇问题检查请求超时
- 应用支持分块上传，可自动断点续传

### 内存不足

- Playwright PDF 生成需要较多内存
- 如频繁 OOM，升级服务器内存或限制并发
- Gunicorn 单 worker 16 线程适合 1GB 内存实例

## 版本更新

1. 拉取最新代码：`git pull origin main`
2. Docker 部署：重新构建镜像 `docker build -t potential-tools .`，重启容器
3. Railway 部署：push 到 main 分支自动触发部署
4. 本地部署：`pip install -r requirements.txt` 更新依赖，重启服务
5. 数据库表结构自动迁移（应用启动时检测并更新）
