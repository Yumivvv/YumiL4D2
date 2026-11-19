# -*- coding: utf-8 -*-
"""本轮五项修复的回归测试（不联网、不开窗口）。

1. 三连只弹**一条**提示（后端不再自己 toast，统一由界面拼一条）
2. 拖拽 json 导入 + 批量导入多个文件
3. 多选导出（只导出勾中的）
4. 导出/导入带合集名（groupNames 往返）
5. 在线时长字体优化（提亮 + 独立胶囊 + 加大字号）
"""
import json
import os
import sys
import tempfile

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


QML_MAIN = open(os.path.join("qml", "Main.qml"), encoding="utf-8").read()
QML_SRV = open(os.path.join("qml", "components", "ServersPage.qml"),
               encoding="utf-8").read()
PY_CORE = open(os.path.join("app", "core.py"), encoding="utf-8").read()
PY_SRV = open(os.path.join("app", "servers.py"), encoding="utf-8").read()

app = QGuiApplication(sys.argv[:1])


# ============================================ 1. 三连只弹一条
print("\n[1] 三连不再重复弹提示")
# 后端 biliTriple 里不能再出现 toast
_triple = PY_CORE[PY_CORE.index("def biliTriple"):]
_triple = _triple[:_triple.index("def biliFollowAuthor")]
check("biliTriple 不再自己弹 toast", "self.toast(" not in _triple,
      [ln for ln in _triple.splitlines() if "self.toast(" in ln][:2])
check("biliTriple 仍写状态栏", "self._set_status(" in _triple)
# QML 只调用一次 toast
_on_triple = QML_MAIN[QML_MAIN.index("onTriple: function"):]
_on_triple = _on_triple[:_on_triple.index("onNeedLogin:")]
check("QML onTriple 里有且仅有一处 toast 调用",
      _on_triple.count("win.toast(") >= 1 and
      # 三个分支各自一条，但每次点击只会走一条
      "else if" in _on_triple, _on_triple.count("win.toast("))
check("部分成功时把成功项也写出来",
      'doneList.join' in _on_triple and "未完成" in _on_triple)

core = Core(app)
try:
    core.client.set_credentials("s", "j", "999")
    core.client.nav_user = lambda: {"mid": 999}
    core.library.videos["BVt"] = {"bvid": "BVt", "aid": 1, "mid": 2}
    core.setBiliLike(True)
    core.setBiliCoin(True)
    core.setBiliFav(True)
    core.setBiliFollow(False)
    core.client.like_video = lambda aid, like=True: {"ok": True}
    core.client.coin_video = lambda aid, n=1: {
        "ok": False, "code": -104, "message": "硬币不足",
        "human": "投币失败：硬币不足"}
    core.client.favorites = lambda: [{"id": 1, "title": "默认"}]
    core.client.favorite_video = lambda aid, fid: {"ok": True}

    toasts = []
    core.toastRequested.connect(lambda t, l: toasts.append((t, l)))
    res = core.biliTriple("BVt")
    check("调 biliTriple 本身不产生任何 toast", not toasts, str(toasts))
    check("返回里有 done 和 errors",
          res.get("done") and res.get("errors"), str(res)[:80])
finally:
    core.shutdown()


