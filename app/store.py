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

"""配置与视频库的持久化（纯 JSON，方便手改和备份）."""
from __future__ import annotations

import json
import os
import shutil
from typing import Any

from .util import DATA_DIR, now_ts

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LIBRARY_PATH = os.path.join(DATA_DIR, "library.json")
LIBRARY_BAK = os.path.join(DATA_DIR, "library.bak.json")

DEFAULT_CONFIG: dict[str, Any] = {
    # 主关键词保留旧字段名，便于老配置平滑迁移
    "keyword": "求生之路2公开",
    # 多关键词：新字段。老配置里没有就用 keyword 初始化
    "keywords": ["求生之路2公开", "求生之路2替换"],
    "order": "pubdate",
    "max_pages": 2,
    "interval_min": 10,
    # 视频库上限：0 = 不限；超过就按发布时间从旧到新清理。
    # 可选 50 / 100 / 200 / 500 / 1000 / 0（不限）
    "video_limit": 0,
    "notify_toast": True,
    "notify_balloon": True,
    "notify_sound": True,
    # 提示音效：存 sounds 目录里的文件名（默认 bbb.mp3，空串=用系统提示音）
    "alert_sound": "bbb.mp3",
    "show_only_new": False,
    # 外观模式："system"（跟随系统，默认）/ "dark"（夜间）/ "light"（日间）
    "appearance": "system",
    "theme": "dark",
    "font_scale": 1.0,
    # 自定义背景图：只认 backgrounds/background.* 这一个文件（空串 = 没设置），
    # bg_opacity 是 0-100 的透明度（越低越看不见），bg_enabled 是「用不用背景图」的开关
    "bg_image": "",
    "bg_opacity": 35,
    "bg_enabled": True,
    # 界面主题色（#RRGGBB）：设置面板里的 RGB 滑块改它，全局强调色跟着变
    "ui_accent": "#FF4D57",
    "tray_on_close": True,
    # 删 MOD 走回收站（默认）还是直接删掉
    "delete_to_recycle": True,
    # 创意工坊导入时的并发下载线程数（1-16，默认 4）。
    "download_threads": 4,
    # ---- MOD 管理器的筛选 / 排序（跨重启记住）----
    # 以前这些只活在内存里，关掉再开就回默认，每次都要重设一遍。
    # 键名统一加 mod_ 前缀，和别的配置项区分开。
    "mod_filter": "",
    "mod_min_mb": 0.0,
    "mod_max_mb": 0.0,
    "mod_status_filter": 0,
    "mod_category": "",
    "mod_sort_mode": 0,
    "mod_import_days": 0,
    "mod_import_from": "",
    "mod_import_to": "",
    "mod_tab": 0,
    # 创意工坊 CDN 加速：国内 cdn.steamusercontent.com 常解析到很远的节点。
    #   workshop_cdn_mode   auto=自动优选最快节点 / manual=手动指定 / off=关闭
    #   workshop_cdn_region 当前节点地名（auto 时由测速结果写入）
    #   workshop_cdn_ip     要连的地址（auto 时是测速选出来的，manual 时是用户自己填的）
    "workshop_cdn_mode": "auto",
    "workshop_cdn_region": "",
    "workshop_cdn_ip": "",
    "workshop_cdn_ms": 0,
    # 工坊 DNS：和上面的「网络加速」是**两件独立的事**——
    # 加速管「连哪台机器」，DNS 管「用谁把域名解析成 IP」。
    #   workshop_dns_mode   dnspod=腾讯 / alidns=阿里 / custom=自定义 / system=系统
    #   workshop_dns_custom 自定义 DNS 地址（IPv4 或 IPv6）
    # 工坊 DNS：和上面的「网络加速」是**两件独立的事**——
    "workshop_dns_mode": "dnspod",
    "workshop_dns_custom": "",
    # Steam Web API Key（用户自己的）。
    # ★ 只有「工坊列表 / 搜索」需要它：Steam 的 QueryFiles 接口强制要 key，
    #   不带 key 直接 403。详情、下载、合集展开都不需要。
    #   存在本地 config.json，不进仓库、不上传。
    "steam_api_key": "",
    # 创意工坊「稍后看」：只存工坊 ID 列表，详情按需再拉
    "workshop_later": [],
    # 收藏的服务器：只存地址和备注名，实时状态（人数/地图/模式）查询时再生
    "servers": [],
    "servers_sort": "players",
    # 手动改过的合集名：{addr: 组名}。自动识别不准时用户可以自己命名，
    # 存这里而不是存到每台服务器的 name 上，是因为它描述的是「整组」。
    "server_group_names": {},
    # 剪贴板里发现服务器地址时问一句「要不要导入」。默认开 —— 这是这次特意加的；
    # 嫌烦可以在设置里关掉（关掉后不再读剪贴板）。
    "clipboard_servers": True,
    # 用户协议：首次启动必须读完并勾选「我已知悉」才能用。
    # 存成版本号而不是布尔：「协议内容改了要重新同意」时只要把这里的
    # 期望版本 +1，老用户的 False 自然失效，不用另加迁移逻辑。
    "agreement_version": 0,
    # ---- B 站登录（用于给创作者三连）----
    # 只存三个必要 cookie（SESSDATA / bili_jct / DedeUserID）+ 昵称头像缓存。
    # 全在本地 config.json，不上传任何地方；失效了重新扫码登录即可。
    "bili_credentials": {},
    # 三连里默认勾选这三项；关注是长期动作，默认关掉
    "bili_triple_like": True,
    "bili_triple_coin": True,
    "bili_triple_fav": True,
    "bili_triple_follow": False,
    # 翻译 MOD 描述用的接口（目前只有免 key 的公开接口）
    "translate_enabled": True,
    # 软件更新：每次打开软件时自动检查一次 GitHub Releases 上的新版本。
    # 默认关 —— 检查更新要走网络，不想每次启动都发请求的可以保持关闭，
    # 需要时到「关于」里手动点「检查更新」。
    "auto_check_update": False,
    # 提取到网盘链接时自动三连（点赞/投币/收藏，按上面那几个开关）。
    # 默认关：这是「顺手替用户做写操作」，必须用户自己打开才生效。
    "bili_auto_triple_on_link": False,
    # 播放器音量（0-100）与静音状态，跨会话记住
    "player_volume": 80,
    "player_muted": False,
    "window": {"w": 1280, "h": 860, "x": -1, "y": -1},
}

