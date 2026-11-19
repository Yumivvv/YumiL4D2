"""本轮 UI 修正的回归测试。

1. 端口遍历弹窗开着时，剪贴板导入不弹（用户粘 IP 是想扫描，不是想导入）
2. 端口遍历 / 多选按钮靠右（和其它图标工具排在一起，不再夹在文字按钮中间）
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


main_qml = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
page_qml = open(os.path.join(ROOT, "qml", "components", "ServersPage.qml"),
                encoding="utf-8").read()

print("=== 1. 端口遍历时挡住剪贴板导入 ===")
check("有 serverDialogOpen() 辅助函数", "function serverDialogOpen" in main_qml)
check("checkClipboardServers 里调用了它",
      "serverDialogOpen()" in main_qml)
for key, label in (
    ("page.formScan === true", "端口遍历（已并入添加服务器）"),
    ("page.formOpen === true", "添加/编辑服务器"),
    ("page.directOpen === true", "IP 直连"),
    ("page.pasteOpen === true", "从文字导入"),
    ("page.selectMode === true", "多选模式"),
):
    check(f"挡住了「{label}」", key in main_qml)

check("没有引用已删除的 bulkOpen", "page.bulkOpen" not in main_qml)
# onActiveChanged 必须还在（之前改动时误删过）
check("onActiveChanged 还在", "onActiveChanged:" in main_qml)

print()
print("=== 2. 工具条按钮顺序（工具图标靠右）===")
order = [
    "srvAddBtn", "srvDirectBtn", "srvRefreshBtn",
    "srvExportBtn", "srvImportBtn", "srvPasteBtn", "srvSelectBtn",
]
pos = {}
for name in order:
    idx = page_qml.find('objectName: "%s"' % name)
    pos[name] = idx
    if idx < 0:
        print(f"  !! 找不到 {name}")

check("工具条按钮都在", all(v > 0 for v in pos.values()))
check("多选在最右", pos["srvSelectBtn"] == max(pos.values()))
check("添加服务器在最左", pos["srvAddBtn"] == min(pos.values()))
check("三颗文字按钮连在一起（中间不夹图标）",
      pos["srvAddBtn"] < pos["srvDirectBtn"] < pos["srvRefreshBtn"]
      < pos["srvExportBtn"])

print()
print("=== 3. 端口遍历已并入「添加服务器」===")
check("工具条上不再有独立的端口遍历按钮",
      'objectName: "srvScanBtn"' not in page_qml)
check("没有独立的扫描弹窗", "id: scanDlg" not in page_qml)
check("有 formScan 模式", "property bool formScan" in page_qml)
check("扫描面板在添加对话框里", "扫描模式的面板" in page_qml)
check("切换器有三档（单条/批量/扫描）",
      '"单条"' in page_qml and '"批量"' in page_qml and '"扫描"' in page_qml)

print()
print('=== 4. 三种模式互斥切换 ===')
# formMode 是按 formScan > formBulk > 单条 算的，所以两个开关必须互斥。
# 用户报过：从「扫描」点「单条 / 批量」没反应 —— 因为 switchToBulk /
# switchToSingle 只改了 formBulk，没清掉 formScan。
check('switchToBulk 会清掉 formScan',
      'page.formScan = false' in page_qml.split('function switchToBulk')[1].split('function ')[0])
check('switchToSingle 会清掉 formScan',
      'page.formScan = false' in page_qml.split('function switchToSingle')[1].split('function ')[0])
check('formMode 以 formScan 优先',
      'page.formScan ? 2 : (page.formBulk ? 1 : 0)' in page_qml)

print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
