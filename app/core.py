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

"""核心逻辑：扫描、去重、过滤、通知，以及给 QML 用的数据模型."""
from __future__ import annotations

import concurrent.futures
import os
import threading
import time
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication

from .bili import BiliClient, BiliError, human_duration
from .appearance import (
    MODE_DARK,
    MODE_LIGHT,
    MODE_SYSTEM,
    MODES as APPEARANCE_MODES,
    mode_label,
    normalize_mode,
    resolve_is_dark,
)
from .notifier import Notifier, play_alert, play_system_alert, set_custom_sound
from .panlink import extract_links
from .player import VideoPlayer
from .downloads import DownloadManager
from .modmanager import ModManager
from .servers import ServerManager
from .sound import (
    DEFAULT_SOUND,
    SOUND_EXTS,
    SoundPlayer,
    ensure_default_sound,
    import_sound,
    list_sounds,
    resolve_sound_path,
)
from .store import DEFAULT_CONFIG, Config, Library
from .updater import GITHUB_REPO, check_update, download_and_install
from .util import (
    BG_DIR,
    SOUNDS_DIR,
    Log,
    ensure_dirs,
    fmt_count,
    fmt_rel,
    fmt_ts,
    norm_url,
)
from .wallpaper import (
    BG_STEM,
    DEFAULT_OPACITY,
    IMAGE_EXTS,
    clamp_opacity,
    current_bg_path,
    import_background,
    list_backgrounds,
    migrate_legacy,
    remove_background,
    resolve_bg_path,
)

log = Log("core.log")

# 默认强调色（红）。设置面板里的 RGB 滑块改的就是它，配置坏掉/没设置时回落到这里。
ACCENT_DEFAULT = str(DEFAULT_CONFIG["ui_accent"])


