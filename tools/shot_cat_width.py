# -*- coding: utf-8 -*-
"""截一张对比图：同一张详情面板里，分类徽标「自动」和「手动指定」的宽度。

用户报的是「改分类后分类文字多出空白」，光看数字不够直观 ——
这张图把两种状态并排摆出来（上面是自动，下面那行是改过分类的）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402
protect_user_data(verbose=False)

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from app.core import Core  # noqa: E402
from app import modmanager as MM  # noqa: E402
from app.util import ROOT as APP_ROOT  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "cat_width_shot.png")


def log(*a):
    print(*a, flush=True)


def wait_ms(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    app = QGuiApplication(sys.argv[:1])
    MM.CATEGORY_OVERRIDE_PATH = os.path.join(
        os.path.join(APP_ROOT, "data"), "modcategories_shot.json")
    try:
        os.remove(MM.CATEGORY_OVERRIDE_PATH)
    except OSError:
        pass

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

    fake = {
        "path": os.path.join("C:\\fake\\addons", "shotsample.vpk"),
        "name": "shotsample.vpk",
        "stem": "+Ultra Particle: Custom Melee Trail",
        "size": 43008,
        "sizeText": "43.0 KB",
        "mtime": 1700000000,
        "workshopId": "3035669635",
    }
    deco = mgr._decorate(fake, {}, is_local=False)
    mgr._all_workshop = [deco]
    mgr._all_local = []
    mgr._apply_filter()
    mgr.modsChanged.emit()
    mgr.selectMod(deco["path"])
    wait_ms(900)
    log("自动分类:", deco.get("categoryLabel"))

    # 改成「感染者」，这样徽标上会带笔尖图标（就是以前多出空白的那种状态）
    r = mgr.setModCategory(deco["path"], "infected")
    log("改成:", r)
    wait_ms(900)

    def shoot():
        win.grabWindowShot(OUT)
        QTimer.singleShot(900, finish)

    def finish():
        log("saved:", os.path.exists(OUT), OUT)
        app.quit()

    QTimer.singleShot(500, shoot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
