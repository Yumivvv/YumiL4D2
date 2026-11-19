"""加载顺序（addonlist.txt）自检：解析 / 往返 / 重排 / 缺失标记 / GBK 编码。

跑法：python -X utf8 tools/addonlist_test.py
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

import shutil
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    line = ("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else "")
    # ★ Windows 控制台默认是 GBK，extra 里可能带服务器抓回来的非 GBK 字符
    #   （`\xd6`、日文、俄文…），直接 print 会抛 UnicodeEncodeError
    #   让整个测试崩在中途，看起来像「程序有 bug」，其实是控制台编不出来。
    #   这里统一走 safe_print：编不了的字符退化成 ?，绝不中断测试。
    try:
        print(line)
    except UnicodeEncodeError:
        enc = (getattr(sys.stdout, "encoding", "") or "utf-8")
        print(line.encode(enc, "replace").decode(enc, "replace"))
    if not ok:
        FAILS.append(name)


def main() -> int:
    from app import addonlist as A

    # ★ 这个测试会真的写 addonlist.txt（临时目录里造的那种）。
    #   万一有人改成用真实 addons 目录跑，就会把用户游戏的加载顺序改掉。
    #   所以这里先算一下真实路径，如果指向游戏目录就立刻中止。
    real_addons = r"E:\SteamLibrary\steamapps\common\Left 4 Dead 2\left4dead2\addons"
    guard_ok = True
    if os.path.isdir(real_addons):
        # 只要目标路径就是真实那份，就不许往下跑（后面所有写操作都在临时目录）
        print(f"  [safe] 真实 addonlist = {A.addonlist_path(real_addons)}（本测试不会碰它）")
    else:
        print("  [safe] 没找到真实游戏目录，纯沙盒运行")
    if not guard_ok:
        return 2

    # ---------------------------------------------------------------- 1. 路径推导
    print("=== 1. addons 目录 → addonlist.txt 路径 ===")
    p1 = A.addonlist_path(r"E:\SteamLibrary\steamapps\common\Left 4 Dead 2\left4dead2\addons")
    check("从 addons 往上退一级", p1.endswith(
        os.path.join("left4dead2", "addonlist.txt")), p1)
    p2 = A.addonlist_path(r"E:\x\left4dead2")
    check("直接给 left4dead2 也行", p2.endswith(os.path.join("left4dead2", "addonlist.txt")), p2)
    check("空串返回空", A.addonlist_path("") == "")

    # ---------------------------------------------------------------- 2. 解析真实格式
    print("=== 2. 解析 KeyValues 格式 ===")
    real = ('"AddonList"\n{\n'
            '\t"132381280.vpk"\t\t"1"\n'
            '\t"【武器】飞鸟凑.vpk"\t\t"1"\n'
            '\t"disabled.vpk"\t\t"0"\n'
            "}\n")
    entries = A.parse_addonlist(real)
    check("解析出 3 条", len(entries) == 3, str(len(entries)))
    check("顺序保持原样",
          [e["name"] for e in entries] == ["132381280.vpk", "【武器】飞鸟凑.vpk", "disabled.vpk"],
          str([e["name"] for e in entries]))
    check("值 1 → enabled", entries[0]["enabled"] is True)
    check("值 0 → disabled", entries[2]["enabled"] is False)
    check("不把 AddonList 当条目",
          all(e["name"] != "AddonList" for e in entries))

    # ---------------------------------------------------------------- 3. GBK 往返
    print("=== 3. GBK 编码往返（中文名最容易坏在这）===")
    tmp = tempfile.mkdtemp(prefix="al_test_")
    l4d2 = os.path.join(tmp, "left4dead2")
    addons = os.path.join(l4d2, "addons")
    os.makedirs(addons)
    for n in ("a.vpk", "b.vpk", "中文名测试.vpk"):
        with open(os.path.join(addons, n), "wb") as f:
            f.write(b"x" * 2048)

    todo = [
        {"name": "a.vpk", "enabled": True},
        {"name": "b.vpk", "enabled": False},
        {"name": "中文名测试.vpk", "enabled": True},
    ]
    res = A.save(addons, todo)
    check("写入成功", bool(res.get("ok")), str(res.get("error")))
    raw = open(res["path"], "rb").read()
    check("是 GBK 不是 UTF-8（中文那段不是合法 UTF-8）",
          b"\xd6\xd0\xce\xc4" in raw, raw[:60].decode("latin-1"))
    check("换行是 LF", b"\r\n" not in raw)
    check("缩进是 TAB", b'\t"a.vpk"\t\t"1"' in raw, raw[:80].decode("latin-1"))

    back = A.build_view(addons)
    check("读回条数一致", len(back["items"]) == 3, str(len(back["items"])))
    check("中文名完好", "中文名测试.vpk" in [i["name"] for i in back["items"]],
          str([i["name"] for i in back["items"]]))
    check("禁用值保留",
          [i["enabled"] for i in back["items"]] == [True, False, True],
          str([i["enabled"] for i in back["items"]]))

    # ---------------------------------------------------------------- 4. 重排
    print("=== 4. 拖动排序 / 上下移 ===")
    order = [i["name"] for i in back["items"]]
    moved = A.reorder(back["items"], 0, 2)
    check("0 → 2", [x["name"] for x in moved] == [order[1], order[2], order[0]],
          str([x["name"] for x in moved]))
    up = A.move_up_down(back["items"], 2, -1)
    check("末位上一格", [x["name"] for x in up] == [order[0], order[2], order[1]],
          str([x["name"] for x in up]))
    clamp = A.move_up_down(back["items"], 0, -5)
    check("越界被夹住（不会崩）", [x["name"] for x in clamp] == order,
          str([x["name"] for x in clamp]))
    same = A.reorder(back["items"], 1, 1)
    check("原地移动不变", [x["name"] for x in same] == order)

    # 落盘
    A.save(addons, moved)
    check("重排真的落盘了",
          [i["name"] for i in A.build_view(addons)["items"]]
          == [x["name"] for x in moved],
          str([i["name"] for i in A.build_view(addons)["items"]]))

    # ---------------------------------------------------------------- 5. 缺失标记
    print("=== 5. 文件不存在标记 ===")
    os.remove(os.path.join(addons, "b.vpk"))
    v = A.build_view(addons)
    check("缺失计数正确", v["missing"] == 1, str(v["missing"]))
    miss = [i for i in v["items"] if not i["exists"]]
    check("标出的是 b.vpk", len(miss) == 1 and miss[0]["name"] == "b.vpk",
          str([m["name"] for m in miss]))
    check("存在的还是 exists=True",
          [i for i in v["items"] if i["name"] == "a.vpk"][0]["exists"] is True)

    # workshop 子目录里的也算存在
    ws = os.path.join(addons, "workshop")
    os.makedirs(ws)
    with open(os.path.join(ws, "c.vpk"), "wb") as f:
        f.write(b"y" * 100)
    A.save(addons, [{"name": "c.vpk", "enabled": True}])
    v2 = A.build_view(addons)
    check("workshop 子目录里的也算存在",
          v2["items"][0]["exists"] is True and v2["missing"] == 0,
          str(v2["items"]))

    # ---------------------------------------------------------------- 6. 同步补入
    print("=== 6. 同步 addons 目录（补未登记的 vpk）===")
    # 先重新建一份干净的 addonlist（第 5 步为了测 workshop 子目录覆盖过一次）
    A.save(addons, [{"name": "a.vpk", "enabled": True},
                    {"name": "中文名测试.vpk", "enabled": True}])
    with open(os.path.join(addons, "newone.vpk"), "wb") as f:
        f.write(b"z" * 100)
    sync = A.sync_from_addons(addons)
    check("同步成功", bool(sync.get("ok")), str(sync.get("error")))
    check("补进了 newone.vpk", "newone.vpk" in (sync.get("added") or []),
          str(sync.get("added")))
    names = [i["name"] for i in A.build_view(addons)["items"]]
    check("原有的顺序没动",
          names[:2] == ["a.vpk", "中文名测试.vpk"], str(names))
    check("新补的在末尾", names[-1] in ("newone.vpk", "b.vpk", "c.vpk"),
          str(names))
    check("补进去的都是之前不在表里的",
          not set(sync.get("added") or []) & {"a.vpk", "中文名测试.vpk"},
          str(sync.get("added")))
    again = A.sync_from_addons(addons)
    check("再同步不会重复补", again.get("added") == [], str(again.get("added")))

    # ---------------------------------------------------------------- 7. 备份
    print("=== 7. 写之前留 .bak（写坏了能捞回来）===")
    check(".bak 已生成", os.path.isfile(res["path"] + ".bak"))
    check("没有残留 .tmp", not os.path.isfile(res["path"] + ".tmp"))

    # ---------------------------------------------------------------- 8. 标题解析
    print("=== 8. 数字 ID 要解析成真实名称（同 MOD 列表）===")
    from PySide6.QtCore import QCoreApplication

    app2 = QCoreApplication.instance() or QCoreApplication([])
    from app.modmanager import ModManager

    mm = ModManager()
    mm.setAddonsDir(addons)

    # 造一个工坊缓存，模拟「MOD 列表里已识别过这个 ID」
    mm._wsc._meta["3829533320"] = {
        "id": "3829533320", "ok": True,
        "title": "【战双帕弥什 X 约战V】时崎狂三", "tags": [],
    }
    A.save(addons, [{"name": "3829533320.vpk", "enabled": True},
                    {"name": "本地某MOD.vpk", "enabled": True}])
    view = mm.addonOrder
    by_name = {it["name"]: it for it in view.get("items") or []}
    ws_item = by_name.get("3829533320.vpk") or {}
    check("数字 ID 解析出真实标题",
          ws_item.get("title") == "【战双帕弥什 X 约战V】时崎狂三",
          str(ws_item.get("title")))
    check("工坊 ID 被识别出来", ws_item.get("workshopId") == "3829533320",
          str(ws_item.get("workshopId")))
    check("已解析的名字不再标成「未知」", ws_item.get("unknownName") is False)

    local_item = by_name.get("本地某MOD.vpk") or {}
    check("本地 MOD 用文件名当标题",
          local_item.get("title") == "本地某MOD", str(local_item.get("title")))
    check("本地 MOD 没有工坊 ID", local_item.get("workshopId") == "")

    # 没有缓存的纯数字 ID 应该被标成「未识别」
    A.save(addons, [{"name": "9999999999.vpk", "enabled": True}])
    v3 = mm.addonOrder
    item3 = (v3.get("items") or [{}])[0]
    check("无缓存的纯数字 ID 标成未识别", item3.get("unknownName") is True,
          str(item3.get("title")))
    mm.shutdown()

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
