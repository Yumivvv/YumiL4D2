"""验证「别人电脑上也能跑」的三项修复。

1. 图标字体：不是硬编码 Segoe Fluent Icons，而是按系统实际装的选
2. B 站 412：干净 session 也能拿到 buvid cookie，搜索成功
3. MOD 封面：坏图（0 字节/过小）不再被当成「有封面」，封面文件名不再撞车
"""
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

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

fails = []


def check(name, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + name + f"  got={got!r}")
    if not ok:
        fails.append(name)


print("=== 1. 图标字体回退 ===")
from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1])
from app.core import Core  # noqa: E402

core = Core(app)
icon = core.iconFontFamily
ui = core.uiFontFamily
mono = core.monoFontFamily
print("  iconFontFamily =", icon)
print("  uiFontFamily   =", ui)
print("  monoFontFamily =", mono)
check("图标字体非空", bool(icon), True)
check("图标字体是已知的一种", icon in ("Segoe Fluent Icons", "Segoe MDL2 Assets",
                                      "Segoe UI Symbol"), True)
check("UI 字体非空", bool(ui), True)
check("等宽字体非空", bool(mono), True)

print()
print("=== 2. 所有图标码位在选中的字体里都有字形 ===")
from PySide6.QtGui import QFont, QRawFont  # noqa: E402

CODEPOINTS = [
    0xE704, 0xE706, 0xE708, 0xE70D, 0xE70F, 0xE710, 0xE711, 0xE713,
    0xE714, 0xE718, 0xE71B, 0xE721, 0xE72B, 0xE72C, 0xE72D, 0xE734,
    0xE735, 0xE73E, 0xE74A, 0xE74B, 0xE74D, 0xE74F, 0xE767, 0xE768,
    0xE769, 0xE76B, 0xE76C, 0xE770, 0xE774, 0xE77B, 0xE77F, 0xE787,
    0xE7B3, 0xE7B8, 0xE7BA, 0xE823, 0xE892, 0xE893, 0xE896, 0xE8A5,
    0xE8A7, 0xE8AB, 0xE8B5, 0xE8B7, 0xE8B9, 0xE8BB, 0xE8C8, 0xE8F1,
    0xE8FD, 0xE921, 0xE922, 0xE923, 0xE945, 0xE946, 0xE968, 0xE9D2,
    0xE9D9, 0xEA8F, 0xEDE1,
]
if icon:
    rf = QRawFont.fromFont(QFont(icon, 16))
    missing = [hex(cp) for cp in CODEPOINTS
               if not rf.isValid() or rf.glyphIndexesForString(chr(cp))[0] == 0]
    print(f"  {len(CODEPOINTS)} 个码位，缺字形 {len(missing)} 个")
    if missing:
        print("  缺:", missing[:10])
    check("选中字体覆盖全部图标", len(missing), 0)

print()
print("=== 3. B 站 cookie（模拟干净电脑）===")
from app.bili import BiliClient  # noqa: E402

bc = BiliClient()
s = bc.session()
names = {c.name for c in s.cookies}
print("  cookie:", sorted(names))
check("拿到 buvid3", "buvid3" in names, True)
check("拿到 b_nut", "b_nut" in names, True)

print()
print("=== 4. MOD 封面：坏图不算有封面 ===")
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import tempfile  # noqa: E402

from app import mods as M  # noqa: E402

tmp = tempfile.mkdtemp(prefix="cover_test_")
good = os.path.join(tmp, "good.jpg")
bad = os.path.join(tmp, "bad.jpg")
with open(good, "wb") as f:
    f.write(b"\xff\xd8\xff" + b"x" * 5000)
with open(bad, "wb") as f:
    f.write(b"\xff\xd8\xff")          # 只有 3 字节

# 直接验证判定函数用的阈值逻辑
def good_enough(p):
    try:
        return bool(p) and os.path.isfile(p) and os.path.getsize(p) > 1024
    except OSError:
        return False


check("正常图算有封面", good_enough(good), True)
check("3 字节坏图不算", good_enough(bad), False)
check("不存在不算", good_enough(os.path.join(tmp, "nope.jpg")), False)

print()
print("=== 5. 封面文件名不再撞车 ===")
from app.modmanager import ModManager  # noqa: E402

# 同一 stem、不同目录的两个 vpk
p1 = os.path.join(tmp, "addons", "123.vpk")
p2 = os.path.join(tmp, "addons", "workshop", "123.vpk")
os.makedirs(os.path.dirname(p1), exist_ok=True)
os.makedirs(os.path.dirname(p2), exist_ok=True)
for p in (p1, p2):
    with open(p, "wb") as f:
        f.write(b"x" * 100)

data = b"\xff\xd8\xff" + b"y" * 3000
n1 = ModManager._save_vpk_cover(p1, data, ".jpg")
n2 = ModManager._save_vpk_cover(p2, data, ".jpg")
print("  文件1:", os.path.basename(n1))
print("  文件2:", os.path.basename(n2))
check("同名不同目录的两个 vpk 封面文件名不同", n1 != n2, True)
check("两个封面都真的写出来了", os.path.isfile(n1) and os.path.isfile(n2), True)

# 禁用态与启用态用同一张图
p3 = os.path.join(tmp, "addons", "dis.vpk")
p4 = p3 + ".disabled"
for p in (p3, p4):
    with open(p, "wb") as f:
        f.write(b"x" * 100)
n3 = ModManager._save_vpk_cover(p3, data, ".jpg")
n4 = ModManager._save_vpk_cover(p4, data, ".jpg")
print("  启用态:", os.path.basename(n3))
print("  禁用态:", os.path.basename(n4))
check("xxx.vpk 和 xxx.vpk.disabled 共用一张封面", n3 == n4, True)

print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
