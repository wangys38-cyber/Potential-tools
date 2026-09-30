"""
V9.2 自动化定时任务调度器
支持定时生成日报/周报、自动发送邮件
"""
import json
import os
import time
import threading
from datetime import datetime, timedelta

SCHEDULER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "scheduler")
os.makedirs(SCHEDULER_DIR, exist_ok=True)
TASKS_FILE = os.path.join(SCHEDULER_DIR, "tasks.json")
LOGS_FILE = os.path.join(SCHEDULER_DIR, "logs.json")

TASK_TYPE_DAILY_REPORT = "daily_report"
TASK_TYPE_WEEKLY_REPORT = "weekly_report"
TASK_TYPE_AGING_REPORT = "aging_report"
TASK_TYPE_ALERT_CHECK = "alert_check"
TASK_TYPE_DATA_REFRESH = "data_refresh"
TASK_TYPE_CR_TIMEOUT = "cr_timeout_alert"
TASK_TYPE_BLOCKER_ALERT = "blocker_alert"
TASK_TYPE_FAIL_MODULE = "fail_module_check"
TASK_TYPE_MILESTONE = "milestone_tracking"
TASK_TYPE_COMPETITOR = "competitor_analysis"

FREQ_DAILY = "daily"
FREQ_WEEKLY = "weekly"
FREQ_HOURLY = "hourly"
FREQ_INTERVAL = "interval"

def _send_scheduler_email(to_emails, subject, html_content):
    try:
        import sys, base64
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db.config import get_config
        cfg = get_config('smtp_mail_config') or {}
        smtp_host = cfg.get('smtp_host', '')
        smtp_port = int(cfg.get('smtp_port', 587))
        username = cfg.get('username', '')
        password = base64.b64decode(cfg.get('password', '')).decode('utf-8') if cfg.get('password') else ''
        use_tls = cfg.get('use_tls', True)
        from_name = cfg.get('from_name', 'Potential Tools')
        if not smtp_host or not username or not password:
            return False, "SMTP未配置"
        import smtplib, ssl
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.utils import formataddr
        from email.header import Header
        msg = MIMEMultipart('alternative')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = formataddr((str(Header(from_name, 'utf-8')), username))
        msg['To'] = ', '.join(to_emails) if isinstance(to_emails, list) else to_emails
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        if smtp_port == 587: use_tls = True
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
        server.sendmail(username, to_emails if isinstance(to_emails, list) else [to_emails], msg.as_string())
        server.quit()
        return True, "邮件发送成功"
    except Exception as e:
        return False, f"邮件发送失败: {str(e)}"

