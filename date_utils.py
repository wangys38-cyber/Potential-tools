"""日期工具模块 — 从 app.py 提取"""
import re
from datetime import datetime, timedelta, timezone


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
    
    # ISO 格式: 2026-08-24T14:30:00.000+0800 或 2026-08-24T14:30:00Z
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})[T ]', date_str)
    if m:
        return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    
    # 尝试用 datetime 解析（扩展格式列表）
    try:
        for fmt in [
            '%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S',
            '%d/%b/%Y', '%d/%b/%y', '%d/%b/%Y %H:%M', '%d/%b/%Y %I:%M %p',
            '%d/%m/%Y', '%d/%m/%y', '%d/%m/%Y %H:%M:%S',
            '%Y/%m/%d', '%Y/%m/%d %H:%M:%S',
            '%d-%m-%Y', '%d-%b-%Y', '%d-%b-%y',
            '%b %d, %Y', '%B %d, %Y',  # Aug 24, 2026
            '%Y.%m.%d', '%Y.%m.%d %H:%M:%S',  # 2026.08.24
        ]:
            try:
                # 只取前25个字符，避免时区信息干扰
                dt = datetime.strptime(date_str[:25].strip(), fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
    except Exception:
        pass
    
    # 最后兜底：如果前10个字符看起来像 YYYY-MM-DD，直接返回
    if len(date_str) >= 10:
        first10 = date_str[:10]
        if re.match(r'^\d{4}-\d{2}-\d{2}$', first10):
            return first10
    
    return date_str[:10] if len(date_str) >= 10 else date_str
# === Excel 文件读取辅助函数 ===
