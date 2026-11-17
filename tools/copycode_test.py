# -*- coding: utf-8 -*-
"""验证：网盘提取码复制（右键复制）+ 网盘链接解析仍正常。"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1])

from app.core import Core          # noqa: E402
from app.panlink import extract_links  # noqa: E402

core = Core(app)

# ---- 1) copyCode 正常
core.copyCode("4qaz", "夸克网盘")
got = QGuiApplication.clipboard().text()
print("剪贴板 =", repr(got), flush=True)
assert got == "4qaz", f"复制失败：{got!r}"
print("状态栏 =", core.statusText, flush=True)
assert "4qaz" in core.statusText

# ---- 2) 前后空格要剥掉
core.copyCode("  FXWS  ", "蓝奏云")
got = QGuiApplication.clipboard().text()
print("剪贴板 =", repr(got), flush=True)
assert got == "FXWS", f"没去掉空格：{got!r}"

# ---- 3) 空码不该覆盖剪贴板
core.copyCode("", "百度网盘")
print("空码后剪贴板 =", repr(QGuiApplication.clipboard().text()), flush=True)
print("状态栏 =", core.statusText, flush=True)
assert QGuiApplication.clipboard().text() == "FXWS", "空码把剪贴板清掉了"
assert "没有提取码" in core.statusText

# ---- 4) 真实简介里能提取到码，且右键就是复制这个值
desc = (
    "AK47和三连发：https://pan.删除baidu.com/s/1mLRDkcit中文c2Sz05w6EwbKaA?pwd=6sg4\n"
    "另一个：https://wwbth.lanzoue.com/b013a648ed 提取码: FXWS\n"
    "夸克：https://pan.quark.cn/s/abcdef123456 密码: 4qaz\n"
)
links = extract_links(desc, fallback_label="测试视频")
print(f"提取到 {len(links)} 个网盘链接", flush=True)
for it in links:
    print(f"  {it['name']} | code={it['code']!r} | label={it['label']!r}", flush=True)
assert len(links) >= 3, "网盘链接提取数量不对"

codes = {it["code"] for it in links}
assert "6sg4" in codes, f"百度码不对（应保留原样小写）：{codes}"
assert "FXWS" in codes, f"蓝奏云码不对：{codes}"
assert "4qaz" in codes, f"夸克码不对（应保留原样小写）：{codes}"
assert "6SG4" not in codes and "4QAZ" not in codes, "提取码被错误地转成了大写"

# 对每个链接执行一次「右键复制」，检查拷到的就是它的码
for it in links:
    core.copyCode(it["code"], it["name"])
    assert QGuiApplication.clipboard().text() == it["code"], \
        f"{it['name']} 复制结果不对"
    print(f"  右键复制 {it['name']} -> {it['code']}  OK", flush=True)

core.shutdown()
print("COPYCODE_OK", flush=True)