def _send_feishu_notification(title, content):
    try:
        import sys, json, time, hmac, hashlib, base64, urllib.request
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db.config import get_config
        cfg = get_config('feishu_bot_config') or {}
        webhook_url = cfg.get('webhook_url', '')
        secret = cfg.get('secret', '')
        if not webhook_url: return False, "未配置飞书Webhook"
        timestamp = int(time.time())
        message = {"msg_type": "text", "content": {"text": f"{title}\n\n{content}"}}
        if secret:
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
            sign = base64.b64encode(hmac_code).decode('utf-8')
            message["timestamp"] = str(timestamp)
            message["sign"] = sign
        data = json.dumps(message).encode('utf-8')
        req = urllib.request.Request(webhook_url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('StatusCode') == 0 or result.get('code') == 0:
                return True, "飞书通知发送成功"
            return False, f"飞书通知失败: {result.get('msg', '未知错误')}"
    except Exception as e:
        return False, f"飞书通知失败: {str(e)}"

def _load_tasks():
    if not os.path.exists(TASKS_FILE): return []
    try:
        with open(TASKS_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except: return []

def _save_tasks(tasks):
    with open(TASKS_FILE, 'w', encoding='utf-8') as f: json.dump(tasks, f, ensure_ascii=False, indent=2)

def _load_logs():
    if not os.path.exists(LOGS_FILE): return []
    try:
        with open(LOGS_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except: return []

def _save_log(log_entry):
    logs = _load_logs()
    logs.insert(0, log_entry)
    logs = logs[:100]
    with open(LOGS_FILE, 'w', encoding='utf-8') as f: json.dump(logs, f, ensure_ascii=False, indent=2)

def create_task(task_type, project_key, freq, time_str="18:00", weekday=4, interval_minutes=60, email_recipients=None, enabled=True, name="", feishu_notify=False):
    tasks = _load_tasks()
    task_id = f"task_{int(time.time() * 1000)}"
    task = {"id": task_id, "name": name or f"{task_type}_{project_key}", "type": task_type, "project_key": project_key, "freq": freq, "time": time_str, "weekday": weekday, "interval_minutes": interval_minutes, "email_recipients": email_recipients or [], "feishu_notify": feishu_notify, "enabled": enabled, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "last_run": None, "next_run": None, "run_count": 0, "success_count": 0, "fail_count": 0}
    task["next_run"] = _calculate_next_run(task)
    tasks.append(task)
    _save_tasks(tasks)
    return task

def update_task(task_id, **kwargs):
    tasks = _load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            for key, value in kwargs.items():
                if key in task: task[key] = value
            task["next_run"] = _calculate_next_run(task)
            _save_tasks(tasks)
            return task
    return None

def delete_task(task_id):
    tasks = _load_tasks()
    tasks = [t for t in tasks if t["id"] != task_id]
    _save_tasks(tasks)
    return True

def get_task(task_id):
    for task in _load_tasks():
        if task["id"] == task_id: return task
    return None

def get_all_tasks(): return _load_tasks()

def get_task_logs(task_id=None, limit=20):
    logs = _load_logs()
    if task_id: logs = [log for log in logs if log.get("task_id") == task_id]
    return logs[:limit]

def _calculate_next_run(task):
    now = datetime.now()
    if task["freq"] == FREQ_DAILY:
        hour, minute = map(int, task["time"].split(":"))
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now: next_run += timedelta(days=1)
        return next_run.strftime("%Y-%m-%d %H:%M:%S")
    elif task["freq"] == FREQ_WEEKLY:
        hour, minute = map(int, task["time"].split(":"))
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = task["weekday"] - now.weekday()
        if days_ahead <= 0: days_ahead += 7
        next_run += timedelta(days=days_ahead)
        return next_run.strftime("%Y-%m-%d %H:%M:%S")
    elif task["freq"] == FREQ_HOURLY:
        return (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    elif task["freq"] == FREQ_INTERVAL:
        return (now + timedelta(minutes=task["interval_minutes"])).strftime("%Y-%m-%d %H:%M:%S")
    return None

def _execute_task(task):
    from services import project_assistant as pa
    result = {"task_id": task["id"], "task_name": task["name"], "task_type": task["type"], "project_key": task["project_key"], "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "status": "running", "message": ""}
    try:
        if task["type"] == TASK_TYPE_DAILY_REPORT:
            report, err = pa.generate_daily_report(task["project_key"])
            if err: raise Exception(err)
            note, err = pa.save_daily_report_to_notes(task["project_key"])
            if err: raise Exception(err)
            result["message"] = f"日报已生成并保存: {note.get('title', '')}"
        elif task["type"] == TASK_TYPE_WEEKLY_REPORT:
            report, err = pa.generate_weekly_report(task["project_key"])
            if err: raise Exception(err)
            note, err = pa.save_weekly_report_to_notes(task["project_key"])
            if err: raise Exception(err)
            result["message"] = f"周报已生成并保存: {note.get('title', '')}"
        elif task["type"] == TASK_TYPE_AGING_REPORT:
            report, err = pa.generate_aging_report(task["project_key"])
            if err: raise Exception(err)
            result["message"] = "老化预警报告已生成"
        elif task["type"] == TASK_TYPE_ALERT_CHECK:
            alert_result = pa.check_project_alerts(task["project_key"])
            result["message"] = f"预警检查完成: {alert_result.get('critical_count', 0)}个严重, {alert_result.get('warning_count', 0)}个警告"
        elif task["type"] == TASK_TYPE_DATA_REFRESH:
            snap = pa.build_project_snapshot(task["project_key"], force=True)
            if not snap: raise Exception("拉取数据失败")
            stats = snap.get("stats", {})
            total_crs = stats.get("total", 0)
            result["message"] = f"项目助手中的数据已刷新（CR总数 {total_crs} 条）"
            result["total_crs"] = total_crs
            result["bc_unresolved"] = stats.get("bc_unresolved", 0)
            result["fail_modules"] = stats.get("fail", 0)
        elif task["type"] == TASK_TYPE_CR_TIMEOUT:
            snap = pa.load_snapshot(task["project_key"])
            if not snap: raise Exception("项目状态尚未生成")
            timeout_crs = []
            for m in snap.get("modules", []):
                for it in m.get("top_list", []):
                    if it.get("status") not in ["Resolved", "Closed"]:
                        timeout_crs.append({"id": it.get("id", ""), "title": it.get("title", ""), "sev": it.get("sev", ""), "module": m.get("module", "")})
            result["report_content"] = "CR超时提醒\n\n超时CR数量: " + str(len(timeout_crs))
            result["message"] = f"CR超时提醒：共{len(timeout_crs)}条"
            result["timeout_count"] = len(timeout_crs)
            result["timeout_list"] = timeout_crs[:10]
        elif task["type"] == TASK_TYPE_BLOCKER_ALERT:
            snap = pa.load_snapshot(task["project_key"])
            if not snap: raise Exception("项目状态尚未生成")
            blocker_count = sum(1 for m in snap.get("modules", []) for it in m.get("top_list", []) if it.get("status") not in ["Resolved", "Closed"] and it.get("sev") == "blocker")
            threshold = task.get("config", {}).get("threshold", 5)
            if blocker_count >= threshold:
                result["report_content"] = f"Blocker预警\n\nBlocker数量: {blocker_count}\n阈值: {threshold}"
                result["message"] = f"Blocker预警：{blocker_count}个Blocker（超过阈值{threshold}）"
            else:
                result["message"] = f"Blocker数量{blocker_count}，未超过阈值{threshold}"
        elif task["type"] == TASK_TYPE_FAIL_MODULE:
            snap = pa.load_snapshot(task["project_key"])
            if not snap: raise Exception("项目状态尚未生成")
            fail_modules = [m for m in snap.get("modules", []) if m.get("fail")]
            result["report_content"] = "FAIL模块巡检\n\nFAIL模块数量: " + str(len(fail_modules))
            result["message"] = f"FAIL模块巡检：{len(fail_modules)}个FAIL模块"
            result["fail_count"] = len(fail_modules)
            result["fail_modules"] = fail_modules[:10]
        elif task["type"] == TASK_TYPE_MILESTONE:
            snap = pa.load_snapshot(task["project_key"])
            if not snap: raise Exception("项目状态尚未生成")
            stats = snap.get("stats", {})
            result["report_content"] = f"里程碑进度跟踪\n\nCR总数: {stats.get('total', 0)}\n未解决BC: {stats.get('bc_unresolved', 0)}"
            result["message"] = "里程碑跟踪完成"
        elif task["type"] == TASK_TYPE_COMPETITOR:
            from services.ai.factory import get_ai_service
            from services.ai.base import ChatMessage
            ai = get_ai_service()
            if not ai:
                result["message"] = "AI服务未配置"
                result["report_content"] = "AI服务未配置"
            else:
                prompt = "请生成IOT行业竞品分析周报，包括热门产品、规格参数、火热原因、值得学习的地方。"
                try:
                    messages = [ChatMessage(role="user", content=prompt)]
                    response = ai.chat(messages, temperature=0.7, max_tokens=3000)
                    content = response.content if hasattr(response, 'content') else str(response)
                    result["report_content"] = content
                    result["message"] = f"竞品分析周报已生成（{len(content)}字）"
                except Exception as e:
                    result["message"] = f"生成竞品分析失败: {str(e)}"
                    result["report_content"] = f"生成失败: {str(e)}"
        if task.get("email_recipients") and len(task["email_recipients"]) > 0:
            try:
                type_names = {"daily_report": "项目日报", "weekly_report": "项目周报", "aging_report": "老化预警报告", "alert_check": "智能预警检查", "data_refresh": "数据刷新"}
                report_type = type_names.get(task["type"], task["type"])
                subject = f"【{report_type}】{task['project_key']} - {datetime.now().strftime('%Y-%m-%d')}"
                report_content = result.get("report_content", "")
                if not report_content:
                    report_content = f"<h2>{report_type}</h2><p>项目: {task['project_key']}</p>"
                try:
                    import markdown as _md
                    report_content = _md.markdown(report_content, extensions=['tables', 'fenced_code', 'nl2br', 'extra'], output_format='html5')
                except: pass
                html_email = f"<div style='font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px'><div style='background:linear-gradient(135deg,#8B5CF6,#6366F1);color:white;padding:20px;border-radius:8px 8px 0 0'><h1 style='margin:0;font-size:20px'>{report_type}</h1></div><div style='background:#fff;padding:24px;border:1px solid #e5e7eb;color:#1f2937;font-size:14px;line-height:1.6'>{report_content}</div></div>"
                success, msg = _send_scheduler_email(task["email_recipients"], subject, html_email)
                if success: result["message"] += f"，邮件已发送给: {', '.join(task['email_recipients'])}"
                else: result["message"] += f"，{msg}"
            except Exception as email_err:
                result["message"] += f"，邮件发送失败: {str(email_err)}"
        if task.get("feishu_notify", False):
            try:
                feishu_success, feishu_msg = _send_feishu_notification(f"【定时任务通知】{task.get('name', task['type'])}", result.get("message", "任务执行完成"))
                if feishu_success: result["message"] += "，飞书通知已发送"
                else: result["message"] += f"，{feishu_msg}"
            except Exception as feishu_err:
                result["message"] += f"，飞书通知失败: {str(feishu_err)}"
        result["status"] = "success"
        result["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        result["status"] = "failed"
        result["message"] = f"执行失败: {str(e)}"
        result["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_log(result)
    tasks = _load_tasks()
    for t in tasks:
        if t["id"] == task["id"]:
            t["last_run"] = result["started_at"]
            t["run_count"] = t.get("run_count", 0) + 1
            if result["status"] == "success": t["success_count"] = t.get("success_count", 0) + 1
            else: t["fail_count"] = t.get("fail_count", 0) + 1
            t["next_run"] = _calculate_next_run(t)
            break
    _save_tasks(tasks)
    return result

_scheduler_running = False
_scheduler_thread = None

def _scheduler_loop():
    global _scheduler_running
    while _scheduler_running:
        try:
            now = datetime.now()
            tasks = _load_tasks()
            for task in tasks:
                if not task.get("enabled", True) or not task.get("next_run"): continue
                next_run = datetime.strptime(task["next_run"], "%Y-%m-%d %H:%M:%S")
                if now >= next_run and (now - next_run).total_seconds() < 120:
                    exec_thread = threading.Thread(target=_execute_task, args=(task,))
                    exec_thread.daemon = True
                    exec_thread.start()
                    tasks_update = _load_tasks()
                    for t in tasks_update:
                        if t["id"] == task["id"]: t["next_run"] = _calculate_next_run(t); break
                    _save_tasks(tasks_update)
        except Exception as e: print(f"[Scheduler] Error: {e}")
        time.sleep(60)

def start_scheduler():
    global _scheduler_running, _scheduler_thread
    if _scheduler_running: return False
    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop)
    _scheduler_thread.daemon = True
    _scheduler_thread.start()
    print("[Scheduler] 定时任务调度器已启动")
    return True

def stop_scheduler():
    global _scheduler_running
    _scheduler_running = False
    return True

def get_scheduler_status():
    return {"running": _scheduler_running, "total_tasks": len(_load_tasks()), "enabled_tasks": len([t for t in _load_tasks() if t.get("enabled", True)])}

def run_task_now(task_id):
    task = get_task(task_id)
    if not task: return None, "任务不存在"
    exec_thread = threading.Thread(target=_execute_task, args=(task,))
    exec_thread.daemon = True
    exec_thread.start()
    return task, "任务已触发执行"

def get_execution_stats(days=30):
    from collections import defaultdict
    from datetime import timedelta
    logs = _load_logs()
    daily_stats = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0})
    today = datetime.now().date()
    for i in range(days-1, -1, -1):
        daily_stats[(today - timedelta(days=i)).strftime("%Y-%m-%d")]
    for log in logs:
        started_at = log.get("started_at", "")
        if started_at:
            try:
                log_date = started_at.split(" ")[0]
                if log_date in daily_stats:
                    daily_stats[log_date]["total"] += 1
                    if log.get("status") == "success": daily_stats[log_date]["success"] += 1
                    else: daily_stats[log_date]["failed"] += 1
            except: pass
    sorted_dates = sorted(daily_stats.keys())
    return {"dates": sorted_dates, "total": [daily_stats[d]["total"] for d in sorted_dates], "success": [daily_stats[d]["success"] for d in sorted_dates], "failed": [daily_stats[d]["failed"] for d in sorted_dates]}
