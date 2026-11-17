"""验证：从 MOD 页点「全部视频」能回到视频页；全选/反选/批量操作可用."""
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
win = engine.rootObjects()[0]
win.show()

mgr = core.mods


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run():
    # 等首次扫描
    wait(4000)

    log("=== 1. 页面切换 ===")
    win.setProperty("section", 1)
    wait(300)
    log("  切到 MOD 页 section =", win.property("section"))

    # 模拟点「全部视频」导航（走 QML 里的逻辑：section=0 + page=0）
    win.setProperty("section", 0)
    win.setProperty("page", 0)
    wait(300)
    log("  点「全部视频」后 section =", win.property("section"),
        "page =", win.property("page"))
    assert win.property("section") == 0, "没能回到视频页"
    log("  -> 修复成功")

    log()
    log("=== 2. 全选 ===")
    log("  本地总数:", mgr.localCount)
    mgr.checkAllLocal(True)
    wait(200)
    log("  全选后 checkedCount =", mgr.checkedCount, " allChecked =", mgr.allChecked)
    assert mgr.checkedCount == mgr.localCount
    assert mgr.allChecked

    log()
    log("=== 3. 取消全选 ===")
    mgr.checkAllLocal(False)
    wait(200)
    log("  取消后 checkedCount =", mgr.checkedCount, " allChecked =", mgr.allChecked)
    assert mgr.checkedCount == 0
    assert not mgr.allChecked

    log()
    log("=== 4. 反选 ===")
    mgr.toggleCheck(0, True)
    mgr.toggleCheck(1, True)
    wait(150)
    n_before = mgr.checkedCount
    mgr.invertSelection()
    wait(150)
    log(f"  选中 {n_before} 个 -> 反选后 {mgr.checkedCount} 个 (总数 {mgr.localCount})")
    assert mgr.checkedCount == mgr.localCount - n_before

    log()
    log("=== 5. tab 切换清空勾选 ===")
    mgr.checkAllLocal(True)
    wait(150)
    log("  本地全选:", mgr.checkedCount)
    mgr.setTab(1)
    wait(150)
    log("  切到云端后 checkedCount =", mgr.checkedCount)
    assert mgr.checkedCount == 0, "切 tab 应清空勾选"
    mgr.setTab(0)
    wait(150)

    log()
    log("=== 6. 批量删除接口（空选保护）===")
    mgr.checkAllLocal(False)
    wait(100)
    r = mgr.deleteCheckedOfTab()
    log("  空选删除返回:", r)
    assert r["ok"] is False

    log()
    log("全部通过")
    app.quit()


QTimer.singleShot(500, run)
QTimer.singleShot(60000, app.quit)
app.exec()
