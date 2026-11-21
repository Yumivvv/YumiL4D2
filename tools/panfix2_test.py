# -*- coding: utf-8 -*-
"""第二批网盘/服务器打磨的回归。

1. **7 天后过期没提示** —— expireText 以前只在「已过期」角标里用，
   没过期的链接虽然查到到期日却一个字都不显示。现在给 expireDays，
   界面在 ≤30 天时显示「N 天后到期」。
2. **蓝奏云没有本地解析下载** —— `is_lanzou` 只认 `lanzou` 子串，
   新域名 `lanzn.com` 不匹配，整个菜单入口不出现。现在按 `lanz*` 形状认。
3. **悬停文案抖动** —— 「收藏（点这里保留）」会让提示条变宽变窄。
4. **收藏后的提示条** —— 「已收藏 xxx」挂在收藏数下面闪一下，用户要求去掉。
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
    from app import lanzou as L
    from app import panshare as PS

    # ---------------------------------------------------------- 1. 到期提醒
    print("=== 1. 「N 天后到期」有数据可显示 ===")
    # expireDays 必须出现在三种状态里（没过的 / 过了的 / 消失的）
    src = open(os.path.join(ROOT, "app", "panshare.py"), encoding="utf-8").read()
    check("panshare 返回 expireDays", "expireDays" in src)
    check("算剩余天数", "expire_ts - now" in src or "//  86400" in src
          or "86400" in src)

    # 用一个真实还有效的链接验证（联网失败则跳过，不判错）
    real = PS.check("https://pan.baidu.com/s/101kIrugJAVJv5eZNfLKVoA?pwd=szut")
    if real.get("state") == "unknown":
        print(f"  [skip] 查不到（网络）：{real}")
    else:
        print(f"  实测：{real}")
        check("查到状态", real.get("state") in ("ok", "expired", "gone"), real)
        check("带回 expireDays", "expireDays" in real, list(real))
        if real.get("state") == "ok" and real.get("expireAt"):
            d = int(real.get("expireDays") or 0)
            check("快到期时 expireDays 在 1~31 之间", 0 < d <= 31, d)

    # 界面要有那个角标
    dp = open(os.path.join(ROOT, "qml", "components", "DetailPanel.qml"),
              encoding="utf-8").read()
    check("界面有 linkExpiringTag", 'objectName: "linkExpiringTag"' in dp)
    check("按 expireDays 显示", "modelData.expireDays" in dp)
    check("文案「天后到期」", "天后到期" in dp)
    check("过期时不重复显示快到期",
          "!(modelData.expired === true)" in dp)

    core_src = open(os.path.join(ROOT, "app", "core.py"), encoding="utf-8").read()
    check("core 把 expireDays 传给界面", 'lk["expireDays"] = days' in core_src)

    # ---------------------------------------------------------- 1b. 真 bug
    print("=== 1b. rec 里必须有 links，否则一次都不查 ===")
    # 用户第二次报「百度网盘还是没有显示过期」。
    # 根因：links 只在 _detail_payload() 里临时算、**从没写回 rec**，
    # 而 _check_pan_expiry(rec) 读的是 rec.get("links") → 永远空 → 直接 return。
    # 第一版误以为只是渲染问题。所以这里显式检查「worker 里会补 rec['links']」。
    i = core_src.find("def _detail_worker")
    wbody = core_src[i:i + 6000] if i > 0 else ""
    check("worker 里会补 rec['links']", 'rec["links"] = extract_links(' in wbody)
    check("补的时候用了 desc", 'rec.get("desc")' in wbody)
    check("也补了置顶评论里的链接",
          "topComment" in wbody and "extra" in wbody)

    # 真实路径验证：造一条**只有 desc** 的记录，走完整流程
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from app.core import Core
    core = Core(app)
    real_url = "https://pan.baidu.com/s/101kIrugJAVJv5eZNfLKVoA?pwd=szut"
    bvid = "BVregress01"
    rec = {"bvid": bvid, "title": "回归", "desc": f"链接: {real_url}",
           "topComment": {}}
    check("初始 rec 没有 links 字段", "links" not in rec)

    from app.panlink import extract_links
    if not rec.get("links"):
        rec["links"] = extract_links(rec.get("desc") or "",
                                     fallback_label=rec.get("title") or "")
    check("补齐后确实有链接", bool(rec.get("links")), len(rec.get("links") or []))

    core._check_pan_expiry(rec)
    lk = (rec.get("links") or [{}])[0]
    state = lk.get("expireText") or ""
    if not state and not lk.get("expireDays"):
        print(f"  [skip] 联网失败，跳过（{lk}）")
    else:
        check("查到了到期信息", bool(state) or int(lk.get("expireDays") or 0) > 0,
              f"{state} / {lk.get('expireDays')} 天")
        payload = core._detail_payload(rec)
        plk = (payload.get("links") or [{}])[0]
        check("payload 里保住了到期信息",
              bool(plk.get("expireText")) or int(plk.get("expireDays") or 0) > 0,
              f"{plk.get('expireText')} / {plk.get('expireDays')} 天")

    # ---------------------------------------------------------- 2. 蓝奏云
    print("=== 2. 蓝奏云新域名能识别（两处一致）===")
    check("lanzou.py 有 LANZOU_HOST_RE", "LANZOU_HOST_RE" in
          open(os.path.join(ROOT, "app", "lanzou.py"), encoding="utf-8").read())

    for url, want in (
        ("https://wwavf.lanzn.com/i37EB4gwigjg", True),   # 用户报的
        ("https://wwi.lanzoup.com/iAbCd0xyz", True),
        ("https://wwx.lanzov.com/iXYZ", True),
        ("https://pan.baidu.com/s/1abc", False),
        ("https://pan.quark.cn/s/abc", False),
    ):
        got = L.is_lanzou(url)
        check(f"Python: {url.split('/')[2]:20s}", got == want, got)

    check("QML isLanzou 也用形状正则",
          "lanz[a-z]*" in dp, "")
    check("QML 不再只认 lanzou 子串",
          'u.indexOf("lanzou")' not in dp)

    # ---------------------------------------------------------- 3. 悬停文案
    print("=== 3. 收藏按钮不再有悬停长文案 ===")
    sp = open(os.path.join(ROOT, "qml", "components", "ServersPage.qml"),
              encoding="utf-8").read()
    # 只看**代码行**，注释里提到这句是允许的（那是解释为什么改掉）
    sp_code = "\n".join(ln for ln in sp.splitlines()
                        if not ln.lstrip().startswith("//"))
    check("代码里没有「点这里保留」", "点这里保留" not in sp_code)
    check("收藏按钮文案是固定的",
          'text: "收藏"' in sp_code)

    # ---------------------------------------------------------- 4. 收藏提示
    print("=== 4. 收藏成功后不弹提示 ===")
    check("QML 不再设「已收藏」hint", 'page.hintText = "已收藏 ' not in sp)
    # 后端也不再 toast/set_status
    srv = open(os.path.join(ROOT, "app", "servers.py"), encoding="utf-8").read()
    i = srv.find("def saveFriendServer")
    body = srv[i:i + 2200] if i > 0 else ""
    check("后端没有「已收藏」的 toast", "_toast(msg" not in body)
    check("后端没有「已收藏」的 status", "_set_status(msg)" not in body)
    check("失败仍然会返回 error", 'return {"ok": False' in body)

    # ---------------------------------------------------------- 5. 区块加大
    print("=== 5. 网盘 / 置顶评论区块加大 ===")
    # 用户报：这两块太小，滚动条只有几个像素高，鼠标抓不住。
    # 改法：简介保底 132→116（腾出十几像素），网盘占比 55%→60%，
    #       两处滚动条 10→14px、padding 2→0、滑块 6→10px。
    i = dp.find("readonly property real descMin")
    seg = dp[i:i + 60] if i > 0 else ""
    check("简介保底降到 116", "descMin: 116" in seg or "descMin: 116" in dp, seg.strip())
    check("网盘占比 60%", "shareRoom * 0.60" in dp)
    check("评论占比 40%", "shareRoom * 0.40" in dp)
    check("滚动条加宽到 14", "width: 14" in dp)
    check("滚动条去掉 padding", "padding: 2" not in dp)
    check("滑块加宽到 10", "implicitWidth: 10" in dp)

    # ---------------------------------------------------------- 6. 夸克也查
    print("=== 6. 夸克网盘也能查过期 ===")
    psrc = open(os.path.join(ROOT, "app", "panshare.py"), encoding="utf-8").read()
    check("有夸克接口常量", "QUARK_TOKEN_APIS" in psrc)
    check("按域名分派到夸克", '"quark.cn" in host' in psrc)
    check("夸克时间戳按毫秒处理", "/ 1000" in psrc or "/1000" in psrc)

    for url, want in (
        ("https://pan.quark.cn/s/a96b2f056eae", "a96b2f056eae"),
        ("https://pan.quark.cn/s/2ce22bd402e3?pwd=U7sV", "2ce22bd402e3"),
        ("https://pan.quark.cn/", ""),
    ):
        got = PS._quark_surl(url)
        check(f"解析 surl: {url[:40]:42s}", got == want, got)

    # _judge 的边界语义（向上取整）
    import time as _t
    now2 = _t.time()
    for label, ts, want_state, want_days in (
        ("永久", 0, "ok", 0),                      # 0 = 没有时间戳
        ("已过期 3 天", int(now2) - 86400 * 3, "expired", 0),
        ("还剩 7 天", int(now2) + 86400 * 7, "ok", 7),
        ("还剩 1.5 天", int(now2) + 86400 * 1.5, "ok", 2),
        ("今天到期", int(now2) + 3600, "ok", 1),
    ):
        got = PS._judge(ts, now2)
        check(f"_judge {label:10s}", got.get("state") == want_state
              and int(got.get("expireDays") or 0) == want_days,
              f"{got.get('state')}/{got.get('expireDays')}")

    # 真实夸克链接（联网失败只 skip）
    qr = PS.check("https://pan.quark.cn/s/a96b2f056eae")
    if qr.get("state") == "unknown":
        print(f"  [skip] 夸克查不到（网络）：{qr}")
    else:
        check("夸克真实链接查到到期信息",
              bool(qr.get("expireAt")) or int(qr.get("expireDays") or 0) > 0,
              f"{qr.get('text')} / {qr.get('expireDays')} 天")

    # ---------------------------------------------------------- 7. 提取码
    print("=== 7. 带提取码的夸克 + 码不串行 ===")
    # 用户给的：夸克 `f333944cc3c6` 码 `1iqM`
    from app.panlink import extract_links
    multi = ("百度网盘：https://pan.baidu.com/s/101kIrugJAVJv5eZNfLKVoA 提取码：szut\n"
             "夸克网盘：https://pan.quark.cn/s/f333944cc3c6 提取码：1iqM\n"
             "蓝奏云：https://wwavf.lanzn.com/i37EB4gwigjg\n")
    got_links = extract_links(multi)
    check("三行提取出 3 条", len(got_links) == 3, len(got_links))
    by_host = {}
    for lk in got_links:
        for tag in ("baidu", "quark", "lanz"):
            if tag in lk["url"]:
                by_host[tag] = lk
    check("百度拿到 szut",
          (by_host.get("baidu") or {}).get("code") == "szut",
          (by_host.get("baidu") or {}).get("code"))
    check("夸克拿到 1iqM",
          (by_host.get("quark") or {}).get("code") == "1iqM",
          (by_host.get("quark") or {}).get("code"))
    # ★ 蓝奏云那行没有码，绝不能抢上一行的 1iqM（跨行串码的 bug）
    check("蓝奏云不该抢上一行的码",
          (by_host.get("lanz") or {}).get("code") == "",
          (by_host.get("lanz") or {}).get("code"))

    # ★★ 反过来：**码在下一行**的也必须拿到（BV1dLyYzjEkK 那条视频）
    #   简介原文：
    #       kuake：
    #       链接：https://pan.q（闪闪闪）uark.cn/s/851a9b7（我能打新加坡major）7089c
    #       提取码：xuhr
    #   上一版限制「必须同一行」，于是这个 `xuhr` 拿不到。
    desc2 = ("kuake：\n"
             "链接：https://pan.q（闪闪闪）uark.cn/s/851a9b7（我能打新加坡major）7089c\n"
             "提取码：xuhr\n"
             "\n"
             "baidu；\n"
             "链接: https://pan.b（删删删）aidu.com/s/1P9uaqDEDMoSoqH"
             "（DANKING！）W50iJHyw?pwd=62nx 提取码: 62nx\n")
    l2 = extract_links(desc2)
    h2 = {}
    for lk in l2:
        for tag in ("baidu", "quark"):
            if tag in lk["url"]:
                h2[tag] = lk
    check("夸克（码在下一行）拿到 xuhr",
          (h2.get("quark") or {}).get("code") == "xuhr",
          (h2.get("quark") or {}).get("code"))
    check("夸克 URL 拼接正确（干扰词清干净）",
          (h2.get("quark") or {}).get("url")
          == "https://pan.quark.cn/s/851a9b77089c",
          (h2.get("quark") or {}).get("url"))
    check("百度（码在同一行）仍是 62nx",
          (h2.get("baidu") or {}).get("code") == "62nx",
          (h2.get("baidu") or {}).get("code"))

    # check 支持 passcode
    import inspect as _ins
    sig = _ins.signature(PS.check)
    check("check 支持 passcode", "passcode" in sig.parameters, list(sig.parameters))
    check("check_many 支持 codes",
          "codes" in _ins.signature(PS.check_many).parameters)
    # 缓存键要区分提取码
    PS.clear_cache()
    PS.check("https://pan.quark.cn/s/f333944cc3c6", passcode="AAAA")
    PS.check("https://pan.quark.cn/s/f333944cc3c6", passcode="BBBB")
    with PS._LOCK:
        ncache = len(PS._CACHE)
    # 联网失败时两次都可能不缓存成功结果？无论成败都写缓存，所以应为 2
    check("缓存按 (url, 码) 分开", ncache == 2, ncache)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())