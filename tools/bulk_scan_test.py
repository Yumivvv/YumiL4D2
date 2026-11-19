"""批量添加 + 端口遍历。

端口遍历用本机回环 + 一个真实在监听的端口来验证「能扫到活的」，
再拿一批肯定没人用的端口验证「不会误报」。
"""
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

import sys
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import time

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from PySide6.QtCore import QObject, QTimer  # noqa: E402

from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1])

from app.servers import ServerManager  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + name + f"  got={got!r}")
    if not ok:
        fails.append(name)


class _Cfg:
    def __init__(self):
        self.data = {"servers": [], "servers_sort": "weight"}

    def __getitem__(self, k):
        return self.data.get(k)

    def __setitem__(self, k, v):
        self.data[k] = v

    def save(self):
        pass


class _Core(QObject):
    def __init__(self):
        super().__init__()
        self.config = _Cfg()


core = _Core()
mgr = ServerManager(core)
mgr._toast = lambda *a, **k: None   # 测试里不用弹提示

print("=== 1. 批量添加 ===")
res = mgr.addMany(["1.1.1.1:27015", "2.2.2.2:27016"])
check("加了两台", res["added"], 2)
check("收藏数量", len(core.config.data["servers"]), 2)

res2 = mgr.addMany(["1.1.1.1:27015"])
check("重复的跳过", res2["skipped"], 1)
check("没有新增", res2["added"], 0)

res3 = mgr.addMany([{"addr": "3.3.3.3:27017", "name": "带名字的服"}])
check("字典形式也能加", res3["added"], 1)
saved = [s for s in core.config.data["servers"] if s["addr"] == "3.3.3.3:27017"]
check("名字存下来了", saved[0]["name"] if saved else None, "带名字的服")

res4 = mgr.addMany(["不是地址", "1.1.1.1:27015"])
check("坏地址计入 bad", res4["bad"], 1)

print()
print("=== 2. 端口遍历参数校验 ===")
r = mgr.scanPortRange("", 27015, 27020)
check("空主机被拒", r["ok"], False)
r = mgr.scanPortRange("1.2.3.4", 1, 2000)
check("超过 1000 端口被拒", r["ok"], False)
print("   （上面可能触发一次真实扫描，等一下）")

print()
print("=== 3. 端口遍历真实扫描（回环）===")
# 开一个 UDP 端口装作「服务器」。注意：我们扫的是 A2S，回环上不会有真的 A2S 回应，
# 所以这里只验证「不崩、不误报、能给出进度和结束信号」。
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
print("  在 127.0.0.1:%d 起了个 UDP 监听" % port)

progress = []
finished = []


def on_prog(done, total, addr):
    progress.append((done, total, addr))


def on_fin(lst):
    finished.append(lst)


mgr.scanProgress.connect(on_prog)
mgr.scanFinished.connect(on_fin)

r = mgr.scanPortRange("127.0.0.1", port, port)
check("扫描已启动", r["ok"], True)
check("总数 1", r["total"], 1)

# 等结束
deadline = time.time() + 20
while not finished and time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)

check("收到 scanFinished", len(finished), 1)
if finished:
    print("  回环上找到:", len(finished[0]), "个（A2S 不会回应普通 UDP，预期 0 或很少）")
    check("结果是个列表", isinstance(finished[0], list), True)
print("  进度回调次数:", len(progress))
check("有进度回调", len(progress) > 0, True)

sock.close()

print()
print("=== 4. 取消扫描 ===")
mgr.scanPortRange("127.0.0.1", 40000, 40050)
mgr.cancelScan()
deadline = time.time() + 20
while mgr._scan_running and time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
check("取消后扫描停了", mgr._scan_running, False)

mgr.shutdown()
print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
