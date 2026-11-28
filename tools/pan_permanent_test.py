# -*- coding: utf-8 -*-
"""「永久有效的网盘显示 26700 天后到期」的回归。

## 用户报的

> 修复永久有效的网盘显示 26700 天后到期的问题，
> 例子：https://pan.quark.cn/s/1396e2ca03d1

## 根因

夸克对**永久分享**不是「不给 `expired_at`」（文档里以前是这么假设的），
而是塞一个**固定的远未来时间戳**当哨兵。实测那条的原始响应：

    "expired_type": 1,
    "expired_at": 4102416000000     ← 毫秒

`4102416000` 秒 = **2100-01-01 00:00:00**。拿它去算「还剩几天」，
就是 26700 天 —— 数字没错，语义全错。

对照（同一天查的）：

| 分享 | expired_type | expired_at | 正确结论 |
| --- | --- | --- | --- |
| 1396e2ca03d1 | 1 | 2100-01-01 | **永久**（哨兵） |
| a96b2f056eae | 3 | 2026-11-28 | 3 天后，正常 |
| 百度 101kIrug… | 7 | 2026-11-27 | 百度写永久但给了真时间戳 → **以时间戳为准** |

## 修法

`panshare._is_permanent_sentinel()` 认这个哨兵值（2100-01-01 **且**
距离现在 >40 年，两条都满足），然后在**四个层次**都拦一遍：

| 位置 | 作用 |
| --- | --- |
| `_check_quark()` | 从接口拿到后先归一化成 0 |
| `_judge()` | 兜底：哨兵值走「永久有效」分支，不显示角标 |
| `expire_tag()` | 直接传哨兵值时也不吐天数 |
| `_refresh()` | 老缓存里存的哨兵值也清掉 |
| `core._check_pan_expiry()` | 不许把哨兵值写进 `library.json` |

多层拦截是因为「老数据里可能已经存了 26700 天」，只修入口不够。

## 本测试

离线验哨兵值判定 + 四个层次的拦截 + 边界（不能误伤真的长期限分享），
最后一节用**用户给的真实链接**跑一次（网络不通就 skip）。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from app import panshare as PS  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []

# 夸克「永久」用的哨兵值：2100-01-01 00:00:00（本地时区）
SENTINEL = 4102416000
URL_PERM = "https://pan.quark.cn/s/1396e2ca03d1"


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def skip(name: str, why: str) -> None:
    print("  [skip] " + name + "  " + why)
    SKIPS.append(name)


def main() -> int:
    # ---------------------------------------------- 1. 哨兵值判定
    print("=== 1. 认出哨兵值（2100-01-01）===")
    check("哨兵值本身被认出来", PS._is_permanent_sentinel(SENTINEL) is True,
          SENTINEL)
    check("0（真·永久）不算哨兵", PS._is_permanent_sentinel(0) is False)
    # ★ 不能误伤真的长期限分享
    check("2026 年的到期时间不算哨兵",
          PS._is_permanent_sentinel(1795881599) is False)
    check("2099-12-31 不算哨兵（不是 2100-01-01）",
          PS._is_permanent_sentinel(4102358400) is False)
    check("离现在只有 40 年的不算哨兵",
          PS._is_permanent_sentinel(int(time.time()) + 40 * 366 * 86400) is False)
    # 2100-01-01 当天但距离很近是不可能的，这里只验「同年同日」那条判据
    import datetime
    same_day = int(time.mktime(
        datetime.datetime(2100, 1, 1, 23, 59, 59).timetuple()))
    check("2100-01-01 当天任意时刻都算哨兵（时区容差）",
          PS._is_permanent_sentinel(same_day) is True, same_day)

    # ---------------------------------------------- 2. 各层拦截
    print("=== 2. 每个可能算天数的入口都不许吐出 26700 ===")
    judge = PS._judge(SENTINEL, time.time())
    check("_judge 判成「永久有效」", judge.get("text") == "永久有效",
          judge.get("text"))
    check("_judge 的 expireDays = 0", judge.get("expireDays") == 0,
          judge.get("expireDays"))
    check("_judge 的 expireAt 归零", judge.get("expireAt") == 0,
          judge.get("expireAt"))
    check("_judge 不给角标", judge.get("expireTag") == "",
          repr(judge.get("expireTag")))

    tag = PS.expire_tag(SENTINEL)
    check("expire_tag 直接传哨兵值也不吐文字", tag["tag"] == "",
          repr(tag["tag"]))
    check("expire_tag 的天数是 0", tag["expireDays"] == 0, tag["expireDays"])

    refreshed = PS.refresh({"ok": True, "state": "ok", "text": "x",
                            "expireAt": SENTINEL})
    check("_refresh 清掉老缓存里的哨兵值",
          refreshed.get("expireAt") == 0, refreshed.get("expireAt"))
    check("_refresh 之后不显示角标", refreshed.get("expireTag") == "",
          repr(refreshed.get("expireTag")))

    # ---------------------------------------------- 3. 全套字段都要齐
    print("=== 3. 永久有效时字段齐全（界面不会拿到 undefined）===")
    j = PS._judge(SENTINEL, time.time())
    for k in ("expired", "expireDays", "expireAt", "expireTag",
              "expireLevel", "state", "text"):
        check(f"带 {k}", k in j, sorted(j))
    check("expired=False（永久不是过期）", j.get("expired") is False)

    # ---------------------------------------------- 4. 真实链接
    print("=== 4. 用户给的真实链接 ===")
    PS.clear_cache()
    real = PS.check(URL_PERM)
    if real.get("state") == "unknown":
        skip("真实链接", real.get("text") or "接口不可达")
    else:
        check("state=ok", real.get("state") == "ok", real.get("state"))
        check("说「永久有效」", "永久" in str(real.get("text")),
              real.get("text"))
        check("expireAt 归零", int(real.get("expireAt") or 0) == 0,
              real.get("expireAt"))
        check("expireDays 是 0（不是 26700）",
              int(real.get("expireDays") or 0) == 0, real.get("expireDays"))
        check("没有角标（不该显示「N 天后到期」）",
              str(real.get("expireTag") or "") == "",
              repr(real.get("expireTag")))

    # 对照组：有真期限的那条，必须**仍然是个正常分享**（没被哨兵判定误伤）。
    #
    # ★ 这里以前断言「必须是 N 天后到期」。那是墙钟依赖：那条分享到期的
    #   绝对时刻是固定的，跑测试时如果它只剩几个小时，正确结果本来就会变成
    #   「N 小时后到期」—— 断言一红就看起来像回归，其实是测试写死了。
    #   （实测：2026-11-28 18:xx 跑，它只剩 4 小时。）
    #
    #   要盯的语义其实是两条：
    #     1. 没被当成「永久」（expireAt 还在、不是 0）；
    #     2. 没被当成「已过期」（state 仍是 ok）；
    #   只要这两条成立，哨兵判定就没有误伤它 —— 至于说的是「天」还是「小时」，
    #   由 expire_tag 按剩余时长自己决定。
    ct = PS.check("https://pan.quark.cn/s/a96b2f056eae")
    if ct.get("state") == "unknown":
        skip("对照组（有期限的分享）", "接口不可达")
    else:
        check("对照组仍是个正常分享（没被误判成永久）",
              int(ct.get("expireAt") or 0) > 0, ct.get("expireAt"))
        check("对照组没被误判成过期", ct.get("state") == "ok", ct.get("state"))
        check("对照组有角标（不是空的）",
              str(ct.get("expireTag") or "") != "", repr(ct.get("expireTag")))
        # 文案必须落在「天后 / 小时后 / 1 小时内」这三档之一 —— 不许再出现
        # 「今天到期」那种模糊说法，也不许没有单位。
        tag = str(ct.get("expireTag") or "")
        check("对照组文案是明确的时长",
              any(u in tag for u in ("天后到期", "小时后到期", "小时内到期")), tag)

    # ---------------------------------------------- 5. 老数据（library.json 里存过 26700）
    print("=== 5. 老数据里已经存了 26700 天的，读出来也要正常 ===")
    from app import core as C
    rec = {
        "bvid": "BVSENT",
        "title": "t",
        "desc": f"夸克：{URL_PERM}",
        "links": [{"url": URL_PERM, "code": "", "expired": False,
                   "expireText": "2100-01-01 到期",
                   "expireAt": SENTINEL, "expireDays": 26700}],
    }
    d = C.Core._detail_payload(rec)
    lk = (d.get("links") or [{}])[0]
    check("老数据不再显示「26700 天后」",
          "26700" not in str(lk.get("expireTag")), lk.get("expireTag"))
    check("老数据的角标为空", str(lk.get("expireTag") or "") == "",
          repr(lk.get("expireTag")))
    check("老数据的 expireAt 归零", int(lk.get("expireAt") or 0) == 0,
          lk.get("expireAt"))
    check("老数据的 expireDays 归零", int(lk.get("expireDays") or 0) == 0,
          lk.get("expireDays"))

    # ---------------------------------------------- 6. 源码断言
    print("=== 6. 别把修复改回去 ===")
    ps_src = open(os.path.join(ROOT, "app", "panshare.py"),
                  encoding="utf-8").read()
    check("有 _is_permanent_sentinel", "def _is_permanent_sentinel(" in ps_src)
    check("_judge 里拦了哨兵值",
          "or _is_permanent_sentinel(expire_s)" in ps_src)
    check("expire_tag 里也拦了", "_is_permanent_sentinel(at)" in ps_src)
    check("_refresh 里也拦了",
          "_is_permanent_sentinel(at)" in ps_src.split("def _refresh", 1)[1][:900])
    # 夸克那边要显式归一化（别只靠 _judge 兜底）
    q = ps_src.split("def _check_quark", 1)[1]
    # 截到下一个顶层函数为止（固定字符数会把断言切在半路 —— 实测偏移 2905）
    q_end = q.find("\ndef ", 10)
    q = q[:q_end] if q_end > 0 else q[:6000]
    check("夸克入口先把哨兵值归一化成 0",
          "if _is_permanent_sentinel(expire_s):" in q
          and "expire_s = 0" in q.split("if _is_permanent_sentinel(expire_s):", 1)[1][:200])
    core_src = open(os.path.join(ROOT, "app", "core.py"),
                    encoding="utf-8").read()
    check("core 也不许把哨兵值写进库",
          "PANS._is_permanent_sentinel(at)" in core_src)

    print()
    if SKIPS:
        print("跳过 %d 项（网络原因）：%s" % (len(SKIPS), " / ".join(SKIPS)))
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
