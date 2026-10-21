# -*- coding: utf-8 -*-
"""
Excel 周报自动生成模块

功能：
1. 每周一自动创建新的 sheet 页（格式：2026W41）
2. 在 CR trend 后面创建
3. 从 CR 分析中提取数据，转换为准确简短的英文
4. 填入到 Excel 表格中

模板结构：
- Executive Summary
- ## SW Development Progress
  - CF ETA: xx/xx
  - Next milestone SW RRR: xx/xx
- Key Issues
  - [High-Risk] ...
  - RCA: ...
  - Action: ...
"""
import os
import json
import logging
import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'excel_weekly_config.json')


# ============================ 配置管理 ============================
def load_config() -> Dict:
    """加载 Excel 周报配置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载配置失败: {e}")
    return {
        'sharepoint_url': '',
        'file_name': 'Santos_26_SWPD_Workbook.xlsx',
        'project_key': 'EKSANTOS',
        'cf_eta': '',
        'next_milestone': '',
        'auto_create_monday': True,
        'enabled': False,
    }


def save_config(config: Dict) -> bool:
    """保存 Excel 周报配置"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return False


# ============================ 周数计算 ============================
def get_week_label(date: Optional[datetime.date] = None) -> str:
    """获取周标签，格式：2026W41"""
    if date is None:
        date = datetime.date.today()
    year, week, _ = date.isocalendar()
    return f"{year}W{week:02d}"


def get_monday_of_week(date: Optional[datetime.date] = None) -> datetime.date:
    """获取指定日期所在周的周一"""
    if date is None:
        date = datetime.date.today()
    return date - datetime.timedelta(days=date.weekday())


# ============================ 从 CR 分析提取数据 ============================
def extract_cr_data(project_key: str) -> Dict:
    """
    从项目状态助手的快照中提取 CR 数据

    返回：
    {
        'total': 总数,
        'unresolved': 未解决,
        'bc_count': 未解决BC,
        'blocker_count': Blocker数量,
        'fail_modules': FAIL模块数,
        'top_blockers': [Top Blocker列表],
        'ios_blockers': [iOS APP Blocker列表],
        'trend': 趋势描述,
    }
    """
    from services.project_assistant import load_snapshot, snapshot_age_hours

    snap = load_snapshot(project_key)
    if not snap:
        return {'error': '项目状态尚未生成，请先在项目助手中拉取数据'}

    # 快照新鲜度信息
    generated_at = snap.get('generated_at', '')
    age_hours = snapshot_age_hours(snap)
    is_fresh = age_hours <= 24  # 24小时内算新鲜

    stats = snap.get('stats', {})
    modules = snap.get('modules', [])
    unresolved_bc = snap.get('unresolved_bc', [])
    daily_stats = snap.get('daily_stats', [])

    # 统计 Blocker
    blocker_list = []
    ios_blocker_list = []
    for it in unresolved_bc:
        if it.get('sev') == 'blocker':
            module = it.get('module', '')
            if 'ios' in module.lower() or 'ios_app' in module.lower():
                ios_blocker_list.append(it)
            else:
                blocker_list.append(it)

    # 趋势
    trend = ''
    if daily_stats and len(daily_stats) >= 2:
        yesterday = daily_stats[-2]
        today = daily_stats[-1]
        delta_new = today.get('new_count', 0) - yesterday.get('new_count', 0)
        delta_resolved = today.get('resolved_count', 0) - yesterday.get('resolved_count', 0)
        net_change = delta_new - delta_resolved
        if net_change < 0:
            trend = f"Improving (resolved {abs(net_change)} more than new)"
        elif net_change > 0:
            trend = f"Worsening (new {net_change} more than resolved)"
        else:
            trend = "Stable"

    return {
        'total': stats.get('total', 0),
        'unresolved': stats.get('unresolved', 0),
        'bc_count': stats.get('bc_unresolved', 0),
        'blocker_count': len(blocker_list) + len(ios_blocker_list),
        'non_ios_blocker_count': len(blocker_list),
        'ios_blocker_count': len(ios_blocker_list),
        'fail_modules': stats.get('fail', 0),
        'pass_modules': stats.get('pass', 0),
        'top_blockers': blocker_list[:5],
        'ios_blockers': ios_blocker_list[:5],
        'trend': trend,
        'project_name': snap.get('project_name', ''),
        # 快照信息
        'snapshot_generated_at': generated_at,
        'snapshot_age_hours': age_hours,
        'snapshot_is_fresh': is_fresh,
    }


