# -*- coding: utf-8 -*-
"""端到端复现事故场景：模拟「游戏目录里躺着被替换过的改版 steam_api64.dll」。

真拿一个会弹「socialclub.dll not found」的坏 DLL 是不现实的（也没有样本），
但**事故的触发条件**可以精确复现：让 `find_steam_api_dll()` 面对一棵
「只有改版 DLL」的游戏库。

判定标准只有一条：**它必须返回空串**（= 我们不会去 LoadLibrary 那个文件）。
只要返回了路径，就意味着新代码会把危险 DLL 拉进进程 —— 那就是没修好。
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

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="l4d2_cracked_")
    saved = (SF._api_dll_cache, SF._steam_root, SF._library_roots)
    try:
        common = os.path.join(tmp, "steamapps", "common")
        game = os.path.join(common, "Grand Theft Auto V")
        os.makedirs(game, exist_ok=True)

        # 找一个「非 Valve 签名、体积够大」的文件冒充改版 DLL。
        # 真实世界里的改版 steam_api64.dll 就是这个特征：不是 Valve 签的。
        donor = ""
        for cand in (r"C:\Windows\System32\shell32.dll",
                     r"C:\Windows\System32\uxtheme.dll",
                     r"C:\Windows\System32\comctl32.dll"):
            if os.path.isfile(cand) and os.path.getsize(cand) > 60_000:
                donor = cand
                break
        if not donor:
            print("  跳过：找不到可用于冒充的文件")
            return 0

        dst = os.path.join(game, "steam_api64.dll")
        shutil.copy2(donor, dst)
        # 故意放一个「更大」的，模拟旧逻辑会优先挑它
        game2 = os.path.join(common, "Red Dead Redemption 2")
        os.makedirs(game2, exist_ok=True)
        shutil.copy2(donor, os.path.join(game2, "steam_api64.dll"))

        print(f"  造了 2 个假 steam_api64.dll（{os.path.getsize(dst):,} 字节，非 Valve 签名）")

        # ★ 还要放一个 steamclient64.dll，否则 open() 会在更前面一步就返回
        #   「找不到 steamclient64.dll」，根本走不到验签逻辑。
        #   这里放个空壳文件即可：open() 只做 os.path.isfile 检查，
        #   而 api_dll 为空时它会在 LoadLibrary 之前就返回。
        open(os.path.join(tmp, "steamclient64.dll"), "wb").close()

        SF._api_dll_cache = None
        SF._steam_root = lambda: tmp            # type: ignore[assignment]
        SF._library_roots = lambda _r: [tmp]    # type: ignore[assignment]

        got = SF.find_steam_api_dll(tmp)
        check("面对全是改版 DLL 的游戏库，返回空串（不会加载它）", got == "", got)

        # 顺便验证 _Steam.open() 会优雅失败，而不是去加载
        s = SF._Steam()
        ok = s.open()
        check("open() 返回 False（好友功能跳过）", ok is False)
        check("错误文案说清了是「签名」问题，不是「找不到文件」",
              "签名" in s.err, s.err[:70])
        s.close()

        # 再验证：一旦混进一个真的，就该挑真的、跳过假的
        real = ""
        root = saved[1]()
        if root:
            for lib in (saved[2](root) if callable(saved[2]) else []):
                c = os.path.join(lib, "steamapps", "common")
                if not os.path.isdir(c):
                    continue
                for name in os.listdir(c):
                    p = os.path.join(c, name, "steam_api64.dll")
                    if os.path.isfile(p) and SF._dll_is_genuine(p):
                        real = p
                        break
                if real:
                    break

        if real:
            good_game = os.path.join(common, "Stardew Valley")
            os.makedirs(good_game, exist_ok=True)
            shutil.copy2(real, os.path.join(good_game, "steam_api64.dll"))
            SF._api_dll_cache = None
            got2 = SF.find_steam_api_dll(tmp)
            check("真假混放时挑中的是真的那个",
                  got2 and SF._dll_is_genuine(got2), got2)
            check("没挑那两个假的",
                  os.path.normcase(got2) not in
                  {os.path.normcase(os.path.join(game, "steam_api64.dll")),
                   os.path.normcase(os.path.join(game2, "steam_api64.dll"))}, got2)
        else:
            print("  (跳过真假混放：这台机器上没有真 DLL 样本)")
    finally:
        SF._api_dll_cache, SF._steam_root, SF._library_roots = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
