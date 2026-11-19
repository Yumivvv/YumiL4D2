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

"""工坊封面加速代理：本地小 HTTP 服务，替 QML 去取 Steam 封面。

## 为什么必须有这一层

「工坊 CDN 加速」的想法是：不走 DNS，直接连一个离你近的 Steam 节点。
下载文件时我们能用 `http.client` 手工建连接（Host 头写域名、SNI 写域名，
只是把「连到哪」换成节点 IP），所以证书照样对得上。

但 **QML 的 Image 组件做不到这件事**：

  * 它没有「自定义 Host / SNI」的入口；
  * 直接把图片地址里的域名换成 IP 的话，Qt 会拿证书去核对「这个 IP」，
    而证书是签给 `*.steamusercontent.com` 的 —— 直接报证书不匹配，图就白了；
  * 也不能挂 sslErrors 忽略（QML 没有这个钩子），而且忽略证书本身就是坏主意。

所以这里起一个只监听 `127.0.0.1` 的小服务：QML 照常发普通的 http 请求，
我们在 Python 里替它走节点 IP、按域名做 TLS 校验，再把字节原样吐回去。

## 第二次改造：为什么浏览还是慢

实测单个工坊封面原图有 **800 KB 上下**（PNG 大图），而卡片本身只有
200 px 宽。一屏 12 张就是 10 MB，滚动起来当然卡。

于是这一层顺便干三件事：

  1. **只发缩略图**：拉到原图后立刻用 Pillow 压到 360 px 宽的 JPEG（约 20 KB），
     QML 拿到的就是能直接显示的小图；原图再大也只走一次内网。
  2. **磁盘缓存**：缩略图落 `data/cache/covers/`，重启程序、来回切分类都不用重下。
  3. **并发闸门**：最多 8 条上游连接，避免一屏几十张图把节点掐死。

外部怎么看：

  * 只绑回环地址，端口由系统分配（0），不对外暴露；
  * 只接受 `http://127.0.0.1:<port>/c?u=<原始地址>&w=<宽度>` 这一种形态；
  * 原始地址只允许 Steam 的两三个 CDN 域名 —— 别人拿它当跳板去访问内网是不行的。
"""
from __future__ import annotations

import hashlib
import io
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Iterable

from . import workshop_dns as WDNS
from . import workshop_net as WN
from .util import CACHE_DIR, Log

log = Log("imageproxy.log")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 只代理这些域名的图（工坊封面 / 作者头像 / 下载直链同族）
_ALLOWED_HOSTS = {
    "images.steamusercontent.com",
    "cdn.steamusercontent.com",
    "steamuserimages-a.akamaihd.net",
    "avatars.steamstatic.com",
    "avatars.akamai.steamstatic.com",
}

# 单张原图最多 12 MB（实测工坊封面 100-800 KB，留足余量）
MAX_BYTES = 12 * 1024 * 1024
# 内存缓存条目上限：滚动几千张卡片也不会把内存吃光
CACHE_LIMIT = 600
# 缩略图默认宽度：卡片实际显示 200 px 左右，留 1.8 倍给高分屏足够
THUMB_WIDTH = 360
# 最大并发上游连接数（缩略图都很快，闸门只是为了别把节点掐死）
MAX_FETCHERS = 8
# 走系统 DNS 直连的并发（慢，单独一条闸门，别占着节点那条）
DIRECT_FETCHERS = 3
# 一次 prefetch 最多预热几张
PREFETCH_LIMIT = 18

_THUMB_DIR = os.path.join(CACHE_DIR, "covers")


def _content_type(data: bytes) -> str:
    """按文件头认图片类型。省一次上游请求，也不信任上游乱写的头。"""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return "application/octet-stream"


def _clamp_width(value: object) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return THUMB_WIDTH
    return max(64, min(1280, n))


def _thumb_key(url: str, width: int) -> str:
    return hashlib.sha1(f"{url}|{width}".encode("utf-8")).hexdigest()


