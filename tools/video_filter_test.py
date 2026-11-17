"""验证视频日期筛选与排序。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

app = QCoreApplication(sys.argv)

from app.core import Core

core = Core(app)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# 等启动扫描完成
for _ in range(80):
    wait(250)
    if core.model.rowCount() > 0:
        break

# 确保「只看新的」不干扰测试（库里可能没有新视频了）
core.setShowOnlyNew(False)
wait(200)

total = core.model.rowCount()
print("total videos:", total)

core.setDateFilter(1); wait(120); n1 = core.shownCount
core.setDateFilter(7); wait(120); n7 = core.shownCount
core.setDateFilter(180); wait(120); n180 = core.shownCount
core.setDateFilter(0); wait(120); n0 = core.shownCount
print("date 0/1/7/180 ->", n0, n1, n7, n180)
assert n0 == total
assert n1 <= n7 <= n180 <= n0

core.setSortMode("views"); wait(120)
print("sort views:", core.sortMode)
core.setSortMode("pubdate"); wait(120)
print("sort pubdate:", core.sortMode)

# 看最近一天的样本时间
if n1 > 0:
    import datetime
    import time as _t
    recs = core.library.all_items()
    now = _t.time()
    recent = [v for v in recs if int(v.get("pubdate") or 0) >= now - 86400]
    print("recent-1d from library:", len(recent), "== shown:", n1)

core.shutdown()
print("VIDEO_FILTER_OK")
