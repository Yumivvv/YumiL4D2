# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys, os
sys.path.insert(0, ".")
from app.mods import find_l4d2_dirs, scan_mods, workshop_id_of

dirs = find_l4d2_dirs()
print("找到的 addons 目录:")
for d in dirs:
    print("  ", d)

if dirs:
    addons = dirs[0]
    res = scan_mods(addons)
    print()
    print("本地 mod:", len(res["local"]))
    print("云  mod:", len(res["workshop"]))
    print()
    print("--- 云 mod 样例 ---")
    for m in res["workshop"][:4]:
        print(f"  {m['name']:28s} size={m['sizeText']:>9s} wid={m['workshopId'] or '-':>12s} img={'有' if m['image'] else '无'}")
    print()
    print("--- 本地 mod 样例 ---")
    for m in res["local"][:4]:
        print(f"  {m['name'][:34]:36s} size={m['sizeText']:>9s} wid={m['workshopId'] or '-':>12s} img={'有' if m['image'] else '无'}")

print()
print("ID 识别测试:")
for n in ["132381280.vpk", "469986973.vpk", "ninya小猫替换三个盒子.vpk", "abc123.vpk", "123.vpk"]:
    print(f"  {n:34s} -> {workshop_id_of(n) or '(非工坊)'}")
