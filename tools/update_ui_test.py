"""检查更新（GitHub Releases）相关 UI 的回归测试。

覆盖：
  1. 关于页的「检查更新」按钮、弹窗里的元素都存在，默认状态正确
  2. 手动检查的链路：有新版 / 出错时，弹窗里的文字和按钮怎么变
  3. 设置页的「自动检测更新」开关（默认关，开关能写进配置）
  4. 源码里的约定（按钮名、弹窗名、label 分支）
  5. 检查过程**不弹窗**，只有发现新版本才由 updatePrompt 弹出来

网络一律不打：直接把 core._update_info 塞进去看 QML 怎么显示。
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

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
# 别真的去扫 B 站：把扫描 worker 换成空操作。
# 否则退出时后台线程还在跑，会踩到「ModListModel 已析构」的 libshiboken 崩溃。
core._scan_worker = lambda: (core._set_busy(False), core.statusChanged.emit())
# 关掉自动检查，别在测试里真去打 GitHub。
_old_auto = core.config["auto_check_update"]
core.config["auto_check_update"] = False
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
    print("=== 1. 元素与默认状态 ===")
    btn = win.findChild(object, "checkUpdateBtn")
    dlg = win.findChild(object, "updateDlg")
    check("关于页有「检查更新」按钮", btn is not None)
    check("检查更新弹窗存在", dlg is not None)
    if dlg is not None:
        check("弹窗默认不显示", dlg.property("visible") is False)

    status = win.findChild(object, "updateStatusText")
    note = win.findChild(object, "updateNoteText")
    download = win.findChild(object, "updateDownloadBtn")
    check("状态文字存在", status is not None)
    check("更新日志区存在", note is not None)
    check("下载按钮存在", download is not None)

    check("默认没有在检查", core.property("updateChecking") is False)
    check("默认不在下载", core.property("updateDownloading") is False)

    info = core.property("updateInfo")
    check("updateInfo 有 6 个键",
          isinstance(info, dict) and set(info) == {
              "has_update", "current", "latest", "note", "url", "error"},
          str(sorted(info) if isinstance(info, dict) else info))
    check("默认没有新版本", info.get("has_update") is False)
    check("默认无错误", (info.get("error") or "") == "")

    check("自动检测更新默认是关的", core.property("autoCheckUpdate") is False,
          str(core.property("autoCheckUpdate")))
    check("配置里有 auto_check_update 键", "auto_check_update" in core.config.data)

    src = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    check("关于页按钮只发起检查、不直接弹窗",
          'objectName: "checkUpdateBtn"' in src
          and "onClicked: core.checkUpdate()" in src)
    check("发现新版时由 updatePrompt 触发弹窗",
          "onUpdatePrompt" in src and "updateDlg.open()" in src)
    check("弹窗对象名是 updateDlg", 'objectName: "updateDlg"' in src)
    check("状态文字有「发现新版本」分支", "发现新版本" in src)
    check("状态文字有「已是最新版本」分支", "当前已是最新版本" in src)
    check("有下载更新的按钮", 'objectName: "updateDownloadBtn"' in src)
    check("设置页有「自动检测更新」开关",
          "自动检测更新" in src and "setAutoCheckUpdate(v)" in src)

    phase2()


def inject(info):
    core._update_info = dict(info)
    core.updateChanged.emit()


def phase2():
    print()
    print("=== 2. 有新版时的显示 ===")
    dlg = win.findChild(object, "updateDlg")
    status = win.findChild(object, "updateStatusText")
    note = win.findChild(object, "updateNoteText")
    download = win.findChild(object, "updateDownloadBtn")
    if dlg is None or status is None or note is None or download is None:
        print("  元素没找到，跳过")
        return finish()

    inject({
        "has_update": True, "current": "1.0.1", "latest": "1.0.2",
        "note": "【1.0.2】\n修了三连按钮的位置", "url": "https://example.com/x.exe",
        "error": "",
    })
    dlg.open()
    QTimer.singleShot(300, lambda: phase3(dlg, status, note, download))


def phase3(dlg, status, note, download):
    check("弹窗已打开", dlg.property("opened") is True,
          str(dlg.property("opened")))
    # 几何：弹窗 460 宽，要整个落在窗口里（用户最在意「文字/框跳出 UI」）。
    dx = dlg.property("x")
    dy = dlg.property("y")
    dw = dlg.property("width")
    dh = dlg.property("height")
    wx, wy = win.property("x"), win.property("y")
    ww, wh = win.property("width"), win.property("height")
    check("弹窗宽度是 460", dw == 460, str(dw))
    check("弹窗没超出窗口右边", dx + dw <= wx + ww + 1,
          f"{dx + dw} <= {wx + ww}")
    check("弹窗没超出窗口下边", dy + dh <= wy + wh + 1,
          f"{dy + dh} <= {wy + wh}")
    # 更新日志的 Text 宽度要小于 Flickable 内容宽（别撑出去）
    note_w = note.property("width")
    check("更新日志文字宽度没超过弹窗内容", note_w <= dw - 24,
          f"{note_w} <= {dw - 24}")
    check("状态显示发现新版本", "发现新版本" in status.property("text"),
          status.property("text"))
    check("日志里能看到新版本号", "1.0.2" in status.property("text"))
    check("更新日志区显示内容", "1.0.2" in note.property("text"),
          note.property("text"))
    check("按钮变成「下载并更新」", download.property("label") == "下载并更新",
          str(download.property("label")))

    print()
    print("=== 3. 检查失败时的显示 ===")
    inject({
        "has_update": False, "current": "1.0.1", "latest": "",
        "note": "", "url": "", "error": "检查更新失败（所有源均不可用）",
    })
    QTimer.singleShot(300, lambda: phase4(status, note, download))


def phase4(status, note, download):
    check("状态显示错误文案", "检查更新失败" in status.property("text"),
          status.property("text"))
    check("错误时按钮是「重新检查」", download.property("label") == "重新检查",
          str(download.property("label")))
    check("错误时不显示日志区", note.property("visible") is False)

    print()
    print("=== 4. 已最新版 ===")
    inject({
        "has_update": False, "current": "1.0.1", "latest": "1.0.1",
        "note": "", "url": "", "error": "",
    })
    QTimer.singleShot(300, lambda: phase5(status, note, download))


def phase5(status, note, download):
    check("状态显示已是最新", "当前已是最新版本" in status.property("text"),
          status.property("text"))
    check("已最新时按钮是「重新检查」", download.property("label") == "重新检查",
          str(download.property("label")))

    print()
    print("=== 5. 自动检测开关能写进配置 ===")
    core.setAutoCheckUpdate(True)
    check("开关打开后属性为真", core.property("autoCheckUpdate") is True)
    check("开关值写进配置", core.config["auto_check_update"] is True,
          str(core.config["auto_check_update"]))
    core.setAutoCheckUpdate(False)
    check("开关关掉后属性为假", core.property("autoCheckUpdate") is False)
    check("配置已还原", core.config["auto_check_update"] is False)

    phase6(win.findChild(object, "updateDlg"))


def phase6(dlg):
    print()
    print("=== 6. 检查过程不弹窗，只有发现新版才弹 ===")
    check("core 有 updatePrompt 信号", hasattr(core, "updatePrompt"))
    dlg.close()
    QTimer.singleShot(250, lambda: _p6_closed(dlg))


_p6_orig = {}


def _p6_closed(dlg):
    check("先确认弹窗是关着的", dlg.property("opened") is False,
          str(dlg.property("opened")))
    # 手动点检查、且服务端没有新版 → 不许弹窗（只 toast 一句）
    # ★ 补丁要等 worker 线程真的跑完再还原，否则线程可能读到已还原的真函数去联网
    import app.core as coremod

    _p6_orig["fn"] = coremod.check_update
    coremod.check_update = lambda repo, cur: {
        "has_update": False, "current": cur, "latest": cur,
        "note": "", "url": "", "error": "",
    }
    core.checkUpdate()
    QTimer.singleShot(700, lambda: _p6_no_popup(dlg))


def _p6_no_popup(dlg):
    import app.core as coremod

    if "fn" in _p6_orig:
        coremod.check_update = _p6_orig["fn"]
    check("没有新版时检查完不弹窗", dlg.property("opened") is False,
          str(dlg.property("opened")))
    check("检查已经结束", core.property("updateChecking") is False)
    # 有新版 → updatePrompt 发出来就该弹
    core.updatePrompt.emit()
    QTimer.singleShot(350, lambda: _p6_prompt(dlg))


def _p6_prompt(dlg):
    check("updatePrompt 一到就弹窗", dlg.property("opened") is True,
          str(dlg.property("opened")))
    dlg.close()
    finish()


def finish():
    bad = [w for w in warns if any(k in w for k in
            ("TypeError", "is not a function", "ReferenceError", "Unable",
             "non-existent", "Binding loop"))]
    if bad:
        print("  QML 告警:", bad[:3], flush=True)
        fails.append("QML 告警")
    dlg = win.findChild(object, "updateDlg")
    if dlg is not None and dlg.property("visible") is not None:
        try:
            dlg.close()
        except Exception:                            # noqa: BLE001
            pass
    # 还原配置，别把「自动检测更新」开着留给下一个测试
    try:
        core.config["auto_check_update"] = _old_auto
        core.config.save()
    except Exception:                                # noqa: BLE001
        pass
    core.shutdown()
    app.quit()
    print()
    if fails:
        print("失败 %d 项：%s" % (len(fails), fails))
        sys.exit(1)
    print("全部通过")


QTimer.singleShot(2000, phase1)
QTimer.singleShot(20000, app.quit)
app.exec()
