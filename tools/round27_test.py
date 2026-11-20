# -*- coding: utf-8 -*-
"""创意工坊详情「一直转圈」的回归测试。

根因（上一轮自己引入的回归）：

  QML 打开详情时用 `page.probeSeq + 1` **自己维护序号**，后端 `_probe_seq`
  是另一套计数器。两边永远对不上 → `onProbe` 每次都把结果当「旧请求」丢弃 →
  `loadingDetail` 永远变不回 false → 界面一直转圈。

  另外 `page.probeSeq` 从没被声明成属性，QML 给未声明属性赋值会**静默丢弃**
  并刷 `Cannot assign to non-existent property`。

修法：
  · `probeWorkshopFast()` 返回本次请求的 seq（**唯一权威**）；
  · QML 记下这个返回值，`onProbe` 拿 `res.seq` 与它比对；
  · `probeSeq` 显式声明成 int，用 -1 当「无请求」哨兵；
  · 排队中的那次请求入队时就带 seq，跑完复用它，不再重新 +1。
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


QML_WS = open(os.path.join("qml", "components", "WorkshopPage.qml"),
              encoding="utf-8").read()
PY_MM = open(os.path.join("app", "modmanager.py"), encoding="utf-8").read()


# ============================================ 1. 序号来源必须唯一
print("\n[1] 序号必须只有一个来源（后端）")
check("probeWorkshopFast 声明返回 int",
      '@Slot(str, result=int)' in PY_MM
      and "def probeWorkshopFast(self, text: str) -> int" in PY_MM)
check("_probe_start 也返回 int",
      "def _probe_start(self, text: str, want_deps: bool) -> int" in PY_MM)
check("入口就 +1 并返回（排队分支也有序号）",
      'self._probe_seq = int(getattr(self, "_probe_seq", 0)) + 1' in PY_MM
      and "return seq" in PY_MM)
check("没有 MOD 目录的分支也带 seq", '"seq": self._probe_seq' in PY_MM)
check("排队元组带 seq（3 个元素）",
      'self._probe_queued = (str(text or ""), bool(want_deps), seq)' in PY_MM)
check("排队重跑时复用入队时的 seq（不再 +1）",
      "queued_seq = (nxt + (None,))[:3]" in PY_MM)
check("_probe_worker 把 seq 写进结果", 'res["seq"]' in PY_MM)

check("QML 从后端拿序号",
      "page.probeSeq = page.mgr ? page.mgr.probeWorkshopFast(item.id) : -1"
      in QML_WS)
check("QML 不再自己 +1 维护序号", "Number(page.probeSeq) + 1" not in QML_WS)
check("probeSeq 已显式声明成 int", "property int probeSeq: -1" in QML_WS)
check("closeDetail 把序号置回 -1", "page.probeSeq = -1;" in QML_WS)
check("onProbe 用 >= 0 判断「有有效请求」", "page.probeSeq >= 0" in QML_WS)


# ============================================ 2/3. 真实链路
print("\n[2] 真实链路：请求序号 == 结果序号")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from app.core import Core  # noqa: E402

app = QGuiApplication(sys.argv[:1])
core = Core(app)
core._scan_worker = lambda: (core._set_busy(False), core.statusChanged.emit())
core.config["auto_check_update"] = False
core.mods.setAddonsDir(os.environ.get("TEMP", "."))

events = []
core.mods.workshopProbed.connect(lambda r: events.append(dict(r)))
state = {}


def _go():
    state["seq"] = core.mods.probeWorkshopFast("3115675033")
    QTimer.singleShot(15000, _check)


def _check():
    if not events:
        check("15 秒内收到解析结果", False, "一条都没收到 → 界面会一直转圈")
    else:
        r = events[-1]
        check("15 秒内收到解析结果", True)
        check("结果里的 seq 与请求返回的一致",
              r.get("seq") == state.get("seq"),
              f"res={r.get('seq')} req={state.get('seq')}")
        check("结果 on 且带 items",
              bool(r.get("ok")) and bool(r.get("items")),
              f"ok={r.get('ok')} items={len(r.get('items') or [])}")

    # ---- 第 3 节：连点两次的序号分配（同步即可验证）
    print()
    print("[3] 连点两次：序号递增，排队项带自己的 seq")
    a = core.mods.probeWorkshopFast("3115675033")
    b = core.mods.probeWorkshopFast("3829533320")
    print("  两次请求序号:", a, b, flush=True)
    check("两次请求序号不同", a != b, f"{a} / {b}")
    check("序号是递增的", b > a, f"{a} -> {b}")
    queued = getattr(core.mods, "_probe_queued", None)
    if queued is not None:
        check("排队项带着自己的 seq（3 元组）",
              isinstance(queued, tuple) and len(queued) == 3
              and queued[2] == b, str(queued)[:90])
    else:
        # 第一次已经跑完、第二次直接开跑（没排队）也是正常路径
        check("第二次要么排队、要么直接开跑", True)

    core.shutdown()
    app.quit()


QTimer.singleShot(1200, _go)
QTimer.singleShot(40000, app.quit)
app.exec()

print()
if fails:
    print(f"失败 {len(fails)} 项：")
    for name in fails:
        print("  - " + name)
    sys.exit(1)
print("创意工坊详情加载的测试全部通过")