# 关键词数量上限，防止误加一堆导致请求过多
MAX_KEYWORDS = 8
KEYWORD_MAX_LEN = 40


def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_json(path: str, fallback: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return fallback


class Config:
    def __init__(self) -> None:
        self.data: dict[str, Any] = dict(DEFAULT_CONFIG)
        existed = os.path.exists(CONFIG_PATH)
        self.load()
        if not existed:
            self.save()  # 首次运行把默认配置落盘，方便用户直接改文件

    def load(self) -> None:
        saved = _read_json(CONFIG_PATH, {})
        if isinstance(saved, dict):
            for k, v in DEFAULT_CONFIG.items():
                if k not in saved:
                    self.data[k] = v
                elif isinstance(v, dict) and isinstance(saved.get(k), dict):
                    merged = dict(v)
                    merged.update(saved[k])
                    self.data[k] = merged
                else:
                    self.data[k] = saved[k]

            # 老配置迁移：只有 keyword、没有 keywords 的，用 keyword + 默认新词生成列表
            if "keywords" not in saved:
                old = str(saved.get("keyword") or DEFAULT_CONFIG["keyword"])
                initial = [old]
                for extra in DEFAULT_CONFIG["keywords"]:
                    if extra.lower() != old.lower():
                        initial.append(extra)
                self.data["keywords"] = initial
            self.data["keywords"] = self.normalize_keywords(self.data.get("keywords"))
            # 保持 keyword = 第一个关键词，兼容旧代码/UI
            if self.data["keywords"]:
                self.data["keyword"] = self.data["keywords"][0]

    @staticmethod
    def normalize_keywords(values: Any) -> list[str]:
        """清洗关键词列表：去空、去重、限长、限数量。"""
        out: list[str] = []
        seen: set[str] = set()
        if isinstance(values, str):
            values = [values]
        # 也接受换行/逗号分隔的一整串
        if isinstance(values, (list, tuple)):
            for raw in values:
                if not isinstance(raw, str):
                    continue
                for part in raw.replace("\n", ",").replace("，", ",").split(","):
                    kw = part.strip()[:KEYWORD_MAX_LEN]
                    if not kw:
                        continue
                    key = kw.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(kw)
                    if len(out) >= MAX_KEYWORDS:
                        return out
        return out or [DEFAULT_CONFIG["keyword"]]

    def keywords(self) -> list[str]:
        return self.normalize_keywords(self.data.get("keywords"))

    def set_keywords(self, values: Any) -> list[str]:
        kws = self.normalize_keywords(values)
        self.data["keywords"] = kws
        self.data["keyword"] = kws[0] if kws else DEFAULT_CONFIG["keyword"]
        self.save()
        return kws

    def save(self) -> None:
        try:
            _atomic_write(CONFIG_PATH, self.data)
        except OSError:
            pass

    def __getitem__(self, key: str) -> Any:
        return self.data.get(key, DEFAULT_CONFIG.get(key))

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def update(self, **kwargs: Any) -> None:
        self.data.update(kwargs)
        self.save()


class Library:
    """已见过的视频集合 + 是否已读状态."""

    def __init__(self) -> None:
        self.videos: dict[str, dict] = {}
        self.meta: dict[str, Any] = {"first_run": True, "last_check": 0, "total_checks": 0}
        self.load()

    # ------------------------------------------------------------ 读写
    def load(self) -> None:
        raw = _read_json(LIBRARY_PATH, None)
        if not isinstance(raw, dict):
            raw = _read_json(LIBRARY_BAK, {}) or {}
        self.videos = raw.get("videos") or {}
        self.meta.update(raw.get("meta") or {})

    def save(self) -> None:
        payload = {"meta": self.meta, "videos": self.videos}
        try:
            if os.path.exists(LIBRARY_PATH):
                shutil.copyfile(LIBRARY_PATH, LIBRARY_BAK)
            _atomic_write(LIBRARY_PATH, payload)
        except OSError:
            pass

    # ------------------------------------------------------------ 查询
    def has(self, bvid: str) -> bool:
        return bvid in self.videos

    def new_items(self) -> list[dict]:
        items = [v for v in self.videos.values() if v.get("is_new")]
        items.sort(key=lambda v: v.get("pubdate") or 0, reverse=True)
        return items

    def new_count(self) -> int:
        return sum(1 for v in self.videos.values() if v.get("is_new"))

    def all_items(self) -> list[dict]:
        items = list(self.videos.values())
        items.sort(key=lambda v: v.get("pubdate") or 0, reverse=True)
        return items

    # ------------------------------------------------------------ 合并
    def merge_scan(self, items: list[dict]) -> list[dict]:
        """把一次扫描结果并入库，返回本次新发现的视频。

        items 里同一条视频可能因为多个关键词被搜到多次，这里按 bvid 去重，
        并把命中的关键词合并到同一个记录的 _keywords 字段里。
        """
        discovered: list[dict] = []
        seen: set[str] = set()

        for it in items:
            bvid = it.get("bvid") or ""
            if not bvid or bvid in seen:
                continue
            seen.add(bvid)

            incoming_kw = list(it.get("_keywords") or [])
            old = self.videos.get(bvid)
            if old is None:
                rec = dict(it)
                rec["is_new"] = True
                rec["discovered_at"] = now_ts()
                rec["_keywords"] = incoming_kw
                self.videos[bvid] = rec
                discovered.append(rec)
            else:
                # 老视频只补全缺失字段（比如上次没抓到简介），不改已读标记
                for key in ("desc", "cover", "duration", "author"):
                    if not old.get(key) and it.get(key):
                        old[key] = it[key]
                if not old.get("detail_loaded") and it.get("detail_loaded"):
                    old["detail_loaded"] = True
                    old["desc"] = it.get("desc") or old.get("desc")
                # 合并多关键词命中记录
                if incoming_kw:
                    exist_kw = list(old.get("_keywords") or [])
                    for kw in incoming_kw:
                        if kw not in exist_kw:
                            exist_kw.append(kw)
                    old["_keywords"] = exist_kw
        self.meta["last_check"] = now_ts()
        self.meta["total_checks"] = int(self.meta.get("total_checks") or 0) + 1
        self._bump_daily_check()
        return discovered

    def _bump_daily_check(self) -> None:
        """累计「今天扫了几次」。

        以前界面上显示的是 total_checks（历史总次数），只会越来越大、越来越没意义。
        现在按自然日算：换了一天就归零，只显示今天扫了多少次。
        """
        import datetime as _dt

        today = _dt.date.today().isoformat()
        if self.meta.get("checks_day") != today:
            self.meta["checks_day"] = today
            self.meta["checks_today"] = 0
        self.meta["checks_today"] = int(self.meta.get("checks_today") or 0) + 1

    def checks_today(self) -> int:
        """今日扫描次数（跨天自动视为 0）。"""
        import datetime as _dt

        if self.meta.get("checks_day") != _dt.date.today().isoformat():
            return 0
        try:
            return int(self.meta.get("checks_today") or 0)
        except (TypeError, ValueError):
            return 0

    def update_item(self, bvid: str, **fields: Any) -> None:
        rec = self.videos.get(bvid)
        if not rec:
            return
        rec.update(fields)
        self.save()

    def mark_seen(self, bvid: str) -> None:
        rec = self.videos.get(bvid)
        if rec and rec.get("is_new"):
            rec["is_new"] = False
            self.save()

    def mark_all_seen(self) -> None:
        for rec in self.videos.values():
            rec["is_new"] = False
        self.save()

    def remove(self, bvid: str) -> None:
        if self.videos.pop(bvid, None) is not None:
            self.save()

    def clear_all(self) -> None:
        self.videos = {}
        self.save()

    # ------------------------------------------------------------ 容量上限
    def trim(self, limit: int) -> list[str]:
        """把库裁到最多 ``limit`` 条，返回被删掉的 bvid 列表。

        裁剪规则（**保新删旧**）：
          1. 先按 ``pubdate``（发布时间）从新到旧排，超出的尾部删掉
          2. 「未读」的优先保留 —— 用户还没看的新视频不该被自动清掉，
             所以排序键是 ``(is_new, pubdate)``：未读的整体排在前面

        `limit <= 0` 表示不限，直接返回空列表（什么都不删）。
        """
        limit = int(limit or 0)
        if limit <= 0:
            return []
        total = len(self.videos)
        if total <= limit:
            return []

        def sort_key(item):
            bvid, rec = item
            return (
                1 if rec.get("is_new") else 0,       # 未读优先保留
                int(rec.get("pubdate") or 0),
                int(rec.get("discovered_at") or 0),
            )

        ordered = sorted(self.videos.items(), key=sort_key, reverse=True)
        keep = dict(ordered[:limit])
        removed = [bvid for bvid, _ in ordered[limit:]]
        self.videos = keep
        return removed

    # ------------------------------------------------------------ 首启
    def first_run(self) -> bool:
        return bool(self.meta.get("first_run", True))

    def finish_first_run(self) -> None:
        self.meta["first_run"] = False
        self.save()
