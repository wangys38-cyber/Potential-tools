# -*- coding: utf-8 -*-
"""CR 项目状态总结服务

根据 CR 分析的 issues 明细，逐模块生成 pass/fail 状态总结：
- 判定口径：模块存在「未解决的 Blocker/Critical（BC）单」即 FAIL，否则 PASS
- 未解决口径与 CR 分析页 module_stats 一致：status 不含
  resolved/fixed/closed/done/已解决/已关闭（Verified 计为未关闭）
- BC 口径：severity 经 _match_severity_level 归一化为 blocker/critical

输出：
1. 模块放行状态总览表（不含每模块问题总数，仅保留判定所需的未解决 BC）
2. 每个 FAIL 模块单列 Top5 待解决问题（含严重度/状态/标题/CR单号）

同时提供写入牛马笔记的能力（固定 note_uid，每日覆盖更新）。
"""
import os
import sys
import datetime
from collections import defaultdict

# 复用项目自带的 severity 归一化，保证口径完全一致
try:
    from excel_analyzers import _match_severity_level
except Exception:  # 兜底：脚本方式直接运行时
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from excel_analyzers import _match_severity_level
    except Exception:
        def _match_severity_level(v):
            s = str(v or '').strip().lower()
            if s in ('blocker', 'p0', 's0', 'highest', '紧急', '1'):
                return 'blocker'
            if s in ('critical', 'p1', 's1', 'high', '高', '2'):
                return 'critical'
            if s in ('major', 'p2', 's2', 'medium', '中', '3'):
                return 'major'
            if s in ('minor', 'p3', 's3', 'low', '低', '4'):
                return 'minor'
            if s in ('trivial', 'p4', 's4', 'lowest', '最低', '5'):
                return 'trivial'
            return ''

# 已解决关键字（与 excel_analyzers.module_stats 口径一致，不含 verified）
_RESOLVED_KW = ('resolved', 'fixed', 'closed', 'done', '已解决', '已关闭')
_SEV_RANK = {'blocker': 0, 'critical': 1, 'major': 2, 'minor': 3, 'trivial': 4, '': 5}
_SEV_CN = {'blocker': 'Blocker', 'critical': 'Critical', 'major': 'Major',
           'minor': 'Minor', 'trivial': 'Trivial', '': '-'}

NOTE_UID = 'cr_status_summary_latest'
NOTE_CATEGORY = 'CR状态'
NOTE_TAGS = ['CR分析', '项目状态', '自动同步']
TOP_N = 5


def _is_resolved(status):
    s = str(status or '').lower()
    return any(k in s for k in _RESOLVED_KW)


def _issue_num(issue_id):
    """从 issue key（如 EKSANTOS-8384 / B2GID:329995）提取尾号，用于近似新旧排序。"""
    digits = ''.join(ch if ch.isdigit() else ' ' for ch in str(issue_id or '')).split()
    return int(digits[-1]) if digits else 0


def _g(issue, *keys, default=''):
    for k in keys:
        v = issue.get(k)
        if v not in (None, ''):
            return v
    return default


def _md_escape_cell(text):
    return str(text or '').replace('|', '/').replace('\n', ' ').strip()


def _short(text, n=60):
    t = _md_escape_cell(text)
    return t if len(t) <= n else t[:n] + '…'


