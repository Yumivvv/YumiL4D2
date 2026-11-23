# -*- coding: utf-8 -*-
"""真窗口点「分类徽标」→ 选择器 → 归类，整条链路走一遍。

为什么不能只做源码断言：上一轮工坊的「重新加载」按钮就是
**代码全对、按钮点不到**（被 GridView 盖住），源码断言一条都没发现。
这次的分类徽标在详情面板里，上面还压着滚动区、图片、好几个 Flow，
更容易出现「看得见、点不着」。所以这里必须用 QTest 真按坐标点。

不联网：`_decorate` 直接喂假数据，不走工坊接口。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import (QEventLoop, QObject, QPoint, QPointF, Qt,  # noqa: E402
                             QTimer, QUrl)
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import modmanager as MM  # noqa: E402
from app.core import Core  # noqa: E402
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


def prop(o, name, default=None):
    try:
        v = o.property(name)
        return default if v is None else v
    except Exception:
        return default


def find_item(root, name):
    """按 objectName 找**QQuickItem**（不是裸 QObject）。

    ★ 必须用 QQuickItem：只有它带 `mapToScene`。`findChild(QObject, ...)` 拿到的是
      Qt 的 QObject 包装，上面没有坐标方法，只能自己累加 x/y —— 而累加在
      **Popup 内部是错的**：Popup 的 `parent()` 是它的逻辑父对象（modPanelRoot），
      绘制却在 `Overlay.overlay` 里，两边坐标系差了面板偏移量。实测偏 100 多像素，
      表现就是「点得到但没反应」。
    """
    return root.findChild(QQuickItem, name)


def win_point(win, item):
    """取 QQuickItem 中心点对应的窗口坐标（越界返回 None）。

    ★ 根对象是 **QQuickWindow**，它没有 `mapFromScene`（那是 QGraphicsView 的）。
      好在 `mapToScene` 给出的就是**窗口内容坐标**本身（QQuickWindow 里
      scene == content），直接取整拿来给 QTest 用就行。
    """
    if item is None:
        return None
    w = float(item.width())
    h = float(item.height())
    if w <= 0 or h <= 0:
        return None
    scene = item.mapToScene(QPointF(w / 2.0, h / 2.0))
    pt = QPoint(int(scene.x()), int(scene.y()))
    if not (0 <= pt.x() < win.width() and 0 <= pt.y() < win.height()):
        return None
    return pt


def click_item(win, item) -> bool:
    if item is None:
        return False
    pt = win_point(win, item)
    if pt is None:
        return False
    QTest.mouseMove(win, pt)
    wait(60)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, pt)
    wait(150)
    return True


def find_by_obj(root, name):
    return root.findChild(QObject, name)


def main() -> int:
    app = QApplication(sys.argv[:1])

    tmp = os.path.join(APP_ROOT, "data")   # guard 已把 data 指到沙盒，这里只用来拼路径
    old_meta = MM.CATEGORY_OVERRIDE_PATH
    MM.CATEGORY_OVERRIDE_PATH = os.path.join(tmp, "modcategories_test.json")
    try:
        engine = QQmlApplicationEngine()
        warns: list = []
        engine.warnings.connect(lambda ws: [warns.append(w.toString()) for w in ws])
        engine.addImportPath(os.path.join(APP_ROOT, "qml"))
        engine.addImportPath(os.path.join(APP_ROOT, "qml", "components"))
        core = Core(app)
        engine.rootContext().setContextProperty("core", core)
        engine.load(QUrl.fromLocalFile(os.path.join(APP_ROOT, "qml", "Main.qml")))
        if not engine.rootObjects():
            print("LOAD FAILED")
            for w in warns[:6]:
                print("  ", w[:160])
            return 1
        win = engine.rootObjects()[0]
        win.show()
        wait(1500)

        mgr = core.mods

        # 直接塞假数据，绕开扫描和网络
        fake = {
            "path": os.path.join("C:\\fake\\addons", "ZombieSlayerRifle.vpk"),
            "name": "ZombieSlayerRifle.vpk",
            "stem": "Zombie Slayer Rifle",
            "size": 1024 * 1024 * 2,
            "sizeText": "2.0 MB",
            "mtime": 1700000000,
            "workshopId": "999999",
        }
        deco = mgr._decorate(fake, {}, is_local=False)
        mgr._all_workshop = [deco]
        mgr._all_local = []
        mgr._apply_filter()
        mgr.modsChanged.emit()
        wait(300)

        print("=== 1. 详情面板里的分类徽标点得到 ===")
        win.setProperty("section", 1)
        wait(900)
        mgr.selectMod(deco["path"])
        wait(700)

        badge = find_item(win, "modCategoryBadge")
        check("找得到 modCategoryBadge", badge is not None)
        check("选中的这条自动判成了感染者（就是要被纠正的那种）",
              deco.get("category") == "infected", deco.get("category"))

        clicked = click_item(win, badge)
        check("徽标坐标在窗口内、点得动", clicked is True)
        wait(500)

        picker = find_by_obj(win, "catPicker")
        check("点徽标后选择器打开了",
              picker is not None and bool(prop(picker, "opened")) is True,
              prop(picker, "opened") if picker else "no picker")

        print("=== 2. 选择器里能新建分类并直接归类 ===")
        field = find_item(win, "catNameField")
        check("有新建分类的输入框", field is not None)
        before = len(mgr.customCategories)
        if field is not None:
            field.setProperty("text", "我的武器们")
            wait(120)
        btn = find_item(win, "catCreateBtn")
        clicked = click_item(win, btn)
        check("「新建并归类」点得动", clicked is True)
        wait(600)

        check("新建的分类进了清单", len(mgr.customCategories) == before + 1,
              str(mgr.customCategories))
        new_key = (mgr.customCategories[-1]["key"]
                   if mgr.customCategories else "")
        cur = mgr._find_mod(deco["path"])
        check("这条 MOD 已经归到新分类",
              cur.get("category") == new_key, cur.get("category"))
        check("显示名是用户起的名字",
              cur.get("categoryLabel") == "我的武器们",
              cur.get("categoryLabel"))
        check("标记成手动指定", cur.get("categoryManual") is True)
        check("选完自动关掉选择器",
              not prop(picker, "opened") if picker else False)

        print("=== 3. 侧边栏出现自建分类这一栏 ===")
        counts = [c["key"] for c in mgr.categoryCounts]
        check("侧边栏里有这个自建分类", new_key in counts, str(counts))

        print("=== 4. 恢复自动判断 ===")
        r = mgr.clearModCategory(deco["path"])
        check("clearModCategory 成功", r.get("ok") is True, str(r))
        back = mgr._find_mod(deco["path"])
        check("回到自动判的感染者", back.get("category") == "infected",
              back.get("category"))
        check("手动标记清掉", back.get("categoryManual") is False)

        print("=== 5. QML 告警 ===")
        bad = [w for w in warns if "ModPanel" in w]
        check("ModPanel 没有告警", not bad, " / ".join(x[:120] for x in bad[:3]))

    finally:
        MM.CATEGORY_OVERRIDE_PATH = old_meta

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
