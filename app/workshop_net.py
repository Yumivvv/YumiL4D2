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
CDN_POOL_URL = "https://lytvpk-get-ips.laoyutang.cn/"

# 测速用的探针路径（Steam 的一张公开小图，返回很快）
_PROBE_PATH = "/ugc/11950912305938203132/6B59A7A5421AAECA12356E625388AEE4DB569E04/"

# 翻译
TRANSLATE_HOST = "translate.yandex.net"
TRANSLATE_PATH = "/api/v1/tr.json/translate"
# Yandex 的移动端 UA；用它才能免 key 调公开接口
TRANSLATE_UA = "ru.yandex.translate/3.20.2024"

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
    """拉一份 CDN 节点池，每项 {ip, region}。

    远端给的是带地名分类的 entries（例如 steam官方-首尔），
    拿不到就退回内置 IP + 本地地名表 —— 调用方永远能拿到非空列表。
    """
    nodes: list[dict] = []
    seen: set[str] = set()
    try:
        q = urllib.parse.urlencode({
            "domain": STEAM_CDN_HOST, "format": "entries",
        })
        req = urllib.request.Request(
            CDN_POOL_URL + "?" + q, headers={"User-Agent": UA})
        with WDNS.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise ValueError(f"节点池返回 HTTP {resp.status}")
            raw = json.loads(resp.read().decode("utf-8", "replace"))
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                ip = str(entry.get("ip") or "").strip()
                if not normalize_ip_list([ip]):
                    continue
                if ip in seen:
                    continue
                # 优先用本地地名表（给的是城市：首尔/东京…）；
                # 远端分类只到国家（steam官方-韩国），当地名兜底。
                known = region_for_ip(ip)
                region = known if known and known != "未知地区" \
                    else (_region_from_category(entry.get("category")) or known)
                seen.add(ip)
                nodes.append({"ip": ip, "region": region})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        nodes = []

    # 远端池不一定包含内置的那几个（比如大阪节点），补上，选择更多
    for ip in BUILTIN_CDN_IPS:
        if ip in seen:
            continue
        seen.add(ip)
        nodes.append({"ip": ip, "region": region_for_ip(ip)})

    if not nodes:
        for ip in BUILTIN_CDN_IPS:
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


def _yandex_ucid() -> str:
    """Yandex 移动端接口要一个 ucid（随便一个 8 位十六进制串就行）。"""
    import random

    return "%08x" % random.getrandbits(32)


