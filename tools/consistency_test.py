# -*- coding: utf-8 -*-
"""「同一件事只有一个实现」的守卫测试。

## 用户的要求

> 同样是 22 小时后到期，但是显示是一天后，前面显示的倒是正常今天到期，
> 这种就是典型代码没统一的问题，而且都分开，导致很多东西都是独立或者屎山代码，
> 全部检测一遍，软件内如果代码重复性较高的帮我统一一点简化

这份测试就是**防止再次分叉**：把「本来是一个概念、却散在多处」的东西钉死。

## 这次统一掉的东西

| 概念 | 以前 | 现在 |
| --- | --- | --- |
| 体积格式化 | `util` / `core` / `mods` / `wallpaper` / `player` / `downloads` / `addonlist` / `workshop_dl` 共 **8 份**实现 | 只有 `util.human_size`，其余转发 |
| 剥 HTML 标签 | `lanzou` 和 `workshop_dl` 各一份，**行为还不一样** | 只有 `util.strip_tags` |
| 清文件名 | `lanzou`（120 字、保留尾点）和 `workshop_dl`（180 字、去尾点）不一致 | 只有 `util.safe_filename(max_len=...)` |
| 到期文案 | QML 里拼「今天到期」/「N 天后到期」，两个角标各算一套 | 只有 `panshare.expire_tag()`，QML 只显示 |
| 「失效 vs 过期」判断 | QML 里 `indexOf("不存在")` | 只有 `core._looks_gone()` |
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def read(*parts: str) -> str:
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def main() -> int:
    # ------------------------------------------------ 1. 体积格式化
    print("=== 1. 体积格式化只有一个实现（util.human_size）===")
    util_src = read("app", "util.py")
    check("util.human_size 存在", "def human_size(" in util_src)
    # 判断「重复实现」的特征：for unit in ("B", "KB", ...) 这种循环体
    # 只在 util 里允许出现一次。
    dup = []
    for name in ("core.py", "mods.py", "wallpaper.py", "player.py",
                 "downloads.py", "addonlist.py", "workshop_dl.py"):
        src = read("app", name)
        # 排除函数内部的转发调用（那只有一行 return human_size(...)）
        body_hits = re.findall(
            r'for unit in \("B", "KB", "MB", "GB"', src)
        if body_hits:
            dup.append(name)
    check("其它模块里没有体积换算的循环体", not dup, str(dup))

    # 六个入口都还能正常格式化（转发没写错）
    from app import (addonlist, core, downloads, mods, player,  # noqa: F401
                     wallpaper)
    from app import util

    for label, fn in (
        ("util.human_size", util.human_size),
        ("mods.human_size", mods.human_size),
        ("wallpaper.human_size", wallpaper.human_size),
        ("player.human_bytes", player.human_bytes),
        ("core.human_bytes", core.human_bytes),
        ("downloads.human_size", downloads.human_size),
    ):
        ok = (fn(1024) == "1.0 KB" and fn(1536) == "1.5 KB")
        check(f"{label} 结果一致", ok, f"{fn(1024)} / {fn(1536)}")
    check("downloads 的 0 显示成破折号（未知）",
          downloads.human_size(0) == "—", downloads.human_size(0))
    check("其它地方的 0 显示成 0 B", util.human_size(0) == "0 B")

    # ------------------------------------------------ 2. strip_tags
    print("=== 2. 剥 HTML 标签只有一个实现（util.strip_tags）===")
    check("util.strip_tags 存在", "def strip_tags(" in util_src)
    lz_src = read("app", "lanzou.py")
    wdl_src = read("app", "workshop_dl.py")
    # 旧实现的特征正则不该再出现在这两个文件里
    old_re = '<[^>]'
    check("lanzou 不再自带标签正则",
          not re.search(r'def _strip_tags\(s: str\) -> str:\n    return html\.unescape\(re\.sub',
                        lz_src))
    check("workshop_dl 不再自带标签正则",
          not re.search(r'def _strip_tags\(s: str\) -> str:\n    s = re\.sub', wdl_src))
    # 行为要一致
    from app import lanzou, workshop_dl
    for s in ("<b>粗体</b>名字", "a<br>c", "x &amp; y", "  空白  "):
        a = util.strip_tags(s)
        b = lanzou._strip_tags(s)
        c = workshop_dl._strip_tags(s)
        check(f"三者一致 {s[:14]!r}", a == b == c, f"{a!r} / {b!r} / {c!r}")

    # ------------------------------------------------ 3. safe_filename
    print("=== 3. 清文件名只有一个实现（util.safe_filename）===")
    check("util.safe_filename 存在", "def safe_filename(" in util_src)
    check("lanzou 不再自带正则替换",
          "def _safe_filename(name: str) -> str:\n    s = re.sub" not in lz_src)
    from app import lanzou as LZ
    from app import workshop_dl as WD
    from app.util import safe_filename

    for s in ("夏侯渊awm+左轮.rar", "a/b/c.vpk", "bad:name?.vpk",
              "trailing. ", ""):
        a = safe_filename(s, max_len=120)
        check(f"一致 {s[:16]!r}", a == LZ._safe_filename(s),
              f"{a!r} vs {LZ._safe_filename(s)!r}")
    # Windows 不允许尾点/尾空格，两个入口都必须去掉
    for s in ("x.", "x ", "x. . "):
        check(f"去掉尾点/空格 {s!r}",
              not safe_filename(s).endswith((".", " ")),
              repr(safe_filename(s)))
        check(f"workshop_dl 也去掉 {s!r}",
              not WD._safe_filename(s).endswith((".", " ")),
              repr(WD._safe_filename(s)))

    # ------------------------------------------------ 4. 到期文案
    print("=== 4. 到期文案只在 panshare.expire_tag() 里算 ===")
    ps_src = read("app", "panshare.py")
    check("panshare.expire_tag 存在", "def expire_tag(" in ps_src)
    dp_src = read("qml", "components", "DetailPanel.qml")
    # QML 里不许再出现「现拼文案」的代码行
    dp_code = [ln.strip() for ln in dp_src.splitlines()
               if ln.strip() and not ln.strip().startswith("//")]
    for word in ("今天到期", "天后到期", "小时后到期"):
        bad = [ln for ln in dp_code if word in ln]
        check(f"QML 里不再拼「{word}」", not bad, str(bad[:2]))
    check("QML 只用后端给的 expireTag", "modelData.expireTag" in dp_src)

    from app import panshare as PS
    import datetime as dt
    now = dt.datetime(2026, 11, 25, 13, 0).timestamp()

    def tag(hours: float) -> str:
        return PS.expire_tag(now + hours * 3600, now)["tag"]

    check("22 小时 → 「22 小时后到期」（用户报的那条）",
          tag(22) == "22 小时后到期", tag(22))
    check("10 小时 → 「10 小时后到期」", tag(10) == "10 小时后到期", tag(10))
    check("24 小时 → 走「天」档", "天后到期" in tag(24), tag(24))
    check("72 小时 → 「3 天后到期」", tag(72) == "3 天后到期", tag(72))
    check("0.5 小时 → 「1 小时内到期」", tag(0.5) == "1 小时内到期", tag(0.5))
    check("负数 → 「已过期」", tag(-1) == "已过期", tag(-1))

    # 「今天到期」这个说法彻底退休了
    for h in (0.2, 1, 5, 10, 20, 23.9):
        check(f"{h} 小时不出现「今天到期」", "今天到期" not in tag(h), tag(h))

    # ------------------------------------------------ 5. 失效 vs 过期
    print("=== 5. 「失效 / 过期」的判断只在 core._looks_gone() ===")
    core_src = read("app", "core.py")
    check("core._looks_gone 存在", "def _looks_gone(" in core_src)
    check("QML 里不再用 indexOf 猜失效",
          'indexOf("不存在")' not in dp_src)
    from app.core import _looks_gone
    check("「已取消」判成失效", _looks_gone("分享不存在或已被取消") is True)
    check("「已过期」不判成失效", _looks_gone("分享已过期（已超过有效期）") is False)
    check("「已失效」判成失效", _looks_gone("分享已失效") is True)

    # ------------------------------------------------ 6. 数据键齐全
    print("=== 6. 每条链接都带齐界面要用的字段 ===")
    import time as _t
    from app import core as C

    future = int(_t.time()) + 7 * 86400
    rec = {
        "bvid": "BVTAG",
        "title": "t",
        "desc": "q: https://pan.quark.cn/s/dcb18f65c568?pwd=CdnP",
        "links": [{"url": "https://pan.quark.cn/s/dcb18f65c568?pwd=CdnP",
                   "code": "CdnP", "expired": False,
                   "expireText": "2026-12-02 到期",
                   "expireAt": future, "expireDays": 7}],
    }
    d = C.Core._detail_payload(rec)
    lk = (d.get("links") or [{}])[0]
    for k in ("expireTag", "expireLevel", "expired", "expireText",
              "expireDays", "expireAt"):
        check(f"链接带 {k}", k in lk, sorted(lk))
    check("expireTag 是可用文字", bool(str(lk.get("expireTag") or "")),
          lk.get("expireTag"))
    check("expireLevel 是 warn/error 之一",
          lk.get("expireLevel") in ("", "warn", "error"),
          lk.get("expireLevel"))

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
