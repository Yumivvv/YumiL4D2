"""通知自检：发一条真实的 Windows Toast."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.notifier import Notifier, send_toast

ok, msg = send_toast(
    "求生之路2公开 · 新视频 2 个",
    ["【求生之路2】昔涟 MOD 公开", "白辰の花散里 · 1 小时前", "…还有 1 个，打开软件查看"],
)
print("toast:", ok, msg)

n = Notifier()
n.notify("测试通知", ["这条是通过 Notifier 发的"])
import time
time.sleep(4)
print("done")
