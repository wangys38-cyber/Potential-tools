"""
响应压缩中间件 — gzip/deflate 压缩 API 响应，减少传输体积
- 仅压缩文本类响应（JSON/HTML/CSS/JS/XML）
- 最小压缩阈值 1KB（小响应压缩反而更慢）
- 尊重 Accept-Encoding 请求头
- 跳过已编码响应（Content-Encoding 已设置）
"""
import gzip
import io
import logging
from flask import request, g

logger = logging.getLogger(__name__)

# 可压缩的 Content-Type 前缀
COMPRESSIBLE_TYPES = (
    'text/',
    'application/json',
    'application/javascript',
    'application/xml',
    'application/xhtml+xml',
    'image/svg+xml',
)

MIN_COMPRESS_SIZE = 1024  # 小于1KB不压缩


def _is_compressible(content_type):
    if not content_type:
        return False
    ct = content_type.lower()
    return any(ct.startswith(t) for t in COMPRESSIBLE_TYPES)


def register_compression_middleware(app):
    """注册 gzip 压缩中间件到 Flask app"""

    @app.after_request
    def _compress_response(response):
        try:
            # 跳过已编码响应
            if response.headers.get('Content-Encoding'):
                return response

            # 检查客户端是否接受 gzip
            accept_encoding = request.headers.get('Accept-Encoding', '')
            if 'gzip' not in accept_encoding.lower():
                return response

            # 检查响应大小
            response.direct_passthrough = False
            data = response.get_data()
            if not data or len(data) < MIN_COMPRESS_SIZE:
                return response

            # 检查 Content-Type
            content_type = response.headers.get('Content-Type', '')
            if not _is_compressible(content_type):
                return response

            # 执行 gzip 压缩
            buf = io.BytesIO()
            with gzip.GzipFile(mode='wb', fileobj=buf, compresslevel=6) as gz:
                gz.write(data)
            compressed = buf.getvalue()

            # 只有压缩后更小才使用
            if len(compressed) >= len(data):
                return response

            response.set_data(compressed)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = len(compressed)
            response.headers.add('Vary', 'Accept-Encoding')

        except Exception as e:
            logger.warning(f'响应压缩失败: {e}')

        return response

    return app


def register_cache_headers(app, static_max_age=86400, api_max_age=0):
    """
    注册缓存控制头中间件
    - 静态资源（/static/）: 长缓存 + immutable
    - API 响应: 不缓存（动态数据）
    - 页面: 短缓存
    """

    @app.after_request
    def _set_cache_headers(response):
        path = request.path

        if path.startswith('/static/'):
            response.headers['Cache-Control'] = f'public, max-age={static_max_age}, immutable'
        elif path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
        else:
            response.headers['Cache-Control'] = 'public, max-age=300'

        return response

    return app
