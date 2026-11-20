# -*- coding: utf-8 -*-
"""本轮三项修复的回归测试（不联网为主）。

1. 「只看新的」开关与页面/侧栏高亮不同步（启动时 + 后端自动关闭时）
2. 网盘链接没有协议头（pan.quark.cn/s/xxx）也要能提取，并自动补 https://
3. 创意工坊详情加载慢：改用 /detail 快通道（实测 2.15s → 0.66s）
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


QML_MAIN = open(os.path.join("qml", "Main.qml"), encoding="utf-8").read()
PY_DL = open(os.path.join("app", "workshop_dl.py"), encoding="utf-8").read()
from app.panlink import extract_links  # noqa: E402


# ============================================ 1. 只看新的状态同步
print("\n[1] 「只看新的」和页面/侧栏高亮保持一致")
check("启动时按 core.showOnlyNew 同步 page",
      "win.page = core.showOnlyNew ? 1 : 0" in QML_MAIN)
check("onStatusChanged 里也跟着拉回 page",
      "var want = core.showOnlyNew ? 1 : 0" in QML_MAIN)
check("只有停在视频页才动 page（不干扰别的页）",
      "win.section === 0" in
      QML_MAIN[QML_MAIN.index("function onStatusChanged"):
               QML_MAIN.index("function onStatusChanged") + 900])


# ============================================ 2. 裸域名网盘链接
print("\n[2] 没有 http:// 的网盘链接也要能提取")
cases = [
    # (输入, 期望 url, 期望网盘名)
    ("pan.quark.cn/s/2ce22bd402e3?pwd=U7sV",
     "https://pan.quark.cn/s/2ce22bd402e3?pwd=U7sV", "夸克网盘"),
    ("链接: pan.quark.cn/s/2ce22bd402e3?pwd=U7sV 提取码 U7sV",
     "https://pan.quark.cn/s/2ce22bd402e3?pwd=U7sV", "夸克网盘"),
    ("pan.baidu.com/s/1abcDEF 提取码 abcd",
     "https://pan.baidu.com/s/1abcDEF", "百度网盘"),
    ("www.123pan.com/s/abcd-efg",
     "https://www.123pan.com/s/abcd-efg", "123 云盘"),
]
for text, want_url, want_name in cases:
    got = extract_links(text)
    urls = [x["url"] for x in got]
    names = [x["name"] for x in got]
    check(f"「{text[:38]}」能提取到", want_url in urls, urls[:2])
    if want_url in urls:
        idx = urls.index(want_url)
        check(f"「{text[:28]}」认出是{want_name}", names[idx] == want_name, names[idx])

# 已经有协议头的不能被破坏
got = extract_links("https://pan.quark.cn/s/2ce22bd402e3?pwd=U7sV")
check("带协议头的链接行为不变",
      got and got[0]["url"] == "https://pan.quark.cn/s/2ce22bd402e3?pwd=U7sV"
      and got[0]["code"] == "U7sV", got[:1])

# 非网盘域名不能被误认
check("普通域名不当网盘链接",
      extract_links("看看 www.example.com/abc 这个") == [])
check("省略协议的非网盘地址也不认",
      extract_links("example.com/s/123") == [])
# 防和谐插字 + 无协议头
got = extract_links("pan.qu[删]ark.cn/s/2ce22bd402e3?pwd=U7sV")
check("插了干扰字且无协议头也能提取",
      any(x["url"].startswith("https://pan.quark.cn/s/2ce22bd402e3")
          for x in got), [x["url"] for x in got][:2])

# 源码约定
check("有 _bare_pan_url 处理裸域名", "def _bare_pan_url" in
      open(os.path.join("app", "panlink.py"), encoding="utf-8").read())


# ============================================ 3. 工坊详情走 Steam 官方接口
print("\n[3] 创意工坊详情走 Steam 官方（不再经过任何第三方中转）")
check("只走 Steam 官方 GetPublishedFileDetails",
      "GetPublishedFileDetails" in PY_DL)
check("没有任何第三方中转地址残留（代码里）",
      not any(("laoyutang" in ln) and not ln.strip().startswith("#")
              for ln in PY_DL.splitlines()),
      [ln.strip()[:60] for ln in PY_DL.splitlines()
       if "laoyutang" in ln and not ln.strip().startswith("#")][:2])
check("详情请求走 netclient 的统一证书",
      "NC.post(" in PY_DL)
check("有 _details_one 单条快通道", "def _details_one" in PY_DL)
check("有 _details_parse_rows 复用字段映射",
      "def _details_parse_rows" in PY_DL)
check("fetch_details 里少量 ID 走单条", "_details_one(w, timeout)" in PY_DL)
check("字段映射里保留了 previews 多图", '"previews"' in PY_DL)
check("简介字段兼容 description（不同来源叫法不同）",
      'f.get("file_description") or f.get("description")' in PY_DL)

print()
if fails:
    print(f"失败 {len(fails)} 项：")
    for name in fails:
        print("  - " + name)
    sys.exit(1)
print("本轮三项修复的测试全部通过")
