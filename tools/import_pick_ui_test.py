# -*- coding: utf-8 -*-
"""真窗口验「导入确认框里的勾选」：默认全选、能点掉、只导勾中的。

为什么必须真点：上一轮工坊的「重新加载」按钮就是**代码全对、按钮点不到**
（被 GridView 盖住），源码断言一条都没发现。这里的勾选框在弹窗里，
行内还有 MouseArea / Text 叠着，更容易「看得见、点不着」。

拖入文件那一步用 `askImport()` 直接触发（等价于 DropArea 收到文件），
因为真拖拽没法在 QTest 里模拟；但**勾选和确认按钮都是真鼠标点**。
"""
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import (QEventLoop, QObject, QPoint, QPointF,  # noqa: E402
                             Q_RETURN_ARG, Qt, QTimer, QUrl)
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import Core  # noqa: E402
from app import modmanager as MM  # noqa: E402
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


def find_item(root, name):
    return root.findChild(QQuickItem, name)


def win_point(win, item):
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


def click(win, item) -> bool:
    if item is None:
        return False
    pt = win_point(win, item)
    if pt is None:
        return False
    QTest.mouseMove(win, pt)
    wait(50)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, pt)
    wait(120)
    return True


def _native(v):
    """QJSValue → 原生 Python 值（读 property() 拿到的都是 QJSValue）。"""
    try:
        return v.toVariant()
    except AttributeError:
        return v


def count_picked(panel) -> int:
    """清单里勾了几条（走 QML 自己的 importPickCount()）。

    ★ PySide6 的 `Q_RETURN_ARG` 只吃一个参数（`Q_RETURN_ARG("int")`），
      和 C++ / PyQt 的 `Q_RETURN_ARG(type, var)` 签名不同 —— 照 PyQt 写会
      TypeError，别想当然。
    """
    from PySide6.QtCore import QMetaObject
    out = QMetaObject.invokeMethod(panel, "importPickCount",
                                   Q_RETURN_ARG("QVariant"))
    v = _native(out)
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def picked_names(panel) -> list:
    """当前勾选的文件名列表（走 QML 的 importPicked，转成原生 list）。"""
    out = _native(panel.property("importPicked"))
    if isinstance(out, list):
        return [str(x) for x in out]
    return []


def main() -> int:
    app = QApplication(sys.argv[:1])

    tmp = tempfile.mkdtemp(prefix="l4d2_pickui_")
    addons = os.path.join(tmp, "addons")
    os.makedirs(addons, exist_ok=True)
    zpath = os.path.join(tmp, "pack.zip")
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("a.vpk", b"A")
        zf.writestr("b.vpk", b"B")
        zf.writestr("a.jpg", b"AIMG")

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
        return 1
    win = engine.rootObjects()[0]
    win.show()
    wait(1500)

    mgr = core.mods
    mgr.trySetAddonsDir(addons)
    wait(300)
    check("MOD 目录设好了", mgr.addonsDir == addons, mgr.addonsDir)

    win.setProperty("section", 1)
    wait(900)
    panel = win.findChild(QObject, "modPanelRoot")
    check("拿得到 modPanel", panel is not None)
    if panel is None:
        return 1

    # ---------------------------------------------------- 1. 弹出确认框
    print("=== 1. 拖入压缩包 -> 确认框默认全选 ===")
    from PySide6.QtCore import Q_ARG, QMetaObject
    # ★ QML 里 `function askImport(paths)` 的形参是**无类型**的，Qt 把它暴露成
    #   `askImport(QVariant)` 而不是 `(QVariantList)` —— 传错签名不会报错，
    #   只会返回 False（"No such method"），测试就莫名其妙地全红。
    ok = QMetaObject.invokeMethod(panel, "askImport",
                                  Q_ARG("QVariant", [zpath]))
    check("askImport 调用成功", ok is True, str(ok))
    wait(600)

    dlg = win.findChild(QObject, "importConfirmDlg")
    check("确认框打开了", dlg is not None and bool(dlg.property("opened")) is True,
          dlg.property("opened") if dlg else "no dlg")

    lst = find_item(win, "importPickList")
    check("勾选清单在", lst is not None and lst.height() > 0)

    # ★ 直接读 property() 拿到的是 QJSValue，len() 会 TypeError；
    #   用 QML 自己的导入勾选计数（它内部就是 importPicked.length）
    picked = panel.property("importPicked")
    picked_n = count_picked(panel)
    check("默认全选（3 个都在）", picked_n == 3, f"{picked_n} / {picked}")
    names = picked_names(panel)
    check("默认勾中了 a.vpk", any(x.lower() == "a.vpk" for x in names), str(names))
    check("默认勾中了 b.vpk", any(x.lower() == "b.vpk" for x in names), str(names))

    # ---------------------------------------------------- 2. 点掉一条
    print("=== 2. 真鼠标点掉一条 ===")
    # 清单第一行的中心点（行高 22，紧贴清单顶部）
    h = float(lst.height())
    first_row_y = float(lst.property("padding") or 0) + 6 + 11
    scene = lst.mapToScene(QPointF(lst.width() / 2.0, first_row_y))
    pt = QPoint(int(scene.x()), int(scene.y()))
    check("清单坐标在窗口内",
          0 <= pt.x() < win.width() and 0 <= pt.y() < win.height(), str(pt))
    QTest.mouseMove(win, pt)
    wait(50)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, pt)
    wait(300)

    after_n = count_picked(panel)
    check("点一下真的取消了一条", after_n == 2, f"{after_n} / {picked_names(panel)}")

    # ---------------------------------------------------- 3. 全不选
    print("=== 3. 全不选 / 全选 ===")
    panel.setProperty("importPicked", [])
    wait(150)
    check("清空后是 0 条", count_picked(panel) == 0)
    from PySide6.QtCore import Q_ARG, QMetaObject
    QMetaObject.invokeMethod(panel, "importPickAll",
                             Q_ARG("QVariant", True))
    wait(200)
    check("全选恢复成 3 条", count_picked(panel) == 3,
          str(picked_names(panel)))

    # ---------------------------------------------------- 4. 真的只导入勾中的
    print("=== 4. 取消一条后确认导入，只该落两条 ===")
    # 只勾 a.vpk 和 a.jpg（去掉 b.vpk）
    panel.setProperty("importPicked", ["a.vpk", "a.jpg"])
    wait(150)
    ok = QMetaObject.invokeMethod(panel, "doImport")
    check("doImport 调用成功", ok is True, str(ok))
    wait(1200)

    on_disk = sorted(os.listdir(addons))
    check("只导了勾中的两个", on_disk == ["a.jpg", "a.vpk"], str(on_disk))
    check("没勾的 b.vpk 没被带进来", "b.vpk" not in on_disk, str(on_disk))
    check("确认框关掉了", not bool(dlg.property("opened")))

    # ---------------------------------------------------- 5. 告警
    print("=== 5. QML 告警 ===")
    bad = [w for w in warns if "ModPanel" in w]
    check("ModPanel 没有告警", not bad, " / ".join(x[:110] for x in bad[:3]))

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
