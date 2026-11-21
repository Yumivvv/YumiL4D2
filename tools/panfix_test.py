# -*- coding: utf-8 -*-
"""网盘链接提取 / 过期检测这批修复的回归。

覆盖四个用户报的问题：

1. **蓝奏云换了域名**（`wwavf.lanzn.com`）后提取不到 ——
   旧表的匹配是子串（`lanzou` in host），新域名 `lanzn` 不含这个词根。
2. **疑似链接误提**：简介里随口提「百度网盘：pan.baidu.com」
   「steamcommunity.com 上有很多 MOD」也被当成网盘链接列出来，
   点开只是首页。现在裸域名必须有分享路径才算。
3. **链接里插英文干扰**：`https://pan.b（删删删）aidu.com/s/1P9uaqDEDMoSoqH（DANKING！）W50iJHyw`
   以前只删中文，`DANKING` 被留下拼进 URL → 提取出一个**打不开的错误链接**。
4. **百度网盘过期检测**：截图里「过期时间：永久有效」那一行，
   现在会用 shorturlinfo 查真实过期时间，过期/失效在链接旁标出来。
"""
import os
import sys

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
    from app import panlink as P

    # ---------------------------------------------------------- 1. 蓝奏云新域名
    print("=== 1. 蓝奏云换域名后还能提取 ===")
    for url in (
        "https://wwavf.lanzn.com/i37EB4gwigjg",     # 用户报的这个
        "https://wwi.lanzoup.com/iAbCd0xyz",        # 老域名
        "https://pan.lanzou.com/iabc",              # 更老的
        "https://wwx.lanzov.com/iXYZ",              # 又一个变体
    ):
        got = P.extract_links(f"下载：{url}")
        ok = bool(got) and got[0].get("url") == url
        check(f"{url.split('/')[2]:22s}", ok,
              got[0].get("url") if got else "(没提取到)")

    # 形状兜底：伪造一个没登记过的新域名
    fake = "https://wwzz.lanzq.com/iFAKE123"
    got = P.extract_links(fake)
    check("没登记过的 lanz* 新域名也能认出（按形状兜底）",
          bool(got) and got[0].get("name") == "蓝奏云",
          got[0].get("name") if got else "(没提取到)")

    # ---------------------------------------------------------- 2. 误提
    print("=== 2. 只是提到网盘名，不该当成链接 ===")
    for text in (
        "百度网盘：pan.baidu.com",
        "pan.quark.cn 这个站不错",
        "steamcommunity.com 上有很多MOD",
        "爱发电 afdian.com 支持我",
        "123pan.com 很好用",
        "阿里云盘 alipan.com 注册就送",
        "https://pan.baidu.com",           # 带协议头但没路径
    ):
        got = P.extract_links(text)
        check(f"不提取：{text[:26]:28s}", not got,
              got[0].get("url") if got else "")

    # ---------------------------------------------------------- 3. 英文干扰
    print("=== 3. 括号里的英文干扰词要整段删掉 ===")
    dirty = ("链接: https://pan.b（删删删）aidu.com/s/1P9uaqDEDMoSoqH"
             "（DANKING！）W50iJHyw?pwd=62nx")
    clean = "链接: https://pan.baidu.com/s/1P9uaqDEDMoSoqHW50iJHyw?pwd=62nx"
    gd = P.extract_links(dirty)
    gc = P.extract_links(clean)
    check("干扰版能提取", bool(gd), "")
    check("干净版能提取", bool(gc), "")
    if gd and gc:
        check("两者提取出的 URL **完全一致**",
              gd[0]["url"] == gc[0]["url"],
              f"\n        干扰={gd[0]['url']}\n        干净={gc[0]['url']}")
        check("没有把 DANKING 拼进 URL",
              "DANKING" not in gd[0]["url"].upper())
        check("提取码正确", gd[0].get("code") == "62nx", gd[0].get("code"))

    # 各种括号都要能删
    for wrap in ("（X）", "(X)", "【X】", "[X]", "〔X〕", "「X」", "《X》"):
        t = f"https://pan.baidu.com/s/1abc{wrap}def?pwd=12"
        g = P.extract_links(t)
        ok = bool(g) and wrap[0] not in g[0]["url"] and "X" not in g[0]["url"]
        check(f"括号 {wrap} 被清掉", ok, g[0]["url"] if g else "(没提取到)")

    # ---------------------------------------------------------- 4. 过期检测
    print("=== 4. 百度网盘过期检测 ===")
    from app import panshare as PS

    # 只测纯逻辑（不联网）：surl 解析 + 非百度直接 unknown
    check("surl 解析", PS._surl("https://pan.baidu.com/s/1P9uaqDEDMoSoqHW50iJHyw?pwd=1")
          == "1P9uaqDEDMoSoqHW50iJHyw", PS._surl("https://pan.baidu.com/s/1P9uaqDEDMoSoqHW50iJHyw"))
    check("带短横线的 surl", PS._surl("https://pan.baidu.com/s/1Ab-C_d") == "1Ab-C_d")
    check("没有 /s/ 就返回空", PS._surl("https://pan.baidu.com/") == "")

    r = PS.check("https://pan.quark.cn/s/abc")
    check("非百度 → unknown", r.get("state") == "unknown", r)

    r2 = PS.check("")
    check("空串 → unknown", r2.get("state") == "unknown", r2)

    # 联网部分：失败也不判错（网络环境不可控），只要求「不崩、给出状态」
    print("  （以下一项需要联网，失败只提示不算失败）")
    import time
    real = PS.check("https://pan.baidu.com/s/1P9uaqDEDMoSoqHW50iJHyw?pwd=62nx")
    st = real.get("state")
    if st == "unknown":
        print(f"  [skip] 查不到（网络/接口问题）：{real}")
    else:
        check("真实链接能查到状态", st in ("ok", "expired", "gone"), real)
        check("有可显示的文字", bool(real.get("text")), real.get("text"))
        if real.get("expireAt"):
            check("给了过期时间戳", int(real["expireAt"]) > 0, real["expireAt"])
            check("时间戳在合理范围（2020~2035）",
                  1577836800 < int(real["expireAt"]) < 2051222400,
                  real["expireAt"])

    # ---------------------------------------------------------- 5. 界面
    print("=== 5. 界面有「已过期」角标 ===")
    dp = open(os.path.join(ROOT, "qml", "components", "DetailPanel.qml"),
              encoding="utf-8").read()
    check("DetailPanel 有 linkExpiredTag", 'objectName: "linkExpiredTag"' in dp)
    check("按 modelData.expired 显示", "modelData.expired === true" in dp)
    check("文案区分已过期/已失效", '"已失效"' in dp and '"已过期"' in dp)

    th = open(os.path.join(ROOT, "qml", "L4D2", "Theme.qml"),
              encoding="utf-8").read()
    check("Theme 有 error 颜色", "property color error:" in th)

    core_src = open(os.path.join(ROOT, "app", "core.py"), encoding="utf-8").read()
    check("core 引入了 panshare", "panshare as PANS" in core_src)
    check("详情加载后查过期", "_check_pan_expiry" in core_src)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())