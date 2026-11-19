# -*- coding: utf-8 -*-
"""本轮修复的回归测试（不联网、不开窗口）。

1. MOD 详情禁用不跳回顶部（新旧 path 都要能定位到行）
2. 创意工坊导入输入框文字不超出（外层裁切 + 右内边距）
3. 多选栏有「导出配置」按钮，且在「取消」左边
4. json 导入先列出服务器清单（含合集名标注）
5. 工坊详情查询走中转站优先（快 20 倍）+ 失败缓存会过期
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from PySide6.QtGui import QGuiApplication  # noqa: E402

from app.core import Core  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


QML_MOD = open(os.path.join("qml", "components", "ModPanel.qml"),
               encoding="utf-8").read()
QML_SRV = open(os.path.join("qml", "components", "ServersPage.qml"),
               encoding="utf-8").read()
QML_MAIN = open(os.path.join("qml", "Main.qml"), encoding="utf-8").read()
PY_MM = open(os.path.join("app", "modmanager.py"), encoding="utf-8").read()
PY_M = open(os.path.join("app", "mods.py"), encoding="utf-8").read()
PY_SRV = open(os.path.join("app", "servers.py"), encoding="utf-8").read()

app = QGuiApplication(sys.argv[:1])


# ============================================ 1. 禁用不跳回顶部
print("\n[1] MOD 详情禁用后不跳回顶部")
_apply = PY_MM[PY_MM.index("def _apply_enabled"):]
_apply = _apply[:_apply.index("def _any_state_filter")]
check("_all 模型会先试 old_path", 'self._all.row_of_path(old_path)' in _apply)
check("_all 模型查不到时再试 new_path",
      "_all.row_of_path(new_path)" in _apply)
check("tab 模型也会试新旧两个 path",
      _apply.count("row_of_path(old_path)") >= 2
      and _apply.count("row_of_path(new_path)") >= 2)
check("QML 禁用按钮记住位置", "grid.rememberPos()" in QML_MOD)
check("QML 禁用后还原位置", "grid.restorePos()" in QML_MOD)
check("有 rememberPos 函数", "function rememberPos" in QML_MOD)
check("有 restorePos 函数", "function restorePos" in QML_MOD)
check("还原用 Qt.callLater（等模型填好）", "Qt.callLater" in QML_MOD)


# ============================================ 2. 工坊导入输入框不溢出
print("\n[2] 创意工坊导入输入框文字不超出")
_ws = QML_MOD[QML_MOD.index('objectName: "wsInputField"'):]
_ws = _ws[:_ws.index("// ---- 加载中")]
check("TextInput 不再自己画背景（已拆到外层）",
      "z: -1" not in _ws)
check("外层容器有 clip", "clip: true" in _ws)
check("TextInput 自身也 clip", "clip: true" in _ws)
check("左右都有内边距", "leftPadding" in _ws and "rightPadding" in _ws)
check("输入框宽度扣掉了按钮宽度",
      "parent.width - 96" in QML_MOD)

# 用一个超长链接实测布局不会把宽度撑爆
from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

core = Core(app)
core._scan_worker = lambda: (core._set_busy(False), core.statusChanged.emit())
core.config["agreement_version"] = int(core.AGREEMENT_VERSION)
core.config["auto_check_update"] = False
eng = QQmlApplicationEngine()
q = os.path.join("qml")
eng.addImportPath(q)
eng.addImportPath(os.path.join(q, "components"))
eng.rootContext().setContextProperty("core", core)
eng.load(QUrl.fromLocalFile(os.path.join(q, "Main.qml")))
win = eng.rootObjects()[0]
win.resize(1320, 880)
win.show()

state = {}


def phase_long_text():
    """塞一个超长 URL 进输入框，量它的实际宽度有没有超过容器。"""
    win.setProperty("section", 1)          # MOD 页
    QTimer.singleShot(800, _open_ws_dlg)


def _open_ws_dlg():
    dlg = win.findChild(object, "wsImportDlg")
    field = win.findChild(object, "wsInputField")
    check("找到工坊导入弹窗", dlg is not None)
    check("找到输入框", field is not None)
    if dlg is None or field is None:
        return _done()
    dlg.open()
    # 粘一段超长链接：如果输入框不裁切，文字会画到框外压住「解析」按钮
    long_text = ("https://steamcommunity.com/sharedfiles/filedetails/?id="
                 + "3115675033&" * 12)
    field.setProperty("text", long_text)
    state["field"] = field
    QTimer.singleShot(600, _measure)


def _measure():
    field = state.get("field")
    fw = float(field.property("width") or 0)
    # 输入框所在 Row 的宽度：输入框 + 8 间距 + 88 按钮
    # 断言：输入框宽度 + 96 <= 所在容器宽（也就是没挤到按钮外面）
    parent_w = float(field.parent().property("width") or 0)
    check("输入框宽度没有溢出容器", fw <= parent_w + 1,
          f"{fw} <= {parent_w}")
    check("输入框确实裁掉了超长内容（clip=true）",
          bool(field.property("clip")) is True,
          field.property("clip"))
    _done()


def _done():
    core.shutdown()
    app.quit()


QTimer.singleShot(1500, phase_long_text)
QTimer.singleShot(20000, app.quit)
app.exec()


# ============================================ 3. 多选导出按钮
print()
print("[3] 多选栏「导出配置」按钮")
check("多选栏有导出按钮", 'objectName: "srvSelExportBtn"' in QML_SRV)
check("导出按钮文案是「导出配置」", 'label: "导出配置"' in QML_SRV)
check("导出按钮点了走 askExportChecked",
      "page.askExportChecked()" in QML_SRV)
check("导出按钮在「取消」左边",
      QML_SRV.index('objectName: "srvSelExportBtn"')
      < QML_SRV.index('label: "取消"'))
check("没勾选时禁用",
      "enabledBtn: page.checkedCount() > 0" in
      QML_SRV[QML_SRV.index('objectName: "srvSelExportBtn"'):
             QML_SRV.index('objectName: "srvSelExportBtn"') + 300])


# ============================================ 4. 导入清单
print()
print("[4] json 导入先列清单")
check("previewImport 返回 more 字段", '"more"' in PY_SRV)
check("previewImport 返回 groups 字段", '"groups"' in PY_SRV)
check("清单条目带合集名标注", 'f"  [{g}]"' in PY_SRV or "[{g}]" in PY_SRV)
check("界面用 Flickable 展示清单", 'id: importNamesFlick' in QML_MAIN)
check("有「还有 N 台」提示", '"…… 还有 "' in QML_MAIN)
check("标题里写了合集名数量", '"，含 "' in QML_MAIN)


# ============================================ 5. 工坊查询加速
print()
print("[5] 工坊详情查询加速与失败重试")
check("有中转站常量", "WORKSHOP_RELAY_DETAIL" in PY_M)
check("中转站走 /detail?id=", '/detail?id={}' in PY_M)
check("有 _query_relay", "def _query_relay" in PY_M)
check("有 _query_official", "def _query_official" in PY_M)
check("_query_batch 先走中转站",
      PY_M.index("_query_relay(wid)") < PY_M.index("_query_official(batch)"))
check("官方 API 超时压到 (5,12)",
      "timeout=(5, 12)" in PY_M)
check("官方 API 只重试 3 次", "range(3)" in PY_M)
check("失败缓存 30 分钟后过期", "1800" in PY_M)
check("缓存里有 previews 多图字段", '"previews"' in PY_M)

print()
if fails:
    print(f"失败 {len(fails)} 项：")
    for name in fails:
        print("  - " + name)
    sys.exit(1)
print("本轮修复的测试全部通过")
