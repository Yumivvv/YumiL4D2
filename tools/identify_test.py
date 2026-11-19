# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys, os
sys.path.insert(0, ".")
from PySide6.QtCore import QTimer, QEventLoop
from PySide6.QtGui import QGuiApplication
from app.modmanager import ModManager

app = QGuiApplication(sys.argv[:1])
mgr = ModManager()

# 等扫描完成
loop = QEventLoop()
mgr.scannedChanged.connect(lambda: loop.quit())
QTimer.singleShot(3000, loop.quit)
mgr.scan()
loop.exec()
print("扫描后 local =", mgr.localCount, flush=True)

# 等识别完成
loop2 = QEventLoop()
done = {"v": False}
def on_busy():
    if not mgr.busy and done["v"]:
        loop2.quit()
mgr.busyChanged.connect(on_busy)
QTimer.singleShot(200, mgr.identifyWorkshop)
done["v"] = True
QTimer.singleShot(120000, loop2.quit)
loop2.exec()
print("识别后 status:", mgr.statusText, flush=True)

m = mgr.localModel
known = 0
shown = 0
for i in range(m.rowCount()):
    idx = m.index(i, 0)
    isk = m.data(idx, 0x0100 + m.ROLES.index("isKnown"))
    if isk: known += 1
    if isk and shown < 8:
        print(f"   {m.data(idx, 0x0100+m.ROLES.index('workshopId')):>12s} | "
              f"图:{'有' if m.data(idx, 0x0100+m.ROLES.index('hasImage')) else '无'} | "
              f"{m.data(idx, 0x0100+m.ROLES.index('title'))[:46]}", flush=True)
        shown += 1
print(f"\n已识别 {known}/{m.rowCount()}", flush=True)
