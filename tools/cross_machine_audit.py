"""跨机器风险体检：把「只在本机能跑」的地方都揪出来。

不是跑功能测试，而是**静态扫描 + 环境依赖检查**，
专门找那些在开发机上成立、换台电脑就崩/显示错的东西。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

issues = []
notes = []


def add(level, title, detail=""):
    (issues if level == "BAD" else notes).append((title, detail))
    print(f"  [{level}] {title}" + (f"  {detail}" if detail else ""))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


py_files = []
for sub in ("app", ""):
    base = os.path.join(ROOT, sub) if sub else ROOT
    for name in os.listdir(base):
        if name.endswith(".py"):
            py_files.append(os.path.join(base, name))

qml_files = []
for sub in ("qml", os.path.join("qml", "components"), os.path.join("qml", "L4D2")):
    base = os.path.join(ROOT, sub)
    if not os.path.isdir(base):
        continue
    for name in os.listdir(base):
        if name.endswith(".qml"):
            qml_files.append(os.path.join(base, name))

print("=== A. 依赖本机才有的东西 ===")

# A1. 图标字体
theme = read("qml/L4D2/Theme.qml")
if re.search(r'property string iconFont: *"Segoe Fluent Icons"', theme):
    add("BAD", "Theme 默认图标字体写死 Win11 的 Segoe Fluent Icons")
elif 'iconFont: "Segoe MDL2 Assets"' in theme:
    add("OK", "Theme 默认图标字体是 Win10 也有的 Segoe MDL2 Assets")
if "core.iconFontFamily" in read("qml/Main.qml"):
    add("OK", "启动时会用系统实际字体覆盖")

# A2. 透明窗口
main_py = read("main.py")
if "_supports_transparent_window" in main_py:
    add("OK", "透明窗口按 Windows build 判断（Win10 用不透明底色）")
else:
    add("BAD", "无边框窗口无条件透明，Win10 可能全黑")

# A3. 字体名
for name, pat in (("Microsoft YaHei UI", "YaHei"), ("Consolas", "Consolas")):
    if pat in read("app/core.py"):
        add("OK", f"{name} 有回退链")

print()
print("=== B. 文件路径 / 权限 ===")

# B1. 用户目录
util = read("app/util.py")
if "_user_root" in util and "sys.executable" in util:
    add("OK", "打包后用户数据放 exe 旁边（不写系统目录）")
if "Program Files" in util or "APPDATA" in util:
    add("BAD", "用户数据写到了系统目录")
else:
    add("OK", "不写 Program Files / AppData")

# B2. 中文路径
hard = []
for p in py_files:
    text = open(p, encoding="utf-8").read()
    for m in re.finditer(r'["\']([A-Za-z]:\\\\[^"\']{2,})["\']', text):
        hard.append((os.path.basename(p), m.group(1)))
if hard:
    add("BAD", "硬编码盘符路径", str(hard[:3]))
else:
    add("OK", "没有硬编码盘符路径（中文路径也能跑）")

print()
print("=== C. 网络 / 风控 ===")
bili = read("app/bili.py")
if "SPI_API" in bili and "_seed_cookies" in bili:
    add("OK", "主动领 buvid3 cookie（避免首次 412）")
else:
    add("BAD", "没领 buvid cookie，首次启动容易 412")
if "for attempt in (0, 1)" in bili:
    add("OK", "412 会自动换 cookie 重试一次")
else:
    add("BAD", "412 直接失败，没有重试")

print()
print("=== D. 封面 / 资源 ===")
mm = read("app/modmanager.py")
if "getsize(img) <= 1024" in mm:
    add("OK", "坏封面（0 字节/过小）会被当成没有，会去补")
else:
    add("BAD", "坏封面被当成有封面，永远补不上")
if "hashlib.md5" in mm and "vpkcover" in mm:
    add("OK", "封面文件名带路径哈希（同名 vpk 不会互相覆盖）")

print()
print("=== E. QML 跨版本 ===")
main_qml = read("qml/Main.qml")
if "QtQuick.Controls.Basic" in main_qml:
    add("OK", "锁定 Controls.Basic 样式（不随系统主题变）")
else:
    add("BAD", "没锁样式，Win10/11 观感不同")
# 检查有没有用 Qt5 语法（Qt6 会报错）
qt5_syntax = []
for p in qml_files:
    text = open(p, encoding="utf-8").read()
    if re.search(r"^\s*import QtQuick 2\.\d+", text, re.M):
        qt5_syntax.append(os.path.basename(p))
    if re.search(r"^\s*import QtQuick\.Controls 2\.\d+", text, re.M):
        qt5_syntax.append(os.path.basename(p) + "(Controls2.x)")
if qt5_syntax:
    add("BAD", "有 Qt5 版本号 import（Qt6 下报错）", str(qt5_syntax[:3]))
else:
    add("OK", "全部无版本号 import（Qt6 兼容）")

print()
print("=== F. 高 DPI / 缩放 ===")
if "HighDpiScaleFactorRoundingPolicy" in main_py:
    add("OK", "设置了高 DPI 舍入策略")
else:
    add("BAD", "高 DPI 未设置，别人的 125%/150% 缩放可能错位")

print()
print("=" * 50)
if notes:
    print(f"提示 {len(notes)} 项")
if issues:
    print(f"问题 {len(issues)} 项：")
    for t, d in issues:
        print("  -", t, d)
    sys.exit(1)
print("跨机器风险扫描通过，未发现问题")
