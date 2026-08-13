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

# ====== 直接从 GitHub 下载最新代码（绕过 Docker COPY 层缓存）======
# Railway 的 Docker COPY 缓存无法通过 ARG 失效，改用 GitHub API 下载
ARG CACHE_BUST=20260813-v3-github-fetch
RUN echo "Cache bust: ${CACHE_BUST}" && \
    python3 -c "\
import urllib.request, tarfile, io, os, shutil; \
print('Downloading from GitHub...'); \
url = 'https://github.com/wangys38-cyber/Potential-tools/archive/refs/heads/main.tar.gz'; \
resp = urllib.request.urlopen(url, timeout=60); \
data = resp.read(); \
print(f'Downloaded {len(data)} bytes'); \
tar = tarfile.open(fileobj=io.BytesIO(data)); \
tar.extractall('/tmp/repo'); \
tar.close(); \
src = '/tmp/repo/Potential-tools-main'; \
for item in ['app.py', 'auth.py', 'db.py', 'templates', 'static', 'railway.toml', 'README.md']: \
    dst = os.path.join('/app', item); \
    if os.path.isdir(dst): shutil.rmtree(dst); \
    elif os.path.exists(dst): os.remove(dst); \
    s = os.path.join(src, item); \
    if os.path.isdir(s): shutil.copytree(s, dst); \
    else: shutil.copy2(s, dst); \
shutil.rmtree('/tmp/repo'); \
print('Code deployed from GitHub successfully')"

# 验证文件大小（构建日志可见）
RUN echo "=== File verification ===" && \
    wc -c /app/static/js/components.js && \
    wc -c /app/static/css/theme.css && \
    echo "components.js should be ~39000 bytes" && \
    echo "theme.css should be ~16000 bytes" && \
    echo "=== Verification complete ==="

# 创建可写目录
RUN mkdir -p /tmp/toolbox/uploads /tmp/toolbox/pdfs

# Railway 运行时自动注入 PORT 环境变量
EXPOSE 8080

# 性能优化配置
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} app:app -k gthread --workers 1 --threads 16 --timeout 300 --preload --worker-tmp-dir /dev/shm --keep-alive 10 --max-requests 1000 --max-requests-jitter 50"]
