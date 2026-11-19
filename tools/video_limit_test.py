"""视频库上限：50 / 100 / 200 / 500 / 1000 / 不限。

规则：
  · 0 = 不限，什么都不删
  · 超出上限时按发布时间**从旧到新**删
  · 「未读」（is_new=True）优先保留 —— 还没来得及看的不该被自动清掉
  · 改完设置**立刻**裁剪，不用等下次扫描
"""
import os
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1])

from app.store import Library  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


def make(n, base_ts=None):
    """造 n 条视频，pubdate 递增（越大越新）。"""
    lib = Library()
    lib.videos = {}
    now = int(time.time())
    for i in range(n):
        bvid = f"BV{i:04d}"
        lib.videos[bvid] = {
            "bvid": bvid,
            "title": f"视频{i}",
            "pubdate": now - (n - i) * 3600,
            "is_new": False,
            "discovered_at": now - (n - i) * 3600,
        }
    return lib


print("=== 1. 不限（0）不删 ===")
lib = make(30)
removed = lib.trim(0)
check("limit=0 不删任何东西", removed == [] and len(lib.videos) == 30,
      f"removed={len(removed)} left={len(lib.videos)}")

print()
print("=== 2. 未超上限不删 ===")
lib = make(10)
removed = lib.trim(50)
check("10 条 < 上限 50 → 不删", removed == [] and len(lib.videos) == 10)

print()
print("=== 3. 超出按「最旧」删 ===")
lib = make(60)
removed = lib.trim(50)
check("60 条 + 上限 50 → 删 10 条", len(removed) == 10, str(len(removed)))
check("剩下 50 条", len(lib.videos) == 50, str(len(lib.videos)))
# 删掉的应该是 pubdate 最小的 10 个（BV0000..BV0009）
expected = [f"BV{i:04d}" for i in range(10)]
check("删的是最旧的 10 条", sorted(removed) == expected, str(sorted(removed)[:12]))

print()
print("=== 4. 未读的优先保留 ===")
lib = make(12)
# 把最旧的 3 条标记成「未读」
for i in range(3):
    lib.videos[f"BV{i:04d}"]["is_new"] = True
removed = lib.trim(10)
check("12 条 + 上限 10 → 删 2 条", len(removed) == 2, str(len(removed)))
kept_unread = [b for b in ("BV0000", "BV0001", "BV0002") if b in lib.videos]
check("3 条未读全都保留下来了", len(kept_unread) == 3, str(kept_unread))
# 被删的应该是没被标记的、较旧的那些（BV0003、BV0004）
check("删的是次旧的非未读条目",
      sorted(removed) == ["BV0003", "BV0004"], str(sorted(removed)))

print()
print("=== 5. 各档上限都能用 ===")
for limit in (50, 100, 200, 500, 1000):
    lib = make(limit + 7)
    r = lib.trim(limit)
    check(f"上限 {limit}：删 7 条剩 {limit}",
          len(r) == 7 and len(lib.videos) == limit,
          f"removed={len(r)} left={len(lib.videos)}")

print()
print("=== 6. 配置项与 Core 接口 ===")
core_src = open("app/core.py", encoding="utf-8").read()
store_src = open("app/store.py", encoding="utf-8").read()
check("store 有 video_limit 默认值", '"video_limit": 0' in store_src)
check("Core 有 videoLimit 属性", "def videoLimit" in core_src)
check("Core 有 setVideoLimit", "def setVideoLimit" in core_src)
check("Core 有 _trim_library", "def _trim_library" in core_src)
check("六档都在 VIDEO_LIMITS 里",
      "VIDEO_LIMITS = (50, 100, 200, 500, 1000, 0)" in core_src)

print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
