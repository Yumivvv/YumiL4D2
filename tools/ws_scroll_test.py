"""创意工坊：滚轮往下加载会不会跳回最开头（GUI 实测）。

背景：GridView 的 model 一换（追加时把整个数组换掉），滚动位置就会归零；
再加上 `onBrowseChanged` 里无条件 `positionViewAtBeginning()`，用户往下滚到
第二页时列表会突然弹回顶部。现在列表走 ListModel 镜像、只有第 1 页才归位，
这个脚本就是盯着这件事的。

跑法：python -X utf8 tools/ws_scroll_test.py
"""
from __future__ import annotations

# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import os
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 会构造真的 Core()：先把数据目录隔离到临时沙盒，别动用户配置
from guard import protect_user_data  # noqa: E402

protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from app.core import Core  # noqa: E402
from app.util import ROOT  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + ("  " + extra if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def spin(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def find_child(win, name: str):
    return win.findChild(QObject, name)


def main() -> int:
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    qml_dir = os.path.join(ROOT, "qml")
    engine.addImportPath(qml_dir)
    engine.addImportPath(os.path.join(qml_dir, "components"))

    warnings: list[str] = []
    engine.warnings.connect(lambda ws: [warnings.append(w.toString()) for w in ws])

    core = Core(app)
    engine.rootContext().setContextProperty("core", core)
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
    if not engine.rootObjects():
        print("QML 加载失败")
        for w in warnings:
            print("   ", w)
        return 1
    win = engine.rootObjects()[0]
    win.show()
    spin(300)

    print("=== 1. 打开创意工坊页，等第一页列表 ===")
    win.setProperty("section", 2)
    spin(200)
    mgr = core.mods
    page = find_child(win, "workshopPage")
    grid = find_child(win, "wsGrid")
    check("找到工坊页", page is not None)
    check("找到卡片墙", grid is not None)
    if page is None or grid is None:
        return 1

    # ★ 工坊列表现在走 Steam 官方 QueryFiles，**必须带用户自己的 API Key**。
    #   测试机通常没填 key，那时列表会是空的 —— 这不是「滚动坏了」，
    #   而是「没有数据源」。所以这里直接塞一批假数据进 browseItems，
    #   让本测试专注验证它真正要验的东西：滚动位置不被重置。
    #   （「没 key 时给出明确提示」由 round26/test 覆盖，不在这里断言。）
    if not mgr.browseItems:
        fake = [{"id": str(3842272870 + i),
                 "title": "假数据 MOD %d" % i,
                 "preview": "", "author": "test", "fileType": 0,
                 "views": 0, "subs": 0, "tags": [], "children": 0}
                for i in range(50)]
        mgr._browse_items = fake
        mgr._browse_thumbs = [""] * len(fake)
        mgr._browse_total = 500
        mgr._browse_done = False
        mgr.browseChanged.emit()
        spin(400)
        print("  （没有 API Key，注入 %d 条假数据来验滚动）" % len(fake), flush=True)

    waited = 0
    while waited < 30000 and not mgr.browseItems:
        spin(250)
        waited += 250
    check("列表加载出内容", len(mgr.browseItems) > 0,
          f"{len(mgr.browseItems)} 条 / {waited}ms")
    first_count = len(mgr.browseItems)

    print("=== 2. 滚到底部，再让列表往下加载 ===")
    # 真实场景：用户滚到下面 → maybeMore() 调 browseMore() → 追加下一页。
    # 这里直接把 contentY 摆到底部（等价于「用户已经滚下去了」），然后调
    # browseMore()，看追加完之后位置有没有被打回顶部。
    spin(400)
    ch = float(grid.property("contentHeight"))
    gh = float(grid.property("height"))
    max_y = max(0.0, ch - gh)
    print(f"      内容高 {ch:.0f} / 视口高 {gh:.0f} → 可滚 {max_y:.0f}")
    grid.setProperty("contentY", max_y)
    spin(200)
    y_before = float(grid.property("contentY"))
    if max_y > 0:
        check("滚动条真的滚下去了", y_before > 0, f"contentY={y_before:.0f}")
    else:
        print("      （这一页还不够长，A/B 两种情况都验证一下）")

    # ★ 没有 key 时 browseMore() 也拉不到新数据，这里同样用本地追加来模拟
    #   「后端又送来一页」，专注验证滚动位置不被打回顶部。
    if not mgr.hasSteamApiKey:
        extra = [{"id": str(3842290000 + i),
                  "title": "假数据 MOD 追加 %d" % i,
                  "preview": "", "author": "test", "fileType": 0,
                  "views": 0, "subs": 0, "tags": [], "children": 0}
                 for i in range(50)]
        mgr._browse_items = list(mgr.browseItems) + extra
        mgr._browse_thumbs = [""] * len(mgr._browse_items)
        mgr.browseAppended.emit()
        mgr.browseChanged.emit()
        print("  （没有 API Key，本地追加 %d 条模拟下一页）" % len(extra),
              flush=True)
    else:
        mgr.browseMore()
    waited = 0
    while waited < 30000 and len(mgr.browseItems) <= first_count:
        spin(250)
        waited += 250
    check("追加到了更多条目", len(mgr.browseItems) > first_count,
          f"{first_count} → {len(mgr.browseItems)} / {waited}ms")
    spin(800)

    y_after = float(grid.property("contentY"))
    ch_after = float(grid.property("contentHeight"))
    print(f"      contentY {y_before:.0f} → {y_after:.0f}；"
          f"内容高 {ch:.0f} → {ch_after:.0f}（追加 "
          f"{len(mgr.browseItems) - first_count} 条）")
    check("追加后没有跳回最开头", y_after > 0.5, f"contentY={y_after:.0f}")
    check("追加后内容变长了", ch_after > ch + 1, f"{ch:.0f} → {ch_after:.0f}")
    check("追加后位置没被大幅挪动（位移 < 一屏）", abs(y_after - y_before) < gh + 40,
          f"Δ={y_after - y_before:.0f}")

    print("=== 3. 重新筛选时才允许回到顶部 ===")
    mgr.browseSetSort("recent")
    spin(1200)
    y_reset = float(grid.property("contentY"))
    check("换排序后回到顶部", y_reset < 100, f"contentY={y_reset:.0f}")

    print("=== 4. QML 告警 ===")
    bad = [w for w in warnings if "Fixedsys" not in w]
    check("无可疑告警", not bad, f"{len(bad)} 条")
    for w in bad[:5]:
        print("      ", w)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
