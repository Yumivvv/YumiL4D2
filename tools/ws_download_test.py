"""本轮两个修复的自检。

1. **创意工坊下载要交给下载页，别一直显示「处理中」**
   - `downloadWorkshopAsync` 必须**立刻** emit 一个 ok 结果（`expanding: True`），
     不能等合集展开完再回。以前 `_expand_collections()` 同步跑在 emit 之前，
     几百个成员要几十秒，UI 就卡在「下载中…」——用户看到的就是「一直处理中」。
   - 真正的展开 + 排队要在后台线程做，且最终真的进到下载队列里。

2. **进服务器页自动刷新一次**
   - 进页面要调一次 `refreshAll()`；
   - 但来回切页不能反复查（有防抖 + 「本次运行只自动刷一次」）；
   - 空列表不查（免得刷出「先加一个服务器地址吧」这种噪音）；
   - 用户手动点「刷新状态」永远立刻生效。
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

from PySide6.QtCore import QEventLoop, QObject, Qt, QUrl          # noqa: E402
from PySide6.QtGui import QGuiApplication                          # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine                    # noqa: E402

from guard import protect_user_data                                # noqa: E402

protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from app.core import Core                                          # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def pump(ms):
    loop = QEventLoop()
    QTimer_single(ms, loop)
    loop.exec()


def QTimer_single(ms, loop):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(ms, loop.quit)


def wait_until(cond, ms=8000, step=80):
    spent = 0
    while spent < ms:
        if cond():
            return True
        pump(step)
        spent += step
    return cond()


def src(rel):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return open(os.path.join(root, rel), encoding="utf-8").read()


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    core = Core(app)
    globals()["_KEEP_CORE"] = core
    mods = core.mods

    print("\n-- 1. 工坊下载不再卡在「处理中」", flush=True)
    mm = src(os.path.join("app", "modmanager.py"))
    ws = src(os.path.join("qml", "components", "WorkshopPage.qml"))

    # emit 必须出现在 _expand_collections 之前
    seg = mm.split("def downloadWorkshopAsync", 1)[1].split("def _downloadable", 1)[0]
    pos_emit = seg.find("workshopDownloaded.emit")
    pos_expand = seg.find("_expand_collections")
    check("先 emit 再展开（不再同步阻塞 UI）",
          0 <= pos_emit < pos_expand, (pos_emit, pos_expand))
    check("emit 里带 expanding 标记", '"expanding": True' in seg)
    check("展开 + 排队跑在后台线程", "threading.Thread(target=prepare" in seg)
    check("排队成功会给 toast 指路下载页", "进度在下载页看" in seg)
    check("页面收到结果后清掉 pendingDeps", "page.pendingDeps = false" in ws)

    # 端到端：真要一次下载，看它是否很快回话并最终进队列
    mods._addons_dir = mods._addons_dir or "C:/tmp/addons_probe"
    got = []
    mods.workshopDownloaded.connect(lambda r: got.append(dict(r)))
    t0 = time.time()
    mods.downloadWorkshopAsync([{"id": "123456", "title": "测试工坊", "url": ""}])
    pump(400)
    elapsed = time.time() - t0
    check("立刻就有回话（<2 秒）", bool(got) and elapsed < 2.0,
          f"{len(got)} 条，用时 {elapsed:.2f}s")
    if got:
        check("回话是 ok + expanding", got[0].get("ok") is True
              and got[0].get("expanding") is True, got[0])

    # 等它真的进队列（会去联网解析直链，给宽一点，拿不到 url 也算进了）
    ok_queued = wait_until(lambda: core.downloads.totalCount > 0, ms=15000)
    check("最终进了下载队列", ok_queued, core.downloads.totalCount)
    for t in core.downloads.tasks:
        core.downloads.cancelTask(t["id"])
    wait_until(lambda: core.downloads.activeCount == 0, ms=10000)
    core.downloads.clearFinished()

    print("\n-- 2. 进服务器页自动刷新一次", flush=True)
    sp = src(os.path.join("qml", "components", "ServersPage.qml"))
    check("有 autoRefreshOnEnter", "function autoRefreshOnEnter(" in sp)
    check("在 onVisibleChanged 里触发", "onVisibleChanged" in sp
          and "page.autoRefreshOnEnter()" in sp)
    check("有 30 秒防抖", "autoRefreshCooldownMs" in sp and "30000" in sp)
    check("空列表不查", "serverCount === 0" in sp)
    check("正在查就不重复查", "page.mgr.busy" in sp)

    # 真加载界面，验证进页面确实查了一次、且切走切回不重复查
    eng = QQmlApplicationEngine()
    qdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "qml")
    eng.addImportPath(qdir)
    eng.addImportPath(os.path.join(qdir, "components"))
    eng.rootContext().setContextProperty("core", core)
    eng.load(QUrl.fromLocalFile(os.path.join(qdir, "Main.qml")))
    win = eng.rootObjects()[0]
    win.show()
    pump(800)

    mgr = core.servers
    mgr.clearAll()
    pump(200)
    win.setProperty("section", 3)
    pump(600)
    # 空列表：不该触发查询
    check("空列表进页面不查（statusText 没变成查询中）",
          "正在查询" not in mgr.statusText, mgr.statusText)

    mgr.saveServer({"addr": "42.193.137.24", "name": "宿舍常玩",
                    "weight": 0, "panels": []})
    pump(600)
    win.setProperty("section", 0)
    pump(400)

    calls = []
    import app.servers as S
    orig_refresh = S.ServerManager.refreshAll

    def spy(self):
        calls.append(time.time())
        return orig_refresh(self)

    S.ServerManager.refreshAll = spy
    try:
        win.setProperty("section", 3)
        pump(900)
        check("进页面自动查了一次", len(calls) == 1, len(calls))
        # 立刻切走再回来：防抖应拦住
        win.setProperty("section", 0)
        pump(300)
        win.setProperty("section", 3)
        pump(700)
        check("30 秒内切回来不重复查", len(calls) == 1, len(calls))
        # 手动点刷新永远立刻生效
        page = win.findChild(QObject, "serversPage")
        if page is not None:
            page.setProperty("_lastAutoRefresh", 0)
        mgr.refreshAll()
        pump(400)
        check("手动刷新永远立刻生效", len(calls) == 2, len(calls))
    finally:
        S.ServerManager.refreshAll = orig_refresh

    win.close()
    pump(200)
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "、".join(FAILS)), flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