# ============================================ 3+4. 导出 / 导入（含合集名、多选）
print("\n[2] 导出带合集名 + 多选导出 + 导入还原")
core = Core(app)
tmpdir = tempfile.mkdtemp(prefix="srv_export_")
try:
    mgr = core.servers
    # 造 4 台，分两个合集
    mgr._favorites = lambda: [
        {"addr": "1.1.1.1:27015", "name": "黑喵1服", "weight": 0, "panels": []},
        {"addr": "1.1.1.1:27016", "name": "黑喵2服", "weight": 0, "panels": []},
        {"addr": "2.2.2.2:27015", "name": "白猫1服", "weight": 0, "panels": []},
        {"addr": "2.2.2.2:27016", "name": "白猫2服", "weight": 0, "panels": []},
    ]
    mgr._live = {}
    mgr._group_key = "all"

    # 给「黑喵」这个合集手动命名
    gs = mgr.groups
    target = next((g for g in gs if "黑喵" in g["label"]), None)
    check("造出「黑喵」合集", target is not None, str([g["label"] for g in gs]))
    if target:
        r = mgr.renameGroup(target["key"], "黑喵服群")
        check("重命名成功", r.get("ok") is True, str(r))

    full = os.path.join(tmpdir, "full.json")
    r = mgr.exportConfig(full)
    check("全部导出成功", r.get("ok") is True, str(r))
    data = json.load(open(full, encoding="utf-8"))
    check("导出文件里有 groupNames", "groupNames" in data, list(data))
    check("groupNames 里记了黑喵服群",
          "黑喵服群" in (data.get("groupNames") or {}).values(),
          data.get("groupNames"))
    check("_version 升到 2", data.get("_version") == 2, data.get("_version"))
    check("每台自带 group 字段",
          all("group" in s for s in data["servers"]), data["servers"][0])

    # 多选导出：只导 2 台
    part = os.path.join(tmpdir, "part.json")
    r = mgr.exportConfig(part, ["1.1.1.1:27015", "2.2.2.2:27015"])
    check("按地址导出成功", r.get("ok") is True, str(r))
    pdata = json.load(open(part, encoding="utf-8"))
    check("只导出了 2 台", len(pdata["servers"]) == 2,
          [s["addr"] for s in pdata["servers"]])
    check("多选导出也带合集名",
          "groupNames" in pdata, list(pdata))
    # 空地址列表 = 全部
    r = mgr.exportConfig(os.path.join(tmpdir, "all2.json"), [])
    check("空 addrs 等于导出全部",
          json.load(open(os.path.join(tmpdir, "all2.json"),
                         encoding="utf-8"))["count"] == 4)

    # 导入到「干净」的实例：合集名要能还原
    core2 = Core(app)
    try:
        mgr2 = core2.servers
        # ★ 彻底清空：只改 _favorites 不够，_group_overrides 是从 config 读的，
        #   沙盒里有用户真实的 server_group_names，会让「未命名」判断失效。
        mgr2.config["servers"] = []
        mgr2.config["server_group_names"] = {}
        mgr2.config.save()
        mgr2._live = {}
        r = mgr2.importConfig(full)
        check("导入成功", r.get("added") == 4, str(r))
        check("还原了合集名", r.get("groups", 0) >= 1, str(r))
        names = mgr2._group_overrides()
        check("黑喵的两台记住了「黑喵服群」",
              names.get("1.1.1.1:27015") == "黑喵服群"
              and names.get("1.1.1.1:27016") == "黑喵服群", str(names))
        gs2 = mgr2.groups
        labels = [g["label"] for g in gs2]
        check("导入后合集名就是「黑喵服群」",
              "黑喵服群" in labels, labels)
    finally:
        core2.shutdown()

    # 批量导入：一次两个文件
    good1 = os.path.join(tmpdir, "b1.json")
    good2 = os.path.join(tmpdir, "b2.json")
    bad = os.path.join(tmpdir, "bad.json")
    json.dump({"servers": [{"addr": "9.9.9.1:27015", "name": "批量A"}]},
              open(good1, "w", encoding="utf-8"))
    json.dump({"servers": [{"addr": "9.9.9.2:27015", "name": "批量B"}],
               "groupNames": {"9.9.9.2:27015": "批量合集"}},
              open(good2, "w", encoding="utf-8"))
    open(bad, "w", encoding="utf-8").write("这不是 json")

    core3 = Core(app)
    try:
        mgr3 = core3.servers
        mgr3.config["servers"] = []
        mgr3.config["server_group_names"] = {}
        mgr3.config.save()
        mgr3._live = {}
        r = mgr3.importConfigs([good1, good2, bad])
        check("批量导入加了 2 台", r.get("added") == 2, str(r))
        check("批量导入报告坏文件数", r.get("failed") == 1, str(r))
        check("批量导入也还原合集名", r.get("groups", 0) >= 1, str(r))
        check("坏文件不影响好文件",
              mgr3._group_overrides().get("9.9.9.2:27015") == "批量合集",
              str(mgr3._group_overrides()))
    finally:
        core3.shutdown()
finally:
    core.shutdown()

# 拖拽 / 多选导出 的 QML 接线
print()
print("[3] 拖拽导入与多选导出的界面接线")
check("有 DropArea", "DropArea {" in QML_SRV)
check("拖拽时整页高亮", 'objectName: "srvDropOverlay"' in QML_SRV)
check("handleDropped 会剥掉 file:// 前缀",
      "replace(/^file:\\/\\/\\//" in QML_SRV, "没找到剥前缀")
check("有 requestDropImport 信号", "signal requestDropImport" in QML_SRV)
check("Main.qml 接了 onRequestDropImport",
      "onRequestDropImport" in QML_MAIN)
check("拖拽走 importConfigs",
      "core.servers.importConfigs(paths)" in QML_MAIN)
check("有 askExportChecked（多选导出）",
      "function askExportChecked" in QML_SRV)
check("多选模式下导出按钮改调 askExportChecked",
      "page.askExportChecked()" in QML_SRV)
check("导出把勾选的地址传下去",
      "exportConfig(s, picked)" in QML_MAIN)
check("导入框支持多选", "FileDialog.OpenFiles" in QML_MAIN)


# ============================================ 5. 在线时长可读性
print()
print("[4] 在线时长字体优化")
_players = QML_SRV[QML_SRV.index('objectName: "srvPlayerList"'):]
_players = _players[:_players.index("// ------------------------------------------------------------ 合集重命名")]
check("时长有独立 Text 且带 objectName",
      'objectName: "srvPlayerTime"' in _players)
check("时长不再是 9px（提到 10）",
      "font.pixelSize: 10" in _players, "没找到 10px")
check("时长颜色比 textMute 亮（用 textDim）",
      "color: Theme.textDim" in _players, "没找到 textDim")
check("时长加了淡底胶囊",
      "color: Theme.scrim(0.07)" in _players)
check("时长和分数拆成两个独立块",
      'objectName: "srvPlayerScore"' in _players)
check("不再用「   」硬拼时长和分数",
      'timeText + "   "' not in _players)
check("行高从 26 提到 28", "height: 28" in _players)

print()
if fails:
    print(f"失败 {len(fails)} 项：")
    for name in fails:
        print("  - " + name)
    sys.exit(1)
print("本轮五项修复的测试全部通过")
