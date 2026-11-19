"""验证设置抽屉的滚动条不再和内容重叠。

之前是 `ScrollBar.vertical: ScrollBar {...}` 挂在 Flickable 上 —— 那种会自动贴在
Flickable 的右边缘、**盖在内容上面**，开关和按钮的右半截被压住（截图里那个红框）。
现在滚动条挪到 Flickable 外面，贴着抽屉右边缘，两者各占一块。
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

LOG = os.path.join(os.environ.get("TEMP", ROOT), "scrollbar_test.log")
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


def find_obj(name):
    for c in win.findChildren(QObject):
        try:
            if c.objectName() == name:
                return c
        except RuntimeError:
            continue
    return None


def rect_of(obj):
    """QQuickItem 的全局矩形（x/y 是相对父项的，这里只用来比较同一父级下的元素）。"""
    return (float(obj.property("x") or 0), float(obj.property("y") or 0),
            float(obj.property("width") or 0), float(obj.property("height") or 0))


def run():
    wait(2000)
    win.setProperty("settingsOpen", True)
    wait(1200)

    src = open(os.path.join(ROOT, "qml/Main.qml"), encoding="utf-8").read()
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))

    # ---------------------------------------------------- 1. 结构：不再挂在 Flickable 上
    log("=== 1. 滚动条不再挂在 Flickable 上 ===")
    assert "ScrollBar.vertical: ScrollBar" not in code.split("settingsFlick")[1][:900], \
        "设置里还在用 ScrollBar.vertical（会自动盖住内容）"
    assert "id: settingsBar" in code, "没有独立滚动条 settingsBar"
    seg = code[code.index("id: settingsBar"):]
    seg = seg[:seg.index("background: Item { }")]
    assert "anchors.right: parent.right" in seg, "滚动条没贴右边缘"
    assert "parent.rightMargin" not in seg, "滚动条没用 rightMargin 定位"
    log("  独立 ScrollBar，锚在抽屉右边缘")

    # ---------------------------------------------------- 2. Flickable 不再为它留 30px
    log()
    log("=== 2. Flickable 不再预留空白 ===")
    flick_seg = code[code.index("id: settingsFlick"):][:600]
    log("  settingsFlick 锚点:", " ".join(
        ln.strip() for ln in flick_seg.splitlines() if "anchors." in ln)[:160])
    assert "anchors.rightMargin: 30" not in flick_seg, \
        "Flickable 还留着给滚动条的 30px（现在滚动条在外面，不需要了）"
    log("  内容区域占满抽屉，滚动条独立在外侧")

    # ---------------------------------------------------- 3. 运行期：几何不重叠
    log()
    log("=== 3. 运行期：滚动条在内容区右侧，不压住内容 ===")
    flick = find_obj("settingsFlick")
    bar = find_obj("settingsBar")
    log("  settingsFlick 找到:", flick is not None)
    log("  settingsBar  找到:", bar is not None)
    if flick is not None and bar is not None:
        fx, fy, fw, fh = rect_of(flick)
        bx, by, bw, bh = rect_of(bar)
        log(f"  Flickable: x={fx:.0f} 宽={fw:.0f} (右边 {fx + fw:.0f})")
        log(f"  滚动条  : x={bx:.0f} 宽={bw:.0f} (右边 {bx + bw:.0f})")
        assert bx >= fx + fw - 2, (
            f"滚动条左边({bx:.0f}) 还在内容区里(内容右边 {fx + fw:.0f})—— 会盖住按钮")
        log("  -> 滚动条完全在内容区右侧")

    # ---------------------------------------------------- 4. 滚动条能滚内容
    log()
    log("=== 4. 拖动滚动条能带动内容 ===")
    if flick is not None and bar is not None:
        max_y = float(flick.property("contentHeight") or 0) - float(flick.property("height") or 0)
        log(f"  可滚范围 maxY = {max_y:.0f}")
        if max_y > 10:
            flick.setProperty("contentY", max_y / 2)
            wait(300)
            pos = float(bar.property("position") or 0)
            log(f"  contentY 设一半后，滚动条 position = {pos:.3f}")
            assert 0.2 < pos < 0.8, f"滚动条位置没跟着走（position={pos:.3f}）"
            log("  -> 位置联动正常")
        else:
            log("  [warn] 内容不够长，跳过")

    # ---------------------------------------------------- 5. 开关没被压住
    log()
    log("=== 5. 右侧开关/按钮没被滚动条压住 ===")
    # 找抽屉里最靠右的那个开关（ToggleSwitch 的 track 宽 40）
    if flick is not None:
        fx, fy, fw, fh = rect_of(flick)
        # 用 QML 侧的实际宽度比对：内容列宽度应等于 Flickable 宽度
        col = find_obj("settingsCol")
        if col is not None:
            cw = float(col.property("width") or 0)
            log(f"  内容列宽={cw:.0f} / Flickable 宽={fw:.0f}")
            assert abs(cw - fw) <= 2, "内容列没铺满 Flickable（说明还在给滚动条让位）"

    log()
    log("全部通过")
    core.shutdown()
    app.quit()


QTimer.singleShot(300, run)
QTimer.singleShot(90000, app.quit)
app.exec()
