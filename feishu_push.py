"""
飞书推送模块 v5.0
通过飞书自定义机器人 Webhook 发送消息到飞书群。

使用方式：
    from feishu_push import send_feishu_text, send_feishu_rich_text, send_feishu_card

    # 纯文本
    send_feishu_text(webhook_url, "Hello from 工具集")

    # 富文本（支持标题、段落、@人）
    send_feishu_rich_text(webhook_url, title="周报", content=[[{"tag":"text","text":"本周完成..."}]])

    # 交互卡片
    send_feishu_card(webhook_url, title="周报", content="markdown内容", url="https://...")
"""

import json
import logging
import time
import hmac
import hashlib
import base64
import requests

logger = logging.getLogger(__name__)

# 飞书 Webhook 域名白名单校验
ALLOWED_WEBHOOK_HOSTS = (
    'open.feishu.cn',
    'open.larksuite.com',
)


def _validate_webhook(webhook_url):
    """校验 Webhook URL 合法性，防止 SSRF"""
    if not webhook_url or not isinstance(webhook_url, str):
        return False, 'Webhook URL 为空'
    if not webhook_url.startswith('https://'):
        return False, 'Webhook URL 必须以 https:// 开头'
    try:
        from urllib.parse import urlparse
        parsed = urlparse(webhook_url)
        if parsed.hostname not in ALLOWED_WEBHOOK_HOSTS:
            return False, f'Webhook 域名不被允许: {parsed.hostname}'
        if not parsed.path.startswith('/open-apis/bot/v2/hook/'):
            return False, 'Webhook 路径格式不正确'
    except Exception as e:
        return False, f'Webhook URL 解析失败: {e}'
    return True, ''


def _gen_sign(secret):
    """
    生成飞书机器人签名
    算法：timestamp + "\n" + secret → HMAC-SHA256 → Base64
    """
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()
    sign = base64.b64encode(hmac_code).decode("utf-8")
    return timestamp, sign


def _post(webhook_url, payload, timeout=10, secret=None, max_retries=1):
    """发送 POST 请求到飞书 Webhook，失败自动重试 max_retries 次"""
    valid, err = _validate_webhook(webhook_url)
    if not valid:
        return {'ok': False, 'error': err}

    # 如果配置了签名密钥，添加 timestamp 和 sign
    if secret:
        timestamp, sign = _gen_sign(secret)
        payload['timestamp'] = timestamp
        payload['sign'] = sign

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=timeout
            )
            data = resp.json()
            # 飞书返回 code=0 表示成功
            if data.get('code', -1) == 0 or data.get('StatusCode', -1) == 0:
                return {'ok': True, 'data': data}
            else:
                last_error = data.get('msg', data.get('StatusMessage', '未知错误'))
                logger.warning(f'飞书推送失败 (尝试 {attempt+1}/{max_retries+1}): {last_error}')
        except requests.exceptions.Timeout:
            last_error = '请求超时'
            logger.warning(f'飞书推送超时 (尝试 {attempt+1}/{max_retries+1})')
        except requests.exceptions.RequestException as e:
            last_error = f'网络错误: {e}'
            logger.warning(f'飞书推送网络错误 (尝试 {attempt+1}/{max_retries+1}): {e}')
        except Exception as e:
            last_error = f'未知错误: {e}'
            logger.warning(f'飞书推送未知错误 (尝试 {attempt+1}/{max_retries+1}): {e}')
        # 重试前短暂等待
        if attempt < max_retries:
            time.sleep(1)
    return {'ok': False, 'error': last_error or '推送失败', 'retried': max_retries}


def send_feishu_text(webhook_url, text, secret=None):
    """
    发送纯文本消息
    :param webhook_url: 飞书机器人 Webhook URL
    :param text: 文本内容
    :param secret: 可选，飞书机器人签名密钥
    """
    payload = {
        'msg_type': 'text',
        'content': {'text': text}
    }
    return _post(webhook_url, payload, secret=secret)


def send_feishu_rich_text(webhook_url, title, content_lines, secret=None):
    """
    发送富文本消息（post 类型）
    :param webhook_url: 飞书机器人 Webhook URL
    :param title: 标题
    :param content_lines: 二维数组
    :param secret: 可选，飞书机器人签名密钥
    """
    payload = {
        'msg_type': 'post',
        'content': {
            'post': {
                'zh_cn': {
                    'title': title,
                    'content': content_lines
                }
            }
        }
    }
    return _post(webhook_url, payload, secret=secret)


