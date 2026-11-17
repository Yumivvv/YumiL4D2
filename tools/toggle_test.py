# -*- coding: utf-8 -*-
"""验证：启用/禁用单个 MOD 时，列表行号不重置（不会跳回顶部）。

用沙盒 addons 目录 + 假 vpk，不碰用户真实 MOD，也不受「游戏正在运行把文件
独占」的影响（之前这个测试在批跑时偶发失败，就是因为那一刻 L4D2 开着）。

跑法：python -X utf8 tools/toggle_test.py
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication  # noqa: E402

app = QCoreApplication(sys.argv)

from app.modmanager import ModManager  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def pump(times=40, until=None, nap=0.05):
    """跑事件循环等后台线程。必须带 sleep —— 扫描在别的线程，
    纯 processEvents 会瞬间空转完，后台还没结束就退出等待了。"""
    for _ in range(times):
        app.processEvents()
        if until and until():
            return
        time.sleep(nap)


def main():
    tmp = tempfile.mkdtemp(prefix="l4d2_toggle_")
    addons = os.path.join(tmp, "left4dead2", "addons")
    os.makedirs(addons)
    # 造 15 个假 vpk（scan 只看文件名/体积，内容无所谓）
    for i in range(15):
        open(os.path.join(addons, "%09d.vpk" % (100000000 + i)), "wb").write(b"x" * 512)

    mm = ModManager()
    # ModManager 构造时会自动探测并扫描真实 addons；scan() 里有 _busy 保护，
    # 不先等它结束，切到沙盒目录后那次 scan 会被直接吞掉。
    pump(200, lambda: mm.scanned and not mm.busy)
    mm.setAddonsDir(addons)
    # setAddonsDir 内部已经 scan 过。这里必须等「沙盒那 15 个」真的出现 ——
    # 只看 rowCount()>=12 不行，真实 addons 的旧列表（几十行）也会满足它。
    pump(200, lambda: mm._local.rowCount() == 15)
    print("local =", mm.localCount, flush=True)
    if mm.localCount < 12:
        print("沙盒 MOD 太少，跳过")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    model = mm._local
    n = model.rowCount()
    before = [dict(model._items[i]) for i in range(n)]
    row = 9
    target = before[row]
    path = target["path"]
    print(f"准备切换第 {row} 行: {target['name']}  enabled={target['enabled']}", flush=True)

    mm.toggleEnabled(path)
    pump(60)

    after = [dict(model._items[i]) for i in range(model.rowCount())]
    check("行数不变", len(after) == n, f"{n} -> {len(after)}")
    mismatch = [i for i in range(n) if i != row and after[i]["name"] != before[i]["name"]]
    check("其余行顺序不变（不会跳回顶部）", not mismatch, str(mismatch))
    check("那一行 enabled 翻转", after[row]["enabled"] != before[row]["enabled"],
          f"{before[row]['enabled']} -> {after[row]['enabled']}")
    check("文件名带上 .disabled", after[row]["name"].endswith(".vpk.disabled"),
          after[row]["name"])

    # 切回来
    mm.toggleEnabled(after[row]["path"])
    pump(60)
    back = [dict(model._items[i]) for i in range(model.rowCount())]
    check("恢复后 enabled 还原", back[row]["enabled"] == before[row]["enabled"])
    check("恢复后文件名还原", back[row]["name"] == before[row]["name"], back[row]["name"])
    check("整体顺序还原", [b["name"] for b in back] == [b["name"] for b in before])

    mm.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("TOGGLE_INPLACE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
