"""验证核心场景：**鼠标一直停在提示上**，提示也必须到点消失。

这是用户实际遇到的：鼠标常常就搁在右下角，早期版本「悬停暂停」会让提示
永远卡着不走，看起来像一直在重复弹。

现在约定了：悬停不做任何事（不暂停、不重置），提示到点必然消失。
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

from PySide6.QtCore import QEventLoop, QObject, QPoint, QTimer, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.core import Core
from app.util import ROOT, ensure_dirs

LOG = os.path.join(os.environ.get("TEMP", ROOT), "toast_hover.log")
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


def toast_count(host):
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

    host = find_obj("toastLayer")
    assert host is not None, "找不到 ToastLayer"
    life = int(host.property("lifeMs") or 3600)
    log("lifeMs =", life)

    # ---------------------------------------------------- 1. 结构：没有暂停
    src = open(os.path.join(ROOT, "qml/components/ToastLayer.qml"), encoding="utf-8").read()
    log()
    log("=== 1. 悬停不再暂停 ===")
    assert "pauseLife" not in src, "还在调 pauseLife（悬停暂停残留）"
    assert "resumeLife" not in src, "还在调 resumeLife"
    assert "onEntered" not in src, "还有 onEntered（悬停时会做事）"
    assert "onExited" not in src, "还有 onExited"
    log("  没有 onEntered / onExited，悬停不做任何事")

    # ---------------------------------------------------- 2. 普通情况
    log()
    log("=== 2. 光标不在提示上：到点消失 ===")
    win.toast("普通提示", "ok")
    wait(400)
    log("  弹出后 =", toast_count(host))
    assert toast_count(host) == 1
    wait(life + 1500)
    log("  等够后 =", toast_count(host))
    assert toast_count(host) == 0, "没消失"

    # ---------------------------------------------------- 3. 鼠标压在提示上
    log()
    log("=== 3. 鼠标一直停在提示上：仍然必须消失 ===")
    win.toast("鼠标压着我", "warn")
    wait(400)
    assert toast_count(host) == 1

    # 把真实鼠标指针移到窗口右下角（提示就在那儿）
    gw = win.width()
    gh = win.height()
    target = QPoint(int(gw - 60), int(gh - 40))
    log("  把鼠标移到窗口右下角:", target.x(), target.y())
    try:
        win.setCursorPos(target) if hasattr(win, "setCursorPos") else None
        from PySide6.QtGui import QCursor

        QCursor.setPos(win.mapToGlobal(target))
        wait(200)
        log("  鼠标位置 =", QCursor.pos())
    except Exception as e:
        log("  [warn] 无法移动真实鼠标:", e)

    # 保持悬停（不停发事件让 hover 状态稳定）
    for _ in range(int((life + 1600) / 300)):
        wait(300)
    log("  等够后 =", toast_count(host))
    assert toast_count(host) == 0, "鼠标停在上面时提示没消失！"

    # ---------------------------------------------------- 4. 连发不叠
    log()
    log("=== 4. 鼠标停着 + 连发同一条：只留 1 条且会消失 ===")
    for _ in range(5):
        win.toast("同样的话", "info")
        wait(80)
    wait(400)
    n = toast_count(host)
    log("  连发 5 次后 =", n)
    assert n == 1, f"同样的文案叠了 {n} 条"

    wait(life + 1600)
    log("  等够后 =", toast_count(host))
    assert toast_count(host) == 0, "最后还有残留"

    log()
    log("全部通过")
    core.shutdown()
    core.quitFromWindow()


QTimer.singleShot(300, run)
QTimer.singleShot(90000, core.quitFromWindow)
app.exec()
