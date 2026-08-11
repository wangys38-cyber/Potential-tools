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
ARG CACHE_BUST=1
RUN echo "Cache bust: ${CACHE_BUST}"

# 复制应用代码
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

# 单 worker + 多线程（不设max-requests，避免worker回收杀死后台分析线程）
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app -k gthread --workers 1 --threads 16 --timeout 300"]
