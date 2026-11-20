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

"""创意工坊导入：给一个工坊 ID / 链接，把文件下到本地 addons。

两条链路各管一件事，互不依赖：

1. **下载** —— `steamworkshop.download` 这个第三方站
   往首页 POST `url` 参数，它会 302 到 `/download/view/<id>`，
   页面上直接给出 CDN 直链（`cdn.steamusercontent.com/...`）、标题、文件名、体积。
   这个站国内能连，所以作为下载主通道。

2. **依赖（必需物品）** —— 只有 Steam 工坊页面 HTML 里有（`Required items` 区块），
   官方 API 的 `GetPublishedFileDetails` **不含依赖字段**。
   而 `steamcommunity.com` 国内经常被重置，所以这里做成
   「能拿到就解析，拿不到就静默跳过」—— 绝不能因为查不到依赖就让下载失败。

设计原则：**下载是主功能，依赖检测是加分项**。
依赖那一步失败时，UI 只标注「未能检查前置」，不影响本体下下来。
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

from . import workshop_dns as WDNS
from .util import Log

log = Log("workshop_dl.log")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 第三方下载站（国内可连）。首页 POST url=... 就会跳转到详情页。
DL_SITE = "http://steamworkshop.download/"
DL_VIEW = "http://steamworkshop.download/download/view/{}"
WORKSHOP_PAGE = "https://steamcommunity.com/sharedfiles/filedetails/?id={}"
STEAM_API = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"

# 只认这些 ID 形态：纯数字，或各种工坊链接
_ID_RE = re.compile(r"(?<!\d)(\d{5,20})(?!\d)")
_URL_ID_RE = re.compile(r"[?&]id=(\d{5,20})")

# 默认下载线程数；实际值由设置里的 download_threads 决定。
#
# 上限为什么从 8 提到 16：
#   * 下载站给的是 Steam CDN 直链，同一 IP 并发 16 条实测不会被限速/掐连接
#     （家用 100~500M 宽带下，8 条经常吃不满带宽，16 条能跑满）；
#   * 工坊 MOD 普遍是「几十个小文件」，不是「几个大文件」——并发高一点收益明显；
#   * 再高收益就开始变差：每个 MOD 先要现解析直链（走下载站，几秒一次），
#     线程多于 16 之后瓶颈全在解析而不是传输，反而更容易被下载站限流。
# 保守的机器（老机械盘 / 小内存）照样可以选 1~4。
DEFAULT_THREADS = 4
MIN_THREADS = 1
MAX_THREADS = 16

# 单个文件的下载超时（秒）；大 MOD 可能几百 MB
DL_TIMEOUT = 300
# 查依赖时给工坊页面的超时。这个站在国内常常直接重置，所以给短一点，别卡住
DEP_TIMEOUT = 8

# ---------------------------------------------------------------------------
# 浏览时点开一个合集：**先只列成员，不逐个查下载直链**。
#
# 实测一个 875 个成员的合集，逐个查下载站（每个约 1.4 秒、4 线程）要 20 分钟，
# 界面上就是「一直在读取详情」。所以浏览阶段只做两件事：
#   1. 官方 API 按 20 个一批拿标题/封面（几十个成员一两秒就完）
#   2. 列表先给前 COLLECT_FAST_LIMIT 个
# 直链留到**真的点下载**时再逐个解析（下载线程里边解析边下，见 download()）。
# ---------------------------------------------------------------------------
COLLECT_FAST_LIMIT = 60

# ---------------------------------------------------------------------------
# 内存缓存：工坊信息是「读多写少」的，同一批 ID 在几分钟内会反复问
#   * 详情页直链：下载站的链接有效期很长，缓存 10 分钟完全安全
#   * 官方详情：标题/体积基本不变，缓存 10 分钟
# 有了它，「点开一个 MOD → 点下载」这条链路从 3 次网络往返降到 0 次。
# ---------------------------------------------------------------------------
DETAIL_TTL = 600.0
RESOLVE_TTL = 600.0
COLLECTION_TTL = 600.0
_CACHE_LOCK = threading.Lock()
_DETAILS_CACHE: dict[str, tuple[float, dict]] = {}
_RESOLVE_CACHE: dict[str, tuple[float, dict]] = {}
_COLLECTION_CACHE: dict[str, tuple[float, dict]] = {}


def _cache_get(store: dict, key: str, ttl: float) -> dict | None:
    with _CACHE_LOCK:
        hit = store.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > ttl:
        with _CACHE_LOCK:
            store.pop(key, None)
        return None
    return dict(value)


def _cache_put(store: dict, key: str, value: dict) -> None:
    with _CACHE_LOCK:
        store[key] = (time.time(), dict(value))
        # 别让缓存无限长：只留最近 500 条
        if len(store) > 500:
            for old in sorted(store, key=lambda k: store[k][0])[:100]:
                store.pop(old, None)


def clear_caches() -> None:
    """换加速节点 / 手动刷新时清空（给测试和设置里「刷新」用）。"""
    with _CACHE_LOCK:
        _DETAILS_CACHE.clear()
        _RESOLVE_CACHE.clear()
        _COLLECTION_CACHE.clear()


def clamp_threads(value: object) -> int:
    """把任意输入收成 MIN_THREADS~MAX_THREADS（当前 1~16）的线程数。"""
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_THREADS
    return max(MIN_THREADS, min(MAX_THREADS, n))


# ===========================================================================
# 输入解析
# ===========================================================================
def parse_workshop_id(text: str) -> str:
    """从用户输入里抠出工坊 ID。

    接受：
      - 纯数字：3829533320
      - 链接：https://steamcommunity.com/sharedfiles/filedetails/?id=3829533320
      - 带一堆别的参数的链接
    返回空串表示认不出。
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    # 先按「?id=xxx」精确取，避免链接里别的数字抢先
    m = _URL_ID_RE.search(raw)
    if m:
        return m.group(1)
    # 纯数字
    if raw.isdigit():
        return raw if 5 <= len(raw) <= 20 else ""
    # 兜底：整串里最像 ID 的那一段
    m = _ID_RE.search(raw)
    return m.group(1) if m else ""


# ===========================================================================
# 下载站：拿直链
# ===========================================================================
class _HeadRequest(urllib.request.Request):
    """urllib 默认会把 POST 在 302 后改成 GET，这里显式保持行为一致。"""


def _http(req: urllib.request.Request, timeout: int) -> tuple[int, bytes, str]:
    """发请求，返回 (状态码, 内容, 最终 URL)。

    走设置里的「工坊 DNS」（workshop_dns.urlopen），拿不到自定义 DNS 时它会
    自动回落系统解析；注意它不像 urllib 那样为 4xx/5xx 抛 HTTPError，
    所以状态码要靠返回值自己看。
    """
    with WDNS.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), r.geturl()


def resolve_download(wid: str) -> dict:
    """查一个工坊 ID 的下载信息（带 10 分钟内存缓存）。

    返回：
        {"ok", "id", "title", "url", "filename", "size", "sizeText",
         "preview", "filenameOnSite", "error"}
    """
    wid = str(wid or "").strip()
    if not wid.isdigit():
        return {"ok": False, "id": wid, "error": "工坊 ID 必须是纯数字"}
    cached = _cache_get(_RESOLVE_CACHE, wid, RESOLVE_TTL)
    if cached is not None:
        return cached
    info = _resolve_download_net(wid)
    # 只有成功的才缓存：失败多半是站点过载，缓存下来会一直失败
    if info.get("ok"):
        _cache_put(_RESOLVE_CACHE, wid, info)
    return info


