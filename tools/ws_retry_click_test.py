# -*- coding: utf-8 -*-
"""用**真鼠标点击**验工坊页那两个「重新加载」入口，而不是直接调函数。

为什么单开一个测试：上一版 `ws_refresh_ui_test.py` 是用
`QMetaObject.invokeMethod(page, "refreshList")` 触发的 —— 那只能证明
「函数能调」，**证明不了用户点得到按钮**。用户反馈「点击重新加载没反应」，
差的正是这一层：按钮被别的 Item 盖住了，点击压根没到 MouseArea。

QML 里后声明的兄弟节点画在上面、也优先拿到鼠标。`wsGrid`
（`anchors.fill: parent`）声明在空状态那一列**之后**，而且 `visible`
只绑了 `!page.showLater` —— 列表为空时它照样铺满整个 gridWrap，
于是把空状态里那个「重新加载」按钮压在下面，点击全被 GridView 吃掉。

所以这里必须用 QTest 真的按坐标点，顺序也和用户一致：
失败 -> 点中间那个「重新加载」 -> 应恢复 -> 再失败 -> 点顶栏刷新。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import QEventLoop, QObject, QPoint, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import Core  # noqa: E402
from app import workshop_net as WN  # noqa: E402
from app.util import ROOT as APP_ROOT  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_idle(mgr, budget_ms: int = 6000) -> None:
    for _ in range(max(1, budget_ms // 50)):
        if not mgr.browseLoading and not mgr.browseLoadingMore:
            return
        wait(50)


def fake_items(n: int = 30) -> list:
    return [{"id": str(3800000000 + i), "title": f"m{i}", "preview": "",
             "author": "", "fileType": 0, "views": 0, "subs": 0,
             "favorited": 0, "children": 0, "created": 0, "updated": 0,
             "tags": []} for i in range(n)]


def find_descendant(root, object_name: str):
    """按 objectName 找（含 Repeater 之外的普通子树）。"""
    return root.findChild(QObject, object_name)


def prop(o, name, default=None):
    try:
        v = o.property(name)
        return default if v is None else v
    except Exception:
        return default


def win_geom(obj):
    """相对**窗口内容区**的坐标（和 detail_actions_test 一个算法）。

    ★ 不能一直加到根：最顶层是 Main（Window 本身），它的 x/y 是窗口在屏幕上
    的位置（比如 194,70）。把它算进来，QTest 的点击就整体偏到窗口外面。

    ★ 也不能用 `mapToScene`：`findChild` 拿到的是 QObject 包装，
      上面没有 QQuickItem 的坐标方法（会 AttributeError）。
    """
    x = y = 0.0
    cur = obj
    while cur is not None and cur.parent() is not None:
        x += float(prop(cur, "x") or 0)
        y += float(prop(cur, "y") or 0)
        cur = cur.parent()
    return x, y


def click_item(win, target) -> bool:
    """把 target 的中心点换成窗口坐标，然后真的按一下左键。

    返回 False 表示坐标落在窗口外（那也算「点不到」）。
    """
    if target is None:
        return False
    x, y = win_geom(target)
    w = float(prop(target, "width") or 0)
    h = float(prop(target, "height") or 0)
    pt = QPoint(int(x + w / 2), int(y + h / 2))
    if not (0 <= pt.x() < win.width() and 0 <= pt.y() < win.height()):
        return False
    QTest.mouseMove(win, pt)
    wait(60)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, pt)
    wait(120)
    return True


def main() -> int:
    app = QApplication(sys.argv[:1])

    real_fetch = WN.fetch_workshop_list
    state = {"mode": "ok", "calls": 0}

    def fake(*a, **k):
        state["calls"] += 1
        if state["mode"] == "fail":
            return {"ok": False, "items": [], "total": 0, "page": 1,
                    "error": "连不上 Steam 工坊页面（ConnectTimeout）",
                    "needNetwork": True}
        return {"ok": True, "items": fake_items(30), "total": 0, "page": 1,
                "error": "", "hasMore": True}

    WN.fetch_workshop_list = fake  # type: ignore[assignment]

    try:
        engine = QQmlApplicationEngine()
        engine.addImportPath(os.path.join(APP_ROOT, "qml"))
        engine.addImportPath(os.path.join(APP_ROOT, "qml", "components"))
        core = Core(app)
        engine.rootContext().setContextProperty("core", core)
        engine.load(QUrl.fromLocalFile(os.path.join(APP_ROOT, "qml", "Main.qml")))
        if not engine.rootObjects():
            print("LOAD FAILED")
            return 1
        win = engine.rootObjects()[0]
        win.show()
        wait(1500)
        mgr = core.mods

        win.setProperty("section", 2)
        wait(1200)
        page = find_descendant(win, "workshopPage")
        check("工坊页在", page is not None)
        if page is None:
            return 1

        # ---------------------------------------------------- 1. 失败态下点「重新加载」
        print("=== 1. 失败态：真鼠标点「重新加载」 ===")
        state["mode"] = "fail"
        WN.clear_list_cache()
        mgr.browseRefresh()
        wait_idle(mgr)
        wait(500)
        check("先进入失败态", mgr.browseError != "" and mgr.browseItems == [],
              f"err={mgr.browseError[:40]} items={len(mgr.browseItems)}")

        retry = find_descendant(win, "wsRetryBtn")
        check("找得到 wsRetryBtn（objectName 已加）", retry is not None,
              "没有 objectName 就点不到，也测不了")

        state["mode"] = "ok"
        before = state["calls"]
        clicked = click_item(win, retry)
        check("按钮坐标在窗口内", clicked is True)
        wait_idle(mgr, 4000)
        wait(400)
        check("点「重新加载」真的发出了新请求", state["calls"] > before,
              f"{before} -> {state['calls']}")
        check("点完恢复出列表", len(mgr.browseItems) == 30,
              str(len(mgr.browseItems)))
        check("点完 error 清空", mgr.browseError == "", mgr.browseError[:40])

        # ---------------------------------------------------- 2. 失败态下点顶栏刷新
        print("=== 2. 失败态：真鼠标点顶栏刷新 ===")
        state["mode"] = "fail"
        WN.clear_list_cache()
        mgr.browseRefresh()
        wait_idle(mgr)
        wait(400)
        check("再次进入失败态", mgr.browseItems == [] and mgr.browseError != "")

        refresh = find_descendant(win, "wsRefreshBtn")
        check("找得到 wsRefreshBtn", refresh is not None)
        state["mode"] = "ok"
        before = state["calls"]
        clicked = click_item(win, refresh)
        check("刷新按钮坐标在窗口内", clicked is True)
        wait_idle(mgr, 4000)
        wait(400)
        check("点顶栏刷新真的发出了新请求", state["calls"] > before,
              f"{before} -> {state['calls']}")
        check("点完恢复出列表", len(mgr.browseItems) == 30,
              str(len(mgr.browseItems)))

        # ---------------------------------------------------- 3. 结构断言
        print("=== 3. 结构：GridView 不能盖住空状态 ===")
        ws = open(os.path.join(APP_ROOT, "qml", "components",
                               "WorkshopPage.qml"), encoding="utf-8").read()
        grid_seg = ws.split('objectName: "wsGrid"', 1)[1][:700]
        # 列表为空时必须让开，否则它铺满 gridWrap 抢走点击
        check("wsGrid 在空列表时不可见（不抢点击）",
              "browseItems.length > 0" in grid_seg,
              grid_seg.split("visible:")[1][:120] if "visible:" in grid_seg else "无 visible")
        check("空状态那块有 z 让它浮在列表之上",
              'objectName: "wsEmptyState"' in ws)
        check("重试按钮有 objectName", 'objectName: "wsRetryBtn"' in ws)

    finally:
        WN.fetch_workshop_list = real_fetch  # type: ignore[assignment]

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
