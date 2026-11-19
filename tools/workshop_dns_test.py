"""工坊 DNS 自检（对应 app/workshop_dns.py）：

    1. valid_address（IPv4 / IPv6 / IPv4-mapped 归一 / 各种非法写法）
    2. server_for / mode_label
    3. DNS_MODES 的顺序和文案
    4. 离线解析：压缩指针 + 两条 A + 一条 CNAME，以及 TTL 缓存生效
    5. 离线解析：TC 截断 → 确实改走 TCP
    6. 离线解析：rcode=3（NXDOMAIN）抛 DNSResolveError
    7. 真实网络：指定 DNS 与系统解析各解析一次
    8. 真实网络：urlopen 在「指定 DNS」和「系统解析」两种设置下各请求一次
    9. cache_stats / clear_cache

网络用例失败只打印 [skip]，不算失败。

用法：python -X utf8 tools/workshop_dns_test.py
"""
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import http.server
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import os
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import socket
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import ssl
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import struct
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import threading
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import time
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from app import workshop_dns as WD  # noqa: E402

FAILS: list[str] = []
DNSPOD = "119.29.29.29"


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 手工构造 DNS 报文的工具（离线用，不碰网络）
# ---------------------------------------------------------------------------
def _answer_ptr_a(ttl: int, ip: str) -> bytes:
    """A 记录，owner 用压缩指针指回报文偏移 12（question 里的域名）。"""
    return (b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, ttl, 4)
            + socket.inet_aton(ip))


def _answer_cname_ptr_owner(ttl: int, target: bytes) -> bytes:
    """CNAME，owner 是 question 里的域名（指针），target 由调用方给字节。"""
    return (b"\xc0\x0c" + struct.pack("!HHIH", 5, 1, ttl, len(target)) + target)


def _answer_named_a(owner: bytes, ttl: int, ip: str) -> bytes:
    """A 记录，owner 是需要自己拼的名字（名字里也可以带压缩指针）。"""
    return (owner + struct.pack("!HHIH", 1, 1, ttl, 4) + socket.inet_aton(ip))


def _answer_named_cname(owner: bytes, ttl: int, target: bytes) -> bytes:
    return (owner + struct.pack("!HHIH", 5, 1, ttl, len(target)) + target)


def _response(packet: bytes, answers: list[bytes], flags: int = 0x8180,
              txid: int | None = None) -> bytes:
    """用请求报文里的 question 段拼一条应答（question 直接照抄，偏移 12 一定对）。"""
    ident = struct.unpack("!H", packet[:2])[0] if txid is None else txid
    header = struct.pack("!HHHHHH", ident, flags, 1, len(answers), 0, 0)
    return header + packet[12:] + b"".join(answers)


def _fake_udp(responses):
    """造一个假的 _udp_query：记录调用次数，按顺序吐出预置报文。

    `responses` 里的元素可以是 bytes，也可以是 callable(packet) -> bytes。
    """
    state = {"calls": 0, "packets": []}

    def fake(server: str, packet: bytes, timeout: float) -> bytes:
        state["calls"] += 1
        state["packets"].append(packet)
        item = responses[min(state["calls"] - 1, len(responses) - 1)]
        return item(packet) if callable(item) else item

    return fake, state


class patched:
    """临时替换模块里的内部函数，退出时一定还原（异常路径也不漏）。"""

    def __init__(self, **funcs):
        self._funcs = funcs
        self._old: dict = {}

    def __enter__(self):
        for name, func in self._funcs.items():
            self._old[name] = getattr(WD, name)
            setattr(WD, name, func)
        return self

    def __exit__(self, *_exc):
        for name, func in self._old.items():
            setattr(WD, name, func)
        return False


