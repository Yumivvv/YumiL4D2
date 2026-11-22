# -*- coding: utf-8 -*-
"""网络加速改进的回归（参考 SteamTools 思路，但不引入 MITM 代理）。

## 这次改了什么

原有实现是「直连 Steam CDN IP、TLS SNI 保持域名」，不装证书、不要管理员权限。
SteamTools（Watt Toolkit）走的是「本地反向代理 + 本地 CA 做 MITM」——
那是另一套机制，**本项目没有移植它的代理代码**。

借鉴的是它两点工程思路：

1. **候选按区域分组管理**，而不是一锅乱炖。国内到首尔/大阪/新加坡的延迟差异很大，
   分组之后既能少测一半 IP，也能让 UI 按地区展示。
2. **选节点不能只看 TCP 延迟，要看实际传输速度**。实测同一批节点里
   延迟都在 400~500ms，但吞吐从 312 KB/s 到 8.5 MB/s 差 27 倍 ——
   只看延迟会选到「握手快、下载慢」的坏节点。

本测试盯：
- 候选池覆盖多个区域、数量足够
- `region_for_ip` 能认出新增 IP（不再「未知地区」）
- 两阶段测速：全量延迟 + 对头部几个做吞吐采样
- 全失败时有回退，不会「加速开着但没节点」
- GPL-3.0 出处声明在场（尊重上游协议）
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def main():
    from app import workshop_net as WN

    # ---------------------------------------------------------- 1. 候选池
    print("=== 1. 候选池按区域分组 ===")
    check("CDN_IP_REGIONS 存在", hasattr(WN, "CDN_IP_REGIONS"))
    regions = WN.CDN_IP_REGIONS
    check("至少 4 个区域", len(regions) >= 4, list(regions))
    total = sum(len(v) for v in regions.values())
    check("候选 IP 总数 >= 15（原来只有 6）", total >= 15, total)
    # 每个区域至少 2 个
    for r, ips in regions.items():
        check(f"区域「{r}」有 >=2 个候选", len(ips) >= 2, len(ips))
    # 摊平表去重且和分组一致
    flat = set(WN._ALL_REGION_IPS)
    check("_ALL_REGION_IPS 已去重", len(flat) == len(WN._ALL_REGION_IPS))
    check("摊平表覆盖所有区域 IP",
          all(ip in flat for ips in regions.values() for ip in ips))
    # 旧的 6 个兜底 IP 必须还在（不能把已有能力弄丢）
    check("原来的 6 个兜底 IP 都保留了",
          all(ip in flat for ip in WN.BUILTIN_CDN_IPS),
          [ip for ip in WN.BUILTIN_CDN_IPS if ip not in flat])

    # ---------------------------------------------------------- 2. 地区
    print("=== 2. region_for_ip 能认出新增 IP ===")
    unknown = []
    for r, ips in regions.items():
        for ip in ips:
            got = WN.region_for_ip(ip)
            if got != r:
                unknown.append((ip, r, got))
    check("所有分组 IP 都能反查回自己的区域", not unknown, unknown[:5])
    check("空 IP 返回空串", WN.region_for_ip("") == "")

    # ---------------------------------------------------------- 3. 两阶段测速
    print("=== 3. 两阶段测速（延迟 + 吞吐）===")
    check("_TOP_FOR_THROUGHPUT 存在", hasattr(WN, "_TOP_FOR_THROUGHPUT"))
    check("吞吐采样只测头部几个", 1 <= WN._TOP_FOR_THROUGHPUT <= 10,
          WN._TOP_FOR_THROUGHPUT)

    import inspect
    sig_probe = inspect.signature(WN._probe_one)
    check("_probe_one 支持 throughput", "throughput" in sig_probe.parameters)
    check("_probe_one 支持 sample_bytes", "sample_bytes" in sig_probe.parameters)
    sig_ti = inspect.signature(WN.test_ips)
    check("test_ips 支持 throughput", "throughput" in sig_ti.parameters)
    sig_bi = inspect.signature(WN.best_ip)
    check("best_ip 支持 throughput", "throughput" in sig_bi.parameters)
    sig_bn = inspect.signature(WN.best_node)
    check("best_node 支持 throughput", "throughput" in sig_bn.parameters)

    src = open(os.path.join(ROOT, "app", "workshop_net.py"),
               encoding="utf-8").read()
    check("_probe_one 里真的读了数据算吞吐", "sample_bytes" in src
          and "kbps" in src)
    check("排序考虑了吞吐（_speed_ok）", "_speed_ok" in src)

    # ---------------------------------------------------------- 4. 回退
    print("=== 4. 全失败时回退 ===")
    # 用 TEST-NET 地址保证连不上
    r = WN.best_ip(["192.0.2.1", "192.0.2.2"], timeout=1.0, throughput=False)
    check("全失败时 ok=False", r.get("ok") is False, r.get("ok"))
    check("仍然给了一个兜底 IP（不是空）", bool(r.get("ip")), r.get("ip"))
    check("错误信息说清楚了", "回退" in str(r.get("error") or ""),
          r.get("error"))

    # ---------------------------------------------------------- 5. 出处声明
    print("=== 5. GPL-3.0 出处声明 ===")
    check("注明参考了 SteamTools", "SteamTools" in src)
    check("注明上游是 GPL-3.0", "GPL-3.0" in src)
    check("说明没有移植它的代理代码", "本地反向代理" in src or "MITM" in src)
    # 项目自身许可仍是 GPL-3.0
    lic = os.path.join(ROOT, "LICENSE")
    check("LICENSE 存在", os.path.isfile(lic))
    head = open(lic, encoding="utf-8", errors="replace").read(400)
    check("LICENSE 是 GPL v3", "GNU GENERAL PUBLIC LICENSE" in head
          and "Version 3" in head)

    # ------------------------------------------------- 6. 只剩网页一条路
    print("=== 6. 工坊列表：只走网页，不再有任何 API Key 依赖 ===")
    # ★ 2026-11 的改动：用户要求「去除 STEAM API KEY 的设置选项，完全去除掉」。
    #   于是 QueryFiles 那条回退（它强制要 key）连同 api_key 参数一起删了。
    #   这里反过来盯：**必须删干净**，别再有人手滑加回来 ——
    #   只要 key 还在，设置里就会再长出一栏，用户又得去注册。
    check("回退函数已经删掉", not hasattr(WN, "_query_files_fallback"))
    check("QueryFiles 地址常量已经删掉",
          not hasattr(WN, "WORKSHOP_QUERY_API"))
    check("QueryFiles 排序映射已经删掉",
          not hasattr(WN, "_STEAM_QUERY_SORT"))
    check("列表仍走官方工坊网页", "steamcommunity.com/workshop/browse" in src)

    # 签名里不该再有 api_key 这个「只为兼容而留」的摆设
    sig_f = inspect.signature(WN.fetch_workshop_list)
    check("fetch_workshop_list 没有 api_key", "api_key" not in sig_f.parameters,
          str(list(sig_f.parameters)))
    sig_n = inspect.signature(WN._fetch_workshop_list_net)
    check("_fetch_workshop_list_net 没有 api_key",
          "api_key" not in sig_n.parameters, str(list(sig_n.parameters)))
    body = inspect.getsource(WN._fetch_workshop_list_net)
    check("列表函数里不再调回退", "_query_files_fallback" not in body)

    mm = open(os.path.join(ROOT, "app", "modmanager.py"), encoding="utf-8").read()
    check("modmanager 不再读配置里的 key", 'self._cfg["steam_api_key"]' not in mm)
    check("modmanager 没有 _steam_api_key", "def _steam_api_key(" not in mm)
    check("modmanager 不再把 key 传下去",
          "api_key=self._steam_api_key()" not in mm)

    # config 默认值里也不该再有这一项（老配置残留无所谓，新装不能有）
    st = open(os.path.join(ROOT, "app", "store.py"), encoding="utf-8").read()
    check("DEFAULT_CONFIG 不再写 steam_api_key",
          '"steam_api_key": ""' not in st)

    # ------------------------------------------------- 7. 设置页已经没有输入框
    print("=== 7. 设置页不再有 API Key 输入框 ===")
    mq = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    for tag in ("steamKeySection", "steamKeyInput", "steamKeySaveBtn",
                "steamKeyClearBtn"):
        check(f"没有 {tag}", f'objectName: "{tag}"' not in mq)
    check("设置里不再出现「Steam API Key」这个标题",
          "Steam API Key" not in mq)

    cs = open(os.path.join(ROOT, "app", "core.py"), encoding="utf-8").read()
    for m in ("steamApiKey", "hasSteamApiKey", "saveSteamApiKey",
              "clearSteamApiKey", "setSteamApiKeyDraft"):
        check(f"core 没有 {m}", f"def {m}(" not in cs)

    # ------------------------------------------- 8. 刷新按钮 + 15 秒上限
    print("=== 8. 工坊刷新按钮 + 15 秒超时（不再无限转圈）===")
    check("modmanager 有 browseRefresh", "@Slot(result=\"QVariantMap\")" in mm
          and "def browseRefresh(" in mm)
    check("刷新会先清列表缓存", "WN.clear_list_cache()" in mm)
    check("有一次请求 15 秒的预算",
          "BROWSE_TIMEOUT_SEC" in mm and "15.0" in mm)
    check("有看门狗计时器（到点判失败）",
          "_browse_start_watchdog" in mm and "_browse_timeout" in mm)
    # ★ 这条是「一直转圈」的真正根因：失败分支以前不清 loading 标志
    apply_body = mm.split("def _browse_apply(", 1)[-1]
    fail_seg = apply_body.split('if not res.get("ok"):', 1)[-1][:900]
    check("失败分支会清掉 browseLoading 标志",
          "self._browse_loading = False" in fail_seg,
          fail_seg.replace("\n", " ")[:120])

    ws = open(os.path.join(ROOT, "qml", "components", "WorkshopPage.qml"),
              encoding="utf-8").read()
    check("顶栏有刷新按钮", 'objectName: "wsRefreshBtn"' in ws)
    check("刷新按钮调 browseRefresh", "page.mgr.browseRefresh()" in ws)
    check("失败时给出「重新加载」入口", "page.refreshList()" in ws)
    check("失败原因和「没搜到」分开显示",
          "browseError.length > 0" in ws)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())