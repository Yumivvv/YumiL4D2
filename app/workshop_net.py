# Yumi的L4D2工具箱
# Copyright (C) 2026 ZengDeRong
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""创意工坊的网络增强：CDN 加速（DNS/IP 优选）+ 描述翻译。

## 为什么需要「创意工坊 DNS / IP 优选」

Steam 的图片和文件都走 `cdn.steamusercontent.com`。国内这个域名经常解析到
很远的节点，或者干脆解析失败 —— 表现就是工坊封面一片空白、下载龟速。

绕过办法很土但有效：**不走 DNS，直接连 IP**。把请求的 Host 头写成域名、
实际连到一个已知可用的 Steam CDN IP 上（TLS SNI 仍然用域名，证书照样对）。

这里维护一份内置 IP 列表，启动/手动触发时**并发测速**挑最快的那个，
之后所有工坊图片请求都走它。也可以手填 IP。

## 翻译

用来把 MOD 描述（很多是老外的英文/俄文）翻成中文。
默认走 Yandex 的公开接口：免注册、免 API key，直接 POST 文本即可。
失败就明确报错，不静默返回原文 —— 用户要知道「没翻成」而不是以为描述本来就长这样。
"""
from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterable

from . import netclient as NC
from . import workshop_dns as WDNS
from .util import Log

log = Log("workshop_net.log")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Steam CDN 域名（图片 / 文件都在这）
STEAM_CDN_HOST = "cdn.steamusercontent.com"
# 工坊封面现在走这个域名（和下载直链同一个 Akamai 池）
STEAM_IMAGE_HOST = "images.steamusercontent.com"

# 内置的 Steam CDN IP（就近的几个 Akamai/Valve 节点）。
# 这些只在本程序内部用，界面上永远只显示节点地名（见 region_for_ip）。
#
# 出处：这 6 个兜底 IP 及其**排列顺序**取自 LytVPK（LaoYutang，GPL-3.0）的
# `defaultSteamCDNIPs`：
# https://github.com/LaoYutang/lytvpk/blob/c8c68819695dfc282c4d059f62e0bf7742befc50/internal/network/ip_selector.go#L29-L37
# 本项目的修改：LytVPK 用这份表在远端节点池不可用时兜底；本项目同样只在
# `CDN_POOL_URL` 为空（不再请求任何第三方节点池）时用它，另加了下面的
# `IP_REGION_HINTS` 地名表（本项目自己整理）与 TCP/TLS/HEAD 测速实现。
BUILTIN_CDN_IPS = (
    "23.59.72.59",
    "23.59.72.42",
    "23.206.175.162",
    "23.206.175.170",
    "23.55.51.221",
    "23.67.75.74",
)

# 节点地名表：IP 只留在程序内部，UI 一律用地名。
# 远端节点池（见 CDN_POOL_URL）会带上「steam官方-首尔」这种分类，
# 优先用它的地名；表里这些是远端挂掉时的兜底。
IP_REGION_HINTS = {
    "2.17.106.6": "新加坡",
    "2.17.106.18": "新加坡",
    "23.61.202.191": "新加坡",
    "23.61.202.175": "新加坡",
    "23.193.186.33": "东京",
    "23.193.186.51": "东京",
    "23.59.72.59": "首尔",
    "23.59.72.42": "首尔",
    "23.206.175.162": "首尔",
    "23.206.175.170": "首尔",
    "23.55.51.221": "大阪",
    "23.67.75.74": "大阪",
    "184.26.127.25": "台北",
    "184.26.127.43": "台北",
}

# 地名里常见的英文 → 中文（远端分类偶尔是纯英文）
_EN_REGION_CN = {
    "seoul": "首尔", "tokyo": "东京", "osaka": "大阪", "singapore": "新加坡",
    "taipei": "台北", "hong kong": "香港", "hongkong": "香港",
    "los angeles": "洛杉矶", "frankfurt": "法兰克福", "london": "伦敦",
    "sydney": "悉尼", "mumbai": "孟买", "paris": "巴黎", "amsterdam": "阿姆斯特丹",
    "south korea": "首尔", "korea": "首尔", "japan": "东京", "taiwan": "台北",
}

# 远端 CDN 节点池（带地名分类）。拿不到就用 BUILTIN_CDN_IPS 兜底。
#
# ★ 历史说明（2026-11 变更）：这里原来指向第三方运营的节点池
#   （`lytvpk-get-ips.laoyutang.cn`），那是 LytVPK 维护者的线上服务，
#   对方已在 issue #1 中要求迁移 —— **已移除**。
#   现在候选节点只有两个来源：
#     1. 内置的 BUILTIN_CDN_IPS（就是上面那几个常用 Akamai 节点）
#     2. 用户自己在设置里填的节点（config 的 workshop_cdn_ip）
#   不再向任何第三方要节点列表。想扩节点就在设置里手动指定。
CDN_POOL_URL = ""

# 测速用的探针路径（Steam 的一张公开小图，返回很快）
_PROBE_PATH = "/ugc/11950912305938203132/6B59A7A5421AAECA12356E625388AEE4DB569E04/"

# 翻译
#
# ★ Yandex 的公开接口已经**彻底停用**，2026 年实测：
#     srv=android  → HTTP 403 {"code":405,"message":"Session is invalid"}
#     去掉 srv     → HTTP 410 "Yandex.Translate API v1 is no longer active.
#                    Please migrate to API v1.5"
#   而 v1.5 要 API key + 计费，不是「免注册」能用起来的东西。
#   所以兜底接口换成腾讯交互翻译（transmart）：免 key、国内直连快、
#   自动识别语种（中英日韩都实测可用），单块上限 6000 字符。
TRANSLATE_HOST = "transmart.qq.com"
TRANSLATE_PATH = "/api/imt"
# 腾讯前端自己用的固定 client_key 形状（chrome + 版本 + 系统 + 32 个 0 占位）
TRANSLATE_CLIENT_KEY = ("browser-chrome-120.0.0-Windows_10-x64-"
                        + "0" * 32)

# MyMemory 的 q 参数上限（**字符**，不是字节）。超了它返回
# HTTP 200 + responseStatus 403 + "QUERY LENGTH LIMIT EXCEEDED"。
MYMEMORY_MAX_CHARS = 500
# 腾讯交互翻译单块上限（实测超过会返回 "Too many characters (over 6000)"）
TRANSMART_MAX_CHARS = 5800

# 认为「已经是中文」时直接跳过翻译
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 日语假名（平假名 + 片假名 + 半角片假名）、韩文谚文。
# 工坊简介里这两种文字很常见，以前被判成「已经是中文」直接跳过，
# 或者硬按 en|zh 的语向发出去，结果就是「点了翻译没反应」。
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")

# 目标语言 → 各翻译接口认的语言代码
_TARGET_CODES = {"zh": "zh-CN", "zh-cn": "zh-CN", "en": "en", "ja": "ja", "ko": "ko"}


# ===========================================================================
# CDN IP 优选
# ===========================================================================
def normalize_ip_list(values: Iterable[str]) -> list[str]:
    """清洗 IP 列表：去空、去重、只留合法 IPv4/IPv6。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        ip = str(raw or "").strip()
        if not ip or ip in seen:
            continue
        try:
            socket.inet_pton(socket.AF_INET, ip)
        except OSError:
            try:
                socket.inet_pton(socket.AF_INET6, ip)
            except OSError:
                continue
        seen.add(ip)
        out.append(ip)
    return out