def _resolve_download_net(wid: str) -> dict:
    """真正去下载站问一次（没有缓存）。"""
    page = WORKSHOP_PAGE.format(wid)
    data = urllib.parse.urlencode({"url": page}).encode()
    req = urllib.request.Request(
        DL_SITE,
        data=data,
        headers={
            "User-Agent": UA,
            "Referer": DL_SITE,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        status, body, final_url = _http(req, DL_TIMEOUT)
    except urllib.error.HTTPError as e:
        return {"ok": False, "id": wid,
                "error": f"下载站返回 HTTP {e.code}（站点可能过载，稍后重试）"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"ok": False, "id": wid, "error": f"连不上下载站：{e}"}

    text = body.decode("utf-8", "replace")
    if "Too many connections" in text or "Database Error" in text:
        return {"ok": False, "id": wid,
                "error": "下载站数据库过载，稍后重试（不是你的问题）"}

    info = _parse_download_page(text)
    info["id"] = wid
    info["viewUrl"] = final_url or DL_VIEW.format(wid)
    if not info.get("url"):
        if "not found" in text.lower() or "error" in text.lower():
            info["error"] = "下载站上没有这个 ID（可能已删除或私有）"
        else:
            info["error"] = "没在页面上找到下载直链"
        info["ok"] = False
        return info
    info["ok"] = True
    return info


def _parse_download_page(text: str) -> dict:
    """从下载站详情页 HTML 里抠出直链 / 标题 / 文件名 / 体积。

    页面结构（实测）：
        <b><a href='https://cdn.steamusercontent.com/...' title='标题'>Download: 标题</a> [Left 4 Dead 2]<br>
        ... Size: 23.7MB ... Subscribers: 211 ... Filename: xxx.vpk
    """
    out: dict = {
        "title": "", "url": "", "filename": "", "size": 0, "sizeText": "",
        "preview": "", "filenameOnSite": "", "error": "",
    }

    # 下载直链：优先 "Download:" 那个 <a>
    m = re.search(
        r"<a\s+href='([^']+)'\s+title='([^']*)'\s*>\s*Download:", text, re.I)
    if not m:
        # 退一步：任何 cdn.steamusercontent 的链接
        m2 = re.search(r"href='(https://cdn\.steamusercontent\.com/[^']+)'", text)
        if m2:
            out["url"] = _html.unescape(m2.group(1))
    else:
        out["url"] = _html.unescape(m.group(1))
        out["title"] = _html.unescape(m.group(2)).strip()

    if not out["title"]:
        m = re.search(r"title='([^']+)'>Download:", text)
        if m:
            out["title"] = _html.unescape(m.group(1)).strip()

    # 体积：Size: 23.7MB
    m = re.search(r"Size:\s*([\d.]+\s*[KMGT]?B)", text, re.I)
    if m:
        out["sizeText"] = m.group(1).strip()
        out["size"] = _size_to_bytes(out["sizeText"])

    # 站点上报的文件名：Filename: xxx.vpk
    m = re.search(r"Filename:\s*([^<\r\n]+)", text, re.I)
    if m:
        out["filenameOnSite"] = _html.unescape(m.group(1)).strip()

    # 封面
    m = re.search(r"background:url\((https://images\.steamusercontent\.com/[^)\s]+)\)", text)
    if m:
        out["preview"] = m.group(1)

    return out


def _size_to_bytes(text: str) -> int:
    """'23.7MB' → 字节数。"""
    m = re.match(r"\s*([\d.]+)\s*([KMGT]?)B", str(text or ""), re.I)
    if not m:
        return 0
    try:
        n = float(m.group(1))
    except ValueError:
        return 0
    unit = (m.group(2) or "").upper()
    factor = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}.get(unit, 1)
    return int(n * factor)


# ===========================================================================
# 详情：优先走国内中转的「解析」接口，官方 API 只当兜底
# ---------------------------------------------------------------------------
# 官方 api.steampowered.com 在国内实测经常超时（就是「点开详情一直转圈」的元凶），
# 而这个中转一次就把标题/体积/预览图/**file_type（2 = 合集）**都给全了，
# 实测 3 个 ID 0.86 秒。
# ===========================================================================
PARSE_API = "https://l4d2-workshop-parse.laoyutang.cn/"
# ★ 单个详情接口（参考 lytvpk 的实现，它走的就是这一条）。
#   国内实测对比（同一个 ID）：
#     · `-parse` 批量接口     2.15 秒，返回 2020 字节
#     · `/detail?id=`         0.87 秒，返回 4075 字节（还带 with_previews 多图）
#     · 备份线路 `/detail`    0.63~0.70 秒
#   快 2.5 倍、数据多 2 倍，所以**优先用它**，`-parse` 只在批量补历史时用。
WORKSHOP_DETAIL_API = "https://l4d2-workshop.laoyutang.cn/detail?id={}"
# 备份线路：主线路挂了/慢了顶上（lytvpk 也是主备双线）
WORKSHOP_DETAIL_BACKUP = "https://lytvpk-backup.laoyutang.cn/detail?id={}"
PARSE_BATCH = 100


def _int_or_zero(value: object) -> int:
    """中转那边 file_size 是字符串（也可能带小数点），别让 int() 抛出去。"""
    try:
        return int(float(str(value or 0).strip() or 0))
    except (TypeError, ValueError):
        return 0


def _plain_desc(text: object) -> str:
    """把工坊简介里的 BBCode 收拾成人能读的纯文本。

    工坊的 `file_description` 长这样（实测）：

        [h2]模型提供：[url=https://…]用户一串数字[/url][/h2]
        [b]最终归属：[/b]库洛/战双
        [list][*]第一个 [*]第二个[/list]

    直接铺到界面上就是一堆方括号，所以这里把常见标签换成对应符号/换行，
    剩下的 `[xxx]` 一律去掉。翻译接口拿到的也是这份纯文本（关键词更容易命中）。
    """
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"\[/?(?:h[1-6]|b|i|u|strike|spoiler|noparse|quote|code|center|right|left)\]",
               "", s, flags=re.I)
    s = re.sub(r"\[url=[^\]]*\]", "", s, flags=re.I)
    s = re.sub(r"\[/url\]", "", s, flags=re.I)
    s = re.sub(r"\[img[^\]]*\]", "", s, flags=re.I)
    s = re.sub(r"\[/img\]", "", s, flags=re.I)
    s = re.sub(r"\[\*\]", "· ", s)                  # 列表项
    s = re.sub(r"\[/?(?:list|olist|table|tr|td|th)\]", "", s, flags=re.I)
    s = re.sub(r"\[(?:previewyoutube|video|hr)[^\]]*\]", "", s, flags=re.I)
    s = re.sub(r"\[/?(?:previewyoutube|video|hr)\]", "", s, flags=re.I)
    s = re.sub(r"\[[^\]\n]{0,40}\]", "", s)         # 剩下没认出来的标签
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _desc_images(text: object) -> list[str]:
    """把简介里的所有图片地址抠出来 —— 这就是「额外的预览图」。

    Steam 的 `preview_url` 只给一张封面，但很多作者会在简介里再贴几张效果图。
    这些图正好可以拿来做详情里的多封面切换，不用额外请求任何接口。

    ⚠ 以前只认 `[img]…[/img]` 一种写法，于是「多张图只加载出封面」
    （用户报的）。实际上作者贴图的手法五花八门，这里全部覆盖：

        [img]https://x/1.jpg[/img]              BBCode（含 [img=800x600] 变体）
        <img src="https://x/2.jpg">             HTML（单/双引号都行）
        ![](https://x/3.jpg)                    Markdown
        https://x/4.jpg                         裸图片链接

    Steam 的简介字段里 BBCode 和 HTML 是混着出现的，只认一种必然漏。
    """
    s = str(text or "")
    out: list[str] = []

    def add(url: str) -> None:
        u = (url or "").strip().strip("\"'")
        if not u.lower().startswith(("http://", "https://")):
            return
        # 去掉 BBCode/HTML 里可能跟着的尾巴
        u = u.rstrip("\\/>")
        if u not in out:
            out.append(u)

    # 1) BBCode：[img]…[/img]、[img=800x600]…[/img]、[img width=800]…[/img]
    for m in re.finditer(r"\[img[^\]]*\]([^\[\]]+)\[/img\]", s, flags=re.I):
        add(m.group(1))

    # 2) HTML：<img src="…"> / <img src='…'> / 属性顺序乱一点也认
    for m in re.finditer(r"<img\b[^>]*?\bsrc\s*=\s*(\"[^\"]+\"|'[^']+')",
                         s, flags=re.I):
        add(m.group(1))

    # 3) Markdown：![alt](url)
    for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)", s):
        add(m.group(1))

    # 4) 裸图片链接（前面不是 = 或引号，避免和上面几条重复抓）
    for m in re.finditer(
            r"(?<![=\"'\w])(https?://[^\s\[\]<>\"']+?"
            r"\.(?:jpe?g|png|gif|webp|bmp))(?![^\s])",
            s, flags=re.I):
        add(m.group(1))

    return out[:12]


