"""
智能报告推送服务 v8.0
支持邮件推送、定时推送、推送记录
"""
import time
import json
import base64
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from . import report_generator
from .agent import AgentScheduler

logger = logging.getLogger(__name__)


def send_email_report(smtp_config: Dict, recipients: List[str],
                      subject: str, html_content: str,
                      text_content: str = '') -> Dict[str, Any]:
    """
    发送邮件报告
    """
    result = {'status': 'success', 'sent_count': 0, 'errors': []}

    if not recipients:
        return {'status': 'error', 'error': '收件人列表为空'}

    if not smtp_config.get('smtp_host') or not smtp_config.get('username'):
        return {'status': 'error', 'error': 'SMTP 未配置'}

    try:
        password = ''
        if smtp_config.get('password'):
            password = base64.b64decode(smtp_config['password']).decode('utf-8')

        # 建立连接
        port = int(smtp_config.get('smtp_port', 587))
        host = smtp_config['smtp_host']
        use_tls = smtp_config.get('use_tls', True)
        if port == 587:
            use_tls = True

        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            if use_tls:
                server.starttls()

        if password:
            server.login(smtp_config['username'], password)

        # 发送给每个收件人
        for recipient in recipients:
            try:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = smtp_config.get('from_name', smtp_config['username'])
                msg['To'] = recipient

                if text_content:
                    msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
                msg.attach(MIMEText(html_content, 'html', 'utf-8'))

                server.sendmail(smtp_config['username'], [recipient], msg.as_string())
                result['sent_count'] += 1
            except Exception as e:
                result['errors'].append(f'{recipient}: {str(e)}')

        server.quit()

        if result['sent_count'] == 0:
            result['status'] = 'error'
            result['error'] = '所有收件人发送失败: ' + '; '.join(result['errors'])
        elif result['errors']:
            result['status'] = 'partial'

    except Exception as e:
        return {'status': 'error', 'error': f'SMTP 连接失败: {str(e)}'}

    return result


def generate_and_push_report(user_id: int, schedule: Dict,
                             issues: List[Dict], daily_data: List[Dict],
                             template: Dict = None,
                             ai_service=None,
                             smtp_config: Dict = None) -> Dict[str, Any]:
    """
    生成并推送报告
    """
    from db import report as report_db

    start_time = time.time()

    # 1. 生成报告
    report = report_generator.generate_report(issues, daily_data, template, ai_service)

    # 2. 构建邮件主题
    subject = schedule.get('subject_format') or report['title']
    now = datetime.now()
    subject = subject.format(
        date=now.strftime('%Y-%m-%d'),
        year=now.year,
        month=now.month,
    )

    # 3. 获取收件人
    recipients = schedule.get('recipients', [])
    if isinstance(recipients, str):
        try:
            recipients = json.loads(recipients)
        except:
            recipients = [r.strip() for r in recipients.split(',') if r.strip()]

    # 4. 创建推送日志
    log_id = report_db.create_push_log(
        user_id=user_id,
        schedule_id=schedule.get('id', 0),
        template_id=schedule.get('template_id', 0),
        recipients=recipients,
        subject=subject,
        content_preview=report['content'][:500],
    )

    # 5. 发送邮件
    if smtp_config and recipients:
        send_result = send_email_report(
            smtp_config=smtp_config,
            recipients=recipients,
            subject=subject,
            html_content=report['html_content'],
            text_content=report['content'],
        )
    else:
        send_result = {'status': 'skipped', 'sent_count': 0, 'error': 'SMTP 未配置或无收件人'}

    # 6. 更新推送日志
    duration_ms = int((time.time() - start_time) * 1000)
    report_db.update_push_log(
        log_id=log_id,
        status=send_result['status'],
        error_message=send_result.get('error', ''),
        duration_ms=duration_ms,
    )

    return {
        'status': send_result['status'],
        'log_id': log_id,
        'report': report,
        'subject': subject,
        'recipients': recipients,
        'sent_count': send_result.get('sent_count', 0),
        'errors': send_result.get('errors', []),
        'duration_ms': duration_ms,
    }


