"""用户协议弹窗的回归测试。

要求：
  1. 首次启动必须弹（agreement_version = 0）
  2. **必须滚动读到底**才能勾选（未读完时勾选框禁用）
  3. 勾选后才能点「开始使用」
  4. 同意后写回版本号，下次启动不再弹
  5. 不能靠 Esc / 点外面关掉（必须明确同意或退出）
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

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
# 别真的去扫 B 站：把扫描 worker 换成空操作，
# 避免退出时后台线程还在跑、踩到「ModListModel 已析构」的崩溃。
core._scan_worker = lambda: (core._set_busy(False), core.statusChanged.emit())
# 强制「没同意过」。同时记住原值，测试结束还原 ——
# 否则跑到一半调 acceptAgreement() 会把 config.json 写成「已同意」，
# 下次再跑这个测试前置状态就不对了（全量跑的顺序依赖）。
_old_agreement = core.config["agreement_version"]
core.config["agreement_version"] = 0
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
    dlg = win.findChild(object, "agreementDlg")
    flick = win.findChild(object, "agreementFlick")

    print("=== 1. 首次启动会弹 ===")
    check("agreementNeeded = True", core.property("agreementNeeded") is True)
    check("弹窗元素存在", dlg is not None)
    check("滚动区存在", flick is not None)
    if dlg is None or flick is None:
        return finish()

    check("弹窗已打开", dlg.property("opened") is True, str(dlg.property("opened")))
    # closePolicy 是 QFlags 枚举，PySide 读回来会报 "Can't find converter"，
    # 改成在源码里断言「写的是 NoAutoClose」。
    main_src = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    check("禁止自动关闭（NoAutoClose，没有 Esc/点外面）",
          "closePolicy: Popup.NoAutoClose" in main_src)

    print()
    print("=== 2. 未读完不能勾选 ===")
    ch = float(flick.property("contentHeight"))
    h = float(flick.property("height"))
    print(f"  正文 {ch:.0f}px，可视 {h:.0f}px", flush=True)
    check("正文比可视区长（需要滚动）", ch > h + 4, f"{ch:.0f} vs {h:.0f}")
    check("初始不在底部", flick.property("contentY") == 0)
    # 倒计时必须真的在跑，不只是写了句文案。
    # 这两个属性在窗口根对象上（弹窗实例的属性名不会传进 contentItem）。
    left = win.property("agreeLeft")
    check("倒计时在走（已从 10 往下减）",
          left is not None and int(left) < 10, str(left))

    box = win.findChild(object, "agreementCheck")
    check("找到勾选框", box is not None)
    # ★ 不用 childItems() 去找 MouseArea —— 无头环境下它拿不到子节点。
    #   改为在源码里断言「勾选框的 enabled 绑到了 agreementReady」，
    #   agreementReady = 读到最底 or 倒计时跑完，这正是「未读完不能点」的实现方式。
    check("勾选框的 enabled 绑到 agreementReady（未读完禁用）",
          "enabled: win.agreementReady" in main_src)
    # 倒计时：10 秒，划到底也能提前解锁（用户要求）。
    check("倒计时初值是 10 秒", "property int agreeLeft: 10" in main_src)
    check("每 1 秒减 1 的 Timer",
          "interval: 1000" in main_src
          and "win.agreeLeft = win.agreeLeft - 1" in main_src)
    check("agreementReady = 到底 or 倒计时结束",
          "agreeFlick.atBottom || agreeLeft <= 0" in main_src)
    check("提示文案不再报 px，改成还剩几秒",
          '还剩 "' in main_src
          and '+ win.agreeLeft + " 秒）' in main_src
          and " px）" not in main_src)

    btn = win.findChild(object, "agreementAcceptBtn")
    check("找到「开始使用」按钮", btn is not None)
    if btn is not None:
        check("未勾选时按钮禁用", btn.property("enabledBtn") is False,
              str(btn.property("enabledBtn")))

    QTimer.singleShot(400, lambda: phase2(flick, btn))


def phase2(flick, btn):
    print()
    print("=== 3. 滚到底后可以勾选 ===")
    ch = float(flick.property("contentHeight"))
    h = float(flick.property("height"))
    flick.setProperty("contentY", max(0.0, ch - h))
    QTimer.singleShot(500, lambda: phase3(flick, btn))


def phase3(flick, btn):
    check("滚到底后 atBottom = True", flick.property("atBottom") is True,
          f"contentY={flick.property('contentY')}")
    dlg = win.findChild(object, "agreementDlg")
    if dlg is not None:
        # 用户要求「划到最底下就能勾选」：即使倒计时还没跑完也要解锁。
        check("划到底后 agreementReady = True（不用等倒计时）",
              win.property("agreementReady") is True,
              f"agreeLeft={win.property('agreeLeft')}")

    # 勾选
    win.setProperty("agreeChecked", True)
    QTimer.singleShot(300, lambda: phase4(btn))


def phase4(btn):
    check("勾选后 agreeChecked = True", win.property("agreeChecked") is True)
    if btn is not None:
        check("勾选后按钮可用", btn.property("enabledBtn") is True,
              str(btn.property("enabledBtn")))

    print()
    print("=== 4. 同意后写回版本号 ===")
    core.acceptAgreement()
    check("agreement_version 已写入",
          int(core.config["agreement_version"]) == core.AGREEMENT_VERSION,
          str(core.config["agreement_version"]))
    check("agreementNeeded 变 False", core.property("agreementNeeded") is False)

    # 关掉弹窗
    dlg = win.findChild(object, "agreementDlg")
    if dlg is not None:
        dlg.close()
    QTimer.singleShot(300, phase5)


def phase5():
    print()
    print("=== 5. 源码里有那几条约定 ===")
    src = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    # 新版协议（草案）的六节标题 + 关键约定
    for key, label in (
        ("1. 这是什么工具", "第 1 节：这是什么工具"),
        ("2. 禁止贩卖和营利", "第 2 节：禁止贩卖和营利"),
        ("3. 禁止违法和违规使用", "第 3 节：禁止违法和违规使用"),
        ("4. MOD 链接功能说明", "第 4 节：MOD 链接功能说明"),
        ("5. 责任限制", "第 5 节：责任限制"),
        ("6. 协议修改", "第 6 节：协议修改"),
        ("三连", "提到三连支持创作者"),
        ("代找 MOD", "列出代找代下的收费行为"),
        ("不是 Valve、Steam 官方产品", "声明非官方"),
        ("github.com/Yumivvv/YumiL4D2", "给出联系方式"),
    ):
        check(label, key in src)

    finish()


def finish():
    bad = [w for w in warns if any(k in w for k in
           ("TypeError", "is not a function", "ReferenceError", "Unable",
            "non-existent", "Binding loop"))]
    if bad:
        print("  QML 告警:", bad[:3], flush=True)
        fails.append("QML 告警")
    # 还原「已同意」状态，别把污染留给下一个测试
    try:
        core.config["agreement_version"] = _old_agreement
        core.config.save()
    except Exception:                        # noqa: BLE001
        pass
    core.shutdown()
    core.quitFromWindow()
    print()
    if fails:
        print("失败 %d 项：%s" % (len(fails), fails))
        sys.exit(1)
    print("全部通过")


QTimer.singleShot(2400, phase1)
QTimer.singleShot(25000, core.quitFromWindow)
app.exec()
