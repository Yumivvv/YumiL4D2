"""删除 MOD 之后列表要立刻刷新（不靠异步扫盘）+ 封面缓存一起清掉。

为什么单独盯这个：
  * `scan()` 在 `_busy` 的时候会被整个丢掉（正好在扫盘就白删），
    而且整表重建会把列表滚回顶部；
  * 所以删除后走 `_forget_paths()` 立刻摘行，`scan()` 只是兜底。
  * `data/modcache/<ID>.jpg` 是工坊封面缓存，MOD 删了那张图也没人认领了。
"""
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import protect_user_data  # noqa: E402

protect_user_data()

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import Core  # noqa: E402
from app import mods as M  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def wait(app, ms: int) -> None:
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_idle(app, mgr, ms: int = 8000) -> None:
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        if not mgr.busy:
            return
        time.sleep(0.02)


def wait_until(app, cond, ms: int = 12000) -> bool:
    """等条件成立（扫盘是后台线程，固定 sleep 容易撞上还没扫完）。"""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        try:
            if cond():
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.05)
    return False


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    core = Core(app)
    mgr = core.mods

    tmp = tempfile.mkdtemp(prefix="l4d2_del_")
    addons = os.path.join(tmp, "left4dead2", "addons")
    os.makedirs(addons, exist_ok=True)
    wid = "3727891945"
    path = os.path.join(addons, f"{wid}.vpk")
    with open(path, "wb") as f:
        f.write(b"x" * 4096)
    # 同名封面图（companion_files 会连它一起删）
    side = os.path.join(addons, f"{wid}.jpg")
    with open(side, "wb") as f:
        f.write(b"i" * 2048)
    # 工坊封面缓存（modcache 里那张，也要一起清）
    os.makedirs(M.CACHE_DIR, exist_ok=True)
    cached = os.path.join(M.CACHE_DIR, f"{wid}.jpg")
    with open(cached, "wb") as f:
        f.write(b"i" * 2048)

    mgr.setDeleteToRecycle(False)          # 直接删，测试跑完不留回收站垃圾
    # Core() 一启动会先把用户真实 addons 目录扫一遍（guard 只隔离 data/，
    # 配置里那个目录还是用户自己的），所以要等它扫完再换成沙盒目录。
    wait_idle(app, mgr)
    wait(app, 300)
    mgr.setAddonsDir(addons)
    wait_idle(app, mgr)
    ok = wait_until(app, lambda: mgr.totalCount == 1)
    wait(app, 300)
    print("=== 1. 删除前 ===")
    check("沙盒里的 MOD 已经列出来", ok and mgr.totalCount == 1, str(mgr.totalCount))
    item = (mgr._all_local + mgr._all_workshop)[0]
    check("认出了工坊 ID", item.get("workshopId") == wid, str(item.get("workshopId")))
    check("列表里带封面（同名图）", bool(item.get("hasImage")))

    print()
    print("=== 2. deleteOne 之后列表要立刻少一行 ===")
    toasts: list[tuple] = []
    # 删除提示是 ModManager 自己发的（toast_level_test 也是听这个）
    mgr.toastRequested.connect(lambda t, l: toasts.append((t, l)))
    mgr.deleteOne(path)
    # 故意**不**等扫盘：_forget_paths 是同步的，扫盘是异步兜底
    check("删完当场就从列表里消失", mgr.totalCount == 0, str(mgr.totalCount))
    check("文件真没了", not os.path.exists(path))
    check("同名封面图一起走了", not os.path.exists(side))
    check("工坊封面缓存也清了", not os.path.exists(cached))
    wait(app, 400)          # toast 是排队的，等事件循环走一轮再看
    check("有删除提示", bool(toasts), str(toasts))

    print()
    print("=== 3. 批量删除也一样 ===")
    for n in ("3727891946.vpk", "3727891947.vpk"):
        with open(os.path.join(addons, n), "wb") as f:
            f.write(b"x" * 1024)
    # 同一个目录再 setAddonsDir 会被 early-return（没变），所以显式重扫
    mgr.scan()
    wait_idle(app, mgr)
    ok3 = wait_until(app, lambda: mgr.totalCount == 2)
    check("两个 MOD 都在", ok3 and mgr.totalCount == 2, str(mgr.totalCount))
    mgr.checkAllLocal(True)
    mgr.deleteCheckedOfTab()
    check("批量删完当场清空", mgr.totalCount == 0, str(mgr.totalCount))

    mgr.setDeleteToRecycle(True)

    print()
    print("=== 4. 下完的工坊 MOD 能自动补上标题和封面 ===")
    # 文件名已经是 <ID>.vpk（download() 就是这么存的），管理器认 ID；
    # 但标题和封面要 _after_download() 去工坊问一次、下到 modcache/ 才有。
    path4 = os.path.join(addons, f"{wid}.vpk")
    with open(path4, "wb") as f:
        f.write(b"x" * 4096)
    # modcache 里那张封面刚才被删了，正好从零开始
    mgr.scan()
    wait_idle(app, mgr)
    wait_until(app, lambda: mgr.totalCount == 1)
    row = (mgr._all_local + mgr._all_workshop)[0] if mgr.totalCount else {}
    check("下完先认出工坊 ID", row.get("workshopId") == wid, str(row.get("workshopId")))
    check("还没补元数据时没有封面", not row.get("hasImage"))

    mgr._after_download([{"id": wid}])
    wait(app, 300)
    try:
        with open(M.META_PATH, encoding="utf-8") as f:
            info = (json.load(f) or {}).get(wid) or {}
    except Exception:  # noqa: BLE001
        info = {}
    row2 = (mgr._all_local + mgr._all_workshop)[0] if mgr.totalCount else {}
    if info:
        check("modmeta 里补上了标题", bool(info.get("title")), str(info.get("title"))[:40])
        check("列表里的标题不再是那串数字",
              row2.get("title") not in ("", wid, f"{wid}.vpk"),
              str(row2.get("title"))[:40])
        check("封面下到了 modcache/", os.path.exists(cached)
              or bool(row2.get("hasImage")),
              f"hasImage={row2.get('hasImage')} file={os.path.exists(cached)}")
    else:
        print("      [skip] 工坊元数据没查成（网络或接口问题），只验证命名与摘行")

    mgr.deleteOne(path4)
    check("这一步建的文件也删掉了", not os.path.exists(path4))

    shutil.rmtree(tmp, ignore_errors=True)
    try:
        if os.path.exists(cached):
            os.remove(cached)
    except OSError:
        pass

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    code = main()
    QTimer.singleShot(0, QCoreApplication.quit)
    sys.exit(code)
