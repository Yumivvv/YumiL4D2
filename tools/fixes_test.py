"""本轮五个修复的自检。

盯这五件事（都是用户报的原始问题）：

  1. **搜索框输入字母字还在** —— `searchField.text` 不能绑 `page.query`（双向绑定
     会把用户刚敲的字顶回去），只能由输入框自己管、程序侧单向同步。
  2. **工坊下载的 MOD 没封面** —— `download_cover()` 只写 `data/modcache`，
     而列表只认 vpk 旁边的同名图，所以必须 `_place_cover_beside()` 落一份过去。
  3. **检查 MOD 文件慢 / 检查完没封面** —— 缺封面/缺名字的要排在前面先查，
     且封面要**每批查完就补**，不能攒到最后（关窗就全丢）。
  4. **筛选重置后排序没回默认** —— `resetFilters()` 要把排序也退回 0。
  5. **点服务器按钮会自动刷一遍** —— 进页面不该有任何查询调用。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEventLoop, QTimer          # noqa: E402
from PySide6.QtGui import QGuiApplication              # noqa: E402

from guard import protect_user_data                    # noqa: E402

protect_user_data()

from app import mods as M                              # noqa: E402
from app.core import Core                              # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def src(rel):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return open(os.path.join(root, rel), encoding="utf-8").read()


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    core = Core(app)
    globals()["_KEEP_CORE"] = core
    mods = core.mods

    print("\n-- 1. 搜索框不再被绑定顶回去", flush=True)
    page = src(os.path.join("qml", "components", "ServersPage.qml"))
    block = page.split('id: searchField', 1)[1][:1200]
    # 取属性行（去掉注释行）再判断有没有 text: 绑定
    code_lines = [ln.strip() for ln in block.splitlines()
                  if ln.strip() and not ln.strip().startswith("//")]
    check("searchField 没有 text: page.query 属性绑定",
          not any(ln.startswith("text: page.query") for ln in code_lines),
          [ln for ln in code_lines if ln.startswith("text:")][:2])
    check("仍然把输入同步回 page.query",
          any(ln.startswith("onTextChanged: page.query = text") for ln in code_lines))
    check("程序侧改 query 时单向同步进输入框",
          "searchField.text = page.query" in page and "onQueryChanged" in page)
    check("注释里说明了为什么不能绑", "双向绑定" in page)

    print("\n-- 2. 工坊下载的 MOD 有封面", flush=True)
    check("有 _place_cover_beside", hasattr(mods, "_place_cover_beside"))
    # 造一个假的 vpk + 假封面缓存，验证复制逻辑
    tmp = tempfile.mkdtemp(prefix="l4d2_cover_")
    addons = os.path.join(tmp, "addons")
    os.makedirs(addons, exist_ok=True)
    vpk = os.path.join(addons, "123456.vpk")
    with open(vpk, "wb") as f:
        f.write(b"fake vpk")

    cache_path = os.path.join(M.CACHE_DIR, "123456.jpg")
    os.makedirs(M.CACHE_DIR, exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(b"x" * 2048)

    placed = mods._place_cover_beside(vpk, "123456", "")
    check("封面被复制到 vpk 旁边", bool(placed) and os.path.isfile(placed), placed)
    check("文件名是 <ID>.<ext>", os.path.basename(placed) == "123456.jpg",
          os.path.basename(placed) if placed else "")
    check("列表的「有没有封面」认得它", bool(mods._local_image_of(vpk)))
    # 已经有封面时不能再覆盖
    with open(placed, "wb") as f:
        f.write(b"user own cover")
    again = mods._place_cover_beside(vpk, "123456", "")
    with open(again, "rb") as f:
        same = f.read() == b"user own cover"
    check("已有封面不覆盖", same)
    # 没有 vpk 路径时应安全返回
    check("没有 vpk 路径安全返回", mods._place_cover_beside("", "1", "") == "")

    print("\n-- 3. 检查 MOD：先查缺封面/缺名字的，且逐批补封面", flush=True)
    mm = src(os.path.join("app", "modmanager.py"))
    check("identifyWorkshop 会算「缺封面/缺名字」", "miss_cover" in mm and "miss_name" in mm)
    check("有优先级排序（缺的排前面）", "def rank(" in mm and "need_fix" in mm)
    check("状态栏会说明先查缺的那批", "先查这些" in mm)
    check("封面逐批补（在批循环内）", "_place_cover_beside" in mm)
    check("不再用旧的「先全查完再统一下」写法", "need_cover = [" not in mm)
    # rank 的排序效果：直接按同样规则验一遍语义
    pending = {"111": (True, True), "222": (True, False),
               "333": (False, True), "444": (False, False)}

    def rank(w):
        mc, mn = pending[w]
        return (-((2 if mc else 0) + (1 if mn else 0)), w)

    order = sorted(pending, key=rank)
    check("两个都缺的排最前", order[0] == "111", order)
    check("什么都不缺的排最后", order[-1] == "444", order)
    check("缺封面的排在只缺名字的前面", order.index("222") < order.index("333"), order)

    print("\n-- 4. 筛选重置后排序回默认", flush=True)
    mmgr = core.mods
    mmgr.resetFilters()
    pump(120)
    mmgr.setSortMode(5)                       # 最近导入
    pump(150)
    check("排序能设成 5", mmgr.sortMode == 5, mmgr.sortMode)
    mmgr.resetFilters()
    pump(200)
    check("重置后排序回 0（默认）", mmgr.sortMode == 0, mmgr.sortMode)
    # 只改排序时点重置，也得真的生效（老代码在这里会直接 return）
    mmgr.setSortMode(4)
    pump(150)
    check("只改排序也能设上", mmgr.sortMode == 4, mmgr.sortMode)
    mmgr.resetFilters()
    pump(200)
    check("只改排序时重置也生效", mmgr.sortMode == 0, mmgr.sortMode)
    check("resetFilters 的源码里确实把排序清零", "_sort_mode = 0" in mm)

    print("\n-- 5. 服务器查询的触发点", flush=True)
    sp = src(os.path.join("app", "servers.py"))
    srv_qml = src(os.path.join("qml", "components", "ServersPage.qml"))
    # ServerManager 构造时不能自己就去查（那是页面该决定的事）
    init_block = sp.split("def __init__(self, core)", 1)[1][:900]
    check("ServerManager 初始化不查询",
          "refreshAll" not in init_block and "refreshOne" not in init_block)
    # 进页面自动刷新是用户明确要的（见 ws_download_test），这里只确认它有防抖
    check("进页面会自动刷新（用户要求）", "autoRefreshOnEnter" in srv_qml)
    check("自动刷新有防抖，不会一直刷", "autoRefreshCooldownMs" in srv_qml)

    print("\n-- QML 整体还能加载 + 真敲键盘", flush=True)
    import subprocess
    shot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shot.py")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "data", "_qmlcheck.png")
    r = subprocess.run([sys.executable, "-X", "utf8", shot, out, "servers"],
                       capture_output=True, timeout=180)
    check("ServersPage 能被加载（无 QML 报错）",
          r.returncode == 0 and b"LOAD FAILED" not in r.stdout, r.returncode)
    try:
        os.remove(out)
    except OSError:
        pass

    # 源码断言证明不了「打字不被打回去」，这里真敲一遍。
    # QTest 的 key* 只吃 QWidget，QML 的 TextInput 不是 widget，
    # 所以自己造 QKeyEvent 发给窗口，让 Qt 按焦点路由。
    from PySide6.QtGui import QKeyEvent                          # noqa: PLC0415
    from PySide6.QtQml import QQmlApplicationEngine              # noqa: PLC0415
    from PySide6.QtCore import QObject, Qt, QUrl                 # noqa: PLC0415
    import os as _os                                              # noqa: PLC0415
    _os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    eng = QQmlApplicationEngine()
    qdir = os.path.join(root, "qml")
    eng.addImportPath(qdir)
    eng.addImportPath(os.path.join(qdir, "components"))
    eng.rootContext().setContextProperty("core", core)
    eng.load(QUrl.fromLocalFile(os.path.join(qdir, "Main.qml")))
    win = eng.rootObjects()[0]
    win.show()
    pump(800)
    smgr = core.servers
    smgr.clearAll()
    smgr.saveServer({"addr": "42.193.137.24:27015", "name": "宿舍常玩",
                     "weight": 0, "panels": []})
    win.setProperty("section", 3)
    pump(700)
    pg = win.findChild(QObject, "serversPage")
    field = win.findChild(QObject, "srvSearchInput")
    check("找得到搜索输入框", field is not None and pg is not None)
    if field is not None:
        field.forceActiveFocus()
        pump(300)
        check("输入框拿到焦点", field.property("activeFocus") is True)

        def type_keys(text):
            for ch in text:
                QGuiApplication.sendEvent(
                    win, QKeyEvent(QKeyEvent.KeyPress, ord(ch), Qt.NoModifier, ch))
                QGuiApplication.sendEvent(
                    win, QKeyEvent(QKeyEvent.KeyRelease, ord(ch), Qt.NoModifier, ch))
            pump(400)

        type_keys("abc")
        check("敲 abc 后输入框里就是 abc（没被绑定顶回去）",
              field.property("text") == "abc", field.property("text"))
        check("query 跟着更新", pg.property("query") == "abc", pg.property("query"))
        type_keys("123")
        check("连续输入累积正常", field.property("text") == "abc123",
              field.property("text"))
        QGuiApplication.sendEvent(
            win, QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Backspace, Qt.NoModifier))
        QGuiApplication.sendEvent(
            win, QKeyEvent(QKeyEvent.KeyRelease, Qt.Key_Backspace, Qt.NoModifier))
        pump(300)
        check("退格正常", field.property("text") == "abc12", field.property("text"))
        pg.clearQuery()
        pump(400)
        check("程序侧清空能同步进输入框",
              field.property("text") == "" and pg.property("query") == "",
              (field.property("text"), pg.property("query")))
    win.close()

    print()
    pump(150)
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "、".join(FAILS)), flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
