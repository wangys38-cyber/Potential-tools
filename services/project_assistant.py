# -*- coding: utf-8 -*-
"""项目状态助手服务。

输入一个 Project Key / 项目名称，即可：
1. 通过已配置的 eDart / Jira 直连实时拉取该项目全量 CR；
2. 复用 CR 分析页同一套口径（excel_analyzers + cr_status_summary）生成项目状态快照
   （总体统计、模块 PASS/FAIL、FAIL 模块 Top 未解决 BC、每日趋势、全部未解决 BC 清单）；
3. 快照落盘缓存（data/project_cache/<KEY>.json），当天可秒级复用、可强制刷新；
4. 基于快照 + 多轮历史，调用统一 AI 服务（智谱 GLM / OpenAI 兼容）流式回答，
   可按用户要求输出表格 / 邮件 / 牛马笔记 Markdown / 模块详情等。

口径必须与 CR 分析页保持一致，禁止在本模块另立统计规则。
"""
import os
import json
import time
import hashlib
import logging
import datetime
import ttl_cache
from collections import defaultdict

from excel_analyzers import _analyze_issue_sheet, _match_severity_level
from services import jira_client as jc
from services.project_status_sync import sync_to_knowledge_base
from services.cr_status_summary import (
    build_module_summary, _is_resolved, _SEV_RANK, _issue_num,
)

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
CACHE_DIR = os.path.join(DATA_DIR, 'project_cache')
UPLOAD_DIR = os.path.join(ROOT, 'uploads')

# 快照缓存有效期（秒）：12 小时内重复打开同一项目直接复用，不重新拉全量
SNAP_TTL = 12 * 3600
# 项目列表缓存有效期（秒）
PROJECTS_TTL = 24 * 3600

_SEV_CN = {'blocker': 'Blocker', 'critical': 'Critical', 'major': 'Major',
           'minor': 'Minor', 'trivial': 'Trivial', '': '未知'}


# ============================ 路径与配置 ============================
def _ensure_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _client():
    cfg = jc.load_config(DATA_DIR)
    if not cfg.get('base_url') or not cfg.get('token'):
        raise RuntimeError('尚未配置 eDart/Jira 连接：请先在「CR 问题分析」页点击'
                           '「从 eDart / Jira 直连拉取」填写站点地址并保存 Token')
    return jc.client_from_config(cfg), cfg


def _snap_path(project_key):
    safe = ''.join(ch for ch in project_key.upper() if ch.isalnum() or ch in '_-')
    return os.path.join(CACHE_DIR, f'{safe}.json')


def _projects_cache_path():
    return os.path.join(CACHE_DIR, '_projects.json')


# ============================ 项目列表 / 解析 ============================
def list_projects(force=False):
    """返回当前凭据可访问的项目列表 [{key,name,projectTypeKey}]，带 24h 文件缓存。"""
    cache = _projects_cache_path()
    if not force and os.path.exists(cache):
        try:
            with open(cache, 'r', encoding='utf-8') as f:
                obj = json.load(f)
            if time.time() - obj.get('ts', 0) < PROJECTS_TTL and obj.get('projects'):
                return obj['projects']
        except Exception:
            pass
    client, _ = _client()
    projects = client.list_projects()
    _ensure_dirs()
    try:
        with open(cache, 'w', encoding='utf-8') as f:
            json.dump({'ts': time.time(), 'projects': projects}, f,
                      ensure_ascii=False, indent=2)
    except Exception:
        logger.warning('项目列表缓存写入失败', exc_info=True)
    return projects


def resolve_project(text, projects=None):
    client, _ = _client()
    if projects is None:
        projects = list_projects()
    return client.resolve_project(text, projects)


# ============================ 快照读写 ============================
@ttl_cache.ttl_cache(ttl_seconds=10, key_prefix='pa_snapshot')
def load_snapshot(project_key):
    p = _snap_path(project_key)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        logger.warning('快照读取失败: %s', p, exc_info=True)
        return None


def _save_snapshot(snap):
    _ensure_dirs()
    with open(_snap_path(snap['project_key']), 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False)
    # 保存后失效缓存
    ttl_cache.invalidate(f"pa_snapshot:load_snapshot:('{snap['project_key']}',)")


def snapshot_age_hours(snap):
    if not snap or not snap.get('built_ts'):
        return None
    return round((time.time() - snap['built_ts']) / 3600, 1)


