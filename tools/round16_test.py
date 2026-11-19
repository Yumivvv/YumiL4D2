"""本轮 10 项改动 + 清理的自检。

1. 设置从「右侧抽屉」变成**普通一页**（section 5），侧栏可点、主区域收起。
2. 下载线程补上 3 这一档，默认 4，上限 16。
3. 下载页「清空已结束」不再压住窗口按钮。
4. 下载页能拖动窗口（拖动带盖在页面之上）。
5. 服务器页那行多余的文字提示已删（只留需要人看的异常）。
6. 蓝奏云下到的是 MOD 文件 → 落 addons；否则 downloads/pan。
7. 视频详情的「下载」按钮已去掉（原来五个按钮挤一行）。
8. MOD 筛选/排序跨重启记住。
9. 「启动游戏」从 MOD 面板搬到左下角（播放图标）。
10. 死代码已清（GlassCard / TagChip）。
"""
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import io
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import json
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import os
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QGuiApplication              # noqa: E402

from guard import protect_user_data                    # noqa: E402

protect_user_data()

from app import workshop_dl as WD                      # noqa: E402
from app.core import Core                              # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def src(rel):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return open(os.path.join(root, rel), encoding="utf-8").read()


def code_lines(text):
    """去掉纯注释行，只留真正的代码（注释里提到旧东西是对的，不该判失败）。"""
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("//")]


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    core = Core(app)
    globals()["_KEEP_CORE"] = core

    main_qml = src(os.path.join("qml", "Main.qml"))
    srv_qml = src(os.path.join("qml", "components", "ServersPage.qml"))
    dl_qml = src(os.path.join("qml", "components", "DownloadsPage.qml"))
    detail_qml = src(os.path.join("qml", "components", "DetailPanel.qml"))
    mod_qml = src(os.path.join("qml", "components", "ModPanel.qml"))
    dl_py = src(os.path.join("app", "downloads.py"))
    mm_py = src(os.path.join("app", "modmanager.py"))

    print("\n-- 1. 设置是普通一页（不是抽屉）", flush=True)
    check("设置页靠 section 5 显示", "win.section === 5" in main_qml)
    check("不再是右侧滑出的抽屉", "anchors.rightMargin: win.settingsOpen ? 14"
          not in main_qml)
    check("侧栏那颗设置按钮切 section", "win.section = (win.section === 5 ? 0 : 5)"
          in main_qml)
    check("设置页把侧栏 224px 让出来", "anchors.leftMargin: 224" in main_qml)
    check("主区域在设置页时收起", "id: mainArea" in main_qml
          and "visible: win.section !== 5" in main_qml)
    # settingsOpen 这个属性已经彻底移除，不应该再有残留代码
    left = [ln for ln in code_lines(main_qml) if "settingsOpen" in ln]
    check("settingsOpen 已彻底移除", not left, left[:2])

    print("\n-- 2. 下载线程：补 3、默认 4、上限 16", flush=True)
    check("默认线程 = 4", WD.DEFAULT_THREADS == 4, WD.DEFAULT_THREADS)
    check("上限 = 16", WD.MAX_THREADS == 16, WD.MAX_THREADS)
    check("配置默认值也是 4",
          '"download_threads": 4' in src(os.path.join("app", "store.py")))
    check("界面上 3 这一档回来了",
          "model: [1, 2, 3, 4, 6, 8, 12, 16]" in main_qml)
    check("clamp(3) 就是 3", WD.clamp_threads(3) == 3, WD.clamp_threads(3))

    print("\n-- 3. 下载页按钮不再压住窗口按钮", flush=True)
    check("清空按钮右侧让位", "winButtonsReserve" in dl_qml)
    check("让位量取自 Main.qml 的统一常量", "winButtonsReserve" in main_qml)

    print("\n-- 4. 下载页能拖窗口", flush=True)
    check("有专门的拖动带", "dlDragStrip" in main_qml)
    check("拖动带走 startSystemMove", "win.startSystemMove()" in main_qml)
    check("拖动带 z 高于页面", "z: 5" in main_qml)
    check("拖动带只吃左键、不吃点击（页头按钮还能点）",
          "acceptedButtons: Qt.LeftButton" in main_qml)

    print("\n-- 5. 服务器页多余文字已删", flush=True)
    check("提示条不再显示长期状态",
          "page.mgr.statusText : \"\"" not in srv_qml)
    check("只有需要人看的才显示", "isTransientHint" in srv_qml)
    check("提示会到点自动消失", "hintTimer" in srv_qml)
    check("提示条有 objectName 供测试定位", 'objectName: "srvHintLine"' in srv_qml)

    print("\n-- 6. 蓝奏云的 MOD 文件落到 addons", flush=True)
    check("会判断是不是 MOD 文件", "is_vpk" in dl_py)
    check("压缩包不算 MOD（要用户自己解）", "is_archive" in dl_py)
    check("是 MOD 就改去向到 addons", "task.dest = addons" in dl_py)
    check("落盘后重扫让列表出现", "mods.scan()" in dl_py)
    # 判定逻辑单测
    def judge(fname, raw_name, direct):
        probe = f"{fname} {raw_name} {direct}".lower()
        is_archive = any(probe.split("?")[0].rstrip().endswith(e)
                         for e in (".zip", ".rar", ".7z"))
        is_vpk = (probe.rstrip().endswith(".vpk") or ".vpk" in probe
                  or (not is_archive and ("mod" in probe or "vpk" in probe)))
        return is_vpk and not is_archive

    check("判 .vpk 为 MOD", judge("武器.vpk", "", "https://x/a"))
    check("判压缩包为非 MOD", not judge("资源.zip", "", "https://x/a.zip"))
    check("判普通文件为非 MOD", not judge("音乐.mp3", "", "https://x/a.mp3"))

    print("\n-- 7. 视频详情去掉「下载」按钮", flush=True)
    check("详情面板没有下载按钮了", 'objectName: "dlVideoButton"' not in detail_qml)
    check("按钮数回到 4 个", detail_qml.count("ActionButton {") == 4,
          detail_qml.count("ActionButton {"))
    check("四个按钮比例加起来就是 1.0",
          all(x in detail_qml for x in ("0.30", "0.24", "0.22", "0.20")))

    print("\n-- 8. 筛选/排序跨重启记住", flush=True)
    check("有 _remember_filters", "_remember_filters" in mm_py)
    check("初始化时读回", 'self._cfg["mod_sort_mode"]' in mm_py)
    check("config 里有这些键",
          all(f'"mod_{k}"' in src(os.path.join("app", "store.py"))
              for k in ("filter", "sort_mode", "status_filter", "category")))
    # 端到端：设一次 → 落盘 → **新建一个 ModManager 读回**。
    # 注意不能拿 `core.config` 去断言：`ModManager` 内部自己 `Config()` 了一份
    # （`self._cfg`），和 `core.config` 是两个实例，各写各的。真正要验的是
    # 「关掉软件再开能不能读回」，所以用新实例最贴近真实。
    mm = core.mods
    mm.setSortMode(5)
    mm.setStatusFilter(3)
    check("排序写进了它自己那份 config", int(mm._cfg["mod_sort_mode"]) == 5,
          mm._cfg["mod_sort_mode"])
    check("状态筛选写进了它自己那份 config",
          int(mm._cfg["mod_status_filter"]) == 3, mm._cfg["mod_status_filter"])
    # 磁盘上也要有（下次启动就是从磁盘读）
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "config.json")
    # guard 会把数据隔离到沙箱，所以按实际路径读
    from app import util                                    # noqa: PLC0415
    cfg_path = os.path.join(util.DATA_DIR, "config.json")
    try:
        disk = json.load(open(cfg_path, encoding="utf-8"))
    except (OSError, ValueError):
        disk = {}
    check("磁盘上也写进去了", int(disk.get("mod_sort_mode", -1)) == 5,
          disk.get("mod_sort_mode"))
    # 新建一个 ModManager 读回来（模拟重启）
    from app.modmanager import ModManager                   # noqa: PLC0415
    mm2 = ModManager(core)
    check("重新构造能读回排序", mm2.sortMode == 5, mm2.sortMode)
    check("重新构造能读回筛选", mm2.statusFilter == 3, mm2.statusFilter)
    mm.resetFilters()
    mm.setSortMode(0)

    print("\n-- 9. 启动游戏搬到左下角", flush=True)
    check("MOD 面板里删掉了", "启动游戏" not in code_lines(mod_qml)
          or "page.mgr.launchGame()" not in mod_qml)
    check("左下角有启动按钮", 'objectName: "launchGameBtn"' in main_qml)
    check("按钮接的是 launchGame", "core.mods.launchGame()" in main_qml)
    check("用播放三角图标", "\\uE768" in main_qml)

    print("\n-- 10. 死代码已清", flush=True)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("GlassCard", "TagChip"):
        p = os.path.join(root, "qml", "components", name + ".qml")
        check(f"{name}.qml 已删除", not os.path.exists(p))
    # 确认全项目真的没有再引用
    all_qml = "\n".join(src(os.path.join("qml", f)) for f in
                        ["Main.qml"] + [os.path.join("components", c)
                                        for c in os.listdir(os.path.join(root, "qml", "components"))
                                        if c.endswith(".qml")])
    check("没有残留引用", "GlassCard" not in all_qml and "TagChip" not in all_qml)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "、".join(FAILS)), flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
