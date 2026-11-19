"""压缩包 → 一键导入 MOD（下载页那颗「导入」按钮的后端）。

造三种真实压缩包（zip / 7z / 只有图片的 zip），每种都放 .vpk + 同名封面
+ 无关文件，验证：
  · inspectTaskArchive 能正确数出 mods / images（只数同名封面）
  · importTaskArchive 只把 .vpk 和**同名封面**导进 addons（无关文件不碰）
  · 同名文件按既有规则**不覆盖**，提示要说「已经有了」而不是「失败」
  · 没有 .vpk 的包要明确说「没东西可导」
  · 坏包 / 不存在的任务要报错不炸

解压后端用 Windows 自带的 `tar.exe`（bsdtar + libarchive，原生认
zip/7z/rar），不依赖 7-Zip 或 WinRAR。
"""
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import json
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

import subprocess
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
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from guard import protect_user_data  # noqa: E402

protect_user_data()

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from app.core import Core  # noqa: E402
from app.downloads import DownloadTask, DONE  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


app = QGuiApplication([])
core = Core(app)
globals()["_KEEP_CORE"] = core
dq = core.downloads

work = tempfile.mkdtemp(prefix="l42d_arctest_")
addons = os.path.join(work, "addons")
src = os.path.join(work, "src")
os.makedirs(src, exist_ok=True)
core.mods._addons_dir = addons      # 假装目录已设置

# --- 造素材：两个 vpk + 各自同名封面 + 一个无关 png + 一个说明文件
for stem in ("weapon_ak47", "skin_knife"):
    with open(os.path.join(src, stem + ".vpk"), "wb") as f:
        f.write(b"fake vpk " + stem.encode())
    with open(os.path.join(src, stem + ".jpg"), "wb") as f:
        f.write(b"fake cover " + stem.encode())
with open(os.path.join(src, "unrelated.png"), "wb") as f:
    f.write(b"not a cover")
with open(os.path.join(src, "readme.txt"), "w", encoding="utf-8") as f:
    f.write("说明文件，不该被导入")

# --- zip（含子目录，验证递归）
zip_path = os.path.join(work, "mods.zip")
with zipfile.ZipFile(zip_path, "w") as zf:
    for name in os.listdir(src):
        zf.write(os.path.join(src, name), "pack/" + name)

# --- 7z（用系统 tar 造）
seven_path = os.path.join(work, "mods.7z")
tar = shutil.which("tar")
subprocess.run([tar, "-c", "-f", seven_path, "-C", src, "."],
               capture_output=True, timeout=60)

# --- 只有图片的包
imgonly_path = os.path.join(work, "images.zip")
with zipfile.ZipFile(imgonly_path, "w") as zf:
    zf.write(os.path.join(src, "unrelated.png"), "a.png")

# --- 坏包
bad_path = os.path.join(work, "broken.7z")
with open(bad_path, "wb") as f:
    f.write(b"this is not an archive at all")


def add_done_task(path: str, title: str) -> str:
    """造一条「已下载完成」的任务，dest 指向给定文件。"""
    t = DownloadTask("pan", title, dest=path, payload={})
    dq._add(t)
    t.status = DONE
    t.done = os.path.getsize(path) if os.path.isfile(path) else 0
    t.total = t.done
    return t.id


print("\n-- 1. 判断「是不是压缩包」", flush=True)
t_zip = add_done_task(zip_path, "mods.zip")
info = dq.inspectTaskArchive(t_zip)
check("zip 认得出来", info.get("isArchive") is True, info)
check("数出 2 个 vpk", info.get("mods") == 2, info.get("mods"))
check("数出 2 张同名封面", info.get("images") == 2, info.get("images"))
check("列出了 vpk 名字", len(info.get("names") or []) == 2, info.get("names"))

t_7z = add_done_task(seven_path, "mods.7z")
info7 = dq.inspectTaskArchive(t_7z)
check("7z 也认得出来（走 bsdtar）", info7.get("isArchive") is True,
      info7.get("error") or info7)
check("7z 里也数出 2 个 vpk", info7.get("mods") == 2, info7.get("mods"))

