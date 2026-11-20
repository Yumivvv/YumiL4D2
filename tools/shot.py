"""截图工具：加载 Main.qml，抓取界面到 data/preview.png。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 测试会构造真的 Core()，必须先把运行时数据目录隔离到临时沙盒，
# 否则会覆盖用户真实的 config.json / library.json / 导入日期台账。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from guard import protect_user_data  # noqa: E402
protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QMetaObject, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.core import Core
from app.util import ROOT

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "preview.png")
MODE = sys.argv[2] if len(sys.argv) > 2 else "list"
# 可选的第三个参数：给 settings-* 当子模式（manual / custom），
# 给 workshop-detail 当工坊 ID（直接打开指定的那一条，验收简介用）。
EXTRA = sys.argv[3] if len(sys.argv) > 3 else ""


def log(*a):
    print(*a, flush=True)


def wait_ms(ms: int) -> None:
    """在 Qt 事件循环里等一会儿，让后台扫描线程的结果回到主线程。"""
    from PySide6.QtCore import QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    qml_dir = os.path.join(ROOT, "qml")
    engine.addImportPath(qml_dir)
    engine.addImportPath(os.path.join(qml_dir, "components"))

    warnings = []
    engine.warnings.connect(lambda ws: [warnings.append(w.toString()) for w in ws])

    core = Core(app)
    engine.rootContext().setContextProperty("core", core)
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
    if not engine.rootObjects():
        log("LOAD FAILED")
        for w in warnings:
            log("  ", w)
        return 1
    for w in warnings:
        if "Fixedsys" not in w:
            log("  WARN:", w)

    win = engine.rootObjects()[0]
    win.show()

    def prepare():
        if MODE in ("list", "detail", "settings", "player", "banner"):
            # 预览图要看真实列表，别被「只看新的」挡住（全部看完时会空着）
            core.setShowOnlyNew(False)
            win.setProperty("page", 0)
            wait_ms(200)
        if MODE == "detail":
            items = core.library.all_items()
            if items:
                bvid = items[0]["bvid"]
                win.openDetail(bvid)
        elif MODE == "player":
            items = core.library.all_items()
            if items:
                bvid = items[0]["bvid"]
                win.setProperty("playerOpen", True)
                core.playVideo(bvid)
        elif MODE == "settings":
            win.setProperty("section", 5)
            log("section =", win.property("section"))
        elif MODE == "mods":
            win.setProperty("section", 1)
            core.mods.scan()
            wait_ms(1500)
            log("mods section, dir =", core.mods.addonsDir,
                "local =", core.mods.localCount, "ws =", core.mods.workshopCount)
        elif MODE == "mods-selected":
            win.setProperty("section", 1)
            core.mods.scan()
            wait_ms(1200)
            win.setProperty("modsSelMode", True)
            core.mods.checkAllLocal(True)
            log("mods section, checked =", core.mods.checkedCount)
        elif MODE == "mods-filter":
            win.setProperty("section", 1)
            core.mods.scan()
            wait_ms(1500)
            core.mods.setSizeRange(1, 50)
            wait_ms(400)
            win.openModFilter()
            wait_ms(500)
            log("mods filter popup, local =", core.mods.localCount,
                "hidden =", core.mods.hiddenCount)
        elif MODE == "mods-sort":
            win.setProperty("section", 1)
            core.mods.scan()
            wait_ms(1500)
            core.mods.setSortMode(3)             # 优先看收藏，菜单里能看到勾
            wait_ms(400)
            win.openModSort()
            wait_ms(500)
            log("mods sort popup, sortMode =", core.mods.sortMode)
        elif MODE == "mods-disabled":
            win.setProperty("section", 1)
            core.mods.scan()
            wait_ms(1500)
            core.mods.setSortMode(0)
            core.mods.setSizeRange(0, 0)
            log("mods normal, local =", core.mods.localCount)
        elif MODE == "mods-detail":
            win.setProperty("section", 1)
            core.mods.scan()
            wait_ms(1800)
            # 优先挑一个查过工坊、有 tags 的，详情面板才好看（有分类 / 作者 / 订阅）
            items = core.mods.allModel.items()
            pick = next((m for m in items if m.get("workshopId") and m.get("tags")), None) \
                or next((m for m in items if m.get("hasImage")), None) \
                or (items[0] if items else None)
            if pick:
                core.mods.selectMod(pick["path"])
                log("mods detail:", pick.get("title"), "|", pick.get("categoryLabel"),
                    "|", pick.get("content"))
            wait_ms(600)
        elif MODE == "mods-order":
            # 加载顺序对话框：验收「深色模式下滚动条可见」
            win.setProperty("section", 1)
            core.mods.scan()
            wait_ms(1800)
            panel = win.findChild(QObject, "modPanelRoot")
            if panel is not None:
                QMetaObject.invokeMethod(panel, "openAddonOrder")
                wait_ms(1200)
                _ai = panel.property("addonItems")
                try:
                    _n = int(_ai.property("length")) if _ai is not None else -1
                except Exception:                      # noqa: BLE001
                    _n = -1
                log("addon order open, items =", _n)
            else:
                log("addon order: 没找到 modPanelRoot")
        elif MODE == "mods-workshop-new":
            # 演示「下载下来的工坊 MOD 自动识别」：沙盒里放两个 <ID>.vpk，
            # 跑一遍 _after_download()（真去工坊拿标题、下封面），再看管理器列表。
            import json
            import tempfile  # noqa: PLC0415

            ids = ["3727891945", "3829533320"]
            box = tempfile.mkdtemp(prefix="l4d2_shot_ws_")
            for wid in ids:
                with open(os.path.join(box, wid + ".vpk"), "wb") as f:
                    f.write(b"x" * 4096)
            core.mods.setAddonsDir(box)
            for _ in range(40):
                wait_ms(300)
                if not core.mods.busy:
                    break
            core.mods._after_download([{"id": i} for i in ids])
            win.setProperty("section", 1)
            core.mods.scan()
            wait_ms(1600)
            rows = core.mods.allModel.items()
            log("ws new:", json.dumps(
                [{"id": m.get("workshopId"), "title": (m.get("title") or "")[:24],
                  "cover": bool(m.get("hasImage"))} for m in rows],
                ensure_ascii=False))
            win.setProperty("section", 1)
            core.mods.scan()
            wait_ms(1800)
            items = core.mods.allModel.items()
            pick = next((m for m in items if m.get("inWorkshopDir")), None)
            if pick:
                core.mods.selectMod(pick["path"])
                log("ws detail:", pick.get("title"), "| inWorkshopDir =",
                    pick.get("inWorkshopDir"))
            else:
                log("  [warn] 没有创意工坊目录里的 MOD")
            wait_ms(600)
        elif MODE == "author":
            items = core.library.all_items()
            target = next((v for v in items if int(v.get("mid") or 0) > 0), None)
            if target:
                win.setProperty("authorOpen", True)
                win.setProperty("authorLoading", True)
                core.openAuthor(target["bvid"])
                log("author:", target["title"][:26])
                # 作者卡要等三路接口（space / 动态 / 昵称搜索）回来，加载态抓出来是骨架屏
                for _ in range(60):
                    wait_ms(500)
                    if not win.property("authorLoading"):
                        break
                wait_ms(700)
                log("  loaded =", not win.property("authorLoading"))
                shoot_later(400)
                return
        elif MODE == "import":
            win.setProperty("section", 1)
            log("import dialog preview")
        elif MODE == "toast":
            # 动作提示浮层：一次弹三种级别，看颜色对不对
            win.setProperty("section", 0)
            wait_ms(200)
            win.toast("已复制到剪贴板", "ok")
            wait_ms(120)
            win.toast("已把 132381280.vpk 放进回收站，删错了能还原", "warn")
            wait_ms(120)
            win.toast("已永久删除 469986973.vpk", "error")
            wait_ms(500)
            log("toast preview")
        elif MODE == "toast-import":
            win.setProperty("section", 1)
            wait_ms(2000)
            win.toast("已导入 3 个文件", "ok")
            wait_ms(400)
            log("toast import preview")
        elif MODE == "toast-long":
            win.setProperty("section", 0)
            wait_ms(1200)
            win.toast("3 个 MOD 被占用，未执行转换。游戏正在运行，请先完全关闭 Left 4 Dead 2 "
                      + "再重试。被占用的 MOD 是整组跳过的，不会出现 vpk 复制过去了、"
                      + "封面图没过去这种半套情况。", "warn")
            wait_ms(700)
            log("toast long preview")
        elif MODE == "toast-stack":
            win.setProperty("section", 0)
            wait_ms(1200)
            win.toast("已复制到剪贴板", "ok")
            wait_ms(160)
            win.toast("已把 132381280.vpk 放进回收站，删错了能还原", "warn")
            wait_ms(160)
            win.toast("已永久删除 469986973.vpk", "error")
            wait_ms(900)
            log("toast stack preview")
        elif MODE == "detail-comment":
            # 找一个有置顶评论的视频，打开详情
            core.setShowOnlyNew(False)
            win.setProperty("page", 0)
            wait_ms(600)
            pick = None
            for v in core.library.all_items():
                tc = v.get("topComment") or {}
                if tc.get("text"):
                    pick = v
                    break
            if pick:
                win.openDetail(pick["bvid"])
                wait_ms(2500)
                log("detail with comment:", pick["bvid"])
            else:
                # 现查一个
                from app.bili import BiliClient

                bc = BiliClient()
                for v in core.library.all_items()[:20]:
                    aid = int(v.get("aid") or 0)
                    if not aid:
                        continue
                    tc = bc.top_comment(aid, v["bvid"])
                    if tc.get("text"):
                        win.openDetail(v["bvid"])
                        log("detail with freshly-fetched comment:", v["bvid"])
                        break
                wait_ms(2500)
        elif MODE == "player-volume":
            win.setProperty("playerOpen", True)
            core.playVideo(core.library.all_items()[0]["bvid"])
            wait_ms(3500)
            log("player volume preview")
        elif MODE in ("servers", "servers-picked", "servers-add", "servers-direct"):
            win.setProperty("section", 3)
            wait_ms(400)
            mgr = core.servers
            if not mgr.serverCount:
                # 「加几个示例」已经从程序里去掉了（示例数据看着像真收藏，容易误导），
                # 截图脚本这里自己摆几条，不依赖产品代码里的常量。
                for demo in (
                    {"addr": "42.193.137.24:27015", "name": "宿舍常玩的那个", "weight": 5,
                     "panels": [{"url": "http://panel.example.com:8080",
                                 "password": "secret"}]},
                    {"addr": "82.156.195.10:27015", "name": "周末混战服", "weight": 0,
                     "panels": []},
                    {"addr": "46.174.51.126:27015", "name": "海外社区服", "weight": 1,
                     "panels": []},
                ):
                    mgr.saveServer(dict(demo))
            if mgr.onlineCount == 0:
                mgr.refreshAll()
            for _ in range(80):
                wait_ms(250)
                if not mgr.busy:
                    break
            log("servers", MODE, "count =", mgr.serverCount,
                "online =", mgr.onlineCount, "players =", mgr.totalPlayers,
                "status =", mgr.statusText)
            page = win.findChild(QObject, "serversPage")
            if MODE == "servers-picked" and page is not None and mgr.servers:
                page.selectServer(mgr.servers[0])
                for _ in range(60):
                    wait_ms(250)
                    if not page.property("playersLoading"):
                        break
                log("picked =", page.property("playersFor"),
                    "players =", len(page.property("players") or []))
                wait_ms(600)
            elif MODE in ("servers-add", "servers-direct") and page is not None:
                if EXTRA == "edit" and mgr.servers:
                    page.selectServer(mgr.servers[0])
                    wait_ms(300)
                    # 编辑既有条目：把地址、权重、面板都填上再看
                    if not mgr.saveServer({"addr": mgr.servers[0].get("addr"),
                                           "name": "我的常用服",
                                           "weight": 5,
                                           "panels": [{"url": "http://panel.example.com:8080",
                                                       "password": "secret"}]}).get("ok"):
                        log("saveServer failed")
                if MODE == "servers-add":
                    if EXTRA == "edit":
                        QMetaObject.invokeMethod(page, "openEdit", Qt.DirectConnection)
                    else:
                        QMetaObject.invokeMethod(page, "openAdd", Qt.DirectConnection)
                    # openAdd/openEdit 会把高级区折叠回去，所以要在它之后再展开
                    page.setProperty("formAdvanced", EXTRA in ("advanced", "edit"))
                else:
                    QMetaObject.invokeMethod(page, "openDirectDialog",
                                             Qt.DirectConnection)
                    wait_ms(200)
                    page.setProperty("directInput", "42.193.137.24")
                    QMetaObject.invokeMethod(page, "updateDirectPreview",
                                             Qt.DirectConnection)
                log("dialog open =", page.property("formOpen"),
                    "direct =", page.property("directOpen"),
                    "preview =", page.property("directPreview"))
                wait_ms(900)
        elif MODE in ("workshop", "workshop-detail", "workshop-collection",
                      "workshop-member", "workshop-later", "workshop-settings"):
            win.setProperty("section", 2)
            wait_ms(500)
            mgr = core.mods
            if MODE in ("workshop-collection", "workshop-member"):
                mgr.browseSetKind("collection")
                page0 = win.findChild(QObject, "workshopPage")
                if page0 is not None:
                    page0.setProperty("kind", "collection")
            for _ in range(80):
                wait_ms(250)
                if not mgr.browseLoading and mgr.browseItems:
                    break
            log("workshop", MODE, "loaded =", len(mgr.browseItems),
                "total =", mgr.browseTotal, "err =", mgr.browseError)
            # 封面是从本地代理拉的，多给点时间让图落进缓存
            wait_ms(2500)
            if MODE in ("workshop-detail", "workshop-collection", "workshop-member"):
                page = win.findChild(QObject, "workshopPage")
                items = mgr.browseItems
                if page is not None and items:
                    # 第三个参数可以给一个工坊 ID，直接打开那一条（验收简介用）
                    want_id = str(EXTRA).strip() if EXTRA else ""
                    pick = items[0]
                    if want_id.isdigit():
                        pick = next((x for x in items if str(x.get("id")) == want_id), None) or {
                            "id": want_id, "title": want_id}
                    t0 = time.time()
                    page.openDetail(pick)
                    # 等详情解析完（合集走 lite 快通道，正常几秒内）
                    for _ in range(60):
                        wait_ms(250)
                        if page.property("loadingDetail") is False:
                            break
                    # page.picked 是 JS 对象，PySide 拿回来不一定是 dict —— 简介长度
                    # 从 probeItems 里读（那是 QVariantList，稳定）。
                    # 合集：成员是一批一批回来的，等它列完再拍（这就是验收点）
                    # 注意 page.picked 是 QML 的 JS 对象，PySide 拿回来**不是 dict**，
                    # 所以判据从 probeItems 里读（那是 QVariantList，稳定）。
                    pitems0 = page.property("probeItems") or []
                    is_coll = bool(pitems0) and pitems0[0].get("isMember") is True
                    if is_coll or int(page.property("memberTotal") or 0) > 0:
                        for _ in range(120):
                            wait_ms(250)
                            if page.property("membersDone") is True:
                                break
                        log("members =", page.property("memberCount"),
                            "/", page.property("memberTotal"),
                            "done =", page.property("membersDone"))
                        # 成员封面也要从本地代理拉，留点时间让前几张落进缓存
                        wait_ms(2200)
                    pitems = page.property("probeItems") or []
                    pdesc = (pitems[0].get("desc") if pitems else "") or ""
                    # 统计数字（浏览/订阅/收藏/日期）是另开一次官方接口拿的，
                    # 比详情晚回来；不等它就把「统计胶囊」拍成空白（踩过）。
                    # 注意 pickedStats 是 QML 的 var（JS 对象），PySide 拿回来
                    # 可能是 dict 也可能是 QJSValue，两种都要能判。
                    for _ in range(24):
                        st = page.property("pickedStats")
                        got = bool(st) if isinstance(st, dict) else False
                        if not got and st is not None and hasattr(st, "property"):
                            got = bool(st.property("viewsText") or st.property("updatedText"))
                        if got:
                            break
                        wait_ms(250)
                    picked = page.property("picked")
                    log(f"detail open = {page.property('detailOpen')} "
                        f"cost = {time.time() - t0:.1f}s "
                        f"| {pick.get('title')} "
                        f"| 简介 = {len(pdesc)} 字 "
                        f"| isCollection = {picked.get('isCollection') if isinstance(picked, dict) else '?'}")
                    # workshop-member：从合集里再点进一个成员，
                    # 验收「返回合集」那条和重复标记
                    if MODE == "workshop-member":
                        members = page.property("memberItems") or []
                        if members:
                            page.openDetail(members[0])
                            for _ in range(40):
                                wait_ms(250)
                                if page.property("loadingDetail") is False:
                                    break
                            wait_ms(1500)
                            _st = page.property("detailStack")
                            try:
                                _n = int(_st.property("length")) if _st is not None else 0
                            except Exception:                     # noqa: BLE001
                                _n = -1
                            log("member open =", page.property("detailOpen"),
                                "stack =", _n, "|", members[0].get("title"))
                        else:
                            log("member open: 没有成员可点")
            elif MODE == "workshop-later":
                for it in mgr.browseItems[:6]:
                    mgr.toggleLater(it["id"])
                wait_ms(400)
                page = win.findChild(QObject, "workshopPage")
                if page is not None:
                    page.setProperty("showLater", True)
                wait_ms(1200)
                log("later =", mgr.laterCount)
            elif MODE == "workshop-settings":
                win.setProperty("section", 5)
                wait_ms(900)
                log("settings + workshop")
        elif MODE in ("settings-net", "settings-dns"):
            # 第三个参数可以带 "manual" / "custom"，把对应的输入框也拍进去
            extra = EXTRA
            win.setProperty("section", 5)
            wait_ms(800)
            if MODE == "settings-net" and extra == "manual":
                core.mods.setCdnMode("manual")
                core.mods.setCdnIp("23.59.72.59")
                wait_ms(400)
            if MODE == "settings-dns" and extra == "custom":
                core.mods.setDnsMode("custom")
                core.mods.setDnsCustom("119.29.29.29")
                wait_ms(400)
            flick = win.findChild(QObject, "settingsFlick")
            col = win.findChild(QObject, "settingsCol")
            sec = win.findChild(QObject, "netAccelSection" if MODE == "settings-net"
                                             else "workshopDnsSection")
            if flick is not None and col is not None and sec is not None:
                # 把目标段滚进视野。它就是 Column 的直接子项，
                # 它的 y 已经相对列顶；用 mapToItem 反而要 QQuickItem 包装，麻烦。
                y = float(sec.property("y") or 0.0)
                flick.setProperty("contentY", max(0.0, y - 90))
                wait_ms(600)
                log(MODE, "section y =", round(y, 1),
                    "contentY =", round(flick.property("contentY"), 1),
                    "extra =", extra or "-")
            else:
                log("  [warn] 没找到 settingsFlick / settingsCol /",
                    "netAccelSection" if MODE == "settings-net" else "workshopDnsSection",
                    flick is not None, col is not None, sec is not None)
            wait_ms(400)
        elif MODE == "settings-credit":
            # 设置 → 关于 → 致谢（「关于」是最后一节，直接滚到底）
            win.setProperty("section", 5)
            wait_ms(900)
            flick = win.findChild(QObject, "settingsFlick")
            box = win.findChild(QObject, "creditBox")
            if flick is not None:
                # 滚到底：致谢就在「关于」卡片里，靠底部
                for _ in range(3):
                    h = float(flick.property("contentHeight") or 0)
                    vh = float(flick.property("height") or 0)
                    flick.setProperty("contentY", max(0.0, h - vh))
                    wait_ms(350)
                log("settings-credit", "contentY =",
                    round(float(flick.property("contentY") or 0), 1),
                    "box 找到 =", box is not None)
            else:
                log("  [warn] 没找到 settingsFlick")
            wait_ms(500)
        elif MODE == "settings-accent":
            # 主题色取色面板（色盘）：滚到那一块再拍
            win.setProperty("section", 5)
            wait_ms(900)
            flick = win.findChild(QObject, "settingsFlick")
            sec = win.findChild(QObject, "accentSection")
            if flick is not None and sec is not None:
                y = float(sec.property("y") or 0.0)
                flick.setProperty("contentY", max(0.0, y - 70))
                wait_ms(700)
                log("accent section y =", round(y, 1),
                    "contentY =", round(flick.property("contentY"), 1))
            else:
                log("  [warn] 没找到 settingsFlick / accentSection",
                    flick is not None, sec is not None)
            wait_ms(400)
        elif MODE == "settings-top":
            win.setProperty("section", 5)
            wait_ms(900)
            log("settings top preview")
        elif MODE == "toast-delete":
            # 设置里选「直接删除」时的红色提示
            win.setProperty("section", 1)
            wait_ms(2000)
            win.toast("已永久删除 469986973.vpk", "error")
            wait_ms(250)
            win.toast("3 个 MOD 被占用，未执行转换。游戏正在运行，请先完全关闭 Left 4 Dead 2 再重试",
                      "warn")
            wait_ms(500)
            log("toast delete preview")
        elif MODE == "sounds":
            win.setProperty("section", 5)
            wait_ms(900)
            # 设置抽屉里的「提示音效」区在中间偏下，滚过去
            log("sound settings preview")
        elif MODE in ("downloads", "downloads-empty", "downloads-mixed"):
            # 下载页截图：自己造几条任务，不真的去下载东西
            win.setProperty("section", 4)
            wait_ms(500)
            dq = core.downloads
            dq.clearFinished()

            if MODE != "downloads-empty":
                import time as _t

                from app.downloads import (
                    CANCELED, DONE, FAILED, RUNNING, DownloadTask,
                )

                def fake(tid_title, kind, status, done, total, err="", speed=0.0):
                    t = DownloadTask(kind, tid_title, dest="C:/tmp",
                                     payload={"id": "1"})
                    dq._add(t)
                    t.status = status
                    t.done = done
                    t.total = total
                    t.speed = speed
                    t.error = err
                    if status in (DONE, FAILED, CANCELED):
                        t.finishedAt = _t.time()
                    return t

                fake("AK47-元让（常态版本）替换", "mod", DONE, 41_400_000, 41_400_000)
                fake("蔚蓝档案 冰室濑名 黑色行动7", "mod", RUNNING,
                     18_600_000, 52_000_000, speed=3_600_000)
                if MODE == "downloads-mixed":
                    fake("漆黑之刃 武士刀替换", "video", FAILED, 2_100_000,
                         9_800_000, err="视频服务器返回 503，稍后再试")
                    fake("塔露拉 黑伤替换砍刀", "mod", RUNNING,
                         6_000_000, 30_000_000, speed=1_200_000)
                dq._changed()
                wait_ms(500)
            log("downloads", MODE, "count =", dq.totalCount,
                "active =", dq.activeCount, "summary =", dq.summaryText)
        elif MODE == "banner":
            win.pendingNew = [{"title": "测试：发现新视频时的应用内提示条"}]
            win.updateBanner()

        shoot_later()

    def shoot():
        # 启动扫描结束后程序会自己跳到「新视频」页，抓图前再压一次，保证预览是「全部视频」
        if MODE in ("list", "detail", "settings"):
            core.setShowOnlyNew(False)
            win.setProperty("page", 0)
            wait_ms(300)
        if MODE == "detail":
            # 上面切页会触发「切页自动收起详情」，所以这里再开一次
            items = core.library.all_items()
            if items:
                win.openDetail(items[0]["bvid"])
                wait_ms(800)
        # 有 Popup 的模式要连 overlay 一起抓，frame.grabToImage 抓不到弹窗
        if MODE in ("servers-add", "servers-direct"):
            win.grabWindowShot(OUT)
        else:
            win.grabPreview(OUT)
        QTimer.singleShot(1200, finish)

    def shoot_later(ms: int = 1400):
        """prepare 里可能有阻塞等待，抓图时间要跟着往后推，不能写死。"""
        QTimer.singleShot(ms, shoot)

    def finish():
        log("saved:", os.path.exists(OUT), OUT)
        app.quit()

    def prepare_guarded():
        # prepare 里出异常时以前会卡死在这里（抓图回调根本没被挂上，事件循环空转）。
        # 现在出错也照样抓一张，至少能看到界面当前的样子。
        try:
            prepare()
        except Exception as e:  # noqa: BLE001
            log("prepare failed:", repr(e))
            shoot_later(200)

    QTimer.singleShot(1200, prepare_guarded)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