def send_feishu_card(webhook_url, title, markdown_content, header_color='blue', link_url=None, link_text='查看详情', secret=None):
    """
    发送交互卡片消息（适合周报、会议纪要等结构化内容）
    :param webhook_url: 飞书机器人 Webhook URL
    :param title: 卡片标题
    :param markdown_content: Markdown 格式正文
    :param header_color: 标题栏颜色
    :param link_url: 可选，底部跳转链接
    :param link_text: 链接按钮文字
    :param secret: 可选，飞书机器人签名密钥
    """
    elements = [
        {
            'tag': 'markdown',
            'content': markdown_content[:28000]  # 飞书卡片Markdown内容限制约30000字符，留余量
        }
    ]
    if link_url:
        elements.append({
            'tag': 'action',
            'actions': [
                {
                    'tag': 'button',
                    'text': {'tag': 'plain_text', 'content': link_text},
                    'type': 'primary',
                    'url': link_url
                }
            ]
        })

    payload = {
        'msg_type': 'interactive',
        'card': {
            'header': {
                'title': {'tag': 'plain_text', 'content': title},
                'template': header_color
            },
            'elements': elements
        }
    }
    return _post(webhook_url, payload, secret=secret)


def send_weekly_report(webhook_url, title, summary, highlights, plans, source_url=None, secret=None):
    """
    专用：推送周报到飞书（卡片格式）
    """
    md_parts = []
    if summary:
        md_parts.append(f'**📊 本周概要**\n{summary}')
    if highlights:
        md_parts.append(f'**✨ 重点成果**\n{highlights}')
    if plans:
        md_parts.append(f'**📅 下周计划**\n{plans}')
    markdown_content = '\n\n'.join(md_parts) if md_parts else '周报内容为空'

    return send_feishu_card(
        webhook_url,
        title=title,
        markdown_content=markdown_content,
        header_color='purple',
        link_url=source_url,
        link_text='查看完整周报',
        secret=secret
    )


def send_meeting_minutes(webhook_url, title, summary, decisions, todos, source_url=None, secret=None):
    """
    专用：推送会议纪要到飞书（卡片格式）
    """
    md_parts = []
    if summary:
        md_parts.append(f'**📋 会议概要**\n{summary}')
    if decisions:
        md_parts.append(f'**✅ 决议事项**\n{decisions}')
    if todos:
        md_parts.append(f'**📝 待办事项**\n{todos}')
    markdown_content = '\n\n'.join(md_parts) if md_parts else '会议纪要内容为空'

    return send_feishu_card(
        webhook_url,
        title=title,
        markdown_content=markdown_content,
        header_color='blue',
        link_url=source_url,
        link_text='查看完整纪要',
        secret=secret
    )


def send_cr_analysis(webhook_url, title, summary, issues, module_stats, source_url=None, secret=None):
    """
    专用：推送 CR 分析报告到飞书（统一卡片模板）
    """
    md_parts = []
    if summary:
        md_parts.append(f'**📊 分析概要**\n{summary}')
    if issues:
        md_parts.append(f'**🐛 问题列表**\n{issues}')
    if module_stats:
        md_parts.append(f'**📦 模块分布**\n{module_stats}')
    markdown_content = '\n\n'.join(md_parts) if md_parts else 'CR 分析内容为空'

    return send_feishu_card(
        webhook_url,
        title=title,
        markdown_content=markdown_content,
        header_color='orange',
        link_url=source_url,
        link_text='查看完整分析',
        secret=secret
    )


def send_daily_standup(webhook_url, title, yesterday, today, blockers, source_url=None, secret=None):
    """
    专用：推送每日站会到飞书（统一卡片模板）
    """
    md_parts = []
    if yesterday:
        md_parts.append(f'**✅ 昨日完成**\n{yesterday}')
    if today:
        md_parts.append(f'**🎯 今日计划**\n{today}')
    if blockers:
        md_parts.append(f'**🚧 阻塞项**\n{blockers}')
    markdown_content = '\n\n'.join(md_parts) if md_parts else '站会内容为空'

    return send_feishu_card(
        webhook_url,
        title=title,
        markdown_content=markdown_content,
        header_color='green',
        link_url=source_url,
        link_text='查看站会详情',
        secret=secret
    )


def send_plan_change(webhook_url, title, change_summary, affected_nodes, source_url=None, secret=None):
    """
    专用：推送计划变更通知到飞书（统一卡片模板）
    """
    md_parts = []
    if change_summary:
        md_parts.append(f'**📝 变更说明**\n{change_summary}')
    if affected_nodes:
        md_parts.append(f'**📋 受影响节点**\n{affected_nodes}')
    markdown_content = '\n\n'.join(md_parts) if md_parts else '计划变更内容为空'

    return send_feishu_card(
        webhook_url,
        title=title,
        markdown_content=markdown_content,
        header_color='red',
        link_url=source_url,
        link_text='查看完整计划',
        secret=secret
    )
