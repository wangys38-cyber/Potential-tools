from flask import Flask, render_template, request, send_file, send_from_directory, jsonify, redirect, session, url_for
import os
import sys
import re
import logging
import traceback
import json
import tempfile
import time
import hashlib
import gc
from datetime import datetime, timezone, timedelta
from functools import wraps

# 认证模块
import auth
import db

# 性能优化：Whingoise直接服务静态文件，Flask-Compress启用gzip
from whitenoise import WhiteNoise
from flask_compress import Compress

_CST = timezone(timedelta(hours=8))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.abspath(os.path.dirname(__file__))

template_dir = os.path.join(base_dir, 'templates')
static_dir = os.path.join(base_dir, 'static')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

# 启用 gzip 压缩（HTML/JSON/CSS/JS 响应自动压缩，减少传输量 60-80%）
Compress(app)
app.config['COMPRESS_MIMETYPES'] = [
    'text/html', 'text/css', 'text/xml',
    'application/json', 'application/javascript',
    'application/xml', 'image/svg+xml',
]
app.config['COMPRESS_LEVEL'] = 6

# Whitenoise: 直接服务静态文件，跳过Flask请求处理（性能提升10倍+）
app.wsgi_app = WhiteNoise(
    app.wsgi_app,
    root=static_dir,
    prefix='/static/',
    max_age=3600,  # 浏览器缓存1小时
)

# 生产环境优化：关闭模板自动重载（避免每次请求检查文件修改时间）
_is_production = bool(os.environ.get('RAILWAY_STATIC_URL') or os.environ.get('PORT'))
app.config['TEMPLATES_AUTO_RELOAD'] = not _is_production
app.config['DEBUG'] = not _is_production
app.secret_key = auth.SESSION_SECRET

# Session 配置 — 确保登录状态持久化、跨页面共享
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = _is_production  # HTTPS环境下启用Secure

# 静态文件缓存 — 浏览器缓存1小时，减少重复请求
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600 if _is_production else 0

# 配置 - Railway等云平台使用 /tmp 作为可写目录
if os.environ.get('RAILWAY_STATIC_URL') or os.environ.get('PORT'):
    _runtime_dir = '/tmp/toolbox'
else:
    _runtime_dir = base_dir

app.config['UPLOAD_FOLDER'] = os.path.join(_runtime_dir, 'uploads')
app.config['PDF_FOLDER'] = os.path.join(_runtime_dir, 'pdfs')
app.config['AI_CONFIG_FILE'] = os.path.join(_runtime_dir, 'ai_config.json')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PDF_FOLDER'], exist_ok=True)

# 注入模板上下文：当前用户信息（仅对模板渲染生效）
@app.context_processor
def inject_user():
    # 快速检查 session，避免无谓的字典构造
    if not session.get('user_id'):
        return dict(current_user=None, is_logged_in=False)
    return dict(
        current_user={
            'id': session.get('user_id'),
            'name': session.get('user_name', ''),
            'email': session.get('user_email', ''),
            'avatar': session.get('user_avatar', ''),
            'provider': session.get('user_provider', ''),
        },
        is_logged_in=True,
    )


# ==================== 登录拦截 ====================
# 允许无需登录即可访问的路径前缀（按频率排序，命中即返回）
_PUBLIC_PATHS = (
    '/static/',
    '/assets/',
    '/login',
    '/auth/',
    '/health',
)

@app.before_request
def require_login():
    """全局登录拦截：未登录用户自动跳转到登录页"""
    path = request.path

    # 公开路径 — 最先检查，快速放行（静态文件、登录、OAuth回调等）
    for prefix in _PUBLIC_PATHS:
        if path.startswith(prefix):
            return None

    # 已登录 — 放行（仅检查 session，不查数据库）
    if session.get('user_id'):
        return None

    # 如果允许游客模式 — 放行
    if auth.ALLOW_GUEST:
        return None

    # 记录用户原始请求路径，登录后跳回
    if path != '/' and not path.startswith('/api/'):
        session['next_url'] = path
    else:
        session['next_url'] = '/'

    # API 请求返回 401，页面请求 302 跳转
    if path.startswith('/api/'):
        return jsonify({'error': '请先登录', 'need_login': True}), 401
    return redirect(url_for('login_page'))


@app.after_request
def add_cache_headers(response):
    """为静态资源添加缓存头，减少重复下载"""
    path = request.path
    # 静态文件缓存1小时
    if path.startswith('/static/') or path.startswith('/assets/'):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    # API 响应不缓存
    elif path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


def normalize_date(date_str):
    """将各种格式的日期字符串统一为 YYYY-MM-DD 格式，便于排序"""
    if not date_str:
        return None
    
    date_str = str(date_str).strip()
    
    # DD/Mon/YY [time] 或 DD/Mon/YYYY [time] 格式 (如 23/May/26 9:56 PM)
    m = re.match(r'^(\d{1,2})/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/(\d{2,4})', date_str, re.IGNORECASE)
    if m:
        day, mon, year = int(m.group(1)), m.group(2).capitalize(), m.group(3)
        months = {'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
                  'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'}
        if len(year) == 2:
            year = '20' + year
        return f'{year}-{months[mon]}-{day:02d}'
    
    # 已经是 YYYY-MM-DD 格式
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', date_str)
    if m:
        return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    
    # DD/MM/YYYY [time] 或 DD/MM/YY [time] 格式
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})', date_str)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if len(year) == 2:
            year = '20' + year
        return f'{year}-{month:02d}-{day:02d}'
    
    # YYYY/MM/DD [time] 格式
    m = re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})', date_str)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    
    # DD-MM-YYYY [time] 格式
    m = re.match(r'^(\d{1,2})-(\d{1,2})-(\d{2,4})', date_str)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if len(year) == 2:
            year = '20' + year
        return f'{year}-{month:02d}-{day:02d}'
    
    # 数字格式: 20260523 -> 2026-05-23
    m = re.match(r'^(\d{4})(\d{2})(\d{2})$', date_str)
    if m:
        return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    
    # 尝试用 datetime 解析
    try:
        for fmt in ['%Y-%m-%d', '%d/%b/%Y', '%d/%b/%y', '%d/%m/%Y', '%d/%m/%y', '%Y/%m/%d', '%d-%m-%Y', '%d-%b-%Y']:
            try:
                dt = datetime.strptime(date_str[:20].strip(), fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
    except Exception:
        pass
    
    return date_str[:10] if len(date_str) >= 10 else date_str
# === Excel 文件读取辅助函数 ===
class ExcelReader:
    """统一的 Excel 读取器，支持 .xls 和 .xlsx 格式，以及 HTML 格式的 Excel 文件"""
    
    def __init__(self, file_path):
        self.file_path = file_path
        self.ext = os.path.splitext(file_path)[1].lower()
        self._wb = None
        self._is_xls = self.ext == '.xls'
        self._is_html = False
        self._read_only = False
        
    def open(self):
        # 检测是否是 HTML 格式的假 Excel 文件
        if self._is_xls:
            with open(self.file_path, 'rb') as f:
                header = f.read(100)
            if b'<html' in header.lower() or b'<!doctype' in header.lower():
                self._is_html = True
        
        if self._is_html:
            return self  # HTML 格式不需要打开
        
        if self._is_xls:
            import xlrd
            try:
                self._wb = xlrd.open_workbook(self.file_path)
            except Exception as e:
                raise ValueError(f'无法读取 .xls 文件: {str(e)}。如果文件是从网页下载的，请转换为 .xlsx 格式后再上传。')
        else:
            from openpyxl import load_workbook
            # 先尝试 read_only=True（内存效率高），如果读到的行太少则回退到 read_only=False
            self._wb = load_workbook(self.file_path, data_only=True, read_only=True)
            self._read_only = True
        return self
    
    def close(self):
        if self._wb and not self._is_xls and not self._is_html:
            self._wb.close()
    
    @property
    def sheetnames(self):
        if self._is_html:
            return ['Sheet1']  # HTML 格式默认返回一个 sheet
        if self._is_xls:
            return self._wb.sheet_names()
        return self._wb.sheetnames
    
    def get_sheet_data(self, sheet_name):
        """获取指定 sheet 的所有行数据，返回 list of lists"""
        if self._is_html:
            return self._parse_html_excel()
        
        if self._is_xls:
            sheet = self._wb.sheet_by_name(sheet_name)
            rows = []
            for row_idx in range(sheet.nrows):
                row = [str(sheet.cell_value(row_idx, col_idx)).strip() if sheet.cell_value(row_idx, col_idx) != '' else '' 
                       for col_idx in range(sheet.ncols)]
                rows.append(row)
            return rows
        else:
            ws = self._wb[sheet_name]
            rows = [[str(cell).strip() if cell is not None else '' for cell in row] for row in ws.iter_rows(values_only=True)]
            
            # read_only=True 模式下某些 Excel 文件只能读到1-2行（openpyxl已知bug）
            # 检测到行数异常少时，回退到 read_only=False 重新读取
            if self._read_only and len(rows) <= 2:
                try:
                    self._wb.close()
                except:
                    pass
                from openpyxl import load_workbook
                self._wb = load_workbook(self.file_path, data_only=True, read_only=False)
                self._read_only = False
                ws = self._wb[sheet_name]
                rows = [[str(cell).strip() if cell is not None else '' for cell in row] for row in ws.iter_rows(values_only=True)]
            
            return rows
    
    def get_headers_only(self, sheet_name=None):
        """轻量级方法：只读取表头行，不加载全部数据（避免 OOM）"""
        if self._is_html:
            return self._parse_html_headers_only()
        
        # 非 HTML 格式：打开后只读第一行
        if not self._wb:
            self.open()
        rows = self.get_sheet_data(sheet_name or (self.sheetnames[0] if self.sheetnames else None))
        return rows[0] if rows else []
    
    def _parse_html_headers_only(self):
        """只解析 HTML 表头，不加载整个文件到内存（流式读取前 N KB）"""
        try:
            # 只读取文件前 500KB 来提取表头和第一行数据
            # 增大到 500KB 以防 thead 超过 200KB（多语言/长列名场景）
            READ_SIZE = 500 * 1024
            with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                chunk = f.read(READ_SIZE)
            
            # 用正则提取 <th> 标签内容作为表头
            th_pattern = re.compile(r'<th[^>]*>(.*?)</th>', re.IGNORECASE | re.DOTALL)
            th_matches = th_pattern.findall(chunk)
            
            # 清理 HTML 标签和实体
            def clean_html_text(text):
                # 移除嵌套标签
                text = re.sub(r'<[^>]+>', '', text)
                # HTML 实体
                text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
                # 处理数字 HTML 实体
                text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))) if int(m.group(1)) < 65536 else '', text)
                text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)) if int(m.group(1), 16) < 65536 else '', text)
                return text.strip()
            
            all_headers = [clean_html_text(m) for m in th_matches if clean_html_text(m)]
            
            if not all_headers:
                # 尝试从第一个 <tr> 中的 <td> 提取
                tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.IGNORECASE | re.DOTALL)
                tr_matches = tr_pattern.findall(chunk)
                if tr_matches:
                    td_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL)
                    td_matches = td_pattern.findall(tr_matches[0])
                    all_headers = [clean_html_text(m) for m in td_matches if clean_html_text(m)]
            
            if not all_headers:
                all_headers = ['Project', 'Key', 'Summary', 'Issue Type', 'Status',
                              'Priority', 'Resolution', 'Assignee', 'Reporter', 'Creator',
                              'Created', 'Last Viewed', 'Updated', 'Resolved', 'Affects Version/s']
            
            # 提取第一行数据（thead 之后的第一个 tr 中的 td）
            first_data_row = []
            # 找到 </thead> 后的内容
            thead_end = chunk.lower().find('</thead>')
            if thead_end >= 0:
                after_thead = chunk[thead_end:]
                # 找第一个 <tr>...</tr>
                tr_match = re.search(r'<tr[^>]*>(.*?)</tr>', after_thead, re.IGNORECASE | re.DOTALL)
                if tr_match:
                    td_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL)
                    td_matches = td_pattern.findall(tr_match.group(1))
                    first_data_row = [clean_html_text(m) for m in td_matches]
            
            # 估算数据行数：统计文件中 <tr 标签出现次数（不加载整个文件）
            data_row_count = 0
            try:
                with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    # 分块统计 <tr 出现次数
                    for piece in iter(lambda: f.read(1024 * 1024), ''):
                        data_row_count += piece.count('<tr')
            except Exception:
                pass
            # 减去表头行
            data_row_count = max(0, data_row_count - 1)
            
            del chunk
            gc.collect()
            
            logger.info(f"HTML表头流式解析完成: {len(all_headers)}列, 约{data_row_count}行")
            
            # 返回表头 + 第一行数据 + 行数估算
            return all_headers, first_data_row, data_row_count
                
        except Exception as e:
            raise ValueError(f'解析 HTML 格式 Excel 文件失败: {str(e)}')
    
    def _parse_html_excel(self):
        """使用 lxml 高性能解析 HTML 格式 Excel 文件（替代逐行正则，速度提升 10-50 倍）"""
        try:
            from lxml import html as lxml_html
            import html as html_module

            # === 第一步：用 lxml 解析整个 HTML（C 级解析器，极快） ===
            with open(self.file_path, 'rb') as f:
                tree = lxml_html.fromstring(f.read())

            # 找到主 table（取第一个含 thead 或行数最多的 table）
            tables = tree.cssselect('table') if hasattr(tree, 'cssselect') else tree.xpath('//table')
            if not tables:
                # 没有 table，回退到正则方式
                return self._parse_html_excel_regex()

            table = tables[0]
            # 如果有多个 table，选行数最多的
            if len(tables) > 1:
                max_rows = 0
                for t in tables:
                    cnt = len(t.xpath('.//tr'))
                    if cnt > max_rows:
                        max_rows = cnt
                        table = t

            # === 第二步：提取表头 ===
            all_headers = []
            # 优先从 thead > tr > th 提取
            thead = table.find('thead')
            if thead is not None:
                for th in thead.iter('th'):
                    text = html_module.unescape(lxml_html.tostring(th, encoding='unicode', method='text').strip())
                    if text:
                        all_headers.append(text)
            # 回退：从第一行 td 提取
            if not all_headers:
                first_tr = table.find('.//tr')
                if first_tr is not None:
                    for td in first_tr.iter('td'):
                        text = html_module.unescape(lxml_html.tostring(td, encoding='unicode', method='text').strip())
                        if text:
                            all_headers.append(text)

            if not all_headers:
                all_headers = ['Project', 'Key', 'Summary', 'Issue Type', 'Status',
                              'Priority', 'Resolution', 'Assignee', 'Reporter', 'Creator',
                              'Created', 'Last Viewed', 'Updated', 'Resolved', 'Affects Version/s']

            # 扫描关键特殊列：Severity / Component / Fix Version
            thead_col_map = {}
            for idx, h in enumerate(all_headers):
                h_lower = h.lower()
                if 'severity' in h_lower and 'severity_col' not in thead_col_map:
                    thead_col_map['severity_col'] = idx
                if 'component' in h_lower and 'component_col' not in thead_col_map:
                    thead_col_map['component_col'] = idx
                if ('fix version' in h_lower or 'fixversion' in h_lower) and 'fix_version_col' not in thead_col_map:
                    thead_col_map['fix_version_col'] = idx

            # 只保留前15列 + 3个特殊列
            MAX_BASE_COLS = 15
            base_count = min(len(all_headers), MAX_BASE_COLS)
            keep_cols = list(range(base_count))
            extra_cols = []
            for col_key in ['severity_col', 'component_col', 'fix_version_col']:
                col_idx = thead_col_map.get(col_key)
                if col_idx is not None and col_idx not in keep_cols:
                    keep_cols.append(col_idx)
                    extra_cols.append((col_idx, col_key))

            full_headers = list(all_headers[:base_count])
            for col_idx, col_key in extra_cols:
                label = all_headers[col_idx] if col_idx < len(all_headers) else {
                    'severity_col': 'Severity', 'component_col': 'Component/s',
                    'fix_version_col': 'Fix Version/s'
                }.get(col_key, '')
                if label and label not in full_headers:
                    full_headers.append(label)

            keep_cols_sorted = sorted(keep_cols)
            _log_mem(f"HTML lxml解析：保留{len(keep_cols)}列，表头{len(full_headers)}个")

            # === 第三步：提取数据行（tbody 中的 tr > td） ===
            result_rows = [full_headers]
            row_count = 0

            # 获取 tbody，如果没有就用 table 本身
            tbody = table.find('tbody')
            tr_source = tbody if tbody is not None else table

            for tr in tr_source.iter('tr'):
                # 跳过表头行
                if tr.find('th') is not None:
                    continue

                tds = tr.findall('td')
                if not tds:
                    continue

                # 提取每个 td 的文本（text_content 是 C 级方法，极快）
                td_texts = [html_module.unescape(td.text_content().strip()) for td in tds]

                row = []
                for col_idx in keep_cols_sorted:
                    if col_idx < len(td_texts):
                        row.append(td_texts[col_idx])
                    else:
                        row.append('')

                if any(c.strip() for c in row):
                    result_rows.append(row)
                    row_count += 1

            del tree, table
            gc.collect()

            logger.info(f"HTML lxml解析完成：{row_count}行 x {len(full_headers)}列")
            _log_mem(f"HTML lxml解析完成：{row_count}行 x {len(full_headers)}列")
            return result_rows

        except Exception as e:
            error_msg = f'解析 HTML 格式 Excel 文件失败: {type(e).__name__}: {str(e)}'
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            # 回退到正则方式
            logger.warning("lxml 解析失败，回退到正则解析")
            return self._parse_html_excel_regex()

    def _parse_html_excel_regex(self):
        """正则方式解析 HTML 格式（回退方案）"""
        try:
            # HTML 实体和标签清理
            def clean_html_text(text):
                text = re.sub(r'<[^>]+>', '', text)
                text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
                text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))) if int(m.group(1)) < 65536 else '', text)
                text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)) if int(m.group(1), 16) < 65536 else '', text)
                return text.strip()

            READ_SIZE = 200 * 1024
            with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                head_chunk = f.read(READ_SIZE)

            th_pattern = re.compile(r'<th[^>]*>(.*?)</th>', re.IGNORECASE | re.DOTALL)
            th_matches = th_pattern.findall(head_chunk)
            all_headers = [clean_html_text(m) for m in th_matches if clean_html_text(m)]

            if not all_headers:
                tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.IGNORECASE | re.DOTALL)
                tr_match = tr_pattern.search(head_chunk)
                if tr_match:
                    td_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL)
                    td_matches = td_pattern.findall(tr_match.group(1))
                    all_headers = [clean_html_text(m) for m in td_matches if clean_html_text(m)]

            if not all_headers:
                all_headers = ['Project', 'Key', 'Summary', 'Issue Type', 'Status',
                              'Priority', 'Resolution', 'Assignee', 'Reporter', 'Creator',
                              'Created', 'Last Viewed', 'Updated', 'Resolved', 'Affects Version/s']

            thead_col_map = {}
            for idx, h in enumerate(all_headers):
                h_lower = h.lower()
                if 'severity' in h_lower and 'severity_col' not in thead_col_map:
                    thead_col_map['severity_col'] = idx
                if 'component' in h_lower and 'component_col' not in thead_col_map:
                    thead_col_map['component_col'] = idx
                if ('fix version' in h_lower or 'fixversion' in h_lower) and 'fix_version_col' not in thead_col_map:
                    thead_col_map['fix_version_col'] = idx

            MAX_BASE_COLS = 15
            base_count = min(len(all_headers), MAX_BASE_COLS)
            keep_cols = list(range(base_count))
            extra_cols = []
            for col_key in ['severity_col', 'component_col', 'fix_version_col']:
                col_idx = thead_col_map.get(col_key)
                if col_idx is not None and col_idx not in keep_cols:
                    keep_cols.append(col_idx)
                    extra_cols.append((col_idx, col_key))

            full_headers = list(all_headers[:base_count])
            for col_idx, col_key in extra_cols:
                label = all_headers[col_idx] if col_idx < len(all_headers) else {
                    'severity_col': 'Severity', 'component_col': 'Component/s',
                    'fix_version_col': 'Fix Version/s'
                }.get(col_key, '')
                if label and label not in full_headers:
                    full_headers.append(label)

            keep_cols_sorted = sorted(keep_cols)
            _log_mem(f"HTML正则解析：保留{len(keep_cols)}列，表头{len(full_headers)}个")

            result_rows = [full_headers]
            row_count = 0
            td_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL)

            thead_end_pos = head_chunk.lower().find('</thead>')
            skip_header = thead_end_pos >= 0
            table_start_pos = head_chunk.lower().find('<table')
            if not skip_header and table_start_pos >= 0:
                start_pos = table_start_pos
            elif skip_header:
                start_pos = thead_end_pos + 8
            else:
                start_pos = 0

            table_ended = False
            with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(start_pos)
                buffer = ''
                CHUNK_SIZE = 512 * 1024

                while True and not table_ended:
                    piece = f.read(CHUNK_SIZE)
                    if not piece:
                        break
                    buffer += piece

                    while True:
                        tr_start = buffer.find('<tr')
                        if tr_start == -1:
                            buffer = ''
                            break
                        tr_end = buffer.find('</tr>', tr_start)
                        if tr_end == -1:
                            buffer = buffer[tr_start:]
                            if len(buffer) > 1024 * 1024:
                                buffer = ''
                            break

                        tr_content = buffer[tr_start:tr_end + 5]
                        buffer = buffer[tr_end + 5:]

                        if '<th' in tr_content.lower():
                            next_tr = buffer.find('<tr')
                            between = buffer[:next_tr] if next_tr >= 0 else buffer
                            if '</table>' in between.lower():
                                table_ended = True
                                break
                            continue

                        td_matches = td_pattern.findall(tr_content)
                        if not td_matches:
                            continue

                        row = []
                        for col_idx in keep_cols_sorted:
                            if col_idx < len(td_matches):
                                row.append(clean_html_text(td_matches[col_idx]))
                            else:
                                row.append('')

                        if any(c.strip() for c in row):
                            result_rows.append(row)
                            row_count += 1

                        next_tr = buffer.find('<tr')
                        between = buffer[:next_tr] if next_tr >= 0 else buffer
                        if '</table>' in between.lower():
                            table_ended = True
                            break

                    del piece

            del buffer, head_chunk
            gc.collect()

            logger.info(f"HTML正则解析完成：{row_count}行 x {len(full_headers)}列, table_ended={table_ended}")
            _log_mem(f"HTML正则解析完成：{row_count}行 x {len(full_headers)}列")
            return result_rows

        except Exception as e:
            error_msg = f'解析 HTML 格式 Excel 文件失败: {type(e).__name__}: {str(e)}'
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            raise ValueError(error_msg)
    
    def get_sheet_names(self):
        """获取所有 sheet 名称"""
        return self.sheetnames


def read_excel_file(file_path, sheet_name=None):
    """读取 Excel 文件，返回 (sheet_names, sheet_data) 或 (sheet_names, None)"""
    reader = ExcelReader(file_path)
    reader.open()
    
    sheet_names = reader.get_sheet_names()
    sheet_data = None
    
    if sheet_name:
        sheet_data = reader.get_sheet_data(sheet_name)
    
    reader.close()
    return sheet_names, sheet_data

