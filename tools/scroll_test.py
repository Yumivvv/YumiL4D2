"""验证：点开视频详情后，列表滚动位置不会被重置到最顶上。

这是用户报的 bug：点了某个视频 → 详情面板弹出 → 列表直接跳回开头。
根因是 `_detail_worker` 结尾调了 `_rebuild()`，而 `set_items()` 会
`beginResetModel()`，ListView 的 contentY 立刻归零。

跑法：python tools/scroll_test.py
"""
from __future__ import annotations

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
from app.util import ROOT, ensure_dirs

LOG = os.path.join(os.environ.get("TEMP", ROOT), "scroll_test.log")
try:
    os.remove(LOG)
except OSError:
    pass


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


ensure_dirs()
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


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def find_listview():
    for child in win.findChildren(QObject):
        try:
            if child.metaObject().className() == "QQuickListView":
                return child
        except RuntimeError:
            continue
    return None


def run():
    wait(2500)
    # 「只看新的」开着的话列表只有一两条，先把全部视频放出来
    core.setShowOnlyNew(False)
    core.setFilterText("")
    core.setDateFilter(0)
    win.setProperty("page", 0)
    win.setProperty("section", 0)
    wait(600)

    lv = find_listview()
    log("ListView 找到:", lv is not None)
    assert lv is not None, "没找到视频 ListView"

    count = lv.property("count")
    log("列表条数:", count)
    if count < 10:
        log("  [warn] 视频太少，跳过（至少 10 条才能验证滚动）")
        app.quit()
        return

    # 滚到中间：直接设 contentY，等价于用户拖滚动条
    lv.setProperty("contentY", 900.0)
    wait(300)
    before = float(lv.property("contentY") or 0)
    log("滚动后 contentY =", before)
    assert before > 100, f"没滚动起来（contentY={before}）"

    # 模拟点第 5 行：打开详情
    model = core.videoModel
    bvid = model.data(model.index(4, 0), 0x0100)          # 0x0100 = bvid
    log("点开第 5 条:", bvid)
    win.openDetail(bvid)

    # 详情走网络（或本地缓存），等它回来
    for _ in range(50):
        wait(200)
        if not win.property("detailLoading"):
            break
    wait(600)

    after = float(lv.property("contentY") or 0)
    log("详情加载完 contentY =", after)
    log("detailOpen =", win.property("detailOpen"))

    assert win.property("detailOpen") is True, "详情面板没打开"
    assert abs(after - before) < 2.0, (
        f"列表被弹回顶部了：before={before:.0f} after={after:.0f}")

    log()
    log("通过：点开详情后滚动位置保持住了")
    app.quit()


QTimer.singleShot(300, run)
QTimer.singleShot(90000, app.quit)
app.exec()