t_txt = add_done_task(os.path.join(src, "readme.txt"), "readme.txt")
check("普通文件不算压缩包",
      dq.inspectTaskArchive(t_txt).get("isArchive") is False)

print("\n-- 2. 一键导入（zip）", flush=True)
res = dq.importTaskArchive(t_zip)
check("导入返回 ok", res.get("ok") is True, res)
copied = [os.path.basename(p) for p in (res.get("copied") or [])]
check("导入了 2 个 vpk", sum(1 for n in copied if n.endswith(".vpk")) == 2,
      copied)
check("同名封面也一起导入",
      sum(1 for n in copied if n.endswith(".jpg")) == 2, copied)
check("无关的 png 没被导入", "unrelated.png" not in copied, copied)
check("说明文件没被导入", "readme.txt" not in copied, copied)
on_disk = sorted(os.listdir(addons))
check("addons 里真的落了文件", len(on_disk) == 4, on_disk)
check("落盘的有 2 个 vpk",
      sum(1 for n in on_disk if n.endswith(".vpk")) == 2, on_disk)

print("\n-- 3. 一键导入（7z，同名时按既定规则不覆盖）", flush=True)
# addons 里刚才 zip 已经导过同名文件，所以 7z 这次会全部 skip ——
# 这是 `import_files` 的**刻意行为**（绝不覆盖用户已有的 MOD）。
res7 = dq.importTaskArchive(t_7z)
check("7z 能走到导入流程（不报异常）", isinstance(res7, dict), res7)
check("同名不覆盖：copied 为空，skipped 有值",
      not (res7.get("copied") or []) and bool(res7.get("skipped")),
      {"copied": res7.get("copied"), "skipped": res7.get("skipped")})
check("提示说清是「已经有了」而不是「失败」",
      "已经有" in (res7.get("error") or ""), res7.get("error"))
# 换一个干净的 addons 再导 7z，验证它本身能导
addons7 = os.path.join(work, "addons7z")
os.makedirs(addons7, exist_ok=True)
core.mods._addons_dir = addons7
res7b = dq.importTaskArchive(t_7z)
check("干净的 addons 里 7z 能正常导入", res7b.get("ok") is True, res7b)
check("7z 导入了 2 个 vpk",
      sum(1 for n in (res7b.get("copied") or []) if n.endswith(".vpk")) == 2,
      res7b.get("copied"))
core.mods._addons_dir = addons      # 还原

print("\n-- 4. 没有 .vpk 的包要说清楚", flush=True)
t_img = add_done_task(imgonly_path, "images.zip")
inf = dq.inspectTaskArchive(t_img)
check("只有图片时 mods=0", inf.get("mods") == 0, inf)
r = dq.importTaskArchive(t_img)
check("导入会被拒绝并说明", not r.get("ok"), r)
check("说的是「没有 .vpk」", "没有 .vpk" in (r.get("error") or ""), r.get("error"))

print("\n-- 5. 坏包 / 不存在的任务不炸", flush=True)
t_bad = add_done_task(bad_path, "broken.7z")
bad_info = dq.inspectTaskArchive(t_bad)
check("坏包 isArchive=False", bad_info.get("isArchive") is False, bad_info)
check("坏包有错误原因", bool(bad_info.get("error")), bad_info.get("error"))
r_bad = dq.importTaskArchive(t_bad)
check("坏包导入失败但不抛", not r_bad.get("ok"), r_bad)

check("不存在的任务安全返回", not dq.inspectTaskArchive("nope").get("isArchive"))
check("不存在的任务导入安全返回", not dq.importTaskArchive("nope").get("ok"))

print("\n-- 6. to_dict 带 isArchive 供界面判断", flush=True)
live = {t["id"]: t for t in dq.tasks}
check("压缩包任务标了 isArchive",
      live.get(t_zip, {}).get("isArchive") is True,
      live.get(t_zip, {}).get("isArchive"))
check("普通文件任务不标", live.get(t_txt, {}).get("isArchive") is False)

# 清理
for tid in list(dq._tasks):
    dq.removeTask(tid)
shutil.rmtree(work, ignore_errors=True)

print()
if FAILS:
    print("失败 %d 项：%s" % (len(FAILS), "、".join(FAILS)), flush=True)
    sys.exit(1)
print("全部通过", flush=True)
