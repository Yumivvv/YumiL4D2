# -*- coding: utf-8 -*-
"""MOD 操作的后端行为验证（沙盒，不碰真实 addons）。

覆盖：
  * import_files：只选 vpk 也自动带上同名封面
  * copy_workshop_to_local：转换是「复制」，工坊那份必须留着（移动会让 Steam 重下）
  * set_enabled：禁用/启用改扩展名；失败返回空串（供上层提示"被占用"）
  * delete_files：连同名封面一起删

跑法：python -X utf8 tools/mods_ops_test.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import mods as _mods  # noqa: E402
from app.mods import (  # noqa: E402
    companion_files,
    copy_workshop_to_local,
    delete_files,
    import_files,
    set_enabled,
)

# 导入会写「导入日期」台账（data/modimports.json），测试必须写到临时文件里，
# 否则会把真实键覆盖掉、还留下一堆假 ID。
_ledger_dir = tempfile.mkdtemp(prefix="l4d2_ledger_")
_mods.IMPORT_LEDGER_PATH = os.path.join(_ledger_dir, "modimports.json")

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def main():
    tmp = tempfile.mkdtemp(prefix="l4d2_modtest_")
    src = os.path.join(tmp, "src")
    os.makedirs(src)
    # 沙盒要造出 left4dead2/addons 结构，normalize_addons_dir 才认
    addons = os.path.join(tmp, "left4dead2", "addons")
    ws = os.path.join(addons, "workshop")
    os.makedirs(ws)

    vpk = os.path.join(src, "469986973.vpk")
    open(vpk, "wb").write(b"x" * 2048)
    open(os.path.join(src, "469986973.jpg"), "wb").write(b"img" * 100)
    open(os.path.join(src, "notes.txt"), "w").write("hi")

    print("=== 1. 导入（只选 vpk，应自动带上同名 jpg）===")
    r = import_files([vpk], addons)
    print("  copied:", r["copied"])
    check("vpk 被复制", "469986973.vpk" in r["copied"])
    check("同名图片自动带上", "469986973.jpg" in r["copied"])

    print()
    print("=== 2. 转换到本地（复制，工坊那份要留着）===")
    open(os.path.join(ws, "132381280.vpk"), "wb").write(b"y" * 1024)
    open(os.path.join(ws, "132381280.png"), "wb").write(b"img")
    r2 = copy_workshop_to_local(addons, None)
    print("  moved:", r2["moved"])
    check("本地出现副本", os.path.exists(os.path.join(addons, "132381280.vpk")))
    check("封面一起复制", os.path.exists(os.path.join(addons, "132381280.png")))
    check("工坊原件保留（不能是移动）",
          os.path.exists(os.path.join(ws, "132381280.vpk")),
          "移动会让 Steam 重新下载")

    print()
    print("=== 3. 启用/禁用 ===")
    p = os.path.join(addons, "132381280.vpk")
    p1 = set_enabled({"path": p}, False)
    print("  禁用后:", os.path.basename(p1))
    check("禁用改扩展名", p1.endswith(".vpk.disabled"))
    check("禁用后原文件不在了", not os.path.exists(p))
    p2 = set_enabled({"path": p1}, True)
    print("  启用后:", os.path.basename(p2))
    check("启用改回 .vpk", p2.endswith(".vpk"))
    # 失败判定要用「真的不存在」的路径（p 此刻已经是 .vpk.disabled 了）
    check("失败返回空串（文件不存在）",
          set_enabled({"path": os.path.join(addons, "nope.vpk")}, False) == "")

    print()
    print("=== 4. 同名封面识别 + 删除（连同名封面一起）===")
    comp = companion_files(p2)
    print("  companion_files:", [os.path.basename(c) for c in comp])
    check("识别出 vpk 本身", p2 in comp)
    check("识别出同名封面", os.path.join(addons, "132381280.png") in comp)
    # delete_files 只删传进去的路径，「带上同名封面」是上层用 companion_files 展开的
    r3 = delete_files(comp, False)
    print("  removed:", r3["removed"])
    check("vpk 被删", not os.path.exists(p2))
    check("同名封面一起删", not os.path.exists(os.path.join(addons, "132381280.png")))

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(_ledger_dir, ignore_errors=True)
    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
