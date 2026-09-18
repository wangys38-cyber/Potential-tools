"""
坚果云 WebDAV 云盘集成
配置：坚果云 → 账户信息 → 安全选项 → 添加应用 → 获取应用密码
"""
import os
import logging
import sqlite3
import base64
import requests
from xml.etree import ElementTree as ET
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = r'D:\app\data\users.db'
WEBDAV_URL = 'https://dav.jianguoyun.com/dav/'
REMOTE_FOLDER = 'Potential-tools-KB'


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _db()
    conn.execute('''CREATE TABLE IF NOT EXISTS webdav_config (
        user_id INTEGER PRIMARY KEY,
        webdav_url TEXT,
        username TEXT,
        app_password TEXT,
        account_name TEXT,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()


def _auth_header(username, password):
    token = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return {'Authorization': f'Basic {token}'}


def save_config(user_id, username, app_password, webdav_url=None):
    init_db()
    url = webdav_url or WEBDAV_URL
    conn = _db()
    conn.execute('''INSERT OR REPLACE INTO webdav_config
        (user_id, webdav_url, username, app_password, account_name, created_at)
        VALUES (?,?,?,?,?,?)''',
        (user_id, url, username, app_password, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_config(user_id):
    init_db()
    conn = _db()
    row = conn.execute('SELECT webdav_url, username, account_name FROM webdav_config WHERE user_id=?', (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {'webdav_url': row['webdav_url'], 'username': row['username'], 'account_name': row['account_name']}


def _get_creds(user_id):
    init_db()
    conn = _db()
    row = conn.execute('SELECT webdav_url, username, app_password FROM webdav_config WHERE user_id=?', (user_id,)).fetchone()
    conn.close()
    return row


def test_connection(username, app_password, webdav_url=None):
    """测试连接"""
    url = webdav_url or WEBDAV_URL
    try:
        r = requests.request('PROPFIND', url, headers=_auth_header(username, app_password),
                             timeout=15)
        return r.status_code in (207, 200)
    except Exception as e:
        logger.error(f"WebDAV连接测试失败: {e}")
        return False


def get_status(user_id):
    cfg = get_config(user_id)
    if not cfg:
        return {'bound': False}
    return {'bound': True, 'account_name': cfg['account_name'], 'username': cfg['username']}


def unbind(user_id):
    conn = _db()
    conn.execute('DELETE FROM webdav_config WHERE user_id=?', (user_id,))
    conn.commit()
    conn.close()


def _ensure_folder(headers, base_url):
    """确保远程文件夹存在"""
    folder_url = f'{base_url.rstrip("/")}/{REMOTE_FOLDER}'
    r = requests.request('MKCOL', folder_url, headers=headers, timeout=10)
    # 201=创建成功 405=已存在
    return folder_url


def upload_file(user_id, local_path, remote_name):
    """上传文件"""
    row = _get_creds(user_id)
    if not row:
        return None
    base_url, username, password = row['webdav_url'], row['username'], row['app_password']
    headers = _auth_header(username, password)
    folder_url = _ensure_folder(headers, base_url)

    file_url = f'{folder_url}/{remote_name}'
    with open(local_path, 'rb') as f:
        r = requests.put(file_url, headers=headers, data=f, timeout=120)
    if r.status_code in (200, 201, 204):
        return remote_name
    logger.error(f"WebDAV上传失败: {r.status_code} {r.text[:200]}")
    return None


def download_file(user_id, remote_name, local_path):
    """下载文件"""
    row = _get_creds(user_id)
    if not row:
        return False
    base_url, username, password = row['webdav_url'], row['username'], row['app_password']
    headers = _auth_header(username, password)
    file_url = f'{base_url.rstrip("/")}/{REMOTE_FOLDER}/{remote_name}'
    r = requests.get(file_url, headers=headers, timeout=60)
    if r.status_code == 200:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(r.content)
        return True
    return False


def list_files(user_id):
    """列出云盘文件"""
    row = _get_creds(user_id)
    if not row:
        return []
    base_url, username, password = row['webdav_url'], row['username'], row['app_password']
    headers = {**_auth_header(username, password), 'Depth': '1'}
    folder_url = f'{base_url.rstrip("/")}/{REMOTE_FOLDER}'
    r = requests.request('PROPFIND', folder_url, headers=headers, timeout=15)
    if r.status_code != 207:
        return []
    try:
        root = ET.fromstring(r.text)
        ns = {'d': 'DAV:'}
        files = []
        for resp in root.findall('.//d:response', ns)[1:]:  # 跳过文件夹自身
            href = resp.find('d:href', ns)
            size = resp.find('.//d:getcontentlength', ns)
            if href is not None:
                name = href.text.rstrip('/').split('/')[-1]
                files.append({'name': name, 'size': int(size.text) if size is not None else 0})
        return files
    except Exception as e:
        logger.error(f"WebDAV解析文件列表失败: {e}")
        return []
