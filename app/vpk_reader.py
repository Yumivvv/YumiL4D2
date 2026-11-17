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

"""VPK 内部解析：读出 MOD 自己带的标题 / 作者 / 简介 / 预览图。

## 为什么要做这个

现在工具对本地 MOD 只能显示**文件名**：`莉音黑伤.vpk` → 标题就是「莉音黑伤」。
但 VPK 内部通常带一份 `addoninfo.txt` 和一张 `addonimage.jpg`，里面是作者
自己写的**真实标题、作者、版本、简介**。读出来之后，本地 MOD 也能像工坊 MOD
一样显示完整信息（封面、作者、简介），不再是一串文件名。

## VPK 格式（按 Valve 公开的格式规范实现，v1 / v2 都支持）

```
偏移   长度        内容
0      4           magic = 0x55AA1234
4      4           version (1 或 2)

-- v1 到此为止（头 12 字节）--
-- v2 继续： --

8      4           treeSize            目录树字节数
12     4           fileDataSectionSize
16     4           archiveMD5SectionSize
20     4           otherMD5SectionSize
24     4           signatureSectionSize
```

目录树紧跟头部，递归结构：

```
string  扩展名（空串表示「目录树结束」）
  循环（直到读到空扩展名）：
    string  路径（空串表示「这一层结束」）
      循环（直到读到空文件名）：
        string  文件名（空串表示「这一层结束」）
        uint32  crc
        uint16  预加载字节数
        uint16  archiveIndex
        uint32  数据偏移
        uint32  数据长度
        uint16  结尾标记 0xFFFF
```

`archiveIndex == 0x7FFF` 表示数据就在本文件里（紧随目录树之后）；
否则数据在 `名字_00N.vpk` 这个分卷里。

字符串都是 **UTF-8、以 `\\0` 结尾**。

## 只读需要的东西，不改文件

解析时只 seek + read，绝不写。大 VPK（几百 MB）也只读几十 KB 的头部和目录树，
所以很快。
"""
from __future__ import annotations

import os
import re
import struct
from typing import BinaryIO

from .util import Log

log = Log("vpk.log")

VPK_MAGIC = 0x55AA1234
# archiveIndex 等于这个值表示数据在本体，否则在 _00N 分卷里
DIR_ENTRY_TERM = 0x7FFF
# 一个 VPK 里可能有一堆文件，读目录树时给个上限防跑飞
MAX_TREE_BYTES = 64 * 1024 * 1024
MAX_FILES = 200000

# 预览图的候选（VPK 里最常见的几种位置）
PREVIEW_CANDIDATES = (
    "addonimage.jpg",
    "addonimage.png",
    "addonimage.jpeg",
    "materials/vgui/maps/menu/",
    "materials/vgui/loadingscreen/",
    "resource/overviews/",
)

# addoninfo.txt 的键 → 我们关心的字段
ADDON_KEYS = {
    "addontitle": "title",
    "addontitle2": "title",
    "addonauthor": "author",
    "addonauthor2": "author",
    "addonversion": "version",
    "addondescription": "desc",
    "addondescription2": "desc",
    "addonurl0": "url",
    "addonurl": "url",
}


class VpkError(Exception):
    """VPK 读不了（不是有效 VPK / 版本不支持 / 文件截断）。"""


# ===========================================================================
# 底层读取
# ===========================================================================
def _read_cstr(f: BinaryIO) -> str:
    """读一个 \\0 结尾的 UTF-8 字符串。"""
    buf = bytearray()
    while True:
        ch = f.read(1)
        if not ch:
            raise VpkError("目录树被截断（读到文件末尾）")
        if ch == b"\0":
            break
        buf += ch
        if len(buf) > 4096:      # 明显不对劲，别把内存吃爆
            raise VpkError("目录树里的字符串异常过长")
    return buf.decode("utf-8", "replace")


def read_header(f: BinaryIO) -> dict:
    """读 VPK 头，返回 {"version", "treeSize", "headerSize", "fileDataOffset"}。"""
    f.seek(0)
    raw = f.read(12)
    if len(raw) < 12:
        raise VpkError("文件太小，不是 VPK")
    magic, version = struct.unpack("<II", raw[:8])
    if magic != VPK_MAGIC:
        raise VpkError(f"magic 不对（0x{magic:08X}），不是 VPK 文件")
    if version == 1:
        return {"version": 1, "treeSize": struct.unpack("<I", raw[8:12])[0],
                "headerSize": 12}
    if version == 2:
        more = f.read(16)
        if len(more) < 16:
            raise VpkError("VPK v2 头不完整")
        tree_size, fd_size, md5_size, other_size, sig_size = struct.unpack("<IIIII", more)
        return {
            "version": 2,
            "treeSize": tree_size,
            "headerSize": 28,
            "fileDataOffset": 28 + tree_size + md5_size + other_size,
            "fileDataSize": fd_size,
            "signatureSize": sig_size,
        }
    raise VpkError(f"不支持的 VPK 版本：{version}")


