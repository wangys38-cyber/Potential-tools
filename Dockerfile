FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright
RUN playwright install chromium --with-deps

# Cache-bust: 确保每次部署都复制最新代码（避免Docker层缓存旧代码）
# 每次提交更新此值，强制Docker失效所有后续层的缓存
ARG CACHE_BUST=20260814-v23-blueprint
RUN echo "Cache bust: ${CACHE_BUST}"

# 允许游客访问（通过环境变量控制，默认允许）
# 安全：不再硬编码 true，可通过 Railway 环境变量覆盖
ENV ALLOW_GUEST=${ALLOW_GUEST:-true}

# 复制应用代码（COPY 层会根据文件内容自动失效缓存）
COPY app.py .
COPY auth.py .
COPY db.py .
COPY ai_utils.py .
COPY bp_ai.py .
COPY templates/ ./templates/
COPY static/ ./static/
COPY railway.toml .
COPY README.md .

# 创建可写目录
RUN mkdir -p /tmp/toolbox/uploads /tmp/toolbox/pdfs

EXPOSE 5001

# 性能优化配置
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app -k gthread --workers 1 --threads 16 --timeout 300 --preload --worker-tmp-dir /dev/shm --keep-alive 10 --max-requests 1000 --max-requests-jitter 50"]
