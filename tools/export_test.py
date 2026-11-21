# -*- coding: utf-8 -*-
"""服务器配置导出：多选只导勾中的 + 合集名跟着走。

## 这个测试防的是什么

用户报「多选后导出，会全部导出」。
根因不在 QML 也不在导出逻辑，而在**槽签名**：

    @Slot(str, result="QVariantMap")            # ← 只声明了 1 个参数
    def exportConfig(self, path, addrs=None):   # ← 实际有 2 个

PySide6 按槽签名派发参数，QML 传来的第二个参数（勾中的地址列表）被
**直接丢掉**，`addrs` 永远是默认 None → 每次都是全量导出。
connect 不报错、QML 也不报错，所以很难看出来。

本测试盯四件事：
1. 槽签名里确实声明了 addrs（"QVariantList"）
2. 传 addrs 时只导出那些
3. 合集名随导出（含未选中成员的合集不会被整组带进来）
4. 不传 addrs 时才是全量
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from guard import protect_user_data  # noqa: E402

protect_user_data()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def main():
    from app import servers as S

    # ---------------------------------------------------------- 1. 槽签名
    print("=== 1. exportConfig 的槽签名必须带上 addrs ===")
    src = open(os.path.join(ROOT, "app", "servers.py"), encoding="utf-8").read()
    i = src.find("def exportConfig(")
    # 往回找最近的装饰器
    head = src[max(0, i - 400):i]
    deco = head[head.rfind("@Slot"):] if "@Slot" in head else ""
    print(f"      装饰器: {deco.strip()[:80]}")
    check("装饰器声明了 QVariantList", "QVariantList" in deco, deco[:60])
    check("装饰器不是只吃 str", '@Slot(str, result=' not in deco)

    # ---------------------------------------------------------- 2. 真实 Core
    print("=== 2. 只导出勾中的那些 ===")
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from app.core import Core

    core = Core(app)
    mgr = core.servers

    # 独立沙盒里收藏可能是空的，也可能带着已有的（这里不清空，避免误删用户数据），
    # 所以用**相对计数**断言，不写死 4。
    base = mgr.serverCount
    for i in range(4):
        mgr.saveServer({"addr": f"10.7.0.{i + 1}:27015",
                        "name": f"服{i}", "weight": 0})
    # 前两台同属手动合集「黑喵」
    mgr.config["server_group_names"] = {
        "10.7.0.1:27015": "黑喵",
        "10.7.0.2:27015": "黑喵",
    }
    check("4 台都加进去了", mgr.serverCount == base + 4,
          f"{base} -> {mgr.serverCount}")

    out = os.path.join(tempfile.gettempdir(), "ysrv_export_partial.json")
    # 只勾第 1、3 台（第 2 台同属「黑喵」但没勾 —— 不该被带进来）
    r = mgr.exportConfig(out, ["10.7.0.1:27015", "10.7.0.3:27015"])
    check("导出调用成功", r.get("ok") is True, str(r))
    data = json.load(open(out, encoding="utf-8"))
    addrs = [x["addr"] for x in data["servers"]]
    print(f"      文件里 {len(addrs)} 台: {addrs}")
    check("只导出 2 台", len(addrs) == 2, str(len(addrs)))
    check("就是勾中的那两台",
          set(addrs) == {"10.7.0.1:27015", "10.7.0.3:27015"}, str(addrs))
    check("没勾的那台没被带进来", "10.7.0.2:27015" not in addrs)
    check("合集名一起导出",
          data.get("groupNames", {}).get("10.7.0.1:27015") == "黑喵",
          str(data.get("groupNames")))
    check("合集名只含选中项",
          "10.7.0.2:27015" not in (data.get("groupNames") or {}),
          str(data.get("groupNames")))

    # ---------------------------------------------------------- 3. 全量
    print("=== 3. 不传 addrs = 全量 ===")
    out2 = os.path.join(tempfile.gettempdir(), "ysrv_export_all.json")
    mgr.exportConfig(out2, [])
    d2 = json.load(open(out2, encoding="utf-8"))
    check("导出全部（= 收藏总数）", len(d2["servers"]) == mgr.serverCount,
          f"{len(d2['servers'])} vs {mgr.serverCount}")

    out3 = os.path.join(tempfile.gettempdir(), "ysrv_export_none.json")
    mgr.exportConfig(out3, None)
    d3 = json.load(open(out3, encoding="utf-8"))
    check("传 None 也是全量", len(d3["servers"]) == mgr.serverCount,
          f"{len(d3['servers'])} vs {mgr.serverCount}")

    # ---------------------------------------------------------- 4. QML 侧
    print("=== 4. QML：askExport 会清掉上次的选择 ===")
    qml = open(os.path.join(ROOT, "qml", "components", "ServersPage.qml"),
               encoding="utf-8").read()
    j = qml.find("function askExport()")
    seg = qml[j:j + 700] if j > 0 else ""
    check("askExport 里清空 exportAddrs", "page.exportAddrs = []" in seg)

    k = qml.find("function askExportChecked()")
    seg2 = qml[k:k + 700] if k > 0 else ""
    check("askExportChecked 会写 exportAddrs", "page.exportAddrs = picked" in seg2)
    check("askExportChecked 会收集 checked", "page.checked" in seg2)

    # Main.qml 里把 picked 真的传给后端
    main_qml = open(os.path.join(ROOT, "qml", "Main.qml"), encoding="utf-8").read()
    check("Main.qml 调 exportConfig 时传了 picked",
          "exportConfig(s, picked)" in main_qml)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    try:
        core.mods.shutdown()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())