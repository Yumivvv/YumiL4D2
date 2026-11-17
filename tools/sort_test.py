# -*- coding: utf-8 -*-
"""检查第九轮新增的三件事：排序、可选更新、检查不跳顶。

跑法：python tools\\sort_test.py
不碰真实文件，只读。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# 会构造真的 ModManager（读配置、写收藏），数据目录先隔离到临时沙盒
from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from PySide6.QtCore import QCoreApplication  # noqa: E402

app = QCoreApplication(sys.argv)

from app import mods as M  # noqa: E402
from app.modmanager import ModManager  # noqa: E402

mm = ModManager()
mm.setAddonsDir(mm.auto_detect() or "")
mm.scan()
for _ in range(200):
    app.processEvents()
    if mm.scanned and not mm.busy:
        break
    time.sleep(0.1)

problems = []
total = mm.totalCount
print("total =", total)

# ---- 1) 排序模式
rows = [mm.allModel.items()[i] for i in range(mm.allModel.rowCount())]
first_path = rows[0]["path"]


def titles():
    return [mm.allModel.items()[i]["title"] for i in range(mm.allModel.rowCount())]


for mode in (0, 1, 2, 3, 4):
    mm.setSortMode(mode)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    if mm.sortMode != mode:
        problems.append(f"sortMode 没生效：想要 {mode} 得到 {mm.sortMode}")
    items = [mm.allModel.items()[i] for i in range(mm.allModel.rowCount())]
    if len(items) != total:
        problems.append(f"排序 {mode} 之后总数从 {total} 变成 {len(items)}")
    # mode 2 是「优先看禁用」，其余都要求未启用沉底
    if mode != 2:
        seen_disabled = False
        for m in items:
            if not m.get("enabled"):
                seen_disabled = True
            elif seen_disabled:
                problems.append(f"排序 {mode}：未启用的没有沉底")
                break
    print(f"  排序 {mode} 首项 = {items[0]['title'][:40]}")

# 字母排序（mode 4）应该真的是按标题升序 —— 但前提是「未启用沉底」这条规则
# 优先级更高，所以整张表会被切成「启用段 + 未启用段」两块，
# 要求的是**每一段内部**升序，而不是全表（有禁用 MOD 时全表必然不是升序）。
mm.setSortMode(4)
app.processEvents()
rows4 = mm.allModel.items()
titles4 = [x["title"].lower() for x in rows4]
ens4 = [bool(x.get("enabled", True)) for x in rows4]
cut = ens4.index(False) if False in ens4 else len(ens4)
seg_on, seg_off = titles4[:cut], titles4[cut:]
if seg_on != sorted(seg_on):
    problems.append("字母排序：启用段不是升序")
elif seg_off != sorted(seg_off):
    problems.append("字母排序：未启用段不是升序")
elif any(not e for e in ens4[:cut]):
    problems.append("字母排序：启用的后面又混进了未启用")
else:
    print(f"  字母排序：启用段 {len(seg_on)} 个升序 OK，未启用段 {len(seg_off)} 个沉底 OK")

mm.setSortMode(0)
app.processEvents()

# ---- 2) 可选更新判定
# 全部 MOD 都是新拷进来的，真实数据里没有可更新的，所以这里伪造一个更早的 mtime
sample = None
for i in range(mm.allModel.rowCount()):
    it = mm.allModel.items()[i]
    if it.get("workshopId") and it.get("updatedTs"):
        sample = it
        break
if sample is None:
    problems.append("找不到带工坊时间的 MOD，没法验可更新")
else:
    wid = sample["workshopId"]
    up = int(sample["updatedTs"])
    fake = mm._decorate(
        {
            "path": sample["path"], "name": sample["name"], "stem": sample["stem"],
            "dir": os.path.dirname(sample["path"]), "size": sample["size"],
            "sizeText": sample["sizeText"], "mtime": up - 3 * 86400,
            "image": "", "workshopId": wid, "isWorkshop": True,
            "inWorkshopDir": False, "enabled": True,
        },
        mm._wsc._meta, is_local=True,
    )
    print(f"  伪造 3 天前的本地文件，工坊更新于 {fake['updatedText']}")
    print(f"  hasUpdate = {fake['hasUpdate']}  updateText = {fake['updateText']}")
    if fake["hasUpdate"] is not True:
        problems.append("工坊时间比本地新时 hasUpdate 没变成 True")
    # 反过来：本地比工坊新，不该提示
    newer = mm._decorate(
        {
            "path": sample["path"], "name": sample["name"], "stem": sample["stem"],
            "dir": os.path.dirname(sample["path"]), "size": sample["size"],
            "sizeText": sample["sizeText"], "mtime": up + 3 * 86400,
            "image": "", "workshopId": wid, "isWorkshop": True,
            "inWorkshopDir": False, "enabled": True,
        },
        mm._wsc._meta, is_local=True,
    )
    if newer["hasUpdate"] is not False:
        problems.append("本地比工坊新时还是提示可更新")

# ---- 3) 「检查 MOD 文件」不该把列表弹回顶部
mm.setSortMode(0)
app.processEvents()
before = [mm.allModel.items()[i]["path"] for i in range(mm.allModel.rowCount())]
mm._apply_meta_to_items()
after = [mm.allModel.items()[i]["path"] for i in range(mm.allModel.rowCount())]
if before != after:
    problems.append("_apply_meta_to_items 之后列表顺序变了（会跳回顶部）")
else:
    print(f"  检查后列表顺序不变（{len(after)} 行）")

# ---- 4) 状态筛选 5 = 可更新
mm.setStatusFilter(5)
app.processEvents()
if mm.statusFilter != 5:
    problems.append("setStatusFilter(5) 没生效")
n5 = mm.localCount
mm.setStatusFilter(0)
app.processEvents()
print(f"  「可更新」筛选：真实数据 {n5} 个（本地文件都比工坊新，0 是正常的）")

# ---- 5) 旧接口应该已经没了
if hasattr(mm, "setStateFilter") or hasattr(mm, "stateFilter"):
    problems.append("旧的 stateFilter 接口还在")

# ---- 6) 用临时目录验证「未启用沉底」在真混合数据下成立
import tempfile  # noqa: E402

tmp = tempfile.mkdtemp(prefix="l42d_sort_")
addons = os.path.join(tmp, "left4dead2", "addons")
os.makedirs(addons)
for name in ("aaa.vpk", "bbb.vpk", "ccc.vpk", "ddd.vpk"):
    with open(os.path.join(addons, name), "wb") as fh:
        fh.write(b"\0" * 4096)
os.rename(os.path.join(addons, "bbb.vpk"), os.path.join(addons, "bbb.vpk.disabled"))
os.rename(os.path.join(addons, "ccc.vpk"), os.path.join(addons, "ccc.vpk.disabled"))

mm.setAddonsDir(addons)
mm.scan()
for _ in range(100):
    app.processEvents()
    if mm.scanned and not mm.busy:
        break
    time.sleep(0.1)

if mm.totalCount != 4:
    problems.append(f"临时目录应该有 4 个 MOD，实际 {mm.totalCount}")
else:
    for mode in (0, 1, 3, 4):
        mm.setSortMode(mode)
        app.processEvents()
        seq = [mm.allModel.items()[i]["enabled"] for i in range(mm.allModel.rowCount())]
        if seq != [True, True, False, False]:
            problems.append(f"排序 {mode} 混合数据下未启用没沉底：{seq}")
    # 优先看禁用要反过来
    mm.setSortMode(2)
    app.processEvents()
    seq = [mm.allModel.items()[i]["enabled"] for i in range(mm.allModel.rowCount())]
    if seq != [False, False, True, True]:
        problems.append(f"排序 2（优先看禁用）不对：{seq}")
    if not problems:
        print("  混合数据（2 启用 + 2 未启用）：各排序都正确")

# 收尾：把临时目录删掉，恢复真实目录
mm.setAddonsDir(mm.auto_detect() or "")
mm.scan()
for _ in range(200):
    app.processEvents()
    if mm.scanned and not mm.busy:
        break
    time.sleep(0.1)
import shutil  # noqa: E402

shutil.rmtree(tmp, ignore_errors=True)

mm.shutdown()

if problems:
    print("\n".join("FAIL " + p for p in problems))
    print("SORT_TEST_FAILED")
    sys.exit(1)
print("SORT_TEST_OK")
