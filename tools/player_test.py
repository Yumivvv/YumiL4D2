# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys, os, time
sys.path.insert(0, ".")

# 测试会构造真的 Core()，必须先把运行时数据目录隔离到临时沙盒，
# 否则会覆盖用户真实的 config.json / library.json / 导入日期台账。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from guard import protect_user_data  # noqa: E402
protect_user_data()
from PySide6.QtCore import QTimer, QEventLoop, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtMultimedia import QVideoSink
from app.core import Core
from app.util import ROOT

app = QGuiApplication(sys.argv[:1])
eng = QQmlApplicationEngine()
q = os.path.join(ROOT, "qml")
eng.addImportPath(q); eng.addImportPath(os.path.join(q, "components"))
core = Core(app)
eng.rootContext().setContextProperty("core", core)
eng.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))
win = eng.rootObjects()[0]
win.show()

p = core.player
states = []

def log(*a):
    print(*a, flush=True)

def step1():
    it = core.library.all_items()
    # ★ 视频库为空时必须优雅跳过，不能 it[0] 直接崩。
    #   以前测试机库是空的就 IndexError，而异常发生在 QTimer 回调里、
    #   事件循环还在跑，于是进程一直挂着等 30 秒超时（看起来像「测试卡死」）。
    if not it:
        log("[skip] 视频库是空的，没法测播放（先抓一次视频再跑）")
        # 仍然把「关闭」那条路径走一遍，保证 stop()/清空流地址是对的
        QTimer.singleShot(200, step3)
        return
    log("播放:", it[0]["bvid"], it[0]["title"][:30])
    p.open(it[0]["bvid"], it[0]["title"])

def step2():
    log("loading:", p.loading, "ready:", p.ready, "streaming:", p.streaming)
    log("duration:", p.duration, "position:", p.position)
    log("音量:", p.volume)
    p.setVolume(35)
    log("调音量后:", p.volume)
    p.changeVolume(20)
    log("再 +20:", p.volume)
    p.changeVolume(-100)
    log("调到 0:", p.volume)
    p.setVolume(70)
    log("恢复 70:", p.volume)

def step3():
    log("--- 关闭测试 ---")
    log("关闭前 playing:", p.playing, "streaming:", p.streaming)
    p.stop()
    log("stop 后 ready:", p.ready, "streaming:", p.streaming, "playing:", p.playing)
    stream_url = getattr(p, "_stream_url", "")
    log("stream_url 已清空:", stream_url == "")
    # ★ 不用 app.quit()：它会给窗口发 close，而 QML 的 onClosing 在
    #   「收进托盘」模式（默认）下会拦下来，事件循环退不出去 → 进程挂住。
    #   这个脚本的结论已经打印完，直接退。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)

QTimer.singleShot(800, step1)
QTimer.singleShot(6000, step2)
QTimer.singleShot(11000, step3)
QTimer.singleShot(30000, lambda: os._exit(1))
app.exec()
