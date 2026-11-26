# -*- coding: utf-8 -*-
"""真窗口验「下载位置」设置：显示、改目录、迁移提示、恢复默认。

不联网、不动用户文件：把下载目录都指向临时目录。
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
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import downloads as D  # noqa: E402
from app import util  # noqa: E402
from app.core import Core  # noqa: E402
from app.util import ROOT as APP_ROOT  # noqa: E402

FAILS: list[str] = []
tmp = tempfile.mkdtemp(prefix="l4d2_dlui_")
old_root = util.ROOT
util.ROOT = tmp


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    app = QApplication(sys.argv[:1])

    eng = QQmlApplicationEngine()
    warns = []
    eng.warnings.connect(lambda ws: [warns.append(w.toString()) for w in ws])
    qml = os.path.join(APP_ROOT, "qml")
    eng.addImportPath(qml)
    eng.addImportPath(os.path.join(qml, "components"))
    core = Core(app)
    eng.rootContext().setContextProperty("core", core)
    eng.load(QUrl.fromLocalFile(os.path.join(qml, "Main.qml")))
    if not eng.rootObjects():
        print("LOAD FAILED")
        for w in warns[:5]:
            print("  ", w[:150])
        return 1
    win = eng.rootObjects()[0]
    win.show()
    wait(1500)

    dl = core.downloads

    # ---------------------------------------------------- 1. 默认值
    print("=== 1. 默认落在软件目录下 ===")
    default = os.path.join(tmp, "downloads")
    check("默认下载目录 = 软件目录/downloads",
          os.path.normcase(dl.downloadDir) == os.path.normcase(os.path.abspath(default)),
          dl.downloadDir)
    check("标记为默认", dl.isDefaultDownloadDir is True)
    check("没有待迁移文件", dl.pendingCount == 0, dl.pendingCount)

    # ---------------------------------------------------- 2. 设置页元素
    print("=== 2. 设置页里有这些控件 ===")
    # ★ 设置页是 section **5**（不是 4 —— 4 是「下载」页）。
    #   传错的话整页 visible=False，下面所有 findChild 都能找到对象、
    #   但 visible 永远是 False，断言会莫名其妙地红。
    win.setProperty("section", 5)
    wait(1400)
    names = set()

    def walk(o):
        try:
            n = o.objectName()
            if n:
                names.add(n)
        except Exception:
            pass
        for c in o.children():
            walk(c)

    walk(win)
    for want in ("downloadDirSection", "downloadDirText", "downloadDirChooseBtn",
                 "downloadDirResetBtn", "downloadDirOpenBtn"):
        check(f"有 {want}", want in names)
    check("有选目录的对话框", win.findChild(QObject, "downloadDirDlg") is not None)

    txt = win.findChild(QObject, "downloadDirText")
    check("路径框显示的是当前目录",
          txt is not None and str(txt.property("text")) == dl.downloadDir,
          txt.property("text") if txt else "no txt")

    reset_btn = win.findChild(QQuickItem, "downloadDirResetBtn")
    check("默认状态下「恢复默认」是灰的",
          reset_btn is not None and reset_btn.property("enabledBtn") is False,
          reset_btn.property("enabledBtn") if reset_btn else "missing")

    # ---------------------------------------------------- 3. 改目录 + 迁移提示
    print("=== 3. 改到自定义目录 -> 旧文件出现迁移提示 ===")
    # 旧目录放两个文件
    os.makedirs(os.path.join(default, "pan"), exist_ok=True)
    os.makedirs(os.path.join(default, "video"), exist_ok=True)
    with open(os.path.join(default, "pan", "旧资源.rar"), "wb") as f:
        f.write(b"x" * 300)
    with open(os.path.join(default, "video", "旧视频.mp4"), "wb") as f:
        f.write(b"y" * 400)

    custom = os.path.join(tmp, "自定义下载")
    r = dl.setDownloadDir(custom)
    check("改目录成功", r.get("ok") is True, str(r))
    check("新目录生效", os.path.normcase(dl.downloadDir) ==
          os.path.normcase(os.path.abspath(custom)), dl.downloadDir)
    check("不再是默认", dl.isDefaultDownloadDir is False)
    wait(400)
    check("发现 2 个待迁移文件", dl.pendingCount == 2, dl.pendingCount)
    check("待迁移大小是文字", bool(dl.pendingSizeText), dl.pendingSizeText)

    box = win.findChild(QQuickItem, "downloadDirMigrateBox")
    check("迁移提示框出现了", box is not None and box.property("visible") is True,
          box.property("visible") if box else "missing")

    # ---------------------------------------------------- 4. 先不搬
    print("=== 4. 「先不搬」后提示消失 ===")
    dl.dismissMigrateHint()
    wait(400)
    check("提示数归零", dl.pendingCount == 0, dl.pendingCount)
    check("文件还在原位（没被删）",
          os.path.isfile(os.path.join(default, "pan", "旧资源.rar")))

    # ---------------------------------------------------- 5. 真搬
    print("=== 5. 一起搬过去 ===")
    # 重新允许提示（等价于又改了一次目录）
    dl.setDownloadDir(custom)
    wait(300)
    check("提示回来了", dl.pendingCount == 2, dl.pendingCount)
    mv = dl.migrateDownloads()
    check("搬成功 2 个", len(mv.get("moved") or []) == 2, str(mv))
    check("新目录里有 pan/旧资源.rar",
          os.path.isfile(os.path.join(custom, "pan", "旧资源.rar")))
    check("新目录里有 video/旧视频.mp4",
          os.path.isfile(os.path.join(custom, "video", "旧视频.mp4")))
    check("旧文件已不在", not os.path.isfile(
        os.path.join(default, "pan", "旧资源.rar")))
    wait(300)
    check("搬完提示自动消失", dl.pendingCount == 0, dl.pendingCount)

    # ---------------------------------------------------- 6. 恢复默认
    print("=== 6. 恢复默认 ===")
    r2 = dl.setDownloadDir("")
    check("恢复成功", r2.get("ok") is True, str(r2))
    check("又回到默认目录",
          os.path.normcase(dl.downloadDir) == os.path.normcase(os.path.abspath(default)),
          dl.downloadDir)
    check("标记回默认", dl.isDefaultDownloadDir is True)

    # ---------------------------------------------------- 7. 源码断言
    print("=== 7. 实现要点（别改回去）===")
    dl_src = open(os.path.join(ROOT, "app", "downloads.py"),
                  encoding="utf-8").read()
    check("配置项存在", '"download_dir"' in open(
        os.path.join(ROOT, "app", "store.py"), encoding="utf-8").read())
    check("有 downloadRoot()", "def downloadRoot(" in dl_src)
    check("pan/video 都走可配目录（不再写死 util.ROOT）",
          'os.path.join(util.ROOT, "downloads", "pan")' not in dl_src
          and 'os.path.join(util.ROOT, "downloads", "video")' not in dl_src)
    check("有迁移方法", "def migrateDownloads(" in dl_src)
    check("重名跳过（不覆盖）", "skipped.append(name)" in dl_src)
    check("配置存空串表示默认（不存死路径）",
          'self._cfg["download_dir"] = os.path.abspath(raw) if raw else ""'
          in dl_src)
    # 默认目录不可用时要退回默认，而不是让下载全废
    check("配的目录不可用时退回默认",
          "download dir unusable" in dl_src)

    qml_src = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    check("设置页有下载位置区块",
          'objectName: "downloadDirSection"' in qml_src)
    check("有选文件夹的 FolderDialog",
          "downloadDirDlg" in qml_src and "FolderDialog {" in qml_src)
    check("迁移提示只在有待搬文件时出现",
          "visible: pending > 0" in qml_src)

    # ---------------------------------------------------- 8. QML 告警
    print("=== 8. QML 告警 ===")
    bad = [w for w in warns if "Main.qml" in w and "downloadDir" in w.lower()]
    check("下载位置相关没有 QML 告警", not bad,
          " / ".join(x[:110] for x in bad[:3]))

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        util.ROOT = old_root
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
