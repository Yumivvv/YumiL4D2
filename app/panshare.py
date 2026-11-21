# -*- coding: utf-8 -*-
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

"""检查网盘分享是否已过期（目前支持百度网盘）。

## 为什么需要它

B 站简介里的百度网盘链接经常是几个月前贴的，点开才发现「分享已过期」。
用户看到界面上列着一串链接，逐个点开试错很烦。

## 怎么查的（实测出来的）

百度有个公开接口，只要分享短链的 shorturl 就能查到元信息：

    GET https://pan.baidu.com/api/shorturlinfo?shorturl=<surl>

返回 JSON 里的关键字段（全是真的实测值）：

| 字段 | 含义 |
| --- | --- |
| `errno` | `-9` = 分享存在；`2` = 分享不存在/已取消；`-62` = 分享不存在 |
| `expired_type` | `7` = 永久有效（界面上也写「永久有效」） |
| `expiretimestamp` | **过期时间戳（秒）** —— 有这个最准，直接和当前时间比 |
| `expire_days` | 分享时选的「有效天数」，仅作参考 |

★ 一定要优先看 `expiretimestamp`：界面上写「永久有效」的分享，
接口有时也会给一个具体时间戳（实测那条界面写永久、接口给 2026-11-28），
以接口的时间戳为准更可靠。

## 并发与缓存

- 一次查一条，调用方自己决定并发（见 `check_many`）；
- 结果缓存 30 分钟：同一个视频重复点开不该重复打接口；
- 任何异常都**不当成过期**（网络抖动时宁可显示「未知」，也不要误伤正常链接）。
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

from . import netclient as NC
from .util import Log

log = Log("panshare.log")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

API = "https://pan.baidu.com/api/shorturlinfo?shorturl={}"

# 夸克分享元信息接口（不需要登录，也不用提取码就能拿到过期时间）。
# ★ 必须是 `clouddrive` 这个路径；`cloudshare` 实测返回 404
#   （`{"status":404,...,"path":"/1/cloudshare/sharepage/token"}`），
#   而 404 的 body 里也带 `status`/`message`，很容易被误当成有效响应。
QUARK_TOKEN_APIS = (
    "https://drive-pc.quark.cn/1/clouddrive/share/sharepage/token",
    "https://drive.quark.cn/1/clouddrive/share/sharepage/token",
)
# 夸克明确表示「分享没了」的 code（拿不到元信息时才用得上）
QUARK_GONE_CODES = {41004, 41005, 41006, 41007, 41009}
QUARK_GONE_TEXT = {
    41004: "分享不存在或已被取消",
    41005: "分享不存在或已被取消",
    41006: "分享已过期",
    41007: "分享已失效",
    41009: "分享不存在或已被取消",
}

# 缓存：{url: (时间戳, 结果dict)}
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 30 * 60.0
_LOCK = threading.Lock()

# `/s/1AbCdEf...` 里 `/s/` 后面那段就是 shorturl
_SURL_RE = re.compile(r"/s/([A-Za-z0-9_-]{4,})")

# errno → 人话
_ERRNO = {
    -9: "",                       # 正常
    2: "分享不存在或已被取消",
    -62: "分享不存在或已被取消",
    -7: "提取码错误",
    -9 - 1: "",                   # 占位，避免 -10 被误判
}


def _surl(url: str) -> str:
    """从百度网盘链接里抠出 shorturl（`/s/xxx` 里的 xxx）。"""
    try:
        m = _SURL_RE.search(urllib.parse.urlparse(url).path or "")
    except ValueError:
        return ""
    return m.group(1) if m else ""


def _fmt(ts: int) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(int(ts)))
    except (ValueError, OSError, TypeError):
        return ""


def _unknown() -> dict:
    """查不到时的统一返回（**绝不误判成过期**）。"""
    return {"ok": False, "state": "unknown", "text": "", "expireAt": 0,
            "expireDays": 0}


def _judge(expire_s: int, now: float) -> dict:
    """按「过期时间戳（秒）」给出结论。0 = 永久有效。

    百度和夸克的时间戳单位不同（百度秒、夸克毫秒），
    但统一换算成秒之后判断逻辑是一样的，所以抽在这儿。
    """
    if not expire_s:
        return {"ok": True, "state": "ok", "text": "永久有效", "expireAt": 0,
                "expireDays": 0}
    if expire_s < now:
        return {"ok": True, "state": "expired",
                "text": f"已过期（{_fmt(expire_s)}）", "expireAt": expire_s,
                "expireDays": 0}
    days = max(0, int((expire_s - now) // 86400))
    if days == 0:
        # 不足一天 → 显示「今天到期」比「0 天后到期」自然
        days = 1
    else:
        # ★ 向上取整：`expire - now` 常因为时间戳精度差几百毫秒，
        #   7×86400 会算成 6 天多一点点 → 向下取整就变成「6 天后到期」，
        #   和接口说的 expired_days=7 对不上，看着像算错了。
        #   只要还剩任何零头，就按「多一天」算更符合直觉。
        if (expire_s - now) % 86400:
            days += 1
    return {"ok": True, "state": "ok", "text": f"{_fmt(expire_s)} 到期",
            "expireAt": expire_s, "expireDays": days}


def _check_baidu(url: str, now: float, timeout: float) -> dict:
    """百度：`/api/shorturlinfo?shorturl=<surl>`。

    字段：`errno`（-9 正常 / 2 不存在）、`expired_type`（7 = 永久）、
    `expiretimestamp`（**秒**）、`expire_days`（仅参考）。
    """
    surl = _surl(url)
    if not surl:
        return _unknown()
    try:
        resp = NC.get(API.format(surl), headers={"User-Agent": UA},
                      timeout=(4, max(5.0, float(timeout))))
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        js = resp.json()
    except Exception as e:  # noqa: BLE001  网络问题一律「未知」，不误判
        log(f"shorturlinfo failed {surl}: {e!r}")
        return _unknown()

    errno = int(js.get("errno") or 0)
    if errno != -9:
        msg = _ERRNO.get(errno) or "分享打不开（可能已被取消）"
        return {"ok": True, "state": "gone", "text": msg, "expireAt": 0,
                "expireDays": 0}
    return _judge(int(js.get("expiretimestamp") or 0), now)


def _quark_surl(url: str) -> str:
    """夸克分享链接里的 pwd_id：`pan.quark.cn/s/<id>`。"""
    try:
        m = re.search(r"/s/([A-Za-z0-9]{4,})",
                      urllib.parse.urlparse(url).path or "")
    except ValueError:
        return ""
    return m.group(1) if m else ""


def _check_quark(url: str, now: float, timeout: float,
                 passcode: str = "") -> dict:
    """夸克：`sharepage/token` 接口，**不需要登录**。

    实测返回（即使 code=41008「需要提取码」，data 里照样带全元信息）::

        "expired_days": 7,
        "expired_type": 3,
        "expired_at": 1795881599000,   ← ★ 毫秒，要 /1000
        "title": "生死狙击魔龙骑士.rar"

    ★ `passcode` 尽量传（从链接的 `?pwd=` 或简介里的「提取码：xxx」拿到）：
      不带提取码时接口仍会给 `expired_at`，但传上更接近真实访客的请求，
      而且某些分享不带码会直接报错。

    `expired_at` 缺失或 0 → 当**永久有效**（夸克永久分享不给这个字段）。
    """
    surl = _quark_surl(url)
    if not surl:
        return _unknown()

    headers = {
        "User-Agent": UA,
        "Referer": "https://pan.quark.cn/",
        "Origin": "https://pan.quark.cn",
    }
    js = None
    for api in QUARK_TOKEN_APIS:
        try:
            resp = NC.post(api, json={"pwd_id": surl,
                                      "passcode": str(passcode or "")},
                           params={"pr": "ucpro", "fr": "pc"},
                           headers=headers,
                           timeout=(4, max(5.0, float(timeout))))
            if int(getattr(resp, "status_code", 0) or 0) != 200:
                continue
            body = resp.json()
        except Exception as e:  # noqa: BLE001
            log(f"quark token failed {surl} @ {api}: {e!r}")
            continue
        # ★ 只认「带 data 且 data 是 dict」的响应。404 的 body 里也有
        #   status/message，光判 `"data" in body` 会把错误响应当成功。
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            js = body
            break

    if not js:
        return _unknown()

    data = js["data"]
    # expired_at 是**毫秒**；没有这个字段 = 永久分享
    raw = data.get("expired_at") or 0
    try:
        expire_s = int(int(raw) / 1000) if raw else 0
    except (TypeError, ValueError):
        expire_s = 0

    res = _judge(expire_s, now)
    # 拿不到时间戳、但 code 明确说「分享没了」→ 判失效
    code = int(js.get("code") or 0)
    if not expire_s and code in QUARK_GONE_CODES:
        return {"ok": True, "state": "gone",
                "text": QUARK_GONE_TEXT.get(code, "分享不存在或已被取消"),
                "expireAt": 0, "expireDays": 0}
    return res


def check(url: str, timeout: float = 8.0, passcode: str = "") -> dict:
    """检查一条链接的状态（目前支持百度网盘、夸克网盘）。

    `passcode` 是可选的提取码 —— 夸克那边带上更接近真实访客的请求；
    百度用不上（它只看 shorturl）。调用方可以把「链接旁边那个提取码」传进来。

    返回：::

        {"ok": bool,        # 请求本身成功了吗
         "state": "ok" | "expired" | "gone" | "unknown",
         "text": "…",       # 给界面显示的一句话
         "expireAt": 0,     # 过期时间戳（秒；0 = 永久/未知）
         "expireDays": 0}   # 还剩几天（0 = 永久/未知）

    `state` 语义：
      - `ok`      正常（可能有到期日，看 `expireDays`）
      - `expired` **已过期**
      - `gone`    分享不存在 / 已被取消
      - `unknown` 查不到（网络、不支持的网盘、接口变了……）
    """
    key = str(url or "").strip()
    if not key:
        return _unknown()

    now = time.time()
    # 提取码参与缓存键：同一个链接换了个码，结果可能不同
    ck = (key, str(passcode or ""))
    with _LOCK:
        hit = _CACHE.get(ck)
        if hit and now - hit[0] < _CACHE_TTL:
            return dict(hit[1])

    try:
        host = (urllib.parse.urlparse(key).hostname or "").lower()
    except ValueError:
        host = ""

    if "baidu.com" in host:
        res = _check_baidu(key, now, timeout)
    elif "quark.cn" in host:
        res = _check_quark(key, now, timeout, passcode)
    else:
        res = _unknown()

    with _LOCK:
        _CACHE[ck] = (now, res)
    return dict(res)


def check_many(urls: Iterable[str], workers: int = 4,
               timeout: float = 8.0,
               codes: dict[str, str] | None = None) -> dict[str, dict]:
    """并发查一批（同一个视频里的链接）。返回 {url: 结果}。

    `codes` 可选：{url: 提取码}，有的话一起传下去（夸克用得上）。
    """
    items = [str(u or "").strip() for u in urls]
    items = [u for u in items if u]
    if not items:
        return {}

    from concurrent.futures import ThreadPoolExecutor

    cmap = codes or {}
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as pool:
        for u, res in zip(items, pool.map(
                lambda x: check(x, timeout, cmap.get(x, "")), items)):
            out[u] = res
    return out


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
