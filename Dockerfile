FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖 + ca-certificates
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright 安装 chromium 并自动安装全部系统依赖
RUN playwright install chromium --with-deps

# Cache bust: 强制 Railway 每次重新复制代码（避免 COPY . . 被缓存）
ARG CACHE_BUST=2026-08-09-v4
RUN echo "Cache bust: $CACHE_BUST"

# 复制应用代码（每次部署都会重新复制，不会被缓存）
COPY . .

# 创建可写目录
RUN mkdir -p /tmp/toolbox/uploads /tmp/toolbox/pdfs

# 声明暴露端口
EXPOSE 5001

# 单 worker + 多线程，适配 Railway 512MB 免费层（sh -c 包装支持 $PORT 变量展开）
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app -k gthread --workers 1 --threads 16 --timeout 300 --max-requests 200 --max-requests-jitter 20"]
