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

# Cache-bust: 确保每次构建都复制最新代码（避免Docker层缓存旧代码）
ARG CACHE_BUST=20260902-v1-add-alerting-monitoring
RUN echo "Cache bust: ${CACHE_BUST}"

# 允许访客访问（通过环境变量控制，默认允许）
ENV ALLOW_GUEST=${ALLOW_GUEST:-true}

# 复制应用代码
COPY app.py .
COPY auth.py .
COPY db.py .
COPY ai_utils.py .
COPY bp_ai.py .
COPY bp_user.py .
COPY feishu_push.py .
COPY date_utils.py .
COPY report_builders.py .
COPY excel_analyzers.py .
COPY crypto_utils.py .
COPY error_utils.py .
COPY rate_limiter.py .
COPY request_logger.py .
COPY security.py .
COPY ttl_cache.py .
COPY performance_middleware.py .
COPY compression_middleware.py .
COPY task_queue.py .
COPY system_metrics.py .
COPY alerting.py .
COPY backup_scheduler.py .
COPY gunicorn.conf.py .
COPY routes/ ./routes/
COPY templates/ ./templates/
COPY static/ ./static/
COPY glossaries/ ./glossaries/
COPY railway.toml .
COPY README.md .

# 创建可写目录
RUN mkdir -p /tmp/toolbox/uploads /tmp/toolbox/pdfs /app/data

EXPOSE 5001

# 生产环境启动：使用 gunicorn 配置文件
CMD ["sh", "-c", "gunicorn -c gunicorn.conf.py app:app"]
