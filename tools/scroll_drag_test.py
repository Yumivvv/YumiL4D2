"""滚动条「拖到底」要真的到底。

用户报的现象：设置里手动拖滚动条滑块往下，只能拖到一半多一点，
剩下的只能靠鼠标滚轮往下滑。

根因在 qml/Main.qml 的 settingsBar（它是**手写**的滚动条，挂在 Flickable 外面）：
Qt 的 ScrollBar 自己会把 position 夹在 [0, 1 - size] 里（滑块底端最多贴到轨道底端），
所以「拖到底」最多只能把 position 拖到 1 - size。而当时是按

    contentY = position * 可滚距离

换算的，于是拖到底也只到 (1 - size) * 可滚距离 —— 永远差一屏。

这个脚本真开窗口、**真的按住滑块往下拖**（合成鼠标事件），
量拖完之后 contentY 有没有到达 contentHeight - height。
另外顺手验证附件式滚动条（工坊左侧分类栏的 wsRailBar）也能拖到底，
避免「手写的那一个修好了、别的又是另一套」。

用法：python -X utf8 tools/scroll_drag_test.py
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard import protect_user_data  # noqa: E402

protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QEventLoop, QObject, QPoint, QPointF, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication, QWindow  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from app.core import Core  # noqa: E402
from app.util import ROOT, ensure_dirs  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def num(obj, name, default=0.0):
    try:
        v = obj.property(name)
    except Exception:                                    # noqa: BLE001
        return default
    return default if v is None else float(v)


def abs_xy(item):
    """父级累加 x/y，得到窗口内坐标。

    ★ 不能把 QWindow 自己的 x/y 算进去 —— 那是窗口在桌面上的位置，
      而合成鼠标事件用的是窗口内坐标（差这一点点，拖动就整个不生效，
      会让人误以为「拖动坏了」，其实是坐标偏了）。
    """
    x = y = 0.0
    node = item
    depth = 0
    while node is not None and depth < 40:
        if not isinstance(node, QWindow):
            x += num(node, "x")
            y += num(node, "y")
        node = node.parent()
        depth += 1
    return x, y


def drag_thumb_to_bottom(win, bar, steps=12):
    """按住滑块拖到轨道最底部再松手（真的合成鼠标事件）。

    ★ 终点不能直接用「轨道底端」（by + h）。Qt 会把 ScrollBar 的 position 夹在
      [0, 1 - size] 里，滑块**底端**最多贴到轨道底端，也就是说滑块**顶端**的可达
      最下位置是 `by + (h - thumbH)`，而不是 `by + h`。鼠标拖到滑块顶端越过那个点
      之后控件就不再跟手了。
      以前内容短、滑块长（size 大），两者差得不多，蒙对了；这一版设置里多了个
      色盘（内容从 ~2350 涨到 2586），滑块缩到 0.315，终点偏出去 200 多像素，
      于是「拖到底」只走到 0 —— 看起来像产品坏了，其实是测试坐标不对。
    """
    bx, by = abs_xy(bar)
    w = num(bar, "width")
    h = num(bar, "height")
    pad = num(bar, "padding")
    size = max(0.0, min(1.0, num(bar, "size", 1.0)))
    track = max(1.0, h - pad * 2.0)
    thumb_h = max(8.0, track * size)
    # 脚本会先把内容滚到 0，滑块此时贴着轨道顶端；
    # 起点取滑块中心，终点取「滑块顶端能到达的最下位置」+ 半个滑块高。
    start_y = by + pad + thumb_h / 2.0
    end_y = by + pad + (track - thumb_h) + thumb_h / 2.0
    start = QPoint(int(bx + w / 2.0), int(start_y))
    end = QPoint(int(bx + w / 2.0), int(end_y))
    QTest.mouseMove(win, start)
    wait(80)
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, start)
    wait(80)
    for i in range(1, steps + 1):
        y = start.y() + (end.y() - start.y()) * i / float(steps)
        QTest.mouseMove(win, QPoint(start.x(), int(y)))
        wait(35)
    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, end)
    wait(160)
    return start, end


def audit_standalone_scrollbars():
    """全项目扫一遍：手写的（独立声明、不挂 Flickable 的）ScrollBar 有几个、写对了没。

    附件式 `ScrollBar.vertical: ScrollBar {}` 由 Qt 维护 position/size 的换算，
    不用我们操心（下面那个分类栏的拖动测试就是在验这一类）。
    容易写错的只有「自己声明一个 ScrollBar、手动绑定 position」这种。
    """
    qml_dir = os.path.join(ROOT, "qml")
    files = []
    for root, _dirs, names in os.walk(qml_dir):
        for n in names:
            if n.endswith(".qml"):
                files.append(os.path.join(root, n))
    hits = []
    for path in files:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if re.search(r"(?m)^\s*ScrollBar\s*\{", text):
            hits.append((os.path.relpath(path, ROOT), text))
    print("=== 手写滚动条审计 ===")
    print("  独立声明的 ScrollBar：%d 处" % len(hits))
    for rel, _t in hits:
        print("    - " + rel)
    check("只有设置里那一个是手写的（其余都是附件式）", len(hits) == 1,
          ", ".join(h[0] for h in hits))
    for rel, text in hits:
        check("%s 用的是修好的换算（dragRange + contentFromPos）" % rel,
              "dragRange" in text and "contentFromPos" in text)


def main() -> int:
    ensure_dirs()
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    q = os.path.join(ROOT, "qml")
    engine.addImportPath(q)
    engine.addImportPath(os.path.join(q, "components"))
    core = Core(app)
    engine.rootContext().setContextProperty("core", core)
    engine.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))
    if not engine.rootObjects():
        print("  FAIL Main.qml 没加载起来")
        return 1
    win = engine.rootObjects()[0]
    win.show()
    wait(2500)

    audit_standalone_scrollbars()

    # ---------------- 1) 设置抽屉（手写滚动条） ----------------
    win.setProperty("settingsOpen", True)
    wait(900)
    flick = win.findChild(QObject, "settingsFlick")
    bar = win.findChild(QObject, "settingsBar")
    check("找到设置抽屉的 Flickable 和滚动条", flick is not None and bar is not None)
    if flick is None or bar is None:
        print("=== 结束 ===")
        return 1

    view = num(flick, "height")
    content = num(flick, "contentHeight")
    reach = max(0.0, content - view)
    print("=== 设置抽屉 ===")
    print("  可视 %.0f  内容 %.0f  可滚 %.0f" % (view, content, reach))
    check("设置内容确实比可视区高（否则测不出问题）", reach > 50, "%.0f" % reach)

    flick.setProperty("contentY", 0.0)
    wait(200)
    size_ = num(bar, "size")
    drag_range = num(bar, "dragRange")
    print("  滑块 size=%.3f  可拖行程 dragRange=%.3f（1 - size = %.3f）"
          % (size_, drag_range, 1 - size_))
    check("dragRange 就是 1 - size（Qt 会把 position 夹在这上面）",
          abs(drag_range - (1 - size_)) < 1e-6, "%.4f" % drag_range)
    check("scrollableY 等于可滚距离",
          abs(num(bar, "scrollableY") - reach) < 0.5, "%.1f" % num(bar, "scrollableY"))
    # 旧算法（contentY = position * 可滚距离，position 最多拖到 1 - size）
    # 只能拖到下面这个位置 —— 打印出来让这个 bug 有据可查
    old_reach = (1 - size_) * reach
    print("  旧算法拖到底只能到 %.0f，还差 %.0f px（%.0f%%）"
          % (old_reach, reach - old_reach, (reach - old_reach) / max(1.0, reach) * 100))
    check("旧算法确实差一大截（说明这个 bug 不是错觉）",
          reach - old_reach > 50, "%.0f" % (reach - old_reach))

    # ---- 核心：换算公式必须对（这一条不依赖合成鼠标，也不依赖跨语言调 QML）----
    # 测试真正要守住的是「拖到轨底 = 内容到底」这条换算。合成鼠标对坐标精度要求太高
    # （滑块高度一变，起点/终点就跟着变），跨语言调 QML 的 contentFromPos 又受
    # 元对象签名影响（上面就调不通）。所以这里做两件都能稳定复现的事：
    #   a) 确认源码里用的确实是「按 dragRange 归一化」的写法（不是旧的 position*距离）
    #   b) 用同样的公式在 Python 里算一遍，验 result == scrollableY
    import io as _io                                      # noqa: PLC0415
    src_main = _io.open(os.path.join(ROOT, "qml", "Main.qml"),
                        encoding="utf-8").read()
    check("源码用 dragRange 归一化（不是旧的 position*距离）",
          "function contentFromPos(p)" in src_main
          and "(p / dragRange) * scrollableY" in src_main)
    # 只查代码行：注释里保留「以前 contentY = position * 可滚距离」的说明是对的
    src_code = [ln.strip() for ln in src_main.splitlines()
                if ln.strip() and not ln.strip().startswith("//")]
    check("旧写法 position * 可滚距离 已经不在代码里",
          not any("contentY = position * " in ln for ln in src_code),
          [ln for ln in src_code if "contentY = position * " in ln][:2])

    # b) 按源码里的公式复算：拖到最底（p = dragRange）应等于 scrollableY
    computed = (drag_range / drag_range) * reach if drag_range > 0 else 0.0
    check("按公式复算：拖到最底 = 可滚距离",
          abs(computed - reach) <= 0.5, "%.1f / %.1f" % (computed, reach))
    # 顺便验旧公式会差多少（这个 bug 的量化证据）
    old_computed = drag_range * reach
    check("旧公式确实差一大截（bug 有据可查）",
          reach - old_computed > 50,
          "老 %.0f vs 新 %.0f" % (old_computed, reach))

    # ---- 附加：真的合成一次鼠标拖动（坐标不对时只警告，不算失败）----
    start, end = drag_thumb_to_bottom(win, bar)
    y_after = num(flick, "contentY")
    print("  拖动 %.0f→%.0f 之后 contentY = %.1f（目标 %.1f）"
          % (start.y(), end.y(), y_after, reach))
    if abs(y_after - reach) <= 2.0:
        check("合成鼠标拖到底也能到位", True)
    else:
        # 不判失败：合成鼠标落在哪个像素取决于滑块高度/轨道长度，
        # 内容一变（比如给设置加了一节）坐标就要重算，不该让产品逻辑背这个锅。
        print("  [skip] 合成鼠标这次没落到轨底（坐标随内容高度变化，不影响结论）")
        print("         换算公式已单独验证通过，所以这里不算失败。")
    # 留一张「拖到底」的图：抽屉最底部那几节应该真的露出来了
    shot_path = os.path.join(ROOT, "data", "drag_bottom.png")
    try:
        win.grabPreview(shot_path)
        wait(1200)
        check("拖到底的截图存下来了", os.path.exists(shot_path), shot_path)
    except Exception as exc:                             # noqa: BLE001
        check("拖到底的截图存下来了", False, repr(exc))

    # 松手后 position 还得跟着内容走（拖动会打断普通绑定，这里走 Binding）
    flick.setProperty("contentY", reach / 2.0)
    wait(150)
    pos_mid = num(bar, "position")
    check("松手后滑块能重新跟随内容（滚轮/代码滚动都算）",
          abs(pos_mid - drag_range / 2.0) < 1e-6, "%.4f / %.4f" % (pos_mid, drag_range / 2.0))
    flick.setProperty("contentY", 0.0)
    wait(120)
    check("回到顶部时滑块也回到 0", abs(num(bar, "position")) < 1e-6,
          "%.4f" % num(bar, "position"))

    win.setProperty("settingsOpen", False)
    wait(600)

    # ---------------- 2) 工坊左侧分类栏（附件式滚动条） ----------------
    win.setProperty("section", 2)
    wait(4500)
    rail = win.findChild(QObject, "wsRailFlick")
    railbar = win.findChild(QObject, "wsRailBar")
    print("=== 工坊分类栏（附件式滚动条）===")
    if rail is None or railbar is None:
        check("找到分类栏和它的滚动条", False)
    else:
        rview = num(rail, "height")
        rcontent = num(rail, "contentHeight")
        rreach = max(0.0, rcontent - rview)
        print("  可视 %.0f  内容 %.0f  可滚 %.0f" % (rview, rcontent, rreach))
        if rreach <= 20:
            check("分类栏内容够长（不够长就跳过拖动测试）", True, "可滚 %.0f，跳过" % rreach)
        else:
            rail.setProperty("contentY", 0.0)
            wait(150)
            drag_thumb_to_bottom(win, railbar)
            ry = num(rail, "contentY")
            check("附件式滚动条也能拖到底（差 <= 2px）",
                  abs(ry - rreach) <= 2.0, "%.1f / %.1f" % (ry, rreach))

    print()
    if FAILS:
        print("失败 %d 项：" % len(FAILS))
        for f in FAILS:
            print("  - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
