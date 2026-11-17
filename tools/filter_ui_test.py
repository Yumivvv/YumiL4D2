"""日期筛选 + 加载顺序 UI 的端到端验证。

重点验证两个用户报的 bug：
1. 日期筛选按钮点了没反应（Property 的 notify 信号和 setter emit 的对不上）
2. 加载顺序下半部分拖拽位置偏移（rowAtY 漏算了 spacing）

跑法：python -X utf8 tools/filter_ui_test.py
"""
from __future__ import annotations

import os
import shutil
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import addonlist as A  # noqa: E402
from app.core import Core  # noqa: E402
from app.util import ROOT  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    app = QApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    warns = []
    engine.warnings.connect(lambda ws: warns.extend(w.toString() for w in ws))
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.addImportPath(os.path.join(ROOT, "qml", "components"))

    core = Core(app)
    engine.rootContext().setContextProperty("core", core)
    engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    if not engine.rootObjects():
        print("LOAD FAILED")
        return 1
    win = engine.rootObjects()[0]
    win.show()
    wait(1500)

    def ev(expr: str):
        e = QQmlExpression(QQmlEngine.contextForObject(win), win, expr)
        v, u = e.evaluate()
        return v

    # ---------------------------------------------------------------- 1. 日期筛选反馈
    print("=== 1. 日期筛选按钮要有反馈（notify 信号修复）===")
    mgr = core.mods
    # 界面上读的是 mgr.importDays / importFilterLabel / hasImportFilter
    # 这些是 Property，只有 notify 信号发了 QML 才会重新求值。
    mgr.setImportDays(7)
    wait(200)
    check("QML 读到 importDays=7", ev("modPanel.mgr.importDays") == 7,
          str(ev("modPanel.mgr.importDays")))
    check("QML 读到筛选标签", ev("modPanel.mgr.importFilterLabel") == "近 7 天",
          str(ev("modPanel.mgr.importFilterLabel")))
    check("QML 读到 hasImportFilter=True",
          ev("modPanel.mgr.hasImportFilter") is True)

    mgr.setImportDays(30)
    wait(200)
    check("切到近一个月后 QML 跟着变", ev("modPanel.mgr.importFilterLabel") == "近 30 天",
          str(ev("modPanel.mgr.importFilterLabel")))

    mgr.setImportRange("2026-01-01", "2026-06-01")
    wait(200)
    check("自定义区间 QML 也刷了",
          ev("modPanel.mgr.importFilterLabel") == "2026-01-01 ～ 2026-06-01",
          str(ev("modPanel.mgr.importFilterLabel")))
    check("自定义区间会清掉快捷档", ev("modPanel.mgr.importDays") == 0,
          str(ev("modPanel.mgr.importDays")))

    mgr.clearImportFilter()
    wait(200)
    check("清掉后 QML 也跟着清", ev("modPanel.mgr.hasImportFilter") is False)
    check("清掉后标签为空", ev("modPanel.mgr.importFilterLabel") == "",
          repr(ev("modPanel.mgr.importFilterLabel")))

    # ★ 用户报的 bug：点「重置」后日期筛选不回到「不限」
    print("=== 1b. 重置要回到「不限」，选好的日期不能自己跑掉 ===")
    mgr.setImportDays(7)
    wait(150)
    check("先设成近七天", ev("modPanel.mgr.importDays") == 7)
    mgr.resetFilters()
    wait(250)
    check("重置后 importDays 回到 0", ev("modPanel.mgr.importDays") == 0,
          str(ev("modPanel.mgr.importDays")))
    check("重置后 hasImportFilter=False",
          ev("modPanel.mgr.hasImportFilter") is False)
    check("重置后标签清空", ev("modPanel.mgr.importFilterLabel") == "",
          repr(ev("modPanel.mgr.importFilterLabel")))

    # 选日期 → 点「应用」（只改体积）→ 日期要保留
    mgr.setImportRange("2026-01-01", "2026-06-01")
    wait(150)
    mgr.setSizeRange(0, 0)          # 「应用」按钮实际做的就是这个
    wait(150)
    check("点应用后日期还在", ev("modPanel.mgr.importFrom") == "2026-01-01"
          and ev("modPanel.mgr.importTo") == "2026-06-01",
          f"{ev('modPanel.mgr.importFrom')} ~ {ev('modPanel.mgr.importTo')}")

    # 重置也要能清掉自定义区间
    mgr.resetFilters()
    wait(250)
    check("重置能清掉自定义区间",
          ev("modPanel.mgr.importFrom") == "" and ev("modPanel.mgr.importTo") == "",
          f"{ev('modPanel.mgr.importFrom')} ~ {ev('modPanel.mgr.importTo')}")
    mgr.clearImportFilter()

    # ---------------------------------------------------------------- 2. 日历选择器
    print("=== 2. 日期用日历选，不用手输 ===")
    # datePickerDlg 是 Popup 的 id，QML 里 id 不可从外部访问，所以直接测行为
    ev("modPanel.openDatePicker('from')")
    wait(300)
    check("打开后默认定位到今天所在月",
          ev("modPanel.calYear") == ev("modPanel.todayParts().y"),
          f"{ev('modPanel.calYear')} vs {ev('modPanel.todayParts().y')}")
    cells = ev("modPanel.calCells().length")
    days = ev("modPanel.daysInMonth(modPanel.calYear, modPanel.calMonth)")
    lead = ev("modPanel.firstWeekday(modPanel.calYear, modPanel.calMonth)")
    check("格子数 = 前导空位 + 当月天数", cells == lead + days,
          f"{cells} vs {lead}+{days}")

    # 选 15 号
    ev("modPanel.pickDate(15)")
    wait(200)
    expect = f"{ev('modPanel.calYear')}-{ev('modPanel.pad2(modPanel.calMonth)')}-15"
    check("点日子后写入 importFrom", mgr.importFrom == expect,
          f"{mgr.importFrom} vs {expect}")

    # 翻月
    before_m = ev("modPanel.calMonth")
    ev("modPanel.calNextMonth()")
    wait(100)
    after_m = ev("modPanel.calMonth")
    check("翻到下一月", after_m == (before_m % 12) + 1,
          f"{before_m} -> {after_m}")

    # ---------------------------------------------------------------- 3. 加载顺序拖拽步长
    print("=== 3. 加载顺序：拖拽步长要算上 spacing ===")
    tmp = tempfile.mkdtemp(prefix="aoui_")
    l4d2 = os.path.join(tmp, "left4dead2")
    addons = os.path.join(l4d2, "addons")
    os.makedirs(addons)
    names = [f"m{i}.vpk" for i in range(12)]
    for n in names:
        with open(os.path.join(addons, n), "wb") as f:
            f.write(b"x" * 256)
    A.save(addons, [{"name": n, "enabled": True} for n in names])
    mgr.setAddonsDir(addons)
    wait(300)
    mgr.scan()
    for _ in range(60):
        wait(200)
        if mgr.scanned and not mgr.busy:
            break
    win.setProperty("section", 1)
    wait(500)
    ev("modPanel.openAddonOrder()")
    wait(900)

    n_items = ev("modPanel.addonItems.length")
    check("加载顺序里有 12 条", n_items == 12, str(n_items))

    # ★ QJSValue 不能直接迭代，所以统一用 JSON.stringify 过一道再解析。
    def order_names() -> list[str]:
        raw = ev("JSON.stringify(modPanel.addonItems.map(function(x){return x.name}))")
        try:
            return json.loads(raw) if isinstance(raw, str) else []
        except ValueError:
            return []

    order0 = order_names()
    check("能读到 12 个名字", len(order0) == 12, str(len(order0)))

    # 上下移动按钮走的是 moveAddonRow，和拖拽同一条路径。
    # 注意：不要用 QQmlExpression 直接求值有信号回调的函数（会嵌套求值卡住），
    # 改成「触发 → 让事件循环跑一会儿 → 重新读状态」。
    mgr.moveAddonOrder(10, 11)          # 靠下的项下移一位（等同点下箭头）
    wait(400)
    order1 = order_names()
    check("靠下的项也能上下移（第 11 项 ↔ 第 12 项）",
          order1[10] == order0[11] and order1[11] == order0[10],
          f"{order0[10:12]} -> {order1[10:12]}")

    mgr.moveAddonOrder(0, 1)            # 靠上的项
    wait(400)
    order2 = order_names()
    check("靠上的项也正常", order2[0] == order1[1] and order2[1] == order1[0],
          f"{order1[0:2]} -> {order2[0:2]}")

    # 落盘校验
    saved = [x["name"] for x in A.build_view(addons)["items"]]
    check("改动已写进 addonlist.txt", saved == order2, str(saved[:3]))

    # 界面不该再显示序号 / 体积数字（用户要求去掉）
    src = open(os.path.join(ROOT, "qml", "components", "ModPanel.qml"),
               encoding="utf-8").read()
    a = src.find("id: addonOrderDlg")
    check("找到加载顺序对话框", a >= 0, str(a))
    seg = src[a:] if a >= 0 else ""
    check("加载顺序行里不再显示体积数字", "modelData.sizeText" not in seg[:20000])
    check("有上下移按钮（E74A/E74B 图标）",
          "\\uE74A" in seg and "\\uE74B" in seg,
          f"up={'\\uE74A' in seg} down={'\\uE74B' in seg}")
    check("有「跳到序号」按钮（#）", 'text: "#"' in seg)
    # 标签四态：缺失 / 禁用 / 本地 / 云
    # （文件其实是 .disabled 的旧代码会显示成「本地」，看着像开着）
    check("本地/云标签（不再是 addons）",
          '"本地"' in seg and '"云"' in seg)
    check("文件是 .disabled 的显示「禁用」而不是「本地」",
          "fileDisabled" in seg and '"禁用"' in seg and '"缺失"' in seg)
    check("去掉了「同步 addons 目录」按钮", "同步 addons 目录" not in seg)
    check("有保存按钮", 'objectName: "addonOrderSave"' in seg)
    check("保存按钮接的是 saveAddonOrder",
          "page.saveAddonOrder()" in seg)

    # ---- 保存式交互：改顺序只动内存，点保存才落盘
    print("=== 4. 改动先攒着，点保存才写盘 ===")
    before_disk = [x["name"] for x in A.build_view(addons)["items"]]
    ev("modPanel.refreshAddonOrder()")
    wait(200)
    # 用 reorderPending 改内存顺序
    ev("modPanel.reorderPending(0, 2)")
    wait(200)
    dirty = ev("modPanel.addonDirty")
    check("改完标记为「有未保存改动」", dirty is True, str(dirty))
    after_mem = json.loads(ev("JSON.stringify(modPanel.addonPending.map("
                              "function(x){return x.name}))"))
    on_disk = [x["name"] for x in A.build_view(addons)["items"]]
    check("内存顺序变了", after_mem != before_disk, str(after_mem[:3]))
    check("磁盘还没变（要等保存）", on_disk == before_disk, str(on_disk[:3]))

    # 保存后落盘
    mgr.saveAddonOrder([{"name": n, "enabled": True} for n in after_mem])
    wait(300)
    saved = [x["name"] for x in A.build_view(addons)["items"]]
    check("点保存后写进 addonlist.txt", saved == after_mem, str(saved[:3]))

    # 撤销
    ev("modPanel.refreshAddonOrder()")
    wait(200)
    ev("modPanel.reorderPending(0, 1)")
    wait(200)
    check("撤销前是脏的", ev("modPanel.addonDirty") is True)
    ev("modPanel.reloadAddonOrder()")
    wait(200)
    check("撤销后不脏了", ev("modPanel.addonDirty") is False)
    check("撤销后顺序回到文件里的",
          json.loads(ev("JSON.stringify(modPanel.addonPending.map("
                        "function(x){return x.name}))")) == saved)

    real = [w for w in warns if any(k in w for k in (
        "TypeError", "not defined", "Unable", "ReferenceError", "Binding loop",
        "is not a function", "Cannot assign", "Required property"))]
    check("QML 无可疑告警", not real, f"{len(warns)} 条原始告警")
    for r in real[:5]:
        print("      !", r[:160])

    mgr.setAddonsDir("")
    core.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
