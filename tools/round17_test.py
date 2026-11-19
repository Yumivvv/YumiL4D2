"""本轮三项修复的自检。

1. **设置里残留的关闭按钮** —— 设置改成普通一页之后不该再有「×」。
   以前那是抽屉时代的遗物；留着既多余又和窗口关闭按钮撞脸。
2. **工坊 MOD 多图只有封面能显示** —— `_desc_images()` 原来只认
   `[img]…[/img]`，作者用 HTML `<img src>` / markdown / 裸链接贴的图全漏了。
3. **工坊 DNS 没有主题色** —— 那块用的是固定 `Theme.cyan`，换主题色后还是青的。
   现在全部改成 `Theme.accent`。
"""
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import os
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import re
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard import protect_user_data                    # noqa: E402

protect_user_data()

from app.workshop_dl import _desc_images               # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def src(rel):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return open(os.path.join(root, rel), encoding="utf-8").read()


def main() -> int:
    main_qml = src(os.path.join("qml", "Main.qml"))

    print("\n-- 1. 设置里不再有「×」关闭按钮", flush=True)
    # 定位 settingsCol 这一整段
    start = main_qml.find("id: settingsCol")
    check("找到 settingsCol", start > 0)
    seg = main_qml[start:start + 2000]
    # 只看代码行，注释里解释「为什么删掉」是对的
    seg_code = "\n".join(ln for ln in seg.splitlines()
                         if ln.strip() and not ln.strip().startswith("//"))
    check("设置页头部没有 IconButton 关闭按钮",
          'glyph: "\\uE711"' not in seg_code, )
    check("也没有 win.section = 0 的关闭动作",
          "win.section = 0" not in seg_code)
    check("标题还在", "设置" in seg_code)
    check("注释说明了为什么删", "抽屉" in seg)

    print("\n-- 2. 工坊多图：各种贴图写法都要认", flush=True)
    cases = [
        ("BBCode 标准",
         "看[img]https://i.imgur.com/a.jpg[/img]还有[img]https://i.imgur.com/b.png[/img]",
         2),
        ("HTML 双引号", '<img src="https://i.imgur.com/c.jpg">', 1),
        ("HTML 单引号", "<img src='https://i.imgur.com/d.jpg'>", 1),
        ("BBCode 带宽度", "[img width=800]https://i.imgur.com/e.jpg[/img]", 1),
        ("Markdown", "![](https://i.imgur.com/f.jpg)", 1),
        ("裸链接", "https://i.imgur.com/g.jpg", 1),
        ("Steam 图床",
         "[img]https://steamuserimages-a.akamaihd.net/ugc/1/2.jpg[/img]", 1),
    ]
    for name, text, want in cases:
        got = _desc_images(text)
        check(f"认得出{name}", len(got) == want, f"{len(got)} 张 {got}")

    # 混合写法：三种一起出现要全都抓到，且不重复
    mixed = ("[img]https://i.imgur.com/1.jpg[/img]\n"
             '<img src="https://i.imgur.com/2.jpg">\n'
             "![](https://i.imgur.com/3.jpg)\n"
             "[img]https://i.imgur.com/1.jpg[/img]")     # 最后一张是重复
    got = _desc_images(mixed)
    check("混合写法三张都抓到", len(got) == 3, got)
    check("重复地址只留一次", len(got) == len(set(got)), got)
    check("全是 http(s) 开头",
          all(u.startswith(("http://", "https://")) for u in got), got)

    # 空 / 垃圾输入不炸
    check("空简介返回空表", _desc_images("") == [])
    check("None 返回空表", _desc_images(None) == [])
    check("纯文字返回空表", _desc_images("这是一个没有图片的简介") == [])

    # 后端确实把 descImages 拼进 images
    dl_py = src(os.path.join("app", "workshop_dl.py"))
    check("封面 + 简介图会合成 images 列表",
          'for u in [api.get("preview")' in dl_py and '"images": pics' in dl_py)
    # QML 侧要能渲染全部
    ws_qml = src(os.path.join("qml", "components", "WorkshopPage.qml"))
    check("缩略图条按全部图渲染", "model: page.detailImages()" in ws_qml)
    check("多于一张才显示缩略图条",
          "page.detailImages().length > 1" in ws_qml)

    print("\n-- 3. 工坊 DNS 跟着主题色", flush=True)
    dns_start = main_qml.find('objectName: "workshopDnsSection"')
    check("找到工坊 DNS 段", dns_start > 0)
    # 取这一段到下一个分区标题
    tail = main_qml.find("④ 数据与缓存", dns_start)
    if tail < 0:
        tail = dns_start + 6000
    dns_seg = main_qml[dns_start:tail]
    check("DNS 段里没有固定青色 Theme.cyan", "Theme.cyan" not in dns_seg,
          dns_seg.count("Theme.cyan"))
    check("DNS 段用的是主题色 Theme.accent", "Theme.accent" in dns_seg,
          dns_seg.count("Theme.accent"))
    # 主题色变了它就该跟着变 —— 靠「引用 Theme.accent」这一点保证
    check("工坊 DNS 不是唯一一个用主题色的（网络加速也是）",
          "Theme.accent" in main_qml[main_qml.find('objectName: "netAccelSection"'):
                                     dns_start])

    print("\n-- 4. 排版：分区标题 + 宽度", flush=True)
    for title in ("① 监控与提醒", "② 外观与主题", "③ 目录与网络", "④ 数据与缓存"):
        check(f"有分区标题 {title}", title in main_qml)
    check("内容宽度放到 980（原来 760 留白太多）",
          "Math.min(980, settingsFlick.width)" in main_qml)
    check("宽度改造带了说明", "右边空一大片" in main_qml)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "、".join(FAILS)), flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
