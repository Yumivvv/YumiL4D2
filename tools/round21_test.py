# -*- coding: utf-8 -*-
"""本轮四个修复的回归测试（全部不联网、不开 QML 窗口）。

1. 服务器连接：游戏已经在跑时，也要用
   `steam://connect/<ip>:<port>/rungameid/550` 直接连过去，
   而不是只把命令塞剪贴板让用户手动粘。
2. MOD 详情「检查MOD」：文件名不是纯数字、但列表里已有 workshopId 的，
   也必须能检查（以前只认文件名）。
3. 作者名片「关注」：没登录返回 needLogin，登录了才真的写接口。
4. 三连部分成功：投币失败时，点赞 / 收藏的成功回执不能丢。
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from app import bili as B  # noqa: E402
from app import servers as S  # noqa: E402
from app.core import Core  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


# ============================================== 1. 游戏在跑也要能连服务器
print("\n[1] 游戏已在运行时连接服务器")
_orig = {
    "steam": S.steam_exe,
    "installed": S.game_installed,
    "running": S.game_running,
    "target": S._connect_target,
    "open": S._open_url,
}
try:
    S.steam_exe = lambda: r"C:\Steam\steam.exe"
    S.game_installed = lambda: True
    S.game_running = lambda: True          # ← 关键：游戏已经在跑
    S._connect_target = lambda a: (a, "")
    opened = []
    S._open_url = lambda url: (opened.append(url), True)[1]

    mgr = S.ServerManager.__new__(S.ServerManager)
    from PySide6.QtCore import QObject
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv[:1])

    class _Cfg:
        def __getitem__(self, k):
            return {"servers": [], "servers_sort": "players",
                    "clipboard_servers": True}.get(k)

        def __setitem__(self, k, v):
            pass

        def save(self):
            pass

    class _FakeCore(QObject):
        """ServerManager 只用到 config / toast 这两个口子，但必须是 QObject。"""

        def __init__(self):
            super().__init__()
            self.config = _Cfg()

        def toast(self, *a, **k):
            pass

        def _toast(self, *a, **k):
            pass

        statusChanged = None

        def _set_status(self, text):
            pass

    S.ServerManager.__init__(mgr, _FakeCore())
    mgr._clipboard = lambda text: True
    mgr._bring_game_foreground = lambda: True

    res = mgr._doConnect("1.2.3.4:27015", notify=False)
    check("游戏在跑时算连接成功", res.get("ok") is True, str(res)[:80])
    check("游戏在跑时走 steam 而不是 console",
          res.get("how") == "steam-running", res.get("how"))
    check("用了带 rungameid 的 URL",
          any("rungameid/550" in u for u in opened), str(opened))
    check("URL 里带上了服务器地址",
          any("1.2.3.4:27015" in u for u in opened), str(opened))

    # 游戏没在跑：仍走老路子
    opened.clear()
    S.game_running = lambda: False
    res = mgr._doConnect("1.2.3.4:27015", notify=False)
    check("游戏没跑时 how=steam", res.get("how") == "steam", res.get("how"))
    check("游戏没跑时 URL 也带 rungameid（两种都通用）",
          any("rungameid/550" in u for u in opened), str(opened))

    # connectUrl / parseAddress 也要带 appid
    check("connectUrl 带 rungameid",
          "rungameid/550" in mgr.connectUrl("1.2.3.4:27015"),
          mgr.connectUrl("1.2.3.4:27015"))
    parsed = mgr.parseAddress("1.2.3.4:27015")
    check("parseAddress 的 url 带 rungameid",
          "rungameid/550" in (parsed.get("url") or ""), parsed.get("url"))
finally:
    S.steam_exe = _orig["steam"]
    S.game_installed = _orig["installed"]
    S.game_running = _orig["running"]
    S._connect_target = _orig["target"]
    S._open_url = _orig["open"]


# ============================================== 2. 有工坊 ID 就能检查
print("\n[2] MOD 详情「检查MOD」")
src = open(os.path.join("app", "modmanager.py"), encoding="utf-8").read()
check("identifyOne 不再只认文件名",
      "_workshop_id_of_path" in src)
check("有按 path 反查 workshopId 的辅助函数",
      "def _workshop_id_of_path" in src)
check("反查覆盖 path / id / stem / basename 四种键",
      all(k in src for k in ('item.get("path")', 'item.get("id")',
                             'item.get("stem")', "os.path.basename")))
check("提示文案已改（不再说「不是工坊 ID 命名」）",
      "不是工坊 ID 命名" not in src.split("def identifyOne")[1][:600],
      src.split("def identifyOne")[1][:200])

# 真正跑一遍反查逻辑
from app.modmanager import ModManager  # noqa: E402

fake = ModManager.__new__(ModManager)
fake._all_local = [
    {"path": r"C:\addons\我的改版武器.vpk", "stem": "我的改版武器",
     "workshopId": "3829533320"},
    {"path": r"C:\addons\另一个.vpk", "stem": "另一个", "workshopId": ""},
]
fake._all_workshop = []
check("中文文件名也能反查出工坊 ID",
      fake._workshop_id_of_path(r"C:\addons\我的改版武器.vpk") == "3829533320",
      fake._workshop_id_of_path(r"C:\addons\我的改版武器.vpk"))
check("只给 basename 也能反查",
      fake._workshop_id_of_path("我的改版武器.vpk") == "3829533320")
check("没有工坊 ID 的返回空串",
      fake._workshop_id_of_path(r"C:\addons\另一个.vpk") == "")
check("不存在的路径返回空串", fake._workshop_id_of_path(r"C:\addons\x.vpk") == "")


# ============================================== 3. 作者名片关注
print("\n[3] 作者名片「关注」")
check("BiliClient 有 following()", hasattr(B.BiliClient, "following"))
check("有 RELATION_API 常量",
      str(getattr(B.BiliClient, "RELATION_API", "")).endswith("/x/relation"),
      getattr(B.BiliClient, "RELATION_API", ""))
check("Core 有 biliFollowAuthor", hasattr(Core, "biliFollowAuthor"))
check("Core 有 biliFollowing", hasattr(Core, "biliFollowing"))

core = Core(app)
try:
    core.biliLogout()
    res = core.biliFollowAuthor("12345")
    check("没登录时 needLogin=True", res.get("needLogin") is True, str(res))
    check("没登录时 ok=False", res.get("ok") is False, str(res))
    check("没登录时给了解释", bool(res.get("error")), res.get("error"))

    # 登录态下：真的会去调关注接口（这里打桩，不联网）
    core.client.set_credentials("s", "j", "999")
    calls = []
    core.client.nav_user = lambda: {"mid": 999, "uname": "t"}
    core.client.following = lambda mid: False
    core.client.follow_user = lambda mid, follow=True: (
        calls.append((mid, follow)), {"ok": True, "code": 0, "message": ""})[1]
    res = core.biliFollowAuthor("12345")
    check("登录后关注成功", res.get("ok") is True, str(res))
    check("关注后 following=True", res.get("following") is True, str(res))
    check("调了 follow_user(act=关注)", calls and calls[0] == (12345, True), str(calls))

    # 已关注状态下再点 = 取关
    calls.clear()
    core.client.following = lambda mid: True
    res = core.biliFollowAuthor("12345")
    check("已关注时再点是取关",
          res.get("following") is False and calls and calls[0] == (12345, False),
          f"{res} {calls}")

    check("mid 非法时不炸",
          core.biliFollowAuthor("abc").get("ok") is False)
finally:
    core.shutdown()


# ============================================== 4. 三连部分成功
print("\n[4] 三连：部分成功也要报成功的部分")
core = Core(app)
try:
    core.client.set_credentials("s", "j", "999")
    core.client.nav_user = lambda: {"mid": 999}
    core.library.videos["BVtest"] = {"bvid": "BVtest", "aid": 111, "mid": 222}
    core.setBiliLike(True)
    core.setBiliCoin(True)
    core.setBiliFav(True)
    core.setBiliFollow(False)
    # 点赞成功、投币失败（硬币不足）、收藏成功
    core.client.like_video = lambda aid, like=True: {"ok": True, "code": 0}
    core.client.coin_video = lambda aid, n=1: {
        "ok": False, "code": -104, "message": "硬币不足",
        "human": "投币失败：硬币不足或账号等级不够（账号里没硬币了，或者等级还没到 2 级）"}
    core.client.favorites = lambda: [{"id": 1, "title": "默认收藏夹"}]
    core.client.favorite_video = lambda aid, fid: {"ok": True, "code": 0}

    res = core.biliTriple("BVtest")
    check("部分成功时 ok=True", res.get("ok") is True, str(res)[:80])
    check("点赞算成功", "点赞" in (res.get("done") or []), res.get("done"))
    check("收藏算成功", "收藏" in (res.get("done") or []), res.get("done"))
    check("投币失败进了 errors", bool(res.get("errors")), res.get("errors"))
    check("错误里说清是硬币不足",
          "硬币" in "".join(res.get("errors") or []), res.get("errors"))
    check("error 字段同时包含成功项和失败项",
          "点赞" in (res.get("error") or "") and "硬币" in (res.get("error") or ""),
          res.get("error"))

    # 全新：三项全失败 → ok=False
    core.client.like_video = lambda aid, like=True: {"ok": False, "code": 1, "message": "x"}
    core.client.favorite_video = lambda aid, fid: {"ok": False, "code": 1, "message": "y"}
    res = core.biliTriple("BVtest")
    check("全失败时 ok=False", res.get("ok") is False, str(res)[:60])
    check("全失败时 done 为空", not (res.get("done") or []), res.get("done"))
finally:
    core.shutdown()

print()
if fails:
    print(f"失败 {len(fails)} 项：")
    for name in fails:
        print("  - " + name)
    sys.exit(1)
print("本轮四项修复的测试全部通过")
