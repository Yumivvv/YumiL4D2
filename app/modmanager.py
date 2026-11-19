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

"""给 QML 用的 MOD 管理器（作为 Yumi的L4D2工具箱的一个功能页）.

负责：
  * 自动探测 / 手动设置 L4D2 的 addons 目录
  * 扫描本地 mod 和 workshop 云 mod
  * 云 mod 识别（查工坊名称、下封面）
  * 导入（含同名图片自动带上）
  * 启用/禁用、删除、移植到本地
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import threading
import time

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    Qt,
    QUrl,
    Signal,
    Slot,
)

from . import mods as M
from . import addonlist as AL
from . import vpk_reader as VD
from . import workshop_dl as WD
from . import workshop_dns as WDNS
from . import workshop_net as WN
from .imageproxy import CoverProxy
from .store import Config
from .util import DATA_DIR, Log, fmt_ts

# 别名：_match_import_date 里用 _time.time()，和模块里已有的 time 用法区分开
_time = time

log = Log("mods_ui.log")

FAV_PATH = os.path.join(DATA_DIR, "favorites.json")


def _file_url(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    return QUrl.fromLocalFile(path).toString()


class ModListModel(QAbstractListModel):
    # 角色名不能叫 "enabled" —— QML 的 delegate 里 `required property bool enabled`
    # 会和 Item 自带的 enabled 撞名，Qt 会告警
    # 「Member enabled overrides a member of the base object」，
    # 而且那个属性被当成可见性开关，容易连点都点不动。
    # 对外叫 enabledState，内部数据键仍然是 enabled。
    ROLE_ALIAS = {"enabledState": "enabled"}

    ROLES = [
        "path", "name", "title", "stem", "sizeText", "size", "imageUrl",
        "hasImage", "workshopId", "isWorkshop", "isKnown", "inWorkshopDir",
        "enabledState", "mtimeText", "disabledName", "desc", "pageUrl",
        "selectable", "checked", "isLocal",
        # 卡片/详情用的扩展字段
        "category", "categoryLabel", "content", "favorited", "tags",
        "viewsText", "subsText", "createdText", "dirText", "selected",
        "hasUpdate", "updateText", "updatedText",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return {i + 0x0100: n.encode() for i, n in enumerate(self.ROLES)}

    def data(self, index: QModelIndex, role: int = -1):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role < 0x0100:
            return None
        name = self.ROLES[role - 0x0100]
        return item.get(self.ROLE_ALIAS.get(name, name))

    def set_items(self, items: list[dict]) -> None:
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def items(self) -> list[dict]:
        return list(self._items)

    def set_checked(self, row: int, value: bool) -> None:
        if 0 <= row < len(self._items):
            self._items[row]["checked"] = value
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [0x0100 + self.ROLES.index("checked")])

    def update_item(self, row: int, item: dict) -> None:
        """原位替换某一行，只发 dataChanged。

        不能走 set_items()，因为它会 beginResetModel，ListView 会
        重置滚动位置直接跳回顶部 —— 启用/禁用单个 mod 时非常难受。
        """
        if 0 <= row < len(self._items):
            self._items[row] = item
            idx = self.index(row, 0)
            self.dataChanged.emit(
                idx, idx, [0x0100 + i for i in range(len(self.ROLES))]
            )

    @Slot(str, result=int)
    def row_of_path(self, path: str) -> int:
        """按路径（大小写不敏感）找行号，找不到返回 -1。

        必须标 @Slot —— 它要从 QML 里调（点开详情后把那张卡滚回视野）。
        没有装饰器时 QML 调它只会静默失败，滚动毫无反应。
        """
        key = os.path.normcase(path or "")
        for i, it in enumerate(self._items):
            if os.path.normcase(it.get("path") or "") == key:
                return i
        return -1

    def checked_paths(self) -> list[str]:
        return [it["path"] for it in self._items if it.get("checked")]


class ModManager(QObject):
    """MOD 管理器门面。"""

    modsChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    addonsDirChanged = Signal()
    scannedChanged = Signal()
    workshopProgress = Signal(int, int)
    importFinished = Signal(int, int)      # 成功数, 跳过数
    detectFailed = Signal(str)
    selectionChanged = Signal()
    detailChanged = Signal()               # 右侧 MOD 详情面板刷新
    toastRequested = Signal(str, str)      # (文字, 级别) info/ok/warn/error
    # 创意工坊导入：解析完成 / 解析进度 / 下载完成
    workshopProbed = Signal("QVariantMap")
    workshopProbeProgress = Signal(str, int, int)
    # 合集成员的后继批次（先给前 60 个，剩下的边拉边补）
    workshopMembersChanged = Signal("QVariantMap")
    # 工坊统计数字（浏览/订阅/收藏/发布/更新）回来了
    workshopStatsChanged = Signal("QVariantMap")
    workshopDownloaded = Signal("QVariantMap")
    # 翻译完成（异步）
    translationReady = Signal("QVariantMap")
    # 工坊浏览列表变化
    browseChanged = Signal()
    # 工坊浏览「追加了一页」（无限滚动用，整表变化走 browseChanged）
    browseAppended = Signal()
    # CDN 节点测速进度 / 完成
    cdnTestChanged = Signal()
    # 工坊 DNS 设置变化（和加速分开，各自有各自的信号）
    dnsChanged = Signal()
    # 加载顺序（addonlist.txt）
    addonOrderChanged = Signal()
    # 导入日期筛选（快捷档 / 自定义区间）变化
    # ★ 必须单独一个信号：以前这几个 Property 声明的是 notify=selectionChanged，
    #   但 setter 实际 emit 的是 statusChanged —— 信号对不上，QML 的绑定永远不刷新，
    #   表现为「点日期筛选按钮没反应」。
    importFilterChanged = Signal()
    # 选中某个 MOD 后发一次（带上 path）。QML 收到后把那张卡滚回视野 ——
    # 详情面板一开，网格从 4 列挤成 3 列，卡片会重排，用户就找不着自己点的那个了。
    revealPath = Signal(str)
    _authorsReady = Signal()               # 后台补完昵称，排队回主线程刷新

    def __init__(self, parent=None):
        super().__init__(parent)
        self._addons_dir = ""
        self._local = ModListModel(self)
        self._workshop = ModListModel(self)
        self._all = ModListModel(self)
        self._wsc = M.WorkshopClient()
        self._busy = False
        self._status = "还没扫描"
        self._scanned = False
        self._filter = ""
        self._min_mb = 0.0      # 0 = 不限
        self._max_mb = 0.0      # 0 = 不限
        self._state_filter = 0  # 已废弃：启用状态筛选挪到侧边栏「状态」，这里只为兼容保留
        self._status_filter = 0  # 0=全部 1=已启用 2=未启用 3=创意工坊 4=我的收藏 5=可更新
        self._sort_mode = 0      # 0=默认 1=优先看启用 2=优先看禁用 3=优先看收藏 4=字母排序 5=最近导入
        self._category = ""      # "" = 全部分类
        # 按「导入日期」筛选：
        #   _import_days > 0 表示「最近 N 天」（快捷档：1/7/30/180）
        #   _import_from / _import_to 是自定义区间（"YYYY-MM-DD"，空串=不限）
        # 快捷档和自定义区间互斥，后设置的那个会清掉前一个。
        self._import_days = 0
        self._import_from = ""
        self._import_to = ""
        self._tab = 0            # 0=本地 1=云端
        self._identify_running = False
        self._last_scan_ts = 0
        self._author_running = False
        self._closing = False    # 退出时置 True，后台线程不再碰模型
        self._selected_path = ""
        self._favorites: set[str] = self._load_favorites()
        self._all_local: list[dict] = []
        self._all_workshop: list[dict] = []
        # 勾选状态的持久存储（按 path 的 normcase 记），独立于模型重建。
        # _all 模型每次 _apply_filter / _refresh_selected_flags 都会被源列表
        # 重建，如果 checked 只存模型里就会被冲掉（「选择 MOD 用不了」的根因）。
        # 这里单独记一份，重建时回填。
        self._checked_paths: set[str] = set()
        # 删除方式：True=回收站（默认） False=直接删
        self._cfg = Config()
        # ---- 筛选 / 排序要跨重启记住（用户报的）----
        # 以前这些状态只活在内存里：关掉软件再开，好不容易调好的
        # 「只看本地 + 最近导入」又回到默认，每次都得重设一遍。
        # 现在初始化时从 config 读回来，改动时写回去（见 _remember_filters）。
        try:
            self._filter = str(self._cfg["mod_filter"] or "")
            self._min_mb = float(self._cfg["mod_min_mb"] or 0)
            self._max_mb = float(self._cfg["mod_max_mb"] or 0)
            self._status_filter = int(self._cfg["mod_status_filter"] or 0)
            self._category = str(self._cfg["mod_category"] or "")
            self._sort_mode = int(self._cfg["mod_sort_mode"] or 0)
            self._import_days = int(self._cfg["mod_import_days"] or 0)
            self._import_from = str(self._cfg["mod_import_from"] or "")
            self._import_to = str(self._cfg["mod_import_to"] or "")
            self._tab = int(self._cfg["mod_tab"] or 0)
        except (TypeError, ValueError, KeyError):
            # 配置被手改坏了就当默认值，不要因为读不回来就起不来
            pass
        if self._sort_mode not in (0, 1, 2, 3, 4, 5):
            self._sort_mode = 0
        if self._status_filter not in (0, 1, 2, 3, 4, 5):
            self._status_filter = 0
        self._delete_to_recycle = bool(self._cfg["delete_to_recycle"])
        # 创意工坊导入的并发线程数（设置里可调，1-16）
        self._dl_threads = WD.clamp_threads(self._cfg["download_threads"])
        # 正在跑的下载器（取消时用）
        self._dl: WD.WorkshopDownloader | None = None
        self._probing = False
        self._probe_queued: tuple | None = None   # 上一次没跑完时排队的那次解析
        self._probe_dl: WD.WorkshopDownloader | None = None   # 正在解析的那个下载器（补成员线程挂在它身上）
        self._translating = False
        # 工坊浏览状态
        self._browse_items: list = []
        self._browse_thumbs: list = []   # 和 items 一一对应的封面地址（已按节点改写）
        self._browse_total = 0
        self._browse_page = 1
        self._browse_query = ""
        self._browse_sort = "trend"
        self._browse_kind = "mod"      # mod=单件 / collection=合集
        self._browse_tags: list = []   # 多标签是 AND
        self._browse_error = ""
        self._browse_loading = False
        self._browse_more = False      # 正在追加下一页
        self._browse_done = False      # 已经到底
        self._browse_seq = 0           # 请求序号：切分类/搜索时丢掉过期结果
        # CDN 节点（地名 + ip）与测速状态
        self._cdn_nodes: list = []
        self._cdn_testing = False
        self._cdn_rows: list = []      # [{region, ms, ok}] 只有地名，给 UI 用
        # 封面加速代理：QML 的 Image 不能自己走节点 IP，只能由本地代理代取
        self._cover_proxy = CoverProxy(node_provider=self._active_cdn_ip)
        # VPK 内部解析结果缓存（路径 → {stamp, info, imagePath, ...}）
        self._vpk_cache: dict[str, dict] = {}
        # 后台线程补完作者昵称后排队回主线程（跨线程 emit，Qt 自动走队列连接）
        self._authorsReady.connect(self._on_authors_ready, Qt.QueuedConnection)

        # 工坊 DNS：和加速相互独立，先把配置里选的解析方案装进解析器
        self._apply_workshop_dns()

        # 自动探测
        self.auto_detect(quiet=True)
        # 封面加速代理：起来之后工坊列表的封面才会走节点 IP
        try:
            self._cover_proxy.start()
        except Exception as e:  # noqa: BLE001  代理起不来不影响主功能
            log(f"cover proxy start failed: {e!r}")
        # 加速模式是「自动」但还没有可用节点时，后台测一次速（不阻塞启动）
        if self.cdnMode == "auto" and not self.cdnIp:
            threading.Thread(target=self._startup_cdn_probe, daemon=True).start()

    def _startup_cdn_probe(self) -> None:
        """启动时补一次自动优选：只在还没有节点、且用户选了自动时跑。"""
        time.sleep(1.5)
        if self._closing or self.cdnMode != "auto" or self.cdnIp:
            return
        try:
            self.autoSelectCdnNode()
        except Exception as e:  # noqa: BLE001
            log(f"startup cdn probe failed: {e!r}")

    # ============================================================ 收藏（本地存盘）
    @staticmethod
    def _fav_key(item: dict) -> str:
        """收藏的键：优先工坊 ID，其次文件名（不带扩展名）。

        不能用完整路径——启用/禁用会改名，路径跟着变。
        """
        wid = str(item.get("workshopId") or "").strip()
        if wid:
            return "w" + wid
        return "s" + str(item.get("stem") or item.get("name") or "").lower()

    def _load_favorites(self) -> set:
        try:
            with open(FAV_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return {str(x) for x in data}
        except (OSError, ValueError):
            pass
        return set()

    def _save_favorites(self) -> None:
        try:
            tmp = FAV_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(sorted(self._favorites), f, ensure_ascii=False, indent=2)
            os.replace(tmp, FAV_PATH)
        except OSError:
            pass


    # ================================================================ 属性
    @Property(QObject, constant=True)
    def localModel(self):
        return self._local

    @Property(QObject, constant=True)
    def workshopModel(self):
        return self._workshop

    @Property(QObject, constant=True)
    def allModel(self):
        """本地 + 云端合并后的一个列表（新版 MOD 管理器只用一个网格）。"""
        return self._all

    @Property(str, notify=addonsDirChanged)
    def addonsDir(self) -> str:
        return self._addons_dir

    @Property(str, notify=addonsDirChanged)
    def workshopDir(self) -> str:
        return os.path.join(self._addons_dir, "workshop") if self._addons_dir else ""

    @Property(bool, notify=addonsDirChanged)
    def hasDir(self) -> bool:
        return bool(self._addons_dir) and os.path.isdir(self._addons_dir)

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status

    @Property(bool, notify=scannedChanged)
    def scanned(self) -> bool:
        return self._scanned

    @Property(int, notify=modsChanged)
    def localCount(self) -> int:
        return self._local.rowCount()

    @Property(int, notify=modsChanged)
    def workshopCount(self) -> int:
        return self._workshop.rowCount()

    @Property(int, notify=modsChanged)
    def totalCount(self) -> int:
        return self._all.rowCount()

    @Property(str, notify=modsChanged)
    def totalSizeText(self) -> str:
        total = 0
        for m in self._local.items() + self._workshop.items():
            total += int(m.get("size") or 0)
        return M.human_size(total)

    @Property(str, notify=modsChanged)
    def lastScanText(self) -> str:
        if not self._last_scan_ts:
            return ""
        return "上次扫描 " + fmt_ts(self._last_scan_ts, "%H:%M:%S")

    @Property(str, notify=statusChanged)
    def filterText(self) -> str:
        return self._filter

    @Property(float, notify=statusChanged)
    def minMB(self) -> float:
        return self._min_mb

    @Property(float, notify=statusChanged)
    def maxMB(self) -> float:
        return self._max_mb

    @Property(int, notify=statusChanged)
    def sortMode(self) -> int:
        """0=默认 1=优先看启用 2=优先看禁用 3=优先看收藏 4=字母排序"""
        return self._sort_mode

    @Property(bool, notify=statusChanged)
    def hasExtraFilter(self) -> bool:
        return bool(self._min_mb or self._max_mb)

    @Property(int, notify=statusChanged)
    def hiddenCount(self) -> int:
        """被筛选挡掉的数量。用 statusChanged 通知：_apply_filter 末尾会发它。"""
        return max(0, len(self._all_local) + len(self._all_workshop) - self._all.rowCount())

    # ------------------------------------------------------------ 侧边栏统计
    @Property(int, notify=statusChanged)
    def statusFilter(self) -> int:
        """0=全部 1=已启用 2=未启用 3=创意工坊 4=我的收藏 5=可更新 6=本地"""
        return self._status_filter

    @Property(str, notify=statusChanged)
    def categoryFilter(self) -> str:
        """当前分类 key，空串=全部分类。"""
        return self._category

    @Property("QVariantMap", notify=modsChanged)
    def statusCounts(self) -> dict:
        """侧边栏「状态」那几项的数量（基于全部 MOD，不受筛选影响）。"""
        items = self._all_local + self._all_workshop
        enabled = sum(1 for m in items if m.get("enabled", True))
        workshop = sum(1 for m in items if m.get("inWorkshopDir"))
        fav = sum(1 for m in items if m.get("favorited"))
        upd = sum(1 for m in items if m.get("hasUpdate"))
        return {
            "all": len(items),
            "enabled": enabled,
            "disabled": len(items) - enabled,
            "workshop": workshop,
            "local": len(items) - workshop,
            "favorite": fav,
            "updatable": upd,
        }

    @Property("QVariantList", notify=modsChanged)
    def categoryCounts(self) -> list:
        """侧边栏「分类」：返回 [{key,label,count}]，只保留有内容的分类。"""
        items = self._all_local + self._all_workshop
        tally: dict[str, int] = {}
        for m in items:
            key = m.get("category") or "other"
            tally[key] = tally.get(key, 0) + 1
        out = []
        for key, label in M.CATEGORY_DEFS:
            n = tally.get(key, 0)
            if n:
                out.append({"key": key, "label": label, "count": n})
        return out

    @Property(int, notify=modsChanged)
    def favoriteCount(self) -> int:
        return sum(1 for m in self._all_local + self._all_workshop if m.get("favorited"))

    # ================================================================ 删除方式
    @Property(bool, notify=statusChanged)
    def deleteToRecycle(self) -> bool:
        """True=删 MOD 时放进回收站（默认），False=直接删掉。"""
        return self._delete_to_recycle

    @Slot(bool)
    def setDeleteToRecycle(self, value: bool) -> None:
        self._delete_to_recycle = bool(value)
        self._cfg["delete_to_recycle"] = self._delete_to_recycle
        self._cfg.save()
        self._set_status("删除方式：放进回收站" if self._delete_to_recycle else "删除方式：直接删除")

    # ================================================================ 目录
    @Slot(result="QVariantList")
    def detectDirs(self) -> list:
        return M.find_l4d2_dirs()

    @Slot()
    def auto_detect(self, quiet: bool = False) -> None:
        found = M.find_l4d2_dirs()
        if found:
            self.setAddonsDir(found[0], quiet=True)
            if not quiet:
                self._set_status(f"已自动找到 L4D2：{found[0]}")
            self.scan()
        else:
            if not quiet:
                self.detectFailed.emit("没有检测到 L4D2，请手动选择 addons 目录")
            self._set_status("没找到 L4D2，请手动选择目录")

    @Slot(str)
    def setAddonsDir(self, path: str, quiet: bool = False) -> None:
        fixed = M.normalize_addons_dir(path)
        if not fixed:
            if not quiet:
                self._set_status("这个目录不对，应该选到 left4dead2\\addons")
            return
        if fixed == self._addons_dir:
            return
        self._addons_dir = fixed
        self.addonsDirChanged.emit()
        if not quiet:
            self._set_status(f"MOD 目录：{fixed}")
        self.scan()

    @Slot(str, result="bool")
    def trySetAddonsDir(self, path: str) -> bool:
        fixed = M.normalize_addons_dir(path)
        if not fixed:
            return False
        self.setAddonsDir(fixed)
        return True

    @Slot()
    def openAddonsFolder(self) -> None:
        if self._addons_dir:
            M.open_in_explorer(self._addons_dir)

    @Slot()
    def openWorkshopFolder(self) -> None:
        ws = self.workshopDir
        if ws and os.path.isdir(ws):
            M.open_in_explorer(ws)

    # ================================================================ 扫描
    @Slot()
    def scan(self) -> None:
        if not self._addons_dir:
            return
        if self._busy:
            return
        self._set_busy(True)
        self._set_status("正在扫描 MOD…")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self) -> None:
        try:
            res = M.scan_mods(self._addons_dir)
        except Exception as e:  # noqa: BLE001
            log(f"scan failed: {e!r}")
            self._set_busy(False)
            self._set_status(f"扫描失败：{e}")
            return

        if self._closing:      # 扫盘期间用户退出了，别再碰模型
            return

        meta = self._wsc._meta  # 直接用缓存里的工坊信息
        # 先补一遍 VPK 内部信息（addoninfo / 预览图），这样 _decorate 拿到的
        # 就是真实标题和封面，不用等第二轮刷新。
        for m in res["local"] + res["workshop"]:
            try:
                self._vpk_meta_cached(m.get("path") or "")
            except Exception as e:  # noqa: BLE001
                log(f"prescan vpk meta failed: {e!r}")
        local = [self._decorate(m, meta, is_local=True) for m in res["local"]]
        workshop = [self._decorate(m, meta, is_local=False) for m in res["workshop"]]

        local.sort(key=self._sort_key)
        workshop.sort(key=self._sort_key)

        self._all_local = local
        self._all_workshop = workshop
        self._apply_filter()

        self._last_scan_ts = int(time.time())
        self._scanned = True
        self._set_busy(False)
        known = sum(1 for m in local + workshop if m["isKnown"])
        self._set_status(
            f"本地 {len(local)} 个，云 {len(workshop)} 个"
            + (f"，已识别 {known} 个工坊 mod" if known else "")
        )
        self.scannedChanged.emit()
        self.modsChanged.emit()
        self.detailChanged.emit()
        # 顺手在后台补作者的 Steam 昵称（拿不到就继续显示 SteamID，不影响界面）
        self.refreshAuthorNames()

    def _decorate(self, m: dict, meta: dict, is_local: bool) -> dict:
        wid = m.get("workshopId") or ""
        info = meta.get(wid) if wid else None
        known = bool(info and info.get("ok"))
        # VPK 内部信息（addoninfo.txt / addonimage.jpg）：
        # 工坊没识别出来的本地 MOD 靠它拿真实标题和封面。
        vpk = self._vpk_meta_cached(m.get("path") or "")
        vinfo = (vpk or {}).get("info") or {}

        title = m["stem"]
        desc = ""
        page = ""
        tags: list = []
        views = 0
        subs = 0
        created = 0
        updated = 0
        if known:
            title = info.get("title") or title
            desc = M.clean_desc(info.get("desc") or "")
            page = M.WORKSHOP_PAGE.format(wid)
            tags = info.get("tags") or []
            views = int(info.get("views") or 0)
            subs = int(info.get("subs") or 0)
            created = int(info.get("created") or 0)
            updated = int(info.get("updated") or 0)
        elif vinfo.get("title"):
            # 不是工坊 MOD（或工坊没查到），但 VPK 内部带了 addoninfo.txt：
            # 用作者自己写的标题/简介，比文件名有意义得多。
            title = vinfo["title"]
            desc = M.clean_desc(vinfo.get("desc") or "")
            page = vinfo.get("url") or ""

        # 分类：名字里点名了 L4N 平台的最优先，其次看工坊 tag
        # （用户可以在创意工坊页面看到同样的分类），
        # 都没有的本地 mod 就按标题关键词猜。
        category = M.platform_category(title, m.get("name") or "")
        if not category:
            category = M.category_from_tags(tags) if tags else ""
        if not category:
            category = M.guess_category(title, m.get("name") or "")
        # VPK 内部路径能给出更硬的证据：真有 .bsp 就是地图，
        # 真有 models/weapons/ 就是武器。比猜关键词准。
        vpk_chars = list((vpk or {}).get("characters") or [])
        vpk_weapons = list((vpk or {}).get("weapons") or [])
        if (vpk or {}).get("hasBsp"):
            category = "map"
        elif not category or category == "other":
            if (vpk or {}).get("hasCharacter"):
                category = "survivor"
            elif (vpk or {}).get("hasWeapon"):
                category = "weapon"

        # 更新检查：工坊最后更新 > 本地文件修改时间 → 作者改过，本地这份可能是旧的。
        # 留 60 秒余量，避免「刚下完就提示要更新」。
        mtime = int(m.get("mtime") or 0)
        has_update = bool(updated and mtime and updated > mtime + 60)
        # 详情面板显示「导入日期」而不是「修改日期」：用户关心的是"这东西啥时候
        # 进到我库里的"，文件 mtime 只反映拷进来的时间，容易被 Steam 重下刷掉。
        # 但上面 has_update 的判断仍然用 mtime，不受影响。
        import_ts = int(m.get("importTs") or mtime)

        img = m.get("image") or ""
        # 本地没有图，就用工坊封面缓存
        if (not img or not os.path.exists(img)) and wid:
            for ext in M.IMAGE_EXTS:
                cand = os.path.join(M.CACHE_DIR, f"{wid}{ext}")
                if os.path.isfile(cand):
                    img = cand
                    break
        # 工坊也没有 → 用从 VPK 内部抽出来的 addonimage.jpg（已经落盘到缓存目录）
        if not img or not os.path.exists(img):
            img = (vpk or {}).get("imagePath") or ""
        # ★ 最后再验一次「这张图真的能用」：0 字节 / 极小的坏图要当成没有，
        #   否则列表会一直显示灰块，而「检查 MOD 文件」也认为已有封面不去补。
        if img:
            try:
                if not os.path.isfile(img) or os.path.getsize(img) <= 1024:
                    img = ""
            except OSError:
                img = ""

        fav_key = self._fav_key({"workshopId": wid, "stem": m.get("stem"),
                                 "name": m.get("name")})

        author_id = str((info or {}).get("author") or "") if known else ""
        # Steam 昵称：先在本地缓存里找，找不到就显示 SteamID（点 authorUrl 能进主页）。
        # 真正的联网补昵称在后台线程做（refreshAuthorNames），不阻塞扫描。
        author_name = self._wsc.cached_author_name(author_id) if author_id else ""
        if author_name:
            author_label = author_name
        elif author_id:
            author_label = f"SteamID {author_id}"
        elif (vinfo.get("author") or "").strip():
            # 本地 MOD：用 addoninfo.txt 里作者自己写的名字
            author_label = vinfo["author"].strip()
        else:
            author_label = "-"

        return {
            "path": m["path"],
            "name": m["name"],
            "stem": m["stem"],
            "title": title,
            "desc": desc,
            "pageUrl": page,
            "size": m["size"],
            "sizeText": m["sizeText"],
            "mtimeText": fmt_ts(import_ts, "%Y-%m-%d"),
            "mtimeTs": int(m.get("mtime") or 0),
            "importTs": import_ts,
            "importText": fmt_ts(import_ts, "%Y-%m-%d"),
            "imageUrl": _file_url(img),
            "hasImage": bool(img and os.path.exists(img)),
            "workshopId": wid,
            "isWorkshop": bool(wid),
            "isKnown": known,
            "inWorkshopDir": not is_local,
            "isLocal": is_local,
            "enabled": not m["name"].lower().endswith(".disabled"),
            "checked": os.path.normcase(m["path"]) in self._checked_paths,
            "selectable": True,
            "disabledName": "",
            # ---- 扩展 ----
            "category": category,
            "categoryLabel": M.CATEGORY_LABELS.get(category, "其他"),
            "content": M.describe_content(title, desc),
            "favorited": fav_key in self._favorites,
            "favKey": fav_key,
            "tags": tags,
            # VPK 内部推断出来的角色/武器（本地 MOD 没有工坊 tag，靠这个补）
            "vpkCharacters": vpk_chars,
            "vpkWeapons": vpk_weapons,
            "vpkFileCount": int((vpk or {}).get("fileCount") or 0),
            "vpkAuthor": (vinfo.get("author") or "").strip(),
            "vpkVersion": (vinfo.get("version") or "").strip(),
            "viewsText": f"{views:,}" if views else "",
            "subsText": f"{subs:,}" if subs else "",
            "createdText": fmt_ts(created, "%Y-%m-%d") if created else "",
            "updatedText": fmt_ts(updated, "%Y-%m-%d") if updated else "",
            "updatedTs": updated,
            "hasUpdate": has_update,
            "updateText": (
                f"工坊 {fmt_ts(updated, '%Y-%m-%d')} 更新过"
                if has_update else ""
            ),
            "author": author_label if author_id else "",
            "authorId": author_id,
            "authorName": author_name,
            "authorLabel": author_label,
            "authorUrl": (
                f"https://steamcommunity.com/profiles/{author_id}"
                if author_id else ""
            ),
            "dirText": os.path.dirname(m["path"]),
            "selected": os.path.normcase(m["path"]) == os.path.normcase(self._selected_path),
        }

    def _apply_meta_to_items(self) -> None:
        """把工坊元数据刷到已扫描的列表上（不重扫盘，也不重置模型）。

        这里刻意**不**走 `_apply_filter()`：那会 `beginResetModel`，列表瞬间弹回
        顶部。用户点「检查这个 MOD」时正看着某一行，弹回顶部非常难受。
        代价是**不会按新标题重新排序**——想重排就点一次「刷新」。
        """
        meta = self._wsc._meta
        fresh: dict[str, dict] = {}
        for attr in ("_all_local", "_all_workshop"):
            items = getattr(self, attr, [])
            if not items:
                continue
            is_local = attr == "_all_local"
            for i, m in enumerate(items):
                wid = m.get("workshopId") or ""
                if not wid:
                    continue
                decorated = self._decorate(
                    {
                        "path": m["path"],
                        "name": m["name"],
                        "stem": m["stem"],
                        "dir": os.path.dirname(m["path"]),
                        "size": m["size"],
                        "sizeText": m["sizeText"],
                        "mtime": int(m.get("mtimeTs") or 0),
                        "importTs": int(m.get("importTs") or 0),
                        "image": self._local_image_of(m["path"]),
                        "workshopId": wid,
                        "isWorkshop": True,
                        "inWorkshopDir": not is_local,
                        "enabled": m.get("enabled", True),
                    },
                    meta,
                    is_local=is_local,
                )
                decorated["checked"] = os.path.normcase(decorated["path"]) in self._checked_paths
                items[i] = decorated
                fresh[os.path.normcase(decorated["path"])] = decorated

        for model in (self._all, self._local, self._workshop):
            for row in range(model.rowCount()):
                key = os.path.normcase(model.items()[row].get("path") or "")
                new = fresh.get(key)
                if new is not None:
                    model.update_item(row, dict(new))

        self.modsChanged.emit()
        self.detailChanged.emit()

    @staticmethod
    def _local_image_of(path: str) -> str:
        import os as _os

        folder = _os.path.dirname(path)
        name = _os.path.basename(path)
        # 禁用态的 MOD 文件名是 xxx.vpk.disabled，splitext 只去掉 .disabled、
        # stem 会变成 "xxx.vpk"，再拼 ".jpg" 就变成 "xxx.vpk.jpg" 找不到封面。
        # 所以先剥掉 .disabled 再取 stem。
        if name.lower().endswith(M.DISABLED_SUFFIX):
            name = name[: -len(M.DISABLED_SUFFIX)]
        stem = _os.path.splitext(name)[0]
        for ext in M.IMAGE_EXTS:
            p = _os.path.join(folder, stem + ext)
            if _os.path.isfile(p):
                return p
        return ""

    def _place_cover_beside(self, vpk_path: str, wid: str,
                            preview_url: str) -> str:
        """把工坊封面真正放到 vpk 旁边（`<ID>.jpg`），返回落地的图片路径。

        为什么必须有这一步：`WorkshopClient.download_cover()` 只把图存进
        `data/modcache/<ID>.jpg`，那是个**内部缓存**；而 MOD 列表判断「有没有封面」
        只看 `addons/` 里有没有和 vpk 同名的图片（`_local_image_of`）。
        两条路各走各的，于是「下载完的工坊 MOD 永远没有封面」——缓存里有图，
        列表里却看不到（用户报的就是这个）。

        这里把缓存里的图复制一份到 vpk 旁边。已经存在同名图就不动，
        绝不覆盖用户自己放的封面。
        """
        if not vpk_path or not wid:
            return ""
        folder = os.path.dirname(vpk_path)
        stem = os.path.splitext(os.path.basename(vpk_path))[0]
        # 已经有封面（不管是谁放的）就别碰
        existing = self._local_image_of(vpk_path)
        if existing:
            return existing

        # 优先用已经下过的缓存（`download_cover` 里也会先查缓存，但这里先自己找一遍，
        # 这样即便 preview_url 为空、只要缓存里有图也能落到位）
        cached = ""
        for ext in M.IMAGE_EXTS:
            cand = os.path.join(M.CACHE_DIR, wid + ext)
            try:
                if os.path.isfile(cand) and os.path.getsize(cand) > 1024:
                    cached = cand
                    break
            except OSError:
                continue
        if not cached and preview_url:
            cached = self._wsc.download_cover(wid, preview_url) or ""
        if not cached or not os.path.isfile(cached):
            return ""
        ext = os.path.splitext(cached)[1] or ".jpg"
        target = os.path.join(folder, stem + ext)
        try:
            if not os.path.exists(target):
                shutil.copy2(cached, target)
            return target if os.path.isfile(target) else ""
        except OSError as e:                  # noqa: BLE001
            log(f"place cover failed {wid}: {e!r}")
            return ""

    # ============================================================ VPK 内部解析
    def _vpk_meta_cached(self, path: str) -> dict:
        """读 VPK 内部信息（带内存 + 磁盘缓存）。

        为什么要有磁盘缓存：扫一遍 addons 有近百个 vpk，其中还有 800MB 的大文件。
        每次都重新解析目录树虽然只要几十毫秒，但加起来也要好几秒。
        这里用「文件路径 + 大小 + mtime」当缓存键，文件没变就直接用上次的结果。

        覆盖图会顺手写到 `data/modcache/vpkcover/` 下，给 QML 当 file:// 用。
        """
        p = str(path or "")
        if not p or not os.path.isfile(p):
            return {}
        key = os.path.normcase(p)
        try:
            st = os.stat(p)
            stamp = f"{int(st.st_size)}:{int(st.st_mtime)}"
        except OSError:
            return {}

        cache = self._vpk_cache
        hit = cache.get(key)
        if hit and hit.get("stamp") == stamp:
            return hit

        res = VD.read_vpk_meta(p)
        entry = {
            "stamp": stamp,
            "info": res.get("info") or {},
            "fileCount": int(res.get("fileCount") or 0),
            "hasBsp": bool(res.get("hasBsp")),
            "hasWeapon": bool(res.get("hasWeapon")),
            "hasCharacter": bool(res.get("hasCharacter")),
            "imagePath": "",
            "characters": [],
            "weapons": [],
            "error": res.get("error") or "",
        }

        img = res.get("image")
        if img and img.get("data"):
            entry["imagePath"] = self._save_vpk_cover(p, img["data"], img["ext"])
            entry["hasImage"] = bool(entry["imagePath"])

        # 内容识别：标题 + 内部路径 → 角色 / 武器标签
        info = entry["info"]
        flist = res.get("fileList") or []
        entry["characters"] = VD.detect_character(info.get("title") or "", flist)
        entry["weapons"] = VD.detect_weapon(info.get("title") or "", flist)

        cache[key] = entry
        return entry

    @staticmethod
    def _save_vpk_cover(vpk_path: str, data: bytes, ext: str) -> str:
        """把从 VPK 里抽出来的封面写成缓存文件，返回本地路径。

        ★ 文件名不能只用 stem。曾经踩过两个坑：
          1. **同名覆盖**：addons/ 和 addons/workshop/ 里可能有同名 vpk
             （Steam 重下、用户手动复制都会造成），只按 stem 命名时，
             后写的会把先写的封面顶掉，于是「A 的封面出现在 B 上」。
          2. **禁用态**：`xxx.vpk.disabled` 的 stem 是 `xxx.vpk`，
             拼出来是 `xxx.vpk.jpg`，而正常态写的是 `xxx.jpg`——
             同一个 MOD 启用/禁用各有一张图，白占空间还容易读错。
          现在改成：stem 里剥掉 .vpk/.disabled 后缀，再拼一个**路径短哈希**，
          保证「同一个文件永远同一个名字、不同文件不会撞车」。
        """
        try:
            d = os.path.join(M.CACHE_DIR, "vpkcover")
            os.makedirs(d, exist_ok=True)
            name = os.path.basename(vpk_path)
            low = name.lower()
            if low.endswith(M.DISABLED_SUFFIX):
                name = name[: -len(M.DISABLED_SUFFIX)]
                low = name.lower()
            if low.endswith(".vpk"):
                name = name[:-4]
            # 文件名里可能有中文/特殊字符，清一下（中文留着，好看）
            safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:60] or "cover"
            # 路径短哈希：区分「同名但不同目录」的 vpk。
            # ★ 算哈希前必须先把 .disabled 剥掉，否则同一个 MOD 启用态一个名、
            #   禁用态另一个名（刚才就是这么错的），白占空间还会读错。
            #   注意顺序：先 abspath（可能补全成绝对路径）再剥后缀，
            #   反过来剥的话 abspath 又把后缀带回来了。
            key_path = os.path.abspath(vpk_path)
            if key_path.lower().endswith(M.DISABLED_SUFFIX):
                key_path = key_path[: -len(M.DISABLED_SUFFIX)]
            # ★ 还要再剥一层 .vpk：目标是让「启用态 xxx.vpk」和
            #   「禁用态 xxx.vpk.disabled」算出**同一个**哈希，
            #   这样同一个 MOD 换状态不会多出一张封面（只有 .disabled
            #   那一层剥掉是不够的，xxx.vpk 还没归一）。
            if key_path.lower().endswith(".vpk"):
                key_path = key_path[:-4]
            tag = hashlib.md5(
                os.path.normcase(key_path).encode("utf-8", "ignore")
            ).hexdigest()[:8]
            dst = os.path.join(d, f"{safe}.{tag}{ext or '.jpg'}")
            # 已经存在且内容大小一致就不用重写
            if os.path.isfile(dst) and os.path.getsize(dst) == len(data):
                return dst
            with open(dst, "wb") as f:
                f.write(data)
            return dst
        except OSError as e:
            log(f"save vpk cover failed: {e!r}")
            return ""

    def _apply_vpk_meta_to_items(self) -> None:
        """把 VPK 内部信息补到已扫描的条目上（详情面板的分类/内容描述也用得上）。"""
        for m in (getattr(self, "_all_local", []) or []) + \
                 (getattr(self, "_all_workshop", []) or []):
            vk = self._vpk_meta_cached(m.get("path") or "")
            if not vk:
                continue
            m["vpkInfo"] = vk

    @Slot(result="QVariantMap")
    def scanVpkMeta(self) -> dict:
        """手动触发一次「读 VPK 内部信息」（扫描后自动也会做一次）。"""
        return self._scan_vpk_meta_impl()

    def _scan_vpk_meta_impl(self) -> dict:
        paths: list[str] = []
        for m in (getattr(self, "_all_local", []) or []) + \
                 (getattr(self, "_all_workshop", []) or []):
            p = m.get("path") or ""
            if p:
                paths.append(p)
        if not paths:
            return {"ok": False, "count": 0, "error": "还没扫描到 MOD"}
        done = 0
        for p in paths:
            try:
                self._vpk_meta_cached(p)
                done += 1
            except Exception as e:  # noqa: BLE001
                log(f"vpk meta failed {p}: {e!r}")
        self._apply_filter()
        return {"ok": True, "count": done, "error": ""}

    # ================================================================ 过滤
    @Slot(str)
    def setFilter(self, text: str) -> None:
        value = (text or "").strip().lower()
        if value == self._filter:
            return
        self._filter = value
        self._remember_filters()
        self._apply_filter()

    @Slot(float, float)
    def setSizeRange(self, min_mb: float, max_mb: float) -> None:
        """按体积筛 mod，0 表示不限。"""
        lo = max(0.0, float(min_mb or 0))
        hi = max(0.0, float(max_mb or 0))
        if lo and hi and lo > hi:      # 用户把大小写反了，自动换过来
            lo, hi = hi, lo
        if (lo, hi) == (self._min_mb, self._max_mb):
            return
        self._min_mb, self._max_mb = lo, hi
        self._remember_filters()
        self._apply_filter()

    @Slot(int)
    def setStatusFilter(self, mode: int) -> None:
        """侧边栏「状态」：0=全部 1=已启用 2=未启用 3=创意工坊 4=我的收藏 5=可更新 6=本地"""
        mode = mode if mode in (0, 1, 2, 3, 4, 5, 6) else 0
        if mode == self._status_filter:
            return
        self._status_filter = mode
        self._apply_filter()
        self._remember_filters()
        self.statusChanged.emit()

    @Slot()
    def resetSessionFilters(self) -> None:
        """进入 MOD 页时把「只在一定条件下才看得见东西」的筛选项复位。

        ★ 用户报的「每次点 MOD 管理自动跳到我的收藏」：
          `_status_filter` 是**跨会话记住**的（`mod_status_filter` 存在 config 里），
          上次看到「我的收藏」关掉软件，下次点进来还停在「我的收藏」——
          看上去就是「自己跳过去了」，而且那时列表里常常只有几条甚至空的。

        复位的只有**会导致空列表**的临时筛选项；关键词、类型、体积这些
        用户手填的条件也一起清掉，等于「点进 MOD 页先看全部」。
        """
        # 只复位置空率高、且用户不会「特意想长久保留」的那几个
        changed = False
        if self._status_filter != 0:
            self._status_filter = 0
            changed = True
        if self._filter:
            self._filter = ""
            changed = True
        if self._category:
            self._category = ""
            changed = True
        if self._min_mb or self._max_mb:
            self._min_mb = 0.0
            self._max_mb = 0.0
            changed = True
        if not changed:
            return
        self._apply_filter()
        self._remember_filters()
        self.statusChanged.emit()

    @Slot(int)
    def setSortMode(self, mode: int) -> None:
        """0=默认 1=优先看启用 2=优先看禁用 3=优先看收藏 4=字母排序 5=最近导入"""
        mode = mode if mode in (0, 1, 2, 3, 4, 5) else 0
        if mode == self._sort_mode:
            return
        self._sort_mode = mode
        self._remember_filters()
        self._apply_filter()
        self.statusChanged.emit()

    # ============================================================ 筛选/排序的持久化
    def _remember_filters(self) -> None:
        """把当前筛选 + 排序状态写进 config.json（跨重启记住）。

        只在真正改动时调（各 setter 末尾），不在 `_apply_filter()` 里调 ——
        那个函数每次重扫盘都会跑，写盘太频繁。

        写失败（磁盘满 / 只读）不抛：记住偏好是锦上添花，不该让筛选点不动。
        """
        cfg = getattr(self, "_cfg", None)
        if cfg is None:
            return
        try:
            cfg["mod_filter"] = self._filter
            cfg["mod_min_mb"] = float(self._min_mb)
            cfg["mod_max_mb"] = float(self._max_mb)
            cfg["mod_status_filter"] = int(self._status_filter)
            cfg["mod_category"] = self._category
            cfg["mod_sort_mode"] = int(self._sort_mode)
            cfg["mod_import_days"] = int(self._import_days)
            cfg["mod_import_from"] = self._import_from
            cfg["mod_import_to"] = self._import_to
            cfg["mod_tab"] = int(getattr(self, "_tab", 0))
            cfg.save()
        except (OSError, TypeError, ValueError) as e:     # noqa: BLE001
            log(f"remember filters failed: {e!r}")

    # ================================================================ 导入日期筛选
    @Property(int, notify=importFilterChanged)
    def importDays(self) -> int:
        """快捷档：最近 N 天（0 = 不限）。"""
        return self._import_days

    @Property(str, notify=importFilterChanged)
    def importFrom(self) -> str:
        return self._import_from

    @Property(str, notify=importFilterChanged)
    def importTo(self) -> str:
        return self._import_to

    @Property(bool, notify=importFilterChanged)
    def hasImportFilter(self) -> bool:
        """当前有没有在用导入日期筛选（界面上给个「已筛选」提示）。"""
        return bool(self._import_days or self._import_from or self._import_to)

    @Property(str, notify=importFilterChanged)
    def importFilterLabel(self) -> str:
        """一行文字概括当前筛选，比如「近 7 天」「2026-01-01 ～ 2026-06-01」。"""
        if self._import_days:
            return f"近 {self._import_days} 天"
        if self._import_from and self._import_to:
            return f"{self._import_from} ～ {self._import_to}"
        if self._import_from:
            return f"{self._import_from} 起"
        if self._import_to:
            return f"截至 {self._import_to}"
        return ""

    @staticmethod
    def _parse_day(value: str) -> int:
        """'YYYY-MM-DD' → 当天 00:00 的时间戳；'YYYY-MM-DD' 作终点时取当天 23:59:59。

        解析不出来返回 -1（表示「不限」）。
        """
        raw = str(value or "").strip()
        if not raw:
            return -1
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                dt = _dt.datetime.strptime(raw, fmt)
                return int(dt.timestamp())
            except ValueError:
                continue
        return -1

    @Slot(int)
    def setImportDays(self, days: int) -> None:
        """快捷档：最近 0（不限）/1/7/30/180 天。"""
        value = int(days or 0)
        if value not in (0, 1, 7, 30, 180):
            value = 0
        # 选快捷档就清掉自定义区间（两者互斥，不然用户会以为两个都生效）
        if (value == self._import_days and not self._import_from
                and not self._import_to):
            return
        self._import_days = value
        if value:
            self._import_from = ""
            self._import_to = ""
        self._apply_filter()
        self._remember_filters()
        self.statusChanged.emit()
        self.importFilterChanged.emit()

    @Slot(str, str)
    def setImportRange(self, start: str, end: str) -> None:
        """自定义区间：'YYYY-MM-DD'，空串表示这一端不限。"""
        lo = str(start or "").strip()
        hi = str(end or "").strip()
        # 用户把两头选反了就自动换过来
        t_lo, t_hi = self._parse_day(lo), self._parse_day(hi)
        if t_lo >= 0 and t_hi >= 0 and t_lo > t_hi:
            lo, hi = hi, lo
        if (lo, hi) == (self._import_from, self._import_to):
            return
        self._import_from, self._import_to = lo, hi
        if lo or hi:
            self._import_days = 0
        self._apply_filter()
        self._remember_filters()
        self.statusChanged.emit()
        self.importFilterChanged.emit()

    @Slot()
    def clearImportFilter(self) -> None:
        """只清导入日期筛选（别的筛选不动）。"""
        if not (self._import_days or self._import_from or self._import_to):
            return
        self._import_days = 0
        self._import_from = ""
        self._import_to = ""
        self._apply_filter()
        self.statusChanged.emit()
        self.importFilterChanged.emit()

    def _match_import_date(self, m: dict) -> bool:
        """这条 MOD 的导入时间落不落在筛选区间里。"""
        if not self.hasImportFilter:
            return True
        ts = int(m.get("importTs") or 0)
        if ts <= 0:
            return False
        if self._import_days:
            cutoff = _time.time() - self._import_days * 86400
            return ts >= cutoff
        lo = self._parse_day(self._import_from)
        if lo >= 0 and ts < lo:
            return False
        hi = self._parse_day(self._import_to)
        if hi >= 0:
            # 终点取当天最后一秒，不然选「到今天」会把今天导入的全挡掉
            if ts > hi + 86399:
                return False
        return True

    def _sort_key(self, m: dict) -> tuple:
        """列表排序。

        基本规则是「未启用沉底」——禁用的 MOD 用户暂时不关心，不该占着前排。
        只有「优先看禁用」这一档是例外（那种时候用户就是来找禁用项的）。
        """
        en = bool(m.get("enabled", True))
        fav = bool(m.get("favorited"))
        title = (m.get("title") or "").lower()
        img = 0 if m.get("hasImage") else 1
        mode = self._sort_mode
        if mode == 5:
            # 最近导入：导入时间新的在前（禁用的仍然沉底，保持一致的规则）
            return (0 if en else 1, -int(m.get("importTs") or 0), img, title)
        if mode == 2:                       # 优先看禁用
            return (0 if not en else 1, 0 if fav else 1, img, title)
        if mode == 3:                       # 优先看收藏
            return (0 if en else 1, 0 if fav else 1, img, title)
        if mode == 4:                       # 字母排序（禁用仍然沉底）
            return (0 if en else 1, 0, 0, title)
        if mode == 1:                       # 优先看启用
            return (0 if en else 1, 0, img, title)
        # 0 = 默认：有封面的先（没封面的卡片是灰块，放前面很难看）
        return (0 if en else 1, 0, img, title)

    @Slot(str)
    def setCategory(self, key: str) -> None:
        """侧边栏「分类」：空串=全部。"""
        value = (key or "").strip()
        if value == self._category:
            return
        self._category = value
        self._apply_filter()
        self._remember_filters()
        self.statusChanged.emit()

    @Slot()
    def resetFilters(self) -> None:
        """一键清空搜索词 + 体积区间 + 导入日期 + 侧边栏状态/分类，**并把排序也退回默认**。

        用户报的：「筛选重置后排序没恢复默认」。上一版这里刻意不动排序
        （docstring 还写着「排序不动」），但「重置」在用户心里就是「一切都回原样」——
        排序胶囊还亮着「最近导入」而筛选按钮已经不亮了，看着就是没重置干净。
        """
        # ★ 判断条件不能带 hasImportFilter 就算完 —— 以前清完之后
        #   只发了 statusChanged，没发 importFilterChanged，
        #   于是「重置」把日期清掉了但界面还显示着旧日期。
        had_import = self.hasImportFilter
        # 排序也要算进「有没有东西可重置」，否则「只改了排序」时点重置会直接 return
        if not (self._filter or self._min_mb or self._max_mb
                or self._status_filter or self._category or had_import
                or self._sort_mode):
            return
        self._filter = ""
        self._min_mb = 0.0
        self._max_mb = 0.0
        self._status_filter = 0
        self._category = ""
        self._import_days = 0
        self._import_from = ""
        self._import_to = ""
        self._sort_mode = 0                 # 0 = 默认排序
        self._apply_filter()
        self.statusChanged.emit()
        if had_import:
            # 日期相关的属性（importDays / importFrom / importTo /
            # hasImportFilter / importFilterLabel）都挂在这个信号上
            self.importFilterChanged.emit()

    def _match(self, m: dict) -> bool:
        f = self._filter
        if f:
            if not (
                f in (m.get("title") or "").lower()
                or f in (m.get("name") or "").lower()
                or f in (m.get("workshopId") or "")
                or f in (m.get("categoryLabel") or "").lower()
                or f in (m.get("content") or "").lower()
            ):
                return False
        # 体积区间（MB，字节转过去比）
        size_mb = int(m.get("size") or 0) / (1024.0 * 1024.0)
        if self._min_mb and size_mb < self._min_mb:
            return False
        if self._max_mb and size_mb > self._max_mb:
            return False
        # 侧边栏「状态」
        sf = self._status_filter
        if sf == 1 and not m.get("enabled", True):
            return False
        if sf == 2 and m.get("enabled", True):
            return False
        if sf == 3 and not m.get("inWorkshopDir"):
            return False
        if sf == 4 and not m.get("favorited"):
            return False
        if sf == 5 and not m.get("hasUpdate"):
            return False
        if sf == 6 and m.get("inWorkshopDir"):
            return False
        # 侧边栏「分类」
        if self._category and (m.get("category") or "other") != self._category:
            return False
        # 按导入日期
        if not self._match_import_date(m):
            return False
        return True

    def _apply_filter(self) -> None:
        if self._closing:
            return
        any_filter = bool(self._filter or self._min_mb or self._max_mb
                          or self._status_filter or self._category
                          or self.hasImportFilter)
        merged: list[dict] = []
        for attr, model in (("_all_local", self._local), ("_all_workshop", self._workshop)):
            items = getattr(self, attr, [])
            shown = items if not any_filter else [m for m in items if self._match(m)]
            model.set_items([dict(m) for m in shown])
            merged.extend(shown)
        # 合并列表：本地 + 云端一起排
        merged.sort(key=self._sort_key)
        self._all.set_items([dict(m) for m in merged])
        self.statusChanged.emit()

    # ================================================================ 选中 / 收藏 / 启动
    @Property(str, notify=detailChanged)
    def selectedPath(self) -> str:
        return self._selected_path

    @Property("QVariantMap", notify=detailChanged)
    def selectedItem(self) -> dict:
        """右侧详情面板要看的那一条（按 path 找，找不到给空字典）。"""
        if not self._selected_path:
            return {}
        key = os.path.normcase(self._selected_path)
        for m in self._all_local + self._all_workshop:
            if os.path.normcase(m.get("path") or "") == key:
                return dict(m)
        return {}

    @Slot(str, result=int)
    def rowOfPath(self, path: str) -> int:
        """按 path 找它当前在合并列表里的行号（QML 用来把卡片滚回视野）。

        为什么放在 ModManager 而不是 ModListModel：QAbstractListModel 子类上的
        @Slot 不会被 QML 的 model 代理暴露出来（实测 `mgr.allModel.rowOfPath` 在 QML 里
        是 undefined，调用直接 TypeError），所以查找必须挂在 manager 这个普通 QObject 上。
        """
        key = os.path.normcase(path or "")
        for i, it in enumerate(self._all.items()):
            if os.path.normcase(it.get("path") or "") == key:
                return i
        return -1

    @Slot(str, result=int)
    def row_of_path(self, path: str) -> int:
        """Python 侧用的（snake_case）别名。"""
        return self.rowOfPath(path)

    @Slot(str)
    def selectMod(self, path: str) -> None:
        """点卡片：选中并刷新详情内容。

        再点同一个 MOD 就取消选中（开关式）。详情面板常驻，选中只影响
        右侧详情显示的内容，不涉及任何滚动/跳行。
        """
        if not path:
            return
        same = os.path.normcase(path) == os.path.normcase(self._selected_path)
        if same and self._selected_path:
            self.clearSelected()
            return
        changed = not same
        self._selected_path = path
        if changed:
            for attr in ("_all_local", "_all_workshop"):
                for m in getattr(self, attr, []):
                    m["selected"] = os.path.normcase(m.get("path") or "") == os.path.normcase(path)
            self._refresh_selected_flags()
        self.detailChanged.emit()

    @Slot()
    def clearSelected(self) -> None:
        if not self._selected_path:
            return
        self._selected_path = ""
        for attr in ("_all_local", "_all_workshop"):
            for m in getattr(self, attr, []):
                m["selected"] = False
        self._refresh_selected_flags()
        self.detailChanged.emit()

    def _refresh_selected_flags(self) -> None:
        """把 selected / favorited 标记同步到当前显示的列表（原位刷新，别 reset）。

        排序必须和 `_apply_filter` 完全一致（同一个 `_sort_key`），否则
        `update_item(row, ...)` 会把 A 的数据写到 B 那一行上——卡片会莫名
        换位置、收藏星跑到别的 MOD 上。早期这里用的是另一套排序键，就是这么来的。
        """
        if self._closing:
            return
        shown = [m for m in (self._all_local + self._all_workshop) if self._match(m)]
        shown.sort(key=self._sort_key)
        for row, m in enumerate(shown):
            if row >= self._all.rowCount():
                break
            self._all.update_item(row, dict(m))
        self.statusChanged.emit()

    @Slot(str)
    def toggleFavorite(self, path: str) -> None:
        """收藏 / 取消收藏（按工坊 ID 或文件名记，改名不丢）。"""
        target = None
        for m in self._all_local + self._all_workshop:
            if os.path.normcase(m.get("path") or "") == os.path.normcase(path or ""):
                target = m
                break
        if target is None:
            return
        key = target.get("favKey") or self._fav_key(target)
        on = key not in self._favorites
        if on:
            self._favorites.add(key)
        else:
            self._favorites.discard(key)
        self._save_favorites()
        for m in self._all_local + self._all_workshop:
            if (m.get("favKey") or self._fav_key(m)) == key:
                m["favorited"] = on
        self._refresh_selected_flags()
        self.modsChanged.emit()
        self.detailChanged.emit()
        if self._status_filter == 4 and not on:
            self._apply_filter()      # 在「我的收藏」里取消收藏，得把它移出去
        title = target.get("title") or ""
        self._set_status(("已收藏 " if on else "已取消收藏 ") + title)
        self.toast(("已收藏 " if on else "已取消收藏 ") + title, "ok" if on else "info")

    @Slot(result="QVariantMap")
    def launchGame(self) -> dict:
        """启动 L4D2：优先直接跑 left4dead2.exe，找不到就交给 Steam。"""
        res = M.launch_game(self._addons_dir)
        if res.get("ok"):
            how = "游戏已启动（直接运行 exe）" if res.get("how") == "exe" else "已交给 Steam 启动游戏"
            self._set_status(how)
            self.toast(how, "ok")
        else:
            msg = f"启动失败：{res.get('error') or '没找到游戏'}（可在设置里检查 MOD 目录）"
            self._set_status(msg)
            self.toast(msg, "error")
        return res

    # ================================================================ 云识别
    @Slot()
    def identifyWorkshop(self) -> None:
        """查工坊 ID 的名称，并下载缺封面的图。

        排序有讲究（用户报的「检查太慢 / 检查完封面没了」）：

        * **先查「没封面」或「没工坊名字」的**。这批是真正需要修的 ——
          卡片上一片空白就是因为它们；先把它们修好，用户马上能看到变化。
        * 已经有封面又有名字的放最后。它们的元数据基本不用更新，查它们纯属浪费
          （而且这边几百个 MOD，全查一遍要几十秒）。
        * 封面下载改成**每批查完就顺手补**，而不是等全部查完再统一下载。
          以前是「先把 N 批全查完（几十秒），再统一下封面」，中间用户一关窗口
          `_closing` 就为真，封面一张都下不到 —— 表现就是「检查完反而没封面了」。
        """
        if self._identify_running:
            return
        # 收集 (wid, 缺封面?, 缺名字?)
        pending: dict[str, tuple[bool, bool]] = {}
        for m in self._all_local + self._all_workshop:
            wid = str(m.get("workshopId") or "")
            if not wid:
                continue
            miss_cover = not bool(m.get("hasImage"))
            miss_name = not str(m.get("title") or "").strip()
            prev = pending.get(wid)
            if prev is None:
                pending[wid] = (miss_cover, miss_name)
            else:
                # 同一个工坊 ID 可能同时有本地副本和工坊副本：只要有一份不缺就算不缺
                pending[wid] = (prev[0] and miss_cover, prev[1] and miss_name)

        if not pending:
            self._set_status("没有发现工坊 ID（纯数字命名）的 mod")
            return

        # 优先级：缺封面或缺口名字的排前面，两个都缺的最优先
        def rank(wid: str) -> tuple[int, int]:
            miss_cover, miss_name = pending[wid]
            score = (2 if miss_cover else 0) + (1 if miss_name else 0)
            return (-score, wid)

        ordered = sorted(pending, key=rank)
        need_fix = sum(1 for w in ordered
                       if pending[w][0] or pending[w][1])

        self._identify_running = True
        self._set_busy(True)
        self._set_status(
            f"正在检查 {len(ordered)} 个工坊 MOD"
            + (f"（其中 {need_fix} 个缺封面或名字，先查这些）" if need_fix else "")
            + "…")
        threading.Thread(target=self._identify_worker, args=(ordered,), daemon=True).start()

    def _has_cover_locally(self, wid: str) -> bool:
        """这个 MOD 是不是已经有**能显示**的封面图了。

        ★ 以前只判断「文件存在」（`_local_image_of` 只 isfile，`hasImage` 只看
          路径非空），于是一张 0 字节、或者内容被截断的图也算「有封面」——
          列表里显示成灰块，用户点「检查 MOD 文件」也不再去补，永远修不好。
          别人电脑上这种情况更常见：工坊 MOD 拷来拷去、Steam 更新中断、
          U 盘复制不完整，都会留下坏图。

          现在要求「文件存在 **且** 大小超过 1KB」（一张能看的封面不会小于这个），
          否则视为没有，让上层去联网补。
        """
        if not wid:
            return False

        def good(p: str) -> bool:
            try:
                return bool(p) and os.path.isfile(p) and os.path.getsize(p) > 1024
            except OSError:
                return False

        for m in self._all_local + self._all_workshop:
            if m.get("workshopId") != wid:
                continue
            if m.get("hasImage"):
                # 有标记还不够，磁盘上那张图得真的像一张图
                img = m.get("image") or ""
                if img and good(img):
                    return True
                # 标记说「本地图在 vpk 旁边」，也验一下大小
                if m.get("path") and good(self._local_image_of(m["path"])):
                    return True
                # 退一步：vpk 旁边 / modcache 里有任何一张像样的同名图就算有
                if m.get("path"):
                    d = os.path.dirname(m["path"])
                    name = os.path.basename(m["path"])
                    if name.lower().endswith(M.DISABLED_SUFFIX):
                        name = name[: -len(M.DISABLED_SUFFIX)]
                    stem = os.path.splitext(name)[0]
                    for ext in M.IMAGE_EXTS:
                        if good(os.path.join(d, stem + ext)):
                            return True
                        if good(os.path.join(M.CACHE_DIR, f"{wid}{ext}")):
                            return True
            # 列表说没有，但盘上可能已经有了（刚放进去 / 用户自己放的）
            if m.get("path") and good(self._local_image_of(m["path"])):
                return True
        # 列表里可能还没扫进这个 id，直接查缓存目录
        for ext in M.IMAGE_EXTS:
            if good(os.path.join(M.CACHE_DIR, f"{wid}{ext}")):
                return True
        return False

    def _identify_worker(self, ids: list[str]) -> None:
        """按传进来的顺序分批查，**每批查完立刻补这一批缺的封面**。

        为什么不等全部查完再统一下封面：几百个 MOD 查一遍要几十秒，用户经常
        中途就把窗口关了。以前封面下载排在最后，`_closing` 一为真就整个跳过，
        于是「检查完反而一张封面也没有」（用户报的就是这个）。
        改成逐批补之后，关窗时至少已经落地了前面几批。
        """
        BATCH = 20
        info: dict[str, dict] = {}
        got = 0
        skipped = 0
        # wid → 磁盘上的 vpk 路径（封面要放到它旁边，列表才认）
        path_of: dict[str, str] = {}
        for m in self._all_local + self._all_workshop:
            wid = str(m.get("workshopId") or "")
            if wid and m.get("path"):
                path_of.setdefault(wid, str(m["path"]))
        try:
            for i in range(0, len(ids), BATCH):
                if self._closing:
                    break
                batch = ids[i: i + BATCH]
                try:
                    part = self._wsc.fetch(
                        batch,
                        progress=lambda d, t, _b=len(batch):
                            self.workshopProgress.emit(d, _b),
                    )
                except Exception as e:          # noqa: BLE001
                    log(f"identify batch failed: {e!r}")
                    continue
                info.update(part)

                # ★ 这一批查完就补封面，别攒到最后
                for wid, v in part.items():
                    if not (v.get("ok") and v.get("preview")):
                        continue
                    if self._has_cover_locally(wid):
                        skipped += 1
                        continue
                    if self._closing:
                        break
                    if self._place_cover_beside(path_of.get(wid, ""), wid,
                                                v["preview"]):
                        got += 1
                # 每批落地就刷一次列表，用户不用等全部跑完才看到名字/封面
                if not self._closing:
                    self._apply_meta_to_items()
        except Exception as e:                  # noqa: BLE001
            log(f"identify failed: {e!r}")

        ok = sum(1 for v in info.values() if v.get("ok"))
        log(
            f"identify: {ok}/{len(ids)} ok, covers {got}"
            f"（本地已有 {skipped} 张，跳过下载）"
        )

        if self._closing:
            return

        self._identify_running = False
        self._set_busy(False)
        parts = [f"检查完成：{ok}/{len(ids)} 个工坊 MOD"]
        if got:
            parts.append(f"补下封面 {got} 张")
        if skipped:
            parts.append(f"本地已有封面跳过 {skipped} 张")
        # 直接把已识别的信息刷到现有列表上（不重新扫描，避免和 UI 竞争）
        self._apply_meta_to_items()
        upd = sum(1 for m in self._all_local + self._all_workshop if m.get("hasUpdate"))
        if upd:
            parts.append(f"发现 {upd} 个可能有更新")
        self._set_status("，".join(parts))

    @Slot(str)
    def identifyOne(self, path: str) -> None:
        """识别单个 mod（重新查一次工坊信息）。

        ★ 工坊 ID 有**两个来源**，以前只用了第一个，于是「明明有工坊 ID 却检查不了」：
          1. 文件名是纯数字（工坊下载的 `<ID>.vpk`）—— `M.workshop_id_of()`
          2. 列表里这一条已经带 `workshopId`（从元数据/上次识别/工坊目录推断出来的）
             用户的 MOD 改名成中文、或者手动挪动过之后，文件名不再纯数字，
             但它其实是工坊来的、详情里也显示着工坊信息 —— 这种必须照样能检查。
        """
        wid = M.workshop_id_of(os.path.basename(path))
        if not wid:
            wid = self._workshop_id_of_path(path)
        if not wid:
            self._set_status("这个 mod 没有工坊 ID，没法识别")
            self.toast("这个 MOD 没有工坊 ID，没法识别", "warn")
            return
        self._set_status(f"正在查询工坊 {wid}…")
        threading.Thread(target=self._identify_one_worker, args=(wid,), daemon=True).start()

    def _workshop_id_of_path(self, path: str) -> str:
        """从已有列表数据里找这个 path 对应的工坊 ID（找不到返回空串）。

        按 id / path / stem 三种键都试一遍：详情面板传进来的 `path` 可能是
        绝对路径，也可能已经被规范化过，用 stem（不含扩展名的文件名）兜底最稳。
        """
        target = str(path or "")
        if not target:
            return ""
        base = os.path.basename(target)
        stem = os.path.splitext(base)[0]
        for item in list(self._all_local) + list(self._all_workshop):
            wid = str(item.get("workshopId") or "").strip()
            if not wid:
                continue
            if target in (str(item.get("path") or ""), str(item.get("id") or "")):
                return wid
            if stem and stem == str(item.get("stem") or ""):
                return wid
            if base and base == os.path.basename(str(item.get("path") or "")):
                return wid
        return ""

    def _identify_one_worker(self, wid: str) -> None:
        info = self._wsc.fetch([wid]).get(wid) or {}
        if self._closing:
            return
        if info.get("ok"):
            if info.get("preview") and not self._has_cover_locally(wid):
                self._wsc.download_cover(wid, info["preview"])
            # 顺手把这位作者的 Steam 昵称补上（没缓存才联网）
            author = str(info.get("author") or "")
            if author and not self._wsc.cached_author_name(author):
                self._wsc.author_name(author)
            if self._closing:
                return
            # 只把这一条的元数据刷回列表，不重扫整盘——
            # 重扫会 beginResetModel，用户刚点的那个 MOD 会被弹回列表顶部。
            self._apply_meta_to_items()
            self._set_status(f"检查完成：{info.get('title')}")
            self.toast(f"已更新信息：{info.get('title')}", "ok")
        else:
            self._set_status(f"工坊 {wid} 查询失败，检查网络后重试")
            self.toast("工坊查询失败，检查网络后重试", "error")

    # ------------------------------------------------------------ 作者昵称
    @Slot()
    def refreshAuthorNames(self) -> None:
        """后台补全所有工坊作者的 Steam 昵称（取不到就继续显示 SteamID）。"""
        if self._author_running:
            return
        ids = {
            str(m.get("workshopId") and (self._wsc._meta.get(m["workshopId"]) or {}).get("author") or "")
            for m in self._all_local + self._all_workshop
        }
        ids = {i for i in ids if i.isdigit()}
        ids = {i for i in ids if not self._wsc.cached_author_name(i)}
        if not ids:
            return
        self._author_running = True
        threading.Thread(target=self._author_worker, args=(sorted(ids),), daemon=True).start()

    def _author_worker(self, ids: list[str]) -> None:
        try:
            self._wsc.fetch_author_names(ids)
        except Exception as e:  # noqa: BLE001
            log(f"author names failed: {e!r}")
        self._author_running = False
        if self._closing:
            return
        # 后台线程不能直接碰模型 —— 排队回主线程再刷
        self._authorsReady.emit()

    @Slot()
    def _on_authors_ready(self) -> None:
        """昵称拉完了：只刷元数据，不重扫盘、不重置模型（滚动位置和选中项都保住）。"""
        if self._closing:
            return
        self._apply_meta_to_items()

    # ================================================================ 选择
    def _model_for_tab(self) -> ModListModel:
        """当前操作的模型。

        新版界面把「本地 / 云端」合成一个网格了，所以这里统一返回合并模型；
        保留这个名字是因为勾选/批量操作的老代码都在调它。
        """
        return self._all

    @Slot(int)
    def setTab(self, tab: int) -> None:
        """切换 本地/云端 时清掉另一个列表的勾选，避免误操作。"""
        tab = 0 if tab <= 0 else 1
        if tab == self._tab:
            return
        self._tab = tab
        self._remember_filters()
        other = self._workshop if tab == 0 else self._local
        for i in range(other.rowCount()):
            other.set_checked(i, False)
        self.selectionChanged.emit()
        self.modsChanged.emit()

    @Property(int, notify=modsChanged)
    def tab(self) -> int:
        return self._tab

    @Slot(int, bool)
    def toggleCheck(self, row: int, value: bool) -> None:
        """勾选/取消勾选某一行的 MOD。

        勾选状态存在 _checked_paths（按 path 的 normcase），而不是只改模型 ——
        因为 _all 模型每次重建都会从源列表重填 checked，只改模型会被冲掉
        （「选择 MOD 用不了」的根因）。这里改持久存储，再同步到所有模型。
        """
        model = self._model_for_tab()
        if not (0 <= row < model.rowCount()):
            return
        item = model._items[row]
        path = item.get("path") or ""
        if not path:
            return
        key = os.path.normcase(path)
        if value:
            self._checked_paths.add(key)
        else:
            self._checked_paths.discard(key)
        # 同步到所有模型（_all / _local / _workshop / 源列表）
        self._sync_checked(key, value)
        self.selectionChanged.emit()

    def _sync_checked(self, key: str, value: bool) -> None:
        """把某个 path 的勾选状态同步到源列表和所有模型。"""
        for attr in ("_all_local", "_all_workshop"):
            for m in getattr(self, attr, []):
                if os.path.normcase(m.get("path") or "") == key:
                    m["checked"] = value
        for model in (self._all, self._local, self._workshop):
            for row in range(model.rowCount()):
                if os.path.normcase(model._items[row].get("path") or "") == key:
                    model.set_checked(row, value)

    @Slot(bool)
    def checkAllLocal(self, value: bool) -> None:
        """全选/取消全选当前列表。"""
        model = self._model_for_tab()
        for i in range(model.rowCount()):
            path = model._items[i].get("path") or ""
            if not path:
                continue
            key = os.path.normcase(path)
            if value:
                self._checked_paths.add(key)
            else:
                self._checked_paths.discard(key)
            self._sync_checked(key, value)
        self.selectionChanged.emit()
        total = model.rowCount()
        if value:
            self._set_status(f"已全选 {total} 个 MOD")
        else:
            self._set_status("已取消全选")

    @Slot()
    def invertSelection(self) -> None:
        """反选。"""
        model = self._model_for_tab()
        for i in range(model.rowCount()):
            idx = model.index(i, 0)
            cur = bool(model.data(idx, 0x0100 + model.ROLES.index("checked")))
            self.toggleCheck(i, not cur)
        self._set_status(f"已反选，当前选中 {self.checkedCount} 个")

    @Slot()
    def clearSelection(self) -> None:
        """清空当前列表的勾选（批量操作做完后调用）."""
        model = self._model_for_tab()
        for i in range(model.rowCount()):
            path = model._items[i].get("path") or ""
            key = os.path.normcase(path)
            self._checked_paths.discard(key)
            self._sync_checked(key, False)
        self.selectionChanged.emit()

    @Property(int, notify=selectionChanged)
    def checkedCount(self) -> int:
        """当前 tab 下选中的数量（Property，QML 绑定才会随选择变化自动刷新）。"""
        model = self._model_for_tab()
        return sum(
            1
            for i in range(model.rowCount())
            if model.data(model.index(i, 0), 0x0100 + model.ROLES.index("checked"))
        )

    @Property(int, notify=selectionChanged)
    def visibleCount(self) -> int:
        return self._model_for_tab().rowCount()

    @Property(bool, notify=selectionChanged)
    def allChecked(self) -> bool:
        """当前列表是否已全选（用于全选框状态）。"""
        model = self._model_for_tab()
        n = model.rowCount()
        if n == 0:
            return False
        checked = sum(
            1
            for i in range(n)
            if model.data(model.index(i, 0), 0x0100 + model.ROLES.index("checked"))
        )
        return checked == n

    @Slot(result="QVariantList")
    def checkedItems(self) -> list:
        model = self._model_for_tab()
        out = []
        for i in range(model.rowCount()):
            idx = model.index(i, 0)
            if model.data(idx, 0x0100 + model.ROLES.index("checked")):
                out.append(model._items[i])
        return out

    @Slot(result="QVariantList")
    def checkedPathsOfTab(self) -> list:
        model = self._model_for_tab()
        out = []
        for i in range(model.rowCount()):
            idx = model.index(i, 0)
            if model.data(idx, 0x0100 + model.ROLES.index("checked")):
                out.append(model._items[i]["path"])
        return out

    # ---------------------------------------------------------------- 批量操作
    def _apply_enabled(self, old_path: str, new_path: str, enabled: bool) -> None:
        """启用/禁用之后只刷新受影响的那一行，不重扫整盘。

        原先是直接 self.scan()，而 scan -> _apply_filter -> set_items()
        会 beginResetModel，ListView 瞬间回到顶部，用户刚点的那个 mod
        就跑没影了。这里改为在原位替换数据 + dataChanged。
        """
        if not new_path:
            return

        # 1) 找到它在哪一侧（本地 / 云端）以及行号
        target_attr = ""
        row = -1
        key = os.path.normcase(old_path or "")
        for attr in ("_all_local", "_all_workshop"):
            items = getattr(self, attr, [])
            for i, m in enumerate(items):
                if os.path.normcase(m.get("path") or "") == key:
                    target_attr, row = attr, i
                    break
            if row >= 0:
                break
        if row < 0:
            # 没在已扫描列表里（比如刚导入），退回整盘扫描
            self.scan()
            return

        is_local = target_attr == "_all_local"
        workshop_dir = os.path.join(self._addons_dir, "workshop")
        items = getattr(self, target_attr)
        old = items[row]

        try:
            info = M.read_mod_info(new_path, self._addons_dir, workshop_dir)
        except Exception as e:  # noqa: BLE001
            log(f"read after toggle failed {new_path}: {e!r}")
            info = dict(old)
            info["path"] = new_path
            info["name"] = os.path.basename(new_path)
            info["enabled"] = bool(enabled)

        decorated = self._decorate(info, self._wsc._meta, is_local=is_local)
        # 保留原有的一些展示信息，避免刷新时闪一下
        decorated["mtimeText"] = old.get("mtimeText", "")
        # checked 从持久存储回填（改名后 path 变了，用新 path 查）
        decorated["checked"] = os.path.normcase(new_path) in self._checked_paths
        # 改过名的 mod 如果正被右侧详情面板看着，path 得跟着换，不然详情就空了
        if os.path.normcase(self._selected_path or "") == key:
            self._selected_path = new_path
            decorated["selected"] = True

        # 开了「只看已启用 / 只看已禁用」时，切换后这一项可能该出现或该消失，
        # 那种情况下必须重新过滤（列表内容真的变了）。
        if self._any_state_filter() and self._match(decorated) != self._match(old):
            items[row] = decorated
            self._apply_filter()
            self.modsChanged.emit()
            self.detailChanged.emit()
            return

        items[row] = decorated
        for attr in ("_local", "_workshop"):
            tab_model = getattr(self, attr, None)
            if tab_model is None:
                continue
            t_row = tab_model.row_of_path(old_path)
            if t_row >= 0:
                tab_model.update_item(t_row, dict(decorated))

        # 2) 同步给当前显示的合并列表（该项可能被筛选隐藏，那就只留在 _all_ 里）
        m_row = self._all.row_of_path(old_path)
        if m_row >= 0:
            self._all.update_item(m_row, dict(decorated))

        self.modsChanged.emit()
        self.detailChanged.emit()

    def _any_state_filter(self) -> bool:
        """开着「启用/未启用/可更新」这类按状态筛的项时，切换后可能该出现或该消失。"""
        return bool(self._status_filter)

    @Slot(bool, result="QVariantMap")
    def setEnabledChecked(self, enabled: bool) -> dict:
        """批量启用/禁用当前选中的 MOD。"""
        model = self._model_for_tab()
        paths = []
        for i in range(model.rowCount()):
            idx = model.index(i, 0)
            if model.data(idx, 0x0100 + model.ROLES.index("checked")):
                paths.append(model._items[i]["path"])
        if not paths:
            self._set_status("没有选中任何 MOD")
            self.toast("没有选中任何 MOD", "warn")
            return {"ok": False, "changed": 0}

        changed = 0
        skipped_same = 0
        failed: list[str] = []
        for p in paths:
            # 已是目标状态就跳过：不改名、也不算进 changed。
            # 否则「全选97个禁用，其中94个本来就禁用」会提示「禁用了97个」，
            # 实际只有 3 个真正发生了禁用。
            cur_disabled = p.lower().endswith(M.DISABLED_SUFFIX)
            need_change = (enabled and cur_disabled) or (not enabled and not cur_disabled)
            if not need_change:
                skipped_same += 1
                continue
            new_path = M.set_enabled({"path": p}, enabled)
            if not new_path:
                # 失败：文件不存在或（游戏占用）改不了名
                failed.append(os.path.basename(p))
                continue
            self._apply_enabled(p, new_path, enabled)
            changed += 1
        # 做完就把勾选清掉，否则底部一直挂着「已选中 N 个」
        self.clearSelection()
        word = "启用" if enabled else "禁用"

        if failed:
            # 部分/全部失败要明确提示，不能只说「都禁用了」
            self._set_status(
                f"已{word} {changed} 个，{len(failed)} 个失败（可能被游戏占用）"
            )
            self.toast(
                f"已{word} {changed} 个 MOD，{len(failed)} 个失败\n"
                f"失败的可能被游戏占用，请先关闭 Left 4 Dead 2 再试",
                "warn",
            )
            return {"ok": changed > 0, "changed": changed, "failed": failed,
                    "skipped": skipped_same}

        self._set_status(f"已{word} {changed} 个 MOD")
        self.toast(f"已{word} {changed} 个 MOD", "ok")
        return {"ok": True, "changed": changed, "skipped": skipped_same}

    @Slot(result="QVariantMap")
    def deleteCheckedOfTab(self) -> dict:
        """批量删除当前选中的 MOD。"""
        paths = self.checkedPathsOfTab()
        if not paths:
            self._set_status("没有选中任何 MOD")
            self.toast("没有选中任何 MOD", "warn")
            return {"ok": False, "removed": 0}
        # 连同名封面图一起走
        files = [q for p in paths for q in M.companion_files(p)]
        res = M.delete_files(files, self._delete_to_recycle)
        recycled = bool(res.get("recycled"))
        verb = "放进回收站" if recycled else "删除"
        count = len(paths)
        self._set_status(f"已把 {count} 个 MOD {verb}")
        # 进回收站是「可挽回」的操作 → 黄色；真删是「不可挽回」→ 红色
        self.toast(
            f"已把 {count} 个 MOD {verb}" + ("，删错了能从回收站还原" if recycled else "，已永久删除"),
            "warn" if recycled else "error",
        )
        locked = list(res.get("locked") or [])
        if locked:
            self.toast(f"{len(locked)} 个文件被占用没删掉，关掉游戏再试", "warn")
        self.clearSelection()
        # 先立刻摘行，再扫盘兜底（scan 在扫盘途中会被丢掉，不能只靠它）
        self._forget_paths(paths)
        self.scan()
        return {"ok": bool(res["removed"]), "removed": len(res["removed"]),
                "errors": res["errors"], "recycled": recycled}

    # ================================================================ 操作
    def _forget_paths(self, paths: list, drop_covers: bool = True) -> int:
        """删完之后立刻把这几行从列表里摘掉（不重扫盘）。

        为什么不直接靠 `scan()`：①它在 `_busy` 时会被整个丢掉（正好在扫盘就白删），
        ②整表重建会把列表滚回顶部。删文件是确定发生的事，直接摘行最快也最稳，
        扫盘还是会照跑一遍兜底。

        `drop_covers` 顺手把 `data/modcache/<ID>.jpg` 那张没人认领的封面也删掉
        （同目录同名图由 `M.companion_files` 负责）。
        """
        want = {os.path.normcase(str(p or "")) for p in (paths or []) if p}
        if not want:
            return 0
        gone_ids: list[str] = []
        for attr in ("_all_local", "_all_workshop"):
            items = getattr(self, attr, [])
            keep = []
            for m in items:
                if os.path.normcase(m.get("path") or "") in want:
                    wid = str(m.get("workshopId") or "")
                    if wid:
                        gone_ids.append(wid)
                    continue
                keep.append(m)
            setattr(self, attr, keep)

        before = self._local.rowCount() + self._workshop.rowCount()
        self._apply_filter()
        after = self._local.rowCount() + self._workshop.rowCount()
        if drop_covers and gone_ids:
            for wid in gone_ids:
                for ext in M.IMAGE_EXTS:
                    p = os.path.join(M.CACHE_DIR, f"{wid}{ext}")
                    try:
                        if os.path.isfile(p):
                            os.remove(p)
                    except OSError as e:
                        log(f"drop cover {p} failed: {e!r}")
        self.scannedChanged.emit()
        self.modsChanged.emit()
        self.detailChanged.emit()
        log(f"forget paths: {len(want)} 个请求，列表 {before} → {after}")
        return before - after

    @Slot(str)
    def toggleEnabled(self, path: str) -> None:
        mod = next(
            (m for m in self._local.items() + self._workshop.items() if m["path"] == path),
            None,
        )
        if not mod:
            return
        enabled = not mod.get("enabled", True)
        new_path = M.set_enabled({"path": path}, enabled)
        word = "启用" if enabled else "禁用"
        if not new_path:
            # 失败：文件被占用（游戏开着）或不存在
            name = os.path.basename(path)
            hint = "文件被占用，请先关闭游戏或禁用该 MOD 后重试"
            if M.is_game_running():
                hint = "游戏正在运行，请先完全关闭 Left 4 Dead 2 再试"
            self._set_status(f"{word}失败：{name}（{hint}）")
            self.toast(f"{word}失败：{name}，{hint}", "error")
            return
        self._set_status(f"已{word}")
        self.toast(f"已{word}", "ok" if enabled else "info")
        # 只刷新这一行，避免整表重置导致列表跳回顶部
        self._apply_enabled(path, new_path, enabled)

    @Slot("QVariantList")
    def deleteChecked(self, paths: list) -> None:
        if not paths:
            self._set_status("没有选中任何 MOD")
            self.toast("没有选中任何 MOD", "warn")
            return
        res = M.delete_files([q for p in paths for q in M.companion_files(p)],
                            self._delete_to_recycle)
        recycled = bool(res.get("recycled"))
        verb = "放进回收站" if recycled else "删除"
        self._set_status(f"已把 {len(res['removed'])} 个文件{verb}")
        self.toast(
            f"已把 {len(res['removed'])} 个文件{verb}",
            "warn" if recycled else "error",
        )
        self._forget_paths(paths)
        self.scan()

    @Slot(str)
    def deleteOne(self, path: str) -> None:
        # 同名封面图一起删（MOD 没了那张图也没人认领）
        res = M.delete_files(M.companion_files(path), self._delete_to_recycle)
        name = os.path.basename(str(path or ""))
        if res["removed"]:
            recycled = bool(res.get("recycled"))
            # 进回收站：可还原 → 黄色；直接删：不可挽回 → 红色
            self._set_status("已放进回收站" if recycled else "已删除")
            self.toast(
                ("已把 " + name + " 放进回收站，删错了能还原")
                if recycled else ("已永久删除 " + name),
                "warn" if recycled else "error",
            )
            if os.path.normcase(self._selected_path or "") == os.path.normcase(path or ""):
                self._selected_path = ""
                self.detailChanged.emit()
            self._forget_paths([path])
            self.scan()
        else:
            locked = list(res.get("locked") or [])
            if locked:
                hint = "文件被占用，请先关闭游戏或禁用该 MOD 后重试"
                if M.is_game_running():
                    hint = "游戏正在运行，请先完全关闭 Left 4 Dead 2 再重试"
                self._set_status("删除失败：" + hint)
                self.toast("删除失败：" + hint, "error")
            else:
                err = res["errors"][0] if res["errors"] else "未知"
                self._set_status("删除失败：" + err)
                self.toast("删除失败：" + err, "error")

    @Slot("QVariantList", result="QVariantMap")
    def convertToLocal(self, paths: list) -> dict:
        """把创意工坊的 MOD「转换到本地」（复制到 addons 根目录）。

        paths 为空就用当前勾选的。空勾选 + 空参数时什么都不做（不再有「全部移植」）。
        被游戏占用时只跳过被占用的那些，其余照常转换；界面据 locked 提示重试。
        """
        wanted = [str(p) for p in (paths or []) if str(p).strip()]
        if not wanted:
            wanted = self.checkedPathsOfTab()
        # 只处理真正在 workshop 目录里的
        ws_dir = os.path.normcase(self.workshopDir or "")
        names: list[str] = []
        for p in wanted:
            if ws_dir and os.path.normcase(os.path.dirname(p)) != ws_dir:
                continue
            names.append(os.path.basename(p))
        if not names:
            self._set_status("没有选中创意工坊的 MOD")
            self.toast("请先选中创意工坊的 MOD 再转换", "warn")
            return {"ok": False, "moved": [], "blocked": [], "errors": [],
                    "error": "没有可转换的创意工坊 MOD"}

        res = M.copy_workshop_to_local(self._addons_dir, names)
        moved_files = list(res.get("moved") or [])
        # 只把 vpk 当「MOD」数，封面图不算
        moved_mods = [f for f in moved_files if f.lower().endswith((".vpk", ".vpk.disabled"))]
        moved = len(moved_mods)
        blocked = list(res.get("blocked") or [])
        game = bool(res.get("gameRunning"))

        if moved or blocked:
            parts = []
            if moved:
                parts.append(f"已转换 {moved} 个 MOD 到本地")
            if blocked:
                parts.append(f"{len(blocked)} 个被占用，没有转换")
            text = "，".join(parts)
            self._set_status(text)
            # 被占用 → 黄色（能重试）；全部成功 → 绿色
            self.toast(text, "warn" if blocked else "ok")
            if blocked:
                hint = ("游戏正在运行，请先完全关闭 Left 4 Dead 2 再重试"
                        if game else "请先关闭占用了这些文件的程序（或禁用该 MOD）再重试")
                self.toast(hint, "warn")
        else:
            err = res.get("error") or (res.get("errors") or ["未知问题"])[0]
            self._set_status("转换失败：" + err)
            self.toast("转换失败：" + err, "error")
        self.clearSelection()
        self.scan()
        return res

    @Slot(str)
    def openModFolder(self, path: str) -> None:
        M.open_in_explorer(os.path.dirname(path), path)

    @Slot(str)
    def openWorkshopPage(self, wid: str) -> None:
        if not wid:
            return
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(M.WORKSHOP_PAGE.format(wid)))

    @Slot(str)
    def copyWorkshopLink(self, wid: str) -> None:
        """复制工坊链接（浏览页卡片的右键菜单用）。"""
        key = str(wid or "").strip()
        if not key:
            return
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(M.WORKSHOP_PAGE.format(key))
        self.toast("工坊链接已复制", "ok")

    # ================================================================ 导入
    @Slot("QVariantList", result="QVariantMap")
    def planImport(self, paths: list) -> dict:
        """导入前预演：压缩包会展开，返回真正会导入的文件数 + 文件名（给确认框显示）。"""
        if not paths:
            return {"count": 0, "names": [], "archives": []}
        try:
            return M.inspect_import_paths(paths)
        except Exception as e:  # noqa: BLE001  预演失败不能让确认框都打不开
            log(f"plan import failed: {e!r}")
            return {"count": len(paths), "names": [], "archives": []}

    @Slot("QVariantList", result="QVariantMap")
    def importFiles(self, paths: list) -> dict:
        if not self._addons_dir:
            self._set_status("还没设置 MOD 目录")
            self.toast("还没设置 MOD 目录，先去设置里检测一下", "error")
            return {"ok": False, "error": "no dir"}
        game = M.is_game_running()
        self._set_status(f"正在导入 {len(paths)} 个文件…")
        res = M.import_files(paths, self._addons_dir)
        game = game or bool(res.get("gameRunning"))
        copied = len(res.get("copied") or [])
        skipped = len(res.get("skipped") or [])
        locked = list(res.get("locked") or [])

        if copied:
            msg = f"导入完成：新增 {copied} 个文件"
            if skipped:
                msg += f"，跳过 {skipped} 个"
            self._set_status(msg)
            self.toast(f"已导入 {copied} 个文件", "ok")
            self.importFinished.emit(copied, skipped)
            self.scan()
        else:
            self._set_status("导入失败：" + (res.get("error") or "没有可导入的文件"))

        if locked:
            hint = "请先关闭游戏或禁用占用它的 MOD 再重试"
            if game:
                hint = "游戏正在运行，请先完全关闭 Left 4 Dead 2 再重试"
            self._set_status(f"{len(locked)} 个文件被占用，未导入。{hint}")
            self.toast(f"{len(locked)} 个文件被占用，未导入。{hint}", "warn")
        elif not copied and not res.get("error"):
            self.toast("没有可导入的文件（只支持 .vpk 和封面图）", "warn")
        return res

    @Slot(result="bool")
    def gameRunning(self) -> bool:
        """给界面用：导入/转换前判断要不要提示「游戏正在运行」。"""
        return M.is_game_running()

    # ================================================================ 创意工坊导入
    # 思路：给一个工坊 ID（或链接）→ 从第三方站拿 CDN 直链 → 查前置物品
    #       → 弹窗让用户勾选 → 按设置的线程数并发下载到 addons 目录。
    @Property(int, notify=statusChanged)
    def downloadThreads(self) -> int:
        """并发下载线程数（设置里可调）。"""
        return WD.clamp_threads(getattr(self, "_dl_threads", WD.DEFAULT_THREADS))

    @Slot(int)
    def setDownloadThreads(self, value: int) -> None:
        n = WD.clamp_threads(value)
        if n == getattr(self, "_dl_threads", None):
            return
        self._dl_threads = n
        self._cfg["download_threads"] = n
        self._cfg.save()
        self.statusChanged.emit()

    @Slot(str)
    def probeWorkshopAsync(self, text: str) -> None:
        """异步解析（不卡界面，含前置）。结果通过 workshopProbed 信号回主线程。

        以前是同步 Slot，解析一个合集要几秒到几十秒，期间整个界面都点不动，
        看起来就像「卡死」了。现在丢到后台线程，UI 侧显示 loading。
        """
        self._probe_start(text, want_deps=True)

    @Slot(str)
    def probeWorkshopFast(self, text: str) -> None:
        """快速解析：只要本体 / 合集成员，不翻前置。工坊里点开卡片走这条。

        实测「点开一个 MOD → 能点下载」这条链路里，翻前置详情页占了大头，
        而浏览时用户根本还没决定要不要前置。
        """
        self._probe_start(text, want_deps=False)

    def _probe_start(self, text: str, want_deps: bool) -> None:
        if not self._addons_dir:
            self.workshopProbed.emit({
                "ok": False, "items": [],
                "error": "还没设置 MOD 目录，先去设置里检测一下",
            })
            return
        if getattr(self, "_probing", False):
            # 上一次还在跑：排队，等它 emit 完接着跑这一次（直接丢掉会让
            # 「点开卡片 → 立刻点下载」这条链路永远等不到结果）
            self._probe_queued = (str(text or ""), bool(want_deps))
            return
        # 用户又点开了别的条目：上一个还在后台补合集成员的线程可以收工了
        prev = getattr(self, "_probe_dl", None)
        if prev is not None:
            try:
                prev.stop_streaming()
            except Exception:  # noqa: BLE001
                pass
        self._probing = True
        # ★ 每次解析带一个自增序号，emit 时一起带回去。
        #   用户关掉详情面板后 QML 会调 cancelWorkshopProbe() 把 _probe_seq 再 +1，
        #   于是「还在路上的那次结果」回来时序号就对不上，QML 直接丢弃它 ——
        #   这就是「点开没加载出来、退出后又自己弹出来」的根因：
        #   结果排队回主线程时面板已经关了，QML 却照着结果把 detailOpen 又设成 true。
        self._probe_seq = int(getattr(self, "_probe_seq", 0)) + 1
        self._set_status("正在解析创意工坊链接…")
        threading.Thread(target=self._probe_worker,
                         args=(str(text or ""), bool(want_deps), self._probe_seq),
                         daemon=True).start()

    @Slot()
    def cancelWorkshopProbe(self) -> None:
        """用户关掉详情：作废「还在路上」的解析结果，别再弹回来。

        序号 +1 就够了 —— 在跑的那次线程 emit 时带着旧序号，QML 一看不对就丢。
        顺便叫停正在补合集成员的那个下载器，省点流量。
        """
        self._probe_seq = int(getattr(self, "_probe_seq", 0)) + 1
        self._probe_queued = None
        dl = getattr(self, "_probe_dl", None)
        if dl is not None:
            try:
                dl.stop_streaming()
            except Exception:  # noqa: BLE001
                pass

    def _probe_worker(self, text: str, want_deps: bool = True,
                      seq: int = 0) -> None:
        """后台线程：解析 + 标注已安装，然后 emit 回主线程。

        `want_deps=False` 只解析本体（/合集的子项），不去翻每个前置的详情页 ——
        浏览时点开一张卡片用这条快速通道，省掉 1-3 次网络往返。
        `seq` 是发起时的请求序号，原样带回给 QML 判断「这次结果还有人要吗」。
        """
        try:
            d = WD.WorkshopDownloader(threads=self.downloadThreads,
                                      cdn_ip=self._active_cdn_ip())
            self._probe_dl = d
            res = d.probe(text, want_deps=want_deps,
                          progress=self._on_probe_progress,
                          on_members=self._on_probe_members)
        except Exception as e:  # noqa: BLE001  解析崩了也要让 UI 退出 loading
            log(f"probe workshop crashed: {e!r}")
            res = {"ok": False, "items": [], "error": f"解析出错：{e}"}
        if res.get("ok"):
            # 已装过的标注出来，并在 UI 上给「是否重新下载」的提示
            installed = {str(m.get("workshopId") or "")
                         for m in (getattr(self, "_all_local", [])
                                   + getattr(self, "_all_workshop", []))}
            any_installed = False
            for it in res.get("items") or []:
                it["installed"] = it["id"] in installed
                # ★ 前置不是必选的：默认只勾本体/合集成员，前置一律不勾（用户自己决定）
                it["checked"] = (not it["installed"]) and bool(it.get("available")) \
                    and not it.get("isDep")
                if it["installed"]:
                    any_installed = True
            res["anyInstalled"] = any_installed
            res["gameRunning"] = M.is_game_running()
        # 先清标志再 emit，否则上一次没跑完的话后面所有解析都会被「叠着开」挡住
        self._probing = False
        # 带上请求序号：QML 拿它和「当前还有效的序号」比，对不上就丢弃
        # （用户已经关掉详情了，别再自己弹回来）
        try:
            res["seq"] = int(seq)
        except (TypeError, ValueError):
            res["seq"] = 0
        # 跨线程 emit，Qt 自动排队回主线程
        self.workshopProbed.emit(res)
        # 排队中的那一次（通常是「点开卡片」之后的「连前置一起下」）现在接着跑
        nxt = getattr(self, "_probe_queued", None)
        if nxt and not self._closing:
            self._probe_queued = None
            self._probe_start(nxt[0], nxt[1])

    def _on_probe_progress(self, stage: str, done: int, total: int) -> None:
        """后台线程里调用，转成信号让 UI 更新进度文字。"""
        try:
            self.workshopProbeProgress.emit(str(stage), int(done), int(total))
        except RuntimeError:
            pass

    def _on_probe_members(self, payload: dict) -> None:
        """合集成员的后续批次（后台线程调用）。

        快通道先给前 60 个成员，剩下的由下载器边拉边回调，这里转成信号——
        Qt 会把它排队回主线程，详情面板就能一批一批把成员铺满。
        """
        try:
            installed = {str(m.get("workshopId") or "")
                         for m in (getattr(self, "_all_local", [])
                                   + getattr(self, "_all_workshop", []))}
            for it in payload.get("items") or []:
                it["installed"] = str(it.get("id")) in installed
                it["checked"] = False
            self.workshopMembersChanged.emit(payload)
        except RuntimeError:
            pass

    @Slot(str, result="QVariantMap")
    def probeWorkshop(self, text: str) -> dict:
        """同步版解析（保留给测试/脚本用；UI 请用 probeWorkshopAsync）。"""
        if not self._addons_dir:
            return {"ok": False, "error": "还没设置 MOD 目录，先去设置里检测一下",
                    "items": []}
        d = WD.WorkshopDownloader(threads=self.downloadThreads,
                                  cdn_ip=self._active_cdn_ip())
        self._set_status("正在解析创意工坊链接…")
        res = d.probe(text, want_deps=True)
        if not res.get("ok"):
            msg = res.get("error") or "解析失败"
            self._set_status(msg)
            self.toast(msg, "error")
            return res

        installed = {str(m.get("workshopId") or "") for m in
                     (getattr(self, "_all_local", []) + getattr(self, "_all_workshop", []))}
        any_installed = False
        for it in res.get("items") or []:
            it["installed"] = it["id"] in installed
            it["checked"] = (not it["installed"]) and bool(it.get("available")) \
                and not it.get("isDep")
            if it["installed"]:
                any_installed = True
        res["anyInstalled"] = any_installed
        res["gameRunning"] = M.is_game_running()
        return res

    @Slot("QVariantList")
    def downloadWorkshopAsync(self, items: list) -> None:
        """异步下载（不卡界面）。

        从这一版起，下载全部交给 `core.downloads`（统一下载队列）：
        每条 MOD 一个任务，进度、取消、重试都在下载页里看得见、点得到。
        以前这里只有状态栏一行字 + 结束一个 toast，下几个/哪个失败全看不到。

        条目**可以没有 url**：合集快通道列出来的成员就是这样，直链在下载线程里
        现解析（浏览时为了快不查）。所以这里只要求有条目就行。
        """
        if not self._addons_dir:
            self.workshopDownloaded.emit({"ok": False, "done": [], "failed": [],
                                          "error": "还没设置 MOD 目录"})
            return
        todo = [it for it in (items or []) if self._downloadable(it)]
        if not todo:
            self.workshopDownloaded.emit({"ok": False, "done": [], "failed": [],
                                          "error": "没有可下载的条目"})
            return

        # `ModManager` 不存 core 引用（构造时传的是 parent），这里按需从 parent 摸上去。
        # 直接 getattr(self, "core") 会 AttributeError —— 之前就这样炸过。
        queue = getattr(self.parent(), "downloads", None)
        if queue is None:
            queue = getattr(getattr(self, "core", None), "downloads", None)
        if queue is None:
            # 兜底：万一 Core 还没接上下载队列，退回老路，别让下载直接没了
            self._set_status(f"正在下载 {len(todo)} 个 MOD（{self.downloadThreads} 线程）…")
            threading.Thread(target=self._download_worker, args=(todo,), daemon=True).start()
            return

        # ★ 立刻回一句「已收到」，把「处理中」那个转圈关掉，剩下的活全丢后台。
        #   以前 `_expand_collections()` 是在这里同步跑的：合集几百个成员要拉一次
        #   完整 children、再 100 个一批问详情，**几十秒**里 UI 一直停在「下载中…」，
        #   用户看到的就是「创意工坊一直显示处理中」（真实反馈）。
        #   现在：马上 emit（页面解除忙碌态），展开和排队都在后台线程里做，
        #   进度改由下载页展示。
        self.workshopDownloaded.emit({"ok": True, "done": [], "failed": [],
                                      "queued": len(todo),
                                      "expanding": True, "error": ""})

        def prepare() -> None:
            expanded = todo
            try:
                expanded = self._expand_collections(todo)
            except Exception as e:          # noqa: BLE001 - 展开失败也别把队列搞崩
                log(f"expand collections failed: {e!r}")
            if self._closing:
                return
            res = queue.addMods(expanded)
            if res.get("ok"):
                self._set_status(f"已排入 {res.get('count')} 个 MOD 下载")
                self.toast(f"已排入 {res.get('count')} 个下载，进度在下载页看", "ok")
            else:
                msg = res.get("error") or "排入失败"
                self._set_status(msg)
                self.toast(msg, "error")

        threading.Thread(target=prepare, daemon=True).start()

    @staticmethod
    def _downloadable(item: dict) -> bool:
        """有条目就是能下的：有直链最好，没有的话下载线程会现查。"""
        if not isinstance(item, dict):
            return False
        return bool(item.get("url")) or str(item.get("id") or "").strip().isdigit()

    def _expand_collections(self, todo: list) -> list:
        """把「合集」条目展开成它的全部成员。

        UI 上传的合集条目只有 {id, isCollection:true}（浏览时只列了前 60 个），
        真正要下的是 875 个成员，所以这里拿一次完整的 children。

        顺手把详情接口白送的下载直链（`file_url`，单文件 .vpk 才是）一起填上：
        合集动辄几百个成员，要是每条都去下载站换一次直链（每个 2~7 秒），
        光解析就要几十分钟；这里的详情是 100 个一批、几秒就能问完。
        拿不到直链的成员不填，交给下载线程现解析。
        """
        out: list = []
        for it in todo:
            if it.get("isCollection") or it.get("isMember"):
                wid = str(it.get("id") or "").strip()
                if not wid.isdigit():
                    continue
                coll = WD.fetch_collection(wid)
                kids = coll.get("children") if coll.get("isCollection") else None
                if not kids:
                    # 拉不到成员列表就退回当成单个条目（至少给个明确失败，而不是静默丢）
                    out.append(it)
                    continue
                self._set_status(f"合集共 {len(kids)} 个成员，正在解析下载直链…")
                info = {}
                try:
                    info = WD.fetch_details(list(kids))       # 100 个一批
                except Exception as e:  # noqa: BLE001
                    log(f"expand collections: details failed: {e!r}")
                for cid in kids:
                    api = info.get(cid) or {}
                    url = WD.direct_file_url(api)
                    out.append({
                        "id": cid,
                        "title": api.get("title") or cid,
                        "size": int(api.get("size") or 0),
                        "preview": api.get("preview") or "",
                        "isMember": True,
                        "url": url,
                        "filename": api.get("filename") or "",
                        "urlFromApi": bool(url),
                    })
            else:
                out.append(it)
        return out

    def _download_worker(self, todo: list) -> None:
        try:
            res = self.downloadWorkshop(todo)
        except Exception as e:  # noqa: BLE001
            log(f"download workshop crashed: {e!r}")
            res = {"ok": False, "done": [], "failed": [], "error": str(e)}
        self.workshopDownloaded.emit(res)

    @Slot("QVariantList", result="QVariantMap")
    def downloadWorkshop(self, items: list) -> dict:
        """把勾选的条目下载到 addons 目录（同步执行，UI 侧请走 downloadWorkshopAsync）。"""
        if not self._addons_dir:
            self._set_status("还没设置 MOD 目录")
            self.toast("还没设置 MOD 目录，先去设置里检测一下", "error")
            return {"ok": False, "error": "no dir", "done": [], "failed": []}

        todo = [it for it in (items or []) if self._downloadable(it)]
        if not todo:
            self.toast("没有可下载的条目（下载站没给直链）", "warn")
            return {"ok": False, "error": "nothing to download", "done": [], "failed": []}

        # 合集先展开成全部成员（并在状态栏说一声，875 个成员要下很久）
        todo = self._expand_collections(todo)

        game = M.is_game_running()
        threads = self.downloadThreads
        self._set_status(f"正在下载 {len(todo)} 个 MOD（{threads} 线程）…")

        d = WD.WorkshopDownloader(threads=threads,
                                  cdn_ip=self._active_cdn_ip())
        self._dl = d
        done_count = [0]

        def on_item(it: dict) -> None:
            # 没有直链的成员会先「正在解析直链…」，875 个成员的合集不至于看着像卡死
            self._set_status(
                f"正在下载 {len(todo)} 个 MOD（{threads} 线程）…"
                + ("　正在解析直链…" if it.get("resolving") else "")
            )

        def on_done(it: dict) -> None:
            done_count[0] += 1
            self._set_status(
                f"下载中 {done_count[0]}/{len(todo)}"
                + (f"（失败：{it.get('error')}）" if not it.get("ok") else "")
            )

        try:
            res = d.download(todo, self._addons_dir, on_item=on_item, on_done=on_done)
        finally:
            self._dl = None

        done = list(res.get("done") or [])
        failed = list(res.get("failed") or [])
        # 下载下来的都记一笔导入日期，详情里显示「导入日期」才对
        if done:
            names = [os.path.basename(x.get("path") or "") for x in done]
            M.record_imports([n for n in names if n])

        if done:
            text = f"已下载 {len(done)} 个 MOD"
            if failed:
                text += f"，{len(failed)} 个失败"
            self._set_status(text)
            self.toast(text, "warn" if failed else "ok")
            self.scan()
            # 文件已经是 <ID>.vpk，但管理器还只知道一串数字 ——
            # 补一次工坊标题 + 封面，列表里才会是「名字 + 图」而不是「3840…」
            self._after_download(done)
        else:
            msg = res.get("error") or "下载失败"
            self._set_status("下载失败：" + msg)
            self.toast("下载失败：" + msg, "error")

        if failed:
            self.toast(f"失败：{failed[0].get('error') or '未知原因'}", "error")
        if game:
            self.toast("游戏正在运行，新下载的 MOD 可能要重启游戏才生效", "warn")

        return {"ok": bool(done), "done": done, "failed": failed,
                "error": res.get("error") or ""}

    # 下完之后补「工坊标题 + 封面」的上限。
    # 875 个成员的合集如果全查全下，封面能吃掉好几百 MB，
    # 所以标题最多补 200 个、封面最多下 60 张；其余的点一次「识别工坊 MOD」补齐。
    META_FILL_LIMIT = 200
    COVER_FILL_LIMIT = 60

    def _after_download(self, done: list) -> None:
        """下完的 MOD 补上工坊标题和封面（文件名已经是 <ID>.vpk 了）。

        这一步是「下载完自动识别」的关键：`_decorate` 认 ID 之后，
        标题、封面、作者、更新检查全都靠 `data/modmeta.json` 里的那一份资料，
        没有它列表里就只有一串数字、卡片一片空白。
        """
        ids: list[str] = []
        for x in done:
            wid = str(x.get("id") or "").strip()
            if wid.isdigit() and wid not in ids:
                ids.append(wid)
        if not ids:
            return

        todo = ids[:self.META_FILL_LIMIT]
        try:
            info = self._wsc.fetch(todo)      # 批量查，顺手写进 modmeta.json
        except Exception as e:  # noqa: BLE001
            log(f"after download meta failed: {e!r}")
            return
        if self._closing:
            return

        # 刚下完的文件路径：封面要放到 vpk **旁边**，列表才认（见 _place_cover_beside）
        path_of = {}
        for x in done:
            wid = str(x.get("id") or "").strip()
            if wid and x.get("path"):
                path_of.setdefault(wid, str(x["path"]))

        def _find_vpk(wid: str) -> str:
            """没给 path 时（老调用方 / 测试）自己按 <ID>.vpk 在 addons 里找一遍。"""
            if not wid or not self._addons_dir:
                return ""
            for folder in (self._addons_dir,
                           os.path.join(self._addons_dir, "workshop")):
                for name in (f"{wid}.vpk", f"{wid}.vpk.disabled"):
                    cand = os.path.join(folder, name)
                    if os.path.isfile(cand):
                        return cand
            return ""

        got = 0
        for wid in todo[:self.COVER_FILL_LIMIT]:
            v = info.get(wid) or {}
            if not (v.get("ok") and v.get("preview")):
                continue
            vpk = path_of.get(wid) or _find_vpk(wid)
            if self._place_cover_beside(vpk, wid, v["preview"]):
                got += 1
            elif not vpk:
                # 连 vpk 都找不到（文件可能被移走了）：至少把缓存下下来，
                # 下次扫到它 / 再检查时能直接用上，不用重新请求一遍。
                self._wsc.download_cover(wid, v["preview"])
        log(f"after download: meta {len(info)}/{len(todo)}, covers {got}")
        if self._closing:
            return

        # 不重扫盘：直接把新拿到的标题/封面贴到已经在列表里的行上（不会滚回顶部）
        self._apply_meta_to_items()
        if got:
            self._set_status(f"已补上 {got} 张工坊封面")

    @Slot()
    def cancelWorkshopDownload(self) -> None:
        """取消正在进行的下载（已经下完的不管）。"""
        d = getattr(self, "_dl", None)
        if d is not None:
            d.cancel()
            self._set_status("正在取消下载…")

    # ================================================================ 加载顺序（addonlist.txt）
    # 这个顺序是真的会改变游戏里「谁覆盖谁」的：addonlist 里越靠后，加载优先级越高。
    # 和界面上的「排序」完全是两件事（那个只影响显示）。
    @Property("QVariantMap", notify=addonOrderChanged)
    def addonOrder(self) -> dict:
        """加载顺序清单（含「文件不存在」标记 + 真实名称）。

        addonlist.txt 里存的只是文件名（工坊 MOD 就是纯数字 ID），
        直接显示就是一串数字。这里复用 MOD 列表那套工坊缓存把它解析成真实名称，
        所以「加载顺序」里看到的名字和卡片墙上的完全一致。
        """
        if not self._addons_dir:
            return {"ok": False, "items": [], "missing": 0, "path": "",
                    "exists": False, "error": "还没设置 MOD 目录"}
        try:
            view = AL.build_view(self._addons_dir)
        except Exception as e:  # noqa: BLE001
            log(f"build addon order failed: {e!r}")
            return {"ok": False, "items": [], "missing": 0, "path": "",
                    "exists": False, "error": f"读取失败：{e}"}

        # 把「文件名/工坊ID」解析成真实标题（和 MOD 列表同一份缓存）
        meta = getattr(self._wsc, "_meta", {}) or {}
        vpk_cache = getattr(self, "_vpk_cache", {}) or {}
        for it in view.get("items") or []:
            stem = it.get("stem") or ""
            wid = M.workshop_id_of(stem + ".vpk")
            it["workshopId"] = wid
            title = ""
            author = ""
            if wid:
                info = meta.get(wid) or {}
                if info.get("ok"):
                    title = (info.get("title") or "").strip()
            # 工坊没识别出来 → 试 VPK 内部的 addoninfo.txt
            if not title:
                vk = vpk_cache.get(os.path.normcase(it.get("path") or "")) or {}
                vi = vk.get("info") or {}
                title = (vi.get("title") or "").strip()
                author = (vi.get("author") or "").strip()
            if not title:
                title = stem
            it["title"] = title
            it["author"] = author
            # 判断一下「名字是不是纯数字」—— UI 上可以把纯数字标成「未识别」
            it["unknownName"] = title.strip().isdigit()
        return view

    @Property(str, notify=addonOrderChanged)
    def addonOrderPath(self) -> str:
        return AL.addonlist_path(self._addons_dir)

    @Slot()
    def refreshAddonOrder(self) -> None:
        self.addonOrderChanged.emit()

    @Slot(int, int, result="QVariantMap")
    def moveAddonOrder(self, from_index: int, to_index: int) -> dict:
        """拖动排序：把第 from 项移到第 to 项的位置，并立刻写回 addonlist.txt。"""
        view = self.addonOrder
        if not view.get("ok"):
            self.toast(view.get("error") or "读取加载顺序失败", "error")
            return view
        items = list(view.get("items") or [])
        if not items:
            return view
        moved = AL.reorder(items, from_index, to_index)
        if [x["name"] for x in moved] == [x["name"] for x in items]:
            return view      # 没变化就别写盘
        res = self._save_addon_order(moved)
        return res

    @Slot(int, int, result="QVariantMap")
    def shiftAddonOrder(self, index: int, delta: int) -> dict:
        """上移 / 下移（给键盘和按钮用）。"""
        view = self.addonOrder
        if not view.get("ok"):
            return view
        items = list(view.get("items") or [])
        if not items:
            return view
        moved = AL.move_up_down(items, index, delta)
        if [x["name"] for x in moved] == [x["name"] for x in items]:
            return view
        return self._save_addon_order(moved)

    @Slot(result="QVariantMap")
    def syncAddonOrder(self) -> dict:
        """把 addons 里「有文件但 addonlist 没记」的 MOD 补到末尾。"""
        if not self._addons_dir:
            return {"ok": False, "error": "还没设置 MOD 目录"}
        res = AL.sync_from_addons(self._addons_dir)
        if res.get("ok"):
            n = len(res.get("added") or [])
            if n:
                self.toast(f"已把 {n} 个未登记的 MOD 补到末尾", "ok")
            else:
                self.toast("加载顺序里没有遗漏的 MOD", "info")
            self.addonOrderChanged.emit()
        else:
            self.toast(res.get("error") or "同步失败", "error")
        return res

    @Slot("QVariantList", result="QVariantMap")
    def saveAddonOrder(self, items: list) -> dict:
        """按界面给的顺序写 addonlist.txt（「保存」按钮走这个）。

        和 moveAddonOrder 的区别：那个是「每动一下立刻写盘」，
        这个是「攒够了再一次性写」—— 用户要求的交互是后者。
        """
        if not self._addons_dir:
            return {"ok": False, "error": "还没设置 MOD 目录", "count": 0}
        if not items:
            return {"ok": False, "error": "没有可保存的条目", "count": 0}
        rows = []
        for it in items:
            name = str((it or {}).get("name") or "").strip()
            if not name:
                continue
            rows.append({"name": name,
                         "enabled": bool((it or {}).get("enabled", True))})
        if not rows:
            return {"ok": False, "error": "没有可保存的条目", "count": 0}
        res = AL.save(self._addons_dir, rows)
        if res.get("ok"):
            self._set_status(f"加载顺序已保存（{res.get('count')} 个 MOD）")
            self.toast(f"加载顺序已保存（{res.get('count')} 个）", "ok")
            self.addonOrderChanged.emit()
        else:
            msg = res.get("error") or "保存失败"
            self._set_status("保存加载顺序失败：" + msg)
            self.toast("保存加载顺序失败：" + msg, "error")
        return {"ok": bool(res.get("ok")), "count": int(res.get("count") or 0),
                "path": res.get("path") or "", "error": res.get("error") or ""}

    @Slot(str, bool, result="QVariantMap")
    def setAddonEnabled(self, name: str, enabled: bool) -> dict:
        """改单个条目的启用/禁用位（addonlist 里那个 0/1）。"""
        view = self.addonOrder
        if not view.get("ok"):
            return view
        items = [dict(x) for x in (view.get("items") or [])]
        hit = False
        for it in items:
            if it["name"] == name:
                it["enabled"] = bool(enabled)
                hit = True
                break
        if not hit:
            return view
        return self._save_addon_order(items)

    def _save_addon_order(self, items: list[dict]) -> dict:
        """写回 addonlist.txt 并刷新界面。"""
        res = AL.save(self._addons_dir, items)
        if res.get("ok"):
            self.addonOrderChanged.emit()
            self._set_status(f"加载顺序已保存（{res.get('count')} 个 MOD）")
        else:
            self.toast(res.get("error") or "保存加载顺序失败", "error")
            self._set_status("保存加载顺序失败")
        view = self.addonOrder
        view["saved"] = bool(res.get("ok"))
        return view

    # ================================================================ 创意工坊网络加速
    # 界面上只出现节点地名（首尔 / 东京 / 香港…），IP 只在程序内部用。
    CDN_MODE_AUTO = "auto"
    CDN_MODE_MANUAL = "manual"
    CDN_MODE_OFF = "off"

    @Property(str, notify=statusChanged)
    def cdnMode(self) -> str:
        """加速模式：auto=自动优选最快节点 / manual=手动指定节点 / off=关闭。"""
        mode = str(self._cfg["workshop_cdn_mode"] or "auto").strip().lower()
        return mode if mode in ("auto", "manual", "off") else "auto"

    @Slot(str)
    def setCdnMode(self, mode: str) -> None:
        v = str(mode or "").strip().lower()
        if v not in ("auto", "manual", "off"):
            return
        if v == self.cdnMode:
            return
        self._cfg["workshop_cdn_mode"] = v
        self._cfg.save()
        self.statusChanged.emit()
        self.cdnTestChanged.emit()
        if v == "auto":
            self.autoSelectCdnNode()
        elif v == "off":
            self._cfg["workshop_cdn_ip"] = ""
            self._cfg["workshop_cdn_ms"] = 0
            self._cfg.save()
            self.statusChanged.emit()
            self.toast("已关闭工坊网络加速，改走系统 DNS", "info")

    @Property(bool, notify=statusChanged)
    def cdnEnabled(self) -> bool:
        """兼容旧接口：加速是否开着（模式不是 off）。"""
        return self.cdnMode != "off"

    @Slot(bool)
    def setCdnEnabled(self, value: bool) -> None:
        if bool(value) == self.cdnEnabled:
            return
        self.setCdnMode("auto" if value else "off")

    @Property(str, notify=statusChanged)
    def cdnIp(self) -> str:
        """当前实际连的节点 IP（内部用，UI 不展示）。"""
        return str(self._cfg["workshop_cdn_ip"] or "")

    def _active_cdn_ip(self) -> str:
        """下载 / 解析时实际要用的节点 IP；关掉加速就是空串。"""
        if self.cdnMode == "off":
            return ""
        return self.cdnIp

    @Property(str, notify=statusChanged)
    def cdnRegion(self) -> str:
        """当前节点的地名（首尔 / 东京…），设置里展示这个。"""
        region = str(self._cfg["workshop_cdn_region"] or "")
        if region:
            return region
        ip = self.cdnIp
        return WN.region_for_ip(ip) if ip else ""

    @Property(int, notify=statusChanged)
    def cdnMs(self) -> int:
        """当前节点的延迟（毫秒），0 = 未知。"""
        try:
            return int(self._cfg["workshop_cdn_ms"] or 0)
        except (TypeError, ValueError):
            return 0

    @Property(str, notify=statusChanged)
    def cdnSummary(self) -> str:
        """给设置面板用的单行状态文字。

        自动模式只报地名（东京/首尔…）——那是程序自己挑的机器，报 IP 对用户没意义；
        手动模式是用户自己填的地址，所以只回一句「手动指定」，地址本身就在输入框里。
        """
        if self.cdnMode == "off":
            return "已关闭"
        if self.cdnMode == "manual":
            if not self.cdnIp:
                return "手动指定（还没填地址）"
            region = self.cdnRegion
            return f"手动 · {region}" if region else "手动指定"
        region = self.cdnRegion
        if not region:
            return "自动优选（还没测速）"
        ms = self.cdnMs
        return f"自动 · {region}" + (f" · {ms}ms" if ms > 0 else "")

    @Slot(str)
    def setCdnRegion(self, region: str) -> None:
        """根据地名挑节点。界面上已经不提供地名列表了，留给脚本/兼容用。"""
        want = str(region or "").strip()
        if not want:
            return
        nodes = self._cdn_nodes or WN.fetch_cdn_nodes()
        self._cdn_nodes = nodes
        node = WN.pick_cdn_node(nodes, want)
        if not node:
            self.toast("没找到这个地区的节点，先点「重新测速」刷新节点表", "warn")
            return
        if self.cdnMode != "manual":
            self._cfg["workshop_cdn_mode"] = "manual"
        self._cfg["workshop_cdn_ip"] = str(node.get("ip") or "")
        self._cfg["workshop_cdn_region"] = str(node.get("region") or want)
        self._cfg["workshop_cdn_ms"] = 0
        self._cfg.save()
        self.statusChanged.emit()
        self.toast(f"工坊加速节点已切到 {self.cdnRegion}", "ok")

    @Slot(str)
    def setCdnIp(self, value: str) -> None:
        """手动指定加速地址：用户自己填的 IPv4 / IPv6。

        以前这里只收「认得出地区」的 Steam CDN 地址，现在按用户要求放开：
        自建服务器/自选节点的地址也能填，认不出地区就不报地区（界面上只写「手动指定」）。
        """
        addr = WDNS.valid_address(value)
        if not addr:
            self.toast("请填一个合法的 IPv4 或 IPv6 地址", "warn")
            return
        region = WN.region_for_ip(addr)
        if region == "未知地区":
            region = ""     # 认不出就别瞎猜，界面上只显示「手动指定」
        if self.cdnMode == "manual" and self.cdnIp == addr:
            return
        self._cfg["workshop_cdn_mode"] = "manual"
        self._cfg["workshop_cdn_ip"] = addr
        self._cfg["workshop_cdn_region"] = region
        self._cfg["workshop_cdn_ms"] = 0
        self._cfg.save()
        self.statusChanged.emit()
        self._cover_proxy.clear_cache(disk=False)   # 换节点：内存里那批图按旧节点取的，扔掉
        self.toast(f"已手动指定加速地址{f'（{region}）' if region else ''}", "ok")

    @Slot()
    def clearCdnIp(self) -> None:
        """恢复走系统 DNS。"""
        self.setCdnMode("off")

    @Property("QVariantList", notify=cdnTestChanged)
    def cdnNodes(self) -> list:
        """可选节点列表：[{region, ms, ok}] —— 只有地名和延迟，没有 IP。"""
        rows = list(getattr(self, "_cdn_rows", []))
        if rows:
            return rows
        return [{"region": WN.region_for_ip(ip), "ms": 0, "ok": True}
                for ip in WN.BUILTIN_CDN_IPS]

    @Slot(result="QVariantList")
    def builtinCdnIps(self) -> list:
        """兼容旧接口：按地名的节点列表（不再返回 IP）。"""
        return self.cdnNodes

    @Property(bool, notify=cdnTestChanged)
    def cdnTesting(self) -> bool:
        return bool(getattr(self, "_cdn_testing", False))

    @Slot()
    def autoSelectCdnNode(self) -> None:
        """自动优选：拉节点表 → 并发测速 → 用最快的那个。"""
        if getattr(self, "_cdn_testing", False):
            return
        self._cdn_testing = True
        self._cdn_rows = []
        self.cdnTestChanged.emit()
        self._set_status("正在测速工坊加速节点…")

        def worker() -> None:
            try:
                nodes = WN.fetch_cdn_nodes()
                self._cdn_nodes = nodes
                res = WN.best_node(nodes, timeout=4.0)
            except Exception as e:  # noqa: BLE001
                res = {"ok": False, "rows": [], "error": f"测速出错：{e}"}
            self._cdn_testing = False
            rows = list(res.get("rows") or [])
            # 同一地区只留最快的一条，UI 上不重复
            best_of: dict[str, dict] = {}
            for row in rows:
                key = str(row.get("region") or "")
                if not key:
                    continue
                if row.get("ok") and row.get("ms", -1) >= 0:
                    old = best_of.get(key)
                    if old is None or row["ms"] < old["ms"]:
                        best_of[key] = row
                elif key not in best_of:
                    best_of[key] = {"region": key, "ms": -1, "ok": False}
            self._cdn_rows = sorted(
                best_of.values(),
                key=lambda r: (0 if r["ok"] else 1,
                               r["ms"] if r["ms"] >= 0 else 10 ** 9))
            if res.get("ok") and self.cdnMode == "auto":
                self._cfg["workshop_cdn_ip"] = str(res.get("ip") or "")
                self._cfg["workshop_cdn_region"] = str(res.get("region") or "")
                self._cfg["workshop_cdn_ms"] = int(res.get("ms") or 0)
                self._cfg.save()
                self._set_status(
                    f"加速节点已选：{res.get('region')}（{res.get('ms')}ms）")
                self.toast(f"已自动选用最快的节点：{res.get('region')}"
                           f"（{res.get('ms')}ms）", "ok")
            elif res.get("ok"):
                self._set_status(
                    f"测速完成，最快是 {res.get('region')}（{res.get('ms')}ms）")
            else:
                self._set_status("所有加速节点都连不上")
                self.toast(res.get("error") or "所有节点都连不上，检查网络", "error")
            self.statusChanged.emit()
            self.cdnTestChanged.emit()

        threading.Thread(target=worker, daemon=True).start()

    @Slot(result="QVariantMap")
    def testCdnIps(self) -> dict:
        """兼容旧接口：等同「重新测速」。"""
        self.autoSelectCdnNode()
        return {"ok": True, "rows": list(getattr(self, "_cdn_rows", [])),
                "best": self.cdnRegion, "error": ""}

    # ================================================================== 工坊 DNS
    # 和上面的「网络加速」是两件事：加速决定「连哪台机器」，
    # DNS 决定「用谁把域名解析成地址」。两边互不影响，用户要分开设置。
    @Property("QVariantList", notify=dnsChanged)
    def dnsModes(self) -> list:
        """给分段控件用的模式列表：[{value, label, active}]。"""
        mode = self.dnsMode
        return [{"value": value, "label": label, "active": value == mode}
                for value, label, _server in WDNS.DNS_MODES]

    @Property(str, notify=dnsChanged)
    def dnsMode(self) -> str:
        mode = str(self._cfg["workshop_dns_mode"] or WDNS.DEFAULT_MODE).strip().lower()
        return mode if mode in WDNS.MODE_VALUES else WDNS.DEFAULT_MODE

    @Property(str, notify=dnsChanged)
    def dnsCustom(self) -> str:
        return str(self._cfg["workshop_dns_custom"] or "")

    @Property(str, notify=dnsChanged)
    def dnsSummary(self) -> str:
        """单行状态：走的是哪家 DNS。自定义地址就是用户自己填的那个。"""
        mode = self.dnsMode
        if mode == "custom":
            addr = WDNS.valid_address(self.dnsCustom)
            return f"自定义 · {addr}" if addr else "自定义（地址还没填对）"
        return WDNS.mode_label(mode)

    @Slot(str)
    def setDnsMode(self, mode: str) -> None:
        v = str(mode or "").strip().lower()
        if v not in WDNS.MODE_VALUES or v == self.dnsMode:
            return
        if v == "custom" and not WDNS.valid_address(self.dnsCustom):
            # 切到自定义但地址还没填好：先切过去，解析暂时按系统走，界面上会提示
            self._cfg["workshop_dns_mode"] = v
            self._cfg.save()
            self._apply_workshop_dns()
            self.dnsChanged.emit()
            self.toast("自定义 DNS 还没填地址，解析暂时按系统走", "warn")
            return
        self._cfg["workshop_dns_mode"] = v
        self._cfg.save()
        self._apply_workshop_dns()
        self.dnsChanged.emit()
        self.toast(f"工坊解析已改为 {WDNS.mode_label(v)}", "ok")

    @Slot(str)
    def setDnsCustom(self, value: str) -> None:
        """自定义 DNS 地址：只收单个 IPv4 / IPv6。"""
        raw = str(value or "").strip()
        if not raw:
            self._cfg["workshop_dns_custom"] = ""
            self._cfg.save()
            self._apply_workshop_dns()
            self.dnsChanged.emit()
            return
        addr = WDNS.valid_address(raw)
        if not addr:
            self.toast("请填一个合法的 IPv4 或 IPv6 地址", "warn")
            return
        if addr == self.dnsCustom and self.dnsMode == "custom":
            return
        self._cfg["workshop_dns_custom"] = addr
        self._cfg["workshop_dns_mode"] = "custom"
        self._cfg.save()
        self._apply_workshop_dns()
        self.dnsChanged.emit()
        self.toast(f"工坊解析已改为自定义 DNS：{addr}", "ok")

    def _apply_workshop_dns(self) -> None:
        """把配置里的 DNS 方案装进解析器（空串 = 走系统解析）。"""
        try:
            WDNS.configure(WDNS.server_for(self.dnsMode, self.dnsCustom))
        except Exception as e:  # noqa: BLE001  装不上就退回系统解析，不能影响启动
            log(f"apply workshop dns failed: {e!r}")
            try:
                WDNS.configure("")
            except Exception:  # noqa: BLE001
                pass

    # ---------------------------------------------------------------- 翻译
    # 翻译现在是「创意工坊详情里点一下才翻」的手动动作，设置里那颗总开关已经撤了
    #（配置键留着，老配置文件照样能读）。这里恒为 True，只为了让旧调用方不炸。
    @Property(bool, notify=statusChanged)
    def translateEnabled(self) -> bool:
        return True

    @Slot(bool)
    def setTranslateEnabled(self, value: bool) -> None:  # noqa: ARG002
        """兼容旧接口：翻译改成手动之后这里不再拦人。"""
        self._cfg["translate_enabled"] = True
        self._cfg.save()
        self.statusChanged.emit()

    @Slot(str, result="QVariantMap")
    def translateText(self, text: str) -> dict:
        """同步翻译（给脚本/测试用；UI 请走 translateTextAsync）。"""
        if not (text or "").strip():
            return {"ok": False, "text": "", "error": "没有可翻译的简介"}
        return WN.translate(text)

    @Slot(str)
    def translateTextAsync(self, text: str) -> None:
        """异步翻译，结果走 translationReady 信号（不卡界面）。"""
        if not (text or "").strip():
            self.translationReady.emit({
                "ok": False, "text": "", "error": "这个 MOD 没有简介可以翻",
            })
            return
        if getattr(self, "_translating", False):
            return
        self._translating = True
        self._set_status("正在翻译…")

        def worker() -> None:
            try:
                res = WN.translate(text)
            except Exception as e:  # noqa: BLE001
                res = {"ok": False, "text": "", "error": f"翻译出错：{e}"}
            self._translating = False
            if res.get("ok"):
                self._set_status("翻译完成")
            else:
                self._set_status("翻译失败：" + (res.get("error") or ""))
            try:
                self.translationReady.emit(res)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    # ================================================================ 创意工坊「浏览」
    # 列表走公开只读中转（Steam 官方 QueryFiles 需要 publisher key，客户端拿不到），
    # 详情仍走官方 GetPublishedFileDetails。
    #
    # ★ 界面是「一直往下滚就继续加载」，所以这里不再有「第几页」的概念：
    #   browseMore() 每次把下一页**追加**到列表尾部，滚到底自动触发。
    #   切分类 / 搜索 / 换排序时会重置成第 1 页。
    @Property("QVariantList", notify=browseChanged)
    def browseItems(self) -> list:
        return list(getattr(self, "_browse_items", []))

    @Property("QVariantList", notify=browseChanged)
    def browseThumbs(self) -> list:
        """列表封面地址（已经按加速节点改写过的）。

        和 browseItems 分开暴露：items 只放业务字段，
        封面走这里，QML 里读起来更顺，也不会把带 IP 的 URL 混进数据模型。
        """
        return list(getattr(self, "_browse_thumbs", []))

    @Property(int, notify=browseChanged)
    def browseTotal(self) -> int:
        return int(getattr(self, "_browse_total", 0))

    @Property(int, notify=browseChanged)
    def browsePage(self) -> int:
        """已经加载到第几页（无限滚动里相当于「已加载页数」）。"""
        return int(getattr(self, "_browse_page", 1))

    @Property(str, notify=browseChanged)
    def browseQuery(self) -> str:
        return str(getattr(self, "_browse_query", ""))

    @Property(str, notify=browseChanged)
    def browseSort(self) -> str:
        return str(getattr(self, "_browse_sort", "trend"))

    @Property(str, notify=browseChanged)
    def browseKind(self) -> str:
        """mod=单件 MOD / collection=合集。"""
        return str(getattr(self, "_browse_kind", "mod"))

    @Property("QVariantList", notify=browseChanged)
    def browseTags(self) -> list:
        return list(getattr(self, "_browse_tags", []))

    @Property(str, notify=browseChanged)
    def browseError(self) -> str:
        return str(getattr(self, "_browse_error", ""))

    @Property(bool, notify=browseChanged)
    def browseLoading(self) -> bool:
        """正在拉第一页（整表清空重来）。"""
        return bool(getattr(self, "_browse_loading", False))

    @Property(bool, notify=browseChanged)
    def browseLoadingMore(self) -> bool:
        """正在追加下一页（列表还在，底部转圈）。"""
        return bool(getattr(self, "_browse_more", False))

    @Property(bool, notify=browseChanged)
    def browseDone(self) -> bool:
        """已经到底了，别再往下要了。"""
        return bool(getattr(self, "_browse_done", False))

    def _browse_reset_state(self) -> None:
        self._browse_items = []
        self._browse_thumbs = []
        self._browse_total = 0
        self._browse_page = 1
        self._browse_done = False

    def _browse_thumb_for(self, url: str) -> str:
        """封面地址：走本地代理，由代理按当前节点 IP 去取。

        为什么不是直接把域名换成节点 IP：QML 的 Image 没有自定义 Host/SNI
        的入口，域名换 IP 后 Qt 会拿证书去核对那个 IP，直接报证书不匹配。
        所以统一交给本地代理（见 imageproxy.py）。
        """
        raw = str(url or "").strip()
        if not raw:
            return raw
        if self.cdnMode == "off" and not self._cover_proxy.port:
            return raw
        wrapped = self._cover_proxy.wrap(raw)
        return wrapped or raw

    @Slot(str, result="QString")
    def coverUrl(self, url: str) -> str:
        """把一个工坊封面地址换成走本机代理的地址（合集成员列表里要用）。

        注意返回类型写 `QString` 而不是 `str`：QML 侧调 `str` 会报
        `Error: Unknown method return type: str`。
        """
        try:
            return self._browse_thumb_for(url)
        except Exception:  # noqa: BLE001
            return str(url or "")

    @Property(str, notify=statusChanged)
    def coverProxyPort(self) -> int:
        """封面代理端口（0 = 没起来，QML 侧不用关心）。"""
        return int(self._cover_proxy.port)

    @Slot(str)
    def requestWorkshopStats(self, wid: str) -> None:
        """异步补一次工坊统计数字（浏览 / 订阅 / 收藏 / 发布 / 更新）。

        这些字段只有 Steam 官方接口有（国内中转那份数据里没有），
        而且官方接口偶尔很慢 —— 所以单独一条后台路，点开详情先看内容，
        统计数字回来了再贴上去，绝不拖慢打开速度。
        """
        wid = str(wid or "").strip()
        if not wid.isdigit():
            return
        threading.Thread(target=self._stats_worker, args=(wid,), daemon=True).start()

    def _stats_worker(self, wid: str) -> None:
        try:
            info = WD.fetch_stats(wid=wid).get(wid) or {}
        except Exception as e:  # noqa: BLE001
            log(f"workshop stats failed: {e!r}")
            return
        if self._closing or not info.get("ok"):
            return
        views = int(info.get("views") or 0)
        subs = int(info.get("subs") or 0)
        favs = int(info.get("favs") or 0)
        created = int(info.get("created") or 0)
        updated = int(info.get("updated") or 0)
        self.workshopStatsChanged.emit({
            "id": wid,
            "views": views,
            "subs": subs,
            "favs": favs,
            "viewsText": f"{views:,}" if views else "",
            "subsText": f"{subs:,}" if subs else "",
            "favsText": f"{favs:,}" if favs else "",
            "createdText": fmt_ts(created, "%Y-%m-%d") if created else "",
            "updatedText": fmt_ts(updated, "%Y-%m-%d") if updated else "",
            "created": created,
            "updated": updated,
        })

    def _browse_prefetch(self, items: list) -> None:
        """后台预热这一页的封面缩略图。

        列表一到就先把图压好落盘，等 QML 真的渲染到那一格时，
        请求打到代理上是「本地命中」，滚动就不会一格一格地白。
        """
        if not self._cover_proxy.port:
            return
        urls = [it.get("preview") or "" for it in (items or [])]
        try:
            self._cover_proxy.prefetch(urls)
        except Exception as e:  # noqa: BLE001  预热失败不能影响列表
            log(f"cover prefetch failed: {e!r}")

    def _browse_kind_ok(self, item: dict) -> bool:
        """这一条该不该出现在当前列表里（单件 / 合集）。

        只认 fileType（= 官方的 file_type，合集是 2），**不要看 children**：
        Steam 会给一部分普通 MOD 也塞上 num_children，用它判会把正常单件
        MOD 当成合并在「单件 MOD」里藏起来（实测一页 20 条里有 4 条这种）。
        列表接口的 filetype 参数本身是准的，这里只是兜一道。
        """
        is_coll = int(item.get("fileType") or 0) == 2
        if self._browse_kind == "collection":
            return is_coll
        return not is_coll

    def _browse_apply(self, res: dict, append: bool, seq: int) -> None:
        """把一页结果并进列表（过期请求直接丢掉）。"""
        if seq != self._browse_seq:
            return
        if not res.get("ok"):
            if append:
                # 追加失败：保留已有内容，只在底部提示
                self._browse_more = False
                self._browse_error = res.get("error") or "加载更多失败"
            else:
                self._browse_items = []
                self._browse_thumbs = []
                self._browse_total = 0
                self._browse_error = res.get("error") or "拉取失败"
                self._set_status("拉取失败：" + self._browse_error)
            self.browseChanged.emit()
            return

        raw_items = list(res.get("items") or [])
        raw_count = len(raw_items)
        # ★ 接口的 filetype 过滤并不严：实测「单件」列表每页都混着 3~4 个合集
        #   （fileType=0 但 num_children>0）。界面上「单件 MOD」就该只有单件，
        #   所以这里再筛一遍。注意「到底了」的判断仍旧用**接口给的原始条数**：
        #   按筛完的条数判，一页被筛掉几条就会被误判成到底。
        page_items = [it for it in raw_items if self._browse_kind_ok(it)]
        thumbs = [self._browse_thumb_for(it.get("preview") or "")
                  for it in page_items]
        self._browse_prefetch(page_items)
        if append:
            seen = {str(it.get("id")) for it in self._browse_items}
            fresh, fresh_thumbs = [], []
            for it, thumb in zip(page_items, thumbs):
                if str(it.get("id")) in seen:
                    continue
                seen.add(str(it.get("id")))
                fresh.append(it)
                fresh_thumbs.append(thumb)
            self._browse_items = list(self._browse_items) + fresh
            self._browse_thumbs = list(self._browse_thumbs) + fresh_thumbs
        else:
            self._browse_items = page_items
            self._browse_thumbs = thumbs

        self._browse_total = int(res.get("total") or 0)
        self._browse_page = WN.normalize_page(res.get("page") or 1)
        self._browse_error = ""
        # 到底的判断：这一页空了、或者已经装满了总数、或者页数到上限
        loaded = len(self._browse_items)
        self._browse_done = (
            not raw_items
            or loaded >= self._browse_total
            or self._browse_page >= 1000
            or raw_count < 20
        )
        self._browse_more = False
        self._browse_loading = False
        kind_label = "合集" if self._browse_kind == "collection" else "单件"
        self._set_status(f"工坊 · {kind_label} · 已加载 {loaded} / "
                         f"{self._browse_total} 个")
        if append:
            self.browseAppended.emit()
        self.browseChanged.emit()

    def _browse_fetch(self, append: bool) -> None:
        seq = self._browse_seq
        q = self._browse_query
        p = self._browse_page if append else 1
        s = self._browse_sort
        k = self._browse_kind
        tags = list(self._browse_tags)

        def worker() -> None:
            try:
                res = WN.fetch_workshop_list(q, p, s, tags=tags, kind=k)
            except Exception as e:  # noqa: BLE001
                res = {"ok": False, "items": [], "total": 0,
                       "error": f"拉取列表出错：{e}"}
            try:
                self._browse_apply(res, append, seq)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    @Slot(str, str, str, "QVariantList")
    def browseFilter(self, query: str = "", sort: str = "trend",
                     kind: str = "mod", tags: list = None) -> None:
        """重新筛选：清空列表，从第 1 页开始拉。

        query / sort / kind（mod|collection）/ tags 一起生效，
        任何一项变了都要走这里，别单独调多项。
        """
        self._browse_seq += 1
        self._browse_query = str(query or "")
        self._browse_sort = WN.normalize_sort(sort)
        self._browse_kind = WN.normalize_kind(kind)
        self._browse_tags = WN.normalize_tags(tags)
        self._browse_loading = True
        self._browse_more = False
        self._browse_error = ""
        self._browse_reset_state()
        self.browseChanged.emit()
        self._set_status("正在拉取创意工坊列表…")
        self._browse_fetch(append=False)

    @Slot(str, int, str)
    def browseWorkshop(self, query: str = "", page: int = 1, sort: str = "trend") -> None:
        """兼容旧接口：重置筛选并拉第 1 页（page 参数现在只用于追加）。"""
        if int(page or 1) > 1:
            self._browse_page = WN.normalize_page(page) - 1
            self.browseMore()
            return
        self.browseFilter(query, sort, self.browseKind, self.browseTags)

    @Slot(result="QVariantMap")
    def browseMore(self) -> dict:
        """滚到底时追加下一页。已经在拉 / 已经到底就什么都不做。"""
        if getattr(self, "_browse_loading", False) or \
                getattr(self, "_browse_more", False) or \
                getattr(self, "_browse_done", False):
            return {"ok": False, "done": self.browseDone,
                    "page": self.browsePage}
        self._browse_more = True
        self._browse_page = self.browsePage + 1
        self.browseChanged.emit()
        self._browse_fetch(append=True)
        return {"ok": True, "page": self.browsePage}

    @Slot(result="QVariantMap")
    def browseNextPage(self) -> dict:
        """兼容旧接口：等同「加载更多」。"""
        return self.browseMore()

    @Slot(result="QVariantMap")
    def browsePrevPage(self) -> dict:
        """旧接口留个空实现：无限滚动没有「上一页」。"""
        return {"ok": False, "page": self.browsePage,
                "error": "列表是一直往下加载的，没有上一页"}

    @Slot(str)
    def browseSetSort(self, sort: str) -> None:
        self.browseFilter(self.browseQuery, sort, self.browseKind,
                          self.browseTags)

    @Slot(str)
    def browseSetKind(self, kind: str) -> None:
        self.browseFilter(self.browseQuery, self.browseSort, kind,
                          self.browseTags)

    @Slot("QVariantList")
    def browseSetTags(self, tags: list) -> None:
        self.browseFilter(self.browseQuery, self.browseSort, self.browseKind,
                          tags)

    @Slot(str)
    def browseToggleTag(self, tag: str) -> None:
        """点一下标签：没选就加上，选了就去掉（多标签是 AND 关系）。"""
        want = str(tag or "").strip()
        if not want:
            return
        current = list(self._browse_tags)
        low = [t.lower() for t in current]
        if want.lower() in low:
            current = [t for t in current if t.lower() != want.lower()]
        else:
            current.append(want)
        self.browseSetTags(current)

    # ---------------------------------------------------------------- 稍后看
    @Property("QVariantList", notify=browseChanged)
    def laterItems(self) -> list:
        """「稍后看」里存的工坊条目。

        配置里只存 ID，标题/封面按三个来源补：①当前浏览列表里已经加载过的那条
        ②modmeta.json 里的缓存（以前下载/解析过就认得）③都没有就写「工坊 <ID>」
        并打个 `missing` 标记 —— 界面据此显示成一条待补齐的占位，而不是空白一行。
        """
        ids = [str(x) for x in (self._cfg["workshop_later"] or [])]
        known = {str(it.get("id")): it for it in getattr(self, "_browse_items", [])}
        by_id_thumb = {}
        for it, thumb in zip(getattr(self, "_browse_items", []),
                             getattr(self, "_browse_thumbs", [])):
            by_id_thumb[str(it.get("id"))] = thumb
        out = []
        for wid in ids:
            it = known.get(wid)
            if it:
                item = dict(it)
                item["preview"] = by_id_thumb.get(wid) or it.get("preview") or ""
                item["missing"] = False
                out.append(item)
                continue
            meta = None
            try:
                meta = self._wsc.cached(wid)
            except Exception:  # noqa: BLE001
                meta = None
            if meta:
                preview = str(meta.get("preview") or "")
                out.append({
                    "id": wid,
                    "title": str(meta.get("title") or ("工坊 " + wid)),
                    "preview": self._browse_thumb_for(preview),
                    "subs": 0,
                    "children": int(meta.get("children") or 0),
                    "fileType": 0,
                    "missing": False,
                })
            else:
                out.append({"id": wid, "title": "工坊 " + wid, "preview": "",
                            "subs": 0, "children": 0, "fileType": 0, "missing": True})
        return out

    @Property(int, notify=browseChanged)
    def laterCount(self) -> int:
        return len(self._cfg["workshop_later"] or [])

    @Slot(str, result="bool")
    def isLater(self, wid: str) -> bool:
        return str(wid or "") in [str(x) for x in (self._cfg["workshop_later"] or [])]

    @Slot(str, result="bool")
    def toggleLater(self, wid: str) -> bool:
        """收藏 / 取消「稍后看」，返回操作后是否在列表里。"""
        key = str(wid or "").strip()
        if not key:
            return False
        ids = [str(x) for x in (self._cfg["workshop_later"] or [])]
        if key in ids:
            ids = [x for x in ids if x != key]
            on = False
        else:
            ids.insert(0, key)
            on = True
        # 最多记 200 个，别让配置文件无限长
        self._cfg["workshop_later"] = ids[:200]
        self._cfg.save()
        self.browseChanged.emit()
        self.toast("已加入稍后看" if on else "已从稍后看移除",
                   "ok" if on else "info")
        return on

    @Slot()
    def clearLater(self) -> None:
        if not (self._cfg["workshop_later"] or []):
            return
        self._cfg["workshop_later"] = []
        self._cfg.save()
        self.browseChanged.emit()
        self.toast("已清空稍后看", "info")

    # ================================================================ 工具
    def shutdown(self) -> None:
        """退出前调用：让后台线程别再碰已经快被销毁的模型。

        否则扫描线程回来时会对已经析构的 ModListModel 调
        beginResetModel()，报
        RuntimeError: libshiboken: Internal C++ object (ModListModel) already deleted
        """
        self._closing = True
        try:
            self._cover_proxy.stop()
        except Exception:  # noqa: BLE001
            pass

    def _set_busy(self, value: bool) -> None:
        if self._closing:
            return
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit()

    def _set_status(self, text: str) -> None:
        if self._closing:
            return
        self._status = text
        self.statusChanged.emit()

    @Slot(str, str)
    def toast(self, text: str, level: str = "info") -> None:
        """动作型提示：QML 侧弹一个浮层然后淡出。

        level 约定（颜色由 QML 决定）：
            info  蓝  一般信息
            ok    绿  成功（导入完成、已复制）
            warn  黄  可挽回的警告（进了回收站、被占用跳过）
            error 红  失败 / 不可挽回（永久删除、删除失败）
        """
        if self._closing or not text:
            return
        self.toastRequested.emit(text, level or "info")