def build_module_summary(issues, project_name='Santos', date_str=None, top_n=TOP_N):
    """聚合模块状态，返回 (markdown_str, stats_dict)。"""
    if date_str is None:
        date_str = datetime.date.today().strftime('%Y-%m-%d')

    mods = defaultdict(lambda: {
        'total': 0, 'unres': 0, 'bc_unres': 0, 'b_unres': 0, 'c_unres': 0,
        'open_issues': []
    })
    total = len(issues)
    total_unres = 0
    total_bc_unres = 0

    for it in issues:
        status_raw = str(_g(it, 'status') or '').strip()
        sev = _match_severity_level(_g(it, 'severity')) or ''
        resolved = _is_resolved(status_raw)
        module = str(_g(it, 'module', 'component', 'Component/s') or '(未分类)').strip() or '(未分类)'
        issue_id = str(_g(it, 'id', 'key', 'issue_id', 'Issue key')).strip()
        title = str(_g(it, 'title', 'summary', 'Summary')).strip()

        m = mods[module]
        m['total'] += 1
        if not resolved:
            total_unres += 1
            m['unres'] += 1
            if sev in ('blocker', 'critical'):
                total_bc_unres += 1
                m['bc_unres'] += 1
                if sev == 'blocker':
                    m['b_unres'] += 1
                else:
                    m['c_unres'] += 1
            # 仅收集未解决问题用于 Top N
            m['open_issues'].append({
                'id': issue_id, 'title': title, 'sev': sev,
                'status': status_raw or '-', 'num': _issue_num(issue_id),
            })

    # FAIL/PASS 与排序
    entries = [(name, d) for name, d in mods.items()]
    for name, d in entries:
        d['fail'] = d['bc_unres'] > 0
        # Top N：严重度高者优先，同级单号大（更新）优先
        d['open_issues'].sort(key=lambda x: (_SEV_RANK.get(x['sev'], 5), -x['num']))
        d['top_list'] = d['open_issues'][:top_n]
    entries.sort(key=lambda kv: (0 if kv[1]['fail'] else 1,
                                 -kv[1]['bc_unres'], -kv[1]['unres'], kv[0]))

    fail_entries = [(n, d) for n, d in entries if d['fail']]
    pass_entries = [(n, d) for n, d in entries if not d['fail']]
    fail_n, pass_n = len(fail_entries), len(pass_entries)

    md = []
    md.append(f"# {project_name} 项目 CR 状态总结（截至 {date_str}）\n")
    md.append(
        f"> 数据源：{project_name} ALL BUG (eDart) {date_str} 导出；判定口径：模块存在"
        f"**未解决的 Blocker/Critical（BC）单即 FAIL**，否则 PASS。"
        f"状态中 Verified 暂计为未关闭（与 CR 分析页口径一致）。\n"
    )

    # 一、总体概览
    md.append("## 一、总体概览\n")
    md.append("| 指标 | 数值 |")
    md.append("|---|--:|")
    md.append(f"| CR 总数 | {total} |")
    md.append(f"| 未解决（含 Verified） | {total_unres} |")
    md.append(f"| 未解决 BC（Blocker+Critical） | {total_bc_unres} |")
    md.append(f"| 模块总数 | {len(entries)} |")
    md.append(f"| ❌ FAIL 模块 | {fail_n} |")
    md.append(f"| ✅ PASS 模块 | {pass_n} |")
    md.append("")

    # 二、模块放行状态（精简，不含每模块总数）
    md.append("## 二、模块放行状态（FAIL 优先）\n")
    md.append("| 模块 | 状态 | 未解决 BC（B/C） |")
    md.append("|---|---|--:|")
    for name, d in entries:
        status = '❌ FAIL' if d['fail'] else '✅ PASS'
        bc = f"{d['bc_unres']}（B{d['b_unres']}/C{d['c_unres']}）" if d['bc_unres'] else '0'
        md.append(f"| {_md_escape_cell(name)} | {status} | {bc} |")
    md.append("")

    # 三、FAIL 模块 Top N 待解决问题
    md.append(f"## 三、FAIL 模块 Top{top_n} 待解决问题\n")
    if not fail_entries:
        md.append("当前无 FAIL 模块，所有模块均无未解决 Blocker/Critical。\n")
    for idx, (name, d) in enumerate(fail_entries, 1):
        md.append(
            f"### {idx}. ❌ {_md_escape_cell(name)}　"
            f"（未解决BC {d['bc_unres']}：B{d['b_unres']}/C{d['c_unres']}）\n"
        )
        md.append("| # | 严重度 | 状态 | 问题 | CR单号 |")
        md.append("|--:|---|---|---|---|")
        for i, p in enumerate(d['top_list'], 1):
            md.append(
                f"| {i} | {_SEV_CN.get(p['sev'], '-')} | {_md_escape_cell(p['status'])} "
                f"| {_short(p['title'])} | {p['id']} |"
            )
        md.append("")

    # 四、结论
    md.append("## 四、结论\n")
    md.append(
        f"- **{fail_n} 个模块未达放行标准（FAIL）**：仍有未解决 Blocker/Critical，"
        f"需在版本放行前清零，各模块 Top{top_n} 问题见第三节。"
    )
    md.append(
        f"- **{pass_n} 个模块当前无未解决 BC（PASS）**：无高优先级遗留，可进入下一阶段；"
        f"其中部分模块仍有 Major 及以下未关闭项，建议持续跟踪。"
    )
    md.append("- 建议优先处理 Blocker，其次 Critical；Reopened 项需复盘回归质量。")

    stats = {
        'project': project_name, 'date': date_str, 'total': total,
        'unresolved': total_unres, 'bc_unresolved': total_bc_unres,
        'modules': len(entries), 'fail': fail_n, 'pass': pass_n,
    }
    return '\n'.join(md), stats


def sync_to_notes(issues, user_id, project_name='Santos', date_str=None, top_n=TOP_N):
    """生成总结并写入（覆盖更新）牛马笔记，返回 (stats, note_dict, created)。"""
    import db
    markdown, stats = build_module_summary(issues, project_name, date_str, top_n=top_n)
    title = f"{project_name} 项目 CR 状态总结（截至 {stats['date']}）"

    existing = db.get_note_by_uid(user_id, NOTE_UID)
    created = existing is None
    if created:
        db.create_note(
            user_id, NOTE_UID, title=title, content=markdown,
            category=NOTE_CATEGORY, tags=NOTE_TAGS, pinned=True
        )
    else:
        db.update_note(
            user_id, NOTE_UID, title=title, content=markdown,
            category=NOTE_CATEGORY, tags=NOTE_TAGS, pinned=True
        )
    note = db.get_note_by_uid(user_id, NOTE_UID)
    return stats, note, created
