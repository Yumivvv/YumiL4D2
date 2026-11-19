"""核心逻辑自检：全新库 → 首次基线 → 模拟新增 → 检测到新视频."""
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
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

# ★ 这个测试会调 lib.clear_all() —— 直接跑会把用户真实的视频库清空！
#   （真发生过：273 条被清成 42 条，只剩测试刚搜到的那一页。）
#   所以必须在 import app.* 之前把数据目录指到临时沙盒。
from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from app.bili import BiliClient  # noqa: E402
from app.store import Config, Library  # noqa: E402
from app.util import ensure_dirs  # noqa: E402

ensure_dirs()
c = BiliClient()
cfg = Config()
kw = cfg["keyword"]

items = c.search(kw, max_pages=1)
print("搜索到", len(items), "个视频")
assert items, "搜索为空"

lib = Library()
lib.clear_all()
lib.meta["first_run"] = True

# 第一次：建立基线
new1 = lib.merge_scan(items)
lib.finish_first_run()
lib.mark_all_seen()
print("首次基线新增(应被忽略):", len(new1), "-> 库里", len(lib.videos))
assert len(lib.videos) == len(items)
assert lib.new_count() == 0

# 模拟"上次没见过的老视频"：从库里删掉 3 个
victims = [v["bvid"] for v in lib.all_items()[:3]]
for b in victims:
    lib.remove(b)
print("删除后库里:", len(lib.videos))

# 第二次：应该检测到 3 个新视频
new2 = lib.merge_scan(items)
print("第二次检测到新视频:", len(new2), [x["title"][:20] for x in new2])
assert len(new2) == len(victims), f"期望 {len(victims)} 个，实际 {len(new2)}"

# 再扫一次：不应该再有新的
new3 = lib.merge_scan(items)
print("第三次检测到:", len(new3))
assert len(new3) == 0

# 已读标记
lib.mark_all_seen()
print("标记已读后 new_count:", lib.new_count())

# 详情接口
d = c.video_detail(items[0]["bvid"])
print("详情:", d["title"][:24], "| 播放", d["views"], "| 简介", len(d["desc"]), "字")

lib.save()
print("\n全部通过 ✔")