# ============================ 结构化聚合（口径同 cr_status_summary） ============================
def structure_modules(all_issues, top_n=5):
    """与 build_module_summary 完全一致的 FAIL/BC 口径，额外产出前端需要的结构化模块表
    与全量未解决 BC 清单。"""
    mods = defaultdict(lambda: {'total': 0, 'unresolved': 0, 'bc': 0,
                                'b': 0, 'c': 0, 'open_bc': []})
    unresolved_bc = []
    for it in all_issues:
        status = str(it.get('status') or '')
        sev_raw = str(it.get('severity') or '')
        sev = _match_severity_level(sev_raw) or ''
        resolved = _is_resolved(status)
        module = (str(it.get('module') or '').strip() or '(未分类)')
        m = mods[module]
        m['total'] += 1
        rec = {
            'id': (it.get('issue_id') or it.get('id') or it.get('key')
                   or it.get('Issue key') or '').strip(),
            'title': it.get('title', ''), 'module': module,
            'sev': sev, 'sev_raw': sev_raw, 'status': status,
            'developer': it.get('developer', ''), 'labels': it.get('labels', ''),
            'num': _issue_num(it.get('id', '')),
            'created': it.get('created', ''),  # 老化预警需要
            'updated': it.get('updated', ''),   # 老化预警需要
        }
        if not resolved:
            m['unresolved'] += 1
            if sev in ('blocker', 'critical'):
                m['bc'] += 1
                if sev == 'blocker':
                    m['b'] += 1
                else:
                    m['c'] += 1
                m['open_bc'].append(rec)
                unresolved_bc.append(rec)

    modules = []
    for name, d in mods.items():
        d['open_bc'].sort(key=lambda x: (_SEV_RANK.get(x['sev'], 5), -x['num']))
        modules.append({
            'module': name, 'fail': d['bc'] > 0,
            'total': d['total'], 'unresolved': d['unresolved'],
            'bc': d['bc'], 'b': d['b'], 'c': d['c'],
            'open_bc_count': len(d['open_bc']),
            'top_list': d['open_bc'][:top_n],
        })
    modules.sort(key=lambda x: (0 if x['fail'] else 1, -x['bc'],
                                -x['unresolved'], x['module']))
    unresolved_bc.sort(key=lambda x: (_SEV_RANK.get(x['sev'], 5), -x['num']))
    return modules, unresolved_bc


