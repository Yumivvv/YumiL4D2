"""检查 MOD 详情面板底部的「转换到本地MOD」按钮。

不截图也能验证：直接翻 QML 对象树，看按钮的文字和可见性。
"""
from __future__ import annotations

import os
import sys

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

from app.core import Core
from app.util import ROOT, ensure_dirs

LOG_PATH = os.path.join(os.environ.get("TEMP", ROOT), "detail_check.log")
try:
    os.remove(LOG_PATH)
except OSError:
    pass


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    # QML 的 TypeError 会走 stderr 混进 stdout，测试结果单独存一份更干净
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


ensure_dirs()
app = QGuiApplication(sys.argv[:1])
engine = QQmlApplicationEngine()
q = os.path.join(ROOT, "qml")
engine.addImportPath(q)
engine.addImportPath(os.path.join(q, "components"))
core = Core(app)
engine.rootContext().setContextProperty("core", core)
engine.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))
win = engine.rootObjects()[0]
win.show()
mgr = core.mods


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def find_texts(root, needle):
    """找所有 Text 对象（走 QObject 树，别走可视树——可视树拿不到 QQuickText）。"""
    from PySide6.QtCore import QObject

    out = []
    all_texts: list[str] = []
    for child in root.findChildren(QObject):
        try:
            if child.metaObject().className() not in ("QQuickText",):
                continue
            t = str(child.property("text") or "")
            if not t:
                continue
            all_texts.append(t)
            if needle in t:
                out.append((t, bool(child.property("visible"))))
        except RuntimeError:
            continue
    find_texts.last_all = all_texts
    return out


def run():
    wait(2500)
    win.setProperty("section", 1)
    wait(2000)

    items = mgr.allModel.items()
    ws = next((m for m in items if m.get("inWorkshopDir")), None)
    local = next((m for m in items if not m.get("inWorkshopDir")), None)

    log("=== 创意工坊 MOD 详情 ===")
    if ws:
        mgr.selectMod(ws["path"])
        wait(700)
        hits = find_texts(win, "转换到本地MOD")
        log("  选中:", ws.get("title"), " inWorkshopDir =", ws.get("inWorkshopDir"))
        log("  找到「转换到本地MOD」按钮:", hits)
        if not hits:
            log("  全部文字样本:", find_texts.last_all[:40])
        assert hits, "创意工坊 MOD 详情里没有「转换到本地MOD」"
        assert any(v for _, v in hits), "按钮存在但不可见"
    else:
        log("  [warn] 没有创意工坊 MOD")

    log()
    log("=== 本地 MOD 详情（不该出现转换按钮）===")
    if local:
        mgr.selectMod(local["path"])
        wait(700)
        hits = find_texts(win, "转换到本地MOD")
        log("  选中:", local.get("title"), " inWorkshopDir =", local.get("inWorkshopDir"))
        log("  「转换到本地MOD」可见项:", [h for h in hits if h[1]])
        assert not any(v for _, v in hits), "本地 MOD 不该有可见的转换按钮"

    log()
    log("=== 详情字段 ===")
    if ws:
        mgr.selectMod(ws["path"])
        wait(400)
        sel = mgr.selectedItem
        log("  导入日期:", sel.get("importText"))
        log("  作者:", sel.get("authorLabel"))
        assert "修改日期" not in "".join(t for t, _ in find_texts(win, "日期")), \
            "详情里还在显示「修改日期」"

    log()
    log("=== 工具条：没有「全部移植」 ===")
    hits = find_texts(win, "全部移植")
    log("  「全部移植」:", hits)
    assert not hits, "「全部移植」按钮还在"

    log()
    log("=== 侧边栏：状态里有「本地」 ===")
    # 侧边栏状态项是 Repeater 里动态建的 Text，QObject 树拿不到它们的 text，
    # 所以这里查「构建列表的源码」+「统计数据」，两者对上就说明项确实存在。
    panel_qml = os.path.join(ROOT, "qml", "components", "ModPanel.qml")
    with open(panel_qml, "r", encoding="utf-8") as f:
        src = f.read()
    assert 'label: "本地"' in src, "ModPanel 的状态列表里没有「本地」"
    assert "key: 6" in src, "「本地」状态项缺 key"
    counts = dict(mgr.statusCounts)
    log("  statusCounts:", counts)
    assert "local" in counts and counts["local"] + counts["workshop"] == counts["all"]
    log("  源码里有「本地」状态项，statusCounts.local =", counts["local"])

    mgr.setStatusFilter(6)
    wait(300)
    log("  切换「本地」筛选后 totalCount =", mgr.totalCount,
        "（应 =", counts["local"], "）")
    assert mgr.totalCount == counts["local"], "「本地」筛选数量不对"
    mgr.setStatusFilter(0)
    wait(200)

    log()
    log("全部通过")
    # ★ 不用 app.quit()：它触发的窗口 close 会被 QML onClosing（收进托盘模式）
    #   拦下来，事件循环退不出去 → 明明跑完了却挂住。判定已打印完，直接退。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


QTimer.singleShot(300, run)
QTimer.singleShot(90000, lambda: os._exit(1))
app.exec()
