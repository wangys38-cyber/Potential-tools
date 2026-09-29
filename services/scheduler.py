"""
V9.2 自动化定时任务调度器
支持定时生成日报/周报、自动发送邮件
"""
import json
import os
import time
import threading
from datetime import datetime, timedelta

# 定时任务配置文件路径
SCHEDULER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "scheduler")
os.makedirs(SCHEDULER_DIR, exist_ok=True)
TASKS_FILE = os.path.join(SCHEDULER_DIR, "tasks.json")
LOGS_FILE = os.path.join(SCHEDULER_DIR, "logs.json")

# 任务类型
TASK_TYPE_DAILY_REPORT = "daily_report"
TASK_TYPE_WEEKLY_REPORT = "weekly_report"
TASK_TYPE_AGING_REPORT = "aging_report"
TASK_TYPE_ALERT_CHECK = "alert_check"
TASK_TYPE_DATA_REFRESH = "data_refresh"
# V9.3 新增任务类型
TASK_TYPE_CR_TIMEOUT = "cr_timeout_alert"          # CR超时提醒
TASK_TYPE_BLOCKER_ALERT = "blocker_alert"          # Blocker预警
TASK_TYPE_FAIL_MODULE = "fail_module_check"         # FAIL模块巡检
TASK_TYPE_MILESTONE = "milestone_tracking"         # 里程碑跟踪
TASK_TYPE_COMPETITOR = "competitor_analysis"       # 竞品分析


# 执行频率
FREQ_DAILY = "daily"
FREQ_WEEKLY = "weekly"
FREQ_HOURLY = "hourly"
FREQ_INTERVAL = "interval"


def _send_scheduler_email(to_emails, subject, html_content):
    """发送定时任务邮件（使用系统SMTP配置）"""
    try:
        import sys
        import os
        import base64
        # 添加项目根目录到路径
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db.config import get_config
        
        # 获取SMTP配置
        cfg = get_config('smtp_mail_config') or {}
        smtp_host = cfg.get('smtp_host', '')
        smtp_port = int(cfg.get('smtp_port', 587))
        username = cfg.get('username', '')
        # 密码是base64编码的，需要解码
        password = base64.b64decode(cfg.get('password', '')).decode('utf-8') if cfg.get('password') else ''
        use_tls = cfg.get('use_tls', True)
        from_name = cfg.get('from_name', 'Potential Tools')
        
        if not smtp_host or not username:
            return False, "SMTP未配置，请先在设置中配置邮箱"
        if not password:
            return False, "SMTP密码未配置，请在设置中填写邮箱密码/授权码"
        
        import smtplib
        import ssl
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.utils import formataddr
        from email.header import Header
        
        # 构建邮件
        msg = MIMEMultipart('alternative')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = formataddr((str(Header(from_name, 'utf-8')), username))
        msg['To'] = ', '.join(to_emails) if isinstance(to_emails, list) else to_emails
        
        # HTML正文
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        # 587端口强制使用TLS
        if smtp_port == 587:
            use_tls = True
        
        # 发送
        context = ssl.create_default_context()
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30, context=context)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            server.ehlo()
            if use_tls:
                server.starttls(context=context)
                server.ehlo()
        
        server.login(username, password)
        recipients = to_emails if isinstance(to_emails, list) else [to_emails]
        server.sendmail(username, recipients, msg.as_string())
        server.quit()
        
        return True, "邮件发送成功"
    except Exception as e:
        return False, f"邮件发送失败: {str(e)}"


def _send_feishu_notification(title, content):
    """发送飞书机器人通知"""
    try:
        import sys
        import os
        import json
        import time
        import hmac
        import hashlib
        import base64
        import urllib.request
        
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db.config import get_config
        
        # 获取飞书Webhook配置
        cfg = get_config('feishu_bot_config') or {}
        webhook_url = cfg.get('webhook_url', '')
        secret = cfg.get('secret', '')
        
        if not webhook_url:
            return False, "未配置飞书Webhook"
        
        # 计算签名（如果配置了secret）
        timestamp = int(time.time())
        message = {
            "msg_type": "text",
            "content": {
                "text": f"{title}\n\n{content}"
            }
        }
        
        if secret:
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
            sign = base64.b64encode(hmac_code).decode('utf-8')
            message["timestamp"] = str(timestamp)
            message["sign"] = sign
        
        # 发送请求
        data = json.dumps(message).encode('utf-8')
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('StatusCode') == 0 or result.get('code') == 0:
                return True, "飞书通知发送成功"
            else:
                return False, f"飞书通知失败: {result.get('msg', '未知错误')}"
                
    except Exception as e:
        return False, f"飞书通知失败: {str(e)}"


