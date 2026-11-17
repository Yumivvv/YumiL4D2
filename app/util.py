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

"""通用小工具：路径、时间格式化、日志."""
from __future__ import annotations

import datetime as _dt
import html
import os
import re
import shutil
import sys
import time

# 打包后（PyInstaller）为 True
FROZEN = bool(getattr(sys, "frozen", False))


def _bundle_root() -> str:
    """程序自带资源（qml / assets / 默认音效）所在目录。

    单文件 exe 运行时，PyInstaller 会把资源解到临时目录并通过 `_MEIPASS` 告诉我们；
    开发时就是项目根目录。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return os.path.abspath(meipass)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _user_root() -> str:
    """用户数据该放哪儿：**打包后放 exe 旁边**，开发时就是项目根。

    以前一律用 `__file__` 往上推，打包成单文件后那会指到 PyInstaller 的临时解包目录
    （退出即删），用户数据每次都会被清空。
    """
    if FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 程序自带资源目录（只读）
ROOT = _bundle_root()
# 用户数据目录（可写，打包后就是 exe 所在目录）
USER_ROOT = _user_root()

# 运行时数据目录。默认在程序目录下的 data/，
# 但允许用环境变量 L4D2_DATA_DIR 整个指到别处 —— 测试靠它把数据隔离到临时目录，
# 这样跑测试永远不会覆盖用户真实的 config.json / library.json / 导入日期台账。
DATA_DIR = os.environ.get("L4D2_DATA_DIR") or os.path.join(USER_ROOT, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
COVER_DIR = os.path.join(DATA_DIR, "covers")
LOG_DIR = os.path.join(DATA_DIR, "logs")
# 自定义提示音目录：用户导入的音效都放这儿，配置里只存文件名
SOUNDS_DIR = os.path.join(USER_ROOT, "sounds")
# 自定义背景图目录：用户导入的壁纸都放这儿，配置里同样只存文件名。
# 同样支持用环境变量覆盖 —— 测试要靠它隔离，
# 因为「移除背景」现在是**真的删文件**，不隔离就会把用户那张壁纸删掉。
BG_DIR = os.environ.get("L4D2_BG_DIR") or os.path.join(USER_ROOT, "backgrounds")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\u3000]+")


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR, COVER_DIR, LOG_DIR, SOUNDS_DIR, BG_DIR):
        os.makedirs(d, exist_ok=True)


# 首次运行时要从旧布局搬过来的小文件（缓存类不搬，体积大且能重建）
_LEGACY_FILES = ("config.json", "library.json", "library.bak.json",
                 "modimports.json", "favorites.json", "authors.json", "modmeta.json")


def _looks_fresh() -> bool:
    """用户数据目录还是空的吗（没有配置也没有库）。"""
    return not os.path.exists(os.path.join(DATA_DIR, "config.json"))


def _migrate_legacy_data() -> None:
    """从「打包进程序目录」的旧布局搬一次数据。

    以前的文件夹版把 data/ 放在 `_internal` 里，单文件版改成 exe 旁边之后，
    老用户一升级会看着像「数据没了」。只在新的 data/ 还没有 config.json 时搬一次。
    """
    if not FROZEN or not _looks_fresh():
        return
    old = os.path.join(ROOT, "data")
    if os.path.abspath(old) == os.path.abspath(DATA_DIR) or not os.path.isdir(old):
        return
    for name in _LEGACY_FILES:
        src = os.path.join(old, name)
        dst = os.path.join(DATA_DIR, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass


def seed_user_dirs() -> None:
    """建好用户目录，并塞进「第一次运行需要的东西」。

    1. 该有的文件夹全部创建（data / cache / covers / logs / sounds / backgrounds）
    2. sounds 目录空的话，把程序自带的默认提示音复制进去
       （单文件版的自带音效在解包目录里，用户看不见也不好管理，
       复制一份出来他才能在设置里「打开目录」看到并替换）
    3. 老版本数据搬一次家
    """
    ensure_dirs()
    _migrate_legacy_data()
    try:
        have = [n for n in os.listdir(SOUNDS_DIR) if n.lower().endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac"))]
    except OSError:
        have = []
    if have:
        return
    bundled = resource_path("sounds")
    if not os.path.isdir(bundled):
        return
    try:
        for name in os.listdir(bundled):
            src = os.path.join(bundled, name)
            dst = os.path.join(SOUNDS_DIR, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
    except OSError:
        pass


def clean_text(text: str | None) -> str:
    """去掉搜索结果里的 <em> 高亮标签和多余空白。"""
    if not text:
        return ""
    text = _TAG_RE.sub("", str(text))
    text = html.unescape(text)
    return text.strip()


def norm_url(url: str | None) -> str:
    url = (url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    return url


def parse_bvid(url_or_id: str) -> str:
    """从各种输入里抠出 hmset/镜像用的 aid+bvid：返回 (bvid, aid) 或 ("","")."""
    s = (url_or_id or "").strip()
    m = re.search(r"(BV[0-9A-Za-z]{10})", s)
    if m:
        return m.group(1)
    m = re.search(r"av(\d+)", s, re.I)
    if m:
        return "av" + m.group(1)
    return ""


def now_ts() -> int:
    return int(time.time())


def fmt_ts(ts: int | float | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not ts:
        return "未知时间"
    try:
        return _dt.datetime.fromtimestamp(int(ts)).strftime(fmt)
    except (ValueError, OSError, OverflowError):
        return "未知时间"


def fmt_rel(ts: int | float | None) -> str:
    """把时间戳格式化成「3 分钟前」这种相对时间。"""
    if not ts:
        return "未知"
    delta = now_ts() - int(ts)
    if delta < 0:
        return fmt_ts(ts, "%m-%d %H:%M")
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{delta // 60} 分钟前"
    if delta < 86400:
        return f"{delta // 3600} 小时前"
    if delta < 86400 * 8:
        return f"{delta // 86400} 天前"
    return fmt_ts(ts, "%Y-%m-%d")


def human_size(n: float) -> str:
    """字节数 → 人类可读体积（1.2 MB / 340 KB）。"""
    n = float(n or 0)
    if n <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def fmt_count(n: int | float | None) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return "0"
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f} 亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f} 万"
    return str(n)


class Log:
    """超简单文件日志，出问题时好排查。"""

    def __init__(self, name: str = "app.log", keep_days: int = 7):
        self.path = os.path.join(LOG_DIR, name)
        self.keep_days = keep_days
        os.makedirs(LOG_DIR, exist_ok=True)

    def write(self, msg: str) -> None:
        line = f"[{_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def __call__(self, msg: str) -> None:
        self.write(msg)

    def trim(self) -> None:
        try:
            if os.path.getsize(self.path) > 2 * 1024 * 1024:
                os.replace(self.path, self.path + ".1")
        except OSError:
            pass


def resource_path(*parts: str) -> str:
    """支持 PyInstaller 打包后的资源定位（始终指向程序自带的只读资源）。"""
    return os.path.join(ROOT, *parts)
