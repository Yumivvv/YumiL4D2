# -*- coding: utf-8 -*-
"""真窗口冒烟：创意工坊顶栏的刷新按钮确实在、点了会走进 browseRefresh。

`ws_refresh_test.py` 验的是后端状态机（不打网络、直接调 `browseRefresh`）。
这里补的是**界面接线**那一段：QML 里那个按钮有没有真的挂上去、
点击有没有打到 `core.mods.browseRefresh`、失败态的那两个新元素在不在。

不联网：`WN.fetch_workshop_list` 被换成固定假数据 / 固定失败。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
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


def collect_names(root) -> set:
    found = set()

    def walk(o):
        try:
            n = o.objectName()
            if n:
                found.add(n)
        except Exception:
            pass
        for c in o.children():
            walk(c)

    walk(root)
    return found


def fake_items(n: int = 30) -> list:
    return [{"id": str(3800000000 + i), "title": f"m{i}", "preview": "",
             "author": "", "fileType": 0, "views": 0, "subs": 0,
             "favorited": 0, "children": 0, "created": 0, "updated": 0,
             "tags": []} for i in range(n)]


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
        wait(1200)

        mgr = core.mods

        # ------------------------------------------------------ 1. 按钮在
        print("=== 1. 工坊页加载 + 刷新按钮接线 ===")
        win.setProperty("section", 2)
        wait(900)
        names = collect_names(win)
        check("工坊页已加载", "workshopPage" in names)
        check("顶栏刷新按钮在", "wsRefreshBtn" in names,
              "（只在 Repeater 委托里的才查不到，这个不是）")
        check("旧的 API Key 输入框没了", "steamKeyInput" not in names)
        check("旧的 API Key 区块没了", "steamKeySection" not in names)

        page = win.findChild(QObject, "workshopPage")
        check("拿得到 workshopPage", page is not None)

        # ------------------------------------------------------ 2. 点它
        print("=== 2. 点刷新 -> 真的重新拉一次 ===")
        wait(600)                      # 让首屏那次自己跑完
        before = state["calls"]
        if page is not None:
            page.metaObject()  # noqa: B018  确保对象活着
            # 走 QML 里的那个函数（等价于点按钮，只是不用真的模拟鼠标坐标）
            from PySide6.QtCore import QMetaObject, Q_ARG
            ok = QMetaObject.invokeMethod(page, "refreshList")
            check("refreshList 可调用", ok is True, str(ok))
        wait(900)
        check("刷新确实又发了一次请求", state["calls"] > before,
              f"{before} -> {state['calls']}")
        check("刷新后列表有内容", len(mgr.browseItems) == 30,
              str(len(mgr.browseItems)))
        check("刷新后不在 loading", mgr.browseLoading is False)

        # ------------------------------------------------------ 3. 失败态
        print("=== 3. 拉取失败：停转圈 + 显示原因 + 给「重新加载」===")
        state["mode"] = "fail"
        WN.clear_list_cache()
        core.mods.browseRefresh()
        wait(1000)
        check("失败后 browseLoading=False（转圈必须停）",
              mgr.browseLoading is False, f"{mgr.browseLoading}")
        check("失败原因非空", mgr.browseError != "", mgr.browseError[:50])
        check("列表被清空", mgr.browseItems == [])

        # QML 侧的失败提示：源码里必须同时有「原因」和「重新加载」两条
        ws = open(os.path.join(APP_ROOT, "qml", "components",
                               "WorkshopPage.qml"), encoding="utf-8").read()
        check("失败态显示具体原因", "列表没拉下来" in ws or "browseError" in ws)
        check("失败态给「重新加载」按钮", "重新加载" in ws)
        check("空状态和失败态分开判",
              "page.mgr.browseError.length > 0" in ws)

        # 点「重新加载」应该恢复
        state["mode"] = "ok"
        if page is not None:
            from PySide6.QtCore import QMetaObject
            QMetaObject.invokeMethod(page, "refreshList")
        wait(1000)
        check("重新加载后恢复出列表", len(mgr.browseItems) == 30,
              str(len(mgr.browseItems)))
        check("恢复后 error 清空", mgr.browseError == "", mgr.browseError[:50])

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