def _load_tasks():
    """加载所有定时任务"""
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_tasks(tasks):
    """保存定时任务"""
    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


def _load_logs():
    """加载执行日志"""
    if not os.path.exists(LOGS_FILE):
        return []
    try:
        with open(LOGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_log(log_entry):
    """保存执行日志（最多保留100条）"""
    logs = _load_logs()
    logs.insert(0, log_entry)
    logs = logs[:100]
    with open(LOGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def create_task(task_type, project_key, freq, time_str="18:00", weekday=4, 
                 interval_minutes=60, email_recipients=None, enabled=True, name="",
                 feishu_notify=False):
    """创建定时任务"""
    tasks = _load_tasks()
    task_id = f"task_{int(time.time() * 1000)}"
    
    task = {
        "id": task_id,
        "name": name or f"{task_type}_{project_key}",
        "type": task_type,
        "project_key": project_key,
        "freq": freq,
        "time": time_str,  # HH:MM格式，如"18:00"
        "weekday": weekday,  # 0=周一, 6=周日，仅weekly有效
        "interval_minutes": interval_minutes,  # 仅interval有效
        "email_recipients": email_recipients or [],
        "feishu_notify": feishu_notify,
        "enabled": enabled,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_run": None,
        "next_run": None,
        "run_count": 0,
        "success_count": 0,
        "fail_count": 0,
    }
    
    # 计算下次执行时间
    task["next_run"] = _calculate_next_run(task)
    
    tasks.append(task)
    _save_tasks(tasks)
    return task


def update_task(task_id, **kwargs):
    """更新定时任务"""
    tasks = _load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            for key, value in kwargs.items():
                if key in task:
                    task[key] = value
            task["next_run"] = _calculate_next_run(task)
            _save_tasks(tasks)
            return task
    return None


def delete_task(task_id):
    """删除定时任务"""
    tasks = _load_tasks()
    tasks = [t for t in tasks if t["id"] != task_id]
    _save_tasks(tasks)
    return True


def get_task(task_id):
    """获取单个定时任务"""
    tasks = _load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            return task
    return None


def get_all_tasks():
    """获取所有定时任务"""
    return _load_tasks()


def get_task_logs(task_id=None, limit=20):
    """获取执行日志"""
    logs = _load_logs()
    if task_id:
        logs = [log for log in logs if log.get("task_id") == task_id]
    return logs[:limit]


def _calculate_next_run(task):
    """计算任务下次执行时间"""
    now = datetime.now()
    
    if task["freq"] == FREQ_DAILY:
        # 每天固定时间执行
        hour, minute = map(int, task["time"].split(":"))
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run.strftime("%Y-%m-%d %H:%M:%S")
    
    elif task["freq"] == FREQ_WEEKLY:
        # 每周固定星期几固定时间执行
        hour, minute = map(int, task["time"].split(":"))
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = task["weekday"] - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_run += timedelta(days=days_ahead)
        return next_run.strftime("%Y-%m-%d %H:%M:%S")
    
    elif task["freq"] == FREQ_HOURLY:
        # 每小时执行
        next_run = now + timedelta(hours=1)
        return next_run.strftime("%Y-%m-%d %H:%M:%S")
    
    elif task["freq"] == FREQ_INTERVAL:
        # 按间隔执行
        next_run = now + timedelta(minutes=task["interval_minutes"])
        return next_run.strftime("%Y-%m-%d %H:%M:%S")
    
    return None


def _execute_task(task):
    """执行定时任务"""
    from services import project_assistant as pa
    
    result = {
        "task_id": task["id"],
        "task_name": task["name"],
        "task_type": task["type"],
        "project_key": task["project_key"],
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "running",
        "message": "",
    }
    
    try:
        if task["type"] == TASK_TYPE_DAILY_REPORT:
            # 生成日报
            report, err = pa.generate_daily_report(task["project_key"])
            if err:
                raise Exception(err)
            # 保存到笔记
            note, err = pa.save_daily_report_to_notes(task["project_key"])
            if err:
                raise Exception(err)
            result["message"] = f"日报已生成并保存: {note.get('title', '')}"
            
        elif task["type"] == TASK_TYPE_WEEKLY_REPORT:
            # 生成周报
            report, err = pa.generate_weekly_report(task["project_key"])
            if err:
                raise Exception(err)
            note, err = pa.save_weekly_report_to_notes(task["project_key"])
            if err:
                raise Exception(err)
            result["message"] = f"周报已生成并保存: {note.get('title', '')}"
            
        elif task["type"] == TASK_TYPE_AGING_REPORT:
            # 生成老化报告
            report, err = pa.generate_aging_report(task["project_key"])
            if err:
                raise Exception(err)
            result["message"] = "老化预警报告已生成"
            
        elif task["type"] == TASK_TYPE_ALERT_CHECK:
            # 预警检查
            alert_result = pa.check_project_alerts(task["project_key"])
            critical_count = alert_result.get("critical_count", 0)
            warning_count = alert_result.get("warning_count", 0)
            result["message"] = f"预警检查完成: {critical_count}个严重, {warning_count}个警告"
            
        elif task["type"] == TASK_TYPE_DATA_REFRESH:
            # 数据刷新（触发重新拉取CR数据）
            from services import project_assistant as pa
            try:
                # force=True 强制拉取最新数据，不使用缓存
                snap = pa.build_project_snapshot(task["project_key"], force=True)
                if not snap:
                    raise Exception("拉取数据失败")
                stats = snap.get("stats", {})
                total_crs = stats.get("total", 0)
                result["message"] = f"项目助手中的数据已刷新（CR总数 {total_crs} 条）"
                result["total_crs"] = total_crs
                result["bc_unresolved"] = stats.get("bc_unresolved", 0)
                result["fail_modules"] = stats.get("fail", 0)
            except Exception as e:
                raise Exception(f"拉取数据失败: {str(e)}")
        
        elif task["type"] == TASK_TYPE_CR_TIMEOUT:
            # CR超时提醒
            from services import project_assistant as pa
            snap = pa.load_snapshot(task["project_key"])
            if not snap:
                raise Exception("项目状态尚未生成")
            
            timeout_days = task.get("config", {}).get("timeout_days", 7)
            timeout_crs = []
            for m in snap.get("modules", []):
                for it in m.get("top_list", []):
                    if it.get("status") not in ["Resolved", "Closed"]:
                        timeout_crs.append({
                            "id": it.get("id", ""),
                            "title": it.get("title", ""),
                            "sev": it.get("sev", ""),
                            "module": m.get("module", ""),
                        })
            
            lines = []
            lines.append("# CR超时提醒")
            lines.append("")
            lines.append(f"**项目**: {snap.get('project_name', '')}")
            lines.append(f"**超时阈值**: {timeout_days}天")
            lines.append(f"**超时CR数量**: {len(timeout_crs)}")
            lines.append("")
            lines.append("## 超时CR列表")
            lines.append("")
            lines.append("| ID | 标题 | 严重程度 | 模块 |")
            lines.append("|------|------|----------|------|")
            for cr in timeout_crs[:20]:
                lines.append(f"| {cr['id']} | {cr['title'][:50]} | {cr['sev']} | {cr['module']} |")
            lines.append("")
            result["report_content"] = "\n".join(lines)
            result["message"] = f"CR超时提醒：共{len(timeout_crs)}条"
            result["timeout_count"] = len(timeout_crs)
            result["timeout_list"] = timeout_crs[:10]  # 前10条

        elif task["type"] == TASK_TYPE_BLOCKER_ALERT:
            # Blocker预警
            from services import project_assistant as pa
            snap = pa.load_snapshot(task["project_key"])
            if not snap:
                raise Exception("项目状态尚未生成")
            
            blocker_count = 0
            blocker_list = []
            for m in snap.get("modules", []):
                for it in m.get("top_list", []):
                    if it.get("status") not in ["Resolved", "Closed"] and it.get("sev") == "blocker":
                        blocker_count += 1
                        blocker_list.append(it)
            
            threshold = task.get("config", {}).get("threshold", 5)
            
            if blocker_count >= threshold:
                lines = []
                lines.append("# Blocker预警")
                lines.append("")
                lines.append(f"**项目**: {snap.get('project_name', '')}")
                lines.append(f"**Blocker数量**: {blocker_count}")
                lines.append(f"**预警阈值**: {threshold}")
                lines.append("")
                lines.append("| ID | 标题 | 模块 |")
                lines.append("|------|------|------|")
                for cr in blocker_list[:10]:
                    lines.append(f"| {cr.get('id','')} | {cr.get('title','')[:50]} | |")
                lines.append("")
                result["report_content"] = "\n".join(lines)
                result["message"] = f"Blocker预警：{blocker_count}个Blocker（超过阈值{threshold}）"
            else:
                result["message"] = f"Blocker数量{blocker_count}，未超过阈值{threshold}"

        elif task["type"] == TASK_TYPE_FAIL_MODULE:
            # FAIL模块巡检
            from services import project_assistant as pa
            snap = pa.load_snapshot(task["project_key"])
            if not snap:
                raise Exception("项目状态尚未生成")
            
            fail_modules = [m for m in snap.get("modules", []) if m.get("fail")]
            
            lines = []
            lines.append("# FAIL模块巡检报告")
            lines.append("")
            lines.append(f"**项目**: {snap.get('project_name', '')}")
            lines.append(f"**FAIL模块数量**: {len(fail_modules)}")
            lines.append("")
            lines.append("| 排名 | 模块 | 未解决BC | Blocker | Critical |")
            lines.append("|------|------|----------|---------|----------|")
            for i, m in enumerate(fail_modules[:10], 1):
                lines.append(f"| {i} | {m.get('module','')} | {m.get('bc',0)} | {m.get('b',0)} | {m.get('c',0)} |")
            lines.append("")
            result["report_content"] = "\n".join(lines)
            result["message"] = f"FAIL模块巡检：{len(fail_modules)}个FAIL模块"
            result["fail_count"] = len(fail_modules)
            result["fail_modules"] = fail_modules[:10]  # 前10个

        elif task["type"] == TASK_TYPE_MILESTONE:
            # 里程碑跟踪
            from services import project_assistant as pa
            snap = pa.load_snapshot(task["project_key"])
            if not snap:
                raise Exception("项目状态尚未生成")
            
            stats = snap.get("stats", {})
            lines = []
            lines.append("# 里程碑进度跟踪")
            lines.append("")
            lines.append(f"**项目**: {snap.get('project_name', '')}")
            lines.append("")
            lines.append("## 当前进度概览")
            lines.append("")
            lines.append(f"- CR总数: {stats.get('total', 0)}")
            lines.append(f"- 未解决: {stats.get('unresolved', 0)}")
            lines.append(f"- 未解决BC: {stats.get('bc_unresolved', 0)}")
            lines.append(f"- FAIL模块: {stats.get('fail', 0)}")
            lines.append(f"- PASS模块: {stats.get('pass', 0)}")
            lines.append("")
            result["report_content"] = "\n".join(lines)
            result["message"] = "里程碑跟踪完成"

        elif task["type"] == TASK_TYPE_COMPETITOR:
            # 竞品分析
            lines = []
            lines.append("# 竞品分析周报")
            lines.append("")
            lines.append("**分析周期**: 本周")
            lines.append("")
            lines.append("## 待收集信息")
            lines.append("")
            lines.append("1. 竞品新产品发布")
            lines.append("2. 竞品功能更新")
            lines.append("3. 竞品价格变动")
            lines.append("4. 竞品用户反馈")
            lines.append("5. 市场趋势变化")
            lines.append("")
            lines.append("*本报告为自动生成模板，需人工补充具体内容*")
            lines.append("")
            result["report_content"] = "\n".join(lines)
            result["message"] = "竞品分析周报已生成"
        
        # 如果配置了邮件收件人，发送邮件
        if task.get("email_recipients") and len(task["email_recipients"]) > 0:
            try:
                # 构建邮件内容
                type_names = {
                    "daily_report": "项目日报",
                    "weekly_report": "项目周报",
                    "aging_report": "老化预警报告",
                    "alert_check": "智能预警检查",
                    "data_refresh": "数据刷新",
                }
                report_type = type_names.get(task["type"], task["type"])
                subject = f"【{report_type}】{task['project_key']} - {datetime.now().strftime('%Y-%m-%d')}"
                
                # 尝试获取报告内容
                report_content = ""
                try:
                    if task["type"] == "daily_report":
                        from services import project_assistant as pa
                        report, err = pa.generate_daily_report(task["project_key"])
                        if report:
                            report_content = report if isinstance(report, str) else str(report)
                    elif task["type"] == "weekly_report":
                        from services import project_assistant as pa
                        report, err = pa.generate_weekly_report(task["project_key"])
                        if report:
                            report_content = report if isinstance(report, str) else str(report)
                except Exception as report_err:
                    report_content = f"<p>报告生成详情请查看系统。</p><p>错误: {report_err}</p>"
                
                if not report_content:
                    report_content = f"<h2>{report_type}</h2><p>项目: {task['project_key']}</p><p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"
                
                # 使用markdown库转换为HTML（不使用Markdown格式显示）
                try:
                    import markdown as _md
                    # 配置markdown，保留所有HTML标签（包括img、svg、style等）
                    html_body = _md.markdown(
                        report_content, 
                        extensions=['tables', 'fenced_code', 'nl2br', 'extra', 'sane_lists'],
                        extension_configs={
                            'extra': {},
                            'tables': {},
                            'fenced_code': {},
                            'nl2br': {},
                            'sane_lists': {},
                        },
                        output_format='html5'
                    )
                    report_content = html_body
                except Exception as md_err:
                    # 转换失败时用纯文本
                    import re as _re
                    report_content = _re.sub(r'[#*`>-]', '', report_content)
                    report_content = report_content.replace('\n', '<br>')
                
                html_email = f"""
                <div style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
                    <div style="background: linear-gradient(135deg, #8B5CF6, #6366F1); color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                        <h1 style="margin: 0; font-size: 20px;">{report_type}</h1>
                        <p style="margin: 5px 0 0 0; opacity: 0.9;">项目: {task['project_key']} | {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
                    </div>
                    <div style="background: #ffffff; padding: 24px; border-radius: 0 0 8px 8px; border: 1px solid #e5e7eb; color: #1f2937; font-size: 14px; line-height: 1.6;">
                        <style>
                            .report-content h1 {{ font-size: 20px; color: #111827; border-bottom: 2px solid #8B5CF6; padding-bottom: 8px; margin-top: 0; }}
                            .report-content h2 {{ font-size: 17px; color: #1f2937; margin-top: 20px; border-left: 4px solid #8B5CF6; padding-left: 10px; }}
                            .report-content h3 {{ font-size: 15px; color: #374151; margin-top: 16px; }}
                            .report-content p {{ margin: 8px 0; }}
                            .report-content table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }}
                            .report-content th {{ background: #f3f4f6; padding: 8px 10px; text-align: left; border: 1px solid #e5e7eb; font-weight: 600; }}
                            .report-content td {{ padding: 8px 10px; border: 1px solid #e5e7eb; }}
                            .report-content tr:nth-child(even) {{ background: #f9fafb; }}
                            .report-content ul, .report-content ol {{ margin: 8px 0; padding-left: 24px; }}
                            .report-content li {{ margin: 4px 0; }}
                            .report-content strong {{ color: #111827; }}
                            .report-content blockquote {{ border-left: 4px solid #8B5CF6; padding-left: 12px; color: #6b7280; margin: 12px 0; }}
                            .report-content code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
                        </style>
                        <div class="report-content">
                        {report_content}
                        </div>
                    </div>
                    <div style="text-align: center; color: #9ca3af; font-size: 12px; margin-top: 20px;">
                        此邮件由 Potential Tools 定时任务系统自动发送
                    </div>
                </div>
                """
                
                # 发送邮件
                success, msg = _send_scheduler_email(task["email_recipients"], subject, html_email)
                if success:
                    result["message"] += f"，邮件已发送给: {', '.join(task['email_recipients'])}"
                else:
                    result["message"] += f"，{msg}"
            except Exception as email_err:
                result["message"] += f"，邮件发送失败: {str(email_err)}"
        
        # 发送飞书通知（如果任务配置了飞书通知）
        if task.get("feishu_notify", False):
            try:
                # 构建详细的飞书通知内容
                feishu_lines = []
                feishu_lines.append(f"📊 {task.get('name', task['type'])}")
                feishu_lines.append("")
                
                # 根据任务类型添加详细内容
                if task["type"] == "cr_timeout_alert":
                    feishu_lines.append(f"⚠️ CR超时提醒")
                    feishu_lines.append(f"项目: {task['project_key']}")
                    feishu_lines.append(f"超时CR数量: {result.get('timeout_count', '未知')}")
                    if result.get('timeout_list'):
                        feishu_lines.append("")
                        feishu_lines.append("前5条超时CR:")
                        for i, cr in enumerate(result['timeout_list'][:5], 1):
                            feishu_lines.append(f"  {i}. {cr.get('id', '')} - {cr.get('title', '')[:30]}")
                
                elif task["type"] == "blocker_alert":
                    feishu_lines.append(f"🚨 Blocker预警")
                    feishu_lines.append(f"项目: {task['project_key']}")
                    feishu_lines.append(f"Blocker数量: {result.get('blocker_count', '未知')}")
                    feishu_lines.append(f"阈值: {result.get('threshold', '未知')}")
                
                elif task["type"] == "fail_module_check":
                    feishu_lines.append(f"🔍 FAIL模块巡检")
                    feishu_lines.append(f"项目: {task['project_key']}")
                    feishu_lines.append(f"FAIL模块数量: {result.get('fail_count', '未知')}")
                    if result.get('fail_modules'):
                        feishu_lines.append("")
                        feishu_lines.append("前5个FAIL模块:")
                        for i, m in enumerate(result['fail_modules'][:5], 1):
                            feishu_lines.append(f"  {i}. {m.get('module', '')} - BC:{m.get('bc', 0)}")
                
                elif task["type"] == "daily_report":
                    feishu_lines.append(f"📅 项目日报")
                    feishu_lines.append(f"项目: {task['project_key']}")
                    feishu_lines.append(f"CR总数: {result.get('total_crs', '未知')}")
                    feishu_lines.append(f"未解决BC: {result.get('bc_unresolved', '未知')}")
                    feishu_lines.append(f"FAIL模块: {result.get('fail_modules', '未知')}")
                
                elif task["type"] == "weekly_report":
                    feishu_lines.append(f"📈 项目周报")
                    feishu_lines.append(f"项目: {task['project_key']}")
                    feishu_lines.append(f"本周新增CR: {result.get('new_count', '未知')}")
                    feishu_lines.append(f"本周解决CR: {result.get('resolved_count', '未知')}")
                
                else:
                    feishu_lines.append(result.get("message", "任务执行完成"))
                
                feishu_content = "\n".join(feishu_lines)
                
                feishu_success, feishu_msg = _send_feishu_notification(
                    f"【定时任务通知】{task.get('name', task['type'])}",
                    feishu_content
                )
                if feishu_success:
                    result["message"] += "，飞书通知已发送"
                else:
                    result["message"] += f"，{feishu_msg}"
            except Exception as feishu_err:
                result["message"] += f"，飞书通知失败: {str(feishu_err)}"
        
        result["status"] = "success"
        result["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
    except Exception as e:
        result["status"] = "failed"
        result["message"] = f"执行失败: {str(e)}"
        result["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 保存日志
    _save_log(result)
    
    # 更新任务统计
    tasks = _load_tasks()
    for t in tasks:
        if t["id"] == task["id"]:
            t["last_run"] = result["started_at"]
            t["run_count"] = t.get("run_count", 0) + 1
            if result["status"] == "success":
                t["success_count"] = t.get("success_count", 0) + 1
            else:
                t["fail_count"] = t.get("fail_count", 0) + 1
            t["next_run"] = _calculate_next_run(t)
            break
    _save_tasks(tasks)
    
    return result


# 调度器后台线程
_scheduler_running = False
_scheduler_thread = None

def _scheduler_loop():
    """调度器主循环，每分钟检查一次"""
    global _scheduler_running
    while _scheduler_running:
        try:
            now = datetime.now()
            now_str = now.strftime("%Y-%m-%d %H:%M:%S")
            
            tasks = _load_tasks()
            for task in tasks:
                if not task.get("enabled", True):
                    continue
                if not task.get("next_run"):
                    continue
                
                # 检查是否到了执行时间（允许1分钟误差）
                next_run = datetime.strptime(task["next_run"], "%Y-%m-%d %H:%M:%S")
                if now >= next_run and (now - next_run).total_seconds() < 120:
                    # 执行任务（在新线程中执行，避免阻塞调度器）
                    exec_thread = threading.Thread(target=_execute_task, args=(task,))
                    exec_thread.daemon = True
                    exec_thread.start()
                    
                    # 立即更新next_run，避免重复执行
                    tasks_update = _load_tasks()
                    for t in tasks_update:
                        if t["id"] == task["id"]:
                            t["next_run"] = _calculate_next_run(t)
                            break
                    _save_tasks(tasks_update)
        
        except Exception as e:
            print(f"[Scheduler] Error: {e}")
        
        # 每分钟检查一次
        time.sleep(60)


def start_scheduler():
    """启动调度器"""
    global _scheduler_running, _scheduler_thread
    if _scheduler_running:
        return False
    
    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop)
    _scheduler_thread.daemon = True
    _scheduler_thread.start()
    print("[Scheduler] 定时任务调度器已启动")
    return True


def stop_scheduler():
    """停止调度器"""
    global _scheduler_running
    _scheduler_running = False
    print("[Scheduler] 定时任务调度器已停止")
    return True


def get_scheduler_status():
    """获取调度器状态"""
    return {
        "running": _scheduler_running,
        "total_tasks": len(_load_tasks()),
        "enabled_tasks": len([t for t in _load_tasks() if t.get("enabled", True)]),
    }


def run_task_now(task_id):
    """立即执行指定任务"""
    task = get_task(task_id)
    if not task:
        return None, "任务不存在"
    
    # 在新线程中执行
    exec_thread = threading.Thread(target=_execute_task, args=(task,))
    exec_thread.daemon = True
    exec_thread.start()
    
    return task, "任务已触发执行"


def get_execution_stats(days=30):
    """获取执行统计数据（按日期分组，用于折线图）"""
    from collections import defaultdict
    from datetime import datetime, timedelta
    
    logs = _load_logs()
    
    # 按日期和任务类型统计
    daily_stats = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0, "daily_report": 0, "weekly_report": 0})
    
    # 生成最近N天的日期
    today = datetime.now().date()
    date_list = []
    for i in range(days-1, -1, -1):
        d = today - timedelta(days=i)
        date_list.append(d.strftime("%Y-%m-%d"))
        daily_stats[d.strftime("%Y-%m-%d")]  # 初始化
    
    # 统计日志
    for log in logs:
        started_at = log.get("started_at", "")
        if started_at:
            try:
                log_date = started_at.split(" ")[0]
                if log_date in daily_stats:
                    daily_stats[log_date]["total"] += 1
                    if log.get("status") == "success":
                        daily_stats[log_date]["success"] += 1
                    else:
                        daily_stats[log_date]["failed"] += 1
                    
                    task_type = log.get("task_type", "")
                    if task_type == "daily_report":
                        daily_stats[log_date]["daily_report"] += 1
                    elif task_type == "weekly_report":
                        daily_stats[log_date]["weekly_report"] += 1
            except:
                pass
    
    # 按日期排序
    sorted_dates = sorted(daily_stats.keys())
    
    return {
        "dates": sorted_dates,
        "total": [daily_stats[d]["total"] for d in sorted_dates],
        "success": [daily_stats[d]["success"] for d in sorted_dates],
        "failed": [daily_stats[d]["failed"] for d in sorted_dates],
        "daily_report": [daily_stats[d]["daily_report"] for d in sorted_dates],
        "weekly_report": [daily_stats[d]["weekly_report"] for d in sorted_dates],
    }

