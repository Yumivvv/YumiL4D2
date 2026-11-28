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

from .util import DATA_DIR, Log

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

# ---------------------------------------------------------------- 好友头像
#
# ★ 为什么单独缓存到磁盘：Steam 的头像是**异步下载**的。
#   第一次问 `GetMediumFriendAvatar()` 常常返回 0（服务器端还没把图传下来），
#   要隔一会儿再问才有。如果每次 `fetch()` 都去重试，一次刷新就要多等好几秒。
#
#   所以策略是：
#     1. 先把**上次存下来的 PNG** 当头像（立即可用，界面不闪）；
#     2. 后台顺手再问一次 Steam，拿到新句柄就覆盖文件（下次刷新就更新了）。
#
#   这样「好友列表」永远是快的，头像最坏情况是「差一次刷新」。
AVATAR_SUBDIR = "avatar"      # 落在 DATA_DIR/cache/avatar/ 下
# 头像句柄重试：间隔（秒）与次数。steam 那边慢的时候 2~3 次才回来。
AVATAR_RETRY = (0.0, 0.35, 0.9, 1.8, 3.0)

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "data": None, "err": ""}
_api_dll_cache: str | None = None

# 只认 Valve 自己签名的 steam_api64.dll（见 `_dll_is_genuine` 的长注释）。
STEAM_DLL_SIGNER = "valve"
# WinVerifyTrust 的返回码里，这几个不代表「文件坏了」，只是我们主动关掉的检查。
_TRUST_OK = 0
_TRUST_E_NOSIGNATURE = 0x800B0100


def _dll_company(path: str) -> str:
    """读文件版本信息里的 CompanyName —— **不加载 DLL**，纯读资源。"""
    try:
        import ctypes as _ct
        ver = _ct.windll.version
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        buf = _ct.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return ""
        ptr = _ct.c_void_p()
        ln = _ct.c_uint()
        for lang in (0x040904B0, 0x040904E4, 0x080404B0):
            if ver.VerQueryValueW(buf, f"\\StringFileInfo\\{lang:08X}\\CompanyName",
                                  _ct.byref(ptr), _ct.byref(ln)) and ptr.value:
                return _ct.wstring_at(ptr.value)[:80]
    except Exception:  # noqa: BLE001 —— 读不到版本信息就当没有
        pass
    return ""


def _trust_ok(path: str) -> bool:
    """文件是否有**受信任的签名**（WinVerifyTrust，全程不弹框、不联网）。

    ★ 为什么必须用 `WTD_UI_NONE`：默认的 UIChoice 会在签名无效时**弹窗**，
      那正是我们要避免的东西。这里永远静默，只拿返回码。
    """
    try:
        import ctypes as _ct
        import ctypes.wintypes as _wt

        class _GUID(_ct.Structure):
            _fields_ = [("Data1", _wt.DWORD), ("Data2", _wt.WORD),
                        ("Data3", _wt.WORD), ("Data4", _ct.c_ubyte * 8)]

        class _FileInfo(_ct.Structure):
            _fields_ = [("cbStruct", _wt.DWORD), ("pcwszFilePath", _wt.LPCWSTR),
                        ("hFile", _wt.HANDLE), ("pgKnownSubject", _ct.c_void_p)]

        class _TrustData(_ct.Structure):
            _fields_ = [
                ("cbStruct", _wt.DWORD), ("pPolicyCallbackData", _ct.c_void_p),
                ("pSIPClientData", _ct.c_void_p), ("dwUIChoice", _wt.DWORD),
                ("fdwRevocationChecks", _wt.DWORD), ("dwUnionChoice", _wt.DWORD),
                ("pFile", _ct.c_void_p), ("dwStateAction", _wt.DWORD),
                ("hWVTStateData", _wt.HANDLE), ("pwszURLReference", _wt.LPCWSTR),
                ("dwProvFlags", _wt.DWORD), ("dwUIContext", _wt.DWORD),
            ]

        action = _GUID()
        buf = _ct.create_unicode_buffer(39)
        _ct.windll.ole32.CLSIDFromString(
            _ct.c_wchar_p("{00AAC56B-CD44-11d0-8CC2-00C04FC295EE}"), buf)
        _ct.memmove(_ct.byref(action), buf, _ct.sizeof(action))

        fi = _FileInfo()
        fi.cbStruct = _ct.sizeof(fi)
        fi.pcwszFilePath = os.path.abspath(path)

        td = _TrustData()
        td.cbStruct = _ct.sizeof(td)
        td.dwUIChoice = 2            # WTD_UI_NONE —— 绝不弹框
        td.fdwRevocationChecks = 0   # WTD_REVOKE_NONE —— 不联网查吊销
        td.dwUnionChoice = 1         # WTD_CHOICE_FILE
        td.pFile = _ct.cast(_ct.byref(fi), _ct.c_void_p)
        td.dwStateAction = 1         # WTD_STATEACTION_VERIFY

        wt_dll = _ct.windll.wintrust
        code = wt_dll.WinVerifyTrust(None, _ct.byref(action), _ct.byref(td))
        td.dwStateAction = 2         # WTD_STATEACTION_CLOSE —— 释放状态
        wt_dll.WinVerifyTrust(None, _ct.byref(action), _ct.byref(td))
        return code == _TRUST_OK
    except Exception:  # noqa: BLE001 —— 验不了就当作不可信（宁可不用好友功能）
        return False


