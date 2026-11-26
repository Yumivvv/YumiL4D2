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

"""统一下载管理：所有下载都排进这一个队列，界面只看这一份数据。

为什么要有它：以前 MOD 下载的结果只体现在两处 —— 状态栏一行字，和结束时的
一个 toast。下了几个、哪个失败了、每个到百分之几，全都看不到；想取消也没有口子
（`WorkshopDownloader.cancel()` 其实早就有，但界面根本调不到）。
视频下载更彻底：`bili.download_stream()` 写好了却从来没被调用过。

这里把「下载」抽象成一个**任务**（`:class:`DownloadTask`），不管底层是工坊 CDN、
B站视频流还是别的什么，界面都只认这几个字段：

    id / kind / title / subtitle / dest 
    status / done / total / speed / error / addedAt / finishedAt

状态流转（都只能往前走，不会倒退）：

    排队中 queued → 下载中 running → 完成 done
                                  ├→ 失败 failed
                                  └→ 已取消 canceled

「取消」是协作式的：任务自己起线程跑，线程在每个 chunk 回调查一下
``self._cancel_flags[tid]``，看到标记就抛 :class:`Cancelled` 收尾。
不这么做的话，点取消要等到整个 300 MB 下完才生效。

持久化只存「结果」，不存进行中的任务 —— 进程重启后重新开始比假装续传诚实。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from . import util
from . import workshop_dl as WD

DOWNLOAD_LOG = os.path.join(util.LOG_DIR, "downloads.log")

# 能装 MOD 的压缩包后缀。蓝奏云上下来的基本就是这三种。
ARCHIVE_EXTS = (".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz")
# 压缩包里的封面图（跟着 .vpk 同名的一起导，卡片才有图）
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def _log(text: str) -> None:
    try:
        os.makedirs(util.LOG_DIR, exist_ok=True)
        with open(DOWNLOAD_LOG, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(text) + "\n")
    except OSError:
        pass


# 状态常量（界面直接拿字符串比对，别用数字，日志里也好看）
QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELED = "canceled"

_ACTIVE = (QUEUED, RUNNING)


class Cancelled(Exception):
    """任务被别人取消了 —— 只用来跳出下载循环，不会冒到界面上。"""


def human_size(n: Any) -> str:
    """字节数转人话。总大小未知时传 0，显示 ``—``。

    ★ 算法在 `util.human_size`（全项目唯一实现），这里只是固定
      「0 显示成 `—`」—— 下载页需要区分「未知」和「真的是 0 字节」。
      以前这里有一份完整的重复实现，改一次要改五六个地方。
    """
    return util.human_size(n, zero="—")


def human_speed(bps: Any) -> str:
    try:
        value = float(bps or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return ""
    return human_size(value) + "/s"


def _is_archive(path: str) -> bool:
    return str(path or "").lower().endswith(ARCHIVE_EXTS)


def _archive_members(path: str) -> tuple[list[str], str]:
    """列出压缩包里的文件名（不解压）。返回 ``(名字列表, 错误)``。

    zip 用标准库（快、准）；其它格式（7z / rar / tar）用 Windows 自带的
    `tar.exe`（bsdtar + libarchive，原生认这些格式，不用装 7-Zip）。
    """
    low = str(path or "").lower()
    if low.endswith(".zip"):
        try:
            with zipfile.ZipFile(path, "r") as zf:
                return [n for n in zf.namelist() if not n.endswith("/")], ""
        except (zipfile.BadZipFile, OSError) as e:
            return [], f"压缩包打不开：{e}"
    # 其它格式走 bsdtar
    tar = shutil.which("tar")
    if not tar:
        return [], "系统没有可用的解压工具（缺 tar.exe）"
    try:
        out = subprocess.run(
            [tar, "-t", "-f", path],
            capture_output=True, timeout=60,
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


def _scan_archive(path: str) -> dict:
    """看压缩包里有没有 MOD。

    返回 ``{isArchive, mods, images, names, error}``：
      * ``mods``   .vpk 的个数
      * ``images`` 封面图个数
      * ``names``  最多 5 个 .vpk 的名字（给界面预览「会用哪些」）
    """
    res = {"isArchive": False, "mods": 0, "images": 0, "names": [], "error": ""}
    if not _is_archive(path):
        res["error"] = "不是压缩包"
        return res
    names, err = _archive_members(path)
    if err:
        res["error"] = err
        return res
    res["isArchive"] = True
    vpks = [n for n in names if n.lower().endswith(".vpk")]
    # 只数「和某个 .vpk 同名」的图片 —— 包里常有一堆截图/无关图，
    # 全算进来会让提示写成「有 20 张封面」，导入进去却没有，属于骗人。
    stems = {os.path.splitext(os.path.basename(n))[0].lower() for n in vpks}
    imgs = [n for n in names
            if n.lower().endswith(IMAGE_EXTS)
            and os.path.splitext(os.path.basename(n))[0].lower() in stems]
    res["mods"] = len(vpks)
    res["images"] = len(imgs)
    res["names"] = [os.path.basename(n) for n in vpks[:5]]
    return res


def _extract_to(path: str, dest: str) -> dict:
    """把压缩包解到 ``dest``，返回 ``{ok, error}``。"""
    os.makedirs(dest, exist_ok=True)
    low = str(path or "").lower()
    if low.endswith(".zip"):
        try:
            with zipfile.ZipFile(path, "r") as zf:
                # 防 zip 路径穿越（../../xxx）
                for member in zf.namelist():
                    target = os.path.abspath(os.path.join(dest, member))
                    if not target.startswith(os.path.abspath(dest) + os.sep) \
                            and target != os.path.abspath(dest):
                        continue
                    zf.extract(member, dest)
            return {"ok": True, "error": ""}
        except (zipfile.BadZipFile, OSError) as e:
            return {"ok": False, "error": f"解压失败：{e}"}

    tar = shutil.which("tar")
    if not tar:
        return {"ok": False, "error": "系统没有可用的解压工具（缺 tar.exe）"}
    try:
        out = subprocess.run(
            [tar, "-x", "-f", path, "-C", dest],
            capture_output=True, timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"解压失败：{e}"}
    if out.returncode != 0:
        msg = (out.stderr or b"").decode("utf-8", "replace").strip()
        return {"ok": False, "error": f"解压失败：{msg[:100]}"}
    return {"ok": True, "error": ""}


def _collect_importable(root: str) -> list[str]:
    """从解压出来的目录里挑出该导入的文件：.vpk + 同名封面图。

    只导 .vpk 和「和某个 .vpk 同名的图」，其它（说明.txt、截图、子目录里的
    无关图片）都不碰 —— 不然 addons 里会多出一堆垃圾。
    """
    out: list[str] = []
    stems: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".vpk"):
                out.append(os.path.join(dirpath, name))
                stems.add(os.path.splitext(name)[0].lower())
    # 再走一遍找同名封面
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            stem, ext = os.path.splitext(name)
            if ext.lower() in IMAGE_EXTS and stem.lower() in stems:
                out.append(os.path.join(dirpath, name))
    return out


class DownloadTask:
    """一条下载任务。字段改动由 :class:`DownloadManager` 负责广播。"""

    __slots__ = (
        "id", "kind", "title", "subtitle", "dest", "status", "done", "total",
        "speed", "error", "addedAt", "finishedAt", "payload", "_last_bytes",
        "_last_time", "cancel",
    )

    def __init__(self, kind: str, title: str, dest: str = "", subtitle: str = "",
                 payload: dict | None = None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind                  # "mod" / "video" / ...
        self.title = title
        self.subtitle = subtitle
        self.dest = dest
        self.status = QUEUED
        self.done = 0
        self.total = 0
        self.speed = 0.0
        self.error = ""
        self.addedAt = time.time()
        self.finishedAt = 0.0
        self.payload = payload or {}
        self._last_bytes = 0
        self._last_time = time.time()
        self.cancel = False

    # ------------------------------------------------------------ 派生值
    @property
    def percent(self) -> int:
        if self.total > 0:
            return max(0, min(100, int(self.done * 100 / self.total)))
        return 0

    @property
    def active(self) -> bool:
        return self.status in _ACTIVE

    def to_dict(self) -> dict:
        # `isArchive` 让界面知道这颗任务下的是压缩包 —— 完成之后可以显示
        # 「导入 MOD」按钮。这里只按扩展名判断（很便宜）；真正有几个 .vpk
        # 由 `inspectTaskArchive()` 去读（那要打开压缩包，别在每次刷新时都做）。
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "dest": self.dest,
            "status": self.status,
            "done": int(self.done),
            "total": int(self.total),
            "percent": self.percent,
            "doneText": human_size(self.done),
            "totalText": human_size(self.total),
            "speed": self.speed,
            "speedText": human_speed(self.speed) if self.status == RUNNING else "",
            "error": self.error,
            "active": self.active,
            "isArchive": bool(self.status == DONE and _is_archive(self.dest)),
            "addedAt": self.addedAt,
            "finishedAt": self.finishedAt,
        }

    def record(self) -> dict:
        """落盘用的精简记录（结果只存这几个字段）。"""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "dest": self.dest,
            "status": self.status,
            "total": int(self.total),
            "error": self.error,
            "addedAt": self.addedAt,
            "finishedAt": self.finishedAt,
        }


class DownloadManager(QObject):
    """下载队列。所有下载都从这里走，界面只读它。

    线程模型：每个任务一条后台线程；进度回调用 ``Qt.QueuedConnection`` 的
    ``_tick`` 信号送回主线程再改数据结构，避免后台线程直接碰 QObject。
    """

    downloadsChanged = Signal()
    toastRequested = Signal(str, str)       # 和 Core.toastRequested 同形
    _tick = Signal(str)                     # 内部：某个任务有进度更新
    _settled = Signal(str)                  # 内部：某个任务结束（成功/失败/取消）

    MAX_HISTORY = 60                        # 已结束的任务最多留这么多条

    def __init__(self, core) -> None:
        super().__init__(core)
        self.core = core
        # 配置：下载目录存在这里（`download_dir`）。和 ModManager 共用同一份
        # Config 对象，避免两处各持一份、改了一边另一边看不到。
        cfg = getattr(core, "config", None)
        if cfg is None:
            from .store import Config
            cfg = Config()
        self._cfg = cfg
        self._tasks: dict[str, DownloadTask] = {}
        self._order: list[str] = []         # 显示顺序：新的在前
        self._lock = threading.Lock()
        self._closed = False
        # 「先不搬」标记：这次运行内不再提示迁移（不改配置，下次开还会问）
        self._migrate_dismissed = False
        self._log_path = DOWNLOAD_LOG
        self._tick.connect(self._on_tick)
        self._settled.connect(self._on_settled)

    # ------------------------------------------------------------ 读写
    def _sorted(self) -> list[DownloadTask]:
        # 进行中的永远在最上面，其余按加入时间倒序
        active = [self._tasks[i] for i in self._order
                  if i in self._tasks and self._tasks[i].active]
        rest = [self._tasks[i] for i in self._order
                if i in self._tasks and not self._tasks[i].active]
        active.sort(key=lambda t: t.addedAt)
        rest.sort(key=lambda t: -t.addedAt)
        return active + rest

    @Property("QVariantList", notify=downloadsChanged)
    def tasks(self) -> list:
        with self._lock:
            return [t.to_dict() for t in self._sorted()]

    @Property(int, notify=downloadsChanged)
    def activeCount(self) -> int:
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.active)

    @Property(int, notify=downloadsChanged)
    def totalCount(self) -> int:
        with self._lock:
            return len(self._tasks)

    @Property(bool, notify=downloadsChanged)
    def busy(self) -> bool:
        return self.activeCount > 0

    @Property(str, notify=downloadsChanged)
    def summaryText(self) -> str:
        """侧栏 / 页头那句「2 个下载中，共 5 个」。"""
        with self._lock:
            rows = list(self._tasks.values())
        active = sum(1 for t in rows if t.active)
        done = sum(1 for t in rows if t.status == DONE)
        failed = sum(1 for t in rows if t.status == FAILED)
        if not rows:
            return "还没有下载"
        parts: list[str] = []
        if active:
            parts.append(f"{active} 个进行中")
        if done:
            parts.append(f"{done} 个已完成")
        if failed:
            parts.append(f"{failed} 个失败")
        if not parts:
            parts.append(f"共 {len(rows)} 个")
        return "，".join(parts)

    def _emit(self, signal, *args) -> None:
        """关窗收尾期间别 emit（会撞上 Signal source has been deleted）。"""
        if self._closed:
            return
        try:
            signal.emit(*args)
        except RuntimeError:
            self._closed = True

    def _changed(self) -> None:
        self._emit(self.downloadsChanged)

    def _toast(self, text: str, level: str = "info") -> None:
        if not text or self._closed:
            return
        try:
            self.toastRequested.emit(text, level or "info")
        except RuntimeError:
            self._closed = True

    # ------------------------------------------------------------ 建任务
    def _add(self, task: DownloadTask) -> DownloadTask:
        with self._lock:
            self._tasks[task.id] = task
            self._order.insert(0, task.id)
            self._trim_locked()
        return task

    def _trim_locked(self) -> None:
        """已结束的留太多会拖慢列表，掐掉最老的。调用方要持锁。

        注意：**不能只在 `_add` 里调**。任务是在 `_run` 收尾时才变成「已结束」的，
        如果只在加入时裁，最后一个刚结束的任务会永远多留一条（实测差一）。
        所以 `_on_settled` 里也要调一次。
        """
        finished = [i for i in self._order
                    if i in self._tasks and not self._tasks[i].active]
        if len(finished) <= self.MAX_HISTORY:
            return
        for tid in finished[self.MAX_HISTORY:]:
            self._tasks.pop(tid, None)
            try:
                self._order.remove(tid)
            except ValueError:
                pass

    # ------------------------------------------------------------ 跑任务
    def _run(self, task: DownloadTask,
             worker: Callable[[DownloadTask], dict]) -> None:
        """在后台线程跑 ``worker(task)``，把异常统一翻译成 failed。"""

        def body() -> None:
            with self._lock:
                if task.cancel:
                    task.status = CANCELED
                    task.finishedAt = time.time()
                    self._emit(self._settled, task.id)
                    return
                task.status = RUNNING
                task._last_time = time.time()
            self._changed()

            try:
                res = worker(task) or {}
            except Cancelled:
                with self._lock:
                    task.status = CANCELED
                    task.finishedAt = time.time()
                    task.speed = 0.0
                _log(f"{task.kind} {task.id} canceled: {task.title}")
                self._emit(self._settled, task.id)
                return
            except Exception as exc:            # noqa: BLE001 - 任何异常都不该炸界面
                res = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}

            with self._lock:
                if task.cancel and task.status == RUNNING:
                    # 用户在收尾的当口点了取消：按取消算
                    task.status = CANCELED
                elif res.get("ok"):
                    task.status = DONE
                    if res.get("path"):
                        task.dest = str(res["path"])
                    if not task.total and task.done:
                        task.total = task.done
                else:
                    task.status = FAILED
                    task.error = str(res.get("error") or "下载失败")
                task.finishedAt = time.time()
                task.speed = 0.0
            _log(f"{task.kind} {task.id} -> {task.status}: {task.title}"
                 + (f" ({task.error})" if task.error else ""))
            self._emit(self._settled, task.id)

        threading.Thread(target=body, daemon=True).start()

    def _on_tick(self, tid: str) -> None:
        self._changed()

    def _on_settled(self, tid: str) -> None:
        with self._lock:
            task = self._tasks.get(tid)
        if task is not None:
            if task.status == DONE:
                self._toast(f"下载完成：{task.title}", "ok")
                self._after_mod_done(task)
            elif task.status == FAILED:
                self._toast(f"下载失败：{task.title}（{task.error}）", "error")
            elif task.status == CANCELED:
                self._toast(f"已取消：{task.title}", "warn")
            _log(f"settled {tid} = {task.status}")
        # 任务是在这里才变成「已结束」的，所以裁历史要在这之后做
        with self._lock:
            self._trim_locked()
        self._changed()

    def _after_mod_done(self, task: DownloadTask) -> None:
        """MOD 下完要通知 MOD 管理器：重新扫目录 + 补工坊标题/封面。

        以前这段逻辑长在 `ModManager.downloadWorkshop()` 里，下载改由队列接管后
        必须搬过来，否则下完的 .vpk 在列表里还是一串数字、没有封面。
        只在「这一批 MOD 全结束了」时补一次，不然几个 MOD 一起下会重复扫好几遍。

        ⚠ 必须**丢到后台线程**做：`mods.scan()` 是同步的，实测在几百个 MOD 的
        目录上会阻塞主线程 20 秒（第一次跑测试时 pump 直接被卡住 20.8 秒）。
        下载完成的那一刻界面正好在刷新，主线程一堵，用户看到的就是「下完了但整个
        程序僵住」，比晚两秒补封面糟糕得多。
        """
        if task.kind != "mod":
            return
        with self._lock:
            busy = any(t.kind == "mod" and t.active for t in self._tasks.values())
            done_items = [{"id": t.payload.get("id") or "",
                           "path": t.dest,
                           "title": t.title}
                          for t in [self._tasks[i] for i in self._order
                                    if i in self._tasks]
                          if t.kind == "mod" and t.status == DONE]
        if busy or not done_items:
            return
        mods = getattr(self.core, "mods", None)
        if mods is None:
            return

        def body() -> None:
            try:
                mods.scan()
            except Exception as exc:          # noqa: BLE001
                _log(f"scan after download failed: {exc!r}")
            # 工坊标题 + 封面：列表里要显示「名字 + 图」而不是「3840…」
            fn = getattr(mods, "_after_download", None)
            if callable(fn):
                try:
                    fn(done_items)
                except Exception as exc:      # noqa: BLE001
                    _log(f"after download decorate failed: {exc!r}")

        threading.Thread(target=body, daemon=True).start()

    # 给 worker 用的进度回调：算速度，攒够 0.2 秒才发一次信号，
    # 否则 64KB 一个 chunk、300MB 的文件能发几千次信号，把主线程压死。
    def make_progress(self, task: DownloadTask) -> Callable[[int, int], None]:
        def progress(got: int, total: int) -> None:
            if task.cancel:
                raise Cancelled()
            with self._lock:
                task.done = int(got or 0)
                if total:
                    task.total = int(total)
                now = time.time()
                span = now - task._last_time
                if span >= 0.2:
                    task.speed = (task.done - task._last_bytes) / span
                    task._last_bytes = task.done
                    task._last_time = now
                    fire = True
                else:
                    fire = False
            if fire:
                self._emit(self._tick, task.id)

        return progress

    def check_cancel(self, task: DownloadTask) -> None:
        """下载循环自己该调一下（有的地方拿不到 progress 回调）。"""
        if task.cancel:
            raise Cancelled()

    # ------------------------------------------------------------ 对外槽
    @Slot("QVariantList", result="QVariantMap")
    def addMods(self, items: list) -> dict:
        """把一批工坊条目排进下载队列（每条一个任务，进度各自独立）。"""
        mods = getattr(self.core, "mods", None)
        dest = ""
        if mods is not None:
            dest = str(getattr(mods, "addonsDir", "") or "")
        if not dest:
            msg = "还没设置 MOD 目录，先去设置里检测一下"
            self._toast(msg, "error")
            return {"ok": False, "error": msg, "ids": []}

        todo = [it for it in (items or []) if isinstance(it, dict)]
        if not todo:
            return {"ok": False, "error": "没有可下载的条目", "ids": []}

        ids: list[str] = []
        for it in todo:
            wid = str(it.get("id") or "").strip()
            title = str(it.get("title") or wid or "未命名 MOD")
            size = int(it.get("size") or 0)
            task = DownloadTask(
                kind="mod", title=title, dest=dest,
                subtitle=f"创意工坊 {wid}" if wid else "创意工坊",
                payload={"item": it, "id": wid},
            )
            if size > 0:
                task.total = size
            self._add(task)
            ids.append(task.id)
            _log(f"queue mod {task.id} {title}")
            self._run(task, self._work_mod)

        self._changed()
        self._set_status(f"已排入 {len(ids)} 个 MOD 下载")
        return {"ok": True, "ids": ids, "count": len(ids), "error": ""}

    def _work_mod(self, task: DownloadTask) -> dict:
        """单个 MOD 的实际下载（直链不在就现解析一次）。"""
        item = dict(task.payload.get("item") or {})
        wid = str(item.get("id") or task.payload.get("id") or "").strip()
        url = str(item.get("url") or "").strip()
        mods = getattr(self.core, "mods", None)
        cdn_ip = ""
        if mods is not None:
            try:
                cdn_ip = str(mods._active_cdn_ip() or "")
            except Exception:                 # noqa: BLE001 - 拿不到就当没有
                cdn_ip = ""

        if not url:
            self._set_task_note(task, "正在解析直链…")
            dl = WD.resolve_download(wid)
            url = str(dl.get("url") or "").strip()
            if not url:
                return {"ok": False,
                        "error": dl.get("error") or "下载站没给直链"}

        # 文件名一律用工坊 ID：MOD 管理器就是靠「纯数字文件名」认这是工坊 MOD 的，
        # 认出来才会自动挂标题 / 封面 / 更新检查。
        name = f"{wid}.vpk" if wid.isdigit() else ""
        if not name:
            name = WD._safe_filename(item.get("filename") or "") or ""
            if name and not os.path.splitext(name)[1]:
                name += ".vpk"

        res = WD.download_file_via_ip(
            url, task.dest, name, cdn_ip,
            progress=self.make_progress(task),
        )
        if not res.get("ok") and item.get("urlFromApi") and wid.isdigit():
            # 中转白送的直链会过期（CDN 换版本就 404），退回下载站再解析一次
            self.check_cancel(task)
            self._set_task_note(task, "直链过期，正在重新解析…")
            dl = WD.resolve_download(wid)
            if dl.get("url"):
                res = WD.download_file_via_ip(
                    dl["url"], task.dest, name, cdn_ip,
                    progress=self.make_progress(task),
                )
        if res.get("ok"):
            task.title = task.title
        return res

    def _set_task_note(self, task: DownloadTask, note: str) -> None:
        with self._lock:
            task.subtitle = note
        self._emit(self._tick, task.id)

    @Slot(str, result="QVariantMap")
    def addVideo(self, bvid: str) -> dict:
        """把一条 B 站视频的 MP4 排进下载队列。"""
        bvid = (bvid or "").strip()
        if not bvid:
            return {"ok": False, "error": "没有视频 ID", "id": ""}
        core = self.core
        rec = {}
        try:
            rec = core.findVideo(bvid) or {}
        except Exception:                     # noqa: BLE001
            rec = {}
        title = str(rec.get("title") or bvid)
        # ★ 落点走 `video_dir()`：默认软件目录/downloads/video，
        #   但用户在设置里改过下载位置的话就跟着走。
        dest = self.video_dir()
        task = DownloadTask(
            kind="video", title=title, dest=dest,
            subtitle=f"B 站视频 {bvid}",
            payload={"bvid": bvid},
        )
        self._add(task)
        _log(f"queue video {task.id} {bvid} {title}")
        self._run(task, self._work_video)
        self._changed()
        self._set_status(f"已排入视频下载：{title[:20]}")
        return {"ok": True, "id": task.id, "error": ""}

    def _work_video(self, task: DownloadTask) -> dict:
        bvid = str(task.payload.get("bvid") or "")
        client = getattr(self.core, "client", None)
        if client is None:
            return {"ok": False, "error": "B 站客户端没准备好"}
        # video_stream 返回 (url, 字节数)：它取的是 durl 的合并 MP4（带音轨），
        # 不是 DASH —— DASH 音视频分离，存下来只有画面没声音。
        try:
            url, size = client.video_stream(bvid)
        except Exception as exc:              # noqa: BLE001 - BiliError 等统一转成失败
            return {"ok": False, "error": str(exc) or "拿不到播放地址"}
        url = str(url or "")
        if not url:
            return {"ok": False, "error": "这个视频没有可用的 MP4 流"}
        if size:
            with self._lock:
                task.total = int(size)

        os.makedirs(task.dest, exist_ok=True)
        safe = WD._safe_filename(task.title) or bvid
        path = os.path.join(task.dest, f"{safe}_{bvid}.mp4")
        self.check_cancel(task)

        ok = client.download_stream(url, bvid, path,
                                    on_progress=self.make_progress(task))
        if not ok:
            return {"ok": False, "error": "视频流下载失败"}
        return {"ok": True, "path": path}

    # ---------------------------------------------------------- 网盘直链
    # ★ 签名必须是 `QVariantMap`（dict），**不能写 str**。
    #   写 `@Slot(str, ...)` 时 QML 传 JS 对象会被 Qt 强转成字符串
    #   （`"{url: ..., name: ...}"` 这种），然后在 Python 里
    #   `info.get(...)` 直接 `AttributeError: 'str' object has no attribute 'get'`。
    #   而 QML 调 Python 槽是同步的，异常被 Qt 吞掉 → 界面上**一点反馈都没有**
    #   （用户报的「本地蓝奏云下载没反应，连反馈都没有」就是这个）。
    @Slot("QVariantMap", result="QVariantMap")
    def addPanFile(self, info: dict) -> dict:
        """把一条网盘分享（目前是蓝奏云）解析成直链后下载。

        `info` 来自详情面板的网盘链接行：``{url, name, code, label}``。
        **也接受纯字符串 URL**（兼容老调用方 / 手动测试）。

        为什么要先解析：蓝奏云的分享页不是文件地址，得先换出 CDN 直链
        才能下（见 `app/lanzou.py`）。解析失败会明确报错并弹 toast ——
        「点了没反应」比失败本身更糟。
        """
        try:
            return self._add_pan_impl(info)
        except Exception as e:                   # noqa: BLE001
            # 兜底：任何意外都要让用户看到，绝不再静默
            msg = f"加入网盘下载失败：{e.__class__.__name__} {e}"
            _log(msg)
            self._toast(msg, "error")
            self._set_status(msg)
            return {"ok": False, "error": msg, "id": ""}

    def _add_pan_impl(self, info) -> dict:
        # 兼容「直接给 URL 字符串」的调用方
        if isinstance(info, str):
            info = {"url": info}
        if not isinstance(info, dict):
            info = {}
        url = str(info.get("url") or "").strip()
        if not url:
            msg = "这条网盘链接没有地址"
            self._toast(msg, "warn")
            return {"ok": False, "error": msg, "id": ""}

        name = str(info.get("name") or "网盘文件")
        label = str(info.get("label") or "").strip()
        title = label or name
        dest = self.pan_dir()
        task = DownloadTask(
            kind="pan", title=title, dest=dest,
            subtitle=f"{name} 直链" + ("（带提取码）" if info.get("code") else ""),
            payload={"url": url, "code": str(info.get("code") or ""),
                     "name": name},
        )
        self._add(task)
        _log(f"queue pan {task.id} {url}")
        self._toast(f"已加入下载：{title[:24]}（进度看左下角「下载」）", "ok")
        self._run(task, self._work_pan)
        self._changed()
        self._set_status(f"已排入网盘下载：{title[:20]}")
        return {"ok": True, "id": task.id, "error": ""}

    def _work_pan(self, task: DownloadTask) -> dict:
        from . import lanzou as LZ

        url = str(task.payload.get("url") or "")
        code = str(task.payload.get("code") or "")
        self._set_task_note(task, "正在解析直链…")
        res = LZ.resolve_lanzou(url, password=code)
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error") or "解析失败"}
        direct = str(res.get("url") or "")
        if not direct:
            return {"ok": False, "error": "没拿到直链"}

        # ---- 文件夹分享：顺手把「里面有 N 个，这次取的是哪个」说清楚 ----
        # 蓝奏云的 /bXXXX 分享是一个文件夹。程序现在能解析（以前直接拒绝），
        # 但一次只能下一个文件 —— 不说清楚的话，用户以为「怎么只下了一个」。
        if res.get("folder"):
            cnt = int(res.get("folderCount") or 0)
            picked = str(res.get("filename") or "")
            names = [str(x.get("name") or "")
                     for x in (res.get("folderFiles") or [])]
            note = f"文件夹分享（共 {cnt} 个），本次取：{picked}"
            if cnt > 1:
                rest = [n for n in names[1:4] if n]
                if rest:
                    note += "；还有 " + "、".join(rest)
                    if cnt > 4:
                        note += f" 等 {cnt - 1} 个"
            self._set_task_note(task, note)
            _log(f"pan folder: {url} -> {picked} ({cnt} files)")

        # ---- 先判断这是不是 MOD 文件 ----
        # 蓝奏云上绝大多数「求生之路2 资源」其实是 .vpk。这种不该丢到 downloads/pan
        # 让用户再手动搬一次 —— 直接落到 addons 目录，MOD 管理器扫一下就能用。
        # 判断依据（由强到弱）：
        #   1) 直链/文件名里的扩展名是 .vpk
        #   2) 分享页标题里带 .vpk
        #   3) 名字里出现「mod / vpk」且不带压缩包扩展名
        fname = str(res.get("filename") or "").strip()
        raw_name = str(task.payload.get("name") or "").strip()
        probe = f"{fname} {raw_name} {direct}".lower()
        is_archive = any(probe.split("?")[0].rstrip().endswith(e)
                         for e in (".zip", ".rar", ".7z"))
        is_vpk = (probe.rstrip().endswith(".vpk")
                  or ".vpk" in probe
                  or (not is_archive
                      and ("mod" in probe or "vpk" in probe)))

        if is_vpk and not is_archive:
            mods = getattr(self.core, "mods", None)
            addons = str(getattr(mods, "addonsDir", "") or "") if mods else ""
            if addons:
                task.kind = "mod"
                task.payload["id"] = ""      # 不是工坊 ID，走普通 MOD 文件
                task.dest = addons
                if not fname.lower().endswith(".vpk"):
                    fname = (WD._safe_filename(fname) or task.title or "pan_mod")
                    fname += ".vpk"
                task.subtitle = "蓝奏云 → MOD 目录"
                self._set_task_note(task, "是 MOD 文件，下到 addons…")
            else:
                task.subtitle = "蓝奏云（没设 MOD 目录，先放 downloads/pan）"

        if not fname:
            fname = raw_name or "pan_file"
        safe = WD._safe_filename(fname) or "pan_file"
        if not os.path.splitext(safe)[1]:
            safe += ".zip"            # 蓝奏云最常见的分享类型
        task.dest = os.path.join(task.dest or "", safe)
        self._set_task_note(task, "正在下载…")
        # ★ 蓝奏云的 /file/ 直链返回的是 **gzip 压缩的原始文件**
        #   （Range 取头 2KB 能看到 \x1f\x8b magic），不是 HTTP 传输编码。
        #   通用下载器不会解压，存下来就是个打不开的坏包 —— 所以这里走
        #   `lanzou.download_direct()`，它边下边解压。
        dl = LZ.download_direct(
            direct, os.path.dirname(task.dest),
            os.path.basename(task.dest),
            referer=url,
            progress=self.make_progress(task),
        )
        if dl.get("ok") and is_vpk and not is_archive:
            # 落进 addons 之后要重扫，列表里才会出现
            mods = getattr(self.core, "mods", None)
            if mods is not None:
                try:
                    mods.scan()
                except Exception:             # noqa: BLE001
                    pass
        return dl

    # ------------------------------------------------------------ 控制
    @Slot(str)
    def cancelTask(self, tid: str) -> None:
        with self._lock:
            task = self._tasks.get(tid)
            if task is None:
                return
            if not task.active:
                return
            task.cancel = True
            if task.status == QUEUED:
                task.status = CANCELED
                task.finishedAt = time.time()
                settled = True
            else:
                settled = False
        self._set_status("正在取消…")
        if settled:
            self._emit(self._settled, tid)
        else:
            self._changed()

    @Slot(str)
    def retryTask(self, tid: str) -> None:
        """把一条失败/取消的任务原样再排一次（新任务，旧记录留着）。"""
        with self._lock:
            old = self._tasks.get(tid)
        if old is None or old.active:
            return
        if old.kind == "mod":
            item = dict(old.payload.get("item") or {})
            if not item:
                self._toast("这条任务没有可以重试的信息", "warn")
                return
            self.addMods([item])
        elif old.kind == "video":
            self.addVideo(str(old.payload.get("bvid") or ""))
        else:
            self._toast("这种任务不支持重试", "warn")

    @Slot()
    def clearFinished(self) -> None:
        """清空已完成/失败的记录，**并把它们下下来的文件一起删掉**。

        ★ 用户报的：「把下载好的文件移除列表，无法真实删除，还会遗留」。
          以前的 `clearFinished()` / `removeTask()` 只从内存 `_tasks` 里
          摘记录，磁盘上的文件一个都不动 —— 列表里看不到了，文件还躺在
          `downloads/` 或 addons 里，用户越积越多还以为程序没删。

        ★ 为什么不删「下到 addons 的 MOD」：那是用户要用的东西，
          清个下载记录就把它删了会出人命。所以按 `kind` 区分：
            · `mod`（下进 addons 的）：**只摘记录，不动文件**
            · 其它（网盘/视频，落在 downloads/ 下）：记录和文件一起清
          这个判断放在 `_cleanup_files()` 里，两个入口共用。
        """
        with self._lock:
            drop = [t for t in self._tasks.values() if not t.active]
            paths = [t.dest for t in drop if self._should_delete_file(t)]
            for t in drop:
                self._tasks.pop(t.id, None)
                try:
                    self._order.remove(t.id)
                except ValueError:
                    pass
        if drop:
            removed = self._delete_paths(paths)
            msg = f"清掉了 {len(drop)} 条记录"
            if removed:
                msg += f"，同时删除 {removed} 个文件"
            self._set_status(msg)
        self._changed()

    @Slot(str)
    def removeTask(self, tid: str) -> None:
        """从列表移除一条记录，并删掉它下下来的文件。

        和 `clearFinished()` 同一套规则（见那边的注释）：
        下进 addons 的 MOD 不删文件，其它下载产物连文件一起删。
        """
        with self._lock:
            task = self._tasks.get(tid)
            if task is None or task.active:
                return
            self._tasks.pop(tid, None)
            try:
                self._order.remove(tid)
            except ValueError:
                pass
            drop_path = task.dest if self._should_delete_file(task) else ""
        removed = self._delete_paths([drop_path] if drop_path else [])
        if removed:
            self._set_status(f"已移除并删除文件：{os.path.basename(drop_path)}")
        self._changed()

    # ------------------------------------------------------------ 下载位置
    #
    # ★ 默认落在**软件目录**下的 `downloads/`（网盘在 `pan/`、视频在 `video/`）。
    #   用户可以在设置里改成任意目录 —— 比如 C 盘紧张、想直接下到 D 盘。
    #
    # ★ 配置里存空串表示「用默认」。不存绝对路径的原因：绿色版软件
    #   可能被整个文件夹搬走 / 改盘符，存死路径会让下载直接失败。
    #
    # ★ 布局保持一致（`<root>/pan`、`<root>/video`），这样换目录之后
    #   「哪些东西是该删的」判断逻辑不用改 —— `_download_roots()` 跟着换根就行。
    DEFAULT_DOWNLOAD_DIR_NAME = "downloads"

    def _default_download_root(self) -> str:
        return os.path.join(str(getattr(util, "ROOT", "") or ""),
                            self.DEFAULT_DOWNLOAD_DIR_NAME)

    def downloadRoot(self) -> str:
        """当前下载根目录（绝对路径）。配置为空时用软件目录下的 downloads/。"""
        raw = ""
        try:
            raw = str(self._cfg["download_dir"] or "").strip()
        except (KeyError, TypeError):
            raw = ""
        # ★ 配的目录不存在（换机器 / 手动删了）就退回默认，别让下载全废。
        #   但**不自动清空配置** —— 那个盘可能只是暂时没挂上（U 盘 / 移动硬盘）。
        if raw:
            try:
                os.makedirs(raw, exist_ok=True)
                return os.path.abspath(raw)
            except OSError as e:
                _log(f"download dir unusable {raw!r}: {e!r}")
        return os.path.abspath(self._default_download_root())

    def pan_dir(self) -> str:
        return os.path.join(self.downloadRoot(), "pan")

    def video_dir(self) -> str:
        return os.path.join(self.downloadRoot(), "video")

    # ---------------------------------------------------------- 给界面用的属性
    @Property(str, notify=downloadsChanged)
    def downloadDir(self) -> str:
        """当前下载根目录（绝对路径），设置页直接显示它。"""
        return self.downloadRoot()

    @Property(bool, notify=downloadsChanged)
    def isDefaultDownloadDir(self) -> bool:
        """现在是默认位置吗（决定「恢复默认」那颗按钮是否可点）。"""
        try:
            raw = str(self._cfg["download_dir"] or "").strip()
        except (KeyError, TypeError):
            raw = ""
        return not raw

    @Property(int, notify=downloadsChanged)
    def pendingCount(self) -> int:
        """旧目录里还能搬的文件数（0 = 不显示那条提示）。

        ★ 点了「先不搬」之后返回 0 —— 不然那条橙色提示会一直杵在设置页里，
          用户已经明确表达过「这次不搬」了。
        """
        if getattr(self, "_migrate_dismissed", False):
            return 0
        return len(self.pendingDownloadFiles())

    @Property(str, notify=downloadsChanged)
    def pendingSizeText(self) -> str:
        """旧目录里待搬文件的总大小（人话）。"""
        try:
            total = sum(int(p.get("size") or 0) for p in self.pendingDownloadFiles())
        except (TypeError, ValueError):
            total = 0
        return util.human_size(total)

    @Slot()
    def dismissMigrateHint(self) -> None:
        """用户点了「先不搬」：这次运行内不再提示（不改配置，下次开还会问）。"""
        self._migrate_dismissed = True
        self.downloadsChanged.emit()

    @Slot(result="QVariantMap")
    def openDownloadDir(self) -> dict:
        """打开当前下载目录（不存在就先建出来）。"""
        d = self.downloadRoot()
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)  # noqa: S606 - 就是要打开资源管理器
            return {"ok": True, "path": d}
        except OSError as e:
            self._toast(f"打不开目录：{e}", "warn")
            return {"ok": False, "path": d, "error": str(e)}

    @Slot(str, result="QVariantMap")
    def setDownloadDir(self, path: str) -> dict:
        """设置下载目录。空串 = 恢复默认（软件目录下的 downloads/）。

        返回 `{ok, dir, error}`。**只改配置、不搬文件** ——
        搬不搬由用户决定（见 `migrateDownloads`），因为几百 MB 的搬动
        不该被「改个设置」这种动作隐式触发。
        """
        raw = str(path or "").strip()
        if raw:
            try:
                os.makedirs(raw, exist_ok=True)
            except OSError as e:
                msg = f"这个目录建不出来：{e}"
                self._toast(msg, "error")
                return {"ok": False, "dir": self.downloadRoot(), "error": msg}
            if not os.access(raw, os.W_OK):
                msg = "这个目录没有写入权限"
                self._toast(msg, "error")
                return {"ok": False, "dir": self.downloadRoot(), "error": msg}
        try:
            self._cfg["download_dir"] = os.path.abspath(raw) if raw else ""
            self._cfg.save()
        except OSError as e:
            msg = f"保存设置失败：{e}"
            self._toast(msg, "error")
            return {"ok": False, "dir": self.downloadRoot(), "error": msg}
        new_dir = self.downloadRoot()
        # 换了目录就重新允许提示「旧文件要不要搬」—— 用户刚才点了「先不搬」
        # 是针对**上一个**目录的，不该一直压着。
        self._migrate_dismissed = False
        self._set_status(f"下载目录已改为：{new_dir}")
        self._toast("下载目录已更新", "ok")
        self.downloadsChanged.emit()
        return {"ok": True, "dir": new_dir, "error": ""}

    @Slot(result="QVariantList")
    def pendingDownloadFiles(self) -> list:
        """旧下载目录里**还在、且可以被搬走**的文件（给「要不要一起搬」提示用）。

        返回 `[{name, path, size, isPan}]`。只统计当前配置之外的目录、
        并且确实存在的文件 —— 用户看到「有 3 个文件，要一起搬过去吗」
        才是有意义的。
        """
        cur = os.path.normcase(self.downloadRoot())
        out: list[dict] = []
        for root in self._all_download_roots():
            norm = os.path.normcase(root)
            if norm == cur:
                continue
            # 只收根目录或 pan/video 这一层的文件，不递归到用户自己建的子目录
            for sub in ("", "pan", "video"):
                d = os.path.join(root, sub) if sub else root
                if not os.path.isdir(d):
                    continue
                try:
                    names = os.listdir(d)
                except OSError:
                    continue
                for name in names:
                    p = os.path.join(d, name)
                    if not os.path.isfile(p):
                        continue
                    try:
                        size = os.path.getsize(p)
                    except OSError:
                        size = 0
                    out.append({"name": name, "path": p, "size": size,
                                "isPan": sub == "pan" or sub == "video"})
        return out

    @Slot(result="QVariantMap")
    def migrateDownloads(self) -> dict:
        """把旧下载目录里的文件搬到**当前**目录。返回 `{ok, moved, skipped, error}`。

        ★ 重名不覆盖：目标已有同名文件就跳过（和 `import_files` 一个原则，
          绝不悄悄覆盖用户的东西）。
        ★ 搬完删掉空的旧目录（只删 pan/video 这层空壳，不递归删别的东西）。
        """
        import shutil

        target_root = self.downloadRoot()
        moved: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []
        for item in self.pendingDownloadFiles():
            src = str(item.get("path") or "")
            name = str(item.get("name") or "")
            if not src or not os.path.isfile(src):
                continue
            # 目标目录：盘/视频各自归位（按它原来在 pan/ 还是 video/ 判断）
            sub = ""
            norm = os.path.normcase(os.path.abspath(src))
            for root in self._all_download_roots():
                r = os.path.normcase(os.path.abspath(root))
                for s in ("pan", "video"):
                    if norm.startswith(os.path.normcase(
                            os.path.join(root, s)) + os.sep):
                        sub = s
                        break
                if sub:
                    break
                if os.path.normcase(os.path.dirname(norm)) == r:
                    sub = ""
                    break
            dst_dir = os.path.join(target_root, sub) if sub else target_root
            try:
                os.makedirs(dst_dir, exist_ok=True)
            except OSError as e:
                errors.append(f"{name}: {e}")
                continue
            dst = os.path.join(dst_dir, name)
            if os.path.exists(dst):
                skipped.append(name)
                continue
            try:
                shutil.move(src, dst)
                moved.append(name)
            except (OSError, shutil.Error) as e:
                errors.append(f"{name}: {e}")
        # 清掉搬空的旧目录（只清 pan/ video/ 和它们自己，不递归）
        for root in self._all_download_roots():
            if os.path.normcase(root) == os.path.normcase(target_root):
                continue
            for d in (os.path.join(root, "pan"), os.path.join(root, "video"), root):
                try:
                    if os.path.isdir(d) and not os.listdir(d):
                        os.rmdir(d)
                except OSError:
                    pass
        msg = f"已转移 {len(moved)} 个文件"
        if skipped:
            msg += f"，{len(skipped)} 个同名跳过"
        if errors:
            msg += f"，{len(errors)} 个失败"
        self._set_status(msg)
        self._toast(msg, "ok" if moved else "info")
        self.downloadsChanged.emit()
        return {"ok": bool(moved) or not errors, "moved": moved,
                "skipped": skipped, "errors": errors,
                "error": "" if not errors else errors[0]}

    def _all_download_roots(self) -> list[str]:
        """所有**可能**存过下载产物的根目录（当前 + 默认）。

        ★ 为什么要两个：用户改过目录之后，旧目录里可能还躺着上次下的东西。
          「哪些文件该跟着记录一起删」「要不要一起搬走」都得把旧目录算进来，
          否则那些文件就成了永远没人管的孤儿。
        """
        out: list[str] = []
        seen: set[str] = set()
        for p in (self.downloadRoot(), self._default_download_root()):
            try:
                n = os.path.normcase(os.path.abspath(p))
            except (TypeError, ValueError):
                continue
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out

    # ------------------------------------------------------------ 删除的辅助
    # 这些是「下载产物」的存放地。只有**落在这些目录下**的文件才允许跟着
    # 记录一起删 —— 防止 dest 指向别处（比如用户手动选的目录）时误删。
    def _download_roots(self) -> list[str]:
        out = []
        for root in self._all_download_roots():
            for sub in ("", "pan", "video"):
                p = os.path.normcase(os.path.abspath(
                    os.path.join(root, sub) if sub else root))
                if p and p not in out:
                    out.append(p)
        return out

    def _should_delete_file(self, task) -> bool:
        """这条任务的产物该不该跟着记录一起删。

        三条都要满足：
          1. 不是下进 addons 的 MOD（那个是用户要用的，不能删）；
          2. 状态是完成（失败/取消的本来就没有完整文件，或只留半个残片）；
          3. 文件确实落在 downloads/ 下（防误删别处的东西）。
        """
        if task is None:
            return False
        if str(getattr(task, "kind", "")) == "mod":
            return False
        if str(getattr(task, "status", "")) != DONE:
            return False
        p = str(getattr(task, "dest", "") or "")
        if not p or not os.path.isfile(p):
            return False
        full = os.path.normcase(os.path.abspath(p))
        parent = os.path.dirname(full)
        for root in self._download_roots():
            if parent == root or parent.startswith(root + os.sep):
                return True
        return False

    def _delete_paths(self, paths: list[str]) -> int:
        """真删一批文件（走回收站，删错了能捞回来）。返回删掉的数量。

        复用 `mods.delete_files()`：它已经处理了「文件被占用」、
        「回收站不可用时退回 os.remove」，这些坑不用再踩一遍。
        """
        from . import mods as M

        usable = [p for p in (paths or [])
                  if p and os.path.isfile(p)
                  and os.path.normcase(os.path.abspath(p)) !=
                  os.path.normcase(os.path.abspath(str(getattr(util, "ROOT", ""))))]
        if not usable:
            return 0
        try:
            res = M.delete_files(usable, to_recycle=bool(self._to_recycle()))
        except Exception as e:      # noqa: BLE001  删文件失败不能影响列表
            _log(f"delete download files failed: {e!r}")
            return 0
        removed = len(res.get("removed") or [])
        errors = res.get("errors") or []
        if errors:
            _log(f"delete download files: {errors[:3]}")
            self._toast(f"{len(errors)} 个文件删不掉（可能被占用）", "warn")
        if removed:
            _log(f"deleted {removed} downloaded files")
        return removed

    def _to_recycle(self) -> bool:
        """跟「删除 MOD」的偏好保持一致（设置里可切直接删除）。"""
        core = getattr(self, "core", None)
        try:
            mods = getattr(core, "mods", None)
            if mods is not None:
                return bool(getattr(mods, "_delete_to_recycle", True))
        except Exception:           # noqa: BLE001
            pass
        return True

    @Slot(str)
    def openTaskFolder(self, tid: str) -> dict:
        with self._lock:
            task = self._tasks.get(tid)
        if task is None:
            return {"ok": False, "error": "任务不在了"}
        path = task.dest
        if path and os.path.isfile(path):
            path = os.path.dirname(path)
        if not path or not os.path.isdir(path):
            return {"ok": False, "error": "文件夹不在了"}
        try:
            os.startfile(path)  # noqa: S606 - 就是要打开资源管理器
            return {"ok": True, "path": path}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------ 压缩包里的 MOD
    #
    # 蓝奏云上下的东西九成是压缩包（.7z / .zip / .rar），里面才是 .vpk。
    # 用户下完还要自己解压、再手动导入 —— 太绕了。
    # 这里做两件事：
    #   · `inspectTaskArchive()`  查这个压缩包里有没有 MOD，有几张封面
    #   · `importTaskArchive()`   一键把里面的 .vpk（连同同名封面）导进 addons
    #
    # 解压用 Windows 自带的 `tar.exe`（bsdtar + libarchive）：它原生认
    # zip / 7z / rar / tar，不用装 7-Zip 或 WinRAR，也不引入新依赖。
    # 只有 .zip 我们额外用标准库兜底（更可靠，且能拿到准确的文件清单）。
    @Slot(str, result="QVariantMap")
    def inspectTaskArchive(self, tid: str) -> dict:
        """查这个下载任务的成品是不是「里面有 MOD 的压缩包」。

        返回 ``{ok, isArchive, mods, images, names, error}``。
        界面据此决定要不要显示「导入 MOD」那颗按钮。
        """
        path, err = self._task_file(tid)
        if err:
            return {"ok": False, "isArchive": False, "mods": 0, "images": 0,
                    "names": [], "error": err}
        info = _scan_archive(path)
        info["ok"] = True
        return info

    @Slot(str, result="QVariantMap")
    def importTaskArchive(self, tid: str) -> dict:
        """把这个任务下的压缩包里的 MOD 一键导进 addons 目录。"""
        path, err = self._task_file(tid)
        if err:
            return {"ok": False, "error": err, "copied": []}

        mods_mgr = getattr(getattr(self, "core", None), "mods", None)
        addons = str(getattr(mods_mgr, "addonsDir", "") or "") if mods_mgr else ""
        if not addons:
            msg = "还没设置 MOD 目录，先去设置里检测一下"
            self._toast(msg, "error")
            return {"ok": False, "error": msg, "copied": []}

        # 解到临时目录，再走和「拖文件进 MOD 管理器」完全一样的导入流程
        tmp = ""
        try:
            tmp = tempfile.mkdtemp(prefix="l42d_zip_")
            got = _extract_to(path, tmp)
            if not got.get("ok"):
                raise RuntimeError(got.get("error") or "解压失败")
            files = _collect_importable(tmp)
            if not files:
                msg = "这个压缩包里没有 .vpk，跳过"
                self._toast(msg, "warn")
                return {"ok": False, "error": msg, "copied": []}

            from . import mods as M

            # `import_files` 内部会 `normalize_addons_dir()`，它要求目录**已存在**
            # （用户的 addons 目录当然在，但第一次用 / 换盘之后可能还没建）。
            # 这里先 ensure 一下，否则会莫名其妙报「还没有设置 MOD 目录」。
            try:
                os.makedirs(addons, exist_ok=True)
            except OSError as e:
                raise RuntimeError(f"MOD 目录建不出来：{e}") from e

            res = M.import_files(files, addons)
            copied = list(res.get("copied") or [])
            skipped = list(res.get("skipped") or [])
            locked = list(res.get("locked") or [])
            failed = list(res.get("errors") or [])
            if copied:
                extra = ""
                if skipped:
                    extra = f"（{len(skipped)} 个 addons 里已有，跳过）"
                self._toast(f"已导入 {len(copied)} 个 MOD 到 addons{extra}", "ok")
                try:
                    mods_mgr.scan()
                except Exception:            # noqa: BLE001
                    pass
            elif locked:
                self._toast("文件被占用（游戏在跑？），关掉游戏再试", "warn")
            elif skipped:
                # 全是同名 —— `import_files` 的既定行为是**不覆盖**，
                # 所以这里不该报「失败」，要说清是「已经有了」。
                msg = f"addons 里已经有这 {len(skipped)} 个 MOD 了，没有重复导入"
                self._toast(msg, "info")
                self._set_status(msg)
                return {"ok": False, "copied": [], "skipped": skipped,
                        "locked": [], "errors": [], "error": msg}
            else:
                self._toast("没导入成功" + (f"：{failed[0]}" if failed else ""), "error")
            self._set_status(
                f"压缩包导入完成：{len(copied)} 个成功"
                + (f"，{len(skipped)} 个已存在" if skipped else "")
                + (f"，{len(locked)} 个被占用" if locked else ""))
            return {"ok": bool(copied), "copied": copied, "skipped": skipped,
                    "locked": locked,
                    "errors": failed,
                    "error": "" if copied else (skipped and "同名已存在" or "没有导入成功的")}
        except Exception as exc:              # noqa: BLE001
            msg = f"导入失败：{exc}"
            self._toast(msg, "error")
            return {"ok": False, "error": msg, "copied": []}
        finally:
            if tmp:
                import shutil

                shutil.rmtree(tmp, ignore_errors=True)

    def _task_file(self, tid: str) -> tuple[str, str]:
        """取任务落盘的那个文件路径；不是文件就返回原因。"""
        with self._lock:
            task = self._tasks.get(tid)
        if task is None:
            return "", "任务不在了"
        p = str(task.dest or "")
        if not p or not os.path.isfile(p):
            return "", "这个任务没有落盘文件"
        return p, ""

    def _set_status(self, text: str) -> None:
        core = getattr(self, "core", None)
        fn = getattr(core, "_set_status", None)
        if callable(fn):
            try:
                fn(text)
            except RuntimeError:
                self._closed = True

    # ------------------------------------------------------------ 收尾
    def shutdown(self) -> None:
        self._closed = True
        with self._lock:
            for task in self._tasks.values():
                if task.active:
                    task.cancel = True
