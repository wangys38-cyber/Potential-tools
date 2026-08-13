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

# Cache-bust: 每次部署强制复制最新代码
# 方案: 先写入版本标记文件到目标目录,改变目录校验和,强制 COPY 层失效
ARG CACHE_BUST=20260813-v3-force-static-refresh
RUN echo "Cache bust: ${CACHE_BUST}" && \
    mkdir -p /app/static /app/templates && \
    echo "${CACHE_BUST}" > /app/_build_version.txt

# 复制应用代码
COPY app.py .
COPY auth.py .
COPY db.py .
COPY templates/ ./templates/
COPY static/ ./static/

# 验证文件确实更新了（构建时可见）
RUN echo "=== Verify deployed files ===" && \
    wc -c /app/static/js/components.js && \
    wc -c /app/static/css/theme.css && \
    cat /app/static/_version.txt && \
    echo "=== Files verified ==="

# 创建可写目录
RUN mkdir -p /tmp/toolbox/uploads /tmp/toolbox/pdfs

# Railway 运行时自动注入 PORT 环境变量，不要在 Dockerfile 中硬编码
# 自定义域名的端口在 Railway Dashboard → Networking 中配置
EXPOSE 8080

# 性能优化配置：
# --preload: 预加载应用代码，减少worker启动时间，模板/缓存全局共享
# --worker-tmp-dir /dev/shm: 使用内存文件系统存储worker心跳，避免磁盘I/O
# --keep-alive 10: 保持连接10秒，减少TCP握手开销（工具页有prefetch，连接复用频繁）
# --max-requests 1000: 每1000请求回收worker，防止内存泄漏
# --max-requests-jitter 50: 随机抖动，避免多worker同时回收
# 1 worker + 16 threads: 避免多worker CPU竞争（Railway容器CPU有限）
# 端口: Railway 自动注入 PORT，本地默认 8080
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} app:app -k gthread --workers 1 --threads 16 --timeout 300 --preload --worker-tmp-dir /dev/shm --keep-alive 10 --max-requests 1000 --max-requests-jitter 50"]