def calculate_next_send_time(schedule: Dict) -> float:
    """计算下次发送时间"""
    now = datetime.now()
    schedule_type = schedule.get('schedule_type', 'daily')
    schedule_time = schedule.get('schedule_time', '09:00')

    try:
        hour, minute = map(int, schedule_time.split(':'))
    except:
        hour, minute = 9, 0

    if schedule_type == 'daily':
        next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_time <= now:
            next_time += timedelta(days=1)
    elif schedule_type == 'weekly':
        next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = 7 - now.weekday()
        if days_ahead == 0 and next_time <= now:
            days_ahead = 7
        next_time += timedelta(days=days_ahead)
    elif schedule_type == 'monthly':
        if now.month == 12:
            next_time = now.replace(year=now.year + 1, month=1, day=1, hour=hour, minute=minute, second=0, microsecond=0)
        else:
            next_time = now.replace(month=now.month + 1, day=1, hour=hour, minute=minute, second=0, microsecond=0)
    else:
        next_time = now + timedelta(days=1)

    return next_time.timestamp()


class ReportPushScheduler(AgentScheduler):
    """报告推送调度器（复用 Agent 调度器框架）"""

    def _check_and_run(self):
        """检查并运行到期的推送计划"""
        from db import report as report_db

        now = time.time()
        due_schedules = report_db.get_due_report_schedules(now)

        for schedule in due_schedules:
            schedule_id = schedule['id']
            user_id = schedule['user_id']

            # 计算下次发送时间
            next_send = calculate_next_send_time(schedule)
            report_db.update_schedule_send_time(schedule_id, now, next_send)

            # 后台执行推送
            import threading
            threading.Thread(
                target=self._run_single_push,
                args=(user_id, schedule_id, schedule),
                daemon=True
            ).start()

    def _run_single_push(self, user_id: int, schedule_id: int, schedule: Dict):
        """执行单次推送"""
        from db import report as report_db
        from db import user_data as user_data_db
        from services.ai import get_ai_service

        try:
            # 获取模板
            template = None
            if schedule.get('template_id'):
                template = report_db.get_report_template(schedule['template_id'])

            # 收集数据
            issues, daily_data = self._collect_data(user_id)
            if not issues:
                logger.warning(f'报告推送跳过: 无数据 user={user_id}')
                return

            # 获取 AI 服务
            ai_service = None
            try:
                ai_service = get_ai_service()
            except:
                pass

            # 获取 SMTP 配置
            from db import get_config
            smtp_config = get_config('smtp_mail_config') or {}

            # 生成并推送
            result = generate_and_push_report(
                user_id=user_id,
                schedule=schedule,
                issues=issues,
                daily_data=daily_data,
                template=template,
                ai_service=ai_service,
                smtp_config=smtp_config,
            )

            logger.info(f'报告推送完成: user={user_id}, schedule={schedule_id}, status={result["status"]}, sent={result["sent_count"]}')

        except Exception as e:
            logger.error(f'报告推送失败: {e}')

    def _collect_data(self, user_id: int):
        """收集用户的 CR 数据"""
        from db import user_data as user_data_db

        try:
            records = user_data_db.list_user_data(user_id, data_type='cr_analysis', limit=1)
            if not records:
                records = user_data_db.list_user_data(user_id, limit=5)

            for record in records:
                content = record.get('content', '')
                if content:
                    try:
                        data = json.loads(content) if isinstance(content, str) else content
                        issues = data.get('issues') or data.get('bugs') or data.get('rows') or []
                        daily = data.get('dailyTrend') or data.get('daily_data') or []
                        if issues:
                            return issues, daily
                    except:
                        continue
        except Exception as e:
            logger.warning(f'收集报告数据失败: {e}')

        return [], []


# 全局调度器实例
_report_scheduler = None


def get_report_scheduler() -> ReportPushScheduler:
    """获取报告推送调度器单例"""
    global _report_scheduler
    if _report_scheduler is None:
        _report_scheduler = ReportPushScheduler()
    return _report_scheduler


def start_report_scheduler():
    """启动报告推送调度器"""
    scheduler = get_report_scheduler()
    scheduler.start()
    logger.info('报告推送调度器已启动')