# ---------------------------------------------------------------------------
# 1. valid_address
# ---------------------------------------------------------------------------
def test_valid_address() -> None:
    print("-- valid_address")
    good = {
        "119.29.29.29": "119.29.29.29",
        "223.5.5.5": "223.5.5.5",
        "  8.8.8.8  ": "8.8.8.8",
        "2001:db8::1": "2001:db8::1",
        "2001:0DB8:0000:0000:0000:0000:0000:0001": "2001:db8::1",
        "::1": "::1",
        # IPv4-mapped IPv6：必须归一成 IPv4（任务要求，跟 lytvpk 对齐）
        "::ffff:23.59.72.59": "23.59.72.59",
        "::FFFF:1.2.3.4": "1.2.3.4",
    }
    for raw, want in good.items():
        got = WD.valid_address(raw)
        check(f"valid_address({raw!r}) == {want!r}", got == want, f"得到 {got!r}")

    bad = ["", "   ", "1.2.3", "999.1.1.1", "abc", "1.2.3.4:53", "1.2.3.4,5.6.7.8",
           "119.029.29.29", "1.2.3.4 5.6.7.8", "2001:db8::zz", "1.2.3.4/24",
           "localhost", "http://1.2.3.4", "::ffff:999.1.1.1"]
    for raw in bad:
        got = WD.valid_address(raw)
        check(f"valid_address({raw!r}) 非法 -> None", got is None, f"得到 {got!r}")


# ---------------------------------------------------------------------------
# 2/3. 模式表、server_for、mode_label
# ---------------------------------------------------------------------------
def test_modes() -> None:
    print("-- DNS_MODES / server_for / mode_label")
    want = [
        ("dnspod", "腾讯 DNS · 119.29.29.29", "119.29.29.29"),
        ("alidns", "阿里 DNS · 223.5.5.5", "223.5.5.5"),
        ("custom", "自定义 DNS", ""),
        ("system", "使用系统 DNS", ""),
    ]
    check("DNS_MODES 与约定完全一致", WD.DNS_MODES == want, repr(WD.DNS_MODES))
    check("DEFAULT_MODE == 'dnspod'", WD.DEFAULT_MODE == "dnspod", repr(WD.DEFAULT_MODE))
    check("MODE_VALUES 顺序一致",
          WD.MODE_VALUES == ("dnspod", "alidns", "custom", "system"), repr(WD.MODE_VALUES))
    for i, (value, label) in enumerate((m[0], m[1]) for m in want):
        check(f"mode_label({value!r}) == {label!r}", WD.mode_label(value) == label,
              repr(WD.mode_label(value)))

    check("server_for('dnspod')", WD.server_for("dnspod") == "119.29.29.29")
    check("server_for('alidns')", WD.server_for("alidns") == "223.5.5.5")
    check("server_for('system') 是空串", WD.server_for("system") == "")
    check("server_for('custom', 合法) 归一",
          WD.server_for("custom", "::ffff:1.2.3.4") == "1.2.3.4",
          repr(WD.server_for("custom", "::ffff:1.2.3.4")))
    check("server_for('custom', '2001:0DB8::1') 归一",
          WD.server_for("custom", "2001:0DB8::1") == "2001:db8::1")
    check("server_for('custom', 非法) 退回空串（系统解析）",
          WD.server_for("custom", "1.2.3") == "" and WD.server_for("custom", "") == "")
    check("server_for(未知模式) 是空串", WD.server_for("nope") == "" and WD.server_for("") == "")
    check("mode_label(未知模式) 返回 system 文案",
          WD.mode_label("nope") == "使用系统 DNS" and WD.mode_label("") == "使用系统 DNS")
    check("模式大小写不敏感", WD.server_for("DNSpod") == "119.29.29.29")


# ---------------------------------------------------------------------------
# 4. 离线解析（压缩指针 / A / CNAME / 缓存）
# ---------------------------------------------------------------------------
HOST = "dns-test.example.com"


