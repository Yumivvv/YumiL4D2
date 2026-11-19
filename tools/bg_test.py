"""背景图功能自检：后端导入/切换/透明度 + QML 图层真的接上了。

跑法：python -X utf8 tools/bg_test.py
会临时往 backgrounds 目录塞一张测试图，跑完删掉并还原 config。
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
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def spin(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def opacity_settled(layer, target: float, tol: float = 0.01,
                    timeout_ms: int = 2500) -> float:
    """等图层淡入动画停下来再断言。

    背景图层有 `Behavior on opacity` 的淡入动画，图片还是异步加载的：
    直接读 opacity 会拿到 0.27 / 0.425 这类「动画中途」的值（run_all 里就
    这样偶发失败）。这里一直转到「连续两次读数一样且等于目标」为止。
    """
    waited = 0
    last = None
    while waited < timeout_ms:
        cur = float(layer.property("opacity"))
        if last is not None and abs(cur - last) < 1e-4 and abs(cur - target) < tol:
            return cur
        last = cur
        spin(50)
        waited += 50
    return float(layer.property("opacity"))


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


def make_png(path: str) -> str:
    """造一张 200x120 的彩色 PNG（不依赖 PIL）。"""
    img = QImage(200, 120, QImage.Format_RGB32)
    img.fill(QColor("#2a5f8a"))
    for x in range(0, 200, 20):
        for y in range(0, 120, 20):
            img.setPixelColor(x, y, QColor("#ff8800"))
    assert img.save(path, "PNG")
    return path


def prop_url(o, name: str) -> str:
    """读一个 QUrl 属性成字符串。注意 PySide6 直接 str() 会把 bytes 按 latin-1 解，
    路径里有中文时抛 UnicodeDecodeError，所以走 toString()。"""
    v = o.property(name)
    if v is None:
        return ""
    if hasattr(v, "toString"):
        return v.toString()
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return str(v)


def main() -> int:
    app = QGuiApplication(sys.argv)
    from app.core import Core
    from app.util import BG_DIR
    from app.wallpaper import import_background, list_backgrounds, resolve_bg_path

    core = Core(app)
    cfg = core.config
    old_image = str(cfg["bg_image"] or "")
    old_opacity = int(cfg["bg_opacity"])

    tmpdir = tempfile.mkdtemp(prefix="l4d2_bg_")
    src = make_png(os.path.join(tmpdir, "test_wallpaper.png"))

    print("=== 1. 后端：导入 / 解析 / 列表 ===")
    res = import_background(src)
    check("导入成功", bool(res.get("ok")), str(res.get("name")))
    name = res.get("name") or ""
    check("落到了 backgrounds 目录", os.path.isfile(os.path.join(BG_DIR, name)))
    check("resolve_bg_path 能找到", bool(resolve_bg_path(name)))
    names = [it["name"] for it in list_backgrounds()]
    check("列表里有这张图", name in names, str(names[:3]))
    bad = import_background(os.path.join(tmpdir, "nope.txt"))
    check("非图片被拒绝", not bad.get("ok"), str(bad.get("error"))[:24])

    print("=== 2. 后端：设为背景 / 透明度 / 移除 ===")
    r = core.setBgImage(name)
    check("setBgImage 成功", bool(r.get("ok")))
    check("bgImageName 对得上", core.bgImageName == name, core.bgImageName)
    check("bgImageUrl 是 file://", core.bgImageUrl.startswith("file://"), core.bgImageUrl[-24:])
    core.previewBgOpacity(72)
    check("previewBgOpacity 生效", core.bgOpacity == 72, str(core.bgOpacity))
    core.setBgOpacity(150)
    check("超范围被夹到 100", core.bgOpacity == 100, str(core.bgOpacity))
    core.setBgOpacity(-20)
    check("负数被夹到 0", core.bgOpacity == 0, str(core.bgOpacity))
    core.setBgOpacity(45)
    check("配置里存了 bg_opacity", int(cfg["bg_opacity"]) == 45, str(cfg["bg_opacity"]))

    print("=== 3. QML：主界面图层 + 设置区预览 ===")
    engine = QQmlApplicationEngine()
    warns: list[str] = []
    engine.warnings.connect(lambda ws: warns.extend([w.toString() for w in ws]))
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.addImportPath(os.path.join(ROOT, "qml", "components"))
    engine.rootContext().setContextProperty("core", core)
    engine.load(os.path.join(ROOT, "qml", "Main.qml"))
    check("QML 加载出窗口", len(engine.rootObjects()) == 1)
    win = engine.rootObjects()[0]
    spin(400)

    layer = find_name(win, "bgImageLayer")
    preview = find_name(win, "bgPreviewBox")
    check("主界面找到背景图层", layer is not None)
    check("设置里找到预览框", preview is not None)
    if layer is not None:
        src_val = prop_url(layer, "source")
        check("背景图层用上了这张图", name in src_val, src_val.split("/")[-1][:32])
        got_op = opacity_settled(layer, 0.45)
        check("图层透明度 = 0.45", abs(got_op - 0.45) < 0.01, str(got_op))
        check("图层可见", bool(layer.property("visible")))

    core.setBgOpacity(0)
    spin(80)
    if layer is not None:
        check("透明度 0 时图层隐藏", not bool(layer.property("visible")))

    core.setBgOpacity(60)
    spin(80)
    core.clearBgImage()
    spin(80)
    if layer is not None:
        check("移除后 source 为空", prop_url(layer, "source") == "")
        check("移除后图层隐藏", not bool(layer.property("visible")))

    print("=== 4. 收尾 ===")
    check("QML 无可疑告警", not [w for w in warns if any(
        k in w for k in ("TypeError", "not defined", "is not a type", "Unable", "ReferenceError", "Duplicate")
    )], str(len(warns)) + " 条原始告警")
    try:
        os.remove(os.path.join(BG_DIR, name))
    except OSError:
        pass
    check("测试图已清理", not os.path.isfile(os.path.join(BG_DIR, name)))
    cfg["bg_image"] = old_image
    cfg["bg_opacity"] = old_opacity
    cfg.save()
    check("配置已还原", str(cfg["bg_image"]) == old_image and int(cfg["bg_opacity"]) == old_opacity)

    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except OSError:
        pass

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
