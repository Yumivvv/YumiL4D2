# -*- coding: utf-8 -*-
"""「MOD 管理器的分类能删掉」的回归 —— 用**真鼠标**点，不是直接调函数。

## 用户报的

> MOD管理器添加删除分类的功能，这边遗留了分类不知道怎么删除

根因不是后端没实现：`createCategory` / `renameCategory` / `deleteCategory`
三个方法**早就都写好了**（上一轮加分类功能时一起写的），
但 QML 里**一次都没调用过** —— 界面上没有任何入口。
所以用户建错的分类只能一直挂着。

## 现在加了什么

- 左侧「分类」标题行右端加「+ 新建」
- **自建分类**悬停时右端出现「⋯」，点开是「管理分类」弹窗：
  改名 / 删除分类
- 删除要二次确认，并说清「删的是这一栏，不是这些 MOD」

## 为什么必须真点

上一轮工坊「重新加载」就是代码全对、按钮被挡住点不到，源码断言一条没发现。
这里的「⋯」是叠在整行 MouseArea 之上的小按钮，更容易被吃掉点击，
所以用 QTest 按真实坐标点。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import (QEventLoop, QObject, QPoint, QPointF,  # noqa: E402
                            Qt, QTimer, QUrl)
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


def find_item(root, name):
    return root.findChild(QQuickItem, name)


def find_obj(root, name):
    return root.findChild(QObject, name)


def win_point(win, item):
    """QQuickItem 中心点 → 窗口坐标。"""
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
    pt = win_point(win, item)
    if pt is None:
        return False
    QTest.mouseMove(win, pt)
    wait(80)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, pt)
    wait(200)
    return True


def main() -> int:
    app = QApplication(sys.argv[:1])

    eng = QQmlApplicationEngine()
    warns: list = []
    eng.warnings.connect(lambda ws: [warns.append(w.toString()) for w in ws])
    qml = os.path.join(APP_ROOT, "qml")
    eng.addImportPath(qml)
    eng.addImportPath(os.path.join(qml, "components"))
    core = Core(app)
    eng.rootContext().setContextProperty("core", core)
    eng.load(QUrl.fromLocalFile(os.path.join(qml, "Main.qml")))
    if not eng.rootObjects():
        print("LOAD FAILED")
        for w in warns[:6]:
            print("  ", w[:150])
        return 1
    win = eng.rootObjects()[0]
    win.show()
    wait(1500)

    mgr = core.mods
    win.setProperty("section", 1)     # MOD 管理器
    wait(1200)

    # ---------------------------------------------------- 1. 造两个分类
    print("=== 1. 先建两个分类（空分类也必须出现在侧边栏）===")
    r1 = mgr.createCategory("临时测试分类")
    r2 = mgr.createCategory("要保留的分类")
    check("建了第一个", r1.get("ok") is True, str(r1))
    check("建了第二个", r2.get("ok") is True, str(r2))
    key_del = r1.get("key")
    key_keep = r2.get("key")
    wait(600)
    # ★★ 这两个都是**空分类**（0 个 MOD）。以前 `categoryCounts` 会把它们
    #   整行滤掉，于是侧边栏里根本没有那一行 —— 用户「找不到删除和重命名的
    #   选项」就是因为它。现在必须可见。
    cats0 = [c["key"] for c in mgr.categoryCounts]
    check("★ 空分类也出现在 categoryCounts 里",
          key_del in cats0 and key_keep in cats0, str(cats0))

    # ★ 空的分类不会出现在 categoryCounts 里（只列有内容的），
    #   所以这里给它塞一条 MOD 让它显形。
    # 再给 key_del 归一个 MOD（后面验证「删分类不删 MOD」要用到）
    fake = {
        "path": os.path.join("C:\\fake\\addons", "cattest.vpk"),
        "name": "cattest.vpk", "stem": "Category Test Mod",
        "size": 1024, "sizeText": "1.0 KB", "mtime": 1700000000,
        "workshopId": "777777",
    }
    deco = mgr._decorate(fake, {}, is_local=False)
    mgr._all_workshop = [deco]
    mgr._all_local = []
    mgr._apply_filter()
    mgr.modsChanged.emit()
    mgr.setModCategory(deco["path"], key_del)
    wait(700)
    cats = [c["key"] for c in mgr.categoryCounts]
    check("归了 MOD 之后仍在", key_del in cats, str(cats))

    # ---------------------------------------------------- 2. 新建按钮
    print("=== 2. 「+ 新建」点得动，而且没走出侧边栏 ===")
    newbtn = find_item(win, "modCatNewBtn")
    check("找得到「+ 新建」", newbtn is not None)
    if newbtn is not None:
        # ★ 用户报过「新建按钮走出 UI 外面」：原来标题行用
        #   `Row + leftPadding 8 + 弹性 Item(width-68)`，
        #   8 + 文字 + 80 + 52 超过 sideCol.width(148)，
        #   按钮右边界顶到 416（侧栏只到 408）。
        #   现在改成「文字左锚 + 按钮右锚」，这里把它钉住。
        p0 = newbtn.mapToScene(QPointF(0, 0))
        right = p0.x() + newbtn.width()
        panel = find_item(win, "modPanelRoot")
        panel_x = panel.mapToScene(QPointF(0, 0)).x() if panel else 0.0
        sidebar_right = panel_x + 160        # page.sideW
        check("★ 新建按钮没超出侧边栏右界",
              right <= sidebar_right + 1,
              f"右边界 {right:.1f} vs 侧栏 {sidebar_right:.1f}")
        check("新建按钮左边界也在侧栏内",
              p0.x() >= panel_x, f"{p0.x():.1f} vs {panel_x:.1f}")
    ok = click(win, newbtn)
    check("点得动", ok is True)
    dlg = find_obj(win, "catMgrDlg")
    check("弹出了管理弹窗", dlg is not None and bool(dlg.property("opened")) is True,
          dlg.property("opened") if dlg else "missing")
    panel = find_obj(win, "modPanelRoot")
    check("新建模式下 key 是空的",
          panel is not None and str(panel.property("catMgrKey")) == "",
          panel.property("catMgrKey") if panel else "no panel")
    # 关掉
    if dlg is not None:
        dlg.close()
    wait(300)

    # ---------------------------------------------------- 3. 「⋯」能点到
    print("=== 3. 自建分类的「⋯」点得动 -> 管理弹窗 ===")
    # ★ 「⋯」在 Repeater 委托里，`findChild(objectName)` 查不到
    #   （委托项不进 QObject 子对象树）。所以这里**按坐标找**：
    #   枚举所有 QQuickItem，挑出「宽约 18、高约 20」的那个小方块
    #   （就是 catTrail），按它的中心点一下，看弹窗开没开、key 对不对。
    #
    #   这也是唯一能证明「用户点得到」的办法 —— 上一轮工坊那颗
    #   「重新加载」就是代码全对、按钮被别的图层盖住点不到。
    def walk(item, out):
        out.append(item)
        for c in item.childItems():
            walk(c, out)

    allitems: list = []
    walk(win.contentItem(), allitems)
    cand = []
    for it in allitems:
        try:
            w = it.width()
            h = it.height()
            v = it.property("visible")
        except Exception:
            continue
        if v is False:
            continue
        # ★ 这块是「⋯」的容器（catTrail）：34 宽、20 高（右边让出 34px 给按钮）。
        #   早期是 18 宽，和 cma 缩进的量对不上会留缝。
        if 32 <= w <= 36 and 18 <= h <= 22:
            p0 = it.mapToScene(QPointF(0, 0))
            cand.append((it, p0.x(), p0.y(), w, h))

    check("侧边栏里能找到「⋯」那块（34x20）", len(cand) > 0,
          f"候选 {len(cand)} 个")
    dlg = find_obj(win, "catMgrDlg")
    hit = False
    for it, x, y, w, h in cand:
        # ★ 先 hover 到行内（不压住「⋯」），让整行 hover 成立 ——
        #   这一步证明 hover 不再被子控件抢走。
        row_pt = QPoint(int(x - 40), int(y + h / 2))
        if 0 <= row_pt.x() < win.width():
            QTest.mouseMove(win, row_pt)
            wait(250)
        # 再移到「⋯」上点下去
        pt = QPoint(int(x + w - 15), int(y + h / 2))
        if not (0 <= pt.x() < win.width() and 0 <= pt.y() < win.height()):
            continue
        QTest.mouseMove(win, pt)
        wait(300)
        QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, pt)
        wait(250)
        if dlg is not None and bool(dlg.property("opened")) \
                and panel is not None \
                and str(panel.property("catMgrKey")) == key_del:
            hit = True
            break
        if dlg is not None and bool(dlg.property("opened")):
            dlg.close()
            wait(120)
    check("★ 点「⋯」能打开管理弹窗（hover 不再自锁）", hit is True,
          f"试了 {len(cand)} 个候选")
    check("分类名回填进输入框",
          str(panel.property("catMgrName")) == "临时测试分类",
          panel.property("catMgrName") if panel else "")

    # ---------------------------------------------------- 4. 真删
    print("=== 4. 点「删除分类」-> 二次确认 -> 真删掉 ===")
    del_btn = find_item(win, "catMgrDeleteBtn")
    check("有「删除分类」按钮", del_btn is not None)
    if del_btn is None:
        print("  [skip] 删不下去了")
    else:
        ok3 = click(win, del_btn)
        check("点得动", ok3 is True)
        wait(300)
        cdlg = find_obj(win, "catDelDlg")
        check("弹出了二次确认", cdlg is not None
              and bool(cdlg.property("opened")) is True,
              cdlg.property("opened") if cdlg else "missing")
        check("确认框里写了分类名",
              str(panel.property("catDelLabel")) == "临时测试分类",
              panel.property("catDelLabel") if panel else "")
        check("确认框里带上了 MOD 数量",
              int(panel.property("catDelCount") or 0) == 1,
              panel.property("catDelCount") if panel else "")

        conf = find_item(win, "catDelConfirmBtn")
        check("有「确认删除」", conf is not None)
        if conf is not None:
            click(win, conf)
            wait(600)
            left = [c["key"] for c in mgr.categoryCounts]
            check("分类真的从侧边栏消失了", key_del not in left, str(left))
            check("那个 MOD 还在（只删分类栏，不删 MOD）",
                  len(mgr._all_workshop) > 0, len(mgr._all_workshop))
            cur = mgr._find_mod(deco["path"])
            check("MOD 回到自动分类", cur is not None
                  and cur.get("categoryManual") is False,
                  cur.get("category") if cur else "None")
            check("另一个自建分类没被误删",
                  any(c["key"] == key_keep for c in mgr.customCategories),
                  str(mgr.customCategories))

    # ---------------------------------------------------- 5. 内置分类不许删
    print("=== 5. 内置分类不给删 ===")
    r = mgr.categoryInfo("weapon")
    check("weapon 被认成内置", r.get("builtin") is True, str(r))
    check("内置分类 custom=False", r.get("custom") is False)
    d = mgr.deleteCategory("weapon")
    check("后端拒绝删内置分类", d.get("ok") is False, str(d))

    # ---------------------------------------------------- 6. 源码断言
    print("=== 6. 接线（别再只写后端不接界面）===")
    qml_src = open(os.path.join(APP_ROOT, "qml", "components", "ModPanel.qml"),
                   encoding="utf-8").read()
    check("有分类管理弹窗", 'objectName: "catMgrDlg"' in qml_src)
    check("有删除确认弹窗", 'objectName: "catDelDlg"' in qml_src)
    check("有「+ 新建」按钮", 'objectName: "modCatNewBtn"' in qml_src)
    check("有「⋯」按钮", 'objectName: "modCatMoreBtn"' in qml_src)
    check("新建调 createCategory", "mgr.createCategory(" in qml_src)
    check("改名调 renameCategory", "mgr.renameCategory(" in qml_src)
    check("删除调 deleteCategory", "mgr.deleteCategory(" in qml_src)
    check("只有自建分类显示「⋯」（内置的不给改）",
          'indexOf("u_") === 0' in qml_src)
    check("删除前有二次确认", "page.askDeleteCategory()" in qml_src)
    # ★ hover 不能再依赖整行 MouseArea 的 containsMouse —— 那会和「⋯」
    #   自己的 MouseArea 互相抢，导致按钮闪一下就没、点击被丢弃
    #   （用户报的「还是没办法删除分类」）。
    check("hover 用 HoverHandler，不依赖 cma.containsMouse",
          "HoverHandler { id: rowHover }" in qml_src
          and "readonly property bool hovered: rowHover.hovered" in qml_src)
    # ★ 只查代码行：注释里保留「不能这么写」的说明是有价值的。
    qml_code = [ln.strip() for ln in qml_src.splitlines()
                if ln.strip() and not ln.strip().startswith("//")]
    check("「⋯」不再写 enabled: shown（那会自锁）",
          not any("enabled: shown" in ln for ln in qml_code),
          [ln for ln in qml_code if "enabled: shown" in ln][:2])
    check("整行 MouseArea 给「⋯」让出右端",
          "anchors.rightMargin: (parent.custom ? 34 : 0)" in qml_src)
    # 新建按钮的布局：不能再用「Row + leftPadding + 弹性 Item」
    head = qml_src.split('objectName: "modCatNewBtn"', 1)[0]
    check("标题行不再用 leftPadding 撑布局",
          "leftPadding: 8" not in head[-900:],
          head[-200:].replace("\n", " "))

    print()
    # ---------------------------------------------------- 7. 告警
    bad = [w for w in warns if "ModPanel" in w]
    print("=== 7. QML 告警 ===")
    check("ModPanel 没有告警", not bad,
          " / ".join(x[:110] for x in bad[:3]))

    if FAILS:
        print()
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print()
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
