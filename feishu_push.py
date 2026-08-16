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


def _post(webhook_url, payload, timeout=10):
    """发送 POST 请求到飞书 Webhook"""
    valid, err = _validate_webhook(webhook_url)
    if not valid:
        return {'ok': False, 'error': err}

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
            return {'ok': False, 'error': data.get('msg', data.get('StatusMessage', '未知错误')), 'raw': data}
    except requests.exceptions.Timeout:
        return {'ok': False, 'error': '请求超时'}
    except requests.exceptions.RequestException as e:
        return {'ok': False, 'error': f'网络错误: {e}'}
    except Exception as e:
        return {'ok': False, 'error': f'未知错误: {e}'}


def send_feishu_text(webhook_url, text):
    """
    发送纯文本消息
    :param webhook_url: 飞书机器人 Webhook URL
    :param text: 文本内容
    """
    payload = {
        'msg_type': 'text',
        'content': {'text': text}
    }
    return _post(webhook_url, payload)


def send_feishu_rich_text(webhook_url, title, content_lines):
    """
    发送富文本消息（post 类型）
    :param webhook_url: 飞书机器人 Webhook URL
    :param title: 标题
    :param content_lines: 二维数组，每行是一个元素列表，元素格式如:
        [{"tag":"text","text":"内容"}, {"tag":"a","text":"链接","href":"https://..."}, {"tag":"at","user_id":"all"}]
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
    return _post(webhook_url, payload)


def send_feishu_card(webhook_url, title, markdown_content, header_color='blue', link_url=None, link_text='查看详情'):
    """
    发送交互卡片消息（适合周报、会议纪要等结构化内容）
    :param webhook_url: 飞书机器人 Webhook URL
    :param title: 卡片标题
    :param markdown_content: Markdown 格式正文（飞书卡片支持部分 Markdown）
    :param header_color: 标题栏颜色: blue/green/orange/red/purple/grey
    :param link_url: 可选，底部跳转链接
    :param link_text: 链接按钮文字
    """
    elements = [
        {
            'tag': 'markdown',
            'content': markdown_content[:3000]  # 飞书卡片内容长度限制
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
    return _post(webhook_url, payload)


def send_weekly_report(webhook_url, title, summary, highlights, plans, source_url=None):
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
        link_text='查看完整周报'
    )


def send_meeting_minutes(webhook_url, title, summary, decisions, todos, source_url=None):
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
        link_text='查看完整纪要'
    )
