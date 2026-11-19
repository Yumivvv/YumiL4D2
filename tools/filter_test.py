# -*- coding: utf-8 -*-
"""验证 MOD 筛选：体积区间 + 只看启用/禁用 + 重置。"""
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys, os, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtGui import QGuiApplication     # noqa: E402

app = QCoreApplication(sys.argv)

from app.modmanager import ModManager  # noqa: E402

mm = ModManager()
if not mm.addonsDir:
    mm.setAddonsDir(mm.detectDirs()[0] if mm.detectDirs() else "")
print("addonsDir =", mm.addonsDir, flush=True)

mm.scan()
for _ in range(150):
    app.processEvents()
    if mm.scanned and not mm.busy:
        break
    time.sleep(0.1)

n = mm.localCount
all_sizes = sorted(int(m["size"]) / 1048576.0 for m in (mm._all_local + mm._all_workshop))
total_all = len(mm._all_local) + len(mm._all_workshop)
print("本地 =", n, "| 云 =", mm.workshopCount, "| 合计 =", total_all, flush=True)
assert n > 0, "没扫到 MOD"

sizes = sorted(int(m["size"]) / 1048576.0 for m in mm._local.items())
print(f"体积范围 {sizes[0]:.1f} MB ~ {sizes[-1]:.1f} MB  中位 {sizes[len(sizes)//2]:.1f} MB", flush=True)

# ---- 1) 无筛选：全都在
mm.resetFilters()
print("无筛选 localCount =", mm.localCount, "hidden =", mm.hiddenCount, flush=True)
assert mm.localCount == n
assert mm.hiddenCount == 0

# ---- 2) 只看小于 1MB
mm.setSizeRange(0, 1)
expect_small = sum(1 for s in all_sizes if s <= 1)
print(f"小于 1MB: 显示 {mm.localCount} / 期望 {expect_small}", flush=True)
assert mm.localCount == expect_small, "体积上限筛选不对"
assert mm.hiddenCount == total_all - mm.localCount, "hiddenCount 应 = 总(本地+云) - 显示"

# ---- 3) 只看大于 50MB（localCount 只统计本地，期望值用本地 sizes）
mm.setSizeRange(50, 0)
expect_big = sum(1 for s in sizes if s >= 50)
print(f"大于 50MB: 显示 {mm.localCount} / 期望 {expect_big}", flush=True)
assert mm.localCount == expect_big, "体积下限筛选不对"

# ---- 4) 区间 1~50MB
mm.setSizeRange(1, 50)
expect_mid = sum(1 for s in sizes if 1 <= s <= 50)
print(f"1~50MB: 显示 {mm.localCount} / 期望 {expect_mid}", flush=True)
assert mm.localCount == expect_mid, "区间筛选不对"

# ---- 5) 上下限写反了要自动纠正
mm.setSizeRange(50, 1)
print("写反后 minMB/maxMB =", mm.minMB, mm.maxMB, flush=True)
assert mm.minMB == 1 and mm.maxMB == 50, "区间没自动换过来"
assert mm.localCount == expect_mid

# ---- 6) 状态筛选（已启用 / 未启用 / 可更新）—— totalCount 是「本地+云」合并后的数量
mm.resetFilters()
mm.setStatusFilter(1)
enabled_n = sum(1 for m in mm._all.items() if m.get("enabled", True))
print(f"只看已启用: {mm.totalCount} / 期望 {enabled_n}", flush=True)
assert mm.totalCount == enabled_n

mm.setStatusFilter(2)
disabled_n = total_all - enabled_n
print(f"只看未启用: {mm.totalCount} / 期望 {disabled_n}", flush=True)
assert mm.totalCount == disabled_n
assert all(not m.get("enabled", True) for m in mm._all.items())

mm.setStatusFilter(5)
upd_n = sum(1 for m in mm._all.items() if m.get("hasUpdate"))
print(f"只看可更新: {mm.totalCount} / 期望 {upd_n}", flush=True)
assert mm.totalCount == upd_n

# ---- 7) 状态筛选 + 名称搜索叠加
mm.setStatusFilter(2)
mm.setFilter("a")
search_n = sum(1 for m in mm._all.items()
               if not m.get("enabled", True)
               and ("a" in (m.get("title") or "").lower()
                    or "a" in (m.get("name") or "").lower()
                    or "a" in (m.get("workshopId") or "")))
print(f"只看未启用 + 搜 'a': {mm.totalCount} / 期望 {search_n}", flush=True)
assert mm.totalCount == search_n, "叠加筛选不对"

# ---- 8) resetFilters 要一次清干净
mm.resetFilters()
print("重置后 totalCount =", mm.totalCount, "minMB =", mm.minMB,
      "maxMB =", mm.maxMB, "status =", mm.statusFilter,
      "category =", repr(mm.categoryFilter), "filter =", repr(mm.filterText), flush=True)
assert mm.totalCount == total_all and mm.minMB == 0 and mm.maxMB == 0
assert mm.statusFilter == 0 and mm.categoryFilter == "" and mm.filterText == ""
assert mm.hasExtraFilter is False and mm.hiddenCount == 0

# ---- 9) 排序模式
for mode in (0, 1, 2, 3, 4):
    mm.setSortMode(mode)
    assert mm.sortMode == mode
    assert mm.localCount == n, f"排序 {mode} 改变了条数"
mm.setSortMode(99)
assert mm.sortMode == 0, "非法排序值应该归 0"
mm.setSortMode(0)

print("FILTER_OK", flush=True)