def file_url(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    return QUrl.fromLocalFile(path).toString()


def bg_root() -> str:
    """当前背景图目录（每次现读 util.BG_DIR，测试会把它指到沙盒）。"""
    from . import util as _util

    return getattr(_util, "BG_DIR", BG_DIR) or BG_DIR


def human_bytes(n: float) -> str:
    n = float(n or 0)
    if n <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def mod_cache_info() -> dict:
    """MOD 封面缓存占用。"""
    from .mods import CACHE_DIR as MOD_CACHE

    total = 0
    count = 0
    try:
        for name in os.listdir(MOD_CACHE):
            p = os.path.join(MOD_CACHE, name)
            if os.path.isfile(p):
                total += os.path.getsize(p)
                count += 1
    except OSError:
        pass
    return {"bytes": total, "count": count, "text": human_bytes(total)}


def clear_mod_cache() -> dict:
    from .mods import CACHE_DIR as MOD_CACHE

    freed = 0
    removed = 0
    try:
        for name in os.listdir(MOD_CACHE):
            p = os.path.join(MOD_CACHE, name)
            if os.path.isfile(p):
                try:
                    freed += os.path.getsize(p)
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass
    except OSError:
        pass
    return {"bytes": freed, "removed": removed, "text": human_bytes(freed)}


class VideoModel(QAbstractListModel):
    """主列表模型。"""

    ROLES = [
        "bvid", "title", "author", "desc", "descSnippet", "pubdate", "pubText",
        "pubRel", "duration", "play", "playText", "danmakuText", "coverUrl",
        "pageUrl", "isNew", "detailLoaded", "avatar", "views", "mid", "tag",
        "discoveredAt",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []

    # ---------------------------------------------------------- Qt 接口
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return {i + 0x0100: name.encode() for i, name in enumerate(self.ROLES)}

    def data(self, index: QModelIndex, role: int = -1) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role < 0x0100:
            return None
        name = self.ROLES[role - 0x0100]
        return item.get(name)

    # ---------------------------------------------------------- 自定义
    def set_items(self, items: list[dict]) -> None:
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def update_cover(self, bvid: str, path: str) -> None:
        for row, item in enumerate(self._items):
            if item.get("bvid") == bvid:
                url = file_url(path)
                if not url:
                    return
                item["coverUrl"] = url
                item["coverPath"] = path
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [0x0100 + self.ROLES.index("coverUrl")])
                return

    def update_item(self, bvid: str, item: dict) -> bool:
        """原位替换某一条，只发 dataChanged。

        不能用 set_items()：那会 beginResetModel，ListView 滚动位置直接归零，
        点开一个视频详情就被弹回列表开头。
        """
        for row, old in enumerate(self._items):
            if old.get("bvid") == bvid:
                self._items[row] = item
                idx = self.index(row, 0)
                self.dataChanged.emit(
                    idx, idx, [0x0100 + i for i in range(len(self.ROLES))]
                )
                return True
        return False


def _decorate(item: dict) -> dict:
    """给原始记录补上 QML 要显示的计算字段。"""
    d = dict(item)
    pub = int(item.get("pubdate") or 0)
    d["pubText"] = fmt_ts(pub, "%Y-%m-%d %H:%M")
    d["pubRel"] = fmt_rel(pub)
    # 播放量有两个来源：搜索/空间接口给 "play"，详情接口给 "views"(stat.view)。
    # 详情刷新后 rec 里两个键会同时存在，谁也不是永远最新 —— 取两者最大值，
    # 播放量只增不减，max 一定是较新的那个。
    # （不这么写，列表卡片会一直停在扫描时的旧 play 值，而详情面板读 views 已经变了）
    views = max(int(item.get("views") or 0), int(item.get("play") or 0))
    d["views"] = views
    d["play"] = views
    d["playText"] = fmt_count(views)
    d["danmakuText"] = fmt_count(item.get("danmaku") or 0)
    d["pageUrl"] = item.get("url") or f"https://www.bilibili.com/video/{item.get('bvid', '')}"
    d["duration"] = human_duration(item.get("duration"))
    desc = (item.get("desc") or "").strip()
    d["desc"] = desc
    snippet = " ".join(desc.split())
    d["descSnippet"] = snippet[:90] + ("…" if len(snippet) > 90 else "")
    d["isNew"] = bool(item.get("is_new"))
    d["detailLoaded"] = bool(item.get("detail_loaded"))
    cover_path = item.get("coverPath") or item.get("cover_path") or ""
    d["coverUrl"] = file_url(cover_path) if cover_path else norm_url(item.get("cover") or "")
    d["tag"] = item.get("tag") or ""
    return d


class Core(QObject):
    # ---- 信号 ----
    videosChanged = Signal()
    listChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    newItemsFound = Signal("QVariantList")
    detailReady = Signal("QVariantMap")
    authorReady = Signal("QVariantMap")
    authorFailed = Signal(str)
    detailFailed = Signal(str)
    scanFinished = Signal(bool, str, int)
    monitorChanged = Signal()
    keywordsChanged = Signal()
    cacheChanged = Signal()
    # 动作型提示（复制 / 导入 / 删除 / 转换…），QML 侧弹一个会淡出的浮层。
    # level: info / ok / warn / error —— 删除时回收站走 warn(黄)、直接删走 error(红)
    toastRequested = Signal(str, str)
    _refreshSig = Signal()
    _coverSig = Signal(str, str)
    # 后台线程刷新「列表里的某一行」必须回到主线程再做 —— QAbstractListModel
    # 的 dataChanged 只有在 GUI 线程发出，QQuickListView 才会真的重绘那一行。
    _oneSig = Signal(str)
    # 软件更新：检查中 / 下载中 / 结果（updateInfo）变化时发，QML 据此刷新「关于」里的检查更新弹窗
    updateChanged = Signal()

    def __init__(self, app: QGuiApplication, parent=None):
        super().__init__(parent)
        ensure_dirs()
        self.app = app
        self.config = Config()
        self.library = Library()
        # 老配置的背景图文件名 → 统一的 background.*（升级迁移，只做一次）
        self._migrate_bg_once()
        self.client = BiliClient()
        # 恢复上次的登录态（client 里装 cookie，界面据此显示「已登录 xxx」）
        self._bili_qr_url = ""
        self._bili_qr_key = ""
        self._bili_qr_file = ""
        self._restore_bili_login()
        self.model = VideoModel(self)
        # 自定义提示音：Qt 播放器必须活在主线程，所以统一由 Core 持有
        self._sound = SoundPlayer(self)
        self._alert_sound = self._resolved_alert_sound()
        set_custom_sound(self._sound, self._alert_sound)
        self.notifier = Notifier(
            sound=bool(self.config["notify_sound"]),
            sound_path=self._alert_sound,
        )
        self._player_obj = VideoPlayer(self, config=self.config)
        self._mods = ModManager(self)
        self._servers = ServerManager(self)
        # 统一下载队列：MOD / 视频的下载都从这里走，界面只看这一份数据
        self._downloads = DownloadManager(self)
        self._downloads.toastRequested.connect(self.toast)
        self._busy = False
        self._status = "就绪"
        self._filter = ""
        self._sort = "pubdate"
        self._date_filter = 0   # 0=全部 1=最近一天 7=最近七天 180=最近半年
        # 当前详情面板上挂着的 bvid：后台刷新回来只推给「还停在这个视频上」的界面
        self._detail_bvid = ""
        self._closing = False
        # 背景图版本号：每次 import / clear 都 +1。QML 的 Image 有 cache，
        # 文件名又不变（永远 background.jpeg），所以靠这个让 source 真的变。
        self._bg_version = 0
        # 启动后第一次扫描：如果这次没发现新视频，自动把「只看新的」关掉。
        # 不这么做的话，用户昨天开着「只看新的」→ 今天打开软件列表一片空白，
        # 会以为软件坏了（真实反馈）。只对启动那一次生效：
        # 用户自己在监控过程中打开开关，不能被后面的周期扫描反复关掉。
        self._startup_scan = True
        self._cover_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self._lock = threading.Lock()

        # 软件更新状态：updateInfo 供「关于」里的检查更新弹窗读；
        # _auto_check_requested 用来区分「启动自动检查」和用户手动点检查
        self._update_info: dict[str, Any] = {
            "has_update": False,
            "current": "",
            "latest": "",
            "note": "",
            "url": "",
            "error": "",
        }
        self._update_checking = False
        self._update_downloading = False
        self._auto_check_requested = False

        self._timer = QTimer(self)
        self._timer.setInterval(int(self.config["interval_min"]) * 60 * 1000)
        self._timer.timeout.connect(self.scan_now)

        # 跨线程刷新：后台线程只发信号，主线程处理
        self._refreshSig.connect(self._rebuild)
        self._coverSig.connect(self.model.update_cover, Qt.QueuedConnection)
        self._oneSig.connect(self._refresh_one, Qt.QueuedConnection)

        # 跟随系统：挂上「系统换了浅色/深色」的信号
        self._hook_system_theme()

        self._rebuild()
        # 启动时总是自动扫一次（不再只对首次启动扫描）——
        # 这样打开软件立刻开始拉最新视频，不用等刷新周期。
        QTimer.singleShot(600, self.scan_now)
        # 开了「自动检测更新」的，启动后晚一点静默检查一次（避开刚启动的那次扫描）
        QTimer.singleShot(2000, self._auto_check_once)
        # 有历史数据且开了监控的，扫完这次后继续按周期监控
        if not self.library.first_run() and int(self.config["interval_min"]) > 0:
            self.start_monitor(quiet=True)

    # ================================================================= 属性
    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status

    @Property(str, notify=videosChanged)
    def lastCheckText(self) -> str:
        ts = int(self.library.meta.get("last_check") or 0)
        if not ts:
            return "还没扫描过"
        # 只显示「今天扫了几次」——总次数越堆越大，看着没意义还容易让人焦虑
        today = self.library.checks_today()
        return f"上次扫描 {fmt_rel(ts)} · 今日扫描 {today} 次"

    @Property(int, notify=videosChanged)
    def newCount(self) -> int:
        return self.library.new_count()

    @Property(int, notify=videosChanged)
    def totalCount(self) -> int:
        return len(self.library.videos)

    @Property(int, notify=videosChanged)
    def shownCount(self) -> int:
        return self.model.rowCount()

    @Property("QVariantList", notify=videosChanged)
    def newVideos(self) -> list:
        return [_decorate(v) for v in self.library.new_items()]

    @Property(QObject, constant=True)
    def videoModel(self):
        return self.model

    @Property(QObject, constant=True)
    def player(self):
        return self._player_obj

    @Property(QObject, constant=True)
    def mods(self):
        return self._mods

    @Property(QObject, constant=True)
    def servers(self):
        return self._servers

    @Property(QObject, constant=True)
    def downloads(self):
        return self._downloads

    @Property(bool, notify=videosChanged)
    def firstRun(self) -> bool:
        return self.library.first_run()

    # ---- 设置项 ----
    @Property(str, notify=statusChanged)
    def keyword(self) -> str:
        return str(self.config["keyword"])

    @Property("QVariantList", notify=keywordsChanged)
    def keywords(self) -> list:
        return list(self.config.keywords())

    @Slot(str, result="QVariantList")
    def addKeyword(self, value: str) -> list:
        """添加一个关键词并立即生效（合并进同一个列表，重复的自动忽略）。"""
        value = (value or "").strip()
        current = self.config.keywords()
        if not value:
            return current
        if len(current) >= 8:
            self._set_status(f"最多 {8} 个关键词，先删掉一个再加吧")
            return current
        if any(value.lower() == k.lower() for k in current):
            self._set_status(f"「{value}」已经在了")
            return current
        kws = self.config.set_keywords(current + [value])
        self.keywordsChanged.emit()
        self.statusChanged.emit()
        self._set_status(f"已添加关键词「{value}」，点刷新开始抓取")
        return kws

    @Slot(str, result="QVariantList")
    def removeKeyword(self, value: str) -> list:
        current = self.config.keywords()
        if len(current) <= 1:
            self._set_status("至少要保留一个关键词")
            return current
        rest = [k for k in current if k != value]
        if len(rest) == len(current):
            return current
        kws = self.config.set_keywords(rest)
        self.keywordsChanged.emit()
        self.statusChanged.emit()
        self._set_status(f"已移除关键词「{value}」（已抓到的视频仍保留在列表里）")
        return kws

    @Property(int, notify=statusChanged)
    def intervalMin(self) -> int:
        return int(self.config["interval_min"])

    @Slot(int)
    def setIntervalMin(self, value: int) -> None:
        value = max(0, min(720, int(value)))
        self.config["interval_min"] = value
        self.config.save()
        if self._timer.isActive():
            self._timer.setInterval(max(1, value) * 60 * 1000)
        self.statusChanged.emit()

    @Property(int, notify=statusChanged)
    def maxPages(self) -> int:
        return int(self.config["max_pages"])

    @Slot(int)
    def setMaxPages(self, value: int) -> None:
        self.config["max_pages"] = max(1, min(5, int(value)))
        self.config.save()
        self.statusChanged.emit()

    @Property(str, notify=statusChanged)
    def sortMode(self) -> str:
        return self._sort

    @Slot(str)
    def setSortMode(self, value: str) -> None:
        if value != self._sort:
            self._sort = value
            self._rebuild()
            # 必须通知，否则 UI 上的"当前排序"高亮不会变
            self._set_status(f"已按{'最多播放' if value == 'views' else '最新发布'}排序")

    # 视频日期筛选：0=全部 1=最近一天 7=最近七天 180=最近半年
    @Property(int, notify=statusChanged)
    def dateFilter(self) -> int:
        return self._date_filter

    @Slot(int)
    def setDateFilter(self, days: int) -> None:
        days = days if days in (0, 1, 7, 180) else 0
        if days == self._date_filter:
            return
        self._date_filter = days
        self._rebuild()
        label = {0: "全部日期", 1: "最近一天", 7: "最近七天", 180: "最近半年"}.get(days, "")
        self._set_status(f"已筛选：{label}")

    @Property(bool, notify=videosChanged)
    def showOnlyNew(self) -> bool:
        return bool(self.config["show_only_new"])

    @Slot(bool)
    def setShowOnlyNew(self, value: bool) -> None:
        self.config["show_only_new"] = bool(value)
        self.config.save()
        self._rebuild()

    @Property(str, notify=statusChanged)
    def filterText(self) -> str:
        return self._filter

    @Slot(str)
    def setFilterText(self, value: str) -> None:
        value = (value or "").strip()
        if value != self._filter:
            self._filter = value
            self._rebuild()

    @Property(bool, notify=statusChanged)
    def monitoring(self) -> bool:
        return self._timer.isActive()

    @Property(bool, notify=statusChanged)
    def notifyToast(self) -> bool:
        return bool(self.config["notify_toast"])

    @Slot(bool)
    def setNotifyToast(self, value: bool) -> None:
        self.config["notify_toast"] = bool(value)
        self.config.save()
        self.statusChanged.emit()

    @Property(bool, notify=statusChanged)
    def notifySound(self) -> bool:
        return bool(self.config["notify_sound"])

    @Slot(bool)
    def setNotifySound(self, value: bool) -> None:
        self.config["notify_sound"] = bool(value)
        self.notifier.sound = bool(value)
        self.config.save()
        if value:
            self.testSound()
        else:
            self.statusChanged.emit()

    # ------------------------------------------------------- 自定义提示音
    def _resolved_alert_sound(self) -> str:
        """配置里的音效名 → 实际路径；配置坏了/文件删了就退回默认 bbb.mp3。"""
        path = resolve_sound_path(str(self.config["alert_sound"] or ""), SOUNDS_DIR)
        if path:
            return path
        default = ensure_default_sound()
        if default:
            # 配置文件里存空了（或存的是别的机器上的绝对路径），顺手纠正回来
            name = os.path.basename(default)
            if str(self.config["alert_sound"] or "") != name:
                self.config["alert_sound"] = name
                self.config.save()
        return default

    @Property("QVariantList", notify=statusChanged)
    def soundList(self) -> list:
        """sounds 目录里可选的全部音效。"""
        return list_sounds()

    @Property(str, notify=statusChanged)
    def alertSoundName(self) -> str:
        """当前提示音的文件名（界面上显示的名字）。"""
        cur = str(self.config["alert_sound"] or "")
        if cur:
            return os.path.basename(cur)
        path = self._alert_sound
        return os.path.basename(path) if path else ""

    @Property(str, notify=statusChanged)
    def soundsDir(self) -> str:
        return SOUNDS_DIR

    @Property(str, notify=statusChanged)
    def soundHint(self) -> str:
        return "支持 " + " / ".join(e.lstrip(".").upper() for e in SOUND_EXTS)

    @Slot(str, result="QVariantMap")
    def setAlertSound(self, name: str) -> dict:
        """选一个已导入的音效当提示音。"""
        value = (name or "").strip()
        if not value:
            return {"ok": False, "error": "没选音效"}
        path = resolve_sound_path(value, SOUNDS_DIR)
        if not path:
            self.statusChanged.emit()
            return {"ok": False, "error": f"sounds 目录里找不到 {value}"}
        self.config["alert_sound"] = os.path.basename(path)
        self.config.save()
        self._alert_sound = path
        set_custom_sound(self._sound, path)
        self.notifier.sound_path = path
        self.statusChanged.emit()
        self.toast(f"提示音已换成 {os.path.basename(path)}", "ok")
        return {"ok": True, "name": os.path.basename(path), "path": path}

    @Slot(str, result="QVariantMap")
    def importAlertSound(self, path: str) -> dict:
        """把外部音效复制进 sounds 目录，并直接设为当前提示音。"""
        res = import_sound(path)
        if not res.get("ok"):
            self.toast("导入音效失败：" + (res.get("error") or "未知"), "error")
            return res
        self.config["alert_sound"] = res["name"]
        self.config.save()
        self._alert_sound = res["path"]
        set_custom_sound(self._sound, res["path"])
        self.notifier.sound_path = res["path"]
        self.statusChanged.emit()
        self.toast(f"已导入提示音 {res['name']}", "ok")
        # 导入后立刻听一下，用户马上就知道行了没有
        self._sound.play(res["path"])
        return res

    @Slot(result="QVariantMap")
    def resetAlertSound(self) -> dict:
        """恢复默认音效 bbb.mp3。"""
        default = ensure_default_sound()
        if not default:
            self.toast(f"sounds 目录里没有默认音效 {DEFAULT_SOUND}", "error")
            return {"ok": False, "error": "missing default"}
        self.config["alert_sound"] = DEFAULT_SOUND
        self.config.save()
        self._alert_sound = default
        set_custom_sound(self._sound, default)
        self.notifier.sound_path = default
        self.statusChanged.emit()
        self.toast("提示音已恢复默认", "ok")
        return {"ok": True, "name": DEFAULT_SOUND, "path": default}

    @Slot()
    def openSoundsFolder(self) -> None:
        """在资源管理器里打开 sounds 目录（用户自己丢文件进去也行）。"""
        os.makedirs(SOUNDS_DIR, exist_ok=True)
        try:
            os.startfile(SOUNDS_DIR)  # noqa: S606
        except OSError as e:
            log(f"open sounds dir failed: {e!r}")

    @Slot()
    def refreshSounds(self) -> None:
        """重新扫一遍 sounds 目录（用户手工往里放了文件时用）。"""
        self._alert_sound = self._resolved_alert_sound()
        set_custom_sound(self._sound, self._alert_sound)
        self.notifier.sound_path = self._alert_sound
        self.statusChanged.emit()

    @Slot()
    def testSound(self) -> None:
        """试听提示音（设置面板的按钮用）。"""
        if not self._alert_sound:
            self._alert_sound = self._resolved_alert_sound()
        if self._alert_sound and play_alert(self._alert_sound):
            self.toast("提示音已播放，能听到就说明没问题", "ok")
        elif play_system_alert():
            self.toast("自定义音效播不了，已退回系统提示音", "warn")
        else:
            self.toast("提示音播放失败，检查系统声音设置", "error")

    # ------------------------------------------------------- 自定义背景图
    def _migrate_bg_once(self) -> None:
        """升级迁移：老配置记的是任意文件名，现在只认 background.*，把它搬过去。"""
        try:
            res = migrate_legacy(str(self.config["bg_image"] or ""))
        except Exception as e:  # noqa: BLE001  迁移失败不能影响启动
            log(f"background migrate crashed: {e!r}")
            return
        if res.get("migrated"):
            self.config["bg_image"] = res["name"]
            self.config.save()

    def _resolved_bg_path(self) -> str:
        """配置里的背景图名 → 实际路径；图片被删了就当没设置。"""
        path = resolve_bg_path(str(self.config["bg_image"] or ""), bg_root())
        if path:
            return path
        if str(self.config["bg_image"] or ""):
            # 记着的图没了（被删 / 换机器），清掉，免得一直找不到
            self.config["bg_image"] = ""
            self.config.save()
        return ""

    @Property(str, notify=statusChanged)
    def bgImageName(self) -> str:
        """当前背景图的文件名（界面上显示的名字），没设置就是空串。"""
        path = self._resolved_bg_path()
        return os.path.basename(path) if path else ""

    @Property(str, constant=True)
    def logoUrl(self) -> str:
        """侧栏品牌图标的图（assets/appLogo.png）：和窗口 / 任务栏 / exe 同一张。"""
        from .util import ROOT as _root

        for name in ("appLogo.png", "icon_256.png", "icon.png"):
            p = os.path.join(_root, "assets", name)
            if os.path.exists(p):
                return file_url(p)
        return ""

    # ---- 关于（设置页底部那张卡片用的）----
    # 文案写在 Python 这边：「关于」里的名字/版本/主页只该有一个来源，
    # 分散到 QML 里以后改名（这次就从 L42D 改成了 Yumi的L4D2）又要找一遍。
    APP_AUTHOR = "Yumi"
    APP_HOMEPAGE = "https://github.com/Yumivvv/YumiL4D2"

    @Property(str, constant=True)
    def aboutName(self) -> str:
        from . import APP_NAME

        return APP_NAME

    @Property(str, constant=True)
    def aboutVersion(self) -> str:
        from . import APP_VERSION

        return APP_VERSION

    @Property(str, constant=True)
    def aboutAuthor(self) -> str:
        return self.APP_AUTHOR

    @Property(str, constant=True)
    def aboutHomepage(self) -> str:
        return self.APP_HOMEPAGE

    @Property(str, constant=True)
    def aboutHomepageText(self) -> str:
        """主页地址的显示文本（去掉 github.com/，卡片里没那么长）。"""
        url = self.APP_HOMEPAGE
        for prefix in ("https://", "http://"):
            if url.startswith(prefix):
                url = url[len(prefix):]
        return url.rstrip("/")

    @Property(str, constant=True)
    def dataDir(self) -> str:
        """用户数据目录（data/ 的上一级），「关于」里给一条「打开目录」用。"""
        data_dir = os.environ.get("L4D2_DATA_DIR") or ""
        if not data_dir:
            from .util import DATA_DIR as _data_dir

            data_dir = _data_dir
        return data_dir

    @Slot()
    def openDataDir(self) -> None:
        """打开数据目录（找不到就退到它上一级）。"""
        from PySide6.QtGui import QDesktopServices

        from .util import USER_ROOT as _user_root

        path = self.dataDir or _user_root
        target = path if os.path.isdir(path) else os.path.dirname(path)
        if target and os.path.isdir(target):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        else:
            self.toast("数据目录还不存在", "warn")

    @Slot()
    def openHomepage(self) -> None:
        self.openUrl(self.APP_HOMEPAGE)

    @Slot()
    def copyHomepage(self) -> None:
        self.copyText(self.APP_HOMEPAGE)

    @Property(str, notify=statusChanged)
    def bgImageUrl(self) -> str:
        """给 QML Image 用的 file:// URL；没设置返回空串（Image 就是空的）。

        ★ 必须带一个**每次换图都会变的版本号**，不能只给干净的文件路径。
          因为换背景图时文件名**不会变**（永远是 `background.jpeg` 这种，
          同扩展名换了就是同一个名字），而 QML 的 `Image` 有 `cache: true` ——
          source 字符串没变化就不会重新加载，表现就是「换了图但画面没变」。

          版本号用两段拼：
            · `self._bg_version`  每次 import / clear 都 +1（最可靠，一定变）
            · 文件 mtime+size     兜底（用户直接往 backgrounds 里手动扔图也能刷新）
          只用 mtime+size 不够：两张 64×64 纯色 JPEG 压出来常常一样大，
          同一秒内替换时 mtime 也可能没变 —— 实测那样 URL 会一模一样。
        """
        path = self._resolved_bg_path()
        if not path:
            return ""
        stamp = ""
        try:
            st = os.stat(path)
            stamp = f"{int(st.st_mtime)}-{st.st_size}"
        except OSError:
            stamp = "0-0"
        return f"{file_url(path)}?v={self._bg_version}-{stamp}"

    @Property(int, notify=statusChanged)
    def bgOpacity(self) -> int:
        return clamp_opacity(self.config["bg_opacity"])

    @Property(bool, notify=statusChanged)
    def bgOn(self) -> bool:
        """背景图总开关：关了就用回默认渐变色（图片还留着，随时能开回来）。"""
        return bool(self.config["bg_enabled"])

    @Slot(bool)
    def setBgOn(self, value: bool) -> None:
        self.config["bg_enabled"] = bool(value)
        self.config.save()
        self.statusChanged.emit()
        if value:
            self.toast("已启用背景图", "ok")
        else:
            self.toast("已关闭背景图", "info")

    @Property("QVariantList", notify=statusChanged)
    def bgList(self) -> list:
        """可用的背景图。现在固定只有一个 `background.*`，所以最多 1 项。"""
        return list_backgrounds()

    @Property(str, notify=statusChanged)
    def bgDir(self) -> str:
        return bg_root()

    @Property(str, notify=statusChanged)
    def bgHint(self) -> str:
        return "支持 " + " / ".join(e.lstrip(".").upper() for e in IMAGE_EXTS)

    @Property(str, notify=statusChanged)
    def bgFileName(self) -> str:
        """背景图的固定文件名（不含扩展名），界面上用来告诉用户会存成什么。"""
        return BG_STEM

    @Slot(int)
    def previewBgOpacity(self, value: int) -> None:
        """拖滑块时只改内存值（实时预览），松手才落盘。"""
        self.config["bg_opacity"] = clamp_opacity(value)
        self.statusChanged.emit()

    @Slot(int)
    def setBgOpacity(self, value: int) -> None:
        self.config["bg_opacity"] = clamp_opacity(value)
        self.config.save()
        self.statusChanged.emit()

    @Slot(str, result="QVariantMap")
    def setBgImage(self, name: str) -> dict:
        """选中 backgrounds 里那张 `background.*`（只有它一个可选）。"""
        value = (name or "").strip()
        if not value:
            return {"ok": False, "error": "没选背景图"}
        path = resolve_bg_path(value, bg_root())
        if not path:
            self.statusChanged.emit()
            return {"ok": False, "error": f"backgrounds 目录里找不到 {BG_STEM}.*"}
        self.config["bg_image"] = os.path.basename(path)
        self.config.save()
        self.statusChanged.emit()
        self.toast("背景图已启用", "ok")
        return {"ok": True, "name": os.path.basename(path), "path": path}

    @Slot(str, result="QVariantMap")
    def importBgImage(self, path: str) -> dict:
        """把外部图片复制成 `background.<ext>`（覆盖旧的那张），并直接启用。"""
        res = import_background(path)
        if not res.get("ok"):
            self.toast("导入背景图失败：" + (res.get("error") or "未知"), "error")
            return res
        # 版本号 +1：文件名没变（同扩展名覆盖），只有这个能让 QML 的 Image 重读
        self._bg_version += 1
        self.config["bg_image"] = res["name"]
        self.config["bg_enabled"] = True
        self.config.save()
        self.statusChanged.emit()
        self.toast(f"已导入背景图 {res['name']}（会覆盖旧的）", "ok")
        return res

    @Slot(result="QVariantMap")
    def clearBgImage(self) -> dict:
        """移除背景图：**真的把 background.* 删掉**，并清掉配置。

        （老版本只是把配置里的文件名清空、文件留在盘上，用户以为没删干净。）
        """
        res = remove_background()
        # 删掉之后也要 +1：不然 QML 那边 Image 可能还留着上一张的缓存，
        # 再导入一张同名图时又会「看起来没换」。
        self._bg_version += 1
        self.config["bg_image"] = ""
        self.config.save()
        self.statusChanged.emit()
        if not res.get("ok"):
            self.toast("移除背景图失败：" + (res.get("error") or "文件被占用"), "error")
            return res
        if res.get("removed"):
            self.toast(f"已删除背景图 {res['removed']}", "warn")
        else:
            self.toast("本来就没有背景图", "info")
        return res

    @Slot()
    def openBgFolder(self) -> None:
        """在资源管理器里打开 backgrounds 目录。"""
        os.makedirs(bg_root(), exist_ok=True)
        try:
            os.startfile(bg_root())  # noqa: S606
        except OSError as e:
            log(f"open backgrounds dir failed: {e!r}")

    @Slot()
    def refreshBackgrounds(self) -> None:
        """重新认一遍背景图（用户手工放了 background.* 进来时用）。"""
        path = current_bg_path()
        name = os.path.basename(path) if path else ""
        if name and name != str(self.config["bg_image"] or ""):
            self.config["bg_image"] = name
            self.config.save()
        self.statusChanged.emit()

    # ------------------------------------------------------- 字体回退
    # ★ 图标字体不能写死成 "Segoe Fluent Icons"。
    #   那是 **Windows 11 才有**的字体；Windows 10 上只有老一代的
    #   "Segoe MDL2 Assets"。写死的结果是：开发机（Win11）一切正常，
    #   别人的 Win10 上**所有图标都变成空白**（字形找不到就渲染成豆腐块或空白）。
    #
    #   实测两个字体的码位兼容性：项目用到的 59 个图标码位
    #   **在两个字体里都存在**，所以只要把字体名做成可回退就行，不用换图标。
    #   顺序：Fluent（Win11，字形最新）→ MDL2（Win10 起自带）→ 空（交给 Qt 兜底）
    _ICON_FONTS = (
        "Segoe Fluent Icons",   # Windows 11
        "Segoe MDL2 Assets",    # Windows 10 及部分 Win11
        "Segoe UI Symbol",      # 很老的系统，至少别是空
    )

    @Property(str, constant=True)
    def iconFontFamily(self) -> str:
        """当前系统上可用的图标字体名（QML 的 Theme.iconFont 用它）。"""
        try:
            from PySide6.QtGui import QFontDatabase

            families = set(QFontDatabase.families())
        except Exception:                    # noqa: BLE001 - 取不到就当没有
            families = set()
        for name in self._ICON_FONTS:
            if name in families:
                return name
        return ""

    @Property(str, constant=True)
    def uiFontFamily(self) -> str:
        """界面正文字体。Win10/11 都有微软雅黑 UI，没有就退到雅黑。"""
        try:
            from PySide6.QtGui import QFontDatabase

            families = set(QFontDatabase.families())
        except Exception:                    # noqa: BLE001
            families = set()
        for name in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei"):
            if name in families:
                return name
        return ""

    @Property(str, constant=True)
    def monoFontFamily(self) -> str:
        """等宽字体（地址、路径、数字对齐用）。"""
        try:
            from PySide6.QtGui import QFontDatabase

            families = set(QFontDatabase.families())
        except Exception:                    # noqa: BLE001
            families = set()
        for name in ("Consolas", "Cascadia Mono", "Courier New"):
            if name in families:
                return name
        return ""

    # ------------------------------------------------------- 外观模式
    @Property(str, notify=statusChanged)
    def appearance(self) -> str:
        """外观模式：system（跟随系统）/ dark（夜间）/ light（日间）。"""
        return normalize_mode(self.config["appearance"])

    @Slot(str)
    def setAppearance(self, mode: str) -> None:
        value = normalize_mode(mode)
        if value == self.appearance:
            return
        self.config["appearance"] = value
        self.config.save()
        self.statusChanged.emit()
        self.toast("外观已切换为「" + mode_label(value) + "」", "ok")

    @Property(str, notify=statusChanged)
    def appearanceLabel(self) -> str:
        return mode_label(self.appearance)

    @Property(bool, notify=statusChanged)
    def isDark(self) -> bool:
        """当前实际用的色板是不是深色（QML 的 Theme 靠它切整套路配色）。"""
        return resolve_is_dark(self.appearance, self._style_hints_light())

    @Property(bool, notify=statusChanged)
    def followsSystem(self) -> bool:
        return self.appearance == MODE_SYSTEM

    @Property(str, notify=statusChanged)
    def systemThemeLabel(self) -> str:
        """给设置面板显示「系统现在是浅色/深色」。"""
        try:
            light = self._style_hints_light()
        except Exception:  # noqa: BLE001
            light = None
        if light is None:
            from .appearance import system_prefers_light

            light = system_prefers_light()
        return "浅色" if light else "深色"

    def _style_hints_light(self) -> bool | None:
        """从 Qt 的 styleHints 读系统色板，拿不到返回 None（回落注册表）。"""
        try:
            hints = QGuiApplication.styleHints()
            scheme = hints.colorScheme()
        except (AttributeError, RuntimeError):
            return None
        # Qt.ColorScheme 枚举：Unknown / Dark / Light
        name = getattr(scheme, "name", "")
        if name == "Light":
            return True
        if name == "Dark":
            return False
        value = getattr(scheme, "value", None)
        try:
            from PySide6.QtCore import Qt as _Qt

            if value == _Qt.ColorScheme.Light.value:
                return True
            if value == _Qt.ColorScheme.Dark.value:
                return False
        except (AttributeError, TypeError):
            pass
        return None

    def _on_system_color_scheme_changed(self, *_args: Any) -> None:
        """系统切换浅色/深色时：只有「跟随系统」才需要重刷界面。"""
        if self.appearance == MODE_SYSTEM:
            self.statusChanged.emit()

    def _hook_system_theme(self) -> None:
        """挂上系统色板变化的信号（跟着系统模式实时变）。"""
        try:
            hints = QGuiApplication.styleHints()
            hints.colorSchemeChanged.connect(self._on_system_color_scheme_changed)
        except (AttributeError, RuntimeError) as e:
            log(f"hook colorSchemeChanged failed: {e!r}")

    # ------------------------------------------------------- 界面主题色
    @staticmethod
    def _normalize_accent(value: Any) -> str:
        """把 #RRGGBB / RRGGBB / #RGB 统一成 #RRGGBB（大写），认不出就用默认色。"""
        raw = str(value or "").strip().lstrip("#")
        if len(raw) == 3:
            raw = "".join(c * 2 for c in raw)
        if len(raw) != 6:
            return ACCENT_DEFAULT
        try:
            int(raw, 16)
        except ValueError:
            return ACCENT_DEFAULT
        return "#" + raw.upper()

    @staticmethod
    def _accent_hex(r: int, g: int, b: int) -> str:
        def _c(v: Any) -> int:
            try:
                return max(0, min(255, int(v)))
            except (TypeError, ValueError):
                return 0

        return "#%02X%02X%02X" % (_c(r), _c(g), _c(b))

    @Property(str, notify=statusChanged)
    def uiAccent(self) -> str:
        """界面主题色（#RRGGBB），QML 侧把它同步进 Theme.accentBase。"""
        return self._normalize_accent(self.config["ui_accent"])

    @Slot(int, int, int)
    def previewAccent(self, r: int, g: int, b: int) -> None:
        """拖 RGB 滑块时只改内存值（界面立刻变色），松手才落盘。"""
        self.config["ui_accent"] = self._accent_hex(r, g, b)
        self.statusChanged.emit()

    @Slot(int, int, int)
    def setAccent(self, r: int, g: int, b: int) -> None:
        self.config["ui_accent"] = self._accent_hex(r, g, b)
        self.config.save()
        self.statusChanged.emit()
        self.toast("主题色已改为 " + self.uiAccent, "ok")

    @Slot()
    def resetAccent(self) -> None:
        """恢复默认强调色。"""
        self.config["ui_accent"] = ACCENT_DEFAULT
        self.config.save()
        self.statusChanged.emit()
        self.toast("主题色已恢复默认", "info")

    @Property(bool, notify=statusChanged)
    def trayOnClose(self) -> bool:
        return bool(self.config["tray_on_close"])

    @Slot(bool)
    def setTrayOnClose(self, value: bool) -> None:
        self.config["tray_on_close"] = bool(value)
        self.config.save()
        self.statusChanged.emit()

    # ------------------------------------------------------- B 站登录（三连用）
    #
    # 用途：给视频 / UP 主点赞、投币、收藏、关注 —— 也就是「三连支持创作者」。
    # 凭据只存本地 config.json（SESSDATA / bili_jct / DedeUserID 三个 cookie），
    # 不上传任何地方。失效了就重新扫码登录。
    #
    # 默认勾选「点赞 + 投币 + 收藏」，可以在设置里关掉任意一项；
    # **关注默认关**（关注是长期动作，不该悄悄替用户点）。

    @Property(bool, notify=statusChanged)
    def biliLoggedIn(self) -> bool:
        return self.client.logged_in()

    @Property(str, notify=statusChanged)
    def biliUserName(self) -> str:
        return str(self._bili_user.get("uname") or "")

    @Property(str, notify=statusChanged)
    def biliUserFace(self) -> str:
        return str(self._bili_user.get("face") or "")

    @Property(int, notify=statusChanged)
    def biliUserId(self) -> int:
        return int(self._bili_user.get("mid") or 0)

    @Property(bool, notify=statusChanged)
    def biliLikeOn(self) -> bool:
        return bool(self.config["bili_triple_like"])

    @Property(bool, notify=statusChanged)
    def biliCoinOn(self) -> bool:
        return bool(self.config["bili_triple_coin"])

    @Property(bool, notify=statusChanged)
    def biliFavOn(self) -> bool:
        return bool(self.config["bili_triple_fav"])

    @Property(bool, notify=statusChanged)
    def biliFollowOn(self) -> bool:
        return bool(self.config["bili_triple_follow"])

    @Slot(bool)
    def setBiliLike(self, v: bool) -> None:
        self.config["bili_triple_like"] = bool(v)
        self.config.save()
        self.statusChanged.emit()

    @Slot(bool)
    def setBiliCoin(self, v: bool) -> None:
        self.config["bili_triple_coin"] = bool(v)
        self.config.save()
        self.statusChanged.emit()

    @Slot(bool)
    def setBiliFav(self, v: bool) -> None:
        self.config["bili_triple_fav"] = bool(v)
        self.config.save()
        self.statusChanged.emit()

    @Slot(bool)
    def setBiliFollow(self, v: bool) -> None:
        self.config["bili_triple_follow"] = bool(v)
        self.config.save()
        self.statusChanged.emit()

    def _restore_bili_login(self) -> None:
        """启动时从配置恢复登录态。"""
        self._bili_user: dict = {}
        creds = self.config["bili_credentials"] or {}
        if not isinstance(creds, dict):
            return
        sess = str(creds.get("SESSDATA") or "")
        jct = str(creds.get("bili_jct") or "")
        if not sess or not jct:
            return
        self.client.set_credentials(sess, jct, str(creds.get("DedeUserID") or ""))
        # 昵称/头像也存着，启动时先显示上次的，避免空白
        self._bili_user = dict(creds.get("user") or {})

    @Slot(result="QVariantMap")
    def biliRefreshUser(self) -> dict:
        """重新问一次 B 站「我是谁」—— 用来验证凭据还有效。"""
        if not self.client.logged_in():
            self._bili_user = {}
            self.statusChanged.emit()
            return {"ok": False, "error": "还没登录"}
        user = self.client.nav_user()
        if not user:
            # 凭据失效：清干净，让界面提示重新登录
            self.client.clear_credentials()
            self.config["bili_credentials"] = {}
            self.config.save()
            self._bili_user = {}
            self.statusChanged.emit()
            return {"ok": False, "expired": True, "error": "登录已失效，请重新扫码登录"}
        self._bili_user = user
        # 顺手把新的昵称头像写回配置
        creds = dict(self.config["bili_credentials"] or {})
        creds["user"] = user
        self.config["bili_credentials"] = creds
        self.config.save()
        self.statusChanged.emit()
        return {"ok": True, "user": user}

    @Property(str, notify=statusChanged)
    def biliQrImage(self) -> str:
        """当前登录二维码的图片 URL（QML 的 Image 直接用）。"""
        return self._bili_qr_url

    @Slot(result="QVariantMap")
    def biliLoginQr(self) -> dict:
        """申请登录二维码：拿 url、画成 PNG 存本地、返回 file:// 给界面。

        为什么存文件而不是 base64 塞进 QML：QML 的 Image 对超长 data: URL
        支持不稳（有些平台直接不显示），存成文件最省事，退出时删掉。
        """
        try:
            qr = self.client.login_qrcode()
        except BiliError as e:
            return {"ok": False, "error": str(e)}

        # 生成 PNG
        path = ""
        try:
            from .qrcode_gen import qr_png

            png = qr_png(qr["url"], scale=8, border=4)
            from . import util as _util

            out_dir = os.path.join(_util.CACHE_DIR, "login")
            os.makedirs(out_dir, exist_ok=True)
            # 每次换个文件名，避免 QML 的 Image 缓存住旧图
            path = os.path.join(out_dir, f"qr_{int(time.time() * 1000)}.png")
            with open(path, "wb") as f:
                f.write(png)
        except Exception as e:                   # noqa: BLE001
            log(f"qr png failed: {e!r}")
            return {"ok": False, "error": "二维码生成失败，请重试"}

        self._bili_qr_key = qr["key"]
        self._bili_qr_url = file_url(path)
        self._bili_qr_file = path
        self.statusChanged.emit()
        return {"ok": True, "url": qr["url"], "key": qr["key"],
                "image": self._bili_qr_url, "error": ""}

    def _drop_qr_file(self) -> None:
        """删掉上一次的二维码图（登录完成 / 关窗时）。"""
        path = getattr(self, "_bili_qr_file", "")
        self._bili_qr_file = ""
        self._bili_qr_url = ""
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


    @Slot(str, result="QVariantMap")
    def biliLoginPoll(self, key: str) -> dict:
        """轮询扫码状态。成功后把凭据落盘。"""
        res = self.client.login_poll(key)
        if res.get("state") == "ok":
            creds = res.get("credentials") or {}
            self.client.set_credentials(
                creds.get("SESSDATA", ""),
                creds.get("bili_jct", ""),
                creds.get("DedeUserID", ""),
            )
            user = self.client.nav_user()
            if not user:
                # ★ 登录确实成功了，但 nav 这一下没拿到昵称（网络抖动 / 接口抽风）。
                #   不能因此让界面显示「UID 0、无头像」——
                #   至少用 cookie 里的 DedeUserID 把 UID 填上，
                #   昵称留空由界面回退成「UID xxxxx」显示。
                #   下次进设置页会再调一次 biliRefreshUser 补全。
                uid = str(creds.get("DedeUserID") or "")
                if uid:
                    user = {"mid": int(uid) if uid.isdigit() else 0,
                            "uname": "", "face": "", "level": 0, "vip": False}
            self._bili_user = user
            self.config["bili_credentials"] = {
                "SESSDATA": creds.get("SESSDATA", ""),
                "bili_jct": creds.get("bili_jct", ""),
                "DedeUserID": creds.get("DedeUserID", ""),
                "user": user,
            }
            self.config.save()
            self.statusChanged.emit()
            name = user.get("uname") or ""
            uid = user.get("mid") or 0
            who = name if name else (f"UID {uid}" if uid else "")
            self.toast(f"登录成功{'，欢迎 ' + who if who else ''}", "ok")
        return res

    @Slot()
    def biliLogout(self) -> None:
        self.client.clear_credentials()
        self.config["bili_credentials"] = {}
        self.config.save()
        self._bili_user = {}
        self.statusChanged.emit()
        self.toast("已退出 B 站账号", "info")

    @Slot(str, result="QVariantMap")
    def biliTriple(self, bvid: str) -> dict:
        """给这个视频「三连」：按设置里的开关决定点赞 / 投币 / 收藏 / 关注。

        返回 ``{ok, done: [...], skipped: [...], error}``，
        界面拿 done 显示「已点赞、已投币」这类回执。
        """
        if not self.client.logged_in():
            return {"ok": False, "done": [], "skipped": [], "error": "还没登录"}
        rec = self.library.videos.get(bvid) or {}
        aid = int(rec.get("aid") or 0)
        mid = int(rec.get("mid") or 0)
        if aid <= 0:
            return {"ok": False, "done": [], "skipped": [], "error": "还没拿到这个视频的 aid"}
        # 校验一次登录态，失效就别瞎试写接口
        user = self.client.nav_user()
        if not user:
            self.client.clear_credentials()
            self.config["bili_credentials"] = {}
            self.config.save()
            self._bili_user = {}
            self.statusChanged.emit()
            return {"ok": False, "done": [], "skipped": [],
                    "error": "登录已失效，请重新扫码登录"}

        done: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        if self.biliLikeOn:
            r = self.client.like_video(aid, True)
            if r.get("ok"):
                done.append("点赞")
            else:
                errors.append(f"点赞失败：{r.get('message') or r.get('code')}")
        else:
            skipped.append("点赞")

        if self.biliCoinOn:
            r = self.client.coin_video(aid, 1)
            if r.get("ok"):
                done.append("投币")
            else:
                code = r.get("code")
                # -104 = 硬币不足。★ 以前把它当成「之前投过」算成功，
                #   这是错的：B 站投币接口里 -104 的官方含义是**硬币不足**
                #   （「已经投过」是 34005「超过投币上限」）。
                #   把失败当成功显示「已投币」，用户会以为投上了，实际没投。
                if code == 34005:
                    # 真的已经投满了（每人每视频最多 2 枚）—— 这个不算失败
                    done.append("投币（已经投满 2 枚）")
                elif code == 34002:
                    # 自己的稿子，投不了币。这也不是错误，只是做不了
                    skipped.append("投币（自己的稿件，投不了）")
                else:
                    # ★ 失败的可能是「硬币不足」「等级不够」「数量非法」……
                    #   不能一律写「等级低」：等级和硬币余额是两条独立门槛，
                    #   只提等级会让人跑去升等级，其实账号里一枚币都没有。
                    #   coin_video 已经把这几类码都翻成人话了，直接用。
                    errors.append(
                        r.get("human")
                        or f"投币失败：{r.get('message') or code}")
        else:
            skipped.append("投币")

        if self.biliFavOn:
            folders = self.client.favorites()
            if not folders:
                errors.append("收藏失败：没拿到收藏夹")
            else:
                # 用第一个收藏夹（B 站默认「默认收藏夹」排第一）
                r = self.client.favorite_video(aid, folders[0]["id"])
                if r.get("ok"):
                    done.append("收藏")
                else:
                    errors.append(f"收藏失败：{r.get('message') or r.get('code')}")
        else:
            skipped.append("收藏")

        if self.biliFollowOn and mid > 0:
            r = self.client.follow_user(mid, True)
            if r.get("ok"):
                done.append("关注")
            else:
                errors.append(f"关注失败：{r.get('message') or r.get('code')}")
        elif mid > 0:
            skipped.append("关注")

        ok = bool(done) and not errors
        msg = "、".join(done) if done else ""
        if errors:
            msg = "；".join(errors)
        if ok:
            self.toast(f"已支持创作者：{msg}", "ok")
            self._set_status(f"三连成功：{msg}")
        elif errors:
            self._set_status(msg)
            self.toast(msg, "warn")
        return {"ok": ok, "done": done, "skipped": skipped, "error": msg}

    @Slot(result="QVariantList")
    def biliFavorites(self) -> list:
        """当前账号的收藏夹（界面上如果以后要让用户选投哪个，用这个）。"""
        return self.client.favorites()


    # 当前协议版本。改了协议正文就把这个数字 +1，
    # 老用户下次启动会重新看到弹窗（因为存的版本对不上了）。
    AGREEMENT_VERSION = 1

    @Property(bool, notify=statusChanged)
    def agreementNeeded(self) -> bool:
        """要不要弹用户协议（首次启动 / 协议改版后）。"""
        try:
            agreed = int(self.config["agreement_version"] or 0)
        except (TypeError, ValueError):
            agreed = 0
        return agreed < self.AGREEMENT_VERSION

    @Slot()
    def acceptAgreement(self) -> None:
        """用户读完并勾选「我已知悉」后调用。"""
        self.config["agreement_version"] = self.AGREEMENT_VERSION
        self.config.save()
        self.statusChanged.emit()
        log(f"agreement accepted (v{self.AGREEMENT_VERSION})")

    # ------------------------------------------------------- 视频库容量上限
    VIDEO_LIMITS = (50, 100, 200, 500, 1000, 0)   # 0 = 不限

    @Property(int, notify=statusChanged)
    def videoLimit(self) -> int:
        """视频库上限；0 表示不限。"""
        try:
            value = int(self.config["video_limit"] or 0)
        except (TypeError, ValueError):
            value = 0
        return value if value in self.VIDEO_LIMITS else 0

    @Slot(int)
    def setVideoLimit(self, value: int) -> None:
        """设置上限并**立刻**按新上限裁剪一次。

        为什么立刻裁：用户改这个设置就是想马上清掉多出来的，
        等到下次扫描才生效会让人以为没生效。
        """
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0
        if value not in self.VIDEO_LIMITS:
            value = 0
        self.config["video_limit"] = value
        self.config.save()
        removed = self._trim_library(force=True)
        self.statusChanged.emit()
        if removed:
            self.toast(f"已清理 {removed} 个旧视频（上限 {value}）", "ok")
        elif value == 0:
            self.toast("视频库上限：不限", "info")
        else:
            self.toast(f"视频库上限设为 {value}，当前没超出", "info")

    def _trim_library(self, force: bool = False) -> int:
        """按上限裁剪视频库，返回删掉的条数。

        `force=False` 时只在超限时才动（扫描结束后调用，正常是 no-op）。
        """
        limit = self.videoLimit
        if not limit:
            return 0
        try:
            removed = self.library.trim(limit)
        except Exception as e:                   # noqa: BLE001
            log(f"trim library failed: {e!r}")
            return 0
        if removed:
            self.library.save()
            log(f"trim library: removed {len(removed)} (limit {limit})")
            # 列表变了，让界面刷新
            self._refreshSig.emit()
        return len(removed)


    @Property(bool, notify=statusChanged)
    def clipboardServers(self) -> bool:
        """剪贴板里发现服务器地址时，要不要弹「一键导入」。

        关掉之后程序**不再读剪贴板**（SettingsPage 那个开关一拨，
        QML 里的轮询 Timer 也跟着停），不是只在界面上不弹。
        """
        return bool(self.config["clipboard_servers"])

    @Slot(bool)
    def setClipboardServers(self, value: bool) -> None:
        self.config["clipboard_servers"] = bool(value)
        self.config.save()
        if not value:
            # 关掉时忘掉「上次看过的那段」，重新打开后同一段还能再问一次
            self._servers.resetClipboardSeen()
        self.statusChanged.emit()

    @Property(int, notify=statusChanged)
    def intervalText(self) -> int:
        return int(self.config["interval_min"])

    # ================================================================= 扫描
    @Slot()
    def scan_now(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._set_status("正在连接 B 站…")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self) -> None:
        keywords = self.config.keywords()
        pages = int(self.config["max_pages"])

        # 多个关键词逐个搜，按 bvid 合并去重（同一个视频只保留第一次出现的记录）
        merged: dict[str, dict] = {}
        hits_by_kw: dict[str, int] = {}
        failed: list[str] = []
        last_error = ""

        for idx, kw in enumerate(keywords, start=1):
            if len(keywords) > 1:
                self._set_status(f"正在搜索 {idx}/{len(keywords)}：{kw}…")
            try:
                items = self.client.search(kw, max_pages=pages)
            except BiliError as e:
                log(f"scan failed [{kw}]: {e}")
                failed.append(kw)
                last_error = str(e)
                continue
            except Exception as e:  # noqa: BLE001  防一手未知异常
                log(f"scan crashed [{kw}]: {e!r}")
                failed.append(kw)
                last_error = str(e)
                continue

            hits_by_kw[kw] = len(items)
            for it in items:
                bvid = it.get("bvid") or ""
                if not bvid:
                    continue
                existing = merged.get(bvid)
                if existing is None:
                    it["_keywords"] = [kw]
                    merged[bvid] = it
                else:
                    # 同一个视频被多个关键词命中，合并关键词标记，不重复入库
                    old_kw = existing.setdefault("_keywords", [])
                    if kw not in old_kw:
                        old_kw.append(kw)

            # 关键词之间稍作间隔，别把接口打太密
            if idx < len(keywords):
                time.sleep(0.5)

        if not merged:
            msg = last_error or "没有搜到任何视频"
            # 扫描失败也要把「启动那一次」的标记清掉，否则下一轮周期扫描
            # 会误以为还是启动扫描，继续去关用户的开关。
            self._startup_scan = False
            self._set_busy(False)
            self._set_status(f"扫描失败：{msg}")
            self.scanFinished.emit(False, msg, 0)
            return

        items = list(merged.values())

        with self._lock:
            first = self.library.first_run()
            discovered = self.library.merge_scan(items)
            if first:
                # 首次扫描只做基线，不提醒（不然一上来就十几个"新"视频）
                self.library.finish_first_run()
                self.library.mark_all_seen()
                discovered = []
            self.library.save()

        # 扫完按「视频库上限」裁一次（不设上限时是 no-op，不产生任何开销）
        self._trim_library()

        # 新视频补一次详情（拿完整简介），顺便下载封面
        if discovered:
            for rec in discovered[:12]:
                try:
                    detail = self.client.video_detail(rec["bvid"])
                    rec.update({k: v for k, v in detail.items() if v not in (None, "", 0)})
                    rec["desc"] = detail.get("desc") or rec.get("desc") or ""
                    rec["detail_loaded"] = True
                except BiliError:
                    pass
            self.library.save()

        self._download_covers([v["bvid"] for v in self.library.all_items()][:60])

        # 扫描结果落库后刷新界面（首次基线也要刷新，否则列表是空的）
        self._refreshSig.emit()

        # 首次基线完成后自动开启后台监控
        if first and int(self.config["interval_min"]) > 0:
            QTimer.singleShot(0, lambda: self.start_monitor(quiet=True))

        count = len(discovered)
        auto_off_new = False
        # 启动那一次扫描没新视频 → 自动关掉「只看新的」，别让列表空着
        if self._startup_scan:
            self._startup_scan = False
            if (not count and self.config["show_only_new"]
                    and self.library.all_items() and not self._closing):
                self.config["show_only_new"] = False
                self.config.save()
                auto_off_new = True
                self._refreshSig.emit()
        self._set_busy(False)
        if count:
            status = f"发现 {count} 个新视频！"
            if failed:
                status += f"（{len(failed)} 个关键词失败）"
            self._set_status(status)
            names = [d.get("title", "") for d in discovered[:3]]
            lines = [f"{d.get('author', '')} · {fmt_rel(d.get('pubdate'))}" for d in discovered[:3]]
            if count > 3:
                lines[-1] = f"…等共 {count} 个"
            self.newItemsFound.emit([_decorate(d) for d in discovered])
            self.notify_new(count, names, lines)
        elif first:
            self._set_status(
                f"已建立基线，共 {len(self.library.videos)} 个视频（来自 {len(hits_by_kw)} 个关键词），开始监控"
                + ("（没有新视频，已自动关掉「只看新的」）" if auto_off_new else "")
            )
        else:
            extra = f"，{len(failed)} 个关键词失败" if failed else ""
            if auto_off_new:
                self._set_status(f"没有新视频，已自动关掉「只看新的」，显示全部{extra}")
            else:
                self._set_status(f"没有新视频，一切正常{extra}")
        self.scanFinished.emit(True, self._status, count)

    def notify_new(self, count: int, titles: list[str], meta_lines: list[str]) -> None:
        if not self.config["notify_toast"]:
            return
        title = f"求生之路2公开 · 新视频 {count} 个"
        lines: list[str] = []
        for i, t in enumerate(titles):
            extra = meta_lines[i] if i < len(meta_lines) else ""
            lines.append(f"{t[:40]}{('  ' + extra) if extra else ''}")
        if count > len(titles):
            lines.append(f"…还有 {count - len(titles)} 个，打开软件查看")
        self.notifier.notify(title, lines)

    # ================================================================= 详情
    @Slot(str)
    def openDetail(self, bvid: str) -> None:
        if not bvid:
            return
        rec = self.library.videos.get(bvid) or {}
        self._detail_bvid = bvid
        if rec.get("detail_loaded") and rec.get("desc"):
            # 先显示缓存，立即有内容
            self.detailReady.emit(self._detail_payload(rec))
        # ★ 无论如何都要后台重拉一次。
        #   以前这里「已有 desc 就直接 return」的写法，只在没查过置顶评论时
        #   才补一次评论，于是：
        #     - UP 主改了简介 / 换了置顶评论 → 永远显示第一次抓到的旧内容
        #     - 评论区当时查失败（风控 -352）留了个空 topComment → 之后也不再补
        #   现在统一走一遍 _detail_worker：它会重拉详情 + 重查置顶评论，
        #   再推一次 detailReady，界面上的数据就跟着更新了。
        if not (rec.get("detail_loaded") and rec.get("desc")):
            self._set_status("正在加载简介…")
        threading.Thread(target=self._detail_worker, args=(bvid,), daemon=True).start()

    @Slot()
    def clearDetail(self) -> None:
        """详情面板关掉了：后台刷新回来就别再推界面更新了。"""
        self._detail_bvid = ""

    def _detail_worker(self, bvid: str) -> None:
        try:
            detail = self.client.video_detail(bvid)
        except BiliError as e:
            self.detailFailed.emit(str(e))
            self._set_status(f"简介加载失败：{e}")
            return
        rec = self.library.videos.get(bvid)
        if rec is None:
            rec = {
                "bvid": bvid,
                "title": detail.get("title"),
                "author": detail.get("author"),
                "pubdate": detail.get("pubdate"),
                "url": detail.get("url"),
                "is_new": False,
                "discovered_at": time.time(),
            }
            self.library.videos[bvid] = rec
        # 标题/作者/简介这类「UP 主可以改」的字段，这次拉回来的才准；
        # 但 desc 为空时别把已有的简介冲掉（有些接口偶尔不回 desc）。
        old_desc = rec.get("desc") or ""
        rec.update(detail)
        new_desc = (detail.get("desc") or "").strip()
        rec["detail_loaded"] = True
        rec["desc"] = new_desc or old_desc
        rec["detailCheckedAt"] = int(time.time())
        # 置顶评论：**每次都重查**，不能只在第一次查。
        # 以前只在 "topComment" not in rec 时查，于是 UP 主后来置顶了新评论
        # （或脚本里存的是旧评论）就再也不更新，用户看到的一直是旧的。
        try:
            top = self.client.top_comment(int(detail.get("aid") or 0), bvid)
        except Exception as e:  # noqa: BLE001  评论挂了不能影响详情
            log(f"top comment crashed {bvid}: {e!r}")
            top = rec.get("topComment") or {}
        # 这次确实查到了才覆盖；查失败（空字典）就保留上次的，免得把好的刷成空
        if top:
            rec["topComment"] = top
        rec.setdefault("topComment", {})
        self.library.save()
        cover = rec.get("coverPath") or self.client.download_cover(detail.get("cover", ""), bvid)
        if cover:
            rec["coverPath"] = cover
            self.model.update_cover(bvid, cover)
        # 只有用户还停在这个视频的详情上才推更新，
        # 否则在后台刷新别的视频会把已经切走的详情页覆盖掉。
        if self._detail_bvid == bvid:
            self.detailReady.emit(self._detail_payload(rec))
        # 这里**不能**调 _rebuild()：它会 beginResetModel，正在看的列表会直接
        # 跳回最顶上（「点开视频详情就滚回开头」就是这么来的）。
        # 详情加载只多了一点简介/封面，原位把那一行换掉就够。
        #
        # ★ 但这一行必须回主线程换：本函数跑在后台线程，直接调 _refresh_one()
        #   会让 dataChanged 从非 GUI 线程发出，QQuickListView 不重绘 ——
        #   表现就是「详情里的播放/点赞数变了，列表卡片还是旧的」。
        self._oneSig.emit(bvid)

    def _refresh_one(self, bvid: str) -> None:
        """只刷新列表里的一条（原位 dataChanged，不动滚动位置）。"""
        if self._closing:
            return
        rec = self.library.videos.get(bvid)
        if not rec:
            return
        if not self.model.update_item(bvid, _decorate(rec)):
            # 这条被搜索/筛选挡住了，不在模型里 —— 什么都不用做
            return

    @staticmethod
    def _detail_payload(rec: dict) -> dict:
        d = _decorate(rec)
        desc = rec.get("desc") or ""
        d["desc"] = desc or "（这个视频没有简介）"
        d["views"] = max(int(rec.get("views") or 0), int(rec.get("play") or 0))
        d["viewsText"] = fmt_count(d["views"])
        d["replyText"] = fmt_count(rec.get("reply") or 0)
        d["likeText"] = fmt_count(rec.get("like") or 0)
        d["favText"] = fmt_count(rec.get("favorite") or 0)
        d["coinText"] = fmt_count(rec.get("coin") or 0)
        d["shareText"] = fmt_count(rec.get("share") or 0)
        d["tname"] = rec.get("tname") or ""
        d["pages"] = int(rec.get("pages") or 1)
        d["pubText"] = fmt_ts(rec.get("pubdate"), "%Y-%m-%d %H:%M:%S")
        d["coverUrl"] = file_url(rec.get("coverPath") or "") or norm_url(rec.get("cover") or "")
        # 简介里的网盘链接（推断不出文件说明时用视频标题兜底）
        d["links"] = extract_links(desc, fallback_label=rec.get("title") or "")
        # 置顶评论（没有就是空字典，界面据此决定显不显示那一块）
        top = rec.get("topComment") or {}
        d["topComment"] = top
        # 置顶评论里如果也发了网盘，一样提取出来 —— UP 主经常把链接放评论里
        if top.get("text"):
            extra = extract_links(top["text"], fallback_label=rec.get("title") or "")
            if extra:
                seen = {lk.get("url") for lk in d["links"]}
                d["commentLinks"] = [lk for lk in extra if lk.get("url") not in seen]
                d["links"] = list(d["links"]) + d["commentLinks"]
            else:
                d["commentLinks"] = []
        else:
            d["commentLinks"] = []
        return d

    # ================================================================= 封面
    def _download_covers(self, bvids: list[str]) -> None:
        for bvid in bvids:
            rec = self.library.videos.get(bvid)
            if not rec or rec.get("coverPath") and os.path.exists(rec.get("coverPath") or ""):
                continue
            self._cover_pool.submit(self._cover_one, bvid)

    def _cover_one(self, bvid: str) -> None:
        rec = self.library.videos.get(bvid)
        if not rec:
            return
        url = norm_url(rec.get("cover") or "")
        path = self.client.download_cover(url, bvid)
        if path:
            rec["coverPath"] = path
            self._coverSig.emit(bvid, path)

    def _queue_model_refresh(self) -> None:
        # 封面是后台线程下的，统一让主线程刷新模型
        self._refreshSig.emit()

    # ================================================================= 列表
    def _rebuild(self) -> None:
        if self._closing:
            return
        items = self.library.all_items()
        if self._filter:
            f = self._filter.lower()
            items = [
                v for v in items
                if f in (v.get("title") or "").lower()
                or f in (v.get("author") or "").lower()
                or f in (v.get("desc") or "").lower()
                or f in (v.get("tag") or "").lower()
            ]
        if self.config["show_only_new"]:
            items = [v for v in items if v.get("is_new")]
        if self._date_filter:
            cutoff = int(time.time()) - self._date_filter * 86400
            items = [v for v in items if int(v.get("pubdate") or 0) >= cutoff]
        if self._sort == "views":
            items.sort(
                key=lambda v: max(int(v.get("views") or 0), int(v.get("play") or 0)),
                reverse=True,
            )
        else:
            items.sort(key=lambda v: int(v.get("pubdate") or 0), reverse=True)
        self.model.set_items([_decorate(v) for v in items])
        self.videosChanged.emit()
        self.listChanged.emit()

    @Slot()
    def refresh(self) -> None:
        self._rebuild()

    # ================================================================= 操作
    @Slot(str)
    def markSeen(self, bvid: str) -> None:
        self.library.mark_seen(bvid)
        # 原位刷新，别整表重建 —— 用户可能正滚到一半
        self._refresh_one(bvid)
        self.videosChanged.emit()

    @Slot()
    def markAllSeen(self) -> None:
        self.library.mark_all_seen()
        self._rebuild()
        self._set_status("已全部标记为已读")
        self.toast("已全部标记为已读", "ok")

    @Slot(str)
    def removeVideo(self, bvid: str) -> None:
        self.library.remove(bvid)
        self._rebuild()
        self._set_status("已从列表移除")
        self.toast("已从列表移除", "ok")

    @Slot()
    def clearAll(self) -> None:
        self.library.clear_all()
        self.library.meta["first_run"] = True
        self.library.save()
        self._rebuild()
        self._set_status("已清空本地记录，下次扫描将重新建立基线")

    @Slot(str)
    def openVideoUrl(self, bvid: str) -> None:
        url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
        self.openUrl(url)

    @Slot(str)
    def openUrl(self, url: str) -> None:
        if not url:
            return
        QUrl.fromUserInput(url)
        from PySide6.QtCore import QUrl as _QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(_QUrl(url))

    @Slot(str)
    def copyText(self, text: str) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text or "")
            self._set_status("已复制到剪贴板")
            self.toast("已复制到剪贴板", "ok")

    @Slot(str)
    def copyLink(self, bvid: str) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(f"https://www.bilibili.com/video/{bvid}")
        self._set_status("已复制视频链接")
        self.toast("已复制视频链接", "ok")

    @Slot(str, str)
    def copyCode(self, code: str, name: str = "") -> None:
        """复制网盘提取码（右键网盘那一行时用）。"""
        value = (code or "").strip()
        if not value:
            self._set_status("这个网盘没有提取码")
            self.toast("这个网盘没有提取码", "warn")
            return
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(value)
            self._set_status(
                f"已复制提取码 {value}" + (f"（{name}）" if name else "")
            )
            self.toast(
                f"已复制提取码 {value}" + (f"（{name}）" if name else ""), "ok"
            )

    @Slot("QVariantMap")
    def copyDesc(self, video: dict) -> None:
        text = (
            f"{video.get('title', '')}\n"
            f"UP：{video.get('author', '')}\n"
            f"发布：{video.get('pubText', '')}\n"
            f"链接：https://www.bilibili.com/video/{video.get('bvid', '')}\n\n"
            f"{video.get('desc', '')}"
        )
        self.copyText(text)

    # ================================================================= 分享
    @staticmethod
    def _share_text(video: dict) -> str:
        """拼一段可以直接粘到群里的分享文案。

        内容：标题 + 视频链接 + UP 主（带主页链接）+ 发布日期 +
        简介/置顶评论里提取到的网盘链接和提取码。
        作者、日期、网盘这三段都是「有才出现」，没有的视频就是干净的「标题 + 链接」。
        """
        title = str(video.get("title") or "").strip()
        bvid = str(video.get("bvid") or "").strip()
        url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""

        lines: list[str] = []
        if title:
            lines.append(title)
        if url:
            lines.append(url)

        # UP 主：有 mid 就带上主页链接，没有就只写名字
        up = str(video.get("author") or "").strip()
        mid = str(video.get("mid") or "").strip()
        space = f"https://space.bilibili.com/{mid}" if mid and mid != "0" else ""
        if up:
            lines.append(f"UP：{up}" + (f"（{space}）" if space else ""))

        # 发布日期（界面 payload 里的 pubText 已经格式化成「年-月-日 时:分:秒」）
        pub = str(video.get("pubText") or "").strip()
        if pub:
            lines.append(f"发布：{pub}")

        # 网盘链接：主简介里的 + 置顶评论里补出来的，都算上
        links: list[dict] = []
        seen: set[str] = set()
        for lk in list(video.get("links") or []) + list(video.get("commentLinks") or []):
            u = str(lk.get("url") or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            links.append(lk)

        if links:
            lines.append("")
            lines.append("网盘：")
            for lk in links:
                name = str(lk.get("name") or "网盘").strip()
                link = str(lk.get("url") or "").strip()
                code = str(lk.get("code") or "").strip()
                label = str(lk.get("label") or "").strip()
                row = f"{name} {link}"
                if code:
                    row += f" 提取码 {code}"
                if label:
                    row += f"（{label}）"
                lines.append(row)
        return "\n".join(lines)

    @Slot("QVariantMap")
    def shareVideo(self, video: dict) -> None:
        """一键分享：标题 + 链接 + UP 主（含主页）+ 发布日期 + 网盘链接和提取码。"""
        text = self._share_text(video or {})
        if not text.strip():
            self.toast("这条视频没有可分享的内容", "warn")
            return
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text)
        n_links = len(video.get("links") or [])
        extra = f"（含 {n_links} 个网盘链接）" if n_links else ""
        self._set_status("已复制分享内容")
        self.toast(f"已复制标题、作者、日期和链接{extra}", "ok")

    @Slot("QVariantMap", result=str)
    def shareText(self, video: dict) -> str:
        """给界面做预览用：返回分享出去的那段文字。"""
        return self._share_text(video or {})

    # ================================================================= UP 主卡片
    @Slot(str)
    def openAuthor(self, bvid: str) -> None:
        """打开视频作者的小卡片（头像/昵称/简介 + 近期视频）。"""
        rec = self.library.videos.get(bvid) or {}
        mid = int(rec.get("mid") or 0)
        if mid <= 0:
            # 本地记录里没有 mid，先拉一次详情补上
            threading.Thread(target=self._author_prefetch, args=(bvid,), daemon=True).start()
            return
        self._set_status("正在加载 UP 主信息…")
        threading.Thread(target=self._author_worker, args=(mid,), daemon=True).start()

    def _author_prefetch(self, bvid: str) -> None:
        try:
            detail = self.client.video_detail(bvid)
        except BiliError as e:
            self.authorFailed.emit(str(e))
            return
        rec = self.library.videos.get(bvid)
        if rec is not None:
            rec.update(detail)
            self.library.save()
        mid = int(detail.get("mid") or 0)
        if mid <= 0:
            self.authorFailed.emit("这个视频没有作者信息")
            return
        self._author_worker(mid)

    def _author_worker(self, mid: int) -> None:
        try:
            card = self.client.user_card(mid)
        except BiliError as e:
            self.authorFailed.emit(str(e))
            self._set_status(f"UP 主信息加载失败：{e}")
            return

        # 缓存头像到本地，避免每次都要联网
        face = card.get("face") or ""
        if face:
            try:
                local = self.client.download_cover(face, f"face_{mid}")
                if local:
                    card["faceLocal"] = file_url(local)
            except Exception:  # noqa: BLE001
                pass

        # 近期视频
        try:
            card["videos"] = self.client.user_videos(mid, card.get("name") or "", 6)
        except BiliError:
            card["videos"] = []

        self.authorReady.emit(card)
        self._set_status(f"{card.get('name') or 'UP 主'} · {len(card.get('videos') or [])} 个近期视频")

    # ================================================================= 工具
    @Slot(str)
    def openSpace(self, mid: str) -> None:
        if mid:
            self.openUrl(f"https://space.bilibili.com/{mid}")

    @Slot(str)
    def openUploadPage(self, mid: str) -> None:
        if mid:
            self.openUrl(f"https://space.bilibili.com/{mid}/upload/video")

    # ================================================================= 播放
    @Slot(str)
    def playVideo(self, bvid: str) -> None:
        """内置播放器播放指定视频."""
        if not bvid:
            return
        rec = self.library.videos.get(bvid) or {}
        title = rec.get("title") or bvid
        self._player_obj.open(bvid, title)
        self._set_status(f"正在准备播放：{title[:24]}")

    @Slot()
    def stopVideo(self) -> None:
        self._player_obj.stop()

    # ---- 缓存管理 ----
    #
    # 只剩「封面缓存」是真实存在的。以前这里还有一套「视频缓存」：
    # `VideoPlayer.cacheSize()/clearCache()` 对着 `cache/video/` 统计和删除，
    # 但**没有任何代码往那个目录写文件** —— 视频是流式播放的，缓冲在
    # QtMultimedia 手里。所以那套接口永远返回 0 B，点清空也清不出东西，
    # 设置在界面上就是个摆设（用户看出来的）。现在整块删掉：
    # 隐藏一个不存在的功能，比留一个假的按钮诚实。
    @Property("QVariantMap", notify=cacheChanged)
    def modCache(self) -> dict:
        return mod_cache_info()

    @Property(str, notify=cacheChanged)
    def cacheSummary(self) -> str:
        m = mod_cache_info()
        return human_bytes(int(m.get("bytes") or 0))

    @Slot(result="QVariantMap")
    def clearAllCaches(self) -> dict:
        m = clear_mod_cache()
        self.cacheChanged.emit()
        freed = int(m.get("bytes") or 0)
        self._set_status(f"已清理缓存，释放 {human_bytes(freed)}")
        return {"bytes": freed, "text": human_bytes(freed)}

    @Slot(result="QVariantMap")
    def clearModCache(self) -> dict:
        m = clear_mod_cache()
        self.cacheChanged.emit()
        self._set_status(f"已清理 MOD 封面缓存，释放 {m.get('text', '0 B')}")
        return m

    @Slot("QVariantMap")
    def openPanLink(self, link: dict) -> None:
        """点网盘链接：打开链接，如果带提取码就一起复制到剪贴板."""
        url = (link or {}).get("url") or ""
        if not url:
            return
        code = (link or {}).get("code") or ""
        if code:
            cb = QGuiApplication.clipboard()
            if cb is not None:
                cb.setText(code)
            self._set_status(f"提取码 {code} 已复制，正在打开{link.get('name', '网盘')}…")
        else:
            self._set_status("正在打开网盘链接…")
        self.openUrl(url)

    @Slot(str, result="QVariantList")
    def extractDescLinks(self, text: str) -> list:
        return extract_links(text or "")

    @Slot(str, result="QVariantMap")
    def findVideo(self, bvid: str) -> dict:
        rec = self.library.videos.get(bvid)
        return _decorate(rec) if rec else {}

    # ================================================================= 监控
    @Slot()
    def toggleMonitor(self) -> None:
        if self._timer.isActive():
            self.stop_monitor()
        else:
            self.start_monitor()

    @Slot()
    @Slot(bool)
    def start_monitor(self, quiet: bool = False) -> None:
        minutes = int(self.config["interval_min"])
        if minutes <= 0:
            minutes = 10
            self.config["interval_min"] = minutes
            self.config.save()
        self._timer.setInterval(max(1, minutes) * 60 * 1000)
        self._timer.start()
        if not quiet:
            self._set_status(f"后台监控已开启，每 {minutes} 分钟检查一次")
        self.statusChanged.emit()
        self.monitorChanged.emit()

    @Slot()
    def stop_monitor(self) -> None:
        self._timer.stop()
        self._set_status("后台监控已暂停")
        self.statusChanged.emit()
        self.monitorChanged.emit()

    @Slot(int, result="QVariantMap")
    def setIntervalAndRestart(self, minutes: int) -> dict:
        """设置面板里点间隔按钮：一次搞定改配置 + 开关监控。"""
        minutes = max(0, min(720, int(minutes)))
        self.config["interval_min"] = minutes
        self.config.save()
        if minutes == 0:
            self._timer.stop()
            self._set_status("自动刷新已关闭")
        else:
            self._timer.setInterval(minutes * 60 * 1000)
            self._timer.start()
            self._set_status(f"已设为每 {minutes} 分钟自动刷新")
        self.statusChanged.emit()
        self.monitorChanged.emit()
        return {"interval": minutes, "monitoring": self._timer.isActive()}

    # ================================================================= 软件更新
    @Property("QVariantMap", notify=updateChanged)
    def updateInfo(self) -> dict:
        """「关于」里的检查更新弹窗要读的全部信息。"""
        return self._update_info

    @Property(bool, notify=updateChanged)
    def updateChecking(self) -> bool:
        return self._update_checking

    @Property(bool, notify=updateChanged)
    def updateDownloading(self) -> bool:
        return self._update_downloading

    @Property(bool, notify=statusChanged)
    def autoCheckUpdate(self) -> bool:
        """设置页的「自动检测更新」开关：每次打开软件时检查一遍。"""
        return bool(self.config["auto_check_update"])

    @Slot(bool)
    def setAutoCheckUpdate(self, value: bool) -> None:
        self.config["auto_check_update"] = bool(value)
        self.config.save()
        self.statusChanged.emit()

    def _auto_check_once(self) -> None:
        """启动时按设置静默检查一次（不弹检查弹窗，只在有新版时提示一句）。"""
        if not bool(self.config["auto_check_update"]):
            return
        self._auto_check_requested = True
        self.checkUpdate()

    @Slot()
    def checkUpdate(self) -> None:
        """检查 GitHub Releases 上的新版本（后台线程，结果经 updateChanged 回主线程）。"""
        if self._update_checking:
            return
        self._update_checking = True
        self.updateChanged.emit()
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self) -> None:
        from . import APP_VERSION

        try:
            info = check_update(GITHUB_REPO, APP_VERSION)
        except Exception as e:  # noqa: BLE001 —— 任何异常都要变成 error 字段，不能让线程静默死掉
            info = {
                "has_update": False,
                "current": APP_VERSION,
                "latest": "",
                "note": "",
                "url": "",
                "error": f"检查更新失败：{e}",
            }
        info["current"] = APP_VERSION
        self._update_info = info
        self._update_checking = False
        self.updateChanged.emit()
        if (
            self._auto_check_requested
            and not info.get("error")
            and info.get("has_update")
        ):
            self.toast(
                f"发现新版本 {info.get('latest')}，可在「关于」里查看更新", "info"
            )

    @Slot()
    def downloadUpdate(self) -> None:
        """下载并安装更新包（后台线程，装好后自动重启软件）。"""
        url = (self._update_info or {}).get("url") or ""
        if not url:
            self.toast("没有找到可用的更新包链接", "warn")
            return
        if self._update_downloading:
            return
        self._update_downloading = True
        self.updateChanged.emit()
        threading.Thread(
            target=self._download_worker, args=(url,), daemon=True
        ).start()

    def _download_worker(self, url: str) -> None:
        try:
            download_and_install(url)
            self._set_status("更新包已安装，重启后生效")
            self.toast("更新完成，软件即将重启…", "ok")
            QTimer.singleShot(1500, self._relaunch_after_update)
        except Exception as e:  # noqa: BLE001
            self._set_status(f"更新失败：{e}")
            self.toast(f"更新失败：{e}", "error")
        self._update_downloading = False
        self.updateChanged.emit()

    def _relaunch_after_update(self) -> None:
        """替换完 exe 后用新程序重新拉起，再退出当前进程。"""
        try:
            import sys

            from PySide6.QtCore import QProcess

            QProcess.startDetached(sys.executable)
        except Exception as e:  # noqa: BLE001
            log(f"relaunch failed: {e!r}")
        self.quit_app()

    # ================================================================= 工具
    def _set_busy(self, value: bool) -> None:
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit()

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()

    def toast(self, text: str, level: str = "info") -> None:
        """动作型提示：QML 侧会弹一个浮层然后淡出。"""
        if text:
            self.toastRequested.emit(text, level or "info")

    @Slot(str, str)
    def showToast(self, text: str, level: str = "info") -> None:
        """给 QML 直接调用的入口（比如纯前端的复制操作）。

        注意别叫 notifyToast：那个名字已经被「是否弹系统通知」的 Property 占了，
        同名会让 Property 被这个 Slot 顶掉，QML 里读到的永远是个函数对象。
        """
        self.toast(text, level)

    @Slot()
    def quit_app(self) -> None:
        self.shutdown()
        self.app.quit()

    def shutdown(self) -> None:
        """退出前收尾：停定时器 / 停后台线程 / 停播放器 / 存盘。

        顺序很重要：先置 _closing 让还在跑的后台线程别再回主线程改模型，
        否则扫描线程会对已经析构的 QAbstractListModel 调 beginResetModel，
        报 libshiboken: Internal C++ object already deleted 直接崩在退出时。
        """
        self._closing = True
        try:
            self._timer.stop()
        except Exception as e:  # noqa: BLE001
            log(f"timer stop failed: {e!r}")
        try:
            self.mods.shutdown()
        except Exception as e:  # noqa: BLE001
            log(f"mods shutdown failed: {e!r}")
        try:
            self._player_obj.shutdown()
        except Exception as e:  # noqa: BLE001
            log(f"player shutdown failed: {e!r}")
        try:
            self._sound.stop_all()
        except Exception as e:  # noqa: BLE001
            log(f"sound player shutdown failed: {e!r}")
        try:
            self._cover_pool.shutdown(wait=False, cancel_futures=True)
        except Exception as e:  # noqa: BLE001
            log(f"cover pool shutdown failed: {e!r}")
        try:
            self._servers.shutdown()
        except Exception as e:  # noqa: BLE001
            log(f"servers shutdown failed: {e!r}")
        try:
            self._downloads.shutdown()
        except Exception as e:  # noqa: BLE001
            log(f"downloads shutdown failed: {e!r}")
        try:
            self.config.save()
            self.library.save()
        except OSError:
            pass
