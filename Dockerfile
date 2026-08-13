FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（含 curl 用于 GitHub 下载）
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright
RUN playwright install chromium --with-deps

# Cache-bust
ARG CACHE_BUST=20260813-v3-curl-refresh
RUN echo "Cache bust: ${CACHE_BUST}"

# 复制应用代码（可能被 Docker 缓存）
COPY app.py .
COPY auth.py .
COPY db.py .
COPY templates/ ./templates/
COPY static/ ./static/
COPY railway.toml .
COPY README.md .

# 强制从 GitHub 下载最新代码，覆盖可能被缓存的 COPY 文件
# 这一步的 RUN 命令包含 CACHE_BUST 值，确保每次构建都重新执行
RUN echo "Fetching latest code from GitHub (${CACHE_BUST})..." && \
    curl -sL --fail "https://github.com/wangys38-cyber/Potential-tools/archive/refs/heads/main.tar.gz" -o /tmp/repo.tar.gz && \
    tar xzf /tmp/repo.tar.gz -C /tmp && \
    cp /tmp/Potential-tools-main/app.py /app/ && \
    cp /tmp/Potential-tools-main/auth.py /app/ && \
    cp /tmp/Potential-tools-main/db.py /app/ && \
    rm -rf /app/templates /app/static && \
    cp -r /tmp/Potential-tools-main/templates /app/templates && \
    cp -r /tmp/Potential-tools-main/static /app/static && \
    rm -rf /tmp/repo.tar.gz /tmp/Potential-tools-main && \
    echo "=== File sizes after GitHub refresh ===" && \
    wc -c /app/static/js/components.js && \
    wc -c /app/static/css/theme.css && \
    echo "=== GitHub refresh complete ==="

# 创建可写目录
RUN mkdir -p /tmp/toolbox/uploads /tmp/toolbox/pdfs

# Railway 运行时自动注入 PORT 环境变量
EXPOSE 8080

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} app:app -k gthread --workers 1 --threads 16 --timeout 300 --preload --worker-tmp-dir /dev/shm --keep-alive 10 --max-requests 1000 --max-requests-jitter 50"]
