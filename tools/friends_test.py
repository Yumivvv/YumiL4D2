# -*- coding: utf-8 -*-
"""好友在玩：后端合并逻辑 + 界面标签（不需要真 Steam 好友在线）。

覆盖：
1. steamfriends 的地址解析与内网过滤
2. ServerManager 把好友并进服务器行（含「只有好友在玩、未收藏」的额外行）
3. 「好友在玩」作为一个独立合集出现在 groups 里，且能正确过滤
4. QML 里确实有 friendTag、且文案函数逻辑正确
"""
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from guard import protect_user_data  # noqa: E402

protect_user_data()

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def make_mgr():
    """造一个不依赖 Core 的 ServerManager（只测数据合并）。"""
    from app import servers as S

    class FakeCfg(dict):
        def save(self):
            pass

    m = S.ServerManager.__new__(S.ServerManager)
    cfg = FakeCfg()
    cfg.update({
        "servers": [
            {"addr": "1.2.3.4:27015", "name": "宿舍服", "weight": 0, "panels": []},
            {"addr": "5.6.7.8:27015", "name": "黑喵0", "weight": 0, "panels": []},
        ],
        "servers_sort": "weight",
        "server_group_names": {},
    })
    m.config = cfg
    m._live = {}
    m._lock = threading.Lock()
    m._sort = "weight"
    m._group_key = "all"
    m._closed = False
    m._friends_map = {}
    m._friends_l4d2 = []
    m._friends_ok = False
    m._friends_err = ""
    m._friends_me = ""
    return m


