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
print("=== 2. 同 IP 不同名字 → 归成一个合集 ===")
# 用户报的正是这个：同一台机器 27016~27022，名字里的「模式」不一样，
# 以前被拆成「一个名字合集 + 几条未分类」，现在必须整台机器一个合集。
rows_ip = [
    {"addr": "1.70.33.241:27015", "name": "4人纯净写实专家 1服"},
    {"addr": "1.70.33.241:27016", "name": "某人的特殊服"},
]
groups_ip = group_servers(rows_ip)
print("  得到分组:")
for g in groups_ip:
    print(f"    {g['label']!r}  {g['count']} 台  kind={g['kind']}  {g['addrs']}")
check("同 IP 名字不同 → 也要成组", len(groups_ip) == 1, str(groups_ip))
check("台数是 2", groups_ip and groups_ip[0]["count"] == 2, str(groups_ip))
check("组名退回用 IP", groups_ip and groups_ip[0]["label"] == "1.70.33.241",
      str(groups_ip))
check("kind 是 ip", groups_ip and groups_ip[0]["kind"] == "ip", str(groups_ip))

print()
print("=== 2b. 真实场景：1.70.33.241:27015~27022（模式不同，同一台机器）===")
# 用户的原话：「1.70.33.241:27016 到 27022 都有 IP，为什么这两个没分类进去，
#              这其实也算在里面因为 IP 一样，然后就模式不一样而已，
#              应该都搞成一个分类里面」
real = [
    {"addr": "1.70.33.241:27015", "name": ""},
    {"addr": "1.70.33.241:27016", "name": "4人纯净写实专家多特 2服"},
    {"addr": "1.70.33.241:27017", "name": "4人纯净写实专家多特 3服"},
    {"addr": "1.70.33.241:27018", "name": "4人纯净写实专家多特 4服"},
    {"addr": "1.70.33.241:27019", "name": "4人纯净写实专家多特 5服"},
    {"addr": "1.70.33.241:27020", "name": "4人纯净写实专家多特 6服"},
    {"addr": "1.70.33.241:27021", "name": "4人纯净战役 7服"},
    {"addr": "1.70.33.241:27022", "name": "4人绝境求生 8服"},
]
real_groups = group_servers(real)
print("  得到分组:")
for g in real_groups:
    print(f"    {g['label']!r}  {g['count']} 台  kind={g['kind']}  host={g['host']!r}")
check("8 台全在一个合集里", len(real_groups) == 1, str(real_groups))
check("合集是 8 台", real_groups and real_groups[0]["count"] == 8, str(real_groups))
check("组名取「台数最多的前缀」",
      real_groups and real_groups[0]["label"] == "4人纯净写实专家",
      str(real_groups))
check("标出同 IP", real_groups and real_groups[0]["host"] == "1.70.33.241",
      str(real_groups))
check("没有一台掉进未分类", sum(g["count"] for g in real_groups) == 8)

print()
print("=== 2c. 两条依据是并集（不能各算各的）===")
# 同一台机器：5 台同前缀 + 2 台名字完全不同。
# 分开算会变成「一个名字合集(5) + 2 条未分类」，用户要的是 1 个合集。
mixed = [
    {"addr": "5.5.5.5:27015", "name": "天域1服"},
    {"addr": "5.5.5.5:27016", "name": "天域2服"},
    {"addr": "5.5.5.5:27017", "name": "天域3服"},
    {"addr": "5.5.5.5:27018", "name": "完全不相干甲"},
    {"addr": "5.5.5.5:27019", "name": "完全不相干乙"},
]
mg = group_servers(mixed)
print("  得到分组:", [(g["label"], g["count"]) for g in mg])
check("同机器上的两批合成一个合集", len(mg) == 1, str(mg))
check("是 5 台", mg and mg[0]["count"] == 5, str(mg))
check("组名取台数多的前缀", mg and mg[0]["label"] == "天域", str(mg))

# 反过来：不同机器但同前缀 → 仍然按名字归一组
cross = [
    {"addr": "6.6.6.6:27015", "name": "天域1服"},
    {"addr": "7.7.7.7:27015", "name": "天域2服"},
]
cg = group_servers(cross)
print("  得到分组:", [(g["label"], g["count"], g["host"]) for g in cg])
check("跨机器同前缀 → 一个合集", len(cg) == 1 and cg[0]["count"] == 2, str(cg))
check("跨机器的组不标同 IP", cg and cg[0]["host"] == "", str(cg))

# 传递合并：A、B 同 IP，B、C 同前缀 → 三台并成一组
chain = [
    {"addr": "8.8.8.1:27015", "name": "甲组1服"},
    {"addr": "8.8.8.1:27016", "name": "乙组1服"},
    {"addr": "8.8.8.2:27015", "name": "乙组2服"},
]
chg = group_servers(chain)
print("  得到分组:", [(g["label"], g["count"]) for g in chg])
check("通过 IP 和前缀传递合并成 1 组", len(chg) == 1 and chg[0]["count"] == 3, str(chg))

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
check("同 IP 但只有 1 台 → 不分组",
      group_servers([{"addr": "4.4.4.4:27015", "name": "独苗"}]) == [])

print()
print("=== 5. kind / host 字段（界面靠它标「同 IP」）===")
gs = group_servers([
    {"addr": "1.1.1.1:27015", "name": "天域1服"},
    {"addr": "1.1.1.1:27016", "name": "天域2服"},
    {"addr": "2.2.2.2:27015", "name": "甲"},
    {"addr": "2.2.2.2:27016", "name": "乙"},
])
kinds = {g["label"]: g.get("kind") for g in gs}
print("  kinds =", kinds)
check("天域是 name 组", kinds.get("天域") == "name", str(kinds))
check("甲/乙 是 ip 组（名字对不上，靠 IP）", kinds.get("2.2.2.2") == "ip", str(kinds))
hosts = {g["label"]: g.get("host") for g in gs}
check("两组都在同一台机器上 → 都标 host",
      hosts.get("天域") == "1.1.1.1" and hosts.get("2.2.2.2") == "2.2.2.2",
      str(hosts))

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
