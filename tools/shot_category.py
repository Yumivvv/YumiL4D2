# -*- coding: utf-8 -*-
"""截一张「详情面板 → 分类选择器」的图（分类功能是这次新加的，原来的
shot.py 没有对应模式，而 Popup 需要连 overlay 一起抓才能拍到）。

用法：python -X utf8 tools/shot_category.py 输出路径
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402
protect_user_data(verbose=False)

from PySide6.QtCore import QMetaObject, QObject, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from app.core import Core  # noqa: E402
from app.util import ROOT as APP_ROOT  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "mod_category_shot.png")


def log(*a):
    print(*a, flush=True)


def wait_ms(ms: int) -> None:
    from PySide6.QtCore import QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    app = QGuiApplication(sys.argv[:1])
    eng = QQmlApplicationEngine()
    qml = os.path.join(APP_ROOT, "qml")
    eng.addImportPath(qml)
    eng.addImportPath(os.path.join(qml, "components"))
    core = Core(app)
    eng.rootContext().setContextProperty("core", core)
    eng.load(QUrl.fromLocalFile(os.path.join(qml, "Main.qml")))
    if not eng.rootObjects():
        log("LOAD FAILED")
        return 1
    win = eng.rootObjects()[0]
    win.show()
    wait_ms(1500)

    mgr = core.mods
    win.setProperty("section", 1)
    wait_ms(800)

    items = mgr.browseItems or []
    _ = items
    # 用现有库里的一条（有封面看着更直观）
    all_items = mgr.allModel.items() if hasattr(mgr.allModel, "items") else []
    pick = next((m for m in all_items if m.get("hasImage")), None) or (
        all_items[0] if all_items else None)
    if pick is None:
        log("没有 MOD，截不了")
        return 1
    log("pick:", pick.get("title"), "| 自动分类:", pick.get("categoryLabel"))
    mgr.selectMod(pick["path"])
    wait_ms(900)

    panel = win.findChild(QObject, "modPanelRoot")
    if panel is not None:
        # 先建一个自建分类，图上能同时看到「内置 + 自建」
        r = mgr.createCategory("我的常用")
        log("createCategory:", r)
        wait_ms(200)
        ok = QMetaObject.invokeMethod(panel, "openCategoryPicker")
        log("openCategoryPicker:", ok)
    wait_ms(900)

    dlg = win.findChild(QObject, "catPicker")
    log("picker opened:", dlg.property("opened") if dlg else None)

    def shoot():
        win.grabWindowShot(OUT)
        QTimer.singleShot(900, finish)

    def finish():
        log("saved:", os.path.exists(OUT), OUT)
        app.quit()

    QTimer.singleShot(600, shoot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
