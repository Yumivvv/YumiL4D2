# -*- coding: utf-8 -*-
"""读 PE 文件的导入表，找出「Win7 上不存在」的 API。

为什么要自己解析：项目里没有任何工具能直接回答「这堆二进制能不能在 Win7 跑」，
而 Qt 6 / Python 3.12 官方文档只说「不再支持 Win7」却不给具体是哪个符号。
把导入表里的 kernel32 函数拿去对 Win7 的导出表比较，才能给出**可复核的证据**。

用法：python -X utf8 tools/win7_compat_check.py [目录或文件...]
"""
from __future__ import annotations

import os
import struct
import sys

# Win7（NT 6.1）的 kernel32 里**没有**的函数。
# 这些都是 Win8 / Win10 才加的，Qt 6 和 Python 3.9+ 大量依赖它们。
WIN7_MISSING = {
    # Windows 8 加入：Qt 的 QSemaphore / QMutex 在 6.x 直接用它们
    "WaitOnAddress", "WakeByAddressSingle", "WakeByAddressAll",
    "InitializeSynchronizationBarrier", "EnterSynchronizationBarrier",
    "DeleteSynchronizationBarrier", "CreateFile2",
    "GetSystemTimePreciseAsFileTime", "GetFileInformationByHandleEx",
    "SetFileInformationByHandle", "CopyFile2",
    # Windows 8.1
    "SetThreadDescription", "GetThreadDescription",
    # Windows 10
    "GetDpiForWindow", "GetDpiForSystem", "SetProcessDpiAwarenessContext",
    "EnableNonClientDpiScaling", "GetSystemMetricsForDpi",
    "SetThreadDpiAwarenessContext", "GetThreadDpiAwarenessContext",
    "GetDpiForMonitor", "AdjustWindowRectExForDpi",
    "LoadLibraryW_",  # 占位，避免误报
    "RtlGetVersion_",  # 占位
    "GetPackageFamilyName", "GetCurrentPackageFullName",
    "CreateFileMappingFromApp", "VirtualAllocFromApp",
    # 其它 Win10+
    "PathCchCanonicalizeEx", "PathCchCombineEx",
    "GetOverlappedResultEx", "WaitForDebugEventEx",
}
# 有些函数是 Universal CRT 转发，Win7 打了 KB2533623 / UCRT 更新后也有，
# 这里只是「可疑清单」，命中不等于必定崩 —— 但 WaitOnAddress 这类是真的没有。
HARD_FAIL = {"WaitOnAddress", "WakeByAddressSingle", "WakeByAddressAll",
             "InitializeSynchronizationBarrier", "CreateFile2",
             "GetSystemTimePreciseAsFileTime", "SetThreadDescription"}


def pe_imports(path: str) -> tuple[list[tuple[str, str]], str]:
    """返回 ([(dll, func), ...], 错误)。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return [], f"读不了：{e}"
    if len(data) < 0x40 or data[:2] != b"MZ":
        return [], "不是 PE"
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return [], "签名不对"
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    is64 = magic == 0x20B
    # 数据目录：PE32+ 从 opt+112 起，PE32 从 opt+96 起
    dd = opt + (112 if is64 else 96)
    imp_rva, imp_size = struct.unpack_from("<II", data, dd + 8)
    if not imp_rva:
        return [], "没有导入表"

    secs = []
    sec_off = opt + opt_size
    for i in range(nsec):
        o = sec_off + i * 40
        name = data[o:o + 8].rstrip(b"\0").decode("latin-1", "replace")
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, o + 8)
        secs.append((name, vaddr, max(vsize, rsize), raddr))

    def rva2off(rva: int) -> int:
        for _n, vaddr, size, raddr in secs:
            if vaddr <= rva < vaddr + size:
                return raddr + (rva - vaddr)
        return -1

    out: list[tuple[str, str]] = []
    desc = rva2off(imp_rva)
    if desc < 0:
        return [], "导入表定位失败"
    while True:
        oft, _ts, _fwd, name_rva, ft = struct.unpack_from("<IIIII", data, desc)
        if not name_rva and not ft:
            break
        dll_off = rva2off(name_rva)
        dll = (data[dll_off:data.index(b"\0", dll_off)]
               .decode("latin-1", "replace")) if dll_off > 0 else "?"
        thunk = oft or ft
        t = rva2off(thunk)
        if t < 0:
            desc += 20
            continue
        step = 8 if is64 else 4
        while True:
            val = struct.unpack_from("<Q" if is64 else "<I", data, t)[0]
            if val == 0:
                break
            if not (val >> (63 if is64 else 31)):      # 按名字导入
                fo = rva2off(val & 0x7FFFFFFF)
                if fo > 0:
                    fn = data[fo + 2:data.index(b"\0", fo + 2)]
                    out.append((dll, fn.decode("latin-1", "replace")))
            t += step
        desc += 20
    return out, ""


def check(path: str) -> int:
    imports, err = pe_imports(path)
    name = os.path.basename(path)
    if err:
        print(f"  ? {name}: {err}")
        return 0
    hits = sorted({fn for dll, fn in imports
                   if dll.lower().startswith(("kernel32", "api-ms-win-core"))
                   and fn in WIN7_MISSING})
    hard = sorted({fn for dll, fn in imports if fn in HARD_FAIL})
    tag = "✗" if hard else ("!" if hits else "✓")
    print(f"  {tag} {name}")
    if hard or hits:
        # 给出「哪个 DLL 要求的」，便于判断是 Qt 还是 Python 的门槛
        owners: dict[str, set] = {}
        for dll, fn in imports:
            if fn in (hard or hits):
                owners.setdefault(dll, set()).add(fn)
        for dll, fns in sorted(owners.items()):
            mark = "必定失败" if fns & HARD_FAIL else "可疑"
            print(f"       {mark} ← {dll}: {', '.join(sorted(fns))}")
    return 1 if hard else 0


def main(argv: list[str]) -> int:
    targets = argv[1:] or ["."]
    files: list[str] = []
    for t in targets:
        if os.path.isfile(t):
            files.append(t)
        else:
            for dirpath, _d, names in os.walk(t):
                for n in names:
                    if n.lower().endswith((".dll", ".pyd", ".exe")):
                        files.append(os.path.join(dirpath, n))
    if not files:
        print("没找到可检查的二进制")
        return 1
    print(f"检查 {len(files)} 个文件里「Win7 缺失的 API」：\n")
    bad = 0
    for f in files:
        bad += check(os.path.abspath(f))
    print()
    if bad:
        print(f"结论：{bad} 个文件用到了 Win7 没有的 API → **不能在 Win7 运行**")
        return 1
    print("结论：没发现 Win7 缺失的 API")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
