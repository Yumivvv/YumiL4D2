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

"""工坊 DNS：用指定的 DNS 服务器解析域名，并把它接成 urlopen 风格的 HTTP 请求。

## 为什么不用 urllib.request.urlopen

`urlopen` 只会问**系统**的 DNS（底层是 getaddrinfo），没有任何入口能说
「这次用哪台 DNS 服务器」。而国内访问 `api.steampowered.com` /
`cdn.steamusercontent.com` 时，系统 DNS 常常解析到很远的节点、返回被污染的
IP、甚至直接超时 —— 表现就是工坊封面空白、下载龟速。要换 DNS，就只能自己
组装 DNS 报文去问。

## 为什么是「自己解析 + http.client 手工建连」

解析出 IP 之后，真正连的是 IP，但 **Host 头和 TLS 的 SNI 必须仍然是域名**：
证书是签给域名的，拿 IP 去校验证书必然 `SSLCertVerificationError`（这也是
不能简单把 URL 里的域名替换成 IP 的原因）。`http.client` 允许先把 socket 连到
指定 IP，再把这个 socket 塞给连接对象（`conn.sock = sock`），这样 Host 和 SNI
就都还是域名，证书照常校验。语义和 lytvpk 的 WorkshopDialer 一致。

## 为什么自己做一层薄薄的响应包装

`urlopen` 返回的对象是 `http.client.HTTPResponse` 被 urllib 一整套 handler
包装后的产物。要换掉它的解析步骤，就得写 `BaseHandler.do_open` 去接管内部建连，
再自己维护 opener 链 —— 又长又容易被标准库版本变化弄坏。我们需要的成员只有
`read / status / status_code / headers / getheader / geturl / close`，
于是直接写个薄包装（`DNSResponse`）套在 `http.client` 的响应外面补上
`.status_code` 就够了，比硬接 handler 链简单得多、也可控得多。

**和 urlopen 的两处差异**（只发生在「指定了 DNS」这条分支上，替换调用时要
心里有数）：
  * 4xx/5xx **不抛** `HTTPError`，照常返回响应，状态码看 `.status`；
  * 包装对象只有常用的那几个成员，没有 `read1()`。

没指定 DNS 时返回的就是标准库 `urlopen` 的响应本身（只额外补了个
`.status_code`），行为和改造前一模一样 —— 这样调用方不用区分模式。

## 比 Go 版多做的一件事

lytvpk 的 DialContext 只管 TCP：连上了就把 socket 交出去，由 http.Transport
去握手，于是「TCP 连得上、TLS 握手却一直不回」的坏节点会让整个请求卡死
（实测 api.steampowered.com 的 A 记录里真有这种）。这里把「连 + 握手」算成
一次尝试，失败就换下一个 IP（最多 `MAX_IP_TRIES` 个）—— 指定 DNS 本来就会
拿到一串 IP，本来就是为了挑一个能用的。

## 排错顺序

空服务器 = 走系统解析（等价于原来的 `urlopen`）。指定服务器解析失败时
**回落到系统解析**并写一条 warning —— 国内有些网络会屏蔽第三方 DNS（丢包或者
直接重置），这时候把请求判死还不如慢一点走系统 DNS。
"""
from __future__ import annotations

import http.client
import ipaddress
import logging
import os
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple

# ===========================================================================
# 模式表（界面文案由 UI 直接读，顺序和文字都不能动）
# ===========================================================================
DNS_MODES: list[tuple[str, str, str]] = [
    ("dnspod", "腾讯 DNS · 119.29.29.29", "119.29.29.29"),
    ("alidns", "阿里 DNS · 223.5.5.5", "223.5.5.5"),
    ("custom", "自定义 DNS", ""),
    ("system", "使用系统 DNS", ""),
]

DEFAULT_MODE = "dnspod"

MODE_VALUES: tuple[str, ...] = tuple(value for value, _label, _server in DNS_MODES)

_LABEL_OF_MODE = {value: label for value, label, _server in DNS_MODES}
_SERVER_OF_MODE = {value: server for value, _label, server in DNS_MODES}

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DNS_PORT = 53
# 跟随 CNAME 的最大跳数（和 lytvpk 的 maxWorkshopCNAMEHops 一致）
MAX_CNAME_HOPS = 8
# 解析缓存条数上限；超了按到期时间淘汰最旧的一批
CACHE_LIMIT = 256
# 缓存 TTL 的夹紧区间：太短等于没缓存，太长会让换节点/换 IP 迟迟不生效
CACHE_TTL_MIN = 30.0
CACHE_TTL_MAX = 600.0
# 系统解析（getaddrinfo）拿不到上游 TTL，固定给 60 秒
SYSTEM_TTL = 60.0
# 单次 DNS 查询的默认超时
DNS_TIMEOUT = 5.0
# urlopen 不给 timeout 时的兜底：标准库的默认行为是「永不超时」，
# 在后台线程里那样会一直卡着，比超时报错更难查。
DEFAULT_TIMEOUT = 30.0
# 名字压缩指针的跳转上限：合法的报文里指针只会往回指，这里再兜一层，防构造出的环
MAX_NAME_JUMPS = 16
# 压缩指针之外还要防「标签套标签」，域名总长上限 255
MAX_NAME_BYTES = 255
# 最多跟几次 HTTP 重定向（urlopen 自己也跟，只是我们这条手工链路要自己实现）
MAX_REDIRECTS = 5
# 指定 DNS 时，「TCP 连接 + TLS 握手」最多在几个 IP 上试。每个失败都要耗掉
# 一整个 timeout，试太多会让请求慢得离谱；坏节点是零星出现的，三个足够。
MAX_IP_TRIES = 3