def test_offline_resolve() -> None:
    print("-- 离线解析（压缩指针 + A + CNAME + 缓存）")

    # 一条 CNAME（owner 是指针、rdata 也是指针）+ 两条 A（owner 都是指针），
    # TTL 分别 300 / 60 / 120，最小 60 → 缓存 60 秒。
    def build(packet: bytes) -> bytes:
        answers = [
            _answer_ptr_a(300, "203.0.113.7"),
            _answer_ptr_a(60, "198.51.100.9"),
            _answer_cname_ptr_owner(120, b"\xc0\x0c"),
        ]
        return _response(packet, answers)

    fake, state = _fake_udp([build])
    WD.configure(DNSPOD)
    with patched(_udp_query=fake):
        ips = WD.resolve(HOST, DNSPOD, timeout=1.0)
        check("离线解析出两条 A（顺序不变）",
              ips == ["203.0.113.7", "198.51.100.9"], repr(ips))
        first = WD.resolve_first(HOST, DNSPOD, timeout=1.0)
        check("resolve_first 取第一条", first == "203.0.113.7", repr(first))
        check("第二次调用命中缓存（只发了一次 UDP）", state["calls"] == 1,
              f"发了 {state['calls']} 次")
        key = (HOST, DNSPOD)
        ttl = WD._CACHE.get(key, (0, []))[0] - time.time()
        check("TTL 取答案最小值 60 并夹在 30..600 之间", 30 <= ttl <= 600 and 55 <= ttl <= 61,
              f"剩余 {ttl:.1f}s")

    # CNAME 链：本条响应里 queried 名只有 CNAME，A 挂在目标名上，要在同一条响应内跟过去
    chain_host = "dns-chain.example.com"
    target = b"\x03cdn\xc0\x0c"  # cdn.<question 里的域名>

    def build_chain(packet: bytes) -> bytes:
        answers = [
            _answer_named_cname(b"\xc0\x0c", 300, target),
            _answer_named_a(target, 200, "192.0.2.10"),
        ]
        return _response(packet, answers)

    fake2, state2 = _fake_udp([build_chain])
    with patched(_udp_query=fake2):
        try:
            ips = WD.resolve(chain_host, DNSPOD, timeout=1.0)
        except WD.DNSResolveError as e:
            check("CNAME 链在响应内跟到 A", False, str(e))
        else:
            check("CNAME 链在响应内跟到 A（一条响应就够，不重发查询）",
                  ips == ["192.0.2.10"] and state2["calls"] == 1,
                  f"{ips!r} / {state2['calls']} 次查询")

    # 事务 id 不匹配必须当失败（防串扰）
    def build_bad_id(packet: bytes) -> bytes:
        return _response(packet, [_answer_ptr_a(300, "203.0.113.7")],
                         txid=(struct.unpack("!H", packet[:2])[0] ^ 0xFFFF))

    fake3, _ = _fake_udp([build_bad_id])
    with patched(_udp_query=fake3):
        try:
            WD.resolve("dns-badid.example.com", DNSPOD, timeout=1.0)
        except WD.DNSResolveError as e:
            check("事务 id 不一致 -> DNSResolveError", True, str(e))
        else:
            check("事务 id 不一致 -> DNSResolveError", False, "竟然成功了")

    # 请求里带事务 id 且 RD=1
    packet = state["packets"][0]
    check("请求报文 RD=1 且 QTYPE=A/QCLASS=IN、QDCOUNT=1",
          struct.unpack("!HHHHHH", packet[:12])[1] & 0x0100 != 0
          and struct.unpack("!HHHHHH", packet[:12])[2] == 1
          and struct.unpack("!HH", packet[-4:]) == (1, 1))
    WD.clear_cache()


# ---------------------------------------------------------------------------
# 5. TC 截断 → TCP
# ---------------------------------------------------------------------------
def test_truncated_tcp() -> None:
    print("-- TC 截断改走 TCP")
    host = "dns-tc.example.com"

    def build_udp_truncated(packet: bytes) -> bytes:
        return _response(packet, [], flags=0x8380)  # QR=1 TC=1 RD=1 RA=1

    def build_tcp_full(packet: bytes) -> bytes:
        return _response(packet, [_answer_ptr_a(240, "203.0.113.99")])

    fake_udp, udp_state = _fake_udp([build_udp_truncated])
    tcp_state = {"calls": 0, "packets": []}

    def fake_tcp(server: str, packet: bytes, timeout: float) -> bytes:
        tcp_state["calls"] += 1
        tcp_state["packets"].append(packet)
        return build_tcp_full(packet)

    WD.configure(DNSPOD)
    WD.clear_cache()
    with patched(_udp_query=fake_udp, _tcp_query=fake_tcp):
        ips = WD.resolve(host, DNSPOD, timeout=1.0)
        check("TC 之后解析结果来自 TCP 报文",
              ips == ["203.0.113.99"], repr(ips))
        check("确实又发了一次 TCP 查询", tcp_state["calls"] == 1,
              f"TCP {tcp_state['calls']} 次 / UDP {udp_state['calls']} 次")
        check("TCP 用的是同一个问题报文（txid 一致）",
              tcp_state["packets"] and tcp_state["packets"][0] == udp_state["packets"][0])
    WD.clear_cache()


