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

"""服务器浏览 / 收藏 / 直连。

自己实现 Valve 的 A2S 查询协议（UDP），不依赖第三方接口：

* ``A2S_INFO``：``FF FF FF FF 54 "Source Engine Query" 00``
  现在大多数服务器会先回一个 ``0x41``（challenge）包，必须把它带回的 4 字节
  附加在请求后面再发一次，才会拿到 ``0x49``（'I'）的正式回包。
* ``A2S_PLAYERS``：``FF FF FF FF 55 FF FF FF FF``，同样是先 challenge。

从回包里解析出：服务器名、地图代码、当前人数 / 上限 / bot 数、版本、VAC、tags。
模式（战役 / 对抗 / 写实 / 生存 / 清道夫 …）先看 tags 里的 ``m:xxx``，
再看 tags 关键字，最后退回服务器名里的中文关键字 —— 国内很多服 tags 是空的
或者干脆是二进制垃圾（实测过），只看 tags 会全都变成「未知」。

地图中文名走**内置表**（`_BUILTIN_MAPS`），完全离线、不查任何第三方服务；
查过的结果再缓存一层（内存 + ``data/cache/maps.json``）。

直连用 Steam 的 ``steam://connect/ip:port``，另外给一条 ``connect ip:port``
控制台命令方便复制。
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from . import util
from . import steamfriends as SF
from . import workshop_dns as WDNS
from .util import Log

log = Log("servers.log")

DEFAULT_PORT = 27015
QUERY_TIMEOUT = 2.2
QUERY_RETRIES = 2
MAX_WORKERS = 4
# 程序启动后这段时间内的剪贴板事件一律忽略（秒）。
# Windows 上 Qt 起来时会自己抛一次 dataChanged（剪贴板所有权交接），
# 不挡住的话「开软件就弹一次」的 bug 会回来。
CLIP_STARTUP_GRACE = 2.5
MAP_TTL = 7 * 24 * 3600.0
# ★ 地图中文名：**内置表**，不再向第三方服务查询。
#   历史上这里会请求 `l4d2-maps.laoyutang.cn`（LytVPK 维护者的线上服务），
#   对方已在 issue #1 中要求迁移 —— 现在完全离线（`MAP_API` 常量已随之删除）。
#   表覆盖 L4D2 官方 13 个战役（c1~c13）的全部章节 + 常见社区图。
#   查不到的图就显示地图代码本身，不影响使用。
MAP_CACHE_PATH = os.path.join(util.CACHE_DIR, "maps.json")

# ---- 好友在玩的服务器 ----
# 「好友服务器」在合集选择器里单独占一项，和「全部 / 未分类 / 自动合集」并列。
# 用 __friends__ 这种带下划线的前缀，避免和真实服名撞车。
FRIEND_GROUP_KEY = "__friends__"
FRIEND_GROUP_LABEL = "好友在玩"
# 好友状态多久刷新一次（秒）。太频繁没必要，Steam 那边状态也变得不快。
FRIEND_REFRESH_SEC = 90

# ---- 用户自建合集 ----
# 和「自动合集」（按名字前缀 / 同 IP 推断）并存：
#   · 自动合集是**算**出来的，成员一变就重组；
#   · 自建合集是**存**下来的，用户说了算，谁进去谁出来都由用户决定。
# 存进 config 的形状（`server_collections`）：
#     [{"id": "c1a2b3", "label": "我的常用服", "addrs": ["1.2.3.4:27015", ...]}]
#
# ★ 为什么自建合集用独立字段而不是塞进 `server_group_names`：
#   那个字段是 `{addr: 组名}`，语义是「给**自动**合集改个名」，
#   一台服务器只能属于一个自动合集。而用户要的是「我把这几台归到一起」——
#   这件事和自动识别是两套逻辑，混在一起会互相打架
#   （比如同一台服务器被自动分到「天域」、又被用户放进「我的常用服」）。
COLLECTION_KEY_PREFIX = "c:"
COLLECTION_MAX = 60          # 合集数量上限，防止界面被撑爆
COLLECTION_LABEL_MAX = 24

_INFO_REQ = b"\xff\xff\xff\xff\x54Source Engine Query\x00"
_PLAYERS_REQ = b"\xff\xff\xff\xff\x55\xff\xff\xff\xff"

# tags 里的 m: 前缀 → (模式码, 显示名)
TAG_MODES: dict[str, tuple[str, str]] = {
    "coop": ("coop", "战役"),
    "versus": ("versus", "对抗"),
    "teamversus": ("versus", "对抗"),
    "survival": ("survival", "生存"),
    "dash": ("dash", "生存跑酷"),
    "scavenge": ("scavenge", "清道夫"),
    "teamscavenge": ("scavenge", "清道夫"),
    "realism": ("realism", "写实"),
    "realismversus": ("realismversus", "写实对抗"),
    "holdout": ("holdout", "死守"),
    "shootzones": ("shootzones", "射击禁区"),
}

# 名字里出现这些词就认为是这个模式（从长到短，先命中者胜）
NAME_MODES: list[tuple[tuple[str, ...], tuple[str, str]]] = [
    (("写实对抗", "realism versus", "realismversus"), ("realismversus", "写实对抗")),
    (("写实", "写真", "realism"), ("realism", "写实")),
    (("对抗", "versus", "vs."), ("versus", "对抗")),
    (("清道夫", "scavenge"), ("scavenge", "清道夫")),
    (("突变", "mutation"), ("mutation", "突变")),
    (("死守", "holdout"), ("holdout", "死守")),
    (("生存", "survival"), ("survival", "生存")),
    (("无限火力", "火力全开"), ("custom", "自定义")),
    (("战役", "coop", "co-op", "合作", "多特", "多人"), ("coop", "战役")),
]

MODE_LABELS = {
    "coop": "战役", "versus": "对抗", "realism": "写实",
    "realismversus": "写实对抗", "survival": "生存", "scavenge": "清道夫",
    "mutation": "突变", "holdout": "死守", "dash": "生存跑酷",
    "shootzones": "射击禁区", "custom": "自定义", "": "未知",
}

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SPACE_RE = re.compile(r"\s+")
_ADDR_RE = re.compile(r"^(?P<host>\[[0-9a-fA-F:]+\]|[^\s:/]+)(?::(?P<port>\d{1,5}))?$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_TLD_RE = re.compile(r"^[A-Za-z]{2,24}$")
_MAP_BAD_RE = re.compile(r"[^\w\s\-\[\]()（）·.|/]")


class ServerError(Exception):
    """地址不合法 / 查询失败。"""


# ---------------------------------------------------------------------------
# 服务器自动分类：按「名字里出现了什么词」归到一类
# ---------------------------------------------------------------------------
# 用户的原话是「相关提示词的就能分类，比如 xx服xx模式#1，这样子差不多的」。
# 所以这里不搞复杂的 NLP，就是**关键词命中**：
#   · 按顺序匹配，先命中的优先（写实对抗要排在写实/对抗前面，否则会被拆开）
#   · 全部坐不上就归「其他」
# 每类给一个稳定的 key（存盘/筛选用）+ 中文显示名。
SERVER_CATEGORIES = (
    # (key, 显示名, 关键词元组)
    ("realismversus", "写实对抗", ("写实对抗", "写实 对抗", "realism versus", "realismversus")),
    ("versus", "对抗", ("对抗", "versus", "pvp", "对战")),
    ("realism", "写实", ("写实", "realism", "真实模式")),
    ("coop", "战役", ("战役", "coop", "合作", "剧情", "通关")),
    ("survival", "生存", ("生存", "survival")),
    ("scavenge", "清道夫", ("清道夫", "scavenge")),
    ("mutation", "突变", ("突变", "mutation")),
    ("holdout", "死守", ("死守", "holdout", "守点")),
    ("dash", "跑酷", ("跑酷", "dash")),
    ("shootzones", "射击禁区", ("射击禁区", "shootzones")),
    ("mod", "模组服", ("模组", "插件", "魔改", "自定义", "custom", "mod")),
)


def server_category(name: str) -> str:
    """按服务器名里的提示词猜一个分类 key（猜不出就 ``other``）。"""
    text = (name or "").strip().lower()
    if not text:
        return "other"
    for key, _label, words in SERVER_CATEGORIES:
        for w in words:
            if w in text:
                return key
    return "other"


# 「名字 → 分类」的关键词表里，这些词太宽泛，单独出现不足以定类。
# ★ 用户报的「明明是战役服却归到其他」：`mutation` 那类里带了 `"mutation"`，
#   而 `mod` 类里带了 `"mod"` —— 后者会命中 `modserver / modded` 这类，
#   但真正的问题在于**顺序**：`mod` 排在最后，`战役/coop` 排在它前面，
#   于是「模组战役服」被判成战役。这本身没错，错的是
#   **`server_category()` 和 `parse_mode()` 用的是两套词表**，
#   同一台服在列表上是「战役」，在分类条里却是「其他」（两边完全不同源）。
#
# 现在给分类加一条「名字猜不出来就借 mode 的结论」的兜底，见 `_merged()`；
# 这里先把 `NAME_MODES` 里有、但 `SERVER_CATEGORIES` 里没有的模式补齐。
_CATEGORY_EXTRA = (
    # (key, 显示名, 关键词) —— 只补 SERVER_CATEGORIES 里缺的，已有的不重复
    ("custom", "自定义", ("无限火力", "火力全开")),
)


def category_key_for_mode(mode_code: str) -> str:
    """把 `parse_mode()` 的模式码映射成分类 key（对不上返回空串）。

    两个函数的词表不同步时，这条映射保证「列表上写战役」的服，
    在分类条里也能落到「战役」而不是「其他」。
    """
    code = (mode_code or "").strip().lower()
    if not code:
        return ""
    mapping = {
        "realismversus": "realismversus",
        "versus": "versus",
        "realism": "realism",
        "coop": "coop",
        "survival": "survival",
        "scavenge": "scavenge",
        "mutation": "mutation",
        "holdout": "holdout",
        "dash": "dash",
        "shootzones": "shootzones",
        "custom": "mod",
    }
    return mapping.get(code, "")


def category_label(key: str) -> str:
    """分类 key → 中文显示名。"""
    for k, label, _words in SERVER_CATEGORIES:
        if k == key:
            return label
    return "其他"


SERVER_CATEGORY_LABELS = {
    "all": "全部分类",
    **{k: label for k, label, _w in SERVER_CATEGORIES},
    "other": "其他",
}


# ---------------------------------------------------------------------------
# 服务器分组：同一「系列」的服归到一个合集里
# ---------------------------------------------------------------------------
# 用户的场景：一整个服群（比如「天域」开头的一排服、或者同一台机器上的
# 27015~27025 一堆端口），想按组看、快速定位要玩的那台。
#
# 两条归类依据，按优先级：
#   1. **名字前缀**：把名字前面的「公共部分」切出来当组名。
#      比如「天域1服」「天域2服」「天域·对抗」都归到「天域」。
#   2. **同一 IP**：名字对不上但 IP 一样的（端口不同），归到该 IP 组。
#      组名用 IP，这样「同一个服主的多个端口」也是一组。
#
# 名字前缀怎么切：去掉数字、括号、端口号、常见分隔符之后，
# 取前 2~6 个字当作前缀；太短（1 个字）或太通用（「服务器」「模式」）就不认。

# 名字里用来分隔的符号：这些之后的都算「明细」，不参与前缀
_NAME_SPLIT_RE = re.compile(r"[\s\-_·•｜|#＃:：/\\()（）\[\]【】<>《》]+")
# 纯数字 / 数字+服 / 端口号 这类尾巴
_NUM_TAIL_RE = re.compile(r"^[\d.]+(服|号|区|线|#\d*)?$")
# 太通用的前缀，不作为组名
_GENERIC_PREFIX = {
    "服务器", "伺服", "模式", "房间", "专用", "公开", "纯净", "官方",
    "求生之路", "求生", "left", "l4d2", "l4d", "4人", "人",
    "the", "server", "srv",
}
# 组名前缀最短 / 最长长度（按字符）
_GROUP_MIN = 2
_GROUP_MAX = 8


def name_prefix(name: str) -> str:
    """从服务器名里切出「系列前缀」，切不出来返回空串。

    例：
        「天域1服」          → 「天域」
        「天域·对抗 2」      → 「天域」
        「【天域】3号线」    → 「天域」（方括号先剥掉）
        「4人纯净写实专家 1服」→ 「4人纯净写实」（数字尾巴去掉）
        「药抗小分队」       → 「药抗小分队」（没有明显分隔，整体当组名）
        「Alice」            → 「」（太短/英文单词，不分组）
    """
    text = clean_name(name or "")
    if not text:
        return ""
    # 开头的方括号/圆括号标签（【CN】【天域】这类）：
    # 它**本身就是最可靠的系列名**（「【天域】3号线」→ 天域），
    # 所以优先用它当组名，而不是丢掉。
    m_tag = re.match(r"^[【\[（(]([^】\]）)]{1,16})[】\]）)]\s*", text)
    if m_tag:
        tag = m_tag.group(1).strip()
        rest = text[m_tag.end():].strip()
        # ★ 方括号里的标签也要**去掉尾部数字**，否则同一个服群会被拆成两组：
        #   「【黑喵0】多人多特」→ 黑喵0、「【黑喵】多人战役#0」→ 黑喵
        #   （用户报的「扫描后导入合集显示成 IP / 有前缀却识别不到」就是这个）。
        tag_clean = re.sub(r"[\d]+\s*(服|号|区|线|#)?$", "", tag).strip()
        # 标签是地区码（CN/HK/TW/US…）时不算系列名，继续看后面的正文
        if not re.fullmatch(r"[A-Za-z]{2,4}", tag):
            for cand in (tag_clean, tag):
                if len(cand) >= _GROUP_MIN and cand not in _GENERIC_PREFIX:
                    return cand[:_GROUP_MAX]
        text = rest
    if not text:
        return ""

    # 按分隔符切，第一段通常是「系列名」
    head = _NAME_SPLIT_RE.split(text)[0] if _NAME_SPLIT_RE.split(text) else text
    head = (head or "").strip()
    # 去掉末尾的数字（「天域1」→「天域」，「专家多特1」→「专家多特」）
    head = re.sub(r"[\d]+\s*(服|号|区|线)?$", "", head).strip()

    # 「3号线」这种**整段就是「数字+单位」**的，剥掉方括号后只剩个编号，
    # 号码不是系列名 → 返回空，让它落到「按 IP 分组」那条路上。
    # 注意：只在整段匹配时才清空，不能把「4人纯净写实专家」开头的 4 吃掉。
    if re.fullmatch(r"[\d]+\s*(号|区|线|服|#)?", head or ""):
        return ""
    if not head:
        return ""

    # 中文前缀：直接截断到 _GROUP_MAX
    if re.search(r"[\u4e00-\u9fff]", head):
        if len(head) < _GROUP_MIN:
            return ""
        prefix = head[:_GROUP_MAX]
        if prefix in _GENERIC_PREFIX or head in _GENERIC_PREFIX:
            return ""
        return prefix

    # 英文/数字前缀：必须是「词 + 数字」这种（比如「Alien1」），
    # 单个普通英文单词不分组（否则「My Server」会把所有英文服并一起）
    m = re.match(r"^([A-Za-z][A-Za-z0-9_]{2,})[\d]*$", head)
    if m:
        word = m.group(1)
        if word.lower() in _GENERIC_PREFIX or len(word) < 3:
            return ""
        return word[:_GROUP_MAX]
    return ""


def natural_sort_key(text: str) -> tuple:
    """「自然排序」的键：把数字当成数字比，而不是逐字符比字符串。

    ★ 用户报的「黑喵0 → 黑喵10 → 黑喵1」：
      纯字符串排序里 `'黑喵10' < '黑喵1服'`（因为 `'0' < '服'`），
      于是 10 排在 1 前面。把连续数字切成整数段之后，
      `黑喵1` 的键是 `['黑喵', 1, '']`、`黑喵10` 是 `['黑喵', 10, '']`，
      自然就按 1 < 10 排了。

    返回值形如 ``('黑喵', 1, '', ...)``，可以直接当 ``sort`` 的 key。
    用 `(type_rank, value)` 元组保证「数字段」和「文字段」不会互相比出 TypeError。
    """
    raw = str(text or "")
    out: list = []
    for part in re.split(r"(\d+)", raw):
        if not part:
            continue
        if part.isdigit():
            # 数字段：转成 int 比较（前导 0 也按数值算，0123 与 123 同序）
            out.append((1, int(part)))
        else:
            out.append((0, part.lower()))
    return tuple(out)


def _sort_key_name(row: dict) -> tuple:
    """按名字排序：先自然序，名字一样再按地址兜底（保证顺序稳定）。"""
    return (natural_sort_key(row.get("name") or ""), row.get("addr") or "")


def host_of(addr: str) -> str:
    """取 ``host:port`` 里的 host（去掉 IPv6 的方括号）；取不到返回空串。"""
    try:
        return split_address(addr)[0] if addr else ""
    except (ValueError, IndexError):
        return (addr or "").rsplit(":", 1)[0]


def server_group(addr: str, name: str) -> str:
    """这一行**单看自己**能算出的组名：目前就是名字前缀（空串 = 切不出）。

    ★ 注意：真正的合集是 ``group_servers()`` 按**整份列表**算的，
      因为「同 IP」这条依据要凑够 2 台才算数，单行看不到别人。
      这个函数只用来给行数据挂一个「名字系列」提示，别拿它当合集来源。
    """
    return name_prefix(name)


def group_servers(rows: list, overrides: dict | None = None) -> list:
    """把服务器聚成合集，返回 ``[{key, label, kind, count, addrs, host}]``。

    ★ 用户原话：「如果少于 2 个同名类似服务器或 IP 那么弄到未分类里面」——
      也就是说**同 IP 本来就算一条归类依据**。中间有一版把它砍掉了，
      只留名字前缀，结果同一台机器上的 27016~27022（模式不同、名字不同）
      被拆成「一个名字合集 + 几条未分类」，用户又报了一次：
      「1.70.33.241:27016 到 27022 都有 IP，为什么这两个没分类进去，
        这其实也算在里面因为 IP 一样，然后就模式不一样而已，应该都搞成一个分类里面」。

    所以现在是**两条依据取并集**，用并查集合并：
      1. 名字前缀相同，且这种前缀至少 2 台（「天域1服」「天域2服」→ 天域）
      2. IP 相同，且这台机器上至少 2 台（27015~27022 模式不同也归一起）

    合并（而不是各算各的）是必须的：同一台机器上如果既有「同前缀的 5 台」
    又有「名字不同的 2 台」，分开算会得到「一个名字合集 + 2 条未分类」——
    还是同一个服主的两堆东西，正是用户不想要的。

    组名怎么定：成员里**出现次数最多的名字前缀**，前缀全都不同就退回用 IP。
    最终**至少 2 台**才算合集，单台的进「未分类」。

    ``overrides`` 是用户**手动改过的合集名**（``{addr: 组名}``）：组里任何一台
    有手动名字，就整组用这个名字，自动识别不出来时用户也能自己命名
    （用户原话：「添加手动修改合集名，这样防止还是识别不到，那么就可以自己修改合集名」）。
    """
    valid = [r for r in (rows or []) if str(r.get("addr") or "")]
    if not valid:
        return []

    overrides = overrides or {}
    addrs = [str(r["addr"]) for r in valid]

    def name_of(r):
        return r.get("name") or r.get("liveName") or ""

    prefixes = [name_prefix(name_of(r)) for r in valid]
    hosts = [host_of(a) for a in addrs]

    # ---- 并查集：同前缀 / 同 IP 都是「一条边」
    parent = list(range(len(valid)))

    def find(i: int) -> int:
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:      # 路径压缩
            parent[i], i = root, parent[i]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def link_by(values: list[str]) -> None:
        """把值相同的下标连起来，但只有该值出现 ≥2 次才算。"""
        buckets: dict[str, list[int]] = {}
        for i, v in enumerate(values):
            if v:
                buckets.setdefault(v.lower(), []).append(i)
        for idx in buckets.values():
            if len(idx) >= 2:
                for j in idx[1:]:
                    union(idx[0], j)

    link_by(prefixes)     # 1) 同名字系列
    link_by(hosts)        # 2) 同一台机器（同 IP 不同端口）

    comps: dict[int, list[int]] = {}
    for i in range(len(valid)):
        comps.setdefault(find(i), []).append(i)

    out: list[dict] = []
    for idx in comps.values():
        if len(idx) < 2:
            continue          # 单台不成组 → 落到「未分类」
        picked = [prefixes[i] for i in idx if prefixes[i]]
        label, kind = "", "ip"
        if picked:
            counts: dict[str, int] = {}
            for p in picked:
                counts[p] = counts.get(p, 0) + 1
            # 台数最多的那个前缀当组名；平票时取更长的（更具体）、再按字典序。
            # ★ 但**至少要有 2 台共用**才配当组名 —— 一台一个前缀的机器
            #   （名字全是各叫各的）用 IP 当组名才不误导人。
            best = max(counts, key=lambda k: (counts[k], len(k), k))
            if counts[best] >= 2:
                label = best
                kind = "name"
        group_host = hosts[idx[0]]
        if not label:
            label = group_host or "合集"
        # ★ 用户手动命名优先：组里任何一台有手动合集名，就整组用这个名字。
        #   这是「自动识别不出来时也能自己命名」的兜底，不能被自动结果盖掉。
        manual = ""
        for i in idx:
            nm = str(overrides.get(addrs[i]) or "").strip()
            if nm:
                manual = nm
                break
        if manual:
            label = manual
            kind = "manual"
        out.append({
            "key": ("n:" if kind == "name" else
                    ("m:" if kind == "manual" else "i:")) + label,
            "label": label,
            "kind": kind,
            "count": len(idx),
            "addrs": [addrs[i] for i in idx],
            # 整组都在同一台机器上 → 界面上可以标「同 IP」
            "host": group_host if all(h == group_host for h in (hosts[i] for i in idx)) else "",
        })

    out.sort(key=lambda g: (-g["count"], g["label"]))
    return out


def apply_collections(groups: list, rows: list,
                      collections: list | None = None) -> list:
    """把**用户自建合集**并进自动合集的结果里。

    ★ 为什么是「并进」而不是「替换」：
      用户明确要的是「能转到某某合集里面保存，还可以自己新建合集」——
      自建是**追加**一种归类方式，不是把自动识别的结果推翻。
      所以：

        · 自建合集整条出现在选择器里（哪怕只有 1 台，用户建的就是它的意思）；
        · 已经被收进自建合集的服务器，**不再重复出现在自动合集里** ——
          否则同一台服务器在两个合集下都能看到，勾选/删除会让人犯迷糊；
        · 没收进任何自建合集的，继续按自动规则归类；
        · 自动合集被搬空了就不显示（成员都跑去自建合集了）。

    ``collections`` 形如 ``[{"id", "label", "addrs"}]``。
    返回的每项多一个 ``kind="custom"`` 和 ``collectionId``，界面据此画不同图标。
    """
    groups = list(groups or [])
    cols = collections or []
    if not cols:
        return groups

    known = {str(r.get("addr") or "") for r in (rows or [])}
    claimed: set[str] = set()
    custom: list[dict] = []
    for c in cols:
        cid = str(c.get("id") or "").strip()
        label = str(c.get("label") or "").strip()
        if not cid or not label:
            continue
        # 只留下**列表里真实存在**的地址：用户可能把服务器删了，
        # 合集里残留的幽灵地址不该让 count 变成假的。
        addrs = [str(a) for a in (c.get("addrs") or []) if str(a) in known]
        claimed.update(addrs)
        custom.append({
            "key": COLLECTION_KEY_PREFIX + cid,
            "label": label,
            "kind": "custom",
            "collectionId": cid,
            "count": len(addrs),
            "addrs": addrs,
            "host": "",
        })

    # 自动合集里剔掉已经被自建合集收走的地址
    trimmed: list[dict] = []
    for g in groups:
        left = [a for a in (g.get("addrs") or []) if str(a) not in claimed]
        if not left:
            continue
        if len(left) != len(g.get("addrs") or []):
            # 成员被搬走了一部分。
            # ★ 只剩 1 台时**整组撤掉**，让它回到「未分类」：
            #   自动合集的成立条件是「至少 2 台同名前缀 / 同 IP」，
            #   被搬走一半后这个前提已经不成立了，还留着「天域 1 台」
            #   会和「未分类」的定义自相矛盾（用户看到同一类东西被拆到两处）。
            if len(left) < 2:
                continue
            g = dict(g)
            g["addrs"] = left
            g["count"] = len(left)
        trimmed.append(g)

    custom.sort(key=lambda g: natural_sort_key(g["label"]))
    return custom + trimmed


# ---------------------------------------------------------------------------
# 地址
# ---------------------------------------------------------------------------
def normalize_address(text: str) -> str:
    """把用户粘进来的东西整理成 ``ip:port``。

    接受 ``1.2.3.4``、``1.2.3.4:27015``、``steam://connect/1.2.3.4:27015``、
    ``connect 1.2.3.4:27015``、``1.2.3.4:27015/password``（密码丢掉）。
    """
    raw = (text or "").strip().strip("\"'")
    if not raw:
        raise ServerError("地址是空的")
    lowered = raw.lower()
    for prefix in ("steam://connect/", "steam://", "connect "):
        if lowered.startswith(prefix):
            raw = raw[len(prefix):]
            break
    raw = raw.replace("\\", "/").split("/")[0].strip()
    raw = raw.split()[0] if raw.split() else raw
    if not raw:
        raise ServerError("地址里没有主机名")
    if len(raw) > 255:
        raise ServerError("地址太长")
    m = _ADDR_RE.match(raw)
    if not m:
        raise ServerError("看不懂这个地址，写 ip:port 就行")
    host = m.group("host")
    port = m.group("port")
    if port is None:
        port = str(DEFAULT_PORT)
    try:
        port_i = int(port)
    except ValueError as exc:
        raise ServerError("端口不是数字") from exc
    if not 1 <= port_i <= 65535:
        raise ServerError("端口要在 1~65535 之间")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not valid_host(host):
        raise ServerError("主机名看着不像 IP 或域名，检查一下")
    return f"{host}:{port_i}"


def valid_host(host: str) -> bool:
    """像不像一台主机：IPv4 / IPv6 / 域名。"""
    text = (host or "").strip()
    if not text or len(text) > 253:
        return False
    if ":" in text:                        # IPv6
        try:
            socket.inet_pton(socket.AF_INET6, text)
            return True
        except OSError:
            return False
    parts = text.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return all(0 <= int(p) <= 255 for p in parts)
    if len(parts) < 2:
        return False
    if not _TLD_RE.match(parts[-1]):
        return False
    return all(_LABEL_RE.match(p) for p in parts[:-1])


def split_address(addr: str) -> tuple[str, int]:
    host, _, port = addr.rpartition(":")
    return host, int(port)


def resolve_host(host: str, timeout: float = 3.0) -> str:
    """域名 → IPv4。解析不了就抛 ServerError。"""
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
    except socket.gaierror as exc:
        raise ServerError(f"域名解析不了：{host}") from exc
    if not infos:
        raise ServerError(f"域名解析不了：{host}")
    return infos[0][4][0]


# ---------------------------------------------------------------------------
# 名字 / 模式 / 地图
# ---------------------------------------------------------------------------
def clean_name(raw: str) -> str:
    """去掉 Valve 彩色名字里的控制字符，压掉多余空格。

    ★ 顺带去掉 BOM（``\\ufeff``）和各种零宽字符：不少国内服的服务器名
      开头带一个 UTF-8 BOM（``〖黑喵0〗多人多特`` 前面就有），
      它不可见但会占一个字符宽度，导致：
        · 名字排序错位（带 BOM 的永远排最前）；
        · 卡片标题开头像多了一个空格；
        · 导出/分享出去的文本里带着看不见的脏字符。
    """
    text = _CTRL_RE.sub("", raw or "").replace("\ufffd", "")
    # BOM + 零宽空格/连接符/方向标记
    text = re.sub("[\ufeff\u200b-\u200f\u202a-\u202e\u2060\ufeff]", "", text)
    return _SPACE_RE.sub(" ", text).strip()


def name_tag(name: str) -> str:
    """名字里的方括号标签，比如 ``【CN】`` → ``CN``。"""
    m = re.search(r"[【\[]([^】\]]{1,12})[】\]]", name or "")
    return m.group(1).strip() if m else ""


def _tag_pairs(tags: str) -> list[str]:
    return [t.strip().lower() for t in (tags or "").split(",") if t.strip()]


def parse_mode(tags: str, name: str) -> tuple[str, str, str]:
    """返回 ``(模式码, 显示名, 依据)``，依据是 ``tags`` / ``name`` / ``""``。"""
    pairs = _tag_pairs(tags)
    for tag in pairs:
        tag = tag.split(":")[-1] if ":" in tag else tag     # m:coop / gm:versus
        if tag in TAG_MODES:
            code, label = TAG_MODES[tag]
            return code, label, "tags"
        if tag.startswith("mutation") and tag[8:].isdigit():
            return "mutation", "突变", "tags"
        if tag.startswith("community") and tag[9:].isdigit():
            return "mutation", "突变", "tags"
    if pairs:
        # 没有 m: 前缀时按包含关系猜（和官方 server browser 的直觉一致）
        joined = ",".join(pairs)
        for key, value in (
            ("realismversus", ("realismversus", "写实对抗")),
            ("coop", ("coop", "战役")),
            ("versus", ("versus", "对抗")),
            ("realism", ("realism", "写实")),
            ("survival", ("survival", "生存")),
            ("scavenge", ("scavenge", "清道夫")),
            ("mutation", ("mutation", "突变")),
        ):
            if key in joined:
                return value[0], value[1], "tags"
    low = (name or "").lower()
    for words, value in NAME_MODES:
        for word in words:
            if word in low:
                return value[0], value[1], "name"
    return "", "未知", ""


_map_cache: dict[str, tuple[float, str]] = {}
_map_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 内置地图中文名表（**全离线**，不再查询任何第三方地图服务）
# ---------------------------------------------------------------------------
# L4D2 官方 13 个战役，代码形如 c1m1_hotel / c8m5_rooftop。
# 这里给到「战役名|章节名」两级，和 `split_map()` 的 `|` 约定一致。
# 服务器报的图名多半只有 cXmY 前缀（后面可能带 _xxx），
# 所以匹配时先精确查，再退到 `cXmY` 前缀，最后退到 `cX`（战役级）。
_BUILTIN_MAPS: dict[str, str] = {
    # 死亡中心 Dead Center
    "c1m1_hotel": "死亡中心|旅馆",
    "c1m2_streets": "死亡中心|街道",
    "c1m3_mall": "死亡中心|购物中心",
    "c1m4_atrium": "死亡中心|中庭",
    # 黑色狂欢节 Dark Carnival
    "c2m1_highway": "黑色狂欢节|高速公路",
    "c2m2_fairgrounds": "黑色狂欢节|游乐场",
    "c2m3_coaster": "黑色狂欢节|过山车",
    "c2m4_barns": "黑色狂欢节|谷仓",
    "c2m5_concert": "黑色狂欢节|音乐会",
    # 沼泽激战 Swamp Fever
    "c3m1_plankcountry": "沼泽激战|乡村",
    "c3m2_swamp": "沼泽激战|沼泽",
    "c3m3_shantytown": "沼泽激战|贫民窟",
    "c3m4_plantation": "沼泽激战|种植园",
    # 暴风骤雨 Hard Rain
    "c4m1_milltown_a": "暴风骤雨|密尔镇",
    "c4m2_sugarmill_a": "暴风骤雨|糖厂",
    "c4m3_sugarmill_b": "暴风骤雨|糖厂（返回）",
    "c4m4_milltown_b": "暴风骤雨|密尔镇（返回）",
    "c4m5_milltown_escape": "暴风骤雨|撤离",
    # 消逝 The Passing
    "c5m1_waterfront": "消逝|码头",
    "c5m2_park": "消逝|公园",
    "c5m3_cemetery": "消逝|墓园",
    "c5m4_quarter": "消逝|街区",
    "c5m5_bridge": "消逝|桥梁",
    # 牺牲 The Sacrifice
    "c6m1_riverbank": "牺牲|河岸",
    "c6m2_bedlam": "牺牲|疯人院",
    "c6m3_port": "牺牲|港口",
    # 毫不留情 No Mercy
    "c7m1_docks": "毫不留情|码头",
    "c7m2_barge": "毫不留情|驳船",
    "c7m3_port": "毫不留情|港口",
    # 教区 The Parish
    "c8m1_apartment": "教区|公寓",
    "c8m2_subway": "教区|地铁",
    "c8m3_sewers": "教区|下水道",
    "c8m4_interior": "教区|内部",
    "c8m5_rooftop": "教区|屋顶",
    # 短暂时刻 Crash Course
    "c9m1_alleys": "短暂时刻|小巷",
    "c9m2_lots": "短暂时刻|停车场",
    # 死亡丧钟 Death Toll
    "c10m1_caves": "死亡丧钟|洞穴",
    "c10m2_drainage": "死亡丧钟|排水沟",
    "c10m3_ranchhouse": "死亡丧钟|农舍",
    "c10m4_mainstreet": "死亡丧钟|大街",
    "c10m5_houseboat": "死亡丧钟|船屋",
    # 归乡 Dead Air
    "c11m1_greenhouse": "归乡|温室",
    "c11m2_offices": "归乡|办公楼",
    "c11m3_garage": "归乡|车库",
    "c11m4_terminal": "归乡|航站楼",
    "c11m5_runway": "归乡|跑道",
    # 冷酷溪流 Cold Stream
    "c12m1_hilltop": "冷酷溪流|山顶",
    "c12m2_tunnel": "冷酷溪流|隧道",
    "c12m3_bridge": "冷酷溪流|桥梁",
    "c12m4_barn": "冷酷溪流|谷仓",
    "c12m5_cornfield": "冷酷溪流|玉米地",
    # 最后一人 The Last Stand（23 周年）
    "c13m1_alpinecreek": "最后一人|高山溪",
    "c13m2_southpinestream": "最后一人|南松溪",
    "c13m3_memorialbridge": "最后一人|纪念桥",
    "c13m4_cutthroatcreek": "最后一人|割喉溪",
}

# 战役级兜底（只给到 cX 前缀时用）
_BUILTIN_CAMPAIGNS: dict[str, str] = {
    "c1": "死亡中心", "c2": "黑色狂欢节", "c3": "沼泽激战",
    "c4": "暴风骤雨", "c5": "消逝", "c6": "牺牲", "c7": "毫不留情",
    "c8": "教区", "c9": "短暂时刻", "c10": "死亡丧钟", "c11": "归乡",
    "c12": "冷酷溪流", "c13": "最后一人",
}

_MAP_CODE_RE = re.compile(r"^(c\d+m\d+)", re.I)


def _builtin_map_label(code: str) -> str:
    """在内置表里查地图中文名（精确 → cXmY → cX 三级）。查不到返回空串。"""
    key = str(code or "").strip().lower()
    if not key:
        return ""
    # 有些服报「c1m1_hotelversus」这种带模式后缀的，先看前缀能否对上
    hit = _BUILTIN_MAPS.get(key)
    if hit:
        return hit
    m = _MAP_CODE_RE.match(key)
    if m:
        token = m.group(1).lower()
        for name, label in _BUILTIN_MAPS.items():
            if name.startswith(token):
                return label
        camp = _BUILTIN_CAMPAIGNS.get(token.split("m")[0])
        if camp:
            return camp
    return ""


def _load_map_cache() -> None:
    try:
        with open(MAP_CACHE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    now = time.time()
    with _map_lock:
        for key, value in data.items():
            if isinstance(value, list) and len(value) == 2:
                ts, name = value
                if isinstance(ts, (int, float)) and isinstance(name, str):
                    if now - ts < MAP_TTL:
                        _map_cache[str(key)] = (float(ts), name)


def _save_map_cache() -> None:
    try:
        os.makedirs(os.path.dirname(MAP_CACHE_PATH), exist_ok=True)
        with _map_lock:
            payload = {k: [v[0], v[1]] for k, v in _map_cache.items()}
        tmp = MAP_CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, MAP_CACHE_PATH)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 面板密码：用 Windows 的 DPAPI 加密再落盘
#
# `config.json` 是明文 JSON，直接写密码等于把密码摊在桌面上。DPAPI
# （CryptProtectData）用的是「当前 Windows 用户」的密钥，别的账户/别的机器
# 拿去也解不开，正好够用。解不开（换了电脑、复制了配置）就当没保存过密码，
# 不会崩，也不会把密文当密码发出去。
# ---------------------------------------------------------------------------
class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DataBlob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi(data: bytes, protect: bool) -> bytes | None:
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
    except (AttributeError, OSError):
        return None
    src = _blob(data)
    out = _DataBlob()
    flags = 0x1                                  # CRYPTPROTECT_UI_FORBIDDEN
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if protect:
        ok = fn(ctypes.byref(src), None, None, None, None, flags, ctypes.byref(out))
    else:
        ok = fn(ctypes.byref(src), None, None, None, None, flags, ctypes.byref(out))
    if not ok:
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect_secret(text: str) -> str:
    """明文密码 → ``dpapi:<base64>``；空密码/加密失败返回空串。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    blob = _dpapi(raw.encode("utf-8"), True)
    if not blob:
        return ""
    return "dpapi:" + base64.b64encode(blob).decode("ascii")


