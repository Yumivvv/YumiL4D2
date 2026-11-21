"""验证 Toast 生命周期：出现 → 到点消失 → 不会越堆越多。

早期 bug：stamp 用 Date.now()+Math.random() 生成（double），
delegate 里声明成 `required property int stamp` 会被截断成整数，
dismiss() 拿截断值去 ListModel 里比原始 double，永远找不到 →
提示永远不消失（而且每次重试又会把提示音再播一遍，听起来像「反复播放」）。

现在用计数型字符串 stamp + 独立 Timer 兜底。
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

LOG = os.path.join(os.environ.get("TEMP", ROOT), "toast_life.log")
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


def find_host():
    for c in win.findChildren(QObject):
        try:
            if c.objectName() == "toastLayer":
                return c
        except RuntimeError:
            continue
    return None


def toast_count(host):
    """数当前 toast 条数：优先读 QML 的 ListModel（类名是 QQmlListModel）。"""
    for c in host.findChildren(QObject):
        try:
            if "ListModel" in c.metaObject().className():
                v = c.property("count")
                if v is not None:
                    return int(v)
        except (RuntimeError, TypeError):
            continue
    return -1


def run():
    wait(2000)

    host = find_host()
    log("ToastLayer:", host is not None)
    assert host is not None, "找不到 ToastLayer"

    life = int(host.property("lifeMs") or 3600)
    log("lifeMs =", life)

    log()
    log("=== 1. 单条：出现 → 到点消失 ===")
    win.toast("测试提示：应当自己消失", "ok")
    wait(500)
    n0 = toast_count(host)
    log("  弹出后条数 =", n0)
    assert n0 == 1, f"应当有 1 条，实际 {n0}"

    wait(life + 1500)
    n1 = toast_count(host)
    log(f"  等 {life + 1500}ms 后 = {n1}")
    assert n1 == 0, f"提示没消失！还留着 {n1} 条"

    log()
    log("=== 2. 三条叠放，全部消失 ===")
    win.toast("第一条", "ok")
    wait(120)
    win.toast("第二条", "warn")
    wait(120)
    win.toast("第三条", "error")
    wait(600)
    log("  弹出后 =", toast_count(host))
    assert toast_count(host) == 3

    wait(life + 2200)
    log("  等够后 =", toast_count(host))
    assert toast_count(host) == 0, f"还有 {toast_count(host)} 条没消失"

    log()
    log("=== 3. 同一条消息连发不叠 ===")
    for _ in range(6):
        core.copyText("重复测试")
        wait(60)
    wait(500)
    n = toast_count(host)
    log("  连发 6 次后 =", n, "（上限 3，且同样的文案只留一条）")
    assert n == 1, f"同样的文案应当只留 1 条，实际 {n}"

    wait(life + 1500)
    log("  之后 =", toast_count(host))
    assert toast_count(host) == 0, "残留没清干净"

    log()
    log("=== 4. 上限仍然是 3 ===")
    for i in range(5):
        win.toast("不同内容 " + str(i), "info")
        wait(100)
    wait(400)
    n = toast_count(host)
    log("  连发 5 条不同内容后 =", n)
    assert n == 3, f"上限应当是 3，实际 {n}"

    wait(life + 2200)
    assert toast_count(host) == 0

    log()
    log("全部通过")
    core.shutdown()
    # ★ 用 os._exit 直接走，不要 app.quit()。
    #   app.quit() 会给窗口发 close 事件，而 QML 的 onClosing 在
    #   「收进托盘」模式下会 accepted=false 把它拦下来 —— 事件循环退不出去，
    #   脚本明明跑完了（输出「全部通过」）却挂在那里，看起来像超时。
    #   这个脚本的结论已经全部打印完了，不需要优雅收尾。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


QTimer.singleShot(300, run)
QTimer.singleShot(90000, lambda: os._exit(1))
app.exec()
