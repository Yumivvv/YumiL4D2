"""查「提示一直重复播放」：统计一次操作会触发多少次 toast / 声音。"""
from __future__ import annotations

import os
import sys

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
from app.util import ROOT

LOG = os.path.join(os.environ.get("TEMP", ROOT), "toast_repeat.log")
try:
    os.remove(LOG)
except OSError:
    pass


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


app = QGuiApplication(sys.argv[:1])
core = Core(app)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run():
    wait(1500)

    toasts: list = []
    sounds: list = []
    core.toastRequested.connect(lambda t, l: toasts.append((t, l)))

    # 拦一层：记录每次真正要播声音
    import app.notifier as N

    orig = N.play_alert

    def spy(path=""):
        sounds.append(path or "<default>")
        return orig(path)

    N.play_alert = spy
    # core 里是 `from .notifier import play_alert`，得改 core 模块里的引用
    import app.core as C

    C.play_alert = spy

    log("=== 1. 一次复制 → 应该只有 1 条 toast、0 次提示音 ===")
    toasts.clear()
    sounds.clear()
    core.copyText("hello")
    wait(1200)
    log("  toasts =", toasts)
    log("  sounds =", sounds)
    assert len(toasts) == 1, f"一次复制发了 {len(toasts)} 条提示"
    assert len(sounds) == 0, f"复制不该播提示音，却播了 {len(sounds)} 次"

    log()
    log("=== 2. 空闲 6 秒：不该自己再冒提示/声音 ===")
    toasts.clear()
    sounds.clear()
    wait(6000)
    log("  toasts =", toasts, " sounds =", sounds)
    assert not toasts, f"空闲时自己冒了 {len(toasts)} 条提示"
    assert not sounds, f"空闲时自己播了 {len(sounds)} 次声音"

    log()
    log("=== 3. 试听按钮 → 应当只播 1 次 ===")
    toasts.clear()
    sounds.clear()
    core.testSound()
    wait(1800)
    log("  toasts =", toasts)
    log("  sounds =", sounds)
    assert len(sounds) == 1, f"试听播了 {len(sounds)} 次"
    assert len(toasts) == 1, f"试听发了 {len(toasts)} 条提示"

    log()
    log("=== 4. 切换提示音开关：只播 1 次 ===")
    toasts.clear()
    sounds.clear()
    core.setNotifySound(True)
    wait(1800)
    log("  sounds =", sounds)
    assert len(sounds) <= 1, f"开提示音播了 {len(sounds)} 次"

    log()
    log("=== 5. 连续调用 testSound 3 次 → 恰好 3 次，不多 ===")
    sounds.clear()
    for _ in range(3):
        core.testSound()
        wait(150)
    wait(800)
    log("  sounds =", len(sounds))
    assert len(sounds) == 3, f"3 次试听播了 {len(sounds)} 次"

    log()
    log("全部通过")
    core.shutdown()
    app.quit()


QTimer.singleShot(300, run)
QTimer.singleShot(90000, app.quit)
app.exec()
