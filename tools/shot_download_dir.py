# -*- coding: utf-8 -*-
"""截一张设置页「下载位置」那一块的图（含迁移提示）。

用法：python -X utf8 tools\shot_download_dir.py [输出路径] [--pending]
"""
import os
import sys
import tempfile

ROOT = r"C:\Users\ZengDeRong\Desktop\编程\求生之路2公开"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import util  # noqa: E402
from app.core import Core  # noqa: E402
from app.util import ROOT as APP_ROOT  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "download_dir_shot.png")
WANT_PENDING = "--pending" in sys.argv

tmp = tempfile.mkdtemp(prefix="l4d2_dlshot_")
old_root = util.ROOT
util.ROOT = tmp


def log(*a):
    print(*a, flush=True)


def wait_ms(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    app = QApplication(sys.argv[:1])

    # 先造好「旧目录里还有文件」的现场（截迁移提示时用）
    dl_default = os.path.join(tmp, "downloads")
    if WANT_PENDING:
        os.makedirs(os.path.join(dl_default, "pan"), exist_ok=True)
        os.makedirs(os.path.join(dl_default, "video"), exist_ok=True)
        for n, size in (("灭世者.rar", 48 * 1024 * 1024),
                        ("教学视频.mp4", 132 * 1024 * 1024)):
            with open(os.path.join(dl_default, "pan", n), "wb") as f:
                f.write(b"x" * 4096)
        with open(os.path.join(dl_default, "video", "data", ), "wb"):
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
    wait_ms(1600)
    win.setProperty("section", 5)
    wait_ms(1400)

    dl = core.downloads
    if WANT_PENDING:
        # 改到自定义目录 -> 旧目录那两个文件变成「待迁移」
        dl.setDownloadDir(os.path.join(tmp, "D盘下载"))
        wait_ms(600)
        log("pending =", dl.pendingCount, dl.pendingSizeText)
        # 滚到「下载位置」那块
        flick = win.findChild(QObject, "settingsFlick")
        box = win.findChild(QObject, "downloadDirSection")
        if flick is not None and box is not None:
            try:
                y = box.property("y")
                flick.setProperty("contentY", max(0, y - 120))
            except Exception as e:  # noqa: BLE001
                log("scroll failed:", e)
        wait_ms(700)

    def shoot():
        win.grabWindowShot(OUT)
        QTimer.singleShot(900, finish)

    def finish():
        log("saved:", os.path.exists(OUT), OUT)
        app.quit()

    QTimer.singleShot(600, shoot)
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        util.ROOT = old_root
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