# ============================ AI 总结和翻译 ============================
def _ai_summarize_and_translate(issues: List[Dict], total_blocker: int, 
                                  ios_count: int, non_ios_count: int) -> Dict:
    """
    使用AI总结问题内容并翻译成英文，生成RCA和Action

    Returns:
        {
            'key_issues': 'Key Issues的英文总结（含RCA和ACT）',
            'device_remarks': 'Device Function Remarks的英文总结',
        }
    """
    try:
        from services.ai.factory import get_ai_service
        from services.ai.base import ChatMessage

        ai = get_ai_service()
        if not ai:
            logger.warning("AI服务未配置，使用默认模板")
            return _get_default_summary(issues, total_blocker, ios_count, non_ios_count)

        # 构建问题列表（最多5个，每个都要单独生成Key Issue）
        issue_list = []
        for idx, it in enumerate(issues[:5], 1):
            issue_list.append(f"Issue {idx}: {it.get('id', '')} - {it.get('title', '')} (Module: {it.get('module', '')}, Status: {it.get('status', '')})")

        issue_text = '\n'.join(issue_list) if issue_list else "No specific issues"
        num_issues = min(len(issues), 5)

        # 构建AI提示词 - 为每个问题单独生成Key Issue
        prompt = f"""You are a professional project manager. Analyze the following blocker issues and generate detailed Key Issues for a weekly report.

ISSUES ({total_blocker} total blockers: {ios_count} iOS APP + {non_ios_count} other modules):
{issue_text}

REQUIREMENTS:
1. Generate ONE Key Issue for EACH of the {num_issues} issues listed above. Do NOT combine them.
2. Each Key Issue must include:
   - Issue summary: 1 concise English sentence describing the problem (NO Chinese)
   - RCA (Root Cause Analysis): Based on the issue title, infer the most likely root cause in 1 short English sentence. If unclear, say "Under investigation"
   - ACT (Action): Recommend 1 specific action item in 1 short English sentence
3. Format for EACH issue exactly as:
[High-Risk] <CR-ID>: <issue summary>
•	RCA: <root cause>
•	ACT: <action>
4. Separate each issue with a blank line.
5. NO Chinese characters anywhere. Use only English.
6. Keep each issue brief and professional.

Also generate a brief English remark for the "Device Function" category (max 150 characters), summarizing the top 2 issues with their ACTUAL CR IDs and brief issue descriptions. 

EXAMPLE FORMAT (use actual CR IDs and issue descriptions, NOT placeholders):
"[EKSANTOS-9547] Heart rate data displayed without wearing watch; [EKSANTOS-9548] Blood oxygen sensor calibration error"

REQUIREMENTS:
- Use ACTUAL CR IDs from the issues list above, NEVER use "[CR-ID1]" or "[CR-ID2]" as placeholders
- Include a brief English description for each issue (3-8 words)
- Separate issues with "; "
- NO Chinese characters. Use only English.
- Put this on a separate line after all the Key Issues.
"""

        messages = [ChatMessage(role='user', content=prompt)]
        response = ai.chat(messages)
        content = getattr(response, 'content', None) or str(response)

        # ========== 解析 Key Issues（更健壮的解析逻辑） ==========
        lines = content.strip().split('\n')
        key_issues_parts = []
        current_issue = {'summary': '', 'rca': '', 'act': ''}
        in_device_remarks = False

        for line in lines:
            line = line.strip()
            if not line:
                # 空行：如果当前issue有内容，保存并开始新的
                if current_issue['summary']:
                    key_issues_parts.append(current_issue.copy())
                    current_issue = {'summary': '', 'rca': '', 'act': ''}
                continue

            # 检测 Device Remarks 部分（包含多个CR ID格式的行）
            if line.count('[') >= 2 and ';' in line and not line.startswith('[High-Risk]'):
                in_device_remarks = True
                # 保存当前issue
                if current_issue['summary']:
                    key_issues_parts.append(current_issue.copy())
                    current_issue = {'summary': '', 'rca': '', 'act': ''}
                continue

            if in_device_remarks:
                continue

            # 解析 Issue Summary（以 [High-Risk] 开头）
            if line.startswith('[High-Risk]'):
                current_issue['summary'] = line
            # 解析 RCA（支持多种格式：• RCA:, - RCA:, RCA:, •\tRCA:）
            elif 'RCA:' in line.upper() and ('ROOT' in line.upper() or line.strip().startswith('•') or line.strip().startswith('-') or line.strip().upper().startswith('RCA')):
                # 提取 RCA 内容
                rca_text = line
                for prefix in ['•\tRCA:', '• RCA:', '- RCA:', 'RCA:', 'rca:']:
                    if rca_text.lower().startswith(prefix.lower()):
                        rca_text = rca_text[len(prefix):].strip()
                        break
                current_issue['rca'] = f"•\tRCA: {rca_text}"
            # 解析 ACT（支持多种格式）
            elif ('ACT:' in line.upper() or 'ACTION:' in line.upper()) and (line.strip().startswith('•') or line.strip().startswith('-') or line.strip().upper().startswith('ACT') or line.strip().upper().startswith('ACTION')):
                # 提取 ACT 内容
                act_text = line
                for prefix in ['•\tACT:', '• ACT:', '- ACT:', 'ACT:', 'act:', 'Action:', 'action:']:
                    if act_text.lower().startswith(prefix.lower()):
                        act_text = act_text[len(prefix):].strip()
                        break
                current_issue['act'] = f"•\tACT: {act_text}"

        # 保存最后一个issue
        if current_issue['summary']:
            key_issues_parts.append(current_issue.copy())

        # 去重：根据 summary 去除重复的 issue（忽略大小写、空格和标点差异）
        def normalize_summary(s):
            import re
            return re.sub(r'[^\w\s]', '', s.lower().strip())
        
        seen_summaries = set()
        unique_issues = []
        for issue in key_issues_parts:
            if issue['summary']:
                norm = normalize_summary(issue['summary'])
                if norm not in seen_summaries:
                    seen_summaries.add(norm)
                    unique_issues.append(issue)
        key_issues_parts = unique_issues

        # 格式化 Key Issues（确保每个issue都有RCA和ACT）
        key_issues_lines = []
        for idx, issue in enumerate(key_issues_parts):
            if not issue['summary']:
                continue
            key_issues_lines.append(issue['summary'])
            # 如果缺少RCA，使用默认值
            if issue['rca']:
                key_issues_lines.append(issue['rca'])
            else:
                key_issues_lines.append("•\tRCA: Under investigation")
            # 如果缺少ACT，使用默认值
            if issue['act']:
                key_issues_lines.append(issue['act'])
            else:
                key_issues_lines.append("•\tACT: Prioritize resolution and assign owner")
            # 问题之间添加空行
            if idx < len(key_issues_parts) - 1:
                key_issues_lines.append('')

        # ========== Device Remarks：直接从 issues 列表生成，不依赖 AI 返回 ==========
        # 从第一个 issue 的 ID 中提取项目前缀（如 EKSANTOS）
        project_prefix = 'EKSANTOS'
        if issues and issues[0].get('id'):
            first_id = issues[0]['id']
            if '-' in first_id:
                project_prefix = first_id.split('-')[0]
        device_remarks = _get_default_device_remarks(issues[:2], project_prefix)

        # 如果没有解析到任何 Key Issue，使用默认模板
        if not key_issues_lines:
            return _get_default_summary(issues, total_blocker, ios_count, non_ios_count)

        key_issues = '\n'.join(key_issues_lines)

        # 确保没有中文
        if _has_chinese(key_issues):
            logger.warning("AI返回的Key Issues包含中文，使用默认模板")
            return _get_default_summary(issues, total_blocker, ios_count, non_ios_count)

        if _has_chinese(device_remarks):
            device_remarks = _get_default_device_remarks(issues)

        return {
            'key_issues': key_issues,
            'device_remarks': device_remarks,
        }

    except Exception as e:
        logger.error(f"AI总结失败: {e}")
        return _get_default_summary(issues, total_blocker, ios_count, non_ios_count)