def _dll_is_genuine(path: str) -> bool:
    """这个 `steam_api64.dll` 能不能安全加载进我们的进程？

    ★★ 这是「打开软件就弹 socialclub.dll not found、点确定整个程序消失」的修复。

    事故现象（用户报的，别人电脑上）：
        打开软件 → 一个 Windows 原生对话框「socialclub.dll not found」
        → 点「确定」→ 软件整个消失。

    查到的根因：
      `socialclub.dll` 是 Rockstar 的组件，本项目**从不碰它**，也**没有任何
      原生弹框**（全项目搜不到 MessageBox）。唯一会把「外来 DLL」拉进我们进程的
      地方就是这里 —— 以前这段代码按**文件大小**从所有游戏目录里挑一个
      `steam_api64.dll` 直接 `LoadLibraryExW` 进来。

      而很多整合包 / 破解补丁会**替换**游戏目录里的 `steam_api64.dll`
      （GTA、RDR2、以及各种「学习版」游戏里尤其常见）。这种改版 DLL 的
      `DllMain` 会去找它自己的依赖（典型就是 `socialclub.dll`），找不到就
      **弹一个原生 MessageBox**，用户一点确定它再 `TerminateProcess()` ——
      死的是**我们的进程**。

      所以「按大小挑最大的那个」这条策略本身就是错的：它恰好会优先挑到
      体积更大的改版 DLL。

    修法：**加载前验签**。真的 steam_api64.dll 一定是 Valve 签名的，
    改版 / 破解的必然验不过（签名被改就失效）。两道关都要过：

      1. `WinVerifyTrust` 返回 0（签名链可信）；
      2. 版本信息里的 CompanyName 含 `Valve`。

    验不过就跳过、继续找下一个；全都验不过就**不启用好友功能**
    （`open()` 返回 False，界面照常工作，只是没有「好友在玩」）。

    ★ 为什么不用 `AddDllDirectory` / 改搜索路径：DllMain 的依赖是它自己
      按自己的路径去找的，我们控制不了。唯一的防线就是「别把这个文件加载进来」。
    """
    if not os.path.isfile(path):
        return False
    if not _trust_ok(path):
        log(f"reject (untrusted signature): {path}")
        return False
    company = _dll_company(path).lower()
    if STEAM_DLL_SIGNER not in company:
        log(f"reject (signer company={company!r}): {path}")
        return False
    return True



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
    """找一个**能安全加载**的 steam_api64.dll。

    Steam 根目录通常**没有**这个文件（它是游戏自带的），所以去各游戏目录里翻。
    找到第一个能用的就记住，避免每次都全盘扫。

    ★★ 这里以前只按「文件大小」挑，是个真实的线上事故（见 `_dll_is_genuine`
      的注释）：挑到的若是整合包/破解补丁替换过的改版 DLL，加载时它会弹
      「socialclub.dll not found」，用户点确定后**我们的进程被它杀掉**。

      现在每个候选都要过 `_dll_is_genuine()`（WinVerifyTrust + CompanyName）。
      另外顺序也改了：**先找 L4D2 自己的**（它在 `common/Left 4 Dead 2/`，
      改版概率最低且和游戏同源），再考虑别的游戏。
    """
    global _api_dll_cache
    if _api_dll_cache and os.path.isfile(_api_dll_cache):
        return _api_dll_cache

    root = steam_root or _steam_root()

    def try_accept(path: str) -> bool:
        """通过就记进缓存并返回 True。"""
        global _api_dll_cache
        if not (os.path.isfile(path) and os.path.getsize(path) > 50_000):
            return False
        if not _dll_is_genuine(path):
            return False
        _api_dll_cache = path
        log(f"steam_api64.dll -> {path}")
        return True

    # 1) Steam 根目录（少数发行版会放一份）
    if root:
        direct = os.path.join(root, "steam_api64.dll")
        if os.path.isfile(direct) and try_accept(direct):
            return direct

    # 2) 游戏目录里翻。★ 先把 L4D2 排到最前面 —— 我们自己这个工具的 MOD 目录
    #    就是 L4D2，用同款游戏自带的 DLL 语义上也最对。
    for lib in _library_roots(root):
        common = os.path.join(lib, "steamapps", "common")
        if not os.path.isdir(common):
            continue
        l4d2 = os.path.join(common, "Left 4 Dead 2")
        for sub in ("", "bin", "bin64", os.path.join("game", "bin", "win64")):
            cand = os.path.join(l4d2, sub, "steam_api64.dll")
            if os.path.isfile(cand) and try_accept(cand):
                return cand

    # 3) 其余游戏：按「常见位置优先」+「体积大的优先」翻，但每个都要验签。
    for lib in _library_roots(root):
        common = os.path.join(lib, "steamapps", "common")
        if not os.path.isdir(common):
            continue
        patterns = [
            os.path.join(common, "*", "steam_api64.dll"),
            os.path.join(common, "*", "bin", "steam_api64.dll"),
            os.path.join(common, "*", "bin64", "steam_api64.dll"),
            os.path.join(common, "*", "*", "steam_api64.dll"),
        ]
        for pat in patterns:
            try:
                hits = sorted(glob.glob(pat), key=lambda p: os.path.getsize(p),
                              reverse=True)
            except OSError:
                continue
            for h in hits:
                if try_accept(h):
                    return h
    log("no genuine steam_api64.dll found (好友功能将不可用)")
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
        # 头像相关（首次用到时才初始化，失败就安静降级）
        self.api_handle = None
        self._utils = None
        self._av_ready = False

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
            # ★ 两种可能：一个是真没有；另一个是「有文件但验签不过」
            #   （整合包 / 破解补丁替换过）。后者必须说清楚 —— 以前正是把它
            #   加载进来才弹「socialclub.dll not found」并杀掉我们的进程。
            self.err = ("没找到**Valve 正版签名**的 steam_api64.dll，好友功能已跳过"
                        "（游戏目录里的那个可能被整合包/破解补丁替换过，"
                        "加载它会导致本程序被它弹框并强制退出）。"
                        "装一款原版 Steam 游戏后重试即可。")
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
        self.api_handle = ha

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

    # ------------------------------------------------------------ 好友头像
    #
    # ★ 链路（Steamworks 的既定做法，已实测）：
    #     1. ISteamFriends::GetMediumFriendAvatar(sid) → int 句柄（图片 ID，不是像素）
    #     2. ISteamUtils::GetImageSize(句柄, &w, &h)
    #     3. ISteamUtils::GetImageRGBA(句柄, buf, w*h*4) → BGRA
    #
    # ★★ 两个坑：
    #   · 头像是**异步下载**的，第一次问常常返回 0，要重试几次（AVATAR_RETRY）；
    #   · `ISteamUtils` 不在 ISteamFriends 上，要从 ISteamClient 的虚表拿，
    #     而且**槽位实测是 12，不是文档顺序的 9**（按 9 会 access violation）。
    #     这个值跟 SteamClient interface 版本有关，换版本可能要重测。
    _UTILS_VT_SLOT = 12

    def _init_utils(self) -> bool:
        """取 ISteamUtils（拿头像像素必须它）。取不到就让头像功能安静降级。"""
        if getattr(self, "_utils", None):
            return True
        if not (self.client and self.pipe and self.user):
            return False
        try:
            vt = ctypes.cast(
                ctypes.cast(self.client, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p))
            getter = ctypes.CFUNCTYPE(
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                ctypes.c_char_p)(vt[self._UTILS_VT_SLOT])
            for name in (b"SteamUtils010", b"SteamUtils009"):
                obj = getter(self.client, self.user, self.pipe, name)
                if obj:
                    self._utils = obj
                    break
        except Exception as e:  # noqa: BLE001  虚表槽位不对会崩/抛，都当没有
            log(f"get ISteamUtils failed: {e!r}")
            self._utils = None
        return bool(getattr(self, "_utils", None))

    def _avatar_funcs(self) -> bool:
        """从 steam_api64.dll 取头像相关的三个导出。"""
        if getattr(self, "_av_ready", False):
            return True
        if not self.api_handle:
            return False

        def sym(name: str):
            p = self.k32.GetProcAddress(self.api_handle, name.encode())
            if not p:
                raise AttributeError(name)
            return p

        try:
            self._av_medium = ctypes.CFUNCTYPE(
                ctypes.c_int, ctypes.c_void_p, ctypes.c_uint64)(
                sym("SteamAPI_ISteamFriends_GetMediumFriendAvatar"))
            self._img_size = ctypes.CFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_int,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.POINTER(ctypes.c_uint32))(
                sym("SteamAPI_ISteamUtils_GetImageSize"))
            self._img_rgba = ctypes.CFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_int,
                ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int)(
                sym("SteamAPI_ISteamUtils_GetImageRGBA"))
            self._av_ready = True
        except (AttributeError, OSError) as e:
            log(f"avatar exports missing: {e!r}")
            self._av_ready = False
        return bool(getattr(self, "_av_ready", False))

    def read_avatar_png(self, sid: int) -> bytes:
        """拿一个好友的 64x64 头像 PNG 字节（拿不到返回空 bytes）。

        重试几次是因为 Steam 那头是异步下载的；退避间隔见 AVATAR_RETRY。
        """
        if not self._init_utils() or not self._avatar_funcs():
            return b""
        handle = 0
        for delay in AVATAR_RETRY:
            if delay:
                time.sleep(delay)
            try:
                handle = self._av_medium(self.friends, sid)
            except Exception:  # noqa: BLE001
                handle = 0
            if handle:
                break
        if not handle:
            return b""
        w = ctypes.c_uint32(0)
        h = ctypes.c_uint32(0)
        try:
            if not self._img_size(self._utils, handle,
                                  ctypes.byref(w), ctypes.byref(h)):
                return b""
            if not w.value or not h.value or w.value > 512 or h.value > 512:
                return b""
            n = w.value * h.value * 4
            buf = (ctypes.c_ubyte * n)()
            if not self._img_rgba(self._utils, handle, buf, n):
                return b""
        except Exception as e:  # noqa: BLE001
            log(f"avatar pixels failed for {sid}: {e!r}")
            return b""
        # BGRA → PNG。用 Pillow（项目已经依赖它），转一下再落盘，
        # 这样 QML 的 Image 直接能读，也不用在前端做通道交换。
        #
        # ★ 顺手裁成**圆形**（带抗锯齿的 alpha）。
        #   为什么在 Python 这边裁、而不是 QML 里 mask：
        #     · `Rectangle { radius: w/2; clip: true }` 的 clip 是**矩形**的，
        #       radius 只影响背景绘制 —— 图像四角会露出来（实测截图里就是
        #       方块头像）；
        #     · 用 `OpacityMask` 得额外 import Qt5Compat.GraphicalEffects，
        #       而它不在 PyInstaller 的 hiddenimports 里，打包容易漏文件；
        #     · 这里裁一次、落盘，之后 QML 只是贴一张早就圆好的图，
        #       最省事也最不容易在别人机器上出岔子。
        try:
            import io as _io

            from PIL import Image, ImageDraw

            img = Image.frombuffer("RGBA", (w.value, h.value), bytes(buf),
                                   "raw", "BGRA", 0, 1).convert("RGBA")
            # 4 倍超采样画圆形遮罩，边缘不锯齿
            ss = 4
            mask = Image.new("L", (w.value * ss, h.value * ss), 0)
            ImageDraw.Draw(mask).ellipse(
                (0, 0, w.value * ss - 1, h.value * ss - 1), fill=255)
            mask = mask.resize((w.value, h.value), Image.LANCZOS)
            img.putalpha(mask)
            out = _io.BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
        except Exception as e:  # noqa: BLE001
            log(f"avatar encode failed for {sid}: {e!r}")
            return b""

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


