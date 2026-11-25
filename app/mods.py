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

"""L4D2 MOD 管理器：扫描 / 导入 / 移植 / 云 mod 识别.

目录约定（以 L4D2 安装目录为根）：
    left4dead2/addons/            本地 mod（.vpk + 同名图片）
    left4dead2/addons/workshop/   Steam 创意工坊下载的云 mod

命名约定：
    创意工坊下载的 mod 文件名就是工坊 ID（纯数字），如 132381280.vpk
    它的封面图通常同名，如 132381280.jpg / 132381280.png
    非纯数字命名的 mod 是本地自制 / 第三方搬运的
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from typing import Callable, Iterable

import requests

from . import netclient as NC
from .util import DATA_DIR, Log
from .util import human_size as _human_size

log = Log("mods.log")

# ---------------------------------------------------------------- 常量
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
MOD_EXTS = (".vpk",)
# 压缩包：用户可以把多个 vpk + 封面打包成 zip 拖进来一次导入
#
# ★ 2026-11 扩了 7z / rar / tar 家族：蓝奏云上大量资源是 .7z 和 .rar，
#   以前只有 .zip 被当成压缩包，拖 .7z 进去会被当普通文件跳过 ——
#   用户看到的就是「拖进去没反应」。
#   zip 用标准库（快、准、能拿到准确清单）；其余走 Windows 自带的
#   `tar.exe`（bsdtar + libarchive，原生认 7z/rar/tar，不用装 7-Zip）。
ARCHIVE_EXTS = (".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz",
                ".tgz", ".tbz2", ".txz")
# 这些交给 bsdtar
_TAR_EXTS = (".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tbz2", ".txz")
# 禁用一个 mod 的方式：把 xxx.vpk 改名成 xxx.vpk.disabled，游戏就不会加载它。
DISABLED_SUFFIX = ".vpk.disabled"
WORKSHOP_API = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
WORKSHOP_PAGE = "https://steamcommunity.com/sharedfiles/filedetails/?id={}"
# 合集成员：官方 GetCollectionDetails（不需要 key，实测可用）
WORKSHOP_COLLECTION_API = (
    "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/")
# ★ 这里原本有一个第三方中转地址（l4d2-workshop.laoyutang.cn/detail?id=），
#   那是 LytVPK 维护者的线上服务，已在 issue #1 中要求迁移，**已移除**。
#   现在所有工坊数据都直接问 Steam 官方接口。
CACHE_DIR = os.path.join(DATA_DIR, "modcache")
META_PATH = os.path.join(DATA_DIR, "modmeta.json")
# 作者 Steam 昵称缓存（SteamID → 昵称）
AUTHOR_PATH = os.path.join(DATA_DIR, "authors.json")
# 「导入日期」台账：这个工具真正导入/转换过来的 MOD 记一笔真实时间，
# 没记过的（用户自己拷进来的 / Steam 下载的）退回文件 mtime。
IMPORT_LEDGER_PATH = os.path.join(DATA_DIR, "modimports.json")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_PURE_ID = re.compile(r"^(\d{5,20})$")


# ===========================================================================
# 导入台账：记录「这个 MOD 什么时候被导入进来」
# ===========================================================================
_ledger_lock = threading.Lock()


def _read_json_dict(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic_json(path: str, data: dict) -> None:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        log(f"write {os.path.basename(path)} failed: {e}")


def load_import_ledger() -> dict:
    return _read_json_dict(IMPORT_LEDGER_PATH)


def _ledger_key(name: str) -> str:
    """台账按「MOD 的名字」记（不含 .disabled 后缀），改名/启停都不丢。"""
    base = str(name or "")
    if base.lower().endswith(DISABLED_SUFFIX):
        base = base[: -len(".disabled")]
    return os.path.splitext(os.path.basename(base))[0].lower()


def record_imports(names: Iterable[str], ts: int | None = None) -> None:
    """把若干 MOD 记进「导入台账」（文件名或 stem 都行）。"""
    stamp = int(ts or time.time())
    keys = [_ledger_key(n) for n in names if _ledger_key(n)]
    if not keys:
        return
    with _ledger_lock:
        data = load_import_ledger()
        for key in keys:
            data[key] = stamp
        _atomic_json(IMPORT_LEDGER_PATH, data)


def import_ts_of(name_or_path: str, fallback: int = 0) -> int:
    """查这个 MOD 的导入时间；没记录过就退回调用方给的 fallback（文件 mtime）。"""
    key = _ledger_key(name_or_path)
    if not key:
        return fallback
    try:
        return int(load_import_ledger().get(key) or fallback or 0)
    except (TypeError, ValueError):
        return fallback or 0


def forget_imports(names: Iterable[str]) -> None:
    """删除 MOD 时把台账里对应的记录一起清掉。"""
    keys = {_ledger_key(n) for n in names}
    keys.discard("")
    if not keys:
        return
    with _ledger_lock:
        data = load_import_ledger()
        if not any(k in data for k in keys):
            return
        for key in keys:
            data.pop(key, None)
        _atomic_json(IMPORT_LEDGER_PATH, data)


# ★ 体积格式化统一走 util.human_size（全项目唯一实现）。
#   这里以前有一份逐字节相同的副本，和 core/wallpaper/player 里的那几份
#   完全一样 —— 改一处漏三处，就是「屎山」的来源。
human_size = _human_size


def workshop_id_of(filename: str) -> str:
    """若文件名是纯数字（创意工坊 ID），返回 ID，否则空串。"""
    stem = os.path.splitext(os.path.basename(filename))[0].strip()
    m = _PURE_ID.match(stem)
    return m.group(1) if m else ""


# ===========================================================================
# Steam / L4D2 目录探测
# ===========================================================================
def _steam_path_from_registry() -> list[str]:
    found: list[str] = []
    try:
        import winreg  # noqa: PLC0415
    except ImportError:
        return found

    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for root, path, name in keys:
        try:
            with winreg.OpenKey(root, path) as k:
                val, _ = winreg.QueryValueEx(k, name)
                if val and os.path.isdir(val):
                    found.append(os.path.normpath(val))
        except OSError:
            continue
    return found


def _steam_libraries(steam_root: str) -> list[str]:
    """解析 libraryfolders.vdf，拿到所有 Steam 库目录。"""
    libs = [steam_root]
    vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return libs

    # 简单解析，不引入 vdf 依赖：抓所有 "path" 值
    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        p = m.group(1).replace("\\\\", "\\")
        if os.path.isdir(p) and p not in libs:
            libs.append(os.path.normpath(p))
    return libs


def find_l4d2_dirs() -> list[str]:
    """返回所有找到的 L4D2 的 left4dead2/addons 目录."""
    result: list[str] = []
    roots: list[str] = []

    for sp in _steam_path_from_registry():
        roots.extend(_steam_libraries(sp))

    # 常见盘符兜底
    for drive in "CDEFGH":
        for name in ("SteamLibrary", "Steam", "Games\\SteamLibrary", "SteamLibrary2"):
            p = f"{drive}:\\{name}"
            if os.path.isdir(p) and p not in roots:
                roots.append(p)

    for root in roots:
        addons = os.path.join(
            root, "steamapps", "common", "Left 4 Dead 2", "left4dead2", "addons"
        )
        if os.path.isdir(addons) and addons not in result:
            result.append(os.path.normpath(addons))
    return result


def normalize_addons_dir(path: str) -> str:
    """用户可能选到 L4D2 根目录 / left4dead2 / addons，统一成 addons。"""
    p = os.path.normpath(path or "")
    if not p:
        return ""
    low = p.lower()
    if low.endswith(os.sep + "addons"):
        return p if os.path.isdir(p) else ""
    for sub in (
        ("left4dead2", "addons"),
        ("addons",),
        (),
    ):
        cand = os.path.join(p, *sub) if sub else p
        if os.path.isdir(cand):
            return os.path.normpath(cand)
    return ""


# ===========================================================================
# 分类 / 内容标签
# ===========================================================================
# 顺序就是侧边栏的显示顺序
CATEGORY_DEFS: list[tuple[str, str]] = [
    ("xdr", "XDR动作模组"),
    ("l4n", "L4N平台"),
    ("survivor", "生还者"),
    ("infected", "感染者"),
    ("weapon", "武器"),
    ("map", "地图"),
    ("hud", "HUD"),
    ("script", "脚本"),
    ("sound", "音效"),
    ("action", "动作"),
    ("other", "其他"),
]
CATEGORY_LABELS = dict(CATEGORY_DEFS)

# 创意工坊的 tag（英文）→ 我们的分类
_TAG_TO_CATEGORY = {
    "weapons": "weapon", "weapon": "weapon", "items": "weapon", "item": "weapon",
    "melee": "weapon", "guns": "weapon", "gun": "weapon",
    "throwable": "weapon", "throwables": "weapon",
    "infected": "infected", "zombies": "infected", "zombie": "infected",
    "special infected": "infected",
    # 工坊里具体特感的 tag（"Tank Voice Pack" 这类按它替换的角色归类）
    "tank": "infected", "witch": "infected", "hunter": "infected",
    "smoker": "infected", "boomer": "infected", "charger": "infected",
    "jockey": "infected", "spitter": "infected",
    "common infected": "infected",
    "campaigns": "map", "campaign": "map", "maps": "map", "map": "map",
    "levels": "map", "level": "map", "versus": "map", "survival": "map",
    "scavenge": "map",
    "ui": "hud", "hud": "hud", "interface": "hud",
    "survivors": "survivor", "survivor": "survivor",
    "characters": "survivor", "character": "survivor",
    # 具体角色名（"replace Ellis / Nick" 之类）
    "ellis": "survivor", "nick": "survivor", "coach": "survivor",
    "zoey": "survivor", "louis": "survivor", "bill": "survivor",
    "francis": "survivor", "rochelle": "survivor",
    "sounds": "sound", "sound": "sound", "music": "sound", "audio": "sound",
    "voice": "sound", "voices": "sound",
    "scripts": "script", "script": "script", "scripting": "script",
    "gameplay": "script", "mutations": "script", "mutation": "script",
    "animations": "action", "animation": "action", "anim": "action",
    "models": "action", "model": "action", "skins": "action", "skin": "action",
}

# 同时命中多个 tag 时按这个顺序挑（越靠前越「具体」）。
# 工坊的 Co-op / Single Player / Realism / Miscellaneous / Textures 是玩法或
# 素材类型标签，几乎每个 mod 都挂着，故意不映射 —— 让它们落到标题关键词兜底，
# 否则「2019 (Anniversary Edition)」会因为带 Co-op 被归成「生还者」。
_TAG_PRIORITY: tuple[str, ...] = (
    "weapons", "melee", "throwable", "guns", "items",
    "infected", "zombies", "special infected",
    "tank", "witch", "hunter", "smoker", "boomer", "charger", "jockey",
    "spitter", "common infected",
    "campaigns", "maps", "levels", "versus", "survival", "scavenge",
    "ui", "hud", "interface",
    "survivors", "characters",
    "ellis", "nick", "coach", "zoey", "louis", "bill", "francis", "rochelle",
    "sounds", "music", "audio", "voice",
    "scripts", "scripting", "mutations", "gameplay",
    "animations", "models", "skins",
)

# 本地 mod 没有工坊 tag，就按标题/文件名里的关键词猜。越靠前越优先。
# 「感染者 / 生还者」放在「音效」前面：像「witch 语音包」这种，
# 参考做法是归到它替换的那个角色上，而不是笼统的「音效」。
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    # 两个整合包家族单独成类（界面上它们各自一栏）
    ("l4n", ("l4n", "l4n平台", "随机生还者", "random survivor")),
    ("xdr", ("xdreanims", "xdr anims", "xdr", "动作模组", "动作包")),
    ("hud", ("hud", "界面", "准星", "crosshair", "血条", "字幕")),
    ("map", ("地图", "战役", "关卡", "campaign", "versus", "coop map",
             "对抗图", "求生图")),
    ("script", ("脚本", "插件", "修改器", "指令", "script", "mutations",
                "游戏性", "平衡")),
    ("action", ("动作", "动画", "姿势", "anim", "xdr", "reload", "换弹",
                "持枪", "跑动")),
    ("infected", ("感染者", "僵尸", "丧尸", "特感", "witch", "tank", "smoker",
                  "boomer", "hunter", "charger", "jockey", "spitter", "zombie",
                  "infec")),
    ("survivor", ("生还者", "幸存者", "人物", "角色", "主角", "survivor",
                  "zoey", "louis", "bill", "francis", "coach", "ellis", "nick",
                  "rochelle")),
    # 武器排最后（兜底概率最高），并且把常见枪械/近战/投掷物名字都列上
    ("weapon", ("武器", "枪", "刀", "剑", "狙击", "步枪", "手枪", "霰弹", "冲锋枪",
                "机枪", "投掷", "燃烧瓶", "手雷", "手榴弹", "急救", "止痛",
                "肾上腺素", "电击器", "除颤", "胆汁", "土制炸弹",
                "weapon", "rifle", "pistol", "shotgun", "sniper", "melee", "smg",
                "blade", "sword", "knife", "axe", "heirloom", "bat", "club",
                "ak47", "m16", "awp", "scar", "sg552", "mp5", "uzi", "rgl",
                "m4a1", "deagle", "magnum", "glock", "m60", "m249", "ssg",
                "鸟狙", "连狙", "单狙", "连喷", "单喷", "微冲",
                "防暴", "斧", "棍", "球棒")),
    ("sound", ("音效", "声音", "音乐", "语音", "电台", "bgm", "sound", "audio",
               "music", "voice")),
]

# 标题里出现这些词，就能大致说出「这个 mod 替换的是什么」
_CONTENT_NOUNS: tuple[str, ...] = (
    "高尔夫球杆", "板球棒", "消防斧", "开山刀", "武士刀", "电锯", "撬棍", "平底锅",
    "棒球棍", "砍刀", "铁锹", "煎锅", "吉他",
    "榴弹发射器", "火箭筒", "机枪", "冲锋枪", "霰弹枪", "步枪", "狙击枪",
    "手枪", "手枪", "连狙", "鸟狙", "单喷", "连喷", "微冲",
    "AK47", "M16", "AWP", "SCAR", "SG552", "MP5", "UZI", "MAC10", "M60",
    "燃烧瓶", "土制炸弹", "胆汁", "止痛药", "肾上腺素", "医疗包", "除颤器",
    "Witch", "Tank", "Smoker", "Boomer", "Hunter", "Charger", "Jockey", "Spitter",
    "Zoey", "Louis", "Bill", "Francis", "Coach", "Ellis", "Nick", "Rochelle",
)

_CONTENT_SPLIT = re.compile(
    r"(?:替换|替换成|替换为|取代|变成|replace(?:d|s)?|->|→|=>)\s*",
    re.I,
)

# 分类规则里「分类词出现在替换目标里」不算，避免把「替换鸟狙」误判成别的
_CATEGORY_MIN_SCORE = 1


def category_from_tags(tags: Iterable[str]) -> str:
    """工坊 tag 列表 → 分类 key，认不出来返回空串。

    工坊返回的 tag 是一个无序列表，直接取第一个能认出来的会很不稳
    （同一个 mod 的标签顺序会变，而且玩法标签几乎人人都有），
    所以这里按 _TAG_PRIORITY 的固定优先级挑。
    """
    have = {str(t).strip().lower() for t in (tags or []) if str(t).strip()}
    for tag in _TAG_PRIORITY:
        if tag in have:
            key = _TAG_TO_CATEGORY.get(tag)
            if key:
                return key
    return ""


def platform_category(title: str, filename: str = "") -> str:
    """名字里点名了某个「平台」的，直接归到那个平台分类。

    L4N 是一整套随机生还者 / 动作平台，mod 名字里通常就写着 "L4N"，
    这类优先于工坊 tag —— 作者给 L4N 做的武器 mod 一样属于 L4N 平台。
    """
    text = f"{title or ''} {filename or ''}".lower()
    if "l4n" in text or "随机生还者" in text or "random survivor" in text:
        return "l4n"
    return ""


def guess_category(title: str, filename: str = "") -> str:
    """没有工坊 tag 时，按标题/文件名关键词猜分类。

    标题里写了「替换 XXX」的，先拿被替换的东西去判断——那才是这个 mod
    真正改的东西（例如「[csgo] SSG-08 替换鸟狙」是武器，不是别的）。
    """
    text = f"{title or ''} {filename or ''}".strip()
    if not text:
        return "other"
    target = describe_content(title)
    if target:
        found = _scan_keywords(target.lower())
        if found:
            return found
    return _scan_keywords(text.lower()) or "other"


def _scan_keywords(low: str) -> str:
    for key, words in _CATEGORY_KEYWORDS:
        for w in words:
            if w in low:
                return key
    return ""


def describe_content(title: str, desc: str = "") -> str:
    """猜「这个 mod 替换的是什么」，用于卡片上那一行小字。

    先看标题；标题里没有就退回简介（工坊简介里常常写着 "Replaces X" /
    "替换 X"）。命中「替换/取代/replace」的取后面那段，否则从名词表里挑。
    """
    text = (title or "").strip()
    if text:
        parts = _CONTENT_SPLIT.split(text)
        if len(parts) > 1:
            tail = parts[-1].strip(" 　-—_·:：,，.。()（）[]【】")
            tail = tail[:18]
            if tail:
                return tail
        low = text.lower()
        for noun in _CONTENT_NOUNS:
            if noun.lower() in low:
                return noun

    # 标题没猜出来，再试简介
    d = (desc or "").strip()
    if d:
        # 中文「把 X 替换成/为 Y」→ 取 Y
        # 常见写法：「把 XX 替换成了一把 YY」——「了」「一把」都是语气/量词，要剥掉
        for m in re.finditer(r"(?:替换成|替换为|改成|改为)\s*了?\s*(?:一把|一个|一台|一支|一条|一柄|一根)?\s*([^，。；;,\s]{1,18})", d):
            tail = m.group(1).strip(" 　-—_·:：,，.。()（）[]【】")
            if tail:
                return tail
        # 英文 "Replaces the hunting rifle (with ...)" → 取被替换的那个名词短语
        for m in re.finditer(r"replaces?\s+(?:the\s+|a\s+|an\s+)?([A-Za-z0-9][A-Za-z0-9\-\. ]{0,20}?)(?:\s+with|\s*$|[.,;])", d, re.I):
            tail = m.group(1).strip()
            if 2 <= len(tail) <= 18:
                return tail
        dlow = d.lower()
        for noun in _CONTENT_NOUNS:
            if noun.lower() in dlow:
                return noun
    return ""


# 创意工坊的简介是 BBCode，详情面板里直接显示会满屏 [h1] [/h1]
_BBCODE_TAG = re.compile(
    r"\[/?(?:h[1-6]|b|i|u|s|strike|url|img|list|olist|\*|quote|code|spoiler|table|tr|td|th"
    r"|hr|noparse|previewyoutube|video|p|center|left|right|font|color|size|sub|sup|expand"
    r"|section|previewyoutube|noparse)(?:=[^\]]*)?\]",
    re.I,
)


def clean_desc(text: str) -> str:
    """把工坊简介里的 BBCode 和 HTML 标签清掉，留给详情面板显示纯文本。"""
    if not text:
        return ""
    s = _BBCODE_TAG.sub("", text)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]{1,80}>", "", s)
    s = html.unescape(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def launch_game(addons_dir: str) -> dict:
    """启动游戏。

    addons 目录是 .../Left 4 Dead 2/left4dead2/addons，
    往上两级就是游戏根目录，直接跑 left4dead2.exe；
    找不到就退回 steam://rungameid/550。
    """
    if addons_dir:
        root = os.path.dirname(os.path.dirname(os.path.normpath(addons_dir)))
        for exe in ("left4dead2.exe", "Left4Dead2.exe"):
            p = os.path.join(root, exe)
            if os.path.isfile(p):
                try:
                    os.startfile(p)  # noqa: S606
                    return {"ok": True, "how": "exe", "target": p}
                except OSError as e:
                    log(f"launch exe failed: {e}")
                    break
    try:
        os.startfile("steam://rungameid/550")  # noqa: S606
        return {"ok": True, "how": "steam", "target": "steam://rungameid/550"}
    except OSError as e:
        log(f"launch steam failed: {e}")
        return {"ok": False, "how": "", "target": "", "error": str(e)}


# ===========================================================================
# 云 mod 元数据（Steam 创意工坊）
# ===========================================================================
class WorkshopClient:
    """查工坊 ID 对应的 mod 名称 / 封面。带本地缓存，避免重复请求。"""

    def __init__(self) -> None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._meta: dict[str, dict] = {}
        self._authors: dict[str, dict] = _read_json_dict(AUTHOR_PATH)
        self._author_lock = threading.Lock()
        self._lock = threading.Lock()
        self.load()

    # ------------------------------------------------------------ 持久化
    def load(self) -> None:
        try:
            with open(META_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._meta = data
        except (OSError, ValueError):
            self._meta = {}

    def save(self) -> None:
        try:
            tmp = META_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp, META_PATH)
        except OSError:
            pass

    def cached(self, wid: str) -> dict | None:
        with self._lock:
            item = self._meta.get(str(wid))
        # 老缓存没有 tags 字段（分类功能是后加的），当作没缓存重新拉一次
        if item and item.get("title") and "tags" in item:
            return item
        # ★ 失败的记录不能「永久占着位置」。
        #   以前这里对 `ok: False` 的条目也直接返回 None（等于每次都重查），
        #   但 `_meta` 里那条失败记录会一直在；而 `fetch()` 里「查不到也记一笔」
        #   的注释写着「避免每次都重查」—— 两者互相矛盾。
        #   现在明确：失败记录 30 分钟内有效（这段时间内不反复打接口），
        #   过了就重新试 —— 这样「一次网络抖动」不会让某个 ID 永远没封面。
        if item and not item.get("ok"):
            age = time.time() - float(item.get("fetched_at") or 0)
            if age < 1800:
                return item
        return None

    def put(self, wid: str, info: dict) -> None:
        with self._lock:
            self._meta[str(wid)] = info
        self.save()

    # ------------------------------------------------------------ 查询
    def fetch(self, wids: Iterable[str], progress: Callable[[int, int], None] | None = None) -> dict[str, dict]:
        """批量查询工坊信息，返回 {id: {title, preview, ...}}。"""
        ids = [str(w) for w in wids if w]
        out: dict[str, dict] = {}
        # 先吃缓存
        todo = []
        for wid in ids:
            hit = self.cached(wid)
            if hit:
                out[wid] = hit
            else:
                todo.append(wid)

        total = len(todo)
        done = 0
        # API 一次最多几百个，这里按 20 个一批
        for i in range(0, len(todo), 20):
            batch = todo[i: i + 20]
            details = self._query_batch(batch)

            got = {}
            for f in details:
                wid = str(f.get("publishedfileid") or "")
                if not wid:
                    continue
                ok = f.get("result") == 1
                raw_tags = f.get("tags") or []
                tags = [
                    str(t.get("tag") or "").strip()
                    for t in raw_tags
                    if isinstance(t, dict) and str(t.get("tag") or "").strip()
                ]
                info = {
                    "id": wid,
                    "title": (f.get("title") or "").strip() if ok else "",
                    "preview": (f.get("preview_url") or "") if ok else "",
                    # 中转站额外给了多张预览图（官方 API 也有，但常常是空的）。
                    # 存下来给「多封面」用；没有就是空列表。
                    "previews": [
                        str(u) for u in (f.get("previews") or [])
                        if isinstance(u, str) and u.strip()
                    ][:12] if ok else [],
                    "desc": (f.get("description") or "")[:400] if ok else "",
                    "size": int(f.get("file_size") or 0),
                    "created": int(f.get("time_created") or 0),
                    "updated": int(f.get("time_updated") or 0),
                    "author": str(f.get("creator") or ""),
                    "tags": tags if ok else [],
                    "category": category_from_tags(tags) if ok else "",
                    "views": int(f.get("views") or 0),
                    "subs": int(f.get("subscriptions") or 0),
                    "ok": bool(ok and f.get("title")),
                    "fetched_at": int(time.time()),
                }
                got[wid] = info
                out[wid] = info
                if info["ok"]:
                    self.put(wid, info)

            # 查不到也记一笔，避免每次都重查；网络失败的不记，方便重试
            if details:
                for wid in batch:
                    if wid not in got:
                        miss = {"id": wid, "title": "", "ok": False, "fetched_at": int(time.time())}
                        out[wid] = miss
                        self._meta[wid] = miss

            done += len(batch)
            if progress:
                progress(done, total)
            self.save()
            time.sleep(0.15)  # 别把 API 打太急
        return out

    @staticmethod
    def _query_batch(ids: list[str]) -> list[dict]:
        """查一批工坊 ID，返回 publishedfiledetails 数组。

        ★ 只走 **Steam 官方** `ISteamRemoteStorage/GetPublishedFileDetails`。

        历史说明（2026-11 变更）：这里原来优先调用第三方运营的中转服务
        （`l4d2-workshop.laoyutang.cn`），那是 LytVPK 维护者的线上服务，
        会占用对方的 Cloudflare Workers 与 Steam Web API 额度，
        对方已在 issue #1 中要求迁移 —— 现在**不再调用任何第三方中转**。

        实测官方接口在国内可用（走 `netclient` 的系统证书，0.2 秒内返回），
        所以也不再需要「先中转、失败再官方」那套兜底。
        """
        return WorkshopClient._query_official(ids)

    @staticmethod
    def _query_relay(wid: str) -> dict:
        """（已停用）原第三方中转查询，保留函数名只为兼容老代码的 hasattr 检查。

        ★ 现在**永远返回空**，所有请求都走 `_query_official`。
          保留它是因为外部脚本 / 测试可能引用这个名字，
          直接删掉会变成 AttributeError。
        """
        return {}

    @staticmethod
    def _query_official(ids: list[str]) -> list[dict]:
        """官方 GetPublishedFileDetails（POST、按批），带短超时重试。

        走 `netclient` 的统一 Session：系统证书 + certifi，
        否则国内装了加速工具时这里会 SSLCertVerificationError 直接失败。
        """
        payload = {"itemcount": len(ids)}
        for j, wid in enumerate(ids):
            payload[f"publishedfileids[{j}]"] = wid

        last_err = ""
        for attempt in range(3):
            try:
                r = NC.post(
                    WORKSHOP_API,
                    data=payload,
                    headers={
                        "User-Agent": UA,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    timeout=(5, 12),
                )
                if r.status_code == 200:
                    js = r.json()
                    det = (js.get("response") or {}).get("publishedfiledetails")
                    if det is not None:
                        return det
                last_err = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                last_err = f"{e.__class__.__name__}"
            log(f"workshop query retry {attempt + 1}/3: {last_err}")
            if attempt < 2:
                time.sleep(0.6 + attempt * 0.7)

        log(f"workshop query failed for {len(ids)} ids: {last_err}")
        return []

    def download_cover(self, wid: str, preview_url: str) -> str:
        """把封面下载到本地缓存，返回路径。"""
        if not preview_url:
            return ""
        ext = ".jpg"
        low = preview_url.lower()
        for e in IMAGE_EXTS:
            if low.endswith(e):
                ext = e
                break
        path = os.path.join(CACHE_DIR, f"{wid}{ext}")
        if os.path.exists(path) and os.path.getsize(path) > 1024:
            return path
        try:
            r = requests.get(preview_url, timeout=25, headers={"User-Agent": UA})
            if r.status_code == 200 and len(r.content) > 1024:
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(r.content)
                os.replace(tmp, path)
                return path
        except Exception as e:  # noqa: BLE001
            log(f"cover download failed {wid}: {e!r}")
        return ""

    def page_url(self, wid: str) -> str:
        return WORKSHOP_PAGE.format(wid)

    # ------------------------------------------------------------ 作者昵称
    def author_name(self, steamid: str) -> str:
        """SteamID → Steam 昵称，取不到就返回空串（调用方显示 SteamID）。

        工坊接口只给 creator 的 64 位 SteamID，昵称得另外查。两条路：
          1. 本地缓存（查过就不再来回请求）
          2. steamcommunity.com/profiles/<id>/?xml=1（**Steam 自家域名**，无需 key）
        哪条成功就把结果记下来，失败也记一笔（24 小时内不重复撞墙）。

        ★ 2026-11 变更：原来还有一条 `steamid.io` 第三方兜底，已**删除**。
          那是外部站点，而本项目对外只依赖 Steam 自己的服务。
          官方 `ISteamUser/GetPlayerSummaries` 能替代它，但**强制要求 Steam API Key**
          （实测无 key 直接 400 "Required parameter 'key' is missing"，
          假 key 是 403），不配 key 的机器上等于不可用，所以没接进这条链。
          XML 这条拿不到昵称时，UI 就显示 SteamID —— 不为了一个昵称去请求第三方站。
        """
        sid = str(steamid or "").strip()
        if not sid.isdigit():
            return ""
        with self._author_lock:
            hit = self._authors.get(sid) or {}
        if hit.get("name"):
            return str(hit["name"])
        # 失败过的短时间内不再重试，避免每次扫描都卡在网络上
        if hit and int(hit.get("checked_at") or 0) > time.time() - 86400:
            return ""

        name = self._fetch_author_community(sid)
        entry = {"name": name or "", "checked_at": int(time.time())}
        with self._author_lock:
            self._authors[sid] = entry
        _atomic_json(AUTHOR_PATH, self._authors)
        return name

    def cached_author_name(self, steamid: str) -> str:
        """只读缓存，不发网络请求（扫描/刷新列表时用，不阻塞 UI）。"""
        sid = str(steamid or "").strip()
        if not sid:
            return ""
        with self._author_lock:
            hit = self._authors.get(sid) or {}
        return str(hit.get("name") or "")

    def fetch_author_names(self, steamids: Iterable[str],
                           progress: Callable[[int, int], None] | None = None) -> dict[str, str]:
        """批量补昵称（后台线程调用）。返回 {steamid: 昵称}，查不到的值为空串。"""
        ids: list[str] = []
        seen: set[str] = set()
        for raw in steamids:
            sid = str(raw or "").strip()
            if sid.isdigit() and sid not in seen:
                seen.add(sid)
                ids.append(sid)
        out: dict[str, str] = {}
        for i, sid in enumerate(ids, start=1):
            out[sid] = self.author_name(sid)
            if progress:
                progress(i, len(ids))
            time.sleep(0.25)   # 别把第三方站点打太急
        return out

    @staticmethod
    def _fetch_author_community(sid: str) -> str:
        url = f"https://steamcommunity.com/profiles/{sid}/?xml=1"
        try:
            r = requests.get(url, timeout=(6, 12), headers={"User-Agent": UA})
            if r.status_code != 200:
                return ""
            m = re.search(r"<steamID><!\[CDATA\[(.+?)\]\]></steamID>", r.text, re.S)
            if m:
                return html.unescape(m.group(1)).strip()
            m = re.search(r"<steamID>(.+?)</steamID>", r.text, re.S)
            if m:
                return html.unescape(m.group(1)).strip()
        except Exception as e:  # noqa: BLE001
            log(f"author community lookup failed {sid}: {e.__class__.__name__}")
        return ""


# ===========================================================================
# MOD 条目
# ===========================================================================
def _find_image_for(addons_dir: str, stem: str) -> str:
    """找同名的图片文件（132381280.jpg / .png 等）。"""
    for ext in IMAGE_EXTS:
        for cand in (stem + ext, stem + ext.upper()):
            p = os.path.join(addons_dir, cand)
            if os.path.isfile(p):
                return p
    return ""


def read_mod_info(path: str, addons_dir: str, workshop_dir: str) -> dict:
    """读取单个 vpk 的信息（不打开 vpk，只看文件系统）。"""
    name = os.path.basename(path)
    # 被本程序禁用的 mod 会改名成 xxx.vpk.disabled，
    # 这里要把两个后缀都剥掉，否则同名封面图和工坊 ID 都会认不出来。
    enabled = not name.lower().endswith(DISABLED_SUFFIX)
    base = name[: -len(DISABLED_SUFFIX)] if not enabled else name
    stem = os.path.splitext(base)[0]
    folder = os.path.dirname(os.path.abspath(path))
    is_workshop_dir = os.path.normcase(folder) == os.path.normcase(workshop_dir)
    wid = workshop_id_of(stem)

    try:
        st = os.stat(path)
        size = st.st_size
        mtime = int(st.st_mtime)
    except OSError:
        size = 0
        mtime = 0

    img = _find_image_for(folder, stem)
    # 云 mod 的封面可能在 addons 根目录（Steam 下载的习惯）
    if not img and is_workshop_dir and addons_dir:
        img = _find_image_for(addons_dir, stem)

    return {
        "path": os.path.abspath(path),
        "name": name,
        "stem": stem,
        "dir": folder,
        "size": size,
        "sizeText": human_size(size),
        "mtime": mtime,
        # 导入日期：台账里有就用台账（这个工具真正导入/转换过来的时间），
        # 没有就退回文件 mtime（用户自己拷进来的，只能看文件时间）。
        "importTs": import_ts_of(stem, fallback=mtime),
        "image": img,
        "workshopId": wid,
        "isWorkshop": bool(wid),
        "inWorkshopDir": is_workshop_dir,
        "enabled": enabled,
    }


def _is_mod_file(name: str) -> bool:
    """是不是一个 mod 文件（含被禁用的 .vpk.disabled）."""
    low = name.lower()
    return low.endswith(".vpk") or low.endswith(DISABLED_SUFFIX)


def scan_mods(addons_dir: str) -> dict:
    """扫描 addons 目录，返回 {"local": [...], "workshop": [...]}。

    注意：**必须把 .vpk.disabled 也算进来**。否则用户一旦批量禁用，
    这些 mod 就会从列表里彻底消失，再也无法在界面里启用回来。
    """
    local_dir = addons_dir
    ws_dir = os.path.join(addons_dir, "workshop")
    out = {"local": [], "workshop": []}

    if os.path.isdir(local_dir):
        for entry in os.scandir(local_dir):
            if entry.is_file() and _is_mod_file(entry.name):
                out["local"].append(read_mod_info(entry.path, local_dir, ws_dir))

    if os.path.isdir(ws_dir):
        for entry in os.scandir(ws_dir):
            if entry.is_file() and _is_mod_file(entry.name):
                out["workshop"].append(read_mod_info(entry.path, local_dir, ws_dir))

    for key in ("local", "workshop"):
        out[key].sort(key=lambda m: m["stem"].lower())
    return out


# ===========================================================================
# 操作：导入 / 删除 / 启用 / 移植
# ===========================================================================
def _archive_member_names(archive_path: str) -> tuple[list[str], str]:
    """列出压缩包里的成员名（不解压）。返回 `(名字列表, 错误)`。

    zip 走标准库；7z / rar / tar 家族走 Windows 自带的 `tar.exe`
    （bsdtar + libarchive，原生认这些格式，不用装 7-Zip / WinRAR）。
    """
    low = str(archive_path or "").lower()
    if low.endswith(".zip"):
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                return [n for n in zf.namelist() if not n.endswith("/")], ""
        except (zipfile.BadZipFile, OSError) as e:
            return [], f"压缩包打不开：{e}"
    tar = shutil.which("tar")
    if not tar:
        return [], "系统没有可用的解压工具（缺 tar.exe）"
    try:
        out = subprocess.run(
            [tar, "-t", "-f", archive_path],
            capture_output=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as e:
        return [], f"列目录失败：{e}"
    if out.returncode != 0:
        msg = (out.stderr or b"").decode("utf-8", "replace").strip()
        return [], f"认不出这个压缩包格式（{msg[:80]}）"
    names = []
    for raw in (out.stdout or b"").decode("utf-8", "replace").splitlines():
        n = raw.strip()
        if n and not n.endswith("/"):
            names.append(n.lstrip("./"))
    return names, ""


def _extract_archive(archive_path: str) -> tuple[list[str], list[str], str]:
    """把 zip 解压到临时目录，返回 (vpk 列表, 封面图列表, 临时目录)。

    只解压 .vpk 和常见封面图，其余内容（readme、文件夹等）忽略。
    解压出来的文件统一摊平放在临时目录（同名封面因此能和 vpk 配对上），
    导入完成后由调用方清理这个临时目录。

    ★ zip 走标准库逐个成员写盘（顺便防路径穿越）；7z / rar / tar 家族
      先整包解到 tmp/_raw，再把需要的摊平搬上来 —— bsdtar 没法只挑
      部分成员稳定工作。
    """
    extracted_vpk: list[str] = []
    extracted_img: list[str] = []
    tmp = tempfile.mkdtemp(prefix="l4d2_archive_")
    low = str(archive_path or "").lower()

    if not low.endswith(".zip"):
        raw_dir = os.path.join(tmp, "_raw")
        os.makedirs(raw_dir, exist_ok=True)
        tar = shutil.which("tar")
        if not tar:
            shutil.rmtree(tmp, ignore_errors=True)
            log(f"no tar.exe for {archive_path}")
            return [], [], ""
        try:
            out = subprocess.run(
                [tar, "-x", "-f", archive_path, "-C", raw_dir],
                capture_output=True, timeout=600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if out.returncode != 0:
                msg = (out.stderr or b"").decode("utf-8", "replace").strip()
                log(f"extract {archive_path} failed: {msg[:120]}")
                shutil.rmtree(tmp, ignore_errors=True)
                return [], [], ""
        except (OSError, subprocess.SubprocessError) as e:
            log(f"extract {archive_path} failed: {e!r}")
            shutil.rmtree(tmp, ignore_errors=True)
            return [], [], ""
        for dirpath, _dirs, names in os.walk(raw_dir):
            for name in names:
                nl = name.lower()
                if not (nl.endswith(".vpk") or nl.endswith(IMAGE_EXTS)):
                    continue
                target = os.path.join(tmp, name)
                if os.path.exists(target):
                    continue
                try:
                    shutil.copyfile(os.path.join(dirpath, name), target)
                except OSError as e:
                    log(f"flatten {name} failed: {e!r}")
                    continue
                if nl.endswith(".vpk"):
                    extracted_vpk.append(target)
                else:
                    extracted_img.append(target)
        shutil.rmtree(raw_dir, ignore_errors=True)
        return extracted_vpk, extracted_img, tmp

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                name = info.filename
                # 跳过目录
                if name.endswith("/"):
                    continue
                lc = name.lower()
                base = os.path.basename(name)
                # 只关心 vpk 和封面图
                if lc.endswith(".vpk"):
                    target = os.path.join(tmp, base)
                elif lc.endswith(IMAGE_EXTS):
                    target = os.path.join(tmp, base)
                else:
                    continue
                # 防 zip 路径穿越
                if os.path.isabs(base) or ".." in base:
                    continue
                # 摊平后重名的跳过（保留先出现的那个）
                if os.path.exists(target):
                    continue
                try:
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                except (OSError, zipfile.BadZipFile) as e:
                    log(f"extract {name} failed: {e}")
                    continue
                if lc.endswith(".vpk"):
                    extracted_vpk.append(target)
                else:
                    extracted_img.append(target)
    except (zipfile.BadZipFile, OSError) as e:
        log(f"bad zip {archive_path}: {e}")
        shutil.rmtree(tmp, ignore_errors=True)
        return [], [], ""
    return extracted_vpk, extracted_img, tmp


def inspect_import_paths(paths: Iterable[str]) -> dict:
    """只读地「预演」一次导入：返回会导入哪些文件、压缩包里有多少个。

    不真正解压（只读压缩包的目录），确认框用它显示「N 个文件」+ 前几个文件名。

    返回里除了老的 `count/names/archives`，还多一个 `items`：
    每个文件一条 `{name, kind, archive}`，**顺序 = 勾选框的顺序**，
    默认全选。界面据此让用户逐条勾掉不要的（用户要的「提示勾选，
    默认全选」就是这个）。

    ★ `items` 和 `names` 必须**来自同一次扫描**：以前界面只拿到 names，
      再自己去猜哪个是 .vpk、哪个是封面，一旦压缩包里有同名图就会错位。
    """
    names: list[str] = []
    archives: list[str] = []
    items: list[dict] = []

    for raw in paths:
        p = os.path.abspath(str(raw))
        if not os.path.isfile(p):
            continue
        low = p.lower()
        if low.endswith(ARCHIVE_EXTS):
            archives.append(os.path.basename(p))
            members, err = _archive_member_names(p)
            if err:
                log(f"inspect archive failed {p}: {err}")
                continue
            vpks: list[str] = []
            imgs: dict[str, str] = {}
            for member in members:
                b = os.path.basename(member)
                lb = b.lower()
                if lb.endswith(".vpk"):
                    vpks.append(b)
                elif lb.endswith(IMAGE_EXTS):
                    imgs.setdefault(os.path.splitext(b)[0].lower(), b)
            for v in vpks:
                names.append(v)
                items.append({"name": v, "kind": "mod",
                              "archive": os.path.basename(p)})
            # 压缩包里的封面图也会一起导入（同名封面跟着 vpk 走，孤儿图也照导）
            for b in imgs.values():
                names.append(b)
                items.append({"name": b, "kind": "image",
                              "archive": os.path.basename(p)})
        elif low.endswith(".vpk"):
            names.append(os.path.basename(p))
            items.append({"name": os.path.basename(p), "kind": "mod",
                          "archive": ""})
            # 同目录同名封面也会自动带上
            stem = os.path.splitext(os.path.basename(p))[0]
            try:
                entries = {
                    e.name.lower(): e.name
                    for e in os.scandir(os.path.dirname(p))
                    if e.is_file()
                }
            except OSError:
                entries = {}
            for ext in IMAGE_EXTS:
                real = entries.get((stem + ext).lower())
                if real:
                    names.append(real)
                    items.append({"name": real, "kind": "image",
                                  "archive": ""})
                    break
        elif low.endswith(IMAGE_EXTS):
            names.append(os.path.basename(p))
            items.append({"name": os.path.basename(p), "kind": "image",
                          "archive": ""})

    # 去重（保持顺序）
    seen: set[str] = set()
    uniq: list[str] = []
    uniq_items: list[dict] = []
    for n, it in zip(names, items):
        k = n.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(n)
        uniq_items.append(it)

    return {"count": len(uniq), "names": uniq, "archives": archives,
            "items": uniq_items}


def import_files(paths: Iterable[str], addons_dir: str, workshop: WorkshopClient | None = None,
                 only: Iterable[str] | None = None) -> dict:
    """把文件（含 zip 压缩包）导入 addons 目录。

    压缩包会先解到临时目录（只挑 .vpk 和封面图），走和普通文件完全一样的复制流程，
    结束后临时目录一定删掉。

    `only`：只导入这些文件名（不区分大小写，按 basename 比）。
      给了它就**严格按勾选来** —— 用户在确认框里取消勾选的东西不该偷偷导入。
      不给（None）保持原来的「全都导入」行为，兼容所有老调用点。
    """
    wanted = None
    if only is not None:
        wanted = {str(x).strip().lower() for x in only if str(x).strip()}
        if not wanted:
            # 用户把所有勾都取消了：什么都不做，别把整包倒进去
            return {"ok": False, "error": "没有勾选任何文件", "copied": [],
                    "skipped": [], "locked": [], "errors": []}

    tmp_dirs: list[str] = []
    expanded: list[str] = []
    for raw in paths:
        p = os.path.abspath(str(raw))
        if os.path.isfile(p) and p.lower().endswith(ARCHIVE_EXTS):
            vpks, imgs, tmp = _extract_archive(p)
            expanded.extend(vpks)
            expanded.extend(imgs)
            if tmp:
                tmp_dirs.append(tmp)
        else:
            expanded.append(raw)

    if wanted is not None:
        expanded = [p for p in expanded
                    if os.path.basename(p).lower() in wanted]

    try:
        return _import_files_impl(expanded, addons_dir, workshop)
    finally:
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)


def _import_files_impl(
    paths: Iterable[str], addons_dir: str, workshop: WorkshopClient | None = None
) -> dict:
    """把文件导入 addons 目录.

    规则：
      * .vpk 一律复制进去；
      * 如果同名的图片（1122.jpg）存在，**自动一起复制**，即使用户没选它；
      * 用户手动选的图片也复制。

    文件被占用（游戏正在跑 / 目标文件被别的程序打开）时的处理：
      * 源文件读不出来 → 跳过这一个，**其它的照常导入**，绝不半途而废；
      * 目标位置已有同名文件且被占用 → 跳过这一个，其它照常；
      * 有任何一个失败都放进 ``locked``，界面据此提示「关掉游戏或 MOD 再试」。
    """
    addons_dir = normalize_addons_dir(addons_dir)
    if not addons_dir:
        return {"ok": False, "error": "还没有设置 MOD 目录", "copied": [],
                "skipped": [], "locked": [], "errors": []}

    os.makedirs(addons_dir, exist_ok=True)
    copied: list[str] = []
    skipped: list[str] = []
    locked: list[str] = []
    errors: list[str] = []

    planned: list[tuple[str, str]] = []  # (src, dst_dir)
    seen_src: set[str] = set()

    for raw in paths:
        src = os.path.abspath(str(raw))
        if not os.path.isfile(src):
            skipped.append(os.path.basename(src))
            continue
        low = src.lower()

        if low.endswith(".vpk"):
            planned.append((src, addons_dir))
            stem = os.path.splitext(os.path.basename(src))[0]
            # 顺带把同名图片带上（大小写不敏感，同一张图只加一次）
            base = os.path.dirname(src)
            added_img = False
            try:
                entries = {e.name.lower(): e.name for e in os.scandir(base) if e.is_file()}
            except OSError:
                entries = {}
            for ext in IMAGE_EXTS:
                for want in (stem + ext,):
                    real = entries.get(want.lower())
                    if not real or added_img:
                        continue
                    p = os.path.join(base, real)
                    if os.path.isfile(p) and p not in seen_src:
                        planned.append((p, addons_dir))
                        seen_src.add(p)
                        added_img = True
            seen_src.add(src)
        elif low.endswith(IMAGE_EXTS):
            # 可能已经被上面「vpk 自动带同名封面」加过一次了，别重复
            if src not in seen_src:
                planned.append((src, addons_dir))
                seen_src.add(src)
        else:
            skipped.append(os.path.basename(src))

    imported: list[str] = []
    for src, dst_dir in planned:
        dst = os.path.join(dst_dir, os.path.basename(src))
        # 源文件被占用（多半是游戏正拿着它）—— 直接跳过，别把整个导入搞崩
        if is_locked(src):
            locked.append(os.path.basename(src))
            continue
        try:
            if os.path.exists(dst):
                # 同名文件：大小一致就当作已存在
                if os.path.getsize(dst) == os.path.getsize(src):
                    skipped.append(os.path.basename(src))
                    continue
                base, ext = os.path.splitext(dst)
                n = 1
                while os.path.exists(f"{base}_{n}{ext}"):
                    n += 1
                dst = f"{base}_{n}{ext}"
            shutil.copy2(src, dst)
            copied.append(os.path.basename(dst))
            imported.append(os.path.basename(dst))
        except PermissionError:
            locked.append(os.path.basename(src))
        except OSError as e:
            errors.append(f"{os.path.basename(src)}: {e}")

    # 导入成功的记一笔「导入日期」（同名封面图不记，只看 vpk）
    record_imports([n for n in imported if not n.lower().endswith(IMAGE_EXTS)])

    log(f"import: copied={len(copied)} skipped={len(skipped)} "
        f"locked={len(locked)} errors={len(errors)}")
    return {
        "ok": bool(copied),
        "addonsDir": addons_dir,
        "copied": copied,
        "skipped": skipped,
        "locked": locked,
        "errors": errors,
        "gameRunning": is_game_running(),
    }


def is_game_running() -> bool:
    """游戏是否在跑：移植/导入时文件会被 left4dead2.exe 占用。"""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq left4dead2.exe", "/NH"],
            capture_output=True, timeout=8, creationflags=0x08000000,
        )
        text = (out.stdout or b"").decode("utf-8", "ignore").lower()
        return "left4dead2.exe" in text
    except Exception as e:  # noqa: BLE001
        log(f"tasklist failed: {e!r}")
        return False


def is_locked(path: str) -> bool:
    """文件是否被别的进程占用（游戏正在加载这个 vpk 时改名会失败）。

    以 rb+ 方式打开试一下：Windows 上被独占打开的文件会抛 PermissionError。
    """
    try:
        with open(path, "rb+"):
            return False
    except PermissionError:
        return True
    except OSError:
        return True


def copy_workshop_to_local(addons_dir: str, names: Iterable[str] | None = None) -> dict:
    """把云 mod（workshop 目录）**复制**到本地 addons 根目录.

    names 为空时表示全部转换。

    为什么是复制而不是移动：workshop 里的文件是 Steam 订阅管理的对象，
    挪走会让 Steam 认为订阅丢失并重新下载（之前那个 860MB 的 MOD 变成 3 份
    就是这么来的）。本地这份才是用户真正掌控的。

    安全性：一个 MOD 的 vpk 和它的同名封面图要一起走。只要其中任意一个被占用，
    整个 MOD 就**不动**（早期实现是逐个 move，vpk 挪走了、图片被占用没挪走，
    结果封面丢失）。
    """
    addons_dir = normalize_addons_dir(addons_dir)
    ws_dir = os.path.join(addons_dir, "workshop")
    if not os.path.isdir(ws_dir):
        return {"ok": False, "error": "没有 workshop 目录", "moved": [], "errors": [], "blocked": []}

    wanted = {str(n) for n in names} if names else None
    moved: list[str] = []
    errors: list[str] = []
    blocked: list[str] = []

    entries = [e for e in os.scandir(ws_dir) if e.is_file()]
    if wanted is not None:
        entries = [e for e in entries if e.name in wanted]

    # 按「模组」分组：xxx.vpk / xxx.vpk.disabled 各带上它的同名图
    groups: dict[str, list[str]] = {}
    loose: list[str] = []
    for entry in entries:
        low = entry.name.lower()
        if low.endswith(".vpk") or low.endswith(DISABLED_SUFFIX):
            stem = os.path.splitext(
                entry.name[: -len(".disabled")] if low.endswith(DISABLED_SUFFIX) else entry.name
            )[0]
            groups.setdefault(stem.lower(), []).append(entry.path)
            for ext in IMAGE_EXTS:
                for cand in (stem + ext, stem + ext.upper()):
                    p = os.path.join(ws_dir, cand)
                    if os.path.isfile(p) and p not in groups[stem.lower()]:
                        groups[stem.lower()].append(p)
        else:
            loose.append(entry.path)

    def _target_for(src: str) -> str:
        dst = os.path.join(addons_dir, os.path.basename(src))
        if os.path.exists(dst):
            # 大小一样说明本地已经有同一份了，不必再复制
            if os.path.getsize(dst) == os.path.getsize(src):
                return ""
            base, ext = os.path.splitext(dst)
            n = 1
            while os.path.exists(f"{base}_{n}{ext}"):
                n += 1
            dst = f"{base}_{n}{ext}"
        return dst

    for group in list(groups.values()) + [[p] for p in loose]:
        locked = [p for p in group if is_locked(p)]
        if locked:
            blocked.append(os.path.basename(group[0]))
            errors.append(f"{os.path.basename(locked[0])}: 文件被占用")
            continue
        done: list[tuple[str, str]] = []
        try:
            for src in group:
                dst = _target_for(src)
                if not dst:
                    continue
                shutil.copy2(src, dst)
                done.append((src, dst))
            moved.extend(os.path.basename(d) for _, d in done)
        except OSError as e:
            # 中途失败就把已经复制过去的删掉，避免半个 MOD 散在两个目录
            for _, dst in reversed(done):
                try:
                    os.remove(dst)
                except OSError:
                    pass
            errors.append(f"{os.path.basename(group[0])}: {e}")

    # 复制到本地的记一笔「导入日期」
    record_imports([n for n in moved if not n.lower().endswith(IMAGE_EXTS)])

    log(f"workshop->local copy: {len(moved)} copied, {len(blocked)} blocked, {len(errors)} errors")
    return {
        "ok": bool(moved),
        "moved": moved,
        "errors": errors,
        "blocked": blocked,
        "gameRunning": is_game_running(),
    }


def set_enabled(mod: dict, enabled: bool) -> str:
    """启用/禁用 mod：改扩展名为 .vpk.disabled（游戏不会加载）。

    返回：新路径（成功，或本来就是目标状态无需操作）；
         空串（失败，比如文件不存在、被游戏占用改不了名）。
    之前失败时返回原 path，调用方无法区分「失败」和「已是目标状态」，
    导致批量禁用时个别被占用失败的 MOD 也被算成成功、不提示。
    """
    path = mod.get("path") or ""
    if not os.path.isfile(path):
        return ""
    try:
        if enabled:
            if path.lower().endswith(DISABLED_SUFFIX):
                new = path[: -len(".disabled")]
                os.replace(path, new)
                return new
            return path
        else:
            if not path.lower().endswith(DISABLED_SUFFIX):
                new = path + ".disabled"
                os.replace(path, new)
                return new
            return path
    except OSError as e:
        log(f"toggle failed {path}: {e}")
        return ""


def companion_files(path: str) -> list[str]:
    """MOD 文件本身 + 它的同名封面图。

    `469986973.vpk` 配 `469986973.jpg`，删 MOD 时这张图也该一起走，
    不然会留下一堆没人认领的孤儿图。启用/禁用改过名的也能认出来
    （会先把 `.vpk.disabled` 剥掉再比名字）。
    """
    out = [path]
    if not os.path.isfile(path):
        return out
    folder = os.path.dirname(path)
    name = os.path.basename(path)
    if name.lower().endswith(DISABLED_SUFFIX):
        name = name[: -len(DISABLED_SUFFIX)]
    stem = os.path.splitext(name)[0].lower()
    if not stem:
        return out
    try:
        for entry in os.scandir(folder):
            if not entry.is_file():
                continue
            base, ext = os.path.splitext(entry.name)
            if base.lower() == stem and ext.lower() in IMAGE_EXTS:
                out.append(entry.path)
    except OSError as e:
        log(f"companion_files scan failed {folder}: {e}")
    return out


def _send_to_recycle_bin(paths: list[str]) -> tuple[list[str], list[str]]:
    """把文件丢进回收站（不是直接抹掉）。

    用的是 shell32 的 SHFileOperationW + FOF_ALLOWUNDO —— 这正是资源管理器
    “删除”走的那条路，所以删错了还能从回收站捞回来。

    返回 (成功移动的文件名列表, 错误信息列表)。
    """
    if os.name != "nt":
        return [], ["当前系统不支持回收站"]

    import ctypes
    from ctypes import wintypes

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040
    FOF_NOERRORUI = 0x0400

    names = [os.path.basename(p) for p in paths]
    # pFrom 必须是“双 null 结尾”的一整串，每段一个路径
    joined = "\0".join(os.path.abspath(p) for p in paths) + "\0\0"

    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = joined
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI

    try:
        shell32 = ctypes.windll.shell32
        shell32.SHFileOperationW.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCTW)]
        shell32.SHFileOperationW.restype = ctypes.c_int
        rc = shell32.SHFileOperationW(ctypes.byref(op))
    except Exception as e:  # noqa: BLE001
        return [], [f"回收站调用失败: {e}"]

    if rc != 0:
        return [], [f"回收站返回错误码 {rc}"]
    if op.fAnyOperationsAborted:
        return [], ["操作被取消"]

    # 复核：确认文件真的不在了
    still = [n for n, p in zip(names, paths) if os.path.exists(p)]
    moved = [n for n, p in zip(names, paths) if not os.path.exists(p)]
    return moved, [f"{n}: 仍在原处" for n in still]


def delete_files(paths: Iterable[str], to_recycle: bool = True) -> dict:
    """删除 MOD。

    `to_recycle=True`（默认）走回收站，删错了能捞回来。
    用户在设置里选了「直接删除」时传 False，就是真删。
    """
    wanted = [p for p in paths if os.path.isfile(p)]
    if not wanted:
        return {"ok": False, "removed": [], "errors": [], "recycled": False}

    # 被占用的（游戏正加载）删不掉，先挑出来，别让一个文件拖死整批
    locked = [p for p in wanted if is_locked(p)]
    usable = [p for p in wanted if p not in locked]
    if not usable:
        return {
            "ok": False,
            "removed": [],
            "errors": [f"{os.path.basename(p)}: 文件被占用" for p in locked],
            "recycled": False,
            "locked": [os.path.basename(p) for p in locked],
        }

    errors: list[str] = []
    result = {"ok": False, "removed": [], "errors": [], "recycled": False}
    if to_recycle:
        moved, errors = _send_to_recycle_bin(usable)
        if moved:
            result = {"ok": True, "removed": moved, "errors": errors, "recycled": True}
            forget_imports(moved)
            result["locked"] = [os.path.basename(p) for p in locked]
            return result
        if not errors:
            errors = ["回收站不可用"]
        log(f"recycle bin unavailable ({errors[:2]}), fell back to os.remove")

    # 直接删除：用户在设置里选了「直接删除」，或回收站不可用时的兜底
    removed: list[str] = []
    for p in usable:
        try:
            os.remove(p)
            removed.append(os.path.basename(p))
        except OSError as e:
            errors.append(f"{os.path.basename(str(p))}: {e}")
    forget_imports(removed)
    return {"ok": bool(removed), "removed": removed, "errors": errors,
            "recycled": False, "locked": [os.path.basename(p) for p in locked]}


def open_in_explorer(path: str, select: str = "") -> None:
    try:
        if select and os.path.exists(select):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(select)])
        elif os.path.isdir(path):
            os.startfile(path)  # noqa: S606
    except OSError as e:
        log(f"open explorer failed: {e}")
