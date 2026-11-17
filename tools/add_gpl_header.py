"""给所有源文件头部加 GPL-3.0 版权声明。

为什么需要：GNU 官方 FAQ 明确建议「每个源文件都应带上版权与许可证声明」，
否则别人单独拷走一个文件时，无法确认它是什么许可（
https://www.gnu.org/licenses/gpl-faq.zh-cn.html#NoticeInSourceFile ）。

这个脚本可以重复运行（已经是声明开头的会跳过），也可以加 --dry 只看会改哪些文件。

用法（在项目根目录执行）：
    python tools/add_gpl_header.py --dry     # 只看
    python tools/add_gpl_header.py           # 真改

注意：它会改动全部 .py / .qml 文件。项目不是 git 仓库，所以**先备份**。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NOTICE = """Yumi的L4D2工具箱
Copyright (C) 2026 ZengDeRong

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

MARK = "Yumi的L4D2工具箱"

# 只处理「自己写的」源码；dist/build/tools 里的临时脚本和第三方不动
TARGET_DIRS = ("app", "qml")
SKIP_PREFIX = (
    os.path.join(ROOT, "dist"),
    os.path.join(ROOT, "build"),
    os.path.join(ROOT, "tools"),
    os.path.join(ROOT, "__pycache__"),
)


def py_header() -> str:
    # ★ 只能作为**注释**插到最前面，不能当 docstring：
    #   `from __future__ import annotations` 必须位于文件第一条语句
    #   （docstring 之后都不行），否则 `SyntaxError: from __future__ imports
    #   must occur at the beginning of the file`。
    #   第一次跑就踩了这个坑，把 19 个 py 文件全弄坏了 —— 用注释最稳。
    return "# " + NOTICE.replace("\n", "\n# ").rstrip("# ").rstrip() + "\n\n"


def qml_header() -> str:
    return "// " + NOTICE.replace("\n", "\n// ").rstrip("/ ").rstrip() + "\n\n"


def iter_targets():
    for sub in TARGET_DIRS:
        base = os.path.join(ROOT, sub)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            if any(os.path.abspath(dirpath).startswith(p) for p in SKIP_PREFIX):
                continue
            for name in filenames:
                if name.endswith((".py", ".qml")):
                    yield os.path.join(dirpath, name)


def main(argv: list[str]) -> int:
    dry = "--dry" in argv
    changed = skipped = 0
    for path in sorted(iter_targets()):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            print(f"  读不了 {path}: {e}")
            continue
        if MARK in text[:1600]:
            skipped += 1
            continue
        header = py_header() if path.endswith(".py") else qml_header()
        # 保留 shebang / coding 声明在**最前面**（Python 要求），其余正文接在注释块后
        prefix = ""
        rest = text
        if path.endswith(".py"):
            lines = text.splitlines(keepends=True)
            keep = 0
            for ln in lines[:2]:
                s = ln.strip()
                if s.startswith("#!") or (s.startswith("#") and "coding" in s):
                    prefix += ln
                    keep += 1
                else:
                    break
            if keep:
                rest = "".join(lines[keep:])
        new = prefix + header + rest.lstrip("\n")
        rel = os.path.relpath(path, ROOT)
        if dry:
            print(f"  会改 {rel}")
        else:
            try:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
                print(f"  已改 {rel}")
            except OSError as e:
                print(f"  写不了 {rel}: {e}")
                continue
        changed += 1
    print(f"\n{'将修改' if dry else '已修改'} {changed} 个文件，跳过 {skipped} 个（已有声明）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
