"""多选删除服务器 / 添加服务器多选功能。

验证：
  1. 后端 removeMany 能一次删多台
  2. 不存在的地址不报错、也不算进 removed
  3. 空列表返回失败而不是崩
  4. QML 里有选择模式、勾选框、操作栏、确认弹窗
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1])

from app.servers import ServerManager  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


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


def seed(n):
    core.config.data["servers"] = [
        {"addr": f"10.0.0.{i}:27015", "name": f"服{i}", "weight": 0, "panels": []}
        for i in range(1, n + 1)
    ]


print("=== 1. 一次删多台 ===")
seed(5)
res = mgr.removeMany(["10.0.0.1:27015", "10.0.0.3:27015", "10.0.0.5:27015"])
check("删除成功", res.get("ok") is True, str(res))
check("删了 3 台", res.get("removed") == 3, str(res.get("removed")))
left = [r["addr"] for r in core.config.data["servers"]]
check("剩下 2 台", len(left) == 2, str(left))
check("剩下的是 2 和 4",
      sorted(left) == ["10.0.0.2:27015", "10.0.0.4:27015"], str(left))

print()
print("=== 2. 大小写 / 空格容错 ===")
seed(2)
res = mgr.removeMany([" 10.0.0.1:27015 ", "10.0.0.2:27015"])
check("带空格也能删", res.get("removed") == 2, str(res))

print()
print("=== 3. 不存在的地址 ===")
seed(2)
res = mgr.removeMany(["9.9.9.9:1", "10.0.0.1:27015"])
check("只删掉存在的那台", res.get("removed") == 1, str(res))
check("结果仍然 ok", res.get("ok") is True)

print()
print("=== 4. 空输入 / 全不存在 ===")
seed(2)
res = mgr.removeMany([])
check("空列表返回失败", res.get("ok") is False, str(res))
check("空列表 removed=0", res.get("removed") == 0)
res = mgr.removeMany(["1.1.1.1:1"])
check("全不存在也返回失败", res.get("ok") is False, str(res))
check("全不存在时列表没被改", len(core.config.data["servers"]) == 2)

print()
print("=== 5. QML 侧关键元素 ===")
page_qml = open(os.path.join(ROOT, "qml", "components", "ServersPage.qml"),
                encoding="utf-8").read()
for key, label in (
    ("function enterSelect", "有进入选择模式"),
    ("function toggleChecked", "有勾选切换"),
    ("function setAllChecked", "有全选"),
    ("function removeChecked", "有批量删除"),
    ('objectName: "srvSelectBtn"', "工具条有「多选」按钮"),
    ('objectName: "srvCardCheck"', "卡片上有勾选框"),
    ('objectName: "srvSelBar"', "有底部操作栏"),
    ('objectName: "srvSelDeleteBtn"', "有「删除选中」按钮"),
    ('objectName: "srvSelConfirm"', "有删除确认弹窗"),
):
    check(label, key in page_qml)

check("后端有 removeMany", "def removeMany" in
      open(os.path.join(ROOT, "app", "servers.py"), encoding="utf-8").read())

mgr.shutdown()
print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