def _has_chinese(text: str) -> bool:
    """检查文本是否包含中文字符"""
    if not text:
        return False
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff':
            return True
    return False


def _get_default_summary(issues: List[Dict], total_blocker: int, 
                           ios_count: int, non_ios_count: int) -> Dict:
    """获取默认的英文总结（不使用AI）- 为每个问题单独生成Key Issue"""
    if total_blocker > 0 and issues:
        key_issues_parts = []
        # 为每个问题单独生成Key Issue（最多5个）
        for it in issues[:5]:
            cr_id = it.get('id', 'UNKNOWN')
            title = it.get('title', '')
            module = it.get('module', '')

            # 提取英文关键词作为简短描述
            english_words = [w for w in title.split() if w.isascii() and len(w) > 1 and not w.isdigit()][:10]
            brief = ' '.join(english_words) if english_words else ''

            # 如果英文单词太少，根据模块或关键词推断描述
            if len(english_words) < 3:
                brief = _infer_issue_description(title, module)

            # 根据模块推断RCA和ACT
            if 'ios' in module.lower() or 'ios' in title.lower():
                rca = "iOS app compatibility issue"
                act = "Debug iOS app and fix compatibility"
            elif 'android' in module.lower() or 'android' in title.lower():
                rca = "Android app compatibility issue"
                act = "Debug Android app and fix compatibility"
            elif 'ota' in title.lower() or 'upgrade' in title.lower():
                rca = "OTA upgrade mechanism failure"
                act = "Investigate OTA upgrade process and fix"
            elif 'bind' in title.lower() or 'pair' in title.lower():
                rca = "Device binding/pairing logic issue"
                act = "Review binding flow and fix synchronization"
            elif 'notification' in title.lower() or 'message' in title.lower():
                rca = "Notification delivery mechanism issue"
                act = "Debug notification pipeline and fix"
            else:
                rca = "Under investigation"
                act = "Prioritize resolution and assign owner"

            issue_text = (
                f"[High-Risk] {cr_id}: {brief}\n"
                f"•\tRCA: {rca}\n"
                f"•\tACT: {act}"
            )
            key_issues_parts.append(issue_text)

        key_issues = '\n\n'.join(key_issues_parts)
    else:
        key_issues = "[Good] No remaining CF blocker issues. Project is on track."

    return {
        'key_issues': key_issues,
        'device_remarks': _get_default_device_remarks(issues),
    }


