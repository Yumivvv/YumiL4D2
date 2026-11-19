"""验证多关键词：合并、去重、不重复入库."""
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import os
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.bili import BiliClient
from app.store import Library

c = BiliClient()
keywords = ["求生之路2公开", "求生之路2替换"]

merged: dict[str, dict] = {}
per_kw: dict[str, list[str]] = {}

for kw in keywords:
    items = c.search(kw, max_pages=1)
    bvids = [i["bvid"] for i in items]
    per_kw[kw] = bvids
    print(f"「{kw}」搜到 {len(items)} 个")
    for it in items:
        bv = it["bvid"]
        if bv in merged:
            merged[bv].setdefault("_keywords", []).append(kw)
        else:
            it["_keywords"] = [kw]
            merged[bv] = it

print()
print("合并去重后总数:", len(merged))

# 交集统计
a = set(per_kw[keywords[0]])
b = set(per_kw[keywords[1]])
print(f"两个关键词都搜到的（重复的）: {len(a & b)} 个")
if a & b:
    for bv in list(a & b)[:3]:
        print("  重复:", merged[bv]["title"][:38])

# 验证入库去重
lib = Library()
before = len(lib.videos)
new = lib.merge_scan(list(merged.values()))
lib.save()
after = len(lib.videos)
print()
print(f"入库前: {before}, 入库后: {after}, 本次新增: {len(new)}")
print(f"增量 == 去重后总数 - 原有: {after - before} == {len(new)}  -> {after - before == len(new)}")

# 再入库一次，应该 0 新增
new2 = lib.merge_scan(list(merged.values()))
print("再扫一次新增（应为 0）:", len(new2))

# 检查 _keywords 合并
multi = [v for v in lib.videos.values() if len(v.get("_keywords") or []) > 1]
print("被多个关键词命中的视频:", len(multi))
for v in multi[:3]:
    print("  ", v["_keywords"], v["title"][:32])
