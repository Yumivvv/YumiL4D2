"""综合回归：页面切换 / 悬浮 / 作者卡片 / 全选 / 导入确认."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 测试会构造真的 Core()，必须先把运行时数据目录隔离到临时沙盒，
# 否则会覆盖用户真实的 config.json / library.json / 导入日期台账。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from guard import protect_user_data  # noqa: E402
protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app import mods as _mods
from app.core import Core
from app.util import ROOT

# 导入会写「导入日期」台账（data/modimports.json）。测试必须写临时文件，
# 否则会把用户真实的导入时间覆盖掉、还留下一堆假 ID（999 / 777 这些）。
_LEDGER_DIR = tempfile.mkdtemp(prefix="l4d2_ledger_")
_mods.IMPORT_LEDGER_PATH = os.path.join(_LEDGER_DIR, "modimports.json")


def log(*a):
    print(*a, flush=True)


app = QGuiApplication(sys.argv[:1])
engine = QQmlApplicationEngine()
q = os.path.join(ROOT, "qml")
engine.addImportPath(q)
engine.addImportPath(os.path.join(q, "components"))

core = Core(app)
engine.rootContext().setContextProperty("core", core)
engine.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))

if not engine.rootObjects():
    log("LOAD FAILED")
    sys.exit(1)

win = engine.rootObjects()[0]
win.show()
mgr = core.mods


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run():
    wait(3500)

    log("=== 1. 页面切换 & 高亮 ===")
    win.setProperty("section", 1)
    wait(250)
    log("  section =", win.property("section"), "(视频导航不应再高亮)")
    win.setProperty("section", 0)
    win.setProperty("page", 0)
    wait(250)
    log("  回到视频页 section =", win.property("section"), "page =", win.property("page"))
    assert win.property("section") == 0

    log()
    log("=== 2. 作者卡片 ===")
    items = core.library.all_items()
    target = None
    for v in items:
        if int(v.get("mid") or 0) > 0:
            target = v
            break
    log("  目标视频:", (target or {}).get("title", "")[:30])

    got = {"info": None}

    def on_author(info):
        got["info"] = info

    core.authorReady.connect(on_author)
    if target:
        core.openAuthor(target["bvid"])
        for _ in range(40):
            wait(500)
            if got["info"]:
                break
        info = got["info"] or {}
        log("  昵称:", info.get("name"))
        log("  粉丝:", info.get("fans"))
        log("  签名:", (info.get("sign") or "")[:30])
        log("  近期视频:", len(info.get("videos") or []))
        log("  主页:", info.get("spaceUrl"))
        assert info.get("name"), "作者名称为空"
        if info.get("videos"):
            log("  近期视频 ok")
        else:
            log("  [warn] space / 动态 / 昵称搜索三路这次都没返回视频（B 站风控或限流），跳过该断言")

    log()
    log("=== 3. MOD 全选 ===")
    mgr.checkAllLocal(True)
    wait(150)
    log("  checkedCount =", mgr.checkedCount, " allChecked =", mgr.allChecked)
    assert mgr.checkedCount == mgr.totalCount
    assert mgr.allChecked

    log()
    log("=== 4. 拖拽导入确认流程（模拟）===")
    log("  pendingImport 初始:", win.property("section"))
    # 模拟一次导入到临时目录（不动真实 addons）
    import tempfile, shutil
    from app.mods import import_files

    tmp = tempfile.mkdtemp(prefix="l4d2_imp_")
    src = os.path.join(tmp, "src"); os.makedirs(src)
    dst = os.path.join(tmp, "addons"); os.makedirs(dst)
    vpk = os.path.join(src, "999.vpk"); open(vpk, "wb").write(b"x" * 1000)
    open(os.path.join(src, "999.jpg"), "wb").write(b"i" * 500)
    res = import_files([vpk], dst)
    log("  导入结果 copied:", res["copied"])
    assert "999.vpk" in res["copied"] and "999.jpg" in res["copied"]
    log("  -> 同名图片自动带上 OK")
    shutil.rmtree(tmp, ignore_errors=True)

    log()
    log("=== 5. 批量启用/禁用（沙盒）===")
    from app.mods import set_enabled
    tmp2 = tempfile.mkdtemp(prefix="l4d2_en_")
    p1 = os.path.join(tmp2, "111.vpk"); open(p1, "wb").write(b"x")
    p2 = set_enabled({"path": p1}, False)
    log("  禁用后:", os.path.basename(p2))
    p3 = set_enabled({"path": p2}, True)
    log("  启用后:", os.path.basename(p3))
    assert p3.endswith(".vpk")
    shutil.rmtree(tmp2, ignore_errors=True)

    log()
    log("=== 6. MOD 筛选面板（开 / 关 / Esc）===")
    win.setProperty("section", 1)
    wait(1600)
    mgr.resetFilters()
    wait(120)
    total = mgr.totalCount
    assert total > 0, "本地 mod 一个都没有，先检查 addons 目录"
    assert mgr.hiddenCount == 0, f"没筛选不该有隐藏项，hiddenCount={mgr.hiddenCount}"
    assert win.closeFilterPopup() is False, "没打开时关闭应当返回 False"

    win.openModFilter()
    wait(150)
    assert win.closeFilterPopup() is True, "打开后应当能关掉（Esc 走的就是这个）"
    wait(150)
    log("  打开 / 关闭 / 重复关闭 都符合预期")

    mgr.setSizeRange(1, 50)
    wait(150)
    shown = mgr.totalCount
    hidden = mgr.hiddenCount
    log(f"  1~50MB: 显示 {shown} / 挡住 {hidden}（共 {total}）")
    assert shown + hidden == total, "显示 + 挡住 应等于总数"
    assert 0 < shown < total, "这个区间应当只留下一部分"

    mgr.setStatusFilter(1)
    wait(150)
    log("  叠加只看已启用 -> 显示", mgr.totalCount, "挡住", mgr.hiddenCount)
    mgr.resetFilters()
    wait(150)
    assert mgr.totalCount == total and mgr.hiddenCount == 0
    assert mgr.hasExtraFilter is False
    log("  重置筛选后恢复全部")

    # 排序
    for mode in (0, 1, 2, 3, 4):
        mgr.setSortMode(mode)
        wait(120)
        assert mgr.sortMode == mode and mgr.totalCount == total, f"排序 {mode} 有问题"
    mgr.setSortMode(0)
    wait(120)
    log("  5 种排序模式都可用且不改变条数")

    # 检查而不跳顶
    order_before = [mgr.allModel.items()[i]["path"] for i in range(mgr.allModel.rowCount())]
    pick_path = order_before[3] if len(order_before) > 3 else order_before[0]
    mgr.selectMod(pick_path)
    wait(120)
    mgr._apply_meta_to_items()
    wait(120)
    order_after = [mgr.allModel.items()[i]["path"] for i in range(mgr.allModel.rowCount())]
    assert order_before == order_after, "刷新元数据后列表顺序变了（会跳回顶部）"
    assert mgr.selectedPath == pick_path, "刷新元数据后详情面板指着的 MOD 丢了"
    log("  刷新元数据后列表顺序不变、选中项不丢")

    # 可选更新判定
    upd_src = next((m for m in mgr.allModel.items() if m.get("updatedTs")), None)
    if upd_src:
        meta = mgr._wsc._meta
        old = mgr._decorate(
            {"path": upd_src["path"], "name": upd_src["name"], "stem": upd_src["stem"],
             "dir": os.path.dirname(upd_src["path"]), "size": upd_src["size"],
             "sizeText": upd_src["sizeText"],
             "mtime": int(upd_src["updatedTs"]) - 86400,
             "image": "", "workshopId": upd_src["workshopId"], "isWorkshop": True,
             "inWorkshopDir": False, "enabled": True}, meta, is_local=True)
        new = mgr._decorate(
            {"path": upd_src["path"], "name": upd_src["name"], "stem": upd_src["stem"],
             "dir": os.path.dirname(upd_src["path"]), "size": upd_src["size"],
             "sizeText": upd_src["sizeText"],
             "mtime": int(upd_src["updatedTs"]) + 86400,
             "image": "", "workshopId": upd_src["workshopId"], "isWorkshop": True,
             "inWorkshopDir": False, "enabled": True}, meta, is_local=True)
        assert old["hasUpdate"] is True, "工坊更新更晚时没判定为可更新"
        assert new["hasUpdate"] is False, "本地更新时不该判定为可更新"
        assert "updatable" in mgr.statusCounts, "状态统计里没有「可更新」"
        log("  可更新判定正确，statusCounts 里有 updatable")
    else:
        log("  [warn] 没有带工坊时间的 MOD，跳过可更新断言")

    log()
    log("=== 7. 提示音 / 本地封面跳过 / 勾选清空 / 详情收起 ===")
    from app.notifier import play_alert

    ok_sound = play_alert()
    log("  play_alert() ->", ok_sound)
    assert ok_sound, "提示音播放失败"

    # 自定义背景图：导入 / 设为背景 / 透明度夹取 / 移除（QML 图层接线见 tools/bg_test.py）
    from app.wallpaper import import_background, list_backgrounds, resolve_bg_path
    from app.util import BG_DIR
    from PySide6.QtGui import QColor, QImage

    tmp_bg = tempfile.mkdtemp(prefix="l4d2_bg_")
    png = os.path.join(tmp_bg, "regress_bg.png")
    _im = QImage(160, 100, QImage.Format_RGB32)
    _im.fill(QColor("#336699"))
    assert _im.save(png, "PNG"), "造测试背景图失败"
    res_bg = import_background(png)
    assert res_bg.get("ok"), "导入背景图失败：%r" % (res_bg,)
    bg_name = res_bg["name"]
    assert os.path.isfile(os.path.join(BG_DIR, bg_name)), "背景图没落到 backgrounds/"
    assert bg_name in [it["name"] for it in list_backgrounds()], "背景图列表里没有它"
    assert resolve_bg_path(bg_name), "resolve_bg_path 找不到背景图"
    assert not import_background(os.path.join(tmp_bg, "x.txt"))["ok"], "非图片该被拒绝"

    old_bg = str(core.config["bg_image"] or "")
    old_op = int(core.config["bg_opacity"])
    core.setBgImage(bg_name)
    wait(60)
    assert core.bgImageName == bg_name, core.bgImageName
    assert core.bgImageUrl.startswith("file://"), core.bgImageUrl
    core.previewBgOpacity(70)
    assert core.bgOpacity == 70
    core.setBgOpacity(999)
    assert core.bgOpacity == 100, core.bgOpacity
    core.setBgOpacity(-3)
    assert core.bgOpacity == 0, core.bgOpacity
    core.setBgOpacity(45)
    core.clearBgImage()
    wait(60)
    assert core.bgImageUrl == "", "移除后背景图 URL 不清空"
    log("  背景图：导入 / 切换 / 透明度 0-100 夹取 / 移除 都对")

    core.config["bg_image"] = old_bg
    core.config["bg_opacity"] = old_op
    core.config.save()
    try:
        os.remove(os.path.join(BG_DIR, bg_name))
    except OSError:
        pass
    import shutil as _shb
    _shb.rmtree(tmp_bg, ignore_errors=True)
    assert not os.path.isfile(os.path.join(BG_DIR, bg_name)), "背景图测试文件没删掉"
    log("  背景图测试文件已清理，配置已还原")

    with_cover = next(
        (m for m in mgr._all_local if m.get("workshopId") and m.get("hasImage")), None
    )
    if with_cover:
        wid = with_cover["workshopId"]
        log(f"  本地已有封面的 mod: {wid} -> _has_cover_locally = {mgr._has_cover_locally(wid)}")
        assert mgr._has_cover_locally(wid) is True, "本地有图却仍认为要下载"
        assert mgr._has_cover_locally("999999999999") is False
        log("  -> 本地有图时会跳过工坊封面下载")
    else:
        log("  [warn] 没有同时具备工坊 ID 和本地封面的 MOD，跳过该断言")

    # 批量操作后自动清空勾选（用临时 addons 目录，不动真实 MOD）
    tmp3 = tempfile.mkdtemp(prefix="l4d2_sel_")
    addons3 = os.path.join(tmp3, "left4dead2", "addons")
    os.makedirs(addons3)
    for n in ("aaa.vpk", "bbb.vpk", "ccc.vpk"):
        open(os.path.join(addons3, n), "wb").write(b"x" * 4096)
    saved_dir = mgr.addonsDir
    mgr.setAddonsDir(addons3)
    for _ in range(30):
        wait(200)
        if not mgr.busy and mgr.localCount == 3:
            break
    log("  临时 addons 目录 localCount =", mgr.localCount)
    assert mgr.localCount == 3, f"临时目录扫描结果不对：{mgr.localCount}"

    mgr.checkAllLocal(True)
    wait(120)
    assert mgr.checkedCount == 3
    mgr.setEnabledChecked(False)
    wait(250)
    names = sorted(os.listdir(addons3))
    log("  批量禁用后 checkedCount =", mgr.checkedCount, "文件名:", names)
    assert mgr.checkedCount == 0, "批量禁用后应当自动清空勾选（否则一直提示已选中）"
    assert all(n.endswith(".vpk.disabled") for n in names)

    mgr.checkAllLocal(True)
    mgr.setEnabledChecked(True)
    wait(250)
    names = sorted(os.listdir(addons3))
    log("  重新启用后文件名:", names)
    assert all(n.endswith(".vpk") and not n.endswith(".disabled") for n in names)

    mgr.setAddonsDir(saved_dir)
    for _ in range(30):
        wait(250)
        if not mgr.busy and mgr.localCount > 0:
            break
    shutil.rmtree(tmp3, ignore_errors=True)
    log("  已恢复真实目录:", mgr.addonsDir, "localCount =", mgr.localCount)
    assert mgr.localCount > 0

    # 详情面板：切页 / 切 MOD / 开设置都要收起
    win.setProperty("section", 1)
    wait(250)
    win.setProperty("detailOpen", True)
    wait(150)
    win.setProperty("page", 1)
    wait(250)
    log("  切页后 detailOpen =", win.property("detailOpen"))
    assert win.property("detailOpen") is False, "切页后详情面板应当收起"

    win.setProperty("section", 0)
    wait(250)
    win.setProperty("detailOpen", True)
    wait(150)
    win.setProperty("section", 1)
    wait(250)
    log("  切到 MOD 页后 detailOpen =", win.property("detailOpen"))
    assert win.property("detailOpen") is False, "切到 MOD 页后详情面板应当收起"

    win.setProperty("section", 0)
    wait(250)
    win.setProperty("detailOpen", True)
    wait(150)
    win.setProperty("settingsOpen", True)
    wait(300)
    log(
        "  打开设置后 detailOpen =",
        win.property("detailOpen"),
        " settingsOpen =",
        win.property("settingsOpen"),
    )
    assert win.property("detailOpen") is False, "打开设置时详情面板应当收起，不能堆叠"
    assert win.property("settingsOpen") is True
    win.setProperty("settingsOpen", False)
    wait(250)

    win.setProperty("settingsOpen", False)
    wait(250)

    log()
    log("=== 8. MOD 管理器新界面：状态 / 分类 / 详情 / 收藏 ===")
    win.setProperty("section", 1)
    wait(400)
    mgr.resetFilters()
    wait(200)

    counts = mgr.statusCounts
    log("  statusCounts =", dict(counts))
    assert counts.get("all", 0) == total, f"状态栏总数({counts.get('all')})应等于总数({total})"
    assert counts.get("all") == counts.get("enabled", 0) + counts.get("disabled", 0)
    assert counts.get("workshop", 0) == mgr.workshopCount

    cats = mgr.categoryCounts
    log("  categoryCounts =", [(c["label"], c["count"]) for c in cats])
    assert isinstance(cats, list) and len(cats) > 0, "分类列表不该为空"
    assert all(c["count"] > 0 for c in cats), "分类列表里不该有 0 个的分类"
    assert sum(c["count"] for c in cats) <= counts.get("all", 0)

    mgr.setStatusFilter(1)
    wait(150)
    assert mgr.totalCount == counts.get("enabled"), "只看已启用 数量不对"
    mgr.setStatusFilter(2)
    wait(150)
    assert mgr.totalCount == counts.get("disabled"), "只看未启用 数量不对"
    mgr.setStatusFilter(0)
    wait(150)
    assert mgr.totalCount == total
    log("  状态筛选 全部/已启用/未启用 都对")

    top = cats[0]
    mgr.setCategory(top["key"])
    wait(150)
    log(f"  分类「{top['label']}」-> 显示 {mgr.totalCount} / 挡住 {mgr.hiddenCount}")
    assert mgr.totalCount == top["count"], "分类筛选数量与侧边栏不一致"
    assert mgr.totalCount + mgr.hiddenCount == total
    mgr.resetFilters()
    wait(150)
    assert mgr.totalCount == total and mgr.categoryFilter == ""

    pick = next((m for m in mgr.allModel.items() if m.get("workshopId")), None)
    assert pick is not None, "找不到带工坊 ID 的 MOD"
    mgr.selectMod(pick["path"])
    wait(250)
    sel = mgr.selectedItem
    log(
        "  选中:", sel.get("title"),
        "| 分类", sel.get("categoryLabel"),
        "| 订阅", sel.get("subsText"),
        "| 作者", sel.get("author"),
    )
    for key in ("title", "sizeText", "categoryLabel", "path", "enabled",
                "favorited", "desc", "tags"):
        assert key in sel, f"详情字段缺失：{key}"
    assert sel.get("path") == pick["path"]
    assert mgr.selectedPath == pick["path"]

    # 收藏数按「相对初始值」判断：data/favorites.json 里可能本来就存着用户收藏
    fav_before = mgr.statusCounts.get("favorite", 0)
    mgr.toggleFavorite(pick["path"])
    wait(250)
    assert mgr.selectedItem.get("favorited") is True, "收藏没生效"
    assert mgr.statusCounts.get("favorite", 0) == fav_before + 1, "收藏计数没更新"
    mgr.setStatusFilter(4)
    wait(200)
    log(f"  我的收藏 -> {mgr.totalCount}（初始 {fav_before}，加 1 后）")
    assert mgr.totalCount >= 1 and mgr.totalCount <= total
    mgr.setStatusFilter(0)
    wait(200)
    mgr.toggleFavorite(pick["path"])
    wait(250)
    assert mgr.selectedItem.get("favorited") is False, "取消收藏没生效"
    assert mgr.statusCounts.get("favorite", 0) == fav_before, "取消收藏后计数没回去"

    from app import mods as M
    assert callable(getattr(M, "launch_game", None)), "缺少 launch_game"
    assert hasattr(mgr, "launchGame"), "ModManager 缺少 launchGame 槽"
    log("  launch_game / launchGame 都在（不真的启动游戏）")

    mgr.clearSelected()
    wait(200)
    log("  详情面板已关闭, selectedPath =", repr(mgr.selectedPath))
    assert mgr.selectedPath == "" and mgr.selectedItem == {}

    # ---------------------------------------------------------- 第 9 段
    log()
    log("=== 第 9 段：回收站 / 同名封面图 / 选择模式 ===")
    import tempfile
    from app import mods as M

    sandbox = tempfile.mkdtemp(prefix="l42d_rb_")
    vpk = os.path.join(sandbox, "469986973.vpk")
    img = os.path.join(sandbox, "469986973.JPG")
    keep = os.path.join(sandbox, "470000000.vpk")
    for p in (vpk, img, keep):
        with open(p, "wb") as f:
            f.write(b"x" * 64)

    comp = M.companion_files(vpk)
    log("  同名封面图识别:", sorted(os.path.basename(c) for c in comp))
    assert len(comp) == 2, "companion_files 应带上同名封面图"

    # 禁用态（.vpk.disabled）也要能认出同名图
    dis = os.path.join(sandbox, "469986973.vpk.disabled")
    os.rename(vpk, dis)
    comp_dis = M.companion_files(dis)
    assert len(comp_dis) == 2, "禁用态下 companion_files 认不出同名图"

    res = M.delete_files(comp_dis)
    log("  delete_files ->", {k: res[k] for k in ("ok", "removed", "recycled")})
    assert res["recycled"] is True, "删除应该走回收站（recycled 为 True）"
    assert not os.path.exists(dis) and not os.path.exists(img), "MOD 与同名图都该被移走"
    assert os.path.exists(keep), "别的 MOD 不能被误删"
    log("  回收站：MOD + 同名图一起移走，无关文件没动")

    # 选择模式：进去之后不该还挂着详情
    win.setProperty("modsSelMode", True)
    wait(200)
    assert bool(win.property("modsSelMode")) is True, "选择模式没打开"
    assert mgr.selectedPath == "", "选择模式下不该还开着 MOD 详情"
    mgr.checkAllLocal(True)
    wait(200)
    log("  选择模式：已选中", mgr.checkedCount)
    assert mgr.checkedCount == mgr.totalCount
    mgr.clearSelection()
    wait(150)
    assert mgr.checkedCount == 0
    win.setProperty("modsSelMode", False)
    wait(150)
    assert bool(win.property("modsSelMode")) is False

    # 筛选面板：点「应用」后应自己关掉
    win.openModFilter()
    wait(200)
    assert win.closeFilterPopup() is True, "筛选面板应该能被关掉"
    log("  筛选面板开/关都正常")

    import shutil as _sh
    _sh.rmtree(sandbox, ignore_errors=True)
    _sh.rmtree(_LEDGER_DIR, ignore_errors=True)

    log()
    log("全部通过")
    app.quit()


QTimer.singleShot(500, run)
QTimer.singleShot(120000, app.quit)
app.exec()