def _infer_issue_description(title: str, module: str) -> str:
    """根据问题标题和模块推断英文问题描述"""
    title_lower = title.lower()
    module_lower = module.lower()

    # 根据关键词推断
    if 'heart' in title_lower or '心率' in title:
        return 'Heart rate monitoring malfunction'
    elif 'blood' in title_lower or '血氧' in title:
        return 'Blood oxygen measurement error'
    elif 'pressure' in title_lower or '血压' in title:
        return 'Blood pressure calibration issue'
    elif 'sleep' in title_lower or '睡眠' in title:
        return 'Sleep tracking inaccuracy'
    elif 'ota' in title_lower or '升级' in title or 'upgrade' in title_lower:
        return 'OTA upgrade failure'
    elif 'bind' in title_lower or '配对' in title or 'pair' in title_lower:
        return 'Device pairing synchronization issue'
    elif 'notification' in title_lower or '通知' in title:
        return 'Notification delivery failure'
    elif 'wear' in title_lower or '佩戴' in title:
        return 'Wearing status detection failure'
    elif 'sensor' in title_lower or '传感器' in title:
        return 'Sensor calibration error'
    elif 'battery' in title_lower or '电池' in title:
        return 'Battery drain or charging issue'
    elif 'display' in title_lower or '屏幕' in title or 'display' in title_lower:
        return 'Display or screen malfunction'
    elif 'bluetooth' in title_lower or '蓝牙' in title:
        return 'Bluetooth connection instability'
    elif 'gps' in title_lower or '定位' in title:
        return 'GPS positioning inaccuracy'
    elif 'ios' in module_lower:
        return 'iOS app compatibility issue'
    elif 'android' in module_lower:
        return 'Android app compatibility issue'
    else:
        return 'Functional defect under investigation'


