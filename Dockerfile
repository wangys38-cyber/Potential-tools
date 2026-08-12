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
ARG CACHE_BUST=20260812-v13-lxml-fix
RUN echo "Cache bust: ${CACHE_BUST}"

# 复制应用代码（COPY 层会根据文件内容自动失效缓存）
COPY app.py .
COPY auth.py .
COPY db.py .
COPY config_oauth.json .
COPY templates/ ./templates/
COPY static/ ./static/
COPY railway.toml .
COPY README.md .

# 创建可写目录
RUN mkdir -p /tmp/toolbox/uploads /tmp/toolbox/pdfs

EXPOSE 5001

# 性能优化配置：
# --preload: 预加载应用代码，减少worker启动时间，模板/缓存全局共享
# --worker-tmp-dir /dev/shm: 使用内存文件系统存储worker心跳，避免磁盘I/O
# --keep-alive 10: 保持连接10秒，减少TCP握手开销（工具页有prefetch，连接复用频繁）
# --max-requests 1000: 每1000请求回收worker，防止内存泄漏
# --max-requests-jitter 50: 随机抖动，避免多worker同时回收
# 1 worker + 16 threads: 避免多worker CPU竞争（Railway容器CPU有限）
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app -k gthread --workers 1 --threads 16 --timeout 300 --preload --worker-tmp-dir /dev/shm --keep-alive 10 --max-requests 1000 --max-requests-jitter 50"]
