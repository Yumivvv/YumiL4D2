"""详情面板「操作按钮」+ 登录弹窗的几何回归。

用户先后报过三件事，这个脚本把它们都钉成断言：

1. **三连按钮曾被挤出面板外面**（五颗按钮比例加起来 1.0 再加 spacing）。
   现在五颗等宽、间距 8px，加起来正好占满可用宽度。
2. **三连要挨着「分享」右边**，而且没登录时点它不能「点了没反应」——
   要提示登录并当场弹出二维码（以前 `enabledBtn: core.biliLoggedIn`
   把 MouseArea 关掉了，`needLogin` 那条分支是死代码）。
3. **切换账号弹窗里的文字跳出 UI 范围**：`Column` 设了 left/rightPadding
   之后，子项的 `width: parent.width` 拿到的仍是整宽，文字右边界比弹窗
   多出 20px，直接压在边框上。

跑法：`python -X utf8 tools/detail_actions_test.py`
不联网、不截图，只量几何。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import protect_user_data      # noqa: E402

protect_user_data(verbose=False)
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, QUrl      # noqa: E402
from PySide6.QtGui import QGuiApplication                          # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine                    # noqa: E402
from PySide6.QtTest import QTest                                   # noqa: E402

from app.core import Core                                          # noqa: E402
from app.util import ROOT                                          # noqa: E402

BTNS = ["playButton", "shareButton", "tripleButton",
        "copyLinkButton", "browserButton"]
FAILS: list[str] = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name
          + (("  " + str(extra)) if extra != "" else ""), flush=True)
    if not ok:
        FAILS.append(name)


def prop(obj, name):
    try:
        return obj.property(name)
    except Exception:            # noqa: BLE001  对象已销毁之类
        return None


def win_geom(obj):
    """相对**窗口内容区**的坐标。

    ★ 不能一直加到根：最顶层是 Main（Window 本身），它的 x/y 是窗口在屏幕上
    的位置（比如 194,70）。把它算进来，QTest 的点击就整体偏到窗口外面。
    """
    x = y = 0.0
    cur = obj
    while cur is not None and cur.parent() is not None:
        x += float(prop(cur, "x") or 0)
        y += float(prop(cur, "y") or 0)
        cur = cur.parent()
    return x, y


def walk(obj, out):
    out.append(obj)
    for kid in obj.children():
        walk(kid, out)


def main() -> int:
    app = QGuiApplication(sys.argv[:1])
    eng = QQmlApplicationEngine()
    qml_dir = os.path.join(ROOT, "qml")
    eng.addImportPath(qml_dir)
    eng.addImportPath(os.path.join(qml_dir, "components"))
    warns: list[str] = []
    eng.warnings.connect(lambda ws: [warns.append(w.toString()) for w in ws])

    core = Core(app)
    # 假凭据在真机上会被 nav 判定失效并清掉，这里直接短路，避免测到一半变未登录
    core.biliRefreshUser = lambda: {"ok": True}       # type: ignore[assignment]
    eng.rootContext().setContextProperty("core", core)
    eng.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
    if not eng.rootObjects():
        print("  FAIL Main.qml 没加载起来")
        return 1
    win = eng.rootObjects()[0]
    win.resize(1320, 880)
    win.show()

    def start():
        # 沙箱会拷用户真实的 config.json 进来，里面可能带真凭据 —— 先明确登出
        core.client.clear_credentials()
        core._bili_user = {}
        core.config["bili_credentials"] = {}
        core.statusChanged.emit()
        check("初始是未登录", core.biliLoggedIn is False)
        win.setProperty("detailVideo", {
            "bvid": "BV1xx411c7mD",
            "title": "【求生之路2】测试视频",
            "author": "测试UP", "mid": "1",
            "pubText": "2026-11-19 12:00:00", "viewsText": "1",
            "replyText": "0", "likeText": "0", "favText": "0",
            "coinText": "0", "shareText": "0",
            "desc": "简介。" * 200,
            "links": [], "topComment": {},
        })
        win.setProperty("detailOpen", True)
        QTimer.singleShot(1500, check_buttons)

    def check_buttons():
        objs = [win.findChild(QObject, n) for n in BTNS]
        check("五颗按钮都找得到", all(o is not None for o in objs),
              [n for n, o in zip(BTNS, objs) if o is None])
        if any(o is None for o in objs):
            return finish()

        geo = []
        for name, obj in zip(BTNS, objs):
            x, y = win_geom(obj)
            geo.append((name, x, x + float(prop(obj, "width") or 0)))

        print("  按钮 x 区间:")
        for name, a, b in geo:
            print("    %-14s %.1f .. %.1f" % (name, a, b))

        xs = [g[1] for g in geo]
        check("顺序是 播放 / 分享 / 三连 / 复制链接 / 浏览器",
              xs == sorted(xs), [round(v) for v in xs])

        widths = [round(b - a, 1) for _, a, b in geo]
        check("五颗按钮等宽", max(widths) - min(widths) <= 0.5, widths)

        gaps = [round(geo[i + 1][1] - geo[i][2], 1) for i in range(len(geo) - 1)]
        check("相邻间距都是 8px", all(abs(g - 8) < 0.6 for g in gaps), gaps)

        # 整行不能超出面板右边界（面板 480 宽，右边距 18）
        panel = win.findChild(QObject, "dpPanel")
        if panel is not None:
            px, _ = win_geom(panel)
            pw = float(prop(panel, "width") or 0)
            check("五颗按钮都在面板内（右边界没被顶出去）",
                  geo[-1][2] <= px + pw, "%.1f <= %.1f" % (geo[-1][2], px + pw))

        # 三连就在分享右边
        check("三连紧挨在分享右边",
              abs(geo[2][1] - geo[1][2] - 8) < 0.6,
              round(geo[2][1] - geo[1][2], 1))

        triple = objs[2]
        check("未登录时三连仍可点（enabledBtn 为真）",
              bool(prop(triple, "enabledBtn")) is True,
              prop(triple, "enabledBtn"))
        check("未登录时三连不是强调色", bool(prop(triple, "accent")) is False,
              prop(triple, "accent"))
        QTimer.singleShot(400, lambda: click_triple(triple))

    def click_triple(btn):
        # ★ 必须用**真实鼠标点击**：invokeMethod("clicked") 会绕过 MouseArea，
        #   验不出 enabledBtn 有没有把事件吞掉（那正是这个 bug 的成因）。
        x, y = win_geom(btn)
        w = float(prop(btn, "width") or 0)
        h = float(prop(btn, "height") or 0)
        pt = QPoint(int(x + w / 2), int(y + h / 2))
        QTest.mouseMove(win, pt)
        QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, pt)
        QTimer.singleShot(1600, check_popup)

    def check_popup():
        dlg = win.findChild(QObject, "biliLoginDlg")
        check("点三连后弹出了扫码登录窗", bool(prop(dlg, "opened")) is True,
              prop(dlg, "opened"))
        check("没把用户丢去设置页", int(prop(win, "section") or 0) == 0,
              prop(win, "section"))
        check("详情面板还开着（扫完能接着点）",
              bool(prop(win, "detailOpen")) is True, prop(win, "detailOpen"))
        check("走的是「登录」不是「切换账号」",
              bool(prop(win, "biliSwitchMode")) is False,
              prop(win, "biliSwitchMode"))
        check("二维码已经在生成",
              prop(win, "biliLoginState") in ("waiting", "loading"),
              prop(win, "biliLoginState"))
        QTimer.singleShot(300, check_dialog_bounds)

    def check_dialog_bounds():
        """切换账号弹窗：长昵称也不许把文字顶出边框。"""
        dlg = win.findChild(QObject, "biliLoginDlg")
        dlg.close()
        long_name = "Yumi_很长的昵称测试ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        core.client.set_credentials("fake_s", "fake_j", "88888888")
        core._bili_user = {"mid": 88888888, "uname": long_name, "face": "",
                           "level": 6, "vip": True}
        core.statusChanged.emit()
        win.setProperty("biliSwitchMode", True)
        win.setProperty("section", 5)
        QTimer.singleShot(1200, lambda: open_and_measure(dlg))

    def open_and_measure(dlg):
        dlg.open()
        QTimer.singleShot(1600, measure_dialog)

    def measure_dialog():
        dlg = win.findChild(QObject, "biliLoginDlg")
        col = win.findChild(QObject, "biliLoginCol")
        dx, dy = win_geom(dlg)
        dw = float(prop(dlg, "width") or 0)
        dh = float(prop(dlg, "height") or 0)
        left, right = dx, dx + dw
        print("  弹窗范围 x %.1f .. %.1f (%.0f 宽, %.0f 高)"
              % (left, right, dw, dh))

        objs: list = []
        walk(col, objs)
        bad = []
        for obj in objs:
            if not prop(obj, "visible"):
                continue
            w = float(prop(obj, "width") or 0)
            h = float(prop(obj, "height") or 0)
            if w <= 0 or h <= 0:
                continue
            ox, oy = win_geom(obj)
            try:
                txt = str(obj.property("text") or "")[:30]
            except Exception:    # noqa: BLE001
                txt = ""
            over_r = (ox + w) - right
            over_l = left - ox
            if over_r > 0.5 or over_l > 0.5:
                bad.append((txt or type(obj).__name__, round(over_r, 1),
                            round(over_l, 1)))
        check("弹窗内所有内容都在边框内（含长昵称）", not bad, bad[:4])

        # 那句提示必须真的显示出来，而且宽度小于弹窗
        hint = None
        for obj in objs:
            try:
                t = str(obj.property("text") or "")
            except Exception:    # noqa: BLE001
                continue
            if "扫码成功才会顶替" in t:
                hint = obj
                break
        check("找得到「顶替当前账号」那句提示", hint is not None)
        if hint is not None:
            hx, _ = win_geom(hint)
            hw = float(prop(hint, "width") or 0)
            check("提示文字宽度小于弹窗（留出左右边距）",
                  hw <= dw - 30, "%.1f <= %.1f" % (hw, dw - 30))
            check("提示文字左右都在弹窗里",
                  hx >= left and hx + hw <= right,
                  "%.1f..%.1f in %.1f..%.1f" % (hx, hx + hw, left, right))

        QTimer.singleShot(300, finish)

    def finish():
        dlg = win.findChild(QObject, "biliLoginDlg")
        if dlg is not None:
            try:
                dlg.close()
            except Exception:    # noqa: BLE001
                pass
        bad = [w for w in warns if any(k in w for k in
               ("TypeError", "ReferenceError", "is not a function",
                "Unable to assign", "non-existent"))]
        if bad:
            print("  QML 告警:", bad[:3], flush=True)
            FAILS.append("QML 告警")
        core.shutdown()
        print()
        if FAILS:
            print("失败 %d 项：%s" % (len(FAILS), FAILS))
        else:
            print("全部通过")
        # 跳过解释器收尾：core 被回收后 QML 还在拆树，会刷一屏无关报错
        os._exit(1 if FAILS else 0)

    QTimer.singleShot(1600, start)
    QTimer.singleShot(40000, app.quit)
    app.exec()
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
