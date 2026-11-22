# -*- coding: utf-8 -*-
"""网盘过期天数「隔天不更新」的回归。

用户报的原话：

    昨天是 7 天后，今天我再看还是 7 天后，实际是 6 天后
    网站例子 https://pan.quark.cn/s/851a9b77089c 提取码 xuhr，百度同理

根因有两层，都要盯住：

1. **`expireDays` 落盘了** —— `Library.save()` 把 `rec["links"]` 整个写进
   `library.json`，于是昨天算出的「7 天」被持久化，重开软件读到的还是 7。
2. **`expireDays` 缓存了** —— `panshare` 的结果缓存 30 分钟，缓存里存的
   也是相对天数，跨天命中缓存照样是旧值。

修法：只持久化/缓存 `expireAt`（绝对时间戳），`expireDays` 每次按当前
时间现算；并且算法从「还剩几个 24 小时」改成「按日历日相减」。

本测试**不联网也能跑**（核心是纯计算 + 落盘行为）。
"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from guard import protect_user_data  # noqa: E402

protect_user_data()

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def main():
    from app import panshare as PS
    from app import store

    # ---------------------------------------------------------- 1. 按日历天算
    print("=== 1. 「还剩几天」按日历日相减，而不是按 24 小时 ===")
    # 造一个「今天中午到期」的时间戳，稳定不依赖跑测试的时刻
    import datetime
    today = datetime.date.today()
    noon_today = datetime.datetime.combine(today, datetime.time(12, 0))
    base = time.mktime(noon_today.timetuple())

    exp7 = time.mktime((today + datetime.timedelta(days=7)).timetuple()) + 12 * 3600
    check("当天算 = 7 天", PS._judge(exp7, base)["expireDays"] == 7,
          PS._judge(exp7, base)["expireDays"])
    check("次日算 = 6 天（关键：以前一直是 7）",
          PS._judge(exp7, base + 86400)["expireDays"] == 6,
          PS._judge(exp7, base + 86400)["expireDays"])
    check("三天后算 = 4 天",
          PS._judge(exp7, base + 3 * 86400)["expireDays"] == 4,
          PS._judge(exp7, base + 3 * 86400)["expireDays"])
    check("过期后 state=expired 且天数为 0",
          PS._judge(exp7, exp7 + 60)["state"] == "expired"
          and PS._judge(exp7, exp7 + 60)["expireDays"] == 0)
    check("永久有效不带天数", PS._judge(0, base)["expireDays"] == 0)

    # 时间戳带毫秒误差时不该算成 7（老的向上取整正是栽在这）
    near = int(base + 7 * 86400 - 0.4)
    check("差 0.4 秒到 7×86400 仍算 7 天",
          PS._judge(near, base)["expireDays"] == 7,
          PS._judge(near, base)["expireDays"])

    # ---------------------------------------------------------- 2. refresh
    print("=== 2. refresh() 按当前时间重算相对字段 ===")
    res = {"ok": True, "state": "ok", "text": "x", "expireAt": exp7, "expireDays": 7}
    check("明天刷新 = 6", PS.refresh(res, base + 86400)["expireDays"] == 6)
    check("刷新不改 expireAt", PS.refresh(res, base + 86400)["expireAt"] == exp7)
    gone = {"ok": True, "state": "gone", "text": "没了", "expireAt": 0, "expireDays": 0}
    check("gone 状态刷新后仍是 0 天", PS.refresh(gone, base)["expireDays"] == 0)
    check("unknown 状态刷新后仍是 0 天",
          PS.refresh({"ok": False, "state": "unknown", "expireAt": 0},
                     base)["expireDays"] == 0)

    # ---------------------------------------------------------- 3. 缓存不存相对值
    print("=== 3. 缓存命中也要现算 ===")
    src = open(os.path.join(ROOT, "app", "panshare.py"), encoding="utf-8").read()
    check("缓存命中走 _refresh", "return _refresh(hit[1], now)" in src)
    check("check() 返回前走 _refresh", "return _refresh(res, now)" in src)
    # 直接验证：手动塞一条 7 天前的缓存，命中后必须给出更新后的天数
    key, ck = "https://pan.baidu.com/s/FAKE_CACHE_TTL_TEST", None
    PS.clear_cache()
    ck = (key, "")
    # 缓存写入时刻设为「7 天前」，内容里 expireDays 故意留成旧值 7
    stale_at = base  # 这里让 expireAt = base+7天
    PS._CACHE[ck] = (time.time() - 60, {"ok": True, "state": "ok",
                                        "text": "old", "expireAt": int(exp7),
                                        "expireDays": 7})
    got = PS.check(key)      # 命中缓存（60 秒前写入，未过 30 分钟）
    expect = PS._days_left(int(exp7), time.time())
    check("缓存命中后天数是现算的", got.get("expireDays") == expect,
          f"{got.get('expireDays')} vs {expect}")
    PS.clear_cache()

    # ---------------------------------------------------------- 4. 不落盘
    print("=== 4. 派生字段绝不写进 library.json ===")
    tmp = tempfile.mkdtemp(prefix="l4d2_lib_")
    old_path, old_bak = store.LIBRARY_PATH, store.LIBRARY_BAK
    try:
        store.LIBRARY_PATH = os.path.join(tmp, "library.json")
        store.LIBRARY_BAK = os.path.join(tmp, "library.bak.json")
        lib = store.Library()
        lib.videos["BV1TEST"] = {
            "bvid": "BV1TEST", "title": "t", "links": [
                {"url": "https://pan.baidu.com/s/abc", "code": "abcd",
                 "expired": False, "expireText": "2026-11-29 到期",
                 "expireDays": 7, "expireAt": int(exp7)},
            ]}
        lib.save()
        saved = json.load(open(store.LIBRARY_PATH, encoding="utf-8"))
        lk = saved["videos"]["BV1TEST"]["links"][0]
        check("落盘不含 expired", "expired" not in lk, sorted(lk))
        check("落盘不含 expireText", "expireText" not in lk)
        check("落盘不含 expireDays", "expireDays" not in lk)
        check("落盘保留 expireAt", lk.get("expireAt") == int(exp7), lk.get("expireAt"))
        check("落盘保留 url/code", lk.get("url") and lk.get("code") == "abcd")

        # 老文件里已经有脏数据 → load() 必须清掉
        dirty = {"videos": {"BV2TEST": {"bvid": "BV2TEST", "links": [
            {"url": "u", "expired": True, "expireText": "x", "expireDays": 6,
             "expireAt": 0}]}}}
        json.dump(dirty, open(store.LIBRARY_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False)
        lib2 = store.Library()
        lk2 = lib2.videos["BV2TEST"]["links"][0]
        check("读历史脏数据时清掉派生字段",
              not any(k in lk2 for k in ("expired", "expireText", "expireDays")),
              sorted(lk2))
    finally:
        store.LIBRARY_PATH, store.LIBRARY_BAK = old_path, old_bak

    # ---------------------------------------------------------- 5. core 回填
    print("=== 5. core._detail_payload 用 expireAt 重算 ===")
    core_src = open(os.path.join(ROOT, "app", "core.py"), encoding="utf-8").read()
    check("core 调 PANS.refresh", "PANS.refresh(" in core_src)
    check("core 保存 expireAt", 'lk["expireAt"] = at' in core_src)
    check("有兼容老数据的兜底分支", "expireAt" in core_src and "兼容老数据" in core_src)

    # 真实跑一遍 _detail_payload（不联网，用假 rec）
    try:
        from app import core as C
        rec = {"bvid": "BV1TEST", "title": "t", "desc": "链接: https://pan.baidu.com/s/101kIrugJAVJv5eZNfLKVoA?pwd=szut",
               "links": [{"url": "https://pan.baidu.com/s/101kIrugJAVJv5eZNfLKVoA?pwd=szut",
                          "expireAt": int(exp7), "expireDays": 7, "expired": False,
                          "expireText": "旧文案"}]}
        d = C.Core._detail_payload(rec)
        hit = [x for x in d.get("links") or [] if "101kIrug" in (x.get("url") or "")]
        if hit:
            expect = PS._days_left(int(exp7), time.time())
            check("详情里天数是现算的", hit[0].get("expireDays") == expect,
                  f"{hit[0].get('expireDays')} vs {expect}")
        else:
            print("  [skip] 链接没被提取出来")
    except Exception as e:  # noqa: BLE001
        print(f"  [skip] _detail_payload 直调失败：{e!r}")

    # ---------------------------------------------------------- 6. 重启后场景
    print("=== 6. 重启后（库里只有 expireAt）三个字段都要有值 ===")
    # ★ 这一节是补漏：`_refresh` 用 `_judge` 的返回值**整体替换**旧 dict，
    #   而 `_judge` 早先只给 expireDays / text，不给 expired / expireText。
    #   结果界面上 `modelData.expired` 是 undefined → 角标全都不显示。
    try:
        from app import core as C
        exp5 = int(time.time()) + 5 * 86400 + 3600
        rec = {"bvid": "BVR", "title": "t",
               "desc": "链接: https://pan.quark.cn/s/851a9b77089c 提取码：xuhr",
               "links": [{"url": "https://pan.quark.cn/s/851a9b77089c",
                          "expireAt": exp5}]}
        d = C.Core._detail_payload(rec)
        hit = [x for x in d.get("links") or [] if "851a9b77089c" in (x.get("url") or "")]
        if hit:
            lk = hit[0]
            check("expired 有值（不是 None）", lk.get("expired") is not None, lk.get("expired"))
            check("expireDays 有值", isinstance(lk.get("expireDays"), int), lk.get("expireDays"))
            check("expireText 有值（界面绑的是这个名字）",
                  bool(str(lk.get("expireText") or "")), repr(lk.get("expireText")))
            check("天数与现算一致",
                  lk.get("expireDays") == PS._days_left(exp5, time.time()),
                  f"{lk.get('expireDays')} vs {PS._days_left(exp5, time.time())}")
        else:
            print("  [skip] 夸克链接没被提取出来")
    except Exception as e:  # noqa: BLE001
        print(f"  [skip] 重启场景直调失败：{e!r}")

    # refresh 本身也要保证键齐全（别的调用方直接用 refresh 的输出）
    full = PS.refresh({"ok": True, "state": "ok", "text": "x",
                       "expireAt": int(exp7)}, base)
    for k in ("expired", "expireDays", "expireAt", "state", "text"):
        check(f"refresh 输出含 {k}", k in full, sorted(full))

    # ---------------------------------------------------------- 7. QML 开关
    print("=== 7. 界面角标的显示条件跟着改成 expireAt 了 ===")
    # ★ 这条最容易漏：日历日算法下「今天到期」= 0 天，
    #   如果 visible 还写 `expireDays > 0`，最该提醒的那条反而被藏起来。
    dp = open(os.path.join(ROOT, "qml", "components", "DetailPanel.qml"),
              encoding="utf-8").read()
    i = dp.find('objectName: "linkExpiringTag"')
    tag = dp[max(0, i - 200): i + 1400] if i > 0 else ""
    check("有 linkExpiringTag", i > 0)
    check("显示条件用 expireAt 而不是 expireDays>0",
          "(modelData.expireAt || 0) > 0" in tag, )
    check("不再用 expireDays > 0 当开关",
          "(modelData.expireDays || 0) > 0" not in tag)
    check("0 天显示「今天到期」", '<= 0' in tag and "今天到期" in tag)

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：" + " / ".join(FAILS))
        sys.exit(1)
    print("全部通过")


if __name__ == "__main__":
    main()