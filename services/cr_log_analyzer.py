# -*- coding: utf-8 -*-
"""CR 日志证据抽取器（纯解析，不依赖网络）。

输入一组附件文件 (filename, bytes)，自动解包 zip/gz/tar，识别 Android / 穿戴设备
bugreport、bug2go 日志包，从海量日志中抽取高信号证据，分类组织后供 AI 做根因分析：

- boot_reasons   ：getprop 中的 (last) boot reason / shutdown reason（定位为何重启）
- device         ：机型 / 版本 / fingerprint
- report_meta    ：bug2go report_information.json（现象、发生时间、频率、调研答案）
- java_crash     ：FATAL EXCEPTION / AndroidRuntime / Caused by 连续栈
- native_crash   ：Fatal signal / SIGSEGV / Abort message / backtrace(tombstone)
- anr            ：ANR in / CPU usage / 超时
- startup_points ：应用进程启动 / 数据库创建锚点（定位重启边界、数据是否重建）
- data_events    ：恢复出厂 / 清数据 / 迁移 / 库为空 等数据生命周期事件
- db_errors      ：SQLite 约束 / 损坏 / 锁 等数据库错误
- system_events  ：watchdog / system_server / kernel panic / lmkd / reboot 等
- error_lines    ：去重降噪后的应用 ERROR 行

设计目标：25MB 级应用日志也能流式扫描；蓝牙 hex 帧、权限检查刷屏等噪音被过滤；
任何单个文件损坏 / 编码异常都不影响整体解析。
"""
import re
import io
import gzip
import json
import zipfile
import tarfile
import logging
import unicodedata

logger = logging.getLogger(__name__)

# ---------- 预算 / 防护 ----------
MAX_ENTRY_BYTES = 60 * 1024 * 1024     # 单个文本文件最多扫描 60MB
TOTAL_UNZIP_CAP = 160 * 1024 * 1024    # 一次分析累计解压字节上限（防 zip bomb）
MAX_ENTRIES = 3000                     # 归档内文件数上限
LONG_LINE = 500                        # 超过该长度再做 hex 噪音判定
MAX_CHARS_DEFAULT = 26000              # 拼装给模型的证据文本上限

TEXT_EXTS = ('.txt', '.log', '.json', '.trace', '.crash', '.anr', '.xml',
             '.yaml', '.yml', '.properties', '.conf', '.cfg', '.text', '.out')
