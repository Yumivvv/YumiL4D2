"""文档体检：README 保持精简，技术长文在 docs/DEVELOPMENT.md。

README 现在只放简介 / 安装 / 使用 / 致谢，篇幅要可控；
原来的逐条实现说明已整体迁到 docs/DEVELOPMENT.md，那份继续做内容完整性检查。
"""
import os
import re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
readme = os.path.join(ROOT, "README.md")
devdoc = os.path.join(ROOT, "docs", "DEVELOPMENT.md")

text = open(readme, encoding="utf-8").read()
dev = open(devdoc, encoding="utf-8").read()

fence = "`" * 3
for name, body in (("README.md", text), ("docs/DEVELOPMENT.md", dev)):
    n = body.count(fence)
    print(f"{name} 代码块数: {n} 偶数? {n % 2 == 0}")
    assert n % 2 == 0, f"{name} 代码块没配对"

for name, body in (("README.md", text), ("docs/DEVELOPMENT.md", dev)):
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if len(p.strip()) > 60]
    dups = {k: v for k, v in Counter(paras).items() if v > 1}
    print(f"{name} 重复段落: {len(dups)}")
    assert not dups, f"{name} 里有重复段落"

# ---- README 要精简 ----
n_lines = len(text.splitlines())
n_kb = len(text.encode("utf-8")) / 1024
print(f"\nREADME 篇幅: {n_lines} 行 / {n_kb:.1f} KB")
assert n_lines < 200, f"README 太长了（{n_lines} 行），技术细节请放 docs/DEVELOPMENT.md"

# ---- README 必须有的东西 ----
need_readme = [
    "Yumi的L4D2工具箱",
    # 三块功能
    "视频监控", "MOD 管理器", "服务器",
    # 致谢（issue #1 的要求）
    "致谢", "LytVPK", "LaoYutang", "lytvpk",
    "issue #1",
    "工坊浏览", "加载顺序", "更新检查", "CDN 优选",
    "工坊 DNS", "兜底 IP",
    "独立实现",
    # 安装 / 使用
    "快速开始", "启动.cmd", "打包成独立 exe", "98–99 MB",
    "系统要求", "Python 3.10+",
    "快捷键", "常见问题",
    # 指向长文
    "docs/DEVELOPMENT.md",
    # 隐私与许可
    "数据与隐私", "Steam API Key", "GPL-3.0",
]
for s in need_readme:
    assert s in text, f"README 缺少：{s}"
    print("  ok:", s)

# ---- 不该再出现的旧说法 ----
stale = [
    "项目自带的中转站",
    "项目自带中转站",
    "可以照做",
]
for s in stale:
    assert s not in text, f"README 里还有旧说法：{s}"

# ---- 技术长文该在的东西（抽查关键项，确保没在拆分中丢内容）----
need_dev = [
    "一、视频监控", "二、MOD 管理器", "缓存与空间",
    "addonlist", "GBK", "VPK 内部解析", "addoninfo.txt",
    "工坊 DNS", "网络加速", "SNI", "QueryFiles",
    "file_url", "direct_file_url", "COLLECT_FAST_LIMIT",
    "A2S", "steam://connect/", "DPAPI",
    "蓝奏云", "acw_sc__v2", "X-FORWARDED-FOR",
    "_BUILTIN_MAPS", "onefile_paths_test", "Qt6WebEngineCore.dll",
    "USER_ROOT", "_MEIPASS", "SPECPATH",
    "常见问题", "跑测试",
]
missing = [s for s in need_dev if s not in dev]
assert not missing, f"docs/DEVELOPMENT.md 缺内容：{missing}"
print(f"\ndocs/DEVELOPMENT.md 关键内容齐全（{len(need_dev)} 项抽查通过）")

print("\n文档体检通过")