def make_thumb(data: bytes, width: int = THUMB_WIDTH) -> bytes:
    """把原图压成 `width` 宽的 JPEG；没装 Pillow 或压不动就原样返回。

    用 Pillow 而不是 Qt：QML 的 `sourceSize` 只影响**解码**尺寸，
    字节还是得完整下载，这正是慢的根源。这一层是「下载也变小」。
    """
    if not data:
        return b""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001  没 Pillow 就退化成原图
        return data
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        if img.width <= width + 8:
            # 本来就够小：不值得再压一次（重编码反而更糊）
            return data
        if img.mode not in ("RGB", "L"):
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (16, 18, 24))
                conv = img.convert("RGBA")
                bg.paste(conv, mask=conv.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")
        ratio = width / float(img.width)
        img = img.resize((width, max(1, int(img.height * ratio))), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=82, optimize=True, progressive=True)
        small = out.getvalue()
        return small if 0 < len(small) < len(data) else data
    except Exception:  # noqa: BLE001  任何一张图压不了都不能影响其它图
        return data


class CoverProxy:
    """封面代理服务本体。

    `node_provider` 每次取图片时调用一次，返回当前要用的节点 IP
    （空串 = 不加速，走系统 DNS）。这样设置里换节点不需要重启代理。
    """

    def __init__(self, node_provider: Callable[[], str] | None = None):
        self._node_provider = node_provider or (lambda: "")
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port = 0
        self._cache: dict[str, bytes] = {}
        self._cache_order: list[str] = []
        self._lock = threading.Lock()
        self._last_node = ""
        self._gate = threading.Semaphore(MAX_FETCHERS)
        self._gate_direct = threading.Semaphore(DIRECT_FETCHERS)
        self._inflight: dict[str, threading.Event] = {}
        self._stats_lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._disk_dir = ""
        try:
            os.makedirs(_THUMB_DIR, exist_ok=True)
            self._disk_dir = _THUMB_DIR
        except OSError as e:  # noqa: BLE001  写不了盘就纯内存
            log(f"thumb dir unavailable: {e!r}")

    # ------------------------------------------------------------ 生命周期
    def start(self) -> int:
        """起服务（幂等），返回端口；失败返回 0。"""
        if self._port:
            return self._port
        proxy = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args) -> None:  # 别把每张图都打进 stderr
                return

            def do_GET(self) -> None:  # noqa: N802  http.server 的约定
                try:
                    proxy._serve(self)
                except Exception as e:  # noqa: BLE001  一张图失败不能拖垮服务
                    log(f"proxy serve failed: {e!r}")
                    try:
                        self.send_error(502)
                    except OSError:
                        pass

            do_HEAD = do_GET

        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        except OSError as e:
            log(f"proxy start failed: {e!r}")
            return 0
        server.daemon_threads = True
        self._server = server
        self._port = server.server_address[1]
        self._thread = threading.Thread(target=server.serve_forever,
                                        kwargs={"poll_interval": 0.3},
                                        daemon=True)
        self._thread.start()
        log(f"cover proxy listening on 127.0.0.1:{self._port}")
        return self._port

    def stop(self) -> None:
        server, self._server = self._server, None
        self._port = 0
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except OSError:
                pass
        self._thread = None

    @property
    def port(self) -> int:
        return self._port

    def stats(self) -> dict:
        with self._stats_lock:
            return {"hits": self._hits, "misses": self._misses,
                    "memory": len(self._cache), "port": self._port,
                    "disk": bool(self._disk_dir)}

    # ------------------------------------------------------------ 对外地址
    def wrap(self, url: str, width: int = THUMB_WIDTH) -> str:
        """把原始图片地址包成代理地址；包不了（或没起来）就原样返回。"""
        raw = str(url or "").strip()
        if not raw:
            return ""
        if not raw.lower().startswith(("http://", "https://")):
            return raw
        if not self._port:
            return raw
        try:
            host = (urllib.parse.urlsplit(raw).hostname or "").lower()
        except ValueError:
            return raw
        if host not in _ALLOWED_HOSTS:
            return raw
        return (f"http://127.0.0.1:{self._port}/c?w={_clamp_width(width)}&u="
                + urllib.parse.quote(raw, safe=""))

    # ------------------------------------------------------------ 缓存
    def clear_cache(self, disk: bool = False) -> None:
        with self._lock:
            self._cache.clear()
            self._cache_order.clear()
        if disk and self._disk_dir:
            try:
                for name in os.listdir(self._disk_dir):
                    if name.endswith(".jpg"):
                        os.remove(os.path.join(self._disk_dir, name))
            except OSError:
                pass

    def _cache_get(self, key: str) -> bytes | None:
        with self._lock:
            return self._cache.get(key)

    def _cache_put(self, key: str, data: bytes) -> None:
        if not data or len(data) > MAX_BYTES:
            return
        with self._lock:
            if key not in self._cache:
                self._cache_order.append(key)
            self._cache[key] = data
            while len(self._cache_order) > CACHE_LIMIT:
                old = self._cache_order.pop(0)
                self._cache.pop(old, None)

    # 磁盘缓存 ---------------------------------------------------------
    def _disk_get(self, key: str) -> bytes:
        if not self._disk_dir:
            return b""
        path = os.path.join(self._disk_dir, key + ".jpg")
        try:
            if os.path.getsize(path) > 0:
                with open(path, "rb") as fh:
                    return fh.read()
        except OSError:
            return b""
        return b""

    def _disk_put(self, key: str, data: bytes) -> None:
        if not self._disk_dir or not data:
            return
        path = os.path.join(self._disk_dir, key + ".jpg")
        tmp = path + ".tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ------------------------------------------------------------ 取图
    def _node(self) -> str:
        try:
            node = str(self._node_provider() or "").strip()
        except Exception:  # noqa: BLE001  取节点失败就当没加速
            node = ""
        # 换了节点就把内存缓存扔了：同一张图在不同节点上是同一份内容，
        # 但旧缓存是「上一个节点还能用时」抓的，留着会掩盖新节点的问题。
        # 磁盘缓存不清 —— 图的内容和节点无关，清了只是白白重下。
        if node != self._last_node:
            self._last_node = node
            self.clear_cache(disk=False)
        return node

    def fetch(self, url: str, width: int = THUMB_WIDTH) -> bytes:
        """取一张缩略图（带内存 + 磁盘缓存）。"""
        raw = str(url or "").strip()
        if not raw:
            return b""
        width = _clamp_width(width)
        key = _thumb_key(raw, width)
        cached = self._cache_get(key)
        if cached:
            with self._stats_lock:
                self._hits += 1
            return cached
        on_disk = self._disk_get(key)
        if on_disk:
            self._cache_put(key, on_disk)
            with self._stats_lock:
                self._hits += 1
            return on_disk

        # 同一张图被格子重复请求时只抓一次，其它线程等结果
        wait_ev: threading.Event | None = None
        with self._lock:
            ev = self._inflight.get(key)
            if ev is None:
                ev = threading.Event()
                self._inflight[key] = ev
            else:
                wait_ev = ev
        if wait_ev is not None:
            wait_ev.wait(timeout=15.0)
            again = self._cache_get(key) or self._disk_get(key)
            if again:
                self._cache_put(key, again)
                return again

        try:
            with self._stats_lock:
                self._misses += 1
            node = self._node()
            data = b""
            if node and WN.is_steam_cdn_url(raw):
                with self._gate:
                    data = WN.fetch_bytes_via_ip(raw, node, timeout=12.0,
                                                 max_bytes=MAX_BYTES)
            if not data:
                # 回落到系统 DNS 时用另一把闸门：直连本来就慢（还可能超时），
                # 让它占着节点的闸门会把其它图的直连也一起拖住。
                with self._gate_direct:
                    data = self._fetch_direct(raw)
            if data:
                thumb = make_thumb(data, width)
                self._cache_put(key, thumb)
                self._disk_put(key, thumb)
                return thumb
            return b""
        finally:
            with self._lock:
                self._inflight.pop(key, None)
            if wait_ev is None:
                ev.set()

    def prefetch(self, urls: Iterable[str], width: int = THUMB_WIDTH,
                 limit: int = PREFETCH_LIMIT) -> int:
        """后台预热一批封面，滚动到下一屏时图已经在本地了。

        只预热还没有缓存的；最多 limit 张、最多 4 条线程 ——
        别让预热把正常请求的带宽抢光。
        """
        todo: list[str] = []
        seen: set[str] = set()
        w = _clamp_width(width)
        for raw in urls or []:
            u = str(raw or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            # 缓存 key 用**原始地址**算（和 fetch 的口径一致）；也必须把原始地址
            # 交给 fetch —— 之前这里传的是 wrap() 出来的代理地址，于是 fetch 先
            # 去抓 127.0.0.1（自己），内层再抓真正的图，两层都要拿 _gate，
            # 8 个预热线程把闸门占满 → 死锁 12 秒后全部失败。
            if self._cache_get(_thumb_key(u, w)) or self._disk_get(_thumb_key(u, w)):
                continue
            todo.append(u)
            if len(todo) >= max(1, limit):
                break
        if not todo:
            return 0

        def _one(u: str) -> None:
            try:
                self.fetch(u, width)
            except Exception:  # noqa: BLE001
                pass

        for i in range(0, len(todo), 4):
            batch = [threading.Thread(target=_one, args=(u,), daemon=True)
                     for u in todo[i:i + 4]]
            for t in batch:
                t.start()
        return len(todo)

    @staticmethod
    def _fetch_direct(url: str) -> bytes:
        """按设置里的工坊 DNS 解析后直连（拿不到自定义 DNS 就退系统解析）。

        以前用的是 urllib 默认解析，于是「工坊 DNS」这个设置对封面不生效。
        """
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Referer": "https://steamcommunity.com/"})
        try:
            with WDNS.urlopen(req, timeout=12.0) as resp:
                return resp.read(MAX_BYTES)
        except (urllib.error.URLError, TimeoutError, OSError):
            return b""

    # ------------------------------------------------------------ 请求处理
    def _serve(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urllib.parse.urlsplit(handler.path)
        if parsed.path not in ("/c", "/cover"):
            handler.send_error(404)
            return
        qs = urllib.parse.parse_qs(parsed.query)
        target = (qs.get("u", [""])[0] or "").strip()
        if not target:
            handler.send_error(400, "missing u")
            return
        width = _clamp_width(qs.get("w", [THUMB_WIDTH])[0])
        try:
            host = (urllib.parse.urlsplit(target).hostname or "").lower()
        except ValueError:
            handler.send_error(400, "bad u")
            return
        if host not in _ALLOWED_HOSTS:
            handler.send_error(403, "host not allowed")
            return

        data = self.fetch(target, width)
        if not data:
            handler.send_error(502, "fetch failed")
            return
        etag = '"' + _thumb_key(target, width)[:20] + '"'
        if (handler.headers.get("If-None-Match") or "").strip() == etag:
            handler.send_response(304)
            handler.send_header("ETag", etag)
            handler.send_header("Cache-Control", "public, max-age=604800")
            handler.end_headers()
            return
        ctype = _content_type(data)
        handler.send_response(200)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", "public, max-age=604800")
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(data)
