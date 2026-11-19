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

"""加载顺序：读写 `left4dead2/addonlist.txt`，调整 MOD 的加载顺序。

## 文件格式（实测）

`left4dead2/addonlist.txt` 是 Source 引擎的 KeyValues 文本：

```
"AddonList"
{
	"132381280.vpk"		"1"
	"【武器】飞鸟凑榴弹发射器.vpk"		"1"
}
```

- 每行：`<TAB>"文件名.vpk"<TAB><TAB>"1"`，值 `1` = 启用、`0` = 禁用
- 换行是 **LF**（`\n`），不是 CRLF
- 编码是 **GBK**（系统 ANSI 代码页），**不是 UTF-8**。
  这一条最容易踩坑：用 UTF-8 读写会把中文文件名写成乱码，游戏就找不到 MOD 了。
  所以这里统一 `encoding="gbk", errors="replace"`，并且写回时保持 GBK。

## 加载顺序的语义

Source 引擎按**文件里从上到下的顺序**加载 addon。同一个 .vpk 被多个 MOD 替换时，
**后面的覆盖前面的**。所以「把某个 MOD 往下拖」= 让它优先级更高。

这跟界面上的「MOD 列表排序」完全是两回事：那个只影响显示顺序，
这个真的会改变游戏里的覆盖结果。
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile

from .util import Log

log = Log("addonlist.log")

ADDONLIST_NAME = "addonlist.txt"

# L4D2 的 addonlist.txt 是 ANSI（GBK）编码，别改成 utf-8
ENCODING = "gbk"

# 一行形如：\t"名称.vpk"\t\t"1"
_LINE_RE = re.compile(r'^\s*"([^"]*)"\s*"([^"]*)"\s*$')


def addonlist_path(addons_dir: str) -> str:
    """addons 目录 → addonlist.txt 的路径。

    addonlist.txt 在 `left4dead2/` 下，而 addons 是它的子目录，
    所以往上退一级。用户如果直接把 left4dead2 传进来也能认。
    """
    d = str(addons_dir or "").strip()
    if not d:
        return ""
    base = os.path.basename(os.path.normpath(d)).lower()
    if base == "addons":
        return os.path.join(os.path.dirname(os.path.normpath(d)), ADDONLIST_NAME)
    # 已经是 left4dead2 目录
    if os.path.basename(os.path.normpath(d)).lower() == "left4dead2":
        return os.path.join(os.path.normpath(d), ADDONLIST_NAME)
    # 兜底：按 addons 的上一级猜
    return os.path.join(os.path.dirname(os.path.normpath(d)), ADDONLIST_NAME)


def _read_text(path: str) -> str:
    """按 GBK 读；GBK 也解不开时用 UTF-8 兜底（有些工具会重写成 UTF-8）。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in (ENCODING, "utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode(ENCODING, "replace")


def parse_addonlist(text: str) -> list[dict]:
    """解析成 [{"name": "x.vpk", "enabled": True, "line": 原行号}]。

    保持文件里的原始顺序 —— 这个顺序就是加载优先级。
    """
    out: list[dict] = []
    for idx, line in enumerate((text or "").splitlines()):
        m = _LINE_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        value = m.group(2).strip()
        if not name or name.lower() == "addonlist":
            continue
        # 只认值像数字的（避免把别的键值对吃进来）
        if value not in ("0", "1"):
            continue
        out.append({"name": name, "enabled": value == "1", "line": idx})
    return out


def load(addons_dir: str) -> dict:
    """读 addonlist.txt。

    返回 {"ok", "path", "exists", "entries": [...], "error"}
    `exists=False` 表示游戏还没生成过这个文件（正常情况，首次运行才有）。
    """
    path = addonlist_path(addons_dir)
    if not path:
        return {"ok": False, "path": "", "exists": False, "entries": [],
                "error": "还没设置 MOD 目录"}
    if not os.path.isfile(path):
        return {"ok": True, "path": path, "exists": False, "entries": [], "error": ""}
    try:
        text = _read_text(path)
    except OSError as e:
        return {"ok": False, "path": path, "exists": True, "entries": [],
                "error": f"读取失败：{e}"}
    entries = parse_addonlist(text)
    return {"ok": True, "path": path, "exists": True, "entries": entries, "error": ""}


def save(addons_dir: str, entries: list[dict]) -> dict:
    """把顺序写回 addonlist.txt（保持原有的启用/禁用值）。

    ★ 关键：先写 .tmp 再 os.replace，避免写一半崩了把原文件弄坏 ——
      这个文件丢了游戏会一个 MOD 都不加载。
    写之前还会留一份 `.bak`。
    """
    path = addonlist_path(addons_dir)
    if not path:
        return {"ok": False, "error": "还没设置 MOD 目录"}
    os.makedirs(os.path.dirname(path), exist_ok=True)

    lines = ['"AddonList"', "{"]
    for it in entries or []:
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        # 文件名里的双引号会破坏 KV 格式，直接换成单引号
        name = name.replace('"', "'")
        value = "1" if it.get("enabled", True) else "0"
        lines.append('\t"%s"\t\t"%s"' % (name, value))
    lines.append("}")
    text = "\n".join(lines) + "\n"

    tmp = path + ".tmp"
    try:
        if os.path.isfile(path):
            # 备份一份，写坏了还能捞回来
            try:
                shutil.copy2(path, path + ".bak")
            except OSError:
                pass
        with open(tmp, "wb") as f:
            f.write(text.encode(ENCODING, "replace"))
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        log(f"save addonlist failed: {e!r}")
        return {"ok": False, "error": f"写入失败：{e}"}
    return {"ok": True, "path": path, "count": len(entries or []), "error": ""}


def build_view(addons_dir: str) -> dict:
    """给界面用：把 addonlist 和真实文件对上，标出「文件不存在」的条目。

    ★ 只列 addonlist.txt 里有的条目 —— 这是用户明确要求的：
      「加载顺序」应该就是游戏真正读的那份清单，不是 addons 目录的全量快照。
      没登记进 addonlist 的 vpk 需要用「同步 addons 目录」手动补进来。

    返回 {"ok", "path", "exists", "items": [...], "missing": n, "error"}

    items 每项：
        {"name", "enabled", "exists", "fileDisabled", "index", "size", "sizeText",
         "stem", "title", "workshopId"}
    """
    res = load(addons_dir)
    if not res.get("ok"):
        return {"ok": False, "path": res.get("path") or "", "exists": False,
                "items": [], "missing": 0, "error": res.get("error") or ""}

    d = str(addons_dir or "")
    items: list[dict] = []
    missing = 0
    for i, ent in enumerate(res.get("entries") or []):
        name = ent["name"]
        # 真实文件可能在 addons 根目录，也可能在 workshop 子目录
        cand = [
            os.path.join(d, name),
            os.path.join(d, "workshop", name),
        ]
        real = next((p for p in cand if os.path.isfile(p)), "")
        # 禁用状态的文件名带 .disabled，也当成存在
        file_disabled = False
        if not real:
            dis = name + ".disabled"
            real = next((p for p in (os.path.join(d, dis),
                                     os.path.join(d, "workshop", dis))
                         if os.path.isfile(p)), "")
            # 只有靠 .disabled 才找到的，说明磁盘上的文件本身是禁用的 ——
            # 界面上要显示成「禁用」而不是「本地」，否则用户会以为它开着。
            file_disabled = bool(real)
        exists = bool(real)
        if not exists:
            missing += 1
        try:
            size = os.path.getsize(real) if real else 0
        except OSError:
            size = 0
        items.append({
            "name": name,
            "enabled": bool(ent.get("enabled")),
            "exists": exists,
            # 磁盘上就是 xxx.vpk.disabled
            "fileDisabled": file_disabled,
            "index": i,
            # 「本地」= addons 根目录，「云」= 创意工坊 workshop 子目录
            "isLocal": bool(real and os.path.normcase(
                os.path.dirname(real)) == os.path.normcase(os.path.normpath(d))),
            "size": size,
            "sizeText": _fmt_size(size),
            "stem": os.path.splitext(name)[0],
            "path": real,
            # 工坊 ID（纯数字文件名才有）
            "workshopId": os.path.splitext(name)[0] if os.path.splitext(name)[0].isdigit()
                          else "",
        })
    return {"ok": True, "path": res.get("path") or "", "exists": res.get("exists"),
            "items": items, "missing": missing, "error": ""}


def reorder(entries: list[dict], from_index: int, to_index: int) -> list[dict]:
    """把 from_index 的条目移到 to_index（纯粹的列表移动，不碰文件）。"""
    items = list(entries or [])
    n = len(items)
    if n == 0:
        return items
    src = max(0, min(n - 1, int(from_index)))
    dst = max(0, min(n - 1, int(to_index)))
    if src == dst:
        return items
    item = items.pop(src)
    items.insert(dst, item)
    return items


def move_up_down(entries: list[dict], index: int, delta: int) -> list[dict]:
    """上移 / 下移 N 位，越界自动夹住。"""
    n = len(entries or [])
    if n == 0:
        return list(entries or [])
    return reorder(entries, index, max(0, min(n - 1, int(index) + int(delta))))


def sync_from_addons(addons_dir: str) -> dict:
    """把 addons 目录里「文件存在但 addonlist 里没有」的 MOD 补到末尾。

    这种情况常见：用户自己往 addons 里丢了 vpk，但游戏还没重新生成 addonlist。
    补进去（默认启用）之后，加载顺序才管得到它们。
    """
    view = build_view(addons_dir)
    if not view.get("ok"):
        return view
    known = {it["name"].lower() for it in view.get("items") or []}
    added: list[str] = []
    d = str(addons_dir or "")
    try:
        names = sorted(os.listdir(d))
    except OSError:
        names = []
    new_entries = [{"name": it["name"], "enabled": it["enabled"]}
                   for it in view.get("items") or []]
    for name in names:
        low = name.lower()
        if not low.endswith(".vpk"):
            continue
        if low in known:
            continue
        new_entries.append({"name": name, "enabled": True})
        added.append(name)
        known.add(low)
    if not added:
        return {"ok": True, "added": [], "count": len(new_entries),
                "path": view.get("path") or "", "error": ""}
    res = save(addons_dir, new_entries)
    return {"ok": bool(res.get("ok")), "added": added, "count": len(new_entries),
            "path": res.get("path") or "", "error": res.get("error") or ""}


def _fmt_size(n: object) -> str:
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        return "0 B"
    if v <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024:
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024.0
    return f"{v:.1f} PB"
