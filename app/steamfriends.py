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

"""从本机 Steam 客户端读好友在线状态（不需要 API Key、不需要密码）。

## 原理

Steam 客户端自己就在本机跑着一个 IPC 服务。只要用 `steamclient64.dll` 导出的
`CreateInterface` 拿到 `ISteamClient`，再 `ConnectToGlobalUser` 就能**复用当前登录态**，
然后 `GetISteamFriends(..., "SteamFriends017")` 就能读到好友列表与「正在玩什么」。

全程只读，不碰账号密码、不联网、不写任何文件。

## 两个 DLL 的分工

* `steamclient64.dll`（Steam 根目录，一定存在）——提供 `CreateInterface`，
  以及 `ISteamClient` / `ISteamFriends` 这些接口对象。
* `steam_api64.dll`（**Steam 根目录通常没有**）——提供 `SteamAPI_ISteamFriends_*`
  这层「扁平包装函数」，参数是显式写出来的，比手工排 vtable 稳得多。
  它一般躺在各个 64 位游戏的安装目录里，所以下面会去游戏库找。

## 调用形式（实测踩出来的，别乱改）

    GetFriendCount      : (self, flags) -> int
    GetFriendByIndex    : (self, index, flags) -> CSteamID   ★ 是**返回值**，不是 out 参数
    GetFriendPersonaName: (self, CSteamID) -> const char*
    GetFriendPersonaState:(self, CSteamID) -> int
    GetFriendGamePlayed : (self, CSteamID, FriendGameInfo_t*) -> bool

`GetFriendByIndex` 这条尤其反直觉：Steamworks 的 C# 封装里它是 `out` 参数，
但 DLL 导出的 C 版本是直接返回 8 字节。按 out 传会静默失败（或访问冲突）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import glob
import os
import sys
import threading
import time
from typing import Any

from .util import Log

log = Log("steamfriends.log")

# 好友标志：k_EFriendFlagImmediate = 「真正的好友」（不是屏蔽/请求中那些）
EFRIEND_IMMEDIATE = 4
L4D2_APPID = 550

# PersonaState 枚举
PERSONA_STATE = {
    0: "离线", 1: "在线", 2: "忙碌", 3: "离开",
    4: "打盹", 5: "想交易", 6: "想玩",
}

LOAD_WITH_ALTERED_SEARCH_PATH = 0x00000008

# 缓存多久。好友状态变得不算快，60 秒足够，也避免频繁调 DLL。
CACHE_TTL = 60.0

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "data": None, "err": ""}
_api_dll_cache: str | None = None


class FriendGameInfo(ctypes.Structure):
    """对应 Steamworks 的 FriendGameInfo_t（布局不能改）。"""
    _fields_ = [
        ("m_gameID", ctypes.c_uint64),
        ("m_unGameIP", ctypes.c_uint32),
        ("m_usGamePort", ctypes.c_uint16),
        ("m_usQueryPort", ctypes.c_uint16),
        ("m_steamIDLobby", ctypes.c_uint64),
    ]


def _steam_root() -> str:
    """Steam 安装目录。优先注册表，其次常见路径。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            p, _ = winreg.QueryValueEx(k, "SteamPath")
            p = str(p or "").replace("/", "\\")
            if p and os.path.isdir(p):
                return p
    except OSError:
        pass
    for c in (r"D:\Steam", r"C:\Program Files (x86)\Steam", r"E:\Steam"):
        if os.path.isdir(c):
            return c
    return ""


