FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（与最后成功构建完全一致，不改动此层）
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright
RUN playwright install chromium --with-deps

# Cache-bust
ARG CACHE_BUST=20260813-v3-python-refresh
RUN echo "Cache bust: ${CACHE_BUST}"

# 复制应用代码
COPY app.py .
COPY auth.py .
COPY db.py .
COPY templates/ ./templates/
COPY static/ ./static/
COPY railway.toml .
COPY README.md .

# 用 Python 从 GitHub 下载最新代码覆盖（绕过 Docker COPY 缓存）
# Python 已在镜像中，无需安装额外依赖，不影响上层缓存
RUN echo "${CACHE_BUST}" && python3 -c "import urllib.request,tarfile,io,os,shutil;resp=urllib.request.urlopen('https://github.com/wangys38-cyber/Potential-tools/archive/refs/heads/main.tar.gz',timeout=60);data=resp.read();tar=tarfile.open(fileobj=io.BytesIO(data));tar.extractall('/tmp/repo');tar.close();src='/tmp/repo/Potential-tools-main';shutil.rmtree('/app/static');shutil.copytree(src+'/static','/app/static');shutil.rmtree('/app/templates');shutil.copytree(src+'/templates','/app/templates');[shutil.copy2(src+'/'+f,'/app/'+f) for f in ['app.py','auth.py','db.py']];shutil.rmtree('/tmp/repo');print('Refreshed from GitHub');print('components.js: %d bytes' % os.path.getsize('/app/static/js/components.js'))"

# 创建可写目录
RUN mkdir -p /tmp/toolbox/uploads /tmp/toolbox/pdfs

EXPOSE 5001

# 与最后成功构建完全一致的 CMD
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app -k gthread --workers 1 --threads 16 --timeout 300 --preload --worker-tmp-dir /dev/shm --keep-alive 10 --max-requests 1000 --max-requests-jitter 50"]
