# -*- coding: utf-8 -*-
"""截「分类管理」的图（管理弹窗 + 删除确认框）。

★ 不走「按坐标找⋯」那条路 —— 那需要在 QQuickItem 树里翻找，容易受
  窗口初始化时序影响。这里直接用 `QMetaObject.invokeMethod` 调 QML 函数
  `openCategoryManager(key)` 把弹窗打开然后抓图，稳定得多。
  （「⋯ 点得到」这件事由 `category_manage_test.py` 用真实点击验证。）

用法：python -X utf8 tools/shot_category_manage.py [输出目录]
"""
import os
import sys

ROOT = r"C:\Users\ZengDeRong\Desktop\编程\求生之路2公开"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import (Q_ARG, QEventLoop, QMetaObject, QObject,  # noqa: E402
                            QTimer, QUrl)
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import Core  # noqa: E402
from app.util import ROOT as APP_ROOT  # noqa: E402

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TEMP", ".")


def log(*a):
    print(*a, flush=True)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    app = QApplication(sys.argv[:1])
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
    wait(1600)

    mgr = core.mods
    win.setProperty("section", 1)
    wait(1400)

    k1 = mgr.createCategory("二次元人物")["key"]
    mgr.createCategory("我的常用武器")
    fake = {
        "path": os.path.join("C:\\fake\\addons", "shotcat.vpk"),
        "name": "shotcat.vpk", "stem": "Category Screenshot Mod",
        "size": 1024 * 1024, "sizeText": "1.0 MB", "mtime": 1700000000,
        "workshopId": "666666",
    }
    deco = mgr._decorate(fake, {}, is_local=False)
    mgr._all_workshop = [deco]
    mgr._all_local = []
    mgr._apply_filter()
    mgr.modsChanged.emit()
    mgr.setModCategory(deco["path"], k1)
    wait(1000)

    panel = win.findChild(QObject, "modPanelRoot")
    if panel is None:
        log("no modPanelRoot")
        return 1

    # ---- ① 管理弹窗（已有的分类）----
    ok = QMetaObject.invokeMethod(panel, "openCategoryManager",
                                  Q_ARG("QVariant", k1))
    log("openCategoryManager ->", ok)
    wait(900)
    p1 = os.path.join(OUT_DIR, "cat_mgr_dlg.png")
    win.grabWindowShot(p1)
    log("saved:", p1)

    # ---- ② 删除确认框 ----
    ok2 = QMetaObject.invokeMethod(panel, "askDeleteCategory")
    log("askDeleteCategory ->", ok2)
    wait(900)
    p2 = os.path.join(OUT_DIR, "cat_del_dlg.png")
    win.grabWindowShot(p2)
    log("saved:", p2)

    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
