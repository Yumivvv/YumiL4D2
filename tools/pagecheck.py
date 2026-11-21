"""切到 MOD 页跑一遍扫描，看 stderr 有没有 QML 警告（判断是否只是测试里的目录切换噪音）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.core import Core
from app.util import ROOT


def log(*a):
    print(*a, flush=True)


app = QGuiApplication(sys.argv[:1])
engine = QQmlApplicationEngine()
q = os.path.join(ROOT, "qml")
engine.addImportPath(q)
engine.addImportPath(os.path.join(q, "components"))

core = Core(app)
engine.rootContext().setContextProperty("core", core)
engine.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))
if not engine.rootObjects():
    log("LOAD FAILED")
    sys.exit(1)

win = engine.rootObjects()[0]
win.show()
mgr = core.mods


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run():
    wait(3000)
    log("切到 MOD 页 …")
    win.setProperty("section", 1)
    for _ in range(40):
        wait(250)
        if not mgr.busy and mgr.localCount:
            break
    log("localCount =", mgr.localCount)

    log("点开详情 -> 打开设置 -> 切页 …")
    win.setProperty("section", 0)
    wait(500)
    win.setProperty("detailOpen", True)
    wait(400)
    win.setProperty("settingsOpen", True)
    wait(500)
    log("detailOpen =", win.property("detailOpen"), " settingsOpen =", win.property("settingsOpen"))
    win.setProperty("settingsOpen", False)
    wait(300)
    win.setProperty("section", 1)
    wait(600)
    log("切回视频页再退出（确认上面的 QML 警告是不是只在拆除 MOD 页时出现）")
    win.setProperty("section", 0)
    wait(600)
    log("OK")
    # 直接退：app.quit() 会被 QML onClosing（收进托盘模式）拦住，退不出去
    import os
    import sys
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


QTimer.singleShot(300, run)
QTimer.singleShot(60000, lambda: __import__("os")._exit(1))
app.exec()
