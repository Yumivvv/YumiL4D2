"""验证：没有网盘的置顶评论也能正常显示（不再被预算压没）。

用户报的问题：置顶评论只有「有网盘」时才显示，没网盘就不显示。

★ 真正的触发条件是**窗口高度**，不是有没有网盘：
  窗口矮 → shareRoom 被简介吃光 → 评论按 45% 分到 0 → 整块消失。
  「有网盘才显示」只是巧合（有网盘时窗口通常更大 / 布局不同）。
  所以本测试特意用**最小窗口尺寸 1040x640** 跑，这正是最容易复现的场景。
根因：commentBudget 固定只拿 shareRoom 的 45%，网盘那块即使高度为 0
也不把 55% 让出来，窗口一小 45% 就接近 0，整块被压没。

这里用真实数据（有置顶评论、但没有网盘的视频）打开详情面板，
读 topCommentBox 的高度和可见性。
"""
import json
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
eng.rootContext().setContextProperty("core", core)
eng.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))
win = eng.rootObjects()[0]
win.resize(1040, 640)   # 界面最小尺寸，最极端的情况   # 故意矮一点，验证空间紧张时也不丢
win.show()

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


def pick_target():
    """找一个有置顶评论、但简介和评论里都没网盘的视频。"""
    lib = json.load(open(os.path.join(ROOT, "data", "library.json"), encoding="utf-8"))
    rows = list(lib["videos"].values()) if isinstance(lib["videos"], dict) else lib["videos"]
    link_keys = ("pan.baidu", "lanzou", "quark", "alipan", "123pan", "aliyundrive")
    for v in rows:
        tc = v.get("topComment") or {}
        txt = (tc.get("text") or "").strip()
        if len(txt) < 8:
            continue
        desc = v.get("desc") or ""
        if any(k in desc for k in link_keys) or any(k in txt for k in link_keys):
            continue
        # 还要 detail_loaded，否则打开详情会走网络
        if not v.get("detail_loaded"):
            continue
        return v
    return None


def phase1():
    target = pick_target()
    if target is None:
        print("  （库里没有合适样本，跳过）", flush=True)
        return finish()
    print(f"  样本: {target.get('bvid')}", flush=True)
    print(f"  标题: {(target.get('title') or '')[:36]}", flush=True)
    print(f"  评论: {((target.get('topComment') or {}).get('text') or '')[:50]}", flush=True)

    # 注意：core.findVideo() 走的是 _decorate，那是**列表用**的精简数据，
    # 不含 topComment（那是 detailReady 才推的完整详情）。
    # 所以这里直接看库里那份记录，以及面板上真实渲染出来的框。
    # target 本身就是库里的原始记录（pick_target 直接读的 library.json）
    rec = target
    desc = rec.get("desc") or ""
    tc_rec = rec.get("topComment") or {}
    link_keys = ("pan.baidu", "lanzou", "quark", "alipan", "123pan", "aliyundrive")
    check("样本简介里没有网盘",
          not any(k in desc for k in link_keys))
    check("样本确实有置顶评论",
          len((tc_rec.get("text") or "").strip()) > 0,
          str(len((tc_rec.get("text") or ""))))

    win.openDetail(target["bvid"])
    QTimer.singleShot(2200, lambda: phase2(target))


def phase2(target):
    box = win.findChild(object, "dpCommentBox")
    check("找到置顶评论框", box is not None)
    if box is None:
        return finish()

    h = float(box.property("height"))
    vis = box.property("visible")
    print(f"  topCommentBox: visible={vis} height={h:.0f}", flush=True)

    check("置顶评论框可见", vis is True)
    check("置顶评论框有高度（没被预算压没）", h > 40, f"{h:.0f}px")

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


QTimer.singleShot(2400, phase1)
QTimer.singleShot(28000, core.quitFromWindow)
app.exec()