def _steam_running() -> bool:
    """Steam 客户端在不在跑。不在跑就别费劲了（ConnectToGlobalUser 必然失败）。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Valve\Steam\ActiveProcess") as k:
            pid, _ = winreg.QueryValueEx(k, "pid")
            if int(pid or 0) > 0:
                return True
    except (OSError, ValueError, TypeError):
        pass
    # 注册表读不到时退回进程检查（避免误判）
    try:
        import subprocess
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
            capture_output=True, timeout=6,
            # ★ 不要用 text=True：Windows 上它会按系统 ANSI(GBK) 解码，
            #   tasklist 中文系统的输出混着本地代码页字节，会抛
            #   UnicodeDecodeError（'utf-8' codec can't decode byte 0xd0）。
            #   这里拿字节自己 decode，错了也不炸。
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = (out.stdout or b"").decode("utf-8", "ignore").lower()
        return "steam.exe" in text
    except Exception:  # noqa: BLE001
        return False


def _library_roots(steam_root: str) -> list[str]:
    """所有 Steam 库根目录（含 libraryfolders.vdf 里登记的其它盘）。"""
    roots: list[str] = []
    if steam_root:
        roots.append(steam_root)
    vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf") if steam_root else ""
    if vdf and os.path.isfile(vdf):
        try:
            text = open(vdf, "r", encoding="utf-8", errors="replace").read()
            import re
            for m in re.finditer(r'"path"\s*"([^"]+)"', text):
                p = m.group(1).replace("\\\\", "\\")
                if os.path.isdir(p) and p not in roots:
                    roots.append(p)
        except OSError:
            pass
    return roots


def find_steam_api_dll(steam_root: str = "") -> str:
    """找一个可用的 steam_api64.dll。

    Steam 根目录通常**没有**这个文件（它是游戏自带的），所以去各游戏目录里翻。
    找到第一个能用的就记住，避免每次都全盘扫。
    """
    global _api_dll_cache
    if _api_dll_cache and os.path.isfile(_api_dll_cache):
        return _api_dll_cache

    root = steam_root or _steam_root()
    # 先看根目录（少数发行版会放一份）
    direct = os.path.join(root, "steam_api64.dll") if root else ""
    if direct and os.path.isfile(direct):
        _api_dll_cache = direct
        return direct

    # 游戏目录里翻。限制层级，别把整个盘扫一遍。
    for lib in _library_roots(root):
        common = os.path.join(lib, "steamapps", "common")
        if not os.path.isdir(common):
            continue
        # 优先找常见位置：<game>/steam_api64.dll、<game>/bin/、<game>/bin64/
        patterns = [
            os.path.join(common, "*", "steam_api64.dll"),
            os.path.join(common, "*", "bin", "steam_api64.dll"),
            os.path.join(common, "*", "bin64", "steam_api64.dll"),
            os.path.join(common, "*", "*", "steam_api64.dll"),
        ]
        for pat in patterns:
            try:
                hits = sorted(glob.glob(pat), key=lambda p: os.path.getsize(p), reverse=True)
            except OSError:
                continue
            for h in hits:
                if os.path.isfile(h) and os.path.getsize(h) > 50_000:
                    _api_dll_cache = h
                    log(f"steam_api64.dll -> {h}")
                    return h
    return ""


class _Steam:
    """一次性会话：加载 DLL、拿 ISteamFriends、读完就释放。

    ★ 必须用完就 `close()`：Steam 的 pipe / user 是**全局资源**，
      不释放会在 Steam 那边累积，反复调用最终会把好友接口搞挂。
    """

    def __init__(self) -> None:
        self.k32 = None
        self.client = None
        self.pipe = 0
        self.user = 0
        self.friends = None
        self._rel_user = None
        self._rel_pipe = None
        self.err = ""

    def open(self) -> bool:
        root = _steam_root()
        if not root:
            self.err = "找不到 Steam 安装目录"
            return False
        client_dll = os.path.join(root, "steamclient64.dll")
        if not os.path.isfile(client_dll):
            self.err = "找不到 steamclient64.dll"
            return False
        api_dll = find_steam_api_dll(root)
        if not api_dll:
            self.err = ("找不到 steam_api64.dll。它一般在某个 64 位游戏的安装目录里，"
                        "装过任意一款 64 位 Steam 游戏就会有")
            return False

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.LoadLibraryExW.restype = wt.HMODULE
        k32.LoadLibraryExW.argtypes = [wt.LPCWSTR, wt.HANDLE, wt.DWORD]
        k32.GetProcAddress.restype = ctypes.c_void_p
        k32.GetProcAddress.argtypes = [wt.HMODULE, ctypes.c_char_p]
        self.k32 = k32

        hc = k32.LoadLibraryExW(client_dll, None, LOAD_WITH_ALTERED_SEARCH_PATH)
        ha = k32.LoadLibraryExW(api_dll, None, LOAD_WITH_ALTERED_SEARCH_PATH)
        if not hc:
            self.err = "steamclient64.dll 加载失败"
            return False
        if not ha:
            self.err = "steam_api64.dll 加载失败（位数不对或版本不兼容）"
            return False

        def sym(name: str):
            p = k32.GetProcAddress(ha, name.encode())
            if not p:
                raise AttributeError(name)
            return p

        try:
            p_ci = k32.GetProcAddress(hc, b"CreateInterface")
            if not p_ci:
                self.err = "steamclient64.dll 没有 CreateInterface 导出"
                return False
            CI = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p,
                                  ctypes.c_void_p)(p_ci)
            client = CI(b"SteamClient020", None)
            if not client:
                CI = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p,
                                      ctypes.c_void_p)(p_ci)
                client = CI(b"SteamClient019", None)
            if not client:
                self.err = "拿不到 ISteamClient（Steam 版本可能不兼容）"
                return False
            self.client = client

            vt = ctypes.cast(
                ctypes.cast(client, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p))
            CreatePipe = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)(vt[0])
            self._rel_pipe = ctypes.CFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_int)(vt[1])
            ConnGlobal = ctypes.CFUNCTYPE(
                ctypes.c_int, ctypes.c_void_p, ctypes.c_int)(vt[2])
            self._rel_user = ctypes.CFUNCTYPE(
                None, ctypes.c_void_p, ctypes.c_int, ctypes.c_int)(vt[4])
            GetFriends = ctypes.CFUNCTYPE(
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                ctypes.c_char_p)(vt[8])

            self.pipe = CreatePipe(client)
            if not self.pipe:
                self.err = "CreateSteamPipe 失败"
                return False
            self.user = ConnGlobal(client, self.pipe)
            if not self.user:
                self.err = "连不上 Steam 客户端（没登录？）"
                return False
            self.friends = GetFriends(client, self.user, self.pipe,
                                      b"SteamFriends017")
            if not self.friends:
                self.err = "拿不到 ISteamFriends"
                return False

            # 把导出函数都挂到实例上
            self._count = ctypes.CFUNCTYPE(
                ctypes.c_int, ctypes.c_void_p, ctypes.c_int)(
                sym("SteamAPI_ISteamFriends_GetFriendCount"))
            # ★ 返回值形式，不是 out 参数
            self._by_index = ctypes.CFUNCTYPE(
                ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int, ctypes.c_int)(
                sym("SteamAPI_ISteamFriends_GetFriendByIndex"))
            self._name = ctypes.CFUNCTYPE(
                ctypes.c_char_p, ctypes.c_void_p, ctypes.c_uint64)(
                sym("SteamAPI_ISteamFriends_GetFriendPersonaName"))
            self._state = ctypes.CFUNCTYPE(
                ctypes.c_int, ctypes.c_void_p, ctypes.c_uint64)(
                sym("SteamAPI_ISteamFriends_GetFriendPersonaState"))
            self._game = ctypes.CFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_uint64,
                ctypes.POINTER(FriendGameInfo))(
                sym("SteamAPI_ISteamFriends_GetFriendGamePlayed"))
            return True
        except (AttributeError, OSError) as e:
            self.err = f"接口不完整：{e}"
            self.close()
            return False

    def my_name(self) -> str:
        """自己的昵称（槽位 0，无参，安全）。"""
        try:
            vf = ctypes.cast(
                ctypes.cast(self.friends, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p))
            fn = ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_void_p)(vf[0])
            p = fn(self.friends)
            return p.decode("utf-8", "replace") if p else ""
        except Exception:  # noqa: BLE001
            return ""

    def read_friends(self) -> list[dict]:
        """读出全部好友。每项：{sid, name, state, stateLabel, appId, ip, port, queryPort, lobby}"""
        out: list[dict] = []
        count = self._count(self.friends, EFRIEND_IMMEDIATE)
        if count <= 0:
            return out
        for i in range(count):
            sid = self._by_index(self.friends, i, EFRIEND_IMMEDIATE)
            if not sid:
                continue
            p = self._name(self.friends, sid)
            name = p.decode("utf-8", "replace") if p else ""
            st = self._state(self.friends, sid)
            g = FriendGameInfo()
            played = self._game(self.friends, sid, ctypes.byref(g))
            appid = int(g.m_gameID) if played else 0
            ip = int(g.m_unGameIP) if played else 0
            out.append({
                "sid": str(sid),
                "name": name or "好友",
                "state": int(st),
                "stateLabel": PERSONA_STATE.get(int(st), "未知"),
                "appId": appid,
                "ip": ip,
                "port": int(g.m_usGamePort) if played else 0,
                "queryPort": int(g.m_usQueryPort) if played else 0,
                "lobby": str(int(g.m_steamIDLobby)) if played else "0",
                "playingL4D2": appid == L4D2_APPID,
                # 好友正在玩的服务器地址（只在共享了公网地址时才有）
                "addr": (f"{ip >> 24}.{(ip >> 16) & 255}.{(ip >> 8) & 255}.{ip & 255}"
                         f":{int(g.m_usGamePort)}"
                         if played and ip and g.m_usGamePort else ""),
            })
        return out

    def close(self) -> None:
        try:
            if self.user and self.client and self._rel_user:
                self._rel_user(self.client, self.pipe, self.user)
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.pipe and self.client and self._rel_pipe:
                self._rel_pipe(self.client, self.pipe)
        except Exception:  # noqa: BLE001
            pass
        self.user = 0
        self.pipe = 0


def _is_private(ip: int) -> bool:
    """内网 / 保留地址判断。好友在局域网时 Steam 会给私有地址，拿它去连没意义。"""
    if not ip:
        return True
    a = (ip >> 24) & 255
    b = (ip >> 16) & 255
    if a == 10 or a == 127 or a == 0:
        return True
    if a == 192 and b == 168:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 169 and b == 254:
        return True
    if a == 100 and 64 <= b <= 127:      # CGNAT
        return True
    if a >= 224:                          # 组播 / 保留
        return True
    return False


def fetch(force: bool = False) -> dict:
    """读好友状态（带缓存）。

    返回：{ok, error, me, friends: [...], at}
    `ok=False` 时 `error` 说明原因（Steam 没开 / 没登录 / 缺 DLL）。
    """
    with _lock:
        now = time.time()
        if not force and _cache["data"] is not None and now - _cache["at"] < CACHE_TTL:
            return _cache["data"]

        if not _steam_running():
            data = {"ok": False, "error": "Steam 没有运行，先打开并登录 Steam",
                    "me": "", "friends": [], "at": now}
            _cache.update(at=now, data=data, err=data["error"])
            return data

        if sys.maxsize <= 2 ** 32:
            data = {"ok": False, "error": "需要 64 位 Python 才能读 Steam 好友",
                    "me": "", "friends": [], "at": now}
            _cache.update(at=now, data=data, err=data["error"])
            return data

        s = _Steam()
        try:
            if not s.open():
                data = {"ok": False, "error": s.err, "me": "", "friends": [],
                        "at": now}
                _cache.update(at=now, data=data, err=s.err)
                return data
            me = s.my_name()
            friends = s.read_friends()
            data = {"ok": True, "error": "", "me": me, "friends": friends,
                    "at": now}
            _cache.update(at=now, data=data, err="")
            return data
        except Exception as e:  # noqa: BLE001
            msg = f"读好友失败：{type(e).__name__}"
            log(f"{msg}: {e!r}")
            data = {"ok": False, "error": msg, "me": "", "friends": [], "at": now}
            _cache.update(at=now, data=data, err=msg)
            return data
        finally:
            s.close()


def clear_cache() -> None:
    with _lock:
        _cache.update(at=0.0, data=None, err="")


def l4d2_friends(force: bool = False) -> list[dict]:
    """只取「正在玩 L4D2」的好友。"""
    d = fetch(force=force)
    if not d.get("ok"):
        return []
    return [f for f in d.get("friends") or [] if f.get("playingL4D2")]


def friends_by_addr(force: bool = False) -> dict[str, list[dict]]:
    """按服务器地址归并：{"1.2.3.4:27015": [好友...]}

    只收**公网**地址（内网地址连不上，也没法匹配已收藏的服务器）。
    """
    out: dict[str, list[dict]] = {}
    for f in l4d2_friends(force=force):
        addr = str(f.get("addr") or "")
        if not addr:
            continue
        try:
            ip_s, port_s = addr.rsplit(":", 1)
            ip_int = 0
            for part in ip_s.split("."):
                ip_int = (ip_int << 8) | (int(part) & 255)
            if _is_private(ip_int):
                continue
            port = int(port_s)
        except (ValueError, TypeError):
            continue
        key = f"{ip_s}:{port}"
        out.setdefault(key, []).append(f)
    return out