def reveal_secret(stored: str) -> str:
    """``dpapi:<base64>`` → 明文；解不开（换了机器/账户）返回空串。"""
    text = (stored or "").strip()
    if not text.startswith("dpapi:"):
        return ""
    try:
        blob = base64.b64decode(text[6:])
    except (ValueError, TypeError):
        return ""
    raw = _dpapi(blob, False)
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def normalize_panel_url(text: str) -> str:
    """面板地址：没写协议就补 ``http://``，去掉末尾斜杠。"""
    value = (text or "").strip()
    if not value:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "http://" + value
    return value.rstrip("/")


def valid_panel_url(text: str) -> bool:
    url = normalize_panel_url(text)
    if not url:
        return False
    parts = urllib.parse.urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def map_label(code: str) -> str:
    """地图代码 → 中文名（**全离线**，查内置表）。

    返回格式和以前一致：``死亡中心|旅馆 [1/4]``（`split_map` 按 `|` 拆）。
    查不到就返回空串，界面回退显示代码本身。
    """
    key = (code or "").strip()
    if not key:
        return ""
    # 服务器自己给的就是中文名（有些模组服会这么干），直接当结果用
    if re.search(r"[\u4e00-\u9fff]", key):
        return _MAP_BAD_RE.sub("", key).strip()

    # 1) 先查运行期缓存（用户以前联网查到的结果也在这里，继续有效）
    with _map_lock:
        hit = _map_cache.get(key)
    if hit:
        return hit[1]

    # 2) 内置表：先精确匹配，再按「章节号 → 战役」兜底
    text = _builtin_map_label(key)
    if not text:
        return ""
    with _map_lock:
        _map_cache[key] = (time.time(), text)
    _save_map_cache()
    return text