def translate(text: str, target: str = "zh", timeout: float = 15.0) -> dict:
    """把文本翻成中文。

    依次尝试多个**免注册、免 API key** 的公开接口，第一个成功的就返回：

      1. MyMemory（实测最稳，国内能连，免费额度够看 MOD 描述）
      2. Yandex 公开接口（有时 403，作备份）

    返回 {"ok", "text", "provider", "error"}。
    已经是中文的直接返回原文并标注 skipped。
    """
    src = str(text or "").strip()
    if not src:
        return {"ok": False, "text": "", "provider": "", "error": "文本为空"}
    if looks_chinese(src):
        return {"ok": True, "text": src, "provider": "none", "skipped": True, "error": ""}

    # 公开接口对单次长度有限制，分段翻（按行/句切，尽量不切断句子）
    chunks = _split_chunks(src, 450)
    errors: list[str] = []
    # 整段一起猜一次当兜底提示：某些分段只有汉字（比如日文里的汉字词），
    # 单看那一段会猜成中文，用整段的结论纠正。
    hint = detect_lang(src)

    for name, fn in (("mymemory", _translate_chunk_mymemory),
                     ("yandex", _translate_chunk_yandex)):
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
    """
    lang = _TARGET_CODES.get((target or "zh").strip().lower(), target or "zh-CN")
    err = "翻译结果为空"
    for src in _source_candidates(chunk, hint):
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
        data = j.get("responseData") or {}
        got = str(data.get("translatedText") or "").strip()
        if not got:
            err = "翻译结果为空"
            continue
        # MyMemory 额度用尽时会返回一段英文提示，别把它当译文
        if "MYMEMORY WARNING" in got.upper():
            return {"ok": False, "text": "", "error": "免费额度用完了，稍后再试"}
        # 语向填错时接口会把原文吐回来（还会带一句 PLEASE SELECT TWO DISTINCT LANGUAGES）
        if got.lower() in (chunk.strip().lower(),) or "DISTINCT LANGUAGES" in got.upper():
            err = f"语向 {src}|{lang} 不被接受"
            continue
        # 日语/韩语没被翻掉（按 en 发过去时就这样）：换个语向再来一次
        if _untranslated_ratio(chunk, got) >= 0.4:
            err = f"语向 {src} 没翻出日语/韩语"
            continue
        return {"ok": True, "text": got, "error": "", "source": src}
    return {"ok": False, "text": "", "error": err}


def _translate_chunk_yandex(chunk: str, target: str, timeout: float,
                            hint: str = "") -> dict:
    """调 Yandex 的公开翻译接口（免 API key，有时 403，作备份）。"""
    params = urllib.parse.urlencode({
        "ucid": _yandex_ucid(),
        "srv": "android",
        "format": "text",
    })
    url = "https://" + TRANSLATE_HOST + TRANSLATE_PATH + "?" + params
    lang = _TARGET_CODES.get((target or "zh").strip().lower(), target or "zh-CN")
    err = "翻译结果为空"
    for src in _source_candidates(chunk, hint):
        form = urllib.parse.urlencode({
            "text": chunk,
            "lang": src + "-" + (lang.split("-")[0] or "zh"),
        }).encode()
        req = urllib.request.Request(
            url, data=form,
            headers={
                "User-Agent": TRANSLATE_UA,
                "Content-Type": "application/x-www-form-urlencoded",
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
        if j.get("code") not in (200, None):
            err = f"翻译失败（code {j.get('code')}）"
            continue
        lines = j.get("text") or []
        got = ""
        if isinstance(lines, list) and lines:
            got = str(lines[0])
        elif isinstance(lines, str) and lines:
            got = lines
        if not got.strip():
            err = "翻译结果为空"
            continue
        if got.strip().lower() == chunk.strip().lower():
            err = f"语向 {src} 不被接受"
            continue
        if _untranslated_ratio(chunk, got) >= 0.4:
            err = f"语向 {src} 没翻出日语/韩语"
            continue
        return {"ok": True, "text": got, "error": "", "source": src}
    return {"ok": False, "text": "", "error": err}


# ===========================================================================
# 创意工坊「浏览」（列表 / 搜索 / 排序 / 翻页）
# ===========================================================================
# 为什么列表要单独走一个代理：
#   Steam 官方的列表接口 `IPublishedFileService/QueryFiles` **必须用 publisher key**，
#   而且官方文档明确写了它「不能在客户端直接调用」；工坊网页 steamcommunity.com
#   在国内又经常被重置（实测 WinError 10054）。
#   所以列表走一个公开的只读中转（社区工具常见做法），
#   详情仍然走官方 GetPublishedFileDetails（不需要 key，国内能通）。
WORKSHOP_LIST_BASE = "https://l4d2-workshop.laoyutang.cn"

# 排序：trend=热门 / recent=最新 / top=最多订阅
SORT_MODES = ("trend", "recent", "top")

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
                        timeout: float = 25.0) -> dict:
    """拉一页工坊列表（L4D2，appid=550），带 10 分钟内存缓存。

    缓存的意义：切分类、点「稍后看」再点回来、来回滚列表时不该再等一次网络。
    返回 {"ok", "items": [...], "total", "page", "error", "cached"}。
    items 每项：{id, title, preview, author, fileType, views, subs, tags, children}
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
                "error": str(res.get("error") or ""), "cached": True}

    res = _fetch_workshop_list_net(query, page, sort, list(tag_key), kind, timeout)
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
                             timeout: float = 25.0) -> dict:
    """真正去问一次列表接口（没有缓存）。"""
    params = urllib.parse.urlencode({
        "page": normalize_page(page),
        "q": str(query or "").strip(),
        "sort": normalize_sort(sort),
        "filetype": _FILE_TYPE_OF_KIND[normalize_kind(kind)],
    })
    tag_list = normalize_tags(tags)
    if tag_list:
        params += "&" + urllib.parse.urlencode({"tags": ",".join(tag_list)})
    url = WORKSHOP_LIST_BASE + "/list?" + params
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with WDNS.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return {"ok": False, "items": [], "total": 0, "page": page,
                        "error": f"列表接口 HTTP {resp.status}"}
            body = resp.read()
    except urllib.error.HTTPError as e:
        return {"ok": False, "items": [], "total": 0, "page": page,
                "error": f"列表接口 HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"ok": False, "items": [], "total": 0, "page": page,
                "error": f"连不上列表接口（{type(e).__name__}）"}
    try:
        j = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return {"ok": False, "items": [], "total": 0, "page": page,
                "error": "列表接口返回的不是 JSON"}

    resp_obj = j.get("response") or {}
    raw_items = resp_obj.get("publishedfiledetails") or []
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