def is_steam_cdn_url(url: str) -> bool:
    """这个 URL 是不是走 Steam CDN（只有这种才值得按 IP 直连）。"""
    try:
        host = (urllib.parse.urlsplit(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return False
    return host in (STEAM_CDN_HOST, STEAM_IMAGE_HOST)


def _region_from_category(category: str) -> str:
    """把远端的分类文字（steam官方-首尔）洗成纯地名（首尔）。"""
    raw = str(category or "").strip()
    if not raw:
        return ""
    for sep in ("-", "－", "_", "/", "|"):
        if sep in raw:
            raw = raw.split(sep)[-1].strip()
    low = raw.lower()
    if low in _EN_REGION_CN:
        return _EN_REGION_CN[low]
    return raw


def region_for_ip(ip: str) -> str:
    """IP → 地名。查不到就返回「未知地区」，绝不把 IP 甩给用户。"""
    key = str(ip or "").strip()
    if not key:
        return ""
    return IP_REGION_HINTS.get(key) or "未知地区"


def fetch_cdn_nodes(timeout: float = 8.0) -> list[dict]:
    """拿一份 CDN 节点列表，每项 {ip, region}。

    ★ 现在**没有远端节点池**（原第三方池已在 issue #1 后移除），
      候选就是内置的 BUILTIN_CDN_IPS + 本地地名表。
      想用别的节点请在设置里「手动指定 IP」，不会向任何第三方要列表。
    """
    nodes: list[dict] = []
    seen: set[str] = set()
    if CDN_POOL_URL:
        # 留个口子：以后真有自建节点池，把 URL 填上这段就能用
        try:
            q = urllib.parse.urlencode({
                "domain": STEAM_CDN_HOST, "format": "entries",
            })
            req = urllib.request.Request(
                CDN_POOL_URL + "?" + q, headers={"User-Agent": UA})
            with WDNS.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    raw = json.loads(resp.read().decode("utf-8", "replace"))
                    if isinstance(raw, list):
                        for entry in raw:
                            if not isinstance(entry, dict):
                                continue
                            ip = str(entry.get("ip") or "").strip()
                            if not normalize_ip_list([ip]) or ip in seen:
                                continue
                            known = region_for_ip(ip)
                            region = known if known and known != "未知地区" \
                                else (_region_from_category(
                                    entry.get("category")) or known)
                            seen.add(ip)
                            nodes.append({"ip": ip, "region": region})
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pass

    # 内置节点永远补上（远端池就算有也常常漏掉大阪这类）
    for ip in BUILTIN_CDN_IPS:
        if ip in seen:
            continue
        seen.add(ip)
        nodes.append({"ip": ip, "region": region_for_ip(ip)})
    return nodes


def pick_cdn_node(nodes: list[dict], region: str) -> dict:
    """按地名挑一个节点（手动指定模式用）。挑不到返回空字典。"""
    want = str(region or "").strip()
    if not want:
        return {}
    for node in nodes or []:
        if str(node.get("region") or "") == want:
            return node
    return {}


def _probe_one(ip: str, timeout: float = 3.0) -> dict:
    """测一个 IP 到 Steam CDN 的连通性和延迟（毫秒），失败返回 -1。

    ★ 关键点：连的是 IP，但 TLS 的 **SNI 必须是域名** —— 否则服务器返回的证书
      是给 IP 签的（或者干脆是默认证书），Python 会直接
      `SSLCertVerificationError`。这也是「把域名换成 IP」最容易被忽略的一步。
    """
    t0 = time.time()
    ctx = ssl.create_default_context()
    try:
        raw_sock = socket.create_connection((ip, 443), timeout=timeout)
        # server_hostname 显式给域名 → 发出去的 SNI 是域名，证书能对上
        sock = ctx.wrap_socket(raw_sock, server_hostname=STEAM_CDN_HOST)
        conn = http.client.HTTPSConnection(STEAM_CDN_HOST, 443, timeout=timeout)
        # 复用已经建好的 TLS 连接，避免再自己握手一次
        conn.sock = sock
        conn.putrequest("HEAD", _PROBE_PATH, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", STEAM_CDN_HOST)
        conn.putheader("User-Agent", UA)
        conn.endheaders()
        resp = conn.getresponse()
        resp.read(64)
        ok = resp.status < 500
        conn.close()
    except (OSError, ssl.SSLError, http.client.HTTPException) as e:
        return {"ip": ip, "ms": -1, "ok": False, "error": type(e).__name__}
    ms = int((time.time() - t0) * 1000)
    return {"ip": ip, "ms": ms if ok else -1, "ok": ok, "error": "" if ok else "bad status"}


def test_ips(ips: Iterable[str], timeout: float = 3.0,
             progress: Callable[[int, int], None] | None = None) -> list[dict]:
    """并发测一批 IP，按延迟从快到慢返回。"""
    targets = normalize_ip_list(ips)
    if not targets:
        return []
    results: list[dict] = []
    lock = threading.Lock()
    queue = list(targets)
    qlock = threading.Lock()

    def worker() -> None:
        while True:
            with qlock:
                if not queue:
                    return
                ip = queue.pop(0)
            r = _probe_one(ip, timeout)
            with lock:
                results.append(r)
                if progress:
                    progress(len(results), len(targets))

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(min(6, len(targets)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    results.sort(key=lambda x: (0 if x["ok"] else 1, x["ms"] if x["ms"] >= 0 else 10 ** 9))
    return results


def best_ip(ips: Iterable[str] | None = None, timeout: float = 3.0) -> dict:
    """挑最快的 IP。全都失败时返回空结果。

    结果的 `region` 是地名（UI 只展示它，`ip` 留给自己用）。
    """
    pool = normalize_ip_list(ips or BUILTIN_CDN_IPS)
    res = test_ips(pool, timeout)
    good = [r for r in res if r["ok"]]
    if not good:
        return {"ok": False, "ip": "", "region": "", "ms": -1,
                "tested": len(res), "all": res, "error": "所有节点都连不上"}
    return {"ok": True, "ip": good[0]["ip"], "region": region_for_ip(good[0]["ip"]),
            "ms": good[0]["ms"], "tested": len(res), "all": res, "error": ""}


def best_node(nodes: list[dict] | None = None, timeout: float = 4.0) -> dict:
    """在节点池里测速挑最快的一个，返回 {ok, ip, region, ms, rows}。

    `rows` 每项 {region, ms, ok} —— 只有地名和延迟，可以安全交给 UI。
    """
    pool = nodes or fetch_cdn_nodes()
    ips = normalize_ip_list([n.get("ip") for n in pool])
    region_of = {str(n.get("ip")): str(n.get("region") or "") for n in pool
                 if n.get("ip")}
    if not ips:
        return {"ok": False, "ip": "", "region": "", "ms": -1,
                "rows": [], "error": "没有可用的加速节点"}
    res = test_ips(ips, timeout)
    rows = [{"region": region_of.get(r["ip"]) or region_for_ip(r["ip"]),
             "ms": int(r.get("ms") or -1), "ok": bool(r.get("ok"))}
            for r in res]
    good = [r for r in res if r.get("ok") and r.get("ms", -1) >= 0]
    if not good:
        return {"ok": False, "ip": "", "region": "", "ms": -1,
                "rows": rows, "error": "所有节点都连不上"}
    top = good[0]
    return {"ok": True, "ip": top["ip"],
            "region": region_of.get(top["ip"]) or region_for_ip(top["ip"]),
            "ms": int(top.get("ms") or -1), "rows": rows, "error": ""}


def rewrite_url(url: str, ip: str) -> tuple[str, dict]:
    """把一个 Steam CDN 的 URL 改写成「连指定 IP」的形式。

    返回 (新 URL, 额外需要的请求头)。urlopen 不支持自定义 Host/SNI，
    所以这里只处理「把域名换成 IP」，调用方还得自己补 Host 头。
    `ip` 为空时原样返回。
    """
    raw = str(url or "").strip()
    if not raw or not ip:
        return raw, {}
    try:
        p = urllib.parse.urlsplit(raw)
    except ValueError:
        return raw, {}
    host = (p.hostname or "").lower()
    if host not in (STEAM_CDN_HOST, STEAM_IMAGE_HOST):
        return raw, {}
    netloc = ip
    if p.port and p.port != 443:
        netloc = f"{ip}:{p.port}"
    new = urllib.parse.urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
    return new, {"Host": host}


def fetch_bytes_via_ip(url: str, ip: str, timeout: float = 15.0,
                       max_bytes: int = 8 * 1024 * 1024) -> bytes:
    """通过指定 IP 取一个 URL 的内容（绕过 DNS）。

    用 http.client 手工建连接，这样 Host 头和 SNI 都能精确控制。
    """
    raw = str(url or "").strip()
    if not raw:
        return b""
    try:
        p = urllib.parse.urlsplit(raw)
    except ValueError:
        return b""
    path = p.path or "/"
    if p.query:
        path += "?" + p.query
    host = p.hostname or STEAM_CDN_HOST
    port = p.port or (443 if p.scheme == "https" else 80)
    ctx = ssl.create_default_context()
    try:
        if p.scheme == "https":
            raw_sock = socket.create_connection((ip, port), timeout=timeout)
            # SNI 必须是域名（见 _probe_one 里的说明）
            sock = ctx.wrap_socket(raw_sock, server_hostname=host)
            conn = http.client.HTTPSConnection(host, port, timeout=timeout)
            conn.sock = sock
        else:
            conn = http.client.HTTPConnection(ip, port, timeout=timeout)
        conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host)
        conn.putheader("User-Agent", UA)
        conn.putheader("Accept", "image/*,*/*")
        conn.endheaders()
        resp = conn.getresponse()
        if resp.status >= 400:
            conn.close()
            return b""
        data = resp.read(max_bytes)
        conn.close()
        return data
    except (OSError, ssl.SSLError, http.client.HTTPException) as e:
        log(f"fetch via ip {ip} failed: {e!r}")
        return b""


def download_via_ip(url: str, dest_path: str, ip: str, timeout: float = 300.0,
                    progress: Callable[[int, int], None] | None = None) -> int:
    """把 URL 的内容写到 dest_path，连接强制走指定 IP。返回写入字节数。

    Host / SNI 仍然按域名走 —— 只换「连到哪」，不换「跟谁握手」。
    """
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("没有下载地址")
    p = urllib.parse.urlsplit(raw)
    path = p.path or "/"
    if p.query:
        path += "?" + p.query
    host = p.hostname or STEAM_CDN_HOST
    port = p.port or (443 if p.scheme == "https" else 80)
    ctx = ssl.create_default_context()
    if p.scheme == "https":
        raw_sock = socket.create_connection((ip, port), timeout=timeout)
        sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        conn = http.client.HTTPSConnection(host, port, timeout=timeout)
        conn.sock = sock
    else:
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
    try:
        conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host)
        conn.putheader("User-Agent", UA)
        conn.putheader("Accept", "*/*")
        conn.endheaders()
        resp = conn.getresponse()
        if resp.status >= 400:
            raise OSError(f"节点返回 HTTP {resp.status}")
        total = int(resp.getheader("Content-Length") or 0)
        got = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
        return got
    finally:
        conn.close()


# ===========================================================================
# 翻译
# ===========================================================================
def detect_lang(text: str) -> str:
    """粗猜一段文本是什么语言，返回 ISO 639-1 代码；猜不出来给 "en"。

    只用字符集统计判断 —— 目的是**把语向发对**，不是做真正的语言识别：
      - 假名 / 谚文占到一定比例 → 日语 / 韩语（工坊简介里这两种最常见）
      - 西里尔字母占优 → 俄语
      - 汉字占优 → 中文（调用方本来就会先跳过中文）
      - 其余 → 英语（占工坊简介的绝大多数）

    为什么按比例而不是「出现就算」：工坊简介经常是「一大段英文 + 一两句日语原话」，
    那种情况按英语发是对的（日语那两句顶多原样留下），
    但整段都在写日语时就必须按 ja 发 —— 以前写死成 en，界面表现就是「点了翻译没反应」。
    """
    s = str(text or "")
    if not s.strip():
        return "en"
    kana = len(_KANA_RE.findall(s))
    hangul = len(_HANGUL_RE.findall(s))
    cyr = len(_CYRILLIC_RE.findall(s))
    han = len(_CJK_RE.findall(s))
    latin = len(re.findall(r"[A-Za-z]", s))
    total = kana + hangul + han + cyr + latin
    if total <= 0:
        return "en"

    def share(n: int) -> float:
        return n / total

    # 假名/谚文只要成对出现、且占比不低就认（单个符号多半是颜文字或装饰）
    if kana >= 2 and share(kana) >= 0.18:
        return "ja"
    if hangul >= 2 and share(hangul) >= 0.18:
        return "ko"
    if cyr >= 2 and share(cyr) >= 0.5:
        return "ru"
    if han >= 5 and share(han) >= 0.5:
        return "zh"
    return "en"


def _source_candidates(chunk: str, hint: str = "") -> list[str]:
    """给一段文本列出「源语言」候选，按可信度排序（去重、去掉中文）。

    顺序 = 主导语种 → 出现的其他语种（假名→ja、谚文→ko）→ 整段提示 → 英语兜底。
    多列几项的意义：像「日文标题 + 英文正文」这种混排，先按 en 发的话
    日文那部分会原样吐回来，这时会自动退到 ja 再翻一次（见 `_kana_left`）。
    """
    out: list[str] = []

    def add(cand: object) -> None:
        c = str(cand or "").strip().lower()
        # 源语言 = 中文时这个请求没有意义（目标就是中文），接口还会报错
        if not c or c.startswith("zh") or c in out:
            return
        out.append(c)

    add(detect_lang(chunk))
    if len(_KANA_RE.findall(chunk)) >= 2:
        add("ja")
    if len(_HANGUL_RE.findall(chunk)) >= 2:
        add("ko")
    add(hint)
    add("en")
    return out or ["en"]


def _untranslated_ratio(src: str, out: str) -> float:
    """译完之后还剩多少日语假名/韩文 —— 用来判断「这一趟到底翻了没有」。"""
    src_n = len(_KANA_RE.findall(src)) + len(_HANGUL_RE.findall(src))
    if src_n < 2:
        return 0.0
    left = len(_KANA_RE.findall(out)) + len(_HANGUL_RE.findall(out))
    return left / src_n


def looks_chinese(text: str) -> bool:
    """文本里有相当比例的中文就认为不需要翻译。"""
    s = str(text or "")
    if not s.strip():
        return False
    # 日语/韩语优先：日文小说标题这类「汉字很多」的简介，
    # 以前会被当成中文直接跳过翻译，用户看到的就是「没反应」。
    if len(_KANA_RE.findall(s)) >= 2 or len(_HANGUL_RE.findall(s)) >= 2:
        return False
    hits = len(_CJK_RE.findall(s))
    # 有 5 个以上汉字，或者汉字占非空白字符 15% 以上
    non_space = len(re.sub(r"\s", "", s)) or 1
    return hits >= 5 or (hits / non_space) >= 0.15


def translate(text: str, target: str = "zh", timeout: float = 15.0) -> dict:
    """把文本翻成中文。

    依次尝试多个**免注册、免 API key** 的公开接口，第一个成功的就返回：

      1. MyMemory（国内能连，中文质量够看 MOD 描述；但单次上限 500 字符、
         有每日额度，超了会「HTTP 200 + responseStatus 403」而不是 4xx）
      2. 腾讯交互翻译 transmart（免 key、自动识别语种、单块 6000 字符，实测稳）

    返回 {"ok", "text", "provider", "error"}。
    已经是中文的直接返回原文并标注 skipped。
    """
    src = str(text or "").strip()
    if not src:
        return {"ok": False, "text": "", "provider": "", "error": "文本为空"}
    if looks_chinese(src):
        return {"ok": True, "text": src, "provider": "none", "skipped": True, "error": ""}

    # 公开接口对单次长度有限制，分段翻（按行/句切，尽量不切断句子）。
    # ★ 上限取 480 而不是 MyMemory 的 500：留 20 字符余量。
    #   以前写的是 450 —— 数字看着安全，但那是**字符**数，而且真正的坑不在
    #   分段本身（见 `_translate_chunk_mymemory` 里那段 403 说明）。
    chunks = _split_chunks(src, 480)
    errors: list[str] = []
    # 整段一起猜一次当兜底提示：某些分段只有汉字（比如日文里的汉字词），
    # 单看那一段会猜成中文，用整段的结论纠正。
    hint = detect_lang(src)

    # 顺序：MyMemory 先（国内连得上、中文质量还行），腾讯兜底
    # （免 key、自动识别语种、单块 6000 字符，实测很稳）。
    # ★ 以前的兜底是 Yandex，那个公开接口已经停用（403 / 410），
    #   留着它只会让每个失败都多一条「HTTP 403」的噪音错误。
    for name, fn in (("mymemory", _translate_chunk_mymemory),
                     ("transmart", _translate_chunk_transmart)):
        out: list[str] = []
        ok = True
        for chunk in chunks:
            got = fn(chunk, target, timeout, hint)
            if not got.get("ok"):
                ok = False
                errors.append(f"{name}: {got.get('error') or '失败'}")
                break
            out.append(got["text"])
        if ok:
            return {"ok": True, "text": "\n".join(out), "provider": name,
                    "skipped": False, "error": "", "source": hint}

    return {"ok": False, "text": "", "provider": "",
            "error": "；".join(errors) or "所有翻译接口都失败了"}


def _split_chunks(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    buf = ""
    for para in text.splitlines(keepends=True):
        if len(buf) + len(para) > limit and buf:
            out.append(buf)
            buf = ""
        if len(para) > limit:
            # 单段太长，硬切
            for i in range(0, len(para), limit):
                out.append(para[i:i + limit])
        else:
            buf += para
    if buf:
        out.append(buf)
    return out


def _translate_chunk_mymemory(chunk: str, target: str, timeout: float,
                              hint: str = "") -> dict:
    """MyMemory 的公开接口（免 key，国内可连）。

    源语言以前写死成 en，日语/韩语简介发过去等于「让英语翻译器翻日文」，
    返回的常常是原文或者一句英文报错，表现就是「点了翻译没反应」。
    现在先按字符集猜语向，猜错（返回原文 / 报语言对无效）再依次退。

    ★ **「翻译 HTTP 403」的根因就在这个函数里**，分两层：

      1. MyMemory 的 q 参数**最多 500 个字符**。超了它不返回 4xx，
         而是 **HTTP 200 + body 里 `responseStatus: 403` +
         "QUERY LENGTH LIMIT EXCEEDED"**。以前只判 `resp.status != 200`，
         于是这种「200 但内容是报错」被当成成功继续往下走，最后把那句
         QUERY LENGTH LIMIT 当译文显示，或者把它当「语向不对」反复重试。
      2. 以前 `_split_chunks` 按 450 切 —— 但那是**字符**，MyMemory 数的是
         **字符**没错，450 本来是安全的；真正的坑是调用方传进来的整段
         偶尔会超（拼接、翻译整段详情时），以及额度耗尽时它返回 429 +
         "MYMEMORY WARNING"，那种也会被当成译文。

    所以这里两道闸都补上：先按 500 字符硬校验，再逐个检查 body 里的
    responseStatus / quotaFinished，最后才相信 translatedText。
    """
    lang = _TARGET_CODES.get((target or "zh").strip().lower(), target or "zh-CN")
    err = "翻译结果为空"
    for src in _source_candidates(chunk, hint):
        # ★ 硬校验：超过 500 字符的请求必然被 MyMemory 拒（403），
        #   直接判失败交给下一个 provider，别浪费一次网络往返。
        if len(chunk) > MYMEMORY_MAX_CHARS:
            return {"ok": False, "text": "",
                    "error": f"这段太长（{len(chunk)} 字符 > "
                             f"{MYMEMORY_MAX_CHARS}），换一家的接口"}
        q = urllib.parse.urlencode({"q": chunk, "langpair": src + "|" + lang})
        req = urllib.request.Request(
            "https://api.mymemory.translated.net/get?" + q,
            headers={"User-Agent": UA},
        )
        try:
            with WDNS.urlopen(req, timeout=timeout) as resp:
                # workshop_dns 不会为 4xx/5xx 抛 HTTPError，这里自己判
                if resp.status != 200:
                    err = f"翻译服务返回 HTTP {resp.status}"
                    continue
                body = resp.read()
        except urllib.error.HTTPError as e:
            # 429 = 额度用完（它 body 里还会写 MYMEMORY WARNING）
            if e.code == 429:
                err = "免费额度用完了，稍后再试"
            else:
                err = f"HTTP {e.code}"
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            err = f"连不上（{type(e).__name__}）"
            continue
        try:
            j = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            err = "返回的不是 JSON"
            continue

        # ★★ 关键：HTTP 200 不代表成功。
        #   超长 → responseStatus 403 + "QUERY LENGTH LIMIT EXCEEDED"
        #   额度 → responseStatus 429 + "MYMEMORY WARNING"
        #   以前只看 resp.status，这两种都会被当成正常译文往下走。
        rs = j.get("responseStatus")
        try:
            rs_int = int(rs)
        except (TypeError, ValueError):
            rs_int = 0
        if j.get("quotaFinished") or rs_int == 429:
            err = "免费额度用完了，稍后再试"
            continue
        detail = str(j.get("responseDetails") or "")
        if rs_int and rs_int != 200:
            if "QUERY LENGTH LIMIT" in detail.upper():
                err = (f"这段太长（{len(chunk)} 字符，接口上限 "
                       f"{MYMEMORY_MAX_CHARS}）")
            else:
                err = f"翻译服务返回 {rs_int}：{detail[:60] or '未知错误'}"
            continue

        data = j.get("responseData") or {}
        got = str(data.get("translatedText") or "").strip()
        if not got:
            err = "翻译结果为空"
            continue
        # 兜底：有些老版本只在 translatedText 里塞提示，responseStatus 还是 200
        up = got.upper()
        if "MYMEMORY WARNING" in up:
            err = "免费额度用完了，稍后再试"
            continue
        if "QUERY LENGTH LIMIT" in up or "MAX ALLOWED" in up:
            err = f"这段太长（{len(chunk)} 字符，接口上限 {MYMEMORY_MAX_CHARS}）"
            continue
        # 语向填错时接口会把原文吐回来（还会带一句 PLEASE SELECT TWO DISTINCT LANGUAGES）
        if got.lower() in (chunk.strip().lower(),) or "DISTINCT LANGUAGES" in up:
            err = f"语向 {src}|{lang} 不被接受"
            continue
        # 日语/韩语没被翻掉（按 en 发过去时就这样）：换个语向再来一次
        if _untranslated_ratio(chunk, got) >= 0.4:
            err = f"语向 {src} 没翻出日语/韩语"
            continue
        return {"ok": True, "text": got, "error": "", "source": src}
    return {"ok": False, "text": "", "error": err}


def _translate_chunk_transmart(chunk: str, target: str, timeout: float,
                               hint: str = "") -> dict:
    """腾讯交互翻译（transmart）的公开接口 —— 免 key、国内直连。

    为什么用它当兜底：Yandex 那个公开接口已经停用（403 Session is invalid /
    410 API v1 is no longer active），而 Google 的 translate_a/single 现在
    一律 429。腾讯这个接口是 `transmart.qq.com` 网页版自己在用的，
    不需要注册、不需要 API key，自动识别源语言。

    请求要点（少一个字段它就报 "Invalid value of source.text_list"）：
      · `header.fn` = "auto_translation"
      · `header.client_key` = 前端那个固定形状的串
      · `source.text_list` 必须是**数组**，不能是 `source.text`
      · `target.lang` 用两字母码（zh / en / ja / ko）
    """
    # 腾讯只认两字母码，且不支持 zh-CN 这种带地区的
    tgt = (target or "zh").strip().lower().split("-")[0] or "zh"
    if len(chunk) > TRANSMART_MAX_CHARS:
        return {"ok": False, "text": "",
                "error": f"这段太长（{len(chunk)} 字符 > {TRANSMART_MAX_CHARS}）"}

    # 源语言：先用猜出来的，猜错（或它自己识别失败）再退到 auto
    cands = _source_candidates(chunk, hint) or ["auto"]
    if "auto" not in cands:
        cands = list(cands) + ["auto"]

    payload_base = {
        "header": {"fn": "auto_translation", "client_key": TRANSLATE_CLIENT_KEY},
        "type": "plain",
        "model_category": "normal",
        "target": {"lang": tgt},
    }
    err = "翻译结果为空"
    for src in cands:
        payload = dict(payload_base)
        payload["source"] = {"lang": src, "text_list": [chunk]}
        req = urllib.request.Request(
            "https://" + TRANSLATE_HOST + TRANSLATE_PATH,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "User-Agent": UA,
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://transmart.qq.com/zh-CN/index",
                "Origin": "https://transmart.qq.com",
            },
        )
        try:
            with WDNS.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    err = f"翻译服务返回 HTTP {resp.status}"
                    continue
                body = resp.read()
        except urllib.error.HTTPError as e:
            err = f"翻译服务返回 HTTP {e.code}"
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            err = f"连不上翻译服务：{type(e).__name__}"
            continue
        try:
            j = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            err = "翻译服务返回的不是 JSON"
            continue

        # ★ 它不看 HTTP 状态码，一切都在 header.ret_code 里：
        #   "succ" 才算成功；失败会带 message，比如
        #   "Required engine is not found, please retry later"（语种没有引擎）
        #   "Too many characters (over 6000) in block"
        head = j.get("header") or {}
        ret = str(head.get("ret_code") or "")
        if ret != "succ":
            msg = str(j.get("message") or "")
            if "too many characters" in msg.lower():
                return {"ok": False, "text": "",
                        "error": f"这段太长（{len(chunk)} 字符）"}
            if "engine is not found" in msg.lower():
                err = f"这个语向（{src}→{tgt}）翻译引擎不支持"
                continue
            err = f"翻译失败（{ret or '未知'}）：{msg[:60]}"
            continue

        got = j.get("auto_translation") or []
        if isinstance(got, list):
            text = "\n".join(str(x) for x in got)
        else:
            text = str(got)
        text = text.strip()
        if not text:
            err = "翻译结果为空"
            continue
        # 原样吐回来 = 这个语向没生效
        if text.lower() == chunk.strip().lower():
            err = f"语向 {src} 不被接受"
            continue
        if _untranslated_ratio(chunk, text) >= 0.4:
            err = f"语向 {src} 没翻出日语/韩语"
            continue
        return {"ok": True, "text": text, "error": "", "source": src}
    return {"ok": False, "text": "", "error": err}


# ===========================================================================
# 创意工坊「浏览」（列表 / 搜索 / 排序 / 翻页）
# ===========================================================================
# ★ 历史说明（2026-11 变更）：这里原来调用第三方运营的中转
#   （`l4d2-workshop.laoyutang.cn/list`），那是 LytVPK 维护者的线上服务，
#   会占用对方的 Cloudflare Workers 与 Steam Web API 额度，
#   对方已在 issue #1 中要求迁移 —— 现在**不再调用任何第三方中转**。
#
# 现在直接用 Steam 官方的 `IPublishedFileService/QueryFiles`。
# ★ 这个接口**必须带 Steam Web API key**（不带 key 实测返回 403
#   "Access is denied. Please verify your key= parameter"）。
#   key 由用户在「设置 → 网络」里自己填，只存本地 config.json，
#   绝不写死进源码 —— 用的是使用者自己的额度。
#   没填 key 时列表页会明确提示，而不是悄悄调用别人的服务兜底。
WORKSHOP_QUERY_API = (
    "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/")

# 排序：trend=热门 / recent=最新 / top=最多订阅
SORT_MODES = ("trend", "recent", "top")
# 映射到 Steam QueryFiles 的排序枚举：
#   0 = Trending（热度）  1 = MostRecent（最新）  3 = TopRated（最高评分）
_STEAM_SORT = {"trend": 0, "recent": 1, "top": 3}

# 没配 key 时的统一提示（界面直接显示这句话）
NO_KEY_ERROR = (
    "列表搜索需要你自己的 Steam Web API Key（设置 → 网络 → Steam API Key）。"
    "详情和下载不需要 key，可以照常使用")

# 浏览对象：mod=单件（含地图/音效等所有普通物品）/ collection=合集
BROWSE_KINDS = ("mod", "collection")

# 列表接口的内存缓存：10 分钟内同样的「关键词+页+排序+类型+标签」直接本地返回
LIST_TTL = 600.0
_LIST_LOCK = threading.Lock()
_LIST_CACHE: dict[tuple, tuple[float, dict]] = {}

# 接口的 filetype 参数（注意：不是 Steam 物品的 file_type 字段）
#   0 = 普通物品（单件 MOD）  1 = 合集
_FILE_TYPE_OF_KIND = {"mod": 0, "collection": 1}


def normalize_sort(value: object) -> str:
    v = str(value or "").strip().lower()
    return v if v in SORT_MODES else "trend"


def normalize_page(value: object) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(1000, n))


def normalize_kind(value: object) -> str:
    v = str(value or "").strip().lower()
    return v if v in BROWSE_KINDS else "mod"


def normalize_tags(value: object) -> list[str]:
    """标签参数：接受列表或逗号分隔的字符串，去空去重，最多 8 个。

    接口里多个标签是 AND 关系（Weapons,Survivors 只返回同时带两个标签的）。
    """
    if isinstance(value, str):
        parts = re.split(r"[,，]", value)
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = []
    out: list[str] = []
    seen: set[str] = set()
    for raw in parts:
        tag = str(raw or "").strip()
        if not tag or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        out.append(tag)
        if len(out) >= 8:
            break
    return out


def fetch_workshop_list(query: str = "", page: int = 1, sort: str = "trend",
                        tags: object = None, kind: str = "mod",
                        timeout: float = 25.0, api_key: str = "") -> dict:
    """拉一页工坊列表（L4D2，appid=550），带 10 分钟内存缓存。

    缓存的意义：切分类、点「稍后看」再点回来、来回滚列表时不该再等一次网络。
    返回 {"ok", "items": [...], "total", "page", "error", "cached", "needKey"}。
    items 每项：{id, title, preview, author, fileType, views, subs, tags, children}

    ★ `api_key` 是使用者自己的 Steam Web API Key（Steam 的列表接口强制要求）。
      没传 key 时返回 `needKey: True` + 明确提示，不会去调任何第三方中转。
    """
    tag_key = tuple(normalize_tags(tags))
    key = (str(query or "").strip(), normalize_page(page),
           normalize_sort(sort), normalize_kind(kind), tag_key)
    with _LIST_LOCK:
        hit = _LIST_CACHE.get(key)
    if hit and time.time() - hit[0] <= LIST_TTL:
        res = hit[1]
        return {"ok": res.get("ok", False),
                "items": [dict(x) for x in res.get("items", [])],
                "total": int(res.get("total") or 0),
                "page": int(res.get("page") or 1),
                "error": str(res.get("error") or ""), "cached": True,
                "needKey": False}

    res = _fetch_workshop_list_net(query, page, sort, list(tag_key), kind,
                                   timeout, api_key)
    if res.get("ok"):
        with _LIST_LOCK:
            _LIST_CACHE[key] = (time.time(), {
                "ok": True, "items": res.get("items") or [],
                "total": res.get("total") or 0, "page": res.get("page") or 1,
                "error": "",
            })
            if len(_LIST_CACHE) > 120:
                for old in sorted(_LIST_CACHE, key=lambda k: _LIST_CACHE[k][0])[:40]:
                    _LIST_CACHE.pop(old, None)
    res = dict(res)
    res["cached"] = False
    return res


def clear_list_cache() -> None:
    """清空列表缓存（设置里改节点、或测试要拿实时数据时用）。"""
    with _LIST_LOCK:
        _LIST_CACHE.clear()


def _fetch_workshop_list_net(query: str = "", page: int = 1, sort: str = "trend",
                             tags: object = None, kind: str = "mod",
                             timeout: float = 25.0,
                             api_key: str = "") -> dict:
    """真正去问一次列表接口（没有缓存）—— 走 Steam 官方 QueryFiles。

    ★ 需要调用者自己的 Steam Web API Key（`api_key` 参数）。
      没有 key 时**不发起请求**、也不回退到任何第三方服务，
      直接返回一句明确的提示（`NO_KEY_ERROR`），界面照这句话显示。
    """
    key = str(api_key or "").strip()
    if not key:
        return {"ok": False, "items": [], "total": 0, "page": page,
                "error": NO_KEY_ERROR, "needKey": True}

    tag_list = normalize_tags(tags)
    params = {
        "key": key,
        "query_type": 1,                      # 1 = ranked by vote
        "page": normalize_page(page) - 1,      # ★ Steam 的页码从 0 开始
        "numperpage": 30,
        "creator_appid": 550,
        "appid": 550,
        # feed 决定「单件 / 合集」：0 = 普通物品，1 = 合集
        "filetype": _FILE_TYPE_OF_KIND[normalize_kind(kind)],
        "return_tags": "true",
        "return_previews": "true",
        "return_short_description": "true",
        "return_metadata": "true",
        "strip_description_bbcode": "false",
        # 排序枚举：0 热度 / 1 最新 / 3 最高评分
        "days": 7,
    }
    q = str(query or "").strip()
    if q:
        params["search_text"] = q
    if tag_list:
        params["requiredtags"] = ",".join(tag_list)
    # Steam 的排序既可以用 query_type，也可以用 days+sortmethod；这里用前者
    params["query_type"] = _STEAM_SORT.get(normalize_sort(sort), 0)

    try:
        resp = NC.get(WORKSHOP_QUERY_API, params=params,
                      headers={"User-Agent": UA}, timeout=(5, max(8, int(timeout))))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "items": [], "total": 0, "page": page,
                "error": f"连不上 Steam 列表接口（{type(e).__name__}）"}

    status = int(getattr(resp, "status_code", 0) or 0)
    if status == 403:
        # key 无效 / 没有权限
        return {"ok": False, "items": [], "total": 0, "page": page,
                "error": "Steam 拒绝了请求：API Key 无效或没有权限，"
                         "请在设置 → 网络里换一个自己的 key",
                "needKey": True}
    if status != 200:
        return {"ok": False, "items": [], "total": 0, "page": page,
                "error": f"Steam 列表接口 HTTP {status}"}
    try:
        j = resp.json()
    except ValueError:
        return {"ok": False, "items": [], "total": 0, "page": page,
                "error": "Steam 列表接口返回的不是 JSON"}

    resp_obj = j.get("response") or {}
    raw_items = (resp_obj.get("publishedfiledetails")
                 or resp_obj.get("publishedfiledetails") or [])
    total = int(resp_obj.get("total") or 0)
    items: list[dict] = []
    for it in raw_items:
        wid = str(it.get("publishedfileid") or "")
        if not wid:
            continue
        tags_out = []
        for t in (it.get("tags") or []):
            if isinstance(t, dict):
                tag = str(t.get("tag") or "").strip()
                if tag:
                    tags_out.append(tag)
        subs = it.get("subscriptions")
        try:
            subs_n = int(subs or 0)
        except (TypeError, ValueError):
            subs_n = 0
        try:
            children = int(it.get("num_children") or 0)
        except (TypeError, ValueError):
            children = 0
        items.append({
            "id": wid,
            "title": (it.get("title") or "").strip(),
            "preview": it.get("preview_url") or "",
            "author": str(it.get("creator") or ""),
            "fileType": int(it.get("file_type") or 0),
            "views": int(it.get("views") or 0),
            "subs": subs_n,
            "favorited": int(it.get("favorited") or 0),
            "children": children,
            "created": int(it.get("time_created") or 0),
            "updated": int(it.get("time_updated") or 0),
            "tags": tags_out,
        })
    return {"ok": True, "items": items, "total": total,
            "page": normalize_page(page), "error": ""}
