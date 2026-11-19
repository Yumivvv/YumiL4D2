"""服务器分组：名字前缀 + 同 IP 两种归类。

用户要的场景：
  · 「天域1服 / 天域2服 / 天域·对抗」→ 归到「天域」一个合集
  · 同一台机器上 27015~27025 一堆端口（名字各不相同）→ 按 IP 归组
  · 快速定位要玩的那台
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from app.servers import (  # noqa: E402
    name_prefix,
    server_group,
    group_servers,
)

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


print("=== 1. 名字前缀切分 ===")
cases = [
    ("天域1服", "天域"),
    ("天域2服", "天域"),
    ("天域·对抗 2", "天域"),
    ("【天域】3号线", "天域"),
    ("天域-生存", "天域"),
    ("4人纯净写实专家 1服", "4人纯净写实专家"),
    ("药抗小分队", "药抗小分队"),
    ("宿舍服", "宿舍服"),
    # 太通用 / 太短 → 不分组
    ("服务器", ""),
    ("模式1", ""),
    ("My Server", ""),
    ("", ""),
]
for raw, want in cases:
    got = name_prefix(raw)
    check(f"「{raw}」→ 「{want}」", got == want, f"拿到 {got!r}")

print()
print("=== 2. 同 IP **不再**成组（只按名字分组）===")
# 名字前缀不同，但 IP 一样 —— 应该按 IP 归到一组
rows_ip = [
    {"addr": "1.70.33.241:27015", "name": "4人纯净写实专家 1服"},
    {"addr": "1.70.33.241:27016", "name": "某人的特殊服"},
]
groups_ip = group_servers(rows_ip)
print("  得到分组:")
for g in groups_ip:
    print(f"    {g['label']!r}  {g['count']} 台  {g['addrs']}")
check("同 IP 但名字不同 → 不成组", len(groups_ip) == 0, str(groups_ip))

print()
print("=== 3. group_servers 汇总 ===")
rows = [
    {"addr": "1.1.1.1:27015", "name": "天域1服"},
    {"addr": "1.1.1.1:27016", "name": "天域2服"},
    {"addr": "1.1.1.1:27017", "name": "天域·对抗"},
    {"addr": "2.2.2.2:27015", "name": "药抗小分队"},
    {"addr": "2.2.2.2:27016", "name": "药抗小分队2"},
    {"addr": "3.3.3.3:27015", "name": "宿舍服"},          # 单独一台，不该成组
    {"addr": "9.9.9.9:27015", "name": ""},
]
groups = group_servers(rows)
print("  得到分组:")
for g in groups:
    print(f"    {g['label']!r}  {g['count']} 台  {g['addrs']}")
labels = {g["label"]: g for g in groups}
check("「天域」成组，3 台", labels.get("天域", {}).get("count") == 3)
check("「药抗」成组，2 台",
      any(g["count"] == 2 and "药抗" in g["label"] for g in groups),
      str([(g["label"], g["count"]) for g in groups]))
check("只有一台的「宿舍服」不出现在分组里",
      all("宿舍" not in g["label"] for g in groups))
check("没有名字的也不会凭空成组",
      all(g["count"] >= 2 for g in groups))

print()
print("=== 4. 边界 ===")
check("空列表 → 空分组", group_servers([]) == [])
check("单台 → 不分组", group_servers([{"addr": "1.1.1.1:1", "name": "天域"}]) == [])
check("没有 addr 的行被跳过",
      group_servers([{"name": "天域"}, {"name": "天域2"}]) == [])

print()
print("=== 5. kind 字段（区分名字组 / IP 组）===")
gs = group_servers([
    {"addr": "1.1.1.1:27015", "name": "天域1服"},
    {"addr": "1.1.1.1:27016", "name": "天域2服"},
    {"addr": "2.2.2.2:27015", "name": "甲"},
    {"addr": "2.2.2.2:27016", "name": "乙"},
])
kinds = {g["label"]: g.get("kind") for g in gs}
print("  kinds =", kinds)
check("天域是 name 组", kinds.get("天域") == "name", str(kinds))
check("不再有 ip 组", "2.2.2.2" not in kinds, str(kinds))

print()
print("=== 6. QML 侧：独立合集选择器（非折叠）===")
qml = open("qml/components/ServersPage.qml", encoding="utf-8").read()
check("有 srvGroupRail 选择器", 'objectName: "srvGroupRail"' in qml)
check("没有折叠用的 __groupHead", "__groupHead" not in qml)
check("没有 expandGroup", "function expandGroup" not in qml)
check("有 selectGroup", "function selectGroup" in qml)
check("有 filterByGroup", "function filterByGroup" in qml)

print()
print('=== 7. 分类能选（category 必须有默认值） ===')
# 用户报过「服务器分类无法选了」：category 属性被误删后 page.category 是
# undefined，分类条里一个都不高亮、点了也没反应（QML 不会报错）。
check('声明了 property string category', 'property string category' in qml)
check('默认值是 all', 'property string category: "all"' in qml)
check('分类条按 category 高亮', 'page.category === modelData.key' in qml)

print()
print('=== 8. 延迟/时间贴卡片右侧 ===')
check('信号行在 bigInfo 里（不是左侧列）',
      qml.find('id: signalPart') > qml.find('id: bigInfo'))
check('信号行用 x 撑到右边', 'x: parent.width - width' in qml)

print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
