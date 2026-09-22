# -*- coding: utf-8 -*-
"""
eDart / Jira REST 数据源客户端
================================

通过 Jira REST API（Data Center 自建实例 与 Atlassian Cloud 均兼容 /rest/api/2）
用 JQL 分页拉取 CR（缺陷），并转换为与「Jira 导出 CSV」完全一致的二维表，
落盘后可直接复用现有 CR 分析流水线（_analyze_issue_sheet / _fast），
从而替代每天手动从 eDart 导出 CSV 再上传的操作。

认证方式：
  - Data Center（内网自建，eDart 多属此类）：Personal Access Token，请求头
        Authorization: Bearer <PAT>
  - Cloud：邮箱 + API Token，HTTP Basic
        Authorization: Basic base64(email:api_token)

设计为不依赖 Flask，可在路由 / 后台线程 / 独立脚本中直接使用。
"""

import os
import json
import time
import base64
import logging
import datetime as _dt
from typing import Callable, Optional

import requests

try:
    from dateutil import parser as _dateparser
except Exception:  # pragma: no cover
    _dateparser = None

logger = logging.getLogger(__name__)

# Jira REST API 版本（DC 与 Cloud 均兼容 api/2）
_API = "/rest/api/2"

# 逻辑字段 -> Jira 系统字段 id（自定义字段在运行时通过 /field 自动探测）
_SYSTEM_FIELDS = {
    "key": "key",
    "summary": "summary",
    "status": "status",
    "assignee": "assignee",
    "components": "components",
    "labels": "labels",
    "created": "created",
    "resolutiondate": "resolutiondate",
    "fixVersions": "fixVersions",
}

# 输出 CSV 的表头（刻意对齐 Jira 官方导出列名，保证 _detect_issue_columns 100% 识别）
CSV_HEADERS = [
    "Issue key",
    "Summary",
    "Status",
    "Assignee",
    "Component/s",
    "Labels",
    "Created",
    "Resolved",
    "Fix Version/s",
    "Custom field (Severity)",
    "Custom field (Closed Date)",
]


class JiraError(Exception):
    """对外展示的、带中文说明的连接/拉取错误。"""


def normalize_base_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise JiraError("请填写 eDart/Jira 站点地址")
    if not (u.startswith("http://") or u.startswith("https://")):
        u = "https://" + u
    return u.rstrip("/")


def _fmt_datetime(raw) -> str:
    """把 Jira 的 ISO8601 时间（2025-12-18T13:08:00.000+0800 / ...Z）格式化为
    'YYYY-MM-DD HH:MM:SS'，与现有 CR 分析日期解析兼容；空值返回空串。"""
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    try:
        if _dateparser is not None:
            dt = _dateparser.parse(s)
        else:
            t = s.replace("Z", "+00:00")
            dt = _dt.datetime.fromisoformat(t)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        # 解析失败则原样返回（交由下游日期解析兜底）
        return s


def _first_present(*vals):
    for v in vals:
        if v not in (None, "", [], {}):
            return v
    return None


