# -*- coding: utf-8 -*-
"""项目状态同步到智能知识库模块。

将项目状态助手的快照自动同步到智能知识库，保持最新状态。
"""
import logging
from services.ai.knowledge_base import get_knowledge_base

logger = logging.getLogger(__name__)


def format_snapshot_for_kb(snap):
    """将项目状态快照格式化为知识库文档内容（Markdown）"""
    key = snap.get('project_key', '')
    name = snap.get('project_name', '')
    generated_at = snap.get('generated_at', '')
    total = snap.get('total', 0)
    stats = snap.get('stats', {}) or {}
    modules = snap.get('modules', []) or []
    unresolved_bc = snap.get('unresolved_bc', []) or []

    # KPI 指标
    unresolved = stats.get('unresolved', 0)
    bc_unresolved = stats.get('bc_unresolved', 0)
    fail = stats.get('fail', 0)
    pass_count = stats.get('pass', 0)

    # 健康度评分（同前端算法）
    score = 100
    bc_penalty = min(bc_unresolved * 5, 40)
    score -= bc_penalty
    rate_penalty = 0
    if total > 0:
        unresolved_rate = unresolved / total
        if unresolved_rate > 0.3:
            rate_penalty = min((unresolved_rate - 0.3) * 50, 20)
            score -= rate_penalty
    fail_penalty = 0
    total_modules = fail + pass_count
    if total_modules > 0:
        fail_rate = fail / total_modules
        if fail_rate > 0.2:
            fail_penalty = min((fail_rate - 0.2) * 50, 25)
            score -= fail_penalty
    blocker_count = 0
    for it in unresolved_bc:
        if str(it.get('severity') or '').lower() == 'blocker':
            blocker_count += 1
    blocker_penalty = min(blocker_count * 3, 15)
    score -= blocker_penalty
    score = max(0, min(100, round(score)))

    if score >= 80:
        health_status = '健康'
    elif score >= 60:
        health_status = '关注'
    else:
        health_status = '风险'

    lines = []
    lines.append('# 项目状态 - ' + name + '（' + key + '）')
    lines.append('')
    lines.append('**更新时间：** ' + str(generated_at))
    lines.append('**数据来源：** eDart/Jira 实时拉取')
    lines.append('**健康度评分：** ' + str(score) + '/100（' + health_status + '）')
    lines.append('')
    lines.append('## 一、核心指标')
    lines.append('')
    lines.append('| 指标 | 数值 |')
    lines.append('|------|------|')
    lines.append('| CR 总数 | ' + str(total) + ' |')
    lines.append('| 未解决 CR | ' + str(unresolved) + ' |')
    lines.append('| 未解决 BC（Blocker+Critical） | ' + str(bc_unresolved) + ' |')
    lines.append('| Blocker 数量 | ' + str(blocker_count) + ' |')
    lines.append('| FAIL 模块 | ' + str(fail) + ' |')
    lines.append('| PASS 模块 | ' + str(pass_count) + ' |')
    lines.append('')

    # 健康度评分构成
    lines.append('## 二、健康度评分构成')
    lines.append('')
    lines.append('| 项目 | 扣分 |')
    lines.append('|------|------|')
    lines.append('| 基础分 | 100 |')
    lines.append('| 未解决 BC 扣分（每个5分，最多40分） | -' + str(bc_penalty) + ' |')
    if rate_penalty > 0:
        lines.append('| 未解决 CR 占比扣分（超30%，最多20分） | -' + str(round(rate_penalty)) + ' |')
    if fail_penalty > 0:
        lines.append('| FAIL 模块比例扣分（超20%，最多25分） | -' + str(round(fail_penalty)) + ' |')
    lines.append('| Blocker 额外扣分（每个3分，最多15分） | -' + str(blocker_penalty) + ' |')
    lines.append('| **最终得分** | **' + str(score) + '** |')
    lines.append('')

    # 模块状态
    lines.append('## 三、模块状态')
    lines.append('')
    fail_modules = [m for m in modules if m.get('status') == 'FAIL']
    pass_modules = [m for m in modules if m.get('status') == 'PASS']
    lines.append('### FAIL 模块（' + str(len(fail_modules)) + '个）')
    lines.append('')
    if fail_modules:
        lines.append('| 模块 | CR总数 | 未解决 | BC数 |')
        lines.append('|------|--------|--------|------|')
        for m in fail_modules[:20]:
            lines.append('| ' + str(m.get('name', '')) + ' | ' + str(m.get('total', 0)) + ' | ' + str(m.get('unresolved', 0)) + ' | ' + str(m.get('bc', 0)) + ' |')
        if len(fail_modules) > 20:
            lines.append('| ... 还有 ' + str(len(fail_modules) - 20) + ' 个模块 | | | |')
    else:
        lines.append('无 FAIL 模块')
    lines.append('')
    lines.append('### PASS 模块（' + str(len(pass_modules)) + '个）')
    lines.append('')
    if pass_modules:
        lines.append('| 模块 | CR总数 | 未解决 | BC数 |')
        lines.append('|------|--------|--------|------|')
        for m in pass_modules[:20]:
            lines.append('| ' + str(m.get('name', '')) + ' | ' + str(m.get('total', 0)) + ' | ' + str(m.get('unresolved', 0)) + ' | ' + str(m.get('bc', 0)) + ' |')
        if len(pass_modules) > 20:
            lines.append('| ... 还有 ' + str(len(pass_modules) - 20) + ' 个模块 | | | |')
    else:
        lines.append('无 PASS 模块')
    lines.append('')

    # Top BC 问题
    lines.append('## 四、未解决 BC 问题清单（Top 20）')
    lines.append('')
    if unresolved_bc:
        lines.append('| CR ID | 标题 | 严重程度 | 状态 | 模块 |')
        lines.append('|-------|------|----------|------|------|')
        for it in unresolved_bc[:20]:
            cr_id = it.get('key') or it.get('id') or ''
            title = str(it.get('summary') or it.get('title') or '')[:60]
            severity = it.get('severity') or it.get('priority') or ''
            status = it.get('status') or ''
            module = it.get('module') or ''
            lines.append('| ' + str(cr_id) + ' | ' + title + ' | ' + str(severity) + ' | ' + str(status) + ' | ' + str(module) + ' |')
        if len(unresolved_bc) > 20:
            lines.append('| ... 还有 ' + str(len(unresolved_bc) - 20) + ' 个 BC 问题 | | | | |')
    else:
        lines.append('无未解决 BC 问题')
    lines.append('')

    lines.append('---')
    lines.append('*本文档由项目状态助手自动同步，数据更新时间：' + str(generated_at) + '*')

    return '\n'.join(lines)


def sync_to_knowledge_base(snap, user_id=1):
    """将项目状态快照同步到智能知识库，保持最新状态"""
    try:
        key = snap.get('project_key', '')
        name = snap.get('project_name', '')
        if not key:
            return False

        doc_id = 'project_status_' + key
        title = '项目状态 - ' + name + '（' + key + '）'
        content = format_snapshot_for_kb(snap)

        kb = get_knowledge_base(user_id)
        # 先删除旧文档（如果存在），确保最新状态
        try:
            kb.delete_document(doc_id)
        except Exception:
            pass
        # 添加新文档
        success = kb.add_document(doc_id, title, content, metadata={
            'category': '项目状态',
            'tags': '项目状态,' + key + ',自动同步',
            'source': 'project_assistant',
            'project_key': key,
            'project_name': name,
            'synced_at': snap.get('generated_at', ''),
        })

        if success:
            logger.info('项目状态已同步到知识库: %s', doc_id)
        return success
    except Exception as e:
        logger.warning('同步到知识库失败: %s', e, exc_info=True)
        return False
