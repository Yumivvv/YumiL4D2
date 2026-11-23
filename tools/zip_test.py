# -*- coding: utf-8 -*-
"""压缩包导入：确认框计数 / 文件名预览 / 真导入 一条龙验证。

跑法：D:\\Python\\Python3.12\\python.exe -X utf8 tools\\zip_test.py
"""
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
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import zipfile

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 测试会构造真的 Core()，必须先把运行时数据目录隔离到临时沙盒，
# 否则会覆盖用户真实的 config.json / library.json / 导入日期台账。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from guard import protect_user_data  # noqa: E402
protect_user_data()

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression  # noqa: E402

OUT = []


def log(msg):
    OUT.append(str(msg))
    print(msg)


def main():
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    warns = []
    engine.warnings.connect(lambda l: [warns.append(w.toString()) for w in l])
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.addImportPath(os.path.join(ROOT, "qml", "components"))

    from app.core import Core

    core = Core(app)
    # 测试导入会写「导入日期」台账，别污染真实 data/modimports.json
    from app import mods as _M

    _M.IMPORT_LEDGER_PATH = os.path.join(tempfile.mkdtemp(prefix="l4d2_ledger_"),
                                         "modimports.json")
    engine.rootContext().setContextProperty("core", core)
    engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    if not engine.rootObjects():
        log("FAIL: QML 没加载起来")
        return 1

    win = engine.rootObjects()[0]

    def find_by_object_name(name):
        from PySide6.QtCore import QObject
        stack = [win]
        while stack:
            o = stack.pop()
            if o.objectName() == name:
                return o
            stack.extend(o.children())
        return None

    panel = find_by_object_name("modPanelRoot")
    if panel is None:
        log("FAIL: 找不到 modPanelRoot")
        return 1

    tmp = tempfile.mkdtemp(prefix="l4d2_zipui_")
    src = os.path.join(tmp, "src")
    os.makedirs(src)
    for n in ("111.vpk", "222.vpk", "333.vpk", "444.vpk", "555.vpk", "666.vpk"):
        open(os.path.join(src, n), "wb").write(b"vpk" + n.encode())
    open(os.path.join(src, "222.jpg"), "wb").write(b"img")
    open(os.path.join(src, "readme.txt"), "wb").write(b"txt")
    zp = os.path.join(tmp, "pack.zip")
    with zipfile.ZipFile(zp, "w") as zf:
        for n in os.listdir(src):
            zf.write(os.path.join(src, n), n)

    addons = os.path.join(tmp, "left4dead2", "addons")
    os.makedirs(addons)
    ctx = QQmlEngine.contextForObject(panel)
    if ctx is None:
        log("FAIL: 拿不到 QML context")
        return 1

    def expr(code):
        e = QQmlExpression(ctx, panel, code)
        return e.evaluate()[0]

    mgr = expr("mgr")
    log(f"mgr = {mgr}")
    ok = mgr.trySetAddonsDir(addons) if mgr is not None else None
    log(f"设置 addons 目录 -> {ok}  addonsDir={mgr.addonsDir if mgr is not None else ''}")

    expr(f"askImport([{QUrl.fromLocalFile(zp).toString()!r}])")
    count = expr("pendingImportCount()")
    # ★ 2026-11 改版：确认框从「只读预览前 5 个」换成了**逐条勾选的清单**
    #   （默认全选）。所以这里不再看 previewImportNames()（它已经删了），
    #   改看 importPickItems()（真实清单）和 importPickCount()（默认全选数）。
    picks = expr("importPickItems()")
    if hasattr(picks, "toVariant"):
        picks = picks.toVariant()
    picks = list(picks or [])
    picked_n = expr("importPickCount()")
    info = expr("pendingImportInfo")
    if hasattr(info, "toVariant"):
        info = info.toVariant()
    log(f"确认框 count = {count}")
    log(f"勾选清单条数 = {len(picks)} 已勾选 = {picked_n}")
    log(f"压缩包 = {info.get('archives') if isinstance(info, dict) else info}")

    ok_count = count == 7  # 6 vpk + 1 同名封面（readme.txt 不算）
    # 清单里每个该导入的文件都在，而且**默认全选**
    ok_pick = len(picks) == 7 and int(picked_n or 0) == 7
    # 每条都标了 MOD / 封面，用户能分清哪个是本体
    ok_kind = all(isinstance(p, dict) and p.get("kind") in ("mod", "image")
                  for p in picks) if picks else False
    ok_archive = bool(info.get("archives")) if isinstance(info, dict) else False
    log(f"count 断言(应为7) = {ok_count}")
    log(f"清单 7 条且默认全选 = {ok_pick}")
    log(f"每条都标了 MOD/封面 = {ok_kind}")
    log(f"显示压缩包名断言 = {ok_archive}")

    expr("doImport()")
    app.processEvents()
    got = sorted(os.listdir(addons))
    log(f"导入后 addons = {got}")
    ok_import = set(got) == {"111.vpk", "222.vpk", "333.vpk", "444.vpk", "555.vpk",
                             "666.vpk", "222.jpg"}
    log(f"导入结果断言 = {ok_import}")
    left = [d for d in os.listdir(tempfile.gettempdir()) if d.startswith("l4d2_archive_")]
    log(f"残留临时目录数 = {len(left)}")

    core.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

    passed = all([ok_count, ok_pick, ok_kind, ok_archive, ok_import, not left])
    log("全部通过" if passed else "有失败项")
    # 日志写到临时目录，不要把测试产物丢进用户的 data/
    with open(os.path.join(tempfile.gettempdir(), "l4d2_zip_test.log"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(OUT))
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())