def split_map(name: str) -> tuple[str, str]:
    """``死亡中心|旅馆 [1/4]`` → ``("死亡中心", "旅馆 [1/4]")``。"""
    text = (name or "").strip()
    if "|" in text:
        head, _, tail = text.partition("|")
        return head.strip(), tail.strip()
    return text, ""


# ---------------------------------------------------------------------------
# A2S 查询
# ---------------------------------------------------------------------------
def _cstr(data: bytes, pos: int) -> tuple[bytes, int]:
    end = data.index(b"\x00", pos)
    return data[pos:end], end + 1


def _looks_ascii(blob: bytes) -> bool:
    if not blob:
        return False
    bad = sum(1 for b in blob if b < 0x20 or b > 0x7E)
    return bad / len(blob) < 0.05


def _pick_tags(tail: bytes) -> str:
    """从版本号之后那堆字节里挑出 tags。

    正常服务器是 ``EDF`` + 若干可选字段 + ``keywords\\0``，但国内一堆模组服
    在这里塞的是二进制（实测 ``\\xb1\\x87i\\x0f...``），所以不能按位硬读：
    直接把尾部所有 NUL 分隔的片段过一遍，挑「最像 tags 的那一段」。
    """
    best = ""
    for chunk in tail.split(b"\x00"):
        chunk = chunk.strip()
        if len(chunk) < 3 or not _looks_ascii(chunk):
            continue
        text = chunk.decode("utf-8", "replace")
        if "," in text or re.fullmatch(r"[A-Za-z0-9_,:\- ]{3,80}", text):
            if len(text) > len(best):
                best = text
    return best


def _recv(sock: socket.socket, timeout: float) -> bytes:
    sock.settimeout(timeout)
    data, _src = sock.recvfrom(65535)
    return data