# === AI 配置管理 ===
def get_ai_config():
    config = {}
    try:
        if os.path.exists(app.config['AI_CONFIG_FILE']):
            with open(app.config['AI_CONFIG_FILE'], 'r', encoding='utf-8') as f:
                config = json.load(f)
    except Exception as e:
        logger.warning(f"加载 AI 配置失败: {e}")
    config['api_key'] = os.environ.get('AI_API_KEY', config.get('api_key', ''))
    config['base_url'] = os.environ.get('AI_BASE_URL', config.get('base_url', 'https://dashscope.aliyuncs.com/api/v1'))
    config['model'] = os.environ.get('AI_MODEL', config.get('model', 'qwen-turbo'))
    config['enabled'] = bool(config.get('api_key', '').strip())
    return config


@app.route('/api/ai-config', methods=['GET'])
def api_get_ai_config():
    config = get_ai_config()
    return jsonify({
        'status': 'success',
        'data': {
            'enabled': config['enabled'],
            'has_key': bool(config.get('api_key', '').strip()),
            'key_masked': config.get('api_key', '')[:4] + '****' if config.get('api_key') else '',
            'base_url': config.get('base_url', ''),
            'model': config.get('model', ''),
        }
    })


@app.route('/api/ai-config', methods=['POST'])
def api_save_ai_config():
    data = request.get_json()
    if not data:
        return jsonify({'error': '无效的配置数据'}), 400
    config = {}
    if os.path.exists(app.config['AI_CONFIG_FILE']):
        try:
            with open(app.config['AI_CONFIG_FILE'], 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception:
            pass
    if 'api_key' in data:
        config['api_key'] = data['api_key'].strip()
    if 'base_url' in data:
        config['base_url'] = data['base_url'].strip()
    if 'model' in data:
        config['model'] = data['model'].strip()
    try:
        with open(app.config['AI_CONFIG_FILE'], 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === 页面路由 ===
@app.route('/')
def index():
    return render_template('index.html')


# ==================== 认证路由 ====================

@app.route('/login')
def login_page():
    """登录页面"""
    error = request.args.get('error', '')
    return render_template('login.html',
                           error=error,
                           feishu_configured=auth.is_configured('feishu'),
                           google_configured=auth.is_configured('google'))


@app.route('/auth/feishu')
def auth_feishu():
    """发起飞书OAuth登录"""
    return auth.feishu_login()


@app.route('/auth/feishu/callback')
def auth_feishu_callback():
    """飞书OAuth回调"""
    return auth.feishu_callback()


@app.route('/auth/google')
def auth_google():
    """发起Google OAuth登录"""
    return auth.google_login()


@app.route('/auth/google/callback')
def auth_google_callback():
    """Google OAuth回调"""
    return auth.google_callback()


@app.route('/auth/logout')
def auth_logout():
    """退出登录"""
    return auth.logout()


@app.route('/api/user/info')
def api_user_info():
    """获取当前用户信息"""
    user = auth.get_current_user()
    if not user:
        return jsonify({'logged_in': False})
    return jsonify({
        'logged_in': True,
        'user': {
            'id': user['id'],
            'name': user['name'],
            'email': user['email'],
            'avatar': user['avatar'],
            'provider': user['provider']
        }
    })


@app.route('/api/user/save-report', methods=['POST'])
def api_user_save_report():
    """保存分析报告到用户账户"""
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json(silent=True) or {}
    report_data = data.get('report_data', {})
    title = data.get('title', f'分析报告_{datetime.now(_CST).strftime("%Y%m%d_%H%M%S")}')

    if not report_data:
        return jsonify({'error': '缺少报告数据'}), 400

    try:
        data_id = db.save_user_data(user['id'], 'test_report', title, report_data)
        return jsonify({'status': 'success', 'id': data_id, 'message': '报告已保存'})
    except Exception as e:
        logger.error(f"保存报告失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/reports')
def api_user_reports():
    """获取用户保存的报告列表"""
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    reports = db.get_user_data_list(user['id'], 'test_report', limit=50)
    # 简化返回，不包含完整content
    result = [{
        'id': r['id'],
        'title': r.get('title', ''),
        'created_at': r.get('created_at', 0)
    } for r in reports]
    return jsonify({'reports': result})


@app.route('/api/user/report/<int:report_id>')
def api_user_get_report(report_id):
    """获取用户保存的某份报告"""
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    report = db.get_user_data_by_id(user['id'], report_id)
    if not report:
        return jsonify({'error': '报告不存在'}), 404
    return jsonify({'report': report})


@app.route('/api/user/report/<int:report_id>', methods=['DELETE'])
def api_user_delete_report(report_id):
    """删除用户保存的报告"""
    user = auth.get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    success = db.delete_user_data(user['id'], report_id)
    if success:
        return jsonify({'status': 'success', 'message': '已删除'})
    return jsonify({'error': '删除失败'}), 404


@app.route('/test-report')
def test_report():
    return render_template('test_report.html')


@app.route('/excel-analysis')
def excel_analysis():
    return render_template('excel_analysis.html')


@app.route('/project-info')
def project_info():
    return render_template('project_info.html')


@app.route('/md2pdf')
def md2pdf():
    return render_template('md2pdf.html')


@app.route('/merit')
def merit():
    return render_template('merit.html')


@app.route('/plan-generator')
def plan_generator():
    return render_template('plan_generator.html')


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'pid': os.getpid()})


@app.route('/api/debug')
def api_debug():
    """诊断端点：返回部署版本、内存、任务状态等信息"""
    import psutil
    p = psutil.Process()
    mem_info = p.memory_info()

    # 统计上传目录中的文件
    upload_dir = app.config['UPLOAD_FOLDER']
    uploaded_files = []
    total_upload_size = 0
    if os.path.exists(upload_dir):
        for fname in os.listdir(upload_dir):
            fpath = os.path.join(upload_dir, fname)
            if os.path.isfile(fpath):
                fsize = os.path.getsize(fpath)
                uploaded_files.append({'name': fname, 'size_kb': round(fsize / 1024, 1)})
                total_upload_size += fsize
            elif os.path.isdir(fpath):
                # 子目录（如 _task_meta, _chunk_meta）
                file_count = len(os.listdir(fpath))
                uploaded_files.append({'name': f'{fname}/', 'files': file_count})

    # 后台任务状态
    active_tasks = {
        tid: {'status': t.get('status'), 'age_seconds': round(time.time() - t.get('created_at', time.time()), 0)}
        for tid, t in _background_tasks.items()
    }

    return jsonify({
        'status': 'ok',
        'pid': os.getpid(),
        'memory': {
            'rss_mb': round(mem_info.rss / 1024 / 1024, 1),
            'vms_mb': round(mem_info.vms / 1024 / 1024, 1),
        },
        'background_tasks': {
            'total': len(_background_tasks),
            'active': active_tasks,
        },
        'uploads': {
            'files': uploaded_files[:20],
            'total_size_mb': round(total_upload_size / 1024 / 1024, 2),
        },
        'config': {
            'upload_folder': upload_dir,
            'pdf_folder': app.config['PDF_FOLDER'],
            'is_cloud': bool(os.environ.get('RAILWAY_STATIC_URL') or os.environ.get('PORT')),
        }
    })

# === 测试报告分析 API ===
@app.route('/api/test-report-analyze', methods=['POST'])
def api_test_report_upload():
    """第一阶段：上传文件，返回Sheet列表和文件ID"""
    if 'file' not in request.files:
        return jsonify({'error': '请选择文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '请选择文件'}), 400

    filename_lower = file.filename.lower()
    if not (filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls')):
        return jsonify({'error': '只支持Excel文件(.xlsx, .xls)'}), 400

    orig_ext = os.path.splitext(file.filename)[1].lower()
    if orig_ext not in ('.xlsx', '.xls'):
        orig_ext = '.xlsx'

    try:
        file_id = hashlib.md5(f"{time.time()}_{file.filename}".encode()).hexdigest()[:16]
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"test_report_{file_id}{orig_ext}")
        file.save(file_path)

        logger.info(f"========== 收到测试报告: {file.filename}, ID: {file_id} ==========")

        reader = ExcelReader(file_path)
        reader.open()
        sheet_names = reader.get_sheet_names()
        reader.close()

        return jsonify({
            'status': 'success',
            'data': {
                'file_id': file_id,
                'file_name': file.filename,
                'file_basename': os.path.splitext(file.filename)[0],
                'sheet_names': sheet_names,
                'sheet_count': len(sheet_names)
            }
        })

    except Exception as e:
        logger.error(f"测试报告上传失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/test-report-analyze-sheet', methods=['POST'])
def api_test_report_analyze_sheet():
    """第二阶段：分析指定Sheet的详细内容"""
    data = request.json or {}
    file_id = data.get('file_id', '')
    sheet_name = data.get('sheet_name', '')

    if not file_id:
        return jsonify({'error': '缺少file_id'}), 400
    if not sheet_name:
        return jsonify({'error': '缺少sheet_name'}), 400

    file_path = None
    for ext in ['.xlsx', '.xls']:
        candidate = os.path.join(app.config['UPLOAD_FOLDER'], f"test_report_{file_id}{ext}")
        if os.path.exists(candidate):
            file_path = candidate
            break

    if not file_path:
        return jsonify({'error': '文件不存在，可能已过期'}), 404

    # 创建后台任务（避免同步分析超过 Railway 5 分钟 HTTP 超时）
    task_id = hashlib.md5(f"test_report_{file_id}_{sheet_name}_{time.time()}".encode()).hexdigest()[:16]
    task_data = {
        'status': 'processing',
        'result': None,
        'error': None,
        'created_at': time.time()
    }
    _background_tasks[task_id] = task_data
    _save_task_meta(task_id, task_data)

    def _do_test_report_analysis():
        try:
            logger.info(f"[分析任务 {task_id}] 开始分析: file={file_path}, sheet={sheet_name}")
            gc.collect()
            t0 = time.time()
            result = _analyze_sheet_detail(file_path, sheet_name)
            elapsed = time.time() - t0
            logger.info(f"[分析任务 {task_id}] 分析完成，耗时 {elapsed:.1f}s, 测试项数={len(result.get('test_items', []))}")
            _background_tasks[task_id]['result'] = result
            _background_tasks[task_id]['status'] = 'done'
            _save_task_meta(task_id, _background_tasks[task_id])
        except Exception as e:
            error_detail = str(e) if str(e) else f'{type(e).__name__} (无详细错误信息)'
            logger.error(f"[分析任务 {task_id}] 分析失败: {traceback.format_exc()}")
            _background_tasks[task_id]['error'] = error_detail
            _background_tasks[task_id]['status'] = 'error'
            _save_task_meta(task_id, _background_tasks[task_id])

    thread = threading.Thread(target=_do_test_report_analysis, daemon=True)
    thread.start()

    return jsonify({'status': 'success', 'data': {'task_id': task_id}})


@app.route('/api/test-report-debug', methods=['POST'])
def api_test_report_debug():
    """诊断端点：返回Excel解析的详细信息，帮助排查解析为空的问题"""
    data = request.json or {}
    file_id = data.get('file_id', '')
    sheet_name = data.get('sheet_name', '')

    if not file_id:
        return jsonify({'error': '缺少file_id'}), 400

    file_path = None
    for ext in ['.xlsx', '.xls']:
        candidate = os.path.join(app.config['UPLOAD_FOLDER'], f"test_report_{file_id}{ext}")
        if os.path.exists(candidate):
            file_path = candidate
            break

    if not file_path:
        return jsonify({'error': '文件不存在，可能已过期'}), 404

    try:
        if not sheet_name:
            reader = ExcelReader(file_path)
            reader.open()
            sheet_name = reader.sheetnames[0] if reader.sheetnames else 'Sheet1'
            reader.close()

        result = _analyze_sheet_detail(file_path, sheet_name, return_debug=True)
        return jsonify({'status': 'success', 'data': result})
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@app.route('/api/test-report-pdf', methods=['POST'])
def api_test_report_pdf():
    """将测试报告分析结果导出为PDF（含Motorola水印+日期）"""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': '请求数据格式错误'}), 400

    analysis_data = data.get('analysis_data', {})
    file_name = data.get('file_name', '')
    sheet_name = data.get('sheet_name', '')

    if not analysis_data:
        return jsonify({'error': '缺少分析数据'}), 400

    try:
        html_content = _build_test_report_pdf_html(analysis_data, file_name, sheet_name)

        import tempfile as tf
        with tf.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
            f.write(html_content)
            html_path = f.name

        safe_name = re.sub(r'[\\/:*?"<>|]', '_', file_name or 'test_report')
        pdf_filename = f"{safe_name}_{datetime.now(_CST).strftime('%Y%m%d_%H%M%S')}.pdf"
        download_name = f"{safe_name}.pdf"
        pdf_path = os.path.join(app.config['PDF_FOLDER'], pdf_filename)

        _render_pdf(html_path, pdf_path,
                    margin={'top': '15mm', 'bottom': '15mm', 'left': '12mm', 'right': '12mm'},
                    extra_wait_ms=1000)

        try:
            os.unlink(html_path)
        except Exception:
            pass

        return jsonify({
            'status': 'success',
            'filename': pdf_filename,
            'download_name': download_name
        })
    except Exception as e:
        logger.error(f"测试报告PDF生成失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/test-report-download/<filename>')
def api_test_report_download(filename):
    """下载生成的PDF文件"""
    safe_name = os.path.basename(filename)
    pdf_path = os.path.join(app.config['PDF_FOLDER'], safe_name)
    if not os.path.exists(pdf_path):
        return jsonify({'error': '文件不存在'}), 404
    download_name = request.args.get('download_name', safe_name)
    return send_file(pdf_path, as_attachment=True, download_name=download_name)


def _build_test_report_pdf_html(data, file_name, sheet_name):
    """构建测试报告PDF的HTML（含Motorola水印+日期）"""
    project_info = data.get('project_info', {})
    stats = data.get('stats', {})
    analysis = data.get('analysis', {})
    test_items = data.get('test_items', [])
    today = datetime.now(_CST).strftime('%Y-%m-%d')

    # 水印文字
    watermark_text = f"Motorola {today}"

    # 水印HTML（平铺）
    watermark_items = []
    for x in range(0, 800, 200):
        for y in range(0, 1200, 150):
            watermark_items.append(
                f'<div style="position:absolute;left:{x}px;top:{y}px;transform:rotate(-30deg);'
                f'font-size:18px;font-weight:600;color:rgba(0,113,227,0.08);white-space:nowrap;'
                f'pointer-events:none;z-index:0;">{watermark_text}</div>'
            )
    watermark_html = '\n'.join(watermark_items)

    # 项目信息
    info_rows = ''
    for k, v in project_info.items():
        if v and str(v).strip():
            info_rows += f'<div class="info-row"><span class="info-label">{k}</span><span class="info-val">{v}</span></div>'
    if not info_rows:
        info_rows = '<div class="info-row"><span class="info-val" style="color:#999;">无项目信息</span></div>'

    # 统计数据
    total = stats.get('total', 0)
    pass_count = stats.get('pass', 0)
    fail_count = stats.get('fail', 0)
    blocked_count = stats.get('blocked', 0)
    delayed_count = stats.get('delayed', 0)
    pass_rate = stats.get('pass_rate', '0%')
    overall_risk = analysis.get('overall_risk', '未知')

    risk_color = {'高': '#dc2626', '中': '#f59e0b', '低': '#3b82f6', '无': '#10b981'}.get(overall_risk, '#6b7280')

    # 关键发现
    key_findings = analysis.get('key_findings', [])
    findings_html = ''
    if key_findings:
        for f in key_findings:
            findings_html += f'<div class="finding-item">• {f}</div>'
    else:
        findings_html = '<div style="color:#999;">无关键发现</div>'

    # 改进建议
    recommendations = analysis.get('recommendations', [])
    recs_html = ''
    if recommendations:
        for r in recommendations:
            recs_html += f'<div class="rec-item">• {r}</div>'
    else:
        recs_html = '<div style="color:#999;">无改进建议</div>'

    # 分类分析
    sections = analysis.get('sections', [])
    sections_html = ''
    for s in sections:
        risk_cls = {'高': 'high', '中': 'medium', '低': 'low', '无': 'none'}.get(s.get('risk_level', ''), 'none')
        sections_html += f'''
        <div class="section-block">
            <div class="section-header">
                <span class="risk-badge-pdf {risk_cls}">{s.get('risk_level', '')}</span>
                <span class="section-cat">{s.get('category', '')}</span>
                <span class="section-stats">通过率 {s.get('pass_rate', '')} · 共 {s.get('total', 0)} 项</span>
            </div>
            <div class="section-summary">{s.get('summary', '')}</div>
        </div>'''

    # 测试项表格
    result_labels = {'pass': '通过', 'fail': '不通过', 'blocked': '阻塞', 'delayed': '已延期', 'n_a': '不适用', 'unknown': '未识别'}
    rows_html = ''
    for item in test_items:
        result_text = result_labels.get(item.get('result', ''), item.get('result_text', ''))
        result_cls = item.get('result', 'unknown')
        target = item.get('target', '')
        actual = item.get('actual', '')
        reason = item.get('reason', '')
        rows_html += f'''<tr>
            <td>{item.get('name', '')}</td>
            <td>{item.get('module', '') or '-'}</td>
            <td><span class="pdf-badge {result_cls}">{result_text}</span></td>
            <td>{target or '-'}</td>
            <td>{actual or '-'}</td>
            <td>{reason or '-'}</td>
        </tr>'''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
@page {{ size: A4; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
    color: #1a1a2e;
    font-size: 12px;
    position: relative;
}}
.watermark-layer {{
    position: fixed;
    top: 0; left: 0; width: 100%; height: 100%;
    z-index: 0; pointer-events: none;
}}
.content {{ position: relative; z-index: 1; }}

/* Header */
.report-header {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 24px 30px;
    border-radius: 12px;
    margin-bottom: 20px;
}}
.report-header h1 {{ font-size: 22px; margin-bottom: 6px; }}
.report-header .meta {{ font-size: 13px; opacity: 0.9; }}

/* Section */
.section {{ margin-bottom: 18px; }}
.section-title {{
    font-size: 15px; font-weight: 700; margin-bottom: 10px;
    padding-left: 10px; border-left: 4px solid #4f46e5;
    color: #1a1a2e;
}}

/* Info grid */
.info-grid {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.info-row {{
    background: #f9fafb; border-radius: 6px; padding: 8px 14px;
    border-left: 3px solid #4f46e5; min-width: 200px;
}}
.info-label {{ font-size: 11px; color: #6b7280; display: block; }}
.info-val {{ font-size: 13px; font-weight: 600; }}

/* Stats grid */
.stats-grid {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.stat-box {{
    background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 12px 16px; text-align: center; min-width: 80px;
}}
.stat-box .num {{ font-size: 22px; font-weight: 800; }}
.stat-box .lbl {{ font-size: 11px; color: #6b7280; margin-top: 4px; }}

/* Risk banner */
.risk-banner {{
    display: inline-block; padding: 6px 16px; border-radius: 20px;
    font-size: 13px; font-weight: 700; margin-bottom: 10px;
    background: {risk_color}22; color: {risk_color}; border: 1px solid {risk_color};
}}

/* Executive summary */
.exec-summary {{
    background: linear-gradient(135deg, #f0f4ff 0%, #e0e7ff 100%);
    border-radius: 8px; padding: 14px 18px; line-height: 1.7;
    border: 1px solid #c7d2fe; font-size: 12px;
}}

/* Findings & recommendations */
.finding-item, .rec-item {{
    padding: 6px 0; line-height: 1.6; border-bottom: 1px solid #f3f4f6;
}}
.finding-item:last-child, .rec-item:last-child {{ border-bottom: none; }}

/* Analysis sections */
.section-block {{
    border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; margin-bottom: 8px;
}}
.section-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
.section-cat {{ font-weight: 600; font-size: 13px; }}
.section-stats {{ font-size: 11px; color: #6b7280; margin-left: auto; }}
.section-summary {{ font-size: 11px; color: #4b5563; line-height: 1.5; }}
.risk-badge-pdf {{
    padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 700;
}}
.risk-badge-pdf.high {{ background: #fee2e2; color: #991b1b; }}
.risk-badge-pdf.medium {{ background: #fef3c7; color: #92400e; }}
.risk-badge-pdf.low {{ background: #dbeafe; color: #1e40af; }}
.risk-badge-pdf.none {{ background: #d1fae5; color: #065f46; }}

/* Table */
table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
th {{
    background: #f9fafb; padding: 8px; text-align: left; font-weight: 600;
    border-bottom: 2px solid #e5e7eb; color: #6b7280; font-size: 10px;
}}
td {{
    padding: 6px 8px; border-bottom: 1px solid #f3f4f6; vertical-align: top;
    word-break: break-word;
}}
tr:nth-child(even) {{ background: #fafbfc; }}
.pdf-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 10px; font-weight: 600; white-space: nowrap;
}}
.pdf-badge.pass {{ background: #d1fae5; color: #065f46; }}
.pdf-badge.fail {{ background: #fee2e2; color: #991b1b; }}
.pdf-badge.blocked {{ background: #fef3c7; color: #92400e; }}
.pdf-badge.delayed {{ background: #ffedd5; color: #9a3412; }}
.pdf-badge.n_a {{ background: #f3f4f6; color: #6b7280; }}
.pdf-badge.unknown {{ background: #f3f4f6; color: #4b5563; }}

/* Footer */
.report-footer {{
    margin-top: 20px; padding-top: 12px; border-top: 1px solid #e5e7eb;
    text-align: center; font-size: 10px; color: #9ca3af;
}}
</style>
</head>
<body>
<div class="watermark-layer">{watermark_html}</div>
<div class="content">

<div class="report-header">
    <h1>📋 测试报告分析</h1>
    <div class="meta">
        文件: {file_name or '未命名'} | Sheet: {sheet_name or '未指定'} | 生成日期: {today}
    </div>
</div>

<div class="section">
    <div class="section-title">项目信息</div>
    <div class="info-grid">{info_rows}</div>
</div>

<div class="section">
    <div class="section-title">测试统计</div>
    <div class="stats-grid">
        <div class="stat-box"><div class="num" style="color:#1a1a2e;">{total}</div><div class="lbl">总数</div></div>
        <div class="stat-box"><div class="num" style="color:#10b981;">{pass_count}</div><div class="lbl">通过</div></div>
        <div class="stat-box"><div class="num" style="color:#ef4444;">{fail_count}</div><div class="lbl">不通过</div></div>
        <div class="stat-box"><div class="num" style="color:#f59e0b;">{delayed_count}</div><div class="lbl">已延期</div></div>
        <div class="stat-box"><div class="num" style="color:#92400e;">{blocked_count}</div><div class="lbl">阻塞</div></div>
        <div class="stat-box"><div class="num" style="color:#4f46e5;">{pass_rate}</div><div class="lbl">通过率</div></div>
    </div>
</div>

<div class="section">
    <div class="section-title">执行摘要</div>
    <div class="risk-banner">整体风险等级: {overall_risk}</div>
    <div class="exec-summary">{analysis.get('executive_summary', '无摘要信息')}</div>
</div>

<div class="section">
    <div class="section-title">分类分析</div>
    {sections_html if sections_html else '<div style="color:#999;">无分类分析数据</div>'}
</div>

<div class="section">
    <div class="section-title">关键发现</div>
    {findings_html}
</div>

<div class="section">
    <div class="section-title">改进建议</div>
    {recs_html}
</div>

<div class="section">
    <div class="section-title">逐项明细</div>
    <table>
        <thead><tr>
            <th>测试项</th><th>模块</th><th>结果</th><th>目标</th><th>实测</th><th>待办事项</th>
        </tr></thead>
        <tbody>{rows_html if rows_html else '<tr><td colspan="6" style="text-align:center;color:#999;">无测试项数据</td></tr>'}</tbody>
    </table>
</div>

<div class="report-footer">
    本报告由测试报告分析工具自动生成 | Motorola Confidential | {today}
</div>

</div>
</body>
</html>'''

    return html


def _analyze_sheet_detail(file_path, sheet_name, return_debug=False):
    """分析单个Sheet的详细内容"""
    reader = ExcelReader(file_path)
    reader.open()
    rows = reader.get_sheet_data(sheet_name)
    reader.close()
    debug_info = {'sheet_name': sheet_name, 'total_rows': len(rows), 'first_10_rows': [], 'detected_headers': [], 'info_end_row': 0, 'data_rows_count': 0}

    if not rows:
        if return_debug:
            return {
                'file_basename': os.path.basename(file_path),
                'sheet_name': sheet_name,
                'project_info': {},
                'test_items': [],
                'stats': {'total': 0, 'pass': 0, 'fail': 0, 'pass_rate': '0%'},
                'analysis': {'executive_summary': '未找到测试项数据，请检查Excel文件格式是否正确。', 'overall_risk': '未知', 'key_findings': [], 'recommendations': [], 'sections': []},
                '_debug': debug_info
            }
        return {
            'file_basename': os.path.basename(file_path),
            'sheet_name': sheet_name,
            'project_info': {},
            'test_items': [],
            'stats': {'total': 0, 'pass': 0, 'fail': 0, 'pass_rate': '0%'}
        }

    # 记录前10行用于调试
    for r in rows[:10]:
        cells_preview = [str(c).strip() if c is not None else '' for c in r]
        non_empty_count = sum(1 for c in cells_preview if c)
        debug_info['first_10_rows'].append({'row': cells_preview[:8], 'non_empty': non_empty_count})

    # 1. 识别KV信息区
    project_info = {}
    info_end_row = 0
    result_keywords = ['pass', 'fail', '通过', '不通过', 'blocker', 'critical', 'major', 'minor', 'trivial']
    header_keywords = ['test item', 'test case', '测试项', '模块', 'module', 'component', 'commponent', 'severity', '结果', 'result', 'status', '状态', 'name', '名称', 'category', '分类', 'risk', '风险', 'cwv', 'target', '目标', 'key issue', 'comment', '备注', '指标', '测试内容']

    for row_idx, row in enumerate(rows):
        cells = [str(c).strip() if c is not None else '' for c in row]
        non_empty = [c for c in cells if c]

        if not non_empty:
            info_end_row = row_idx + 1
            continue

        # 检查是否是表头行（至少匹配2个不同的表头关键词，避免KV行被误判）
        row_text = ' '.join(cells).lower()
        matched_kws = set()
        for kw in header_keywords:
            if kw in row_text:
                matched_kws.add(kw)
        is_header_row = len(non_empty) >= 3 and len(matched_kws) >= 2
        
        if is_header_row:
            info_end_row = row_idx
            break

        is_kv_row = False
        kv_pairs = []

        for cell_idx, cell_val in enumerate(cells):
            if not cell_val:
                continue

            if ':' in cell_val or '：' in cell_val:
                parts = cell_val.replace('：', ':').split(':', 1)
                label = parts[0].strip()
                value = parts[1].strip()
                if label and value and not any(kw in value.lower() for kw in result_keywords):
                    kv_pairs.append({'label': label, 'value': value})
                    is_kv_row = True

            elif cell_idx + 1 < len(cells) and cells[cell_idx + 1]:
                right_val = cells[cell_idx + 1].strip()
                if (len(cell_val) <= 20 and
                    not any(kw in cell_val.lower() for kw in result_keywords) and
                    not any(kw in right_val.lower() for kw in result_keywords)):
                    kv_pairs.append({'label': cell_val, 'value': right_val})
                    is_kv_row = True
                    break

        if is_kv_row and kv_pairs:
            for pair in kv_pairs:
                project_info[pair['label']] = pair['value']
            info_end_row = row_idx + 1
        elif non_empty and not is_kv_row:
            if len(non_empty) >= 2:
                break
            info_end_row = row_idx + 1

    # 2. 识别表格区域
    test_items = []
    headers = []
    data_rows = []
    table_header_keywords = ['结果', 'result', 'pass', 'fail', '通过', '不通过', '测试项', '测试内容', '测试用例', 'test item', 'test case', 'module', '模块', '组件', 'severity', '严重程度', '严重性', '等级', 'status', '状态', 'name', '名称', '指标', 'remark', '备注', '说明', '原因', 'reason', '目标', 'target', '实测', 'actual', '问题', 'issue', 'category', '分类', '类型']

    for row_idx in range(info_end_row, len(rows)):
        row = rows[row_idx]
        cells = [str(c).strip() if c is not None else '' for c in row]
        non_empty = [c for c in cells if c]

        if not non_empty:
            if headers:
                break
            continue

        if not headers and len(non_empty) >= 2:
            row_text = ' '.join(cells).lower()
            matched_kws = set()
            for kw in table_header_keywords:
                if kw in row_text:
                    matched_kws.add(kw)
            # 宽松匹配：2个非空+1个关键词，或3个非空+2个关键词
            if (len(non_empty) >= 3 and len(matched_kws) >= 2) or (len(non_empty) >= 2 and len(matched_kws) >= 1):
                headers = cells
                continue

        if headers and len(non_empty) >= 1:
            data_rows.append({'cells': cells, 'row_idx': row_idx})

    # 回退：如果严格匹配没找到表头，尝试找第一个含"结果"或"result"的行
    if not headers:
        for row_idx in range(info_end_row, len(rows)):
            row = rows[row_idx]
            cells = [str(c).strip() if c is not None else '' for c in row]
            non_empty = [c for c in cells if c]
            if not non_empty:
                continue
            row_text = ' '.join(cells).lower()
            if '结果' in row_text or 'result' in row_text or 'pass' in row_text or 'pass/fail' in row_text or '状态' in row_text or 'status' in row_text:
                headers = cells
                # 收集后续数据行
                for dr_idx in range(row_idx + 1, len(rows)):
                    dr = rows[dr_idx]
                    dr_cells = [str(c).strip() if c is not None else '' for c in dr]
                    dr_non_empty = [c for c in dr_cells if c]
                    if not dr_non_empty:
                        break
                    data_rows.append({'cells': dr_cells, 'row_idx': dr_idx})
                break

    # 最终回退：如果仍没找到表头，把所有非空行当数据，用第一行做表头
    if not headers and len(rows) > info_end_row:
        for row_idx in range(info_end_row, len(rows)):
            row = rows[row_idx]
            cells = [str(c).strip() if c is not None else '' for c in row]
            non_empty = [c for c in cells if c]
            if len(non_empty) >= 2:
                headers = cells
                for dr_idx in range(row_idx + 1, len(rows)):
                    dr = rows[dr_idx]
                    dr_cells = [str(c).strip() if c is not None else '' for c in dr]
                    dr_non_empty = [c for c in dr_cells if c]
                    if dr_non_empty:
                        data_rows.append({'cells': dr_cells, 'row_idx': dr_idx})
                break

    # 3. 检测列索引
    col_indices = _detect_column_indices(headers)

    # 记录调试信息
    debug_info['detected_headers'] = headers
    debug_info['info_end_row'] = info_end_row
    debug_info['data_rows_count'] = len(data_rows)
    debug_info['col_indices'] = col_indices

    # 4. 解析测试项
    for data_row in data_rows:
        cells = data_row['cells']
        row_idx = data_row['row_idx']

        name = _get_cell_value(cells, col_indices.get('name', -1))
        module = _get_cell_value(cells, col_indices.get('module', -1))
        severity = _get_cell_value(cells, col_indices.get('severity', -1))
        result_raw = _get_cell_value(cells, col_indices.get('result', -1))
        reason = _get_cell_value(cells, col_indices.get('reason', -1))
        key_issue = _get_cell_value(cells, col_indices.get('key_issue', -1)) if 'key_issue' in col_indices else ''
        comment = _get_cell_value(cells, col_indices.get('comment', -1)) if 'comment' in col_indices else ''

        # 尝试提取目标值和实测值
        target_val = _get_cell_value(cells, col_indices.get('target', -1)) if 'target' in col_indices else ''
        actual_val = _get_cell_value(cells, col_indices.get('actual', -1)) if 'actual' in col_indices else ''

        # 跳过没有名称的行（空行、子标题行）
        if not name or not name.strip():
            continue

        # 跳过明显不是测试项的行（纯数字、纯符号、太短）
        name_stripped = name.strip()
        if len(name_stripped) < 2 or name_stripped in ['-', '/', 'N/A', 'NA']:
            continue

        # 智能判断结果状态
        # 优先级1: 直接从 result 列文本判断
        result_text = result_raw.strip() if result_raw else ''
        result_class = _classify_result(result_text)

        # 优先级2: 如果 result 列无法识别，尝试用 CWV/actual 和 target 比较
        if result_class == 'unknown' and actual_val and target_val:
            result_class, result_text = _compare_target_actual(target_val, actual_val)

        # 优先级3: 如果 result 列和 actual 列都无法识别，检查 actual_val 是否是 Pass/Fail 文本
        if result_class == 'unknown' and actual_val:
            actual_class = _classify_result(actual_val.strip())
            if actual_class != 'unknown':
                result_class = actual_class
                result_text = actual_val.strip()

        # 如果 actual_val 为空但 result_raw 有值，用 result_raw 作为 actual
        if not actual_val and result_raw:
            actual_val = result_raw

        # 合并 key_issue + comment + reason 为完整备注
        raw_notes_parts = []
        if key_issue and key_issue.strip():
            raw_notes_parts.append(key_issue.strip())
        if comment and comment.strip():
            raw_notes_parts.append(comment.strip())
        if reason and reason.strip():
            raw_notes_parts.append(reason.strip())
        raw_notes = '\n'.join(raw_notes_parts)

        # 从备注中提取待办事项
        action_items = _extract_action_items(raw_notes)
        # 只保留待办事项，不显示原始备注
        if action_items:
            notes_display = '\n'.join(action_items)
        else:
            notes_display = ''

        test_item = {
            'name': name or f'测试项{row_idx + 1}',
            'module': module,
            'severity': severity,
            'result': result_class,
            'result_text': result_text if result_text else result_class,
            'reason': notes_display,
            'action_items': action_items,
            'target': target_val,
            'actual': actual_val,
            'row_index': row_idx + 1
        }
        test_items.append(test_item)

    # 5. 统计
    total = len(test_items)
    pass_count = sum(1 for item in test_items if item['result'] == 'pass')
    fail_count = sum(1 for item in test_items if item['result'] == 'fail')
    blocked_count = sum(1 for item in test_items if item['result'] == 'blocked')
    delayed_count = sum(1 for item in test_items if item['result'] == 'delayed')
    na_count = sum(1 for item in test_items if item['result'] == 'n_a')
    unknown_count = sum(1 for item in test_items if item['result'] == 'unknown')

    # 已执行项 = 总数 - 延期 - 阻塞 - N/A - 未知
    executed_count = total - delayed_count - blocked_count - na_count - unknown_count
    pass_rate = f"{(pass_count / total * 100):.1f}%" if total > 0 else "0%"
    executed_pass_rate = f"{(pass_count / executed_count * 100):.1f}%" if executed_count > 0 else "0%"

    severity_stats = {}
    for item in test_items:
        sev = item.get('severity', '').strip()
        if sev:
            sev_lower = sev.lower()
            for level in ['blocker', 'critical', 'major', 'minor', 'trivial']:
                if level in sev_lower:
                    severity_stats[level] = severity_stats.get(level, 0) + 1
                    break

    # 6. 生成智能分析报告
    analysis = _generate_intelligent_analysis(test_items, project_info, {
        'total': total,
        'pass': pass_count,
        'fail': fail_count,
        'blocked': blocked_count,
        'delayed': delayed_count,
        'n_a': na_count,
        'unknown': unknown_count,
        'executed': executed_count,
        'pass_rate': pass_rate,
        'executed_pass_rate': executed_pass_rate
    })

    result = {
        'file_basename': os.path.splitext(os.path.basename(file_path))[0],
        'sheet_name': sheet_name,
        'project_info': project_info,
        'test_items': test_items,
        'stats': {
            'total': total,
            'pass': pass_count,
            'fail': fail_count,
            'blocked': blocked_count,
            'delayed': delayed_count,
            'n_a': na_count,
            'unknown': unknown_count,
            'executed': executed_count,
            'pass_rate': pass_rate,
            'executed_pass_rate': executed_pass_rate,
            'severity': severity_stats
        },
        'analysis': analysis
    }
    if return_debug:
        result['_debug'] = debug_info
    return result


def _detect_column_indices(headers):
    col_map = {}
    if not headers:
        return col_map
    # 清理表头：去掉换行符、@符号后面的内容、多余空格
    def clean_header(h):
        h = str(h).replace('\n', ' ').replace('\r', ' ')
        # 去掉 @xxx 部分
        if '@' in h:
            h = h.split('@')[0].strip()
        return h.lower().strip()
    headers_lower = [clean_header(h) for h in headers]

    for i, h in enumerate(headers_lower):
        if any(kw in h for kw in ['测试项', '测试内容', '测试用例', '名称', 'name', 'test item', 'test case', 'case', '指标', '项目', '检查项', 'test items']):
            col_map['name'] = i
        elif any(kw in h for kw in ['模块', 'module', 'component', 'commponent', '组件', '功能', '分类', 'category', '类型', '领域', '专项']):
            col_map['module'] = i
        elif any(kw in h for kw in ['severity', '严重程度', '严重性', '等级', 'level', '优先级', 'priority']):
            col_map['severity'] = i
        elif any(kw in h for kw in ['结果', 'result', 'pass/fail', '通过', '状态', 'status', '结论', '判定']):
            col_map['result'] = i
        elif any(kw in h for kw in ['key issue', '核心问题', '关键问题', '主要问题']):
            col_map['key_issue'] = i
        elif any(kw in h for kw in ['comment', '备注', 'remark', 'note', '说明', 'comment.', 'comments']):
            col_map['comment'] = i
        elif any(kw in h for kw in ['原因', 'reason', '描述', '问题', 'issue', '问题描述', '问题描述']):
            col_map['reason'] = i
        elif any(kw in h for kw in ['目标', 'target', '要求', '门槛', '标准值', 'sr6 target', 'sr5 target', 'sr4 target', 'sr target', '基线', 'baseline', '阈值', 'threshold']):
            col_map['target'] = i
        elif any(kw in h for kw in ['实测', '实际', 'actual', '当前', 'current', '结果值', '测量', 'measured', 'cwv']):
            col_map['actual'] = i
        elif any(kw in h for kw in ['风险', 'risk']):
            col_map['risk'] = i

    # 如果没有找到 result 列，但有 actual(CWV) 列，用 actual 作为 result
    # (CWV 值可能是 Pass/Fail 文本或数值，后续通过 _compare_target_actual 判断)
    if 'result' not in col_map and 'actual' in col_map:
        col_map['result'] = col_map['actual']

    if 'result' not in col_map:
        for i, h in enumerate(headers_lower):
            if any(kw in h for kw in ['pass', 'fail', '通过', '不通过', '结论', '判定']):
                col_map['result'] = i
                break

    if 'name' not in col_map:
        col_map['name'] = 0

    if 'reason' not in col_map and len(headers) > 0:
        col_map['reason'] = len(headers) - 1

    # 优先使用 SR6 Target 作为目标值（覆盖通用 target 列）
    # 当存在多个 Target 列（SR4/SR5/SR6）时，优先取 SR6 Target
    for i, h in enumerate(headers_lower):
        if 'sr6' in h and ('target' in h or '目标' in h):
            col_map['target'] = i
            break

    return col_map


def _get_cell_value(cells, idx):
    if idx < 0 or idx >= len(cells):
        return ''
    return str(cells[idx]).strip() if cells[idx] else ''


def _extract_action_items(text):
    """
    从 Key issue / Comment 文本中提取待办事项。
    识别模式：
    - 显式标记: TODO, 待办, 待跟进, action, 行动项, 下一步, follow up
    - 动作引导词: 需要, 需, 应, 应当, 建议, 请, 要求, 必须, 需跟进, 待修复, 待验证
    - 序号列表: 1. 2. 3. 或 ① ② ③ 或 - / * 开头
    - 时态标记: 将, 计划, 拟, 预计
    - 状态标记: 未关闭, 未解决, open, pending, in progress, 进行中
    """
    if not text or not text.strip():
        return []

    import re
    lines = text.replace('\r', '\n').split('\n')
    action_items = []

    # 待办关键词（行首或独立出现）
    action_keywords = [
        'todo', '待办', '待跟进', '待修复', '待验证', '待确认', '待补齐',
        'action', '行动项', '行动', 'follow up', 'follow-up', 'followup',
        '下一步', '后续', '计划', '拟', '预计', '将跟进', '将修复',
        '需要', '需跟进', '需修复', '需验证', '需确认', '需推进',
        '建议', '应', '应当', '应该', '必须', '请',
        '未关闭', '未解决', '未完成', '未达标',
        'open', 'pending', 'in progress', '进行中', '处理中',
        '跟进', '推进', '修复', '验证', '确认', '闭环', '整改',
        '负责', 'owner', 'assign',
    ]

    # 排除词（避免误判）
    exclude_keywords = ['已通过', '已关闭', '已解决', '已完成', 'pass', 'passed', 'done', 'closed', 'resolved']

    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        line_lower = line.lower()

        # 跳过纯排除词行
        if any(line_lower == kw for kw in exclude_keywords):
            continue

        is_action = False

        # 检测序号开头: 1. / 1) / ① / - / * / •
        if re.match(r'^(\d+[.)\]]|[\u2460-\u2473]|[—\-*/•·])\s+', line):
            is_action = True

        # 检测待办关键词
        for kw in action_keywords:
            if kw in line_lower:
                # 排除"已通过"等已完成的描述
                if not any(ex in line_lower for ex in exclude_keywords):
                    is_action = True
                    break

        # 检测"XX:XXX"格式中的动作描述 (如 "责任人:张三 待修复")
        if re.search(r'[:：].*(?:待|需|应|建议|跟进|修复|验证)', line):
            is_action = True

        if is_action:
            # 清理前缀符号
            cleaned = re.sub(r'^(\d+[.)\]]|[\u2460-\u2473]|[—\-*/•·])\s*', '', line)
            cleaned = re.sub(r'^(todo|action|待办|行动项|下一步|follow\s*up)[:：\s]*', '', cleaned, flags=re.IGNORECASE)
            if cleaned and len(cleaned) >= 3:
                # 去重
                if cleaned not in action_items:
                    action_items.append(cleaned)

    return action_items


def _compare_target_actual(target_val, actual_val):
    """
    比较目标值和实测值，返回结果类别和文本描述。
    支持：百分比(1/0.95/95%/100%)、数值、天数等
    """
    def parse_number(val):
        """尝试解析为浮点数，正确处理百分比"""
        if not val:
            return None
        s = str(val).strip()
        has_percent = '%' in s
        # 去掉前缀符号和单位
        s = s.replace('%', '').replace('days', '').replace('day', '').replace('天', '')
        s = re.sub(r'[>=≤<≥~≈约]', '', s).replace('H', '').replace('h', '').replace('fps', '').strip()
        # 去掉括号及后面的内容
        s = re.sub(r'[（(].*$', '', s).strip()
        try:
            num = float(s)
            # 百分比形式：90% -> 0.90, 95% -> 0.95
            if has_percent and num > 1:
                num = num / 100.0
            return num
        except:
            return None

    target_num = parse_number(target_val)
    actual_num = parse_number(actual_val)

    if target_num is None or actual_num is None:
        return 'unknown', ''

    # 判断通过/不通过
    if actual_num >= target_num:
        return 'pass', f'达标 ({actual_val} >= {target_val})'
    else:
        return 'fail', f'未达标 ({actual_val} < {target_val})'


def _classify_result(text):
    """
    全面分类测试结果状态，返回标准化的状态类别。
    类别: pass / fail / blocked / delayed / n_a / unknown
    - pass:     通过、合格、达标
    - fail:     不通过、失败、不达标、未达标、NG
    - blocked:  阻塞、未执行、跳过、skip
    - delayed:  已延期、延期、推迟
    - n_a:      不适用、N/A
    - unknown:  无法识别
    """
    if not text:
        return 'unknown'

    t = text.strip().lower()

    # N/A 类
    na_words = ['n/a', 'na', '不适用', '无', 'none', 'null', '-']
    if t in na_words:
        return 'n_a'

    # 否定形式优先判断（"不通过"含"通过"，"未达标"含"达标"，须在 pass 之前判断）
    negative_fail_kws = ['不通过', '未通过', '不达标', '未达标', '不合格', '未合格',
                         '不满足', '未满足', '失败', 'fail', 'failed', 'failure',
                         'ng', 'error', 'reject', 'rejected', 'crash',
                         'abort', 'timeout', '超时', '异常', '拒绝']
    for kw in negative_fail_kws:
        if kw in t:
            return 'fail'

    # 延期类
    delayed_words = ['已延期', '延期', '推迟', 'delayed', 'postponed', 'deferred',
                     'pending', '待定', '未开始', 'not started', '暂缓']
    for kw in delayed_words:
        if kw in t:
            return 'delayed'

    # 阻塞类
    blocked_words = ['block', 'blocked', '阻塞', '阻塞中', 'skip', 'skipped',
                     '跳过', '未执行', 'not executed', 'not run', 'wip',
                     '进行中', 'in progress', 'in_progress']
    for kw in blocked_words:
        if kw in t:
            return 'blocked'

    # 通过类
    pass_words = ['pass', 'passed', '通过', '合格', '达标', 'yes', 'y', 'ok',
                  'success', '√', '✓', 'p', 'done', 'complete', 'completed',
                  'closed', 'resolved', '完成', '已关闭', '已解决']
    if t in pass_words or t.startswith('pass') or '通过' in t or '合格' in t or '达标' in t:
        return 'pass'

    # 失败类（精确匹配兜底）
    fail_exact = ['no', 'n', '×', '✗', 'f', 'bug']
    if t in fail_exact:
        return 'fail'

    return 'unknown'


def _is_pass_result(text):
    return _classify_result(text) == 'pass'


def _is_fail_result(text):
    cls = _classify_result(text)
    return cls in ('fail', 'blocked', 'delayed')


# === 智能分析引擎 ===

# 测试项分类关键词映射
_CATEGORY_KEYWORDS = {
    '功能测试': ['functional', '功能', 'cuj', 'oobe', 'ota', 'requirement', '需求', '用例', 'case', 'p0'],
    '性能专项': ['ttid', 'ttfd', 'fps', 'latency', '延迟', '响应', 'performance', '性能', '帧率',
                 '启动', 'launch', 'scroll', '滚动', 'time to', '功耗'],
    '续航DOU': ['dou', '续航', 'battery', '电池', '功耗', 'power', '耗电', '待机', 'endurance'],
    '稳定性MTTF': ['mttf', '稳定性', 'stability', 'crash', '死机', '重启', 'reboot', '挂机',
                   '内存', 'memory', 'leak', '泄漏'],
    '运动健康算法': ['心率', 'heart rate', '睡眠', 'sleep', '步数', 'step', 'gps', '轨迹',
                    '游泳', 'swim', '血氧', 'spo2', 'spO2', '血氧', '训练', 'training',
                    '运动', 'sport', '健康', 'health', '算法', 'algorithm', '配速', 'pace',
                    '划次', 'stroke', '能量', 'energy', '压力', 'stress', '指南针', 'compass'],
    '兼容性': ['compatib', '兼容', 'bluetooth', '蓝牙', 'wifi', 'pairing', '配对',
              '连接', 'connect', 'interop'],
    '音频': ['audio', '音质', '音量', '麦克风', 'mic', 'speaker', '扬声器', '降噪', 'anc'],
    'UI/UX': ['ui', 'ux', '界面', '交互', '动画', 'animation', '表盘', 'watch face',
              'theme', '主题', '壁纸', 'widget', '小组件'],
    '安全': ['security', '安全', '加密', 'encrypt', 'privacy', '隐私', '认证', 'auth'],
    '网络通信': ['network', '网络', 'sync', '同步', 'push', '通知', 'notification',
                'cellular', '蜂窝', ' esim', 'esim'],
}

# 状态中文标签
_STATUS_LABELS = {
    'pass': '通过',
    'fail': '不通过',
    'blocked': '阻塞',
    'delayed': '已延期',
    'n_a': '不适用',
    'unknown': '未识别',
}


def _detect_category(item_name, item_module=''):
    """根据测试项名称和模块识别所属分类"""
    text = f"{item_name} {item_module}".lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text:
                return category
    return '其他'


def _assess_risk_level(items):
    """
    根据一组测试项的结果评估风险等级。
    返回: '高' / '中' / '低' / '无'
    """
    if not items:
        return '无'

    total = len(items)
    fail_count = sum(1 for i in items if i['result'] in ('fail',))
    delayed_count = sum(1 for i in items if i['result'] == 'delayed')
    blocked_count = sum(1 for i in items if i['result'] == 'blocked')
    pass_count = sum(1 for i in items if i['result'] == 'pass')

    problem_count = fail_count + delayed_count + blocked_count
    problem_ratio = problem_count / total if total > 0 else 0
    fail_ratio = fail_count / total if total > 0 else 0

    # 高风险：有失败项且占比 >= 30%，或全部延期/阻塞
    if fail_ratio >= 0.3 or (problem_count == total and total > 0):
        return '高'
    # 中风险：有失败项但占比 < 30%，或有延期/阻塞项
    if fail_count > 0 or delayed_count > 0 or blocked_count > 0:
        return '中'
    # 低风险：全部通过但有未知项
    if pass_count < total:
        return '低'
    return '无'


def _generate_intelligent_analysis(test_items, project_info, stats):
    """
    生成结构化智能分析报告，对标豆包的分析质量。
    输出包含：执行摘要、分类汇总、风险等级、关键发现、改进建议。
    """
    if not test_items:
        return {
            'executive_summary': '未找到测试项数据，请检查Excel文件格式是否正确。',
            'overall_risk': '无',
            'sections': [],
            'key_findings': [],
            'recommendations': []
        }

    total = stats['total']
    pass_count = stats['pass']
    fail_count = stats['fail']
    blocked_count = stats['blocked']
    delayed_count = stats['delayed']
    unknown_count = stats['unknown']
    executed = stats['executed']
    pass_rate = stats['pass_rate']
    executed_pass_rate = stats['executed_pass_rate']

    # === 1. 按分类分组 ===
    category_groups = {}
    for item in test_items:
        cat = _detect_category(item['name'], item.get('module', ''))
        if cat not in category_groups:
            category_groups[cat] = []
        category_groups[cat].append(item)

    # === 2. 生成各分类的汇总 ===
    sections = []
    for cat, items in category_groups.items():
        cat_total = len(items)
        cat_pass = sum(1 for i in items if i['result'] == 'pass')
        cat_fail = sum(1 for i in items if i['result'] == 'fail')
        cat_blocked = sum(1 for i in items if i['result'] == 'blocked')
        cat_delayed = sum(1 for i in items if i['result'] == 'delayed')
        cat_unknown = sum(1 for i in items if i['result'] == 'unknown')
        cat_risk = _assess_risk_level(items)

        # 生成分类摘要文本
        summary_parts = []
        summary_parts.append(f"共 {cat_total} 项")
        if cat_pass > 0:
            summary_parts.append(f"通过 {cat_pass} 项")
        if cat_fail > 0:
            summary_parts.append(f"不通过 {cat_fail} 项")
        if cat_delayed > 0:
            summary_parts.append(f"延期 {cat_delayed} 项")
        if cat_blocked > 0:
            summary_parts.append(f"阻塞 {cat_blocked} 项")
        if cat_unknown > 0:
            summary_parts.append(f"未识别 {cat_unknown} 项")

        cat_pass_rate = f"{(cat_pass / cat_total * 100):.1f}%" if cat_total > 0 else "0%"
        summary_parts.append(f"通过率 {cat_pass_rate}")

        # 提取该分类下的问题项详情
        problem_items = [i for i in items if i['result'] in ('fail', 'blocked', 'delayed')]

        sections.append({
            'category': cat,
            'risk_level': cat_risk,
            'total': cat_total,
            'pass': cat_pass,
            'fail': cat_fail,
            'blocked': cat_blocked,
            'delayed': cat_delayed,
            'pass_rate': cat_pass_rate,
            'summary': '，'.join(summary_parts),
            'problem_items': [{
                'name': i['name'],
                'result': i['result'],
                'result_text': i['result_text'],
                'reason': i.get('reason', ''),
                'target': i.get('target', ''),
                'actual': i.get('actual', '')
            } for i in problem_items],
            'items': items
        })

    # 按风险等级排序：高 > 中 > 低 > 无
    risk_order = {'高': 0, '中': 1, '低': 2, '无': 3}
    sections.sort(key=lambda s: risk_order.get(s['risk_level'], 4))

    # === 3. 评估整体风险 ===
    all_risks = [s['risk_level'] for s in sections]
    if '高' in all_risks:
        overall_risk = '高'
    elif '中' in all_risks:
        overall_risk = '中'
    elif '低' in all_risks:
        overall_risk = '低'
    else:
        overall_risk = '无'

    # === 4. 生成执行摘要 ===
    summary_lines = []

    # 基本信息
    summary_lines.append(f"本次共分析 {total} 项测试")

    # 执行情况
    if delayed_count > 0 or blocked_count > 0:
        summary_lines.append(f"其中已执行 {executed} 项，延期 {delayed_count} 项，阻塞 {blocked_count} 项")
    else:
        summary_lines.append(f"已执行 {executed} 项")

    # 通过/失败情况
    result_parts = []
    if pass_count > 0:
        result_parts.append(f"通过 {pass_count} 项")
    if fail_count > 0:
        result_parts.append(f"不通过 {fail_count} 项")
    if blocked_count > 0:
        result_parts.append(f"阻塞 {blocked_count} 项")
    if delayed_count > 0:
        result_parts.append(f"延期 {delayed_count} 项")
    if unknown_count > 0:
        result_parts.append(f"未识别 {unknown_count} 项")
    summary_lines.append('，'.join(result_parts))

    # 通过率
    if executed > 0 and executed < total:
        summary_lines.append(f"整体通过率 {pass_rate}（已执行项通过率 {executed_pass_rate}）")
    else:
        summary_lines.append(f"整体通过率 {pass_rate}")

    # 整体评估
    if fail_count > 0:
        high_risk_sections = [s for s in sections if s['risk_level'] == '高']
        mid_risk_sections = [s for s in sections if s['risk_level'] == '中']
        if high_risk_sections:
            risk_names = '、'.join([s['category'] for s in high_risk_sections])
            summary_lines.append(f"整体风险等级为「高」，{risk_names} 存在高风险项，需重点关注")
        elif mid_risk_sections:
            summary_lines.append(f"整体风险等级为「中」，部分测试项未通过，需跟进闭环")
        else:
            summary_lines.append(f"整体风险等级为「低」，存在少量未通过项")
    elif delayed_count > 0 or blocked_count > 0:
        summary_lines.append(f"整体风险等级为「{'中' if (delayed_count + blocked_count) > total * 0.3 else '低'}」，"
                             f"部分测试项延期或阻塞，需推进执行")
    elif pass_count == total:
        summary_lines.append("所有测试项均已通过，整体风险等级为「无」")
    else:
        summary_lines.append("部分测试项状态未明确，建议核实数据完整性")

    executive_summary = '。'.join(summary_lines) + '。'

    # === 5. 关键发现 ===
    key_findings = []

    # 高风险分类
    for s in sections:
        if s['risk_level'] == '高':
            finding = f"【高风险】{s['category']}：{s['summary']}"
            if s['problem_items']:
                fail_names = [pi['name'] for pi in s['problem_items'][:5]]
                finding += f"。主要问题项：{', '.join(fail_names)}"
            key_findings.append(finding)

    # 中风险分类
    for s in sections:
        if s['risk_level'] == '中':
            finding = f"【中风险】{s['category']}：{s['summary']}"
            if s['problem_items']:
                fail_names = [pi['name'] for pi in s['problem_items'][:3]]
                finding += f"。关注项：{', '.join(fail_names)}"
            key_findings.append(finding)

    # 延期项汇总
    if delayed_count > 0:
        delayed_items = [i for i in test_items if i['result'] == 'delayed']
        delayed_names = [i['name'] for i in delayed_items[:5]]
        more = f" 等 {len(delayed_items)} 项" if len(delayed_items) > 5 else ""
        key_findings.append(f"【延期项】{len(delayed_items)} 项测试已延期：{', '.join(delayed_names)}{more}，需尽快安排执行")

    # 阻塞项汇总
    if blocked_count > 0:
        blocked_items = [i for i in test_items if i['result'] == 'blocked']
        blocked_names = [i['name'] for i in blocked_items[:5]]
        more = f" 等 {len(blocked_items)} 项" if len(blocked_items) > 5 else ""
        key_findings.append(f"【阻塞项】{len(blocked_items)} 项测试受阻：{', '.join(blocked_names)}{more}，需解除阻塞依赖")

    # 通过项亮点
    pass_sections = [s for s in sections if s['risk_level'] == '无' and s['pass'] == s['total']]
    if pass_sections:
        pass_names = '、'.join([s['category'] for s in pass_sections])
        key_findings.append(f"【达标项】{pass_names} 全部通过，无风险")

    # === 6. 改进建议 ===
    recommendations = []

    if fail_count > 0:
        recommendations.append(f"针对 {fail_count} 项不通过测试，建议优先修复 Fail 项并安排回归验证")
    if delayed_count > 0:
        recommendations.append(f"针对 {delayed_count} 项延期测试，建议明确执行时间节点并推进落地")
    if blocked_count > 0:
        recommendations.append(f"针对 {blocked_count} 项阻塞测试，建议排查阻塞根因并协调资源解除依赖")
    if unknown_count > 0:
        recommendations.append(f"针对 {unknown_count} 项状态未识别的测试，建议核实结果字段填写是否规范")

    high_risk_sections = [s for s in sections if s['risk_level'] == '高']
    if high_risk_sections:
        rec_cats = '、'.join([s['category'] for s in high_risk_sections])
        recommendations.append(f"「{rec_cats}」为高风险领域，建议作为下一阶段重点攻关方向")

    if not recommendations:
        recommendations.append("所有测试项均已通过，建议保持现有质量水平，持续监控")

    return {
        'executive_summary': executive_summary,
        'overall_risk': overall_risk,
        'sections': sections,
        'key_findings': key_findings,
        'recommendations': recommendations,
        'status_labels': _STATUS_LABELS
    }


# === 分块上传 API（绕过预览代理的请求体大小限制）===
# 使用磁盘持久化存储分块上传元数据（兼容 Railway --max-requests 导致的 worker 重启）
_chunk_uploads_dir = os.path.join(app.config['UPLOAD_FOLDER'], '_chunk_meta')
os.makedirs(_chunk_uploads_dir, exist_ok=True)

def _chunk_meta_path(upload_id):
    return os.path.join(_chunk_uploads_dir, f"{upload_id}.json")

def _load_chunk_meta(upload_id):
    """从磁盘加载分块上传元数据"""
    meta_path = _chunk_meta_path(upload_id)
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, 'r') as f:
            meta = json.load(f)
        meta['received_chunks'] = set(meta.get('received_chunks', []))
        return meta
    except Exception:
        return None

def _save_chunk_meta(upload_id, meta):
    """持久化分块上传元数据到磁盘"""
    meta_to_save = dict(meta)
    meta_to_save['received_chunks'] = list(meta.get('received_chunks', set()))
    with open(_chunk_meta_path(upload_id), 'w') as f:
        json.dump(meta_to_save, f)

def _delete_chunk_meta(upload_id):
    """删除分块上传元数据"""
    try:
        os.unlink(_chunk_meta_path(upload_id))
    except Exception:
        pass

@app.route('/api/upload-init', methods=['POST'])
def api_upload_init():
    """初始化分块上传，返回 upload_id"""
    data = request.get_json(silent=True)
    if data is None:
        data = {}

    filename = data.get('filename', '')
    total_size = data.get('total_size', 0)
    total_chunks = data.get('total_chunks', 0)

    if not filename or total_chunks == 0:
        return jsonify({'error': '缺少必要参数: filename, total_chunks'}), 400

    filename_lower = filename.lower()
    if not (filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls')):
        return jsonify({'error': '只支持Excel文件(.xlsx, .xls)'}), 400

    orig_ext = os.path.splitext(filename)[1].lower()
    if orig_ext not in ('.xlsx', '.xls'):
        orig_ext = '.xlsx'

    upload_id = hashlib.md5(f"{time.time()}_{filename}".encode()).hexdigest()[:16]
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"excel_{upload_id}{orig_ext}")

    _chunk_uploads = {
        'filename': filename,
        'file_path': file_path,
        'ext': orig_ext,
        'total_chunks': total_chunks,
        'total_size': total_size,
        'received_chunks': set(),
        'created_at': time.time()
    }
    _save_chunk_meta(upload_id, _chunk_uploads)

    # 预分配文件大小（支持并发分块按 offset 写入）
    with open(file_path, 'wb') as f:
        if total_size > 0:
            f.truncate(total_size)

    logger.info(f"分块上传初始化: {filename}, upload_id={upload_id}, total_chunks={total_chunks}, total_size={total_size}")

    return jsonify({
        'status': 'success',
        'data': {
            'upload_id': upload_id
        }
    })

@app.route('/api/upload-chunk', methods=['POST'])
def api_upload_chunk():
    """上传单个分块"""
    upload_id = request.form.get('upload_id', '')
    chunk_index = request.form.get('chunk_index', '')
    chunk_file = request.files.get('chunk', None)

    if not upload_id:
        return jsonify({'error': '无效的 upload_id'}), 400

    meta = _load_chunk_meta(upload_id)
    if meta is None:
        return jsonify({'error': '无效的 upload_id'}), 400

    if chunk_index == '' or chunk_file is None:
        return jsonify({'error': '缺少 chunk_index 或 chunk'}), 400

    chunk_index = int(chunk_index)

    if chunk_index in meta['received_chunks']:
        return jsonify({'status': 'success', 'data': {'chunk_index': chunk_index, 'duplicate': True}})

    # 读取分块数据，按 offset 写入正确位置（支持并发乱序上传）
    chunk_data = chunk_file.read()
    offset = int(request.form.get('offset', -1))
    if offset < 0:
        return jsonify({'error': '缺少 offset 参数'}), 400

    with open(meta['file_path'], 'r+b') as f:
        f.seek(offset)
        f.write(chunk_data)

    meta['received_chunks'].add(chunk_index)
    _save_chunk_meta(upload_id, meta)
    logger.info(f"分块上传: upload_id={upload_id}, chunk={chunk_index}/{meta['total_chunks'] - 1}, size={len(chunk_data)}")

    return jsonify({
        'status': 'success',
        'data': {
            'chunk_index': chunk_index,
            'received': len(meta['received_chunks']),
            'total': meta['total_chunks']
        }
    })

@app.route('/api/upload-complete', methods=['POST'])
def api_upload_complete():
    """分块上传完成，验证文件并返回 file_id"""
    data = request.get_json(silent=True)
    if data is None:
        data = {}

    upload_id = data.get('upload_id', '')
    if not upload_id:
        return jsonify({'error': '无效的 upload_id'}), 400

    meta = _load_chunk_meta(upload_id)
    if meta is None:
        return jsonify({'error': '无效的 upload_id'}), 400

    if len(meta['received_chunks']) != meta['total_chunks']:
        return jsonify({
            'error': f'分块不完整: 已收到 {len(meta["received_chunks"])}/{meta["total_chunks"]}'
        }), 400

    file_path = meta['file_path']
    filename = meta['filename']

    # 从文件路径提取 file_id
    file_id = os.path.basename(file_path).replace('excel_', '').replace(meta['ext'], '')

    try:
        file_size = os.path.getsize(file_path)
        logger.info(f"========== 分块上传完成: {filename} (size={file_size / 1024 / 1024:.2f}MB) ==========")

        # 检测文件格式
        is_html = False
        with open(file_path, 'rb') as f:
            header = f.read(200)
        if b'<html' in header.lower() or b'<!doctype' in header.lower():
            is_html = True
            logger.info(f"文件格式检测: HTML 伪装的 .xls 文件")
        elif header[:4] == b'\x50\x4b\x03\x04':
            logger.info(f"文件格式检测: .xlsx (ZIP格式)")
        elif header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            logger.info(f"文件格式检测: 真正的 .xls (OLE2格式)")
        else:
            logger.info(f"文件格式检测: 未知格式, header={header[:20]}")

        reader = ExcelReader(file_path)
        reader.open()
        sheet_names = reader.get_sheet_names()
        reader.close()

        # 清理元数据
        _delete_chunk_meta(upload_id)

        logger.info(f"上传成功: file_id={file_id}, sheets={sheet_names}, is_html={is_html}")

        return jsonify({
            'status': 'success',
            'data': {
                'file_id': file_id,
                'file_name': filename,
                'sheet_names': sheet_names,
                'file_size_mb': round(file_size / 1024 / 1024, 2),
                'is_html': is_html,
            }
        })

    except Exception as e:
        logger.error(f"分块上传文件分析失败: {traceback.format_exc()}")
        # 清理元数据和文件
        try:
            os.unlink(file_path)
        except Exception:
            pass
        _delete_chunk_meta(upload_id)
        return jsonify({'error': str(e)}), 500


# === Excel问题分析 API ===
@app.route('/api/excel-analyze', methods=['POST'])
def api_excel_analyze():
    if 'file' not in request.files:
        return jsonify({'error': '请选择文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '请选择文件'}), 400

    filename_lower = file.filename.lower()
    if not (filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls')):
        return jsonify({'error': '只支持Excel文件(.xlsx, .xls)'}), 400

    # 检查文件大小（云平台内存有限）
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > 50 * 1024 * 1024:
        return jsonify({'error': f'文件过大({file_size // 1024 // 1024}MB)，云端最大支持50MB。大文件请使用本地部署：git clone https://github.com/wangys38-cyber/CR-tools.git'}), 413

    orig_ext = os.path.splitext(file.filename)[1].lower()
    if orig_ext not in ('.xlsx', '.xls'):
        orig_ext = '.xlsx'

    try:
        file_id = hashlib.md5(f"{time.time()}_{file.filename}".encode()).hexdigest()[:16]
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"excel_{file_id}{orig_ext}")
        file.save(file_path)

        logger.info(f"========== 收到问题分析文件: {file.filename} ==========")

        reader = ExcelReader(file_path)
        reader.open()
        sheet_names = reader.get_sheet_names()
        reader.close()

        return jsonify({
            'status': 'success',
            'data': {
                'file_id': file_id,
                'file_name': file.filename,
                'sheet_names': sheet_names
            }
        })

    except Exception as e:
        logger.error(f"文件上传失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


# 缓存完整分析结果（避免重复计算）
_analysis_cache = {}

# 后台任务存储
_background_tasks = {}
_background_tasks_dir = os.path.join(app.config['UPLOAD_FOLDER'], '_task_meta')
os.makedirs(_background_tasks_dir, exist_ok=True)

def _task_meta_path(task_id):
    return os.path.join(_background_tasks_dir, f"{task_id}.json")

def _load_task_meta(task_id):
    """从磁盘加载任务元数据"""
    meta_path = _task_meta_path(task_id)
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, 'r') as f:
            return json.load(f)
    except Exception:
        return None

def _save_task_meta(task_id, task_data):
    """持久化任务元数据到磁盘"""
    try:
        with open(_task_meta_path(task_id), 'w') as f:
            json.dump(task_data, f, default=str)
    except Exception:
        pass

def _delete_task_meta(task_id):
    """删除任务元数据"""
    try:
        os.unlink(_task_meta_path(task_id))
    except Exception:
        pass

import threading

@app.route('/api/excel-analyze-fields', methods=['POST'])
def api_excel_analyze_fields():
    """轻量级字段映射接口：同步执行（仅需读取表头，耗时约5秒）"""
    data = request.get_json(silent=True)
    if data is None:
        data = {}

    file_id = data.get('file_id', '')
    sheet_name = data.get('sheet_name', '')

    logger.info(f"excel-analyze-fields 请求: file_id={file_id}, sheet_name={sheet_name}")

    if not file_id or not sheet_name:
        return jsonify({'error': '缺少参数: file_id, sheet_name'}), 400

    file_path = None
    for ext in ['.xlsx', '.xls']:
        candidate = os.path.join(app.config['UPLOAD_FOLDER'], f"excel_{file_id}{ext}")
        if os.path.exists(candidate):
            file_path = candidate
            break

    if not file_path:
        return jsonify({'error': f'文件不存在: {file_id}'}), 404

    try:
        reader = ExcelReader(file_path)
        reader.open()

        # 使用轻量级表头读取方法，避免大文件 OOM
        if reader._is_html:
            headers, first_data_row, data_row_count = reader._parse_html_headers_only()
            reader.close()
            
            if not headers:
                return jsonify({
                    'status': 'done',
                    'data': {
                        'headers': [],
                        'detected_columns': {},
                        'detected_fields_count': 0,
                        'current_sheet': sheet_name,
                        'summary': {'total_issues': 0},
                        'sample_data': [],
                    }
                })

            headers = [str(c).strip() if c else '' for c in headers]
            col_map = _detect_issue_columns(headers)

            raw_detected = {
                'issue_id': col_map.get('id', -1),
                'title': col_map.get('title', -1),
                'module': col_map.get('module', -1),
                'severity': col_map.get('severity', -1),
                'status': col_map.get('status', -1),
                'developer': col_map.get('developer', -1),
                'create_date': col_map.get('created_date', -1),
                'resolve_date': col_map.get('resolved_date', -1),
                'fixed_date': col_map.get('closed_date', -1),
                'fixed_version': col_map.get('fix_version', -1),
            }
            detected_columns = {k: v for k, v in raw_detected.items() if v >= 0}

            sample_data = [first_data_row] if first_data_row else []
            total_issues = data_row_count

            logger.info(f"字段映射完成(轻量级): detected_columns={detected_columns}, total_issues≈{total_issues}")

            result = {
                'headers': headers,
                'detected_columns': detected_columns,
                'detected_fields_count': len(detected_columns),
                'current_sheet': sheet_name,
                'summary': {'total_issues': total_issues},
                'sample_data': sample_data,
            }

            gc.collect()
            return jsonify({'status': 'done', 'data': result})
        else:
            # 非 HTML 格式：正常读取（内存安全）
            rows = reader.get_sheet_data(sheet_name)
            reader.close()

            if not rows or len(rows) < 1:
                return jsonify({
                    'status': 'done',
                    'data': {
                        'headers': [],
                        'detected_columns': {},
                        'detected_fields_count': 0,
                        'current_sheet': sheet_name,
                        'summary': {'total_issues': 0},
                        'sample_data': [],
                    }
                })

            headers = [str(c).strip() if c else '' for c in rows[0]]
            col_map = _detect_issue_columns(headers)

            raw_detected = {
                'issue_id': col_map.get('id', -1),
                'title': col_map.get('title', -1),
                'module': col_map.get('module', -1),
                'severity': col_map.get('severity', -1),
                'status': col_map.get('status', -1),
                'developer': col_map.get('developer', -1),
                'create_date': col_map.get('created_date', -1),
                'resolve_date': col_map.get('resolved_date', -1),
                'fixed_date': col_map.get('closed_date', -1),
                'fixed_version': col_map.get('fix_version', -1),
            }
            detected_columns = {k: v for k, v in raw_detected.items() if v >= 0}

            data_rows = rows[1:]
            total_issues = sum(1 for row in data_rows if any(str(c).strip() for c in row))
            sample_data = data_rows[:3] if data_rows else []

            logger.info(f"字段映射完成: detected_columns={detected_columns}, total_issues={total_issues}")

            result = {
                'headers': headers,
                'detected_columns': detected_columns,
                'detected_fields_count': len(detected_columns),
                'current_sheet': sheet_name,
                'summary': {'total_issues': total_issues},
                'sample_data': sample_data,
            }

            del rows, data_rows
            gc.collect()

            return jsonify({'status': 'done', 'data': result})

    except Exception as e:
        logger.error(f"字段映射失败: {traceback.format_exc()}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/task-status', methods=['POST'])
def api_task_status():
    """查询后台任务状态"""
    data = request.get_json(silent=True)
    if data is None:
        data = {}

    task_id = data.get('task_id', '')
    if not task_id:
        return jsonify({'error': '无效的 task_id'}), 400

    # 优先从内存读取，worker 重启后从磁盘恢复
    task = _background_tasks.get(task_id)
    if task is None:
        task = _load_task_meta(task_id)
        if task is None:
            return jsonify({'status': 'error', 'error': '任务不存在或已过期，请重新上传文件'}), 400

    # 检查任务是否超时（超过 7 分钟仍在 processing 视为超时）
    if task['status'] == 'processing':
        created_at = task.get('created_at', 0)
        if created_at and (time.time() - created_at) > 420:
            task['status'] = 'error'
            task['error'] = '分析超时（超过7分钟），可能是文件过大或格式异常，请尝试减少数据量或转换为 .xlsx 格式'
            _save_task_meta(task_id, task)

    resp = {'status': task['status']}

    if task['status'] == 'done':
        resp['data'] = task['result']
        # 清理已完成的任务（延迟清理，让客户端有机会获取结果）
    elif task['status'] == 'error':
        resp['error'] = task['error']

    return jsonify(resp)


@app.route('/api/excel-analyze-sheet', methods=['POST'])
def api_excel_analyze_sheet():
    """完整分析接口：启动后台分析，立即返回 task_id"""
    data = request.get_json(silent=True)
    if data is None:
        data = {}

    file_id = data.get('file_id', '')
    sheet_name = data.get('sheet_name', '')

    logger.info(f"excel-analyze-sheet 请求: file_id={file_id}, sheet_name={sheet_name}, content_type={request.content_type}")

    if not file_id or not sheet_name:
        return jsonify({'error': f'缺少参数: file_id={repr(file_id)}, sheet_name={repr(sheet_name)}'}), 400

    file_path = None
    for ext in ['.xlsx', '.xls']:
        candidate = os.path.join(app.config['UPLOAD_FOLDER'], f"excel_{file_id}{ext}")
        if os.path.exists(candidate):
            file_path = candidate
            break

    if not file_path:
        return jsonify({'error': f'文件不存在: {file_id}'}), 404

    # 创建后台任务
    task_id = hashlib.md5(f"sheet_{file_id}_{sheet_name}_{time.time()}".encode()).hexdigest()[:16]
    task_data = {
        'status': 'processing',
        'result': None,
        'error': None,
        'created_at': time.time()
    }
    _background_tasks[task_id] = task_data
    _save_task_meta(task_id, task_data)

    def _do_full_analysis():
        try:
            gc.collect()
            _log_mem("开始分析前")
            t0 = time.time()
            result = _analyze_issue_sheet(file_path, sheet_name)
            elapsed = time.time() - t0
            _log_mem(f"分析完成，耗时 {elapsed:.1f}s")
            gc.collect()

            _background_tasks[task_id]['result'] = result
            _background_tasks[task_id]['status'] = 'done'
            _save_task_meta(task_id, _background_tasks[task_id])
        except Exception as e:
            error_detail = str(e) if str(e) else f'{type(e).__name__} (无详细错误信息)'
            logger.error(f"分析失败: {traceback.format_exc()}")
            _background_tasks[task_id]['error'] = error_detail
            _background_tasks[task_id]['status'] = 'error'
            _save_task_meta(task_id, _background_tasks[task_id])

    thread = threading.Thread(target=_do_full_analysis, daemon=True)
    thread.start()

    return jsonify({'status': 'success', 'data': {'task_id': task_id}})


def _log_mem(label):
    try:
        import psutil
        p = psutil.Process()
        mb = p.memory_info().rss / 1024 / 1024
        logger.info(f"[MEM] {label}: RSS={mb:.1f}MB")
    except Exception:
        pass


def _analyze_issue_sheet(file_path, sheet_name):
    """分析问题列表Sheet，返回前端期望的数据格式"""
    _log_mem("分析开始：读取Excel")
    t0 = time.time()
    reader = ExcelReader(file_path)
    reader.open()
    rows = reader.get_sheet_data(sheet_name)
    reader.close()
    _log_mem(f"Excel读取完成：{len(rows)}行")

    if not rows or len(rows) < 2:
        return {
            'summary': {},
            'severity_values': [],
            'severity_detected': False,
            'module_stats': {},
            'dev_stats': {},
            'daily_stats': [],
            'suggestions': [],
            'unverified_issues': [],
            'detected_columns': {},
            'sample_data': [],
            'headers': []
        }

    headers = [str(c).strip() if c else '' for c in rows[0]]
    data_rows = rows[1:]
    # 立即释放 rows 内存（只保留 data_rows 和 headers）
    del rows
    gc.collect()
    _log_mem(f"表头提取：{len(headers)}列 x {len(data_rows)}数据行")

    col_map = _detect_issue_columns(headers)
    
    # 调试日志：显示识别到的字段
    logger.info(f"字段识别结果: {col_map}")
    logger.info(f"Fix Version column: {col_map.get('fix_version', -1)}")
    if col_map.get('fix_version', -1) >= 0:
        logger.info(f"Fix Version header: {headers[col_map['fix_version']]}")
    logger.info(f"所有 headers: {headers}")

    issues = []
    for row in data_rows:
        cells = [str(c).strip() if c else '' for c in row]
        if not any(cells):
            continue

        issue = {
            'id': _safe_get(cells, col_map.get('id', -1)),
            'title': _safe_get(cells, col_map.get('title', -1)),
            'module': _safe_get(cells, col_map.get('module', -1)),
            'severity': _safe_get(cells, col_map.get('severity', -1)),
            'status': _safe_get(cells, col_map.get('status', -1)),
            'developer': _safe_get(cells, col_map.get('developer', -1)),
            'created_date': _safe_get(cells, col_map.get('created_date', -1)),
            'resolved_date': _safe_get(cells, col_map.get('resolved_date', -1)),
            'closed_date': _safe_get(cells, col_map.get('closed_date', -1)),
            'fix_version': _safe_get(cells, col_map.get('fix_version', -1)),
            'resolution': _safe_get(cells, col_map.get('resolution', -1)),
        }
        issues.append(issue)

    total = len(issues)
    
    # 统计
    by_severity = {'blocker': 0, 'critical': 0, 'major': 0, 'minor': 0, 'trivial': 0}
    by_severity_resolved = {'blocker': 0, 'critical': 0, 'major': 0, 'minor': 0, 'trivial': 0}
    by_module = {}
    by_developer = {}
    resolved = 0
    severity_values = set()
    daily_stats = {}  # date -> {new: count, resolved: count}
    current_severity_level = ''
    
    # 严重程度检测
    has_severity_col = col_map.get('severity', -1) >= 0
    
    for issue in issues:
        # Severity 统计
        sev = issue.get('severity', '').lower().strip()
        current_severity_level = ''
        if sev:
            severity_values.add(issue.get('severity', '').strip())
            for level in ['blocker', 'critical', 'major', 'minor', 'trivial']:
                if level in sev:
                    by_severity[level] += 1
                    current_severity_level = level
                    break

        # 模块统计
        mod = issue.get('module', '').strip()
        if mod:
            if mod not in by_module:
                by_module[mod] = {'total': 0, 'resolved': 0, 'unresolved': 0}
            by_module[mod]['total'] += 1

        # 研发统计
        dev = issue.get('developer', '').strip()
        if dev:
            if dev not in by_developer:
                by_developer[dev] = {'total': 0, 'resolved': 0, 'unresolved': 0, 'modules': []}
            by_developer[dev]['total'] += 1
            if mod and mod not in by_developer[dev]['modules']:
                by_developer[dev]['modules'].append(mod)

        # 状态判断
        status = issue.get('status', '').lower()
        is_resolved = any(kw in status for kw in ['resolved', 'fixed', 'closed', 'done', '已解决', '已关闭'])
        
        if is_resolved:
            resolved += 1
            # 更新模块/研发的已解决计数
            if mod and mod in by_module:
                by_module[mod]['resolved'] += 1
            if dev and dev in by_developer:
                by_developer[dev]['resolved'] += 1
            # 更新严重程度的已解决计数
            if current_severity_level and current_severity_level in by_severity_resolved:
                by_severity_resolved[current_severity_level] += 1
        else:
            if mod and mod in by_module:
                by_module[mod]['unresolved'] += 1
            if dev and dev in by_developer:
                by_developer[dev]['unresolved'] += 1
        
        # 日期统计
        created = issue.get('created_date', '').strip()
        if created:
            date_key = normalize_date(created)
            if date_key:
                if date_key not in daily_stats:
                    daily_stats[date_key] = {'new': 0, 'resolved': 0}
                daily_stats[date_key]['new'] += 1
        
        resolved_date = issue.get('resolved_date', '').strip()
        if resolved_date:
            date_key = normalize_date(resolved_date)
            if date_key:
                if date_key not in daily_stats:
                    daily_stats[date_key] = {'new': 0, 'resolved': 0}
                daily_stats[date_key]['resolved'] += 1

    # 计算比率
    def calc_rate(count):
        return round(count / total * 100, 1) if total > 0 else 0
    
    def calc_bc_rate():
        bc_total = by_severity.get('blocker', 0) + by_severity.get('critical', 0)
        bc_resolved = 0
        # 计算 B+C 已解决数
        for issue in issues:
            sev = issue.get('severity', '').lower()
            status = issue.get('status', '').lower()
            if ('blocker' in sev or 'critical' in sev) and any(kw in status for kw in ['resolved', 'fixed', 'closed', 'done', '已解决', '已关闭']):
                bc_resolved += 1
        return bc_total, round(bc_resolved / bc_total * 100, 1) if bc_total > 0 else 0

    bc_total, bc_rate = calc_bc_rate()
    
    # 构建 summary
    summary = {
        'total_issues': total,
        'total_resolved': resolved,
        'total_unresolved': total - resolved,
        'resolution_rate': calc_rate(resolved),
        'blocker_total': by_severity['blocker'],
        'blocker_resolved': by_severity_resolved['blocker'],
        'blocker_rate': calc_rate(by_severity['blocker']),
        'critical_total': by_severity['critical'],
        'critical_resolved': by_severity_resolved['critical'],
        'critical_rate': calc_rate(by_severity['critical']),
        'major_total': by_severity['major'],
        'major_resolved': by_severity_resolved['major'],
        'major_rate': calc_rate(by_severity['major']),
        'minor_total': by_severity['minor'],
        'minor_resolved': by_severity_resolved['minor'],
        'minor_rate': calc_rate(by_severity['minor']),
        'trivial_total': by_severity['trivial'],
        'trivial_resolved': by_severity_resolved['trivial'],
        'trivial_rate': calc_rate(by_severity['trivial']),
        'blocker_critical_total': bc_total,
        'blocker_critical_rate': bc_rate,
    }
    
    # 模块统计格式
    module_stats = {}
    stability_stats = {}  # 稳定性模块统计
    stability_module_names = []  # 稳定性模块名称列表
    
    for mod, stats in by_module.items():
        module_stats[mod] = {
            'total': stats['total'],
            'resolved': stats['resolved'],
            'unresolved': stats['unresolved']
        }
        # 检查是否是稳定性模块 - 基于 MTTF 关键字
        mod_lower = mod.lower()
        if 'mttf' in mod_lower:
            stability_stats[mod] = {
                'total': stats['total'],
                'resolved': stats['resolved'],
                'unresolved': stats['unresolved']
            }
            stability_module_names.append(mod)
    
    # 研发统计格式
    dev_stats = {}
    for dev, stats in by_developer.items():
        dev_stats[dev] = {
            'total': stats['total'],
            'resolved': stats['resolved'],
            'unresolved': stats['unresolved'],
            'modules': stats['modules'][:5]  # 最多显示5个模块
        }
    
    # 日期统计排序
    daily_stats_list = sorted([
        {'date': k, 'new_count': v['new'], 'resolved_count': v['resolved']}
        for k, v in daily_stats.items()
    ], key=lambda x: x['date'])
    
    # 智能分析建议
    suggestions = []
    if total > 0:
        # 1. 总体概览
        resolved_rate = (resolved / total * 100) if total > 0 else 0
        unresolved_count = total - resolved
        suggestions.append({
            'type': 'overview',
            'title': '📊 问题总体概览',
            'detail': f'共 {total} 个问题，已解决 {resolved} 个（{resolved_rate:.1f}%），未解决 {unresolved_count} 个',
            'stats': {
                'total': total,
                'resolved': resolved,
                'unresolved': unresolved_count,
                'rate': f'{resolved_rate:.1f}%'
            }
        })
        
        # 2. 问题最多的模块
        sorted_modules = sorted(by_module.items(), key=lambda x: x[1]['total'], reverse=True)
        if sorted_modules:
            top_mod = sorted_modules[0]
            mod_rate = (top_mod[1]['resolved'] / top_mod[1]['total'] * 100) if top_mod[1]['total'] > 0 else 0
            suggestions.append({
                'type': 'module',
                'title': f'🔥 模块「{top_mod[0]}」问题最多（{top_mod[1]["total"]}个）',
                'detail': f'已解决 {top_mod[1]["resolved"]} 个（{mod_rate:.1f}%），未解决 {top_mod[1]["unresolved"]} 个',
                'stats': {
                    'name': top_mod[0],
                    'total': top_mod[1]['total'],
                    'resolved': top_mod[1]['resolved'],
                    'unresolved': top_mod[1]['unresolved'],
                    'rate': f'{mod_rate:.1f}%'
                }
            })
        
        # 3. Blocker/Critical 问题
        bc_unresolved = sum(
            1 for issue in issues
            if any(kw in issue.get('severity', '').lower() for kw in ['blocker', 'critical'])
            and not any(kw in issue.get('status', '').lower() for kw in ['resolved', 'fixed', 'closed', 'done', '已解决', '已关闭'])
        )
        bc_total = sum(
            1 for issue in issues
            if any(kw in issue.get('severity', '').lower() for kw in ['blocker', 'critical'])
        )
        if bc_total > 0:
            suggestions.append({
                'type': 'urgent',
                'title': f'🚨 Blocker/Critical 高优先级问题',
                'detail': f'共 {bc_total} 个，其中 {bc_unresolved} 个未解决，建议优先处理',
                'stats': {
                    'total': bc_total,
                    'unresolved': bc_unresolved
                }
            })
        
        # 4. 问题最多的研发人员
        sorted_devs = sorted(by_developer.items(), key=lambda x: x[1]['total'], reverse=True)
        if sorted_devs and len(sorted_devs) > 0:
            top_dev = sorted_devs[0]
            dev_mods = ", ".join(top_dev[1]['modules'][:3])
            suggestions.append({
                'type': 'developer',
                'title': f'👤 「{top_dev[0]}」负责的问题最多（{top_dev[1]["total"]}个）',
                'detail': f'涉及模块: {dev_mods}',
                'stats': {
                    'name': top_dev[0],
                    'total': top_dev[1]['total'],
                    'modules': top_dev[1]['modules'][:5]
                }
            })
        
        # 5. 解决率分析
        low_rate_modules = []
        for mod, stats in by_module.items():
            if stats['total'] >= 5:  # 只考虑问题数>=5的模块
                rate = (stats['resolved'] / stats['total'] * 100) if stats['total'] > 0 else 0
                if rate < 50:
                    low_rate_modules.append({'name': mod, 'rate': rate, 'unresolved': stats['unresolved']})
        
        if low_rate_modules:
            low_rate_modules.sort(key=lambda x: x['rate'])
            top_low = low_rate_modules[:3]
            mod_names = ", ".join([m['name'] for m in top_low])
            suggestions.append({
                'type': 'warning',
                'title': f'⚠️ 解决率低于50%的模块（{len(low_rate_modules)}个）',
                'detail': f'{mod_names}',
                'stats': {
                    'count': len(low_rate_modules),
                    'lowest': f'{top_low[0]["rate"]:.1f}%'
                }
            })
        
        # 6. 建议
        advice = []
        if bc_unresolved > 0:
            advice.append(f'优先处理 {bc_unresolved} 个 Blocker/Critical 级别的未解决问题')
        if sorted_modules and sorted_modules[0][1]['unresolved'] > 50:
            advice.append(f'重点关注模块「{sorted_modules[0][0]}」，有 {sorted_modules[0][1]["unresolved"]} 个问题待解决')
        if low_rate_modules:
            advice.append(f'提升 {len(low_rate_modules)} 个解决率低于 50% 模块的处理进度')
        advice.append('定期审查已解决但未验证的问题，及时关闭')
        
        suggestions.append({
            'type': 'advice',
            'title': '💡 分析建议',
            'detail': '\n'.join([f'• {a}' for a in advice]),
            'advice_list': advice
        })
    
    # 未验证的问题（无标题或无状态）
    unverified_issues = [
        issue for issue in issues
        if not issue.get('title', '').strip() or not issue.get('status', '').strip()
    ][:10]  # 最多显示10个
    
    # 已解决待验证的问题：从 Status 字段筛选 verified
    resolved_unverified = []
    for issue in issues:
        status = issue.get('status', '').lower().strip()
        if status and 'verified' in status:
            resolved_unverified.append({
                'issue_id': issue.get('id', ''),
                'developer': issue.get('developer', ''),
                'module': issue.get('module', ''),
                'resolution': issue.get('resolution', ''),
                'status': issue.get('status', ''),
                'severity': issue.get('severity', ''),
                'title': issue.get('title', ''),
                'create_date': issue.get('created_date', ''),
            })
            if len(resolved_unverified) >= 30:
                break
    
    # 收集稳定性模块的问题列表 - 精简到200条节省内存/带宽
    all_issues_brief = []
    for issue in issues:
        all_issues_brief.append({
            'issue_id': issue.get('id', ''),
            'title': issue.get('title', ''),
            'module': issue.get('module', ''),
            'developer': issue.get('developer', ''),
            'status': issue.get('status', ''),
            'severity': issue.get('severity', ''),
            'create_date': issue.get('created_date', ''),
            'resolved_date': issue.get('resolved_date', ''),
            'closed_date': issue.get('closed_date', ''),
            'fix_version': issue.get('fix_version', ''),
            'resolution': issue.get('resolution', ''),
        })
    all_issues_brief.sort(key=lambda x: x.get('create_date', ''), reverse=True)
    all_issues_brief = all_issues_brief[:200]
    
    # 释放大列表内存
    sample_data = data_rows[:3] if data_rows else []
    del data_rows, issues
    gc.collect()
    
    _log_mem(f"构建结果对象完成，总耗时 {time.time() - t0:.1f}s")
    
    # Build detected_columns - only include columns that were actually found
    raw_detected = {
        'issue_id': col_map.get('id', -1),
        'title': col_map.get('title', -1),
        'module': col_map.get('module', -1),
        'severity': col_map.get('severity', -1),
        'status': col_map.get('status', -1),
        'developer': col_map.get('developer', -1),
        'create_date': col_map.get('created_date', -1),
        'resolve_date': col_map.get('resolved_date', -1),
        'fixed_date': col_map.get('closed_date', -1),
        'fixed_version': col_map.get('fix_version', -1),
    }
    detected_columns = {k: v for k, v in raw_detected.items() if v >= 0}
    
    logger.info(f"detected_columns (valid only): {detected_columns}")
    logger.info(f"detected_fields_count: {len(detected_columns)}")
    
    return {
        'summary': summary,
        'severity_values': list(severity_values)[:20],
        'severity_detected': has_severity_col and len(severity_values) > 0,
        'module_stats': module_stats,
        'stability_stats': stability_stats,
        'all_issues': all_issues_brief,
        'dev_stats': dev_stats,
        'daily_stats': daily_stats_list,
        'suggestions': suggestions,
        'unverified_issues': unverified_issues,
        'resolved_unverified': resolved_unverified,
        'current_sheet': sheet_name,
        'detected_columns': detected_columns,
        'detected_fields_count': len(detected_columns),
        'sample_data': sample_data,
        'headers': headers,
    }


def _detect_issue_columns(headers):
    col_map = {}
    headers_lower = [str(h).lower().strip() for h in headers]

    for i, h in enumerate(headers_lower):
        # 问题编号 - 精确匹配 "key"（排除 "issue key", "edart key" 等）
        if h == 'key':
            col_map['id'] = i
        elif any(kw in h for kw in ['title', 'summary', '标题', '描述']):
            col_map['title'] = i
        # 模块组件 - 优先匹配 "component/s"，再匹配 "component"
        elif h == 'component/s' or h == 'component/s ':
            col_map['module'] = i
        elif h == 'component' and 'module' not in col_map:
            col_map['module'] = i
        # 严重程度 - 优先匹配 severity 而非 priority
        elif any(kw in h for kw in ['severity', '严重程度', '严重性']):
            col_map['severity'] = i
        elif h == 'priority' or '优先级' in h:
            if 'severity' not in col_map:
                col_map['severity'] = i
        # Status - 精确匹配 "status"，排除 "HW Status", "Test Status" 等
        elif h == 'status' or h == '状态':
            col_map['status'] = i
        # 研发 - 匹配 "assignee"
        elif h == 'assignee':
            col_map['developer'] = i
        # 创建日期 - 精确匹配 "created"
        elif h == 'created' or '创建日期' in h:
            col_map['created_date'] = i
        # Fix Version/s
        elif 'fix version' in h or 'fixversion' in h or 'fix_version' in h:
            col_map['fix_version'] = i
        # Resolved 日期 - 精确匹配 "resolved"
        elif h == 'resolved' or h == '解决日期':
            col_map['resolved_date'] = i
        # Closed Date - fixed日期
        elif 'closed' in h and 'date' in h:
            col_map['closed_date'] = i
        elif any(kw in h for kw in ['project', '项目']):
            col_map['project'] = i
        elif any(kw in h for kw in ['issue type', 'type', '类型']):
            col_map['issue_type'] = i
        elif h == 'resolution' or h == '解决方式':
            col_map['resolution'] = i
        elif 'resolution' in h and 'resolution' not in col_map:
            col_map['resolution'] = i
        elif any(kw in h for kw in ['reporter', '报告人', '提交人']):
            col_map['reporter'] = i
        elif any(kw in h for kw in ['updated', '更新']):
            col_map['updated_date'] = i

    return col_map


def _safe_get(cells, idx):
    if idx < 0 or idx >= len(cells):
        return ''
    return str(cells[idx]).strip() if cells[idx] else ''


def _escape_html(text):
    """转义HTML特殊字符"""
    import html
    return html.escape(str(text)) if text else ''

# === Chromium 浏览器全局复用（避免每次 PDF 渲染冷启动 3-10s） ===
from playwright.sync_api import sync_playwright as _sync_playwright

_pdf_render_lock = threading.Lock()
_pw_instance = None
_pw_browser = None

def _get_pw_browser():
    """获取或创建全局 Chromium 浏览器实例（复用，避免每次冷启动）"""
    global _pw_instance, _pw_browser
    if _pw_browser is not None:
        try:
            _ = _pw_browser.version
            return _pw_browser
        except Exception:
            _pw_browser = None
            logger.warning("Chromium 浏览器已断开，正在重新创建...")
    if _pw_instance is None:
        _pw_instance = _sync_playwright().start()
    # 优先使用系统 Chrome（本地环境），失败后回退到 Playwright 内置 Chromium（Docker/Railway）
    try:
        _pw_browser = _pw_instance.chromium.launch(headless=True, channel="chrome")
    except Exception:
        _pw_browser = _pw_instance.chromium.launch(headless=True)
    logger.info("Chromium 浏览器实例已创建（全局复用）")
    return _pw_browser

def _render_pdf(html_path, pdf_path, margin=None, extra_wait_ms=0, wait_selector=None):
    """使用全局 Chromium 实例渲染 PDF（线程安全）。

    通过 _pdf_render_lock 串行化访问，避免 Playwright sync API 的线程安全问题。
    每次创建独立的 browser context，渲染完毕后关闭；浏览器进程本身保持常驻。
    """
    if margin is None:
        margin = {'top': '2cm', 'right': '2cm', 'bottom': '2cm', 'left': '2cm'}
    with _pdf_render_lock:
        browser = _get_pw_browser()
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(f'file://{html_path}')
            page.wait_for_load_state('networkidle')
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=5000)
                except Exception:
                    pass
            if extra_wait_ms > 0:
                page.wait_for_timeout(extra_wait_ms)
            page.pdf(
                path=pdf_path,
                format='A4',
                margin=margin,
                print_background=True
            )
        finally:
            context.close()

# === Markdown转PDF API ===
@app.route('/api/md2pdf', methods=['POST'])
def api_md2pdf():
    data = request.json or {}
    markdown_content = data.get('content', '')
    if not markdown_content:
        return jsonify({'error': '内容不能为空'}), 400

    try:
        import markdown
        html_content = markdown.markdown(
            markdown_content,
            extensions=['extra', 'codehilite', 'tables', 'fenced_code']
        )

        import tempfile as tf

        with tf.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
            f.write(f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; padding: 40px; line-height: 1.8; }}
        h1, h2, h3 {{ margin-top: 1.5em; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px 12px; }}
        th {{ background: #f5f5f7; }}
        pre {{ background: #f5f5f7; padding: 16px; border-radius: 8px; overflow-x: auto; }}
        code {{ font-family: "SF Mono", Monaco, Consolas, monospace; }}
        blockquote {{ border-left: 4px solid #0071e3; margin: 1em 0; padding: 0.5em 1em; background: #f9f9f9; }}
    </style>
</head>
<body>{html_content}</body>
</html>
''')
            html_path = f.name

        pdf_path = os.path.join(app.config['PDF_FOLDER'], f"md2pdf_{int(time.time())}.pdf")

        _render_pdf(html_path, pdf_path)

        return jsonify({'filename': os.path.basename(pdf_path)})
    except Exception as e:
        logger.error(f"PDF生成失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


# === PDF快转 - 预览API ===
@app.route('/preview', methods=['POST'])
def api_preview():
    data = request.json or {}
    markdown_content = data.get('content', '')
    watermark = data.get('watermark', '')

    if not markdown_content:
        return jsonify({'html': ''})

    try:
        import markdown
        html_content = markdown.markdown(
            markdown_content,
            extensions=['extra', 'codehilite', 'tables', 'fenced_code']
        )
        
        # 如果有水印，添加水印样式
        if watermark:
            html_content += f'''
            <div style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;opacity:0.035;font-size:70px;font-weight:600;color:#0071e3;text-align:center;display:flex;align-items:center;justify-content:center;transform:rotate(-15deg);">
                {watermark}
            </div>
            '''
        
        return jsonify({'html': html_content})
    except Exception as e:
        logger.error(f"预览失败: {traceback.format_exc()}")
        return jsonify({'html': '', 'error': str(e)}), 500


# === PDF快转 - 转换API ===
@app.route('/convert', methods=['POST'])
def api_convert():
    data = request.json or {}
    markdown_content = data.get('content', '')
    watermark = data.get('watermark', '')
    filename = data.get('filename', '')

    if not markdown_content:
        return jsonify({'error': '内容不能为空'}), 400

    try:
        import markdown
        html_content = markdown.markdown(
            markdown_content,
            extensions=['extra', 'codehilite', 'tables', 'fenced_code']
        )

        import tempfile as tf

        # 添加水印
        watermark_html = ''
        if watermark:
            watermark_html = f'''
            <div style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;opacity:0.035;font-size:70px;font-weight:600;color:#0071e3;text-align:center;display:flex;align-items:center;justify-content:center;transform:rotate(-15deg);">
                {watermark}
            </div>
            '''

        with tf.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
            f.write(f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif; padding: 40px; line-height: 1.8; }}
        h1, h2, h3 {{ margin-top: 1.5em; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px 12px; }}
        th {{ background: #f5f5f7; }}
        pre {{ background: #f5f5f7; padding: 16px; border-radius: 8px; overflow-x: auto; }}
        code {{ font-family: "SF Mono", Monaco, Consolas, monospace; }}
        blockquote {{ border-left: 4px solid #0071e3; margin: 1em 0; padding: 0.5em 1em; background: #f9f9f9; }}
    </style>
</head>
<body>
{html_content}
{watermark_html}
</body>
</html>
''')
            html_path = f.name

        if filename:
            safe_filename = re.sub(r'[^\w\s-]', '', filename).strip() or 'document'
            pdf_filename = f"{safe_filename}_{int(time.time())}.pdf"
        else:
            pdf_filename = f"md2pdf_{int(time.time())}.pdf"

        pdf_path = os.path.join(app.config['PDF_FOLDER'], pdf_filename)

        # 后台渲染 PDF（避免同步请求超过 Railway 5 分钟超时）
        task_id = hashlib.md5(f"convert_{time.time()}".encode()).hexdigest()[:16]
        task_data = {
            'status': 'processing',
            'result': None,
            'error': None,
            'created_at': time.time()
        }
        _background_tasks[task_id] = task_data
        _save_task_meta(task_id, task_data)

        def _do_convert_pdf():
            try:
                _render_pdf(html_path, pdf_path)
                _background_tasks[task_id]['result'] = {'filename': pdf_filename}
                _background_tasks[task_id]['status'] = 'done'
                _save_task_meta(task_id, _background_tasks[task_id])
            except Exception as e:
                error_detail = str(e) if str(e) else f'{type(e).__name__}'
                logger.error(f"PDF转换失败: {traceback.format_exc()}")
                _background_tasks[task_id]['error'] = error_detail
                _background_tasks[task_id]['status'] = 'error'
                _save_task_meta(task_id, _background_tasks[task_id])

        thread = threading.Thread(target=_do_convert_pdf, daemon=True)
        thread.start()

        return jsonify({'status': 'success', 'data': {'task_id': task_id}})
    except Exception as e:
        logger.error(f"PDF生成失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


# === PDF快转 - Word上传转换API ===
@app.route('/upload', methods=['POST'])
def api_upload():
    if 'file' not in request.files:
        return jsonify({'error': '请选择文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '请选择文件'}), 400

    watermark = request.form.get('watermark', '')
    orig_name = os.path.splitext(file.filename)[0]

    if not file.filename.lower().endswith('.docx'):
        return jsonify({'error': '只支持Word文件(.docx)'}), 400

    try:
        file_id = hashlib.md5(f"{time.time()}_{file.filename}".encode()).hexdigest()[:16]
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"word_{file_id}.docx")
        file.save(file_path)

        # 使用python-docx2pdf或其他方式转换
        from docx2pdf import convert
        pdf_filename = f"{orig_name}_{int(time.time())}.pdf"
        pdf_path = os.path.join(app.config['PDF_FOLDER'], pdf_filename)

        convert(file_path, pdf_path)

        # 如果有水印，添加水印
        if watermark:
            # 对于Word转PDF，水印已在PDF快转页面的前端添加
            pass

        return jsonify({
            'filename': pdf_filename,
            'original_name': orig_name
        })
    except ImportError:
        # 如果没有docx2pdf库，尝试使用其他方法
        try:
            # 使用docx库读取并转换
            from docx import Document

            doc = Document(file_path)
            html_content = ''
            for para in doc.paragraphs:
                html_content += f'<p>{para.text}</p>'
            
            # 简单的表格处理
            for table in doc.tables:
                html_content += '<table border="1">'
                for row in table.rows:
                    html_content += '<tr>'
                    for cell in row.cells:
                        html_content += f'<td>{cell.text}</td>'
                    html_content += '</tr>'
                html_content += '</table>'
            
            watermark_html = ''
            if watermark:
                watermark_html = f'''
                <div style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;opacity:0.035;font-size:70px;font-weight:600;color:#0071e3;text-align:center;display:flex;align-items:center;justify-content:center;transform:rotate(-15deg);">
                    {watermark}
                </div>
                '''

            import tempfile as tf
            with tf.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
                f.write(f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif; padding: 40px; line-height: 1.8; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
        td {{ border: 1px solid #ddd; padding: 8px 12px; }}
    </style>
</head>
<body>
{html_content}
{watermark_html}
</body>
</html>
''')
                html_path = f.name

            pdf_filename = f"{orig_name}_{int(time.time())}.pdf"
            pdf_path = os.path.join(app.config['PDF_FOLDER'], pdf_filename)

            _render_pdf(html_path, pdf_path)

            return jsonify({
                'filename': pdf_filename,
                'original_name': orig_name
            })
        except Exception as e2:
            logger.error(f"Word转PDF失败: {traceback.format_exc()}")
            return jsonify({'error': f'Word转PDF失败: {str(e2)}'}), 500
    except Exception as e:
        logger.error(f"Word上传失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


# === Excel 解析路由 (for md2pdf tool) ===
@app.route('/excel-parse', methods=['POST'])
def api_excel_parse():
    if 'file' not in request.files:
        return jsonify({'error': '请选择文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '请选择文件'}), 400

    filename_lower = file.filename.lower()
    if not (filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls')):
        return jsonify({'error': '只支持Excel文件(.xlsx, .xls)'}), 400

    try:
        file_id = hashlib.md5(f"{time.time()}_{file.filename}".encode()).hexdigest()[:16]
        orig_ext = os.path.splitext(file.filename)[1].lower()
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"excel_parse_{file_id}{orig_ext}")
        file.save(file_path)

        reader = ExcelReader(file_path)
        reader.open()
        sheet_names = reader.get_sheet_names()
        
        sheets_data = []
        for sheet_name in sheet_names:
            try:
                rows = reader.get_sheet_data(sheet_name)
                if not rows:
                    sheets_data.append({
                        'name': sheet_name,
                        'row_count': 0,
                        'column_count': 0,
                        'headers': [],
                        'data_preview': [],
                        'rows': [],
                        'summary': '空工作表',
                        'categories': {}
                    })
                    continue
                
                headers = [str(c).strip() if c else '' for c in rows[0]]
                data_rows = rows[1:] if len(rows) > 1 else []
                col_count = len(headers)
                row_count = len(data_rows)
                
                # 生成数据预览（前5行）
                data_preview = []
                for row in data_rows[:5]:
                    cells = [str(c).strip() if c else '' for c in row]
                    # 对齐到headers长度
                    while len(cells) < col_count:
                        cells.append('')
                    data_preview.append(cells[:col_count])
                
                # 生成完整数据（用于PDF生成）
                all_rows = []
                for row in data_rows:
                    cells = [str(c).strip() if c else '' for c in row]
                    while len(cells) < col_count:
                        cells.append('')
                    all_rows.append(cells[:col_count])
                
                # 分析表头并分类
                categories = _categorize_headers(headers)
                
                # 生成摘要
                non_empty_headers = [h for h in headers if h]
                summary_parts = []
                if row_count > 0:
                    summary_parts.append(f'{row_count}行数据')
                if non_empty_headers:
                    summary_parts.append(f'{len(non_empty_headers)}列字段')
                
                # 检测日期列
                date_cols = [h for h in headers if any(kw in h.lower() for kw in ['date', '日期', '时间', 'created', 'updated', 'resolved'])]
                if date_cols:
                    summary_parts.append(f'含时间字段')
                
                # 检测数值列
                numeric_count = 0
                for col_idx in range(min(col_count, 20)):
                    for row in data_rows[:10]:
                        cells = [str(c).strip() if c else '' for c in row]
                        if col_idx < len(cells) and cells[col_idx]:
                            try:
                                float(cells[col_idx].replace(',', ''))
                                numeric_count += 1
                                break
                            except (ValueError, IndexError):
                                pass
                
                if numeric_count > col_count * 0.3:
                    summary_parts.append('数值型数据')
                
                # 检测是否有状态/分类字段
                status_cols = [h for h in headers if any(kw in h.lower() for kw in ['status', '状态', 'type', '类型', 'category', '分类'])]
                if status_cols:
                    summary_parts.append(f'含状态字段')
                
                summary = ' · '.join(summary_parts) if summary_parts else f'{row_count}行 x {col_count}列'
                
                # 保留完整列数，确保headers和rows对齐
                # 如果列数超过100，限制到100列以避免性能问题
                max_cols = min(col_count, 100)
                limited_headers = headers[:max_cols]
                limited_data_preview = [row[:max_cols] for row in data_preview]
                limited_rows = [row[:max_cols] for row in all_rows]
                
                sheets_data.append({
                    'name': sheet_name,
                    'row_count': row_count,
                    'column_count': max_cols,
                    'headers': limited_headers,
                    'data_preview': limited_data_preview,
                    'rows': limited_rows,
                    'summary': summary,
                    'categories': categories
                })
            except Exception as e:
                logger.warning(f"解析sheet {sheet_name} 失败: {e}")
                sheets_data.append({
                    'name': sheet_name,
                    'row_count': 0,
                    'column_count': 0,
                    'headers': [],
                    'data_preview': [],
                    'summary': f'解析失败: {str(e)}',
                    'categories': {}
                })
        
        reader.close()
        
        return jsonify({
            'status': 'success',
            'data': {
                'file_name': file.filename,
                'total_sheets': len(sheet_names),
                'sheets': sheets_data
            }
        })
    except Exception as e:
        logger.error(f"Excel解析失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


def _categorize_headers(headers):
    """将表头分类，返回类别到列名的映射"""
    categories = {}
    
    category_rules = {
        '基本信息': ['id', 'key', '编号', '名称', 'name', 'title', '标题', 'summary', '描述', 'description'],
        '状态信息': ['status', '状态', 'state', 'resolved', '解决', 'closed', '关闭'],
        '时间信息': ['date', '日期', '时间', 'created', 'updated', 'resolved', 'date', 'due'],
        '人员信息': ['assignee', 'developer', '负责人', '研发', 'reporter', '报告人', 'creator', '创建人'],
        '优先级': ['priority', '优先级', 'severity', '严重性', 'criticality'],
        '模块/组件': ['component', 'module', '模块', '组件', 'project', '项目'],
        '版本信息': ['version', '版本', 'fix version', 'affected version'],
        '数值指标': ['count', 'total', '金额', 'cost', 'price', 'rate', '比率', 'percentage'],
    }
    
    for header in headers:
        h_lower = header.lower().strip()
        if not h_lower:
            continue
        for category, keywords in category_rules.items():
            if any(kw in h_lower for kw in keywords):
                if category not in categories:
                    categories[category] = []
                categories[category].append({'name': header})
                break
    
    return categories


# === Excel 智能整理路由 ===
@app.route('/excel-organize', methods=['POST'])
def api_excel_organize():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': '请求数据格式错误'}), 400
    
    structured_data = data.get('structured_data', {})
    user_request = data.get('user_request', '')
    selected_sheets = data.get('selected_sheets', [])
    
    if not structured_data or not user_request:
        return jsonify({'error': '缺少必要参数'}), 400
    
    try:
        ai_config = get_ai_config()
        sheets = structured_data.get('sheets', [])
        
        # 过滤选中的sheets
        if selected_sheets:
            sheets = [s for s in sheets if s.get('name') in selected_sheets]
        
        if not sheets:
            return jsonify({'error': '没有选中的工作表数据'}), 400
        
        # 准备数据摘要供AI使用
        data_summary = _prepare_excel_summary(structured_data, sheets)
        
        if ai_config.get('enabled'):
            # 使用AI进行智能整理
            organized = _ai_organize_excel(data_summary, user_request, ai_config)
        else:
            # 本地整理
            organized = _local_organize_excel(data_summary, user_request)
        
        return jsonify({
            'status': 'success',
            'data': organized
        })
    except Exception as e:
        logger.error(f"Excel整理失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


def _prepare_excel_summary(structured_data, sheets):
    """准备Excel数据摘要"""
    summary = {
        'file_name': structured_data.get('file_name', ''),
        'sheets': []
    }
    
    for sheet in sheets:
        sheet_info = {
            'name': sheet.get('name', ''),
            'row_count': sheet.get('row_count', 0),
            'column_count': sheet.get('column_count', 0),
            'headers': sheet.get('headers', []),
            'data_preview': sheet.get('data_preview', [])[:10]
        }
        summary['sheets'].append(sheet_info)
    
    return summary


def _ai_organize_excel(data_summary, user_request, ai_config):
    """使用AI整理Excel数据"""
    try:
        import requests as req
        
        sheets_text = ''
        for s in data_summary.get('sheets', []):
            headers_str = ', '.join(s.get('headers', [])[:20])
            preview_str = ''
            for row in s.get('data_preview', [])[:3]:
                preview_str += ' | '.join([str(c)[:30] for c in row[:10]]) + '\n'
            sheets_text += f"\n工作表「{s['name']}」({s['row_count']}行x{s['column_count']}列):\n列: {headers_str}\n数据预览:\n{preview_str}"
        
        prompt = f"""你是一个数据分析师。请根据用户需求整理以下Excel数据。

文件: {data_summary.get('file_name', '')}
{sheets_text}

用户需求: {user_request}

请以JSON格式返回:
{{
    "summary": "数据总览总结（2-3句话）",
    "sections": [
        {{
            "title": "章节标题",
            "content": "详细内容，使用HTML格式，支持表格、列表等",
            "table": [["表头1", "表头2"], ["数据1", "数据2"]]  // 可选，用于生成表格
        }}
    ]
}}

要求:
1. 根据用户需求提取关键信息
2. 使用HTML格式化输出
3. 表格数据以二维数组形式提供
4. 内容要简洁明了"""
        
        response = req.post(
            f"{ai_config.get('base_url', 'https://dashscope.aliyuncs.com/api/v1')}/services/aigc/text-generation/generation",
            headers={
                'Authorization': f'Bearer {ai_config.get("api_key", "")}',
                'Content-Type': 'application/json'
            },
            json={
                'model': ai_config.get('model', 'qwen-turbo'),
                'input': {
                    'messages': [
                        {'role': 'system', 'content': '你是一个专业的数据分析师。'},
                        {'role': 'user', 'content': prompt}
                    ]
                },
                'parameters': {
                    'result_format': 'message',
                    'max_tokens': 2000
                }
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            output_text = result.get('output', {}).get('choices', [{}])[0].get('message', {}).get('content', '')
            
            # 尝试解析JSON
            try:
                # 清理可能的markdown代码块标记
                json_str = output_text
                if '```json' in json_str:
                    json_str = json_str.split('```json')[1].split('```')[0]
                elif '```' in json_str:
                    json_str = json_str.split('```')[1].split('```')[0]
                json_str = json_str.strip()
                
                parsed = json.loads(json_str)
                return _build_organized_result(parsed)
            except (json.JSONDecodeError, IndexError):
                # 如果JSON解析失败，使用文本
                return _build_text_result(output_text, user_request)
        else:
            logger.warning(f"AI请求失败: {response.status_code}")
            return _local_organize_excel(data_summary, user_request)
    except Exception as e:
        logger.warning(f"AI整理失败，使用本地整理: {e}")
        return _local_organize_excel(data_summary, user_request)


def _local_organize_excel(data_summary, user_request):
    """本地整理Excel数据"""
    sheets = data_summary.get('sheets', [])
    
    sections = []
    summary_text = f"文件「{data_summary.get('file_name', '')}」共包含 {len(sheets)} 个工作表。"
    
    for sheet in sheets:
        headers = sheet.get('headers', [])
        data_preview = sheet.get('data_preview', [])
        row_count = sheet.get('row_count', 0)
        
        # 构建表格数据
        table_data = [headers[:10]]  # 表头
        for row in data_preview[:10]:
            table_data.append([str(c)[:50] for c in row[:10]])
        
        # 分析数据特征
        numeric_cols = []
        for col_idx in range(min(len(headers), 10)):
            numeric_count = 0
            for row in data_preview:
                if col_idx < len(row) and row[col_idx]:
                    try:
                        float(str(row[col_idx]).replace(',', ''))
                        numeric_count += 1
                    except ValueError:
                        pass
            if numeric_count > len(data_preview) * 0.3:
                numeric_cols.append(headers[col_idx])
        
        # 生成章节
        section_content = f"<p>工作表「{sheet.get('name', '')}」包含 <strong>{row_count}</strong> 行数据，<strong>{len(headers)}</strong> 列字段。</p>"
        
        if numeric_cols:
            section_content += f"<p>主要数值字段: {', '.join(numeric_cols)}</p>"
        
        section_content += "<h4>数据预览</h4>"
        
        sections.append({
            'title': f"📋 {sheet.get('name', '')} ({row_count}行)",
            'content': section_content,
            'table': table_data
        })
    
    # 添加用户需求相关的总结
    sections.insert(0, {
        'title': '📊 数据总览',
        'content': f"<p>{summary_text}</p><p><strong>用户需求:</strong> {user_request}</p><p>请查看以下各工作表的详细数据预览。</p>",
        'table': []
    })
    
    return {
        'summary': summary_text,
        'sections': sections
    }


def _build_organized_result(parsed):
    """构建整理后的结果"""
    sections = parsed.get('sections', [])
    html_sections = []
    
    for section in sections:
        content = section.get('content', '')
        table = section.get('table', [])
        
        if table and len(table) > 1:
            # 生成HTML表格
            headers = table[0] if table else []
            rows = table[1:] if len(table) > 1 else []
            
            table_html = '<table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:13px;"><thead><tr>'
            for h in headers:
                table_html += f'<th style="background:#1d1d1f;color:white;padding:10px 12px;text-align:left;font-weight:600;font-size:12px;">{h}</th>'
            table_html += '</tr></thead><tbody>'
            
            for row in rows:
                table_html += '<tr>'
                for cell in row:
                    table_html += f'<td style="padding:8px 12px;border-bottom:1px solid #e5e5ea;">{cell}</td>'
                table_html += '</tr>'
            
            table_html += '</tbody></table>'
            content += table_html
        
        html_sections.append({
            'title': section.get('title', ''),
            'content': content,
            'table': table
        })
    
    return {
        'summary': parsed.get('summary', ''),
        'sections': html_sections
    }


def _build_text_result(text, user_request):
    """从纯文本构建结果"""
    sections = [{
        'title': '📊 AI分析结果',
        'content': text.replace('\n', '<br>'),
        'table': []
    }]
    return {
        'summary': f'根据需求「{user_request}」生成的分析结果',
        'sections': sections
    }


# === Excel 整理后PDF生成路由 ===
@app.route('/excel-organize-pdf', methods=['POST'])
def api_excel_organize_pdf():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': '请求数据格式错误'}), 400
    
    organized_data = data.get('organized_data', {})
    watermark = data.get('watermark', '')
    
    if not organized_data:
        return jsonify({'error': '缺少整理后的数据'}), 400
    
    try:
        sections = organized_data.get('sections', [])
        summary = organized_data.get('summary', '')
        user_request = organized_data.get('user_request', '')
        
        # 构建HTML内容
        html_content = _build_excel_report_html(sections, summary, user_request, watermark)

        import tempfile as tf
        
        with tf.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
            f.write(html_content)
            html_path = f.name
        
        pdf_filename = f"excel_report_{int(time.time())}.pdf"
        pdf_path = os.path.join(app.config['PDF_FOLDER'], pdf_filename)
        
        _render_pdf(html_path, pdf_path,
                    margin={'top': '20mm', 'bottom': '20mm', 'left': '15mm', 'right': '15mm'},
                    extra_wait_ms=1000)
        
        try:
            os.unlink(html_path)
        except Exception:
            pass
        
        return jsonify({
            'status': 'success',
            'filename': pdf_filename
        })
    except Exception as e:
        logger.error(f"Excel PDF生成失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


def _build_excel_report_html(sections, summary, user_request, watermark):
    """构建Excel报告HTML"""
    sections_html = ''
    for section in sections:
        title = section.get('title', '')
        content = section.get('content', '')
        
        sections_html += f'''
        <div style="margin-bottom:32px;">
            <h2 style="font-size:18px;font-weight:700;margin-bottom:16px;color:#1d1d1f;border-bottom:2px solid #0071e3;padding-bottom:8px;">{title}</h2>
            <div style="font-size:13px;line-height:1.8;color:#3c3c43;">{content}</div>
        </div>
        '''
    
    watermark_html = ''
    if watermark:
        watermark_html = f'''
        <div style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;opacity:0.035;font-size:70px;font-weight:600;color:#0071e3;text-align:center;display:flex;align-items:center;justify-content:center;transform:rotate(-15deg);">
            {watermark}
        </div>
        '''
    
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ 
            font-family: -apple-system, "SF Pro Display", "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif; 
            padding: 40px; 
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
        }}
        h1 {{ 
            font-size: 24px; 
            font-weight: 700; 
            margin-bottom: 8px;
            color: #1d1d1f;
        }}
        h2 {{ 
            margin-top: 1.5em;
        }}
        table {{ 
            border-collapse: collapse; 
            width: 100%; 
            margin: 1em 0;
            font-size: 13px;
        }}
        th {{ 
            background: #1d1d1f; 
            color: white; 
            padding: 10px 12px; 
            text-align: left;
            font-weight: 600;
            font-size: 12px;
        }}
        td {{ 
            border: 1px solid #e5e5ea; 
            padding: 8px 12px; 
        }}
        tr:nth-child(even) td {{
            background: #f5f5f7;
        }}
        .header {{
            text-align: center;
            margin-bottom: 32px;
            padding-bottom: 20px;
            border-bottom: 1px solid #e5e5ea;
        }}
        .summary-box {{
            background: linear-gradient(135deg, #f0f7ff, #e8f1ff);
            border: 1px solid #bae0ff;
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 24px;
            font-size: 13px;
            color: #3c3c43;
        }}
        .user-request {{
            font-size: 12px;
            color: #6e6e73;
            margin-top: 8px;
            font-style: italic;
        }}
    </style>
</head>
<body>
    {watermark_html}
    <div class="header">
        <h1>📊 数据分析报告</h1>
    </div>
    <div class="summary-box">
        <strong>📋 分析摘要:</strong> {summary}
        {f'<div class="user-request">💡 需求: {user_request}</div>' if user_request else ''}
    </div>
    {sections_html}
</body>
</html>'''


@app.route('/excel-pdf', methods=['POST'])
def api_excel_pdf():
    """PDF快转 - 根据结构化数据生成PDF"""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': '请求数据格式错误'}), 400
    
    structured_data = data.get('structured_data', {})
    selected_sheets = data.get('selected_sheets', [])
    watermark = data.get('watermark', '')
    custom_title = data.get('custom_title', '').strip()
    
    if not structured_data:
        return jsonify({'error': '缺少结构化数据'}), 400
    
    try:
        html_content = _build_excel_structured_report_html(structured_data, selected_sheets, watermark, custom_title)

        import tempfile as tf
        
        with tf.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
            f.write(html_content)
            html_path = f.name
        
        # 生成PDF文件名：如果有自定义标题，使用自定义标题作为文件名
        if custom_title:
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', custom_title)
            pdf_filename = f"{safe_title}_{int(time.time())}.pdf"
            download_name = f"{safe_title}.pdf"
        else:
            pdf_filename = f"excel_pdf_{int(time.time())}.pdf"
            download_name = pdf_filename
        pdf_path = os.path.join(app.config['PDF_FOLDER'], pdf_filename)

        _render_pdf(html_path, pdf_path,
                    margin={'top': '20mm', 'bottom': '20mm', 'left': '15mm', 'right': '15mm'},
                    extra_wait_ms=1500)
        
        try:
            os.unlink(html_path)
        except Exception:
            pass
        
        return jsonify({
            'status': 'success',
            'filename': pdf_filename,
            'download_name': download_name
        })
    except Exception as e:
        logger.error(f"Excel PDF生成失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


@app.route('/excel-select-pdf', methods=['POST'])
def api_excel_select_pdf():
    """PDF快转 - 根据选中数据生成PDF"""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': '请求数据格式错误'}), 400
    
    structured_data = data.get('structured_data', {})
    selected_data = data.get('selected_data', {})  # {sheetName: [rowIndices]}
    selected_columns = data.get('selected_columns', {})  # {sheetName: [colIndices]}
    watermark = data.get('watermark', '')
    custom_title = data.get('custom_title', '').strip()
    
    if not selected_data:
        return jsonify({'error': '缺少选中数据'}), 400
    
    try:
        html_content = _build_excel_selected_report_html(structured_data, selected_data, selected_columns, watermark, custom_title)

        import tempfile as tf
        
        with tf.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
            f.write(html_content)
            html_path = f.name
        
        # 生成PDF文件名：如果有自定义标题，使用自定义标题作为文件名
        if custom_title:
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', custom_title)
            pdf_filename = f"{safe_title}_{int(time.time())}.pdf"
            download_name = f"{safe_title}.pdf"
        else:
            pdf_filename = f"excel_select_pdf_{int(time.time())}.pdf"
            download_name = pdf_filename
        pdf_path = os.path.join(app.config['PDF_FOLDER'], pdf_filename)

        _render_pdf(html_path, pdf_path,
                    margin={'top': '20mm', 'bottom': '20mm', 'left': '15mm', 'right': '15mm'},
                    extra_wait_ms=1500)
        
        try:
            os.unlink(html_path)
        except Exception:
            pass
        
        return jsonify({
            'status': 'success',
            'filename': pdf_filename,
            'download_name': download_name
        })
    except Exception as e:
        logger.error(f"Excel select PDF生成失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


def _escape_html(text):
    """转义HTML特殊字符"""
    import html
    return html.escape(str(text)) if text else ''


def _build_excel_structured_report_html(structured_data, selected_sheets, watermark, custom_title=''):
    """构建结构化数据报告HTML - 支持数组格式"""
    watermark_html = ''
    if watermark:
        watermark_items = ''.join([
            f'<div style="position:absolute;left:{x}px;top:{y}px;transform:rotate(-30deg);font-size:12px;font-weight:400;color:#0071e3;white-space:nowrap;">{_escape_html(watermark)}</div>'
            for x in range(80, 1200, 200)
            for y in range(150, 1000, 200)
        ])
        watermark_html = f'''
        <div style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;opacity:0.08;overflow:hidden;">
            {watermark_items}
        </div>
        '''
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    title = _escape_html(custom_title) if custom_title else '📊 数据分析报告'
    
    # 获取工作表数据 - 支持数组格式 [{name, headers, rows}, ...]
    sheets_data = structured_data.get('sheets', []) if isinstance(structured_data, dict) else []
    
    # 构建工作表名称到数据的映射
    sheet_map = {}
    max_cols = 0
    for sheet in sheets_data:
        if isinstance(sheet, dict):
            name = sheet.get('name', '')
            if name:
                sheet_map[name] = sheet
                col_count = len(sheet.get('headers', []))
                if col_count > max_cols:
                    max_cols = col_count
    
    # 确定页面方向：列数超过15列使用横向打印
    use_landscape = max_cols > 15
    page_size = 'A4 landscape' if use_landscape else 'A4'
    
    # 确定要显示的工作表
    sheets_to_show = selected_sheets if selected_sheets else list(sheet_map.keys())
    
    # 处理选中的工作表数据
    sheets_html = ''
    for sheet_name in sheets_to_show:
        sheet_data = sheet_map.get(sheet_name, {})
        if not sheet_data:
            continue
        
        headers = sheet_data.get('headers', [])
        rows = sheet_data.get('rows', [])
        
        if not headers:
            continue
        
        # 如果没有 rows，使用 data_preview
        if not rows:
            rows = sheet_data.get('data_preview', [])
        
        if not rows:
            continue
        
        # 确保 headers 和 rows 对齐
        num_cols = len(headers)
        aligned_headers = [_escape_html(h) for h in headers]
        
        # 根据列数调整字体大小
        if num_cols > 50:
            font_size = '6px'
            padding = '2px 3px'
        elif num_cols > 30:
            font_size = '8px'
            padding = '3px 4px'
        elif num_cols > 15:
            font_size = '9px'
            padding = '4px 5px'
        else:
            font_size = '10px'
            padding = '5px 8px'
        
        # 生成表头
        header_html = ''.join([f'<th style="padding:{padding};font-size:{font_size};">{h}</th>' for h in aligned_headers])
        
        # 生成数据行（确保每行的列数与headers对齐）
        rows_html = ''
        display_rows = rows[:50]  # 最多显示50行
        for row in display_rows:
            # 对齐行数据到headers长度
            aligned_row = list(row[:num_cols]) + [''] * max(0, num_cols - len(row))
            cells = ''.join([f'<td style="border:1px solid #e5e5ea;padding:{padding};font-size:{font_size};">{_escape_html(cell)}</td>' for cell in aligned_row])
            rows_html += f'<tr>{cells}</tr>'
        
        total_rows = len(rows)
        sheets_html += f'''
        <div style="margin-bottom:20px;break-inside:avoid;">
            <h2 style="font-size:14px;font-weight:600;margin-bottom:10px;color:#1d1d1f;padding:6px 10px;background:#f5f5f7;border-radius:6px;border-left:3px solid #0071e3;">📋 {_escape_html(sheet_name)} ({num_cols}列)</h2>
            <div style="overflow-x:auto;border:1px solid #e5e5ea;border-radius:6px;">
                <table style="border-collapse:collapse;width:100%;">
                    <thead><tr style="background:#1d1d1f;color:white;">{header_html}</tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
            {f'<p style="font-size:9px;color:#6e6e73;margin-top:4px;text-align:right;">共 {total_rows} 行数据，仅显示前50行</p>' if total_rows > 50 else ''}
        </div>
        '''
    
    if not sheets_html:
        sheets_html = '<p style="text-align:center;color:#6e6e73;padding:40px;">暂无数据</p>'
    
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        @page {{ size: {page_size}; margin: 10mm 8mm; }}
        body {{
            font-family: -apple-system, "SF Pro Display", "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
            padding: 5px;
            line-height: 1.3;
            max-width: 100%;
            margin: 0 auto;
            color: #1d1d1f;
        }}
        table {{ border-collapse: collapse; width: 100%; margin: 0; }}
        th {{ background: #1d1d1f; color: white; text-align: left; font-weight: 600; }}
        td {{ border: 1px solid #e5e5ea; }}
        h1 {{ font-size: 20px; font-weight: 700; margin: 0 0 6px 0; color: #1d1d1f; }}
        h2 {{ font-size: 14px; font-weight: 600; margin-bottom: 10px; }}
        .header-box {{
            text-align:center;
            margin-bottom:16px;
            padding-bottom:12px;
            border-bottom:2px solid #e5e5ea;
        }}
        .meta-info {{
            font-size: 9px;
            color:#6e6e73;
            margin-top:4px;
        }}
    </style>
</head>
<body>
    {watermark_html}
    <div class="header-box">
        <h1>{title}</h1>
        <div class="meta-info">生成时间: {now}</div>
    </div>
    {sheets_html}
</body>
</html>'''


def _build_excel_selected_report_html(structured_data, selected_data, selected_columns, watermark, custom_title=''):
    """构建选中数据报告HTML - 根据选中的行列索引从原始数据中提取"""
    watermark_html = ''
    if watermark:
        watermark_items = ''.join([
            f'<div style="position:absolute;left:{x}px;top:{y}px;transform:rotate(-30deg);font-size:12px;font-weight:400;color:#0071e3;white-space:nowrap;">{_escape_html(watermark)}</div>'
            for x in range(80, 1200, 200)
            for y in range(150, 1000, 200)
        ])
        watermark_html = f'''
        <div style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;opacity:0.08;overflow:hidden;">
            {watermark_items}
        </div>
        '''
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    title = _escape_html(custom_title) if custom_title else '📊 数据分析报告'
    
    # 获取原始工作表数据
    sheets_data = structured_data.get('sheets', []) if isinstance(structured_data, dict) else []
    
    # 构建工作表名称到数据的映射
    sheet_map = {}
    max_cols = 0
    for sheet in sheets_data:
        if isinstance(sheet, dict):
            name = sheet.get('name', '')
            if name:
                sheet_map[name] = sheet
    
    # 计算最大列数（用于决定页面方向）
    for sheet_name, row_indices in selected_data.items():
        col_indices = selected_columns.get(sheet_name, [])
        if len(col_indices) > max_cols:
            max_cols = len(col_indices)
    
    # 确定页面方向：列数超过15列使用横向打印
    use_landscape = max_cols > 15
    page_size = 'A4 landscape' if use_landscape else 'A4'
    
    # selected_data: {sheetName: [rowIndices]} 行索引
    # selected_columns: {sheetName: [colIndices]} 列索引
    
    tables_html = ''
    for sheet_name, row_indices in selected_data.items():
        sheet_data = sheet_map.get(sheet_name, {})
        if not sheet_data:
            continue
        
        headers = sheet_data.get('headers', [])
        rows = sheet_data.get('rows', [])
        
        # 如果没有 rows，使用 data_preview
        if not rows:
            rows = sheet_data.get('data_preview', [])
        
        if not headers or not rows:
            continue
        
        # 获取选中的列索引
        col_indices = selected_columns.get(sheet_name, list(range(len(headers))))
        
        # 过滤列（带HTML转义）
        filtered_headers = [_escape_html(headers[i]) if i < len(headers) else '' for i in col_indices]
        
        # 过滤行（确保对齐）
        num_filtered_cols = len(filtered_headers)
        filtered_rows = []
        for row_idx in row_indices:
            if row_idx < len(rows):
                row = rows[row_idx]
                filtered_row = [_escape_html(row[i]) if i < len(row) else '' for i in col_indices]
                # 对齐到列数
                filtered_row = filtered_row[:num_filtered_cols] + [''] * max(0, num_filtered_cols - len(filtered_row))
                filtered_rows.append(filtered_row)
        
        if not filtered_rows:
            continue
        
        # 根据列数调整字体大小
        if num_filtered_cols > 50:
            font_size = '6px'
            padding = '2px 3px'
        elif num_filtered_cols > 30:
            font_size = '8px'
            padding = '3px 4px'
        elif num_filtered_cols > 15:
            font_size = '9px'
            padding = '4px 5px'
        else:
            font_size = '10px'
            padding = '5px 8px'
        
        # 生成表格
        header_html = ''.join([f'<th style="padding:{padding};font-size:{font_size};">{h}</th>' for h in filtered_headers])
        rows_html = ''
        display_rows = filtered_rows[:50]
        for row in display_rows:
            cells = ''.join([f'<td style="border:1px solid #e5e5ea;padding:{padding};font-size:{font_size};">{c}</td>' for c in row])
            rows_html += f'<tr>{cells}</tr>'
        
        total_filtered = len(filtered_rows)
        tables_html += f'''
        <div style="margin-bottom:20px;break-inside:avoid;">
            <h2 style="font-size:14px;font-weight:600;margin-bottom:10px;color:#1d1d1f;padding:6px 10px;background:#f5f5f7;border-radius:6px;border-left:3px solid #0071e3;">📋 {_escape_html(sheet_name)} ({num_filtered_cols}列)</h2>
            <div style="overflow-x:auto;border:1px solid #e5e5ea;border-radius:6px;">
                <table style="border-collapse:collapse;width:100%;">
                    <thead><tr style="background:#1d1d1f;color:white;">{header_html}</tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
            {f'<p style="font-size:9px;color:#6e6e73;margin-top:4px;text-align:right;">共 {total_filtered} 行数据，仅显示前50行</p>' if total_filtered > 50 else ''}
        </div>
        '''
    
    if not tables_html:
        tables_html = '<p style="text-align:center;color:#6e6e73;padding:40px;">暂无选中数据</p>'
    
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        @page {{ size: {page_size}; margin: 10mm 8mm; }}
        body {{
            font-family: -apple-system, "SF Pro Display", "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
            padding: 5px;
            line-height: 1.3;
            max-width: 100%;
            margin: 0 auto;
            color: #1d1d1f;
        }}
        table {{ border-collapse: collapse; width: 100%; margin: 0; }}
        th {{ background: #1d1d1f; color: white; text-align: left; font-weight: 600; }}
        td {{ border: 1px solid #e5e5ea; }}
        h1 {{ font-size: 20px; font-weight: 700; margin: 0 0 6px 0; color: #1d1d1f; }}
        h2 {{ font-size: 14px; font-weight: 600; margin-bottom: 10px; }}
        .header-box {{
            text-align:center;
            margin-bottom:16px;
            padding-bottom:12px;
            border-bottom:2px solid #e5e5ea;
        }}
        .meta-info {{
            font-size: 9px;
            color:#6e6e73;
            margin-top:4px;
        }}
    </style>
</head>
<body>
    {watermark_html}
    <div class="header-box">
        <h1>{title}</h1>
        <div class="meta-info">生成时间: {now}</div>
    </div>
    {tables_html}
</body>
</html>'''


# === Excel分析PDF生成 API ===
@app.route('/api/excel-analyze-pdf', methods=['POST'])
def api_excel_analyze_pdf():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': '请求数据格式错误'}), 400

    analysis_data = data.get('analysis_data', {})
    watermark = data.get('watermark', '')
    custom_title = data.get('custom_title', '').strip()
    file_name = data.get('file_name', '')

    if not analysis_data:
        return jsonify({'error': '缺少分析数据'}), 400

    try:
        html_content = _build_cr_analysis_report_html(analysis_data, watermark, file_name, custom_title)

        import tempfile as tf

        with tf.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
            f.write(html_content)
            html_path = f.name

        # 生成PDF文件名：如果有自定义标题，使用自定义标题作为文件名
        if custom_title:
            # 清理文件名中的非法字符
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', custom_title)
            pdf_filename = f"{safe_title}_{datetime.now(_CST).strftime('%Y%m%d_%H%M%S')}.pdf"
            download_name = f"{safe_title}.pdf"
        else:
            pdf_filename = f"cr_analysis_{int(time.time())}.pdf"
            download_name = pdf_filename
        
        pdf_path = os.path.join(app.config['PDF_FOLDER'], pdf_filename)

        _render_pdf(html_path, pdf_path,
                    margin={'top': '20mm', 'bottom': '20mm', 'left': '15mm', 'right': '15mm'},
                    extra_wait_ms=3000, wait_selector='canvas')

        try:
            os.unlink(html_path)
        except Exception:
            pass

        return jsonify({
            'status': 'success',
            'filename': pdf_filename,
            'download_name': download_name
        })
    except Exception as e:
        logger.error(f"CR分析PDF生成失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


def _build_cr_analysis_report_html(data, watermark, file_name, custom_title=''):
    """构建CR问题分析报告HTML（含Chart.js图表）"""
    summary = data.get('summary', {})
    module_stats = data.get('module_stats', {})
    dev_stats = data.get('dev_stats', {})
    daily_stats = data.get('daily_stats', [])
    suggestions = data.get('suggestions', [])
    resolved_unverified = data.get('resolved_unverified', [])
    stability_stats = data.get('stability_stats', {})

    # 水印 - 小水印，密度适中
    watermark_html = ''
    if watermark:
        # 生成多个水印，平铺在页面上
        watermark_items = ''.join([
            f'<div style="position:absolute;left:{x}px;top:{y}px;transform:rotate(-30deg);font-size:16px;font-weight:500;color:#0071e3;white-space:nowrap;">{watermark}</div>'
            for x in range(50, 600, 120)
            for y in range(80, 800, 120)
        ])
        watermark_html = f'''
        <div style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;opacity:0.12;overflow:hidden;">
            {watermark_items}
        </div>
        '''

    # 概览卡片
    total = summary.get('total_issues', 0)
    resolved = summary.get('total_resolved', 0)
    unresolved = summary.get('total_unresolved', 0)
    rate = summary.get('resolution_rate', 0)

    overview_html = f'''
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px;">
        <div style="background:linear-gradient(135deg,#f0f7ff,#e8f1ff);border-radius:12px;padding:20px;text-align:center;border:1px solid #bae0ff;">
            <div style="font-size:13px;color:#6e6e73;margin-bottom:8px;">问题总数</div>
            <div style="font-size:32px;font-weight:700;color:#0071e3;">{total}</div>
        </div>
        <div style="background:linear-gradient(135deg,#e8f8f0,#d4f0e0);border-radius:12px;padding:20px;text-align:center;border:1px solid #a8e0b8;">
            <div style="font-size:13px;color:#6e6e73;margin-bottom:8px;">已解决</div>
            <div style="font-size:32px;font-weight:700;color:#34c759;">{resolved}</div>
        </div>
        <div style="background:linear-gradient(135deg,#fff5e8,#ffe8d4);border-radius:12px;padding:20px;text-align:center;border:1px solid #ffcc80;">
            <div style="font-size:13px;color:#6e6e73;margin-bottom:8px;">未解决</div>
            <div style="font-size:32px;font-weight:700;color:#ff9500;">{unresolved}</div>
        </div>
        <div style="background:linear-gradient(135deg,#f0e8ff,#e0d4ff);border-radius:12px;padding:20px;text-align:center;border:1px solid #b8a8ff;">
            <div style="font-size:13px;color:#6e6e73;margin-bottom:8px;">解决率</div>
            <div style="font-size:32px;font-weight:700;color:#5856d6;">{rate}%</div>
        </div>
    </div>
    '''

    # 智能建议（放在最前面）
    suggestions_html = ''
    if suggestions:
        sug_cards = ''
        for sug in suggestions:
            level = sug.get('level', 'info')
            icon = {'critical': '🚨', 'warning': '⚠️', 'info': '💡', 'success': '✅'}.get(level, '💡')
            color_map = {'critical': '#ff3b30', 'warning': '#ff9500', 'info': '#0071e3', 'success': '#34c759'}
            color = color_map.get(level, '#0071e3')
            title = sug.get('title', '')
            detail = sug.get('detail', '')
            desc = sug.get('desc', '')
            sug_cards += f'''
            <div style="background:white;border-radius:10px;padding:16px;margin-bottom:12px;border-left:4px solid {color};box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                <div style="font-size:14px;font-weight:600;color:{color};margin-bottom:6px;display:flex;align-items:center;gap:6px;">
                    <span>{icon}</span> {title}
                </div>
                <div style="font-size:12px;color:#3c3c43;line-height:1.6;">{detail or desc}</div>
            </div>
            '''
        suggestions_html = f'''
        <div style="margin-bottom:28px;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #34c759;">💡 智能分析建议</h2>
            {sug_cards}
        </div>
        '''

    # 严重程度分布（卡片样式）
    sev_html = ''
    if summary:
        total_issues = summary.get('total_issues', 1)
        sev_config = [
            ('blocker', 'Blocker', '#ff3b30'),
            ('critical', 'Critical', '#ff6b35'),
            ('major', 'Major', '#ff9500'),
            ('minor', 'Minor', '#34c759'),
            ('trivial', 'Trivial', '#5ac8fa'),
        ]
        # 计算B+C解决率
        blocker_total = summary.get('blocker_total', 0)
        critical_total = summary.get('critical_total', 0)
        blocker_resolved = summary.get('blocker_resolved', 0)
        critical_resolved = summary.get('critical_resolved', 0)
        bc_total = blocker_total + critical_total
        bc_resolved = blocker_resolved + critical_resolved
        bc_rate = round(bc_resolved / bc_total * 100, 1) if bc_total > 0 else 0
        
        sev_cards = ''
        for sev_name, label, color in sev_config:
            count = summary.get(f'{sev_name}_total', 0)
            pct = round(count / total_issues * 100, 1) if total_issues > 0 else 0
            sev_cards += f'''
            <div style="background:linear-gradient(135deg,{color}10,{color}20);border-radius:12px;padding:16px;text-align:center;border:1px solid {color}30;">
                <div style="font-size:28px;font-weight:700;color:{color};">{count}</div>
                <div style="font-size:12px;color:#3c3c43;margin-top:4px;">{label} {pct}%</div>
            </div>
            '''
        
        # B+C解决率卡片
        sev_cards += f'''
        <div style="background:linear-gradient(135deg,#5856d610,#5856d620);border-radius:12px;padding:16px;text-align:center;border:1px solid #5856d630;">
            <div style="font-size:28px;font-weight:700;color:#5856d6;">{bc_rate}%</div>
            <div style="font-size:12px;color:#3c3c43;margin-top:4px;">B+C解决率 ({bc_resolved})</div>
        </div>
        '''
        
        sev_html = f'''
        <div style="margin-bottom:28px;break-inside:avoid;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #0071e3;">🔴 严重程度分布</h2>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
                {sev_cards}
            </div>
        </div>
        '''

    # 模块分布（含饼图）
    module_html = ''
    module_chart_js = ''
    if module_stats:
        sorted_modules = sorted(module_stats.items(), key=lambda x: x[1]['total'], reverse=True)[:10]
        module_labels = json.dumps([mod for mod, _ in sorted_modules], ensure_ascii=False)
        module_data = json.dumps([stats['total'] for _, stats in sorted_modules])
        
        module_html = f'''
        <div style="margin-bottom:28px;break-inside:avoid;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #0071e3;">📦 模块问题分布</h2>
            <div style="background:linear-gradient(135deg,#fff,#f8f9fa);border-radius:16px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);border:1px solid #e5e5ea;">
                <canvas id="modulePieChart" style="max-height:300px;"></canvas>
            </div>
        </div>
        '''
        
        module_chart_js = f'''
        // 模块饼图
        (function() {{
            const ctx = document.getElementById('modulePieChart');
            if (!ctx) return;
            new Chart(ctx, {{
                type: 'doughnut',
                data: {{
                    labels: {module_labels},
                    datasets: [{{
                        data: {module_data},
                        backgroundColor: ['#0071e3','#34c759','#ff9500','#ff3b30','#af52de','#5856d6','#ff2d55','#5ac8fa','#4cd964','#ffcc00'],
                        borderWidth: 3,
                        borderColor: '#fff',
                        hoverOffset: 8
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    cutout: '45%',
                    plugins: {{
                        legend: {{
                            position: 'right',
                            labels: {{ font: {{ size: 11, family: '-apple-system, PingFang SC' }}, padding: 10, usePointStyle: true, pointStyle: 'circle' }}
                        }},
                        tooltip: {{
                            backgroundColor: 'rgba(29,29,31,0.9)',
                            titleFont: {{ size: 13, weight: '600' }},
                            bodyFont: {{ size: 12 }},
                            padding: 12,
                            cornerRadius: 8
                        }}
                    }}
                }}
            }});
        }})();
        '''

    # 每日趋势（含折线图+详细表格）
    daily_html = ''
    daily_chart_js = ''
    if daily_stats:
        display_data = daily_stats[-14:] if len(daily_stats) > 14 else daily_stats
        dates = json.dumps([d.get('date', '')[-5:] for d in display_data])
        new_counts = json.dumps([d.get('new_count', d.get('new', 0)) for d in display_data])
        resolved_counts = json.dumps([d.get('resolved_count', d.get('resolved', 0)) for d in display_data])
        
        # 计算最大值用于条形图缩放
        max_new = max((d.get('new_count', d.get('new', 0)) for d in daily_stats), default=0)
        max_resolved = max((d.get('resolved_count', d.get('resolved', 0)) for d in daily_stats), default=0)
        max_val = max(max_new, max_resolved, 1)
        
        # 表格数据 - 保持在线版UI样式，取最近30天
        display_table_daily = daily_stats[-30:] if len(daily_stats) > 30 else daily_stats
        daily_rows = ''
        for item in display_table_daily:
            d = item.get('date', '')
            new_count = item.get('new_count', item.get('new', 0))
            resolved_count = item.get('resolved_count', item.get('resolved', 0))
            net = new_count - resolved_count
            new_width = round(new_count / max_val * 100, 1) if max_val > 0 else 0
            resolved_width = round(resolved_count / max_val * 100, 1) if max_val > 0 else 0
            net_color = '#ff3b30' if net > 0 else ('#34c759' if net < 0 else '#8e8e93')
            net_text = f'+{net}' if net >= 0 else str(net)
            
            # 格式化日期 MM-DD
            date_short = d[5:] if len(d) >= 10 else d
            
            daily_rows += f'''
            <tr>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;white-space:nowrap;font-weight:500;">{date_short}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;text-align:center;color:#ff3b30;font-weight:600;">+{new_count}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;min-width:120px;">
                    <div style="background:#f0f0f3;border-radius:4px;height:10px;overflow:hidden;">
                        <div style="background:linear-gradient(90deg,#ff3b30,#ff9500);height:100%;width:{new_width}%;border-radius:4px;"></div>
                    </div>
                </td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;text-align:center;color:#34c759;font-weight:600;">-{resolved_count}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;min-width:120px;">
                    <div style="background:#f0f0f3;border-radius:4px;height:10px;overflow:hidden;">
                        <div style="background:linear-gradient(90deg,#34c759,#5ac8fa);height:100%;width:{resolved_width}%;border-radius:4px;"></div>
                    </div>
                </td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;text-align:center;color:{net_color};font-weight:600;">{net_text}</td>
            </tr>
            '''
        
        daily_html = f'''
        <div style="margin-bottom:28px;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #0071e3;">📅 每日问题趋势 (共 {len(daily_stats)} 天)</h2>
            <div style="background:linear-gradient(135deg,#fff,#f8f9fa);border-radius:16px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);border:1px solid #e5e5ea;margin-bottom:20px;">
                <canvas id="dailyLineChart" style="max-height:300px;"></canvas>
            </div>
            <div style="margin-bottom:12px;padding:10px 14px;background:#f0f7ff;border-radius:8px;font-size:12px;display:flex;gap:20px;align-items:center;">
                <div><span style="display:inline-block;width:10px;height:10px;background:linear-gradient(90deg,#ff3b30,#ff9500);border-radius:2px;margin-right:6px;"></span>新增问题 (最高 {max_new})</div>
                <div><span style="display:inline-block;width:10px;height:10px;background:linear-gradient(90deg,#34c759,#5ac8fa);border-radius:2px;margin-right:6px;"></span>解决问题 (最高 {max_resolved})</div>
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:11px;">
                <thead>
                    <tr style="background:#1d1d1f;color:white;">
                        <th style="padding:6px 8px;text-align:left;width:70px;">日期</th>
                        <th style="padding:6px 8px;text-align:center;width:50px;">新增</th>
                        <th style="padding:6px 8px;text-align:left;width:120px;">新增趋势</th>
                        <th style="padding:6px 8px;text-align:center;width:50px;">解决</th>
                        <th style="padding:6px 8px;text-align:left;width:120px;">解决趋势</th>
                        <th style="padding:6px 8px;text-align:center;width:50px;">净增</th>
                    </tr>
                </thead>
                <tbody>{daily_rows}</tbody>
            </table>
        </div>
        '''
        
        daily_chart_js = f'''
        // 每日趋势折线图
        (function() {{
            const ctx = document.getElementById('dailyLineChart');
            if (!ctx) return;
            new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: {dates},
                    datasets: [{{
                        label: '新增问题',
                        data: {new_counts},
                        borderColor: '#ff3b30',
                        backgroundColor: 'rgba(255, 59, 48, 0.08)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#ff3b30',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        borderWidth: 2.5
                    }}, {{
                        label: '解决问题',
                        data: {resolved_counts},
                        borderColor: '#34c759',
                        backgroundColor: 'rgba(52, 199, 89, 0.08)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#34c759',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        borderWidth: 2.5
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    interaction: {{ mode: 'index', intersect: false }},
                    plugins: {{
                        legend: {{
                            position: 'top',
                            labels: {{ font: {{ size: 11, family: '-apple-system, PingFang SC' }}, padding: 12, usePointStyle: true, pointStyle: 'circle' }}
                        }},
                        tooltip: {{
                            backgroundColor: 'rgba(29,29,31,0.9)',
                            titleFont: {{ size: 13, weight: '600' }},
                            bodyFont: {{ size: 12 }},
                            padding: 12,
                            cornerRadius: 8
                        }}
                    }},
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            grid: {{ color: 'rgba(0,0,0,0.04)' }},
                            ticks: {{ font: {{ size: 10 }} }}
                        }},
                        x: {{
                            grid: {{ display: false }},
                            ticks: {{ font: {{ size: 10 }} }}
                        }}
                    }}
                }}
            }});
        }})();
        '''

    # 研发分布
    dev_html = ''
    if dev_stats:
        dev_rows = ''
        sorted_devs = sorted(dev_stats.items(), key=lambda x: x[1]['total'], reverse=True)[:20]
        for dev, stats in sorted_devs:
            dev_total = stats['total']
            dev_resolved = stats['resolved']
            dev_unresolved = stats['unresolved']
            dev_rate = round(dev_resolved / dev_total * 100, 1) if dev_total > 0 else 0
            dev_rows += f'''
            <tr>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;">{dev}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;">{dev_total}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;color:#34c759;">{dev_resolved}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;color:#ff9500;">{dev_unresolved}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;font-weight:600;">{dev_rate}%</td>
            </tr>
            '''
        dev_html = f'''
        <div style="margin-bottom:28px;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #0071e3;">👥 研发问题分布 (Top {len(sorted_devs)})</h2>
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead>
                    <tr style="background:#1d1d1f;color:white;">
                        <th style="padding:10px 12px;text-align:left;">研发</th>
                        <th style="padding:10px 12px;text-align:center;">总数</th>
                        <th style="padding:10px 12px;text-align:center;">已解决</th>
                        <th style="padding:10px 12px;text-align:center;">未解决</th>
                        <th style="padding:10px 12px;text-align:center;">解决率</th>
                    </tr>
                </thead>
                <tbody>{dev_rows}</tbody>
            </table>
        </div>
        '''

    # 稳定性分析
    stability_html = ''
    if stability_stats:
        stab_rows = ''
        stab_total = sum(s['total'] for s in stability_stats.values())
        stab_resolved = sum(s['resolved'] for s in stability_stats.values())
        stab_unresolved = sum(s['unresolved'] for s in stability_stats.values())
        stab_rate = round(stab_resolved / stab_total * 100, 1) if stab_total > 0 else 0
        for mod, stats in stability_stats.items():
            stab_rows += f'''
            <tr>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;">{mod}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;">{stats['total']}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;color:#34c759;">{stats['resolved']}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;color:#ff9500;">{stats['unresolved']}</td>
            </tr>
            '''
        stability_html = f'''
        <div style="margin-bottom:28px;background:linear-gradient(135deg,#fff,#f8f9fa);border-radius:12px;padding:20px;border:1px solid #bae0ff;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:12px;color:#1d1d1f;">🛡️ 稳定性模块分析</h2>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;">
                <div style="background:white;border-radius:8px;padding:12px;text-align:center;border:1px solid #e5e5ea;">
                    <div style="font-size:11px;color:#6e6e73;">模块数</div>
                    <div style="font-size:22px;font-weight:700;color:#0071e3;">{len(stability_stats)}</div>
                </div>
                <div style="background:white;border-radius:8px;padding:12px;text-align:center;border:1px solid #e5e5ea;">
                    <div style="font-size:11px;color:#6e6e73;">问题总数</div>
                    <div style="font-size:22px;font-weight:700;color:#ff3b30;">{stab_total}</div>
                </div>
                <div style="background:white;border-radius:8px;padding:12px;text-align:center;border:1px solid #e5e5ea;">
                    <div style="font-size:11px;color:#6e6e73;">已解决</div>
                    <div style="font-size:22px;font-weight:700;color:#34c759;">{stab_resolved}</div>
                </div>
                <div style="background:white;border-radius:8px;padding:12px;text-align:center;border:1px solid #e5e5ea;">
                    <div style="font-size:11px;color:#6e6e73;">解决率</div>
                    <div style="font-size:22px;font-weight:700;color:#5856d6;">{stab_rate}%</div>
                </div>
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead>
                    <tr style="background:#1d1d1f;color:white;">
                        <th style="padding:10px 12px;text-align:left;">稳定性模块</th>
                        <th style="padding:10px 12px;text-align:center;">总数</th>
                        <th style="padding:10px 12px;text-align:center;">已解决</th>
                        <th style="padding:10px 12px;text-align:center;">未解决</th>
                    </tr>
                </thead>
                <tbody>{stab_rows}</tbody>
            </table>
        </div>
        '''

    # 待验证问题
    unverified_html = ''
    if resolved_unverified:
        unv_rows = ''
        for item in resolved_unverified[:50]:
            unv_rows += f'''
            <tr>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;text-align:center;font-family:monospace;">{item.get('issue_id', '-')}</td>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;max-width:200px;overflow:hidden;text-overflow:ellipsis;">{item.get('title', '-')}</td>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;">{item.get('developer', '-')}</td>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;">{item.get('module', '-')}</td>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;text-align:center;">{item.get('severity', '-')}</td>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;text-align:center;">{item.get('resolution', '-')}</td>
            </tr>
            '''
        unverified_html = f'''
        <div style="margin-bottom:28px;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#ff9500;padding-bottom:8px;border-bottom:2px solid #ff9500;">⚠️ 待验证问题 (共 {len(resolved_unverified)} 条，显示前 {min(len(resolved_unverified), 50)} 条)</h2>
            <p style="font-size:12px;color:#6e6e73;margin-bottom:12px;">以下问题的 Status 为 Verified，需要进行验证测试</p>
            <table style="width:100%;border-collapse:collapse;font-size:11px;">
                <thead>
                    <tr style="background:#ff9500;color:white;">
                        <th style="padding:8px 10px;text-align:center;">edartID</th>
                        <th style="padding:8px 10px;text-align:left;">标题</th>
                        <th style="padding:8px 10px;text-align:left;">研发</th>
                        <th style="padding:8px 10px;text-align:left;">模块</th>
                        <th style="padding:8px 10px;text-align:center;">严重性</th>
                        <th style="padding:8px 10px;text-align:center;">Resolution</th>
                    </tr>
                </thead>
                <tbody>{unv_rows}</tbody>
            </table>
        </div>
        '''

    # 生成完整HTML（按新顺序：概览→智能建议→严重程度→模块饼图→每日折线图→研发→稳定性→待验证）
    now = datetime.now(_CST).strftime('%Y-%m-%d %H:%M:%S')
    # 使用自定义标题或默认标题
    report_title = custom_title if custom_title else '📊 CR问题分析报告'
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{report_title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        @page {{ size: A4; margin: 20mm 15mm; }}
        body {{
            font-family: -apple-system, "SF Pro Display", "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
            padding: 40px;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            color: #1d1d1f;
        }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 12px; }}
        th {{ background: #1d1d1f; color: white; padding: 10px 12px; text-align: left; font-weight: 600; font-size: 12px; }}
        td {{ border: 1px solid #e5e5ea; padding: 8px 12px; }}
        .header {{ text-align: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #e5e5ea; }}
        .footer {{ text-align: center; font-size: 11px; color: #8e8e93; margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e5ea; }}
        @media print {{ body {{ padding: 0; }} }}
    </style>
</head>
<body>
    {watermark_html}
    <div class="header">
        <h1 style="font-size:24px;font-weight:700;color:#1d1d1f;margin:0;">{report_title}</h1>
        <div style="font-size:13px;color:#6e6e73;margin-top:8px;">
            {f'文件: {file_name}' if file_name else ''} | 生成时间: {now}
        </div>
    </div>
    {overview_html}
    {suggestions_html}
    {sev_html}
    {module_html}
    {daily_html}
    {dev_html}
    {stability_html}
    {unverified_html}
    <div class="footer">
        📊 CR问题智能分析系统 — 自动生成报告
    </div>
    <script>
        document.addEventListener('DOMContentLoaded', function() {{
            {module_chart_js}
            {daily_chart_js}
        }});
    </script>
</body>
</html>'''
# === 下载路由 ===
@app.route('/download/<filename>')
def download_file(filename):
    # 先检查UPLOAD_FOLDER
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)

    # 再检查PDF_FOLDER
    filepath = os.path.join(app.config['PDF_FOLDER'], filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)

    return jsonify({'error': '文件不存在'}), 404
# === NoteNB 笔记应用路由 ===
NOTENB_DIST = os.path.join(static_dir, 'noteNB')

@app.route('/noteNB')
def notenb_redirect():
    return redirect('/noteNB/')

@app.route('/noteNB/')
def notenb_index():
    return send_from_directory(NOTENB_DIST, 'index.html')

@app.route('/noteNB/assets/<path:filename>')
def notenb_assets(filename):
    notenb_assets = os.path.join(NOTENB_DIST, 'assets')
    return send_from_directory(notenb_assets, filename)

@app.route('/noteNB/<path:path>')
def notenb_catch_all(path):
    file_path = os.path.join(NOTENB_DIST, path)
    if os.path.isfile(file_path):
        return send_file(file_path)
    return send_from_directory(NOTENB_DIST, 'index.html')


# === 静态资源路由 ===
@app.route('/assets/<path:filename>')
def serve_assets(filename):
    assets_dir = os.path.join(base_dir, 'assets')
    return send_from_directory(assets_dir, filename)


if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT', 5001))
        print(f"GGB 1.0 启动中... (port={port})")
        logger.info(f"GGB 1.0 启动中... (port={port})")
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logger.error(f"启动失败: {e}")
        logger.error(traceback.format_exc())
        print(f"启动失败: {str(e)}")
