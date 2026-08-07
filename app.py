from flask import Flask, render_template, request, send_file, send_from_directory, jsonify, redirect
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
app.config['TEMPLATES_AUTO_RELOAD'] = True

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

app.config['AI_CONFIG_FILE'] = os.path.join(_runtime_dir, 'ai_config.json')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PDF_FOLDER'], exist_ok=True)


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
            self._wb = load_workbook(self.file_path, data_only=True)
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
            return [[str(cell).strip() if cell is not None else '' for cell in row] for row in ws.iter_rows(values_only=True)]
    
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
            # 只读取文件前 200KB 来提取表头和第一行数据
            # HTML Excel 的 <thead> 在文件开头，数据行紧随其后
            READ_SIZE = 200 * 1024
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
        """流式解析 HTML 格式 Excel 文件，不使用 BeautifulSoup 避免大文件 OOM"""
        try:
            # HTML 实体和标签清理
            def clean_html_text(text):
                text = re.sub(r'<[^>]+>', '', text)
                text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
                return text.strip()

            # === 第一步：流式读取表头（只读前 200KB）===
            READ_SIZE = 200 * 1024
            with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                head_chunk = f.read(READ_SIZE)

            # 提取 <th> 表头
            th_pattern = re.compile(r'<th[^>]*>(.*?)</th>', re.IGNORECASE | re.DOTALL)
            th_matches = th_pattern.findall(head_chunk)
            all_headers = [clean_html_text(m) for m in th_matches if clean_html_text(m)]

            if not all_headers:
                # 回退：从第一个 <tr> 中的 <td> 提取
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
            _log_mem(f"HTML流式解析：保留{len(keep_cols)}列，表头{len(full_headers)}个")

            # === 第二步：流式提取数据行 ===
            result_rows = [full_headers]
            row_count = 0
            td_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL)

            # 找到 </thead> 位置，跳过表头
            thead_end_pos = head_chunk.lower().find('</thead>')
            skip_header = thead_end_pos >= 0

            with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                if skip_header:
                    f.seek(thead_end_pos + 8)
                else:
                    f.seek(0)

                buffer = ''
                CHUNK_SIZE = 512 * 1024  # 512KB chunks

                while True:
                    piece = f.read(CHUNK_SIZE)
                    if not piece:
                        break
                    buffer += piece

                    # 提取完整的 <tr>...</tr> 块
                    while True:
                        tr_start = buffer.find('<tr')
                        if tr_start == -1:
                            buffer = ''
                            break
                        tr_end = buffer.find('</tr>', tr_start)
                        if tr_end == -1:
                            # 不完整的行，保留到下次
                            buffer = buffer[tr_start:]
                            # 防止缓冲区无限增长（单行不应超过 1MB）
                            if len(buffer) > 1024 * 1024:
                                buffer = ''
                            break

                        tr_content = buffer[tr_start:tr_end + 5]
                        buffer = buffer[tr_end + 5:]

                        # 跳过包含 <th> 的行（表头行）
                        if '<th' in tr_content.lower():
                            continue

                        # 提取 <td> 单元格
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

                    del piece

            del buffer, head_chunk
            gc.collect()

            _log_mem(f"HTML流式解析完成：{row_count}行 x {len(full_headers)}列")
            return result_rows

        except Exception as e:
            raise ValueError(f'解析 HTML 格式 Excel 文件失败: {str(e)}')
    
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
    import psutil
    mem = psutil.Process().memory_info().rss / 1024 / 1024
    return jsonify({'status': 'ok', 'memory_mb': round(mem, 1), 'pid': os.getpid()})

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

    try:
        result = _analyze_sheet_detail(file_path, sheet_name)
        return jsonify({'status': 'success', 'data': result})
    except Exception as e:
        logger.error(f"Sheet分析失败: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


def _analyze_sheet_detail(file_path, sheet_name):
    """分析单个Sheet的详细内容"""
    reader = ExcelReader(file_path)
    reader.open()
    rows = reader.get_sheet_data(sheet_name)
    reader.close()

    if not rows:
        return {
            'file_basename': os.path.basename(file_path),
            'sheet_name': sheet_name,
            'project_info': {},
            'test_items': [],
            'stats': {'total': 0, 'pass': 0, 'fail': 0, 'pass_rate': '0%'}
        }

    # 1. 识别KV信息区
    project_info = {}
    info_end_row = 0
    result_keywords = ['pass', 'fail', '通过', '不通过', 'blocker', 'critical', 'major', 'minor', 'trivial']
    header_keywords = ['test item', 'test case', '测试项', '模块', 'module', 'severity', '结果', 'result', 'status', '状态', 'name', '名称']

    for row_idx, row in enumerate(rows):
        cells = [str(c).strip() if c is not None else '' for c in row]
        non_empty = [c for c in cells if c]

        if not non_empty:
            info_end_row = row_idx + 1
            continue

        # 检查是否是表头行（多个单元格，且包含表头关键词）
        row_text = ' '.join(cells).lower()
        is_header_row = len(non_empty) >= 2 and any(kw in row_text for kw in header_keywords)
        
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
    table_header_keywords = ['结果', 'result', 'pass', 'fail', '通过', '测试项', 'test item', 'test case', 'module', '模块', 'severity', '严重程度', 'status', '状态', 'name', '名称', 'remark', '备注']

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
            if any(kw in row_text for kw in table_header_keywords):
                headers = cells
                continue

        if headers and len(non_empty) >= 1:
            data_rows.append({'cells': cells, 'row_idx': row_idx})

    # 3. 检测列索引
    col_indices = _detect_column_indices(headers)

    # 4. 解析测试项
    for data_row in data_rows:
        cells = data_row['cells']
        row_idx = data_row['row_idx']

        name = _get_cell_value(cells, col_indices.get('name', -1))
        module = _get_cell_value(cells, col_indices.get('module', -1))
        severity = _get_cell_value(cells, col_indices.get('severity', -1))
        result = _get_cell_value(cells, col_indices.get('result', -1))
        reason = _get_cell_value(cells, col_indices.get('reason', -1))

        result_clean = result.strip().lower()
        is_pass = _is_pass_result(result_clean)
        is_fail = _is_fail_result(result_clean)

        test_item = {
            'name': name or f'测试项{row_idx + 1}',
            'module': module,
            'severity': severity,
            'result': 'pass' if is_pass else ('fail' if is_fail else 'unknown'),
            'result_text': result.strip() or ('Pass' if is_pass else 'Fail'),
            'reason': reason,
            'row_index': row_idx + 1
        }
        test_items.append(test_item)

    # 5. 统计
    total = len(test_items)
    pass_count = sum(1 for item in test_items if item['result'] == 'pass')
    fail_count = sum(1 for item in test_items if item['result'] == 'fail')
    pass_rate = f"{(pass_count / total * 100):.1f}%" if total > 0 else "0%"

    severity_stats = {}
    for item in test_items:
        sev = item.get('severity', '').strip()
        if sev:
            sev_lower = sev.lower()
            for level in ['blocker', 'critical', 'major', 'minor', 'trivial']:
                if level in sev_lower:
                    severity_stats[level] = severity_stats.get(level, 0) + 1
                    break

    return {
        'file_basename': os.path.splitext(os.path.basename(file_path))[0],
        'sheet_name': sheet_name,
        'project_info': project_info,
        'test_items': test_items,
        'stats': {
            'total': total,
            'pass': pass_count,
            'fail': fail_count,
            'pass_rate': pass_rate,
            'severity': severity_stats
        }
    }


def _detect_column_indices(headers):
    col_map = {}
    if not headers:
        return col_map
    headers_lower = [str(h).lower().strip() for h in headers]

    for i, h in enumerate(headers_lower):
        if any(kw in h for kw in ['测试项', '测试内容', '名称', 'name', 'test item', 'test case', 'case']):
            col_map['name'] = i
        elif any(kw in h for kw in ['模块', 'module', 'component', '组件', '功能']):
            col_map['module'] = i
        elif any(kw in h for kw in ['severity', '严重程度', '严重性', '等级', 'level']):
            col_map['severity'] = i
        elif any(kw in h for kw in ['结果', 'result', 'pass/fail', '通过', 'status', '状态']):
            col_map['result'] = i
        elif any(kw in h for kw in ['原因', 'reason', '备注', 'remark', 'note', '说明', '描述']):
            col_map['reason'] = i

    if 'result' not in col_map:
        for i, h in enumerate(headers_lower):
            if any(kw in h for kw in ['pass', 'fail', '通过', '不通过']):
                col_map['result'] = i
                break

    if 'name' not in col_map:
        col_map['name'] = 0

    if 'reason' not in col_map and len(headers) > 0:
        col_map['reason'] = len(headers) - 1

    return col_map


def _get_cell_value(cells, idx):
    if idx < 0 or idx >= len(cells):
        return ''
    return str(cells[idx]).strip() if cells[idx] else ''


def _is_pass_result(text):
    pass_words = ['pass', '通过', '合格', 'yes', 'y', 'ok', 'success', '√', '✓', 'p', 'done']
    return text in pass_words or text.startswith('pass') or '通过' in text or '合格' in text


def _is_fail_result(text):
    fail_words = ['fail', '不通过', '不合格', 'no', 'n', 'ng', 'error', '×', '✗', 'f', 'bug', 'failed']
    return text in fail_words or text.startswith('fail') or '不通过' in text or '不合格' in text or '失败' in text

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

    # 创建空文件
    with open(file_path, 'wb') as f:
        pass

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

    # 读取分块数据并追加到文件
    chunk_data = chunk_file.read()
    with open(meta['file_path'], 'ab') as f:
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
        logger.info(f"========== 分块上传完成: {filename} ==========")

        reader = ExcelReader(file_path)
        reader.open()
        sheet_names = reader.get_sheet_names()
        reader.close()

        # 清理元数据
        _delete_chunk_meta(upload_id)

        return jsonify({
            'status': 'success',
            'data': {
                'file_id': file_id,
                'file_name': filename,
                'sheet_names': sheet_names
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

    # 检查任务是否超时（超过 5 分钟仍在 processing 视为超时）
    if task['status'] == 'processing':
        created_at = task.get('created_at', 0)
        if created_at and (time.time() - created_at) > 300:
            task['status'] = 'error'
            task['error'] = '分析超时（超过5分钟），可能是文件过大或格式异常，请尝试减少数据量或转换为 .xlsx 格式'
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
            logger.error(f"分析失败: {traceback.format_exc()}")
            _background_tasks[task_id]['error'] = str(e)
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

        from playwright.sync_api import sync_playwright
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

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"file://{html_path}")
            page.wait_for_load_state('networkidle')
            page.pdf(
                path=pdf_path,
                format='A4',
                margin={'top': '2cm', 'right': '2cm', 'bottom': '2cm', 'left': '2cm'},
                print_background=True
            )
            browser.close()

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

        from playwright.sync_api import sync_playwright
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

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"file://{html_path}")
            page.wait_for_load_state('networkidle')
            page.pdf(
                path=pdf_path,
                format='A4',
                margin={'top': '2cm', 'right': '2cm', 'bottom': '2cm', 'left': '2cm'},
                print_background=True
            )
            browser.close()

        return jsonify({'filename': pdf_filename})
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
            from playwright.sync_api import sync_playwright
            
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

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(f"file://{html_path}")
                page.wait_for_load_state('networkidle')
                page.pdf(
                    path=pdf_path,
                    format='A4',
                    margin={'top': '2cm', 'right': '2cm', 'bottom': '2cm', 'left': '2cm'},
                    print_background=True
                )
                browser.close()

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
        
        from playwright.sync_api import sync_playwright
        import tempfile as tf
        
        with tf.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
            f.write(html_content)
            html_path = f.name
        
        pdf_filename = f"excel_report_{int(time.time())}.pdf"
        pdf_path = os.path.join(app.config['PDF_FOLDER'], pdf_filename)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f'file://{html_path}')
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(1000)
            page.pdf(
                path=pdf_path,
                format='A4',
                margin={'top': '20mm', 'bottom': '20mm', 'left': '15mm', 'right': '15mm'},
                print_background=True
            )
            browser.close()
        
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
        
        from playwright.sync_api import sync_playwright
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
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f'file://{html_path}')
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(1500)
            page.pdf(
                path=pdf_path,
                format='A4',
                margin={'top': '20mm', 'bottom': '20mm', 'left': '15mm', 'right': '15mm'},
                print_background=True
            )
            browser.close()
        
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
        
        from playwright.sync_api import sync_playwright
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
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f'file://{html_path}')
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(1500)
            page.pdf(
                path=pdf_path,
                format='A4',
                margin={'top': '20mm', 'bottom': '20mm', 'left': '15mm', 'right': '15mm'},
                print_background=True
            )
            browser.close()
        
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

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # 优先使用系统 Chrome（本地环境），失败后回退到 Playwright 内置 Chromium（Docker/Railway 环境）
            try:
                browser = p.chromium.launch(headless=True, channel="chrome")
            except Exception:
                browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f'file://{html_path}')
            page.wait_for_load_state('networkidle')
            # 等待Chart.js加载完成并渲染图表
            try:
                page.wait_for_selector('canvas', timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            page.pdf(
                path=pdf_path,
                format='A4',
                margin={'top': '20mm', 'bottom': '20mm', 'left': '15mm', 'right': '15mm'},
                print_background=True
            )
            browser.close()

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
