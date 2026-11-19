"""检查 MOD 文件 / 更新检查（不用联网的确定性部分）。

盯三件事：
  1. 本地文件是用工坊 ID 命名的，`identifyWorkshop()` 能认出「有几个工坊 MOD」；
     没有工坊 ID 的目录会明确提示，而不是默默什么都不做。
  2. 更新判据：工坊 `time_updated` 比本地文件 mtime 新（留 60 秒余量）才算「有新版本」，
     反过来说「用户自己动过文件」不会被误报成有更新。
  3. 「检查MOD」按钮走的是单条 `identifyOne()`，它只补这一条、不整盘重扫
     （重扫会把用户刚点的那一行弹回列表顶部）。
"""
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
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEventLoop, QTimer          # noqa: E402
from PySide6.QtGui import QGuiApplication              # noqa: E402

from guard import protect_user_data                    # noqa: E402

protect_user_data()

from app.core import Core                              # noqa: E402
from app.modmanager import ModManager                  # noqa: E402

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


def wait_until(app, cond, ms=8000, step=120):
    spent = 0
    while spent < ms:
        if cond():
            return True
        wait(app, step)
        spent += step
    return cond()


def main() -> int:
    sandbox = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "data", "_upd_mods")
    sandbox = os.path.abspath(sandbox)
    os.makedirs(sandbox, exist_ok=True)
    for f in os.listdir(sandbox):
        try:
            os.remove(os.path.join(sandbox, f))
        except OSError:
            pass

    wid_hit = "3727891945"      # 有工坊信息的
    wid_old = "3829533320"      # 本地文件比工坊还新的
    wid_plain = "my_own_mod"    # 没有工坊 ID 的本地 MOD
    for name in (f"{wid_hit}.vpk", f"{wid_old}.vpk", f"{wid_plain}.vpk"):
        with open(os.path.join(sandbox, name), "wb") as fh:
            fh.write(b"\x34\x12\xaa\x55" + b"\x00" * 32)

    now = int(time.time())
    hit_file = os.path.join(sandbox, f"{wid_hit}.vpk")
    os.utime(hit_file, (now - 7 * 86400, now - 7 * 86400))   # 本地那份是一周前下的
    old_file = os.path.join(sandbox, f"{wid_old}.vpk")
    os.utime(old_file, (now + 86400, now + 86400))           # 本地文件「更新」

    mm_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "app", "modmanager.py"), encoding="utf-8").read()

    app = QGuiApplication(sys.argv[:1])
    core = Core(app)
    mgr = ModManager()
    # 先把启动时那次「扫真实 addons 目录」等完，再换成沙盒目录；
    # 否则 localCount 里混着用户真实的 99 个 MOD，断言全都不准。
    wait_until(app, lambda: not mgr.busy, 20000)

    print("=== 1. 识别工坊 ID ===")
    mgr.setAddonsDir(sandbox)
    ok3 = wait_until(app, lambda: mgr.localCount == 3 and not mgr.busy, 20000)
    check("沙盒里的 3 个 MOD 都列出来了", ok3 and mgr.localCount == 3, str(mgr.localCount))

    ids = [m.get("workshopId") for m in mgr._all_local]
    check("两个用 ID 命名的认得出来",
          wid_hit in ids and wid_old in ids, str(ids))
    check("没有工坊 ID 的不算工坊 MOD（workshopId 为空）",
          ids.count("") == 1, str(ids))

    print("=== 2. 更新判据（工坊 time_updated vs 本地 mtime）===")
    # 直接往 modmeta 里塞数据，避免依赖网络
    wsc = mgr._wsc
    wsc.put(wid_hit, {"ok": True, "title": "更新测试 MOD", "preview": "",
                      "updated": now - 3600,
                      "created": now - 86400, "size": 1024, "author": "tester",
                      "tags": ["Weapons"], "views": 10, "subs": 2,
                      "fetched_at": now})
    wsc.put(wid_old, {"ok": True, "title": "本地更新过的 MOD", "preview": "",
                      "updated": now - 86400,
                      "created": now - 86400, "size": 1024, "author": "tester",
                      "tags": ["Weapons"], "views": 10, "subs": 2,
                      "fetched_at": now})
    mgr.scan()
    wait_until(app, lambda: mgr.localCount == 3 and not mgr.busy, 20000)
    rows = {m.get("workshopId"): m for m in mgr._all_local}
    hit = rows.get(wid_hit) or {}
    old = rows.get(wid_old) or {}
    check("工坊那里更新过 → 标出「有新版本」", hit.get("hasUpdate") is True,
          str(hit.get("hasUpdate")))
    check("有新版本时给了文案", bool((hit.get("updateText") or "").strip()),
          str(hit.get("updateText")))
    check("本地文件更新过 → 不误报", old.get("hasUpdate") is False,
          "mtime 比工坊新，hasUpdate=%s" % old.get("hasUpdate"))
    check("工坊标题用上了", (hit.get("title") or "") == "更新测试 MOD",
          str(hit.get("title")))
    check("浏览/订阅数字带上了",
          (hit.get("viewsText") or "") != "" and (hit.get("subsText") or "") != "",
          "%s / %s" % (hit.get("viewsText"), hit.get("subsText")))

    print("=== 3. 「检查MOD」是单条补，不整盘重扫 ===")
    before = mgr.localCount
    mgr.identifyOne(os.path.join(sandbox, f"{wid_hit}.vpk"))
    wait(app, 1500)
    check("单条检查没有整盘重扫（行数不变、模型没被重置）",
          mgr.localCount == before, "%d -> %d" % (before, mgr.localCount))
    check("单条检查走的是 _apply_meta_to_items（只原位更新）",
          "_apply_meta_to_items" in mm_src
          and "self.scan()" not in mm_src.split("def _identify_one_worker")[1][:1200])

    print("=== 4. 没有工坊 ID 时的提示 ===")
    empty_dir = os.path.join(sandbox, "_plain_only")
    os.makedirs(empty_dir, exist_ok=True)
    for f in os.listdir(empty_dir):
        os.remove(os.path.join(empty_dir, f))
    with open(os.path.join(empty_dir, "aaa.vpk"), "wb") as fh:
        fh.write(b"\x34\x12\xaa\x55")
    mgr.setAddonsDir(empty_dir)
    wait_until(app, lambda: mgr.localCount == 1)
    mgr.identifyWorkshop()
    wait(app, 800)
    check("纯本地 MOD 会明说「没有工坊 ID」",
          "工坊" in mgr.statusText, mgr.statusText)

    core.shutdown()
    for f in os.listdir(sandbox):
        try:
            os.remove(os.path.join(sandbox, f))
        except OSError:
            pass
    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
