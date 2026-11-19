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

"""自定义提示音：播放 / 导入 / 列出 sounds 目录里的音效.

为什么不用 winsound.PlaySound：
    它只认 WAV 和系统别名，用户挑的 mp3 / flac / ogg 会**静默失败**——
    听起来像"提示音坏了"。QtMultimedia 内置 FFmpeg，这些格式都能解码。

线程安全：
    通知是在后台线程发的，而 QMediaPlayer 必须在主线程创建/使用。
    所以 request() 只 emit 信号，Qt 的队列连接会把播放投递到主线程执行。
"""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QObject, QUrl, Qt, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .util import SOUNDS_DIR, Log, human_size, resource_path

log = Log("sound.log")

# 支持导入的扩展名（QtMultimedia 内置 FFmpeg 全能解）
SOUND_EXTS = (".mp3", ".wav", ".flac", ".ogg", ".aac", ".ape")

# 默认音效：程序自带的 bbb.mp3。删掉了就静默退回系统提示音。
DEFAULT_SOUND = "bbb.mp3"

# 同时最多留几个播放器实例，防止连续通知堆一堆
_MAX_PLAYERS = 4


def resolve_sound_path(value: str, base_dir: str = SOUNDS_DIR) -> str:
    """配置里存的值 → 实际文件路径。

    存裸文件名时优先按 base_dir（sounds 目录）解析，这样整个程序目录挪走也能用；
    再退回程序自带的 sounds（单文件 exe 里默认音效在解包目录，用户目录可能还没有）；
    存绝对路径时直接用。找不到返回空串。
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    if os.path.isabs(raw):
        return raw if os.path.isfile(raw) else ""
    cand = os.path.join(base_dir, raw)
    if os.path.isfile(cand):
        return cand
    bundled = resource_path("sounds", raw)
    if os.path.isfile(bundled):
        return bundled
    return raw if os.path.isfile(raw) else ""


def is_sound_file(name: str) -> bool:
    return os.path.splitext(str(name or ""))[1].lower() in SOUND_EXTS


def list_sounds() -> list[dict]:
    """列出 sounds 目录里所有可用音效，返回 [{name, path, size, sizeText}]。"""
    out: list[dict] = []
    try:
        entries = list(os.scandir(SOUNDS_DIR))
    except OSError:
        return out
    for entry in entries:
        if not entry.is_file() or not is_sound_file(entry.name):
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            size = 0
        out.append({
            "name": entry.name,
            "path": entry.path,
            "size": size,
            "sizeText": human_size(size),
        })
    out.sort(key=lambda it: it["name"].lower())
    return out


def import_sound(src: str) -> dict:
    """把用户选的音效复制进 sounds 目录（同名就加 _1、_2 后缀）。

    返回 {"ok", "name", "path", "error"}。
    """
    src = os.path.abspath(src or "")
    if not os.path.isfile(src):
        return {"ok": False, "name": "", "path": "", "error": "文件不存在"}
    if not is_sound_file(src):
        return {
            "ok": False, "name": "", "path": "",
            "error": "只支持 " + " / ".join(e.lstrip(".").upper() for e in SOUND_EXTS),
        }
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    name = os.path.basename(src)
    dst = os.path.join(SOUNDS_DIR, name)
    stem, ext = os.path.splitext(name)
    n = 1
    while os.path.exists(dst):
        # 同名且内容一样就当作已经导入过，直接用它
        try:
            if os.path.getsize(dst) == os.path.getsize(src):
                return {"ok": True, "name": os.path.basename(dst), "path": dst, "error": ""}
        except OSError:
            pass
        dst = os.path.join(SOUNDS_DIR, f"{stem}_{n}{ext}")
        n += 1
    try:
        shutil.copy2(src, dst)
    except OSError as e:
        log(f"import sound failed: {e}")
        return {"ok": False, "name": "", "path": "", "error": str(e)}
    return {"ok": True, "name": os.path.basename(dst), "path": dst, "error": ""}


def ensure_default_sound() -> str:
    """确保默认音效存在（随程序发布，一般已经有了）。返回路径或空串。"""
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    p = os.path.join(SOUNDS_DIR, DEFAULT_SOUND)
    return p if os.path.isfile(p) else ""


class SoundPlayer(QObject):
    """主线程上的提示音播放器。"""

    playRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._players: list[QMediaPlayer] = []
        # 队列连接：request() 可以从任意线程调用，播放一定落在主线程
        self.playRequested.connect(self.play, Qt.QueuedConnection)

    def request(self, path: str) -> None:
        """任意线程调用：把播放请求丢给主线程。"""
        if path and os.path.isfile(path):
            self.playRequested.emit(path)

    @Slot(str)
    def play(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            return
        player = QMediaPlayer(self)
        out = QAudioOutput(player)
        out.setVolume(0.8)
        player.setAudioOutput(out)
        player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))

        def _cleanup(status, p=player) -> None:
            S = QMediaPlayer.MediaStatus
            if status in (S.EndOfMedia, S.InvalidMedia):
                if p in self._players:
                    self._players.remove(p)
                p.stop()
                p.deleteLater()

        player.mediaStatusChanged.connect(_cleanup)
        self._players.append(player)
        # 超出上限就掐掉最老的
        while len(self._players) > _MAX_PLAYERS:
            old = self._players.pop(0)
            try:
                old.stop()
                old.deleteLater()
            except RuntimeError:
                pass
        player.play()

    def stop_all(self) -> None:
        for p in list(self._players):
            try:
                p.stop()
                p.deleteLater()
            except RuntimeError:
                pass
        self._players.clear()