def _extract_option(value) -> str:
    """从 Jira 自定义字段的多种形态里取人类可读值。
    option: {'value':'Blocker'}；级联: {'value':..}；数组: [{'value':..}]；字符串直接返回。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for k in ("value", "name", "displayName", "label"):
            if value.get(k):
                return str(value[k]).strip()
        return ""
    if isinstance(value, (list, tuple)):
        parts = [_extract_option(v) for v in value]
        return ", ".join([p for p in parts if p])
    return str(value).strip()


def _names(value, key="name") -> str:
    """components / fixVersions 这类 [{name:...}, ...] -> 'a, b'。"""
    if not value:
        return ""
    if isinstance(value, dict):
        return str(value.get(key) or value.get("value") or "").strip()
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            if isinstance(v, dict):
                n = v.get(key) or v.get("value") or v.get("displayName")
                if n:
                    out.append(str(n).strip())
            elif v:
                out.append(str(v).strip())
        return ", ".join(out)
    return str(value).strip()


class JiraClient:
    def __init__(self, base_url, auth_mode="dc", email="", token="",
                 verify_ssl=True, timeout=30):
        """
        :param auth_mode: 'dc' -> Bearer PAT；'cloud' -> Basic(email:api_token)
        """
        self.base_url = normalize_base_url(base_url)
        self.auth_mode = (auth_mode or "dc").lower()
        self.email = (email or "").strip()
        self.token = (token or "").strip()
        self.verify_ssl = bool(verify_ssl)
        self.timeout = timeout
        self._session = None
        self._field_map = None

    # ---------- 连接 ----------
    def _make_session(self) -> requests.Session:
        s = requests.Session()
        if self.auth_mode == "cloud":
            if not self.email or not self.token:
                raise JiraError("Jira Cloud 需要同时填写邮箱和 API Token")
            raw = f"{self.email}:{self.token}".encode("utf-8")
            s.headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        else:
            if not self.token:
                raise JiraError("Data Center/eDart 需要填写 Personal Access Token（PAT）")
            s.headers["Authorization"] = "Bearer " + self.token
        s.headers["Accept"] = "application/json"
        s.headers["Content-Type"] = "application/json"
        s.verify = self.verify_ssl
        if not self.verify_ssl:
            try:
                requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
            except Exception:
                pass
        return s

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._make_session()
        return self._session

    def _get(self, path, params=None):
        url = self.base_url + path
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.exceptions.SSLError as e:
            raise JiraError(
                "SSL 证书校验失败（内网自签证书常见）。可在配置中勾选「忽略证书校验」后重试。"
                f"（{type(e).__name__}）")
        except requests.exceptions.ConnectTimeout:
            raise JiraError(f"连接超时（{self.timeout}s）。若 eDart 是内网系统，请确认已连接公司网络/VPN。")
        except requests.exceptions.ConnectionError:
            raise JiraError(
                f"无法连接到 {self.base_url}。请检查地址是否正确，以及是否需要连接公司网络/VPN。")
        except requests.RequestException as e:
            raise JiraError(f"请求失败：{type(e).__name__}: {e}")

        if resp.status_code in (401, 403):
            raise JiraError(
                f"认证失败（HTTP {resp.status_code}）。请检查 Token 是否正确/过期、"
                "Data Center 用 Personal Access Token（Bearer），Cloud 用邮箱+API Token（Basic），"
                "并确认账号有该项目的访问权限。")
        if resp.status_code == 404:
            raise JiraError(
                f"接口不存在（HTTP 404）：{path}。该站点可能不是 Jira，或 REST API 被 IT 关闭。"
                "可在浏览器登录后访问 <站点>/rest/api/2/serverInfo 自测。")
        if resp.status_code >= 400:
            snippet = (resp.text or "")[:300]
            raise JiraError(f"Jira 返回错误 HTTP {resp.status_code}：{snippet}")
        try:
            return resp.json()
        except Exception:
            raise JiraError("返回内容不是 JSON，可能被重定向到了 SSO 登录页。请确认 Token 认证可用（而非网页单点登录）。")

    def test_connection(self) -> dict:
        """测试连通性与认证，返回账号/版本/部署形态信息。"""
        myself = self._get(f"{_API}/myself")
        info = {}
        try:
            info = self._get(f"{_API}/serverInfo")
        except JiraError:
            info = {}
        display = _first_present(myself.get("displayName"), myself.get("name"),
                                 myself.get("emailAddress"))
        return {
            "ok": True,
            "user": display or "",
            "account_id": myself.get("key") or myself.get("accountId") or "",
            "version": info.get("version", ""),
            "deployment": info.get("deploymentType", ""),
            "base_url": info.get("baseUrl", self.base_url),
        }

    # ---------- 字段自动探测 ----------
    def discover_fields(self, force=False) -> dict:
        """GET /rest/api/2/field，自动定位 Severity / Closed Date 等自定义字段 id。
        返回 {逻辑字段: jira_field_id}。"""
        if self._field_map is not None and not force:
            return self._field_map
        fields = self._get(f"{_API}/field")
        if not isinstance(fields, list):
            raise JiraError("字段接口 /rest/api/2/field 返回异常。")

        fmap = dict(_SYSTEM_FIELDS)

        def _match(names_kw):
            for f in fields:
                name = str(f.get("name", "")).strip().lower()
                fid = f.get("id", "")
                if not fid:
                    continue
                for kw in names_kw:
                    if kw in name:
                        return fid
            return None

        # Severity：优先精确/包含 severity，其次中文「严重」
        sev = _match(["severity", "严重级别", "严重程度", "严重"])
        if sev:
            fmap["severity"] = sev
        # Closed Date
        closed = _match(["closed date", "close date", "关闭日期", "关闭时间"])
        if closed:
            fmap["closed_date"] = closed

        self._field_map = fmap
        logger.info("Jira 字段映射: %s", fmap)
        return fmap

    # ---------- JQL 检索（分页） ----------
    def search(self, jql, fields=None, page_size=1000,
               on_progress: Optional[Callable[[int, int, int], None]] = None) -> list:
        """按 JQL 分页拉取 issue，返回原始 issue 列表。
        on_progress(fetched, total, page_no)。"""
        if fields is None:
            fields = list(self.discover_fields().values())
        # 去重并保序
        seen = set()
        field_param = []
        for f in fields:
            if f and f not in seen:
                seen.add(f)
                field_param.append(f)

        out = []
        start = 0
        page = 0
        total = None
        while True:
            page += 1
            params = {
                "jql": jql,
                "startAt": start,
                "maxResults": page_size,
                "fields": ",".join(field_param),
            }
            data = self._get(f"{_API}/search", params=params)
            batch = data.get("issues", []) or []
            if total is None:
                total = int(data.get("total", len(batch)))
            out.extend(batch)
            if on_progress:
                on_progress(len(out), total if total is not None else len(out), page)
            # 终止条件：拿完 / 本页为空 / 服务端限制导致不足
            if not batch:
                break
            start += len(batch)
            if total is not None and start >= total:
                break
            # 服务端可能把 maxResults 限制为更小的值（如自建实例上限100），
            # 必须以响应里实际声明的 maxResults 判断是否末页，而不是请求的 page_size。
            actual_page = int(data.get('maxResults') or len(batch) or page_size)
            if len(batch) < actual_page:
                break
            if page >= 200:  # 安全上限：200*1000=20万
                logger.warning("Jira 拉取达到 200 页安全上限，停止分页")
                break
        return out

    @staticmethod
    def build_jql(project_key="", jql="", incremental_days=None) -> str:
        if jql and jql.strip():
            return jql.strip()
        conds = []
        if project_key:
            conds.append(f"project = {project_key.strip()}")
        if incremental_days:
            try:
                d = int(incremental_days)
                if d > 0:
                    since = (_dt.date.today() - _dt.timedelta(days=d)).strftime("%Y-%m-%d")
                    conds.append(f'updated >= "{since}"')
            except Exception:
                pass
        if not conds:
            # 没有任何过滤条件时给一个安全兜底（按更新时间倒序）
            return "ORDER BY updated DESC"
        return " AND ".join(conds) + " ORDER BY updated DESC"

    # ---------- 转 CSV 行 ----------
    def issues_to_rows(self, issues, field_map=None) -> list:
        """把 Jira issue 列表转成 [表头, 行...] 二维数组，列对齐 CSV_HEADERS。"""
        fmap = field_map or self.discover_fields()
        sev_id = fmap.get("severity")
        closed_id = fmap.get("closed_date")

        def f(issue, fid):
            if not fid:
                return None
            return (issue.get("fields") or {}).get(fid)

        rows = [list(CSV_HEADERS)]
        for issue in issues:
            fields = issue.get("fields") or {}
            key = issue.get("key", "")
            summary = (fields.get("summary") or "").strip()
            status = _names(fields.get("status"))
            a = fields.get("assignee") or {}
            assignee = a.get("displayName") or a.get("name") or a.get("emailAddress") or ""
            components = _names(fields.get("components"))
            labels = " ".join(fields.get("labels") or [])  # Jira labels 空格分隔
            created = _fmt_datetime(fields.get("created"))
            resolved = _fmt_datetime(fields.get("resolutiondate"))
            fix_versions = _names(fields.get("fixVersions"))
            severity = _extract_option(f(issue, sev_id)) if sev_id else ""
            closed = _fmt_datetime(f(issue, closed_id)) if closed_id else ""

            rows.append([
                key, summary, status, str(assignee).strip(), components, labels,
                created, resolved, fix_versions, severity, closed,
            ])
        return rows


# ==================== 配置持久化 ====================
CONFIG_VERSION = 1
DEFAULT_CONFIG = {
    "base_url": "",
    "auth_mode": "dc",        # dc | cloud
    "email": "",
    "project_key": "",
    "default_jql": "",
    "incremental_days": 7,
    "verify_ssl": True,
    # token 单独存，GET 时脱敏
}


def config_path(data_dir) -> str:
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "edart_config.json")


def load_config(data_dir) -> dict:
    p = config_path(data_dir)
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fp:
                saved = json.load(fp)
            if isinstance(saved, dict):
                cfg.update({k: saved.get(k, cfg[k]) for k in DEFAULT_CONFIG})
                cfg["token"] = saved.get("token", "")
        except Exception as e:
            logger.warning("读取 eDart 配置失败: %s", e)
            cfg["token"] = ""
    else:
        cfg["token"] = ""
    return cfg


def save_config(data_dir, data: dict, keep_token="") -> dict:
    """保存配置；data 中 token 为空（或脱敏掩码）时保留原 token。"""
    old = load_config(data_dir)
    cfg = dict(DEFAULT_CONFIG)
    cfg["base_url"] = (data.get("base_url") or old["base_url"]).strip()
    cfg["auth_mode"] = data.get("auth_mode") or old["auth_mode"]
    cfg["email"] = data.get("email", old["email"]).strip()
    cfg["project_key"] = data.get("project_key", old["project_key"]).strip()
    cfg["default_jql"] = data.get("default_jql", old["default_jql"]).strip()
    try:
        cfg["incremental_days"] = int(data.get("incremental_days", old["incremental_days"]))
    except Exception:
        cfg["incremental_days"] = old["incremental_days"]
    cfg["verify_ssl"] = bool(data.get("verify_ssl", old["verify_ssl"]))

    token = data.get("token", "") or ""
    if not token or set(token) <= {"*"}:  # 空或全是掩码 * -> 保留原值
        token = old.get("token") or keep_token
    cfg["token"] = token

    with open(config_path(data_dir), "w", encoding="utf-8") as fp:
        json.dump(cfg, fp, ensure_ascii=False, indent=2)
    return cfg


def public_config(cfg: dict) -> dict:
    """返回给前端的脱敏配置（不含明文 token）。"""
    out = {k: v for k, v in cfg.items() if k != "token"}
    out["has_token"] = bool(cfg.get("token"))
    out["token_hint"] = ("*" * 8) if cfg.get("token") else ""
    return out


def client_from_config(cfg: dict) -> JiraClient:
    return JiraClient(
        base_url=cfg.get("base_url", ""),
        auth_mode=cfg.get("auth_mode", "dc"),
        email=cfg.get("email", ""),
        token=cfg.get("token", ""),
        verify_ssl=cfg.get("verify_ssl", True),
    )


def write_rows_to_csv(rows, csv_path) -> int:
    """把二维数组以 utf-8-sig、标准 CSV 转义写盘，返回数据行数（不含表头）。"""
    import csv
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp, quoting=csv.QUOTE_MINIMAL)
        for row in rows:
            writer.writerow(["" if c is None else c for c in row])
    return max(0, len(rows) - 1)