_TYPE_A = 1
_TYPE_CNAME = 5
_CLASS_IN = 1

# rcode 的说明文案：报错时必须把数字带上，不然用户只知道「失败了」
_RCODE_TEXT = {
    1: "DNS 报文格式错误",
    2: "DNS 服务器故障",
    3: "域名不存在",
    4: "该查询类型不被支持",
    5: "DNS 服务器拒绝回答",
}

_REDIRECT_CODES = (301, 302, 303, 307, 308)


class DNSResolveError(OSError):
    """解析失败（含 DNS 服务器返回错误码、报文不可信、网络超时）。

    继承 OSError 是为了让调用方沿用原来 catch `(urllib.error.URLError,
    TimeoutError, OSError)` 的写法就能兜住。
    """


# ===========================================================================
# 地址校验 / 模式换算
# ===========================================================================
def valid_address(value: str) -> str | None:
    """校验**单个** IPv4 或 IPv6 地址，合法返回规范化后的字符串，否则 None。

    和 lytvpk 的 `netip.ParseAddr` 对齐：
      * 只认一个地址 —— `1.2.3.4,5.6.7.8`、`1.2.3.4:53`（带端口）、
        `1.2.3.4 5.6.7.8` 都算非法，免得把「服务器地址」当成别的东西用；
      * IPv4-mapped IPv6（`::ffff:23.59.72.59`）归一成 IPv4 字符串 ——
        netip 也认这种写法，但我们的 A 记录只可能是 IPv4，统一成 IPv4 之后
        选 socket 地址族、拼日志都简单；
      * IPv6 用小写压缩形式（由 ipaddress 保证），例如
        `2001:0DB8:0:0::1` → `2001:db8::1`；
      * 前导零的 IPv4（`119.029.29.29`）返回 None：ipaddress 从 3.9.5 起就
        拒绝它（八进制歧义），系统 socket 也可能按八进制解释，
        与其猜不如当非法。
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return None
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        return str(mapped)
    return str(addr)


def server_for(mode: str, custom: str = "") -> str:
    """模式 → 要用的 DNS 服务器地址；空串表示走系统解析。

    未知模式、以及 `custom` 给了非法地址，都退回空串（系统解析）——
    设置项存坏了不该让整个程序连不上网。
    """
    m = str(mode or "").strip().lower()
    if m == "custom":
        return valid_address(custom) or ""
    return _SERVER_OF_MODE.get(m, "")


def mode_label(mode: str) -> str:
    """模式 → 界面文案；未知模式返回 `system` 的文案（界面永远有东西可显示）。"""
    m = str(mode or "").strip().lower()
    return _LABEL_OF_MODE.get(m) or _LABEL_OF_MODE["system"]


def _clean_host(host: object) -> str:
    """域名洗成小写、去尾部点（`Example.COM.` 和 `example.com` 是同一个）。"""
    raw = str(host or "").strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]  # 允许 [::1] 这种写法
    return raw.lower().rstrip(".")


def _where(server: str, host: str) -> str:
    """统一错误前缀：消息里必须能看出「哪台 DNS 解析哪个域名失败了」。"""
    if server:
        return f"工坊 DNS {server} 解析 {host} 失败"
    return f"系统解析 {host} 失败"


# ===========================================================================
# 缓存 / 当前服务器（多线程：图片代理会并发调用）
# ===========================================================================
# 一把可重入锁管住所有共享状态。锁里只做字典读写，绝不在持锁时做网络 I/O。
_LOCK = threading.RLock()
_SERVER = ""
_CACHE: dict[tuple[str, str], tuple[float, list[str]]] = {}
_STATS = {"hits": 0, "misses": 0}
# 「上一次连通的 IP」：DNS 抽风时还能先拿它试一下。key 是 (域名, DNS 服务器)
_REMEMBER: dict[tuple[str, str], str] = {}
_REMEMBER_LIMIT = 128


def configure(server: str) -> None:
    """设置进程内当前使用的 DNS 服务器（空串 = 系统解析），并清空解析缓存。

    换服务器后缓存里的结果可能是**另一台 DNS** 给的，解析结果会不一样，
    必须丢掉；「上次连通的 IP」同理。
    """
    global _SERVER
    srv = str(server or "").strip()
    if srv:
        # 顺手规范化：设置里填 "::FFFF:1.2.3.4" 也能正确选到 IPv4 地址族
        srv = valid_address(srv) or srv
    with _LOCK:
        _SERVER = srv
    clear_cache()


def current_server() -> str:
    """当前使用的 DNS 服务器（空串 = 系统解析）。"""
    with _LOCK:
        return _SERVER


def clear_cache() -> None:
    """清空解析缓存和「上次连通的 IP」提示。计数（hits/misses）是累计值，不动。"""
    with _LOCK:
        _CACHE.clear()
        _REMEMBER.clear()


def cache_stats() -> dict:
    """缓存概况：entries=条目数，servers=缓存里涉及几台 DNS（空串算系统解析一台）。"""
    with _LOCK:
        return {
            "entries": len(_CACHE),
            "servers": len({key[1] for key in _CACHE}),
            "hits": _STATS["hits"],
            "misses": _STATS["misses"],
        }


def _cache_put(key: tuple[str, str], ips: list[str], ttl: float) -> None:
    if not ips:
        return
    ttl = max(CACHE_TTL_MIN, min(CACHE_TTL_MAX, float(ttl or 0)))
    expire = time.time() + ttl
    with _LOCK:
        _CACHE[key] = (expire, list(ips))
        if len(_CACHE) > CACHE_LIMIT:
            # 淘汰最旧的 1/4。不做 LRU：解析结果基本用一次就够，
            # 命中率高低只跟 TTL 有关，为它维护访问顺序不值得。
            for old in sorted(_CACHE, key=lambda k: _CACHE[k][0])[: CACHE_LIMIT // 4]:
                _CACHE.pop(old, None)


def _remembered(host: str, server: str) -> str:
    with _LOCK:
        return _REMEMBER.get((host, server), "")


def _remember(host: str, server: str, ip: str) -> None:
    if not ip:
        return
    with _LOCK:
        _REMEMBER[(host, server)] = ip
        if len(_REMEMBER) > _REMEMBER_LIMIT:
            for old in list(_REMEMBER)[: _REMEMBER_LIMIT // 4]:
                _REMEMBER.pop(old, None)


# ===========================================================================
# 解析
# ===========================================================================
def resolve(host: str, server: str | None = None, timeout: float = DNS_TIMEOUT) -> list[str]:
    """解析域名的 A 记录，按 DNS 返回的顺序返回 IPv4 列表。

    `server` 为 None 时用 `current_server()`；为空串时走系统解析
    （`socket.getaddrinfo`）。失败抛 `DNSResolveError`。

    注：`host` 本身是 IP 字面量时直接返回它，不问 DNS（对齐 lytvpk 的
    `netip.ParseAddr` 分支 —— 拿 IP 去当域名查毫无意义）。
    """
    name = _clean_host(host)
    if not name:
        raise DNSResolveError("没有域名")
    srv = current_server() if server is None else str(server or "").strip()
    literal = valid_address(name)
    if literal:
        return [literal]

    key = (name, srv)
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] > now:
            _STATS["hits"] += 1
            return list(hit[1])
        if hit is not None:
            _CACHE.pop(key, None)  # 过期的顺手删掉，别占着 256 条的名额
        _STATS["misses"] += 1

    if srv:
        ips, ttl = _lookup_ipv4(name, srv, float(timeout))
    else:
        ips, ttl = _system_lookup(name), SYSTEM_TTL
    _cache_put(key, ips, ttl)
    return list(ips)


def resolve_first(host: str, server: str | None = None,
                  timeout: float = DNS_TIMEOUT) -> str:
    """解析并返回第一个 IP；失败抛 `DNSResolveError`。"""
    ips = resolve(host, server, timeout)
    if not ips:
        srv = current_server() if server is None else str(server or "").strip()
        raise DNSResolveError(_where(srv, _clean_host(host)) + ": 没有解析到 IP")
    return ips[0]


def _system_lookup(host: str) -> list[str]:
    """系统解析（getaddrinfo），只取 IPv4，和指定 DNS 时的口径保持一致。

    注意：标准库没给 getaddrinfo 传超时的入口，所以这条路不受 `timeout` 约束
    —— 这也是「指定 DNS」那条路值得自己写的原因之一。
    """
    try:
        infos = socket.getaddrinfo(host, 0, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise DNSResolveError(_where("", host) + f": {e}") from e
    out: list[str] = []
    seen: set[str] = set()
    for info in infos:
        ip = str(info[4][0])
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    if not out:
        raise DNSResolveError(_where("", host) + ": 没有解析到 IPv4 地址")
    return out


def _lookup_ipv4(host: str, server: str, timeout: float) -> tuple[list[str], float]:
    """按指定 DNS 查 A 记录，跟随 CNAME（最多 MAX_CNAME_HOPS 跳）。

    结构和 lytvpk 的 lookupIPv4 一样：先在**同一条响应**里顺着 CNAME 找 A；
    如果服务器只回了 CNAME 没带 A，就拿目标名再问一次。
    """
    where = _where(server, host)
    current = _clean_host(host)
    seen = {current}
    hops = 0
    while True:
        queried = current
        answer = _query_once(current, server, timeout, where)
        while True:
            ips = answer.addresses.get(current) or []
            if ips:
                return ips, answer.ttl
            target = answer.aliases.get(current)
            if not target:
                if current != queried:
                    break  # 这条响应只给了 CNAME，拿目标名再问一次
                raise DNSResolveError(f"{where}: 没有返回 IPv4 地址")
            hops += 1
            if target in seen or hops > MAX_CNAME_HOPS:
                # 成环或者链太长都直接放弃，免得无限问下去
                raise DNSResolveError(f"{where}: CNAME 循环或跳转超过 {MAX_CNAME_HOPS} 次")
            seen.add(target)
            current = target


def _query_once(host: str, server: str, timeout: float, where: str) -> "_Answer":
    """问一次这台 DNS（UDP 不行就 TCP），返回解析后的答案。"""
    qname = _clean_host(host)
    # 事务 id 用 os.urandom 而不是 random：random 是可预测的（Mersenne
    # Twister），而 transaction id 是 DNS 防串扰/防投毒的第一道门。
    txid = struct.unpack("!H", os.urandom(2))[0]
    try:
        packet = _build_query(qname, txid)
    except (ValueError, UnicodeError) as e:
        raise DNSResolveError(f"{where}: 域名不合法（{e}）") from e

    try:
        data = _udp_query(server, packet, timeout)
    except OSError as e:
        raise DNSResolveError(f"{where}: UDP 查询失败（{type(e).__name__}：{e}）") from e
    answer = _parse_answer(data, txid, qname, where)

    if answer.truncated:
        # TC 置位 = UDP 里装不下（默认 512 字节）答案，服务器把它截断了。
        # 这时候 answer 段是残缺的，直接当「没有这条记录」会误判成解析失败；
        # RFC 1035 规定必须改用 TCP 重查，TCP 上有 2 字节长度前缀、没有大小限制。
        try:
            data = _tcp_query(server, packet, timeout)
        except OSError as e:
            raise DNSResolveError(f"{where}: TCP 重查失败（{type(e).__name__}：{e}）") from e
        answer = _parse_answer(data, txid, qname, where)
        if answer.truncated:
            raise DNSResolveError(f"{where}: 改用 TCP 之后响应仍然被截断")
    return answer


# ---------------------------------------------------------------- 收发报文
def _build_query(host: str, txid: int) -> bytes:
    """拼一条标准查询：QTYPE=A、QCLASS=IN、RD=1（要递归）。"""
    header = struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    return header + _encode_name(host) + struct.pack("!HH", _TYPE_A, _CLASS_IN)


def _encode_name(host: str) -> bytes:
    """域名 → DNS 报文里的「一串长度+标签」。"""
    out = bytearray()
    for label in host.split("."):
        if not label:
            raise ValueError("域名里有空标签")
        try:
            raw = label.encode("ascii")
        except UnicodeEncodeError:
            # 中文域名之类：转成 punycode 再发
            raw = label.encode("idna")
        if len(raw) > 63:
            raise ValueError("域名单个标签超过 63 字节")
        out.append(len(raw))
        out += raw
    if len(out) > MAX_NAME_BYTES:
        raise ValueError("域名过长")
    out.append(0)
    return bytes(out)


def _udp_query(server: str, packet: bytes, timeout: float) -> bytes:
    """发一次 UDP 查询，返回原始响应。

    这里**不能**用 `socket.create_connection` —— 它只会建 TCP 连接。
    UDP 得自己建 socket、设超时、sendto/recvfrom。
    （自测会 monkeypatch 这个函数，用离线报文验证解析逻辑。）
    """
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(packet, (server, DNS_PORT))
        data, _peer = sock.recvfrom(4096)
        return data
    finally:
        sock.close()


def _tcp_query(server: str, packet: bytes, timeout: float) -> bytes:
    """TCP 重查：同样的问题报文，前面加 2 字节长度前缀（RFC 1035 4.2.2）。

    少了这个前缀，服务器会把报文开头两个字节当长度，直接报格式错。
    """
    with socket.create_connection((server, DNS_PORT), timeout=timeout) as sock:
        sock.sendall(struct.pack("!H", len(packet)) + packet)
        size = struct.unpack("!H", _recv_exact(sock, 2))[0]
        return _recv_exact(sock, size)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    """TCP 上没有「一次 recv 就是一条消息」这回事，必须按长度收满。"""
    buf = bytearray()
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise OSError(f"DNS 服务器提前关闭了连接（还差 {size - len(buf)} 字节）")
        buf += chunk
    return bytes(buf)


# ---------------------------------------------------------------- 解析响应
class _Answer(NamedTuple):
    addresses: dict[str, list[str]]  # 名字 → IPv4 列表
    aliases: dict[str, str]          # 名字 → CNAME 目标
    ttl: int                         # 答案段里最小的 TTL
    truncated: bool                  # TC 置位（需要改 TCP 重查）


def _read_name(data: bytes, offset: int) -> tuple[str, int]:
    """从 offset 读一个域名，返回 (小写域名, 下一个字段的偏移)。

    报文里的名字有两种写法：一串「长度+内容」的标签，或者以 `0xC0` 开头的
    两字节指针 —— 指针指向报文里**前面**出现过的同一串名字（压缩省字节用），
    必须支持。但指针可以互相指、可以成环，所以这里同时限制：

      * 指针只能指回前面（RFC 1035 4.1.4 的合法用法就是这么用的）；
      * 最多跳 MAX_NAME_JUMPS 次。

    任何一条不满足就报错 —— 死循环比解析失败糟糕得多。
    """
    labels: list[str] = []
    pos = offset
    nxt = -1  # 名字结束后该继续读的位置（跟随过指针时和 pos 不是一回事）
    jumps = 0
    total = 0
    while True:
        if pos >= len(data):
            raise DNSResolveError("响应里的域名越界（报文被截断）")
        size = data[pos]
        if size == 0:
            pos += 1
            break
        if size & 0xC0 == 0xC0:
            if pos + 1 >= len(data):
                raise DNSResolveError("响应里的压缩指针不完整")
            target = ((size & 0x3F) << 8) | data[pos + 1]
            if nxt < 0:
                nxt = pos + 2
            jumps += 1
            if jumps > MAX_NAME_JUMPS:
                raise DNSResolveError("响应里的压缩指针跳转次数过多")
            if target >= pos:
                raise DNSResolveError("响应里的压缩指针指向前方（疑似成环）")
            pos = target
            continue
        if size & 0xC0:
            raise DNSResolveError(f"响应里出现保留的名字类型（0x{size:02x}）")
        if pos + 1 + size > len(data):
            raise DNSResolveError("响应里的域名标签越界（报文被截断）")
        # 名字只用来比对（DNS 名字大小写不敏感），非 ASCII 字节替换掉即可
        labels.append(data[pos + 1: pos + 1 + size].decode("ascii", "replace").lower())
        total += size + 1
        if total > MAX_NAME_BYTES:
            raise DNSResolveError("响应里的域名过长")
        pos += 1 + size
    return ".".join(labels), (nxt if nxt >= 0 else pos)


def _parse_answer(data: bytes, txid: int, qname: str, where: str) -> _Answer:
    """解析 DNS 响应：跳过 question 段，读 answer 段里的 A 和 CNAME。"""
    if len(data) < 12:
        raise DNSResolveError(f"{where}: 响应不到 12 字节，连报文头都不全")
    rid, flags, qdcount, ancount, _nscount, _arcount = struct.unpack("!HHHHHH", data[:12])
    if rid != txid:
        # 16 位事务 id 就是用来挡住「收到了别人的响应」的
        raise DNSResolveError(f"{where}: 响应事务 id 不匹配（请求 {txid}，响应 {rid}）")
    if not flags & 0x8000:
        raise DNSResolveError(f"{where}: 收到的不是应答报文")
    if flags & 0x0200:
        # TC：UDP 装不下，交给调用方用 TCP 重查
        return _Answer({}, {}, 0, True)
    rcode = flags & 0x000F
    if rcode:
        text = _RCODE_TEXT.get(rcode, "DNS 返回了错误")
        raise DNSResolveError(f"{where}: {text}（rcode={rcode}）")

    if qdcount < 1:
        raise DNSResolveError(f"{where}: 响应里没有问题段")
    pos = 12
    for i in range(qdcount):
        name, pos = _read_name(data, pos)
        if pos + 4 > len(data):
            raise DNSResolveError(f"{where}: 问题段不完整")
        qtype, qclass = struct.unpack("!HH", data[pos: pos + 4])
        pos += 4
        if i == 0 and (name != qname or qtype != _TYPE_A or qclass != _CLASS_IN):
            # 问 A 却回了别的、或者名字对不上：一律不认（防串扰）
            raise DNSResolveError(f"{where}: 响应的问题段与请求不一致")

    addresses: dict[str, list[str]] = {}
    aliases: dict[str, str] = {}
    ttl = 0
    for _ in range(ancount):
        owner, pos = _read_name(data, pos)
        if pos + 10 > len(data):
            raise DNSResolveError(f"{where}: 答案段不完整")
        rtype, rclass, rttl, rdlength = struct.unpack("!HHIH", data[pos: pos + 10])
        pos += 10
        end = pos + rdlength
        if end > len(data):
            raise DNSResolveError(f"{where}: 答案段里的数据越界")
        if rclass == _CLASS_IN:
            if rttl > 0 and (ttl == 0 or rttl < ttl):
                ttl = int(rttl)
            if rtype == _TYPE_A and rdlength == 4:
                addresses.setdefault(owner, []).append(socket.inet_ntoa(data[pos:end]))
            elif rtype == _TYPE_CNAME:
                # rdata 里的名字自己也可能带压缩指针，必须按绝对偏移解
                target, _ = _read_name(data, pos)
                aliases.setdefault(owner, target)
        pos = end
    return _Answer(addresses, aliases, ttl, False)


# ===========================================================================
# 建连 / urlopen
# ===========================================================================
def connect(host: str, port: int, server: str | None = None,
            timeout: float = 10.0, prefer: str | None = None) -> socket.socket:
    """建一条到 host:port 的 TCP 连接，连接目标是解析出来的 IP。

    `server` 为 None 时用 `current_server()`，空串 = 系统解析（直接
    `socket.create_connection`）。`prefer` 是上一次成功的 IP，会先拿它试一次。
    解析失败或所有 IP 都连不上时抛异常，消息里保留最后一次的系统错误。
    """
    name = _clean_host(host)
    if not name:
        raise ValueError("没有域名")
    try:
        port_n = int(port)
    except (TypeError, ValueError) as e:
        raise ValueError(f"端口不对：{port!r}") from e
    srv = current_server() if server is None else str(server or "").strip()
    return _dial(name, port_n, srv, float(timeout), prefer)


def _resolve_candidates(host: str, server: str, timeout: float,
                        prefer: str | None) -> list[str]:
    """按指定 DNS 解析出要试的 IP 列表（`prefer` / 上次成功的 IP 排最前）。

    解析失败时不直接死掉：上次连通的 IP 往往还能用（那台 DNS 临时抽风、
    或者网络刚好屏蔽了它的时候，这一手能让请求照样跑通），所以把它当候选
    保底；实在一个都没有才抛异常。
    """
    hint = str(prefer or "").strip() or _remembered(host, server)
    dns_err: OSError | None = None
    ips: list[str] = []
    try:
        # DNS 只给 5 秒：连不上的原因十有八九是「那台 DNS 不通」，
        # 不该在这里耗掉整个 connect 超时。
        ips = resolve(host, server, timeout=min(timeout, DNS_TIMEOUT))
    except DNSResolveError as e:
        dns_err = e

    candidates = ([hint] if hint else []) + [x for x in ips if x != hint]
    if not candidates:
        raise dns_err or DNSResolveError(_where(server, host) + ": 没有解析到可用的 IP")
    return candidates


def _dial(host: str, port: int, server: str, timeout: float,
          prefer: str | None = None) -> socket.socket:
    """按当前模式建一条裸 TCP 连接（`connect` 用）。"""
    literal = valid_address(host)
    if literal or not server:
        # 目标是 IP 字面量（问 DNS 没意义），或者本来就走系统解析 ——
        # 这两种情况标准库自己就会按地址类型把地址试一遍。
        return socket.create_connection((literal or host, port), timeout=timeout)

    last_err: OSError | None = None
    for ip in _resolve_candidates(host, server, timeout, prefer):
        try:
            sock = socket.create_connection((ip, port), timeout=timeout)
        except OSError as e:
            last_err = e
            continue
        _remember(host, server, ip)
        return sock
    raise OSError(
        f"连接 {host} 失败：所有 IP 都连不上（最后一次：{last_err}）") from last_err


def _tls_wrap(sock: socket.socket, scheme: str, host: str,
              context: ssl.SSLContext | None) -> socket.socket:
    """http 原样返回；https 就地握手。SNI 用域名，证书照常校验。"""
    if scheme != "https":
        return sock
    ctx = context if context is not None else ssl.create_default_context()
    # server_hostname 必须是域名：证书是签给域名的，拿 IP 去握手会直接
    # SSLCertVerificationError（不放松校验，这个函数也不负责吞异常）。
    return ctx.wrap_socket(sock, server_hostname=host)


def _open(host: str, port: int, scheme: str, server: str, timeout: float,
          context: ssl.SSLContext | None,
          prefer: str | None = None) -> socket.socket:
    """返回一个「马上能发 HTTP 请求」的 socket：TCP 已连，https 已握手完成。

    和 `_dial` 的区别就在这里：**握手也算进「这个 IP 行不行」的判定**。
    实测（api.steampowered.com 的 A 记录里就有这种节点）会遇到「TCP 连得上、
    TLS 握手却一直不回直到超时」的 IP：`socket.create_connection` 只负责 TCP，
    挪到 IP 上去连成功就撒手不管了，于是整个请求卡死在第一个坏节点上。
    所以这里把「连 + 握手」一起按 IP 重试 —— 这也是能做到「指定 DNS」的意义所在：
    解析出好几个 IP，本来就是为了挑一个能用的。
    """
    literal = valid_address(host)
    if literal or not server:
        # 系统解析（或目标是 IP）：交给标准库，它自己会把系统返回的地址
        # （含 IPv6）挨个试一遍，我们只是在末尾补一次握手。
        sock = socket.create_connection((literal or host, port), timeout=timeout)
        try:
            return _tls_wrap(sock, scheme, host, context)
        except BaseException:
            sock.close()
            raise

    candidates = _resolve_candidates(host, server, timeout, prefer)
    last_err: OSError | None = None
    # 每个 IP 最坏要耗掉整个 timeout，全试完等待时间就很可观了，所以只试前
    # MAX_IP_TRIES 个：坏节点是零星的，试三个足够越过它。
    for ip in candidates[:MAX_IP_TRIES]:
        try:
            sock = socket.create_connection((ip, port), timeout=timeout)
        except OSError as e:
            last_err = e
            continue
        try:
            sock = _tls_wrap(sock, scheme, host, context)
        except ssl.SSLCertVerificationError:
            # 证书不对是配置/中间人的问题，换 IP 也一样，直接报出去
            sock.close()
            raise
        except OSError as e:
            # 握手超时/被重置：这个 IP 不能用，记一笔换下一个（不是吞异常）
            sock.close()
            last_err = e
            logging.warning("工坊 DNS %s 解析出的 %s 握手失败，换下一个 IP：%s",
                            server, ip, e)
            continue
        _remember(host, server, ip)
        return sock
    raise OSError(
        f"连接 {host} 失败：试了 {len(candidates[:MAX_IP_TRIES])} 个 IP 都失败"
        f"（最后一次：{last_err}）") from last_err


def _host_header(host: str, port: int, scheme: str, headers: dict) -> str:
    """算 Host 头：调用方自己指定了就照它的，否则按域名和端口拼。"""
    for name, value in headers.items():
        if str(name).lower() == "host" and str(value).strip():
            return str(value).strip()
    default = 443 if scheme == "https" else 80
    if port == default:
        return f"[{host}]" if ":" in host else host
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


class DNSResponse:
    """urlopen 风格的薄响应包装（内部就是 `http.client` 的响应）。

    只补上 urllib 响应有、`http.client` 没有的成员（`.status_code`、
    `.geturl()`），其余直接转发。刻意**不**做 `__getattr__` 兜底：
    成员就是列出来的这些，没有 `read1()` 之类的东西，用起来心里有数。
    """

    def __init__(self, resp: http.client.HTTPResponse, conn: http.client.HTTPConnection,
                 url: str):
        self._resp = resp
        self._conn = conn
        self._closed = False
        self.url = url
        self.status = int(resp.status)
        self.status_code = self.status
        self.code = self.status
        self.reason = resp.reason
        self.version = resp.version
        self.msg = resp.msg
        self.headers = resp.headers

    # ---------------------------------------------------------- 读响应
    def read(self, amt: int | None = None) -> bytes:
        if amt is None:
            return self._resp.read()
        return self._resp.read(amt)

    def readline(self, limit: int = -1) -> bytes:
        return self._resp.readline(limit)

    def readlines(self, hint: int = -1) -> list[bytes]:
        return self._resp.readlines(hint)

    # ---------------------------------------------------------- 头 / 地址
    def getheader(self, name: str, default: str | None = None):
        return self._resp.getheader(name, default)

    def getheaders(self) -> list[tuple[str, str]]:
        return self._resp.getheaders()

    def info(self):
        return self._resp.headers

    def geturl(self) -> str:
        return self.url

    # ---------------------------------------------------------- 生命周期
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._resp.close()
        except OSError:
            # 读到一半就关、或者对端已经断了，这里报错没有意义：
            # 响应确实不用了，紧接着还会关掉下面的连接，吞掉是安全的。
            pass
        try:
            self._conn.close()
        except OSError:
            pass

    def __enter__(self) -> "DNSResponse":
        return self

    def __exit__(self, *_exc) -> bool:
        self.close()
        return False


def _unpack_request(req, data_kw) -> tuple[str, str, bytes | None, dict]:
    """把 urlopen 的第一个参数（str 或 Request）拆成 (url, method, data, headers)。"""
    if isinstance(req, urllib.request.Request):
        url = req.full_url
        method = (req.get_method() or "GET").upper()
        data = req.data if req.data is not None else data_kw
        headers = dict(req.header_items())
        # Host 之类的「不跟随重定向」头 urllib 单独放一个表里，得一起算上
        headers.update(req.unredirected_hdrs)
    else:
        url = str(req or "").strip()
        method = "POST" if data_kw is not None else "GET"
        data = data_kw
        headers = {}
    if not url:
        raise ValueError("urlopen() 没有有效的地址")
    return url, method, data, headers


def _request_once(url: str, method: str, data, headers: dict, timeout: float,
                  context: ssl.SSLContext | None, server: str) -> DNSResponse:
    """按指定 DNS 发一次请求，返回响应（不跟重定向）。

    指定 DNS 解析失败时**回落到系统解析**：国内有些网络会屏蔽/劫持第三方
    DNS，这时候让请求直接失败还不如慢一点走系统 DNS。
    """
    parts = urllib.parse.urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"只支持 http/https，收到的是：{scheme or '（空）'}")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"地址里没有域名：{url}")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as e:
        raise ValueError(f"地址里的端口不对：{url}") from e
    request_path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
    host_header = _host_header(host, port, scheme, headers)

    try:
        sock = _open(host, port, scheme, server, timeout, context)
    except OSError as e:
        # DNSResolveError 也是 OSError：解析失败、或者解析出来的 IP 都连不上/握不上手
        if not server:
            raise urllib.error.URLError(f"连不上 {host}：{e}") from e
        logging.warning("工坊 DNS %s 解析 %s 失败，回落到系统解析：%s", server, host, e)
        try:
            sock = _open(host, port, scheme, "", timeout, context)
        except OSError as e2:
            raise urllib.error.URLError(
                f"连不上 {host}（指定 DNS 与系统解析都失败）：{e2}") from e2

    return _send_request(sock, scheme, host, port, request_path, host_header,
                         method, data, headers, timeout, context, url)


def _send_request(sock: socket.socket, scheme: str, host: str, port: int,
                  request_path: str, host_header: str, method: str, data,
                  headers: dict, timeout: float, context: ssl.SSLContext | None,
                  url: str) -> DNSResponse:
    """在已经连好（https 还握过手）的 socket 上发请求。

    Host 头和 TLS 的 SNI 都还是域名，只有「连到哪个 IP」被换掉了。
    """
    if scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            host, port, timeout=timeout,
            context=context if context is not None else ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.sock = sock  # 塞进上面那个连好的 socket，http.client 不会再自己拨号

    lower = {str(k).lower() for k in headers}
    body = data
    if isinstance(body, str):
        body = body.encode("utf-8")
    try:
        conn.putrequest(method, request_path, skip_host=True, skip_accept_encoding=True)
        for name, value in headers.items():
            if str(name).lower() in ("host", "content-length"):
                continue  # 这两个下面按实际端口/长度自己补，免得对不上
            conn.putheader(name, value)
        conn.putheader("Host", host_header)
        if body is not None:
            # 和 urllib 一致：给了请求体又没写 Content-Type 时补表单类型
            if "content-type" not in lower:
                conn.putheader("Content-Type", "application/x-www-form-urlencoded")
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders()
        if body:
            conn.send(body)
        resp = conn.getresponse()
    except BaseException:
        # 出错必须把 socket 放掉（图片代理是多线程的，漏 fd 很快就耗光）。
        # 这里是重新抛出，没有吞异常。
        conn.close()
        raise
    return DNSResponse(resp, conn, url)


def _proxy_in_use(req) -> bool:
    """这套网络里配了代理吗？配了就别自己拨号。

    `urllib.request.getproxies()` 在 Windows 上还会读注册表里的 IE 代理设置，
    和 urllib 自己的判断保持一致（不然会出现「标准库走代理、我们走直连」的分裂）。
    """
    try:
        proxies = urllib.request.getproxies()
    except Exception:  # noqa: BLE001  读注册表失败不该影响联网
        return False
    if not proxies:
        return False
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    scheme = urllib.parse.urlsplit(url).scheme or "http"
    # 只认 http/https：ftp/代理排除列表等和这里无关
    for key in (scheme, scheme + "s" if not scheme.endswith("s") else scheme[:-1]):
        if proxies.get(key):
            return True
    # 只有 all / all_proxy 也算配了代理
    return bool(proxies.get("all") or proxies.get("all_proxy"))


_PROXY_WARNED = False


def _warn_proxy_once() -> None:
    global _PROXY_WARNED
    if _PROXY_WARNED:
        return
    _PROXY_WARNED = True
    logging.warning("系统里配了代理，这次让标准库走代理（工坊 DNS 的自定义服务器对代理请求不生效）")


def urlopen(req, timeout: float | None = None, **kwargs) -> DNSResponse:
    """`urllib.request.urlopen` 的替代品：按 `current_server()` 解析，Host/SNI 保持域名。

    第一个参数可以是 str 或 `urllib.request.Request`（GET/POST、data、headers
    都从 Request 上取）。`current_server()` 为空时直接交给标准库
    `urllib.request.urlopen`，行为跟改造前一模一样。

    只支持 `http://` 和 `https://`，端口用默认端口或 URL 里的显式端口。
    返回对象可当上下文管理器，有 `read/status/status_code/headers/
    getheader/geturl`；**指定 DNS 时 4xx 不抛 HTTPError**，没指定 DNS 时
    仍然是标准库的响应（照旧抛 HTTPError）。
    """
    server = current_server()
    # 非 http/https（file://、ftp://、data: …）跟 DNS 没关系，一律交回标准库：
    # 以前这些协议会撞到下面那句「只支持 http/https」而直接报错 —— 比如
    # 测试用的 file:// 直链、以及某些本地路径下载都会被误伤。
    raw_url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    if urllib.parse.urlsplit(raw_url).scheme.lower() not in ("http", "https"):
        return urllib.request.urlopen(req, timeout=timeout, **kwargs)

    if not server:
        # 系统解析：直接用标准库，不再自己绕一圈（超时语义、HTTPError
        # 的抛法都和改造前完全一致）。
        resp = urllib.request.urlopen(req, timeout=timeout, **kwargs)
        if not hasattr(resp, "status_code") and getattr(resp, "status", None) is not None:
            # urllib 的响应只有 .status，没有 .status_code。两条分支返回的东西
            # 必须长得一样，调用方才能不分模式地写 —— 这里直接给这个实例补一个
            # 属性（这两个类都没有 __slots__），比再套一层包装更透明：
            # read1() 之类 urllib 特有的方法原封不动都还在。
            resp.status_code = resp.status
        return resp

    if _proxy_in_use(req):
        # 手工建连是我们自己拨号，读不到 urllib 的代理设置。真配了代理还硬走
        # 直连只会连不上，所以这里让开、交给标准库去走代理（DNS 设置这次不生效，
        # 但网络是通的 —— 明确写日志，不装作没这回事）。
        _warn_proxy_once()
        resp = urllib.request.urlopen(req, timeout=timeout, **kwargs)
        if not hasattr(resp, "status_code") and getattr(resp, "status", None) is not None:
            resp.status_code = resp.status
        return resp

    data_kw = kwargs.pop("data", None)
    context = kwargs.pop("context", None)
    cafile = kwargs.pop("cafile", None)
    capath = kwargs.pop("capath", None)
    kwargs.pop("cadefault", None)  # 标准库里这个参数早就没用了，忽略不算吞异常
    if kwargs:
        # 不认识就明确报错：默默忽略等于把调用方的意图吃掉
        raise TypeError("urlopen() 不支持这些参数：" + "、".join(sorted(kwargs)))
    if context is None and (cafile or capath):
        context = ssl.create_default_context(cafile=cafile or None, capath=capath or None)

    timeout = DEFAULT_TIMEOUT if timeout is None else float(timeout)
    url, method, data, headers = _unpack_request(req, data_kw)

    for _ in range(MAX_REDIRECTS + 1):
        resp = _request_once(url, method, data, headers, timeout, context, server)
        if resp.status in _REDIRECT_CODES:
            location = resp.getheader("Location")
            if location:
                resp.close()
                url = urllib.parse.urljoin(url, str(location).strip())
                # 303（以及 301/302 上的 POST）按惯例降级成 GET 并丢掉请求体；
                # 307/308 是要保持原方法和请求体的，不能动。
                if resp.status == 303 or (
                        resp.status in (301, 302) and method not in ("GET", "HEAD")):
                    method, data = "GET", None
                    headers = {k: v for k, v in headers.items()
                               if str(k).lower() not in ("content-length", "content-type")}
                continue
            # 没给 Location 的重定向就当普通响应返回（urlopen 也是这么处理的）
        return resp
    raise urllib.error.URLError(f"重定向次数超过 {MAX_REDIRECTS} 次")