def _details_one(wid: str, timeout: int = 12) -> dict[str, dict]:
    """查**单个**工坊详情的快通道（参考 lytvpk：走 `/detail?id=`）。

    实测比批量 `-parse` 接口快 2.5 倍（0.87s vs 2.15s），而且带 `with_previews=1`
    时多返回作者贴的效果图。主线路挂了立刻退备份线路（lytvpk 也是主备双线）。

    返回结构和 `_details_parse` 完全一致，调用方不用区分。
    """
    key = str(wid or "").strip()
    if not key.isdigit():
        return {}
    for url in (WORKSHOP_DETAIL_API.format(key) + "&with_previews=1",
                WORKSHOP_DETAIL_BACKUP.format(key) + "&with_previews=1"):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            status, raw, _ = _http(req, timeout)
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        if int(status or 0) != 200:
            continue
        try:
            js = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        det = ((js or {}).get("response") or {}).get("publishedfiledetails") or []
        if not isinstance(det, list) or not det:
            continue
        row = det[0]
        if isinstance(row, dict):
            # 复用批量接口那套字段映射：把单条包装成同一形状再走一次
            out = _details_parse_rows([row])
            if out:
                return out
    return {}


def _details_parse_rows(arr: list) -> dict[str, dict]:
    """把「publishedfiledetails 数组」映射成我们的统一结构（_details_parse 的公共部分）。"""
    out: dict[str, dict] = {}
    for f in arr or []:
        if not isinstance(f, dict):
            continue
        wid = str(f.get("publishedfileid") or "")
        if not wid:
            continue
        kids = [str(c.get("publishedfileid") or "")
                for c in (f.get("children") or []) if isinstance(c, dict)]
        kids = [k for k in kids if k.isdigit()]
        ftype = int(f.get("file_type") or 0)
        out[wid] = {
            "id": wid,
            # 合集的 result 常常是 0（中转拿不到合集自身的文件信息），
            # 但这不影响判断：file_type 会给 2。
            "ok": int(f.get("result") or 0) == 1,
            "title": (f.get("title") or "").strip(),
            "preview": f.get("preview_url") or "",
            "size": _int_or_zero(f.get("file_size")),
            "author": str(f.get("creator") or ""),
            "appId": 0,
            "filename": f.get("filename") or "",
            # 简介（不同来源叫 file_description 或 description）
            "desc": _plain_desc(f.get("file_description") or f.get("description")),
            # ★ 中转直接给了 CDN 上的文件地址（file_url）。对**单文件 .vpk** 来说
            #   它就是下载直链，省掉「去下载站换直链」那一趟（那一步实测要 2~7 秒
            #   而且经常连不上）。多文件条目 Steam 只给第一个文件的地址，不能当
            #   整体下载用 —— 判据见 direct_file_url()。
            "fileUrl": (f.get("file_url") or "").strip(),
            "fileType": ftype,
            # 只有合集才有「成员数」；单个 MOD 也会带 children（那是它的前置/
            # 关联项），别把它当成员数，否则卡片上会冒出「合集 1」。
            "children": len(kids) if ftype == 2 else 0,
            "childrenIds": kids,
            # 简介里作者自己贴的效果图（BB Code 的 [img]）——详情里可以切换查看。
            # 快通道额外给的 `previews` 也一起并进来（那是作者上传的多张预览图）。
            "descImages": _desc_images(
                f.get("file_description") or f.get("description") or ""),
            "previews": [str(u) for u in (f.get("previews") or [])
                         if isinstance(u, str) and u.strip()][:12],
        }
    return out


