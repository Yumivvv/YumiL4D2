"""测试网盘链接的"文件说明"推断."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.panlink import extract_links

cases = [
    (
        "用户给的例子",
        "AK47和三连发：\nhttps://pan.qu【删】ark.cn/s/e0066df91f26?pwd=5jiy\n提取码：5jiy",
    ),
    (
        "百度+文件名",
        "通过网盘分享的文件：九条都Bayonet for CSS Knife公开.vpk 链接: "
        "https://pan.baidu.com/s/1Af4WKVkSeFeQLu2DvOBv9w?pwd=d4qj 提取码: d4qj",
    ),
    (
        "多链接带标签",
        "百度网盘链接: https://pan.baidu.com/s/1xnAa3gTVlH-aCeuqthkzEw 提取码: li78\n"
        "夸克网盘链接：https://pan.quark.cn/s/b40b52daffe5?pwd=sqLq 提取码：sqLq",
    ),
    (
        "蓝奏云",
        "蓝奏云\nhttps://wwawf.lanzouu.com/ijldw4f627uf\n密码:9ks0",
    ),
    (
        "无标签只有链接",
        "https://pan.baidu.com/s/1eZiOgToR76vZuy6N_8oz4w\n提取码:29g4",
    ),
]

for name, text in cases:
    print(f"=== {name} ===")
    for it in extract_links(text):
        print(f"  {it['name']:6s} | 说明: {it['label'] or '（无）'!r}")
        print(f"         链接: {it['url'][:66]}  码: {it['code'] or '-'}")
    print()
