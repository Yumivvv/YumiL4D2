"""本地数据兼容测试：跑一遍关键词搜索，落到真实 library.json."""
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
from app.store import Config, Library
from app.util import ensure_dirs

ensure_dirs()
cfg = Config()
lib = Library()
c = BiliClient()

print("keyword:", cfg["keyword"])
items = c.search(cfg["keyword"], max_pages=1)
print("got:", len(items))
if items:
    print("first:", items[0]["title"], "|", items[0]["pubdate"])
    print("cover:", items[0]["cover"])
    p = c.download_cover(items[0]["cover"], items[0]["bvid"])
    print("cover cached:", p, os.path.exists(p) if p else False)
    d = c.video_detail(items[0]["bvid"])
    print("detail title:", d["title"])
    print("desc:", (d["desc"] or "")[:120].replace("\n", " "))
    print("stats:", d["views"], d["danmaku"], d["reply"])
    new = lib.merge_scan(items)
    lib.meta["first_run"] = False
    lib.save()
    print("merged new:", len(new), "total:", len(lib.videos))