def _get_default_device_remarks(issues: List[Dict], project_key: str = 'EKSANTOS') -> str:
    """获取默认的Device Remarks（英文）- 包含具体问题描述和正确的CR ID"""
    if not issues:
        return ""
    # 取前2个问题，生成包含具体问题描述的remarks
    remarks = []
    for it in issues[:2]:
        cr_id = it.get('id', '') or it.get('cr_id', '') or 'UNKNOWN'
        # 修复 CR ID 格式：如果是 CR-9547 格式，改成 EKSANTOS-9547
        if cr_id.startswith('CR-'):
            cr_id = f"{project_key}-{cr_id[3:]}"
        elif cr_id == 'UNKNOWN' or not cr_id:
            # 尝试从 title 或其他字段提取 CR ID
            title = it.get('title', '')
            import re
            match = re.search(r'([A-Z]+-\d+)', title)
            if match:
                cr_id = match.group(1)
            else:
                cr_id = f"{project_key}-UNKNOWN"
        
        title = it.get('title', '')
        module = it.get('module', '')

        # 尝试提取英文单词作为问题描述
        english_words = [w for w in title.split() if w.isascii() and len(w) > 1 and not w.isdigit()][:10]
        brief = ' '.join(english_words) if len(english_words) >= 3 else _infer_issue_description(title, module)

        remarks.append(f"[{cr_id}] {brief}")
    return '; '.join(remarks)


# ============================ 生成英文周报内容 ============================
def generate_weekly_content(cr_data: Dict, config: Dict) -> List[Tuple[str, str]]:
    """
    生成周报内容，返回 [(单元格, 内容), ...] 列表
    基于 2026W40 模板格式，全部使用英文

    模板结构：
    A1:D1 合并: Executive Summary
    F1: Mid Risk
    G1: After SR4
    A2:D3 合并: ## SW Development Progress + CF ETA + Next milestone
    A5:D5 合并: Key Issues
    A6:D7 合并: High-Risk 问题描述 + RCA + ACT
    D15: Device - Function 的 Remarks
    """
    rows = []

    # ===== A2:D3 合并: SW Development Progress =====
    cf_eta = config.get('cf_eta', 'TBD')
    next_milestone = config.get('next_milestone', 'TBD')
    sw_progress = f"## SW Development Progress\n- CF ETA: {cf_eta}, \n- Next milestone SW RRR: {next_milestone}"
    rows.append(('A2', sw_progress))

    # ===== 收集所有 blocker 问题 =====
    ios_count = cr_data.get('ios_blocker_count', 0)
    non_ios_count = cr_data.get('non_ios_blocker_count', 0)
    total_blocker = ios_count + non_ios_count
    all_issues = cr_data.get('ios_blockers', []) + cr_data.get('top_blockers', [])

    # ===== 使用AI总结和翻译 =====
    ai_result = _ai_summarize_and_translate(all_issues, total_blocker, ios_count, non_ios_count)
    key_issues = ai_result.get('key_issues', '')
    device_remarks = ai_result.get('device_remarks', '')

    # ===== Key Issues - 按行拆分，分别写入到 A6, A7, A8... =====
    # 模板中 A6 开始是 Key Issues 区域，每行一个单元格
    if key_issues:
        key_issue_lines = key_issues.split('\n')
        for idx, line in enumerate(key_issue_lines):
            cell_ref = f'A{6 + idx}'
            rows.append((cell_ref, line))

    # ===== D15: Device - Function 的问题描述（Remarks） =====
    if device_remarks:
        rows.append(('D15', device_remarks))

    return rows


def _summarize_issues(issues: List[Dict], category: str) -> str:
    """
    简要总结问题类型，转换为英文
    """
    if not issues:
        return "various issues"

    # 提取问题标题中的关键词
    keywords = []
    for it in issues[:3]:
        title = it.get('title', '')
        # 简单提取关键词（取前几个词）
        words = title.split()[:5]
        if words:
            keywords.append(' '.join(words).lower())

    if not keywords:
        return "various issues"

    # 去重
    unique_keywords = list(dict.fromkeys(keywords))
    if len(unique_keywords) == 1:
        return unique_keywords[0]
    elif len(unique_keywords) == 2:
        return f"{unique_keywords[0]} and {unique_keywords[1]}"
    else:
        return ', '.join(unique_keywords[:2]) + f", and {len(unique_keywords) - 2} more"


