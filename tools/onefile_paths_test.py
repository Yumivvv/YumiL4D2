"""验证「打包成单文件 exe 之后，用户数据落在 exe 旁边」这套路径逻辑。

背景（真出过事）：`app/util.py` 以前用 `__file__` 往上两级当 ROOT。
PyInstaller 单文件版会把资源解到 `%TEMP%\\_MEIxxxx`，`__file__` 就在那里，
于是 `data/`、`sounds/`、`backgrounds/` 全落进临时目录 —— 程序一关就被删掉，
用户看到的是「每次打开都是空的、MOD 目录也没记住」。

这个脚本不需要开窗口，纯逻辑验证：
1. 模拟 frozen 状态，确认各目录分别指向 exe 旁边 / 解包目录
2. 跑一遍 seed_user_dirs()，确认文件夹建好、自带音效铺过去、老数据搬一次家
3. 确认 `resolve_sound_path()` 在用户目录还没有音效时能退回自带的那份
4. 开发模式（未打包）行为不变
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


def fresh_util(frozen: bool, exe_dir: str, bundle: str):
    """按给定「运行形态」重新加载 app.util，返回模块.

    注意：不能只删 `sys.modules["app.util"]` 再 `from app import util` ——
    `from X import Y` 会先看 `app` 包上挂着的旧属性，拿回来的还是老模块，
    常量全是上一次算的（这个坑实测踩过，dev 模式断言因此误报）。
    用 importlib.reload() 最稳：对象不变、模块代码重跑一遍。
    """
    if frozen:
        sys.frozen = True
        sys.executable = os.path.join(exe_dir, "Yumi的L4D2工具箱.exe")
        sys._MEIPASS = bundle
    else:
        sys.__dict__.pop("frozen", None)
        sys.__dict__.pop("_MEIPASS", None)
        sys.executable = os.path.join(bundle, "python.exe")
    return importlib.reload(importlib.import_module("app.util"))


def main() -> int:
    sandbox = tempfile.mkdtemp(prefix="l4d2_onefile_")
    exe_dir = os.path.join(sandbox, "导出目录")
    bundle = os.path.join(sandbox, "_MEI123456")
    os.makedirs(exe_dir)
    # 伪造「打包进 exe 的只读资源」
    os.makedirs(os.path.join(bundle, "qml"))
    os.makedirs(os.path.join(bundle, "sounds"))
    with open(os.path.join(bundle, "qml", "Main.qml"), "w", encoding="utf-8") as fh:
        fh.write("// qml\n")
    with open(os.path.join(bundle, "sounds", "bbb.mp3"), "wb") as fh:
        fh.write(b"ID3fake")
    # 伪造「老版本把数据放在程序目录里」的现场
    os.makedirs(os.path.join(bundle, "data"))
    with open(os.path.join(bundle, "data", "config.json"), "w", encoding="utf-8") as fh:
        fh.write('{"keyword": "老配置"}')

    old_frozen = getattr(sys, "frozen", None)
    old_exe = sys.executable
    old_meipass = getattr(sys, "_MEIPASS", None)
    try:
        print("=== 单文件模式 ===")
        util = fresh_util(True, exe_dir, bundle)
        check("自带资源指向解包目录", os.path.abspath(util.ROOT) == os.path.abspath(bundle),
              util.ROOT)
        check("用户目录指向 exe 所在目录", os.path.abspath(util.USER_ROOT) == os.path.abspath(exe_dir),
              util.USER_ROOT)
        check("data 在 exe 旁边",
              os.path.abspath(util.DATA_DIR) == os.path.abspath(os.path.join(exe_dir, "data")))
        check("sounds 在 exe 旁边",
              os.path.abspath(util.SOUNDS_DIR) == os.path.abspath(os.path.join(exe_dir, "sounds")))
        check("backgrounds 在 exe 旁边",
              os.path.abspath(util.BG_DIR) == os.path.abspath(os.path.join(exe_dir, "backgrounds")))
        check("缓存/封面/日志都在 data 下面",
              all(p.startswith(os.path.abspath(util.DATA_DIR))
                  for p in (util.CACHE_DIR, util.COVER_DIR, util.LOG_DIR)))
        check("resource_path 仍然指向解包目录的只读资源",
              os.path.isfile(util.resource_path("sounds", "bbb.mp3")))

        util.seed_user_dirs()
        check("data / cache / covers / logs 都建好了",
              all(os.path.isdir(d) for d in (util.DATA_DIR, util.CACHE_DIR,
                                             util.COVER_DIR, util.LOG_DIR)))
        check("sounds / backgrounds 也建好了",
              os.path.isdir(util.SOUNDS_DIR) and os.path.isdir(util.BG_DIR))
        check("自带提示音铺进了用户目录",
              os.path.isfile(os.path.join(util.SOUNDS_DIR, "bbb.mp3")))
        check("老版本的数据搬过来了（config.json）",
              os.path.isfile(os.path.join(util.DATA_DIR, "config.json")))
        with open(os.path.join(util.DATA_DIR, "config.json"), encoding="utf-8") as fh:
            check("搬过来的就是老配置", "老配置" in fh.read())

        # 再跑一次不应该覆盖用户自己改过的音效
        with open(os.path.join(util.SOUNDS_DIR, "bbb.mp3"), "wb") as fh:
            fh.write(b"user-replaced")
        util.seed_user_dirs()
        with open(os.path.join(util.SOUNDS_DIR, "bbb.mp3"), "rb") as fh:
            check("用户替换过的音效不会被再次覆盖", fh.read() == b"user-replaced")

        print("=== 自带音效的兜底查找 ===")
        from app import sound                   # noqa: PLC0415
        os.remove(os.path.join(util.SOUNDS_DIR, "bbb.mp3"))
        got = sound.resolve_sound_path("bbb.mp3", util.SOUNDS_DIR)
        check("用户目录没有时退回程序自带的那份",
              got and os.path.abspath(got) == os.path.abspath(os.path.join(bundle, "sounds", "bbb.mp3")),
              got)

        print("=== 开发模式（未打包）===")
        dev = fresh_util(False, exe_dir, bundle)
        proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        check("不打包时用户目录就是项目根", os.path.abspath(dev.USER_ROOT) == os.path.abspath(proj),
              dev.USER_ROOT)
        check("不打包时 data 还在项目里",
              os.path.abspath(dev.DATA_DIR) == os.path.abspath(os.path.join(proj, "data")))
    finally:
        if old_frozen is None:
            sys.__dict__.pop("frozen", None)
        else:
            sys.frozen = old_frozen
        if old_meipass is None:
            sys.__dict__.pop("_MEIPASS", None)
        else:
            sys._MEIPASS = old_meipass
        sys.executable = old_exe
        # 再 reload 一次，把模块常量还原成开发模式的取值，别污染同进程里的其它测试
        importlib.reload(importlib.import_module("app.util"))
        shutil.rmtree(sandbox, ignore_errors=True)

    if FAILS:
        print("\n失败 %d 项：%s" % (len(FAILS), "，".join(FAILS)))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
