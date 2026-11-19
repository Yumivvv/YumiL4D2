"""网盘链接提取：常规写法 + 各种防和谐插字。

重点盯「干扰词插进 URL 内部」这一类 —— 用户报的那个视频
把 `https` 拆成了 `htt【删】ps`，原来的实现是先正则找协议头再清洗，
协议头已经被拆开，整条链接直接漏掉。
"""
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys

sys.path.insert(0, ".")
from app.panlink import extract_links

cases = [
    ("百度带中文", "链接: https://pan.删除baidu.com/s/1mLRDkcit中文c2Sz05w6EwbKaA?pwd=6sg4"),
    ("夸克", "我用夸克网盘分享了「MOD」：https://pan.quark.cn/s/1a2b3c4d5e6f 提取码：k9x2"),
    ("蓝奏", "蓝奏云 https://wwi.lanzoup.com/iXyZ1234 密码:8f3a"),
    ("阿里", "https://www.alipan.com/s/AbCdEfGhIjK"),
    ("123", "123云盘 https://www.123pan.com/s/abc-def.html 提取码 1234"),
    ("多链接", "夸克 https://pan.quark.cn/s/aaa111 百度 https://pan.baidu.com/s/1bbb222?pwd=xy99"),
    ("非网盘", "https://www.bilibili.com/video/BV1xx411c7mD 和 "
              "https://steamcommunity.com/sharedfiles/filedetails/?id=123"),
    ("空", ""),
]

# 用户报的那个视频：干扰词被插进 URL 内部，连协议名都被拆开
OBFUSCATED = (
    "htt【删】ps://pan.ba【除】idu.com/s/18【文】VHP-PnAp7t3【字】dksJSOoU【谢】ww?pwd=【谢】tvrk"
    "       提取码: tvrk  长期有效"
)
WANT = "https://pan.baidu.com/s/18VHP-PnAp7t3dksJSOoUww?pwd=tvrk"

cases += [
    ("插字拆开协议名", OBFUSCATED),
    ("只拆域名", "https://pan.ba【除】idu.com/s/1AbCdEfG?pwd=a1b2"),
    ("方括号", "https://pan.baidu.com/s/1AbCdEfG[删]?pwd=z9y8"),
    ("全角括号", "https://pan.baidu.com/s/1AbCdEfG（删除）?pwd=q1w2"),
    ("零宽字符", "https://pan.quark.cn/s/1a2b3c\u200b4d5e6f 提取码 k9x2"),
]

ok = 0
for name, text in cases:
    res = extract_links(text)
    print(f"[{name}] {len(res)} 条")
    for r in res:
        print("   ", r["name"], "|", r["url"], "| code:", r["code"] or "-")
    ok += 1

bad = []
print()
hit = [r for r in extract_links(OBFUSCATED) if r["url"] == WANT]
if hit:
    print("ok   插字链接还原正确:", hit[0]["url"], "| code =", hit[0]["code"])
    if hit[0]["code"] != "tvrk":
        bad.append("插字链接的提取码（拿到 %r）" % hit[0]["code"])
else:
    print("FAIL 插字链接没还原成预期 URL")
    bad.append("插字链接")

if all("bilibili.com" not in r["url"] for r in extract_links(cases[6][1])):
    print("ok   非网盘链接没有误判")
else:
    bad.append("B 站链接被当成网盘")

print(f"\n用例 {ok} 个跑完")
if bad:
    raise SystemExit("失败：" + "，".join(bad))
print("全部通过")
