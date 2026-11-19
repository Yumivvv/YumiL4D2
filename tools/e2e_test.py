"""端到端自检（带事件循环）：模拟真实扫描 → 发现新视频 → 发通知."""
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
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

from app.core import Core

app = QGuiApplication(sys.argv[:1])
core = Core(app)

state = {"phase": 0, "finished": False}


def say(*a):
    print(*a, flush=True)


def on_scan(ok, msg, count):
    say(f"[scan] ok={ok} count={count} msg={msg}")
    if state["phase"] == 0:
        # 首次基线已完成，删掉 2 条模拟「新视频」
        items = core.library.all_items()[:2]
        for v in items:
            core.library.remove(v["bvid"])
        say("删除了", len(items), "条，准备再扫")
        state["phase"] = 1
        QTimer.singleShot(800, core.scan_now)
    else:
        core.library.save()
        state["finished"] = True
        QTimer.singleShot(4000, app.quit)


def on_new(items):
    say(f"[NEW] 检测到 {len(items)} 个新视频")
    for it in items[:3]:
        say("   -", it["title"][:34], "|", it["author"])


core.scanFinished.connect(on_scan)
core.newItemsFound.connect(on_new)

# 强制重新建立基线
core.library.clear_all()
core.library.meta["first_run"] = True
core.library.save()

QTimer.singleShot(500, core.scan_now)
QTimer.singleShot(75000, app.quit)

app.exec()
say("finished:", state["finished"])
sys.exit(0 if state["finished"] else 1)
