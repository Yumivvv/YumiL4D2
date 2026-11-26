# -*- coding: utf-8 -*-
"""只截「管理分类」弹窗（不叠删除确认框）。

用法：python -X utf8 tools/shot_cat_mgr_only.py [输出路径]
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

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "cat_mgr_only.png")


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
        print("LOAD FAILED")
        return 1
    win = eng.rootObjects()[0]
    win.show()
    wait(1600)
    win.setProperty("section", 1)
    wait(1400)

    mgr = core.mods
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
        print("no panel")
        return 1
    ok = QMetaObject.invokeMethod(panel, "openCategoryManager",
                                  Q_ARG("QVariant", k1))
    print("open ->", ok)
    wait(1000)
    win.grabWindowShot(OUT)
    print("saved:", OUT)
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
