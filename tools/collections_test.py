# -*- coding: utf-8 -*-
"""服务器页两处改动的回归：扫描勾选 + 自建合集。

## 一、扫描结果「全不选之后再勾选，勾不上、也保存不了」

用户原话：

    修复添加服务器扫描，然后扫到的IP按全不选之后，我再去勾选无法保存选中的问题

根因是 **QML `property var` 的赋值语义**：

```qml
// 扫描结果 delegate 里原来的写法
var sel = page.scanChecked
sel[modelData.addr] = checked     // 改的是同一个 JS 对象
page.scanChecked = sel            // 同一个引用 → QML 认为「没变」，不发 changed
```

`property var` 只在赋一个**不同的对象**时才发 `changed` 信号。原地改的话，
依赖 `scanChecked` 的绑定（保存按钮的 `enabledBtn: scanSelectedCount() > 0`）
永远不会重算 —— 按钮一直是灰的，用户「勾了也没反应」。

所以这里要盯两件事：
  1. 源码里不能再有「原地改再赋回」的写法；
  2. 真实操作序列（全不选 → 勾 1 台 → 保存）确实能存进去。

## 二、自建合集

用户原话：

    添加能把服务器自定义合集的功能，可以转到某某合集里面保存，还可以自己新建合集

要点：
  · 能新建 / 改名 / 删除合集；
  · 能把选中的服务器**转**进某个合集（转移 = 从别的合集里摘掉，不能同时在两个）；
  · 删合集**不能删服务器**；
  · 自建合集的成员不再重复出现在自动合集里；
  · 自动合集被搬走一半后不成立（< 2 台）就撤掉，别留「天域 1 台」。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from guard import protect_user_data  # noqa: E402

protect_user_data()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import (QEventLoop, QMetaObject, QObject, QTimer,  # noqa: E402
                            QUrl, Q_ARG)
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

import app.servers as S  # noqa: E402
from app.core import Core  # noqa: E402
from app.util import ROOT as APP_ROOT  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def skip(name, why=""):
    print(f"  skip  {name}" + (f"  {why}" if why else ""))


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def to_py(v):
    """QML 的 var 属性取出来可能是 QJSValue，统一转成 Python 对象。"""
    if hasattr(v, "toVariant"):
        v = v.toVariant()
    return v


def main():
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda ws: [warnings.append(w.toString()) for w in ws])
    qml_dir = os.path.join(APP_ROOT, "qml")
    engine.addImportPath(qml_dir)
    engine.addImportPath(os.path.join(qml_dir, "components"))
    core = Core(app)
    engine.rootContext().setContextProperty("core", core)
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
    if not engine.rootObjects():
        print("QML 加载失败")
        for w in warnings[:10]:
            print("   ", w)
        return 1
    win = engine.rootObjects()[0]
    win.show()
    spin(800)

    page = win.findChild(QObject, "serversPage")
    check("找到 serversPage", page is not None)
    if page is None:
        return 1

    # ============================================================ 一、扫描勾选
    print("=== 一、扫描结果：全不选 → 再勾选 → 保存 ===")

    src = open(os.path.join(APP_ROOT, "qml", "components", "ServersPage.qml"),
               encoding="utf-8").read()
    # ① 源码层面：**delegate 里**不能再有「原地改再赋回」的写法。
    #    注意要精确定位到那个 CheckBox —— 文件里 "scanCheck" 还出现在
    #    属性声明、函数体里，全文或首次匹配都会抓错地方（这里踩了两次）。
    chk_i = src.find("checked: page.scanChecked[modelData.addr]")
    scan_delegate = src[max(0, chk_i - 500): chk_i + 500] if chk_i > 0 else ""
    check("找到扫描结果的勾选框", chk_i > 0)
    check("扫描勾选不再原地改对象",
          "var sel = page.scanChecked" not in scan_delegate,
          "delegate 里应调 toggleScanOne(addr, on)")
    check("delegate 改成调 toggleScanOne",
          "toggleScanOne(modelData.addr" in scan_delegate, scan_delegate[-160:])
    check("有 toggleScanOne 函数", "function toggleScanOne(" in src)
    # ② 它必须建新对象（和主列表 toggleChecked 一个写法）
    i = src.find("function toggleScanOne(")
    body = src[i:i + 700] if i > 0 else ""
    check("toggleScanOne 先建新对象", "var next = ({}" in body, body[:80])

    # ③ 真实操作序列
    fake = [{"addr": f"6.6.6.{i}:27015", "name": f"T{i}", "mapName": "c1",
             "mapTitle": "t", "chapter": "c1", "players": i, "maxPlayers": 8,
             "ms": 20, "modeLabel": "战役"} for i in (1, 2, 3)]
    QMetaObject.invokeMethod(page, "onScanFinished", Q_ARG("QVariant", fake))
    spin(400)
    btn = win.findChild(QObject, "srvScanStartBtn")
    check("找到保存按钮", btn is not None)
    if btn is None:
        return 1
    check("扫描完默认全选：按钮可用", btn.property("enabledBtn") is True)

    QMetaObject.invokeMethod(page, "toggleScanAll", Q_ARG("QVariant", False))
    spin(300)
    check("全不选后按钮变灰", btn.property("enabledBtn") is False)

    # ★ 这一句就是用户报的场景：勾一台，按钮必须重新亮起来
    QMetaObject.invokeMethod(page, "toggleScanOne",
                             Q_ARG("QVariant", "6.6.6.2:27015"),
                             Q_ARG("QVariant", True))
    spin(400)
    check("全不选后再勾选：按钮重新可用",
          btn.property("enabledBtn") is True,
          "（以前是 False —— 原地改不发信号，按钮永远灰）")
    check("勾选状态只留这一台",
          to_py(page.property("scanChecked")) == {"6.6.6.2:27015": True},
          to_py(page.property("scanChecked")))

    before = len(core.servers.servers or [])
    QMetaObject.invokeMethod(page, "saveScanPicked")
    spin(600)
    addrs = [str(s.get("addr") or "") for s in (core.servers.servers or [])]
    added = [a for a in addrs if a.startswith("6.6.6.")]
    check("保存只加勾中的那一台", added == ["6.6.6.2:27015"], added)
    check("收藏数 +1", len(addrs) == before + 1, f"{before} → {len(addrs)}")

    # ============================================================ 二、自建合集
    print("\n=== 二、自建合集 ===")
    mgr = core.servers
    for fn in ("createCollection", "renameCollection", "deleteCollection",
               "moveToCollection"):
        check(f"后端有 {fn}", hasattr(mgr, fn))
    check("后端有 collections 属性", "collections" in dir(mgr))

    # 界面对象
    check("有「新建合集」按钮",
          win.findChild(QObject, "srvNewCollectionBtn") is not None)
    check("有「转到合集」按钮",
          win.findChild(QObject, "srvSelMoveBtn") is not None)
    check("有转移弹窗", win.findChild(QObject, "srvMoveDlg") is not None)
    check("有合集右键菜单", win.findChild(QObject, "srvColMenu") is not None)

    # 新建（走界面的函数，链路才算真的通）
    QMetaObject.invokeMethod(page, "openCollectionDialog",
                             Q_ARG("QVariant", ""), Q_ARG("QVariant", ""),
                             Q_ARG("QVariant", ""))
    spin(300)
    check("新建弹窗打开了", page.property("renameOpen") is True)
    check("处于新建模式", page.property("renameIsCustom") is True)
    page.setProperty("renameLabel", "回归测试合集")
    QMetaObject.invokeMethod(page, "applyCollectionDialog")
    spin(400)
    cols = to_py(page.property("collectionList")) or []
    check("合集建出来了", len(cols) == 1, cols)
    check("名字正确", cols and cols[0].get("label") == "回归测试合集")
    cid = (cols[0].get("id") if cols else "") or ""
    check("新建后自动切到该合集",
          str(page.property("groupKey") or "") == "c:" + cid)

    # 重名不让建
    r = mgr.createCollection("回归测试合集")
    check("重名不让建", r.get("ok") is False, r)

    # 转移
    rows = to_py(page.property("visibleServers")) or []
    addrs = [r.get("addr") for r in rows][:2]
    if len(addrs) >= 2:
        page.setProperty("checked", {a: True for a in addrs})
        QMetaObject.invokeMethod(page, "moveCheckedToCollection",
                                 Q_ARG("QVariant", cid))
        spin(400)
        got = [c for c in (to_py(page.property("collectionList")) or [])
               if c.get("id") == cid]
        check("服务器转移进合集", bool(got) and got[0].get("count") == len(addrs),
              got[0].get("count") if got else None)
    else:
        skip("服务器转移进合集", "列表里不足 2 台")

    # 转移语义：移到第二个合集后，第一个里就不该再有它
    r2 = mgr.createCollection("第二个合集")
    cid2 = r2.get("id")
    if addrs:
        moved = addrs[0]
        mgr.moveToCollection([moved], cid2)
        col1 = next((c for c in mgr.collections if c["id"] == cid), {})
        check("转移是「移走」不是「复制」",
              moved not in (col1.get("addrs") or []), col1.get("addrs"))

    # 删合集不删服务器
    n_before = mgr.serverCount
    mgr.deleteCollection(cid2)
    check("删合集不动服务器", mgr.serverCount == n_before,
          f"{n_before} → {mgr.serverCount}")

    # 自建合集的成员不重复出现在自动合集里。
    # ★ 只看**真正的自动合集**（kind = name / ip / manual）；
    #   「未分类」（kind = none）恰恰是「没被任何合集收走」的那些，
    #   把它算进来会误报 —— 第一次就踩了这个坑。
    auto_kinds = ("name", "ip", "manual")
    auto_addrs = set()
    for g in (mgr.groups or []):
        if g.get("kind") in auto_kinds:
            auto_addrs.update(g.get("addrs") or [])
    col1 = next((c for c in mgr.collections if c["id"] == cid), {})
    members = [a for a in (col1.get("addrs") or [])]
    dup = [a for a in members if a in auto_addrs]
    check("自建成员不重复出现在自动合集", not dup, dup)

    # 落盘
    check("合集写进了 config",
          isinstance(mgr.config["server_collections"], list)
          and any(c.get("label") == "回归测试合集"
                  for c in mgr.config["server_collections"]),
          mgr.config["server_collections"])

    # ★ 桩 config 是普通 dict 时（`friends_test` 就是这种），
    #   缺 `server_collections` 键不能把 groups 炸掉 —— 那会让服务器页白屏。
    #   这个坑真的踩到过：KeyError 直接把 groups 属性抛穿。
    print("  -- 缺键的桩 config 不能崩 --")

    class _OldCfg(dict):
        def save(self):
            pass

    class _Fake:
        config = _OldCfg({"servers": []})   # 故意不放 server_collections
        serversChanged = None

        def _merged(self):
            return []

    got = S.ServerManager._collections(_Fake())
    check("缺键时返回空列表而不是抛 KeyError", got == [], got)

    # 清理
    mgr.deleteCollection(cid)

    # ============================================================ QML 告警
    print("\n=== 三、QML 告警 ===")
    bad = [w for w in warnings if "Fixedsys" not in w and "TypeError" not in w]
    check("无可疑告警", not bad, f"{len(bad)} 条")
    for w in bad[:5]:
        print("      ", w)

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：" + " / ".join(FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())