def read_tree(f: BinaryIO, header: dict) -> list[dict]:
    """读目录树，返回 [{path, crc, archiveIndex, offset, length, preload}]。

    `path` 是 VPK 内部的完整路径（小写、正斜杠），比如
    `materials/models/survivor/zoey/zoey_body.vmt`。
    """
    tree_size = int(header.get("treeSize") or 0)
    if tree_size <= 0:
        return []
    if tree_size > MAX_TREE_BYTES:
        raise VpkError(f"目录树异常大（{tree_size} 字节），拒绝解析")

    f.seek(header["headerSize"])
    out: list[dict] = []
    guard = 0
    while True:
        ext = _read_cstr(f)
        if not ext:                 # 空扩展名 = 整个目录树结束
            break
        while True:
            folder = _read_cstr(f)
            if not folder:          # 空路径 = 这一层结束
                break
            while True:
                name = _read_cstr(f)
                if not name:        # 空文件名 = 这一层结束
                    break
                raw = f.read(18)
                if len(raw) < 18:
                    raise VpkError("目录树条目被截断")
                crc, preload, arch, off, ln = struct.unpack("<IHHII", raw[:16])
                term = struct.unpack("<H", raw[16:18])[0]
                if term != DIR_ENTRY_TERM:
                    # 格式不符，但通常能继续读；不抛错，避免整个文件判失败
                    pass
                guard += 1
                if guard > MAX_FILES:
                    raise VpkError("目录树条目过多，可能解析错位")
                # folder 结尾通常带 "/"，拼出来就是完整路径
                full = (folder + name) if folder.endswith("/") else (
                    folder + "/" + name if folder else name)
                # 扩展名单独存，要补回去
                if ext and not full.lower().endswith("." + ext.lower()):
                    full = full + "." + ext
                out.append({
                    "path": full.lower().replace("\\", "/"),
                    "crc": crc,
                    "preload": preload,
                    "archiveIndex": arch,
                    "offset": off,
                    "length": ln,
                })
    return out


def read_file_bytes(f: BinaryIO, header: dict, entry: dict,
                    max_bytes: int = 4 * 1024 * 1024) -> bytes:
    """读出某个条目在**本体**里的字节（分卷里的暂不支持，返回空）。

    `max_bytes` 是安全阀：只用来读 addoninfo.txt / 预览图这种小文件。
    """
    if entry.get("archiveIndex") != DIR_ENTRY_TERM:
        return b""       # 数据在 _001.vpk 分卷里，这里不处理
    length = int(entry.get("length") or 0)
    if length <= 0 or length > max_bytes:
        return b""
    base = int(header.get("fileDataOffset") or (header["headerSize"]
                                                + int(header.get("treeSize") or 0)))
    try:
        f.seek(base + int(entry.get("offset") or 0))
        return f.read(length)
    except OSError:
        return b""


# ===========================================================================
# addoninfo.txt 解析
# ===========================================================================
_KV_RE = re.compile(r'"([^"]*)"\s*"([^"]*)"')


def parse_addoninfo(text: str) -> dict:
    """解析 addoninfo.txt（KeyValues 方言，但很宽松）。

    实际文件长这样，键值都带引号，也可能不带：

        "AddonInfo"
        {
            "addontitle"      "【武器】飞鸟凑"
            "addonauthor"     "某人"
            "addondescription" "替换了 xxx"
        }

    所以两种写法都认：
      - `"key" "value"`
      - `key "value"`
    """
    out: dict = {"title": "", "author": "", "version": "", "desc": "", "url": ""}
    if not text:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        # 结构标记跳过
        if line in ("{", "}") or line.lower() in ('"addoninfo"', "addoninfo"):
            continue
        key = value = ""
        m = _KV_RE.search(line)
        if m:
            key, value = m.group(1), m.group(2)
        else:
            # key "value"（键没引号）
            i = line.find('"')
            if i <= 0:
                continue
            key = line[:i].strip()
            rest = line[i:]
            m2 = _KV_RE.search(rest)
            if m2:
                value = m2.group(1)
            else:
                j = rest.rfind('"')
                if j <= 0:
                    continue
                value = rest[1:j]
        k = key.strip().lower()
        field = ADDON_KEYS.get(k)
        if not field:
            continue
        v = _clean_value(value)
        # 同一字段有多行（addondescription2 之类）时，第一个非空的赢
        if v and not out.get(field):
            out[field] = v
    return out