def _details_parse(ids: list[str], timeout: int = 20) -> dict[str, dict]:
    """一次问一批 ID 的详情（返回结构和 _details_batch 一致）。"""
    if not ids:
        return {}
    body = json.dumps([str(i) for i in ids]).encode()
    req = urllib.request.Request(
        PARSE_API, data=body,
        headers={"User-Agent": UA, "Content-Type": "application/json"},
    )
    try:
        status, raw, _ = _http(req, timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log(f"parse details failed: {e!r}")
        return {}
    if int(status or 0) != 200:
        return {}
    try:
        arr = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return {}
    if not isinstance(arr, list):
        return {}
    return _details_parse_rows(arr)


# ===========================================================================
# Steam 官方 API（兜底）：标题 / 体积
# ===========================================================================
def fetch_details(wids: Iterable[str] | None = None, wid: str | None = None,
                  timeout: int = 20) -> dict[str, dict]:
    """查一批工坊 ID 的基本信息（标题/体积/作者/预览图 + file_type）。

    顺序：内存缓存 → 国内中转解析接口 → 官方 API。
    官方那个在国内经常超时，所以只当兜底；两边都失败才算失败。
    """
    # 单个 ID 直接传进来（fetch_details("3829533320")）也要认，
    # 否则字符串会被当成一串「字符 ID」一个个去查，结果一个都查不到。
    if isinstance(wids, str):
        wids = [wids]
    ids = [str(w) for w in (wids if wids is not None else ([wid] if wid else [])) if w]
    if not ids:
        return {}
    out: dict[str, dict] = {}
    missing: list[str] = []
    # 先吃缓存，只把没缓存的送上网
    for i in ids:
        hit = _cache_get(_DETAILS_CACHE, i, DETAIL_TTL)
        if hit is not None:
            out[i] = hit
        else:
            missing.append(i)
    # ---- 1. 先走国内中转（快）----
    # ★ 数量少时（详情页点开一张卡片就是 1 个）用**单条 /detail 接口**：
    #   实测 0.87 秒 vs 批量 -parse 的 2.15 秒，快 2.5 倍还多一倍数据。
    #   数量多时仍是 -parse 批量（一次 100 个），那才是它的强项。
    parsed: dict[str, dict] = {}
    single_ids = [i for i in missing if i.isdigit()]
    if 0 < len(single_ids) <= 6:
        with ThreadPoolExecutor(max_workers=max(1, len(single_ids))) as pool:
            for one in pool.map(lambda w: _details_one(w, timeout), single_ids):
                if one:
                    parsed.update(one)
        missing = [i for i in missing if i not in parsed]

    p_batches = [missing[i: i + PARSE_BATCH] for i in range(0, len(missing), PARSE_BATCH)]
    if p_batches:
        if len(p_batches) <= 1:
            for batch_ids in p_batches:
                parsed.update(_details_parse(batch_ids, timeout))
        else:
            with ThreadPoolExecutor(max_workers=max(1, min(4, len(p_batches)))) as pool:
                for batch in pool.map(lambda b: _details_parse(b, timeout), p_batches):
                    parsed.update(batch)
    for k, v in parsed.items():
        out[k] = v
        _cache_put(_DETAILS_CACHE, k, v)

    # ---- 2. 中转没给出来的，再问官方 API（一批 20 个，批次并行）----
    missing = [i for i in missing if i not in parsed]
    batches = [missing[i: i + 20] for i in range(0, len(missing), 20)]
    if len(batches) <= 1:
        for batch_ids in batches:
            for k, v in _details_batch(batch_ids, timeout).items():
                out[k] = v
                _cache_put(_DETAILS_CACHE, k, v)
    else:
        workers = max(1, min(6, len(batches)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for batch in pool.map(lambda b: _details_batch(b, timeout), batches):
                for k, v in batch.items():
                    out[k] = v
                    _cache_put(_DETAILS_CACHE, k, v)
    return out


def _details_batch(ids: list[str], timeout: int, stats_only: bool = False) -> dict[str, dict]:
    payload = {"itemcount": len(ids)}
    for i, w in enumerate(ids):
        payload[f"publishedfileids[{i}]"] = w
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        STEAM_API, data=data,
        headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        _, body, _ = _http(req, timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log(f"fetch_details failed: {e!r}")
        return {}
    try:
        j = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return {}
    out: dict[str, dict] = {}
    for f in (j.get("response") or {}).get("publishedfiledetails") or []:
        wid = str(f.get("publishedfileid") or "")
        if not wid:
            continue
        ok = f.get("result") == 1
        out[wid] = {
            "id": wid,
            "ok": bool(ok),
            "title": (f.get("title") or "").strip() if ok else "",
            "preview": (f.get("preview_url") or "") if ok else "",
            "size": int(f.get("file_size") or 0),
            "author": str(f.get("creator") or ""),
            "appId": int(f.get("consumer_app_id") or 0),
            "filename": (f.get("filename") or "") if ok else "",
            # 官方这边简介字段叫 description（同样是 BBCode）
            "desc": _plain_desc(f.get("description")) if ok else "",
            # ★ 这两项让「是不是合集」不用再单独问一次合集接口：
            #   官方详情里 num_children 只有合集才有值。
            "fileType": int(f.get("file_type") or 0),
            #   num_children 单独看不可靠：普通 MOD 也可能带上它（实测单件列表
            #   20 条里有 4 条），所以不是合集就一律记 0，避免被当成合集成员数。
            "children": (int(f.get("num_children") or 0)
                         if int(f.get("file_type") or 0) == 2 else 0),
            # 官方接口能一次给全：浏览 / 订阅 / 收藏 / 发布时间 / 更新时间
            "views": int(f.get("views") or 0),
            "subs": int(f.get("subscriptions") or 0),
            "favs": int(f.get("favorited") or 0),
            "created": int(f.get("time_created") or 0),
            "updated": int(f.get("time_updated") or 0),
            "descImages": _desc_images(f.get("description")) if ok else [],
        }
        if stats_only:
            # 补统计时不需要标题/简介这些大字段，省点内存也省得覆盖掉
            # 中转那份更全的简介（官方 description 常常是空的）。
            for k in ("title", "preview", "desc", "filename", "descImages"):
                out[wid].pop(k, None)
    return out


# ===========================================================================
# 统计数字（浏览 / 订阅 / 收藏 / 发布时间 / 更新时间）
#
# 这些字段只有 Steam 官方接口有（国内中转那份数据里没有），所以单独一条路：
# 详情面板打开后再异步补一次，拿不到就不显示，绝不让它拖慢点开详情的速度。
# ===========================================================================
STATS_TTL = 600.0
_STATS_CACHE: dict[str, tuple[float, dict]] = {}


def fetch_stats(wids: Iterable[str] | None = None, wid: str | None = None,
                timeout: int = 15) -> dict[str, dict]:
    """查一批 ID 的统计数字：views / subs / favs / created / updated。"""
    # 和 fetch_details 一样：单个 ID 字符串也要当成「一个 ID」而不是「一串字符」
    if isinstance(wids, str):
        wids = [wids]
    ids = [str(w) for w in (wids if wids is not None else ([wid] if wid else [])) if w]
    out: dict[str, dict] = {}
    missing: list[str] = []
    for i in ids:
        hit = _cache_get(_STATS_CACHE, i, STATS_TTL)
        if hit is not None:
            out[i] = hit
        else:
            missing.append(i)
    for i in range(0, len(missing), 20):
        batch = missing[i: i + 20]
        got = _details_batch(batch, timeout, stats_only=True)
        for k, v in got.items():
            if v.get("ok"):
                _cache_put(_STATS_CACHE, k, v)
            out[k] = v
    return out


# ===========================================================================
# 合集（collection）：只有官方 API 能拿 children
# ===========================================================================
COLLECTION_API = "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/"


def fetch_collection(wid: str, timeout: int = 20) -> dict:
    """查一个 ID 是不是合集，是的话返回子项 ID 列表。

    返回 {"isCollection": bool, "children": [id, ...], "ok": bool, "error": str}

    注意区分「查到了但不是合集」和「没查成」：
      - 不是合集 → isCollection=False, ok=True
      - 网络失败 → ok=False
    两者 UI 处理完全不同（前者正常当单个 MOD，后者要报错）。

    带 10 分钟内存缓存：这个接口在「点开卡片 → 再点下载」时会被问第二次，
    而 875 个成员的合集列表本身好几百 KB，缓存能省下实打实的一次往返。
    """
    wid = str(wid or "").strip()
    if not wid.isdigit():
        return {"isCollection": False, "children": [], "ok": False, "error": "ID 不合法"}
    hit = _cache_get(_COLLECTION_CACHE, wid, COLLECTION_TTL)
    if hit is not None:
        return hit
    res = _fetch_collection_net(wid, timeout)
    # 失败不缓存：多半是一时连不上，缓存住会一直失败
    if res.get("ok"):
        _cache_put(_COLLECTION_CACHE, wid, res)
    return res


def _fetch_collection_net(wid: str, timeout: int = 20) -> dict:
    # 先问国内中转：它一次请求就把 file_type 和 children 都给出来（官方要另外
    # 打 api.steampowered.com，国内经常超时）
    p = _details_parse([wid], timeout).get(wid) or {}
    # ★ children 只有配合 file_type==2 才是「合集成员」：实测单个 MOD
    #   （file_type=0，3829533320）也会返回 children=[一个 ID]，那是它的前置/
    #   关联项，不是合集成员 —— 只按 children 判会把普通 MOD 说成合集。
    if p and int(p.get("fileType") or 0) != 2:
        return {"isCollection": False, "children": [], "ok": True, "error": ""}
    kids = [k for k in (p.get("childrenIds") or []) if k.isdigit()]
    if kids:
        return {"isCollection": True, "children": kids, "ok": True, "error": ""}

    payload = {"collectioncount": 1, "publishedfileids[0]": wid}
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        COLLECTION_API, data=data,
        headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        _, body, _ = _http(req, timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"isCollection": False, "children": [], "ok": False,
                "error": f"查合集失败：{e}"}
    try:
        j = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return {"isCollection": False, "children": [], "ok": False,
                "error": "合集接口返回的不是 JSON"}
    details = (j.get("response") or {}).get("collectiondetails") or []
    for d in details:
        if str(d.get("publishedfileid") or "") != wid:
            continue
        # result == 9 表示「不是合集」，1 表示是合集
        if d.get("result") != 1:
            return {"isCollection": False, "children": [], "ok": True, "error": ""}
        children = [
            str(c.get("publishedfileid") or "")
            for c in (d.get("children") or [])
            if str(c.get("publishedfileid") or "").isdigit()
        ]
        return {"isCollection": True, "children": children, "ok": True, "error": ""}
    # 没返回这条记录：当作「不是合集」，但不算失败
    return {"isCollection": False, "children": [], "ok": True, "error": ""}


# ===========================================================================
# 依赖（必需物品）：只能从工坊页面 HTML 拿
# ===========================================================================
_REQ_BLOCK_RE = re.compile(
    r"requiredItems.*?<h3[^>]*>.*?</h3>(.*?)</div>\s*</div>", re.S | re.I)


def parse_required_items(html_text: str) -> list[dict]:
    """从工坊页面 HTML 里解析「必需物品」列表。

    结构大致是：
        <div class="requiredItemsContainer">
          <div ...><h3>Required items</h3>
            <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=123">
              <img ...> <div class="requiredItem">名称</div>
            </a>
          ...
    """
    text = html_text or ""
    pos = text.find("requiredItems")
    if pos < 0:
        pos = text.find("Required Items")
    if pos < 0:
        return []

    # 从这个位置往后截一段，避免扫到页面别处的链接
    chunk = text[pos: pos + 30000]
    # 提前截断：遇到「描述」区块就停，免得把作者的其他作品也扫进来
    for stop in ("<div class=\"workshopItemDescription", "id=\"description\"",
                 "class=\"workshopTags\"", "id=\"footer\""):
        i = chunk.find(stop)
        if i > 0:
            chunk = chunk[:i]
            break

    out: list[dict] = []
    seen: set[str] = set()
    # 每个必需物品是一个 <a ...filedetails/?id=xxx...> ... </a>
    for m in re.finditer(
            r"<a[^>]*filedetails/\?id=(\d{5,20})[^>]*>(.*?)</a>", chunk, re.S | re.I):
        wid = m.group(1)
        if wid in seen:
            continue
        seen.add(wid)
        inner = m.group(2)
        # 名称：优先 requiredItem 那个 div
        name = ""
        nm = re.search(r'class="requiredItem"[^>]*>(.*?)</div>', inner, re.S | re.I)
        if nm:
            name = _strip_tags(nm.group(1))
        if not name:
            name = _strip_tags(inner)
        out.append({"id": wid, "title": name[:120]})
    return out


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = _html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_required_items(wid: str, timeout: int = DEP_TIMEOUT) -> dict:
    """查一个 MOD 的必需物品。

    返回 {"ok": bool, "items": [{id,title}], "reason": 失败原因}
    `ok=False` 表示**没能查**（网络被重置/超时），而不是「没有依赖」。
    """
    wid = str(wid or "").strip()
    if not wid.isdigit():
        return {"ok": False, "items": [], "reason": "ID 不合法"}
    req = urllib.request.Request(
        WORKSHOP_PAGE.format(wid),
        headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
    )
    try:
        _, body, _ = _http(req, timeout)
    except urllib.error.HTTPError as e:
        return {"ok": False, "items": [], "reason": f"工坊页面 HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001  SSL 重置 / 超时 / DNS 都可能
        return {"ok": False, "items": [], "reason": f"连不上工坊页面（{type(e).__name__}）"}
    text = body.decode("utf-8", "replace")
    return {"ok": True, "items": parse_required_items(text), "reason": ""}


# ===========================================================================
# 下载文件
# ===========================================================================
def _direct_url_ok(url: str, filename: str) -> bool:
    """中转给的 `file_url` 能不能直接当下载直链用。

    只认「Steam CDN 上的单个 .vpk」：

    * 域名必须是 `cdn.steamusercontent.com`（`images.steamusercontent.com` 是
      封面图，合集条目经常返回那个，直接下就下成一张图了）；
    * 文件名里不能带目录（`myl4d2addons/molotov_variants.vpk` 这种说明这个条目
      是**多文件**的，Steam 只给了第一个文件的地址，直接下会少文件，还是交给
      下载站打包）；
    * 必须真的是 `.vpk`。
    """
    url = str(url or "").strip()
    name = str(filename or "").strip()
    if not url.startswith("https://cdn.steamusercontent.com/"):
        return False
    if "/" in name or "\\" in name:
        return False
    return name.lower().endswith(".vpk")


def direct_file_url(api: dict) -> str:
    """从详情里取可以直接下载的地址（取不到就返回空串）。"""
    api = api or {}
    url = str(api.get("fileUrl") or "").strip()
    return url if _direct_url_ok(url, api.get("filename") or "") else ""


def download_file(url: str, dest_dir: str, filename: str = "",
                  progress: Callable[[int, int], None] | None = None,
                  timeout: int = DL_TIMEOUT) -> dict:
    """把 CDN 直链下载到 dest_dir，返回 {"ok","path","bytes","error"}。

    progress(已下载字节, 总字节) 总字节未知时传 0。
    """
    url = str(url or "").strip()
    if not url:
        return {"ok": False, "path": "", "bytes": 0, "error": "没有下载地址"}
    os.makedirs(dest_dir, exist_ok=True)

    name = _safe_filename(filename)
    if not name:
        name = _filename_from_url(url)
    if not name:
        return {"ok": False, "path": "", "bytes": 0, "error": "认不出文件名"}

    dst = os.path.join(dest_dir, name)
    # 重名就加 (1)(2)，别覆盖用户已有的 MOD。
    # ★ 必须用 O_CREAT|O_EXCL 原子地「抢占」文件名：多线程同时下两个同名文件时，
    #   先 exists() 再 open() 的写法会双双通过检查、后写的把先写的覆盖掉。
    stem, ext = os.path.splitext(name)
    n = 1
    while True:
        try:
            fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            dst = os.path.join(dest_dir, f"{stem} ({n}){ext}")
            n += 1
            if n > 999:
                return {"ok": False, "path": "", "bytes": 0,
                        "error": "同名文件太多，放弃"} 
        except OSError as e:
            return {"ok": False, "path": "", "bytes": 0, "error": f"创建文件失败：{e}"}

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tmp = dst + ".part"
    got = 0
    try:
        with WDNS.urlopen(req, timeout=timeout) as r:
            # file:// 这类响应的 status 是 None，别拿它当失败
            status = getattr(r, "status", None)
            if status is not None and int(status) != 200:
                raise OSError(f"下载链接返回 HTTP {status}")
            total = int(r.headers.get("Content-Length") or 0)
            with open(tmp, "wb") as f:
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if progress:
                        progress(got, total)
        os.replace(tmp, dst)
    except Exception as e:  # noqa: BLE001
        # 失败时连「占位用的空文件」一起清掉：留着的话 addons 里会多出一个
        # 0 字节的 .vpk，游戏看着就当坏 MOD 了。
        for p in (tmp, dst):
            try:
                if p == dst and os.path.getsize(dst) > 0:
                    continue          # 已经有内容了（不该发生），别删
                os.remove(p)
            except OSError:
                pass
        return {"ok": False, "path": "", "bytes": got, "error": f"下载失败：{e}"}

    return {"ok": True, "path": dst, "bytes": got, "error": ""}


def download_file_via_ip(url: str, dest_dir: str, filename: str = "",
                         ip: str = "",
                         progress: Callable[[int, int], None] | None = None,
                         timeout: int = DL_TIMEOUT) -> dict:
    """和 download_file 一样，但可以先绕开 DNS 直连指定 CDN 节点。

    `ip` 为空、或者 URL 不在 Steam CDN 域名下时，退回普通 download_file。
    绕路时 TLS 的 SNI / Host 仍然用域名（否则证书对不上），
    所以这里不能用 urlopen，得用 http.client 手工建连接。
    """
    from . import workshop_net as WN

    raw = str(url or "").strip()
    if not raw or not ip or not WN.is_steam_cdn_url(raw):
        return download_file(raw, dest_dir, filename,
                             progress=progress, timeout=timeout)
    os.makedirs(dest_dir, exist_ok=True)
    name = _safe_filename(filename)
    if not name:
        name = _filename_from_url(raw)
    if not name:
        return {"ok": False, "path": "", "bytes": 0, "error": "认不出文件名"}

    dst = os.path.join(dest_dir, name)
    stem, ext = os.path.splitext(name)
    n = 1
    while True:
        try:
            fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            dst = os.path.join(dest_dir, f"{stem} ({n}){ext}")
            n += 1
            if n > 999:
                return {"ok": False, "path": "", "bytes": 0,
                        "error": "同名文件太多，放弃"}
        except OSError as e:
            return {"ok": False, "path": "", "bytes": 0, "error": f"创建文件失败：{e}"}

    tmp = dst + ".part"
    got = 0
    try:
        got = WN.download_via_ip(raw, tmp, ip, timeout=timeout, progress=progress)
        os.replace(tmp, dst)
    except Exception as e:  # noqa: BLE001
        # 同样把占位的空文件清掉，别在 addons 里留 0 字节的 .vpk
        for p in (tmp, dst):
            try:
                if p == dst and os.path.getsize(dst) > 0:
                    continue
                os.remove(p)
            except OSError:
                pass
        return {"ok": False, "path": "", "bytes": got, "error": f"下载失败：{e}"}

    return {"ok": True, "path": dst, "bytes": got, "error": ""}


def _safe_filename(name: str) -> str:
    """清掉 Windows 文件名里不能用的字符。"""
    raw = os.path.basename(str(name or "").strip())
    if not raw:
        return ""
    raw = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).strip(" .")
    return raw[:180]


def _filename_from_url(url: str) -> str:
    """CDN 直链通常没有扩展名（结尾是哈希），所以退回用 ID.vpk。"""
    path = urllib.parse.urlparse(url).path
    base = os.path.basename(path)
    if base and "." in base:
        return _safe_filename(base)
    return ""


# ===========================================================================
# 一站式：解析 → 查依赖 → 并发下载
# ===========================================================================
class WorkshopDownloader:
    """给 UI 用的一站式下载器。

    典型用法：
        d = WorkshopDownloader(threads=3)
        info = d.probe("3829533320")
        d.download(info["items"], dest, on_progress, on_done)
    """

    def __init__(self, threads: int = DEFAULT_THREADS, cdn_ip: str = ""):
        self.threads = clamp_threads(threads)
        self._lock = threading.Lock()
        self._cancel = False
        # 补合集成员的后台线程看到这个就收工（用户又点开了别的条目）
        self._stream_stop = False
        # 工坊网络加速选中的节点（空串 = 不加速，走系统 DNS）
        self.cdn_ip = str(cdn_ip or "").strip()

    # ------------------------------------------------------------ 预检
    def probe(self, text: str, want_deps: bool = True,
              progress: Callable[[str, int, int], None] | None = None,
              on_members: Callable[[dict], None] | None = None) -> dict:
        """解析输入 + 查下载直链 + 查依赖（也支持合集）。

        `progress(阶段文字, 已完成, 总数)` 用来给 UI 显示进度 —— 合集可能有十几个子项，
        每个都要单独查一次下载直链，不给进度的话界面就是干等。

        `on_members(批次)` 只对合集有意义：快通道先给前 COLLECT_FAST_LIMIT 个，
        剩下的成员在后台按 100 个一批继续补，拿一批就回调一次
        （{"id","items","listedCount","memberCount","done"}），
        这样点开一个 875 个成员的合集也能看到**全部**成员信息，而不是只看到「有多少个」。

        返回：
            {"ok", "id", "isCollection", "title", "size", "sizeText", "preview",
             "filename", "items": [...], "depCount", "depsChecked", "depsReason",
             "error"}
        `items` 里 isMain=True 的是本体（合集则是每个子项都算 main=False 的成员）。
        """
        wid = parse_workshop_id(text)
        if not wid:
            return {"ok": False, "error": "认不出工坊 ID，粘贴链接或数字都行", "items": []}

        def tick(stage: str, done: int, total: int) -> None:
            if progress:
                progress(stage, done, total)

        # ---- 1. 先看官方详情能不能直接告诉我们「是不是合集」----
        # 判据只有 **file_type == 2**：num_children 不能用来判 —— Steam 会给
        # 一些普通 MOD 也塞上 num_children（实测单件列表里 20 条里有 4 条
        # 带着 num_children>0，卡片上照样显示成「合集」就是这个原因）。
        # 合集自己的详情 API 经常压根不给 num_children，所以只认 file_type。
        tick("正在识别…", 0, 0)
        api = fetch_details(wid=wid).get(wid) or {}
        looks_coll = int(api.get("fileType") or 0) == 2
        if looks_coll or not api.get("ok"):
            coll = fetch_collection(wid)
            if coll.get("isCollection") and coll.get("children"):
                res = self._probe_collection(wid, coll["children"], want_deps, tick,
                                             lite=not want_deps,
                                             title=api.get("title") or "",
                                             on_members=on_members)
                # 合集自己的简介也一起带回去（详情里同样能翻译）
                res["desc"] = api.get("desc") or ""
                return res

        # ---- 2. 单个 MOD ----
        # 只是「点开看看」（want_deps=False）时**不查下载直链**：查下载站一次要
        # 一秒多，而这一步完全可以在用户真的点下载时再做（download() 支持现解析）。
        # 这样详情页半秒就出来了 —— 这就是「点开 MOD 一直加载」的另一半原因。
        fast = not want_deps
        direct = direct_file_url(api)          # 中转白送的直链，不用白不用
        if direct:
            tick("正在整理信息…", 1, 2)
            main = {"ok": True, "url": direct, "error": "", "fromApi": True}
        elif fast and api.get("ok"):
            tick("正在整理信息…", 1, 2)
            main = {"ok": True, "url": "", "error": ""}
        else:
            tick("正在解析 MOD…", 0, 2)
            main = resolve_download(wid)
            tick("正在核对信息…", 1, 2)
        if not api.get("ok") and not main.get("ok"):
            return {
                "ok": False, "id": wid, "items": [], "isCollection": False,
                "error": main.get("error") or "查不到这个工坊 ID",
            }

        title = api.get("title") or main.get("title") or wid
        size = int(api.get("size") or 0) or main.get("size") or 0
        # 预览图：官方封面 + 作者贴在简介里的效果图（详情里可以切换看）
        pics: list[str] = []
        for u in [api.get("preview") or main.get("preview") or ""] + list(api.get("descImages") or []):
            if u and u not in pics:
                pics.append(u)
        item = {
            "id": wid,
            "title": title,
            "size": size,
            "sizeText": main.get("sizeText") or _fmt_size(size),
            "preview": api.get("preview") or main.get("preview") or "",
            "images": pics,
            "url": main.get("url") or "",
            "filename": api.get("filename") or main.get("filenameOnSite") or "",
            "desc": api.get("desc") or "",
            "isMain": True,
            "isDep": False,
            "isMember": False,
            "available": bool(main.get("url")) or (fast and bool(main.get("ok"))),
            "note": "" if main.get("url") else (main.get("error") or "直链在下载时解析"),
            # 标记这条直链是「中转白送的」：万一 CDN 上已经没有这个文件，
            # download() 会退回下载站再解析一次（见那里的 fallback）。
            "urlFromApi": bool(main.get("fromApi")),
        }

        items = [item]

        # ---- 3. 依赖（**不是必选**：UI 上默认不勾，但可以勾）----
        deps_checked = False
        deps_reason = ""
        if want_deps:
            tick("正在检查前置物品…", 2, 3)
            dep_res = fetch_required_items(wid)
            deps_checked = bool(dep_res.get("ok"))
            deps_reason = dep_res.get("reason") or ""
            dep_items = list(dep_res.get("items") or []) if deps_checked else []
            for i, d in enumerate(dep_items):
                tick(f"正在查前置 {i + 1}/{len(dep_items)}…", 3 + i, 3 + len(dep_items))
                dl = resolve_download(d["id"])
                api_d = (fetch_details(wid=d["id"]).get(d["id"]) or {})
                items.append({
                    "id": d["id"],
                    "title": dl.get("title") or api_d.get("title") or d.get("title") or d["id"],
                    "size": dl.get("size") or int(api_d.get("size") or 0),
                    "sizeText": dl.get("sizeText") or _fmt_size(api_d.get("size") or 0),
                    "preview": dl.get("preview") or api_d.get("preview") or "",
                    "url": dl.get("url") or "",
                    "filename": dl.get("filenameOnSite") or "",
                    "isMain": False,
                    "isDep": True,
                    "isMember": False,
                    "available": bool(dl.get("url")),
                    "note": "" if dl.get("url") else "下载站没给直链",
                })

        return {
            "ok": True,
            "id": wid,
            "isCollection": False,
            "title": title,
            "size": size,
            "sizeText": item["sizeText"],
            "preview": item["preview"],
            "filename": item["filename"],
            "items": items,
            "depCount": len(items) - 1,
            "depsChecked": deps_checked,
            "depsReason": deps_reason,
            "error": "",
        }

    def _member_item(self, cid: str, api: dict) -> dict:
        """把一个合集成员整理成详情面板能直接显示的条目。"""
        a = api.get(cid) or {}
        size = int(a.get("size") or 0)
        direct = direct_file_url(a)
        pics: list[str] = []
        for u in [a.get("preview") or ""] + list(a.get("descImages") or []):
            if u and u not in pics:
                pics.append(u)
        return {
            "id": cid,
            "title": a.get("title") or cid,
            "size": size,
            "sizeText": _fmt_size(size) if size else "",
            "preview": a.get("preview") or "",
            "images": pics,
            # 详情接口白送的直链（单文件才有；拿不到就留空，下载时再解析）
            "url": direct,
            "filename": a.get("filename") or "",
            "isMain": False,
            "isDep": False,
            "isMember": True,
            "available": bool(direct),
            "note": "" if direct else "直链在下载时解析",
            "urlFromApi": bool(direct),
        }

    def _stream_members(self, wid: str, children: list[str], done: int,
                        on_members: Callable[[dict], None]) -> None:
        """把合集**剩下的**成员一批一批补出来（后台线程，边拉边报）。

        为什么不在 _probe_collection 里一次拉完：875 个成员虽然只是问官方详情
        （100 个一批），也要好几秒；先给前 COLLECT_FAST_LIMIT 个让界面立刻有东西看，
        剩下的边拉边塞进详情面板，用户能看到「已列出 320 / 875」在往前走。
        """
        step = PARSE_BATCH
        total = len(children)
        while done < total:
            if getattr(self, "_stream_stop", False):
                return
            batch = children[done:done + step]
            try:
                api_map = fetch_details(batch)
            except Exception:  # noqa: BLE001
                api_map = {}
            items = [self._member_item(cid, api_map) for cid in batch]
            done += len(batch)
            try:
                on_members({
                    "id": wid,
                    "items": items,
                    "listedCount": done,
                    "memberCount": total,
                    "done": done >= total,
                })
            except Exception:  # noqa: BLE001
                return
        return

    def stop_streaming(self) -> None:
        """用户又点开了别的条目：让正在补成员的后台线程停下来。"""
        self._stream_stop = True

    def _probe_collection(self, wid: str, children: list[str], want_deps: bool,
                          tick: Callable[[str, int, int], None],
                          lite: bool = False, title: str = "",
                          on_members: Callable[[dict], None] | None = None) -> dict:
        """合集。

        lite=True 是**浏览详情时的快通道**：只按 20 个一批向官方接口要标题/封面，
        绝不碰下载站（每个成员一次 POST ≈ 1.4 秒），而且只列前 COLLECT_FAST_LIMIT 个。
        直链留到用户真的点下载时由 download() 现解析。

        为什么要这样：实测一个 875 个成员的合集，want_deps=False 也会跑满 25 秒
        只解析出 18/875，界面显示「一直在读取详情」。不查直链后这个数变成 1~2 秒。

        快通道只列前 60 个**不代表后面看不到**：给了 on_members 回调时，
        剩下的成员由 _stream_members 在后台按 100 个一批继续补，
        一批一报，详情面板里能看到完整的成员信息（标题/封面/体积）。

        lite=False（用户勾了「连前置一起下」，需要知道真实可下载列表）走原来的重通道：
        并发逐个查直链，顺带解析前置。
        """
        total = len(children)
        coll_title = title or (fetch_details(wid=wid).get(wid) or {}).get("title") or f"合集 {wid}"

        if lite:
            listed = children[:COLLECT_FAST_LIMIT]
            tick(f"正在读取合集成员 0/{len(listed)}…", 0, len(listed))
            api_map = fetch_details(listed)
            items: list[dict] = [self._member_item(cid, api_map) for cid in listed]
            tick("解析完成", len(listed), len(listed))
            # 剩下的成员：后台慢慢补，界面先能看
            if on_members is not None and total > len(listed):
                threading.Thread(
                    target=self._stream_members,
                    args=(wid, children, len(listed), on_members),
                    daemon=True,
                ).start()
            listed_size = sum(int(it.get("size") or 0) for it in items)
            return {
                "ok": True,
                "id": wid,
                "isCollection": True,
                "title": coll_title,
                # 只列了一部分时不要报「总体积」，会让人以为是全部
                "size": listed_size if len(listed) == total else 0,
                "sizeText": (_fmt_size(listed_size) + "（已列出部分）")
                            if len(listed) == total and listed_size else "",
                "preview": next((it["preview"] for it in items if it.get("preview")), ""),
                "filename": "",
                "items": items,
                "memberCount": total,
                "readyCount": 0,
                "lite": True,
                "truncated": total > len(listed),
                "listedCount": len(items),
                "streaming": total > len(listed) and on_members is not None,
                "depCount": 0,
                "depsChecked": False,
                "depsReason": "",
                "error": "",
            }

        results: dict[str, dict] = {}
        results_lock = threading.Lock()
        queue = list(children)
        queue_lock = threading.Lock()
        done_count = [0]
        count_lock = threading.Lock()

        def worker() -> None:
            while True:
                with queue_lock:
                    if not queue:
                        return
                    cid = queue.pop(0)
                item = self._probe_one_member(cid)
                with results_lock:
                    results[cid] = item
                with count_lock:
                    done_count[0] += 1
                    n = done_count[0]
                tick(f"正在解析合集 {n}/{total}…", n, total)

        threads = []
        for _ in range(min(max(1, self.threads), total)):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        # 按合集的原始顺序排，别让并发顺序把列表打乱
        items: list[dict] = [results[cid] for cid in children if cid in results]
        ok_count = sum(1 for it in items if it.get("url") or it.get("title"))

        # 前置：只在拿到直链的子项上查，同样并发
        if want_deps:
            seen_deps = set(children)
            dep_ids: list[tuple[str, str]] = []   # (dep_id, 名称提示)
            dep_queue = [it["id"] for it in items if it.get("url")]
            dep_lock = threading.Lock()
            dep_scan_done = [0]

            def dep_scan() -> None:
                while True:
                    with dep_lock:
                        if not dep_queue:
                            return
                        cid = dep_queue.pop(0)
                    dep = fetch_required_items(cid, timeout=DEP_TIMEOUT)
                    for d in (dep.get("items") or []) if dep.get("ok") else []:
                        with dep_lock:
                            if d["id"] in seen_deps:
                                continue
                            seen_deps.add(d["id"])
                            dep_ids.append((d["id"], d.get("title") or ""))
                    with dep_lock:
                        dep_scan_done[0] += 1

            ds = [threading.Thread(target=dep_scan, daemon=True)
                  for _ in range(min(max(1, self.threads), max(1, len(dep_queue))))]
            for t in ds:
                t.start()
            for t in ds:
                t.join()

            if dep_ids:
                tick("正在解析前置…", 0, len(dep_ids))
                dep_results: dict[str, dict] = {}

                def dep_one(did: str, hint: str) -> None:
                    ddl = resolve_download(did)
                    api = (fetch_details(wid=did).get(did) or {})
                    dep_results[did] = {
                        "id": did,
                        "title": ddl.get("title") or api.get("title") or hint or did,
                        "size": ddl.get("size") or int(api.get("size") or 0),
                        "sizeText": ddl.get("sizeText") or _fmt_size(api.get("size") or 0),
                        "preview": ddl.get("preview") or api.get("preview") or "",
                        "url": ddl.get("url") or "",
                        "filename": ddl.get("filenameOnSite") or "",
                        "isMain": False,
                        "isDep": True,
                        "isMember": False,
                        "available": bool(ddl.get("url")),
                        "note": "" if ddl.get("url") else "下载站没给直链",
                    }

                dq = list(dep_ids)
                dlk = threading.Lock()
                dcnt = [0]

                def dep_worker() -> None:
                    while True:
                        with dlk:
                            if not dq:
                                return
                            did, hint = dq.pop(0)
                        dep_one(did, hint)
                        with dlk:
                            dcnt[0] += 1
                            n = dcnt[0]
                        tick(f"正在解析前置 {n}/{len(dep_ids)}…", n, len(dep_ids))

                dts = [threading.Thread(target=dep_worker, daemon=True)
                       for _ in range(min(max(1, self.threads), len(dep_ids)))]
                for t in dts:
                    t.start()
                for t in dts:
                    t.join()
                items.extend(dep_results[did] for did, _ in dep_ids if did in dep_results)

        tick("解析完成", total, total)
        total_size = sum(int(it.get("size") or 0) for it in items
                         if it.get("isMember"))
        return {
            "ok": True,
            "id": wid,
            "isCollection": True,
            "title": coll_title,
            "size": total_size,
            "sizeText": _fmt_size(total_size),
            "preview": next((it["preview"] for it in items if it.get("preview")), ""),
            "filename": "",
            "items": items,
            "memberCount": total,
            "readyCount": ok_count,
            "lite": False,
            "truncated": False,
            "listedCount": len(items),
            "depCount": sum(1 for it in items if it.get("isDep")),
            "depsChecked": True,      # 合集靠 API，不依赖工坊页面
            "depsReason": "",
            "error": "",
        }

    def _probe_one_member(self, cid: str) -> dict:
        """查合集里一个子项的直链与信息。"""
        api = (fetch_details(wid=cid).get(cid) or {})
        direct = direct_file_url(api)          # 有白送的直链就别去下载站了
        dl = {} if direct else resolve_download(cid)
        url = direct or dl.get("url") or ""
        return {
            "id": cid,
            "title": dl.get("title") or api.get("title") or cid,
            "size": dl.get("size") or int(api.get("size") or 0),
            "sizeText": dl.get("sizeText") or _fmt_size(api.get("size") or 0),
            "preview": dl.get("preview") or api.get("preview") or "",
            "url": url,
            "filename": dl.get("filenameOnSite") or api.get("filename") or "",
            "isMain": False,
            "isDep": False,
            "isMember": True,
            "available": bool(url),
            "note": "" if url else (dl.get("error") or "下载站没给直链"),
            "urlFromApi": bool(direct),
        }

    # ------------------------------------------------------------ 下载
    def cancel(self) -> None:
        with self._lock:
            self._cancel = True

    def download(
        self,
        items: list[dict],
        dest_dir: str,
        on_item: Callable[[dict], None] | None = None,
        on_bytes: Callable[[str, int, int], None] | None = None,
        on_done: Callable[[dict], None] | None = None,
    ) -> dict:
        """并发下载一批条目（`probe()` 返回的 items，可只传勾选的）。

        线程数取 self.threads。每个条目独立成败，不会因为一个失败就全停。

        条目**可以没有 url**（合集快通道给的成员就是这种）：轮到它时先现查一次
        下载直链再下，查不到就把这一条记成失败、继续下一条。
        """
        todo = [it for it in (items or []) if it.get("url") or str(it.get("id") or "").strip()]
        if not todo:
            return {"ok": False, "done": [], "failed": [], "skipped": [],
                    "error": "没有可下载的条目"}

        with self._lock:
            self._cancel = False

        results: list[dict] = []
        results_lock = threading.Lock()
        queue = list(todo)
        queue_lock = threading.Lock()

        def worker() -> None:
            while True:
                with queue_lock:
                    if self._cancel or not queue:
                        return
                    it = queue.pop(0)
                
                # 没有直链的（浏览时为了快没查）现在补一次
                if not it.get("url"):
                    if on_item:
                        on_item({**it, "resolving": True})
                    dl = resolve_download(str(it.get("id") or ""))
                    if not dl.get("url"):
                        bad = {**it, "ok": False, "size": 0,
                               "error": dl.get("error") or "下载站没给直链"}
                        with results_lock:
                            results.append(bad)
                        if on_done:
                            on_done(bad)
                        continue
                    it = {**it, "url": dl["url"],
                          "filename": it.get("filename") or dl.get("filenameOnSite") or ""}
                if on_item:
                    on_item(it)
                wid = str(it.get("id") or "").strip()
                if wid.isdigit():
                    # 文件名一律用创意工坊 ID（<id>.vpk）。
                    # MOD 管理器就是靠「纯数字文件名」认这是工坊 MOD 的
                    #（mods.workshop_id_of），认出来才会自动挂上工坊标题、封面和更新检查；
                    # 用下载站给的名字存下来，那一栏永远是一串自己看不懂的英文名。
                    name = f"{wid}.vpk"
                else:
                    name = it.get("filename") or ""
                if not name:
                    # 没有 ID（理论上不会）：用「标题（清理过）.vpk」兜底
                    name = _safe_filename(it.get("title") or "") or wid
                    if not os.path.splitext(name)[1]:
                        name += ".vpk"
                res = download_file_via_ip(
                    it["url"], dest_dir, name, self.cdn_ip,
                    progress=(lambda got, total, _wid=it["id"]:
                              on_bytes(_wid, got, total) if on_bytes else None),
                )
                # 中转白送的直链是「当时那个文件」的地址，CDN 上换了版本就会 404；
                # 这时退回下载站再解析一次，别让用户只看到一句失败。
                if (not res.get("ok") and it.get("urlFromApi")
                        and str(it.get("id") or "").isdigit()):
                    if on_item:
                        on_item({**it, "resolving": True})
                    dl = resolve_download(str(it.get("id")))
                    if dl.get("url"):
                        res = download_file_via_ip(
                            dl["url"], dest_dir, name, self.cdn_ip,
                            progress=(lambda got, total, _wid=it["id"]:
                                      on_bytes(_wid, got, total) if on_bytes else None),
                        )
                with results_lock:
                    results.append({**it, **res})
                if on_done:
                    on_done({**it, **res})

        threads = []
        for _ in range(min(self.threads, len(todo))):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        done = [r for r in results if r.get("ok")]
        failed = [r for r in results if not r.get("ok")]
        skipped = [it for it in (items or [])
                   if not it.get("url") and not str(it.get("id") or "").strip()]
        return {
            "ok": bool(done),
            "done": done,
            "failed": failed,
            "skipped": skipped,
            "error": "" if done else (failed[0].get("error") if failed else "全部失败"),
        }


def _fmt_size(n: object) -> str:
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        return "0 B"
    if v <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024:
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024.0
    return f"{v:.1f} PB"