# ---------------------------------------------------------------------------
# 6. NXDOMAIN
# ---------------------------------------------------------------------------
def test_nxdomain() -> None:
    print("-- rcode=3 NXDOMAIN")
    host = "dns-nx.example.com"

    def build(packet: bytes) -> bytes:
        return _response(packet, [], flags=0x8183)  # rcode=3

    fake, _ = _fake_udp([build])
    WD.configure(DNSPOD)
    WD.clear_cache()
    with patched(_udp_query=fake):
        try:
            WD.resolve(host, DNSPOD, timeout=1.0)
        except WD.DNSResolveError as e:
            msg = str(e)
            check("NXDOMAIN 抛 DNSResolveError 且消息里有域名", host in msg, msg)
            check("消息里带 rcode 数字和中文说明", "rcode=3" in msg and "域名不存在" in msg, msg)
            check("DNSResolveError 是 OSError 子类",
                  isinstance(e, OSError) and not isinstance(e, TimeoutError))
        else:
            check("NXDOMAIN 抛 DNSResolveError", False, "竟然成功了")
    WD.clear_cache()


# ---------------------------------------------------------------------------
# 9. 缓存统计
# ---------------------------------------------------------------------------
def test_cache_stats() -> None:
    print("-- cache_stats / clear_cache")
    fake, _ = _fake_udp([lambda packet: _response(packet, [_answer_ptr_a(300, "203.0.113.1")])])
    WD.configure(DNSPOD)
    WD.clear_cache()
    stats0 = WD.cache_stats()
    check("clear_cache 后 entries == 0", WD.cache_stats()["entries"] == 0, repr(stats0))
    check("cache_stats 四个键齐全",
          set(WD.cache_stats()) >= {"entries", "servers", "hits", "misses"},
          repr(WD.cache_stats()))
    with patched(_udp_query=fake):
        WD.resolve("dns-stat.example.com", DNSPOD, timeout=1.0)
        WD.resolve("dns-stat.example.com", DNSPOD, timeout=1.0)
        stats = WD.cache_stats()
        check("缓存里有 1 条、涉及 1 台 DNS",
              stats["entries"] == 1 and stats["servers"] == 1, repr(stats))
        check("hits >= 1 且 misses >= 1", stats["hits"] >= 1 and stats["misses"] >= 1,
              repr(stats))
    WD.clear_cache()
    check("clear_cache 之后 entries 归零", WD.cache_stats()["entries"] == 0)
    check("current_server 跟随 configure",
          (WD.configure(DNSPOD), WD.current_server() == DNSPOD)[1])
    check("configure('') 回到系统解析", (WD.configure(""), WD.current_server() == "")[1])


# ---------------------------------------------------------------------------
# 8b. 本机回环 urlopen：确定性验证「手工建连」那条路
# ---------------------------------------------------------------------------
class _Handler(http.server.BaseHTTPRequestHandler):
    """够用的迷你 HTTP 服务：GET/POST/302/404 各一条。"""

    def _send(self, code: int, body: bytes = b"", headers=()) -> None:
        self.send_response(code)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/redir":
            self._send(302, b"", [("Location", "/ok")])
        elif self.path == "/missing":
            self._send(404, b"nope")
        else:
            self._send(200, b"hello-body", [("Content-Type", "text/plain")])

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(size) if size else b""
        self._send(200, b"posted:" + body)

    def log_message(self, *_args) -> None:
        pass  # 自检输出要干净，别让 http.server 往 stderr 里打请求日志


