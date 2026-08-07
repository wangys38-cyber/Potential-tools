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

# Cache bust: Railway 自动传入 RAILWAY_GIT_COMMIT_SHA 作为 build arg
ARG RAILWAY_GIT_COMMIT_SHA=unknown
RUN echo "Building from commit: $RAILWAY_GIT_COMMIT_SHA"

# 复制应用代码
COPY . .

# 创建可写目录
RUN mkdir -p /tmp/toolbox/uploads /tmp/toolbox/pdfs

# 声明暴露端口
EXPOSE 5001

# 单 worker + 多线程，适配 Railway 512MB 免费层
CMD gunicorn --bind 0.0.0.0:$PORT app:app -k gthread --workers 1 --threads 16 --timeout 300 --max-requests 200 --max-requests-jitter 20
