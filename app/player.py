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

"""内置播放器：流式播放 B 站视频（边下边播，不落地整份文件）.

关于解码：
    PySide6 自带的 Qt WebEngine 不带 H.264 解码（实测 canPlayType('avc1')=NO），
    所以 B 站网页播放器嵌不进来。这里用 QtMultimedia（内置 FFmpeg 7.x，支持 H.264）。

关于播放方式：
    QtMultimedia 的 QMediaPlayer 不让我们自定义请求头，upos CDN 缺 Referer 会 403。
    做法是本机起一个 **本地流代理**（127.0.0.1:随机端口）：
        player <- http://127.0.0.1:port/stream  <- 代理带 Referer 转发 <- upos CDN
    这样 QMediaPlayer 只需顺序读本地 HTTP 流，实现真正的"边下边播"，
    不会在磁盘留下整份视频文件。

关于缓存：
    只有用户主动打开的、较大概率会回看的视频才写盘（默认关闭，可在设置里开）。
"""
from __future__ import annotations

import http.server
import os
import socket
import threading
import time
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

from .bili import BiliClient, BiliError
from .util import CACHE_DIR, Log
from .util import human_size

log = Log("player.log")

PLAYER_DIR = os.path.join(CACHE_DIR, "video")


def _ensure_dir() -> None:
    os.makedirs(PLAYER_DIR, exist_ok=True)


# ===========================================================================
# 本地流代理：解决 CDN 校验 Referer 的问题，同时避免整份文件落盘
# ===========================================================================
class _StreamProxy:
    """极简 HTTP 反向代理，把 upos 的流带 Referer 转发给 QMediaPlayer。"""

    def __init__(self) -> None:
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._upstream = ""
        self._referer = ""
        self.port = 0
        self._lock = threading.Lock()

    def set_source(self, upstream: str, referer: str) -> None:
        with self._lock:
            self._upstream = upstream
            self._referer = referer

    def start(self) -> int:
        if self._server is not None:
            return self.port

        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # 静音
                pass

            def do_GET(self):
                proxy._handle(self)

            def do_HEAD(self):
                proxy._handle(self, head_only=True)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        log(f"stream proxy on 127.0.0.1:{self.port}")
        return self.port

    def stop(self) -> None:
        srv, self._server = self._server, None
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except OSError:
                pass

    # ------------------------------------------------------------------
    def _handle(self, h: http.server.BaseHTTPRequestHandler, head_only: bool = False) -> None:
        with self._lock:
            upstream = self._upstream
            referer = self._referer
        if not upstream:
            h.send_error(503, "no source")
            return

        # 透传 Range，让 QMediaPlayer 能 seek
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": referer or "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "Accept": "*/*",
        }
        rng = h.headers.get("Range")
        if rng:
            headers["Range"] = rng

        try:
            r = requests.get(upstream, headers=headers, stream=True, timeout=(10, 60))
        except requests.RequestException as e:
            log(f"proxy upstream error: {e}")
            try:
                h.send_error(502, "upstream failed")
            except OSError:
                pass
            return

        if r.status_code not in (200, 206):
            log(f"proxy upstream status {r.status_code}")
            try:
                h.send_error(r.status_code)
            except OSError:
                pass
            r.close()
            return

        try:
            h.send_response(r.status_code)
            h.send_header("Content-Type", r.headers.get("Content-Type", "video/mp4"))
            length = r.headers.get("Content-Length")
            if length:
                h.send_header("Content-Length", length)
            cr = r.headers.get("Content-Range")
            if cr:
                h.send_header("Content-Range", cr)
            h.send_header("Accept-Ranges", "bytes")
            h.end_headers()
            if head_only:
                return

            for chunk in r.iter_content(64 * 1024):
                if not chunk:
                    continue
                h.wfile.write(chunk)
        except (OSError, ConnectionError):
            pass  # 播放器主动断开（seek / 关闭）很正常
        finally:
            r.close()


