# -*- coding: utf-8 -*-
"""致谢区块：确保「技术参考 LytVPK（作者 LaoYutang）」在设置→关于里能看到、能点开。

## 设计取舍（v1.0.2 起）

原先这里铺了一大段「参考范围」（工坊浏览 / 加载顺序 / 更新检查 / CDN 优选 /
DNS / 兜底 IP 表……），把关于卡片撑得老长。用户反馈「看着别扭」，
所以收成**一句话**：只说明技术参考了谁，细节留在 README 的「致谢」一节。

本测试因此只断言「一句话版本」该有的东西：
1. core 仍提供 creditName / creditAuthor / creditHomepage / openCreditPage
2. QML 里那一行由 core 拼出来（不硬编码项目名/地址）
3. 真加载 QML，确认 creditBox 存在、文字含 LytVPK 与 LaoYutang、点击走 openCreditPage
4. 界面**不再**展示参考范围（creditScope）
"""
import os
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
    # ---------------------------------------------------------- 1. 后端
    print("=== 1. core 里的致谢信息 ===")
    from app.core import Core
    import inspect

    src = inspect.getsource(Core)
    check("CREDIT_NAME = LytVPK", 'CREDIT_NAME = "LytVPK"' in src)
    check("CREDIT_AUTHOR = LaoYutang", 'CREDIT_AUTHOR = "LaoYutang"' in src)
    check("CREDIT_HOMEPAGE 指向 GitHub",
          'CREDIT_HOMEPAGE = "https://github.com/LaoYutang/lytvpk"' in src)
    for m in ("creditName", "creditAuthor", "creditHomepage",
              "creditHomepageText", "creditText", "creditScope",
              "openCreditPage", "copyCredit"):
        check(f"有 {m}", hasattr(Core, m))

    # ---------------------------------------------------------- 2. 真加载 QML
    print("=== 2. 设置 → 关于 里的致谢 ===")
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem

    app = QApplication.instance() or QApplication(sys.argv[:1])
    core = Core(app)

    engine = QQmlApplicationEngine()
    qml_dir = os.path.join(ROOT, "qml")
    engine.addImportPath(qml_dir)
    engine.addImportPath(os.path.join(qml_dir, "components"))
    engine.rootContext().setContextProperty("core", core)
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
    roots = engine.rootObjects()
    check("QML 加载成功", bool(roots), f"{len(roots)} 个根对象")
    if not roots:
        return 1
    win = roots[0]

    box = win.findChild(QQuickItem, "creditBox")
    check("找到致谢区块 creditBox", box is not None)
    label = win.findChild(QQuickItem, "creditTextLabel")
    check("找到致谢文字 creditTextLabel", label is not None)

    if label is not None:
        body = str(label.property("text") or "")
        print(f"      文字: {body!r}")
        check("文字含项目名 LytVPK", "LytVPK" in body)
        check("文字含作者 LaoYutang", "LaoYutang" in body)
        check("文字说明是「技术参考」", "技术参考" in body)

    # ---------------------------------------------------------- 3. QML 侧
    print("=== 3. 文案来自 core，不硬编码 ===")
    qml = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    i = qml.find('objectName: "creditBox"')
    seg = qml[max(0, i - 200):i + 3200] if i > 0 else ""
    check("用 core.creditName", "core.creditName" in seg)
    check("用 core.creditAuthor", "core.creditAuthor" in seg)
    check("点击走 core.openCreditPage()", "core.openCreditPage()" in seg)
    check("QML 里没硬编码 LaoYutang/lytvpk", "LaoYutang/lytvpk" not in seg)

    # ---------------------------------------------------------- 4. 精简验证
    print("=== 4. 已精简（不再铺参考范围）===")
    check("QML 不再引用 core.creditScope", "core.creditScope" not in qml)
    check("core 仍保留 creditScope 供 README 用", hasattr(Core, "creditScope"))

    # 三个操作按钮应该在同一行（重排后的紧凑布局）
    j1 = qml.find('objectName: "copyHomepageBtn"')
    j3 = qml.find('objectName: "checkUpdateBtn"')
    check("三个按钮存在", j1 > 0 and j3 > j1)
    if j1 > 0 and j3 > j1:
        between = qml[j1:j3]
        check("三按钮之间没有新 Row（同一行）", between.count("Row {") == 0,
              f"{between.count('Row {')} 个 Row")

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")

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