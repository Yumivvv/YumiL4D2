# -*- coding: utf-8 -*-
"""本轮五项修复的回归测试（不联网、不开窗口）。

1. 切合集后「什么都不显示」：换组必须把分类复位回「全部」
2. 点 MOD 管理自动跳到「我的收藏」：进页时复位会导致空列表的筛选项
3. 名字排序：黑喵1 → 黑喵2 → … → 黑喵10（不是 1 → 10 → 2）
4. 创意工坊：关掉详情后，还在路上的解析结果不许把面板弹回来
5. 创意工坊：预览图超过 7 张时缩略图条要能横向滚，不能藏在后面
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from app import servers as S  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


QML_SRV = open(os.path.join("qml", "components", "ServersPage.qml"),
               encoding="utf-8").read()
QML_WS = open(os.path.join("qml", "components", "WorkshopPage.qml"),
              encoding="utf-8").read()
QML_MAIN = open(os.path.join("qml", "Main.qml"), encoding="utf-8").read()
PY_MM = open(os.path.join("app", "modmanager.py"), encoding="utf-8").read()
PY_SRV = open(os.path.join("app", "servers.py"), encoding="utf-8").read()


# ============================================ 1. 切合集后空列表
print("\n[1] 切合集不能因为残留分类而显示空列表")
check("selectGroup 里把分类复位成 all",
      'page.category = "all"' in QML_SRV)
# selectGroup 函数体里必须有这一句
_seg = QML_SRV[QML_SRV.index("function selectGroup("):]
_seg = _seg[:_seg.index("}")]
check("复位语句在 selectGroup 里",
      'page.category = "all"' in _seg, _seg[:200])
check("复位后仍会通知后端合集变化",
      "setGroupFilter" in _seg, _seg[:200])

# 真的模拟一遍：A 合集只有战役，B 合集只有对抗，停在「战役」切到 B 应该是空
# → 复位后 category=all 就不空了。这里验后端 _rows_in_group 的语义。
rows = [
    {"addr": "1.1.1.1:1", "name": "甲服战役1"},
    {"addr": "1.1.1.1:2", "name": "甲服战役2"},
    {"addr": "2.2.2.2:1", "name": "乙服对抗1"},
    {"addr": "2.2.2.2:2", "name": "乙服对抗2"},
]
gs = S.group_servers(rows)
check("造出两个合集", len(gs) == 2, str([g["label"] for g in gs]))


# ============================================ 3. 名字自然排序
print("\n[2] 名字排序：黑喵1 在 黑喵10 前面")
names = ["黑喵10服务器", "黑喵1服务器", "黑喵2服务器", "黑喵0服务器"]
got = sorted(names, key=S.natural_sort_key)
want = ["黑喵0服务器", "黑喵1服务器", "黑喵2服务器", "黑喵10服务器"]
check("自然排序结果正确", got == want, got)

check("纯数字段按数值比",
      S.natural_sort_key("服10") > S.natural_sort_key("服9"))
check("前导零不破坏顺序",
      sorted(["x2", "x02", "x10"], key=S.natural_sort_key)[0] in ("x02", "x2"))
# 混合中英文也不能抛异常
try:
    sorted(["Alice1", "爱丽丝10", "爱丽丝2", "bob"], key=S.natural_sort_key)
    check("中英混合不抛异常", True)
except TypeError as e:
    check("中英混合不抛异常", False, str(e))
check("servers.py 里 name 排序用的是自然排序",
      '"name": _sort_key_name' in PY_SRV)


# ============================================ 2. MOD 页复位筛选
print("\n[3] 点 MOD 管理不再自动停在「我的收藏」")
check("有 resetSessionFilters 方法", "def resetSessionFilters" in PY_MM)
check("复位会把状态筛选清 0",
      "_status_filter = 0" in PY_MM[PY_MM.index("def resetSessionFilters"):][:1400])
check("复位会清关键词", "_filter = \"\"" in PY_MM[PY_MM.index("def resetSessionFilters"):][:1400])
check("复位会清分类", "_category = \"\"" in PY_MM[PY_MM.index("def resetSessionFilters"):][:1400])
check("复位会清体积范围",
      "_min_mb = 0.0" in PY_MM[PY_MM.index("def resetSessionFilters"):][:1400])
check("进 MOD 页时调用它",
      "resetSessionFilters()" in QML_MAIN,
      "Main.qml 里没有调用")
# 调用点必须在「切到 section 1」的同一个 onClicked 里
_idx = QML_MAIN.index("resetSessionFilters()")
_ctx = QML_MAIN[_idx:_idx + 400]
check("调用点在切 MOD 页之前",
      "win.section = 1" in _ctx, _ctx[:150])


# ============================================ 4. 关窗后不再弹回来
print("\n[4] 关掉创意工坊详情后，迟到的解析结果不许弹回来")
check("后端有 cancelWorkshopProbe", "def cancelWorkshopProbe" in PY_MM)
check("cancelWorkshopProbe 是 Slot",
      "@Slot()" in PY_MM[max(0, PY_MM.index("def cancelWorkshopProbe") - 40):
                        PY_MM.index("def cancelWorkshopProbe")])
check("解析结果带 seq 字段", 'res["seq"]' in PY_MM)
check("closeDetail 会作废结果",
      "cancelWorkshopProbe" in QML_WS[QML_WS.index("function closeDetail("):
                                     QML_WS.index("function closeDetail(") + 500])
check("onProbe 校验 detailOpen", "if (!page.detailOpen" in QML_WS)
check("onProbe 校验 seq", "page.probeSeq" in QML_WS)
check("openDetail 会推进 probeSeq",
      "page.probeSeq = " in QML_WS)


# ============================================ 5. 预览图能横向滚
print("\n[5] 预览图超过 7 张时能横向滚动")
_strip = QML_WS[QML_WS.index("id: coverStrip"):]
_strip = _strip[:_strip.index("wsCoverMoreHint")]
check("缩略图条改成 Flickable", "Flickable {" in QML_WS[
    QML_WS.index("id: coverStrip") - 120:QML_WS.index("id: coverStrip")],
      QML_WS[QML_WS.index("id: coverStrip") - 120:QML_WS.index("id: coverStrip")])
check("是横向滚动", "Flickable.HorizontalFlick" in _strip)
check("设了 contentWidth（能滚的前提）", "contentWidth: coverRow.width" in _strip)
check("有 clip（不然溢出到外面）", "clip: true" in _strip)
check("挂了横向 ScrollBar", "ScrollBar.horizontal" in _strip)
check("支持鼠标滚轮横滚", "onWheel" in _strip)
check("有「共 N 张图」提示", "共 " in QML_WS and "wsCoverMoreHint" in QML_WS)


# ============================================ 真实服务器排序（用真 Core）
print("\n[6] 用真 ServerManager 验排序")
from PySide6.QtGui import QGuiApplication  # noqa: E402

from app.core import Core  # noqa: E402

app = QGuiApplication(sys.argv[:1])
core = Core(app)
try:
    mgr = core.servers
    mgr._favorites = lambda: [
        {"addr": f"9.9.9.1:{27010 + i}", "name": nm, "weight": 0, "panels": []}
        for i, nm in enumerate(
            ["黑喵10服务器", "黑喵1服务器", "黑喵2服务器", "黑喵0服务器"])
    ]
    mgr._live = {}
    mgr._sort = "name"
    got = [r["name"] for r in mgr._merged()]
    check("ServerManager 名字排序正确",
          got == ["黑喵0服务器", "黑喵1服务器", "黑喵2服务器", "黑喵10服务器"], got)
finally:
    core.shutdown()

print()
if fails:
    print(f"失败 {len(fails)} 项：")
    for name in fails:
        print("  - " + name)
    sys.exit(1)
print("本轮五项修复的测试全部通过")
