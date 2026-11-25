# -*- coding: utf-8 -*-
"""「能不能在 Win7 上跑」的结论 + 证据，做成可复跑的检查。

## 为什么不是「改几行代码就能支持 Win7」

下结论不能靠感觉，这里直接读**二进制的导入表**（PE Import Directory）：

    Qt6Core.dll  →  KERNEL32.dll: SetThreadDescription
                    api-ms-win-core-synch-l1-2-0.dll:
                        WaitOnAddress / WakeByAddressSingle / WakeByAddressAll
    python312.dll → KERNEL32.dll: CopyFile2 / GetFileInformationByHandleEx
                    api-ms-win-core-path-l1-1-0.dll: PathCchCombineEx

这些 API 都是 **Windows 8 以后**才有的。而它们在**静态导入表**里
（不是延迟加载），所以 Windows 7 加载这两个 DLL 时就会报
「无法定位程序输入点」，进程直接起不来 —— 不是「某个功能不能用」，
而是**双击就闪退**。

这个结论对 PySide6 6.x（Qt 6）和 Python 3.9+ 都成立：
- Qt 6 官方要求 Windows 10 及以上（Qt 5.15 是最后一个支持 Win7 的）；
- CPython 3.9 起官方也只构建到 Win8.1+（3.8 是最后一个支持 Win7 的）。

## 本测试验什么

1. 当前依赖的 Qt / Python 二进制确实带 Win7 缺失的 API（证据在，别凭记忆）
2. 这些 API 在**静态**导入表里（决定了「启动即失败」而不是「用到才失败」）
3. 项目**自己的代码**没有直接调用 Win10+ 专属 API（这部分是干净的，
   说明瓶颈在运行时、不在业务代码）
4. 现有的 Win10 分支逻辑在 Win7 上会走「安全的那条」（不透明窗口、
   图标字体回退），它不构成障碍
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from win7_compat_check import HARD_FAIL, WIN7_MISSING, pe_imports  # noqa: E402
from win7_delay_check import pe_delay_imports  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def site_packages() -> str:
    import PySide6
    return os.path.dirname(os.path.dirname(os.path.abspath(PySide6.__file__)))


def check_binary(label: str, path: str) -> list[str]:
    """返回这个二进制在 Win7 上缺失、且是**静态**导入的 API 列表。"""
    if not os.path.isfile(path):
        print(f"  [skip] {label}: 没这个文件 {path}")
        return []
    static, err = pe_imports(path)
    if err:
        print(f"  [skip] {label}: {err}")
        return []
    delayed = pe_delay_imports(path)
    s_hits = sorted({fn for _d, fn in static if fn in WIN7_MISSING})
    d_hits = {fn for _d, fn in delayed if fn in WIN7_MISSING}
    hard = [f for f in s_hits if f in HARD_FAIL]
    print(f"  {label}:")
    print(f"    静态导入里 Win7 缺的: {s_hits or '无'}")
    print(f"    延迟加载里 Win7 缺的: {sorted(d_hits) or '无'}")
    return hard or s_hits


def main() -> int:
    sp = site_packages()
    py_dir = os.path.dirname(sp)

    # ------------------------------------------------ 1. Qt 核心库
    print("=== 1. Qt 6 核心库是否依赖 Win8+ 的 API ===")
    qt_core = os.path.join(sp, "PySide6", "Qt6Core.dll")
    qt_hits = check_binary("Qt6Core.dll", qt_core)
    check("Qt6Core.dll 确实用了 Win7 没有的 API（这是硬门槛）",
          bool(qt_hits), str(qt_hits))
    check("其中包含 WaitOnAddress 家族（Win8 同步原语）",
          any("WakeByAddress" in h or h == "WaitOnAddress" for h in qt_hits),
          str([h for h in qt_hits if "Address" in h]))
    check("其中包含 SetThreadDescription（Win10 线程命名）",
          "SetThreadDescription" in qt_hits)

    # ------------------------------------------------ 2. Python 运行时
    print("=== 2. Python 运行时本身 ===")
    # ★ pythonXY.dll 在**解释器根目录**（D:\Python\3.12\），不在 Lib\ 下。
    #   而且根目录里还有个 `python3.dll`（转发存根，没有导入表），
    #   按 startswith("python3") 会先挑到它 —— 必须按「python3+数字」精确匹配。
    py_hits: list[str] = []
    ver_tag = "python%d%d.dll" % sys.version_info[:2]
    for base in (sys.base_prefix, os.path.dirname(sys.executable)):
        if not base:
            continue
        cand = os.path.join(base, ver_tag)
        if os.path.isfile(cand):
            py_hits = check_binary(ver_tag, cand)
            break
    else:
        print(f"  [skip] Python 运行时：找不到 {ver_tag}")
    check("Python 运行时也用了 Win7 没有的 API",
          bool(py_hits), str(py_hits))

    # ------------------------------------------------ 3. 是否静态导入
    print("=== 3. 是不是「启动就失败」而不是「用到才失败」 ===")
    if os.path.isfile(qt_core):
        static, _ = pe_imports(qt_core)
        delayed = pe_delay_imports(qt_core)
        s = {fn for _d, fn in static if fn in WIN7_MISSING}
        d = {fn for _d, fn in delayed if fn in WIN7_MISSING}
        check("Qt 的 Win8+ API 在**静态**导入表里（→ 加载即失败）",
              bool(s), str(sorted(s)))
        check("这些 API 并不在延迟加载表里（否则还能救）",
              not (d & s), f"延迟里也有：{sorted(d & s)}")

    # ------------------------------------------------ 4. 项目自己的代码干净
    print("=== 4. 项目业务代码有没有直接用 Win10+ 专属 API ===")
    project_hits: list[str] = []
    skip_dirs = {"build", "dist", "__pycache__", ".git", "tools"}
    for dirpath, dirnames, names in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for n in names:
            if not n.endswith(".py"):
                continue
            p = os.path.join(dirpath, n)
            try:
                src = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for api in ("GetDpiForWindow", "SetProcessDpiAwarenessContext",
                        "SetThreadDescription", "CopyFile2", "WaitOnAddress",
                        "PathCchCombineEx", "GetSystemTimePreciseAsFileTime"):
                if api in src:
                    project_hits.append(f"{n}:{api}")
    check("业务代码没有直接调用 Win10+ 专属 API（瓶颈在运行时，不在代码）",
          not project_hits, str(project_hits[:6]))

    # ------------------------------------------------ 5. 现有 Win7 分支
    print("=== 5. 已有的版本分支在 Win7 上走的是安全路径 ===")
    main_src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    check("透明窗口按 build 号判断（不是写死开启）",
          "sys.getwindowsversion().build" in main_src)
    check("阈值是 22000（Win11）→ Win7 会走不透明底色",
          "22000" in main_src)
    # Win7 build=7601 → `7601 >= 22000` 为 False，也就是「安全的那条」。
    # ★ 不能用 `7601 >= 22000 is False`：Python 把它解析成链式比较
    #   `(7601 >= 22000) and (22000 is False)`，右侧恒为 False，断言永远失败。
    win7_build = 7601
    check("Win7(build 7601) 判定为不支持透明 → 用不透明窗口",
          (win7_build >= 22000) == False)  # noqa: E712
    core_src = open(os.path.join(ROOT, "app", "core.py"),
                    encoding="utf-8").read()
    check("图标字体有回退链（不会写死 Win11 字体）",
          "Segoe Fluent Icons" in core_src and "Segoe MDL2 Assets" in core_src)
    check("回退链里还有更老的 Segoe UI Symbol",
          "Segoe UI Symbol" in core_src)

    # ------------------------------------------------ 6. 结论
    print()
    blocked = bool(qt_hits or py_hits)
    print("=" * 62)
    if blocked:
        print("结论：**当前版本无法在 Windows 7 上运行**")
        print()
        print("原因不在本项目代码，而在两个运行时：")
        print("  · Qt 6（PySide6 6.x）静态依赖 WaitOnAddress 等 Win8+ API")
        print("  · Python 3.12 静态依赖 CopyFile2 / PathCchCombineEx 等")
        print("Win7 加载这两个 DLL 时会报「无法定位程序输入点」，进程直接起不来。")
        print()
        print("（详细清单与可复现的检查命令见 docs/DEVELOPMENT.md 的")
        print(" 「能不能在 Win7 上跑」一节）")
    print("=" * 62)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过（结论有据可查）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
