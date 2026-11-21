"""回归：悬浮快捷按钮不能和右侧数据区重叠。

在 ServersPage 里加一个诊断函数，用 QML 自己的坐标系算：
  · 悬浮按钮行（anchors.verticalCenter = srvCardTopActionBar.verticalCenter）
  · 右侧数据区 bigInfo
  · 两者在卡片内的矩形是否相交
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import protect_user_data  # noqa: E402

protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QMetaObject, QTimer, QUrl  # noqa: E402
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
core.config["servers"] = [
    {"addr": "1.1.1.1:27015", "name": "天域1服 对抗 长期有效", "weight": 5, "panels": []},
    {"addr": "3.3.3.3:27015", "name": "宿舍常玩的服", "weight": 9, "panels": []},
]
eng.rootContext().setContextProperty("core", core)
eng.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))
win = eng.rootObjects()[0]
win.resize(1320, 880)
win.show()

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


def phase1():
    win.setProperty("section", 3)
    QTimer.singleShot(1800, phase2)


def phase2():
    page = win.findChild(object, "serversPage")
    if page is None:
        return finish()
    # 调 QML 侧的诊断函数（返回值是 QVariantMap）
    res = QMetaObject.invokeMethod(page, "probeCardGeometry")
    print("  probe 直接返回:", res, flush=True)

    # 用 QMetaObject 拿不到返回值时，改读暴露的属性
    geo = page.property("cardGeometry")
    try:
        geo = geo.toVariant()
    except Exception:
        pass
    print("  cardGeometry =", geo, flush=True)

    if not isinstance(geo, dict):
        check("能拿到卡片几何", False, str(type(geo)))
        return finish()

    check("能拿到卡片几何", True, str(list(geo.keys())))

    card_h = geo.get("cardH", 0)
    btn = geo.get("btnRect") or {}
    info = geo.get("infoRect") or {}
    print(f"  卡片高={card_h}  按钮={btn}  数据区={info}", flush=True)

    if btn and info:
        # 矩形相交判断
        bx, by = btn.get("x", 0), btn.get("y", 0)
        bw, bh = btn.get("w", 0), btn.get("h", 0)
        ix, iy = info.get("x", 0), info.get("y", 0)
        iw, ih = info.get("w", 0), info.get("h", 0)
        ox = max(0, min(bx + bw, ix + iw) - max(bx, ix))
        oy = max(0, min(by + bh, iy + ih) - max(by, iy))
        check("按钮与数据区不重叠", ox == 0 or oy == 0, f"重叠 {ox}x{oy}")

        check("按钮完全在卡片内",
              by >= 0 and by + bh <= card_h,
              f"y={by}..{by+bh} / cardH={card_h}")

        check("按钮在卡片下半部分", by > card_h * 0.55,
              f"y={by} / {card_h}")

        check("数据区在按钮上方结束", iy + ih <= by + 2,
              f"数据区底={iy+ih}  按钮顶={by}")

    finish()


def finish():
    bad = [w for w in warns if any(k in w for k in
           ("TypeError", "is not a function", "ReferenceError", "Unable",
            "non-existent", "Binding loop"))]
    if bad:
        print("  QML 告警:", bad[:3], flush=True)
        fails.append("QML 告警")
    core.shutdown()
    core.quitFromWindow()
    print()
    if fails:
        print("失败 %d 项：%s" % (len(fails), fails))
        sys.exit(1)
    print("全部通过")


QTimer.singleShot(2200, phase1)
QTimer.singleShot(25000, core.quitFromWindow)
app.exec()
