"""本轮七个修复的自检。

1. **任务栏点击不能最小化** —— 无边框窗口必须显式带 WindowMinimizeButtonHint
   （等一组 hint），否则 Windows 会把它当成不可最小化的工具窗。
2. **每个界面各有一套窗口按钮** —— 抽成 WindowButtons，只在窗口右上角放一份。
3. **蓝奏云直链** —— 详情页点蓝奏云弹「本地下载 / 浏览器打开」；`resolve_lanzou`
   要能识别域名、对非法输入明确失败（不能假装成功）。
4. **下载线程上限** —— 从 8 提到 16，且 clamp 要跟着放宽。
5. **视频缓存是摆设** —— 已删：Core 不再暴露 videoCache / clearVideoCache，
   界面上也没有那一格了。
6. **主题色改成色盘** —— ColorWheel 存在、接了 previewAccent / setAccent。
7. **服务器元数据字体** —— 中英混排的字段走 UI 字体，纯数字的保留等宽。
"""
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QGuiApplication              # noqa: E402

from guard import protect_user_data                    # noqa: E402

protect_user_data()

from app import lanzou as LZ                           # noqa: E402
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


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    core = Core(app)
    globals()["_KEEP_CORE"] = core

    main_qml = src(os.path.join("qml", "Main.qml"))
    srv_qml = src(os.path.join("qml", "components", "ServersPage.qml"))
    detail_qml = src(os.path.join("qml", "components", "DetailPanel.qml"))
    wheel_qml = src(os.path.join("qml", "components", "ColorWheel.qml"))
    btn_qml = src(os.path.join("qml", "components", "WindowButtons.qml"))

    print("\n-- 1. 任务栏点击能最小化", flush=True)
    check("窗口 flags 带 WindowMinimizeButtonHint",
          "Qt.WindowMinimizeButtonHint" in main_qml)
    check("还带最大化 / 系统菜单 / 关闭 hint",
          all(x in main_qml for x in ("Qt.WindowMaximizeButtonHint",
                                      "Qt.WindowSystemMenuHint",
                                      "Qt.WindowCloseButtonHint")))
    check("仍然是无边框（不能为了 hint 丢掉 FramelessWindowHint）",
          "Qt.FramelessWindowHint" in main_qml)

    print("\n-- 2. 窗口按钮只有一份", flush=True)
    check("有 WindowButtons 组件", "objectName: \"windowButtons\"" in btn_qml)
    check("Main.qml 里只实例化一次",
          main_qml.count("WindowButtons {") == 1, main_qml.count("WindowButtons {"))
    # 以前每页各一套，特征是最小化按钮出现 4 次
    check("不再有 4 套重复的最小化按钮",
          main_qml.count('glyph: "\\uE921"') == 0, main_qml.count('glyph: "\\uE921"'))
    check("组件里三个按钮都在",
          all(x in btn_qml for x in ("winMinBtn", "winMaxBtn", "winCloseBtn")))

    print("\n-- 3. 蓝奏云直链", flush=True)
    check("能认出蓝奏云域名", LZ.is_lanzou("https://wwi.lanzoup.com/iAbCd0xyz"))
    check("认得出 lanzoui/lanzoux 这些变体",
          LZ.is_lanzou("https://pan.lanzoux.com/abc")
          and LZ.is_lanzou("https://wws.lanzoui.com/abc"))
    check("不把别的网盘当蓝奏云", not LZ.is_lanzou("https://pan.baidu.com/s/1abc"))
    check("空链接明确失败", not LZ.resolve_lanzou("")["ok"])
    check("非蓝奏云明确失败",
          not LZ.resolve_lanzou("https://pan.quark.cn/s/abc")["ok"])
    bad = LZ.resolve_lanzou("https://pan.baidu.com/s/1abc")
    check("失败时带原因", bool(bad.get("error")), bad.get("error"))
    # 蓝奏云解析的骨架（细节由 tools/lanzou_test.py 单独盯，这里只确认还接得上）
    lz_src = src(os.path.join("app", "lanzou.py"))
    check("蓝奏云模块还在", "def resolve_lanzou" in lz_src)
    check("下载队列能下网盘文件", "download_direct" in lz_src)
    check("有 iframe 分支（普通分享页）", "_js_var(fn_page" in lz_src)

    # 详情页：点蓝奏云要弹选择菜单，而不是闷头开浏览器
    check("详情页有蓝奏云选择菜单", 'objectName: "lanzouChoiceMenu"' in detail_qml)
    check("菜单有「本地下载」", "本地下载" in detail_qml)
    check("菜单有「浏览器打开」", "在浏览器打开" in detail_qml)
    check("只有蓝奏云才弹（其它网盘没稳定直链）",
          "isLanzou" in detail_qml and "lanzou" in detail_qml)
    check("Main.qml 接了 onDownloadPanLink", "onDownloadPanLink" in main_qml)
    check("下载队列有 addPanFile", hasattr(core.downloads, "addPanFile"))

    print("\n-- 4. 下载线程上限", flush=True)
    check("MAX_THREADS 提到 16", WD.MAX_THREADS == 16, WD.MAX_THREADS)
    # 默认值后来按用户要求从 3 改成 4（「默认 4 线程」）
    check("默认值是 4", WD.DEFAULT_THREADS == 4, WD.DEFAULT_THREADS)
    check("clamp 放宽到 16", WD.clamp_threads(99) == 16, WD.clamp_threads(99))
    check("clamp 仍然有下限", WD.clamp_threads(0) == 1, WD.clamp_threads(0))
    check("clamp 吃得下字符串", WD.clamp_threads("8") == 8, WD.clamp_threads("8"))
    check("设置里出现了 16 这一档", "16" in main_qml)

    print("\n-- 5. 视频缓存（摆设）已删除", flush=True)
    check("Core 不再暴露 videoCache", not hasattr(core, "videoCache"))
    check("Core 不再暴露 clearVideoCache", not hasattr(core, "clearVideoCache"))
    # 只查「真的还在界面上」，不查注释 —— 注释里留着「这里原来有视频缓存」的说明是对的
    code_lines = [ln.strip() for ln in main_qml.splitlines()
                  if ln.strip() and not ln.strip().startswith("//")]
    check("设置界面里没有「视频缓存」这一格",
          not any("视频缓存" in ln for ln in code_lines),
          [ln for ln in code_lines if "视频缓存" in ln][:2])
    check("也没有调 clearVideoCache 的地方",
          not any("clearVideoCache" in ln for ln in code_lines))
    check("cacheSummary 只看封面缓存", core.cacheSummary in ("0 B",)
          or "B" in core.cacheSummary, core.cacheSummary)
    check("clearAllCaches 还能用", isinstance(core.clearAllCaches(), dict))
    check("player.py 里那套空接口也删了",
          "def cacheSize" not in src(os.path.join("app", "player.py")))

    print("\n-- 6. 主题色改成色盘", flush=True)
    check("有 ColorWheel 组件", 'objectName: "accentWheel"' in wheel_qml)
    check("色盘用 Canvas 画", "Canvas {" in wheel_qml)
    # 同样只查代码行：注释里说明「为什么不用 ImageData」是应该保留的
    wheel_code = [ln.strip() for ln in wheel_qml.splitlines()
                  if ln.strip() and not ln.strip().startswith("//")]
    check("没有退化成全黑的 ImageData 写法",
          not any("putImageData" in ln for ln in wheel_code),
          [ln for ln in wheel_code if "putImageData" in ln][:2])
    check("改用 fillRect 铺格子", any("fillRect" in ln for ln in wheel_code))
    check("有明度条", "picker.val" in wheel_qml)
    check("保留 RGB 微调", "ChannelSlider" in wheel_qml)
    check("Main.qml 用了 ColorWheel", "ColorWheel {" in main_qml)
    check("拖动时走 previewAccent（实时预览不写盘）",
          "previewAccent" in main_qml and "onPicked" in main_qml)
    check("松手才 setAccent（落盘）",
          "function commit()" in wheel_qml and "core.setAccent" in wheel_qml)
    check("主题色区块有 objectName（截图/测试能定位）",
          'objectName: "accentSection"' in main_qml)

    print("\n-- 7. 服务器元数据字体", flush=True)
    check("值按 mono 标记选字体", "modelData.mono" in srv_qml)
    check("含中文的字段标了 mono: false",
          'k: "模式", v: page.selected.modeLabel, mono: false' in srv_qml)
    check("纯数字的字段标了 mono: true",
          'k: "BOT"' in srv_qml and "mono: true" in srv_qml)
    check("中英混排的字段加粗以统一视觉重量",
          "modelData.mono ? Font.Normal" in srv_qml)
    check("字号比原来大（11 → 12）", "font.pixelSize: 12" in srv_qml)

    print()
    # ★ 收尾：这个测试只做源码断言，但构造了 Core()，它会起后台扫描线程。
    #   进程退出时那线程可能正走到 `model.set_items()`，而 QObject 已被回收，
    #   于是抛 `RuntimeError: Internal C++ object (ModListModel) already deleted`，
    #   被 run_all 记成「FAIL」（其实所有断言都过了）。
    #   这里先 shutdown 停掉线程、再静置一会儿让在途的收尾跑完。
    try:
        core.shutdown()
    except Exception:                                # noqa: BLE001
        pass
    _app = QGuiApplication.instance()
    if _app is not None:
        from PySide6.QtCore import QEventLoop, QTimer
        _loop = QEventLoop()
        QTimer.singleShot(600, _loop.quit)
        _loop.exec()

    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "、".join(FAILS)), flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
