"""抓「日间模式 + 列表滚动」那一屏，验证顶部渐隐遮罩不再是一条黑杠。

跑法：python -X utf8 tools/shot_fade.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

_SANDBOX = protect_user_data(verbose=False)

# 沙盒里默认没有视频库，列表会是空的、看不到顶部遮罩。
# 复制一份真实库进去（只读用，不改它），让列表有内容可滚。
import shutil  # noqa: E402

_real_lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "library.json")
if os.path.isfile(_real_lib):
    shutil.copy2(_real_lib, os.path.join(_SANDBOX, "library.json"))

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from app.core import Core  # noqa: E402
from app.util import ROOT  # noqa: E402

OUT_DIR = os.environ.get("TEMP", ROOT)


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
        return 1
    win = engine.rootObjects()[0]
    win.show()
    wait(2000)

    # 切日间
    core.setAppearance("light")
    wait(600)

    # 让视频列表滚下去一点，顶部遮罩才会出现
    lv = find_name(win, "videoList")
    if lv is None:
        # 没有 objectName 就按类型找 ListView
        from PySide6.QtCore import QObject
        for o in walk(win):
            try:
                if o.metaObject().className().startswith("QQuickListView"):
                    lv = o
                    break
            except Exception:
                pass
    if lv is not None:
        lv.setProperty("contentY", 260.0)
        wait(500)
        log("contentY =", lv.property("contentY"))
    else:
        log("[warn] 没找到列表")

    out = os.path.join(OUT_DIR, "fade_light.png")
    if os.path.exists(out):
        os.remove(out)
    win.grabPreview(out)
    for _ in range(30):
        wait(100)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            break
    log("saved:", os.path.exists(out), out)

    real = [w for w in warns if any(k in w for k in (
        "TypeError", "not defined", "Unable", "ReferenceError", "Binding loop",
        "is not a function", "Cannot assign"))]
    log("可疑告警:", len(real))
    for r in real[:5]:
        log("  !", r[:160])
    core.shutdown()
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
