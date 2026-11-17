"""验证「直接删除」走红色提示、「回收站」走黄色提示。

删除动作在真实文件上做太危险，这里用临时沙盒 + 直接调 ModManager 的槽，
监听 toastRequested 的 level。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 测试会构造真的 Core()，必须先把运行时数据目录隔离到临时沙盒，
# 否则会覆盖用户真实的 config.json / library.json / 导入日期台账。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from guard import protect_user_data  # noqa: E402
protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

from app.core import Core
from app.util import ROOT, ensure_dirs

LOG = os.path.join(os.environ.get("TEMP", ROOT), "toast_levels.log")
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
core = Core(app)
mgr = core.mods


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_idle(limit_s: float = 25.0):
    import time

    end = time.time() + limit_s
    while time.time() < end:
        app.processEvents()
        time.sleep(0.05)
        if not mgr.busy:
            return


def run():
    wait_idle(30)          # 等启动时的自动扫描结束

    toasts: list[tuple[str, str]] = []
    mgr.toastRequested.connect(lambda t, l: toasts.append((t, l)))

    def make_sandbox(files: dict[str, bytes]) -> str:
        sb = tempfile.mkdtemp(prefix="l42d_del_")
        addons = os.path.join(sb, "left4dead2", "addons")
        os.makedirs(addons)
        for n, data in files.items():
            with open(os.path.join(addons, n), "wb") as f:
                f.write(data)
        return sb

    # ---------------------------------------------------------- 回收站 → 黄
    log("=== 1. 删除方式：放进回收站 → 应弹 warn（黄） ===")
    sb = make_sandbox({"111.vpk": b"x" * 100, "111.jpg": b"i" * 50})
    addons = os.path.join(sb, "left4dead2", "addons")
    mgr.setDeleteToRecycle(True)
    log("  deleteToRecycle =", mgr.deleteToRecycle)
    mgr.setAddonsDir(addons)
    wait_idle()
    log("  localCount =", mgr.localCount)
    assert mgr.localCount == 1, f"沙盒扫描不对：{mgr.localCount}"

    toasts.clear()
    mgr.deleteOne(os.path.join(addons, "111.vpk"))
    wait(400)
    log("  toasts =", toasts)
    assert toasts, "删除后没有任何提示"
    assert toasts[0][1] == "warn", f"回收站应该是 warn，实际 {toasts[0][1]}"
    assert "回收站" in toasts[0][0], f"文案没提回收站：{toasts[0][0]}"
    log("  -> 黄色 + 回收站文案 OK")
    shutil.rmtree(sb, ignore_errors=True)

    # ---------------------------------------------------------- 直接删 → 红
    log()
    log("=== 2. 删除方式：直接删除 → 应弹 error（红） ===")
    sb = make_sandbox({"222.vpk": b"x" * 100, "222.png": b"i" * 50})
    addons = os.path.join(sb, "left4dead2", "addons")
    mgr.setDeleteToRecycle(False)
    log("  deleteToRecycle =", mgr.deleteToRecycle)
    mgr.setAddonsDir(addons)
    wait_idle()
    assert mgr.localCount == 1, f"沙盒扫描不对：{mgr.localCount}"

    toasts.clear()
    mgr.deleteOne(os.path.join(addons, "222.vpk"))
    wait(400)
    log("  toasts =", toasts)
    assert toasts, "删除后没有任何提示"
    assert toasts[0][1] == "error", f"直接删除应该是 error，实际 {toasts[0][1]}"
    assert "永久删除" in toasts[0][0] or "已删除" in toasts[0][0], \
        f"文案不对：{toasts[0][0]}"
    assert not os.path.exists(os.path.join(addons, "222.vpk"))
    log("  -> 红色 + 永久删除文案 OK")
    shutil.rmtree(sb, ignore_errors=True)

    # ---------------------------------------------------------- 恢复默认
    mgr.setDeleteToRecycle(True)

    log()
    log("=== 3. 复制 / 未选中批量操作 都有提示 ===")
    toasts.clear()
    core.toastRequested.connect(lambda t, l: toasts.append((t, l)))
    core.copyText("测试")
    # 用 QCoreApplication.processEvents 多转几圈，信号才投递完
    wait(500)
    app.processEvents()
    log("  copyText ->", toasts[:2])
    log("  剪贴板 =", app.clipboard().text() if app.clipboard() else "N/A")
    assert toasts and toasts[0][1] == "ok", f"复制没提示：{toasts}"

    toasts.clear()
    mgr.setStatusFilter(1)
    wait(200)
    mgr.setEnabledChecked(True)      # 没勾选
    wait(400)
    app.processEvents()
    log("  未选中时批量启用 ->", toasts[:2])
    assert toasts and toasts[0][1] == "warn", f"没选中时应给黄色提醒：{toasts}"
    mgr.setStatusFilter(0)

    log()
    log("全部通过")
    core.shutdown()
    app.quit()


QTimer.singleShot(300, run)
QTimer.singleShot(120000, app.quit)
app.exec()