# ===========================================================================
# 播放器
# ===========================================================================
class VideoPlayer(QObject):
    """给 QML 用的播放器封装（QML 侧只放 VideoOutput 和控制条）."""

    stateChanged = Signal()
    positionChanged = Signal()
    errorOccurred = Signal(str)
    loadingChanged = Signal()
    titleChanged = Signal()

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        _ensure_dir()
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._cfg = config          # Config 实例（可空），用来记住音量/静音

        # 音量与静音跨会话记住：下次进来还是上次的状态
        try:
            vol = int(self._cfg["player_volume"]) if self._cfg is not None else 80
        except (TypeError, ValueError):
            vol = 80
        self._volume = max(0, min(100, vol))
        muted = bool(self._cfg["player_muted"]) if self._cfg is not None else False
        self._muted = muted
        self._audio.setVolume(self._volume / 100.0)
        self._audio.setMuted(muted)
        self._player.setAudioOutput(self._audio)

        self._proxy = _StreamProxy()

        self._bvid = ""
        self._title = ""
        self._loading = False
        self._ready = False
        self._stream_url = ""

        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(lambda _: self.stateChanged.emit())
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)

    # ================================================================ 属性
    @Property(QObject, constant=True)
    def mediaPlayer(self):
        return self._player

    @Slot(QObject)
    def attachOutput(self, sink) -> None:
        """把 QML 里 VideoOutput.videoSink 接到播放器上。"""
        if sink is None:
            return
        if isinstance(sink, QVideoSink):
            self._player.setVideoSink(sink)
            log("video sink attached")

    @Property(bool, notify=loadingChanged)
    def loading(self) -> bool:
        return self._loading

    @Property(bool, notify=stateChanged)
    def ready(self) -> bool:
        return self._ready

    @Property(bool, notify=stateChanged)
    def playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @Property(int, notify=positionChanged)
    def position(self) -> int:
        return int(self._player.position())

    @Property(int, notify=positionChanged)
    def duration(self) -> int:
        return int(self._player.duration())

    @Property(str, notify=positionChanged)
    def positionText(self) -> str:
        return _fmt_ms(self._player.position())

    @Property(str, notify=positionChanged)
    def durationText(self) -> str:
        return _fmt_ms(self._player.duration())

    @Property(str, notify=titleChanged)
    def title(self) -> str:
        return self._title

    @Property(str, notify=titleChanged)
    def bvid(self) -> str:
        return self._bvid

    @Property(bool, notify=stateChanged)
    def muted(self) -> bool:
        return self._muted

    @Property(int, notify=stateChanged)
    def volume(self) -> int:
        return self._volume

    @Property(float, notify=stateChanged)
    def rate(self) -> float:
        return float(self._player.playbackRate())

    @Property(bool, notify=stateChanged)
    def streaming(self) -> bool:
        """当前是否为在线流式播放（不落盘）。"""
        return bool(self._stream_url)

    # ================================================================ 播放
    @Slot(str, str)
    def open(self, bvid: str, title: str = "") -> None:
        if not bvid:
            return
        self.stop_internal(keep_title=False)

        self._bvid = bvid
        self._title = title or bvid
        self.titleChanged.emit()

        self._loading = True
        self.loadingChanged.emit()
        self.errorOccurred.emit("")
        threading.Thread(target=self._prepare_worker, args=(bvid,), daemon=True).start()

    def _prepare_worker(self, bvid: str) -> None:
        client = BiliClient(timeout=20)
        try:
            url, _size = client.video_stream(bvid)
        except BiliError as e:
            self._fail(str(e))
            return

        # 起本地代理，把它指向上游 CDN
        port = self._proxy.start()
        self._proxy.set_source(url, f"https://www.bilibili.com/video/{bvid}")
        self._stream_url = f"http://127.0.0.1:{port}/stream.mp4"

        log(f"stream ready {bvid} -> {self._stream_url}")
        self._use_stream(self._stream_url)

    def _use_stream(self, url: str) -> None:
        self._ready = True
        self._loading = False
        self.loadingChanged.emit()
        self._player.setSource(QUrl(url))
        self._player.play()
        self.stateChanged.emit()

    def _fail(self, msg: str) -> None:
        self._loading = False
        self._ready = False
        self.loadingChanged.emit()
        self.stateChanged.emit()
        log(f"player error: {msg}")
        self.errorOccurred.emit(msg)

    @Slot()
    def togglePlay(self) -> None:
        if not self._ready:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    @Slot()
    def play(self) -> None:
        if self._ready:
            self._player.play()

    @Slot()
    def pause(self) -> None:
        self._player.pause()

    @Slot()
    def stop(self) -> None:
        """彻底停止：断源 + 停代理，确保关闭后不会继续播放或继续拉流。"""
        self.stop_internal(keep_title=True)

    def stop_internal(self, keep_title: bool = True) -> None:
        try:
            self._player.stop()
            self._player.setSource(QUrl())  # 断开流，代理连接会随之关闭
        except RuntimeError:
            pass
        self._proxy.stop()
        self._stream_url = ""
        self._ready = False
        self._loading = False
        if not keep_title:
            self._title = ""
        self.stateChanged.emit()
        self.loadingChanged.emit()
        self.titleChanged.emit()

    @Slot(int)
    def seek(self, ms: int) -> None:
        if self._ready:
            self._player.setPosition(max(0, int(ms)))

    @Slot(int)
    def seekRelative(self, delta_ms: int) -> None:
        if self._ready:
            self._player.setPosition(
                max(0, min(self._player.duration(), self._player.position() + int(delta_ms)))
            )

    # ---------------------------------------------------------------- 音量
    def _save_audio_state(self) -> None:
        """把音量/静音写进配置，下次打开视频还是这个状态。"""
        if self._cfg is None:
            return
        try:
            self._cfg["player_volume"] = int(self._volume)
            self._cfg["player_muted"] = bool(self._muted)
            self._cfg.save()
        except Exception as e:  # noqa: BLE001
            log(f"save audio state failed: {e!r}")

    @Slot()
    def toggleMute(self) -> None:
        self._muted = not self._muted
        self._audio.setMuted(self._muted)
        self._save_audio_state()
        self.stateChanged.emit()

    @Slot(int)
    def setVolume(self, percent: int) -> None:
        """设置音量 0-100（大于 0 就顺手解除静音）。"""
        v = max(0, min(100, int(percent)))
        self._volume = v
        self._audio.setVolume(v / 100.0)
        if v > 0 and self._muted:
            self._muted = False
            self._audio.setMuted(False)
        self._save_audio_state()
        self.stateChanged.emit()

    @Slot(int)
    def changeVolume(self, delta: int) -> None:
        """相对调节音量，供 +/- 按钮和滚轮使用。"""
        self.setVolume(self._volume + int(delta))


    @Slot(int)
    def previewVolume(self, percent: int) -> None:
        """拖动中只改声音，不写盘（松手时再调 setVolume 落盘）。"""
        v = max(0, min(100, int(percent)))
        self._volume = v
        self._audio.setVolume(v / 100.0)
        if v > 0 and self._muted:
            self._muted = False
            self._audio.setMuted(False)
        self.stateChanged.emit()

    @Slot(float)
    def setRate(self, rate: float) -> None:
        self._player.setPlaybackRate(max(0.25, min(3.0, rate)))
        self.stateChanged.emit()

    # ---------------------------------------------------------------- 缓存
    # 这里原来有 cacheSize() / clearCache()，对着 `cache/video/` 统计和删除文件。
    # 但**从来没有代码往那个目录写过东西**：视频是流式播放的，缓冲由
    # QtMultimedia 内部管理，不落盘。于是那两个接口永远返回 0 B，
    # 设置里那格「视频缓存 0 B —— 点一下清空」就是个摆设（用户发现的）。
    # 与其留着假按钮，不如整块去掉 —— 真需要缓存的话得自己实现分段下载，
    # 那是另一个功能，不该用一个永远为 0 的标签冒充。

    # ================================================================ 内部
    def _on_position(self, _pos: int) -> None:
        self.positionChanged.emit()

    def _on_duration(self, _dur: int) -> None:
        self.positionChanged.emit()

    def _on_media_status(self, status) -> None:
        S = QMediaPlayer.MediaStatus
        if status == S.InvalidMedia:
            self._fail("这个视频无法播放（可能是直播 / 番剧 / 付费内容）")
        elif status == S.EndOfMedia:
            self.stateChanged.emit()

    def _on_error(self, err, msg: str) -> None:
        if err != QMediaPlayer.Error.NoError:
            self._fail(msg or "播放出错")

    def shutdown(self) -> None:
        """程序退出时调用，确保代理线程停掉。"""
        self.stop_internal(keep_title=False)


def _fmt_ms(ms: int) -> str:
    ms = max(0, int(ms))
    total = ms // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ★ 体积格式化统一走 util.human_size（全项目唯一实现），这里保留旧名字。
human_bytes = human_size
