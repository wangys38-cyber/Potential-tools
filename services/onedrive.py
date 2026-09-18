"""
OneDrive 云盘集成 - Microsoft Graph API
"""
import os
import json
import time
import logging
import sqlite3
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = r'D:\app\data\users.db'

# Azure AD 应用配置（用户需在 Azure Portal 注册后填入）
# 注册地址: https://portal.azure.com → Microsoft Entra ID → 应用注册
CLIENT_ID = os.environ.get('ONEDRIVE_CLIENT_ID', '')
CLIENT_SECRET = os.environ.get('ONEDRIVE_CLIENT_SECRET', '')
REDIRECT_URI = 'http://localhost:5000/knowledge-base/onedrive/callback'
AUTHORITY = 'https://login.microsoftonline.com/common'
GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
SCOPES = 'offline_access Files.ReadWrite.All User.Read'


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """创建OneDrive token表"""
    conn = _db()
    conn.execute('''CREATE TABLE IF NOT EXISTS onedrive_tokens (
        user_id INTEGER PRIMARY KEY,
        access_token TEXT,
        refresh_token TEXT,
        expires_at REAL,
        account_name TEXT,
        account_email TEXT,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()


def get_auth_url():
    """获取OAuth授权URL"""
    from urllib.parse import urlencode
    params = {
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
        'response_mode': 'query',
    }
    return f"{AUTHORITY}/oauth2/v2.0/authorize?{urlencode(params)}"


def exchange_code(code):
    """用授权码换token"""
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code',
        'scope': SCOPES,
    }
    r = requests.post(f'{AUTHORITY}/oauth2/v2.0/token', data=data, timeout=15)
    r.raise_for_status()
    return r.json()


def refresh_access_token(user_id):
    """刷新access_token"""
    conn = _db()
    row = conn.execute('SELECT refresh_token FROM onedrive_tokens WHERE user_id=?', (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'refresh_token': row['refresh_token'],
        'grant_type': 'refresh_token',
        'scope': SCOPES,
    }
    r = requests.post(f'{AUTHORITY}/oauth2/v2.0/token', data=data, timeout=15)
    r.raise_for_status()
    tokens = r.json()
    conn = _db()
    conn.execute('UPDATE onedrive_tokens SET access_token=?, expires_at=? WHERE user_id=?',
                 (tokens['access_token'], time.time() + tokens.get('expires_in', 3600) - 300, user_id))
    conn.commit()
    conn.close()
    return tokens['access_token']


def get_valid_token(user_id):
    """获取有效的access_token，过期自动刷新"""
    conn = _db()
    row = conn.execute('SELECT access_token, expires_at FROM onedrive_tokens WHERE user_id=?', (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    if row['expires_at'] and time.time() < row['expires_at']:
        return row['access_token']
    return refresh_access_token(user_id)


def save_tokens(user_id, tokens):
    """保存token"""
    init_db()
    # 获取用户信息
    headers = {'Authorization': f'Bearer {tokens["access_token"]}'}
    account_name = ''
    account_email = ''
    try:
        r = requests.get(f'{GRAPH_BASE}/me', headers=headers, timeout=10)
        if r.ok:
            me = r.json()
            account_name = me.get('displayName', '')
            account_email = me.get('userPrincipalName', me.get('mail', ''))
    except Exception:
        pass

    conn = _db()
    conn.execute('''INSERT OR REPLACE INTO onedrive_tokens
        (user_id, access_token, refresh_token, expires_at, account_name, account_email, created_at)
        VALUES (?,?,?,?,?,?,?)''',
        (user_id, tokens['access_token'], tokens.get('refresh_token', ''),
         time.time() + tokens.get('expires_in', 3600) - 300,
         account_name, account_email, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_status(user_id):
    """获取绑定状态"""
    init_db()
    conn = _db()
    row = conn.execute('SELECT account_name, account_email, created_at FROM onedrive_tokens WHERE user_id=?', (user_id,)).fetchone()
    conn.close()
    if not row:
        return {'bound': False, 'configured': bool(CLIENT_ID)}
    return {
        'bound': True,
        'configured': True,
        'account_name': row['account_name'],
        'account_email': row['account_email'],
    }


def unbind(user_id):
    """解绑"""
    conn = _db()
    conn.execute('DELETE FROM onedrive_tokens WHERE user_id=?', (user_id,))
    conn.commit()
    conn.close()


def upload_file(user_id, local_path, remote_name, folder='Potential-tools-KB'):
    """上传文件到OneDrive，返回file_id"""
    token = get_valid_token(user_id)
    if not token:
        return None
    headers = {'Authorization': f'Bearer {token}'}

    # 确保文件夹存在
    folder_url = f'{GRAPH_BASE}/me/drive/root:/{folder}:'
    r = requests.get(folder_url, headers=headers, timeout=10)
    if not r.ok:
        # 创建文件夹
        r = requests.post(f'{GRAPH_BASE}/me/drive/root/children',
            headers={**headers, 'Content-Type': 'application/json'},
            json={'name': folder, 'folder': {}, '@microsoft.graph.conflictBehavior': 'replace'},
            timeout=10)

    # 上传文件（<4MB用简单上传）
    file_size = os.path.getsize(local_path)
    if file_size < 4 * 1024 * 1024:
        url = f'{GRAPH_BASE}/me/drive/root:/{folder}/{remote_name}:/content'
        with open(local_path, 'rb') as f:
            r = requests.put(url, headers=headers, data=f, timeout=60)
    else:
        # 大文件分片上传
        r = _upload_large(token, local_path, folder, remote_name)

    if r.ok:
        return r.json().get('id')
    logger.error(f"OneDrive上传失败: {r.status_code} {r.text[:200]}")
    return None


def _upload_large(token, local_path, folder, remote_name):
    """大文件分片上传"""
    headers = {'Authorization': f'Bearer {token}'}
    file_size = os.path.getsize(local_path)

    # 创建上传会话
    url = f'{GRAPH_BASE}/me/drive/root:/{folder}/{remote_name}:/createUploadSession'
    r = requests.post(url, headers={**headers, 'Content-Type': 'application/json'}, json={}, timeout=15)
    if not r.ok:
        return r
    upload_url = r.json()['uploadUrl']

    # 分片上传
    chunk_size = 320 * 1024  # 320KB
    with open(local_path, 'rb') as f:
        offset = 0
        while offset < file_size:
            chunk = f.read(chunk_size)
            end = min(offset + len(chunk), file_size) - 1
            r = requests.put(upload_url, headers={
                'Content-Length': str(len(chunk)),
                'Content-Range': f'bytes {offset}-{end}/{file_size}',
            }, data=chunk, timeout=60)
            if not r.ok and r.status_code != 202:
                return r
            offset = end + 1
    return r


def download_file(user_id, remote_name, local_path, folder='Potential-tools-KB'):
    """从OneDrive下载文件"""
    token = get_valid_token(user_id)
    if not token:
        return False
    url = f'{GRAPH_BASE}/me/drive/root:/{folder}/{remote_name}:/content'
    headers = {'Authorization': f'Bearer {token}'}
    r = requests.get(url, headers=headers, timeout=60, allow_redirects=True)
    if r.ok:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(r.content)
        return True
    return False


def list_files(user_id, folder='Potential-tools-KB'):
    """列出云盘文件"""
    token = get_valid_token(user_id)
    if not token:
        return []
    url = f'{GRAPH_BASE}/me/drive/root:/{folder}:/children'
    headers = {'Authorization': f'Bearer {token}'}
    r = requests.get(url, headers=headers, timeout=15)
    if r.ok:
        return r.json().get('value', [])
    return []