def main():
    from app import servers as S
    from app import steamfriends as SF

    # ---------------------------------------------------------- 1. 地址过滤
    print("=== 1. 好友服务器地址：内网要挡掉 ===")
    # _is_private 收的是「点分 IP 拼成的整数」
    def as_int(dotted):
        v = 0
        for p in dotted.split("."):
            v = (v << 8) | int(p)
        return v

    for ip, private in (("192.168.1.10", True), ("10.1.2.3", True),
                        ("172.16.0.5", True), ("127.0.0.1", True),
                        ("100.64.1.1", True), ("169.254.1.1", True),
                        ("103.44.156.99", False), ("8.8.8.8", False),
                        ("45.125.45.95", False)):
        check(f"{ip} {'判为内网' if private else '判为公网'}",
              SF._is_private(as_int(ip)) is private)

    # ---------------------------------------------------------- 2. 合并
    print("=== 2. 好友并进服务器行 ===")
    m = make_mgr()
    m._friends_map = {
        "1.2.3.4:27015": [{"name": "小明"}, {"name": "阿强"}],
        "9.9.9.9:27015": [{"name": "夜猫子"}],
    }
    m._friends_l4d2 = [{"name": "小明"}, {"name": "阿强"}, {"name": "夜猫子"}]
    m._friends_ok = True
    m._friends_me = "Yumi"

    rows = m._merged()
    check("收藏 2 台 + 好友 1 台 = 3 行", len(rows) == 3, str(len(rows)))

    by_addr = {r["addr"]: r for r in rows}
    a = by_addr.get("1.2.3.4:27015") or {}
    check("已收藏的服带上了好友名", a.get("friends") == ["小明", "阿强"],
          str(a.get("friends")))
    check("已收藏的服 friendCount=2", a.get("friendCount") == 2)
    check("已收藏的服不算 fromFriend", a.get("fromFriend") is False)

    b = by_addr.get("5.6.7.8:27015") or {}
    check("没好友的服 friends 为空", b.get("friends") == [])

    c = by_addr.get("9.9.9.9:27015") or {}
    check("好友独有服被补进来", c.get("addr") == "9.9.9.9:27015")
    check("好友独有服标记 fromFriend", c.get("fromFriend") is True)
    check("好友独有服属于「好友在玩」组", c.get("group") == S.FRIEND_GROUP_KEY)

    # ---------------------------------------------------------- 3. 合集
    print("=== 3. 「好友在玩」作为独立合集 ===")
    gs = type(m).groups.fget(m)
    keys = [g["key"] for g in gs]
    check("合集里有 __friends__", S.FRIEND_GROUP_KEY in keys, str(keys))
    fg = next((g for g in gs if g["key"] == S.FRIEND_GROUP_KEY), {})
    check("「好友在玩」排在「全部」之后", keys.index(S.FRIEND_GROUP_KEY) == 1, str(keys))
    check("「好友在玩」计数 = 2（一台收藏+一台独有）",
          fg.get("count") == 2, str(fg.get("count")))
    check("kind 是 friends", fg.get("kind") == "friends", str(fg.get("kind")))

    fr = m._rows_in_group(rows, S.FRIEND_GROUP_KEY)
    addrs = sorted(r["addr"] for r in fr)
    check("过滤出 2 台", len(fr) == 2, str(addrs))
    check("过滤内容正确", addrs == ["1.2.3.4:27015", "9.9.9.9:27015"], str(addrs))

    # ---------------------------------------------------------- 4. 属性
    print("=== 4. 暴露给界面的属性 ===")
    check("friendsPlayingCount = 3",
          type(m).friendsPlayingCount.fget(m) == 3,
          str(type(m).friendsPlayingCount.fget(m)))
    check("friendsOk = True", type(m).friendsOk.fget(m) is True)
    check("mySteamName = Yumi", type(m).mySteamName.fget(m) == "Yumi")

    # 没有好友时，「好友在玩」不该出现在合集里
    m2 = make_mgr()
    gs2 = type(m2).groups.fget(m2)
    keys2 = [g["key"] for g in gs2]
    check("没有好友时不出「好友在玩」", S.FRIEND_GROUP_KEY not in keys2, str(keys2))

    # ---------------------------------------------------------- 5. 刷新覆盖
    print("=== 5. 刷新时好友服务器也要被查 ===")
    # 这是这次修的问题：refreshAll 以前只查 _favorites()，
    # 「好友在玩但没收藏」的那种卡片永远停在「未查询」，地图/人数全空。
    m3 = make_mgr()
    fav_addr = "1.2.3.4:27015"            # make_mgr 里已收藏
    new_addr = "203.0.113.77:27015"        # 好友在玩、没收藏
    m3._friends_map = {fav_addr: [{"name": "甲"}],
                       new_addr: [{"name": "乙"}]}
    lst = m3._friends_addr_list()
    check("_friends_addr_list 有这个方法", hasattr(m3, "_friends_addr_list"))
    check("列进未收藏的那台", new_addr in lst, str(lst))
    check("已收藏的不重复列", fav_addr not in lst, str(lst))
    check("只列 1 台", len(lst) == 1, str(lst))

    # 源码里 refreshAll 确实把好友地址并进查询清单
    src = open(os.path.join(ROOT, "app", "servers.py"), encoding="utf-8").read()
    i = src.find("def refreshAll(")
    body_r = src[i:i + 900] if i > 0 else ""
    check("refreshAll 里并入了好友地址", "_friends_addr_list()" in body_r)
    # 读完好友后要主动查那些新地址
    j = src.find("def refreshFriends(")
    body_f = src[j:j + 2200] if j > 0 else ""
    check("refreshFriends 会主动查新地址",
          "_query_friends_addrs" in body_f, "")
    check("有 _query_friends_addrs 实现", "def _query_friends_addrs(" in src)

    # ---------------------------------------------------------- 6. 可收藏
    print("=== 6. 好友在玩默认临时、可手动收藏 ===")
    # 用真 Core 更贴近实际（saveFriendServer 要写配置）
    from PySide6.QtWidgets import QApplication as _QA
    _app = _QA.instance() or _QA(sys.argv[:1])
    from app.core import Core as _Core
    core = _Core(_app)
    mgr = core.servers

    tmp_addr = "203.0.113.99:27015"        # TEST-NET-3，绝不会是真实服务器
    check("测试地址不在收藏里",
          tmp_addr not in {r["addr"] for r in mgr._favorites()})

    mgr._friends_map = {tmp_addr: [{"name": "测试好友"}]}
    mgr._friends_l4d2 = [{"name": "测试好友"}]

    row = next((r for r in mgr.servers if r["addr"] == tmp_addr), None)
    check("默认就出现在列表里", row is not None)
    if row:
        check("标 fromFriend", row["fromFriend"] is True)
    check("默认**不**写进配置",
          tmp_addr not in {r["addr"] for r in mgr._favorites()})

    res = mgr.saveFriendServer(tmp_addr)
    check("收藏成功", res.get("ok") is True, str(res))
    check("收藏后进配置",
          tmp_addr in {r["addr"] for r in mgr._favorites()})
    row2 = next((r for r in mgr.servers if r["addr"] == tmp_addr), None)
    if row2:
        check("收藏后不再是 fromFriend", row2["fromFriend"] is False)

    res2 = mgr.saveFriendServer(tmp_addr)
    check("重复收藏被拒", res2.get("ok") is False, str(res2))

    # 好友退出：收藏的留着，没收藏的消失
    mgr._friends_map = {}
    mgr._friends_l4d2 = []
    check("好友退出后收藏的那台还在",
          any(r["addr"] == tmp_addr for r in mgr.servers))

    tmp2 = "203.0.113.100:27015"
    mgr._friends_map = {tmp2: [{"name": "另一个"}]}
    check("另一台临时服出现了", any(r["addr"] == tmp2 for r in mgr.servers))
    mgr._friends_map = {}
    check("没收藏的临时服随好友消失",
          not any(r["addr"] == tmp2 for r in mgr.servers))

    # ---------------------------------------------------------- 7. QML
    print("=== 7. QML 界面 ===")
    qml = open(os.path.join(ROOT, "qml", "components", "ServersPage.qml"),
               encoding="utf-8").read()
    for s, label in (
        ('objectName: "friendTag"', "有 friendTag 组件"),
        ("function friendTagText(", "有 friendTagText 函数"),
        ("function showFriendNames(", "有 showFriendNames 函数"),
        ("modelData.friends", "卡片读了 modelData.friends"),
        ("fromFriend", "界面区分 fromFriend"),
        ("friendPlayingCount", "用了 friendPlayingCount"),
        ("core.servers.friendsPlayingCount", "绑到后端的计数"),
    ):
        check(label, s in qml)

    # titleOf 对「好友独有服」要给一句人话，别只显示 IP
    idx = qml.find("function titleOf(")
    body = qml[idx:idx + 700] if idx >= 0 else ""
    check("titleOf 对好友独有服给友好标题", "fromFriend" in body)
    check("titleOf 仍然优先用用户起的名字", 'row.name || ""' in body)

    # 好友标签的位置。
    #
    # ★ 2026-11 又改了一次：标签从「地址右边」挪到「地址下面独立一行」
    #   （用户：「放到 IP 右边不太协调，可以放到 IP 下面」）。
    #   所以「地址按内容宽度排」这条老断言已经不成立了 —— 现在地址**独占一行、
    #   撑满宽度**，标签在下一行。
    k = qml.find('objectName: "friendTag"')
    seg = qml[max(0, k - 1400):k] if k > 0 else ""
    check("地址独占一行、撑满宽度（不再给右侧标签让位）",
          "id: addrTxt" in seg and "width: parent.width" in seg)
    check("地址不再写 parent.width - 标签宽",
          "width: parent.width - (friendTag.visible" not in seg,
          "仍是旧写法" if "width: parent.width - (friendTag.visible" in seg else "")
    # 标签不该再锚在地址右边（那是上一版的位置）
    tail = qml[k:k + 1500] if k > 0 else ""
    check("好友标签不再锚在地址右边",
          "anchors.left: addrTxt.right" not in tail,
          "又挤回地址右边了")

    # 收藏入口：卡片星标 + 详情面板提示条
    check("卡片有「收藏」按钮", 'objectName: "srvCardSaveFriend"' in qml)
    check("收藏按钮只对 fromFriend 显示",
          "visible: srvCard.modelData.fromFriend" in qml)
    check("有 saveFriend 函数", "function saveFriend(" in qml)
    check("详情面板有临时提示条", 'objectName: "friendTempBar"' in qml)
    check("提示条说明会消失", "好友退出后这台会消失" in qml)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())