def _clean_value(value: str) -> str:
    """收拾 addoninfo 里的值：去引号、把 \\n 还原成真换行、压掉多余空白。"""
    v = str(value or "").strip()
    # addoninfo 里换行常写成字面量 \n
    v = v.replace("\\n", "\n").replace("\\t", "\t")
    v = re.sub(r"[ \t]+", " ", v)
    return v.strip()


# ===========================================================================
# 图片识别（不依赖 PIL，只看魔数）
# ===========================================================================
def guess_image_ext(data: bytes) -> str:
    """根据文件头判断图片格式，返回扩展名（.jpg/.png/.gif/.webp）或空串。"""
    if not data or len(data) < 12:
        return ""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""


# ===========================================================================
# 对外主入口
# ===========================================================================
def read_vpk_meta(path: str, max_image_bytes: int = 4 * 1024 * 1024) -> dict:
    """读一个 VPK 的内部信息。

    返回：
        {
          "ok": bool,
          "error": str,
          "version": int,
          "fileCount": int,
          "info": {"title", "author", "version", "desc", "url"},
          "image": {"name", "data", "ext"} | None,   # data 是原始字节
          "hasBsp": bool, "hasNav": bool,
          "hasWeapon": bool, "hasCharacter": bool,
          "fileList": [path, ...]  # 最多 2000 条，冲突检测用
        }

    **任何异常都不抛**：返回 ok=False + error。调用方不用写 try。
    """
    res = {
        "ok": False, "error": "", "version": 0, "fileCount": 0,
        "info": {"title": "", "author": "", "version": "", "desc": "", "url": ""},
        "image": None,
        "hasBsp": False, "hasNav": False, "hasWeapon": False, "hasCharacter": False,
        "fileList": [],
    }
    path = str(path or "")
    if not path or not os.path.isfile(path):
        res["error"] = "文件不存在"
        return res
    try:
        with open(path, "rb") as f:
            header = read_header(f)
            res["version"] = header["version"]
            entries = read_tree(f, header)
            res["fileCount"] = len(entries)
            if not entries:
                res["error"] = "目录树为空"
                return res

            # 归类：找 addoninfo、找预览图、判断内容类型
            info_entry = None
            image_entry = None
            preview_fallback = None
            for e in entries:
                p = e["path"]
                low = p.lower()
                if low.endswith("addoninfo.txt") and info_entry is None:
                    info_entry = e
                if image_entry is None:
                    base = os.path.basename(low)
                    if base in ("addonimage.jpg", "addonimage.png", "addonimage.jpeg"):
                        image_entry = e
                if preview_fallback is None and guess_image_ext_from_name(low):
                    for pat in PREVIEW_CANDIDATES[3:]:
                        if pat in low:
                            preview_fallback = e
                            break
                if low.endswith(".bsp"):
                    res["hasBsp"] = True
                elif low.endswith(".nav"):
                    res["hasNav"] = True
                if ("models/weapons/" in low or "scripts/weapons/" in low
                        or "materials/weapons/" in low):
                    res["hasWeapon"] = True
                if is_character_path(low):
                    res["hasCharacter"] = True

            res["fileList"] = [e["path"] for e in entries[:2000]]

            if info_entry is not None:
                raw = read_file_bytes(f, header, info_entry)
                if raw:
                    text = _decode_text(raw)
                    res["info"] = parse_addoninfo(text)

            pick = image_entry or preview_fallback
            if pick is not None:
                data = read_file_bytes(f, header, pick, max_bytes=max_image_bytes)
                ext = guess_image_ext(data)
                if ext:
                    res["image"] = {"name": os.path.basename(pick["path"]),
                                    "data": data, "ext": ext}

            res["ok"] = True
            return res
    except VpkError as e:
        res["error"] = str(e)
        return res
    except (OSError, struct.error, MemoryError) as e:
        res["error"] = f"读取失败：{e}"
        return res
    except Exception as e:  # noqa: BLE001  解析器绝不能把调用方带崩
        log(f"read_vpk_meta crashed on {path}: {e!r}")
        res["error"] = f"解析出错：{e}"
        return res


def guess_image_ext_from_name(name: str) -> str:
    low = str(name or "").lower()
    for ext in (".jpg", ".jpeg", ".png", ".gif"):
        if low.endswith(ext):
            return ext
    return ""


