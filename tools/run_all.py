"""跑全量回归，并且**不碰用户真实数据**。

为什么需要它：
大部分测试会构造真的 `Core()`，而 `Core` 一启动就会读/写
`data/config.json`、`data/library.json`、`data/modimports.json`。
以前一批跑完，用户自己调好的主题色、背景图透明度、播放器音量、
导入日期台账就会被测试值覆盖掉（真发生过）。

所以这里在开跑前把 `data/` 里那几个文件整体备份，跑完（无论成败）再还原。

跑法：
    python -X utf8 tools/run_all.py            # 全部
    python -X utf8 tools/run_all.py bg_test    # 只跑指定的几个
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TOOLS = os.path.join(ROOT, "tools")

# 这些文件会被测试写坏，跑之前备份、跑完还原
GUARDED = [
    "config.json",
    "library.json",
    "library.bak.json",
    "modimports.json",
    "favorites.json",
    "authors.json",
    "modmeta.json",
]

# 顺序有讲究：先纯逻辑，再 UI 冒烟，最后综合回归（最慢、动得最多）
DEFAULT_SUITE = [
    "readme_check",
    "core_test",
    "update_check_test",
    "apply_test",
    "mods_test",
    "sort_test",
    "filter_test",
    "toggle_test",
    "mods_ops_test",
    "zip_test",
    "bg_test",
    "accent_test",
    "theme_test",
    "vpk_test",
    "addonlist_test",
    "filter_ui_test",
    "workshop_page_test",
    "ws_scroll_test",
    "mod_delete_test",
    "mod_update_test",
    "workshop_dl_test",
    "copycode_test",
    "player_test",
    "toast_life_test",
    "toast_level_test",
    "toast_hover_test",
    "toast_repeat_test",
    "scroll_test",
    "scrollbar_test",
    "scroll_drag_test",
    "resize_test",
    "detail_check",
    "video_detail_test",
    "detail_actions_test",
    "update_ui_test",
    "agreement_test",
    "onefile_paths_test",
    "servers_test",
    "downloads_test",
    "fixes_test",
    "ws_download_test",
    "round15_test",
    "round16_test",
    "round17_test",
    "lanzou_test",
    "translate_test",
    "archive_import_test",
    "round18_test",
    "round21_test",
    "round22_test",
    "round23_test",
    "round24_test",
    "round25_test",
    "round26_test",
    "round12_test",
    "round12_ui_test",
    "round13_test",
    "round14_test",
    "uismoke_test",
    "regress_test",
]


def snapshot(tmpdir: str) -> dict[str, str]:
    """把受保护文件复制到临时目录，返回「文件名 → 备份路径」。"""
    saved: dict[str, str] = {}
    for name in GUARDED:
        src = os.path.join(DATA, name)
        if os.path.isfile(src):
            dst = os.path.join(tmpdir, name)
            shutil.copy2(src, dst)
            saved[name] = dst
    return saved


def restore(saved: dict[str, str]) -> None:
    """还原；备份里没有的（跑之前本来就不存在）就删掉，别留垃圾。"""
    for name in GUARDED:
        dst = os.path.join(DATA, name)
        if name in saved:
            shutil.copy2(saved[name], dst)
        else:
            try:
                os.remove(dst)
            except OSError:
                pass


def main(argv: list[str]) -> int:
    tests = argv[1:] or DEFAULT_SUITE
    tmpdir = tempfile.mkdtemp(prefix="l4d2_guard_")
    saved = snapshot(tmpdir)
    print("已备份用户数据:", ", ".join(sorted(saved)) or "（无）")
    print()

    results: list[tuple[str, int, float]] = []
    try:
        for name in tests:
            path = os.path.join(TOOLS, name + ".py")
            if not os.path.isfile(path):
                print(f"{name:20s} 跳过（没有这个文件）")
                results.append((name, -1, 0.0))
                continue
            t0 = time.time()
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", path],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            cost = time.time() - t0
            ok = proc.returncode == 0
            print(f"{name:20s} {'PASS' if ok else 'FAIL'}  ({cost:.1f}s)")
            if not ok:
                tail = [ln for ln in (proc.stdout or "").splitlines()
                        if ln.strip() and not ln.startswith(("  ok", "==="))]
                for ln in tail[-12:]:
                    print("      " + ln[:150])
            results.append((name, proc.returncode, cost))
    finally:
        restore(saved)
        shutil.rmtree(tmpdir, ignore_errors=True)
        print()
        print("用户数据已还原")

    failed = [r for r in results if r[1] > 0]
    skipped = [r for r in results if r[1] < 0]
    print()
    print(f"共 {len(results)} 项：通过 {len(results) - len(failed) - len(skipped)}"
          f"，失败 {len(failed)}，跳过 {len(skipped)}")
    if failed:
        print("失败：" + ", ".join(r[0] for r in failed))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
