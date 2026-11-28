# -*- coding: utf-8 -*-
"""「打开软件就弹 socialclub.dll not found，点确定整个程序消失」的回归。

## 事故现象（用户报的，别人电脑上）

    打开软件 → 一个 Windows 原生对话框「socialclub.dll not found」
    → 点「确定」→ 软件整个消失。

## 根因（不是我们弹的框）

全项目搜不到任何 MessageBox，也没有这句英文 —— 这个框是**被加载进来的
第三方 DLL 弹的**。

`app/steamfriends.py` 为了读 Steam 好友，会从游戏目录里挑一个
`steam_api64.dll` 直接 `LoadLibraryExW` 进我们进程。而整合包 / 破解补丁
经常把游戏目录里这个文件**替换成改版** —— 它的 `DllMain` 去找自己的
依赖（典型就是 Rockstar 的 `socialclub.dll`），找不到就弹原生框，
用户点确定后它 `TerminateProcess()`，**死的是我们的进程**。

以前挑文件的策略是「按体积从大到小」—— 恰好优先挑到体积更大的改版 DLL。

## 修法

加载前验签（`WinVerifyTrust` + 版本信息里的 CompanyName 必须含 Valve），
验不过就跳过；全都不合格就不启用好友功能（界面照常，只是没有「好友在玩」）。

## 本测试盯什么

1. 本机所有真 `steam_api64.dll` 都能通过验签（别把正版误杀）
2. 伪造的 DLL（随便一个非 Valve 签名的文件）被拒
3. `find_steam_api_dll` 在「目录里只有一个假 DLL」时**返回空串**
   —— 也就是宁可不启用好友，也不加载它
4. 源码断言：不许再出现「只按大小挑」的老写法
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from app import steamfriends as SF  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    src = open(os.path.join(ROOT, "app", "steamfriends.py"), encoding="utf-8").read()

    # ---------------------------------------------------------------- 1. 验签
    print("=== 1. 真的 steam_api64.dll 不许被误杀 ===")
    root = SF._steam_root()
    libs = SF._library_roots(root) if root else []
    real = []
    for lib in libs:
        common = os.path.join(lib, "steamapps", "common")
        if not os.path.isdir(common):
            continue
        for name in os.listdir(common):
            d = os.path.join(common, name, "steam_api64.dll")
            if os.path.isfile(d):
                real.append(d)
        # 再往下两层（bin/ bin64/ 之类）
        for name in os.listdir(common):
            for sub in ("bin", "bin64"):
                d = os.path.join(common, name, sub, "steam_api64.dll")
                if os.path.isfile(d):
                    real.append(d)

    if not real:
        print("  (跳过：这台机器上没有 steam_api64.dll 样本)")
    else:
        passed = [p for p in real if SF._dll_is_genuine(p)]
        check(f"真 DLL 全部通过验签（{len(passed)}/{len(real)}）",
              len(passed) == len(real),
              str([os.path.basename(os.path.dirname(p)) for p in real if p not in passed]))

    print("=== 2. 假 DLL 必须被拒 ===")
    # 拿一个本机必然存在、非 Valve 签名、但体积足够的文件冒充
    fakes = [r"C:\Windows\System32\uxtheme.dll",
             r"C:\Windows\System32\shell32.dll"]
    for f in fakes:
        if os.path.isfile(f):
            check(f"{os.path.basename(f)}（非 Valve 签名）被拒",
                  not SF._dll_is_genuine(f))

    # 复制成 steam_api64.dll 名字，也得拒（光改名骗不过验签）
    tmpd = tempfile.mkdtemp(prefix="l4d2_fakedll_")
    try:
        srcfake = next((f for f in fakes if os.path.isfile(f)), "")
        if srcfake:
            named = os.path.join(tmpd, "steam_api64.dll")
            shutil.copy2(srcfake, named)
            check("冒充的文件改名为 steam_api64.dll 后仍被拒",
                  not SF._dll_is_genuine(named), named)
        else:
            print("  (跳过：没有可用的冒充样本)")

        # -------------------------------------------------- 3. 找不到真 DLL
        print("=== 3. 只有假 DLL 时，必须返回空串（宁可不启用好友）===")
        fake_common = os.path.join(tmpd, "steamapps", "common", "SomeGame")
        os.makedirs(fake_common, exist_ok=True)
        if srcfake:
            shutil.copy2(srcfake, os.path.join(fake_common, "steam_api64.dll"))

        saved_cache = SF._api_dll_cache
        saved_root = SF._steam_root
        saved_libs = SF._library_roots
        try:
            SF._api_dll_cache = None
            SF._steam_root = lambda: tmpd                    # type: ignore[assignment]
            SF._library_roots = lambda _r: [tmpd]            # type: ignore[assignment]
            got = SF.find_steam_api_dll(tmpd)
            check("假 DLL 不会被选中", got == "", got)
        finally:
            SF._api_dll_cache = saved_cache
            SF._steam_root = saved_root                      # type: ignore[assignment]
            SF._library_roots = saved_libs                   # type: ignore[assignment]
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)

    # ---------------------------------------------------------------- 4. 源码
    print("=== 4. 源码断言：不许再退回「只按大小挑」 ===")
    check("有验签函数", "def _dll_is_genuine" in src)
    check("用了 WinVerifyTrust", "WinVerifyTrust" in src)
    check("绝不弹框（UIChoice=NONE）", "dwUIChoice = 2" in src)
    check("检查 CompanyName", "STEAM_DLL_SIGNER" in src and "_dll_company" in src)
    check("find_steam_api_dll 里调了验签", "try_accept" in src and "_dll_is_genuine" in src)
    # 老写法：直接按大小排序取第一个，中间没有任何验签
    check("不再有「排序后直接 return h」的老写法",
          "for h in hits:\n                if os.path.isfile(h) and os.path.getsize(h) > 50_000:" not in src)

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
