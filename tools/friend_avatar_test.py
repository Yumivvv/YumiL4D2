# -*- coding: utf-8 -*-
"""「服务器列表里好友在玩 → 显示好友头像」的回归。

## 实现链路（三层，每层都要能独立失败而不拖垮别的）

1. **steamfriends**：`_Steam.read_avatar_png()` 走
   `GetMediumFriendAvatar → GetImageSize → GetImageRGBA → BGRA→PNG`，
   然后 `_avatar_store()` 落盘到 `data/cache/avatar/<steamid>.png`。
2. **servers**：`_merged()` 的行里多一个 `friendAvatars`，
   和 `friends` **一一对应**（空串 = 这个好友还没抓到）。
3. **ServersPage.qml**：标签里有头像就画头像堆叠（最多 3 个），
   没有就退回原来的人形图标。

## 本测试盯什么

- 头像真的能从 Steam 取到像素（联网 + 本机 Steam 可用时；不可用就 skip）
- 磁盘缓存能命中、能清理「已经不是好友」的旧文件（只增不减会堆垃圾）
- `friends` / `friendAvatars` **长度和顺序一一对应**
  （★ 不能用名字做键 —— Steam 昵称不重复才怪）
- QML 侧：有头像走头像分支、没头像走回退分支，且**不因为没头像就把整个标签藏掉**
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from app import steamfriends as SF  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def skip(name: str, why: str) -> None:
    print("  [skip] " + name + "  " + why)
    SKIPS.append(name)


def png_bytes(rgb=(200, 60, 60)) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (64, 64), rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    # ---------------------------------------------- 1. 磁盘缓存
    print("=== 1. 头像落盘 / 命中 / 清理 ===")
    sid_a = "76561198000009001"
    sid_b = "76561198000009002"
    try:
        p = SF._avatar_store(sid_a, png_bytes())
        check("能落盘", bool(p) and os.path.isfile(p), p)
        check("落盘后能命中", SF._avatar_cached(sid_a) == p)
        check("大小合理（是张真图）",
              os.path.getsize(p) > 64 if p else False)
        # 0 字节 / 极小文件要当成「没有」（否则界面会显示破图）
        bad = os.path.join(SF._avatar_dir(), "tiny.png")
        with open(bad, "wb") as f:
            f.write(b"x")
        check("坏文件（太小）当成没有",
              SF._avatar_cached("tiny") == "", SF._avatar_cached("tiny"))
        os.remove(bad)

        # 空 sid / 空字节 → 不落盘
        check("空 sid 不落盘", SF._avatar_store("", png_bytes()) == "")
        check("空字节不落盘", SF._avatar_store("76561198000009003", b"") == "")

        # 清理：不属于好友列表的旧文件要删掉
        SF._avatar_store(sid_b, png_bytes((10, 200, 10)))
        SF._prune_avatars({sid_a})
        check("不在好友列表的头像被清掉",
              SF._avatar_cached(sid_b) == "", SF._avatar_cached(sid_b))
        check("还在好友列表的头像保留",
              SF._avatar_cached(sid_a) != "", SF._avatar_cached(sid_a))
    finally:
        for s in (sid_a, sid_b):
            try:
                os.remove(SF._avatar_cached(s))
            except OSError:
                pass

    # ---------------------------------------------- 2. 真去 Steam 取像素
    print("=== 2. 真的从 Steam 取一张头像（本机 Steam 可用时）===")
    s = SF._Steam()
    opened = False
    try:
        opened = s.open()
    except Exception as e:  # noqa: BLE001
        print("  open EXC", e)
    if not opened:
        skip("Steam 取头像", s.err or "Steam 不可用")
    else:
        try:
            friends = s.read_friends()
        finally:
            pass
        check("能读到好友", len(friends) > 0, len(friends))
        got = b""
        target = None
        if friends:
            # 挑一个在线的（在线的头像下载更快）
            online = [f for f in friends if f["state"] != 0]
            target = (online or friends)[0]
            try:
                got = s.read_avatar_png(int(target["sid"]))
            except Exception as e:  # noqa: BLE001
                print("  read_avatar_png EXC", e)
        if not got:
            skip("Steam 取头像", "这次没拿到（头像异步下载，可能要再试一次）")
        else:
            check("拿到了 PNG 字节", got[:8] == b"\x89PNG\r\n\x1a\n",
                  got[:8])
            check("大小合理", len(got) > 200, len(got))
            # 能解出 64x64
            from PIL import Image
            img = Image.open(io.BytesIO(got))
            check("尺寸是 64x64（medium）", img.size == (64, 64), img.size)
            # ★ 必须是**圆形**（四角透明）：QML 里 `Rectangle{radius;clip}`
            #   的 clip 是矩形的，圆角只能靠 Python 这边把 alpha 裁出来。
            if img.mode == "RGBA":
                a = img.getchannel("A")
                corners = [a.getpixel((0, 0)), a.getpixel((63, 0)),
                           a.getpixel((0, 63)), a.getpixel((63, 63))]
                center = a.getpixel((32, 32))
                check("四角是透明的（圆形裁切生效）",
                      all(c == 0 for c in corners), corners)
                check("中心不透明", center > 200, center)
            else:
                check("是带 alpha 的 RGBA", False, img.mode)
        s.close()

    # ---------------------------------------------- 3. servers 层
    print("=== 3. servers 行的 friendAvatars 和 friends 一一对应 ===")
    src = open(os.path.join(ROOT, "app", "servers.py"),
               encoding="utf-8").read()
    check("行里有 friendAvatars 字段", '"friendAvatars"' in src)
    # 两处（收藏行 + 好友行）都要有
    check("收藏行和好友行都带上了",
          src.count('"friendAvatars"') >= 2, src.count('"friendAvatars"'))
    # 必须按下标对应，不能按名字建 map（Steam 昵称会重名）
    check("用 list 不是 dict（防重名合并）",
          '"friendAvatars": [str(p.get("avatarPath") or "") for p in pals]'
          in src)

    # 真跑一遍（注入假数据，不依赖 Steam）
    print("=== 3b. 注入假好友，看行里带没带出来 ===")
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv[:1])
        from app.core import Core
        core = Core(app)
        mgr = core.servers

        addr = "9.9.9.9:27015"
        p1 = SF._avatar_store("76561198000009011", png_bytes())
        fake = [
            {"sid": "76561198000009011", "name": "有头像的",
             "state": 1, "stateLabel": "在线", "appId": 550,
             "playingL4D2": True, "addr": addr,
             "avatarPath": SF._avatar_cached("76561198000009011")},
            {"sid": "76561198000009012", "name": "没头像的",
             "state": 1, "stateLabel": "在线", "appId": 550,
             "playingL4D2": True, "addr": addr, "avatarPath": ""},
        ]
        mgr._friends_map = {addr: fake}
        mgr._favorites = lambda: [{"addr": addr, "name": "假服",
                                   "weight": 0, "panels": []}]
        mgr._live = {}
        rows = mgr._merged()
        row = next((r for r in rows if r.get("addr") == addr), None)
        check("找到注入的那一行", row is not None, len(rows))
        if row:
            names = row.get("friends") or []
            avs = row.get("friendAvatars") or []
            check("friendAvatars 和 friends 等长",
                  len(avs) == len(names), f"{len(avs)} vs {len(names)}")
            check("有头像那条是真实路径",
                  len(avs) > 0 and os.path.isfile(avs[0]), avs[:1])
            check("没头像那条是空串",
                  len(avs) > 1 and avs[1] == "", avs)
        core.shutdown()
    except Exception as e:  # noqa: BLE001
        skip("servers 注入验证", f"{type(e).__name__}: {e}")
    finally:
        try:
            os.remove(SF._avatar_cached("76561198000009011"))
        except OSError:
            pass

    # ---------------------------------------------- 4. QML
    print("=== 4. 界面：有头像画头像，没头像退回人形图标 ===")
    qml = open(os.path.join(ROOT, "qml", "components", "ServersPage.qml"),
               encoding="utf-8").read()
    check("有 friendAvatarList()", "function friendAvatarList(" in qml)
    check("读 friendAvatars", "row.friendAvatars" in qml)
    check("头像用 Image 画", 'source: modelData.path' in qml
          or "modelData.path.startsWith" in qml)
    check("回退：没头像时人形图标还在",
          "!friendTag.withAvatar" in qml)
    seg = qml.split('objectName: "friendTag"', 1)[1][:2200]
    check("★ 整个标签的显示条件只看 friends，不看头像",
          "visible: (modelData.friends || []).length > 0" in seg,
          seg[:150].replace("\n", " "))
    check("最多只画 3 个头像（卡片放不下更多）",
          "friendAvatarMax: 3" in qml)
    # ---- 位置：标签必须**单独成行**（在 IP 下面），不能挤在 IP 右边 ----
    # 用户报的「放到 IP 右边不太协调」。
    check("★ 好友标签不再锚在地址右边",
          "anchors.left: addrTxt.right" not in qml)
    check("★ 好友标签自己贴左（独立成行）",
          "anchors.left: parent.left" in seg, seg[:120].replace("\n", " "))
    # 地址行要独占一行、宽度撑满（不在右侧给标签留空间）
    check("地址行宽度撑满",
          "id: addrTxt\n                            width: parent.width" in qml,
          [ln.strip() for ln in qml.splitlines()
           if "id: addrTxt" in ln][:1])
    check("卡片高度够 5 行（140）", "height: 140" in qml)
    # ---- 尺寸：12px 认不出人，必须 >= 20 ----
    check("头像不小于 20px（12px 认不出是谁）",
          "friendAvatarSize: 24" in qml)
    check("标签高度跟着头像走（否则头像会溢出圆角）",
          "withAvatar ? avSize + 4 : 22" in qml)
    # ---- 圆形：必须靠 Python 端裁 alpha，不能指望 QML 的矩形 clip ----
    check("QML 不再用 `radius + clip` 假装圆形",
          "clip: true\n                                                color: Qt.rgba" not in qml)
    check("QML 里没有引入 Qt5Compat 依赖",
          not any(("Qt5Compat" in ln or "OpacityMask" in ln)
                  for ln in [x.strip() for x in qml.splitlines()
                             if x.strip() and not x.strip().startswith("//")]))

    sf_src = open(os.path.join(ROOT, "app", "steamfriends.py"),
                  encoding="utf-8").read()
    check("Python 端把头像裁成圆形",
          "putalpha" in sf_src and "ellipse" in sf_src)
    # ---- 路径要能喂给 Image：Windows 反斜杠得转成 / ----
    check("Windows 路径转换好了", '.replace(/\\\\/g, "/")' in qml
          or 'replace(/\\\\/g' in qml)

    print()
    if SKIPS:
        print("跳过 %d 项：%s" % (len(SKIPS), " / ".join(SKIPS)))
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
