# -*- coding: utf-8 -*-
"""本轮五项修复的回归测试（不联网、不开窗口）。

1. 详情里提取到网盘链接 → 按设置自动三连（默认关、开着提示、每视频只一次）
2. 服务器扫描导入：带方括号前缀的名字（【黑喵0】/【黑喵】）必须归进同一个合集
3. 合集与分类一致：切合集后分类条的数字跟着变，不能再出现「有数字但点进去空」
4. 手动修改合集名：自动识别不出来时用户可以自己命名
5. 分类与模式一致：卡片写着战役，分类就不能落到「其他」
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from app import servers as S  # noqa: E402
from app.core import Core  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


# ============================================ 2. 方括号前缀归组
print("\n[1] 带方括号前缀的名字要归进同一个合集")
check("【黑喵0】多人多特 → 黑喵",
      S.name_prefix("【黑喵0】多人多特") == "黑喵",
      S.name_prefix("【黑喵0】多人多特"))
check("【黑喵】多人战役#0 → 黑喵",
      S.name_prefix("【黑喵】多人战役#0") == "黑喵",
      S.name_prefix("【黑喵】多人战役#0"))
check("【天域】3号线 仍 → 天域",
      S.name_prefix("【天域】3号线") == "天域",
      S.name_prefix("【天域】3号线"))
check("地区码【CN】不当组名",
      S.name_prefix("【CN】服务器") == "", S.name_prefix("【CN】服务器"))

rows = [
    {"addr": "1.1.1.1:27015", "name": "【黑喵0】多人多特"},
    {"addr": "2.2.2.2:27015", "name": "【黑喵】多人战役#0"},
]
gs = S.group_servers(rows)
check("两台带前缀的服合成一个合集", len(gs) == 1, str(gs))
check("合名叫「黑喵」", gs and gs[0]["label"] == "黑喵", str(gs))
check("合集包含两台", gs and gs[0]["count"] == 2, str(gs))


# ============================================ 4. 手动改合集名
print("\n[2] 手动修改合集名")
gs = S.group_servers(rows, {"1.1.1.1:27015": "黑喵服群"})
check("手动名优先于自动识别",
      gs and gs[0]["label"] == "黑喵服群", str(gs))
check("kind 标成 manual", gs and gs[0]["kind"] == "manual", str(gs))
check("key 用 m: 前缀", gs and gs[0]["key"].startswith("m:"), str(gs))
# 只给组里一台命名，整组都要用这个名字
gs = S.group_servers(rows, {"2.2.2.2:27015": "另一台命的名"})
check("组里任一平台手动名整组生效",
      gs and gs[0]["label"] == "另一台命的名", str(gs))
# 空 override 不影响
gs = S.group_servers(rows, {})
check("没有手动名时保持自动结果",
      gs and gs[0]["label"] == "黑喵", str(gs))


# ============================================ 5. 分类与模式一致
print("\n[3] 分类要和模式对得上（战役服不能落到「其他」）")
check("mode=coop 映射到 coop 分类",
      S.category_key_for_mode("coop") == "coop")
check("mode=versus 映射到 versus",
      S.category_key_for_mode("versus") == "versus")
check("mode=realismversus 映射到 realismversus",
      S.category_key_for_mode("realismversus") == "realismversus")
check("未知 mode 返回空串", S.category_key_for_mode("") == "")
check("未知 mode 码返回空串",
      S.category_key_for_mode("whatever") == "")
check("名字能判出来时仍以名字为准（战役）",
      S.server_category("14人纯净战役 7服") == "coop",
      S.server_category("14人纯净战役 7服"))


# ============================================ 3. 合集与分类一致
print("\n[4] 切合集后分类条的数字要跟着变")
from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1])
core = Core(app)
try:
    mgr = core.servers
    # 造两台「战役」+ 两台「对抗」，分属两个不同前缀（不同 IP）
    mgr._favorites = lambda: [
        {"addr": "9.9.9.1:27015", "name": "甲服战役1", "weight": 0, "panels": []},
        {"addr": "9.9.9.1:27016", "name": "甲服战役2", "weight": 0, "panels": []},
        {"addr": "9.9.9.2:27015", "name": "乙服对抗1", "weight": 0, "panels": []},
        {"addr": "9.9.9.2:27016", "name": "乙服对抗2", "weight": 0, "panels": []},
    ]
    mgr._live = {}
    mgr._group_key = "all"
    cats_all = mgr.categories
    total_all = sum(c["count"] for c in cats_all if c["key"] != "all")
    check("全部合集下分类总数 = 4", total_all == 4, str(cats_all))

    gs = mgr.groups
    # 取「甲服」那个合集
    target = None
    for g in gs:
        if "甲服" in g["label"]:
            target = g
            break
    check("找得到「甲服」合集", target is not None,
          str([g["label"] for g in gs]))
    if target:
        mgr.setGroupFilter(target["key"])
        cats_one = mgr.categories
        total_one = sum(c["count"] for c in cats_one if c["key"] != "all")
        check("切到该合集后分类总数变成 2", total_one == 2,
              str(cats_one))
        check("分类里只剩「战役」类",
              all(c["key"] in ("all", "coop") for c in cats_one),
              str(cats_one))
        # 关键断言：分类条上的数字必须和列表里真实台数一致
        rows_in = mgr._rows_in_group(mgr._merged(), target["key"])
        check("分类数字之和 == 该合集里的台数",
              total_one == len(rows_in), f"{total_one} vs {len(rows_in)}")

    # 不存在的合集 key → 当「全部」，不能给出空列表
    mgr.setGroupFilter("n:不存在的合集")
    rows_bad = mgr._rows_in_group(mgr._merged(), "n:不存在的合集")
    check("合集 key 失效时退回全部（不显示空列表）",
          len(rows_bad) == 4, len(rows_bad))
finally:
    core.shutdown()


# ============================================ 1. 自动三连
print("\n[5] 提取到网盘链接时自动三连")
core = Core(app)
try:
    check("默认关闭", core.biliAutoTripleOnLink is False,
          str(core.biliAutoTripleOnLink))
    check("配置里有 bili_auto_triple_on_link 键",
          "bili_auto_triple_on_link" in core.config.data)

    # 没开开关：即使有链接也不动作
    calls = []
    core.biliTriple = lambda bvid: (calls.append(bvid), {"ok": True, "done": ["点赞"]})[1]
    core.maybeAutoTriple("BV1", [{"url": "https://pan.baidu.com/x"}])
    check("开关关着时不三连", not calls, str(calls))

    # 打开开关 + 已登录 → 自动三连一次
    core.config["bili_auto_triple_on_link"] = True
    core.client.set_credentials("s", "j", "999")
    core.maybeAutoTriple("BV1", [{"url": "https://pan.baidu.com/x"}])
    check("开着且已登录会三连一次", calls == ["BV1"], str(calls))

    # 同一个视频只自动一次
    calls.clear()
    core.maybeAutoTriple("BV1", [{"url": "https://pan.baidu.com/x"}])
    check("同一个视频不重复三连", not calls, str(calls))

    # 没有链接 → 不动作
    calls.clear()
    core.maybeAutoTriple("BV2", [])
    check("没有网盘链接时不三连", not calls, str(calls))

    # 没登录 → 跳过（不弹错）
    calls.clear()
    core.biliLogout()
    core.maybeAutoTriple("BV3", [{"url": "https://pan.baidu.com/x"}])
    check("没登录时静默跳过", not calls, str(calls))

    # 开关切换会提示
    msgs = []
    core.toastRequested.connect(lambda t, l: msgs.append((t, l)))
    core.setBiliAutoTripleOnLink(True)
    check("打开开关时给了提示", bool(msgs), str(msgs))
    check("提示里说清会自动点赞/投币/收藏",
          any("自动" in m[0] for m in msgs), str(msgs))
    check("提示用 warn 级别（不是普通 info）",
          any(m[1] == "warn" for m in msgs), str(msgs))
    core.setBiliAutoTripleOnLink(False)
    check("关掉后配置为 False",
          core.config["bili_auto_triple_on_link"] is False)
finally:
    core.config["bili_auto_triple_on_link"] = False
    core.shutdown()

print()
if fails:
    print(f"失败 {len(fails)} 项：")
    for name in fails:
        print("  - " + name)
    sys.exit(1)
print("本轮五项修复的测试全部通过")
