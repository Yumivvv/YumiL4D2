"""把 QML 里写死的深色值换成 Theme 里跟着明暗走的语义色。

只替换那些「一眼就是深色主题专用」的颜色，类似 `#12161F`、`#0B0E14`、
`#1A2029`、`#161B25`；以及 `Qt.rgba(1, 1, 1, a)` 这种提亮叠层
（浅色主题下必须换成压暗，否则控件糊成白块）。

压在图片上的东西（`#ffffff` 白字、`#E8EBF2`）**不动** —— 它们放在封面图上，
不跟主题走。

跑法：python -X utf8 tools/qml_darken.py [--apply]
不带 --apply 只打印将要改什么。
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 写死的深色 → Theme 语义色
DARK_MAP = {
    "#12161F": "Theme.panel",
    "#0B0E14": "Theme.panelDeep",
    "#1A2029": "Theme.panelHi",
    "#161B25": "Theme.surfaceHi",
    "#141822": "Theme.surface",
    "#0A0C11": "Theme.bg",
    "#0E1118": "Theme.bgAlt",
    "#10141C": "Theme.surfaceSoft",
    "#05070A": "Theme.bg",       # 播放器黑底单独处理，这里只兜底
}

# 只在「卡片/按钮的叠层」上下文里替换的 rgba 白
SCRIM_RE = re.compile(r"Qt\.rgba\(1,\s*1,\s*1,\s*([0-9.]+)\)")

# 这些行的 rgba 白是压在图片上的高光，不换
KEEP_HINTS = ("heroOverlay", "heroText")


# 播放器遮罩始终是深色的（视频画面旁边铺白色很刺眼），不参与换色
SKIP_FILES = {"PlayerOverlay.qml"}


def process(path: str, apply: bool) -> int:
    if os.path.basename(path) in SKIP_FILES:
        return 0
    text = io.open(path, encoding="utf-8").read()
    orig = text
    changes: list[str] = []

    for hexv, repl in DARK_MAP.items():
        # 只替换完整的带引号字面量
        pat = '"' + hexv + '"'
        if pat in text:
            n = text.count(pat)
            text = text.replace(pat, repl)
            changes.append(f"{pat} → {repl}  x{n}")

    def scrim_sub(m: re.Match) -> str:
        amount = m.group(1)
        return f"Theme.scrim({amount})"

    if SCRIM_RE.search(text):
        n = len(SCRIM_RE.findall(text))
        text = SCRIM_RE.sub(scrim_sub, text)
        changes.append(f"Qt.rgba(1,1,1,a) → Theme.scrim(a)  x{n}")

    if text != orig:
        name = os.path.basename(path)
        print(f"=== {name} ===")
        for c in changes:
            print("   ", c)
        if apply:
            io.open(path, "w", encoding="utf-8").write(text)
        return 1
    return 0


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    total = 0
    for name in sorted(os.listdir(os.path.join(ROOT, "qml", "components"))):
        if not name.endswith(".qml"):
            continue
        total += process(os.path.join(ROOT, "qml", "components", name), apply)
    total += process(os.path.join(ROOT, "qml", "Main.qml"), apply)
    print()
    print(("已应用" if apply else "预览（加 --apply 才会写）") + f"，涉及 {total} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
