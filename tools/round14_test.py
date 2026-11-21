"""第十四轮修复验证：

  1. 鼠标悬停在提示上：**暂停**，离开后接着剩余时间走完 —— 不是重置。
     以前 resume() 调 lifeTimer.start() 会从头计时，于是鼠标一碰就重置、
     永远走不完，看起来就是「一直重复弹」。
  2. 提示的光标是默认箭头（不是可点击的手型）。
  3. 点开 MOD 详情后，被选中的卡片要能看出来（加粗边框 + 左侧色块 + 已选中角标），
     并且会重新滚回视野。
  4. 状态行右边那段「检查完成：xxx」重复文案已去掉。
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

import os
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import re
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

# 测试会构造真的 Core()，必须先把运行时数据目录隔离到临时沙盒，
# 否则会覆盖用户真实的 config.json / library.json / 导入日期台账。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from guard import protect_user_data  # noqa: E402
protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.core import Core
from app.util import ROOT, ensure_dirs

LOG = os.path.join(os.environ.get("TEMP", ROOT), "round14.log")
try:
    os.remove(LOG)
except OSError:
    pass


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


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


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def find_obj(name):
    for c in win.findChildren(QObject):
        try:
            if c.objectName() == name:
                return c
        except RuntimeError:
            continue
    return None


def toast_count(host):
    for c in host.findChildren(QObject):
        try:
            if "ListModel" in c.metaObject().className():
                v = c.property("count")
                if v is not None:
                    return int(v)
        except (RuntimeError, TypeError):
            continue
    return -1


def run():
    wait(1800)
    toast_qml = read("qml/components/ToastLayer.qml")
    panel_qml = read("qml/components/ModPanel.qml")
    code_lines = [ln for ln in panel_qml.splitlines() if not ln.strip().startswith("//")]
    panel_code = "\n".join(code_lines)

    # ------------------------------------------------------ 1. 结构检查
    log("=== 1. Toast 悬停不再重置 ===")
    # resume 不能再是「无参 + start()」那种写法
    assert "lifeTimer.resume(remaining)" in toast_qml or "lifeTimer.resume(" in toast_qml, \
        "没有按剩余时间恢复的逻辑"
    assert "property real remaining" in toast_qml, "没有记录剩余时间"
    assert "lifeTimer.start()" not in toast_qml.replace("lifeTimer.restart()", ""), \
        "还在用 start() 从头计时"
    log("  用 remaining 记录剩余时长，resume(ms) 接着走")

    log()
    log("=== 2. 光标是默认箭头 ===")
    cursor_lines = [ln.strip() for ln in toast_qml.splitlines() if "cursorShape" in ln]
    log("  cursorShape 出现:", cursor_lines)
    assert cursor_lines, "没有设置 cursorShape"
    assert all("ArrowCursor" in ln for ln in cursor_lines), \
        f"还有手型光标：{[l for l in cursor_lines if 'ArrowCursor' not in l]}"
    log("  全部是 Qt.ArrowCursor")

    # ------------------------------------------------------ 2. 运行期：悬停暂停
    log()
    log("=== 3. 运行期：正常情况到点消失（不受悬停逻辑影响） ===")
    host = find_obj("toastLayer")
    assert host is not None
    life = int(host.property("lifeMs") or 3600)
    log("  lifeMs =", life)

    win.toast("计时测试", "info")
    wait(500)
    n = toast_count(host)
    log("  弹出后 =", n)
    assert n == 1

    wait(life + 1600)
    n2 = toast_count(host)
    log(f"  等 {life + 1600}ms 后 =", n2)
    assert n2 == 0, f"提示没消失，还剩 {n2}"

    log()
    log("  悬停/离开的语义（pauseLife → resumeLife 保留 remaining）:")
    toast_src = read("qml/components/ToastLayer.qml")
    # 关键：onExited 走的是 resumeLife()，而 resumeLife 用 remaining 恢复
    assert "onExited: slot.resumeLife()" in toast_src, "离开时没走 resumeLife"
    assert "onEntered: slot.pauseLife()" in toast_src, "进入时没走 pauseLife"
    resume_block = toast_src[toast_src.index("function resumeLife()"):]
    # 取到下一个 "function " 或固定长度为止（别被内层大括号截断）
    nxt = resume_block.find("function ", 10)
    resume_block = resume_block[: nxt if nxt > 0 else 320]
    log("  resumeLife 内容:", " ".join(resume_block.split())[:220])
    assert "lifeTimer.resume(remaining)" in resume_block, "恢复时没用剩余时间"
    assert "lifeTimer.start()" not in resume_block, "恢复时还在从头 start（会无限重置）"
    log("  -> 悬停暂停、离开接着剩余时间走，不会重置")

    # ------------------------------------------------------ 3. 选中卡片可见
    log()
    log("=== 4. 选中的 MOD 卡片看得出来 ===")
    assert "selTag" in panel_code, "没有「已选中」角标"
    assert '"已选中"' in panel_code, "角标文字缺失"
    assert "border.width: model.selected ? 2 : 1" in panel_code, "选中边框没有加粗"
    assert "pendingRevealPath" in panel_code, "没有「滚回视野」的逻辑"
    assert "positionViewAtIndex" in panel_code, "没有调用 positionViewAtIndex"
    log("  角标 + 加粗边框 + 底色 + 自动滚回视野 都在")

    items = core.mods.allModel.items()
    if items:
        p0 = items[3]["path"] if len(items) > 3 else items[0]["path"]
        core.mods.selectMod(p0)
        wait(500)
        sel = core.mods.selectedItem
        log("  选中:", sel.get("title"))
        assert sel.get("path") == p0
        assert sel.get("selected") is True, "selectedItem 里的 selected 标记不对"
        # 模型里那一行也要带 selected=True
        rows = [core.mods.allModel.items()[i].get("selected")
                for i in range(core.mods.allModel.rowCount())]
        log("  模型里 selected=True 的行数 =", sum(1 for r in rows if r))
        assert sum(1 for r in rows if r) == 1, "应该正好一行是选中的"
        core.mods.clearSelected()
    else:
        log("  [warn] 没有 MOD，跳过")

    # ------------------------------------------------------ 4. 重复文案已删
    log()
    log("=== 5. 状态行右侧重复文案已删 ===")
    assert "text: page.qStatusText" not in panel_code, \
        "状态行右边那段 qStatusText 还在（和标题栏重复）"
    # 「共 N 个」那串统计要保留
    assert "共 \" + page.mgr.totalCount" in panel_code or 'parts = ["共 "' in panel_code, \
        "左边的「共 N 个」统计被误删了"
    log("  右侧重复文案已删，左侧统计保留")

    log()
    log("全部通过")
    core.shutdown()
    core.quitFromWindow()


QTimer.singleShot(300, run)
QTimer.singleShot(90000, core.quitFromWindow)
app.exec()