def query_info(addr: str, timeout: float = QUERY_TIMEOUT,
               retries: int = QUERY_RETRIES) -> dict:
    """查一次 A2S_INFO。返回 dict（含 ``ok`` / ``ms`` / 错误原因）。"""
    host, port = split_address(addr)
    try:
        ip = resolve_host(host)
    except ServerError as exc:
        return {"ok": False, "addr": addr, "host": host, "port": port,
                "error": str(exc), "checked": time.time()}
    last = ""
    for attempt in range(retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            t0 = time.monotonic()
            sock.sendto(_INFO_REQ, (ip, port))
            data = _recv(sock, timeout)
            if data[4:5] == b"\x41":                    # challenge
                sock.sendto(_INFO_REQ + data[5:9], (ip, port))
                data = _recv(sock, timeout)
            ms = int((time.monotonic() - t0) * 1000)
            if not data.startswith(b"\xff\xff\xff\xff"):
                raise ServerError("回包头不对")
            if data[4:5] != b"\x49":
                raise ServerError(f"回包类型不对（0x{data[4]:02x}）")
            info = _parse_info(data)
            info.update({"ok": True, "ms": ms, "addr": addr,
                         "host": host, "port": port, "ip": ip,
                         "checked": time.time()})
            return info
        except (OSError, ServerError, struct.error, IndexError) as exc:
            last = str(exc) or "连不上"
            time.sleep(0.2 * (attempt + 1))
        finally:
            sock.close()
    return {"ok": False, "addr": addr, "host": host, "port": port,
            "error": last or "连不上", "checked": time.time()}


def _parse_info(data: bytes) -> dict:
    # ★ 起始偏移必须是 5，不是 6。
    #   A2S_INFO 回包结构：
    #       FF FF FF FF | 49('I') | protocol(1B) | name\0 | map\0 | ...
    #        0  1  2  3     4         5
    #   所以跳过「4 字节头 + 1 字节类型」= 5，protocol 在偏移 5。
    #
    #   以前写的是 6（多跳了 1 字节），后果是：
    #     · protocol 读到的是 **name 的第一个字节**（例如「药」的 0xE8=232）
    #     · name 从第二个字节开始读 → **名字永远丢掉第一个字节**
    #   一个 UTF-8 汉字占 3 字节，少 1 字节后解码出乱码或整字消失。
    #   实测服务器「药抗小分队」显示成「抗小分队」就是这个原因。
    #
    #   这个 bug 藏得很深：map / folder / game / appid / 人数这些字段都是
    #   按 \0 或固定宽度往后走的，错位 1 字节后它们**碰巧还能读对**
    #   （因为名字和地图之间有个 \0，多跳的字节被那个 \0 吃掉了），
    #   所以只有「名字第一字消失」这一个看得见的症状。
    pos = 5
    protocol = data[pos]
    pos += 1
    name_b, pos = _cstr(data, pos)
    map_b, pos = _cstr(data, pos)
    folder_b, pos = _cstr(data, pos)
    game_b, pos = _cstr(data, pos)
    appid = struct.unpack("<h", data[pos:pos + 2])[0]
    pos += 2
    players, max_players, bots = data[pos], data[pos + 1], data[pos + 2]
    pos += 3
    server_type = chr(data[pos])
    env = chr(data[pos + 1])
    visibility = data[pos + 2]
    vac = data[pos + 3]
    pos += 4
    version_b, pos = _cstr(data, pos)
    tags = _pick_tags(data[pos:])
    name = clean_name(name_b.decode("utf-8", "replace"))
    map_code = map_b.decode("utf-8", "replace").strip()
    mode_code, mode_label, mode_src = parse_mode(tags, name)
    return {
        "name": name, "tag": name_tag(name),
        "map": map_code, "folder": folder_b.decode("utf-8", "replace"),
        "game": game_b.decode("utf-8", "replace"), "appid": appid,
        "players": int(players), "maxPlayers": int(max_players),
        "bots": int(bots), "protocol": int(protocol),
        "serverType": "专用" if server_type == "d" else "监听",
        "os": "Windows" if env == "w" else "Linux",
        "passworded": bool(visibility), "vac": bool(vac),
        "version": clean_name(version_b.decode("utf-8", "replace")),
        "tags": tags,
        "mode": mode_code, "modeLabel": mode_label, "modeSource": mode_src,
    }


def query_players(addr: str, timeout: float = QUERY_TIMEOUT,
                  retries: int = QUERY_RETRIES) -> dict:
    """查在线玩家（A2S_PLAYERS）。失败返回 ``ok=False``。"""
    host, port = split_address(addr)
    try:
        ip = resolve_host(host)
    except ServerError as exc:
        return {"ok": False, "addr": addr, "error": str(exc), "players": []}
    last = ""
    for attempt in range(retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(_PLAYERS_REQ, (ip, port))
            data = _recv(sock, timeout)
            if data[4:5] == b"\x41":
                sock.sendto(_PLAYERS_REQ[:5] + data[5:9], (ip, port))
                data = _recv(sock, timeout)
            if data[4:5] != b"\x44":
                raise ServerError("这个服不提供玩家列表")
            players = _parse_players(data)
            return {"ok": True, "addr": addr, "players": players}
        except (OSError, ServerError, struct.error, IndexError) as exc:
            last = str(exc) or "连不上"
            time.sleep(0.2 * (attempt + 1))
        finally:
            sock.close()
    return {"ok": False, "addr": addr, "error": last, "players": []}


def _parse_players(data: bytes) -> list[dict]:
    count = data[5]
    pos = 6
    out: list[dict] = []
    for _ in range(count):
        if pos >= len(data):
            break
        pos += 1                            # index
        name_b, pos = _cstr(data, pos)
        score = struct.unpack("<l", data[pos:pos + 4])[0]
        pos += 4
        secs = struct.unpack("<f", data[pos:pos + 4])[0]
        pos += 4
        name = clean_name(name_b.decode("utf-8", "replace"))
        if not name or name == "< blank >":
            continue
        secs = int(max(0.0, secs))
        out.append({"name": name, "score": int(score), "secs": secs,
                    "timeText": _time_text(secs)})
    out.sort(key=lambda p: (p["score"], p["secs"]), reverse=True)
    return out


def _time_text(secs: int) -> str:
    if secs >= 3600:
        return f"{secs // 3600} 小时 {secs % 3600 // 60} 分"
    if secs >= 60:
        return f"{secs // 60} 分钟"
    return f"{secs} 秒"


# ---------------------------------------------------------------------------
# 唤起 Steam 连接
#
# 这一段是本轮返工的重点。上一版把所有希望押在
# `QDesktopServices.openUrl("steam://connect/ip:port")` 上，实测有这么几种
# 「点了没反应」，而且**每种都不报错**：
#
#   1. 机器上没装 Steam —— openUrl 直接返回 False，界面上什么也看不到；
#   2. 装了 Steam 但没装 550（L4D2）—— openUrl 照样返回 True，
#      Steam 收到协议后发现没有游戏可启动，静默丢掉；
#   3. **地址是域名**（`jssx.trygek.com:18931` 这类国服常用的跳板域名）——
#      Steam 的 `steam://connect/` 只吃字面 IP，吃到域名就停在
#      `ExecCommandLine:` 那一行，不报错、也不启动游戏（实测 D:\Steam\logs\console_log.txt）；
#   4. **游戏已经在跑** —— 老写法 `steam://connect/<ip>:<port>` 会被 Steam 当成
#      「又一次启动 550」，走 `WaitingPrevProcess` 然后 Completed，看起来没反应；
#      但 `steam://connect/<ip>:<port>/rungameid/550`（带 appid）**能**让已经在跑的
#      进程连过去 —— 这是用户实测指出来的（「并非打开游戏后就不能进服务器了」）。
#
# 所以正确的做法不是「把 URL 丢给系统」，而是自己把这几件事办掉：
#   * 域名先自己解析成 IP（`resolve_host`），再交给 Steam；
#   * 游戏没跑就用 `steam://connect/` 让它带 `+connect` 起来（这条路实测最稳）；
#   * 游戏在跑就优先试 `steam://connect/<ip>:<port>/rungameid/550`；
#     万一系统没交出去，才退回「把 `connect ip:port` 塞剪贴板 + 提示玩家去控制台粘」——
#     因为 Source 引擎没有外部「让运行中的进程执行命令」的口子，
#     `-applaunch 550 +connect` 也只会被 Steam 回一句 `>>> command not found: connect`。
# ---------------------------------------------------------------------------
STEAM_APPID = "550"                       # Left 4 Dead 2
_STEAM_CACHE: dict[str, Any] = {}
_GAME_EXE_NAMES = ("left4dead2.exe", "Left4Dead2.exe")


def _win_reg(path: str, name: str) -> str:
    """读一个注册表字符串值，读不到就返回空串（非 Windows 也返回空）。"""
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:                    # pragma: no cover - 只有非 Windows 会到这
        return ""
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, path) as key:
                value, _kind = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def steam_exe() -> str:
    """Steam 主程序路径；找不到就返回空串（结果缓存，免得每次点都查注册表）。"""
    cached = _STEAM_CACHE.get("exe")
    if isinstance(cached, str):
        return cached
    cands: list[str] = []
    reg_exe = _win_reg(r"Software\Valve\Steam", "SteamExe")
    if reg_exe:
        cands.append(reg_exe.replace("/", "\\"))
    for value_name in ("SteamPath", "InstallPath"):
        root = _win_reg(r"Software\Valve\Steam", value_name)
        if root:
            cands.append(os.path.join(root.replace("/", "\\"), "steam.exe"))
    install = _win_reg(r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")
    if install:
        cands.append(os.path.join(install, "steam.exe"))
    cands.extend([
        r"C:\Program Files (x86)\Steam\steam.exe",
        r"C:\Program Files\Steam\steam.exe",
    ])
    found = ""
    for path in cands:
        try:
            if path and os.path.isfile(path):
                found = path
                break
        except OSError:
            continue
    _STEAM_CACHE["exe"] = found
    return found


def _steam_libraries() -> list[str]:
    """Steam 库目录（含主目录），从 libraryfolders.vdf 里抠 path。"""
    libs: list[str] = []
    exe = steam_exe()
    if not exe:
        return libs
    root = os.path.dirname(exe)
    libs.append(root)
    vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        text = ""
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        path = match.group(1).replace("\\\\", "\\")
        if path and path not in libs:
            libs.append(path)
    return libs


def game_installed() -> bool:
    """这台机器装了《求生之路2》没有（看 appmanifest / 游戏目录）。"""
    cached = _STEAM_CACHE.get("game")
    if isinstance(cached, bool):
        return cached
    ok = False
    for lib in _steam_libraries():
        manifest = os.path.join(lib, "steamapps", f"appmanifest_{STEAM_APPID}.acf")
        folder = os.path.join(lib, "steamapps", "common", "Left 4 Dead 2",
                              "left4dead2")
        if os.path.isfile(manifest) or os.path.isdir(folder):
            ok = True
            break
    _STEAM_CACHE["game"] = ok
    return ok


def game_exe() -> str:
    """`left4dead2.exe` 的绝对路径；找不到返回空串（结果缓存）。"""
    cached = _STEAM_CACHE.get("game_exe")
    if isinstance(cached, str):
        return cached
    found = ""
    for lib in _steam_libraries():
        root = os.path.join(lib, "steamapps", "common", "Left 4 Dead 2")
        for name in _GAME_EXE_NAMES:
            path = os.path.join(root, name)
            if os.path.isfile(path):
                found = path
                break
        if found:
            break
    _STEAM_CACHE["game_exe"] = found
    return found


def game_running() -> bool:
    """游戏是不是已经在跑（tasklist 查一次，不引第三方的 psutil）。"""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq left4dead2.exe", "/NH"],
            capture_output=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "left4dead2.exe" in (out.stdout or b"").decode("mbcs", "ignore").lower()


def _open_url(url: str) -> bool:
    """交给系统壳开一个 URL，成功与否都说实话。

    `QDesktopServices.openUrl` 在 Windows 上走的是 `ShellExecute`，返回值只表示
    「壳子把请求收下了」，不代表目标程序真的起来了 —— 所以这里同时试
    `os.startfile`（shell 关联）和 `cmd /c start`，三个里有一个不炸就算发出去。
    """
    opened = False
    try:
        opened = bool(QDesktopServices.openUrl(QUrl(url)))
    except Exception:                     # noqa: BLE001 - 唤起失败不该崩界面
        opened = False
    if opened:
        return True
    try:
        os.startfile(url)                 # noqa: S606 - 就是要把 URL 交给 shell
        return True
    except OSError:
        pass
    try:
        rc = subprocess.run(
            ["cmd", "/c", "start", "", url], capture_output=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).returncode
        return rc == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _connect_target(addr: str) -> tuple[str, str]:
    """把地址整理成 Steam 认的形式：``(给蒸汽的 ip:port, 报错)``。

    Steam 的 `steam://connect/` **只吃字面 IP**，域名要自己解析（实测见文件头注释）。
    解析不了就退回原样的地址，让玩家至少能从提示里看出是哪个域名。
    """
    host, port = split_address(addr)
    if host and not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
        try:
            ip = resolve_host(host)
        except ServerError:
            return addr, f"域名 {host} 解析不了，检查一下网络或换个地址"
        return f"{ip}:{port}", ""
    return addr, ""


# weight 是按「排序权重」排的，其他三个是看实时数据排
SORT_MODES = ("weight", "players", "ping", "name")
DEFAULT_WEIGHT = 0


class ServerManager(QObject):
    """服务器列表 + 实时状态。

    每台服务器存 ``{addr, name, weight, panels}``：
    ``addr`` 规范化后小写；``name`` 是用户自己起的名字；``weight`` 是排序权重
    （大的排前面）；``panels`` 是 ``[{url, pw}]``，``pw`` 是 DPAPI 加密后的密文，
    解不开就当没存过（换电脑/换账户时不会炸）。
    """

    serversChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    serverUpdated = Signal("QVariantMap")
    playersLoaded = Signal("QVariantMap")

    def __init__(self, core) -> None:
        super().__init__(core)
        self.core = core
        self.config = core.config
        self._live: dict[str, dict] = {}
        # ---- 好友在玩 ----
        # _friends_map  {addr: [好友...]}        —— 有服务器地址的
        # _friends_l4d2 全部在玩 L4D2 的好友       —— 含没共享地址的
        # 这几项只由 refreshFriends() 在后台线程里写，读接口只读内存。
        self._friends_map: dict[str, list[dict]] = {}
        self._friends_l4d2: list[dict] = []
        self._friends_ok = False
        self._friends_err = ""
        self._friends_me = ""
        self._friends_at = 0.0
        self._busy = False
        self._status = ""
        self._lock = threading.Lock()
        self._closed = False
        self._sort = str(self.config["servers_sort"] or "weight")
        if self._sort not in SORT_MODES:
            self._sort = "weight"
        # 当前选中的合集（界面切换时写进来）。分类条的数字要跟着它走，
        # 否则会出现「分类上写 5、点进去 0 个」。
        self._group_key = "all"
        # 剪贴板监听：记住「上次看过的那段文字」，同一段只问一次
        self._clip_seen = ""
        self._clip_enabled = True
        # ---- 剪贴板检测的状态（见 scanClipboard / watch_clipboard）----
        # _clip_seq          剪贴板真的被复制过多少次（QClipboard.dataChanged 计数）
        # _clip_seen_seq     已经处理过的计数（问过 / 用户点了不用）
        # _clip_baseline     上一次看到的文字（没收到事件时用来兜底比较）
        # _clip_baseline_done 第一次调用只记基线，不算「新复制」
        self._clip_seq = 0
        self._clip_seen_seq = 0
        self._clip_baseline = ""
        self._clip_baseline_done = False
        self._clip_watcher = None
        self._clip_self_writes = 0
        self._clip_ignore_until = 0.0
        self._clip_lock = threading.Lock()
        # 端口遍历状态（同一时间只允许跑一个）
        self._scan_running = False
        self._scan_cancel = False
        _load_map_cache()

    # ---------------------------------------------------------------- 数据
    def _favorites(self) -> list[dict]:
        raw = self.config["servers"]
        out: list[dict] = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                addr = str(item.get("addr") or "").strip().lower()
                if not addr:
                    continue
                # 老版本只存了 note，这里顺手兼容一下
                name = str(item.get("name") or item.get("note") or "").strip()
                try:
                    weight = int(item.get("weight") or 0)
                except (TypeError, ValueError):
                    weight = 0
                panels: list[dict] = []
                raw_panels = item.get("panels")
                if isinstance(raw_panels, list):
                    for p in raw_panels:
                        if not isinstance(p, dict):
                            continue
                        url = str(p.get("url") or "").strip()
                        if not url:
                            continue
                        panels.append({"url": url, "pw": str(p.get("pw") or "")})
                out.append({"addr": addr, "name": name, "weight": weight,
                            "panels": panels})
        return out

    def _save_favorites(self, rows: list[dict]) -> None:
        self.config["servers"] = [
            {"addr": r["addr"],
             "name": r.get("name") or "",
             "weight": int(r.get("weight") or 0),
             "panels": [{"url": p["url"], "pw": p.get("pw") or ""}
                        for p in (r.get("panels") or [])]}
            for r in rows
        ]
        self.config.save()

    def _merged(self) -> list[dict]:
        rows: list[dict] = []
        # 好友在玩的服务器：{addr: [好友...]}。取不到就是空 dict，不影响列表。
        fmap = self._friends_by_addr()
        for fav in self._favorites():
            live = self._live.get(fav["addr"]) or {}
            panels = fav.get("panels") or []
            pals = fmap.get(fav["addr"]) or []
            rows.append({
                "addr": fav["addr"],
                "name": fav["name"],
                "note": fav["name"],            # 老界面用它当标题，留着
                "weight": fav["weight"],
                "panelCount": len(panels),
                "panelUrls": [p["url"] for p in panels],
                "hasPassword": any(bool(p.get("pw")) for p in panels),
                "state": live.get("state", "idle"),
                "liveName": live.get("name", ""),
                "tag": live.get("tag", ""),
                "map": live.get("map", ""),
                "mapName": live.get("mapName", ""),
                "mapTitle": live.get("mapTitle", ""),
                "chapter": live.get("chapter", ""),
                "mode": live.get("mode", ""),
                "modeLabel": live.get("modeLabel", "未知"),
                "modeSource": live.get("modeSource", ""),
                # ---- 好友信息 ----
                # friends: 正在这台服务器上玩的好友昵称列表
                # fromFriend: 这条是不是「因为好友在玩才加进来的」（非收藏）
                "friends": [p["name"] for p in pals],
                # friendAvatars: 和 friends **一一对应**的头像文件路径
                #   （空串 = 这个好友还没抓到，界面画占位）。
                #   ★ 用 list 而不是 map：好友重名很常见（Steam 昵称不唯一），
                #     按名字建 map 会把两个不同的人合成一个。
                "friendAvatars": [str(p.get("avatarPath") or "") for p in pals],
                "friendCount": len(pals),
                "fromFriend": False,
                # 自动分类：先按「名字里的提示词」归类，猜不出再借 mode 的结论。
                # ★ 这两套词表本来是分开的（`SERVER_CATEGORIES` vs `NAME_MODES`），
                #   于是会出现「卡片上写着战役、分类条里却是其他」的自相矛盾
                #   （用户报的「明明是战役服却在其他里」）。现在加一条兜底：
                #   名字猜不出来时，用 `parse_mode()` 已经算好的 mode 去映射分类。
                "category": (server_category(
                    fav.get("name") or live.get("name", "")) or
                    category_key_for_mode(live.get("mode", "")) or "other"),
                # 所属「系列」组名（同前缀 / 同 IP 的一组），空串 = 不归组
                "group": server_group(
                    fav["addr"], fav.get("name") or live.get("name", "")),
                "players": int(live.get("players") or 0),
                "maxPlayers": int(live.get("maxPlayers") or 0),
                "bots": int(live.get("bots") or 0),
                "ms": int(live.get("ms") or 0),
                "version": live.get("version", ""),
                "vac": bool(live.get("vac")),
                "passworded": bool(live.get("passworded")),
                "error": live.get("error", ""),
                "checkedText": live.get("checkedText", ""),
            })

        # ---- 好友在玩、但还没收藏的服务器，补成额外条目 ----
        # 这些不是用户收藏的，所以单独标 fromFriend=True，界面上可以据此区分
        # （比如不给「删除」按钮、排序时归到好友那组）。
        known = {r["addr"] for r in rows}
        for addr, pals in fmap.items():
            if addr in known:
                continue
            live = self._live.get(addr) or {}
            rows.append({
                "addr": addr,
                "name": "",
                "note": "",
                "weight": 0,
                "panelCount": 0,
                "panelUrls": [],
                "hasPassword": False,
                "state": live.get("state", "idle"),
                "liveName": live.get("name", ""),
                "tag": live.get("tag", ""),
                "map": live.get("map", ""),
                "mapName": live.get("mapName", ""),
                "mapTitle": live.get("mapTitle", ""),
                "chapter": live.get("chapter", ""),
                "mode": live.get("mode", ""),
                "modeLabel": live.get("modeLabel", "未知"),
                "modeSource": live.get("modeSource", ""),
                "friends": [p["name"] for p in pals],
                "friendAvatars": [str(p.get("avatarPath") or "") for p in pals],
                "friendCount": len(pals),
                "fromFriend": True,
                "category": (server_category(live.get("name", "")) or
                             category_key_for_mode(live.get("mode", "")) or "other"),
                "group": FRIEND_GROUP_KEY,
                "players": int(live.get("players") or 0),
                "maxPlayers": int(live.get("maxPlayers") or 0),
                "bots": int(live.get("bots") or 0),
                "ms": int(live.get("ms") or 0),
                "version": live.get("version", ""),
                "vac": bool(live.get("vac")),
                "passworded": bool(live.get("passworded")),
                "error": live.get("error", ""),
                "checkedText": live.get("checkedText", ""),
            })
        key = {
            "weight": lambda r: (-r["weight"], -r["players"], r["addr"]),
            "players": lambda r: (-r["players"], r["ms"] or 9999),
            "ping": lambda r: (r["ms"] or 9999, -r["players"]),
            # 名字用**自然排序**：黑喵1 → 黑喵2 → … → 黑喵10（不是 1 → 10 → 2）
            "name": _sort_key_name,
        }.get(self._sort)
        if key:
            rows.sort(key=key)
        return rows

    # -------------------------------------------------------------- 属性
    @Property("QVariantList", notify=serversChanged)
    def servers(self) -> list:
        return self._merged()

    @Property(int, notify=serversChanged)
    def serverCount(self) -> int:
        return len(self._favorites())

    @Property(int, notify=serversChanged)
    def onlineCount(self) -> int:
        return sum(1 for r in self._merged() if r["state"] == "online")

    @Property(int, notify=serversChanged)
    def totalPlayers(self) -> int:
        return sum(r["players"] for r in self._merged() if r["state"] == "online")

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status

    @Property(bool, notify=serversChanged)
    def scanRunning(self) -> bool:
        """端口遍历是不是正在跑（界面关/开弹窗时用它判断要不要收尾）。"""
        return bool(self._scan_running)

    @Property(str, notify=serversChanged)
    def sortMode(self) -> str:
        return self._sort

    # -------------------------------------------------------------- 自建合集
    def _collections(self) -> list[dict]:
        """读用户自建的合集（过滤掉形状不对的脏数据）。

        ★ 为什么用 try/except 而不是 `self.config["..."]` 直接取：
          `Config.__getitem__` 会回退到 DEFAULT_CONFIG，所以正常情况是安全的；
          但**测试里的桩 config 是普通 dict**，`friends_test` 就因此抛过
          KeyError，把 `groups` 整个炸掉（表现成服务器页白屏）。
          这里对「键不存在」宽容一点：没有就是没有自建合集。
        """
        try:
            raw = self.config["server_collections"]
        except (KeyError, TypeError):
            return []
        if not isinstance(raw, list):
            return []
        out: list[dict] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or "").strip()
            label = str(item.get("label") or "").strip()[:COLLECTION_LABEL_MAX]
            if not cid or not label or cid in seen:
                continue
            seen.add(cid)
            addrs: list[str] = []
            for a in (item.get("addrs") or []):
                s = str(a or "").strip()
                if s and s not in addrs:
                    addrs.append(s)
            out.append({"id": cid, "label": label, "addrs": addrs})
        return out

    def _save_collections(self, cols: list[dict]) -> None:
        self.config["server_collections"] = cols
        self.config.save()
        self.serversChanged.emit()

    @staticmethod
    def _new_collection_id(cols: list[dict]) -> str:
        """造一个不和现有撞车的短 id（存进 key 里，所以只要稳定唯一即可）。"""
        existing = {str(c.get("id") or "") for c in cols}
        import secrets
        for _ in range(50):
            cid = secrets.token_hex(4)
            if cid not in existing:
                return cid
        return str(len(existing) + 1)

    @Property("QVariantList", notify=serversChanged)
    def collections(self) -> list:
        """给界面用的自建合集列表（带每台的实时状态，便于预览）。"""
        rows = {str(r.get("addr") or ""): r for r in self._merged()}
        out: list[dict] = []
        for c in self._collections():
            live = [rows[a] for a in c["addrs"] if a in rows]
            out.append({
                "id": c["id"],
                "key": COLLECTION_KEY_PREFIX + c["id"],
                "label": c["label"],
                "count": len(live),
                "online": sum(1 for r in live if r.get("state") == "online"),
                "addrs": [str(r.get("addr") or "") for r in live],
            })
        return out

    @Slot(str, result="QVariantMap")
    def createCollection(self, label: str) -> dict:
        """新建一个空合集。"""
        name = str(label or "").strip()[:COLLECTION_LABEL_MAX]
        if not name:
            return {"ok": False, "error": "合集名不能为空"}
        cols = self._collections()
        if len(cols) >= COLLECTION_MAX:
            return {"ok": False, "error": f"最多 {COLLECTION_MAX} 个合集"}
        # 同名不让建：界面上两个「我的常用服」根本分不清谁是谁
        if any(c["label"] == name for c in cols):
            return {"ok": False, "error": f"已经有叫「{name}」的合集了"}
        cid = self._new_collection_id(cols)
        cols.append({"id": cid, "label": name, "addrs": []})
        self._save_collections(cols)
        self._set_status(f"已新建合集「{name}」")
        self._toast(f"已新建合集「{name}」", "ok")
        return {"ok": True, "id": cid, "key": COLLECTION_KEY_PREFIX + cid,
                "label": name, "error": ""}

    @Slot(str, str, result="QVariantMap")
    def renameCollection(self, collection_id: str, label: str) -> dict:
        name = str(label or "").strip()[:COLLECTION_LABEL_MAX]
        if not name:
            return {"ok": False, "error": "合集名不能为空"}
        cols = self._collections()
        cid = str(collection_id or "").strip()
        target = next((c for c in cols if c["id"] == cid), None)
        if target is None:
            return {"ok": False, "error": "找不到这个合集"}
        if any(c["label"] == name and c["id"] != cid for c in cols):
            return {"ok": False, "error": f"已经有叫「{name}」的合集了"}
        old = target["label"]
        target["label"] = name
        self._save_collections(cols)
        self._set_status(f"合集「{old}」已改名为「{name}」")
        self._toast(f"已改名为「{name}」", "ok")
        return {"ok": True, "label": name, "error": ""}

    @Slot(str, result="QVariantMap")
    def deleteCollection(self, collection_id: str) -> dict:
        """删合集（**只删归类，不删服务器**）。

        ★ 这一点必须明确：用户点「删除合集」时多半只是想拆掉这个分组，
          里面的服务器还得留着。所以这里只把合集条目去掉。
        """
        cols = self._collections()
        cid = str(collection_id or "").strip()
        target = next((c for c in cols if c["id"] == cid), None)
        if target is None:
            return {"ok": False, "error": "找不到这个合集"}
        cols = [c for c in cols if c["id"] != cid]
        self._save_collections(cols)
        msg = f"已删除合集「{target['label']}」（服务器还在，只是不再归类）"
        self._set_status(msg)
        self._toast(msg, "info")
        return {"ok": True, "label": target["label"], "error": ""}

    @Slot("QVariantList", str, result="QVariantMap")
    def moveToCollection(self, addrs: list, collection_id: str) -> dict:
        """把服务器**转移**到某个自建合集里。

        `collection_id` 为空串 = 移出所有自建合集（回到自动归类）。
        ★ 「转移」的语义：从**其它**自建合集里摘掉，再放进目标合集。
          一台服务器同时出现在两个自建合集里没有意义，只会让人重复操作。
        """
        picked = []
        for a in (addrs or []):
            s = str(a or "").strip()
            if s and s not in picked:
                picked.append(s)
        if not picked:
            return {"ok": False, "error": "没有选中服务器"}

        cols = self._collections()
        cid = str(collection_id or "").strip()
        target = None
        if cid:
            target = next((c for c in cols if c["id"] == cid), None)
            if target is None:
                return {"ok": False, "error": "找不到这个合集"}

        # 先从所有合集里摘掉（含目标，去重靠这一步）
        for c in cols:
            c["addrs"] = [a for a in c["addrs"] if a not in picked]
        if target is not None:
            target["addrs"] = list(target["addrs"]) + picked

        # 空合集不自动删：用户可能是先建好、再慢慢往里挪
        self._save_collections(cols)
        if target is not None:
            msg = f"已把 {len(picked)} 台移到「{target['label']}」"
        else:
            msg = f"已把 {len(picked)} 台移出自建合集（回到自动归类）"
        self._set_status(msg)
        self._toast(msg, "ok")
        return {"ok": True, "count": len(picked),
                "collectionId": cid, "error": ""}

    # -------------------------------------------------------------- 合集名手动覆盖
    def _group_overrides(self) -> dict:
        """读「手动改过的合集名」：``{addr: 组名}``。"""
        raw = self.config["server_group_names"]
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in raw.items():
            addr = str(k or "").strip()
            label = str(v or "").strip()
            if addr and label:
                out[addr] = label[:24]
        return out

    @Slot(str, str, result="QVariantMap")
    def renameGroup(self, group_key: str, label: str) -> dict:
        """给整个合集起个名字（自动识别不准时的兜底）。

        把组里**每一台**都记上这个名字 —— 这样以后即使成员变了、
        或者某一台单独跑到了别的组，手动名字也不会莫名其妙丢掉。
        """
        name = str(label or "").strip()[:24]
        rows = self.groups
        target = None
        for g in rows:
            if str(g.get("key") or "") == str(group_key or ""):
                target = g
                break
        if target is None:
            return {"ok": False, "error": "找不到这个合集"}
        addrs = [str(a) for a in (target.get("addrs") or [])]
        if not addrs:
            return {"ok": False, "error": "这个合集里没有服务器"}

        cur = dict(self._group_overrides())
        if name:
            for a in addrs:
                cur[a] = name
        else:
            # 空名字 = 撤销手动命名，回到自动识别
            for a in addrs:
                cur.pop(a, None)
        self.config["server_group_names"] = cur
        self.config.save()
        self.serversChanged.emit()
        msg = f"合集已重命名为「{name}」" if name else "已恢复自动识别的合集名"
        self._set_status(msg)
        self._toast(msg, "ok" if name else "info")
        return {"ok": True, "label": name, "count": len(addrs), "error": ""}

    @Property("QVariantList", notify=serversChanged)
    def groups(self) -> list:
        """当前列表里的「合集」，给界面的合集选择器用。

        每项：``{key, label, count, addrs, kind, host}``。
        头部固定带两项：
          · ``key="all"``   全部服务器
          · ``key="none"``  未分类（凑不成 2 台的散服）
        这样选择器里永远是「全部 / 未分类 / 各合集」，用户不用猜。
        """
        rows = self._merged()
        auto = group_servers(rows, self._group_overrides())
        # ★ 自建合集并进来：已经被用户收进自建合集的服务器，
        #   不再同时出现在自动合集里（否则同一台在两个合集下都有，
        #   勾选/删除时会让人犯迷糊）。
        groups = apply_collections(auto, rows, self._collections())
        in_group: set[str] = set()
        for g in groups:
            in_group.update(g.get("addrs") or [])
        loose = [str(r["addr"]) for r in rows
                 if str(r.get("addr") or "") and str(r["addr"]) not in in_group]

        out = [{"key": "all", "label": "全部服务器", "kind": "all",
                "count": len(rows), "addrs": [str(r["addr"]) for r in rows]}]
        # 「好友在玩」排在「全部」后面、其它合集前面 —— 它是**临时的**，
        # 好友一退出就没了，所以永远放显眼位置，且只在这一组非空时出现。
        friend_rows = [r for r in rows if r.get("fromFriend") or r.get("friendCount")]
        if friend_rows:
            out.append({"key": FRIEND_GROUP_KEY, "label": FRIEND_GROUP_LABEL,
                        "kind": "friends", "count": len(friend_rows),
                        "addrs": [str(r["addr"]) for r in friend_rows]})
        if loose:
            out.append({"key": "none", "label": "未分类", "kind": "none",
                        "count": len(loose), "addrs": loose})
        out.extend(groups)
        return out

    @Property("QVariantList", notify=serversChanged)
    def categories(self) -> list:
        """分类条：只统计**当前合集里**的服务器。

        ★ 用户报的「点进合集，分类的数字还在、但点进去一个都没有」：
          以前这里恒按**全部**服务器统计，而列表又按合集过滤过 ——
          两个数是两套来源，于是分类条上写「战役 5」，点进去列表空。
          现在按当前选中的合集算，数字和列表永远一致。

        `groupKey` 由界面写进来（"all" = 不限制）。
        每项：{key, label, count}
        """
        rows = self._merged()
        rows = self._rows_in_group(rows, getattr(self, "_group_key", "all"))
        counts: dict[str, int] = {}
        for r in rows:
            k = r.get("category") or "other"
            counts[k] = counts.get(k, 0) + 1
        out = [{"key": "all", "label": "全部分类", "count": len(rows)}]
        # 按 SERVER_CATEGORIES 的定义顺序摆，最后才是「其他」
        for key, _label, _w in SERVER_CATEGORIES:
            if counts.get(key):
                out.append({"key": key,
                            "label": SERVER_CATEGORY_LABELS.get(key, key),
                            "count": counts[key]})
        if counts.get("other"):
            out.append({"key": "other", "label": "其他", "count": counts["other"]})
        return out

    def _friends_by_addr(self) -> dict[str, list[dict]]:
        """好友正在玩的服务器：``{addr: [好友...]}``。

        ★ 这里有**一道刻意的取舍**：好友状态要走本机 Steam 的 IPC，
          慢的时候能卡一两秒。列表是每次 serversChanged 都会被重算的，
          如果每次都同步去读，界面会一阵一阵地顿。
          所以：
            · 结果在 `steamfriends` 里带 60 秒缓存，这里再叠一层 `_friends_map`；
            · 刷新由 `refreshFriends()` 在后台线程里做（见 core 里的定时器）；
            · 这个函数只读内存，**绝不发起网络/IPC 调用**。
        """
        return dict(getattr(self, "_friends_map", {}) or {})

    def _friends_addr_list(self) -> list[str]:
        """好友在玩、但还没收藏的服务器地址（刷新时要一起查）。"""
        known = {str(r.get("addr") or "").lower() for r in self._favorites()}
        out: list[str] = []
        for addr in self._friends_by_addr():
            a = str(addr or "").strip().lower()
            if a and a not in known:
                out.append(a)
        return out

    def refreshFriends(self) -> dict:
        """后台刷新好友状态（在 worker 线程里调）。

        读成功后把 `{addr: [好友...]}` 存进 `_friends_map` 并让列表刷新；
        读失败（Steam 没开 / 缺 DLL）只记状态，不动已有数据。
        """
        try:
            fmap = SF.friends_by_addr(force=True)
            info = SF.fetch()
        except Exception as e:  # noqa: BLE001
            log(f"refreshFriends failed: {e!r}")
            return {"ok": False, "error": f"读好友失败：{type(e).__name__}",
                    "count": 0}

        with self._lock:
            self._friends_map = fmap
            self._friends_ok = bool(info.get("ok"))
            self._friends_err = str(info.get("error") or "")
            self._friends_me = str(info.get("me") or "")
            all_l4d2 = [f for f in (info.get("friends") or [])
                        if f.get("playingL4D2")]
            self._friends_l4d2 = all_l4d2
            self._friends_at = time.time()

        self.serversChanged.emit()

        # ★ 新出现的好友服务器要**主动查一次**，否则那些卡片会一直是
        #   「未查询」：地图/人数/延迟全空。用户看到的就是「好友在玩，
        #   但什么信息都没有」——这次报的问题就是它。
        #   只查「还没有有效数据」的那些，避免每 90 秒把已知的重复查一遍。
        need = []
        for addr in fmap:
            a = str(addr or "").strip().lower()
            if not a:
                continue
            live = self._live.get(a) or {}
            if live.get("state") not in ("online", "off"):
                need.append(a)
        if need:
            threading.Thread(target=self._query_friends_addrs,
                             args=(need,), daemon=True).start()

        return {"ok": True, "error": "", "count": len(all_l4d2),
                "servers": len(fmap)}

    def _query_friends_addrs(self, addrs: list[str]) -> None:
        """后台把一批「好友在玩」的地址查一遍（不碰收藏，只填 _live）。"""
        try:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                for addr, live in zip(addrs, pool.map(query_info, addrs)):
                    if self._closed:
                        return
                    if live.get("ok"):
                        label = map_label(live.get("map") or "")
                        title, chapter = split_map(label)
                        live["mapName"] = label
                        live["mapTitle"] = title
                        live["chapter"] = chapter
                        live["state"] = "online"
                    else:
                        live["state"] = "off"
                    live["checkedText"] = time.strftime(
                        "%H:%M:%S", time.localtime())
                    with self._lock:
                        self._live[addr] = live
                    self._emit(self.serverUpdated, dict(live))
            self._emit(self.serversChanged)
        except Exception as e:  # noqa: BLE001
            log(f"query friends addrs failed: {e!r}")

    @Slot(result="QVariantMap")
    def refreshFriendsNow(self) -> dict:
        """界面上的「刷新好友」按钮（同步版，会阻塞一下，按钮点了才调）。"""
        return self.refreshFriends()

    @Property("QVariantList", notify=serversChanged)
    def friendsPlaying(self) -> list:
        """正在玩 L4D2 的好友（全部，不只是有服务器地址的）。

        界面用它在「好友在玩」入口上显示人数，也用来展示「在玩但没共享地址」的人。
        """
        return [dict(f) for f in (getattr(self, "_friends_l4d2", []) or [])]

    @Property(int, notify=serversChanged)
    def friendsPlayingCount(self) -> int:
        return len(getattr(self, "_friends_l4d2", []) or [])

    @Property(bool, notify=serversChanged)
    def friendsOk(self) -> bool:
        """好友数据能不能读到（读不到时界面给一句原因，不显示空的「好友在玩」）。"""
        return bool(getattr(self, "_friends_ok", False))

    @Property(str, notify=serversChanged)
    def friendsError(self) -> str:
        return str(getattr(self, "_friends_err", "") or "")

    @Property(str, notify=serversChanged)
    def mySteamName(self) -> str:
        return str(getattr(self, "_friends_me", "") or "")

    def _rows_in_group(self, rows: list, group_key: str) -> list:
        """按合集过滤行（和界面上的 `filterByGroup` 同一套语义）。"""
        key = str(group_key or "all")
        if key == "all":
            return rows
        # 「好友在玩」不是自动合集，它按 friendCount 判断
        if key == FRIEND_GROUP_KEY:
            return [r for r in rows
                    if r.get("fromFriend") or r.get("friendCount")]
        # 自建合集：直接按存的地址过滤（不参与自动推断）
        if key.startswith(COLLECTION_KEY_PREFIX):
            cid = key[len(COLLECTION_KEY_PREFIX):]
            col = next((c for c in self._collections() if c["id"] == cid), None)
            if col is None:
                return rows
            wanted = set(col["addrs"])
            return [r for r in rows if str(r.get("addr") or "") in wanted]
        groups = apply_collections(group_servers(rows, self._group_overrides()),
                                   rows, self._collections())
        addrs: list[str] = []
        for g in groups:
            if str(g.get("key") or "") == key:
                addrs = [str(a) for a in (g.get("addrs") or [])]
                break
        if not addrs:
            # 合集不存在（被删空了 / 提交存了旧 key）→ 当「全部」，别显示空列表
            return rows
        wanted = set(addrs)
        return [r for r in rows if str(r.get("addr") or "") in wanted]

    @Slot(str)
    def setGroupFilter(self, group_key: str) -> None:
        """界面切换合集时告诉后端，分类条的数字才会跟着变。"""
        key = str(group_key or "all")
        if key == getattr(self, "_group_key", "all"):
            return
        self._group_key = key
        self.serversChanged.emit()

    def _set_status(self, text: str) -> None:
        self._status = text or ""
        self.statusChanged.emit()

    def _toast(self, text: str, level: str = "info") -> None:
        """动作型提示：走 Core 的浮层（服务器页没有自己的 toast 通道）。

        这里要防一手「core 已被回收」：连服可能发生在关窗的收尾阶段，
        那时候再 emit 会撞上 RuntimeError，不该让它顶到控制台上。
        """
        if not text:
            return
        core = getattr(self, "core", None)
        fn = getattr(core, "toast", None)
        if not callable(fn):
            return
        try:
            fn(text, level or "info")
        except RuntimeError:
            self._closed = True

    def _set_busy(self, value: bool) -> None:
        if self._busy != bool(value):
            self._busy = bool(value)
            self.busyChanged.emit()

    # -------------------------------------------------------------- 收藏
    def _find(self, rows: list[dict], addr: str) -> dict | None:
        target = (addr or "").strip().lower()
        for row in rows:
            if row["addr"] == target:
                return row
        return None

    @Slot(str, result="QVariantMap")
    def addServer(self, text: str) -> dict:
        """快捷收藏：只给地址（工具栏/IP 直连里顺手存下来的老路）。

        ★ 默认名不再留空：先查一次服务器，把它**自报的名字**当备注。
          以前留空 → 列表里只剩一串 IP，一堆服务器分不清谁是谁。
          查不到（离线 / 超时）才退回空串，界面仍显示地址。
        """
        try:
            addr = normalize_address(text)
        except ServerError as exc:
            return {"ok": False, "error": str(exc)}
        rows = self._favorites()
        if self._find(rows, addr):
            return {"ok": False, "addr": addr,
                    "error": "这个服务器已经在列表里了"}

        # 先问一次服务器，用它的真实名字当默认备注（查不到就算了，不阻塞）
        default_name = ""
        try:
            obs = self._query_one_sync(addr)
            if isinstance(obs, dict) and obs.get("ok"):
                default_name = str(obs.get("name") or "").strip()
        except Exception as e:  # noqa: BLE001
            log(f"addServer default name failed {addr}: {e!r}")

        rows.append({"addr": addr.lower(), "name": default_name, "weight": 0,
                     "panels": []})
        self._save_favorites(rows)
        self.serversChanged.emit()
        self._set_status(f"已添加 {addr}"
                         + (f"（{default_name}）" if default_name else ""))
        return {"ok": True, "addr": addr, "name": default_name}

    @Slot(str, result="QVariantMap")
    def saveFriendServer(self, addr: str) -> dict:
        """把「好友在玩」里那台**临时**服务器存成收藏。

        好友在玩的服务器默认只是**借用 Steam 的实时状态显示**，不进配置：
        好友一退、或换服，它就从列表里消失。这是刻意的 ——
        否则你列表里会慢慢堆满一堆「当初谁在玩来着」的死服。

        但有时候确实想留住（比如觉得这服不错），所以给一个显式动作。
        存的时候用**服务器自报的名字**当备注（查不到才退回地址），
        和「只填 IP 添加」保持一致的体验。
        """
        raw = str(addr or "").strip()
        if not raw:
            return {"ok": False, "error": "没有地址", "addr": ""}
        try:
            key = normalize_address(raw).lower()
        except ServerError as exc:
            return {"ok": False, "error": str(exc), "addr": raw}

        rows = self._favorites()
        if self._find(rows, key):
            return {"ok": False, "error": "这台已经在收藏里了", "addr": key}

        # 名字优先用**已经查到的**（列表里那张卡就在 _live 里），
        # 没有才临时问一次。这样点「收藏」几乎瞬间完成，不用等网络。
        live = self._live.get(key) or {}
        name = str(live.get("name") or "").strip()
        if not name:
            try:
                obs = self._query_one_sync(key)
                if isinstance(obs, dict) and obs.get("ok"):
                    name = str(obs.get("name") or "").strip()
            except Exception as e:  # noqa: BLE001
                log(f"saveFriendServer name lookup failed {key}: {e!r}")

        rows.append({"addr": key, "name": name[:40], "weight": 0, "panels": []})
        self._save_favorites(rows)
        self.serversChanged.emit()
        # ★ 成功后**不弹提示**：用户要求去掉「已收藏 xxx 服务器」那句。
        #   它挂在服务器页顶部（收藏数下面），每收藏一次闪一下很吵。
        #   卡片从「好友在玩」转成普通条目、星标消失，本身就是足够的反馈。
        #   失败仍然要报 —— 见上面的 return，界面会显示原因。
        return {"ok": True, "addr": key, "name": name}

    # ------------------------------------------------------- 分享 / 剪贴板
    #
    # 两条路子，目的都是「把一台服务器发给朋友」：
    #   · 分享：把地址写成一段人话（带名字和连接命令），复制走贴微信 / QQ 就行
    #   · 粘贴：反过来，从任意一段文字里把 ip:port 抠出来，问一句要不要导入
    # 后者同时给「剪贴板监听」用 —— 别人发过来一段服务器推荐，直接 import。
    #
    # ★ 抠地址的正则**故意比 normalize_address 宽松**：聊天记录里常见
    #   「1.2.3.4:27015」和「connect 1.2.3.4:27015」，但也有只写 IP 的；
    #   而「版本 1.3.2.4」这种四段数字又必须排除。所以额外要求端口在
    #   1024~65535（能对上 L4D2 的常用端口），并且不跟在字母数字点后面。
    _TEXT_ADDR_RE = re.compile(
        r"(?<![0-9A-Za-z._-])"
        r"(?P<host>\d{1,3}(?:\.\d{1,3}){3}|(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24})"
        r"(?::(?P<port>\d{2,5}))?"
        r"(?![0-9A-Za-z])"
    )

    def shareText(self, addr: str) -> str:
        """一台服务器的分享文本（纯文本，贴哪儿都能看）。"""
        rows = self._favorites()
        fav = self._find(rows, addr)
        key = (addr or "").strip().lower()
        name = (fav or {}).get("name") or ""
        live = self._live.get(key) or {}
        lines: list[str] = ["【Yumi的L4D2工具箱】求生之路2 服务器"]
        if name:
            lines.append(f"名字：{name}")
        if live.get("name"):
            lines.append(f"服务器：{live['name']}")
        lines.append(f"地址：{key}")
        if live.get("mapName") or live.get("map"):
            lines.append(f"地图：{live.get('mapName') or live.get('map')}")
        if live.get("modeLabel"):
            lines.append(f"模式：{live['modeLabel']}")
        if live.get("state") == "online":
            lines.append(
                f"状态：在线 {live.get('players', 0)}/{live.get('maxPlayers', 0)}"
                f" · {live.get('ms', 0)} ms"
            )
        lines.append(f"直连：connect {key}")
        lines.append("把这段发给我，我用「从文字导入」一键加进收藏。")
        return "\n".join(lines)

    @Slot(str, result="QVariantMap")
    def shareServer(self, addr: str) -> dict:
        """分享一台服务器：复制分享文本到剪贴板，返回文本给界面显示。"""
        key = (addr or "").strip().lower()
        if not key or self._find(self._favorites(), key) is None:
            return {"ok": False, "error": "这台服务器不在收藏里", "text": ""}
        text = self.shareText(key)
        if not self._clipboard(text):
            return {"ok": False, "error": "复制失败了，手动抄一下吧", "text": text}
        self._set_status("分享文本已复制")
        self._toast("分享文本已复制，直接贴给朋友就行", "ok")
        return {"ok": True, "text": text, "error": ""}

    # 没写端口时，光凭「四段数字」认不出是服务器还是版本号（`1.3.2.4` 也像 IP），
    # 所以要求它附近出现这些字眼才算数。窗口取前后 16 个字符。
    _ADDR_HINT_WORDS = (
        "connect", "服务器", "伺服", "地址", "ip", "端口", "联机", "加入",
        "join", "l4d2", "求生", "服",
    )
    _ADDR_HINT_SPAN = 16

    def extract_addrs(self, text: str) -> list[str]:
        """从一段文字里抠出所有服务器地址（规范化 + 去重 + 保序）。"""
        raw = (text or "").strip()
        if not raw:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for m in self._TEXT_ADDR_RE.finditer(raw):
            host = m.group("host")
            port = m.group("port")
            if port is None:
                # 只写了 IP：只有「看着就是 IPv4」且附近有服务器字眼才补默认端口。
                # 纯域名（比如 github.com）一律不认 —— 不然任何一句话都能「导入」。
                if not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", host):
                    continue
                lo = max(0, m.start() - self._ADDR_HINT_SPAN)
                hi = min(len(raw), m.end() + self._ADDR_HINT_SPAN)
                near = raw[lo:hi].lower()
                if not any(w in near for w in self._ADDR_HINT_WORDS):
                    continue
                port = str(DEFAULT_PORT)
            try:
                addr = normalize_address(f"{host}:{port}")
            except ServerError:
                continue
            if addr in seen:
                continue
            seen.add(addr)
            out.append(addr)
        return out

    @Slot(str, result="QVariantMap")
    def parseShareText(self, text: str) -> dict:
        """预览「一段文字里有哪些服务器」—— 不写入，界面拿它弹确认框。"""
        addrs = self.extract_addrs(text)
        known = {r["addr"] for r in self._favorites()}
        fresh = [a for a in addrs if a not in known]
        return {"ok": True, "total": len(addrs), "fresh": len(fresh),
                "duplicate": len(addrs) - len(fresh),
                "addrs": addrs, "freshAddrs": fresh, "error": ""}

    @Slot(str, result="QVariantMap")
    def importFromText(self, text: str) -> dict:
        """把一段文字里的服务器**全部**加进收藏（重复地址跳过）。"""
        info = self.parseShareText(text)
        fresh = list(info.get("freshAddrs") or [])
        if not fresh:
            msg = ("这段文字里没找到服务器地址" if info["total"] == 0
                   else "这些服务器都已经在收藏里了")
            return {"ok": False, "added": 0, "skipped": info["duplicate"],
                    "error": msg, "addrs": info["addrs"]}
        rows = self._favorites()
        for addr in fresh:
            rows.append({"addr": addr, "name": "", "weight": 0, "panels": []})
        self._save_favorites(rows)
        self.serversChanged.emit()
        msg = f"从文字导入了 {len(fresh)} 台服务器"
        if info["duplicate"]:
            msg += f"，{info['duplicate']} 台已存在跳过"
        self._set_status(msg)
        self._toast(msg, "ok")
        self.refreshAll()
        return {"ok": True, "added": len(fresh), "skipped": info["duplicate"],
                "error": "", "addrs": fresh}

    @Slot(result="QVariantMap")
    def scanClipboard(self) -> dict:
        """看一眼剪贴板里有没有服务器地址（只读，绝不改剪贴板内容）。

        ``changed`` = 「打从程序起来（或上次问过）之后，剪贴板真的换过内容」。
        界面据此决定要不要弹询问框。

        ★ 这里的判定分两件事，缺一件就会变成「每次开软件都弹」：
          1. **程序启动时的剪贴板是旧内容** —— 第一次调用只把当前内容记成基线
             （``_clip_baseline``），一律 ``changed=False``。用户开软件之前复制的
             东西，不该被当成「刚复制了一个服务器」。
          2. **要真的是新复制** —— 靠 QClipboard 的 ``dataChanged`` 事件
             （见 ``watch_clipboard``）。只要用户复制了新东西（哪怕内容和上次
             一模一样）就会打一个 ``_clip_seq`` 戳；``_clip_seq`` 变了才算换过。

        只比较文字内容是不够的：先复制 A、再复制 B、又复制回 A，
        内容「和上次一样」但确实是新的一次复制，那种也该问。
        """
        text = ""
        try:
            from PySide6.QtGui import QGuiApplication

            board = QGuiApplication.clipboard()
            if board is not None:
                text = board.text() or ""
        except Exception:                    # noqa: BLE001 - 剪贴板不该崩界面
            text = ""
        text = text.strip()
        # 剪贴板里的东西可能很长（一整篇文章），只看前 4000 字，够用了
        digest = text[:4000]

        # 第一次调用 = 程序刚起来：只记基线，不认为「有新内容」
        if not self._clip_baseline_done:
            self._clip_baseline_done = True
            self._clip_baseline = digest
            self._clip_seen_seq = self._clip_seq
            return self._clip_result(digest, False, self.parseShareText(digest))

        # 有 dataChanged 事件就要以它为准：没有新事件 = 剪贴板没被动过
        fresh_copy = self._clip_seq != self._clip_seen_seq
        if not fresh_copy and self._clip_seq == 0:
            # 极端情况：系统没给 dataChanged（某些环境/远程桌面），
            # 退化成「内容变了才算」，至少不会每次焦点都弹
            fresh_copy = digest != self._clip_baseline
        self._clip_seen_seq = self._clip_seq
        self._clip_baseline = digest
        return self._clip_result(digest, bool(fresh_copy), self.parseShareText(digest))

    def _clip_result(self, text: str, changed: bool, info: dict) -> dict:
        out = dict(info)
        out.update({"changed": bool(changed), "text": (text or "")[:4000]})
        return out

    def watch_clipboard(self) -> None:
        """挂上 QClipboard.dataChanged，并**立刻**把当前剪贴板记成基线。

        必须在**主线程**调（QClipboard 是 GUI 线程的对象），main.py 在窗口
        建好之后调用一次。挂不上（没有剪贴板 / 没 GUI）也不影响别的功能，
        ``scanClipboard`` 会退化到「比较内容」那条路。

        ★ 基线必须在这里就建立，不能等第一次 scanClipboard。
          以前是「第一次查询时才记基线」，于是有个致命窗口期：
          窗口起来后用户先复制了一段服务器地址、程序才第一次查剪贴板 ——
          那次复制会被当成「启动时的旧内容」吞掉，用户切回来什么都不弹。
        """
        if self._clip_watcher is not None:
            return
        try:
            from PySide6.QtGui import QGuiApplication

            board = QGuiApplication.clipboard()
            if board is None:
                return
            # 先记基线（此刻剪贴板里的东西 = 程序启动前就有的，不算新复制）
            try:
                self._clip_baseline = (board.text() or "").strip()[:4000]
            except Exception:                # noqa: BLE001
                self._clip_baseline = ""
            self._clip_baseline_done = True
            self._clip_seen_seq = self._clip_seq
            # ★ 启动宽限期：Windows 上程序刚起来时，Qt / 系统会自己抛一次
            #   dataChanged（剪贴板所有权交接、格式探测都会触发），内容就是
            #   启动前那段文字。不挡住的话，程序一启动就把旧剪贴板当成
            #   「用户刚复制的」—— 又变回「每次开软件都弹」。
            self._clip_ignore_until = time.monotonic() + CLIP_STARTUP_GRACE
            board.dataChanged.connect(self._on_clipboard_changed)
            self._clip_watcher = board
        except Exception:                    # noqa: BLE001 - 监听失败不该崩程序
            self._clip_watcher = None

    def _on_clipboard_changed(self) -> None:
        with self._clip_lock:
            if self._clip_self_writes > 0:
                # 这次是本程序自己 setText 触发的（分享 / 复制地址 / 复制命令），
                # 不算「用户复制了新内容」。
                self._clip_self_writes -= 1
                return
            if time.monotonic() < self._clip_ignore_until:
                # 启动宽限期内的事件一律不算（见 watch_clipboard 里的说明）
                return
            self._clip_seq += 1

    @Slot()
    def resetClipboardSeen(self) -> None:
        """忘掉「上次看过的剪贴板」—— 关掉监听 / 用户点了「不用」之后调。"""
        with self._clip_lock:
            self._clip_baseline = ""
            self._clip_baseline_done = False
            self._clip_seen_seq = self._clip_seq

    @Slot()
    def noteClipboardHandled(self) -> None:
        """用户已经处理过当前这段剪贴板（点了「不用」/「一键导入」）。

        只把「已看过的事件计数」对齐到当前值 —— 下次还是同一段内容、
        没有新的复制动作，就不会再问。
        """
        with self._clip_lock:
            self._clip_seen_seq = self._clip_seq

    # --------------------------------------------------- 批量添加 / 端口遍历
    #
    # 两个功能，共用一套「先试通、再落库」的逻辑：
    #
    #   1. 批量添加：一段文字里的所有地址一次加完（复用 extract_addrs）
    #   2. 端口遍历：给一个 IP 和端口范围（如 27000~27100），逐个 UDP 试活，
    #      只把**真的有回应**的留下来，可以一键全存。
    #
    # 为什么要「试活」而不是直接存：一个 IP 段的端口扫下来可能几百个地址，
    # 全塞进收藏夹就废了。只有 A2S 有回应的才值得存。
    #
    # 并发：UDP 查询是 IO，用线程池。但**不能开太大**：
    #   · 对目标服务器不礼貌（等于小规模扫描）
    #   · 家用路由器/防火墙容易被触发限速，反而全部超时
    # 8 个并发 + 每个 1.2 秒超时，100 个端口大约 15 秒扫完，比较稳。
    SCAN_WORKERS = 8
    SCAN_TIMEOUT = 1.2
    SCAN_MAX_PORTS = 1000

    scanProgress = Signal(int, int, str)   # 已完成 / 总数 / 当前地址
    scanFinished = Signal("QVariantList")

    @Slot(str, int, int, result="QVariantMap")
    def scanPortRange(self, host: str, start_port: int, end_port: int) -> dict:
        """遍历 host 的 [start_port, end_port]，返回**有回应**的服务器列表。

        结果通过 `scanFinished(list)` 信号异步送出；这个槽只负责启动。
        `scanProgress(done, total, addr)` 用来更新进度条。

        ★ host 里如果带端口（用户直接粘 `1.1.1.1:25000`），会自动拆开：
          IP 用 `1.1.1.1`，起始端口用 `25000`、结束端口 `25099`（+99）。
          这样用户从聊天记录里复制一整条地址粘进来就能直接扫，不用手动拆。
          用户显式改过的起止端口以参数为准（见返回值里的 adjusted 标记）。
        """
        if self._scan_running:
            return {"ok": False, "error": "上一次扫描还没结束", "total": 0}
        host = str(host or "").strip()
        end_port = int(end_port) if str(end_port).strip() else 0
        start_port = int(start_port) if str(start_port).strip() else 0

        # 拆「IP:端口」：粘贴进来的写法五花八门，宽松一点
        paste_port = 0
        for prefix in ("steam://connect/", "steam://", "connect "):
            if host.lower().startswith(prefix):
                host = host[len(prefix):].strip()
                break
        host = host.replace("\\", "/").split("/")[0].strip()
        if host.count(":") == 1:
            maybe_host, maybe_port = host.split(":", 1)
            if maybe_port.strip().isdigit():
                paste_port = int(maybe_port.strip())
                host = maybe_host.strip()

        if not valid_host(host):
            return {"ok": False, "error": "IP / 域名不合法", "total": 0}

        adjusted = False
        if paste_port:
            # 粘的是「IP:端口」→ 从这个端口开始扫 100 个
            start_port = paste_port
            end_port = paste_port + 99
            adjusted = True

        try:
            lo = max(1, int(start_port or DEFAULT_PORT))
            hi = min(65535, int(end_port or (lo + 99)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "端口不是数字", "total": 0}
        if lo > hi:
            lo, hi = hi, lo
        count = hi - lo + 1
        if count > self.SCAN_MAX_PORTS:
            return {"ok": False,
                    "error": f"一次最多扫 {self.SCAN_MAX_PORTS} 个端口", "total": 0}

        ports = list(range(lo, hi + 1))
        self._scan_running = True
        self._scan_cancel = False
        self._set_status(f"正在遍历 {host} 的 {count} 个端口…")

        def run() -> None:
            found: list[dict] = []
            done = 0
            try:
                def probe(port: int) -> dict | None:
                    if self._scan_cancel:
                        return None
                    addr = f"{host}:{port}"
                    try:
                        live = query_info(addr, timeout=self.SCAN_TIMEOUT)
                    except Exception:            # noqa: BLE001
                        return None
                    if not live.get("ok"):
                        return None
                    label = map_label(live.get("map") or "")
                    title, chapter = split_map(label)
                    return {
                        "addr": addr,
                        "name": clean_name(live.get("name") or ""),
                        "mapName": label,
                        "mapTitle": title,
                        "chapter": chapter,
                        "players": int(live.get("players") or 0),
                        "maxPlayers": int(live.get("maxPlayers") or 0),
                        "ms": int(live.get("ms") or 0),
                        "modeLabel": live.get("modeLabel") or "",
                    }

                with ThreadPoolExecutor(max_workers=self.SCAN_WORKERS) as pool:
                    futures = {}
                    for _p in ports:
                        # 提交过程中用户可能已经点了停止 —— 那就别再往里塞任务了
                        if self._scan_cancel:
                            break
                        futures[pool.submit(probe, _p)] = _p
                    for fut in as_completed(futures):
                        if self._scan_cancel:
                            break
                        done += 1
                        try:
                            hit = fut.result()
                        except Exception:        # noqa: BLE001
                            hit = None
                        if hit:
                            found.append(hit)
                        # 每 5 个报一次进度，别把事件循环刷爆
                        if done % 5 == 0 or done == count:
                            self._emit(self.scanProgress, done, count, hit["addr"]
                                       if hit else f"{host}:{futures[fut]}")
                found.sort(key=lambda r: (-r["players"], r["addr"]))
                if not self._scan_cancel:
                    self._set_status(
                        f"遍历完成：{len(found)}/{count} 个端口有回应")
            finally:
                # ★ 被取消时不要把 _scan_running 再翻回 False、也不要再发
                #   scanFinished：cancelScan() 已经把状态清掉并且界面可能已经
                #   开始新的一轮扫描了，这里再发一次会把新结果冲掉。
                if not self._scan_cancel:
                    self._scan_running = False
                    self._emit(self.scanFinished, found)

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "total": count, "host": host,
                "start": lo, "end": hi, "error": "",
                "adjusted": adjusted, "pastePort": paste_port}

    @Slot()
    def cancelScan(self) -> None:
        """停止正在跑的端口遍历。

        ★ 以前只是把 `_scan_cancel` 设成 True，靠工作线程自己在循环里发现。
          问题是线程池里**已经提交**的任务不会立刻停（`as_completed` 要等
          当前这批跑完），用户关掉弹窗再点进来时 `_scan_running` 还是 True，
          于是就出现「关了还在扫描、重新打开还在继续」的现象（用户报的）。

          现在改成：置取消位 + **立刻**把状态标成「没在跑」并送出当前结果，
          后台线程看到取消位后自己安静退出（它不再发 scanFinished，
          避免覆盖界面上的新结果）。
        """
        if not self._scan_running:
            return
        self._scan_cancel = True
        self._scan_running = False
        self._set_status("已停止遍历")

    @Slot("QVariantList", result="QVariantMap")
    def addMany(self, addrs: list) -> dict:
        """一次加多台（端口遍历选中的那几台 / 批量粘贴的结果）。

        `addrs` 可以是纯地址字符串数组，也可以是带 name 的字典数组
        （遍历结果就带名字，顺手把服务器自报名存成备注更好认）。
        """
        rows = self._favorites()
        known = {r["addr"] for r in rows}
        added = 0
        skipped = 0
        bad = 0
        for item in (addrs or []):
            name = ""
            raw = item
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()[:40]
                raw = item.get("addr") or ""
            try:
                addr = normalize_address(str(raw or ""))
            except ServerError:
                bad += 1
                continue
            key = addr.lower()
            if key in known:
                skipped += 1
                continue
            # 没有名字就现查一次（批量加的时候这一步要几十~几百毫秒，
            # 但换来的是列表里能认出谁是谁，值得）
            if not name:
                try:
                    obs = self._query_one_sync(key)
                    if obs.get("ok"):
                        name = str(obs.get("name") or "").strip()[:40]
                except Exception:  # noqa: BLE001
                    pass
            rows.append({"addr": key, "name": name, "weight": 0, "panels": []})
            known.add(key)
            added += 1
        if added:
            self._save_favorites(rows)
            self.serversChanged.emit()
            msg = f"添加了 {added} 台服务器"
            if skipped:
                msg += f"，{skipped} 台已存在跳过"
            if bad:
                msg += f"，{bad} 个地址不合法"
            self._set_status(msg)
            self._toast(msg, "ok")
            self.refreshAll()
        else:
            msg = "没有新的服务器可添加"
            if skipped:
                msg = f"{skipped} 台都已经在收藏里了"
            self._set_status(msg)
        return {"ok": bool(added), "added": added, "skipped": skipped,
                "bad": bad, "error": "" if added else "没有新增"}

    @Slot("QVariantMap", result="QVariantMap")
    def saveServer(self, payload: dict) -> dict:
        """添加 / 修改一台服务器（对话框用）。

        payload::

            {addr, oldAddr, name, weight, panels: [{url, password}],
             clearPassword: bool}

        * ``oldAddr`` 有值表示「改这一台」，可以顺手改地址（改错了 IP 能救回来）
        * ``password`` 留空 = 保留原来存的密码；``clearPassword`` = 全部清掉
        * 密码用 DPAPI 加密后再进 config.json
        """
        data = payload or {}
        try:
            addr = normalize_address(str(data.get("addr") or ""))
        except ServerError as exc:
            return {"ok": False, "error": str(exc)}
        key = addr.lower()
        old_raw = str(data.get("oldAddr") or "").strip()
        try:
            old_key = normalize_address(old_raw).lower() if old_raw else ""
        except ServerError:
            old_key = old_raw.lower()
        name = str(data.get("name") or "").strip()[:40]
        try:
            weight = int(data.get("weight") or 0)
        except (TypeError, ValueError):
            weight = 0
        weight = max(-9999, min(9999, weight))

        panels_in = data.get("panels")
        clear_pw = bool(data.get("clearPassword"))
        rows = self._favorites()
        cur = self._find(rows, old_key) if old_key else None
        if old_key and cur is None:
            return {"ok": False, "error": "要修改的服务器已经不在列表里了"}
        # 没给 oldAddr 但地址已经在列表里 = 「原地改这一台」。
        # 界面每次打开对话框都会带上 oldAddr，这里是给脚本/老调用留的宽容：
        # 同一个地址再存一次就是改它，不该报「已经在列表里了」。
        if cur is None:
            cur = self._find(rows, key)
        if cur is not None and key != cur["addr"] and self._find(rows, key):
            return {"ok": False, "error": "改到这个地址会和列表里另一台重复"}

        old_panels = {p["url"]: p for p in (cur.get("panels") or [])} if cur else {}
        panels: list[dict] = []
        if isinstance(panels_in, list):
            for item in panels_in:
                if not isinstance(item, dict):
                    continue
                raw_url = str(item.get("url") or "").strip()
                if not raw_url:
                    continue
                if not valid_panel_url(raw_url):
                    return {"ok": False, "error": f"面板地址看不懂：{raw_url}"}
                url = normalize_panel_url(raw_url)
                pw = "" if clear_pw else protect_secret(str(item.get("password") or ""))
                if not pw:
                    # 没填新密码：沿用原来这条地址存过的
                    prev = old_panels.get(url)
                    pw = (prev or {}).get("pw", "")
                panels.append({"url": url, "pw": pw})
        elif clear_pw:
            panels = [{"url": p["url"], "pw": ""} for p in (cur.get("panels") or [])] \
                if cur else []
        elif cur is not None:
            panels = list(cur.get("panels") or [])

        row = {"addr": key, "name": name, "weight": weight, "panels": panels}
        if cur is None:
            rows.append(row)
            action = "已添加"
        else:
            rows[rows.index(cur)] = row
            action = "已保存"
        # 地址变了：把旧地址的实时状态挪到新地址下，省得白查一遍
        if old_key and old_key != key:
            live = self._live.pop(old_key, None)
            if live:
                self._live[key] = live
        self._save_favorites(rows)
        self.serversChanged.emit()
        self._set_status(f"{action} {addr}" + (f"（{name}）" if name else ""))
        self.refreshOne(addr)
        return {"ok": True, "addr": addr}

    @Slot(str, result="QVariantMap")
    def serverDetail(self, addr: str) -> dict:
        """编辑对话框要的数据。**不返回明文密码**，只说有没有存过。"""
        row = self._find(self._favorites(), addr)
        if row is None:
            return {"ok": False, "error": "这行已经不在列表里了"}
        panels = [{"url": p["url"], "hasPassword": bool(p.get("pw"))}
                  for p in (row.get("panels") or [])]
        return {"ok": True, "addr": row["addr"], "name": row["name"],
                "weight": int(row.get("weight") or 0), "panels": panels,
                "hasPassword": any(p["hasPassword"] for p in panels)}

    @Slot(str, result="QVariantMap")
    def revealPanelPassword(self, addr: str, index: int) -> dict:
        """把某一行的面板密码解出来给界面填（只在本机、当前账户下能解开）。"""
        row = self._find(self._favorites(), addr)
        if row is None:
            return {"ok": False, "error": "这行已经不在列表里了"}
        panels = row.get("panels") or []
        if index < 0 or index >= len(panels):
            return {"ok": False, "error": "没有这个面板"}
        pw = reveal_secret(panels[index].get("pw") or "")
        if not pw:
            return {"ok": False,
                    "error": "解不开这个密码（换了电脑或系统账户就会这样），重新填一次吧"}
        return {"ok": True, "password": pw}

    @Slot(str, result="int")
    def clearPasswords(self, addr: str) -> int:
        """清掉已保存的面板密码；``addr`` 为空串就清全部。返回清了几条。"""
        rows = self._favorites()
        target = (addr or "").strip().lower()
        cleared = 0
        for row in rows:
            if target and row["addr"] != target:
                continue
            for panel in row.get("panels") or []:
                if panel.get("pw"):
                    panel["pw"] = ""
                    cleared += 1
        if cleared:
            self._save_favorites(rows)
            self.serversChanged.emit()
            self._set_status(f"已清掉 {cleared} 个面板密码")
        else:
            self._set_status("没有保存过面板密码")
        return cleared

    # ------------------------------------------------------ 配置导出 / 导入
    #
    # 用途：攒了一堆服务器想分享给朋友时，不用一个个手抄地址。
    #
    # 导出的 JSON 结构（带 `_kind` 标记，导入时用来确认「这是本程序的服务器配置」）：
    #
    #     {
    #       "_kind": "l42d.servers",
    #       "_version": 1,
    #       "exportedAt": "2026-11-17 21:30:00",
    #       "servers": [
    #         {"addr": "1.2.3.4:27015", "name": "宿舍服", "weight": 5,
    #          "panels": [{"url": "http://...", "pw": ""}]}
    #       ]
    #     }
    #
    # ★ **密码绝不导出**。面板密码是用本机 Windows 账户密钥（DPAPI）加密的，
    #   换台电脑根本解不开，导出密文只会让对方拿到一串废数据，还多一层误会。
    #   所以导出的 `pw` 一律清空，导入时也不碰对方本机已有的密码。
    #
    # ★ 槽签名必须把 addrs 也声明出来：以前只写了 `@Slot(str, ...)`，
    #   而方法实际有两个参数 —— QML 调 `exportConfig(s, picked)` 时，
    #   第二个参数会被 PySide6 **直接丢掉**，addrs 永远是默认的 None，
    #   于是「多选导出」每次都变成全量导出（用户报的那个 bug）。
    @Slot(str, "QVariantList", result="QVariantMap")
    def exportConfig(self, path: str, addrs: list | None = None) -> dict:
        """把收藏的服务器写成 JSON（**不含密码**）。``path`` 为空就报错。

        ``addrs`` 有值时只导出这些地址（多选导出用），没给就导出全部。
        **合集名一起导出**：`groupNames` 是 `{addr: 手动合集名}`，
        只包含本次导出里确实带手动名的那些地址。
        """
        target = str(path or "").strip()
        if not target:
            return {"ok": False, "error": "没有选保存位置", "count": 0}
        rows = self._favorites()
        if not rows:
            return {"ok": False, "error": "列表里还没有服务器", "count": 0}
        if addrs:
            wanted = {str(a or "").strip().lower() for a in addrs if str(a or "").strip()}
            rows = [r for r in rows if str(r.get("addr") or "").lower() in wanted]
            if not rows:
                return {"ok": False, "error": "选中的服务器都不在了", "count": 0}
        overrides = self._group_overrides()
        group_names = {str(r["addr"]): overrides[str(r["addr"])]
                       for r in rows if str(r["addr"]) in overrides}
        payload = {
            "_kind": "l42d.servers",
            "_version": 2,
            "exportedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(rows),
            # 手动改过的合集名：地址 → 名字（导入方据此还原用户的自定义分组）
            "groupNames": group_names,
            "servers": [
                {
                    "addr": r["addr"],
                    "name": r.get("name") or "",
                    "weight": int(r.get("weight") or 0),
                    # 只保留地址，密码抹掉（见上面说明）
                    "panels": [{"url": p["url"], "pw": ""}
                               for p in (r.get("panels") or [])],
                    # 顺手把「这台属于哪个合集」也写上（仅作参考，导入时以 groupNames 为准）
                    "group": overrides.get(str(r["addr"])) or "",
                }
                for r in rows
            ],
        }
        try:
            with open(target, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            msg = f"写入失败：{exc}"
            self._set_status(msg)
            self._toast(msg, "error")
            return {"ok": False, "error": msg, "count": 0}
        extra = f"，含 {len(group_names)} 个合集名" if group_names else ""
        self._set_status(f"已导出 {len(rows)} 台服务器{extra}")
        self._toast(f"已导出 {len(rows)} 台服务器（不含面板密码）{extra}", "ok")
        return {"ok": True, "count": len(rows), "path": target,
                "groups": len(group_names), "error": ""}

    @Slot(str, result="QVariantMap")
    def previewImport(self, path: str) -> dict:
        """导入前先看一眼：这个文件里有几台、几台是新的、几台重复。

        不做任何写入 —— 界面先拿这个显示「将导入 N 台（M 台已存在）」+ **具体是哪些**，
        用户确认了才真的动。

        ★ `names` 现在给**全部**新服务器（以前只给前 5 个，用户看不到全貌，
          没法确认「这真是我要的那批配置」）。每条形如
          ``「宿舍服」 1.2.3.4:27015``，带合集名的写成 ``「宿舍服」 1.2.3.4:27015 [合集名]``。
        """
        items, err = self._read_export(path)
        if err:
            return {"ok": False, "error": err, "total": 0, "fresh": 0,
                    "duplicate": 0, "names": []}
        groups = self._read_export_groups(path)
        known = {r["addr"] for r in self._favorites()}
        fresh = [it for it in items if it["addr"] not in known]

        def _label(it: dict) -> str:
            name = str(it.get("name") or "").strip()
            addr = it["addr"]
            text = (f"「{name}」 {addr}" if name else addr)
            g = str(groups.get(addr) or "").strip()
            if g:
                text += f"  [{g}]"
            return text

        # 界面最多铺 24 条（再多给它一个滚动区也读不完），剩下的只用数量说明
        show = fresh[:24]
        return {"ok": True, "total": len(items), "fresh": len(fresh),
                "duplicate": len(items) - len(fresh), "error": "",
                "names": [_label(it) for it in show],
                "more": max(0, len(fresh) - len(show)),
                "groups": len({groups.get(it["addr"]) for it in fresh
                               if groups.get(it["addr"])})}

    @Slot(str, result="QVariantMap")
    def importConfig(self, path: str) -> dict:
        """导入服务器配置。**只加不删**，重复地址跳过（保留本机已有的名字/密码）。

        ★ 现在会**连合集名一起还原**（`groupNames`）：导入后那些服务器
          仍然归在对方给它们起的合集里，不用再手动重命名一遍。
        """
        items, err = self._read_export(path)
        if err:
            self._set_status(err)
            self._toast(err, "error")
            return {"ok": False, "error": err, "added": 0, "skipped": 0}

        groups = self._read_export_groups(path)
        rows = self._favorites()
        known = {r["addr"] for r in rows}
        added = 0
        for it in items:
            addr = it["addr"]
            if addr in known:
                continue
            rows.append({"addr": addr, "name": it.get("name") or "",
                         "weight": int(it.get("weight") or 0),
                         # 对方导出的 pw 是空的；就算有也不采信（DPAPI 解不开）
                         "panels": [{"url": p["url"], "pw": ""}
                                    for p in (it.get("panels") or [])]})
            known.add(addr)
            added += 1
        # 合集名：只给「这次真的导进来的地址」补，别把本机已有服务器改名
        restored = 0
        if groups:
            cur = dict(self._group_overrides())
            for it in items:
                addr = it["addr"]
                nm = str(groups.get(addr) or "").strip()
                if nm and addr not in cur and addr in known:
                    cur[addr] = nm[:24]
                    restored += 1
            if restored:
                self.config["server_group_names"] = cur
                self.config.save()

        skipped = len(items) - added
        if added:
            self._save_favorites(rows)
            self.serversChanged.emit()
            self.refreshAll()
        msg = f"导入了 {added} 台服务器" + (f"，{skipped} 台已存在跳过" if skipped else "")
        if restored:
            msg += f"，还原了 {restored} 个合集名"
        self._set_status(msg)
        if added:
            self._toast(msg, "ok")
        elif skipped:
            self._toast(f"{skipped} 台都已经在列表里了", "info")
        else:
            self._toast("这个文件里没有服务器", "warn")
        return {"ok": bool(added) or skipped > 0, "added": added,
                "skipped": skipped, "groups": restored,
                "error": "" if added else "没有新的可导入"}

    @Slot("QVariantList", result="QVariantMap")
    def importConfigs(self, paths: list) -> dict:
        """一次导入多个 JSON（拖拽进来的那一堆文件）。

        每个文件单独处理：能用的加进收藏，坏文件跳过但**不中断**，
        最后汇总成一条提示（用户拖 5 个文件不该看到 5 条 toast）。
        """
        files = [str(p or "").strip() for p in (paths or []) if str(p or "").strip()]
        if not files:
            return {"ok": False, "added": 0, "skipped": 0, "failed": 0,
                    "error": "没有可导入的文件"}
        rows = self._favorites()
        known = {r["addr"] for r in rows}
        cur_groups = dict(self._group_overrides())
        added = 0
        skipped = 0
        groups = 0
        failed = 0
        for path in files:
            items, err = self._read_export(path)
            if err:
                failed += 1
                continue
            groups_map = self._read_export_groups(path)
            for it in items:
                addr = it["addr"]
                if addr in known:
                    skipped += 1
                    continue
                rows.append({"addr": addr, "name": it.get("name") or "",
                             "weight": int(it.get("weight") or 0),
                             "panels": [{"url": p["url"], "pw": ""}
                                        for p in (it.get("panels") or [])]})
                known.add(addr)
                added += 1
                nm = str(groups_map.get(addr) or "").strip()
                if nm and addr not in cur_groups:
                    cur_groups[addr] = nm[:24]
                    groups += 1
        if added:
            self._save_favorites(rows)
            if groups:
                self.config["server_group_names"] = cur_groups
                self.config.save()
            self.serversChanged.emit()
            self.refreshAll()

        parts = [f"导入了 {added} 台服务器"]
        if groups:
            parts.append(f"{groups} 个合集名")
        if skipped:
            parts.append(f"{skipped} 台已存在")
        if failed:
            parts.append(f"{failed} 个文件读不了")
        msg = "，".join(parts)
        self._set_status(msg)
        if added:
            self._toast(msg, "ok")
        elif failed and not skipped:
            self._toast(f"这 {failed} 个文件都不是服务器配置", "error")
        else:
            self._toast(msg, "info")
        return {"ok": added > 0, "added": added, "skipped": skipped,
                "failed": failed, "groups": groups,
                "error": "" if added else "没有新增服务器"}

    def _read_export_groups(self, path: str) -> dict:
        """读导出文件里的 `groupNames`（地址 → 手动合集名）；没有就返回空 dict。

        兼容两种写法：顶层 `groupNames` 字典，或者每台服务器自带的 `group` 字段。
        """
        try:
            with open(str(path or ""), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        out: dict[str, str] = {}
        if isinstance(data, dict):
            raw = data.get("groupNames")
            if isinstance(raw, dict):
                for k, v in raw.items():
                    addr = str(k or "").strip().lower()
                    name = str(v or "").strip()
                    if addr and name:
                        out[addr] = name[:24]
            servers = data.get("servers")
        elif isinstance(data, list):
            servers = data
        else:
            servers = None
        # 每台自带的 group 字段兜底（只补没写进 groupNames 的）
        for it in (servers or []):
            if not isinstance(it, dict):
                continue
            try:
                addr = normalize_address(str(it.get("addr") or "")).lower()
            except ServerError:
                continue
            name = str(it.get("group") or "").strip()
            if addr and name and addr not in out:
                out[addr] = name[:24]
        return out

    def _read_export(self, path: str) -> tuple[list[dict], str]:
        """读导出文件，返回 ``(服务器列表, 错误)``。地址一律规范化 + 去重。"""
        target = str(path or "").strip()
        if not target:
            return [], "没有选文件"
        try:
            with open(target, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except OSError as exc:
            return [], f"读不了这个文件：{exc}"
        except ValueError as exc:
            return [], f"不是合法的 JSON：{exc}"

        # 宽容一点：既认我们自己的结构，也认「直接一个数组」
        raw: list = []
        if isinstance(data, dict):
            kind = str(data.get("_kind") or "")
            if kind and kind != "l42d.servers":
                return [], "这不是本程序导出的服务器配置"
            raw = data.get("servers")
            if not isinstance(raw, list):
                return [], "文件里没有 servers 列表"
        elif isinstance(data, list):
            raw = data
        else:
            return [], "文件结构看不懂"

        out: list[dict] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                # 允许直接是地址字符串
                if isinstance(item, str):
                    item = {"addr": item}
                else:
                    continue
            try:
                addr = normalize_address(str(item.get("addr") or "")).lower()
            except ServerError:
                continue                    # 单条坏了跳过，别让整个文件失败
            if not addr or addr in seen:
                continue
            seen.add(addr)
            panels = []
            for p in (item.get("panels") or []):
                if not isinstance(p, dict):
                    continue
                url = str(p.get("url") or "").strip()
                if url and valid_panel_url(url):
                    panels.append({"url": normalize_panel_url(url), "pw": ""})
            out.append({"addr": addr,
                        "name": str(item.get("name") or "").strip()[:40],
                        "weight": int(item.get("weight") or 0),
                        "panels": panels})
        if not out:
            return [], "文件里没有能用的服务器地址"
        return out, ""

    @Slot(str)
    def removeServer(self, addr: str) -> None:
        target = (addr or "").strip().lower()
        rows = [r for r in self._favorites() if r["addr"] != target]
        self._save_favorites(rows)
        self._live.pop(target, None)
        self.serversChanged.emit()
        self._set_status("已移出列表")

    @Slot("QVariantList", result="QVariantMap")
    def removeMany(self, addrs: list) -> dict:
        """一次移出多台（多选删除）。返回 ``{ok, removed, error}``。"""
        targets = set()
        for a in (addrs or []):
            key = str(a or "").strip().lower()
            if key:
                targets.add(key)
        if not targets:
            return {"ok": False, "removed": 0, "error": "没有选中任何服务器"}
        rows = [r for r in self._favorites() if r["addr"] not in targets]
        removed = len(self._favorites()) - len(rows)
        if removed <= 0:
            return {"ok": False, "removed": 0, "error": "这些服务器已经不在列表里了"}
        self._save_favorites(rows)
        for key in targets:
            self._live.pop(key, None)
        self.serversChanged.emit()
        msg = f"已移出 {removed} 台服务器"
        self._set_status(msg)
        self._toast(msg, "ok")
        return {"ok": True, "removed": removed, "error": ""}

    @Slot(str, str)
    def renameServer(self, addr: str, name: str) -> None:
        rows = self._favorites()
        row = self._find(rows, addr)
        if row is None:
            return
        row["name"] = (name or "").strip()[:40]
        self._save_favorites(rows)
        self.serversChanged.emit()

    @Slot(str, int)
    def setWeight(self, addr: str, weight: int) -> None:
        rows = self._favorites()
        row = self._find(rows, addr)
        if row is None:
            return
        row["weight"] = max(-9999, min(9999, int(weight)))
        self._save_favorites(rows)
        self.serversChanged.emit()

    @Slot()
    def clearAll(self) -> None:
        self._save_favorites([])
        self._live.clear()
        self.serversChanged.emit()
        self._set_status("列表清空了")

    @Slot(str)
    def setSortMode(self, mode: str) -> None:
        if mode not in SORT_MODES or mode == self._sort:
            return
        self._sort = mode
        self.config["servers_sort"] = mode
        self.config.save()
        self.serversChanged.emit()

    # -------------------------------------------------------------- 查询
    def _query_one_sync(self, addr: str) -> dict:
        """只查一次、**不写 `_live`、不发信号**。

        给「添加服务器时取默认名」用：那一步只想知道服务器自报的名字，
        不该顺手把列表状态改掉（后面 refreshOne 会正式刷一次）。
        """
        try:
            live = query_info(addr)
        except Exception as e:  # noqa: BLE001
            log(f"query for default name failed {addr}: {e!r}")
            return {"ok": False, "error": str(e)}
        if live.get("ok"):
            label = map_label(live.get("map") or "")
            title, chapter = split_map(label)
            live["mapName"] = label
            live["mapTitle"] = title
            live["chapter"] = chapter
        return live

    def _query_one(self, addr: str, with_players: bool = False) -> dict:
        live = query_info(addr)
        if live.get("ok"):
            label = map_label(live.get("map") or "")
            title, chapter = split_map(label)
            live["mapName"] = label
            live["mapTitle"] = title
            live["chapter"] = chapter
            live["state"] = "online"
        else:
            live["state"] = "off"
        live["checkedText"] = time.strftime("%H:%M:%S", time.localtime())
        with self._lock:
            self._live[addr] = live
        self._emit(self.serverUpdated, dict(live))
        self._emit(self.serversChanged)
        return live

    # 后台线程在窗口关闭之后还可能跑完最后一步（刷新是发了就不管的），
    # 这时候 emit 会撞上「Signal source has been deleted」。
    # 包一层，退出途中丢掉就行，别在控制台打一堆假崩溃。
    def _emit(self, signal, *args) -> None:
        if self._closed:
            return
        try:
            signal.emit(*args)
        except RuntimeError:
            self._closed = True

    def shutdown(self) -> None:
        """窗口关掉时调一下，后台线程的收尾 emit 就不再做无用功。"""
        self._closed = True

    # ---------------------------------------------------------- 好友在玩
    def start_friend_watch(self) -> None:
        """起一个后台线程，每隔一阵读一次 Steam 好友状态。

        ★ 只在后台线程里读，且只在**数据真的变了**时才 emit ——
          好友列表是每 90 秒一次，但界面不该被无意义的刷新打断滚动位置。
        """
        if getattr(self, "_friend_thread", None) is not None:
            return
        self._friend_thread = threading.Thread(
            target=self._friend_loop, name="friend-watch", daemon=True)
        self._friend_thread.start()

    def _friend_loop(self) -> None:
        # 启动后先等一下：这时候主界面还在建，别抢资源
        time.sleep(6.0)
        while not self._closed:
            try:
                if self._closed:
                    break
                before = self._friends_signature()
                self.refreshFriends()
                after = self._friends_signature()
                if before != after and not self._closed:
                    # 状态真变了才刷新界面（refreshFriends 内部已 emit 过一次，
                    # 这里不动，避免重复触发打乱列表滚动）
                    pass
            except Exception as e:  # noqa: BLE001
                log(f"friend watch loop: {e!r}")
            # 分段睡，退出时能及时收尾
            for _ in range(int(FRIEND_REFRESH_SEC)):
                if self._closed:
                    return
                time.sleep(1.0)

    def _friends_signature(self) -> tuple:
        """当前好友状态的指纹（用来判断「变了没有」）。"""
        l4 = getattr(self, "_friends_l4d2", []) or []
        return tuple(sorted(
            (str(f.get("sid") or ""), str(f.get("addr") or "")) for f in l4))

    @Slot(str)
    def refreshOne(self, addr: str) -> None:
        try:
            target = normalize_address(addr).lower()
        except ServerError as exc:
            self._set_status(str(exc))
            return
        with self._lock:
            self._live[target] = {"state": "querying"}
        self.serversChanged.emit()

        def run() -> None:
            self._query_one(target)

        threading.Thread(target=run, daemon=True).start()

    @Slot()
    def refreshAll(self) -> None:
        rows = self._favorites()
        # ★ 好友在玩、但**还没收藏**的服务器也要一起查，否则那些卡片
        #   永远停在「未查询」：地图、人数、延迟全是空的 —— 而它们恰恰是
        #   用户最想知道「现在几人在玩、什么图」的那几条。
        #   （以前只查 _favorites()，好友条目根本不在查询范围内。）
        addrs = [r["addr"] for r in rows]
        for addr in self._friends_addr_list():
            if addr not in addrs:
                addrs.append(addr)
        if not addrs:
            self._set_status("先加一个服务器地址吧")
            return
        if self._busy:
            return
        for addr in addrs:
            with self._lock:
                self._live[addr] = {"state": "querying"}
        self.serversChanged.emit()
        self._set_busy(True)
        self._set_status(f"正在查询 {len(addrs)} 个服务器…")

        def run() -> None:
            ok = 0
            try:
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                    for addr, live in zip(addrs, pool.map(query_info, addrs)):
                        if live.get("ok"):
                            ok += 1
                            label = map_label(live.get("map") or "")
                            title, chapter = split_map(label)
                            live["mapName"] = label
                            live["mapTitle"] = title
                            live["chapter"] = chapter
                            live["state"] = "online"
                        else:
                            live["state"] = "off"
                        live["checkedText"] = time.strftime(
                            "%H:%M:%S", time.localtime())
                        with self._lock:
                            self._live[addr] = live
                        self._emit(self.serverUpdated, dict(live))
                self._emit(self.serversChanged)
                self._set_status(f"查完了：{ok}/{len(addrs)} 个在线")
            finally:
                self._set_busy(False)

        threading.Thread(target=run, daemon=True).start()

    @Slot(str)
    def requestPlayers(self, addr: str) -> None:
        try:
            target = normalize_address(addr).lower()
        except ServerError as exc:
            self._set_status(str(exc))
            return

        def run() -> None:
            res = query_players(target)
            res["addr"] = target
            self._emit(self.playersLoaded, res)

        threading.Thread(target=run, daemon=True).start()

    # -------------------------------------------------------------- 直连
    @Slot(str)
    def connectServer(self, addr: str) -> None:
        """连接一台收藏里的服务器。见 `_doConnect`。"""
        self._doConnect(addr, notify=True)

    def _doConnect(self, addr: str, notify: bool = True) -> dict:
        """连接一台服务器，返回 ``{ok, addr, how, message, error}``。

        分支和实测依据都写在文件头「唤起 Steam 连接」那段注释里，这里只复述结论：

        * 没装 Steam / 没装 550 → 直接说清楚，别让玩家对着桌面发呆；
        * 域名 → 自己解析成 IP 再交给 Steam（Steam 不认域名）；
        * 游戏没跑 → `steam://connect/<ip>:<port>`，Steam 带 `+connect` 起游戏，最稳；
        * 游戏在跑 → 把窗口拉到前台，`connect <ip>:<port>` 塞剪贴板，提示去控制台粘
          （Source 引擎没有从外部让运行中进程执行命令的口子）。
        """
        try:
            target = normalize_address(addr)
        except ServerError as exc:
            self._set_status(str(exc))
            return {"ok": False, "addr": "", "error": str(exc)}

        if not steam_exe():
            msg = "没找到 Steam，先把它装好再连"
            self._set_status(msg)
            if notify:
                self._toast(msg, "error")
            return {"ok": False, "addr": target, "error": msg}
        if not game_installed():
            msg = "这台机器上没装《求生之路2》（Steam 库 id 550）"
            self._set_status(msg)
            if notify:
                self._toast(msg, "error")
            return {"ok": False, "addr": target, "error": msg}

        steam_target, warn = _connect_target(target)
        if warn:
            self._set_status(warn)
            if notify:
                self._toast(warn, "warn")
            return {"ok": False, "addr": target, "error": warn}
        if steam_target != target:
            self._set_status(f"{target} → 解析成 {steam_target}")

        if game_running():
            # ★ 游戏已经在跑 ≠ 连不上服务器。
            #   用户实测并明确指出：`steam://connect/<ip>:<port>/rungameid/550`
            #   这种带 appid 的写法，**游戏开着也能让正在运行的那个进程连过去**
            #   （Steam 会把它当成「给 550 传一条启动参数」，已经跑起来的进程会接住）。
            #   以前这里直接走「复制命令 + 让用户自己开控制台」，等于把一个本来能用的
            #   功能做成了半手动，用户的原话就是「并非打开游戏后就不能进服务器了」。
            #
            #   所以现在：先试带 rungameid 的 URL，失败再退回剪贴板 + 控制台提示。
            url = f"steam://connect/{steam_target}/rungameid/{STEAM_APPID}"
            ok = _open_url(url)
            if ok:
                self._bring_game_foreground()
                msg = f"正在让已经在运行的游戏连接 {steam_target}"
                self._set_status(msg)
                if notify:
                    self._toast(msg, "ok")
                return {"ok": True, "addr": target, "steamTarget": steam_target,
                        "how": "steam-running", "url": url, "message": msg,
                        "error": ""}

            # 走到这里说明系统没把 URL 交出去：老办法，复制控制台命令
            cmd = f"connect {steam_target}"
            copied = self._clipboard(cmd)
            self._bring_game_foreground()
            msg = (f"游戏已经在运行：{cmd} 已复制，按 ~ 打开控制台粘进去"
                   if copied else f"游戏已经在运行：进控制台敲 {cmd}")
            self._set_status(msg)
            if notify:
                self._toast(msg, "info")
            return {"ok": True, "addr": target, "steamTarget": steam_target,
                    "how": "console", "command": cmd, "copied": copied,
                    "message": msg, "error": ""}

        # 游戏没在跑：同样用带 appid 的写法 —— Steam 会带着 `+connect` 把 550 启动起来。
        # 两条路用同一个 URL 形状，行为更可预期，也省得维护两套。
        url = f"steam://connect/{steam_target}/rungameid/{STEAM_APPID}"
        ok = _open_url(url)
        if not ok:
            msg = "唤起 Steam 失败，可以从任务管理器把 Steam 彻底关掉再试"
            self._set_status(msg)
            if notify:
                self._toast(msg, "error")
            return {"ok": False, "addr": target, "error": msg}

        msg = f"正在用 Steam 连接 {steam_target}（游戏可能要几十秒才起来）"
        self._set_status(msg)
        if notify:
            self._toast(msg, "ok")
        return {"ok": True, "addr": target, "steamTarget": steam_target,
                "how": "steam", "url": url, "message": msg, "error": ""}

    @Slot(str, result="QVariantMap")
    def connectResult(self, addr: str) -> dict:
        """给 QML 用的同一套逻辑（能拿到结果，方便按返回值关对话框）。"""
        return self._doConnect(addr, notify=True)

    def _bring_game_foreground(self) -> bool:
        """把已经在跑的游戏窗口拉到前台，省得玩家自己在任务栏里翻。"""
        if os.name != "nt":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            found: list[int] = []
            enum_proc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            pid = os.getpid()

            def _cb(hwnd, _lparam):       # noqa: ANN001 - ctypes 回调签名固定
                buf = ctypes.create_unicode_buffer(64)
                user32.GetWindowTextW(hwnd, buf, 64)
                if "left 4 dead" not in buf.value.lower():
                    return True
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if owner.value != pid and user32.IsWindowVisible(hwnd):
                    found.append(hwnd)
                return True

            user32.EnumWindows(enum_proc(_cb), 0)
            for hwnd in found:
                user32.ShowWindow(hwnd, 9)         # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            return bool(found)
        except Exception:                     # noqa: BLE001 - 拉窗口失败不影响连服
            return False

    @Slot(str, result=str)
    def connectCommand(self, addr: str) -> str:
        try:
            return f"connect {normalize_address(addr)}"
        except ServerError:
            return ""

    @Slot(str, result=str)
    def connectUrl(self, addr: str) -> str:
        """给界面「复制链接」用的 Steam 连接 URL。

        ★ 带上 `/rungameid/550`：这种写法**游戏开着也能直接连进服务器**
          （用户实测指出）。不带 appid 的老写法在游戏已运行时会被 Steam 当成
          「再启动一次 550」然后什么都不做，看起来就是「点了进不去」。
        """
        try:
            target = normalize_address(addr)
        except ServerError:
            return ""
        return f"steam://connect/{target}/rungameid/{STEAM_APPID}"

    def _clipboard(self, text: str) -> bool:
        try:
            from PySide6.QtGui import QGuiApplication

            board = QGuiApplication.clipboard()
            if board is None:
                return False
            # ★ 自己往剪贴板写东西时先打好「这是本程序写的」标记：
            #   setText 会触发 dataChanged，不打标记的话「分享 / 复制地址」
            #   会被当成「用户在外面复制了新内容」，切回来就弹自己的框。
            self._clip_self_writes += 1
            board.setText(text)
            # 事件是同步还是异步派发因平台而异，异步时标记要留一会儿再撤
            threading.Timer(1.5, self._relax_self_write).start()
            return True
        except Exception:                    # noqa: BLE001 - 剪贴板不该崩界面
            return False

    def _relax_self_write(self) -> None:
        with self._clip_lock:
            if self._clip_self_writes > 0:
                self._clip_self_writes -= 1

    @Slot(str)
    def copyConnectCommand(self, addr: str) -> None:
        cmd = self.connectCommand(addr)
        if cmd and self._clipboard(cmd):
            self._set_status(f"已复制：{cmd}")
        else:
            self._set_status("复制失败了，手动抄一下吧")

    @Slot(str)
    def copyAddress(self, addr: str) -> None:
        if self._clipboard(addr or ""):
            self._set_status(f"已复制地址：{addr}")

    # ------------------------------------------------------------ IP 直连
    @Slot(str, result="QVariantMap")
    def parseAddress(self, text: str) -> dict:
        """给「IP 直连」输入框实时校验用：只写 IP 也算对（补 27015）。

        `url` 里的域名会先解析成 IP —— Steam 的 `steam://connect/` 不认域名，
        上一版这里直接把域名塞进去，于是「填了能连的域名，点连接没反应」。
        """
        try:
            addr = normalize_address(text)
        except ServerError as exc:
            return {"ok": False, "addr": "", "error": str(exc)}
        steam_target, warn = _connect_target(addr)
        return {"ok": warn == "", "addr": addr,
                "steamTarget": steam_target,
                "command": f"connect {steam_target}",
                "url": f"steam://connect/{steam_target}/rungameid/{STEAM_APPID}",
                "error": warn}

    @Slot(str, result="QVariantMap")
    def directConnect(self, text: str) -> dict:
        """IP 直连：不收藏，直接连过去（分支见 `_doConnect`）。"""
        parsed = self.parseAddress(text)
        if not parsed.get("ok"):
            msg = parsed.get("error") or "地址不对"
            self._set_status(msg)
            self._toast(msg, "error")
            return parsed
        return self._doConnect(parsed["addr"], notify=True)