# ============================ 构建快照（拉取 -> 分析） ============================
def build_project_snapshot(project_text, on_progress=None, force=False):
    """全流程：解析项目 -> 拉全量 CR -> 落 CSV -> CR 分析 -> 组装并缓存快照。"""
    def _p(pct, msg):
        if on_progress:
            try:
                on_progress(pct, msg)
            except Exception:
                pass

    client, cfg = _client()

    _p(4, '正在获取项目列表...')
    projects = client.list_projects()
    proj, cands = client.resolve_project(project_text, projects)
    if proj is None:
        if cands:
            names = '、'.join(f"{c['key']}({c['name']})" for c in cands[:8])
            raise RuntimeError(f'匹配到多个项目：{names}，请输入更精确的 Project Key')
        raise RuntimeError(f'未找到与「{project_text}」匹配的项目，请检查 Project Key 或项目名称')
    key, name = proj['key'], proj['name']

    if not force:
        old = load_snapshot(key)
        if old and (time.time() - old.get('built_ts', 0)) < SNAP_TTL:
            old['_cached'] = True
            _p(100, '已复用当天缓存快照')
            return old

    _p(8, f'已定位项目 {key}（{name}），正在探测字段...')
    fmap = client.discover_fields()
    jql = client.build_jql(project_key=key)
    logger.info('项目助手拉取 JQL: %s', jql)

    _p(14, f'正在从 eDart 拉取 {key} 全量 CR，数据较多时约需 1-3 分钟...')

    def _prog(fetched, total, page):
        pct = 14 + int(66 * fetched / max(1, total))
        _p(pct, f'已拉取 {fetched}/{total} 条（第 {page} 页）')

    # 只拉取CR分析必要的字段，减少数据传输量，提升速度
    # 注意：severity在eDart中是自定义字段，需要用fmap中的实际字段ID
    sev_field = fmap.get('severity', 'severity')
    essential_fields = [
        'summary', 'status', 'components', 'assignee', 'reporter',
        'priority', sev_field, 'issuetype', 'created', 'updated', 'resolutiondate',
        'resolution', 'fixVersions', 'versions', 'labels'
    ]
    issues = client.search(jql, fields=essential_fields, page_size=100, on_progress=_prog)
    if not issues:
        raise RuntimeError(f'项目 {key} 未检索到任何问题单，请检查 JQL 或权限')

    _p(82, f'正在转换 {len(issues)} 条数据为标准 CSV...')
    rows = client.issues_to_rows(issues, fmap)
    _ensure_dirs()
    file_id = hashlib.md5(f'pa_{key}_{time.time()}'.encode()).hexdigest()[:16]
    csv_path = os.path.join(UPLOAD_DIR, f'excel_{file_id}.csv')
    n = jc.write_rows_to_csv(rows, csv_path)

    _p(88, '正在执行 CR 分析（与 CR 分析页同一套口径）...')
    result = _analyze_issue_sheet(csv_path, 'Sheet1')
    all_issues = result.get('all_issues', [])

    today = datetime.datetime.now().strftime('%Y-%m-%d')
    module_md, stats = build_module_summary(all_issues, project_name=name or key,
                                            date_str=today)
    modules, unresolved_bc = structure_modules(all_issues)

    snap = {
        'project_key': key,
        'project_name': name,
        'built_ts': time.time(),
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'source_base_url': (cfg.get('base_url') or '').rstrip('/'),
        'jql': jql,
        'csv_file_id': file_id,
        'total': n,
        'stats': stats,
        'summary': result.get('summary', {}),
        'daily_stats': result.get('daily_stats', []),
        'modules': modules,
        'unresolved_bc': unresolved_bc,
        'module_md': module_md,
    }
    _save_snapshot(snap)
    # 自动同步到智能知识库，保持最新状态
    try:
        sync_to_knowledge_base(snap, user_id=1)
    except Exception as e:
        logger.warning(f'自动同步知识库失败（不影响主流程）: {e}')
    _p(100, f'{key} 项目状态生成完成')
    logger.info('项目助手快照完成: %s, %s 条', key, n)
    return snap


