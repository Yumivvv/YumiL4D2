"""视频详情面板的空间分配：网盘 / 置顶评论多起来时，简介不能被挤没。

用户报的现象是「网盘链接过多导致简介看不到」，还有「被提取的链接在简介里看不到」。
根因是统计区下面三块（网盘区 / 置顶评论 / 简介）各占各的固定上限，一多起来
简介那块算出来就是 0 高。现在按剩余高度做预算，简介至少留 132px。

这个脚本不联网、不截图：直接给详情面板塞一份「网盘很多 + 简介很长」的数据，
量三块的实际高度。
"""
from __future__ import annotations

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard import protect_user_data  # noqa: E402

protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from app.core import Core  # noqa: E402
from app.util import ROOT, ensure_dirs  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def height_of(root, name):
    obj = root.findChild(QObject, name)
    if obj is None:
        return None
    return float(obj.property("height") or 0)


def main() -> int:
    ensure_dirs()
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    q = os.path.join(ROOT, "qml")
    engine.addImportPath(q)
    engine.addImportPath(os.path.join(q, "components"))
    core = Core(app)
    engine.rootContext().setContextProperty("core", core)
    engine.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))
    if not engine.rootObjects():
        print("  FAIL Main.qml 没加载起来")
        return 1
    win = engine.rootObjects()[0]
    win.show()
    wait(2000)

    # 一条「网盘特别多、评论也带网盘、简介又长」的视频
    links = []
    for i in range(9):
        links.append({
            "url": "https://pan.baidu.com/s/abcdefg%d" % i,
            "label": "整合包 %d" % i,
            "code": "ab%d" % i,
            "name": "baidu",
        })
    comment_links = [{
        "url": "https://pan.quark.cn/s/xyz%d" % i,
        "label": "评论里的补档 %d" % i,
        "code": "cd%d" % i,
        "name": "quark",
    } for i in range(4)]
    video = {
        "bvid": "BV1xx411c7mD",
        "title": "网盘特别多的一个视频",
        "author": "测试UP",
        "mid": "12345",
        "pubText": "2026-11-10 12:00:00",
        "viewsText": "1.2万",
        "replyText": "34",
        "likeText": "56",
        "favText": "7",
        "coinText": "8",
        "shareText": "9",
        "tname": "单机游戏",
        "pages": [{"page": 1, "part": "P1", "duration": 100}],
        "desc": "这是简介。" * 400,
        "links": links,
        "topComment": {"text": "补档在这，解压码 1234", "like": 12, "links": comment_links},
        "commentLinks": comment_links,
        "coverUrl": "",
    }
    win.setProperty("detailVideo", video)
    win.setProperty("detailOpen", True)
    wait(1200)

    h_links = height_of(win, "dpLinksBox")
    h_comment = height_of(win, "dpCommentBox")
    h_desc = height_of(win, "dpDescFlick")

    print("=== 空间分配 ===")
    print("  网盘区 = %s  置顶评论 = %s  简介 = %s" % (h_links, h_comment, h_desc))
    check("找到了三块（有 objectName 才好量）",
          None not in (h_links, h_comment, h_desc),
          "%s / %s / %s" % (h_links, h_comment, h_desc))
    if None not in (h_links, h_comment, h_desc):
        check("网盘很多时简介还在（>= 120px）", h_desc >= 120, "%.1f" % h_desc)
        check("网盘区没被撑爆（<= 160px）", h_links <= 160, "%.1f" % h_links)
        check("置顶评论也出现了", h_comment > 0, "%.1f" % h_comment)
        check("置顶评论没被撑爆（<= 160px）", h_comment <= 160, "%.1f" % h_comment)
        check("三块加起来没超出面板",
              h_links + h_comment + h_desc <= float(win.property("height") or 1320),
              "%.0f" % (h_links + h_comment + h_desc))

    # 只有很短的内容时：简介也不该被无谓地撑大 / 压小
    short = dict(video)
    short["desc"] = "很短"
    short["links"] = []
    short["commentLinks"] = []
    short["topComment"] = {}
    win.setProperty("detailVideo", short)
    wait(900)
    h2_links = height_of(win, "dpLinksBox")
    h2_desc = height_of(win, "dpDescFlick")
    check("没有网盘时网盘区收起来", (h2_links or 0) == 0, str(h2_links))
    check("简介还是看得见", (h2_desc or 0) >= 120, str(h2_desc))

    core.shutdown()
    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
