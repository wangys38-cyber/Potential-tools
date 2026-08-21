"""Excel 分析模块 — 从 app.py 提取"""
import re
import time
import gc
import logging
from date_utils import normalize_date

logger = logging.getLogger(__name__)

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
    from app import ExcelReader  # 延迟导入避免循环引用
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

    # 调试日志：输出表头和前3行数据（所有列），帮助排查列错位问题
    logger.info(f"[调试] 表头({len(headers)}列): {headers}")
    for di in range(min(3, len(data_rows))):
        sample = [str(c).strip() if c else '' for c in data_rows[di]]
        logger.info(f"[调试] 数据行{di}({len(sample)}列): {sample}")

    col_map = _detect_issue_columns(headers)
    
    # 调试日志：显示识别到的字段
    logger.info(f"字段识别结果: {col_map}")
    logger.info(f"Fix Version column: {col_map.get('fix_version', -1)}")
    if col_map.get('fix_version', -1) >= 0:
        logger.info(f"Fix Version header: {headers[col_map['fix_version']]}")
    logger.info(f"所有 headers: {headers}")

    # Severity 列有效性检测：如果检测到的 severity 列值不像 severity 等级，尝试查找其他列
    severity_warning = ''
    severity_col_idx = col_map.get('severity', -1)
    if severity_col_idx >= 0:
        # 采样前 30 行检查 severity 值是否有效
        sample_sev_values = []
        for row in data_rows[:30]:
            cells = [str(c).strip() if c else '' for c in row]
            sv = _safe_get(cells, severity_col_idx)
            if sv:
                sample_sev_values.append(sv)
        valid_count = sum(1 for v in sample_sev_values if _is_valid_severity_value(v))
        total_sampled = len(sample_sev_values)
        logger.info(f"[Severity检测] 列={headers[severity_col_idx]}(idx={severity_col_idx}), 采样={total_sampled}, 有效={valid_count}, 样本={sample_sev_values[:5]}")

        if total_sampled > 0 and valid_count == 0:
            # 所有采样值都不是有效的 severity 等级 → 可能列识别错误（HTML colspan/多行表头导致错位）
            old_header = headers[severity_col_idx] if severity_col_idx < len(headers) else f'列{severity_col_idx}'
            old_col_idx = severity_col_idx
            logger.warning(f"[Severity检测] 列 '{old_header}' 的值不像 severity 等级（样本: {sample_sev_values[:3]}），扫描所有列查找正确的 severity 数据")

            # 遍历所有列（包括超出 headers 长度的列），找到值匹配 severity 等级的列
            max_cols = max((len(data_rows[i]) for i in range(min(30, len(data_rows)))), default=len(headers))
            max_cols = max(max_cols, len(headers))
            best_col = -1
            best_valid_ratio = 0
            for ci in range(max_cols):
                if ci == old_col_idx:
                    continue
                col_values = []
                for row in data_rows[:30]:
                    cells = [str(c).strip() if c else '' for c in row]
                    val = _safe_get(cells, ci)
                    if val:
                        col_values.append(val)
                if not col_values:
                    continue
                col_valid = sum(1 for v in col_values if _is_valid_severity_value(v))
                col_ratio = col_valid / len(col_values)
                if col_ratio > 0.5 and col_ratio > best_valid_ratio:
                    best_valid_ratio = col_ratio
                    best_col = ci
                    logger.info(f"[Severity检测] 候选列 {ci} ({headers[ci] if ci < len(headers) else '无表头'}): 有效率={col_ratio:.0%}, 样本={col_values[:3]}")

            if best_col >= 0:
                col_map['severity'] = best_col
                new_header = headers[best_col] if best_col < len(headers) else f'列{best_col}'
                severity_warning = f"原 Severity 列 '{old_header}' 的值不是有效的严重等级（如: {sample_sev_values[:2]}），已自动切换到 '{new_header}' 列"
                logger.info(f"[Severity检测] ✅ 自动切换到列 {best_col} '{new_header}' (有效率={best_valid_ratio:.0%})")
            else:
                severity_warning = f"Severity 列 '{old_header}' 的值（如: {sample_sev_values[:3]}）不是标准的严重等级。支持: Blocker/Critical/Major/Minor/Trivial, P0-P4, 1-5, 严重/重要/一般/轻微/提示"
                logger.warning(f"[Severity检测] ❌ 未找到有效的 severity 列，保留原列")
    else:
        # 没有检测到 Severity 列 → 扫描所有列查找包含 severity 等级值的列
        logger.info("[Severity检测] 表头中未找到 Severity 列，扫描所有列查找 severity 数据")
        max_cols = max((len(data_rows[i]) for i in range(min(30, len(data_rows)))), default=0)
        max_cols = max(max_cols, len(headers))
        best_col = -1
        best_valid_ratio = 0
        for ci in range(max_cols):
            col_values = []
            for row in data_rows[:30]:
                cells = [str(c).strip() if c else '' for c in row]
                val = _safe_get(cells, ci)
                if val:
                    col_values.append(val)
            if not col_values:
                continue
            col_valid = sum(1 for v in col_values if _is_valid_severity_value(v))
            col_ratio = col_valid / len(col_values)
            if col_ratio > 0.5 and col_ratio > best_valid_ratio:
                best_valid_ratio = col_ratio
                best_col = ci
                logger.info(f"[Severity检测] 候选列 {ci} ({headers[ci] if ci < len(headers) else '无表头'}): 有效率={col_ratio:.0%}, 样本={col_values[:3]}")

        if best_col >= 0:
            col_map['severity'] = best_col
            new_header = headers[best_col] if best_col < len(headers) else f'列{best_col}'
            severity_warning = f"表头中未找到 Severity 列，已自动识别 '{new_header}' 列为严重程度数据"
            logger.info(f"[Severity检测] ✅ 自动识别列 {best_col} '{new_header}' 为 severity (有效率={best_valid_ratio:.0%})")

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
    # 状态分布统计
    unresolved_status_dist = {}  # 未关闭问题的状态分布
    blocker_unresolved_status_dist = {}  # Blocker未关闭问题的状态分布
    
    # 严重程度检测
    has_severity_col = col_map.get('severity', -1) >= 0
    
    for issue in issues:
        # Severity 统计 — 使用增强匹配函数
        sev_raw = issue.get('severity', '').strip()
        current_severity_level = ''
        if sev_raw:
            severity_values.add(sev_raw)
            matched = _match_severity_level(sev_raw)
            if matched:
                by_severity[matched] += 1
                current_severity_level = matched

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
            # 未关闭问题的状态分布统计
            status_raw = issue.get('status', '').strip()
            if status_raw:
                unresolved_status_dist[status_raw] = unresolved_status_dist.get(status_raw, 0) + 1
                # Blocker未关闭的状态分布
                if current_severity_level == 'blocker':
                    blocker_unresolved_status_dist[status_raw] = blocker_unresolved_status_dist.get(status_raw, 0) + 1
        
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
            sev = issue.get('severity', '').strip()
            status = issue.get('status', '').lower()
            matched = _match_severity_level(sev)
            if matched in ('blocker', 'critical') and any(kw in status for kw in ['resolved', 'fixed', 'closed', 'done', '已解决', '已关闭']):
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
        'blocker_unresolved': by_severity['blocker'] - by_severity_resolved['blocker'],
        'blocker_unresolved_rate': round((by_severity['blocker'] - by_severity_resolved['blocker']) / by_severity['blocker'] * 100, 1) if by_severity['blocker'] > 0 else 0,
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
        'unresolved_status_dist': unresolved_status_dist,
        'blocker_unresolved_status_dist': blocker_unresolved_status_dist,
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
            if _match_severity_level(issue.get('severity', '')) in ('blocker', 'critical')
            and not any(kw in issue.get('status', '').lower() for kw in ['resolved', 'fixed', 'closed', 'done', '已解决', '已关闭'])
        )
        bc_total = sum(
            1 for issue in issues
            if _match_severity_level(issue.get('severity', '')) in ('blocker', 'critical')
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
    
    # 已解决待验证的问题：Status 为 Resolved（已解决但未验证/未关闭）
    resolved_unverified = []
    for issue in issues:
        status = issue.get('status', '').lower().strip()
        # Resolved = 已解决待验证；排除 Verified/Closed/Done（已验证/已关闭）
        if status and ('resolved' in status or '已解决' in status) \
                and 'verified' not in status and 'closed' not in status \
                and 'done' not in status and '已关闭' not in status:
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
            if len(resolved_unverified) >= 50:
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
    # 不限制数量，导出全部数据用于趋势看板
    
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
        'severity_warning': severity_warning,
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


# Severity 级别匹配模式 — 支持多种格式
_SEVERITY_PATTERNS = {
    'blocker': [
        'blocker', 'block', 'fatal', '致命', '阻断', 'P0', 'S0',
        'urgent', '紧急', 'immediate', 'showstopper',
    ],
    'critical': [
        'critical', 'crit', '严重', '高', 'P1', 'S1',
        'high', '重要', 'major-high',
    ],
    'major': [
        'major', 'main', '中等', '一般', 'normal', 'P2', 'S2',
        'medium', 'moderate', '普通',
    ],
    'minor': [
        'minor', '低', '轻微', 'small', 'P3', 'S3',
        'low', 'less', 'minor-issue',
    ],
    'trivial': [
        'trivial', 'triv', '很小', '微小', '提示', 'P4', 'S4',
        'cosmetic', 'info', 'informational', 'suggestion', '建议',
    ],
}

# 数字 → severity 映射（1=最高, 5=最低）
_SEVERITY_NUM_MAP = {
    '1': 'blocker', '2': 'critical', '3': 'major', '4': 'minor', '5': 'trivial',
}

# 优先级 → severity 映射
_SEVERITY_PRIORITY_MAP = {
    'p0': 'blocker', 'p1': 'critical', 'p2': 'major', 'p3': 'minor', 'p4': 'trivial',
    's0': 'blocker', 's1': 'critical', 's2': 'major', 's3': 'minor', 's4': 'trivial',
    'highest': 'blocker', 'high': 'critical', 'medium': 'major', 'low': 'minor', 'lowest': 'trivial',
    '紧急': 'blocker', '高': 'critical', '中': 'major', '低': 'minor', '最低': 'trivial',
    '严重': 'critical', '一般': 'major', '轻微': 'minor', '提示': 'trivial',
}


def _match_severity_level(value):
    """
    将 severity 字段值匹配到标准级别。
    支持：英文关键词、中文、数字 1-5、P0-P4/S0-S4、High/Medium/Low
    返回: 'blocker'/'critical'/'major'/'minor'/'trivial' 或 None
    """
    if not value:
        return None
    v = str(value).strip()
    if not v:
        return None
    v_lower = v.lower().strip()

    # 1. 精确优先级映射 (P0-P4, S0-S4, High/Medium/Low 等)
    if v_lower in _SEVERITY_PRIORITY_MAP:
        return _SEVERITY_PRIORITY_MAP[v_lower]

    # 2. 纯数字 1-5
    if v.isdigit() and v in _SEVERITY_NUM_MAP:
        return _SEVERITY_NUM_MAP[v]

    # 3. 包含 P0-P4 / S0-S4 模式
    import re
    p_match = re.match(r'^[ps](\d)$', v_lower)
    if p_match:
        num = p_match.group(1)
        if num in _SEVERITY_NUM_MAP:
            return _SEVERITY_NUM_MAP[num]

    # 4. 关键词包含匹配
    for level, keywords in _SEVERITY_PATTERNS.items():
        for kw in keywords:
            if kw in v_lower:
                return level

    # 5. 中文数字
    cn_num_map = {'一': 'blocker', '二': 'critical', '三': 'major', '四': 'minor', '五': 'trivial'}
    if v in cn_num_map:
        return cn_num_map[v]

    return None


def _is_valid_severity_value(value):
    """检查值是否是有效的 severity 等级（能匹配到标准级别）"""
    return _match_severity_level(value) is not None


def _detect_issue_columns(headers):
    col_map = {}
    headers_lower = [str(h).lower().strip() for h in headers]

    for i, h in enumerate(headers_lower):
        # 问题编号 - 匹配 "key" 或 "issue key"（Jira 导出标准列名）
        if h == 'key' or h == 'issue key':
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


# ============================================================
# 高性能分析（pandas 版）— 适用于大文件（>10MB）
# ============================================================

def _analyze_issue_sheet_fast(file_path, sheet_name, progress_cb=None):
    """使用 pandas 的高性能分析，适合大文件。

    Args:
        file_path: Excel 文件路径
        sheet_name: 要分析的 sheet 名
        progress_cb: 进度回调函数 progress_cb(percent, message)

    Returns:
        与 _analyze_issue_sheet 相同格式的结果字典
    """
    import time
    import gc
    import pandas as pd

    t0 = time.time()
    _log_mem("Fast分析开始：pandas读取Excel")

    if progress_cb:
        progress_cb(5, "正在读取Excel文件...")

    # pandas 读取（dtype=str 避免类型推断，na_filter=False 避免空值被转NaN）
    try:
        df = pd.read_excel(
            file_path,
            sheet_name=sheet_name,
            engine='openpyxl',
            dtype=str,
            na_filter=False
        )
    except Exception as e:
        logger.error(f"pandas读取失败，回退到openpyxl: {e}")
        return _analyze_issue_sheet(file_path, sheet_name)

    _log_mem(f"pandas读取完成：{len(df)}行 x {len(df.columns)}列")
    if progress_cb:
        progress_cb(20, f"读取完成，共 {len(df)} 行，正在分析...")

    if df.empty or len(df) < 1:
        return {
            'summary': {}, 'severity_values': [], 'severity_detected': False,
            'module_stats': {}, 'dev_stats': {}, 'daily_stats': [],
            'suggestions': [], 'unverified_issues': [], 'detected_columns': {},
            'sample_data': [], 'headers': list(df.columns)
        }

    headers = [str(c).strip() if c else '' for c in df.columns]
    col_map = _detect_issue_columns(headers)
    logger.info(f"Fast字段识别: {col_map}")

    # Severity 列有效性检测（采样前30行）
    severity_warning = ''
    severity_col_idx = col_map.get('severity', -1)
    if severity_col_idx >= 0 and severity_col_idx < len(headers):
        sample_sev = df.iloc[:30, severity_col_idx].astype(str).str.strip()
        sample_sev = sample_sev[sample_sev != '']
        valid_count = sum(1 for v in sample_sev if _is_valid_severity_value(v))
        if len(sample_sev) > 0 and valid_count == 0:
            # 扫描所有列找正确的 severity
            best_col, best_ratio = -1, 0
            for ci in range(len(headers)):
                if ci == severity_col_idx:
                    continue
                col_vals = df.iloc[:30, ci].astype(str).str.strip()
                col_vals = col_vals[col_vals != '']
                if len(col_vals) == 0:
                    continue
                col_valid = sum(1 for v in col_vals if _is_valid_severity_value(v))
                ratio = col_valid / len(col_vals)
                if ratio > 0.5 and ratio > best_ratio:
                    best_ratio, best_col = ratio, ci
            if best_col >= 0:
                col_map['severity'] = best_col
                severity_warning = f"已自动切换到 '{headers[best_col]}' 列"
            else:
                severity_warning = "Severity列值不标准"
    elif severity_col_idx < 0:
        # 未检测到，扫描所有列
        best_col, best_ratio = -1, 0
        for ci in range(len(headers)):
            col_vals = df.iloc[:30, ci].astype(str).str.strip()
            col_vals = col_vals[col_vals != '']
            if len(col_vals) == 0:
                continue
            col_valid = sum(1 for v in col_vals if _is_valid_severity_value(v))
            ratio = col_valid / len(col_vals)
            if ratio > 0.5 and ratio > best_ratio:
                best_ratio, best_col = ratio, ci
        if best_col >= 0:
            col_map['severity'] = best_col
            severity_warning = f"已自动识别 '{headers[best_col]}' 列为严重程度"

    if progress_cb:
        progress_cb(35, "正在统计严重程度...")

    # 提取需要的列（避免处理全部列）
    def get_col(name):
        idx = col_map.get(name, -1)
        if idx >= 0 and idx < len(headers):
            return df.iloc[:, idx].astype(str).str.strip()
        return pd.Series([''] * len(df))

    col_id = get_col('id')
    col_title = get_col('title')
    col_module = get_col('module')
    col_severity = get_col('severity')
    col_status = get_col('status')
    col_developer = get_col('developer')
    col_created = get_col('created_date')
    col_resolved = get_col('resolved_date')
    col_closed = get_col('closed_date')
    col_fix_version = get_col('fix_version')
    col_resolution = get_col('resolution')

    total = len(df)

    # 严重程度统计（向量化）
    by_severity = {'blocker': 0, 'critical': 0, 'major': 0, 'minor': 0, 'trivial': 0}
    by_severity_resolved = {'blocker': 0, 'critical': 0, 'major': 0, 'minor': 0, 'trivial': 0}
    severity_values = set()
    severity_levels = col_severity.map(lambda x: _match_severity_level(x) if x else '')

    for level in by_severity:
        mask = severity_levels == level
        by_severity[level] = int(mask.sum())

    # 状态判断（向量化）
    status_lower = col_status.str.lower()
    resolved_mask = status_lower.str.contains('resolved|fixed|closed|done|已解决|已关闭', na=False, regex=True)
    resolved = int(resolved_mask.sum())

    # 严重程度已解决统计
    for level in by_severity_resolved:
        by_severity_resolved[level] = int((severity_levels == level) & resolved_mask).sum()

    severity_values = set(col_severity[col_severity != ''].unique())

    if progress_cb:
        progress_cb(55, "正在统计模块和研发...")

    # 模块统计（向量化 groupby）
    module_mask = col_module != ''
    module_data = pd.DataFrame({
        'module': col_module[module_mask],
        'resolved': resolved_mask[module_mask]
    })
    module_grouped = module_data.groupby('module')['resolved'].agg(['count', 'sum'])
    by_module = {}
    for mod, row in module_grouped.iterrows():
        by_module[mod] = {
            'total': int(row['count']),
            'resolved': int(row['sum']),
            'unresolved': int(row['count'] - row['sum'])
        }

    # 研发统计
    dev_mask = col_developer != ''
    dev_data = pd.DataFrame({
        'developer': col_developer[dev_mask],
        'module': col_module[dev_mask],
        'resolved': resolved_mask[dev_mask]
    })
    dev_grouped = dev_data.groupby('developer')['resolved'].agg(['count', 'sum'])
    dev_modules = dev_data.groupby('developer')['module'].apply(lambda x: list(set(x[x != '']))).to_dict()
    by_developer = {}
    for dev, row in dev_grouped.iterrows():
        by_developer[dev] = {
            'total': int(row['count']),
            'resolved': int(row['sum']),
            'unresolved': int(row['count'] - row['sum']),
            'modules': dev_modules.get(dev, [])
        }

    if progress_cb:
        progress_cb(75, "正在统计日期趋势...")

    # 日期统计（向量化）
    from date_utils import normalize_date
    daily_stats = {}

    created_dates = col_created[col_created != ''].map(normalize_date)
    created_dates = created_dates[created_dates != '']
    for d in created_dates:
        if d not in daily_stats:
            daily_stats[d] = {'new': 0, 'resolved': 0}
        daily_stats[d]['new'] += 1

    resolved_dates = col_resolved[col_resolved != ''].map(normalize_date)
    resolved_dates = resolved_dates[resolved_dates != '']
    for d in resolved_dates:
        if d not in daily_stats:
            daily_stats[d] = {'new': 0, 'resolved': 0}
        daily_stats[d]['resolved'] += 1

    daily_stats_list = [{'date': d, **v} for d, v in sorted(daily_stats.items())]

    if progress_cb:
        progress_cb(90, "正在生成建议和样本...")

    # 样本数据（前20行）
    sample_data = []
    for i in range(min(20, total)):
        sample_data.append({
            'id': col_id.iloc[i],
            'title': col_title.iloc[i],
            'module': col_module.iloc[i],
            'severity': col_severity.iloc[i],
            'status': col_status.iloc[i],
            'developer': col_developer.iloc[i],
        })

    # 未验证问题（状态包含 unverified/待验证）
    unverified_mask = status_lower.str.contains('unverified|待验证|reopened|重新打开', na=False, regex=True)
    unverified_issues = []
    for i in df.index[unverified_mask][:50]:
        unverified_issues.append({
            'id': col_id.loc[i],
            'title': col_title.loc[i],
            'module': col_module.loc[i],
            'severity': col_severity.loc[i],
            'status': col_status.loc[i],
            'developer': col_developer.loc[i],
        })

    # 已解决待验证问题（Status 为 Resolved，排除 Verified/Closed/Done）
    resolved_mask = status_lower.str.contains('resolved|已解决', na=False, regex=True) & \
                    ~status_lower.str.contains('verified|closed|done|已关闭', na=False, regex=True)
    resolved_unverified = []
    for i in df.index[resolved_mask][:50]:
        resolved_unverified.append({
            'issue_id': str(col_id.loc[i]),
            'title': str(col_title.loc[i]),
            'module': str(col_module.loc[i]),
            'severity': str(col_severity.loc[i]),
            'status': str(col_status.loc[i]),
            'developer': str(col_developer.loc[i]),
            'resolution': str(col_resolved.loc[i]) if 'resolution' in col_map else '',
            'create_date': str(col_created.loc[i]),
        })

    # 建议
    suggestions = []
    if severity_warning:
        suggestions.append(severity_warning)
    if total > 0 and by_severity['blocker'] > 0:
        suggestions.append(f"存在 {by_severity['blocker']} 个 Blocker 问题，需优先处理")
    if total > 0 and (total - resolved) / total > 0.5:
        suggestions.append(f"未解决率超过50%（{total - resolved}/{total}），建议加速修复")

    # 计算比率
    def calc_rate(count):
        return round(count / total * 100, 1) if total > 0 else 0

    bc_total = by_severity['blocker'] + by_severity['critical']
    bc_resolved = by_severity_resolved['blocker'] + by_severity_resolved['critical']
    bc_rate = round(bc_resolved / bc_total * 100, 1) if bc_total > 0 else 0

    summary = {
        'total_issues': total,
        'total_resolved': resolved,
        'total_unresolved': total - resolved,
        'resolution_rate': calc_rate(resolved),
        'blocker_total': by_severity['blocker'],
        'blocker_resolved': by_severity_resolved['blocker'],
        'critical_total': by_severity['critical'],
        'critical_resolved': by_severity_resolved['critical'],
        'major_total': by_severity['major'],
        'major_resolved': by_severity_resolved['major'],
        'minor_total': by_severity['minor'],
        'minor_resolved': by_severity_resolved['minor'],
        'trivial_total': by_severity['trivial'],
        'trivial_resolved': by_severity_resolved['trivial'],
        'bc_total': bc_total,
        'bc_resolved': bc_resolved,
        'bc_rate': bc_rate,
    }

    # all_issues（不限制数量，导出全部用于前端研发趋势等功能）
    all_issues_brief = []
    for i in range(total):
        all_issues_brief.append({
            'id': str(col_id.iloc[i]) if i < len(col_id) else '',
            'title': str(col_title.iloc[i]) if i < len(col_title) else '',
            'module': str(col_module.iloc[i]) if i < len(col_module) else '',
            'developer': str(col_developer.iloc[i]) if i < len(col_developer) else '',
            'status': str(col_status.iloc[i]) if i < len(col_status) else '',
            'severity': str(col_severity.iloc[i]) if i < len(col_severity) else '',
            'create_date': str(col_created.iloc[i]) if i < len(col_created) else '',
            'resolved_date': str(col_resolved.iloc[i]) if i < len(col_resolved) else '',
        })

    # 释放内存
    del df, module_data, dev_data
    gc.collect()

    elapsed = time.time() - t0
    _log_mem(f"Fast分析完成，耗时 {elapsed:.1f}s")
    if progress_cb:
        progress_cb(100, f"分析完成，耗时 {elapsed:.1f}s")

    return {
        'summary': summary,
        'severity_values': sorted(list(severity_values)),
        'severity_detected': col_map.get('severity', -1) >= 0,
        'module_stats': by_module,
        'dev_stats': by_developer,
        'daily_stats': daily_stats_list,
        'all_issues': all_issues_brief,
        'suggestions': suggestions,
        'unverified_issues': unverified_issues,
        'resolved_unverified': resolved_unverified,
        'detected_columns': col_map,
        'sample_data': sample_data,
        'headers': headers,
        'analysis_time': round(elapsed, 1),
    }

