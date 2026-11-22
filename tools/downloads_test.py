"""统一下载队列（`app/downloads.py` + 下载页）的自检。

盯五件事：
  1. 任务状态机：queued → running → done / failed / canceled，**只往前不倒退**；
     抛异常也要落成 failed，不能把线程打死。
  2. 取消是协作式的：点取消后下载循环里的 progress 回调要能把它抛出去
     （`Cancelled`），而不是等整个文件下完才生效。
  3. 重试 / 清空 / 移除 / 历史上限这些操作不能把队列搞坏。
  4. 人话格式化：字节数、速度、百分比、剩余大小。
  5. QML 侧真的有这颗入口和这一页（源码断言，防以后被误删）。

不跑真实网络下载：所有 worker 都是假的，测的是队列本身。
"""
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import os
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEventLoop, QTimer          # noqa: E402
from PySide6.QtGui import QGuiApplication              # noqa: E402

from guard import protect_user_data                    # noqa: E402

protect_user_data()

from app import downloads as D                         # noqa: E402
from app.core import Core                              # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(cond, ms=5000, step=80):
    spent = 0
    while spent < ms:
        if cond():
            return True
        pump(step)
        spent += step
    return cond()


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    core = Core(app)
    globals()["_KEEP_CORE"] = core          # 别让 Core 在收尾前被回收
    dq = core.downloads
    dq.clearFinished()

    print("\n-- 人话格式化", flush=True)
    check("0 字节显示破折号", D.human_size(0) == "—", D.human_size(0))
    check("KB 档", D.human_size(2048) == "2.0 KB", D.human_size(2048))
    check("MB 档", D.human_size(5 * 1024 * 1024) == "5.0 MB",
          D.human_size(5 * 1024 * 1024))
    check("GB 档", D.human_size(3 * 1024 ** 3) == "3.0 GB",
          D.human_size(3 * 1024 ** 3))
    check("速度带 /s", D.human_speed(2 * 1024 * 1024) == "2.0 MB/s",
          D.human_speed(2 * 1024 * 1024))
    check("0 速度不显示", D.human_speed(0) == "", D.human_speed(0))

    print("\n-- 任务对象", flush=True)
    t = D.DownloadTask("mod", "测试", dest="C:/tmp", payload={"id": "7"})
    check("新任务是排队中", t.status == D.QUEUED, t.status)
    check("新任务算 active", t.active)
    t.total = 1000
    t.done = 250
    check("百分比算得对", t.percent == 25, t.percent)
    t.done = 2000
    check("百分比不会超过 100", t.percent == 100, t.percent)
    t.total = 0
    t.done = 5
    check("总大小未知时百分比是 0（不瞎猜）", t.percent == 0, t.percent)
    info = t.to_dict()
    for key in ("id", "kind", "title", "status", "percent", "doneText",
                "totalText", "speedText", "error", "active"):
        check(f"to_dict 有 {key}", key in info)

    print("\n-- 正常完成", flush=True)

    def ok_worker(task):
        p = dq.make_progress(task)
        for i in range(1, 5):
            time.sleep(0.01)
            p(i * 25, 100)
        return {"ok": True, "path": "C:/tmp/a.vpk"}

    t1 = D.DownloadTask("mod", "正常任务", dest="C:/tmp", payload={"id": "1"})
    dq._add(t1)
    dq._run(t1, ok_worker)
    check("跑起来了", wait_until(lambda: t1.status == D.DONE), t1.status)
    check("进度跑到 100%", t1.percent == 100, t1.percent)
    check("大小补齐了", t1.total == 100, t1.total)
    check("结束后不再 active", not t1.active)
    check("结束时间记了", t1.finishedAt > 0, t1.finishedAt)

    print("\n-- 失败与异常", flush=True)

    def fail_worker(task):
        return {"ok": False, "error": "下载站没给直链"}

    t2 = D.DownloadTask("mod", "失败任务", dest="C:/tmp", payload={"id": "2"})
    dq._add(t2)
    dq._run(t2, fail_worker)
    check("失败任务变 failed", wait_until(lambda: t2.status == D.FAILED), t2.status)
    check("失败原因留着", "直链" in t2.error, t2.error)

    def boom_worker(task):
        raise RuntimeError("模拟炸了")

    t3 = D.DownloadTask("mod", "炸了", dest="C:/tmp", payload={"id": "3"})
    dq._add(t3)
    dq._run(t3, boom_worker)
    check("抛异常也落成 failed", wait_until(lambda: t3.status == D.FAILED), t3.status)
    check("异常文字进了 error", "模拟炸了" in t3.error, t3.error)

    print("\n-- 取消", flush=True)

    def slow_worker(task):
        p = dq.make_progress(task)
        for i in range(1, 101):
            time.sleep(0.02)
            p(i * 10, 1000)          # 取消标记在这里抛 Cancelled
        return {"ok": True, "path": "C:/tmp/b.vpk"}

    t4 = D.DownloadTask("mod", "取消任务", dest="C:/tmp", payload={"id": "4"})
    dq._add(t4)
    dq._run(t4, slow_worker)
    check("慢任务进入 running", wait_until(lambda: t4.status == D.RUNNING), t4.status)
    dq.cancelTask(t4.id)
    check("取消后变 canceled", wait_until(lambda: t4.status == D.CANCELED), t4.status)
    check("取消后不再 active", not t4.active)

    # 排队中就取消：不该起线程干活
    t5 = D.DownloadTask("mod", "排队取消", dest="C:/tmp", payload={"id": "5"})
    dq._add(t5)
    t5.cancel = True
    dq._run(t5, slow_worker)
    check("排队中就被取消的任务直接 canceled",
          wait_until(lambda: t5.status == D.CANCELED), t5.status)

    # 已结束的任务点取消没有副作用
    before = t1.status
    dq.cancelTask(t1.id)
    pump(120)
    check("已完成的任务点取消不变", t1.status == before, t1.status)

    print("\n-- 队列操作", flush=True)
    check("activeCount 算对", dq.activeCount == 0, dq.activeCount)
    check("总数算对", dq.totalCount >= 4, dq.totalCount)

    # 撤回一个失败任务
    n_before = dq.totalCount
    dq.removeTask(t2.id)
    pump(100)
    check("移除一条失败记录", dq.totalCount == n_before - 1, dq.totalCount)

    # 重试：没有原始条目的情况要安全退出，不能炸
    dq.retryTask(t2.id)
    pump(150)
    check("重试不存在的任务不会炸", True)

    # 清空已结束
    dq.clearFinished()
    pump(150)
    check("清空已结束后一条不剩", dq.totalCount == 0, dq.totalCount)

    print("\n-- 历史上限", flush=True)
    # 走真实路径：_run → worker 返回 ok → _on_settled → _trim_locked。
    # 不能直接改 status —— 那样绕过了 settle 钩子，裁剪压根不会触发。
    #
    # 必须**逐条等它自己结束**：一次性堆 72 个线程 + 72 个 settled 信号，
    # Qt 事件循环会被淹没，测试自己卡死（踩过）。
    # 注意别用 `activeCount == 0` 当判据 —— 循环里下一条马上就加上来了，
    # 这个条件在两条任务之间根本不会稳定成立，只会一路等到超时（也踩过）。
    def instant_ok(task):
        return {"ok": True, "path": "C:/tmp/h.vpk"}

    for i in range(dq.MAX_HISTORY + 12):
        tt = D.DownloadTask("mod", f"历史{i}", dest="C:/tmp", payload={"id": str(i)})
        dq._add(tt)
        dq._run(tt, instant_ok)
        # 只等这一条落地（后台线程改完 status 就会 emit，很快），
        # 不等 Qt 队列排空 —— 72 轮各排一次能把测试拖到一分多钟。
        wait_until(lambda t=tt: not t.active, ms=3000)
    # 全部跑完后统一排空队列，让最后一条的 `_on_settled`（做裁剪的那个）执行到
    wait_until(lambda: dq.activeCount == 0, ms=3000)
    pump(300)
    wait_until(lambda: dq.totalCount <= dq.MAX_HISTORY, ms=3000)
    check(f"已结束记录不超过上限（{dq.MAX_HISTORY}）",
          dq.totalCount <= dq.MAX_HISTORY, dq.totalCount)

    print("\n-- MOD 下载入口接上队列", flush=True)
    dq.clearFinished()
    mods = core.mods
    old_dir = getattr(mods, "_addons_dir", "")
    mods._addons_dir = "C:/tmp/addons"        # 假装目录已设置，别真去建
    try:
        res = dq.addMods([{"id": "123456", "title": "测试 MOD", "url": ""}])
        check("addMods 收下了", res.get("ok"), res)
        check("排进去 1 个任务", res.get("count") == 1, res.get("count"))
        got = dq.tasks
        check("任务标题对得上", any(t["title"] == "测试 MOD" for t in got), got[:1])
        check("任务是 mod 类型", any(t["kind"] == "mod" for t in got))
        # 这条任务会真去联网解析直链（worker 已经在跑了），所以立刻取消，
        # 并等它落定，免得后面测 summaryText 时还挂着一条 active。
        for tt in got:
            dq.cancelTask(tt["id"])
        wait_until(lambda: dq.activeCount == 0, ms=8000)
    finally:
        mods._addons_dir = old_dir

    # 没设目录时要明确拒绝
    mods._addons_dir = ""
    try:
        bad = dq.addMods([{"id": "1", "title": "x"}])
        check("没设 MOD 目录会被拦住", not bad.get("ok"), bad)
    finally:
        mods._addons_dir = old_dir

    print("\n-- 视频下载入口", flush=True)
    bad_v = dq.addVideo("")
    check("空 bvid 被拒", not bad_v.get("ok"), bad_v)

    print("\n-- summaryText", flush=True)
    # 先把还在跑的任务取消干净再断言「空队列」。
    # 前面「MOD 下载入口」那一段会真去联网解析直链，任务可能还没结束；
    # 只调 clearFinished() 是清不掉它们的（它只清已结束的），于是
    # summaryText 会说「1 个进行中」—— 那是测试自己没收拾干净，不是产品问题。
    #
    # ★ 为什么不能「取消一次就断言」：取消是**异步**的 ——
    #   `cancelTask` 只是置了标志，工作线程要跑完当前那一步才会把 active 落成 False。
    #   套件里前面几项更慢、机器更忙，这段收尾时间就变长，于是偶尔会
    #   在「还没真结束」时断言 → 报「1 个进行中」。
    #   现在改成「反复取消 + 等 + 清，直到真的空了」，最多试 20 轮（约 4 秒）。
    for _ in range(20):
        for t in dq.tasks:
            if t.get("active"):
                dq.cancelTask(t["id"])
        wait_until(lambda: dq.activeCount == 0, ms=3000)
        dq.clearFinished()
        pump(120)
        if not dq.tasks:
            break
    check("空队列说人话", dq.summaryText == "还没有下载", dq.summaryText)

    print("\n-- QML / 集成源码断言", flush=True)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_qml = open(os.path.join(root, "qml", "Main.qml"), encoding="utf-8").read()
    page_qml = open(os.path.join(root, "qml", "components", "DownloadsPage.qml"),
                    encoding="utf-8").read()
    detail_qml = open(os.path.join(root, "qml", "components", "DetailPanel.qml"),
                      encoding="utf-8").read()
    for word, why in (
        ('objectName: "dlNavItem"', "左下角下载入口"),
        ('objectName: "downloadsPage"', "下载页本身"),
        ('objectName: "dlList"', "任务列表"),
        ('objectName: "dlCancelBtn"', "取消按钮"),
        ('objectName: "dlRetryBtn"', "重试按钮"),
        ('objectName: "dlFolderBtn"', "打开文件夹按钮"),
        ('objectName: "dlClearBtn"', "清空已结束按钮"),
        ('objectName: "dlEmpty"', "空状态"),
        ("win.section === 4", "下载页自己的 section"),
    ):
        check("QML 里有" + why, word in main_qml or word in page_qml, word)
    # 视频详情那颗「下载」按钮后来被删了（五个按钮挤一行，用户要求去掉）。
    # 现在视频改成从别处进队列，这里只要求「信号 / 接收端」还在，
    # 以及蓝奏云的网盘下载入口仍然从这个面板发起。
    check("详情面板没有视频下载按钮了（已按用户要求移除）",
          'objectName: "dlVideoButton"' not in detail_qml)
    check("蓝奏云的网盘下载仍然从详情面板发起",
          "downloadPanLink" in detail_qml)
    check("Main.qml 接了 onDownloadPanLink", "onDownloadPanLink" in main_qml)
    check("侧栏角标跟着进行中数量", "dlNavItem.activeN" in main_qml
          or "activeCount" in main_qml)
    check("Ctrl+J 能开下载页", "Ctrl+J" in main_qml)
    check("窗口矮时监控卡片让位", "win.height > 720" in main_qml)
    # DownloadsPage 的四个筛选档
    for mode in ("all", "active", "done", "failed"):
        check(f"下载页有 {mode} 筛选", f'"{mode}"' in page_qml)

    check("Core 暴露 downloads 属性", hasattr(core, "downloads"))
    check("MOD 异步下载走队列（不再是老路）", "queue.addMods" in
          open(os.path.join(root, "app", "modmanager.py"), encoding="utf-8").read())

    print()
    pump(200)                                # 让后台收尾的信号跑完
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "、".join(FAILS)), flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
