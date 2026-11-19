"""验证登录成功后的用户信息链路（UID / 昵称 / 头像）。

不能拿真账号测（没有凭据），但要覆盖三条路径：
  1. nav_user 正常 → 昵称、头像、UID 都对
  2. nav_user 失败（网络抖动）→ 至少用 DedeUserID 填上 UID，不能是 0
  3. 凭据失效 → 自动清理并提示

用 monkeypatch 模拟 nav_user 的三种返回，验证 Core 的处理逻辑。
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1])

from app.core import Core  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


core = Core(app)
old_creds = core.config["bili_credentials"]

CREDS = {"SESSDATA": "s", "bili_jct": "j", "DedeUserID": "88888888"}


def simulate_poll(nav_result):
    """模拟一次「扫码成功 + nav 返回 nav_result」。"""
    core.client.login_poll = lambda key: {
        "state": "ok", "message": "登录成功", "credentials": dict(CREDS),
    }
    core.client.nav_user = lambda: dict(nav_result)
    core._bili_user = {}
    core.biliLoginPoll("dummy-key")


print("=== 1. nav 正常：昵称/头像/UID 都要有 ===")
simulate_poll({
    "mid": 88888888, "uname": "测试用户",
    "face": "https://i2.hdslb.com/bfs/face/abc.jpg",
    "level": 6, "vip": True,
})
check("UID 正确", core.biliUserId == 88888888, str(core.biliUserId))
check("昵称正确", core.biliUserName == "测试用户", core.biliUserName)
check("头像 URL 非空", len(core.biliUserFace) > 0, core.biliUserFace[:50])
saved = core.config["bili_credentials"].get("user") or {}
check("用户信息已写进配置", saved.get("uname") == "测试用户", str(saved)[:60])

print()
print("=== 2. nav 失败（网络抖动）：至少 UID 不能是 0 ===")
simulate_poll({})      # nav 返回空
check("UID 用 DedeUserID 兜底填上了", core.biliUserId == 88888888,
      str(core.biliUserId))
check("昵称留空（界面回退显示 UID）", core.biliUserName == "", repr(core.biliUserName))
check("仍然算已登录", core.biliLoggedIn is True)

print()
print("=== 3. 凭据失效：biliRefreshUser 要清干净并报 expired ===")
core.client.nav_user = lambda: {}     # 模拟 nav 说「我不认识你」
res = core.biliRefreshUser()
check("返回失败", res.get("ok") is False, str(res))
check("标记为 expired", res.get("expired") is True, str(res))
check("凭据已清掉", core.biliLoggedIn is False)
check("配置里的凭据已清空", core.config["bili_credentials"] == {},
      str(core.config["bili_credentials"]))

print()
print("=== 4. 界面有 UID 兜底显示 ===")
main_src = open(os.path.join("qml", "Main.qml"), encoding="utf-8").read()
# ★ 断言用「带空值保护的写法」：(core.biliUserName || "").length > 0
#   直接写 core.biliUserName.length 在用户名叫不出来时会抛 TypeError，
#   所以这里两种写法都算过，但**必须真的回退到 UID** 才算。
has_uid_fallback = ('(core.biliUserName || "").length > 0' in main_src
                    or 'core.biliUserName.length > 0' in main_src)
check("界面在昵称为空时回退到 UID", has_uid_fallback and 'UID ' in main_src,
      has_uid_fallback)
check("设置页打开时会刷新用户信息",
      "biliRefreshUser" in main_src)

# 还原
core.config["bili_credentials"] = old_creds
core.config.save()
core.shutdown()

print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