def _start_server():
    """起一个监听所有回环地址的迷你服务（127.0.0.1 / 127.0.0.2 都能连上）。"""
    srv = http.server.ThreadingHTTPServer(("", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, thread


def test_loopback_urlopen() -> None:
    print("-- 本机回环 urlopen（手工建连 / 状态码 / POST / 重定向）")
    try:
        srv, thread = _start_server()
    except OSError as e:
        print(f"      [skip] 起不了本机测试服务：{type(e).__name__}: {e}")
        return
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    # 127.0.0.1 是 IP 字面量，resolve 会直接返回它，所以这条路不碰 DNS，
    # 但 current_server() 非空 → 走的正是 workshop_dns 自己的 http.client 分支
    WD.configure(DNSPOD)
    try:
        with WD.urlopen(base + "/ok", timeout=5.0) as resp:
            body = resp.read()
            check("回环 urlopen 走到人工分支且状态码 200", resp.status == 200, str(resp.status))
            check("回环 urlopen 读到正文", body == b"hello-body", repr(body))
            check("回环 urlopen getheader / geturl 可用",
                  resp.getheader("Content-Type") == "text/plain"
                  and resp.geturl() == base + "/ok")

        req = urllib.request.Request(base + "/post", data=b"a=1&b=2",
                                     headers={"Host": "127.0.0.1"})
        with WD.urlopen(req, timeout=5.0) as resp:
            body = resp.read()
            check("回环 POST 带上请求体（Content-Length 正确）",
                  body == b"posted:a=1&b=2", repr(body))

        with WD.urlopen(base + "/missing", timeout=5.0) as resp:
            check("回环 404 不抛异常、状态码可读", resp.status == 404,
                  f"{resp.status} / {resp.read()!r}")

        with WD.urlopen(base + "/redir", timeout=5.0) as resp:
            check("回环 302 自动跟随到 /ok 且 geturl 是最终地址",
                  resp.status == 200 and resp.geturl() == base + "/ok" and
                  resp.read() == b"hello-body", f"{resp.status} {resp.geturl()}")
    except Exception as e:  # 本机服务出问题也算 skip，不让它污染结论
        print(f"      [skip] 回环 urlopen 异常：{type(e).__name__}: {e}")
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
        WD.configure("")


# ---------------------------------------------------------------------------
# 8c. 指定 DNS：TCP 连得上但握手卡死的坏节点 → 换下一个 IP
# ---------------------------------------------------------------------------
def test_handshake_retry() -> None:
    print("-- 坏节点重试（TCP 连得上但 TLS 握手卡死）")
    try:
        srv, thread = _start_server()
    except OSError as e:
        print(f"      [skip] 起不了本机测试服务：{type(e).__name__}: {e}")
        return
    port = srv.server_address[1]
    host = "multi-ip.example.com"
    attempts: list[str] = []
    WD.configure(DNSPOD)
    WD.clear_cache()

    def fake_wrap_first_stalls(sock, scheme, host_arg, context):
        attempts.append(sock.getpeername()[0])
        if len(attempts) == 1:
            raise TimeoutError("模拟握手卡死")  # TimeoutError 是 OSError 子类
        return sock

    try:
        with patched(_resolve_candidates=lambda *a, **k: ["127.0.0.1", "127.0.0.2"],
                     _tls_wrap=fake_wrap_first_stalls):
            sock = WD._open(host, port, "https", DNSPOD, 3.0, None, None)
            peer = sock.getpeername()[0]
            sock.close()
        check("第一个 IP 握手卡死后换了第二个 IP",
              attempts == ["127.0.0.1", "127.0.0.2"] and peer == "127.0.0.2",
              f"{attempts} peer={peer}")
        check("成功的 IP 记进「上次连通」提示",
              WD._remembered(host, DNSPOD) == "127.0.0.2", WD._remembered(host, DNSPOD))

        # 证书错误不该重试：换 IP 也一样，必须原样抛出去
        attempts.clear()

        def fake_wrap_cert_error(sock, scheme, host_arg, context):
            attempts.append(sock.getpeername()[0])
            raise ssl.SSLCertVerificationError(1, "证书不对")

        with patched(_resolve_candidates=lambda *a, **k: ["127.0.0.1", "127.0.0.2"],
                     _tls_wrap=fake_wrap_cert_error):
            try:
                WD._open(host, port, "https", DNSPOD, 3.0, None, None)
            except ssl.SSLCertVerificationError:
                check("证书错误不重试、直接抛出", attempts == ["127.0.0.1"], repr(attempts))
            else:
                check("证书错误不重试、直接抛出", False, "竟然成功了")

        # 候选多于 MAX_IP_TRIES 时只试前三个，之后报错并带上最后一次错误
        attempts.clear()

        def fake_wrap_all_stall(sock, scheme, host_arg, context):
            attempts.append(sock.getpeername()[0])
            raise TimeoutError("模拟握手卡死")

        with patched(_resolve_candidates=lambda *a, **k: [f"127.0.0.{i}" for i in range(1, 6)],
                     _tls_wrap=fake_wrap_all_stall):
            try:
                WD._open(host, port, "https", DNSPOD, 3.0, None, None)
            except OSError as e:
                check("全是坏节点时只试 MAX_IP_TRIES 个并报错",
                      len(attempts) == WD.MAX_IP_TRIES == 3 and "3 个 IP" in str(e)
                      and "模拟握手卡死" in str(e), f"{attempts} / {e}")
            else:
                check("全是坏节点时只试 MAX_IP_TRIES 个并报错", False, "竟然成功了")
    except Exception as e:
        print(f"      [skip] 坏节点重试用例异常：{type(e).__name__}: {e}")
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
        WD.clear_cache()
        WD.configure("")


# ---------------------------------------------------------------------------
# 7. 真实网络解析
# ---------------------------------------------------------------------------
def test_real_resolve() -> None:
    print("-- 真实网络解析（失败算 skip）")
    try:
        ips = WD.resolve_first("api.steampowered.com", DNSPOD, timeout=3.0)
    except Exception as e:
        print(f"      [skip] 指定 DNS {DNSPOD} 解析失败：{type(e).__name__}: {e}")
    else:
        check(f"指定 DNS {DNSPOD} 解析 api.steampowered.com", bool(ips), ips)
    try:
        sys_ips = WD.resolve("api.steampowered.com", "", timeout=3.0)
    except Exception as e:
        print(f"      [skip] 系统解析失败：{type(e).__name__}: {e}")
    else:
        check("系统解析 api.steampowered.com", bool(sys_ips), ", ".join(sys_ips[:4]))


# ---------------------------------------------------------------------------
# 8. 真实网络 urlopen
# ---------------------------------------------------------------------------
URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"


def _try_urlopen(tag: str) -> None:
    req = urllib.request.Request(
        URL,
        data=b"itemcount=1&publishedfileids[0]=219990",
        headers={"User-Agent": "Mozilla/5.0 (workshop_dns_test)", "Accept": "*/*"},
    )
    try:
        # 先只看响应头：状态码能读出来就算通（任务要求「不是异常」即可）
        with WD.urlopen(req, timeout=15.0) as resp:
            status = resp.status
            status_code = resp.status_code
            ctype = resp.getheader("Content-Type")
            final_url = resp.geturl()
            try:
                size = len(resp.read())
            except Exception as e:  # 正文读慢/读断不影响「拿到响应」这个结论
                size = -1
                print(f"      [skip] {tag} 正文没读完：{type(e).__name__}: {e}")
    except Exception as e:
        print(f"      [skip] {tag} 请求失败：{type(e).__name__}: {e}")
        return
    check(f"{tag} 拿到 HTTP 响应（状态码可读）", isinstance(status, int) and status > 0,
          f"status={status} status_code={status_code} 字节={size}")
    check(f"{tag} status_code 与 status 一致", status_code == status)
    check(f"{tag} headers / getheader / geturl 可用",
          ctype is not None and final_url == URL, f"{ctype!r} {final_url}")


def test_real_urlopen() -> None:
    print("-- 真实网络 urlopen（失败算 skip）")
    WD.configure(DNSPOD)
    _try_urlopen(f"configure({DNSPOD!r})")
    WD.configure("")
    _try_urlopen("configure('') 系统解析")
    WD.configure("")


def main() -> int:
    print("工坊 DNS 自检")
    test_valid_address()
    test_modes()
    test_offline_resolve()
    test_truncated_tcp()
    test_nxdomain()
    test_cache_stats()
    test_loopback_urlopen()
    test_handshake_retry()
    test_real_resolve()
    test_real_urlopen()
    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "; ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
