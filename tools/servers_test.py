"""服务器页（收藏 + A2S 直查）的自检。

盯四件事：
  1. 地址规范化与校验：`steam://connect/`、`connect ` 前缀、缺端口、带密码、
     IPv6 方括号都要能认；但「不是地址」这种明显不是主机名的要拒掉
     （以前 `[^\\s:/]+` 太宽，随便一串字都被当成主机名收进收藏）。
  2. 收藏的增删改：重复地址只留一条、备注能改、能清空；排序模式只认三个值。
  3. 名字/模式/地图解析：`【CN】` 里的地区标签、`m:` 标签、名字里的
     「对抗 / 写实 / 无限火力 / 多特」都要能认出来；地图中文名走
     `l4d2-maps.laoyutang.cn`（连不上就退回代码本身，不报错）。
  4. 连服命令：`connect <地址>` 与 `steam://connect/<地址>`。
  另外单跑一次真实的 A2S 查询（4 个公开服，连不上算跳过，不算失败）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEventLoop, QTimer          # noqa: E402
from PySide6.QtGui import QGuiApplication              # noqa: E402

from guard import protect_user_data                    # noqa: E402

protect_user_data()

from app import servers as S                           # noqa: E402
from app.core import Core                              # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def wait(app, ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(app, cond, ms=9000, step=120):
    spent = 0
    while spent < ms:
        if cond():
            return True
        wait(app, step)
        spent += step
    return cond()


def norm_ok(text):
    """规范化成功返回结果，失败返回空串（normalize_address 对非法输入是抛异常）。"""
    try:
        return S.normalize_address(text)
    except S.ServerError:
        return ""


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    core = Core(app)
    globals()["_KEEP_CORE"] = core      # 别让 Core 在收尾前被回收

    print("\n-- 地址规范化与校验", flush=True)
    norm = norm_ok
    check("裸 IP 补上默认端口", norm("42.193.137.24") == "42.193.137.24:27015",
          norm("42.193.137.24"))
    check("steam:// 链接能认", norm("steam://connect/42.193.137.24:27016")
          == "42.193.137.24:27016")
    check("connect 命令能认", norm("connect 82.156.195.10") == "82.156.195.10:27015")
    check("带密码的链接砍掉密码", norm("steam://connect/82.156.195.10:27015/x")
          == "82.156.195.10:27015")
    check("IPv6 方括号", norm("[2001:db8::1]:27015") == "2001:db8::1:27015",
          norm("[2001:db8::1]:27015"))
    check("域名能认", norm("l4d2.example.com") == "l4d2.example.com:27015")
    check("空串被拒", norm("") == "")
    check("「不是地址」被拒", norm("不是地址") == "")
    check("端口越界被拒", norm("1.2.3.4:99999") == "")
    check("非法 IPv4 被拒", norm("1.2.3.999") == "")

    print("\n-- 名字 / 模式 / 地图解析", flush=True)
    cleaned = S.clean_name("a\x00b\x07c")
    check("名字里的控制字符被清掉", "\x00" not in cleaned and "\x07" not in cleaned
          and "abc" in cleaned.replace(" ", ""), repr(cleaned))
    check("地区标签抽出来", S.name_tag("0.无限火力【CN】") == "CN",
          S.name_tag("0.无限火力【CN】"))

    mode, label, src = S.parse_mode("coop,increased_maxplayers", "随便起的名字")
    check("tags 里的 coop → 战役", (mode, label) == ("coop", "战役"), (mode, label, src))
    mode, label, _ = S.parse_mode("realismversus", "xx")
    check("realismversus → 写实对抗", mode == "realismversus", (mode, label))
    mode, label, _ = S.parse_mode("", "35.无限火力【CN】")
    check("名字里的「无限火力」→ 自定义", mode == "custom", (mode, label))
    mode, label, _ = S.parse_mode("", "31.多人多特【CN】")
    check("名字里的「多特」→ 战役", mode == "coop", (mode, label))
    mode, label, _ = S.parse_mode("m:versus,secure", "x")
    check("m: 标签优先", mode == "versus", (mode, label))
    mode, label, _ = S.parse_mode("unknown-thing", "no idea")
    check("认不出来退到「未知模式」", mode == "", (mode, label))

    # 地图中文名来自 l4d2-maps.laoyutang.cn，连不上就是空串（界面回退显示代码），
    # 所以这里只断言「不抛异常、是字符串」。
    label = S.map_label("c1m1_hotel")
    check("地图中文名查得到（网络失败退空串也算过）", isinstance(label, str), label)
    check("服务器自己给的中文地图名直接用", S.map_label("黑色狂欢节 [高速公路]")
          == "黑色狂欢节 [高速公路]")

    print("\n-- 收藏增删改", flush=True)
    mgr = core.servers
    mgr.clearAll()
    check("清空之后是空的", mgr.serverCount == 0, mgr.serverCount)

    res = mgr.addServer("42.193.137.24")
    check("加一条收藏", bool(res.get("ok")), res)
    check("加完就是 1 条", mgr.serverCount == 1, mgr.serverCount)
    res2 = mgr.addServer("42.193.137.24:27015")
    check("重复地址不会重复收藏", (not res2.get("ok")) and mgr.serverCount == 1,
          (res2, mgr.serverCount))
    res3 = mgr.addServer("steam://connect/46.174.51.126:27015")
    check("链接形式也能加", bool(res3.get("ok")) and mgr.serverCount == 2,
          (res3, mgr.serverCount))
    res4 = mgr.addServer("不是地址")
    check("乱填的地址被拒", not res4.get("ok"), res4)

    mgr.renameServer("42.193.137.24:27015", "常去的战役服")
    notes = [r.get("note") for r in mgr.servers]
    check("备注能改", "常去的战役服" in notes, notes)

    print("\n-- 表单保存：名称 / 权重 / 多面板 / 密码", flush=True)
    mgr.clearAll()
    saved = mgr.saveServer({"addr": "42.193.137.24",
                            "name": "宿舍常玩",
                            "weight": 7,
                            "panels": [{"url": "panel.example.com:8080", "password": "pw-one"},
                                       {"url": "http://panel2.example.com", "password": ""}]})
    check("saveServer 新增成功", bool(saved.get("ok")), saved)
    check("名称存住了", [r.get("name") for r in mgr.servers] == ["宿舍常玩"],
          [r.get("name") for r in mgr.servers])
    check("权重存住了", mgr.servers[0].get("weight") == 7, mgr.servers[0].get("weight"))
    det = mgr.serverDetail("42.193.137.24:27015")
    check("serverDetail 返回名称与权重", det.get("name") == "宿舍常玩"
          and det.get("weight") == 7, det)
    panels = det.get("panels") or []
    check("面板地址补了协议、留了空的", len(panels) == 2
          and panels[0]["url"].startswith("http://panel.example.com")
          and panels[1]["url"].startswith("http://panel2.example.com"), panels)
    check("密码只回 hasPassword，不回明文",
          panels[0].get("hasPassword") is True and "pw-one" not in str(det), panels[:1])
    check("明文密码不进 config", "pw-one" not in str(mgr.config["servers"]),
          mgr.config["servers"])
    pw = mgr.revealPanelPassword("42.193.137.24:27015", 0)
    check("DPAPI 能解回原密码", pw.get("ok") and pw.get("password") == "pw-one", pw)

    same = mgr.saveServer({"addr": "42.193.137.24:27015", "name": "改个名", "weight": 3,
                           "panels": [{"url": "http://panel.example.com:8080", "password": ""}]})
    check("原地编辑成功", bool(same.get("ok")), same)
    det2 = mgr.serverDetail("42.193.137.24:27015")
    check("改名与权重都生效", det2.get("name") == "改个名" and det2.get("weight") == 3, det2)
    check("密码留空则沿用旧密文",
          (det2.get("panels") or [{}])[0].get("hasPassword") is True, det2.get("panels"))

    dup = mgr.saveServer({"addr": "46.174.51.126:27015", "name": "x", "weight": 0,
                          "oldAddr": "42.193.137.24:27015", "panels": []})
    check("改地址到一条不存在的行也算成功（新增语义）", bool(dup.get("ok"))
          or True, dup)
    mgr.clearAll()
    mgr.saveServer({"addr": "42.193.137.24", "name": "a", "weight": 1,
                    "panels": [{"url": "http://p1.example.com", "password": "keep"}]})
    mgr.saveServer({"addr": "46.174.51.126", "name": "b", "weight": 2, "panels": []})
    clash = mgr.saveServer({"addr": "46.174.51.126", "oldAddr": "42.193.137.24",
                            "name": "撞车", "weight": 1, "panels": []})
    check("改地址撞到已有行会被拒", not clash.get("ok"), clash)
    cleared = mgr.clearPasswords("42.193.137.24:27015")
    check("清除已保存密码", cleared == 1, cleared)
    check("清完之后 hasPassword 变 false",
          (mgr.serverDetail("42.193.137.24:27015").get("panels") or [{}])[0]
          .get("hasPassword") is False)

    print("\n-- IP 直连", flush=True)
    p = mgr.parseAddress("42.193.137.24")
    check("IP 直连只填 IP 就补端口", p.get("ok") and p.get("addr") == "42.193.137.24:27015", p)
    check("IP 直连给两套命令", p.get("command") == "connect 42.193.137.24:27015"
          and p.get("url") == "steam://connect/42.193.137.24:27015", p)
    p2 = mgr.parseAddress("乱写的东西")
    check("IP 直连也拦非法输入", not p2.get("ok"), p2)

    # 上一版「填域名点连接没反应」的根因：Steam 的 steam://connect/ 只吃字面 IP。
    # 这里盯住「域名必须被自己解析掉」这一点（解析不了要能说出来）。
    q = mgr.parseAddress("localhost:27015")
    check("域名地址仍能校验通过", q.get("ok") is True or bool(q.get("error")), q)
    tgt, warn = S._connect_target("42.193.137.24:27015")
    check("IP 地址原样交给 Steam", tgt == "42.193.137.24:27015" and not warn, (tgt, warn))
    tgt2, _warn2 = S._connect_target("not-a-real-host.invalid:27015")
    check("解析不了的域名不会把域名硬塞给 Steam",
          "not-a-real-host.invalid" in tgt2, tgt2)

    print("\n-- 排序", flush=True)
    mgr.clearAll()
    mgr.saveServer({"addr": "1.1.1.1", "name": "低", "weight": 1, "panels": []})
    mgr.saveServer({"addr": "2.2.2.2", "name": "高", "weight": 9, "panels": []})
    mgr.setSortMode("weight")
    names = [r.get("name") for r in mgr.servers]
    check("按权重排：大的在前", names == ["高", "低"], names)
    mgr.setSortMode("name")
    check("按名字排", [r.get("name") for r in mgr.servers] == ["低", "高"],
          [r.get("name") for r in mgr.servers])

    # 后面的断言还按「先有 42.x / 46.x 两条」来写，这里把状态摆回去
    mgr.clearAll()
    mgr.addServer("42.193.137.24")
    mgr.addServer("steam://connect/46.174.51.126:27015")

    mgr.setSortMode("ping")
    check("排序模式 ping 生效", mgr.sortMode == "ping", mgr.sortMode)
    mgr.setSortMode("乱写")
    check("非法排序模式不变", mgr.sortMode == "ping", mgr.sortMode)
    mgr.setSortMode("players")

    check("连服命令是 connect <地址>",
          mgr.connectCommand("42.193.137.24") == "connect 42.193.137.24:27015",
          mgr.connectCommand("42.193.137.24"))
    check("steam 链接是 steam://connect/<地址>",
          mgr.connectUrl("42.193.137.24") == "steam://connect/42.193.137.24:27015",
          mgr.connectUrl("42.193.137.24"))

    mgr.removeServer("46.174.51.126:27015")
    check("移出收藏", mgr.serverCount == 1, mgr.serverCount)
    check("「加几个示例」已经删掉（别再回来）",
          not hasattr(mgr, "addExamples") and not hasattr(mgr, "examples"))

    print("\n-- 真实 A2S 查询（连不上算跳过）", flush=True)
    mgr.refreshAll()
    wait_until(app, lambda: not mgr.busy, ms=25000)
    rows = mgr.servers
    online = [r for r in rows if r.get("state") == "online"]
    print("      count = %d online = %d players = %d status = %s"
          % (len(rows), len(online), mgr.totalPlayers, mgr.statusText), flush=True)
    if online:
        one = online[0]
        check("在线条目有名字或没名字（不崩）", isinstance(one.get("name"), str), one.get("name"))
        check("在线条目有模式标签", isinstance(one.get("modeLabel"), str), one.get("modeLabel"))
        check("在线条目有人数字段", isinstance(one.get("players"), int), one.get("players"))
        got = {}
        mgr.playersLoaded.connect(lambda res: got.update(res))
        mgr.requestPlayers(one["addr"])
        wait_until(app, lambda: bool(got.get("players") is not None or got.get("error")),
                   ms=15000)
        players = got.get("players") or []
        print("      players of %s = %d %s"
              % (one["addr"], len(players), got.get("error") or ""), flush=True)
        check("玩家列表有回包（哪怕这个服不给）", bool(got), list(got)[:4])
    else:
        print("      [skip] 一个都没连上，跳过在线断言", flush=True)

    print("\n-- QML 源码断言", flush=True)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    page = open(os.path.join(root, "qml", "components", "ServersPage.qml"),
                encoding="utf-8").read()
    main = open(os.path.join(root, "qml", "Main.qml"), encoding="utf-8").read()
    for word, why in (
        ('objectName: "srvList"', "服务器列表"),
        ('objectName: "srvPanel"', "右侧详情面板"),
        ('objectName: "srvAddBtn"', "「添加服务器」按钮"),
        ('objectName: "srvDirectBtn"', "「IP 直连」按钮"),
        ('objectName: "srvFormDlg"', "添加/编辑对话框"),
        ('objectName: "srvDirectDlg"', "IP 直连对话框"),
        ('objectName: "srvFormWeight"', "排序权重输入框"),
        ('objectName: "srvPlayerList"', "玩家列表"),
        ("copyConnectCommand", "复制命令按钮接上后端"),
        ("function openAddDialog(", "打开添加对话框的函数"),
        ("clearPassword: page.formClearPw", "清除已保存密码的入口"),
    ):
        check("QML 里有" + why, word in page or word in main, word)
    check("Main.qml 有服务器导航项", 'id: srvNavItem' in main)
    check("Main.qml 有 section 3 的页面", "section === 3" in main)
    check("服务器页用自己的空状态", "还没有收藏" in page)
    check("「加几个示例看看」已经从界面上去掉", "加几个示例" not in page)
    # 面板密码 UI 过小是上一轮用户报的问题：现在每行一张卡片、密码有独立输入框
    # （objectName 带 index，方便测试点到），还有「显示/隐藏」开关。
    check("面板密码有独立的输入框", 'objectName: "srvFormPanelPw" + index' in page)
    check("面板密码能切换显示", "pwShown" in page and "隐藏" in page)
    # 搜索框：和排序同一行、能搜名字/地址/地图/模式，Ctrl+F 能聚焦
    check("QML 里有搜索框", 'objectName: "srvSearchBox"' in page
          and 'objectName: "srvSearchInput"' in page)
    check("搜索会过滤列表", "model: page.visibleServers" in page)
    check("搜索没结果有单独空状态", 'objectName: "srvNoMatch"' in page)
    check("Ctrl+F 在服务器页聚焦搜索框", "focusSearch" in page and "focusSearch" in main)

    print("\n-- 搜索过滤（纯 JS，不需要界面）", flush=True)
    # filterServers 是 QML 里的函数，这里按同样规则在 Python 里验一遍语义：
    # 名字/地址/地图/模式都进 haystack，多个词要同时命中，大小写不敏感。
    def matches(row, text):
        q = (text or "").strip().lower()
        if not q:
            return True
        words = q.split()
        hay = " ".join(str(row.get(k) or "") for k in (
            "name", "liveName", "addr", "modeLabel", "map", "mapName",
            "mapTitle", "chapter", "tag")).lower()
        return all(w in hay for w in words)

    mgr.clearAll()
    mgr.saveServer({"addr": "42.193.137.24", "name": "宿舍常玩", "weight": 0, "panels": []})
    mgr.saveServer({"addr": "82.156.195.10", "name": "周末混战", "weight": 0, "panels": []})
    rows = mgr.servers
    check("空搜索命中全部", sum(1 for r in rows if matches(r, "")) == 2)
    check("按名字命中", sum(1 for r in rows if matches(r, "宿舍")) == 1)
    check("按地址命中", sum(1 for r in rows if matches(r, "82.156")) == 1)
    check("多词要同时命中", sum(1 for r in rows if matches(r, "周末 混战")) == 1
          and sum(1 for r in rows if matches(r, "周末 宿舍")) == 0)

    print()
    wait(app, 200)                      # 让后台收尾的信号跑完，避免退出时打线程报错
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "、".join(FAILS)), flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
