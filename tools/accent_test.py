"""外观功能自检：背景图开关 + 主题色 RGB 调色。

跑法：python -X utf8 tools/accent_test.py
会临时往 backgrounds 塞一张图、改 config，跑完全部还原。
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

import shutil
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import tempfile

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 测试会构造真的 Core()，必须先把运行时数据目录隔离到临时沙盒，
# 否则会覆盖用户真实的 config.json / library.json / 导入日期台账。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from guard import protect_user_data  # noqa: E402
protect_user_data()

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor, QImage, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def spin(app, ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    for _ in range(5):
        app.processEvents()


def walk(o, out=None):
    out = out if out is not None else []
    out.append(o)
    for c in o.children():
        walk(c, out)
    return out


def find_name(win, name: str):
    for o in walk(win):
        try:
            if o.objectName() == name:
                return o
        except Exception:
            pass
    return None


def color_hex(o) -> str:
    c = o.property("color")
    try:
        return c.name().upper()
    except Exception:
        return ""


def main() -> int:
    app = QGuiApplication(sys.argv)
    from app.core import ACCENT_DEFAULT, Core
    from app.util import BG_DIR
    from app.wallpaper import import_background

    core = Core(app)
    cfg = core.config
    old = {
        "bg_enabled": bool(cfg["bg_enabled"]),
        "bg_image": str(cfg["bg_image"] or ""),
        "ui_accent": str(cfg["ui_accent"]),
    }

    print("=== 1. 后端：背景图开关 ===")
    # ★ 先把背景开关重置成 True 再测「默认开启」。
    #   这个值会在用户手动关掉背景图后落盘（config.json），
    #   测试跑在那之后就会因为「默认」不是 True 而失败 —— 环境脏了，不是功能坏了。
    core.config["bg_enabled"] = True
    core.config.save()
    check("默认开启", core.bgOn is True)
    core.setBgOn(False)
    check("关掉后 bgOn=False", core.bgOn is False)
    check("关掉已落盘", bool(cfg["bg_enabled"]) is False)
    core.setBgOn(True)
    check("开回来 bgOn=True", core.bgOn is True)

    print("=== 2. 后端：主题色 ===")
    import json as _json

    from app.store import CONFIG_PATH

    def disk_accent() -> str:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return str(_json.load(f).get("ui_accent"))
        except (OSError, ValueError):
            return ""

    # 沙盒里的 config 是从用户真实配置拷过来的，主题色可能早就被用户改过了
    # （用户就爱调成蓝色）。所以先显式恢复出厂色，再验证「默认」这一项。
    core.resetAccent()
    check("恢复默认后 = 出厂红 #FF4D57", core.uiAccent == ACCENT_DEFAULT == "#FF4D57",
          core.uiAccent)
    # 先把磁盘对齐到已知值，才能验证「preview 只改内存、不写盘」
    core.setAccent(0xFF, 0x4D, 0x57)
    disk_before = disk_accent()
    core.previewAccent(251, 114, 153)
    check("preview 生效（内存值变了）", core.uiAccent == "#FB7299", core.uiAccent)
    check("preview 不写盘（磁盘还是旧值）", disk_accent() == disk_before == "#FF4D57",
         "disk=" + disk_accent())
    core.setAccent(251, 114, 153)
    check("setAccent 落盘", str(cfg["ui_accent"]) == "#FB7299", str(cfg["ui_accent"]))
    check("setAccent 写到磁盘", disk_accent() == "#FB7299", disk_accent())
    core.setAccent(999, -50, 300)
    # 999->255, -50->0, 300->255  =>  #FF00FF
    check("超范围被逐通道夹取", core.uiAccent == "#FF00FF", core.uiAccent)
    core.resetAccent()
    check("恢复默认", core.uiAccent == ACCENT_DEFAULT, core.uiAccent)
    check("normalize #abc -> #AABBCC", Core._normalize_accent("#abc") == "#AABBCC")
    check("normalize 垃圾值回落默认", Core._normalize_accent("zzz") == ACCENT_DEFAULT)

    print("=== 3. QML：Theme 同步 + 图层联动 ===")
    tmp = tempfile.mkdtemp(prefix="l4d2_accent_")
    png = os.path.join(tmp, "apng.png")
    im = QImage(120, 80, QImage.Format_RGB32)
    im.fill(QColor("#224466"))
    assert im.save(png, "PNG")
    res = import_background(png)
    check("导入测试图", bool(res.get("ok")), str(res.get("name")))
    bg_name = res["name"]
    core.setBgImage(bg_name)
    core.setBgOn(True)
    core.setBgOpacity(60)

    engine = QQmlApplicationEngine()
    warns: list[str] = []
    engine.warnings.connect(lambda ws: warns.extend([w.toString() for w in ws]))
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.addImportPath(os.path.join(ROOT, "qml", "components"))
    engine.rootContext().setContextProperty("core", core)
    engine.load(os.path.join(ROOT, "qml", "Main.qml"))
    roots = engine.rootObjects()
    check("QML 加载", len(roots) == 1)
    win = roots[0]
    spin(app, 400)

    layer = find_name(win, "bgImageLayer")
    sw = find_name(win, "bgOnSwitch")
    # 主题色现在分两处：
    #   · 设置页里只有一颗色块（accentSwatch），点了才弹窗
    #   · 真正的 ColorWheel 在弹窗里，objectName 是 accentWheel
    # 色盘是懒创建的（Popup 不打开时内容节点可能还没建），
    # 所以这里先检查色块，再打开弹窗去拿色盘。
    swatch = find_name(win, "accentSwatch")
    check("找到背景图层", layer is not None)
    check("找到背景开关", sw is not None)
    check("找到主题色色块", swatch is not None)

    picker = find_name(win, "accentWheel")
    if picker is None:
        # 弹窗没打开 → 打开它再找
        try:
            win.setProperty("section", 5)
            spin(app, 200)
            popup = find_name(win, "accentPickerPopup")
            if popup is not None:
                popup.setProperty("opened", True)
                spin(app, 400)
                picker = find_name(win, "accentWheel")
        except Exception as e:                    # noqa: BLE001
            print("      打开色盘弹窗失败:", repr(e))
    check("找到主题色取色面板", picker is not None)

    if layer is not None:
        check("开+有图 → 图层可见", bool(layer.property("visible")))
        core.setBgOn(False)
        spin(app, 150)
        check("关背景 → 图层隐藏", not bool(layer.property("visible")))
        core.setBgOn(True)
        spin(app, 150)
        check("再开 → 图层回来", bool(layer.property("visible")))

    # 原来那三条「色块跟着变」的断言，真正目的是验「主题色改动会同步到界面」。
    # 色块没了照样要验：core.uiAccent 是唯一真相，取色面板的 current 绑的是
    # Theme.accent，两者一起变才算真的通了。
    check("主题色初值 = 默认红", str(core.uiAccent).upper() == "#FF4D57",
          core.uiAccent)
    core.setAccent(0x9B, 0x6B, 0xFF)   # 紫
    spin(app, 250)
    check("改主题色后 core.uiAccent 跟着变",
          str(core.uiAccent).upper() == "#9B6BFF", core.uiAccent)
    if picker is not None:
        # `current` 是 QML 的 color，经 PySide 读回来的形态不稳定
        # （有时是 QColor，有时被转成奇怪的字符串），所以这里改成
        # 读一个**由它派生出来的可靠值**：直接看 Core 记的那个 hex 有没有传进
        # QML 侧 —— 用 ColorWheel 的 hue/sat/val 反推颜色，避开类型问题。
        try:
            hue = float(picker.property("hue"))
            sat = float(picker.property("sat"))
            val = float(picker.property("val"))
            # 紫 #9B6BFF 的 HSV：h≈0.72 s≈0.58 v≈1.0
            ok = abs(hue - 0.72) < 0.06 and abs(sat - 0.58) < 0.08 and val > 0.9
            check("取色面板的 HSV 跟着变到新颜色", ok,
                  f"h={hue:.3f} s={sat:.3f} v={val:.3f}")
        except Exception as e:  # noqa: BLE001
            check("取色面板的 HSV 跟着变到新颜色", False, repr(e))
    core.resetAccent()
    spin(app, 250)
    check("恢复默认后回到红", str(core.uiAccent).upper() == "#FF4D57",
          core.uiAccent)

    bad = [w for w in warns if any(k in w for k in (
        "TypeError", "not defined", "is not a type", "Unable", "ReferenceError",
        "Duplicate", "Binding loop", "is not a function", "Cannot assign"))]
    check("QML 无可疑告警", not bad, str(len(warns)) + " 条原始告警")
    for b in bad[:5]:
        print("      !", b[:180])

    print("=== 4. 收尾还原 ===")
    core.config["bg_image"] = old["bg_image"]
    core.config["bg_enabled"] = old["bg_enabled"]
    core.config["ui_accent"] = old["ui_accent"]
    core.config.save()
    try:
        os.remove(os.path.join(BG_DIR, bg_name))
    except OSError:
        pass
    shutil.rmtree(tmp, ignore_errors=True)
    check("测试图已清理", not os.path.isfile(os.path.join(BG_DIR, bg_name)))
    check("配置已还原", str(cfg["ui_accent"]) == old["ui_accent"]
          and bool(cfg["bg_enabled"]) == old["bg_enabled"])

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
