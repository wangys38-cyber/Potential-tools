# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r'D:\Potential-tools')
from services.jira_client import get_jira_client

client = get_jira_client()
if client:
    try:
        issue = client.get_issue('EKSANTOS-9136')
        fields = issue.get('fields', {})
        attachments = fields.get('attachment', [])
        print(f'附件数量: {len(attachments)}')
        for a in attachments:
            size = a.get('size', 0)
            print(f'  文件名: {a.get("filename")}')
            print(f'  大小(字节): {size}')
            print(f'  大小(MB): {size / 1024 / 1024:.2f}')
            print(f'  MIME: {a.get("mimeType")}')
            print()
    except Exception as e:
        print(f'错误: {e}')
        import traceback
        traceback.print_exc()
else:
    print('Jira客户端未配置')
