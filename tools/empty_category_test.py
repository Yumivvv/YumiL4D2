# -*- coding: utf-8 -*-
"""「0 个 MOD 的分类不显示，导致找不到删除/改名入口」的回归。

## 用户报的

> 找不到删除和重命名的选项
> MOD管理器修复0个分类导致不显示该分类的问题

## 根因

`categoryCounts` 对所有分类都套了「有内容才显示」：

```python
for row in self._custom_categories:
    n = tally.get(key, 0)
    if key and n:          # ← 0 个就整行不返回
```

于是：
- 刚建好的空分类，侧边栏里**完全看不到**；
- 把某个分类里的 MOD 全删掉 / 全移走之后，这一栏也跟着消失。

而「改名 / 删除」的入口恰恰挂在那一行上 —— 行没了，入口自然找不到。

## 修法

自建分类**即使 0 个也列出来**（`count: 0`）。内置分类保持「有内容才显示」：
11 个全列出来会把侧边栏撑得很长，而且空的内置分类没什么可点。

另外两处配套：
- 点空分类时状态栏说一句「「X」里还没有 MOD」，否则 0 条列表看着像坏了
- 空状态文案区分「这个分类是空的」和「筛选筛没了」
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from app import mods as M  # noqa: E402
from app import modmanager as MM  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    mgr = MM.ModManager()

    # ---------------------------------------------------- 1. 空分类必须可见
    print("=== 1. 刚建好的空分类要出现在 categoryCounts 里 ===")
    r = mgr.createCategory("空分类A")
    check("建分类成功", r.get("ok") is True, str(r))
    k = r.get("key")

    cats = mgr.categoryCounts
    keys = [c["key"] for c in cats]
    check("★ 0 个 MOD 的分类也列出来了", k in keys, str(keys))
    row = next((c for c in cats if c["key"] == k), None)
    check("计数是 0", row is not None and int(row["count"]) == 0,
          row.get("count") if row else None)
    check("名字对", row is not None and row["label"] == "空分类A",
          row.get("label") if row else None)

    # ---------------------------------------------------- 2. 多个空分类
    print("=== 2. 多个空分类都在 ===")
    k2 = mgr.createCategory("空分类B")["key"]
    keys = [c["key"] for c in mgr.categoryCounts]
    check("两个空分类都在", k in keys and k2 in keys, str(keys))

    # ---------------------------------------------------- 3. MOD 移走后仍可见
    print("=== 3. 分类里的 MOD 被移走后，这一栏不许消失 ===")
    fake = {
        "path": os.path.join("C:\\fake\\addons", "emptycat.vpk"),
        "name": "emptycat.vpk", "stem": "Empty Cat Mod",
        "size": 1024, "sizeText": "1.0 KB", "mtime": 1700000000,
        "workshopId": "222222",
    }
    deco = mgr._decorate(fake, {}, is_local=False)
    mgr._all_workshop = [deco]
    mgr._all_local = []
    mgr._apply_filter()
    mgr.setModCategory(deco["path"], k)
    row = next((c for c in mgr.categoryCounts if c["key"] == k), None)
    check("归进 1 个 MOD 后计数是 1", row is not None and row["count"] == 1,
          row.get("count") if row else None)

    # 把 MOD 从分类里清掉（恢复自动分类）→ 这一栏要留在侧边栏
    mgr.clearModCategory(deco["path"])
    cats = mgr.categoryCounts
    row = next((c for c in cats if c["key"] == k), None)
    check("★ MOD 移走后这一栏还在（计数回到 0）",
          row is not None, f"keys={[c['key'] for c in cats]}")
    check("计数回到 0", row is not None and int(row["count"]) == 0,
          row.get("count") if row else None)

    # ---------------------------------------------------- 4. 内置分类规则不变
    print("=== 4. 内置分类仍然「有内容才显示」（不被塞满 11 行）===")
    empty_builtins = [c["key"] for c in mgr.categoryCounts
                      if c["key"] in M.CATEGORY_LABELS and c["count"] == 0]
    check("没有 0 计数的内置分类混进来", not empty_builtins, str(empty_builtins))
    check("内置分类总数没被撑大",
          len([c for c in mgr.categoryCounts if c["key"] in M.CATEGORY_LABELS]) <= 11)

    # ---------------------------------------------------- 5. 能删能改名
    print("=== 5. 空分类照样能删、能改名 ===")
    rn = mgr.renameCategory(k, "改名后的分类")
    check("改名成功", rn.get("ok") is True, str(rn))
    row = next((c for c in mgr.categoryCounts if c["key"] == k), None)
    check("改名后侧边栏名字跟着变",
          row is not None and row["label"] == "改名后的分类",
          row.get("label") if row else None)

    d = mgr.deleteCategory(k)
    check("删空分类成功", d.get("ok") is True, str(d))
    keys = [c["key"] for c in mgr.categoryCounts]
    check("删完从侧边栏消失", k not in keys, str(keys))
    check("另一个空分类还在（没误删）", k2 in keys, str(keys))

    # ---------------------------------------------------- 6. 点空分类有提示
    print("=== 6. 点空分类时状态栏要说话（否则 0 条像坏了）===")
    mgr.setCategory(k2)
    check("筛选切到了那个分类", mgr.categoryFilter == k2, mgr.categoryFilter)
    check("列表是空的", mgr.totalCount == 0, mgr.totalCount)
    st = str(mgr.statusText or "")
    check("状态栏说了「还没有 MOD」", "还没有 MOD" in st, st)

    # ---------------------------------------------------- 7. QML 空状态文案
    print("=== 7. 界面空状态区分「分类是空的」和「筛选筛没了」===")
    qml = open(os.path.join(ROOT, "qml", "components", "ModPanel.qml"),
               encoding="utf-8").read()
    check("有「这个分类里还没有 MOD」这种说法",
          "里还没有 MOD" in qml, "")
    check("用 qCategoryLabel 显示分类名", "page.qCategoryLabel" in qml)
    check("qCategoryLabel 属性存在",
          "readonly property string qCategoryLabel" in qml)

    # ---------------------------------------------------- 8. 后端源码
    print("=== 8. 别再给自建分类加「有内容才显示」===")
    src = open(os.path.join(ROOT, "app", "modmanager.py"),
               encoding="utf-8").read()
    seg = src.split("def categoryCounts", 1)[1][:2000]
    check("自建分类那段没有再 `if n` 过滤",
          "if key and n:" not in seg,
          seg[seg.find("for row in getattr"):][:200].replace("\n", " ")
          if "for row in getattr" in seg else "")

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
