"""复现并验证：拖动窗口改宽度时，MOD 详情面板不能从右边「露」出来。

原来的写法是  x: page.detailOpen ? (parent.width - width) : parent.width
加 visible: x < parent.width - 2。窗口一被拖宽，parent.width 立刻变大，
而 x 还在动画里追 —— 中间那一刻 x < parent.width - 2 恒成立，于是详情面板
从右边缘露出一截（截图里那个红框就是这么来的）。

现在改成 anchors.right + rightMargin 定位，窗口宽度怎么变都只整体平移。
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

LOG = os.path.join(os.environ.get("TEMP", ROOT), "resize_test.log")
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
mgr = core.mods


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def find_obj(name):
    for c in win.findChildren(QObject):
        try:
            if c.objectName() == name:
                return c
        except RuntimeError:
            continue
    return None


def panel_width() -> float:
    """详情面板的参照宽度是 **ModPanel 自身**，不是整个窗口
    （左侧还有 224px 侧栏 + 各种边距，拿窗口宽度算会差出一大截）。"""
    root = find_obj("modPanelRoot")
    return float(root.property("width")) if root is not None else float(win.width())


def run():
    wait(2200)
    win.setProperty("section", 1)
    wait(2200)

    detail = find_obj("modDetailPanel")
    log("详情面板找到:", detail is not None)
    assert detail is not None, "找不到 modDetailPanel（objectName 没加？）"

    # ---------------------------------------------------- 1. 关着的时候不能露出来
    log()
    log("=== 1. 详情关闭时，面板必须完全在可视区外 ===")
    mgr.clearSelected()
    wait(700)
    page_w = panel_width()
    dx = float(detail.property("x"))
    dw = float(detail.property("width"))
    log(f"  ModPanel 宽={page_w:.0f} 详情 x={dx:.0f} 宽={dw:.0f}")
    assert dx >= page_w, f"详情关闭时 x={dx:.0f} 还在可视区内（面板 {page_w:.0f}）"

    # 根节点必须裁剪：ModPanel 外面还有 24px 边距，不裁的话超出部分会漏出去
    root = find_obj("modPanelRoot")
    log("  ModPanel clip =", root.property("clip"))
    assert root.property("clip") is True, "ModPanel 没有 clip，超出部分会从小缝里露出来"

    # ---------------------------------------------------- 2. 拖宽窗口：不能露出来
    log()
    log("=== 2. 关着的时候把窗口拖宽 ===")
    for extra in (60, 180, 320):
        w0 = float(win.width())
        win.setProperty("width", w0 + extra)
        # 在动画进行中多次采样（这就是穿帮发生的时刻）
        worst = None
        for _ in range(10):
            wait(40)
            pw = panel_width()
            x = float(detail.property("x"))
            if worst is None or (pw - x) > worst[0]:
                worst = (pw - x, pw, x)
        log(f"  拉宽 +{extra}: 面板宽={worst[1]:.0f} 详情x={worst[2]:.0f} "
            f"露出 {worst[0]:.0f}px")
        assert worst[0] <= 0, (
            f"窗口拉宽 +{extra} 时详情露出来了 {worst[0]:.0f}px")

    wait(500)

    # ---------------------------------------------------- 3. 打开后再改宽度
    log()
    log("=== 3. 详情打开时改宽度，面板应贴着右边缘 ===")
    items = mgr.allModel.items()
    assert items, "没有 MOD"
    mgr.selectMod(items[0]["path"])
    wait(700)
    log("  selectedPath:", bool(mgr.selectedPath))

    for extra in (80, -140, 220):
        w0 = float(win.width())
        new_w = max(1100, w0 + extra)
        win.setProperty("width", new_w)
        wait(450)
        pw = panel_width()
        x = float(detail.property("x"))
        dw = float(detail.property("width"))
        gap = (x + dw) - pw
        log(f"  窗口 {w0:.0f}->{float(win.width()):.0f}: 详情 x={x:.0f} "
            f"宽={dw:.0f} 距面板右边 {gap:.0f}px")
        assert abs(gap) <= 3, f"详情没有贴住右边（差 {gap:.0f}px）"

    # ---------------------------------------------------- 4. 关掉后仍然不露
    log()
    log("=== 4. 改完宽度再关掉，仍然不露 ===")
    mgr.clearSelected()
    wait(700)
    pw = panel_width()
    x = float(detail.property("x"))
    log(f"  面板宽={pw:.0f} 详情 x={x:.0f}")
    assert x >= pw, f"关掉后 x={x:.0f} 还在可视区内"

    # ---------------------------------------------------- 5. 代码层面别再用 x 三元
    log()
    log("=== 5. 定位方式检查 ===")
    src = open(os.path.join(ROOT, "qml/components/ModPanel.qml"), encoding="utf-8").read()
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
    assert "x: page.detailOpen ?" not in code, "详情还在用 x 三元定位（窗口改宽会穿帮）"
    assert "anchors.rightMargin: page.detailOpen ? 0" in code, "没有用 rightMargin 定位"
    assert "Behavior on anchors.rightMargin" in code, "rightMargin 没有动画"
    assert "Behavior on x" not in code.split("id: detail")[1][:1500], \
        "详情里还残留 Behavior on x"
    log("  用 anchors.right + rightMargin 定位，动画挂在 rightMargin 上")

    log()
    log("全部通过")
    core.shutdown()
    core.quitFromWindow()


QTimer.singleShot(300, run)
QTimer.singleShot(120000, core.quitFromWindow)
app.exec()
