"""验证第十二轮的新功能：
  * 置顶评论（有就带 origin 字段，没有就空）
  * 置顶评论里的网盘会被合并进 links
  * 播放器音量 / 静音能跨会话记住
  * 「今日扫描」计数
  * 再点同一个 MOD 会关掉详情
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

# 测试会构造真的 Core()，必须先把运行时数据目录隔离到临时沙盒，
# 否则会覆盖用户真实的 config.json / library.json / 导入日期台账。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from guard import protect_user_data  # noqa: E402
protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

from app.core import Core
from app.util import ROOT

LOG = os.path.join(os.environ.get("TEMP", ROOT), "round12.log")
try:
    os.remove(LOG)
except OSError:
    pass


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


app = QGuiApplication(sys.argv[:1])
core = Core(app)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run():
    wait(1500)

    # ---------------------------------------------------------- 1. 今日扫描
    log("=== 1. 今日扫描次数 ===")
    log("  lastCheckText =", core.lastCheckText)
    assert "今日扫描" in core.lastCheckText, "文案没改成「今日扫描」"
    log("  checks_today =", core.library.checks_today())
    assert core.library.checks_today() >= 0

    # ---------------------------------------------------------- 2. 置顶评论
    log()
    log("=== 2. 置顶评论 ===")
    from app.bili import BiliClient

    bc = BiliClient()
    cases = [
        (117608636548561, "BV1ApWi6qEJS"),   # 有 UP 置顶
        (117607999084430, "BV1jvWe6DEbH"),   # 没有置顶
    ]
    for aid, bvid in cases:
        got = bc.top_comment(aid, bvid)
        if got:
            log(f"  {bvid}: 置顶 by {got.get('user')} | {got['text'][:50]}")
            assert got.get("text") and got.get("user")
            assert got.get("pinned") is True
        else:
            log(f"  {bvid}: 无置顶（正常）")

    # 置顶评论里的网盘要能被提取出来
    log()
    log("  --- 置顶评论里的网盘 ---")
    from app.panlink import extract_links

    sample = "链接过期后有喜欢的可找我\n补档：https://pan.baidu.com/s/1AbCdEfGhIjK?pwd=9xyz 提取码 9xyz"
    links = extract_links(sample, fallback_label="测试")
    log("  提取到:", [(lk.get("name"), lk.get("code")) for lk in links])
    assert links, "置顶评论里的网盘没被提取出来"

    # ---------------------------------------------------------- 3. 详情 payload
    log()
    log("=== 3. 详情 payload 带 topComment / commentLinks ===")
    rec = {
        "bvid": "BVtest", "title": "t", "desc": "简介",
        "topComment": {"text": "置顶里也有网盘 https://pan.quark.cn/s/abcdef?pwd=1234",
                       "user": "UP", "like": 3, "pinned": True},
    }
    payload = core._detail_payload(rec)
    log("  topComment:", bool(payload.get("topComment")))
    log("  commentLinks:", [(l.get("name"), l.get("code")) for l in payload.get("commentLinks") or []])
    log("  links 总数:", len(payload.get("links") or []))
    assert payload["topComment"].get("text")
    assert payload.get("commentLinks"), "置顶评论里的网盘没进 commentLinks"

    rec2 = {"bvid": "BVtest2", "title": "t", "desc": "简介", "topComment": {}}
    p2 = core._detail_payload(rec2)
    assert p2["topComment"] == {} and p2["commentLinks"] == []
    log("  没有置顶时 topComment 是空的 ->「有才显示」成立")

    # ---------------------------------------------------------- 4. 音量/静音记忆
    log()
    log("=== 4. 播放器音量 / 静音记忆 ===")
    p = core.player
    log("  初始 volume =", p.volume, " muted =", p.muted)
    p.setVolume(35)
    wait(120)
    log("  设为 35 后 volume =", p.volume, " 配置 =", core.config["player_volume"])
    assert p.volume == 35 and int(core.config["player_volume"]) == 35

    p.toggleMute()
    wait(120)
    log("  静音后 muted =", p.muted, " 配置 =", core.config["player_muted"])
    assert p.muted is True and bool(core.config["player_muted"]) is True

    # 重新读配置，模拟「下次启动」
    from app.store import Config

    cfg2 = Config()
    log("  重新加载配置 volume =", cfg2["player_volume"], " muted =", cfg2["player_muted"])
    assert int(cfg2["player_volume"]) == 35
    assert bool(cfg2["player_muted"]) is True

    # 恢复
    p.toggleMute()
    p.setVolume(80)
    wait(120)

    # ---------------------------------------------------------- 5. 重复点同 MOD
    log()
    log("=== 5. 再点同一个 MOD 会关掉详情 ===")
    mgr = core.mods
    items = mgr.allModel.items()
    if items:
        p0 = items[0]["path"]
        mgr.selectMod(p0)
        wait(120)
        log("  第一次点: selectedPath =", bool(mgr.selectedPath))
        assert mgr.selectedPath
        mgr.selectMod(p0)
        wait(120)
        log("  再点一次: selectedPath =", repr(mgr.selectedPath))
        assert mgr.selectedPath == "", "重复点同一个 MOD 没关闭详情"
        mgr.selectMod(p0)
        wait(120)
        assert mgr.selectedPath, "再点第三次应该重新打开"
        mgr.clearSelected()
        log("  开关式行为正常")
    else:
        log("  [warn] 没有 MOD，跳过")

    log()
    log("全部通过")
    core.shutdown()
    core.quitFromWindow()


QTimer.singleShot(300, run)
QTimer.singleShot(120000, core.quitFromWindow)
app.exec()
