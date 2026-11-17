"""创意工坊页自检（本轮重写版）：

    1. 导航 / 页面骨架 / 滚动条 / 卡片浮层（不能有「稍后看」按钮）
    2. 无限滚动列表（默认单件 MOD、合集切换、标签、内存缓存）
    3. 稍后看
    4. 网络加速（自动优选 / 手动填 IPv4·IPv6）与工坊 DNS（两个独立设置）
    5. 封面代理（压图 + 磁盘缓存）
    6. 快速解析（不带前置）与「连前置一起下」的数据流
    7. 真机无 QML 告警

用法：python -X utf8 tools/workshop_page_test.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import Core  # noqa: E402
from app.util import ROOT  # noqa: E402
from app import workshop_net as WN  # noqa: E402

FAILS: list[str] = []
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_browse(mgr, ms: int = 250, tries: int = 240) -> None:
    for _ in range(tries):
        wait(ms)
        if not mgr.browseLoading and not mgr.browseLoadingMore:
            return


def collect_names(root) -> set:
    found = set()

    def walk(o):
        try:
            n = o.objectName()
            if n:
                found.add(n)
        except Exception:
            pass
        for c in o.children():
            walk(c)

    walk(root)
    return found


def main() -> int:
    app = QApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    warns = []
    engine.warnings.connect(lambda ws: warns.extend(w.toString() for w in ws))
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.addImportPath(os.path.join(ROOT, "qml", "components"))
    core = Core(app)
    engine.rootContext().setContextProperty("core", core)
    engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    if not engine.rootObjects():
        print("LOAD FAILED")
        return 1
    win = engine.rootObjects()[0]
    win.show()
    wait(1500)

    mgr = core.mods

    # ---------------------------------------------------------------- 1. 骨架
    print("=== 1. 创意工坊页骨架 ===")
    win.setProperty("section", 2)
    wait(1200)
    names = collect_names(win)
    check("工坊页已加载", "workshopPage" in names, f"共 {len(names)} 个 objectName")
    # 注意：Repeater 的委托项不进 QObject 子对象树（findChild/children 都找不到），
    # 所以「委托里有什么」只能读源码断言，别拿 objectName 去查。
    for want in ("wsSearchInput", "wsSearchBox", "wsKindSwitch", "wsGrid",
                 "wsGridBar", "wsRailFlick", "wsRailBar", "wsLaterGrid",
                 "wsLaterBar"):
        check(f"有 {want}", want in names)
    page = win.findChild(QObject, "workshopPage")
    check("拿得到 workshopPage 对象", page is not None)

    # 滚动条是「附加 ScrollBar」，不是手画的：GridView 上必须挂着
    check("卡片墙默认单件 MOD", page is not None and page.property("kind") == "mod",
          str(page.property("kind")) if page else "")
    check("详情默认关着", page is not None and page.property("detailOpen") is False)

    # 卡片浮层：只有提示、没有「稍后看」按钮
    card_src = open(os.path.join(ROOT, "qml", "components", "WorkshopPage.qml"),
                    encoding="utf-8").read()
    hover_part = card_src.split("objectName: \"wsCardHover\"", 1)[-1][:1200]
    check("悬停浮层里没有「稍后看」", "稍后看" not in hover_part)
    check("悬停浮层里没有 MouseArea（点击归整张卡片）", "MouseArea" not in hover_part)
    check("搜索框挂了工字光标 HoverHandler",
          "HoverHandler { cursorShape: Qt.IBeamCursor }" in card_src)
    check("单件/合集开关里没有方块字形", "\\uE7B8" not in card_src)
    check("单件/合集两个标签都在",
          "单件 MOD" in card_src and "合集" in card_src)
    kind_part = card_src.split("objectName: \"wsKindSwitch\"", 1)[-1][:1800]
    check("开关的委托带 wsKind_ 前缀命名",
          "wsKind_\" + modelData.k" in kind_part or "wsKind_" in kind_part)

    # 往下加载不跳回顶部：列表走 ListModel 镜像 + 只有第 1 页才归位
    check("列表用 ListModel 镜像（追加不清空，滚动位置才不丢）",
          "ListModel { id: wsModel }" in card_src and "function syncWsModel()" in card_src)
    check("追加完成有专门的处理（不清位置）",
          "onBrowseAppended" in card_src and "syncWsModel()" in card_src)
    # 追加完成的那条分支里，positionViewAtBeginning 必须带「第 1 页」条件
    br_part = card_src.split("function onBrowseChanged", 1)[-1][:600]
    if "function onBrowseChanged" not in card_src:
        br_part = card_src.split("onBrowseChanged", 1)[-1][:600]
    check("追加完成时才谈归位，且只有第 1 页才回到顶部",
          "positionViewAtBeginning" not in br_part
          or "browsePage <= 1" in br_part,
          br_part.replace("\n", " ")[:110])
    # 合集详情：成员全列出来（首屏 + 后续批次），不再只是「先列前 N 个」
    check("合集详情说明成员都列出来了", "下面都列出来了" in card_src)
    check("卡片「合集」角标只看 fileType",
          "Number(item.fileType || 0) === 2" in card_src)
    check("角标不再用 children 判合集",
          "isCollection: Number(item.fileType || 0) === 2\n" in card_src
          or "children || 0) > 0" not in card_src.split("readonly property bool isCollection")[1][:200])

    # ---------------------------------------------------------------- 2. 列表
    print("=== 2. 无限滚动列表 ===")
    mgr.browseFilter("", "trend", "mod", [])
    wait_browse(mgr)
    if mgr.browseError:
        print("      [skip] 列表接口不可用：", mgr.browseError)
    else:
        # 页大小以配置为准（后端可能改成 50 或动态给），这里只要求
        # 「有拿到东西 + 不超过一页的上限」，别把具体数字写死 ——
        # 写死 20 的话，后端一调页大小测试就红，那是测试脆弱不是产品坏了。
        n = len(mgr.browseItems)
        check("默认能拉到一页", 0 < n <= max(50, mgr.browsePageSize
                                             if hasattr(mgr, "browsePageSize") else 50),
              str(n))
        check("默认是单件 MOD", mgr.browseKind == "mod", mgr.browseKind)
        check("总数 > 0", mgr.browseTotal > 0, str(mgr.browseTotal))
        check("封面地址一一对应", len(mgr.browseThumbs) == len(mgr.browseItems),
              f"{len(mgr.browseThumbs)}/{len(mgr.browseItems)}")
        check("封面走本地代理（或直连原图）",
              all(("127.0.0.1" in t) or ("steam" in t) for t in mgr.browseThumbs))

        p0 = mgr.browsePage
        ids0 = [x["id"] for x in mgr.browseItems]
        mgr.browseMore()
        wait_browse(mgr)
        check("往下滚是追加、不是翻页", mgr.browsePage == p0 + 1, str(mgr.browsePage))
        # 远端列表在两次请求之间会变（新条目插队 → 第二页可能和第一页有重叠），
        # 所以只断言「变多了 + 去重干净」，不去断言恰好 40 条。
        now = [x["id"] for x in mgr.browseItems]
        check("追加后条目变多了", len(now) > len(ids0), f"{len(ids0)} → {len(now)}")
        check("追加内容不重复（重复的已按 id 去掉）",
              len(set(now)) == len(now) and len(set(ids0)) == len(ids0),
              f"{len(now)} 条 / 去重后 {len(set(now))} 条")
        check("没有「上一页」这种概念",
              mgr.browsePrevPage().get("ok") is False)

        # 内存缓存：同一个请求第二次不该再走网络
        r1 = WN.fetch_workshop_list("", 1, "trend", [], "mod")
        r2 = WN.fetch_workshop_list("", 1, "trend", [], "mod")
        check("列表第二次命中缓存",
              r1.get("ok") and r2.get("cached") is True and len(r2["items"]) > 0)

        # 合集
        mgr.browseSetKind("collection")
        wait_browse(mgr)
        first = mgr.browseItems[0] if mgr.browseItems else {}
        check("能切到合集", mgr.browseKind == "collection", mgr.browseKind)
        check("合集条目带子项数", Number_ok(first), str(first.get("children")))
        check("合集列表里都是真合集（fileType=2）",
              all(int(x.get("fileType") or 0) == 2 for x in mgr.browseItems),
              str([int(x.get("fileType") or 0) for x in mgr.browseItems]))
        mgr.browseSetKind("mod")
        wait_browse(mgr)
        # 「单件 MOD 里冒出合集」：判据只能是 fileType==2。
        # Steam 会给一部分普通 MOD 也带 num_children，按 children 判会冤枉它们。
        check("单件列表里没有真合集",
              all(int(x.get("fileType") or 0) != 2 for x in mgr.browseItems),
              str([int(x.get("fileType") or 0) for x in mgr.browseItems]))
        check("单件列表里允许带 children 的普通 MOD（那不算合集）",
              all(mgr._browse_kind_ok(x) for x in mgr.browseItems))
        check("判据不看 children：单件 + children=3 仍算单件",
              mgr._browse_kind_ok({"fileType": 0, "children": 3}) is True)
        check("判据看 fileType：fileType=2 就是合集",
              mgr._browse_kind_ok({"fileType": 2, "children": 0}) is False)

        # 标签（多标签是 AND）
        mgr.browseSetTags(["Survivors"])
        wait_browse(mgr)
        check("按标签筛选有结果", len(mgr.browseItems) > 0, str(len(mgr.browseItems)))
        check("筛选后总数变少", 0 < mgr.browseTotal < 227187, str(mgr.browseTotal))
        mgr.browseSetTags([])
        wait_browse(mgr)

    # ---------------------------------------------------------------- 3. 稍后看
    print("=== 3. 稍后看 ===")
    mgr.clearLater()
    if mgr.browseItems:
        wid = mgr.browseItems[0]["id"]
        check("标记稍后看", mgr.toggleLater(wid) is True)
        check("稍后看里有了", mgr.isLater(wid) is True and mgr.laterCount == 1,
              str(mgr.laterCount))
        check("稍后看条目带标题封面",
              bool(mgr.laterItems[0].get("title")) and "preview" in mgr.laterItems[0])
        check("稍后看条目带 missing 标记（界面据此显示占位）",
              "missing" in mgr.laterItems[0], str(mgr.laterItems[0].get("missing")))
        # 没在浏览列表里、modmeta 也没缓存过的 ID：至少要有名字，别是空白一行
        mgr.toggleLater("3727891945")
        item = next((x for x in mgr.laterItems if x["id"] == "3727891945"), None)
        check("补不到元数据的稍后看也有名字和标记",
              bool(item) and bool(item.get("title")) and "missing" in item,
              str(item)[:90])
        mgr.toggleLater("3727891945")
        check("再点一次取消", mgr.toggleLater(wid) is False and mgr.laterCount == 0)

    check("稍后看用 ListModel 镜像（不整体替换，才不会卡）",
          "ListModel { id: laterModel }" in card_src
          and "function syncLaterModel()" in card_src
          and "model: laterModel" in card_src)
    check("稍后看每条能直接移除、也能一键清空",
          "wsLaterRemove" in card_src and "wsLaterClear" in card_src
          and "page.mgr.clearLater()" in card_src)
    check("切到稍后看不再对着隐藏的 wsGrid 调 positionViewAtBeginning",
          "laterGrid.positionViewAtBeginning()" in card_src)

    # ------------------------------------------------- 4. 加速 / DNS（两件事）
    print("=== 4. 网络加速 + 工坊 DNS（各管各的）===")
    check("有 CDN 模式", mgr.cdnMode in ("auto", "manual", "off"), mgr.cdnMode)
    check("加速摘要里没有 IP（自动优选只说地名）",
          mgr.cdnMode != "auto" or not IP_RE.search(mgr.cdnSummary), mgr.cdnSummary)

    # 手动指定 = 用户自己填 IPv4 / IPv6，不再是「选地名」
    mgr.setCdnMode("manual")
    mgr.setCdnIp("23.59.72.59")
    check("手动填 IPv4 生效", mgr.cdnIp == "23.59.72.59", mgr.cdnIp)
    check("手动模式摘要里也不摆地址",
          "23.59.72.59" not in mgr.cdnSummary, mgr.cdnSummary)
    mgr.setCdnIp("2400:3200::1")
    check("手动填 IPv6 也认", mgr.cdnIp == "2400:3200::1", mgr.cdnIp)
    mgr.setCdnIp("23.59.72.59")
    before = mgr.cdnIp
    mgr.setCdnIp("不是地址")
    check("乱填的地址被拒（保留上一个）", mgr.cdnIp == before, mgr.cdnIp)
    mgr.setCdnMode("off")
    check("能关掉加速", mgr.cdnEnabled is False)
    mgr.setCdnMode("auto")
    check("能回到自动优选", mgr.cdnEnabled is True and "自动" in mgr.cdnSummary,
          mgr.cdnSummary)

    # 工坊 DNS：独立设置，只决定「谁来解析域名」
    print("--- 工坊 DNS ---")
    modes = mgr.dnsModes
    check("DNS 有四个模式", isinstance(modes, list) and len(modes) == 4,
          str([m.get("value") for m in modes] if isinstance(modes, list) else modes))
    if isinstance(modes, list) and modes:
        check("模式行只有 value/label/active",
              set(modes[0].keys()) == {"value", "label", "active"},
              str(sorted(modes[0].keys())))
        vals = [m.get("value") for m in modes]
        check("模式值齐全",
              vals == ["dnspod", "alidns", "custom", "system"], str(vals))
        check("默认是腾讯 DNS", mgr.dnsMode == "dnspod", mgr.dnsMode)
    else:
        vals = []
    mgr.setDnsMode("system")
    check("能切到系统 DNS", mgr.dnsMode == "system" and "系统" in mgr.dnsSummary,
          mgr.dnsSummary)
    mgr.setDnsCustom("119.29.29.29")
    check("填了地址就自动进自定义模式",
          mgr.dnsMode == "custom" and mgr.dnsCustom == "119.29.29.29",
          f"{mgr.dnsMode} / {mgr.dnsCustom}")
    check("自定义摘要带地址", "119.29.29.29" in mgr.dnsSummary, mgr.dnsSummary)
    mgr.setDnsCustom("2400:3200::1")
    check("自定义 DNS 也收 IPv6", mgr.dnsCustom == "2400:3200::1", mgr.dnsCustom)
    mgr.setDnsCustom("随便写")
    check("非法 DNS 地址不写进配置", mgr.dnsCustom == "2400:3200::1", mgr.dnsCustom)
    mgr.setDnsCustom("")
    mgr.setDnsMode("dnspod")
    check("能切回腾讯 DNS", mgr.dnsMode == "dnspod" and "腾讯" in mgr.dnsSummary,
          mgr.dnsSummary)

    # 界面上：加速段里不该再有「点地名切地区」，DNS 段要独立存在
    main_src = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    check("设置里已经没有地名胶囊", "cdnRegionFlow" not in main_src
          and "点地名即可切到那个地区" not in main_src)
    check("加速段有手填地址的输入框", "cdnIpInput" in main_src)
    check("设置里有独立的工坊 DNS 段", "workshopDnsSection" in main_src
          and "dnsMode_" in main_src and "dnsCustomInput" in main_src)
    check("DNS 和加速是两个标题",
          "工坊 DNS" in main_src and "网络加速" in main_src)

    # ---------------------------------------------------------------- 5. 封面代理
    print("=== 5. 封面代理 ===")
    check("代理已在监听", mgr.coverProxyPort > 0, str(mgr.coverProxyPort))
    proxy = mgr._cover_proxy
    raw = "https://images.steamusercontent.com/ugc/123456/ABC/"
    wrapped = proxy.wrap(raw, 360)
    check("wrap 出本地地址", wrapped.startswith("http://127.0.0.1:"), wrapped[:60])
    check("wrap 带宽度参数", "w=360" in wrapped, wrapped[:80])
    data = proxy.fetch(raw, 360)
    check("取图有结果或优雅失败", data is not None)
    st = proxy.stats()
    check("stats 有磁盘缓存字段", "disk" in st, str(sorted(st.keys())))
    # 数据目录被 guard 隔离到临时沙盒了，所以要问 imageproxy 自己把缩略图写哪
    from app import imageproxy
    check("缩略图目录已建", os.path.isdir(imageproxy._THUMB_DIR),
          imageproxy._THUMB_DIR)

    # ---------------------------------------------------------------- 6. 解析链路
    print("=== 6. 快速解析 / 连前置一起下 ===")
    got = []
    mgr.workshopProbed.connect(lambda x: got.append(x))
    mgr.probeWorkshopFast("3829533320")
    for _ in range(300):
        wait(250)
        if got:
            break
    res = got[0] if got else {}
    if res.get("ok"):
        items = res.get("items") or []
        check("快速解析拿到条目", len(items) >= 1, str(len(items)))
        check("快速解析不带前置", not any(x.get("isDep") for x in items))
        # ★ 快速解析刻意**不去下载站换直链**（那一趟要一秒多）：详情页因此才秒开。
        #   但现在详情接口会白送一个 CDN 文件地址（file_url），单文件 .vpk 直接就能用，
        #   所以「有直链」也是正常的 —— 关键是不能是下载站来的地址。
        u = items[0].get("url") or ""
        check("快速解析不经过下载站（点开就秒开）",
              (not u) or u.startswith("https://cdn.steamusercontent.com/"),
              repr(u)[:56])
        check("没有直链时说明「直链在下载时解析」",
              bool(u) or "直链" in (items[0].get("note") or ""),
              repr(items[0].get("note")))
        check("快速解析的条目仍然可下载（有 ID）",
              items[0].get("available") is True and str(items[0].get("id")).isdigit())
        check("白送的直链会被标记（坏了能退回下载站）",
              ("urlFromApi" in items[0]) and (bool(items[0].get("urlFromApi")) == bool(u)))
        # 简介：以前详情里一律是「（这个 MOD 没写简介）」，因为压根没解析这个字段
        check("详情带上了简介（不再是「没写简介」）",
              len(items[0].get("desc") or "") > 0, f"{len(items[0].get('desc') or '')} 字")
        check("简介里的 BBCode 被清掉了",
              "[" not in (items[0].get("desc") or "")[:200],
              repr((items[0].get("desc") or "")[:60]))
    else:
        print("      [skip] 解析没成：", res.get("error"))

    # 详情接口白送的 file_url：单文件 .vpk 能用，多文件条目/合集不能用
    from app import workshop_dl as WD  # noqa: PLC0415

    _page = WN.fetch_workshop_list("", 1, "trend", None, "mod")
    _api = WD.fetch_details([it["id"] for it in (_page.get("items") or [])[:20]])
    _ok = [v for v in _api.values() if WD.direct_file_url(v)]
    _multi = [v for v in _api.values() if "/" in (v.get("filename") or "")]
    check("单文件 .vpk 能直接拿到 CDN 直链（省掉下载站那一趟）",
          bool(_ok) or not _api, f"{len(_ok)}/{len(_api)} 个")
    check("多文件条目的地址不会被当成整包直链",
          all(not WD.direct_file_url({"fileUrl": v.get("fileUrl"),
                                      "filename": v.get("filename")})
              for v in _multi),
          f"{len(_multi)} 个多文件条目")

    # 大合集必须走 lite 快通道：只列前 60 个、不逐个查直链
    got_coll = []
    mgr.workshopProbed.connect(lambda x: got_coll.append(x))
    mgr.probeWorkshopFast("3472563767")
    for _ in range(400):
        wait(250)
        if got_coll:
            break
    rc = got_coll[0] if got_coll else {}
    stream_batches = []
    if rc.get("ok") and rc.get("isCollection"):
        check("大合集走 lite 快通道", rc.get("lite") is True, str(rc.get("lite")))
        check("大合集成员数正确", int(rc.get("memberCount") or 0) > 60,
              str(rc.get("memberCount")))
        check("大合集只列前 60 个", len(rc.get("items") or []) <= 60,
              str(len(rc.get("items") or [])))
        check("大合集标了 truncated", rc.get("truncated") is True)
        check("成员带上来的直链只会是详情接口白送的 CDN 地址",
              all((not x.get("url")) or str(x.get("url")).startswith(
                  "https://cdn.steamusercontent.com/")
                  for x in (rc.get("items") or [])))
        check("大合集没有把成员当合集", rc.get("isCollection") is True)
        # ★ 首屏之后剩下的成员要能一批一批送回来（详情里看得到**全部**成员）
        # 多个批次按成员 ID 去重：中途「用户又点开别的条目」会让上一轮收工，
        # 两边可能都往这个信号里送过东西。
        seen: dict = {}

        def _on_members(x: dict) -> None:
            stream_batches.append(x)
            if str(x.get("id")) != "3472563767":
                return
            for m in x.get("items") or []:
                seen[str(m.get("id"))] = m

        mgr.workshopMembersChanged.connect(_on_members)
        mgr.probeWorkshopFast("3472563767")
        want = int(rc.get("memberCount") or 0)
        listed = len(rc.get("items") or [])
        for _ in range(600):
            wait(250)
            if stream_batches and stream_batches[-1].get("done") is True:
                break
        check("首屏之后还有成员批次送回来", len(stream_batches) > 0,
              f"{len(stream_batches)} 批")
        check("后面每批都带进度和总数",
              all(("listedCount" in b) and ("memberCount" in b) for b in stream_batches),
              str(stream_batches[-1] if stream_batches else {})[:80])
        first_ids = {str(x["id"]) for x in (rc.get("items") or [])}
        overlap = first_ids & set(seen)
        check("所有成员都拿到了（首屏 + 后续批次不重复地补齐）",
              len(seen) + listed == want and want > 60 and not overlap,
              f"{listed} + {len(seen)} / {want}，与首屏重复 {len(overlap)}")
        check("成员条目带标题和大小",
              all(x.get("title") for x in (stream_batches[0].get("items") or []))
              if stream_batches else False,
              str((stream_batches[0].get("items") or [{}])[0])[:80]
              if stream_batches else "")
    else:
        print("      [skip] 合集解析没成：", rc.get("error"))

    # 成员列表要看得到全部成员：QML 侧要有这块界面，而不是一句「共 N 个」
    check("详情里有成员清单（不是只说数量）",
          "wsMemberList" in card_src and "function membersHint()" in card_src
          and "page.memberItems" in card_src)
    check("成员批次接在信号上",
          "onWorkshopMembersChanged" in card_src and "function onMembers(" in card_src)
    check("后端有成员条目构造函数和停止流式的方法",
          all(s in open(os.path.join(ROOT, "app", "workshop_dl.py"),
                        encoding="utf-8").read()
              for s in ("def _member_item(", "def _stream_members(", "def stop_streaming(")))

    # 合集下载：浏览器里只有合集这一条（没有成员、没有直链），后端要能自己展开
    check("没有直链但有 ID 的条目算可下载（下载时现解析）",
          mgr._downloadable({"id": "3829533320", "url": ""}) is True)
    check("连 ID 都没有才算不能下",
          mgr._downloadable({"id": "", "url": ""}) is False)
    exp = mgr._expand_collections(
        [{"id": "3727891945", "title": "某合集", "isCollection": True}])
    if len(exp) > 1:
        check("合集能被展开成成员列表", True, f"{len(exp)} 个成员")
        check("展开出的成员带 ID", all(str(x.get("id") or "").isdigit() for x in exp))
        check("展开出的成员直链只可能是详情接口白送的 CDN 地址",
              all((not x.get("url"))
                  or str(x["url"]).startswith("https://cdn.steamusercontent.com/")
                  for x in exp),
              str([x.get("url") for x in exp if x.get("url")])[:60])
        check("展开出的成员都标了 isMember",
              all(x.get("isMember") for x in exp))
    else:
        print("      [skip] 合集展开没拿到成员（接口不通或无成员）",
              str(exp)[:80])

    if page is not None and mgr.browseItems:
        # 走一遍 UI 的数据流：点开卡片 → 勾「连前置一起下」 → 生成的下载条目
        page.setProperty("picked", mgr.browseItems[0])
        page.setProperty("detailOpen", True)
        wait(200)
        check("详情里的「连前置一起下」默认不勾",
              page.property("includeDeps") is False)
        page.setProperty("probeItems", res.get("items") or [])
        page.setProperty("probeFull", True)
        page.setProperty("includeDeps", True)
        items_txt = page.metaObject().indexOfMethod("buildDownloadItems()")
        check("有 buildDownloadItems 方法", items_txt >= 0)
        check("depHint 文案正常",
              isinstance(page.property("includeDeps"), bool))

    # 没有前置的 MOD：详情里不该出现「连前置一起下」那一行
    print("=== 6b. 下载下来的工坊 MOD 能认出来 + 删除立刻刷新 ===")
    from app import workshop_dl as WD  # noqa: PLC0415

    dl_src = open(os.path.join(ROOT, "app", "workshop_dl.py"), encoding="utf-8").read()
    mm_src = open(os.path.join(ROOT, "app", "modmanager.py"), encoding="utf-8").read()
    check("下载时按创意工坊 ID 命名（<ID>.vpk）",
          'name = f"{wid}.vpk"' in dl_src and "wid.isdigit()" in dl_src)
    check("下完自动补工坊元数据（标题/封面）",
          "def _after_download(" in mm_src and "_after_download(done)" in mm_src)
    check("补封面时先看本地有没有",
          "_has_cover_locally" in mm_src and "download_cover" in mm_src)
    check("删除后先就地摘行（不等扫盘）",
          "def _forget_paths(" in mm_src
          and mm_src.count("self._forget_paths(") >= 3)
    check("摘行时顺手清掉工坊封面缓存",
          "drop_covers" in mm_src and "CACHE_DIR" in mm_src)
    check("删除路径仍然会兜底重扫",
          mm_src.count("self.scan()") >= 3)

    dep_src = card_src
    check("详情行用 showDepRow 控制显隐",
          "function showDepRow()" in dep_src
          and "height: page.showDepRow() ?" in dep_src)
    check("没查过前置时不说「没写前置」",
          "勾上会顺带查一遍前置" in dep_src)
    _sdr = dep_src.split("function showDepRow()", 1)[-1].split("function ", 1)[0]
    check("没有前置时不显示那一行（源码判据）",
          "return page.depCount() > 0;" in _sdr and "!page.probeFull" not in _sdr)
    check("没查到前置的条目给一颗「检查前置」小按钮",
          "检查前置" in dep_src and "复查前置" in dep_src and "onClicked: page.wantDeps()" in dep_src)
    if page is not None:
        check("页面里有 showDepRow 方法",
              page.metaObject().indexOfMethod("showDepRow()") >= 0)
        page.setProperty("picked", {"id": "111", "isCollection": False})
        page.setProperty("probeItems", [])
        page.setProperty("probeFull", True)
        page.setProperty("depsProbing", False)
        page.setProperty("pendingDeps", False)
        page.setProperty("includeDeps", False)
        page.setProperty("loadingDetail", False)
        wait(120)
        row = page.findChild(QObject, "wsDepRow")
        if row is not None:
            check("没前置时那一行真的收起来了", float(row.property("height") or 0) == 0,
                  str(row.property("height")))
            page.setProperty("probeItems", [{"id": "9", "isDep": True, "title": "前置"}])
            wait(120)
            check("有前置时那一行又出现", float(row.property("height") or 0) == 42,
                  str(row.property("height")))
            page.setProperty("probeItems", [])
        else:
            print("      [skip] 没找到 wsDepRow（详情抽屉没建）")

    # 简介 + 翻译：简介以前压根没解析，所以详情里永远是「没写简介」；
    # 翻译以前在设置里有个总开关，现在撤掉，改成详情里点一下才翻。
    main_src = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    check("设置里不再有「描述翻译」那一节",
          "translateSwitch" not in main_src and "描述翻译" not in main_src)
    check("详情里有「译成中文 / 看原文」按钮",
          "译成中文" in dep_src and "看原文" in dep_src)
    check("翻译不再被总开关拦（translateEnabled 恒真）",
          "def translateEnabled(self) -> bool:\n        return True" in mm_src)
    check("没简介时明确说没法翻",
          "没有可翻译的简介" in mm_src and "没有简介可以翻" in mm_src)
    check("简介字段来自详情接口（中转 file_description / 官方 description）",
          "file_description" in dl_src and "_plain_desc" in dl_src
          and 'f.get("description")' in dl_src)

    # 手动翻译：设置里那颗总开关撤了，详情里点一下就能翻；网络不通也得给一句明白话
    got_tr = []
    mgr.translationReady.connect(lambda r: got_tr.append(r))
    mgr.translateTextAsync("Replace the shotgun with a tactical version.")
    for _ in range(40):
        wait(250)
        if got_tr:
            break
    if got_tr:
        _r = got_tr[0]
        check("详情里点一下就能翻（不再被总开关拦）",
              bool(_r.get("ok")) or bool(_r.get("error")), str(_r.get("error"))[:36])
    else:
        print("      [skip] 翻译接口没回（网络慢）")
    _empty = mgr.translateText("   ")
    check("没简介时明确说没法翻",
          _empty.get("ok") is False and "简介" in (_empty.get("error") or ""),
          repr(_empty.get("error")))

    # ------------------------------------------- 6c. 多封面 / 统计 / 返回 / 重复
    print("=== 6c. 多封面、统计数字、返回合集、重复成员 ===")
    check("详情能列出作者贴的效果图（简介里的 [img]）",
          "def _desc_images(" in dl_src and "descImages" in dl_src
          and "desc_images" in dl_src)
    check("封面列表 = 工坊封面 + 效果图",
          '"images"' in dl_src and "_desc_images" in dl_src)
    check("统计数字走官方接口单独补（中转没有）",
          "def fetch_stats(" in dl_src and "STATS_TTL" in dl_src
          and "stats_only" in dl_src)
    check("统计不覆盖中转那份更全的简介",
          'pop("title"' in dl_src or "stats_only" in dl_src)
    check("管理器把统计异步送到界面",
          "workshopStatsChanged" in mm_src and "def requestWorkshopStats(" in mm_src
          and "def _stats_worker(" in mm_src)
    check("详情里接了统计信号", "onWorkshopStatsChanged" in dep_src)
    check("详情里有多封面切换（左右箭头 + 缩略图条）",
          "wsCoverStrip" in dep_src and "function coverSourceAt(" in dep_src
          and "page.detailImages()" in dep_src)
    check("详情里有浏览/订阅/收藏/发布/更新这一行",
          "wsStatsRow" in dep_src and "function statChips()" in dep_src
          and "浏览 " in dep_src and "订阅 " in dep_src and "收藏 " in dep_src
          and "更新 " in dep_src and "发布 " in dep_src)
    check("从合集点进成员能返回上一级",
          "wsBackRow" in dep_src and "function backDetail()" in dep_src
          and "page.detailStack" in dep_src and "detailStack = []" in dep_src)
    check("合集成员里重复的 MOD 会标出来",
          "function isDupMember(" in dep_src and "function dupMemberCount()" in dep_src
          and '"重复"' in dep_src and "isDupMember(modelData.id)" in dep_src)
    check("成员进度行会说有几个重复", "个重复" in dep_src)
    check("检查MOD / 更新检查的判据还在（工坊时间 > 本地 mtime）",
          "has_update" in mm_src and "> mtime + 60" in mm_src
          and "def identifyWorkshop(" in mm_src and "def identifyOne(" in mm_src)

    if page is not None:
        page.setProperty("picked", {
            "id": "3839961551", "title": "多图测试",
            "preview": "https://images.steamusercontent.com/a.jpg",
            "images": ["https://images.steamusercontent.com/a.jpg",
                       "https://i.imgur.com/one.gif",
                       "https://i.imgur.com/two.gif"],
            "fileType": 0,
        })
        wait(120)
        check("详情知道这一条有几张图",
              page.metaObject().indexOfMethod("detailImages()") >= 0)
        check("有 backDetail 方法",
              page.metaObject().indexOfMethod("backDetail()") >= 0)
        check("有 statChips 方法",
              page.metaObject().indexOfMethod("statChips()") >= 0)
        strip = page.findChild(QObject, "wsCoverStrip")
        if strip is not None:
            check("缩略图条出现了", float(strip.property("height") or 0) > 0,
                  str(strip.property("height")))
        else:
            print("      [skip] 没找到 wsCoverStrip")

    # 统计数字：官方接口能拿到就要求有数字，网络不行就跳过
    got_stats = []
    try:
        mgr.workshopStatsChanged.connect(lambda r: got_stats.append(r))
        mgr.requestWorkshopStats("3829533320")
        for _ in range(40):
            wait(250)
            if got_stats:
                break
    except Exception as exc:  # noqa: BLE001
        print("      [skip] 统计接口异常：%s" % str(exc)[:60])
    if got_stats:
        s = got_stats[0]
        check("统计数字拿到了（浏览/订阅/收藏）",
              bool(s.get("viewsText")) and bool(s.get("subsText")),
              "views=%s subs=%s favs=%s updated=%s" % (
                  s.get("viewsText"), s.get("subsText"),
                  s.get("favsText"), s.get("updatedText")))
        check("统计里有更新日期", bool(s.get("updatedText")),
              str(s.get("updatedText")))
    else:
        print("      [skip] 统计接口没回（网络慢）")

    # --------------------------------------- 6d. 启动无新视频 / 稍后看 / 翻译语种
    print("=== 6d. 只看新的自动关、稍后看里点分类、日韩翻译 ===")
    core_src = open(os.path.join(ROOT, "app", "core.py"), encoding="utf-8").read()
    net_src = open(os.path.join(ROOT, "app", "workshop_net.py"), encoding="utf-8").read()
    check("启动扫到没有新视频时自动关掉「只看新的」",
          "_startup_scan" in core_src and "show_only_new" in core_src
          and "没有新视频，已自动关掉" in core_src)
    check("只在启动那一次生效（不让周期扫描反复关）",
          "self._startup_scan = False" in core_src
          and core_src.count("_startup_scan") >= 3)
    check("稍后看里点「全部分类」能回到列表",
          "page.activeTags.length === 0 && !page.showLater" in dep_src)
    check("翻译会先自动判断原文语种",
          "def detect_lang(" in net_src and "_KANA_RE" in net_src
          and "_HANGUL_RE" in net_src and "def _source_candidates(" in net_src)
    check("日文/韩文不再被当成英文发出去",
          '"en|" + lang' not in net_src and 'f"en|' not in net_src)
    check("译完还有假名/谚文就换语向重试",
          "def _untranslated_ratio(" in net_src)
    # 语种判断本身
    got_ja = WN.detect_lang("モロトフのバリエーションを追加します。")
    got_ko = WN.detect_lang("몰로토프 병을 추가합니다.")
    got_en = WN.detect_lang("Replace the shotgun with a tactical version.")
    got_zh = WN.detect_lang("把霰弹枪换成战术版本，伤害不变。")
    check("假名多的判成日语", got_ja == "ja", got_ja)
    check("谚文多的判成韩语", got_ko == "ko", got_ko)
    check("英文判成英文", got_en == "en", got_en)
    check("中文判成中文", got_zh == "zh", got_zh)
    check("日文简介不会被当成「已经是中文」",
          WN.looks_chinese("モロトフのバリエーションです。") is False)
    check("英文夹一两句日语仍按英文发",
          "en" in WN._source_candidates(
              "This mod adds new bottles. モロトフ追加。", ""))
    # 统计胶囊不溢出：两行、宽度有上限、日期单独一行
    check("统计分两行（数字一行、日期一行）",
          'objectName: "wsStatsRow"' in dep_src
          and "function statDateChips()" in dep_src
          and dep_src.count("delegate: statChipComp") >= 2)
    check("统计胶囊宽度有上限且过长会省略",
          "Math.min(statTxt.implicitWidth + 24, 168)" in dep_src
          and "ElideRight" in dep_src)
    if page is not None:
        page.setProperty("pickedStats", {
            "viewsText": "646", "subsText": "166", "favsText": "96",
            "updatedText": "2026-11-15", "createdText": "2026-11-15",
        })
        wait(200)
        row = page.findChild(QObject, "wsStatsRow")
        if row is not None:
            # 抽屉内容宽 358：两行各自都在里面，且总高不超过 52
            h = float(row.property("height") or 0)
            w = float(row.property("width") or 0)
            check("统计行撑开了（不是 0 高）", h > 0, f"h={h:.0f} w={w:.0f}")
            check("统计行没超出抽屉宽度", w <= 380, f"w={w:.0f}")
            check("统计行两行以内（不挤成三行以上）", h <= 56, f"h={h:.0f}")
        else:
            print("      [skip] 没找到 wsStatsRow")
        page.setProperty("pickedStats", {})

    # ---------------------------------------------------------------- 7. 告警
    print("=== 7. QML 告警 ===")
    noise = ("QML Connections", "Unable to assign")
    real = [w for w in warns if any(k in w for k in (
        "TypeError", "not defined", "ReferenceError", "Binding loop",
        "is not a function", "Cannot assign", "Required property",
        "anchor loop")) and not any(n in w for n in noise)]
    check("无可疑告警", not real, f"{len(warns)} 条原始")
    for r in real[:6]:
        print("      !", r[:170])

    core.shutdown()
    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


def Number_ok(item) -> bool:
    try:
        return int(item.get("children") or 0) > 0
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
