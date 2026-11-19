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

"""Windows 通知：优先用系统 Toast（右下角横幅），失败就退回托盘气泡."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading

from .util import Log

log = Log("notify.log")

# PowerShell 自带的 AUMID，用它发 Toast 最省事，不需要注册快捷方式
_PS_AUMID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"

_PS_TEMPLATE = r"""
$ErrorActionPreference = "Stop"
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
  [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
  $xml = [System.IO.File]::ReadAllText("__PAYLOAD__", [System.Text.Encoding]::UTF8)
  $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
  $doc.LoadXml($xml)
  $toast = New-Object Windows.UI.Notifications.ToastNotification $doc
  $aumid = "__AUMID__"
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aumid).Show($toast)
  "OK"
} catch {
  "FAIL: " + $_.Exception.Message
}
"""


# 系统自带提示音别名，按顺序试（第一条在 Win10/11 上就是「通知」音）
_SOUND_ALIASES = ("SystemNotification", "SystemAsterisk", "SystemExclamation")


def play_system_alert() -> bool:
    """系统提示音的兜底播放（自定义音效不可用时才走这里）。

    为什么不靠 Toast 的 ``<audio>``：Windows 允许把「Windows PowerShell」这个
    通知来源的声音单独关掉，专注助手开着时也会静音，所以经常「通知弹出来了但没声音」。
    这里直接在本进程用 winsound 播系统提示音，不依赖 Toast 的音频设置。
    """
    if sys.platform != "win32":
        return False
    try:
        import winsound
    except ImportError:
        return False
    for alias in _SOUND_ALIASES:
        try:
            winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
            return True
        except RuntimeError:
            continue
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        return True
    except RuntimeError:
        log("play_alert: 所有提示音都播放失败")
        return False


# 自定义提示音：Core 启动时把 SoundPlayer 和音效路径注册进来。
# 用模块级单例是为了让 Notifier 的后台线程也能直接调用，不必层层传参。
_custom_player = None
_custom_path = ""


def set_custom_sound(player, path: str) -> None:
    """注册自定义提示音（player 可以是 None，表示只记录路径）。"""
    global _custom_player, _custom_path
    _custom_player = player
    _custom_path = path or ""


def play_alert(path: str = "") -> bool:
    """播放提示音：优先自定义音效，取不到就退回系统提示音。"""
    target = (path or _custom_path or "").strip()
    if target and os.path.isfile(target):
        if _custom_player is not None:
            try:
                _custom_player.request(target)
                return True
            except Exception as e:  # noqa: BLE001
                log(f"custom alert failed: {e!r}")
        else:
            return _play_file_fallback(target)
    return play_system_alert()


def _play_file_fallback(path: str) -> bool:
    """没有 Qt 播放器时的兜底：wav 用 winsound，其它格式直接返回 False。"""
    if sys.platform != "win32":
        return False
    if not path.lower().endswith(".wav"):
        return play_system_alert()
    try:
        import winsound

        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True
    except (ImportError, RuntimeError):
        return play_system_alert()


def _xml_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_toast_xml(title: str, lines: list[str], silent: bool = False) -> str:
    texts = [f"<text>{_xml_escape(title)}</text>"]
    for line in lines[:3]:
        texts.append(f"<text>{_xml_escape(line)}</text>")
    audio = (
        "<audio silent=\"true\"/>"
        if silent
        else '<audio src="ms-winsoundevent:Notification.Default"/>'
    )
    return (
        "<toast scenario=\"default\"><visual><binding template=\"ToastGeneric\">"
        + "".join(texts)
        + "</binding></visual>"
        + audio
        + "</toast>"
    )


def _run_powershell(script: str, timeout: float = 12.0) -> tuple[bool, str]:
    fd, path = tempfile.mkstemp(suffix=".ps1", prefix="l4d2_toast_")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write(script)
        creation = 0
        if sys.platform == "win32":
            creation = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                path,
            ],
            capture_output=True,
            timeout=timeout,
            creationflags=creation,
        )
        out = (proc.stdout or b"").decode("utf-8", "ignore").strip()
        err = (proc.stderr or b"").decode("utf-8", "ignore").strip()
        return (out.startswith("OK"), out or err)
    except (subprocess.SubprocessError, OSError) as e:
        return (False, str(e))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def send_toast(title: str, lines: list[str], silent: bool = False) -> tuple[bool, str]:
    xml = build_toast_xml(title, lines, silent=silent)
    # 内容作为文件传给 PowerShell，避免编码 / 引号地狱
    fd, xml_path = tempfile.mkstemp(suffix=".xml", prefix="l4d2_toast_")
    os.close(fd)
    try:
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml)
        script = _PS_TEMPLATE.replace("__PAYLOAD__", xml_path.replace("\\", "\\\\")).replace(
            "__AUMID__", _PS_AUMID.replace("\\", "\\\\")
        )
        ok, msg = _run_powershell(script)
        if not ok:
            log(f"toast failed: {msg}")
        return ok, msg
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass


class Notifier:
    """封装通知行为，并保证不阻塞 UI 线程."""

    def __init__(self, tray=None, sound: bool = True, sound_path: str = ""):
        self.tray = tray
        self.sound = sound
        self.sound_path = sound_path or ""
        self._thread: threading.Thread | None = None

    def set_tray(self, tray) -> None:
        self.tray = tray

    def notify(self, title: str, lines: list[str]) -> None:
        lines = [ln for ln in lines if ln]
        # Toast 是 async 的，开个线程发，避免 PowerShell 启动拖慢 UI
        self._thread = threading.Thread(
            target=self._send, args=(title, lines), daemon=True
        )
        self._thread.start()

    def _send(self, title: str, lines: list[str]) -> None:
        if self.sound:
            # 先自己出声，保证「静音 Toast」的场景也听得到
            play_alert(self.sound_path)
        ok, _ = send_toast(title, lines, silent=True)
        if not ok and self.tray is not None:
            try:
                self.tray.showMessage(title, "\n".join(lines), 5000)
            except (RuntimeError, AttributeError):
                pass
        log(f"notified: {title} | {' / '.join(lines)}")
