"""外观三件套自检：夜间 / 日间 / 跟随系统 + 背景图单文件语义 + 分享 + MOD 日期筛选。

跑法：python -X utf8 tools/theme_test.py
"""
from __future__ import annotations

# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import datetime as _dt
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

import shutil
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
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def spin(app, ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    for _ in range(3):
        app.processEvents()


def make_img(path: str, color: str, fmt: str) -> str:
    im = QImage(60, 40, QImage.Format_RGB32)
    im.fill(QColor(color))
    assert im.save(path, fmt), f"造图失败 {path}"
    return path


def main() -> int:
    app = QGuiApplication(sys.argv[:1])

    from app import appearance as A
    from app import wallpaper as W
    from app.core import Core
    from app.util import BG_DIR, ROOT

    core = Core(app)

    # ---------------------------------------------------------------- 1. 外观
    print("=== 1. 外观模式（默认跟随系统）===")
    # 沙盒的 config 是从用户真实配置拷来的，用户可能已经选了夜间/日间。
    # 所以先显式恢复「跟随系统」，再验证「默认」这一项。
    core.setAppearance("system")
    check("恢复后是跟随系统", core.appearance == "system", core.appearance)
    check("followsSystem = True", core.followsSystem is True)
    check("标签是「跟随系统」", core.appearanceLabel == "跟随系统", core.appearanceLabel)

    core.setAppearance("light")
    check("日间 → isDark=False", core.isDark is False)
    core.setAppearance("dark")
    check("夜间 → isDark=True", core.isDark is True)
    core.setAppearance("system")
    check("跟随系统时不报错", core.appearance == "system")
    # 跟随系统的结果要跟「系统偏好」一致
    expected_dark = A.resolve_is_dark("system")
    check("跟随系统的结果和系统偏好一致", core.isDark == expected_dark,
          f"isDark={core.isDark} 系统={core.systemThemeLabel}")

    core.setAppearance("nonsense")
    check("非法值回落跟随系统", core.appearance == "system", core.appearance)
    check("normalize_mode 容错", A.normalize_mode("LIGHT") == "light")
    check("resolve_is_dark 夜里恒 True", A.resolve_is_dark("dark", style_hints_light=True) is True)
    check("resolve_is_dark 日间恒 False", A.resolve_is_dark("light", style_hints_light=False) is False)
    check("跟随系统听 styleHints", A.resolve_is_dark("system", style_hints_light=False) is True)

    # ---------------------------------------------------------------- 2. 背景图
    print("=== 2. 背景图：只留一个 background.* ===")
    tmp = tempfile.mkdtemp(prefix="l4d2_bg_")
    p_png = make_img(os.path.join(tmp, "a.png"), "#224466", "PNG")
    r1 = W.import_background(p_png)
    check("导入成 background.png", r1.get("name") == "background.png", str(r1.get("name")))
    check("目录里只有它一个", len(W.list_backgrounds()) == 1)

    p_jpg = make_img(os.path.join(tmp, "b.jpg"), "#662244", "JPG")
    r2 = W.import_background(p_jpg)
    check("再导入覆盖成 background.jpg", r2.get("name") == "background.jpg", str(r2.get("name")))
    check("旧扩展名被清掉（不会两张）",
          not os.path.isfile(os.path.join(BG_DIR, "background.png")))
    check("仍然只有一个", len(W.list_backgrounds()) == 1)

    check("resolve 认 background.jpg", bool(W.resolve_bg_path("background.jpg")))
    check("resolve 不认别的名字", W.resolve_bg_path("whatever.png") == "")
    check("current_bg_path 指向它",
          os.path.basename(W.current_bg_path()) == "background.jpg")

    # 移除 = 真删
    rm = W.remove_background()
    check("remove 报成功", bool(rm.get("ok")))
    check("remove 真的删了文件", not os.path.isfile(os.path.join(BG_DIR, "background.jpg")))
    check("remove 后 current 为空", W.current_bg_path() == "")
    check("remove 后配置也清空（走 core）",
          core.bgImageName == "", core.bgImageName)

    # 老配置迁移
    legacy = make_img(os.path.join(BG_DIR, "old_name.jpg"), "#333333", "JPG")
    mig = W.migrate_legacy("old_name.jpg")
    check("老文件名被迁移", mig.get("migrated") is True, str(mig))
    check("迁移成 background.jpg",
          os.path.isfile(os.path.join(BG_DIR, "background.jpg")))
    check("老文件不在了", not os.path.isfile(legacy))
    W.remove_background()

    # ---------------------------------------------------------------- 3. 分享
    print("=== 3. 分享视频 ===")
    video = {
        "bvid": "BV1xx411c7mD",
        "title": "【求生之路2】测试标题",
        "links": [
            {"name": "百度网盘", "url": "https://pan.baidu.com/s/1abc",
             "code": "6sg4", "label": "AK47和三连发"},
            {"name": "爱发电", "url": "https://ifdian.net/a/xx", "code": "", "label": ""},
        ],
        "commentLinks": [
            {"name": "夸克网盘", "url": "https://pan.quark.cn/s/xyz", "code": "5jiy", "label": ""},
        ],
    }
    text = core.shareText(video)
    check("含标题", "【求生之路2】测试标题" in text)
    check("含视频链接", "https://www.bilibili.com/video/BV1xx411c7mD" in text)
    check("含百度网盘", "https://pan.baidu.com/s/1abc" in text)
    check("含百度提取码", "6sg4" in text)
    check("含评论里的夸克网盘", "https://pan.quark.cn/s/xyz" in text)
    check("含夸克提取码", "5jiy" in text)
    # 爱发电本来就没有提取码，那一行不该冒出「提取码」三个字
    afdian_line = next((ln for ln in text.splitlines() if "ifdian.net" in ln), "")
    check("爱发电行没有提取码", "提取码" not in afdian_line, afdian_line[:60])

    core.shareVideo(video)
    clip = QGuiApplication.clipboard().text()
    check("分享真的进了剪贴板", clip == text, clip[:40].replace("\n", "|"))
    check("重复网盘不会出现两次", text.count("pan.baidu.com/s/1abc") == 1)

    bare = {"bvid": "BV1yy", "title": "只有标题"}
    core.shareVideo(bare)
    check("没网盘时就是标题+链接",
          QGuiApplication.clipboard().text() == "只有标题\nhttps://www.bilibili.com/video/BV1yy")

    # ---------------------------------------------------------------- 4. MOD 日期筛选
    print("=== 4. MOD 按导入日期筛选 + 最近导入排序 ===")
    mgr = core.mods
    now = time.time()

    def mk(name: str, days_ago: float) -> dict:
        ts = int(now - days_ago * 86400)
        return {
            "path": "C:/fake/" + name, "name": name, "stem": name.rsplit(".", 1)[0],
            "title": name, "enabled": True, "size": 1024 * 1024, "importTs": ts,
            "importText": _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
            "category": "other", "categoryLabel": "其他", "hasImage": True,
            "inWorkshopDir": False, "favorited": False, "hasUpdate": False,
            "checked": False,
        }

    mgr._all_local = [mk("a.vpk", 0.5), mk("b.vpk", 3), mk("c.vpk", 10), mk("d.vpk", 100)]
    mgr._all_workshop = []
    # ★ 先把所有筛选重置干净再测。
    #   这些筛选状态是**跨重启记住**的（存在 config.json 里），
    #   上一次手动点过「只看收藏」之类的，下次跑测试 `_status_filter` 就是 4，
    #   假数据里 favorited 全是 False → 全被过滤掉 → totalCount 恒为 0，
    #   看起来像程序坏了，其实是测试环境脏了。
    mgr.setStatusFilter(0)
    mgr.setCategory("")
    mgr.setFilter("")
    mgr.setSizeRange(0.0, 0.0)
    mgr.setImportDays(0)
    mgr.setImportRange("", "")
    mgr._apply_filter()
    check("先看到全部 4 个", mgr.totalCount == 4, str(mgr.totalCount))

    for days, expect in ((1, 1), (7, 2), (30, 3), (180, 4)):
        mgr.setImportDays(days)
        check(f"近 {days} 天 → {expect} 个", mgr.totalCount == expect, str(mgr.totalCount))
    check("筛选标签正确", mgr.importFilterLabel == "近 180 天", mgr.importFilterLabel)
    mgr.setImportDays(0)
    check("不限 → 全部", mgr.totalCount == 4)

    today = _dt.date.today()
    start = (today - _dt.timedelta(days=5)).isoformat()
    mgr.setImportRange(start, today.isoformat())
    check("自定义区间筛出 2 个", mgr.totalCount == 2, str(mgr.totalCount))
    mgr.setImportRange(today.isoformat(), start)
    check("区间反了会自动纠正", (mgr.importFrom, mgr.importTo) == (start, today.isoformat()),
          f"{mgr.importFrom}~{mgr.importTo}")
    mgr.setImportRange("", today.isoformat())
    check("只填结束 = 截至那天", mgr.totalCount == 4, str(mgr.totalCount))
    check("只填结束的标签", mgr.importFilterLabel.startswith("截至"), mgr.importFilterLabel)
    mgr.clearImportFilter()
    check("清掉筛选", not mgr.hasImportFilter and mgr.totalCount == 4)

    mgr.setSortMode(5)
    order = [m["title"] for m in mgr._all.items()]
    check("最近导入排序（新→旧）", order == ["a.vpk", "b.vpk", "c.vpk", "d.vpk"], str(order))
    mgr.resetFilters()
    mgr.setSortMode(0)

    # ---------------------------------------------------------------- 5. 详情刷新
    print("=== 5. 打开详情会刷新简介和置顶评论 ===")
    bvid = "BV1detailtest"
    core.library.videos[bvid] = {
        "bvid": bvid, "aid": 123, "title": "旧标题", "desc": "旧的简介内容",
        "detail_loaded": True,
        "topComment": {"text": "旧的置顶评论", "user": "a", "like": 1},
        "is_new": False, "discovered_at": time.time(),
    }
    core.library.save()

    class _FakeClient:
        """假装 B 站返回了改过的简介和新置顶评论。"""

        def video_detail(self, b: str) -> dict:
            return {
                "bvid": b, "aid": 123, "title": "旧标题", "desc": "新的简介内容",
                "author": "up", "mid": 1, "cover": "", "pubdate": 0, "views": 1,
                "danmaku": 0, "reply": 0, "favorite": 0, "coin": 0, "like": 0,
                "share": 0, "url": "", "duration": 1, "tname": "", "pages": 1,
            }

        def top_comment(self, aid: int, bvid: str = "") -> dict:
            return {"text": "新的置顶评论", "user": "b", "like": 9}

        def download_cover(self, url: str, bvid: str) -> str:
            return ""

    core.client = _FakeClient()
    pushes: list[dict] = []
    core.detailReady.connect(lambda v: pushes.append(v))
    core.openDetail(bvid)
    for _ in range(60):
        app.processEvents()
        QEventLoop()
        QTimer.singleShot(50, lambda: None)
        spin(app, 50)
        if len(pushes) >= 2:
            break
    check("先推缓存、再推新内容（共 2 次）", len(pushes) >= 2, f"{len(pushes)} 次")
    if pushes:
        check("第一次见到的是旧内容", pushes[0].get("desc") == "旧的简介内容")
    last = pushes[-1] if pushes else {}
    check("简介刷新成新的", last.get("desc") == "新的简介内容", str(last.get("desc"))[:30])
    check("置顶评论刷新成新的",
          (last.get("topComment") or {}).get("text") == "新的置顶评论",
          str((last.get("topComment") or {}).get("text")))
    # 关掉详情后就不该再推了
    core.clearDetail()
    pushes.clear()
    core.openDetail(bvid)
    spin(app, 300)
    core.clearDetail()
    before = len(pushes)
    spin(app, 300)
    check("关掉详情后不再推更新", len(pushes) == before, f"{before} -> {len(pushes)}")

    # ---------------------------------------------------------------- 6. QML
    print("=== 6. QML：Theme 真的跟着切 ===")
    engine = QQmlApplicationEngine()
    warns: list[str] = []
    engine.warnings.connect(lambda ws: warns.extend(w.toString() for w in ws))
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.addImportPath(os.path.join(ROOT, "qml", "components"))
    engine.rootContext().setContextProperty("core", core)
    engine.load(os.path.join(ROOT, "qml", "Main.qml"))
    roots = engine.rootObjects()
    check("QML 加载", len(roots) == 1)
    if roots:
        win = roots[0]
        theme = win.findChild(type(win), "")  # 占位，下面用属性读
        spin(app, 400)

        def eval_qml(expr_text: str):
            # QQmlExpression.evaluate() 返回 (值, 是否未定义) 二元组，取第一个。
            from PySide6.QtQml import QQmlEngine, QQmlExpression
            expr = QQmlExpression(QQmlEngine.contextForObject(win), win, expr_text)
            value, undefined = expr.evaluate()
            return None if undefined else value

        def theme_dark() -> bool:
            return bool(eval_qml("Theme.dark"))

        core.setAppearance("light")
        spin(app, 300)
        check("切日间后 Theme.dark=False", theme_dark() is False)
        core.setAppearance("dark")
        spin(app, 300)
        check("切夜间后 Theme.dark=True", theme_dark() is True)

        # 背景色也跟着换（不是只有开关变了）
        dark_bg = eval_qml("Theme.bg")
        core.setAppearance("light")
        spin(app, 300)
        light_bg = eval_qml("Theme.bg")
        check("日间底色和夜间底色不同",
              dark_bg.name().upper() != light_bg.name().upper(),
              f"{dark_bg.name()} vs {light_bg.name()}")
        # 浅色主题的文字必须深、深色主题的文字必须浅，否则整片糊成一体
        core.setAppearance("light")
        spin(app, 250)
        light_text = eval_qml("Theme.text")
        check("日间文字是深色", light_text.lightnessF() < 0.5,
              f"lightness={light_text.lightnessF():.2f}")
        core.setAppearance("dark")
        spin(app, 250)
        dark_text = eval_qml("Theme.text")
        check("夜间文字是浅色", dark_text.lightnessF() > 0.5,
              f"lightness={dark_text.lightnessF():.2f}")

        # 滚动渐隐遮罩：以前写死成深色，日间模式里列表顶上会横一道黑杠。
        # 现在跟背景色走，所以日间的渐隐应该是「浅色」，夜间的应该是「深色」。
        core.setAppearance("light")
        spin(app, 250)
        light_fade = eval_qml("Theme.fade(1.0)")
        check("日间渐隐是浅色（不会出现黑杠）", light_fade.lightnessF() > 0.5,
              f"lightness={light_fade.lightnessF():.2f}")
        core.setAppearance("dark")
        spin(app, 250)
        dark_fade = eval_qml("Theme.fade(1.0)")
        check("夜间渐隐是深色", dark_fade.lightnessF() < 0.5,
              f"lightness={dark_fade.lightnessF():.2f}")
        # 渐隐的底色要和背景色系一致，而不是纯黑
        check("渐隐颜色跟背景走（不等于纯黑）",
              eval_qml("Theme.fadeSolid").lightnessF()
              == eval_qml("Theme.bg").lightnessF(),
              f"{eval_qml('Theme.fadeSolid').name()} vs {eval_qml('Theme.bg').name()}")

        # 日间模式下的深色叠层不能太重：详情面板左侧那道阴影在浅色底上
        # 用 0.45 的黑会糊成一条很脏的灰边（用户截图里红框那条）。
        # 这里直接验证两套主题下 scrim 的方向是相反的。
        core.setAppearance("light")
        spin(app, 250)
        light_scrim = eval_qml("Theme.scrim(0.10)")
        check("日间 scrim 是压暗（不是提亮）", light_scrim.lightnessF() < 0.05,
              f"lightness={light_scrim.lightnessF():.3f}")
        core.setAppearance("dark")
        spin(app, 250)
        dark_scrim = eval_qml("Theme.scrim(0.10)")
        check("夜间 scrim 是提亮", dark_scrim.lightnessF() > 0.95,
              f"lightness={dark_scrim.lightnessF():.3f}")

        # 按钮的 hover / 按下色必须跟着主题色走（以前写死了红色，
        # 用户把主题改成蓝色后按下去还是红的）。
        core.setAccent(0xFF, 0x4D, 0x57)      # 红
        spin(app, 200)
        red_hover = eval_qml("Theme.accentHover")
        red_press = eval_qml("Theme.accentPress")
        core.setAccent(0x4D, 0x8C, 0xFF)      # 蓝
        spin(app, 200)
        blue_hover = eval_qml("Theme.accentHover")
        blue_press = eval_qml("Theme.accentPress")
        check("换主题色后 hover 色跟着变",
              red_hover.name().upper() != blue_hover.name().upper(),
              f"{red_hover.name()} vs {blue_hover.name()}")
        check("换主题色后按下色跟着变",
              red_press.name().upper() != blue_press.name().upper(),
              f"{red_press.name()} vs {blue_press.name()}")
        # 蓝色主题下按下色不该是红的（红通道不该占主导）
        check("蓝色主题下按下色偏蓝不偏红",
              blue_press.blue() > blue_press.red(),
              f"r={blue_press.red():.2f} b={blue_press.blue():.2f}")
        core.resetAccent()
        spin(app, 200)

        bad = [w for w in warns if any(k in w for k in (
            "TypeError", "not defined", "is not a type", "Unable", "ReferenceError",
            "Duplicate", "Binding loop", "is not a function", "Cannot assign",
            "Required property"))]
        check("QML 无可疑告警", not bad, f"{len(warns)} 条原始告警")
        for b in bad[:4]:
            print("      !", b[:170])

    shutil.rmtree(tmp, ignore_errors=True)
    core.shutdown()

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