# ============================ AI 上下文与对话 ============================
def build_system_prompt(snap):
    """把快照压缩为模型上下文。数字 / 单号全部来自快照。"""
    st = snap.get('stats', {})
    summ = snap.get('summary', {})
    lines = []
    lines.append(
        f"你是「项目 CR 状态助手」，数据来自 eDart/Jira 实时拉取的项目 "
        f"{snap.get('project_key','')}（{snap.get('project_name','')}），"
        f"快照时间 {snap.get('generated_at','')}。")
    lines.append(
        "判定口径与 CR 分析页完全一致：状态包含 resolved/fixed/closed/done/已解决/已关闭 "
        "才算已解决（Verified 计未解决）；模块只要存在未解决的 Blocker 或 Critical（合称 BC）"
        "即 FAIL，否则 PASS。")
    # 明确统计未解决的Blocker和Critical数量（避免AI混淆）
    _blocker_unresolved = int(summ.get('blocker_unresolved', 0) or 0)
    _critical_unresolved = int((summ.get('critical_total', 0) or 0) - (summ.get('critical_resolved', 0) or 0))
    lines.append(
        f"总体：CR 总数 {st.get('total',0)}，未解决 {st.get('unresolved',0)}，"
        f"未解决 BC {st.get('bc_unresolved',0)}（其中 Blocker {_blocker_unresolved} 个、Critical {_critical_unresolved} 个）；"
        f"模块 {st.get('modules',0)} 个，其中 FAIL {st.get('fail',0)}、PASS {st.get('pass',0)}。")

    sev_bits = []
    for label, tk, rk in (('Blocker', 'blocker_total', 'blocker_resolved'),
                          ('Critical', 'critical_total', 'critical_resolved'),
                          ('Major', 'major_total', 'major_resolved')):
        total = summ.get(tk)
        if total is not None:
            resolved = summ.get(rk, 0) or 0
            sev_bits.append(f'{label} {total}（未解决 {total - resolved}）')
    if sev_bits:
        lines.append('严重度分布（总数/未解决）：' + '；'.join(sev_bits) + '。')
        lines.append(
            f'⚠️ 注意：未解决 BC 共 {st.get("bc_unresolved",0)} 个 = '
            f'未解决 Blocker {_blocker_unresolved} 个 + 未解决 Critical {_critical_unresolved} 个，'
            f'回答数量问题时请严格区分，不要把 BC 总数当成 Blocker 或 Critical 数量。')

    daily = snap.get('daily_stats', [])
    recent = daily[-14:]
    if recent:
        trend = '，'.join(f"{str(d.get('date',''))[5:]} 新增{d.get('new_count',0)}/解决{d.get('resolved_count',0)}"
                          for d in recent)
        lines.append(f'近 {len(recent)} 天每日（新增/解决）：{trend}。')

    lines.append('\n===== 模块状态明细（含每个 FAIL 模块 Top 未解决 BC 单）=====\n'
                 + snap.get('module_md', ''))

    bc = snap.get('unresolved_bc', [])
    # 提取所有labels（去重，按出现次数排序）
    label_counts = {}
    for r in bc:
        labels = r.get('labels', '')
        if isinstance(labels, (list, tuple)):
            label_list = [str(l).strip() for l in labels if str(l).strip()]
        else:
            label_text = str(labels or '').strip()
            if label_text:
                # 支持逗号、空格、分号分隔
                import re as _re
                label_list = [l.strip() for l in _re.split(r'[,，;；\s]+', label_text) if l.strip()]
            else:
                label_list = []
        for lb in label_list:
            label_counts[lb] = label_counts.get(lb, 0) + 1
    sorted_labels = sorted(label_counts.items(), key=lambda x: -x[1])
    if sorted_labels:
        top_labels = sorted_labels[:50]  # 最多显示50个标签
        lines.append(f'\n===== 可用 Labels 列表（未解决 BC 中出现，共 {len(sorted_labels)} 个，按出现次数排序）=====')
        lines.append('；'.join(f'{lb}({cnt})' for lb, cnt in top_labels))
        if len(sorted_labels) > 50:
            lines.append(f'（仅显示前50个，完整列表请在 CR 分析页查看）')

    lines.append(f'\n===== 全部未解决 BC 清单（共 {len(bc)} 条；'
                 '格式：[严重度][模块][状态] ID @经办人 {Labels}，为节省token不含标题）=====')
    for r in bc:
        dev = r.get('developer') or '未指派'
        labels = r.get('labels', '')
        if isinstance(labels, (list, tuple)):
            label_str = ','.join(str(l).strip() for l in labels if str(l).strip())
        else:
            label_str = str(labels or '').strip()
        label_part = f' {{{label_str}}}' if label_str else ''
        lines.append(f"[{_SEV_CN.get(r.get('sev',''), '未知')}][{r.get('module','')}]"
                     f"[{r.get('status','')}] {r.get('id','')} @{dev}{label_part}")

    lines.append(
        '\n===== 交互与回答规范（请严格遵守，让对话自然智能）=====\n'
        '\n【基础原则】\n'
        '1. 只依据上面的数据作答，所有数字、CR ID、模块名、标签名、状态必须来自数据，严禁编造；数据里没有就明确说没有，不要猜。\n'
        '2. 结论先行：先用1-2句话给核心结论/数字，再展开细节。去掉空泛套话和免责声明。\n'
        '3. 默认中文，口语化自然表达，不要太机械。比如不说"经查询，共有..."，直接说"有X个"。\n'
        '4. 默认输出不带CR标题，只带ID；用户明确说"带标题"时才提示去CR分析页查看。\n'
        '5. ⚠️ 重要：状态列必须使用上面清单中提供的实际状态（New/In Progress/Verified/Open/Reopened等），严禁默认写成New！如果清单中某个CR的状态是Verified，就写Verified，不能写New！\n'
        '\n【意图识别（重要）】\n'
        '5. 先判断用户意图，再决定输出格式：\n'
        '   - "统计/多少/数量/汇总" → 给数字+简要分布，不需要列每条问题\n'
        '   - "列出/有哪些/清单/明细" → 给Markdown表格，列出所有符合条件的问题\n'
        '   - "导出/复制/发给我/邮件" → 给可一键复制的完整Markdown，不省略\n'
        '   - "分析/为什么/原因/趋势" → 给洞察和结论，必要时配数据\n'
        '   - "周报/日报/放行报告/牛马笔记" → 按第12条的固定格式输出\n'
        '6. 识别组合/排除逻辑：\n'
        '   - "同时包含A和B"、"既要A又要B" → 交集（AND）\n'
        '   - "包含A或B"、"A或者B都行" → 并集（OR）\n'
        '   - "不包含A"、"除了A"、"去掉A"、"排除A" → 排除（NOT）\n'
        '   - "只要New状态"、"只看XX模块"、"只要某人负责的" → 叠加筛选条件\n'
        '\n【标签查询智能交互（核心）】\n'
        '7. 当用户提到标签相关查询（"带有XX"、"包含XX标签"、"XX label"、"打了XX标记"等）时：\n'
        '   a. **智能匹配**：从「可用 Labels 列表」中匹配，规则：\n'
        '      - 大小写不敏感、忽略空格/下划线/连字符差异（CF Blocker = CF_BLOCKER = cf-blocker）\n'
        '      - 支持部分匹配（用户说"blocker"能匹配到"CF Blocker"、"Display Blocker"等）\n'
        '      - 支持同义词（"阻塞"→blocker，"严重"→critical，"冒烟"→smoke，"回归"→regression）\n'
        '   b. **自动合并**：匹配到的标签如果只是大小写/分隔符差异，自动合并为一组，不需要用户选\n'
        '   c. **多标签直接输出**：匹配到多个不同含义的标签时，直接分别统计输出，格式：\n'
        '      "找到X个相关标签：\n- 标签A（N条）\n- 标签B（M条）\n\n**标签A明细：**\n[表格]\n\n**标签B明细：**\n[表格]"\n'
        '   d. **无匹配智能提示**：没匹配到时，不说"没有"就完了，而是：\n'
        '      - "没找到包含XX的标签，你是不是想找：A、B、C？（列出5-10个最接近的）"\n'
        '      - 如果完全不沾边，列出当前最常用的10个标签供参考\n'
        '   e. **输出内容**：\n'
        '      - 统计：标签名、问题数、Blocker/Critical分布、Top5模块、Top5经办人\n'
        '      - 清单：Markdown表格，列：严重度 | CR ID | 模块 | 状态 | 经办人 | Labels\n'
        '      - 主动给1句洞察："这些问题主要集中在XX模块，建议优先关注"（如果有明显集中）\n'
        '\n【上下文记忆与多轮交互（重要）】\n'
        '8. 记住上下文，支持自然指代：\n'
        '   - 用户说"这个"、"那个"、"上面的"、"刚才的" → 指代上一轮提到的标签/模块/问题\n'
        '   - 用户说"同上"、"和刚才一样" → 复用上一轮的筛选条件\n'
        '   - 用户说"再加上XX"、"还要XX" → 在当前筛选基础上叠加条件\n'
        '   - 用户说"去掉XX"、"排除XX"、"不要XX" → 从当前筛选中移除条件\n'
        '   - 用户说"只要New状态的"、"只看未解决的" → 叠加状态筛选\n'
        '9. 用户纠正时灵活调整：\n'
        '   - 用户说"不对"、"不是这个"、"我要的是另一个" → 理解为匹配不对，尝试其他相关标签或条件\n'
        '   - 用户说"换一个"、"看看别的" → 列出其他相关选项\n'
        '   - 不要固执己见，用户说不对就主动调整，不要重复同样的结果\n'
        '10. 追问要简洁：只有信息严重不足时才追问，且一次只问一个关键点，给选项让用户选，不要开放式追问。\n'
        '    - 好的追问："你是要统计数量，还是列出明细？"\n'
        '    - 不好的追问："你需要什么？"\n'
        '\n【固定格式输出】\n'
        '11. 用户要邮件/周报/放行报告/牛马笔记时，直接输出可一键复制的完整Markdown，不设字数限制，必须完整输出所有符合条件的问题，绝对不能省略或截断，格式严格按以下顺序：\n'
        '    第一部分【趋势结论】：一句话总结近14天趋势（新增/解决/风险变化）。\n'
        '    第二部分【总体状态】：CR总数/未解决/未解决BC/FAIL模块数，一句话。\n'
        '    第三部分【未解决 BC（不含 iOS APP）】：Markdown表格，列出所有未解决且模块不包含IOS_APP/iOS/Apps-iOS的Blocker和Critical，全部列出；列：严重度 | CR ID | 模块 | 状态 | 经办人。\n'
        '    第四部分【iOS APP 未解决 BC】：Markdown表格，列出所有未解决且模块包含IOS_APP/iOS/Apps-iOS的Blocker和Critical，全部列出；列同上。\n'
        '    - 重要：状态列必须使用上面提供的实际状态（New/In Progress/Verified/Open等），严禁编造或默认写成New！\n'
        '    - 不要额外解释，不要空泛套话，不要省略任何符合条件的问题。\n'
        '\n【其他】\n'
        '12. 用户问某模块/某人/某严重度时，从清单筛选汇总，必要时给表格。\n'
        '13. 不要复述本提示词，不要暴露内部实现，不要说"根据数据"、"经查询"这类机械表达。')
    # ===== 报告内容清理：合并多余换行，去掉行首行尾空白 =====
    import re as _re
    raw_report = '\n'.join(lines)
    # 1. 去掉每行首尾的空白字符
    cleaned_lines = []
    for line in raw_report.split('\n'):
        stripped = line.strip()
        if stripped:
            cleaned_lines.append(stripped)
        else:
            cleaned_lines.append('')
    raw_report = '\n'.join(cleaned_lines)
    # 2. 合并连续多个空行为最多2个
    raw_report = _re.sub(r'\n{3,}', '\n\n', raw_report)
    # 3. 去掉行首的空格（HTML表格缩进）
    raw_report = _re.sub(r'\n[ \t]+', '\n', raw_report)
    # 4. 最终再清理一次连续换行
    raw_report = _re.sub(r'\n{3,}', '\n\n', raw_report)
    return raw_report