def _avatar_dir() -> str:
    """头像缓存目录（`data/cache/avatar/`）。"""
    p = os.path.join(DATA_DIR, "cache", AVATAR_SUBDIR)
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


def _avatar_cached(sid: str) -> str:
    """已经存下来的头像文件路径（没有就是空串）。"""
    if not sid:
        return ""
    p = os.path.join(_avatar_dir(), f"{sid}.png")
    try:
        if os.path.isfile(p) and os.path.getsize(p) > 64:
            return p
    except OSError:
        pass
    return ""


def _avatar_store(sid: str, png: bytes) -> str:
    """把头像 PNG 落盘，返回路径（失败返回空串）。"""
    if not sid or not png:
        return ""
    path = os.path.join(_avatar_dir(), f"{sid}.png")
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(png)
        os.replace(tmp, path)
        return path
    except OSError as e:
        log(f"store avatar failed {sid}: {e!r}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return ""


def _fetch_avatars(sess: _Steam, friends: list[dict]) -> None:
    """给好友列表补上 `avatarPath`（原地改）。

    ★ 只为「正在玩 L4D2」的好友抓头像 —— 服务器列表里只显示这些人的头像，
      给全部 33 个好友都抓一遍要等十几秒，纯属浪费。

    ★ 先用**磁盘里已有的**当结果（本次立即可用），再顺手问一次 Steam：
      拿到新的就覆盖文件。这样界面永远不等人，最新头像最多「差一次刷新」。
    """
    for f in friends:
        sid = str(f.get("sid") or "")
        if not sid:
            continue
        cached = _avatar_cached(sid)
        if cached:
            f["avatarPath"] = cached
        if not f.get("playingL4D2"):
            continue        # 只给「在玩」的抓，省时间
        try:
            png = sess.read_avatar_png(int(sid))
        except Exception as e:  # noqa: BLE001  头像失败不能影响好友列表
            log(f"avatar fetch failed {sid}: {e!r}")
            continue
        if png:
            path = _avatar_store(sid, png)
            if path:
                f["avatarPath"] = path


def _prune_avatars(keep_sids: set[str]) -> None:
    """删掉不在好友列表里的头像文件。

    ★ 为什么要清：好友删了、或者换了 Steam 账号，旧头像就永远没人用了。
      一个文件才几 KB，但这类「只增不减」的目录两年后能堆出几千个，
      而且没人知道它们是什么。既然每次 fetch 都能拿到当前好友列表，
      顺手对一遍账最省事。

    ★ 用 `keep` 白名单而不是按年龄删：头像的价值和「多久没更新」无关
      （一个半年没换头像的好友，头像依然是对的）。
    """
    d = _avatar_dir()
    try:
        names = os.listdir(d)
    except OSError:
        return
    removed = 0
    for name in names:
        if not name.endswith(".png"):
            continue
        stem = name[:-4]
        if stem in keep_sids:
            continue
        try:
            os.remove(os.path.join(d, name))
            removed += 1
        except OSError:
            pass
    if removed:
        log(f"pruned {removed} stale avatars")


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
            # 头像：先贴磁盘缓存的，再顺手补「在玩」的那几个（失败不影响列表）
            try:
                _fetch_avatars(s, friends)
            except Exception as e:  # noqa: BLE001
                log(f"avatar pass failed: {e!r}")
            # 顺手把「已经不是好友」的头像清掉（只增不减会堆垃圾）
            try:
                _prune_avatars({str(f.get("sid") or "") for f in friends})
            except Exception as e:  # noqa: BLE001
                log(f"avatar prune failed: {e!r}")
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