# -*- coding: utf-8 -*-
"""从打包好的 exe 里挖出 `app.steamfriends` 的字节码，确认修复真的进去了。

## 为什么要这么验

「源码测试通过」不等于「打包产物含修复」。PyInstaller 有过因为 spec / hiddenimports
漏文件的历史，而 `steam_api64.dll` 的验签逻辑恰恰只有在 exe 里才影响用户 ——
如果它没被打进去，别人装上新版照样会被弹框杀掉。

所以这里不信任 build 日志，直接读 exe 的 CArchive → PYZ → 目标模块的 code
object，在里面找**只属于修复后代码**的符号。

## 用法

    python -X utf8 tools/exe_contains_fix_test.py                # 自动找 dist/*.exe
    python -X utf8 tools/exe_contains_fix_test.py 某个.exe        # 指定文件

没有 exe 时**跳过**（返回 0），这样源码环境跑全量回归不会红。
"""
import glob
import marshal
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 只属于「socialclub 闪退」修复后的符号（修复前一个都不存在）
MUST_HAVE = (
    "WinVerifyTrust",     # 验签 API
    "_dll_is_genuine",    # 验签入口
    "STEAM_DLL_SIGNER",   # CompanyName 判据（模块级常量 → 只在 co_names 里）
    "_dll_company",       # 读版本信息（不加载 DLL）
    "try_accept",         # 新挑选逻辑的内层函数
)
TARGET_MODULE = "app.steamfriends"
CODE = type((lambda: 0).__code__)


def names_of(code):
    """递归收集 code object 的 co_names 与字符串常量。

    ★ 必须同时收 `co_names`：像 `STEAM_DLL_SIGNER` 这种**模块级常量**，
      它的值（"valve"）在 co_consts 里，但名字只在引用处作为 co_names 出现。
      只收 co_consts 会把「已打包」误判成「没打包」（实测踩过）。
    """
    out = [code.co_name]
    out.extend(str(n) for n in code.co_names)
    out.extend(str(c) for c in code.co_consts if isinstance(c, (str, int)))
    for c in code.co_consts:
        if isinstance(c, CODE):
            out.extend(names_of(c))
    return out


def find_exe(argv):
    if len(argv) > 1 and argv[1]:
        return argv[1]
    hits = glob.glob(os.path.join(ROOT, "dist", "*.exe"))
    return hits[0] if hits else ""


def main(argv) -> int:
    exe = find_exe(argv)
    if not exe or not os.path.isfile(exe):
        print("  跳过：没有打包好的 exe（源码环境）")
        return 0

    try:
        from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
    except ImportError:
        print("  跳过：没有 PyInstaller（装完才能验打包产物）")
        return 0

    print(f"  exe = {os.path.basename(exe)}  ({os.path.getsize(exe):,} 字节)")

    car = CArchiveReader(exe)
    pyz_name = next((n for n in car.toc if "PYZ" in n.upper()), "")
    if not pyz_name:
        print("  FAIL CArchive 里没有 PYZ")
        return 1

    with tempfile.NamedTemporaryFile(suffix=".pyz", delete=False) as f:
        f.write(car.extract(pyz_name))
        tmp = f.name
    try:
        pyz = ZlibArchiveReader(tmp)
        target = next((m for m in pyz.toc if m == TARGET_MODULE
                       or m.endswith("." + TARGET_MODULE)), "")
        if not target:
            print(f"  FAIL PYZ 里没有 {TARGET_MODULE}")
            return 1

        code = pyz.extract(target)
        if isinstance(code, bytes):
            code = marshal.loads(code)
        found = set(names_of(code))

        print(f"  模块 {target}，共 {len(found)} 个符号")
        ok = True
        for s in MUST_HAVE:
            hit = s in found
            print(f"  {'ok  ' if hit else 'FAIL'} {s}")
            ok &= hit
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    print("  结论:", "打包产物包含修复" if ok else "打包产物**缺少**修复")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
