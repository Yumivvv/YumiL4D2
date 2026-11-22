# -*- coding: utf-8 -*-
"""1.0.2 这批改动的回归：默认服务器名 / 工坊缓存 hasMore / 关于界面 / Ctrl+C。"""

import os
import re
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from guard import protect_user_data  # noqa: E402

protect_user_data()

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def main():
    from app import servers as S
    from app import workshop_net as WN
    from app import APP_VERSION

    # ---------------------------------------------------------- 1. 版本
    print("=== 1. 版本号 ===")
    check("版本是 1.0.2", APP_VERSION == "1.0.2", APP_VERSION)

    # ---------------------------------------------------------- 2. 默认名
    print("=== 2. 只填 IP 添加：默认名取服务器自报名 ===")
    src = open(os.path.join(ROOT, "app", "servers.py"), encoding="utf-8").read()
    i = src.find("def addServer(")
    body = src[i:i + 1800]
    check("addServer 会去查服务器名", "_query_one_sync" in body)
    check("addServer 把名字写进记录", "default_name" in body)
    check("addMany 也会补名字", src.count("_query_one_sync") >= 3,
          f"出现 {src.count('_query_one_sync')} 次")

    # BOM 清理
    check("clean_name 去 BOM", "\\ufeff" in src or "\ufeff" in src)
    raw = "\ufeff〖黑喵0〗多人多特"
    cleaned = S.clean_name(raw)
    check("clean_name 真的去掉了 BOM", cleaned == "〖黑喵0〗多人多特", repr(cleaned))
    # 零宽字符
    check("clean_name 去零宽空格",
          S.clean_name("a\u200bb") == "ab", repr(S.clean_name("a\u200bb")))

    # ---------------------------------------------------------- 3. 工坊缓存
    print("=== 3. 工坊列表缓存保留 hasMore ===")
    import time as _t
    items = [{"id": str(3800000000 + i), "title": f"m{i}", "preview": "",
              "author": "", "fileType": 0, "views": 0, "subs": 0, "favorited": 0,
              "children": 0, "created": 0, "updated": 0, "tags": []}
             for i in range(30)]
    key = ("", 1, "trend", "mod", ())
    with WN._LIST_LOCK:
        WN._LIST_CACHE[key] = (_t.time(), {
            "ok": True, "items": items, "total": 0, "page": 1,
            "error": "", "hasMore": True,
        })
    r = WN.fetch_workshop_list("", 1, "trend", None, "mod")
    check("缓存命中仍带 hasMore=True", r.get("cached") is True and r.get("hasMore") is True,
          f"cached={r.get('cached')} hasMore={r.get('hasMore')}")
    WN.clear_list_cache()

    wsrc = open(os.path.join(ROOT, "app", "workshop_net.py"), encoding="utf-8").read()
    check("缓存写入时存了 hasMore", '"hasMore": bool(res.get("hasMore", False))' in wsrc)
    check("缓存读取时返回 hasMore", '"hasMore": bool(res.get("hasMore", False))' in wsrc)
    check("连不上时重试 2 次", "for attempt in range(2)" in wsrc)
    # 提示要「可操作」。2026-11 起不再是「配一个 API Key」（那栏已彻底删除），
    # 而是让用户点顶栏的刷新重试 —— 所以这里认「刷新」这个词。
    check("网络失败提示可操作",
          "刷新" in wsrc or "挂个加速器" in wsrc or "API Key" in wsrc)

    # ---------------------------------------------------------- 4. 关于界面
    print("=== 4. 关于界面重排 ===")
    qml = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    check("三个按钮收进同一个 Row", 'objectName: "copyHomepageBtn"' in qml
          and 'objectName: "openDataDirBtn"' in qml
          and 'objectName: "checkUpdateBtn"' in qml)
    # 找到那三个按钮的 Row，确认它们在同一行（同一个 Row 块内）
    i1 = qml.find('objectName: "copyHomepageBtn"')
    i3 = qml.find('objectName: "checkUpdateBtn"')
    between = qml[i1:i3]
    check("复制链接与检查更新之间没有新的 Row 起点",
          between.count("Row {") == 0, f"{between.count('Row {')} 个")
    check("按钮高度收到 28", "height: 28" in between, "")

    # 致谢只剩一句：不再引用 creditScope
    check("关于里不再显示参考范围", "core.creditScope" not in qml)
    check("致谢仍显示项目名", "core.creditName" in qml)
    check("致谢仍显示作者", "core.creditAuthor" in qml)
    check("致谢仍可点开项目页", "core.openCreditPage()" in qml)

    # ---------------------------------------------------------- 5. Ctrl+C
    print("=== 5. Ctrl+C 复制选中服务器 ===")
    sp = open(os.path.join(ROOT, "qml", "components", "ServersPage.qml"),
              encoding="utf-8").read()
    check("ServersPage 有 copySelected", "function copySelected(" in sp)
    check("copySelected 走 shareServer", "page.mgr.shareServer(row.addr)" in sp)
    check("copySelected 无选中时给提示", "先选中一台服务器" in sp)

    check("Main.qml 有 Ctrl+C 快捷键", '"Ctrl+C"' in qml)
    ic = qml.find('"Ctrl+C"')
    seg = qml[max(0, ic - 700):ic + 900]
    check("Ctrl+C 只在服务器页生效", 'win.section === 3' in seg)
    check("Ctrl+C 会避让输入框", "activeFocusItem" in seg)
    check("Ctrl+C 调到 copySelected", "copySelected()" in seg)

    # ---------------------------------------------------------- 6. MOD 简介重叠
    print("=== 6. MOD 详情简介不再被滚动条压住 ===")
    mp = open(os.path.join(ROOT, "qml", "components", "ModPanel.qml"),
              encoding="utf-8").read()
    j = mp.find("id: descFlick")
    seg2 = mp[j:j + 2600] if j > 0 else ""
    check("descFlick 定义了 barW", "barW" in seg2)
    check("TextEdit 宽度扣掉滚动条", "needBar ? descFlick.barW" in seg2)
    check("滚动条贴右边缘", "anchors.right: parent.right" in seg2)
    check("滚动条不盖住文字（文字已让位）", "barW + descFlick.barGap" in seg2)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())