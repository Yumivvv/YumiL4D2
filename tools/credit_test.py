# -*- coding: utf-8 -*-
"""验证「设置 → 关于 → 致谢」区块：文案来源、界面元素、点击行为。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from guard import protect_user_data  # noqa: E402

protect_user_data()

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem

    app = QApplication(sys.argv[:1])

    # ---------------------------------------------------------- 1. 后端文案
    print("=== 1. core 里的致谢文案 ===")
    from app.core import Core

    import inspect
    src = inspect.getsource(Core)
    check("定义 CREDIT_NAME = LytVPK", 'CREDIT_NAME = "LytVPK"' in src)
    check("定义 CREDIT_AUTHOR = LaoYutang", 'CREDIT_AUTHOR = "LaoYutang"' in src)
    check("定义 CREDIT_HOMEPAGE",
          'CREDIT_HOMEPAGE = "https://github.com/LaoYutang/lytvpk"' in src)
    for m in ("creditName", "creditAuthor", "creditHomepage",
              "creditHomepageText", "creditText", "creditScope",
              "openCreditPage", "copyCredit"):
        check(f"有 {m}", hasattr(Core, m))

    # ---------------------------------------------------------- 2. 界面元素
    print("=== 2. 设置页「关于」里的致谢区块 ===")
    from app.core import Core as C2
    core = C2(app)

    engine = QQmlApplicationEngine()
    qml_dir = os.path.join(ROOT, "qml")
    engine.addImportPath(qml_dir)
    engine.addImportPath(os.path.join(qml_dir, "components"))
    engine.rootContext().setContextProperty("core", core)
    qml = os.path.join(qml_dir, "Main.qml")
    engine.load(QUrl.fromLocalFile(qml))
    roots = engine.rootObjects()
    check("QML 加载成功", bool(roots), f"{len(roots)} 个根对象")
    if not roots:
        return 1
    win = roots[0]

    from PySide6.QtQuick import QQuickItem

    box = win.findChild(QQuickItem, "creditBox")
    check("找到致谢区块 creditBox", box is not None)
    if box is None:
        return 1

    txt = win.findChild(QQuickItem, "creditTextLabel")
    scope = win.findChild(QQuickItem, "creditScopeLabel")
    link = win.findChild(QQuickItem, "creditLink")
    btn = win.findChild(QQuickItem, "creditCopyBtn")

    check("找到致谢正文", txt is not None)
    check("找到参考范围说明", scope is not None)
    check("找到项目链接行", link is not None)
    check("找到复制按钮", btn is not None)

    if txt is not None:
        body = str(txt.property("text") or "")
        check("正文含 LytVPK", "LytVPK" in body, body[:50])
        check("正文含作者 LaoYutang", "LaoYutang" in body, body[:50])
        check("正文含「致谢」", "致谢" in body)
    if scope is not None:
        s = str(scope.property("text") or "")
        check("范围含「工坊浏览」", "工坊浏览" in s)
        check("范围含「加载顺序」", "加载顺序" in s)
        check("范围含「独立实现」", "独立实现" in s)

    # ---------------------------------------------------------- 3. 文案来自 core（不是硬编码）
    print("=== 3. 文案来自 core.credit*（QML 里不写死）===")
    qml_src = open(qml, encoding="utf-8").read()
    seg = qml_src[qml_src.find('objectName: "creditBox"'):]
    seg = seg[:seg.find("GPL-3.0")] if "GPL-3.0" in seg else seg[:4000]
    check("QML 用 core.creditText", "core.creditText" in seg)
    check("QML 用 core.creditScope", "core.creditScope" in seg)
    check("QML 用 core.creditName", "core.creditName" in seg)
    check("QML 点击走 core.openCreditPage", "core.openCreditPage()" in seg)
    check("QML 复制走 core.copyCredit", "core.copyCredit()" in seg)
    check("QML 里没硬编码 lytvpk 地址", "LaoYutang/lytvpk" not in seg)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")

    # 收尾：Core 一构造就会起后台扫描线程，解释器退出时它还活着的话，
    # 会和已经销毁的 model 撞上（打印一堆 RuntimeError，看着像失败）。
    # 这里主动让它停掉再退，输出才干净。
    try:
        if hasattr(core, "mods") and core.mods is not None:
            core.mods.shutdown()
    except Exception:  # noqa: BLE001
        pass
    del engine
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())