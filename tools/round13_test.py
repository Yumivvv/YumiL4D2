"""第十三轮修复验证：
  1. 提示会自己消失（不会永远挂着）—— 由 toast_life_test 覆盖，这里看静态结构
  2. 播放器音量：常驻显示、只有一个喇叭图标
  3. MOD 详情：「看起来是最新的」那段删掉，可更新改成工坊 ID 右边的黄色图块
  4. 详情滑入：宽度固定、只动 x，不做逐帧布局
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

LOG = os.path.join(os.environ.get("TEMP", ROOT), "round13.log")
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


def run():
    wait(1600)

    player_qml = read("qml/components/PlayerOverlay.qml")
    panel_qml = read("qml/components/ModPanel.qml")
    toast_qml = read("qml/components/ToastLayer.qml")

    # ---------------------------------------------------- 1. 音量常驻 + 单图标
    log("=== 1. 播放器音量 ===")
    # 滑块的可见性不该依赖 hover
    assert "musicVolShown" not in player_qml, "滑块还在靠悬停展开（musicVolShown 残留）"
    assert "volSliderBox" in player_qml, "找不到滑块容器"
    # 整个文件里喇叭字形只应出现在一处（音量控件内）
    speaker_count = player_qml.count("\\uE767") + player_qml.count("\\uE74F")
    log("  喇叭字形出现次数 =", speaker_count)
    assert speaker_count == 2, (
        f"喇叭字形应只出现在同一处（静音/非静音两种状态各一次），实际 {speaker_count} 次"
    )
    # IconButton 那个独立的静音按钮应该没了
    assert 'tip: "静音"' not in player_qml, "独立的静音 IconButton 还在（会变成两个喇叭）"
    # 滑块宽度固定、不靠动画展开
    assert "Behavior on width" not in player_qml.split("volSliderBox")[1][:800], \
        "滑块还在做宽度展开动画"
    log("  滑块常驻、只有一个喇叭图标")

    # ---------------------------------------------------- 2. 更新提示已删
    log()
    log("=== 2. MOD 详情更新提示 ===")
    # 只看真正会被显示出来的字符串（text: "..."），别被源码注释干扰
    shown_texts = re.findall(r'text:\s*"([^"]*)"', panel_qml)
    leftovers = [s for s in shown_texts if "看起来是最新的" in s or "更新过，本地文件比它旧" in s]
    log("  还残留的更新提示文案:", leftovers)
    assert not leftovers, f"更新提示文案还在显示：{leftovers}"
    # 也不能再有拼接出来的同类文案
    assert "看起来是最新的" not in " ".join(shown_texts), "「看起来是最新的」还在显示"
    assert "updBox" not in panel_qml, "旧的更新提示块（updBox）还在"
    assert "updBadgeTxt" in panel_qml, "没有「可更新」图块"
    # 图块文字就是「可更新」，且在有工坊 ID 的那一行之后
    badge_idx = panel_qml.index("updBadgeTxt")
    id_idx = panel_qml.index('id: idTxt')
    log(f"  工坊ID块位置={id_idx}, 可更新块位置={badge_idx}")
    assert id_idx < badge_idx, "「可更新」图块没放在工坊 ID 右边"
    assert '"可更新"' in panel_qml
    log("  「看起来是最新的」那段已删；「可更新」在图块里，紧跟工坊 ID")

    # ---------------------------------------------------- 3. 滑入不动布局
    log()
    log("=== 3. 详情滑入不重算布局 ===")
    # 宽度必须固定为 page.detailW，不能用三元表达式跟着 detailOpen 变
    assert "width: page.detailW\n" in panel_qml, "详情宽度不是固定的（还在按打开状态变宽）"
    assert "width: page.detailOpen ? page.detailW : 0" not in panel_qml, \
        "详情还在 animate width（这会导致每帧重排）"
    assert "x: page.detailOpen ?" in panel_qml, "详情不是靠 x 滑入"
    m = re.search(r"Behavior on x \{\s*NumberAnimation \{ duration: (\d+)", panel_qml)
    log("  x 动画时长 =", m.group(1) if m else "?", "ms")
    assert m and 150 <= int(m.group(1)) <= 300, "滑入时长不合理"
    # 阴影用 x 跟随，不再 anchors 到 detail.left。
    # 只看真正的 QML 语句行（跳过注释），否则会被源码里的说明文字误判。
    code_lines = [ln for ln in panel_qml.splitlines()
                  if not ln.strip().startswith("//")]
    code = "\n".join(code_lines)
    assert "anchors.right: detail.left" not in code, "阴影还在锚到 detail.left（每帧重算）"
    assert "x: detail.x - width" in code
    log("  宽度固定 + 只动 x + 阴影跟随 x，都没触发内部重排")

    # ---------------------------------------------------- 4. 运行期：详情真的能开关
    log()
    log("=== 4. 运行期开关详情 ===")
    items = core.mods.allModel.items()
    if items:
        p0 = items[0]["path"]
        core.mods.selectMod(p0)
        wait(400)
        assert core.mods.selectedPath == p0
        core.mods.selectMod(p0)
        wait(400)
        assert core.mods.selectedPath == ""
        log("  打开 / 关闭 都正常")
    else:
        log("  [warn] 没有 MOD，跳过")

    # ---------------------------------------------------- 5. toast 结构合理
    log()
    log("=== 5. Toast 结构 ===")
    assert 'required property string stamp' in toast_qml, "stamp 还不是字符串（会被截断）"
    assert "function _newStamp()" in toast_qml, "没有字符串 stamp 生成器"
    assert "lifeTimer" in toast_qml, "没有独立 Timer 兜底"
    log("  stamp 是字符串、有独立 Timer 兜底")

    log()
    log("全部通过")
    core.shutdown()
    app.quit()


QTimer.singleShot(300, run)
QTimer.singleShot(90000, app.quit)
app.exec()
