# -*- coding: utf-8 -*-
"""盘点重复代码：为「统一/简化」提供依据，别凭感觉删。

只看**明确可量化的重复**：
  1. 同一个字符串/判断在多个文件里重复出现（文案不统一）
  2. 同一个小函数被复制到多处
  3. QML 里重复的组件块

输出是「候选清单」，人工判断后再合并 —— 不做自动改写。
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {"build", "dist", "__pycache__", ".git", "assets",
             "backgrounds", "sounds", "downloads", "docs", "data"}


def iter_files(exts: tuple[str, ...]):
    for dirpath, dirnames, names in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for n in names:
            if n.endswith(exts):
                yield os.path.join(dirpath, n)


def norm(rel: str) -> str:
    return rel.replace(os.sep, "/")


# ---------------------------------------------------------------- 1. 文案重复
def duplicate_literals() -> None:
    print("=" * 70)
    print("1. 重复的用户可见文案（同一句话散落在多处）")
    print("=" * 70)
    pat = re.compile(r'["\']([\u4e00-\u9fff][^"\']{5,40})["\']')
    hits: dict[str, set] = defaultdict(set)
    for p in iter_files((".py",)):
        rel = norm(os.path.relpath(p, ROOT))
        if rel.startswith("tools/"):
            continue
        src = open(p, encoding="utf-8", errors="replace").read()
        for m in pat.finditer(src):
            s = m.group(1).strip()
            if len(s) >= 6 and not s.startswith(("http", "%", "{")):
                hits[s].add(rel)
    rows = [(s, fs) for s, fs in hits.items() if len(fs) >= 2]
    rows.sort(key=lambda x: (-len(x[1]), x[0]))
    for s, fs in rows[:25]:
        print(f"  [{len(fs)} 处] {s!r}")
        print(f"        {', '.join(sorted(fs))}")
    if not rows:
        print("  （没有跨文件重复的文案）")
    print()


# ---------------------------------------------------------------- 2. 函数重复
def duplicate_functions() -> None:
    print("=" * 70)
    print("2. 同名函数出现在多个文件（可能是复制粘贴）")
    print("=" * 70)
    pat = re.compile(r"^(?:    )?def (\w+)\s*\(", re.M)
    where: dict[str, set] = defaultdict(set)
    for p in iter_files((".py",)):
        rel = norm(os.path.relpath(p, ROOT))
        if rel.startswith("tools/"):
            continue
        src = open(p, encoding="utf-8", errors="replace").read()
        for m in pat.finditer(src):
            where[m.group(1)].add(rel)
    # 过滤掉明显的测试/dunder/通用小工具
    skip = {"__init__", "__str__", "__repr__", "setUp", "tearDown"}
    rows = [(n, fs) for n, fs in where.items()
            if len(fs) >= 2 and n not in skip and not n.startswith("__")]
    rows.sort(key=lambda x: (-len(x[1]), x[0]))
    for n, fs in rows[:30]:
        print(f"  {n:32s} {', '.join(sorted(fs))}")
    print()


# ---------------------------------------------------------------- 3. QML 重复
def duplicate_qml_blocks() -> None:
    print("=" * 70)
    print("3. QML 里重复出现的「胶囊 / 角标 / 圆角按钮」样式块")
    print("=" * 70)
    # 统计常见的样式属性组合出现次数，看是否该抽成组件
    sigs = Counter()
    for p in iter_files((".qml",)):
        rel = norm(os.path.relpath(p, ROOT))
        src = open(p, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"radius:\s*(\w+\.\w+|\d+)\s*\n", src):
            sigs[(rel, m.group(1))] += 1
    # 按 radius 值汇总
    by_radius = Counter()
    for (rel, r), n in sigs.items():
        by_radius[r] += n
    print("  radius 取值分布（同一取值越多、越说明该统一成 Theme 常量）：")
    for r, n in by_radius.most_common(12):
        print(f"    radius: {r:22s} 共 {n} 处")
    print()
    # Theme 里已有的 radius 常量
    theme = open(os.path.join(ROOT, "qml", "L4D2", "Theme.qml"),
                 encoding="utf-8").read()
    consts = re.findall(r"readonly property (?:int|real) (radius\w*):\s*([\d.]+)",
                        theme)
    print("  Theme.qml 里已定义的圆角常量：")
    for name, val in consts:
        print(f"    {name} = {val}")
    print("  → 上面那些裸数字如果和常量值一样，应该改用常量。")


# ---------------------------------------------------------------- 4. 到期文案
def expiry_wording() -> None:
    print("=" * 70)
    print("4. 「到期」相关文案/判断出现的位置（用户报的不一致）")
    print("=" * 70)
    words = ("今天到期", "天后到期", "已过期", "已失效", "永久有效", "到期")
    for p in iter_files((".py", ".qml")):
        rel = norm(os.path.relpath(p, ROOT))
        if rel.startswith("tools/"):
            continue
        src = open(p, encoding="utf-8", errors="replace").read()
        for i, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("#", "//")):
                continue
            for w in words:
                if w in stripped:
                    print(f"  {rel}:{i}  {stripped[:90]}")
                    break
    print()


def main() -> int:
    duplicate_literals()
    duplicate_functions()
    duplicate_qml_blocks()
    expiry_wording()
    return 0


if __name__ == "__main__":
    sys.exit(main())
