"""QML 加载 / 关键交互冒烟测试（不需要真 L4D2 目录）。

跑法：
    python tools/uismoke_test.py
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

from app import mods as _mods
from app.core import Core
from app.util import ROOT, ensure_dirs

# 转换到本地 / 导入都会写「导入日期」台账（data/modimports.json）。
# 测试必须写临时文件，否则会把用户真实的导入时间覆盖掉（132381280 就被盖过一次）。
_LEDGER_DIR = tempfile.mkdtemp(prefix="l4d2_ledger_")
_mods.IMPORT_LEDGER_PATH = os.path.join(_LEDGER_DIR, "modimports.json")


def log(*a):
    print(*a, flush=True)


ensure_dirs()
app = QGuiApplication(sys.argv[:1])
engine = QQmlApplicationEngine()
q = os.path.join(ROOT, "qml")
engine.addImportPath(q)
engine.addImportPath(os.path.join(q, "components"))

warnings: list[str] = []
engine.warnings.connect(lambda ws: warnings.extend(str(w.toString()) for w in ws))

core = Core(app)
engine.rootContext().setContextProperty("core", core)
engine.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))

if not engine.rootObjects():
    log("LOAD FAILED")
    for w in warnings:
        log("  warn:", w)
    sys.exit(1)

win = engine.rootObjects()[0]
win.show()
mgr = core.mods


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run():
    wait(2500)

    log("=== 1. toast 浮层 ===")
    win.toast("这是一条测试提示", "warn")
    wait(300)
    # QML 里的 id 外部访问不到，靠 objectName 找
    host = win.findChild(QObject, "toastLayer") if hasattr(win, "findChild") else None
    if host is None:
        for child in win.findChildren(QObject):
            if child.objectName() == "toastLayer":
                host = child
                break
    log("  ToastLayer 找到:", host is not None)
    assert host is not None, "ToastLayer 没加载"

    log()
    log("=== 2. 提示音设置 ===")
    log("  当前音效:", core.alertSoundName)
    log("  候选列表:", [s["name"] for s in core.soundList])
    log("  sounds 目录:", core.soundsDir)
    assert core.alertSoundName, "没有当前音效"
    assert core.soundList, "sounds 列表空了"
    res = core.setAlertSound(core.alertSoundName)
    log("  重新选中:", res)
    assert res.get("ok") is True
    res = core.resetAlertSound()
    log("  恢复默认:", res.get("ok"), res.get("name"))

    log()
    log("=== 3. MOD 状态统计含「本地」 ===")
    counts = dict(mgr.statusCounts)
    log("  statusCounts =", counts)
    assert "local" in counts, "statusCounts 缺 local"
    assert counts["local"] + counts["workshop"] == counts["all"]

    total = mgr.totalCount
    if total:
        mgr.setStatusFilter(6)
        wait(200)
        log("  只看本地 ->", mgr.totalCount, "（应等于", counts["local"], "）")
        assert mgr.totalCount == counts["local"], "本地筛选数量不对"
        mgr.setStatusFilter(3)
        wait(200)
        log("  只看创意工坊 ->", mgr.totalCount, "（应等于", counts["workshop"], "）")
        assert mgr.totalCount == counts["workshop"]
        mgr.setStatusFilter(0)
        wait(200)
    else:
        log("  [warn] 没有扫描到 MOD，跳过数量断言")

    log()
    log("=== 4. 详情字段：导入日期 / 作者昵称 ===")
    pick = mgr.allModel.items()[0] if mgr.allModel.rowCount() else None
    if pick:
        mgr.selectMod(pick["path"])
        wait(200)
        sel = mgr.selectedItem
        log("  importText =", sel.get("importText"), " mtimeText =", sel.get("mtimeText"))
        log("  authorLabel =", sel.get("authorLabel"), " authorId =", sel.get("authorId"))
        assert "importText" in sel and sel["importText"], "详情缺 importText"
        assert "authorLabel" in sel, "详情缺 authorLabel"
        assert sel["importText"] == sel["mtimeText"], "导入日期和 mtimeText 不一致"
        if sel.get("authorId"):
            assert sel["authorId"] in (sel.get("authorUrl") or ""), "作者链接里没有 SteamID"
    else:
        log("  [warn] 没有 MOD，跳过详情断言")

    log()
    log("=== 5. 转换到本地（临时目录沙盒）===")
    import shutil
    import tempfile

    from app import mods as M

    sandbox = tempfile.mkdtemp(prefix="l42d_conv_")
    addons = os.path.join(sandbox, "left4dead2", "addons")
    ws = os.path.join(addons, "workshop")
    os.makedirs(ws)
    for n in ("132381280.vpk", "132381280.jpg", "999.vpk"):
        with open(os.path.join(ws, n), "wb") as f:
            f.write(b"x" * 2048)
    with open(os.path.join(ws, "888.vpk"), "wb") as f:
        f.write(b"y" * 1024)

    res = M.copy_workshop_to_local(addons, ["132381280.vpk", "132381280.jpg"])
    log("  转换结果 moved =", res["moved"], "blocked =", res["blocked"])
    assert "132381280.vpk" in res["moved"], "vpk 没复制过去"
    assert "132381280.jpg" in res["moved"], "封面图没跟上（就是那个丢图 bug）"
    assert os.path.exists(os.path.join(addons, "132381280.vpk"))
    assert os.path.exists(os.path.join(addons, "132381280.jpg"))
    assert os.path.exists(os.path.join(ws, "132381280.vpk")), "工坊那份不该被删"

    log("  导入日期台账:", M.import_ts_of("132381280.vpk"))
    assert M.import_ts_of("132381280.vpk") > 0, "转换后没记导入日期"

    log()
    log("=== 6. 占用文件：只跳过被占用的，其余照常 ===")
    # 用 CreateFileW(dwShareMode=0) 模拟「游戏独占打开着这个 vpk」——
    # 和真实情况一样：别的进程连 open() 都会 PermissionError。
    import ctypes
    from ctypes import wintypes

    locked_path = os.path.join(ws, "888.vpk")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    k32.CreateFileW.restype = wintypes.HANDLE
    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
    handle = k32.CreateFileW(locked_path, GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
    assert handle not in (None, -1, 0xFFFFFFFFFFFFFFFF), "模拟占用失败"
    try:
        assert M.is_locked(locked_path), "is_locked 没认出被独占打开的文件"
        res = M.copy_workshop_to_local(addons, ["888.vpk", "999.vpk"])
        log("  moved =", res["moved"], " blocked =", res["blocked"])
        assert "999.vpk" in res["moved"], "没被占用的应照常转换"
        assert res["blocked"], "被占用的没被识别出来"
        assert not os.path.exists(os.path.join(addons, "888.vpk")), "被占用的不该复制过去"
    finally:
        k32.CloseHandle(handle)

    log()
    log("=== 7. import_files 记录导入日期 + locked 字段 ===")
    src = os.path.join(sandbox, "src")
    os.makedirs(src)
    for n in ("777.vpk", "777.png"):
        with open(os.path.join(src, n), "wb") as f:
            f.write(b"z" * 512)
    dst = os.path.join(sandbox, "dst")
    os.makedirs(dst)
    res = M.import_files([os.path.join(src, "777.vpk")], dst)
    log("  copied =", res["copied"], " locked =", res["locked"],
        " gameRunning =", res["gameRunning"])
    assert "777.vpk" in res["copied"] and "777.png" in res["copied"]
    assert M.import_ts_of("777.vpk") > 0, "导入后没记导入日期"

    shutil.rmtree(sandbox, ignore_errors=True)
    shutil.rmtree(_LEDGER_DIR, ignore_errors=True)

    log()
    log("=== 8. 视频详情不再把列表弹回顶部 ===")
    model = core.videoModel
    n = model.rowCount()
    log("  列表条数:", n)
    if n > 3:
        rows_before = [model.data(model.index(i, 0), 0x0100) for i in range(min(n, 8))]
        target = model.data(model.index(2, 0), 0x0100 + 0)   # bvid 是第 0 个 role
        log("  刷新第 3 条:", target)
        core._refresh_one(target)
        wait(120)
        rows_after = [model.data(model.index(i, 0), 0x0100) for i in range(min(n, 8))]
        assert rows_before == rows_after, "原位刷新后列表顺序变了（会跳回顶部）"
        log("  原位刷新后顺序不变（不会 beginResetModel）")
    else:
        log("  [warn] 视频太少，跳过")

    log()
    log("=== 9. QML 警告 ===")
    real = [w for w in warnings if "TypeError" in w or "is not defined" in w
            or "Unable to assign" in w or "Cannot assign" in w]
    for w in real[:20]:
        log("  ", w)
    log("  可疑警告数:", len(real))
    assert not real, "QML 有类型/绑定错误"

    log()
    log("全部通过")
    core.quitFromWindow()


QTimer.singleShot(400, run)
QTimer.singleShot(90000, core.quitFromWindow)
app.exec()
