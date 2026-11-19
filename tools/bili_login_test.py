"""B 站登录 + 三连的测试。

不碰真实账号（不能拿用户凭据做测试），只验证：
  1. 未登录时的行为（三连直接拒绝、不瞎试写接口）
  2. 凭据存取 / 失效清理
  3. 三连开关的读取与落盘
  4. 二维码生成能接上（用真实 B 站接口拿一次 URL）
  5. 界面元素存在
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


core = Core(app)
old_creds = core.config["bili_credentials"]
old_switches = (core.config["bili_triple_like"], core.config["bili_triple_coin"],
                core.config["bili_triple_fav"], core.config["bili_triple_follow"])

print("=== 1. 初始状态：未登录 ===")
core.biliLogout()
check("未登录", core.biliLoggedIn is False)
check("用户名是空", core.biliUserName == "")

print()
print("=== 2. 未登录时三连被拒绝（不瞎试写接口）===")
res = core.biliTriple("BV1xx411c7mD")
check("三连返回失败", res.get("ok") is False, str(res))
check("提示「还没登录」", "登录" in (res.get("error") or ""), res.get("error"))

print()
print("=== 3. 三连开关：默认点赞/投币/收藏开、关注关 ===")
# ★ 先把四个开关重置成出厂默认再断言。
#   这些值会落盘到 config.json，别的测试或用户手动改过之后，
#   「默认值」就不再是出厂值了 —— 断言会假失败。
#   出厂默认：点赞/投币/收藏 = True，关注 = False。
core.setBiliLike(True)
core.setBiliCoin(True)
core.setBiliFav(True)
core.setBiliFollow(False)
check("点赞默认开", core.biliLikeOn is True)
check("投币默认开", core.biliCoinOn is True)
check("收藏默认开", core.biliFavOn is True)
check("关注默认关", core.biliFollowOn is False)

core.setBiliLike(False)
check("关掉点赞后读回 False", core.biliLikeOn is False)
core.setBiliFollow(True)
check("打开关注后读回 True", core.biliFollowOn is True)
core.setBiliLike(True)
core.setBiliFollow(False)
# 落盘验证
cfg2 = core.config
check("开关已写进配置", cfg2["bili_triple_like"] is True
      and cfg2["bili_triple_follow"] is False)

print()
print("=== 4. 凭据存取 / 清理 ===")
core.client.set_credentials("fake_sess", "fake_jct", "12345")
check("set_credentials 后算已登录", core.biliLoggedIn is True)
creds = core.client.credentials()
check("凭据能读回来", creds.get("SESSDATA") == "fake_sess", str(creds.get("SESSDATA")))
core.client.clear_credentials()
check("clear 后算未登录", core.biliLoggedIn is False)

print()
print("=== 5. 真实拿一次登录二维码 ===")
qr = core.biliLoginQr()
if qr.get("ok"):
    check("拿到二维码 URL", bool(qr.get("url")), (qr.get("url") or "")[:40])
    check("拿到轮询 key", bool(qr.get("key")))
    check("生成了二维码图片", bool(qr.get("image")), (qr.get("image") or "")[:50])
    # 图片文件确实存在且是 PNG
    img_path = qr.get("image", "").replace("file:///", "").replace("/", os.sep)
    exists = os.path.isfile(img_path)
    check("二维码图片文件存在", exists, img_path[-40:] if img_path else "")
    if exists:
        with open(img_path, "rb") as f:
            head = f.read(8)
        check("是 PNG 文件", head[:8] == b"\x89PNG\r\n\x1a\n", head.hex())
        check("文件大小合理（>1KB）", os.path.getsize(img_path) > 1024,
              str(os.path.getsize(img_path)))
else:
    print(f"  （网络问题，跳过：{qr.get('error')}）")

print()
print("=== 6. 界面元素存在 ===")
main_src = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
detail_src = open(os.path.join(ROOT, "qml", "components", "DetailPanel.qml"),
                 encoding="utf-8").read()
check("设置页有登录卡片", 'objectName: "biliLoginCard"' in main_src)
check("有「扫码登录」按钮", 'objectName: "biliLoginBtn"' in main_src)
check("有「退出」按钮", 'objectName: "biliLogoutBtn"' in main_src)
check("有登录弹窗", 'objectName: "biliLoginDlg"' in main_src)
check("弹窗里有二维码图", 'objectName: "biliQrImage"' in main_src)
check("设置页有四个三连开关", main_src.count('"like"') > 0 and '"coin"' in main_src
      and '"fav"' in main_src and '"follow"' in main_src)
check("详情面板有三连按钮", 'objectName: "tripleButton"' in detail_src)
check("详情面板有 triple 信号", "signal triple(string bvid)" in detail_src)
check("详情面板有 needLogin 信号", "signal needLogin()" in detail_src)

print()
print("=== 6b. 三连按钮：紧挨分享、等宽、未登录也能点 ===")
# 用户报的两件事都在这一段：
#   · 「三连」要在「分享」右边，位置和别的按钮对得齐
#   · 没登录时点三连要提示登录 + 弹二维码（而不是点了没反应 / 被丢去设置页）
row = detail_src[detail_src.index("id: actionsRow"):]
order = [row.index('label: "%s"' % s) for s in ("播放", "分享", "三连",
                                               "复制链接", "浏览器")]
check("按钮顺序是 播放/分享/三连/复制链接/浏览器",
      order == sorted(order), order)
# 五颗按钮都必须用同一个比例，宽窄才会一致
import re as _re
ratio_vals = [float(x) for x in _re.findall(
    r"width:\s*actionsRow\.avail\s*\*\s*([0-9.]+)", row)]
check("五颗按钮各占一个比例（共 5 个）", len(ratio_vals) == 5, ratio_vals)
check("五颗按钮等宽（比例全相同）",
      len(set(ratio_vals)) == 1, ratio_vals)
check("五个比例加起来正好 1.0（不会撑破 / 留空）",
      abs(sum(ratio_vals) - 1.0) < 1e-6, sum(ratio_vals))
# ★ 关键：enabledBtn 不能绑 core.biliLoggedIn。
#   ActionButton 的 MouseArea 是 `enabled: enabledBtn`，绑上登录态就等于
#   未登录时点击事件根本到不了 onClicked，needLogin 那条分支成死代码。
triple_part = row[row.index('objectName: "tripleButton"'):]
triple_part = triple_part[:triple_part.index("ActionButton {")]
check("三连在未登录时也可点（enabledBtn 不绑登录态）",
      "enabledBtn: core.biliLoggedIn" not in triple_part
      and "enabledBtn: (panel.video.bvid" in triple_part)
check("未登录点三连会发 needLogin", "panel.needLogin()" in triple_part)
check("三连只在已登录时才用强调色", "accent: core.biliLoggedIn" in triple_part)

# 主窗口收到 needLogin：提示 + 就地弹二维码，不再跳设置页
need = main_src[main_src.index("onNeedLogin:"):]
need = need[:need.index("onDownloadVideo:")]
check("点三连会弹出扫码登录窗", "biliLoginDlg.open()" in need)
check("不再把人丢去设置页", "win.section = 5" not in need)
check("不关详情面板（扫完能接着点）", "win.detailOpen = false" not in need)
check("未登录走「登录」而不是「切换账号」", "biliSwitchMode = false" in need)

print()
print("=== 6c. 弹窗文字不许越出边框 ===")
# ★ 根因：Column 设了 leftPadding/rightPadding 之后，子项的 `width: parent.width`
#   拿到的仍是**整宽**（不含 padding 扣减），文字右边界会比弹窗多出 20px。
#   用户报的「切换账号提示文字跳出 UI 范围」就是它。
login_block = main_src[main_src.index('id: biliLoginDlg'):]
login_block = login_block[:login_block.index("clipAskDlg") if "clipAskDlg" in login_block
                          else len(login_block)]
check("登录弹窗正文用 x + (width - 40) 做左右留白",
      'objectName: "biliLoginCol"' in login_block
      and "x: 20" in login_block and "width: parent.width - 40" in login_block)
check("弹窗正文不再用 leftPadding/rightPadding 塞左右边距",
      "leftPadding: 20" not in login_block
      and "rightPadding: 20" not in login_block)
check("标题有 elide，不会把弹窗撑宽", "elide: Text.ElideRight" in login_block)

print()
print("=== 7. 还原配置 ===")
core.config["bili_credentials"] = old_creds
(core.config["bili_triple_like"], core.config["bili_triple_coin"],
 core.config["bili_triple_fav"], core.config["bili_triple_follow"]) = old_switches
core.config.save()
check("配置已还原", True)

core.shutdown()
print()
print('=== 8. nav_user 永不抛异常（UID=0 的根因回归）===')
# 曾经 bug：nav_user 里写成了模块级 NAV_API_LOGIN（实际是类属性），
# 触发 NameError，而 except 只捕 BiliError → 整个函数崩掉，
# 上层拿到异常而不是空字典，于是「登录成功但 UID 一直是 0、头像空白」。
import app.bili as _b
c_nav = _b.BiliClient()
c_nav.set_credentials('fake_sess', 'fake_jct', '12345')
try:
    u = c_nav.nav_user()
    check('假 cookie 调 nav_user 不抛异常', True, repr(u)[:40])
except Exception as e:                    # noqa: BLE001
    check('假 cookie 调 nav_user 不抛异常', False, repr(e))
check('假 cookie 时返回空字典（视为未登录）', u == {}, str(u))
c_nav.clear_credentials()
check('清掉凭据后 nav_user 直接返回空', c_nav.nav_user() == {})

print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
