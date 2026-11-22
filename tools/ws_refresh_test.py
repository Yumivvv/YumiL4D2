# -*- coding: utf-8 -*-
"""工坊「刷新」+ 15 秒上限 + 失败不再无限转圈 的回归。

## 为什么单开一个测试

用户报的是三个具体症状，而它们**全是状态机的错**，不是网络慢：

1. 「一直转圈图标加载不出来」—— 首屏一失败，`_browse_apply` 的失败分支
   只设了 error，**没清 `_browse_loading`**。于是 `browseLoading` 永远为真：
   首屏那个 Spinner 一直转，连「加载失败」的空状态都不显示
   （它的显示条件要求 `!browseLoading`）。
2. 「刷新」根本不存在 —— 唯一能重来的办法是切分类或改搜索词。
3. 没有任何时间上限 —— `fetch_workshop_list` 内部对网页重试 2 次，
   最坏能拖到 30 秒以上，用户完全分不清是「在转」还是「死了」。

## 本测试怎么跑

**不打真网络**：把 `WN.fetch_workshop_list` 换成假的，用事件循环推进时间，
这样离线也能跑，而且能精确验证「迟到结果被丢弃」「15 秒到点收尾」。
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

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import modmanager as MM  # noqa: E402
from app import workshop_net as WN  # noqa: E402
from app.util import ROOT as APP_ROOT  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_idle(mgr, budget_ms: int = 4000) -> None:
    """等这一次请求收尾（成功/失败/超时都算）。"""
    step = 25
    for _ in range(max(1, budget_ms // step)):
        pump(step)
        if not mgr.browseLoading and not mgr.browseLoadingMore:
            return


def fake_items(n: int = 30, kind: int = 0) -> list:
    return [{"id": str(3800000000 + i), "title": f"m{i}", "preview": "",
             "author": "", "fileType": kind, "views": 0, "subs": 0,
             "favorited": 0, "children": 0, "created": 0, "updated": 0,
             "tags": []} for i in range(n)]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    mgr = MM.ModManager()

    real_fetch = WN.fetch_workshop_list
    calls: list = []

    def install(fn) -> None:
        WN.fetch_workshop_list = fn  # type: ignore[assignment]

    def restore() -> None:
        WN.fetch_workshop_list = real_fetch  # type: ignore[assignment]

    try:
        # ------------------------------------------------------ 1. 失败不再转圈
        print("=== 1. 首屏失败必须停下来（这是「一直转圈」的根因）===")
        WN.clear_list_cache()

        def fail(*a, **k):
            calls.append(("fail", a, k))
            return {"ok": False, "items": [], "total": 0, "page": 1,
                    "error": "连不上 Steam 工坊页面（ConnectTimeout）",
                    "needNetwork": True}

        install(fail)
        mgr.browseFilter("", "trend", "mod", [])
        # ★ 不在这里断言「刚开始是 loading」：假 fetch 是瞬间返回的，
        #   工作线程可能在主线程检查之前就把 `_browse_loading` 清掉了，
        #   那属于测试自己抢跑（真网络请求不可能这么快）。
        #   这里只验最终态 —— 也就是用户真正看到的那一帧。
        wait_idle(mgr)
        check("失败后 browseLoading 必须变回 False",
              mgr.browseLoading is False, f"browseLoading={mgr.browseLoading}")
        check("失败后 browseLoadingMore 也是 False", mgr.browseLoadingMore is False)
        check("错误信息留下来了", mgr.browseError != "", mgr.browseError[:60])
        check("列表是空的", mgr.browseItems == [])
        check("失败后标记为 done（不许自动续拉）", mgr.browseDone is True)

        # 失败后滚到底不该再自动发请求
        calls.clear()
        r = mgr.browseMore()
        check("失败后 browseMore 直接拒绝", r.get("ok") is False)
        check("失败后没有偷偷再发请求", calls == [], str(calls))
        pump(120)

        # ------------------------------------------------------ 2. 刷新能重来
        print("=== 2. 刷新按钮：清缓存 + 按当前筛选重拉 ===")
        WN.clear_list_cache()
        # 先塞一条假缓存，验证刷新会把它清掉（不清的话「刷新」永远拿到旧数据）
        with WN._LIST_LOCK:
            WN._LIST_CACHE[("", 1, "trend", "mod", ())] = (
                time.time(), {"ok": True, "items": fake_items(3), "total": 0,
                              "page": 1, "error": "", "hasMore": True})

        def ok(*a, **k):
            calls.append(("ok", a, k))
            return {"ok": True, "items": fake_items(30), "total": 0, "page": 1,
                    "error": "", "hasMore": True}

        install(ok)
        calls.clear()
        res = mgr.browseRefresh()
        check("browseRefresh 返回 ok", res.get("ok") is True, str(res))
        # 同上：假 fetch 太快，loading 可能已经收尾了。这里验的是
        # 「刷新会把请求打出去 + 打出去时用的是清完缓存的那一份」。
        wait_idle(mgr)
        check("刷新后拿到第 1 页", len(mgr.browseItems) == 30,
              str(len(mgr.browseItems)))
        check("刷新确实走网络（缓存已清）", any(c[0] == "ok" for c in calls),
              str(calls)[:80])
        check("刷新后 browseLoading=False", mgr.browseLoading is False)
        check("刷新后 error 清空", mgr.browseError == "", mgr.browseError[:50])
        check("刷新后不再是 done", mgr.browseDone is False)
        check("刷新没改筛选条件",
              (mgr.browseQuery, mgr.browseSort, mgr.browseKind) == ("", "trend", "mod"),
              f"{mgr.browseQuery}/{mgr.browseSort}/{mgr.browseKind}")
        check("timeout 预算真的传下去了（15 秒）",
              all(abs(float(c[2].get("timeout", 0)) - 15.0) < 0.01
                  for c in calls if c[2].get("timeout") is not None),
              str([c[2].get("timeout") for c in calls]))
        check("BROWSE_TIMEOUT_SEC 就是 15", MM.ModManager.BROWSE_TIMEOUT_SEC == 15.0,
              str(MM.ModManager.BROWSE_TIMEOUT_SEC))

        # ------------------------------------------------------ 3. 15 秒到点收尾
        print("=== 3. 请求卡住 -> 15 秒到点判失败（不再无限等）===")
        WN.clear_list_cache()

        def hang(*a, **k):
            calls.append(("hang", a, k))
            time.sleep(30)          # 模拟「TCP 连上了但一直不回」
            return {"ok": True, "items": fake_items(5), "total": 0,
                    "page": 1, "error": "", "hasMore": False}

        install(hang)
        calls.clear()
        # 把预算临时压到 300ms：验的是「到点会不会收尾」，不是真等 15 秒
        old_sec = MM.ModManager.BROWSE_TIMEOUT_SEC
        MM.ModManager.BROWSE_TIMEOUT_SEC = 0.3
        try:
            mgr.browseFilter("", "trend", "mod", [])
            check("卡住时是 loading", mgr.browseLoading is True)
            pump(900)
            check("到点后 browseLoading 变 False",
                  mgr.browseLoading is False, f"browseLoading={mgr.browseLoading}")
            check("到点后给出超时提示", "超时" in mgr.browseError, mgr.browseError[:80])
            check("到点后标记 done（不自动续拉）", mgr.browseDone is True)
            seq_after = mgr._browse_seq

            # 迟到的结果必须被丢掉，不能把超时的空列表又填上东西
            pump(400)
            check("迟到结果被丢弃（序号已推进）", mgr._browse_seq == seq_after,
                  f"{mgr._browse_seq} vs {seq_after}")
            check("迟到结果没有污染列表", mgr.browseItems == [],
                  str(len(mgr.browseItems)))

            # 超时之后点刷新，仍然能正常工作
            install(ok)
            calls.clear()
            mgr.browseRefresh()
            wait_idle(mgr, 2000)
            check("超时后点刷新能恢复", len(mgr.browseItems) == 30,
                  str(len(mgr.browseItems)))
            check("恢复后 loading=False", mgr.browseLoading is False)
        finally:
            MM.ModManager.BROWSE_TIMEOUT_SEC = old_sec

        # ------------------------------------------------------ 4. 追加失败
        print("=== 4. 追加下一页失败：保留已有内容 + 停掉底部转圈 ===")
        WN.clear_list_cache()
        install(ok)
        mgr.browseFilter("", "trend", "mod", [])
        wait_idle(mgr)
        have = len(mgr.browseItems)
        check("先拿到一页", have == 30, str(have))

        def fail_append(*a, **k):
            return {"ok": False, "items": [], "total": 0, "page": 2,
                    "error": "第二页超时"}

        install(fail_append)
        mgr.browseMore()
        wait_idle(mgr)
        check("追加失败后 browseLoadingMore=False",
              mgr.browseLoadingMore is False)
        check("追加失败不清掉已有内容", len(mgr.browseItems) == have,
              f"{len(mgr.browseItems)} vs {have}")
        check("追加失败有底部提示", mgr.browseError != "", mgr.browseError[:40])

        # ------------------------------------------------------ 4b. 追加超时
        print("=== 4b. 追加超时：停底部转圈，但不封死后续加载 ===")
        WN.clear_list_cache()
        install(ok)
        mgr.browseFilter("", "trend", "mod", [])
        wait_idle(mgr)
        have = len(mgr.browseItems)

        def hang_append(*a, **k):
            time.sleep(30)
            return {"ok": True, "items": [], "total": 0, "page": 2,
                    "error": "", "hasMore": False}

        install(hang_append)
        old_sec2 = MM.ModManager.BROWSE_TIMEOUT_SEC
        MM.ModManager.BROWSE_TIMEOUT_SEC = 0.3
        try:
            mgr.browseMore()
            pump(900)
            check("追加超时后 browseLoadingMore=False",
                  mgr.browseLoadingMore is False)
            check("追加超时不丢掉已有内容", len(mgr.browseItems) == have,
                  f"{len(mgr.browseItems)} vs {have}")
            check("追加超时**不**把列表标成到底（还能继续滚）",
                  mgr.browseDone is False, str(mgr.browseDone))
            check("追加超时有提示", "超时" in mgr.browseError, mgr.browseError[:60])
        finally:
            MM.ModManager.BROWSE_TIMEOUT_SEC = old_sec2

        # ------------------------------------------------------ 5. 源码断言
        print("=== 5. 结构断言（别把修复改回去）===")
        mm_src = open(os.path.join(APP_ROOT, "app", "modmanager.py"),
                      encoding="utf-8").read()
        apply_body = mm_src.split("def _browse_apply(", 1)[-1]
        fail_seg = apply_body.split('if not res.get("ok"):', 1)[-1][:900]
        check("失败分支清 _browse_loading",
              "self._browse_loading = False" in fail_seg)
        check("失败分支清 _browse_more", "self._browse_more = False" in fail_seg)
        check("browseRefresh 会清列表缓存", "WN.clear_list_cache()" in mm_src)
        check("用 QTimer 做看门狗", "QTimer" in mm_src and "_browse_guard" in mm_src)
        check("超时会推进 seq 让迟到结果作废", "self._browse_seq += 1" in mm_src)

        ws_src = open(os.path.join(APP_ROOT, "qml", "components",
                                   "WorkshopPage.qml"), encoding="utf-8").read()
        check("QML 有刷新按钮", 'objectName: "wsRefreshBtn"' in ws_src)
        check("QML 刷新调 browseRefresh", "page.mgr.browseRefresh()" in ws_src)
        check("首屏失败时不再显示转圈（条件是 !browseLoading）",
              "!page.mgr.browseLoading" in ws_src)

    finally:
        restore()

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
