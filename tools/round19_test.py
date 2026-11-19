"""本轮四项改动的回归测试。

1. 批量添加已并进「添加服务器」（不再有独立弹窗/按钮）
2. 关掉端口遍历弹窗 → 扫描立刻终止
3. 加/删服务器后列表不跳回开头
4. 粘「IP:端口」到主机框 → 自动拆出 IP 和 端口~端口+99
5. 服务器按名字里的提示词自动分类
"""
import os
import re
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1])

from app.servers import (  # noqa: E402
    ServerManager,
    server_category,
    category_label,
    SERVER_CATEGORY_LABELS,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


page_qml = read("qml/components/ServersPage.qml")

print("=== 1. 批量添加并进「添加服务器」 ===")
check("工具条没有独立的批量按钮", 'objectName: "srvBulkBtn"' not in page_qml)
check("没有独立的批量弹窗", "id: bulkDlg" not in page_qml)
check("添加对话框里有 formBulk 模式切换", "formBulk" in page_qml)
check("批量面板在添加对话框内", 'objectName: "srvBulkInput"' in page_qml)
check("批量模式下按钮叫「全部添加」", "全部添加" in page_qml)

print()
print("=== 2. 关扫描弹窗就终止 ===")
check("onClosed 里调了 stopScan", re.search(
    r"onClosed:\s*\{[^}]*stopScan", page_qml, re.S) is not None)
check("后端有 scanRunning 属性", "def scanRunning" in read("app/servers.py"))
check("cancelScan 会立刻清状态", "_scan_running = False" in read("app/servers.py"))

print()
print("=== 3. 列表不跳回开头 ===")
check("有 _anchorAddr 锚点记录", "_anchorAddr" in page_qml)
check("只在行数变化时恢复位置", "_lastCount" in page_qml)

print()
print("=== 4. 主机框自动拆 IP:端口 ===")
check("有 normalizeScanHost", "function normalizeScanHost" in page_qml)
check("粘贴后自动拆（onEditingFinished）",
      "onEditingFinished: page.normalizeScanHost()" in page_qml)
# ★ 用户报的 bug：只在 onEditingFinished 里拆，而那个信号要**失焦**才发 —
#   粘贴完光标还在框里，于是「IP 输进去了、后面两个端口框没变」。
#   现在输入时就带防抖地拆一次。
check("输入时就自动拆（防抖，不用等失焦）",
      "scanSplitTimer.restart()" in page_qml)
# 拆完必须把两个端口框的文字也换掉（TextInput 的 text 不是双向绑定）
check("拆分时同步改两个端口框的文字",
      "scanFromInput.text = String(page.scanFrom)" in page_qml
      and "scanToInput.text = String(page.scanTo)" in page_qml)


# --- 后端拆端口逻辑实测
class _Cfg:
    def __init__(self):
        self.data = {"servers": [], "servers_sort": "weight"}

    def __getitem__(self, k):
        return self.data.get(k)

    def __setitem__(self, k, v):
        self.data[k] = v

    def save(self):
        pass


class _Core(QObject):
    def __init__(self):
        super().__init__()
        self.config = _Cfg()


core = _Core()
mgr = ServerManager(core)
mgr._toast = lambda *a, **k: None

# 用一个不存在的端口段，扫很快
r = mgr.scanPortRange("1.1.1.1:25000", 27015, 27025)
print("  传入 1.1.1.1:25000 ->",
      f"host={r.get('host')} start={r.get('start')} end={r.get('end')} "
      f"total={r.get('total')}")
check("主机被拆成 IP", r.get("host") == "1.1.1.1")
check("起始端口 = 25000", r.get("start") == 25000)
check("结束端口 = 25099", r.get("end") == 25099)
check("总数 100", r.get("total") == 100)
check("标记为已调整", r.get("adjusted") is True)

# 取消它，避免测试变慢
mgr.cancelScan()
check("取消后不再 running", mgr.scanRunning is False)

print()
print("=== 5. 自动分类 ===")
cases = [
    ("xx服 写实对抗 #1", "realismversus"),
    ("4人纯净写实专家多特 1服", "realism"),
    ("xx服 对抗模式#1", "versus"),
    ("合作战役 长期服", "coop"),
    ("生存模式 挑战", "survival"),
    ("模组服 插件版", "mod"),
    ("随便一个名字", "other"),
]
for name, want in cases:
    got = server_category(name)
    check(f"分类「{name}」", got == want, f"{got}（期望 {want}）")

check("分类中文名可用", category_label("versus") == "对抗")
check("分类表含全部+其他", "all" in SERVER_CATEGORY_LABELS and
      "other" in SERVER_CATEGORY_LABELS)

# _merged 里带 category 字段
core.config.data["servers"] = [
    {"addr": "1.1.1.1:27015", "name": "xx服 对抗#1", "weight": 0, "panels": []},
    {"addr": "2.2.2.2:27015", "name": "合作战役", "weight": 0, "panels": []},
]
rows = mgr.servers
cats = {row["addr"]: row.get("category") for row in rows}
check("每行都带 category", all(v for v in cats.values()), str(cats))
check("对抗服归到 versus", cats.get("1.1.1.1:27015") == "versus")
check("战役服归到 coop", cats.get("2.2.2.2:27015") == "coop")

# categories 属性只列出有的类
cats_list = mgr.categories
keys = [c["key"] for c in cats_list]
print("  categories =", [(c["key"], c["label"], c["count"]) for c in cats_list])
check("含 all", "all" in keys)
check("含 versus", "versus" in keys)
check("含 coop", "coop" in keys)
check("不含空的 survival", "survival" not in keys)

mgr.shutdown()
print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
