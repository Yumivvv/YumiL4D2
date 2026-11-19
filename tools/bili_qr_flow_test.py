"""扫码登录的端到端验证（真实 B 站接口 + 真实 QML）。

重点验证「一直显示二维码已过期」这个报障：
  在 QML 里打开弹窗、等 20 秒（超过 10 次轮询），
  全程采样 biliLoginState，断言它**从来没有变成 expired**。

真机上「手机上点确认」这一步没法自动化，但「不应该过期」完全可以验证。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import protect_user_data  # noqa: E402

protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from app.core import Core  # noqa: E402
from app.util import ROOT  # noqa: E402

app = QGuiApplication(sys.argv[:1])
eng = QQmlApplicationEngine()
q = os.path.join(ROOT, "qml")
eng.addImportPath(q)
eng.addImportPath(os.path.join(q, "components"))
warns = []
eng.warnings.connect(lambda ws: [warns.append(w.toString()) for w in ws])
core = Core(app)
core.biliLogout()
eng.rootContext().setContextProperty("core", core)
eng.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))
win = eng.rootObjects()[0]
win.resize(1200, 800)
win.show()

fails = []
samples = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


def phase1():
    win.setProperty("section", 5)
    QTimer.singleShot(1200, phase2)


def phase2():
    dlg = win.findChild(object, "biliLoginDlg")
    if dlg is None:
        check("找到登录弹窗", False)
        return finish()
    check("找到登录弹窗", True)
    dlg.open()
    QTimer.singleShot(800, phase3)


def phase3():
    st = win.property("biliLoginState")
    samples.append(st)
    check("打开后开始生成（state 不是空）", st != "", repr(st))
    check("state 是 waiting（不是 expired）", st == "waiting", repr(st))
    key = win.property("biliQrKey")
    check("轮询 key 已设置", len(key or "") > 0, (key or "")[:16])
    check("二维码图片 URL 非空", len(core.biliQrImage) > 0,
          (core.biliQrImage or "")[:40])

    # 每隔 2 秒采样一次，共 18 秒（B 站二维码 3 分钟内有效，这里只验证不过期）
    QTimer.singleShot(2000, sample_tick)


def sample_tick():
    if len(samples) >= 10:
        return report()
    st = win.property("biliLoginState")
    samples.append(st)
    print(f"  第 {len(samples)} 次采样: state={st!r}", flush=True)
    QTimer.singleShot(2000, sample_tick)


def report():
    print()
    print("  全部采样:", samples)
    expired = [s for s in samples if s == "expired"]
    check("全程没有出现 expired", len(expired) == 0, str(expired))
    check("全程保持在 waiting", all(s == "waiting" for s in samples),
          str(set(samples)))
    finish()


def finish():
    bad = [w for w in warns if any(k in w for k in
           ("TypeError", "is not a function", "ReferenceError",
            "Unable", "non-existent"))]
    if bad:
        print("  QML 告警:", bad[:3], flush=True)
        fails.append("QML 告警")
    core.shutdown()
    app.quit()
    print()
    if fails:
        print("失败 %d 项：%s" % (len(fails), fails))
        # 用 os._exit 跳过解释器收尾：core 被回收之后 QML 引擎还在拆树，
        # 会刷一屏「Cannot read property xxx of null」（那不是被测代码的问题），
        # 而且会让退出码变成 1，看起来像测试失败。
        os._exit(1)
    print("全部通过")
    os._exit(0)


QTimer.singleShot(2000, phase1)
QTimer.singleShot(30000, app.quit)
app.exec()
