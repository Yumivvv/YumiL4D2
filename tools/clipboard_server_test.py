"""从一段文字里抠服务器地址：把常见的几种分享格式都过一遍。"""
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

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import protect_user_data  # noqa: E402

protect_user_data()

from PySide6.QtCore import QObject  # noqa: E402
from app.servers import ServerManager, normalize_address  # noqa: E402

fails = []


def check(name, got, want):
    if got == want:
        print(f"  ok   {name}  {got}")
    else:
        print(f"  FAIL {name}  got={got}  want={want}")
        fails.append(name)


class _Config:
    def __init__(self):
        self.data = {"servers": [], "servers_sort": "weight"}

    def __getitem__(self, k):
        return self.data.get(k)

    def __setitem__(self, k, v):
        self.data[k] = v

    def save(self):
        pass


class FakeCore(QObject):
    def __init__(self):
        super().__init__()
        self.config = _Config()


CORE = FakeCore()
mgr = ServerManager(CORE)
mgr._clipboard = lambda t: True

# 1. 本程序导出的分享文本
share = mgr.shareText("1.2.3.4:27015")
print("--- shareText ---")
print(share)
check("分享文本带地址", "1.2.3.4:27015" in share, True)
check("分享文本带 connect", "connect 1.2.3.4:27015" in share, True)

# 2. 各种聊天里会出现的写法
cases = [
    ("裸地址", "服务器 1.2.3.4:27015 快来", ["1.2.3.4:27015"]),
    ("steam 链接", "steam://connect/5.6.7.8:27016", ["5.6.7.8:27016"]),
    ("connect 命令", "进控制台敲 connect 9.9.9.9:27015", ["9.9.9.9:27015"]),
    ("多个地址", "A 1.1.1.1:27015 B 2.2.2.2:27016", ["1.1.1.1:27015", "2.2.2.2:27016"]),
    ("重复地址", "1.2.3.4:27015 和 1.2.3.4:27015", ["1.2.3.4:27015"]),
    ("只有 IP 且提到服", "服务器 ip 是 3.3.3.3 端口默认", ["3.3.3.3:27015"]),
    ("只有 IP 无字眼", "随便 3.3.3.3 一下", []),
    ("域名带端口", "l4d2.example.com:27015", ["l4d2.example.com:27015"]),
    ("纯域名不认", "看 github.com 上的项目", []),
    ("版本号不误判", "版本 1.3.2.4 更新了", []),
    ("中文没有地址", "今天天气不错", []),
    ("空文本", "", []),
    ("端口越界", "1.2.3.4:99999", []),
    ("粘在数字后面", "abc1.2.3.4:27015", []),
]
print("--- extract ---")
for name, text, want in cases:
    check(name, mgr.extract_addrs(text), want)

# 3. 预览 + 导入
CORE.config.data["servers"] = [{"addr": "1.1.1.1:27015", "name": "旧的",
                                    "weight": 0, "panels": []}]
info = mgr.parseShareText("旧的 1.1.1.1:27015 新的 4.4.4.4:27015")
check("预览总数", info["total"], 2)
check("预览新的", info["fresh"], 1)
check("预览重复", info["duplicate"], 1)
res = mgr.importFromText("旧的 1.1.1.1:27015 新的 4.4.4.4:27015")
check("导入数量", res["added"], 1)
check("导入后收藏数", len(CORE.config.data["servers"]), 2)
res2 = mgr.importFromText("1.1.1.1:27015")
check("重复导入不报成功", res2["ok"], False)

# 4. 分享不存在的服务器
check("分享不存在的", mgr.shareServer("9.9.9.9:1")["ok"], False)

# 5. 剪贴板：只认「新的复制动作」，不认「启动时剪贴板里本来就有」
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import PySide6.QtGui as _qg  # noqa: E402


class _Board:
    text_value = ""

    def text(self):
        return self.text_value

    def dataChanged(self):          # 只用来接 watch_clipboard 的 connect
        pass


board = _Board()
_qg.QGuiApplication.clipboard = staticmethod(lambda: board)  # type: ignore[attr-defined]

# --- 5a. 没有任何 dataChanged 事件（剪贴板是程序起来之前就有的内容）---
mgr.resetClipboardSeen()
board.text_value = "老内容 7.7.7.7:27015"
r0 = mgr.scanClipboard()
check("启动时旧内容不弹", (r0["changed"], r0["fresh"]), (False, 1))
r0b = mgr.scanClipboard()
check("不改剪贴板就一直不弹", r0b["changed"], False)

# --- 5b. 真发生了一次复制（打戳），才认 ---
mgr._on_clipboard_changed()
r1 = mgr.scanClipboard()
check("新复制的内容才弹", (r1["changed"], r1["fresh"]), (True, 1))
r2 = mgr.scanClipboard()
check("问过一次就不再问", r2["changed"], False)

# --- 5c. 用户点了「不用」之后，同一段不会再弹 ---
mgr.noteClipboardHandled()
check("点了不用后不再弹", mgr.scanClipboard()["changed"], False)

# --- 5d. 复制了别的东西（哪怕没有地址）后再复制回原来的，也算新复制 ---
board.text_value = "普通文字"
mgr._on_clipboard_changed()
mgr.scanClipboard()
check("没地址的新内容不问", mgr.scanClipboard()["changed"], False)
board.text_value = "老内容 7.7.7.7:27015"
mgr._on_clipboard_changed()
r4 = mgr.scanClipboard()
check("复制回同样内容也算新复制", (r4["changed"], r4["fresh"]), (True, 1))

# --- 5e. 关掉开关再打开：同一段不应立刻又弹 ---
mgr.resetClipboardSeen()
r5 = mgr.scanClipboard()
check("重置后第一下只记基线", r5["changed"], False)


# 6. 启动宽限期：Qt 起来时系统自己抛的那次 dataChanged 不能算用户复制
mgr.resetClipboardSeen()
mgr._clip_baseline = "启动前的旧内容"
mgr._clip_baseline_done = True
mgr._clip_ignore_until = __import__("time").monotonic() + 5
mgr._on_clipboard_changed()          # 模拟启动时系统抛的那次
check("启动宽限期内的事件被忽略", mgr._clip_seq, mgr._clip_seen_seq)
mgr._clip_ignore_until = 0
mgr._on_clipboard_changed()
check("宽限期过后正常计数", mgr._clip_seq, mgr._clip_seen_seq + 1)
print()
print("全部通过" if not fails else f"失败 {len(fails)} 项：{fails}")
sys.exit(0 if not fails else 1)
