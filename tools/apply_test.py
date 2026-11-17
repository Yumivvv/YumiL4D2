import sys, os
sys.path.insert(0, ".")
from PySide6.QtCore import QTimer, QEventLoop
from PySide6.QtGui import QGuiApplication
from app.modmanager import ModManager

app = QGuiApplication(sys.argv[:1])
mgr = ModManager()
loop = QEventLoop()
mgr.scannedChanged.connect(lambda: loop.quit())
QTimer.singleShot(3000, loop.quit)
mgr.scan()
loop.exec()
print("local =", mgr.localCount, flush=True)
print("_all_local 数量:", len(getattr(mgr, "_all_local", [])))
if mgr._all_local:
    m0 = mgr._all_local[0]
    print("第一项 keys:", sorted(m0.keys())[:12])
    print("workshopId:", repr(m0.get("workshopId")))
    print("isKnown:", m0.get("isKnown"))
    print("cache has:", bool(mgr._wsc._meta.get(m0.get("workshopId") or "")))
    # 手动 apply
    mgr._apply_meta_to_items()
    m0b = mgr._all_local[0]
    print("apply 后 isKnown:", m0b.get("isKnown"), "title:", m0b.get("title"))
    mm = mgr.localModel
    print("model row0 isKnown:", mm.data(mm.index(0,0), 0x0100 + mm.ROLES.index("isKnown")))
