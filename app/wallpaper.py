# Yumi的L4D2工具箱
# Copyright (C) 2026 ZengDeRong
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""自定义背景图：固定只有一个文件，叫 `background.*`.

设计取舍（用户明确要求）：
- 目录里**只保留一张**背景图，名字固定为 `background`，扩展名随图片格式变
  （`background.jpg` / `background.png` …）。程序只认这个文件名，别的一律忽略。
- 换图 = 覆盖同一个文件，不会越攒越多。
- 「移除背景」= **真的把文件删掉**，不是仅仅把配置里的名字清空。

这样用户想换图就只有一条路径：导入 → 覆盖 background.*；
目录永远干净，也不会有「点了图片名切换」那种连用户自己都搞不清的旧状态。

配置里只存**文件名**（`bg_image`），所以整个程序目录挪走、备份、拷给朋友都能直接用。
"""
from __future__ import annotations

import os
import shutil

from . import util as _util
from .util import BG_DIR, Log
from .util import human_size as _human_size

log = Log("wallpaper.log")


def bg_dir() -> str:
    """当前背景图目录。

    每次现读 `util.BG_DIR`，而不是死记 import 时那一份 ——
    测试会把 `util.BG_DIR` 指到临时沙盒（因为「移除背景」是真删文件），
    如果这里缓存了旧路径，就会删到用户真实的壁纸。
    """
    return getattr(_util, "BG_DIR", BG_DIR) or BG_DIR

# 支持导入的图片格式（QML Image 走 Qt 的图像插件，这几种都稳）
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")

# 固定文件名（不含扩展名）。只认这一个名字，别的图片文件会被忽略。
BG_STEM = "background"

# 透明度的默认值 / 上限下限（百分比）。默认压得比较低，
# 不然一张照片会把上面的文字糊掉。
DEFAULT_OPACITY = 35


def clamp_opacity(value: object) -> int:
    """把任意输入收成 0-100 的整数透明度。"""
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_OPACITY
    return max(0, min(100, n))


def is_image_file(name: str) -> bool:
    return os.path.splitext(str(name or ""))[1].lower() in IMAGE_EXTS


def ext_of(name: str) -> str:
    """取规范化的扩展名（小写），不是支持格式就返回空串。"""
    ext = os.path.splitext(str(name or ""))[1].lower()
    return ext if ext in IMAGE_EXTS else ""


def current_bg_path(base_dir: str = "") -> str:
    """当前背景图的实际路径：directory 里叫 background.* 的那张。

    同时存在多个扩展名（用户手动放了 background.png 又 background.jpg）时，
    按 IMAGE_EXTS 的顺序取第一个，保证结果稳定。
    """
    base_dir = base_dir or bg_dir()
    for ext in IMAGE_EXTS:
        cand = os.path.join(base_dir, BG_STEM + ext)
        if os.path.isfile(cand):
            return cand
    return ""


def resolve_bg_path(value: str, base_dir: str = "") -> str:
    """配置里存的值 → 实际图片路径，找不到返回空串。

    只有当配置值指向 `background.*` 时才认；老配置里存的别的文件名一律当失效处理，
    免得升级后还按老名字去找一张已经不存在的图。
    """
    base_dir = base_dir or bg_dir()
    raw = (value or "").strip()
    if not raw:
        # 配置里没记，但目录里可能已经有一张 background.*（比如用户自己丢进去的）
        return current_bg_path(base_dir)
    name = os.path.basename(raw)
    stem, ext = os.path.splitext(name)
    if stem.lower() != BG_STEM or ext.lower() not in IMAGE_EXTS:
        return ""
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    cand = os.path.join(base_dir, BG_STEM + ext.lower())
    if os.path.isfile(cand):
        return cand
    # 扩展名大小写不一致时再兜一次底
    return current_bg_path(base_dir)


def list_backgrounds() -> list[dict]:
    """当前可用的背景图（最多一条，就是 background.*）。

    保留成列表是为了不让上层调用点改签名；但现在永远只有 0 或 1 项。
    """
    path = current_bg_path()
    if not path:
        return []
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return [{
        "name": os.path.basename(path),
        "path": path,
        "size": size,
        "sizeText": human_size(size),
    }]


# ★ 体积格式化统一走 util.human_size（全项目唯一实现）。
human_size = _human_size


def import_background(src: str) -> dict:
    """把用户选的图片复制成 `background.<ext>`，覆盖旧的那张。

    「只有一个文件」所以不需要 _1/_2 后缀：换了就是换掉。
    旧文件扩展名不同（比如原来是 png，现在导入 jpg）会顺手删掉，
    不然目录里会同时躺着 background.png 和 background.jpg。

    返回 {"ok", "name", "path", "error"}。
    """
    src = os.path.abspath(src or "")
    if not os.path.isfile(src):
        return {"ok": False, "name": "", "path": "", "error": "文件不存在"}
    ext = ext_of(src)
    if not ext:
        return {
            "ok": False, "name": "", "path": "",
            "error": "只支持 " + " / ".join(e.lstrip(".").upper() for e in IMAGE_EXTS),
        }
    os.makedirs(bg_dir(), exist_ok=True)
    dst = os.path.join(bg_dir(), BG_STEM + ext)

    # 先清掉其它扩展名的旧背景，保证目录里只有一张
    for other in IMAGE_EXTS:
        old = os.path.join(bg_dir(), BG_STEM + other)
        if old != dst and os.path.isfile(old):
            try:
                os.remove(old)
            except OSError as e:
                log(f"remove old background {old} failed: {e}")

    if os.path.isfile(dst) and os.path.abspath(dst) == src:
        # 用户选的就是 backgrounds 里那张，什么都不用做
        return {"ok": True, "name": os.path.basename(dst), "path": dst, "error": ""}
    try:
        shutil.copy2(src, dst)
    except OSError as e:
        log(f"import background failed: {e}")
        return {"ok": False, "name": "", "path": "", "error": str(e)}
    return {"ok": True, "name": os.path.basename(dst), "path": dst, "error": ""}


def remove_background() -> dict:
    """移除背景：把 `background.*` 真的删掉（用户要求「移除就是删除图片」）。

    返回 {"ok", "removed"} —— removed 是删掉的文件名，没东西可删就是空串。
    """
    removed = ""
    for ext in IMAGE_EXTS:
        path = os.path.join(bg_dir(), BG_STEM + ext)
        if os.path.isfile(path):
            try:
                os.remove(path)
                removed = os.path.basename(path)
            except OSError as e:
                log(f"remove background {path} failed: {e}")
                return {"ok": False, "removed": "", "error": str(e)}
    return {"ok": True, "removed": removed, "error": ""}


def migrate_legacy(configured: str) -> dict:
    """把老配置里记着的背景图改名成 `background.<ext>`。

    老版本允许多张图、配置里存原文件名（比如 `ockrEBCn…_q80.jpeg`）。
    升级后只认 `background.*`，所以这里把配置指向的那张搬过去，
    免得用户升级完发现背景突然没了。

    返回 {"migrated": bool, "name": 新文件名}。
    """
    raw = os.path.basename((configured or "").strip())
    if not raw:
        return {"migrated": False, "name": ""}
    ext = ext_of(raw)
    if not ext:
        return {"migrated": False, "name": ""}
    # 已经是 background.* 就不用动
    if os.path.splitext(raw)[0].lower() == BG_STEM:
        return {"migrated": False, "name": raw}
    src = os.path.join(bg_dir(), raw)
    if not os.path.isfile(src):
        return {"migrated": False, "name": ""}
    dst = os.path.join(bg_dir(), BG_STEM + ext)
    # 已经有 background.* 了就不再覆盖（用户可能刚导入过新的）
    if os.path.isfile(dst) and os.path.abspath(dst) != os.path.abspath(src):
        return {"migrated": False, "name": os.path.basename(dst)}
    try:
        os.replace(src, dst)
    except OSError as e:
        log(f"migrate legacy background {src} failed: {e}")
        return {"migrated": False, "name": ""}
    log(f"background migrated: {raw} -> {os.path.basename(dst)}")
    return {"migrated": True, "name": os.path.basename(dst)}
