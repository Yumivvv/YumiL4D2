# -*- coding: utf-8 -*-
"""窗口关闭逻辑：确保不会因为 QQuickCloseEvent 参数转换失败而静默失效。

## 这个测试防的是什么

`Window.closing` 信号的参数类型是 `QQuickCloseEvent*`。在 Python 里
`window.closing.connect(某个函数)` **不会报错**，但事件真正触发时会抛：

    TypeError: Cannot call meta function "slot(QQuickCloseEvent*)"
    because parameter 0 of type "QQuickCloseEvent*" cannot be converted

结果是那个处理器**一次都不执行** —— 表现为「点关闭按钮，既不收托盘也不退出」。
这个坑实际踩过：打包后才发现，源码跑也一样，只是平时走托盘退出没暴露。

所以关闭逻辑必须写在 QML 的 `onClosing` 里，Python 只提供无参槽
`core.hideToTray()` / `core.quitFromWindow()`。

本测试断言：
1. main.py 里不再有 `closing.connect(` 这种写法
2. QML 顶层窗口有 `onClosing`
3. Main.qml 的 onClosing 调用了这两个无参槽
4. core 确实暴露了这两个槽
5. 真加载 QML 并触发 close()，确认调到了 hideToTray 且不抛异常
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from guard import protect_user_data  # noqa: E402

protect_user_data()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def main():
    # ---------------------------------------------------------- 1. 源码静态检查
    print("=== 1. 源码里不再用 closing.connect 接 Python 函数 ===")
    main_py = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    # 只看**非注释**行：注释里可能会提到这个写法（用来解释为什么不能这么写）
    code_lines = [ln for ln in main_py.splitlines()
                  if not ln.lstrip().startswith("#")]
    hit = [ln for ln in code_lines if re.search(r"closing\.connect\s*\(", ln)]
    check("main.py 的可执行代码里没有 closing.connect(", not hit,
          (hit[0].strip()[:70] if hit else ""))

    qml = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    # 只看顶层 Window 区块的前 200 行，避免撞到别处的 onClosing
    head = qml[:4000]
    check("Main.qml 顶层有 onClosing", "onClosing:" in head)
    check("onClosing 里改 close.accepted", "close.accepted" in head)
    check("onClosing 调 core.hideToTray()", "core.hideToTray()" in head)
    check("onClosing 调 core.quitFromWindow()", "core.quitFromWindow()" in head)
    check("收托盘时隐藏窗口 win.hide()", "win.hide()" in head)

    # ---------------------------------------------------------- 2. core 的槽
    print("=== 2. core 暴露两个无参槽 ===")
    from app.core import Core

    for m in ("hideToTray", "quitFromWindow"):
        check(f"Core 有 {m}", hasattr(Core, m))
    # 签名必须是无参的：带参数就又可能踩参数转换的坑
    import inspect
    for m in ("hideToTray", "quitFromWindow"):
        fn = getattr(Core, m, None)
        if fn is not None:
            params = [p for p in inspect.signature(fn).parameters.values()
                      if p.name != "self"]
            check(f"{m} 无参", not params, f"参数={[p.name for p in params]}")

    # ---------------------------------------------------------- 3. 真跑一次关闭
    print("=== 3. 真加载 QML 并触发 close() ===")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine

    app = QApplication.instance() or QApplication(sys.argv[:1])
    core = Core(app)

    called = {"hide": 0}
    _orig = core.hideToTray

    def _hide():
        called["hide"] += 1
        _orig()

    core.hideToTray = _hide
    # 托盘模式：关窗只隐藏，不真退出（这样测试进程能继续跑完）
    core.config["tray_on_close"] = True

    engine = QQmlApplicationEngine()
    qml_dir = os.path.join(ROOT, "qml")
    engine.addImportPath(qml_dir)
    engine.addImportPath(os.path.join(qml_dir, "components"))
    engine.rootContext().setContextProperty("core", core)
    engine.load(os.path.join(qml_dir, "Main.qml"))
    roots = engine.rootObjects()
    check("QML 加载成功", bool(roots), f"{len(roots)} 个根")
    if not roots:
        return 1
    win = roots[0]

    state = {"closed_ok": None}

    def do_close():
        try:
            win.close()
            state["closed_ok"] = True
        except Exception as e:  # noqa: BLE001
            state["closed_ok"] = False
            print("      close() 抛异常:", type(e).__name__, e)

    def finish():
        check("close() 没抛异常", state["closed_ok"] is True)
        check("走到了 hideToTray（没静默失效）", called["hide"] == 1,
              f"调用 {called['hide']} 次")
        check("窗口已隐藏", win.property("visible") is False)
        app.quit()

    QTimer.singleShot(900, do_close)
    QTimer.singleShot(2000, finish)
    app.exec()

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())