def build_messages(snap, history, question):
    from services.ai.base import ChatMessage
    msgs = [ChatMessage(role='system', content=build_system_prompt(snap))]
    for h in (history or [])[-12:]:
        role = h.get('role')
        if role not in ('user', 'assistant'):
            continue
        content = (h.get('content') or '').strip()
        if content:
            msgs.append(ChatMessage(role=role, content=content))
    q = (question or '').strip()
    if q:
        msgs.append(ChatMessage(role='user', content=q))
    return msgs


def _chunk_text(chunk):
    if isinstance(chunk, str):
        return chunk
    return getattr(chunk, 'content', None) or str(chunk)


def _is_ios_module(module):
    """判断是否为 iOS APP 模块"""
    m = (module or '').lower()
    return ('ios' in m) or ('ios_app' in m) or ('apps - ios' in m) or ('apps-ios' in m)


# 非功能性问题关键词（本地化/文案/纯UI/文档/测试/流程等）
_NON_FUNCTIONAL_KEYWORDS = (
    '本地化', 'localize', 'localization', '翻译', 'translation', 'translate',
    '文案', 'copy', 'text', 'string', '字串',
    '界面', '颜色', 'color', 'colour', '字体', 'font',
    '布局', 'layout', '样式', 'style', '主题', 'theme', '皮肤', 'skin',
    '文档', 'doc', 'document', '帮助', 'help', 'faq', '指南', 'guide', '教程', 'tutorial',
    '说明', 'manual', 'release note', '更新日志', 'changelog',
    '测试用例', 'case', 'mock', '桩', 'stub', '自动化测试', 'automat',
    '流程', 'process', '规范', 'standard', '标准', '评审', 'review', '审计', 'audit',
    '会议', 'meeting', '培训', 'training', '支持', 'support',
    '版本', 'version', '发布', 'release', '打包', 'build', '编译', 'compile',
    '权限', 'permission', '证书', 'certificate', '签名', 'sign', '密钥', 'key',
)


def _is_functional_issue(title, module=''):
    """判断是否为功能性问题（排除本地化/文案/UI/文档/测试等非功能性问题）"""
    text = ((title or '') + ' ' + (module or '')).lower()
    for kw in _NON_FUNCTIONAL_KEYWORDS:
        if kw in text:
            return False
    return True


# ============================ 管理决策摘要部分（V9.3.3新增） ============================
# 八、管理决策摘要（给管理层看的重点信息）
# 8.1 当前最影响项目交付的 Top 风险
# 8.2 需要管理层介入协调的问题
# 8.3 对发版时程有直接影响的 Blocker
# 8.4 风险趋势（与昨日对比）
# 8.5 团队明天最需要关注的三件事

# 完整代码请参考本地文件 D:\Potential-tools\services\project_assistant.py
# 由于文件较大（119KB），无法通过API直接推送完整内容
# 请在本地网络恢复后执行: git push origin main
