"""抓「设置 → 主题色」那一屏（要滚到下面才看得到）。

跑法：python -X utf8 tools/shot_accent.py [输出png]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 测试会构造真的 Core()，必须先把运行时数据目录隔离到临时沙盒，
# 否则会覆盖用户真实的 config.json / library.json / 导入日期台账。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from guard import protect_user_data  # noqa: E402
protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.core import Core
from app.util import ROOT

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "preview-accent.png")


def log(*a):
    print(*a, flush=True)


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def walk(o, out=None):
    out = out if out is not None else []
    out.append(o)
    for c in o.children():
        walk(c, out)
    return out


def find_name(win, name):
    for o in walk(win):
        try:
            if o.objectName() == name:
                return o
        except Exception:
            pass
    return None


def main() -> int:
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    warns = []
    engine.warnings.connect(lambda ws: warns.extend(w.toString() for w in ws))
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.addImportPath(os.path.join(ROOT, "qml", "components"))

    core = Core(app)
    engine.rootContext().setContextProperty("core", core)
    engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    if not engine.rootObjects():
        log("LOAD FAILED")
        for w in warns:
            log("  ", w)
        return 1
    win = engine.rootObjects()[0]
    win.show()
    wait(1500)

    win.setProperty("settingsOpen", True)
    wait(800)

    flick = find_name(win, "settingsFlick")
    if flick is None:
        log("找不到 settingsFlick")
        return 1
    content_h = flick.property("contentHeight")
    view_h = flick.property("height")
    swatch = find_name(win, "accentSwatch")
    # 让主题色色块落在可视区中间偏上
    target = 0.0
    if swatch is not None:
        # 色块相对于 flick 内容的 y
        y = swatch.property("y")
        parent = swatch.parent()
        while parent is not None and parent is not flick:
            y += parent.property("y") or 0
            parent = parent.parent()
        target = max(0.0, min(content_h - view_h, y - view_h * 0.30))
    log("contentHeight =", content_h, " viewHeight =", view_h, " scrollTo =", target)
    flick.setProperty("contentY", target)
    wait(700)

    win.grabPreview(OUT)
    wait(400)
    real = [w for w in warns if any(k in w for k in (
        "TypeError", "not defined", "Unable", "ReferenceError", "Binding loop",
        "is not a function", "Cannot assign"))]
    log("可疑告警:", len(real))
    for r in real[:5]:
        log("  !", r[:160])
    log("saved:", os.path.exists(OUT), OUT)
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