def _decode_text(raw: bytes) -> str:
    """addoninfo.txt 可能是 UTF-8，也可能被存成 GBK。"""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


# HUD/界面资源不算「人物」证据 —— 这些目录下几乎必然出现角色名，
# 拿它们当证据会把界面 MOD 全判成人物 MOD。
_NON_CHARACTER_DIRS = (
    "materials/vgui/",
    "resource/",
    "scripts/",
    "particles/",
    "sound/ui/",
)


def is_character_path(low_path: str) -> bool:
    """这个 VPK 内部路径能不能作为「人物 MOD」的证据。

    `low_path` 要传小写、正斜杠的路径。
    """
    p = str(low_path or "").lower().replace("\\", "/")
    for d in _NON_CHARACTER_DIRS:
        if p.startswith(d):
            return False
    # 幸存者 / 感染者的模型、材质、音效目录
    signs = (
        "models/survivors/", "models/infected/", "models/survivor/",
        "materials/models/survivors/", "materials/models/infected/",
        "sound/survivors/", "sound/infected/",
    )
    return any(s in p for s in signs)


# 角色关键词表（有序，具体→笼统）。顺序即优先级。
CHARACTER_KEYWORDS = (
    ("common_male_ceda", "CEDA"),
    ("common_male_riot", "防暴警察"),
    ("common_male_pilot", "飞行员"),
    ("common_male_soldier", "军人"),
    ("zoey", "Zoey"),
    ("louis", "Louis"),
    ("francis", "Francis"),
    ("bill", "Bill"),
    ("coach", "Coach"),
    ("ellis", "Ellis"),
    ("rochelle", "Rochelle"),
    ("nick", "Nick"),
    ("smoker", "Smoker"),
    ("boomer", "Boomer"),
    ("hunter", "Hunter"),
    ("spitter", "Spitter"),
    ("jockey", "Jockey"),
    ("charger", "Charger"),
    ("tank", "Tank"),
    ("witch", "Witch"),
)


def detect_character(title: str, file_list: list[str], limit: int = 3) -> list[str]:
    """从标题 + VPK 内部路径推断是哪个角色。返回去重后的中文/英文名列表。"""
    hits: list[str] = []
    seen: set[str] = set()
    text = (str(title or "") + " " + " ".join(
        p for p in (file_list or []) if is_character_path(p))).lower()
    for key, label in CHARACTER_KEYWORDS:
        if key in text and label not in seen:
            seen.add(label)
            hits.append(label)
            if len(hits) >= limit:
                break
    return hits


def detect_weapon(title: str, file_list: list[str], limit: int = 3) -> list[str]:
    """从标题 + VPK 内部路径推断替换了哪些武器。"""
    weapons = (
        ("ak47", "AK47"), ("m16", "M16"), ("desert_eagle", "沙鹰"),
        ("pistol", "手枪"), ("pumpshotgun", "泵动霰弹"), ("shotgun_chrome", "铬合金霰弹"),
        ("autoshotgun", "自动霰弹"), ("shotgun_spas", "SPAS"), ("hunting_rifle", "猎枪"),
        ("sniper_military", "军狙"), ("sniper_scout", "鸟狙"), ("awp", "AWP"),
        ("smg", "SMG"), ("smg_silenced", "消音SMG"), ("smg_mp5", "MP5"),
        ("rifle", "步枪"), ("rifle_desert", "沙漠步枪"), ("rifle_ak47", "AK47"),
        ("rifle_m60", "M60"), ("grenade_launcher", "榴弹发射器"),
        ("melee", "近战"), ("chainsaw", "电锯"), ("katana", "武士刀"),
        ("baseball_bat", "棒球棍"), ("crowbar", "撬棍"), ("knife", "刀"),
        ("pistol_magnum", "马格南"), ("molotov", "燃烧瓶"), ("pipe_bomb", "土制炸弹"),
        ("gascan", "油桶"), ("adrenaline", "肾上腺素"), ("pain_pills", "止痛药"),
        ("first_aid", "急救包"), ("defibrillator", "除颤器"),
    )
    text = str(title or "").lower()
    # 优先看标题（作者通常会写「替换 m16」），找不到再看内部路径
    paths = " ".join(file_list or [])
    hits: list[str] = []
    seen: set[str] = set()
    for key, label in weapons:
        if key in text and label not in seen:
            seen.add(label)
            hits.append(label)
            if len(hits) >= limit:
                return hits
    if len(hits) < limit:
        for key, label in weapons:
            if key in paths and label not in seen:
                seen.add(label)
                hits.append(label)
                if len(hits) >= limit:
                    break
    return hits
