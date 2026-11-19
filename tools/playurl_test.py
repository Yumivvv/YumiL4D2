# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys
sys.path.insert(0, ".")
from app.bili import BiliClient
c = BiliClient()
bv = "BV1QBWX68ENB"
r = c.session().get("https://api.bilibili.com/x/player/pagelist", params={"bvid": bv},
                    headers={"Referer": f"https://www.bilibili.com/video/{bv}"}, timeout=15)
cid = r.json()["data"][0]["cid"]

for fnval, label in ((1, "MP4/DURL"), (16, "DASH")):
    r = c.session().get("https://api.bilibili.com/x/player/playurl",
        params={"bvid": bv, "cid": cid, "qn": 64, "fnval": fnval, "fourk": 0},
        headers={"Referer": f"https://www.bilibili.com/video/{bv}"}, timeout=15)
    j = r.json()
    d = j.get("data") or {}
    print(f"=== {label} code={j.get('code')} quality={d.get('quality')} format={d.get('format')}")
    if d.get("durl"):
        for u in d["durl"]:
            print("   size:", u.get("size"), "url:", u["url"][:100])
    if label == "MP4/DURL":
        print("   accept:", d.get("accept_description"))
        print("   timelength:", d.get("timelength"))
