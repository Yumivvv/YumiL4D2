# -*- coding: utf-8 -*-
"""区分「静态导入」和「延迟加载导入」—— 决定 Win7 上到底是「启动就崩」还是「用到才崩」。

Qt 有些 Win8+ API 放在 delay-load 里，那种在 Win7 上不会导致加载失败，
只有真去调用才会炸。这个区别直接决定兼容性结论，不能含糊。
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from win7_compat_check import WIN7_MISSING, pe_imports  # noqa: E402


def pe_delay_imports(path: str) -> list[tuple[str, str]]:
    """读 PE 的 Delay Import Directory。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    if len(data) < 0x40 or data[:2] != b"MZ":
        return []
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return []
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    is64 = struct.unpack_from("<H", data, opt)[0] == 0x20B
    dd = opt + (112 if is64 else 96)
    # 数据目录第 13 项（0-based）是 delay import
    off = dd + 13 * 8
    dl_rva, dl_size = struct.unpack_from("<II", data, off)
    if not dl_rva:
        return []

    secs = []
    for i in range(nsec):
        o = opt + opt_size + i * 40
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, o + 8)
        secs.append((vaddr, max(vsize, rsize), raddr))

    def rva2off(rva):
        for vaddr, size, raddr in secs:
            if vaddr <= rva < vaddr + size:
                return raddr + (rva - vaddr)
        return -1

    out = []
    d = rva2off(dl_rva)
    if d < 0:
        return []
    while True:
        if d + 32 > len(data):
            break
        attrs, name_rva = struct.unpack_from("<II", data, d)
        if not name_rva:
            break
        no = rva2off(name_rva)
        if no > 0:
            dll = data[no:data.index(b"\0", no)].decode("latin-1", "replace")
            # 清除属性位
            int_rva = struct.unpack_from("<I", data, d + (4 if not attrs & 1 else 4))[0]
            if attrs & 1:
                int_rva = struct.unpack_from("<I", data, d + 4)[0]
            else:
                int_rva = struct.unpack_from("<I", data, d + 4)[0]
            t = rva2off(int_rva)
            if t > 0:
                step = 8 if is64 else 4
                while True:
                    val = struct.unpack_from("<Q" if is64 else "<I", data, t)[0]
                    if val == 0:
                        break
                    if not (val >> (63 if is64 else 31)):
                        fo = rva2off(val & 0x7FFFFFFF)
                        if fo > 0:
                            fn = data[fo + 2:data.index(b"\0", fo + 2)]
                            out.append((dll, fn.decode("latin-1", "replace")))
                    t += step
        d += 32
    return out


def main(paths: list[str]) -> int:
    for p in paths:
        p = os.path.abspath(p)
        static, _err = pe_imports(p)
        delayed = pe_delay_imports(p)
        s_hits = sorted({fn for _d, fn in static if fn in WIN7_MISSING})
        d_hits = sorted({fn for _d, fn in delayed if fn in WIN7_MISSING})
        print(f"\n{os.path.basename(p)}")
        print(f"  静态导入里 Win7 缺的：{s_hits or '无'}")
        print(f"  延迟加载里 Win7 缺的：{d_hits or '无'}")
        if s_hits:
            print("  → 加载这个 DLL 时就会失败（Win7 直接起不来）")
        elif d_hits:
            print("  → 能加载，只有真正用到那些功能时才失败")
        else:
            print("  → 这两个层面都没问题")
        # 打印延迟加载里的 DLL 名，便于核对
        if delayed:
            dlls = sorted({d for d, _f in delayed})
            print(f"  （延迟加载的 DLL：{', '.join(dlls[:6])}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
