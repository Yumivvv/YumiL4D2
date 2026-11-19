"""测试用的「用户数据保护罩」。

很多测试会构造真的 `Core()`，而 `Core` 一启动就会写
`data/config.json`、`data/library.json`、`data/modimports.json`。
以前直接跑这些测试，会把用户自己调好的主题色、背景图透明度、播放器音量、
导入日期台账覆盖成测试值（真的发生过）。

用法（放在 `import app.*` **之前**，紧跟在 sys.path 设置之后）：

    from guard import protect_user_data     # tools 目录在 sys.path 里
    protect_user_data()

原理：设置环境变量 `L4D2_DATA_DIR`，并让 `app.util.DATA_DIR` 读它。
只要在 import `app.*` 之前设好，`store.CONFIG_PATH` / `mods.IMPORT_LEDGER_PATH`
这些全部会落到临时沙盒里，一条真实文件都写不到。

**`backgrounds/` 也要隔离**：背景图现在是「只有一个 background.*，移除即删除」，
测试里一调 `clearBgImage()` 就会把用户那张图真删掉（真发生过，用户的壁纸被删了）。
所以沙盒里也建一个空的 `backgrounds/`，并把 `util.BG_DIR` 指过去。

如果已经 import 过 `app.*` 了，用 `guard_after_import()` 就地改掉模块里的路径常量。
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

_real_data_dir_cache: str | None = None


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_subdirs(sandbox: str, bg_dir: str = "") -> None:
    for sub in ("cache", "covers", "logs", "modcache"):
        os.makedirs(os.path.join(sandbox, sub), exist_ok=True)
    if bg_dir:
        os.makedirs(bg_dir, exist_ok=True)


def _repoint_loaded_modules(sandbox: str, bg_dir: str = "") -> None:
    """把已经 import 过的模块里的路径常量改到沙盒。"""
    import app.util as util  # noqa: PLC0415

    util.DATA_DIR = sandbox
    if bg_dir:
        util.BG_DIR = bg_dir
        # wallpaper / sound 在 import 时把 BG_DIR 当默认参数吃进去了，得一起改
        for mod_name in ("app.wallpaper", "app.sound"):
            mod = sys.modules.get(mod_name)
            if mod is not None and bg_dir:
                if hasattr(mod, "BG_DIR"):
                    mod.BG_DIR = bg_dir
    # 这几个在 import 时就把路径算死了，必须挨个改
    for mod_name, attrs in (
        ("app.store", ("CONFIG_PATH", "LIBRARY_PATH", "LIBRARY_BAK")),
        ("app.mods", ("CACHE_DIR", "META_PATH", "AUTHOR_PATH", "IMPORT_LEDGER_PATH")),
        ("app.modmanager", ("FAV_PATH",)),
    ):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for attr in attrs:
            cur = getattr(mod, attr, "")
            base = os.path.basename(cur) if cur else ""
            if base:
                setattr(mod, attr, os.path.join(sandbox, base))


def protect_user_data(verbose: bool = True) -> str:
    """把运行时数据目录切到临时沙盒；返回沙盒路径（重复调用幂等）。"""
    root = project_root()
    if root not in sys.path:
        sys.path.insert(0, root)

    sandbox = os.environ.get("L4D2_TEST_DATA_DIR")
    if sandbox and os.path.isdir(sandbox):
        _repoint_loaded_modules(sandbox, os.environ.get("L4D2_TEST_BG_DIR", ""))
        return sandbox

    global _real_data_dir_cache
    _real_data_dir_cache = os.path.join(root, "data")

    sandbox = tempfile.mkdtemp(prefix="l4d2_testdata_")
    os.environ["L4D2_TEST_DATA_DIR"] = sandbox
    # 关键：让之后 import 的 app.util 直接指向沙盒
    os.environ["L4D2_DATA_DIR"] = sandbox

    # 背景图目录也隔离：测试会「移除背景 = 真删文件」，绝不能碰用户那张
    bg_dir = os.path.join(sandbox, "backgrounds")
    os.environ["L4D2_TEST_BG_DIR"] = bg_dir
    os.environ["L4D2_BG_DIR"] = bg_dir

    # 复制小的配置/缓存类文件，让测试看到接近真实的环境。
    # 视频库（library.json 几百 KB）不复制：测试不该依赖用户的具体数据；
    # modmeta.json / authors.json 是工坊元数据缓存，测试要靠它验证「可更新」这类判定。
    for name in ("config.json", "favorites.json", "modmeta.json", "authors.json"):
        src = os.path.join(_real_data_dir_cache, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(sandbox, name))

    _ensure_subdirs(sandbox, bg_dir)
    _repoint_loaded_modules(sandbox, bg_dir)

    atexit.register(lambda: shutil.rmtree(sandbox, ignore_errors=True))
    if verbose:
        print(f"[guard] 用户数据已隔离到 {sandbox}")
    return sandbox


def guard_after_import(verbose: bool = True) -> str:
    """已经 import 过 app.* 时用这个补救（在构造 Core 之前调用）。"""
    return protect_user_data(verbose=verbose)

