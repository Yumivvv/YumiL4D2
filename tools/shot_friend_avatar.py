# -*- coding: utf-8 -*-
"""截图验证：放大后的好友头像（24px）到底认不认得出人。

用**真实 Steam 头像**做样本（不是纯色块）—— 纯色块看不出「能不能认出是谁」，
而这正是用户报的问题（「太小了，分辨不出来是谁」）。

用法：python -X utf8 tools\shot_friend_avatar.py [输出路径] [--real]
"""
import io
import os
import sys

ROOT = r"C:\Users\ZengDeRong\Desktop\编程\求生之路2公开"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from app import steamfriends as SF  # noqa: E402
from app.core import Core  # noqa: E402
from app.util import ROOT as APP_ROOT  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "friend_avatar_big.png")
USE_REAL = "--real" in sys.argv


def log(*a):
    print(*a, flush=True)


def wait_ms(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def collect_avatars() -> list[tuple[str, str]]:
    """拿三张（sid, 名字）用来当样本。优先真实 Steam 头像。"""
    out: list[tuple[str, str]] = []
    if USE_REAL:
        s = SF._Steam()
        try:
            if s.open():
                for f in s.read_friends():
                    if f["state"] == 0:
                        continue
                    png = s.read_avatar_png(int(f["sid"]))
                    if png:
                        SF._avatar_store(f["sid"], png)
                        out.append((f["sid"], f["name"]))
                    if len(out) >= 3:
                        break
        except Exception as e:  # noqa: BLE001
            log("real avatar failed:", e)
        finally:
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass
    # 兜底：生成带图案的色块（比纯色好认，能看出半径/裁剪对不对）
    if len(out) < 3:
        from PIL import Image, ImageDraw
        base = [(214, 72, 72), (66, 158, 216), (120, 200, 120)]
        for i, c in enumerate(base[len(out):]):
            img = Image.new("RGB", (64, 64), c)
            d = ImageDraw.Draw(img)
            d.ellipse([16, 12, 48, 44], fill=(250, 250, 250))   # 脸
            d.rectangle([24, 44, 40, 64], fill=(250, 250, 250))  # 身子
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            sid = f"7656119800000{9000 + i}"
            SF._avatar_store(sid, buf.getvalue())
            out.append((sid, ["小明", "小红", "阿强"][i]))
    return out


def main() -> int:
    app = QGuiApplication(sys.argv[:1])

    samples = collect_avatars()
    log("样本:", [(n, SF._avatar_cached(s) != "") for s, n in samples])

    eng = QQmlApplicationEngine()
    qml = os.path.join(APP_ROOT, "qml")
    eng.addImportPath(qml)
    eng.addImportPath(os.path.join(qml, "components"))
    core = Core(app)
    eng.rootContext().setContextProperty("core", core)
    eng.load(QUrl.fromLocalFile(os.path.join(qml, "Main.qml")))
    if not eng.rootObjects():
        log("LOAD FAILED")
        return 1
    win = eng.rootObjects()[0]
    win.show()
    wait_ms(1500)

    mgr = core.servers
    addr = "1.2.3.4:27015"

    # 三个好友都有头像（正常情况）
    fake = [
        {"sid": sid, "name": name, "state": 1, "stateLabel": "在线",
         "appId": 550, "playingL4D2": True, "addr": addr,
         "avatarPath": SF._avatar_cached(sid)}
        for sid, name in samples[:3]
    ]
    mgr._friends_map = {addr: fake}
    mgr._favorites = lambda: [
        {"addr": addr, "name": "好友在玩 · 三个都有头像",
         "weight": 0, "panels": []},
        # 对照组：没头像 → 应该退回人形图标
        {"addr": "5.6.7.8:27015", "name": "对照组 · 没头像",
         "weight": 0, "panels": []},
    ]
    mgr._live = {}
    mgr._friends_map["5.6.7.8:27015"] = [
        {"sid": "76561198999999999", "name": "还没头像的好友", "state": 1,
         "stateLabel": "在线", "appId": 550, "playingL4D2": True,
         "addr": "5.6.7.8:27015", "avatarPath": ""},
    ]
    mgr.serversChanged.emit()
    wait_ms(400)

    win.setProperty("section", 3)
    wait_ms(1800)

    def shoot():
        win.grabWindowShot(OUT)
        QTimer.singleShot(900, finish)

    def finish():
        log("saved:", os.path.exists(OUT), OUT)
        app.quit()

    QTimer.singleShot(700, shoot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
