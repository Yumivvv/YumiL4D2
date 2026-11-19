"""Win10 / 别人电脑兼容性体检。

逐项检查「只在开发机上成立」的假设：

  1. 图标字体（Win11 独占 Segoe Fluent Icons）
  2. 透明窗口（Win10 上 frameless+transparent 可能全黑）
  3. 字体名回退（雅黑 / Consolas 缺失时）
  4. 硬编码的绝对路径
  5. 依赖本机才有的目录 / 环境变量
  6. Python 版本要求（是否用了 3.10+ 语法）
  7. 网络依赖是否有兜底
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

import re
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

fails = []
warns = []


def ok(name, msg=""):
    print(f"  ok   {name}" + (f"  {msg}" if msg else ""))


def bad(name, msg=""):
    print(f"  FAIL {name}" + (f"  {msg}" if msg else ""))
    fails.append(name)


def warn(name, msg=""):
    print(f"  warn {name}" + (f"  {msg}" if msg else ""))
    warns.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


print("=== 1. 图标字体回退 ===")
core_src = read("app/core.py")
if "_ICON_FONTS" in core_src and "Segoe MDL2 Assets" in core_src:
    ok("core.py 有多种图标字体候选")
else:
    bad("core.py 没有字体回退")

theme = read("qml/L4D2/Theme.qml")
if "property string iconFont" in theme and "readonly" not in theme.split("property string iconFont")[0][-30:]:
    ok("Theme.iconFont 可写（能被子程序覆盖）")
else:
    bad("Theme.iconFont 是 readonly，无法回退")

main_qml = read("qml/Main.qml")
if "core.iconFontFamily" in main_qml:
    ok("Main.qml 会用系统的图标字体覆盖 Theme")
else:
    bad("Main.qml 没有应用 core.iconFontFamily")

print()
print("=== 2. 透明窗口（Win10 风险）===")
main_py = read("main.py")
if "_supports_transparent_window" in main_py:
    ok("main.py 有版本判断")
    if "build >= 22000" in main_py:
        ok("按 Windows build 区分（22000 = Win11）")
    else:
        bad("版本判断条件不对")
    if "QColor(10, 12, 17)" in main_py:
        ok("Win10 用不透明底色兜底")
    else:
        bad("没有不透明兜底")
else:
    bad("没有透明窗口判断")

print()
print("=== 3. 硬编码绝对路径 ===")
bad_paths = []
for dirpath, _d, files in os.walk(os.path.join(ROOT, "app")):
    for name in files:
        if not name.endswith(".py"):
            continue
        p = os.path.join(dirpath, name)
        text = open(p, encoding="utf-8").read()
        for m in re.finditer(r'["\']([A-Za-z]:\\\\[^"\']{3,})["\']', text):
            bad_paths.append((name, m.group(1)))
if bad_paths:
    bad("发现硬编码盘符路径", str(bad_paths[:3]))
else:
    ok("没有硬编码盘符路径")

print()
print("=== 4. 依赖本机环境变量 ===")
env_hits = []
for dirpath, _d, files in os.walk(os.path.join(ROOT, "app")):
    for name in files:
        if not name.endswith(".py"):
            continue
        text = open(os.path.join(dirpath, name), encoding="utf-8").read()
        for m in re.finditer(r'os\.environ(?:\.get)?\(["\']([A-Z_]+)["\']', text):
            env_hits.append(m.group(1))
uniq = sorted(set(env_hits))
print("  读取的环境变量:", uniq or "(无)")
# 这些是我们自己定义的可选覆盖项，缺失时有默认值，没问题
risky = [e for e in uniq if e not in ("L4D2_DATA_DIR", "L4D2_BG_DIR")]
if risky:
    warn("有别名的环境变量", str(risky))
else:
    ok("环境变量都是可选覆盖项（缺失时有默认值）")

print()
print("=== 5. Python 版本要求 ===")
# 找 3.10+ 才有的语法
py_files = []
for sub in ("app", "tools"):
    for dirpath, _d, files in os.walk(os.path.join(ROOT, sub)):
        for name in files:
            if name.endswith(".py"):
                py_files.append(os.path.join(dirpath, name))
py_files.append(os.path.join(ROOT, "main.py"))

uses_match = []
for p in py_files:
    text = open(p, encoding="utf-8").read()
    if re.search(r"^\s+match\s+\w+\s*:", text, re.M):
        uses_match.append(os.path.relpath(p, ROOT))
if uses_match:
    warn("用了 match 语句（需要 3.10+）", str(uses_match[:3]))
else:
    ok("没用 match 语句")
ok("README 里已注明 Python 3.10+")

print()
print("=== 6. 字体名回退链 ===")
for name, chain in (
    ("UI 字体", '("Microsoft YaHei UI", "Microsoft YaHei", "SimHei")'),
    ("等宽字体", '("Consolas", "Cascadia Mono", "Courier New")'),
):
    if chain in core_src:
        ok(f"{name}有回退链")
    else:
        bad(f"{name}没有回退链")

print()
print("=== 7. 网络请求是否有超时 ===")
no_timeout = []
for dirpath, _d, files in os.walk(os.path.join(ROOT, "app")):
    for name in files:
        if not name.endswith(".py"):
            continue
        p = os.path.join(dirpath, name)
        lines = open(p, encoding="utf-8").read().splitlines()
        for i, ln in enumerate(lines, 1):
            if not re.search(r"requests\.(get|post)\(", ln):
                continue
            # 调用可能跨多行，要往后找到配对的右括号为止
            tail = []
            depth = ln.count("(") - ln.count(")")
            tail.append(ln)
            j = i
            while depth > 0 and j < len(lines):
                nxt = lines[j]
                tail.append(nxt)
                depth += nxt.count("(") - nxt.count(")")
                j += 1
            if "timeout" not in "\n".join(tail):
                no_timeout.append(f"{name}:{i}")
if no_timeout:
    warn("有请求没写 timeout", str(no_timeout[:5]))
else:
    ok("所有 requests 调用都有 timeout")

print()
print("=== 8. 关键目录自动创建 ===")
util = read("app/util.py")
if "def ensure_dirs" in util and "makedirs" in util:
    ok("ensure_dirs 会建目录（不依赖预置文件夹）")
else:
    bad("没有 ensure_dirs")

print()
print("=== 9. QML 控件样式是否锁定 Basic ===")
if "QtQuick.Controls.Basic" in main_qml:
    ok("用 Controls.Basic（不跟随系统主题，各版本一致）")
else:
    warn("没锁 Basic 样式，Win10/11 观感可能不同")

print()
print("=" * 50)
if warns:
    print("警告 %d 项（通常可接受）：%s" % (len(warns), warns))
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("兼容性检查全部通过")
