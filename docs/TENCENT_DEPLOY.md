# Potential-tools 腾讯云服务器部署指南

本指南适用于将 Potential-tools 部署到腾讯云 CVM（或任意 Linux 服务器），使用 Nginx + Gunicorn + SQLite/PostgreSQL 架构。

## 目录

1. [服务器环境准备](#1-服务器环境准备)
2. [代码拉取与配置](#2-代码拉取与配置)
3. [Python 虚拟环境与依赖](#3-python-虚拟环境与依赖)
4. [Gunicorn 系统服务配置](#4-gunicorn-系统服务配置)
5. [Nginx 反向代理配置](#5-nginx-反向代理配置)
6. [HTTPS 证书配置](#6-https-证书配置)
7. [数据库配置](#7-数据库配置)
8. [防火墙与安全设置](#8-防火墙与安全设置)
9. [自动备份](#9-自动备份)
10. [日志管理](#10-日志管理)
11. [更新与维护](#11-更新与维护)
12. [常见问题排查](#12-常见问题排查)

---

## 1. 服务器环境准备

### 1.1 系统要求

- **操作系统**：Ubuntu 20.04 / 22.04 LTS（推荐）或 CentOS 7/8
- **配置**：2核4G 起步（推荐 4核8G）
- **磁盘**：40G 系统盘 + 数据盘（可选）
- **带宽**：5Mbps 以上

### 1.2 安装基础软件（Ubuntu）

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装基础工具
sudo apt install -y git curl wget vim unzip build-essential

# 安装 Python 3.10+
sudo apt install -y python3 python3-pip python3-venv python3-dev

# 安装 Nginx
sudo apt install -y nginx

# 安装 PostgreSQL（可选，默认用 SQLite）
sudo apt install -y postgresql postgresql-contrib

# 安装 Supervisor（进程管理）
sudo apt install -y supervisor
```

### 1.3 安装基础软件（CentOS）

```bash
# 更新系统
sudo yum update -y

# 安装基础工具
sudo yum install -y git curl wget vim unzip gcc gcc-c++ make

# 安装 Python 3.10+（CentOS 7 需要额外源）
sudo yum install -y python3 python3-pip python3-devel

# 安装 Nginx
sudo yum install -y nginx

# 安装 Supervisor
sudo yum install -y supervisor
```

---

## 2. 代码拉取与配置

### 2.1 创建项目目录

```bash
# 创建项目目录
sudo mkdir -p /var/www/potential-tools
sudo chown $USER:$USER /var/www/potential-tools

# 进入目录
cd /var/www/potential-tools
```

### 2.2 拉取代码

```bash
# 克隆仓库
git clone https://github.com/wangys38-cyber/Potential-tools.git .

# 查看版本
git log --oneline -5
```

### 2.3 配置文件

```bash
# 复制配置模板（如果有）
cp config.example.py config.py 2>/dev/null || true

# 创建数据目录
mkdir -p data uploads pdfs backups

# 设置目录权限
chmod 755 data uploads pdfs backups
```

### 2.4 环境变量配置

创建 `.env` 文件：

```bash
cat > .env << 'EOF'
# 应用配置
FLASK_ENV=production
SECRET_KEY=your-secret-key-here-change-this

# 数据库配置（SQLite 默认，无需修改）
DATABASE_URL=sqlite:////var/www/potential-tools/data/app.db

# PostgreSQL 配置（如使用 PostgreSQL）
# DATABASE_URL=postgresql://username:password@localhost:5432/potential_tools

# AI 配置（可选，用户可在页面设置）
# AI_API_KEY=your-api-key
# AI_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
# AI_MODEL=doubao-pro-32k

# 微信登录配置（可选）
# WECHAT_APP_ID=your-app-id
# WECHAT_APP_SECRET=your-app-secret

# 文件上传限制
MAX_CONTENT_LENGTH=104857600
EOF
```

生成随机 SECRET_KEY：

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 3. Python 虚拟环境与依赖

### 3.1 创建虚拟环境

```bash
cd /var/www/potential-tools

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate
```

### 3.2 安装依赖

```bash
# 升级 pip
pip install --upgrade pip

# 安装项目依赖
pip install -r requirements.txt

# 安装 Gunicorn
pip install gunicorn

# 安装 Playwright（PDF 生成需要）
pip install playwright
playwright install-deps
playwright install chromium
```

### 3.3 初始化数据库

```bash
# 激活虚拟环境
source venv/bin/activate

# 初始化数据库
python3 -c "from app import app; from db import init_db; init_db(); print('Database initialized')"
```

### 3.4 测试运行

```bash
# 测试启动
python3 app.py

# 浏览器访问 http://服务器IP:5000 确认正常
# Ctrl+C 停止
```

---

## 4. Gunicorn 系统服务配置

### 4.1 创建 Gunicorn 配置文件

```bash
cat > gunicorn_config.py << 'EOF'
import multiprocessing

# 监听地址和端口
bind = "127.0.0.1:8000"

# 工作进程数（CPU核心数 * 2 + 1）
workers = multiprocessing.cpu_count() * 2 + 1

# 工作模式
worker_class = "gthread"
threads = 4

# 超时时间（PDF生成需要较长时间）
timeout = 300
graceful_timeout = 30

# 日志
accesslog = "/var/www/potential-tools/logs/gunicorn_access.log"
errorlog = "/var/www/potential-tools/logs/gunicorn_error.log"
loglevel = "info"

# 进程名称
proc_name = "potential-tools"

# 预热加载
preload_app = True

# 最大请求数后重启（防止内存泄漏）
max_requests = 1000
max_requests_jitter = 50
EOF
```

### 4.2 创建日志目录

```bash
mkdir -p /var/www/potential-tools/logs
```

### 4.3 配置 Supervisor

```bash
sudo cat > /etc/supervisor/conf.d/potential-tools.conf << 'EOF'
[program:potential-tools]
directory=/var/www/potential-tools
command=/var/www/potential-tools/venv/bin/gunicorn app:app -c /var/www/potential-tools/gunicorn_config.py
user=www-data
autostart=true
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/var/www/potential-tools/logs/supervisor.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
environment=PATH="/var/www/potential-tools/venv/bin",FLASK_ENV="production"
EOF
```

CentOS 用户将 `user=www-data` 改为 `user=nginx`。

### 4.4 启动服务

```bash
# 重新加载 Supervisor 配置
sudo supervisorctl reread
sudo supervisorctl update

# 启动服务
sudo supervisorctl start potential-tools

# 查看状态
sudo supervisorctl status potential-tools

# 查看日志
sudo tail -f /var/www/potential-tools/logs/supervisor.log
```

### 4.5 常用管理命令

```bash
# 重启服务
sudo supervisorctl restart potential-tools

# 停止服务
sudo supervisorctl stop potential-tools

# 查看日志
sudo tail -100 /var/www/potential-tools/logs/gunicorn_error.log
```

---

## 5. Nginx 反向代理配置

### 5.1 创建 Nginx 配置

```bash
sudo cat > /etc/nginx/sites-available/potential-tools << 'EOF'
server {
    listen 80;
    server_name wangys666.top www.wangys666.top;

    # 客户端最大上传大小
    client_max_body_size 100M;

    # 访问日志
    access_log /var/log/nginx/potential-tools_access.log;
    error_log /var/log/nginx/potential-tools_error.log;

    # Gzip 压缩
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/x-javascript application/xml+rss application/javascript application/json image/svg+xml;

    # 静态文件
    location /static/ {
        alias /var/www/potential-tools/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # 上传文件（如需要直接访问）
    location /uploads/ {
        alias /var/www/potential-tools/uploads/;
        expires 7d;
    }

    # 反向代理到 Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 超时设置（PDF生成需要）
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;

        # WebSocket 支持（如需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # 健康检查
    location = /health {
        proxy_pass http://127.0.0.1:8000/health;
        access_log off;
    }
}
EOF
```

### 5.2 启用配置

```bash
# 创建软链接
sudo ln -s /etc/nginx/sites-available/potential-tools /etc/nginx/sites-enabled/

# 删除默认配置
sudo rm -f /etc/nginx/sites-enabled/default

# 测试配置
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx
```

### 5.3 CentOS Nginx 配置路径

CentOS 的 Nginx 配置目录不同：

```bash
# 配置文件放在 conf.d 目录
sudo cat > /etc/nginx/conf.d/potential-tools.conf << 'EOF'
# 同上配置内容
EOF

# 测试并重启
sudo nginx -t
sudo systemctl restart nginx
```

---

## 6. HTTPS 证书配置

### 6.1 安装 Certbot

```bash
# Ubuntu
sudo apt install -y certbot python3-certbot-nginx

# CentOS
sudo yum install -y certbot python3-certbot-nginx
```

### 6.2 申请证书

```bash
# 自动配置 HTTPS
sudo certbot --nginx -d wangys666.top -d www.wangys666.top

# 按提示输入邮箱和同意条款
```

### 6.3 自动续期

```bash
# 测试续期
sudo certbot renew --dry-run

# Certbot 会自动添加定时任务，查看：
sudo systemctl list-timers | grep certbot
```

### 6.4 手动配置 HTTPS（如 Certbot 失败）

证书申请后，修改 Nginx 配置：

```nginx
server {
    listen 443 ssl http2;
    server_name wangys666.top www.wangys666.top;

    ssl_certificate /etc/letsencrypt/live/wangys666.top/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/wangys666.top/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # 其他配置同上...
}

# HTTP 重定向到 HTTPS
server {
    listen 80;
    server_name wangys666.top www.wangys666.top;
    return 301 https://$host$request_uri;
}
```

---

## 7. 数据库配置

### 7.1 SQLite（默认，推荐小团队）

无需额外配置，数据库文件位于：
```
/var/www/potential-tools/data/app.db
```

**注意**：确保 `data` 目录有写入权限：
```bash
sudo chown -R www-data:www-data /var/www/potential-tools/data
sudo chmod 755 /var/www/potential-tools/data
```

### 7.2 PostgreSQL（推荐生产环境）

#### 安装和配置

```bash
# 安装 PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# 切换到 postgres 用户
sudo -u postgres psql
```

在 PostgreSQL 命令行中执行：

```sql
-- 创建用户
CREATE USER potential WITH PASSWORD 'your-password-here';

-- 创建数据库
CREATE DATABASE potential_tools OWNER potential;

-- 授予权限
GRANT ALL PRIVILEGES ON DATABASE potential_tools TO potential;

-- 退出
\q
```

#### 修改环境变量

```bash
# 修改 .env 文件
DATABASE_URL=postgresql://potential:your-password-here@localhost:5432/potential_tools
```

#### 初始化数据库

```bash
cd /var/www/potential-tools
source venv/bin/activate
python3 -c "from app import app; from db import init_db; init_db(); print('PostgreSQL initialized')"
```

#### 定时备份

```bash
# 创建备份脚本
cat > /var/www/potential-tools/backup_pg.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/var/www/potential-tools/backups"
DATE=$(date +%Y%m%d_%H%M%S)
pg_dump -U potential potential_tools | gzip > "$BACKUP_DIR/pg_backup_$DATE.sql.gz"
find $BACKUP_DIR -name "pg_backup_*.sql.gz" -mtime +7 -delete
EOF

chmod +x /var/www/potential-tools/backup_pg.sh

# 添加定时任务（每天凌晨2点）
(crontab -l 2>/dev/null; echo "0 2 * * * /var/www/potential-tools/backup_pg.sh") | crontab -
```

---

## 8. 防火墙与安全设置

### 8.1 配置防火墙（Ubuntu UFW）

```bash
# 允许 SSH
sudo ufw allow 22/tcp

# 允许 HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 启用防火墙
sudo ufw enable

# 查看状态
sudo ufw status
```

### 8.2 配置防火墙（CentOS firewalld）

```bash
# 允许 HTTP/HTTPS
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https

# 重新加载
sudo firewall-cmd --reload

# 查看状态
sudo firewall-cmd --list-all
```

### 8.3 腾讯云安全组

在腾讯云控制台配置安全组：
- 入站规则：允许 22（SSH）、80（HTTP）、443（HTTPS）
- 出站规则：全部允许
- 数据库端口（5432）不要对外开放

### 8.4 文件权限加固

```bash
# 设置项目目录权限
sudo chown -R www-data:www-data /var/www/potential-tools
sudo find /var/www/potential-tools -type d -exec chmod 755 {} \;
sudo find /var/www/potential-tools -type f -exec chmod 644 {} \;

# 敏感文件限制权限
sudo chmod 600 /var/www/potential-tools/.env
sudo chmod 600 /var/www/potential-tools/data/app.db
```

### 8.5 禁用密码登录（可选，推荐）

```bash
# 编辑 SSH 配置
sudo vim /etc/ssh/sshd_config

# 修改以下配置
PasswordAuthentication no
PubkeyAuthentication yes

# 重启 SSH
sudo systemctl restart sshd
```

**注意**：确保已配置 SSH 密钥登录后再禁用密码登录！

---

## 9. 自动备份

### 9.1 创建备份脚本

```bash
cat > /var/www/potential-tools/backup.sh << 'EOF'
#!/bin/bash

PROJECT_DIR="/var/www/potential-tools"
BACKUP_DIR="$PROJECT_DIR/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# 创建备份目录
mkdir -p $BACKUP_DIR

# 备份数据库（SQLite）
if [ -f "$PROJECT_DIR/data/app.db" ]; then
    sqlite3 $PROJECT_DIR/data/app.db ".backup" "$BACKUP_DIR/db_$DATE.db"
fi

# 备份上传文件
if [ -d "$PROJECT_DIR/uploads" ]; then
    tar -czf "$BACKUP_DIR/uploads_$DATE.tar.gz" -C $PROJECT_DIR uploads
fi

# 备份配置
cp $PROJECT_DIR/.env "$BACKUP_DIR/env_$DATE" 2>/dev/null

# 删除7天前的备份
find $BACKUP_DIR -name "*.db" -mtime +7 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete
find $BACKUP_DIR -name "env_*" -mtime +7 -delete

echo "Backup completed: $DATE"
EOF

chmod +x /var/www/potential-tools/backup.sh
```

### 9.2 添加定时任务

```bash
# 每天凌晨3点备份
(crontab -l 2>/dev/null; echo "0 3 * * * /var/www/potential-tools/backup.sh >> /var/www/potential-tools/logs/backup.log 2>&1") | crontab -

# 查看定时任务
crontab -l
```

### 9.3 备份到腾讯云 COS（可选）

安装 coscmd：

```bash
pip install coscmd

# 配置
coscmd config -a <SecretId> -s <SecretKey> -b <BucketName-APPID> -r <Region>

# 在备份脚本末尾添加
coscmd upload -r $BACKUP_DIR /backups/
```

---

## 10. 日志管理

### 10.1 日志轮转

```bash
sudo cat > /etc/logrotate.d/potential-tools << 'EOF'
/var/www/potential-tools/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    copytruncate
    create 0644 www-data www-data
}
EOF
```

### 10.2 常用日志查看

```bash
# 应用错误日志
sudo tail -f /var/www/potential-tools/logs/gunicorn_error.log

# Nginx 访问日志
sudo tail -f /var/log/nginx/potential-tools_access.log

# Nginx 错误日志
sudo tail -f /var/log/nginx/potential-tools_error.log

# Supervisor 日志
sudo tail -f /var/www/potential-tools/logs/supervisor.log
```

---

## 11. 更新与维护

### 11.1 更新代码

```bash
cd /var/www/potential-tools

# 拉取最新代码
git pull origin main

# 激活虚拟环境
source venv/bin/activate

# 安装新增依赖
pip install -r requirements.txt

# 数据库迁移（如有）
python3 -c "from db import init_db; init_db()"

# 重启服务
sudo supervisorctl restart potential-tools
```

### 11.2 一键更新脚本

```bash
cat > /var/www/potential-tools/update.sh << 'EOF'
#!/bin/bash
cd /var/www/potential-tools

echo "=== Pulling latest code ==="
git pull origin main

echo "=== Installing dependencies ==="
source venv/bin/activate
pip install -r requirements.txt

echo "=== Migrating database ==="
python3 -c "from db import init_db; init_db()"

echo "=== Restarting service ==="
sudo supervisorctl restart potential-tools

echo "=== Done ==="
sudo supervisorctl status potential-tools
EOF

chmod +x /var/www/potential-tools/update.sh
```

使用：
```bash
/var/www/potential-tools/update.sh
```

### 11.3 系统监控

```bash
# 查看 CPU/内存使用
top
htop

# 查看磁盘使用
df -h

# 查看内存使用
free -h

# 查看服务状态
sudo supervisorctl status
sudo systemctl status nginx
```

---

## 12. 常见问题排查

### 12.1 502 Bad Gateway

**原因**：Gunicorn 未启动或崩溃

**排查**：
```bash
# 查看 Gunicorn 状态
sudo supervisorctl status potential-tools

# 查看错误日志
sudo tail -100 /var/www/potential-tools/logs/gunicorn_error.log

# 重启服务
sudo supervisorctl restart potential-tools
```

### 12.2 500 Internal Server Error

**原因**：应用代码错误

**排查**：
```bash
# 查看应用日志
sudo tail -100 /var/www/potential-tools/logs/gunicorn_error.log

# 直接运行测试
cd /var/www/potential-tools
source venv/bin/activate
python3 app.py
```

### 12.3 403 Forbidden

**原因**：文件权限问题

**修复**：
```bash
sudo chown -R www-data:www-data /var/www/potential-tools
sudo chmod -R 755 /var/www/potential-tools
```

### 12.4 数据库锁定（SQLite）

**原因**：SQLite 并发写入限制

**解决方案**：
- 小流量可接受
- 高流量建议迁移到 PostgreSQL

### 12.5 PDF 生成失败

**原因**：Playwright 未安装或内存不足

**修复**：
```bash
cd /var/www/potential-tools
source venv/bin/activate
playwright install-deps
playwright install chromium

# 增加交换内存（如内存不足）
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### 12.6 上传文件失败

**原因**：文件大小限制

**修复**：
- Nginx 配置：`client_max_body_size 100M;`
- 应用配置：`MAX_CONTENT_LENGTH=104857600`

### 12.7 静态文件 404

**原因**：Nginx 静态文件路径配置错误

**检查**：
```bash
# 确认静态文件存在
ls -la /var/www/potential-tools/static/

# 检查 Nginx 配置
sudo nginx -t
```

---

## 附录：快速部署脚本

将以下内容保存为 `deploy.sh`，一键部署：

```bash
#!/bin/bash
set -e

echo "=== Potential-tools 一键部署脚本 ==="

# 1. 安装依赖
echo "[1/6] 安装系统依赖..."
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nginx supervisor

# 2. 拉取代码
echo "[2/6] 拉取代码..."
sudo mkdir -p /var/www/potential-tools
sudo chown $USER:$USER /var/www/potential-tools
cd /var/www/potential-tools
git clone https://github.com/wangys38-cyber/Potential-tools.git .

# 3. 配置环境
echo "[3/6] 配置环境..."
mkdir -p data uploads pdfs backups logs
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt gunicorn playwright
playwright install-deps
playwright install chromium

# 4. 初始化数据库
echo "[4/6] 初始化数据库..."
python3 -c "from db import init_db; init_db()"

# 5. 配置服务
echo "[5/6] 配置服务..."
# （需要手动配置 Gunicorn、Nginx、Supervisor，参考上文）

# 6. 完成
echo "[6/6] 部署完成！"
echo "请继续配置 Gunicorn、Nginx 和 HTTPS 证书"
```

---

## 性能优化建议

1. **启用 Redis 缓存**：安装 Redis，配置 Flask-Caching
2. **CDN 加速**：静态文件使用腾讯云 CDN
3. **数据库优化**：PostgreSQL + 连接池
4. **负载均衡**：多台服务器 + 负载均衡器
5. **对象存储**：上传文件存储到腾讯云 COS

---

**部署完成后，访问 https://wangys666.top 即可使用。**

如有问题，查看日志文件或联系技术支持。
