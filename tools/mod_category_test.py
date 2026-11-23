# -*- coding: utf-8 -*-
"""「手动指定 MOD 分类」的回归。

## 为什么要有这个功能

用户原话：**「添加 MOD 详情可以自定义分类的功能，防止文件判断错误和标签不符合」**。

自动分类靠三样东西猜：工坊 tag（作者自己勾的）、标题关键词、VPK 内部路径。
三样都会错，而且错得很有规律：

| 情况 | 自动判断的结果 | 实际 |
| --- | --- | --- |
| 「Zombie Slayer Rifle」 | 感染者（命中 zombie） | 武器 |
| 「Survivor Weapon Pack」（tag 含 Survivors） | 生还者 | 武器 |
| 作者只勾了 `Miscellaneous` 的武器 | 其他 | 武器 |
| 本地 MOD 没有 tag | 只能靠文件名猜 | 常常错 |

规则越加越容易误伤（改一条可能弄坏十条），所以正确解法是：
**自动结果当默认值，用户改过的以用户为准，并且记住。**

## 这个测试盯什么

1. 手动指定后，分类和显示名都变、并且 `categoryManual` 为真
2. **重新扫描 / 重启之后仍然生效**（落盘在 modcategories.json）
3. 「恢复自动判断」能删掉覆盖、回到自动值
4. 自建分类：新建 / 归类到它 / 改名 / 删除（删除后 MOD 回到自动分类）
5. 内置分类不允许改名/删除（它们有固定含义）
6. 按分类筛选时改分类，列表要跟着重筛（不然看着像没反应）
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import modmanager as MM  # noqa: E402
from app import mods as M  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def make_mod(i: int, title: str, wid: str = "", stem: str = "") -> dict:
    """造一条扫盘结果的形状（够 _decorate 用就行）。

    ★ 标题只能通过 `stem` 给：`_decorate` 的起点就是 `m["stem"]`
      （没有工坊元数据时标题 = 文件名去掉扩展名），传个单独的 title
      字段它是不认的 —— 这一点是实测出来的，别想当然。
    """
    stem = stem or f"mod{i}"
    return {
        "path": os.path.join("C:\\fake\\addons", f"{stem}.vpk"),
        "name": f"{stem}.vpk",
        "stem": title or stem,
        "size": 1024 * 1024,
        "sizeText": "1.0 MB",
        "mtime": 1700000000,
        "workshopId": wid,
    }


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])

    tmp = tempfile.mkdtemp(prefix="l4d2_cat_")
    old_meta = MM.CATEGORY_OVERRIDE_PATH
    old_fav = MM.FAV_PATH
    MM.CATEGORY_OVERRIDE_PATH = os.path.join(tmp, "modcategories.json")
    MM.FAV_PATH = os.path.join(tmp, "favorites.json")

    try:
        mgr = MM.ModManager()
        meta: dict = {}

        # 造四条：一条会把武器误判成感染者的、一条本地无 tag 的、
        # 一条工坊的正常武器、一条地图。
        rows = [
            make_mod(1, "Zombie Slayer Rifle", wid="111111"),
            make_mod(2, "SomeLocalPack", stem="SomeLocalPack"),
            make_mod(3, "AK47 Replacer", wid="333333"),
            make_mod(4, "Dead Center Campaign", wid="444444"),
        ]
        decorated = [mgr._decorate(m, meta, is_local=not m["workshopId"])
                     for m in rows]
        mgr._all_local = [x for x in decorated if not x.get("workshopId")]
        mgr._all_workshop = [x for x in decorated if x.get("workshopId")]
        mgr._apply_filter()

        by_title = {m.get("title") or m.get("stem"): m for m in decorated}

        # ---------------------------------------------------- 1. 自动分类的错
        print("=== 1. 先确认「自动判断确实会错」（这是要解决的问题本身）===")
        slayer = next(m for m in decorated if "Zombie Slayer" in (m.get("title") or ""))
        check("「Zombie Slayer Rifle」被自动判成感染者（典型的误判）",
              slayer.get("category") == "infected",
              slayer.get("category"))
        check("记录下自动判断的结果供恢复用",
              slayer.get("categoryAuto") == "infected",
              slayer.get("categoryAuto"))
        check("默认没有手动标记", slayer.get("categoryManual") is False)

        # ---------------------------------------------------- 2. 手动改成武器
        print("=== 2. 手动指定分类 ===")
        r = mgr.setModCategory(slayer["path"], "weapon")
        check("setModCategory 成功", r.get("ok") is True, str(r))
        check("返回的显示名是武器", r.get("label") == "武器", str(r.get("label")))
        now = mgr._find_mod(slayer["path"])
        check("内存里的分类改了", now.get("category") == "weapon", now.get("category"))
        check("显示名改了", now.get("categoryLabel") == "武器",
              now.get("categoryLabel"))
        check("标记成手动", now.get("categoryManual") is True)
        check("自动判断的原值还留着（恢复时要用）",
              now.get("categoryAuto") == "infected", now.get("categoryAuto"))

        # ---------------------------------------------------- 3. 落盘 + 重启还在
        print("=== 3. 记住：重启 / 重新扫描之后仍然生效 ===")
        check("覆盖文件写出来了", os.path.isfile(MM.CATEGORY_OVERRIDE_PATH))
        saved = json.load(open(MM.CATEGORY_OVERRIDE_PATH, encoding="utf-8"))
        check("文件里存的是 分类key → 覆盖值",
              saved.get(slayer.get("catKey")) == "weapon",
              str(saved)[:120])

        mgr2 = MM.ModManager()
        d2 = [mgr2._decorate(m, meta, is_local=not m["workshopId"]) for m in rows]
        s2 = next(m for m in d2 if "Zombie Slayer" in (m.get("title") or ""))
        check("新实例重新扫描后仍是用户指定的武器",
              s2.get("category") == "weapon", s2.get("category"))
        check("新实例也知道这是手动指定的",
              s2.get("categoryManual") is True)

        # ---------------------------------------------------- 4. 恢复自动
        print("=== 4. 恢复自动判断 ===")
        r = mgr.clearModCategory(slayer["path"])
        check("clearModCategory 成功", r.get("ok") is True, str(r))
        back = mgr._find_mod(slayer["path"])
        check("回到自动判断的感染者", back.get("category") == "infected",
              back.get("category"))
        check("手动标记清掉", back.get("categoryManual") is False)
        saved = json.load(open(MM.CATEGORY_OVERRIDE_PATH, encoding="utf-8"))
        check("覆盖记录从文件里删掉了",
              slayer.get("catKey") not in saved, str(saved)[:120])

        # ---------------------------------------------------- 5. 自建分类
        print("=== 5. 自建分类：新建 / 归类 / 改名 / 删除 ===")
        r = mgr.createCategory("我的常用武器")
        check("新建分类成功", r.get("ok") is True, str(r))
        ckey = r.get("key")
        check("key 带 u_ 前缀（和内置分类区分开）",
              str(ckey).startswith(MM.CUSTOM_CAT_PREFIX), str(ckey))
        check("出现在分类清单里",
              any(x["key"] == ckey for x in mgr.categoryChoices))
        check("自建分类标记了 custom",
              any(x["key"] == ckey and x["custom"] for x in mgr.categoryChoices))

        r2 = mgr.createCategory("我的常用武器")
        check("重名不重复创建（复用已有的）",
              r2.get("ok") is True and r2.get("key") == ckey and r2.get("existed"),
              str(r2))

        r3 = mgr.createCategory("   ")
        check("空名字被拒绝", r3.get("ok") is False, str(r3))

        ak = next(m for m in mgr._all_workshop if "AK47" in (m.get("title") or ""))
        r4 = mgr.setModCategory(ak["path"], ckey)
        check("能把 MOD 归到自建分类", r4.get("ok") is True, str(r4))
        check("显示名是用户起的那个",
              r4.get("label") == "我的常用武器", str(r4.get("label")))

        # 侧边栏计数里要出现这一栏
        counts = mgr.categoryCounts
        custom_row = next((c for c in counts if c["key"] == ckey), None)
        check("侧边栏出现了自建分类这一栏", custom_row is not None, str(counts))
        check("自建分类计数正确", custom_row and custom_row["count"] == 1,
              str(custom_row))
        check("内置分类排在自建分类前面",
              counts[0]["key"] in M.CATEGORY_LABELS, str(counts[0]))

        r5 = mgr.renameCategory(ckey, "二次元人物")
        check("能改名", r5.get("ok") is True, str(r5))
        ak2 = mgr._find_mod(ak["path"])
        check("改名后已归类的 MOD 显示名跟着变",
              ak2.get("categoryLabel") == "二次元人物",
              ak2.get("categoryLabel"))

        r6 = mgr.renameCategory("weapon", "乱改")
        check("内置分类不给改名", r6.get("ok") is False, str(r6))
        r7 = mgr.deleteCategory("weapon")
        check("内置分类不给删除", r7.get("ok") is False, str(r7))

        # 正筛着这个分类时删掉它：筛选要自动清掉，否则列表空着出不来
        mgr.setCategory(ckey)
        check("先筛到这个自建分类", mgr.categoryFilter == ckey)
        r8 = mgr.deleteCategory(ckey)
        check("删除自建分类成功", r8.get("ok") is True, str(r8))
        check("删除后筛选自动清空（否则列表会空着）",
              mgr.categoryFilter == "", mgr.categoryFilter)
        ak3 = mgr._find_mod(ak["path"])
        check("归在它下面的 MOD 回到自动分类（没被删）",
              ak3 is not None and ak3.get("categoryManual") is False,
              ak3.get("category") if ak3 else "None")
        check("MOD 还在列表里", len(mgr._all_workshop) > 0)

        # ---------------------------------------------------- 6. 筛选联动
        print("=== 6. 按分类筛着的时候改分类，列表要跟着重筛 ===")
        mgr.setCategory("weapon")
        before = mgr.totalCount
        # 把一条武器改成地图 → 它应该从「武器」这个分类里消失
        wep = next((m for m in mgr._all_workshop if m.get("category") == "weapon"), None)
        check("筛选后列表里确实有武器", wep is not None and before > 0,
              f"count={before}")
        if wep is not None:
            mgr.setModCategory(wep["path"], "map")
            after = mgr.totalCount
            check("改完分类后当前筛选的列表跟着变少", after == before - 1,
                  f"{before} -> {after}")
            gone = all(m.get("category") == "weapon"
                       for m in mgr._all.items())
            check("被改走的那条已经不在「武器」列表里", gone)
            mgr.clearModCategory(wep["path"])

        # ---------------------------------------------------- 7. QML 接线
        print("=== 7. 详情面板接线（源码断言）===")
        mp = open(os.path.join(ROOT, "qml", "components", "ModPanel.qml"),
                  encoding="utf-8").read()
        check("分类徽标可点", 'objectName: "modCategoryBadge"' in mp)
        check("点徽标打开选择器", "page.openCategoryPicker()" in mp)
        check("选择器存在", 'objectName: "catPicker"' in mp)
        check("选择器用 categoryChoices 铺开", "mgr.categoryChoices" in mp)
        check("选中当前分类会高亮", "page.qSelected.category || \"\"" in mp)
        check("有「新建并归类」", 'objectName: "catCreateBtn"' in mp)
        check("有「恢复自动判断」", 'objectName: "catRestoreBtn"' in mp)
        check("手动指定过的徽标带笔尖标记", "categoryManual ? \"  \\uE70F\"" in mp)
        check("改分类调的是 setModCategory", "mgr.setModCategory(" in mp)
        check("恢复调的是 clearModCategory", "mgr.clearModCategory(" in mp)

        # 分类徽标必须能被点到：以前工坊「重新加载」就被 GridView 盖住过
        check("徽标挂了 MouseArea", "catMa" in mp and "onClicked: page.openCategoryPicker()" in mp)

    finally:
        MM.CATEGORY_OVERRIDE_PATH = old_meta
        MM.FAV_PATH = old_fav

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