# ============================ Excel 操作（本地文件） ============================
def create_weekly_sheet_local(excel_path: str, week_label: str, rows: List[Tuple[str, str]], 
                               template_sheet: str = "2026W40") -> bool:
    """
    在本地 Excel 文件中创建新的 sheet 并填入数据
    使用复制模板的方式，保持模板的格式和合并单元格

    Args:
        excel_path: Excel 文件路径
        week_label: 周标签，如 "2026W41"
        rows: [(单元格, 内容), ...] 列表
        template_sheet: 模板 sheet 名称，默认 "2026W40"

    Returns:
        是否成功
    """
    try:
        import openpyxl
        from openpyxl.styles import Alignment
        from copy import copy

        # 打开工作簿
        wb = openpyxl.load_workbook(excel_path)

        # 检查模板是否存在
        if template_sheet not in wb.sheetnames:
            logger.error(f"模板 sheet {template_sheet} 不存在")
            return False

        # 如果目标 sheet 已存在，先删除
        if week_label in wb.sheetnames:
            logger.info(f"Sheet {week_label} 已存在，先删除")
            del wb[week_label]

        # 复制模板 sheet
        template_ws = wb[template_sheet]
        new_ws = wb.copy_worksheet(template_ws)
        new_ws.title = week_label

        # 找到 CR trend 的位置，移动新 sheet 到 CR trend 后面
        cr_trend_index = None
        for i, name in enumerate(wb.sheetnames):
            if 'cr trend' in name.lower():
                cr_trend_index = i
                break

        if cr_trend_index is not None:
            # 移动 sheet 到 CR trend 后面
            wb.move_sheet(week_label, offset=cr_trend_index + 1 - wb.sheetnames.index(week_label))

        # 替换模板中的内容
        for cell_ref, value in rows:
            try:
                cell = new_ws[cell_ref]
                cell.value = value
                # 设置自动换行，确保多行内容（如Key Issues的RCA/ACT）能完整显示
                if value and '\n' in str(value):
                    cell.alignment = Alignment(
                        wrap_text=True,
                        vertical='top',
                        horizontal='left'
                    )
            except Exception as e:
                logger.warning(f"设置单元格 {cell_ref} 失败: {e}")

        # 保存
        wb.save(excel_path)
        logger.info(f"成功创建 sheet {week_label}（基于模板 {template_sheet}）")
        return True

    except Exception as e:
        logger.error(f"创建 sheet 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================ 主入口 ============================
def generate_weekly_report(project_key: str = None, excel_path: str = None, week_label: str = None) -> Dict:
    """
    生成周报主入口

    Args:
        project_key: 项目 key
        excel_path: Excel 文件路径（本地）
        week_label: 周标签，如 "2026W41"

    Returns:
        结果字典
    """
    config = load_config()

    if project_key is None:
        project_key = config.get('project_key', 'EKSANTOS')

    if week_label is None:
        week_label = get_week_label()

    # 1. 提取 CR 数据
    cr_data = extract_cr_data(project_key)
    if 'error' in cr_data:
        return {'success': False, 'error': cr_data['error']}

    # 2. 生成周报内容
    rows = generate_weekly_content(cr_data, config)

    # 3. 如果提供了 Excel 路径，创建 sheet
    if excel_path and os.path.exists(excel_path):
        success = create_weekly_sheet_local(excel_path, week_label, rows)
        if success:
            return {
                'success': True,
                'week_label': week_label,
                'excel_path': excel_path,
                'rows_count': len(rows),
                'cr_data': cr_data,
            }
        else:
            return {'success': False, 'error': '创建 sheet 失败'}

    # 4. 没有 Excel 路径，返回内容预览
    return {
        'success': True,
        'week_label': week_label,
        'rows': rows,
        'cr_data': cr_data,
        'message': '未提供 Excel 文件路径，仅返回内容预览',
    }