ARCHIVE_EXTS = ('.zip', '.gz', '.gzip', '.tgz', '.tar', '.tar.gz', '.bz2')
BINARY_SKIP_EXTS = ('.core', '.db', '.sqlite', '.dat', '.bin', '.png', '.jpg',
                    '.jpeg', '.gif', '.webp', '.mp4', '.mp3', '.wav', '.so',
                    '.apk', '.dex', '.odex', '.oat', '.art', '.ttf', '.otf',
                    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip.done')

# 各类证据条数上限
CAPS = {
    'java_crash': 8,
    'native_crash': 8,
    'anr': 6,
    'startup_points': 24,
    'data_events': 40,
    'db_errors': 30,
    'system_events': 45,
    'error_lines': 40,
}

# ---------- 正则 ----------
# 崩溃类只认强信号，避免普通日志里出现 Exception/crash 等单词造成误报
RE_JAVA = re.compile(
    r'FATAL EXCEPTION|E AndroidRuntime|AndroidRuntime: FATAL|'
    r'\*\*\* FATAL|Caused by:\s*[\w\.$]+(Exception|Error)|'
    r'java\.lang\.RuntimeException:|kotlinx?\.[\w\.]+Exception:', re.I)
RE_NATIVE = re.compile(
    r'Fatal signal \d+|signal \d+ \(SIG[A-Z]+\)|SIGSEGV|SIGABRT|SIGBUS|'
    r'Abort message:|crash_dump\d*[: ]|backtrace:\s*$|'
    r'#\d{2}\s+pc\s+0x[0-9a-fA-F]+', re.I)
RE_ANR = re.compile(
    r'ANR in [\w\.]|Application Not Responding|Input dispatching timed out|'
    r'am_anr|Reason: Input dispatching|Subject: Input dispatching timed out', re.I)
RE_STARTUP = re.compile(
    r'attachBaseContext|BaseApplication[ -]*onCreate|processName\s*[:=]|'
    r'AppDatabase - create|HealthDatabase|Database created|Database open\b|'
    r'Application onCreate|RoomOpenHelper|onCreate\(\)\.\.\.', re.I)
RE_DATA = re.compile(
    r'factory reset|factoryReset|wipe data|wipeData|clearApplicationUserData|'
    r'pm clear|restore default|恢复出厂|清空|清除数据|数据重置|'
    r'no need to migrate|items in instant DB|items in daily DB|'
    r'Migrating the|encryptMigration|database build|deleting database file|'
    r'Room cannot verify|Migration|fallbackToDestructive|createAllTables', re.I)
RE_DB = re.compile(
    r'SQLITE_[A-Z]+|SQLiteException|SQLiteConstraint|SQLiteDiskIOException|'
    r'constraint failed|database is locked|disk I/O error|'
    r'database disk image is malformed|database .* is corrupt|'
    r'Cannot open database|unable to open database|file is not a database', re.I)
RE_SYSTEM = re.compile(
    r'watchdog|WatchDog|system_server|kernel panic|Kernel panic|'
    r'lowmemorykiller|low memory killer|\blmkd\b|OutOfMemoryError|'
    r'Force finishing|Killing \d+:|reboot|Restarting system|'
    r'shutdown reason|boot reason|bootreason|thermal shutdown|'
    r'sys.boot_completed|init: Service|crash_dump|Zygote.*exited|'
    r'process .* has died|Process .* died|tombstoned', re.I)
# 应用日志：HH:MM:SS.mmm [thread] LEVEL Logger - msg
RE_APP_ERR = re.compile(
    r'^\s*\d{2}:\d{2}:\d{2}[\.,]\d+\s+\[[^\]]+\]\s+(ERROR|FATAL|CRITICAL)\s+'
    r'([\w\.\$]+)\s*[-:]?\s*(.*)$')
# logcat：MM-DD HH:MM:SS.ms PID TID LEVEL/tag:
RE_LOGCAT_E = re.compile(
    r'^\s*\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\d+\s+\d+\s+E\s+'
    r'([A-Za-z0-9_\.\- /]{1,40})\s*:\s*(.*)$')
# 噪音 logger / 消息（反复刷屏且无诊断价值）
NOISE_LOGGERS = {'PermissionUtils', 'MotoAccountSdkLogPrinter', 'BluetoothPermissionUtils'}
NOISE_MSG = re.compile(
    r'checkSelfPermission|not exist account\.apk|arePermissionsAvailable|'
    r'BLUETOOTH_SCAN checkSelfPermission|ACCESS_FINE_LOCATION checkSelfPermission', re.I)
RE_GETPROP = re.compile(r'^\s*\[([^\]]+)\]\s*:\s*\[(.*)\]\s*$')
RE_BOOT_PROP = re.compile(r'boot.{0,3}reason|bootreason|shutdown.{0,3}reason|last.boot', re.I)
BUILD_PROPS = (
    'ro.product.model', 'ro.product.brand', 'ro.product.device',
    'ro.product.manufacturer', 'ro.product.name',
    'ro.build.version.release', 'ro.build.version.sdk',
    'ro.build.display.id', 'ro.build.fingerprint', 'ro.build.date',
    'ro.build.version.incremental', 'ro.build.type', 'ro.debuggable',
)
RE_HEX = re.compile(r'[0-9a-fA-F]')


def strip_cf(text):
    """去除 bug2go json 键名里混入的不可见格式字符（U+200E/U+202E 等）。"""
    return ''.join(c for c in str(text) if unicodedata.category(c) != 'Cf')


def _printable_ratio(text):
    """可打印字符占比；Unicode 格式控制字符(Cf，如 RTL 标记)按可接受处理。"""
    if not text:
        return 1.0
    ok = sum(1 for c in text
             if c.isprintable() or c in '\r\n\t' or unicodedata.category(c) == 'Cf')
    return ok / len(text)


def _is_noise_hex_line(line):
    """蓝牙 SPP / FrameBuffer 等超长十六进制帧，整行无诊断价值。"""
    if len(line) <= LONG_LINE:
        return False
    head = line[:1200]
    hexd = len(RE_HEX.findall(head))
    return hexd / max(1, len(head)) > 0.45


def _short_name(path):
    return path.replace('\\', '/').split('/')[-1]


def new_evidence():
    return {
        'device': {},
        'boot_reasons': [],
        'report_meta': {},
        'java_crash': [],
        'native_crash': [],
        'anr': [],
        'startup_points': [],
        'data_events': [],
        'db_errors': [],
        'system_events': [],
        'error_lines': [],
        'files': [],
        'skipped': [],
        'truncated': [],
        'counts': {},
    }


class _Collector:
    def __init__(self, ev):
        self.ev = ev
        self._seen = set()

    def add(self, bucket, text, source, dedup=None, cap=None):
        cap = cap if cap is not None else CAPS.get(bucket, 30)
        arr = self.ev[bucket]
        if len(arr) >= cap:
            return False
        text = (text or '').strip()
        if not text:
            return False
        key = dedup if dedup is not None else (bucket, text[:140])
        if key in self._seen:
            return False
        self._seen.add(key)
        arr.append({'source': source, 'text': text[:1800]})
        return True


def _scan_getprop(lines, ev):
    for line in lines:
        m = RE_GETPROP.match(line)
        if not m:
            continue
        k, v = m.group(1).strip(), m.group(2).strip()
        if not v:
            continue
        kl = k.lower()
        if RE_BOOT_PROP.search(k):
            item = '%s = %s' % (k, v)
            if item not in ev['boot_reasons']:
                ev['boot_reasons'].append(item)
        elif kl in BUILD_PROPS:
            ev['device'].setdefault(k, v)


def _flatten_json(obj, out, prefix=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            kk = strip_cf(k)
            if isinstance(v, (dict, list)):
                _flatten_json(v, out, prefix + kk + '.')
            else:
                out[strip_cf(prefix + kk)] = strip_cf(v)
    elif isinstance(obj, list):
        for i, x in enumerate(obj[:8]):
            _flatten_json(x, out, prefix + '[%d].' % i)


def _scan_report_meta(text, ev):
    try:
        obj = json.loads(strip_cf(text))
    except Exception:
        return
    flat = {}
    _flatten_json(obj, flat)
    want = re.compile(r'summary|description|report creation|time the issue|how often|'
                      r'priority|recover|category|report type|firmware|software version|'
                      r'app version|build|serial|battery', re.I)
    for k, v in flat.items():
        kk = k.split('.')[-1]
        if v and want.search(kk):
            # Surveys 答案保留，丢弃布尔/版本噪声
            if str(v).lower() in ('true', 'false'):
                continue
            ev['report_meta'].setdefault(kk, str(v)[:300])


def _norm_msg(msg):
    return re.sub(r'[0-9a-fA-F]{6,}', '#', re.sub(r'\d+', '#', msg))[:70]


def scan_text(name, data_bytes, ev, ctx=3, block_after=26):
    """扫描单个文本文件内容，把证据写入 ev。"""
    source = _short_name(name) or name
    if len(data_bytes) > MAX_ENTRY_BYTES:
        ev['truncated'].append('%s（%.1fMB，仅扫描前 %.0fMB）'
                               % (source, len(data_bytes) / 1048576,
                                  MAX_ENTRY_BYTES / 1048576))
        data_bytes = data_bytes[:MAX_ENTRY_BYTES]
    text = data_bytes.decode('utf-8', 'ignore')
    # 可打印率过低视为二进制
    if _printable_ratio(text[:4096]) < 0.82:
        ev['skipped'].append({'name': source, 'reason': 'binary/non-text'})
        return
    lines = text.splitlines()
    low = source.lower()
    # bug2go 的 deam.yaml / categories.yaml 等是监控规则与分类配置（含 Kernel Panic、
    # >>> proc <<< 等规则文本），不是设备日志，跳过以免产生伪崩溃证据
    if low.endswith(('.yaml', '.yml', '.ini', '.conf')):
        ev['skipped'].append({'name': source, 'reason': 'config file'})
        return
    ev['files'].append({'name': source, 'lines': len(lines),
                        'kb': round(len(data_bytes) / 1024, 1)})
    if 'getprop' in low:
        _scan_getprop(lines, ev)
        # getprop 是键值属性表，不参与通用日志模式匹配（避免属性名污染事件）
        return
    if low.endswith('.json') and 'report_information' in low:
        _scan_report_meta(text, ev)
        return

    col = _Collector(ev)
    n = len(lines)
    covered = [False] * n
    block_specs = (('java_crash', RE_JAVA), ('native_crash', RE_NATIVE), ('anr', RE_ANR))

    # 第一遍：连续栈块
    for i, line in enumerate(lines):
        if covered[i] or _is_noise_hex_line(line):
            continue
        for cat, rx in block_specs:
            if rx.search(line):
                start = max(0, i - ctx)
                end = min(n, i + block_after)
                block = '\n'.join(lines[start:end])
                for k in range(start, end):
                    covered[k] = True
                col.add(cat, block, source,
                        dedup=(cat, rx.search(line).group(0), _norm_msg(line)))
                break

    # 第二遍：单行分类
    for i, line in enumerate(lines):
        if covered[i]:
            continue
        if _is_noise_hex_line(line) or len(line) > 600:
            continue
        m_app = RE_APP_ERR.match(line)
        m_log = RE_LOGCAT_E.match(line)
        if m_app:
            logger_, msg = m_app.group(2), m_app.group(3)
            if logger_ in NOISE_LOGGERS or NOISE_MSG.search(msg):
                continue
            if RE_DB.search(line):
                col.add('db_errors', line, source, dedup=('db', logger_, _norm_msg(msg)))
            elif RE_DATA.search(line):
                col.add('data_events', line, source, dedup=('data', logger_, _norm_msg(msg)))
            elif RE_SYSTEM.search(line):
                col.add('system_events', line, source, dedup=('sys', logger_, _norm_msg(msg)))
            else:
                col.add('error_lines', line, source, dedup=('err', logger_, _norm_msg(msg)))
            continue
        if m_log:
            tag, msg = m_log.group(1).strip(), m_log.group(2)
            if NOISE_MSG.search(msg):
                continue
            if RE_JAVA.search(line):
                col.add('java_crash', '\n'.join(lines[max(0, i - ctx):i + 20]), source,
                        dedup=('java', tag, _norm_msg(msg)))
            elif RE_NATIVE.search(line):
                col.add('native_crash', '\n'.join(lines[max(0, i - ctx):i + 22]), source,
                        dedup=('native', tag, _norm_msg(msg)))
            elif RE_ANR.search(line):
                col.add('anr', '\n'.join(lines[max(0, i - ctx):i + 20]), source,
                        dedup=('anr', tag, _norm_msg(msg)))
            elif RE_DB.search(line):
                col.add('db_errors', line, source, dedup=('db', tag, _norm_msg(msg)))
            elif RE_SYSTEM.search(line):
                col.add('system_events', line, source, dedup=('sys', tag, _norm_msg(msg)))
            continue
        # 非错误级别的普通锚点 / 事件
        if RE_STARTUP.search(line):
            ts = line.strip()[:16]
            col.add('startup_points', line, source, dedup=('start', ts, _norm_msg(line)))
        elif RE_DB.search(line):
            col.add('db_errors', line, source, dedup=('db', _norm_msg(line)))
        elif RE_DATA.search(line):
            col.add('data_events', line, source, dedup=('data', _norm_msg(line)))
        elif RE_SYSTEM.search(line):
            col.add('system_events', line, source, dedup=('sys', _norm_msg(line)))


def _looks_text(name, head):
    low = name.lower()
    if low.endswith(TEXT_EXTS) or '.' not in name.replace('\\', '/').split('/')[-1]:
        if head:
            txt = head[:2048].decode('utf-8', 'ignore')
            return _printable_ratio(txt) > 0.82
        return True
    return low.endswith(TEXT_EXTS)


def process_item(name, data, ev, state, depth=0):
    """处理归档内一个条目（递归解包）。state 记录累计字节/条目用于防护。"""
    low = name.lower()
    if state['entries'] > MAX_ENTRIES:
        return
    state['entries'] += 1
    try:
        if low.endswith(BINARY_SKIP_EXTS) or re.search(r'\.(core|so|apk|db|png|jpg|jpeg|mp4)$', low):
            ev['skipped'].append({'name': name, 'reason': 'binary',
                                  'kb': round(len(data) / 1024, 1)})
            return
        if low.endswith('.zip'):
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
            except Exception as e:
                ev['skipped'].append({'name': name, 'reason': 'bad-zip:%s' % type(e).__name__})
                return
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if state['bytes'] > TOTAL_UNZIP_CAP:
                    ev['truncated'].append('达到解压字节上限，其余文件未扫描')
                    break
                with zf.open(info) as fh:
                    chunk = fh.read(MAX_ENTRY_BYTES + 1)
                state['bytes'] += len(chunk)
                if depth < 2:
                    process_item(info.filename, chunk, ev, state, depth + 1)
            return
        if low.endswith(('.gz', '.gzip')) and not low.endswith('.tar.gz'):
            try:
                inner = gzip.decompress(data[: MAX_ENTRY_BYTES + 2_000_000])
            except Exception as e:
                ev['skipped'].append({'name': name, 'reason': 'bad-gz:%s' % type(e).__name__})
                return
            inner_name = name[:-3] if name.lower().endswith('.gz') else name
            state['bytes'] += len(inner)
            process_item(inner_name, inner, ev, state, depth + 1)
            return
        if low.endswith(('.tar', '.tgz', '.tar.gz', '.bz2')):
            try:
                tf = tarfile.open(fileobj=io.BytesIO(data), mode='r:*')
                for member in tf.getmembers()[:500]:
                    if not member.isfile():
                        continue
                    ef = tf.extractfile(member)
                    if ef is None:
                        continue
                    chunk = ef.read(MAX_ENTRY_BYTES + 1)
                    state['bytes'] += len(chunk)
                    process_item(member.name, chunk, ev, state, depth + 1)
            except Exception as e:
                ev['skipped'].append({'name': name, 'reason': 'bad-tar:%s' % type(e).__name__})
            return
        # 普通文本
        head = data[:2048]
        if _looks_text(name, head):
            state['bytes'] += len(data)
            scan_text(name, data, ev)
        else:
            ev['skipped'].append({'name': name, 'reason': 'binary/unknown',
                                  'kb': round(len(data) / 1024, 1)})
    except Exception as e:
        logger.warning('解析日志条目失败 %s: %s', name, e)
        ev['skipped'].append({'name': name, 'reason': 'parse-error:%s' % type(e).__name__})


def extract_from_files(items):
    """items: [(filename, bytes), ...] -> evidence dict。"""
    ev = new_evidence()
    state = {'bytes': 0, 'entries': 0}
    for name, data in items:
        if state['bytes'] > TOTAL_UNZIP_CAP:
            ev['truncated'].append('达到累计解压上限，%s 及其后未扫描' % name)
            break
        process_item(name, data or b'', ev, state)
    ev['counts'] = {k: len(ev[k]) for k in CAPS}
    ev['counts']['files_scanned'] = len(ev['files'])
    ev['counts']['files_skipped'] = len(ev['skipped'])
    return ev


# ---------- 证据 -> 模型文本 ----------
def _section(title, lines, out, budget):
    if not lines:
        return
    block = ['\n===== %s =====' % title]
    for ln in lines:
        if isinstance(ln, dict):
            block.append('[%s] %s' % (ln.get('source', ''), ln.get('text', '')))
        else:
            block.append(str(ln))
    text = '\n'.join(block)
    if len('\n'.join(out)) + len(text) > budget:
        remain = max(200, budget - len('\n'.join(out)))
        text = text[:remain] + '\n…（已截断）'
    out.append(text)


def evidence_to_text(ev, max_chars=MAX_CHARS_DEFAULT):
    out = []
    dev = ev.get('device', {})
    if dev:
        out.append('===== 设备 / 版本 =====\n' + '\n'.join('%s = %s' % (k, v)
                                                          for k, v in list(dev.items())[:18]))
    br = ev.get('boot_reasons', [])
    if br:
        _section('启动/重启原因（getprop，关键）', br, out, max_chars)
    else:
        out.append('===== 启动/重启原因 =====\n（getprop 中未发现 boot reason 属性）')
    rm = ev.get('report_meta', {})
    if rm:
        out.append('===== 用户报告 / 调研（bug2go）=====\n'
                   + '\n'.join('%s: %s' % (k, v) for k, v in rm.items()))
    # 崩溃类最高优先
    _section('Java 崩溃栈（FATAL EXCEPTION）', ev['java_crash'], out, max_chars)
    _section('Native 崩溃（Tombstone / signal / backtrace）', ev['native_crash'], out, max_chars)
    _section('ANR（应用无响应）', ev['anr'], out, max_chars)
    if not (ev['java_crash'] or ev['native_crash'] or ev['anr']):
        out.append('===== 崩溃栈 =====\n（所有日志中均未发现 Java 崩溃 / Native tombstone / ANR 记录）')
    _section('应用进程启动 / 数据库初始化锚点（用于判断重启边界与数据是否重建）',
             ev['startup_points'], out, max_chars)
    _section('数据生命周期事件（恢复出厂 / 清数据 / 迁移 / 库为空）', ev['data_events'], out, max_chars)
    _section('数据库错误（SQLite）', ev['db_errors'], out, max_chars)
    _section('系统级事件（watchdog / system_server / 重启 / LMK / 内核）',
             ev['system_events'], out, max_chars)
    _section('其它应用错误（已按模块去重降噪）', ev['error_lines'], out, max_chars)

    scanned = ', '.join('%s(%s行)' % (f['name'], f['lines']) for f in ev.get('files', [])[:30])
    skipped = ', '.join('%s(%s)' % (s.get('name'), s.get('reason'))
                        for s in ev.get('skipped', [])[:20])
    out.append('===== 证据覆盖范围 =====\n已扫描文本文件：%s\n未解析/跳过：%s%s'
               % (scanned or '无', skipped or '无',
                  ('\n截断说明：' + '；'.join(ev['truncated'])) if ev.get('truncated') else ''))
    text = '\n\n'.join(out)
    if len(text) > max_chars:
        text = text[:max_chars] + '\n\n…（证据量较大，已按优先级截断）'
    return text
