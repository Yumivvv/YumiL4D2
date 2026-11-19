"""第十二轮 UI 细节验证：文案 / 重复入口 / 布局 / 动画时长。

纯静态检查（读 QML 源码 + 少量运行期属性），不依赖网络。
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

LOG = os.path.join(os.environ.get("TEMP", ROOT), "round12_ui.log")
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


def find_object(name: str):
    for child in win.findChildren(QObject):
        try:
            if child.objectName() == name:
                return child
        except RuntimeError:
            continue
    return None


def run():
    wait(1800)

    panel = read("qml/components/ModPanel.qml")
    mainq = read("qml/Main.qml")
    detail = read("qml/components/DetailPanel.qml")

    # ---------------------------------------------------- 1. 组合提示词已删除
    log("=== 1. 去掉「组合（一键切换）」 ===")
    assert "组合（一键切换）" not in panel, "侧边栏还在显示「组合（一键切换）」"
    assert "一键切换" not in panel, "还有「一键切换」字样"
    log("  ModPanel 里已无「组合」相关文案")

    # ---------------------------------------------------- 2. 检查按钮只剩一个
    log()
    log("=== 2. 检查MOD 只保留一个 ===")
    # 只看真正的 label，别被源码注释里的字眼干扰。
    # 「检查 MOD 文件」是工具条上的批量功能，和详情里的单个检查不是一回事，排除。
    labels = re.findall(r'label:\s*"([^"]*)"', panel)
    check_labels = [s for s in labels if "检查" in s and s != "检查 MOD 文件"]
    log("  详情里的检查类按钮:", check_labels, "（工具条另有「检查 MOD 文件」）")
    assert check_labels == ["检查MOD"], f"检查类按钮应只剩「检查MOD」，实际 {check_labels}"
    assert panel.count('label: "检查MOD"') == 1
    log("  只剩一个「检查MOD」按钮（批量那个「检查 MOD 文件」保留）")

    # ---------------------------------------------------- 3. 启用/禁用文案
    log()
    log("=== 3. 禁用MOD / 启用MOD ===")
    assert '"禁用MOD"' in panel and '"启用MOD"' in panel, "按钮文案没改成 禁用MOD/启用MOD"
    assert '"禁用这个 MOD"' not in panel and '"启用这个 MOD"' not in panel
    log("  文案是「禁用MOD」/「启用MOD」")

    # ---------------------------------------------------- 4. 试听只剩一个
    log()
    log("=== 4. 设置里「试听」去重 ===")
    n_test = mainq.count("text: \"试听\"")
    log("  Main.qml 里 text: \"试听\" 出现", n_test, "次")
    assert n_test == 1, f"「试听」入口应该只剩 1 个，实际 {n_test}"

    # ---------------------------------------------------- 5. 位置提示已删
    log()
    log("=== 5. 启动游戏下的位置提示已删 ===")
    assert "选到 Left 4 Dead 2\\left4dead2\\addons 就行" not in mainq, "那串位置提示还在"
    log("  已删除")

    # ---------------------------------------------------- 6. 详情过渡简化
    log()
    log("=== 6. MOD 详情过渡简化 ===")
    m = re.search(r"Behavior on width \{\s*NumberAnimation \{ duration: (\d+)", panel)
    log("  详情宽度动画时长 =", m.group(1) if m else "?", "ms")
    assert m and int(m.group(1)) <= 130, "详情过渡还是太长（>130ms），看着累"
    assert "detailShadow" in panel
    # 阴影那层不该再有 Behavior on width
    shadow_block = panel[panel.index("id: detailShadow"):]
    shadow_block = shadow_block[: shadow_block.index("Behavior on width")] \
        if "Behavior on width" in shadow_block[:900] else shadow_block[:900]
    assert "Behavior on width" not in shadow_block, "阴影层还在单独做宽度动画（会和面板抖）"
    log("  阴影层已去掉独立动画，只剩面板本体 110ms 滑入")

    # ---------------------------------------------------- 7. 扫描次数文案
    log()
    log("=== 7. 今日扫描 xx 次 ===")
    log("  lastCheckText =", core.lastCheckText)
    assert "今日扫描" in core.lastCheckText
    assert "共扫描" not in core.lastCheckText

    # ---------------------------------------------------- 8. 标题可选中
    log()
    log("=== 8. 详情标题可拖选 ===")
    assert "titleEdit" in detail, "标题没换成 TextEdit"
    title_block = detail[detail.index("id: titleEdit"):][:700]
    assert "selectByMouse: true" in title_block, "标题没有 selectByMouse"
    log("  标题是 readOnly + selectByMouse 的 TextEdit")

    # ---------------------------------------------------- 9. 置顶评论块存在
    log()
    log("=== 9. 置顶评论块 ===")
    assert "topCommentBox" in detail, "详情里没有置顶评论块"
    assert "置顶评论" in detail
    assert "commentLinks" in detail, "置顶评论里的网盘没接到界面"
    log("  置顶评论块 + 评论网盘都在")

    # ---------------------------------------------------- 10. 重复点关闭详情
    log()
    log("=== 10. 再点同一个 MOD 关闭详情 ===")
    items = core.mods.allModel.items()
    if items:
        p0 = items[0]["path"]
        core.mods.selectMod(p0)
        wait(100)
        assert core.mods.selectedPath
        core.mods.selectMod(p0)
        wait(100)
        assert core.mods.selectedPath == "", "重复点没关闭"
        log("  开关式行为正常")
    else:
        log("  [warn] 没有 MOD，跳过")

    # ---------------------------------------------------- 11. 设置滚动条不再压按钮
    log()
    log("=== 11. 设置滚动条位置 ===")
    assert "anchors.rightMargin: 30" in mainq, "设置 Flickable 没给滚动条留位置"
    log("  设置内容右边留了 30px 给滚动条")

    # ---------------------------------------------------- 12. toast 在右下角
    log()
    log("=== 12. Toast 在右下角 ===")
    toast_src = read("qml/components/ToastLayer.qml")
    assert "anchors.right: parent.right" in toast_src
    assert "anchors.bottom: parent.bottom" in toast_src
    assert "anchors.horizontalCenter" not in toast_src, "还在水平居中（应该在右下角）"
    log("  Toast 锚在右下角")

    log()
    log("全部通过")
    core.shutdown()
    app.quit()


QTimer.singleShot(300, run)
QTimer.singleShot(90000, app.quit)
app.exec()
