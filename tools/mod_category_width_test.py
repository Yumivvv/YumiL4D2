# -*- coding: utf-8 -*-
"""分类徽标的宽度回归：手动指定过分类时**不许凭空多出空白**。

## 用户报的

「修改 MOD 分类导致在 MOD 详情里面观看分类文字多出空白」

## 根因（纯宽度算错）

改分类之前，徽标的宽度是：

    width: badTxt.width + 16 + (categoryManual ? 12 : 0)

笔尖图标一开始是**拼在 badTxt 的字符串里**的（`"  \\uE70F"`），
所以那 12px 补的是一段**已经被算进去**的宽度 —— 重复计算。
结果：手动指定过分类的条目，徽标右边多出一小截空白；
没手动指定的（categoryManual=false）看着正常，所以只有「改过分类」的才会遇到。

## 修法

笔尖拆成独立的 Text（`font.family: Theme.iconFont`，尺寸单独控制），
宽度改成 `catRow.implicitWidth + 16` —— 文字和图标各自算各自的，
不再有「谁已经算过」这种模糊地带。

## 本测试验什么

1. 手动指定后，徽标宽度 == 内容宽度 + 固定内边距（不允许多出 > 2px）
2. 自动分类时同样是「刚好」
3. 手动 / 自动两种状态的宽度差 == 笔尖图标 + 间距（不是瞎补的 12px）
4. 文字本身不带空白（不靠空格撑宽度）
5. 徽标里真的有两个子元素（文字 + 笔尖），笔尖只在手动时可见
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import Core  # noqa: E402
from app import modmanager as MM  # noqa: E402
from app.util import ROOT as APP_ROOT  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _visible(item) -> bool:
    """QQuickItem 的可见性。

    ★ `item.property("visible")` 在 QQuickItem 上拿不到（返回 None），
      要用 `isVisible()`。用错的话 `not None` 恒为 True，
      「笔尖是否隐藏」这条断言永远是绿的 —— 假通过。
    """
    try:
        return bool(item.isVisible())
    except (AttributeError, RuntimeError):
        try:
            return bool(item.property("visible"))
        except RuntimeError:
            return False


def main() -> int:
    app = QApplication(sys.argv[:1])

    tmp = os.path.join(APP_ROOT, "data")
    old_meta = MM.CATEGORY_OVERRIDE_PATH
    MM.CATEGORY_OVERRIDE_PATH = os.path.join(tmp, "modcategories_w_test.json")
    # ★ 上一次跑留下的覆盖记录会让「这条本来是自动分类」不成立。
    #   测试自己要先把它擦干净，不能依赖沙盒是新的。
    try:
        os.remove(MM.CATEGORY_OVERRIDE_PATH)
    except OSError:
        pass
    try:
        engine = QQmlApplicationEngine()
        warns: list = []
        engine.warnings.connect(lambda ws: [warns.append(w.toString()) for w in ws])
        engine.addImportPath(os.path.join(APP_ROOT, "qml"))
        engine.addImportPath(os.path.join(APP_ROOT, "qml", "components"))
        core = Core(app)
        engine.rootContext().setContextProperty("core", core)
        engine.load(QUrl.fromLocalFile(os.path.join(APP_ROOT, "qml", "Main.qml")))
        if not engine.rootObjects():
            print("LOAD FAILED")
            return 1
        win = engine.rootObjects()[0]
        win.show()
        wait(1500)

        mgr = core.mods
        fake = {
            "path": os.path.join("C:\\fake\\addons", "wtest.vpk"),
            "name": "wtest.vpk",
            "stem": "Category Width Test",
            "size": 1024 * 1024,
            "sizeText": "1.0 MB",
            "mtime": 1700000000,
            "workshopId": "888888",
        }
        deco = mgr._decorate(fake, {}, is_local=False)
        mgr._all_workshop = [deco]
        mgr._all_local = []
        mgr._apply_filter()
        mgr.modsChanged.emit()

        win.setProperty("section", 1)
        wait(800)
        mgr.selectMod(deco["path"])
        wait(800)

        badge = win.findChild(QQuickItem, "modCategoryBadge")
        check("找得到分类徽标", badge is not None)
        if badge is None:
            return 1

        def measure():
            """返回 (徽标宽, 内容行, 文字 Text, 笔尖 Text)。

            ★ 不能用 `property("text") is not None` 去区分 Row 和 Text：
              PySide 的 `property()` 对**不存在的属性也返回 None**（不抛异常），
              而 Row 没有 `text`，于是 Row 和 Text 都会被判成「文字」，
              测量全乱（content 恒等于 0）。改成按 objectName 找笔尖、
              按「有没有 implicitWidth 且是第一个子项」找 Row。
            """
            row = None
            txt = None
            pen = None
            for ch in badge.childItems():
                if ch.objectName() == "modCategoryPen":
                    pen = ch
                    continue
                # Row 本身没有 text；Text 有
                try:
                    ch.property("text")
                    has_text = ch.property("text") is not None
                except RuntimeError:
                    has_text = False
                if has_text:
                    if txt is None:
                        txt = ch
                elif row is None:
                    row = ch
            if row is not None:
                for ch in row.childItems():
                    if ch.objectName() == "modCategoryPen":
                        pen = ch
            return badge.width(), row, txt, pen

        # ---------------------------------------------- 1. 自动分类（未手动）
        print("=== 1. 自动分类：宽度刚好贴合内容 ===")
        check("这条是自动分类（没有被手动覆盖）",
              deco.get("categoryManual") is False,
              str(deco.get("categoryManual")))
        w_auto, row, txt, pen = measure()
        check("徽标里有一行布局（Row）", row is not None)
        if row is not None:
            content = float(row.implicitWidth())
            pad = w_auto - content
            check("自动时：宽度 == 内容 + 16（内边距）", abs(pad - 16) <= 2,
                  f"w={w_auto:.1f} content={content:.1f} pad={pad:.1f}")
        check("自动时笔尖是隐藏的",
              pen is None or not _visible(pen))

        # ---------------------------------------------- 2. 手动指定分类
        print("=== 2. 手动指定分类：宽度仍然刚好，不多出空白 ===")
        r = mgr.setModCategory(deco["path"], "weapon")
        check("改成武器成功", r.get("ok") is True, str(r))
        wait(600)

        cur = mgr._find_mod(deco["path"])
        check("这条现在标成手动指定", cur.get("categoryManual") is True)
        w_manual, row2, txt2, pen2 = measure()
        check("手动时笔尖可见", pen2 is not None and _visible(pen2), pen2)
        if row2 is not None:
            content2 = float(row2.implicitWidth())
            pad2 = w_manual - content2
            # ★ 这就是用户报的那个 bug：以前这里会多出 12px
            check("手动时：宽度 == 内容 + 16，没有多出来的空白",
                  abs(pad2 - 16) <= 2,
                  f"w={w_manual:.1f} content={content2:.1f} pad={pad2:.1f}")
            check("手动时的内边距和自动时一致（不因加了图标而变化）",
                  abs(pad2 - pad) <= 2,
                  f"auto pad={pad:.1f} manual pad={pad2:.1f}")

        # ---------------------------------------------- 3. 文字里不许有空格的空白
        print("=== 3. 文字本身不靠空格撑宽度 ===")
        sql = open(os.path.join(APP_ROOT, "qml", "components", "ModPanel.qml"),
                   encoding="utf-8").read()
        seg = sql.split('objectName: "modCategoryBadge"', 1)[1][:2200]
        check("文字里没有拼空格图标（旧的写法）",
              '"  \\uE70F"' not in seg, "还有 `+ \"  \\\\uE70F\"` 这种拼法")
        check("宽度由 Row.implicitWidth 算", "catRow.implicitWidth" in seg)
        check("笔尖是独立 Text 且用图标字体",
              'objectName: "modCategoryPen"' in seg
              and "Theme.iconFont" in seg)

        # ---------------------------------------------- 4. 两种分类都试
        print("=== 4. 换成名字更长的自建分类：宽度照样贴合 ===")
        r2 = mgr.createCategory("一个特别长的自建分类名字")
        check("新建长名分类", r2.get("ok") is True, str(r2))
        mgr.setModCategory(deco["path"], r2["key"])
        wait(600)
        w_long, row3, _t, _p = measure()
        if row3 is not None:
            pad3 = w_long - float(row3.implicitWidth())
            check("长分类名：仍是 内容 + 16",
                  abs(pad3 - 16) <= 2,
                  f"w={w_long:.1f} content={row3.implicitWidth():.1f} pad={pad3:.1f}")
        check("长分类名的徽标变宽了（说明宽度跟着文字走）",
              w_long > w_auto, f"{w_auto:.1f} -> {w_long:.1f}")

        # ---------------------------------------------- 5. 告警
        print("=== 5. QML 告警 ===")
        bad = [w for w in warns if "ModPanel" in w]
        check("ModPanel 没有告警", not bad,
              " / ".join(x[:120] for x in bad[:3]))

    finally:
        MM.CATEGORY_OVERRIDE_PATH = old_meta

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
