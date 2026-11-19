"""QML 加载 + 真实窗口走一遍，看有没有绑定报错。

为什么要走 app.exec()：早先这里不 show()、用嵌套 QEventLoop 收尾，结果委托压根
没建出来，「LOAD: True 无警告」是假结论。

为什么要自己重定向 fd 2：QML 的 TypeError 是 C++ 层直接写 stderr 的，Python
的 sys.stderr 拦不到；而进程退出时 Python 会先回收 `core`、QML 引擎后拆树，
那时绑定重新求值读到的全是 null，会刷一屏假的
"Cannot read property 'xxx' of null"。所以这里把 stderr 重定向到文件，在窗口
走完全程、还没开始退出的时候把文件读出来判定 —— 退出阶段写进去的一律不算。

真正跑起来的 main.py 是干净的（本脚本的 before-exit 行数应为 0）。
"""
import os, sys

sys.path.insert(0, ".")

# 测试会构造真的 Core()，必须先把运行时数据目录隔离到临时沙盒，
# 否则会覆盖用户真实的 config.json / library.json / 导入日期台账。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from guard import protect_user_data  # noqa: E402
protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from app.util import ROOT, DATA_DIR

# 先把 fd 2 换成文件，之后所有 C++ 层的警告都会落到这里
LOG_PATH = os.path.join(DATA_DIR, "loadcheck.log")
os.makedirs(DATA_DIR, exist_ok=True)
_log_fd = os.open(LOG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
os.dup2(_log_fd, 2)

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from app.core import Core

NOISE = ("Fixedsys", "DirectWrite", "qt.multimedia", "FFmpeg version")

app = QGuiApplication(sys.argv[:1])
eng = QQmlApplicationEngine()
q = os.path.join(ROOT, "qml")
eng.addImportPath(q)
eng.addImportPath(os.path.join(q, "components"))
ws = []
eng.warnings.connect(lambda x: [ws.append(w.toString()) for w in x])
core = Core(app)
eng.rootContext().setContextProperty("core", core)
eng.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))
print("LOAD:", bool(eng.rootObjects()), flush=True)

if not eng.rootObjects():
    app.quit()
else:
    win = eng.rootObjects()[0]
    win.show()


def step1():
    # 到 MOD 页，让那边的委托也建出来
    win.setProperty("section", 1)
    QTimer.singleShot(1500, step2)


def step2():
    win.setProperty("section", 0)
    win.setProperty("detailOpen", True)
    QTimer.singleShot(1200, step3)


def step3():
    win.setProperty("settingsOpen", True)
    QTimer.singleShot(1200, step4)


def step4():
    win.setProperty("settingsOpen", False)
    win.setProperty("section", 0)
    QTimer.singleShot(800, done)


def done():
    # 正常收工（停后台线程、停扫描），避免后台线程在退出阶段还去动模型
    try:
        core.shutdown()
    except Exception as e:
        print("shutdown 出错:", e, flush=True)
    QTimer.singleShot(400, report)


def report():
    """窗口走完了、还没开始拆树，这时判定 stderr。"""
    try:
        os.fsync(_log_fd)
    except Exception:
        pass
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = [ln.rstrip() for ln in f if ln.strip()]
    except Exception as e:
        lines = ["读取日志失败: %s" % e]
    bad = [ln for ln in lines if not any(n in ln for n in NOISE)]
    qml_warn = [w for w in ws if not any(n in w for n in NOISE)]
    print("窗口已走过 视频页/MOD页/详情/设置", flush=True)
    print("退出前 stderr 有内容的行数:", len(bad), flush=True)
    for ln in bad[:40]:
        print("  ERR:", ln, flush=True)
    print("QQmlEngine.warnings:", len(qml_warn), flush=True)
    for w in qml_warn[:20]:
        print("  WARN:", w, flush=True)
    print("RESULT:", "CLEAN" if (not bad and not qml_warn) else "DIRTY", flush=True)
    app.quit()


QTimer.singleShot(2200, step1)
QTimer.singleShot(30000, app.quit)
app.exec()
