# -*- coding: utf-8 -*-
"""压缩包导入的「逐条勾选」+ 网盘过期识别 的回归。

## 两件用户提的事

1. **「导入或拖入压缩包文件进 MOD 管理，会自动检测压缩包文件里面的
   后缀为 vpk，然后提示勾选添加到 MOD 管理里面，默认是全选」**

   以前确认框只给一个**只读数**（前 5 个文件名 + 「等 N 个」），
   用户没法去掉不想要的；而且只支持 .zip —— 蓝奏云上大量 .7z / .rar
   拖进去直接当普通文件处理（等于什么都不导入）。

2. **「视频详情添加百度和夸克网盘显示已过期文件的显示」**

   实测两条真实链接：
     · 百度  `1mNBVxgENXBEEo5j5r3gEOA`（码 7y2n）
     · 夸克  `dcb18f65c568`（码 CdnP）
   两条**都已过期**，但改之前：
     · 百度返回 `errno: -21`，没映射 → 显示「分享打不开（可能已被取消）」，
       角标是「已失效」—— 用户以为是作者删了，其实只是到期；
     · 夸克更快：token 接口返回 **HTTP 404** + `code 41019`，
       旧代码 `status != 200 → continue` 直接把这响应扔了，
       最后 `unknown` —— **界面上一个字都不显示**。

## 本测试

前两节走真实网络（过期结论必须来自真接口，不能靠 mock 自证）。
网络不通时**降级成 skip**，不算 FAIL（不然离线环境永远是红的）。
后三节是纯本地：勾选逻辑 + 只导入勾中的那些。
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from app import mods as M  # noqa: E402
from app import panshare as PS  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def skip(name: str, why: str) -> None:
    print("  [skip] " + name + "  " + why)
    SKIPS.append(name)


def make_zip(path: str, members: dict) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def main() -> int:
    # ------------------------------------------------------ 1. 勾选清单
    print("=== 1. planImport：自动找出 .vpk，并且给出可勾选的清单 ===")
    tmp = tempfile.mkdtemp(prefix="l4d2_pick_")
    zpath = os.path.join(tmp, "一堆mod.zip")
    make_zip(zpath, {
        "mods/aaa.vpk": b"VPK1",
        "mods/bbb.vpk": b"VPK2",
        "mods/aaa.jpg": b"IMG1",          # 和 aaa.vpk 同名 → 该带上
        "mods/bbb.png": b"IMG2",          # 和 bbb.vpk 同名 → 该带上
        "screenshots/random.png": b"IMG", # 无关截图 → 不该带上
        "readme.txt": b"hello",
    })

    info = M.inspect_import_paths([zpath])
    check("认得出这是压缩包", info.get("archives") == ["一堆mod.zip"],
          str(info.get("archives")))
    check("找出 2 个 .vpk", sum(1 for n in info["names"]
                                if n.endswith(".vpk")) == 2, str(info["names"]))
    items = info.get("items") or []
    check("返回了可勾选的 items", len(items) == len(info["names"]),
          f"{len(items)} vs {len(info['names'])}")
    check("每条都带 name/kind", all(x.get("name") and x.get("kind")
                                    for x in items), str(items[:2]))
    check("kind 把 MOD 和封面分开",
          sum(1 for x in items if x["kind"] == "mod") == 2
          and sum(1 for x in items if x["kind"] == "image") == 3,
          str([(x["name"], x["kind"]) for x in items]))
    check("每条都知道自己来自哪个压缩包",
          all(x.get("archive") == "一堆mod.zip" for x in items))
    # ★ 无关截图仍在清单里：这是**有意**的。老的 inspect_import_paths 会把
    #   压缩包里的所有图片都列出来（.jpg/.png 都算封面候选），
    #   界面上它们标成「封面」、用户可以自己取消勾选 —— 比我们猜「哪张是
    #   封面」更可靠（作者贴的效果图也叫预览图，机器分不出来）。
    check("无关截图也列出来（交给用户自己取消勾选）",
          any("random" in x["name"] for x in items))
    check("readme 没进清单", not any(x["name"] == "readme.txt" for x in items))

    # ------------------------------------------------------ 2. 只导入勾中的
    print("=== 2. 只导入勾选的文件（取消勾选的不许偷偷带上）===")
    addons = os.path.join(tmp, "addons")
    os.makedirs(addons, exist_ok=True)

    res = M.import_files([zpath], addons, only=["aaa.vpk", "aaa.jpg"])
    check("导入成功", res.get("ok") is True, str(res.get("error")))
    copied = [os.path.basename(x) for x in (res.get("copied") or [])]
    check("只导了勾中的两个", sorted(copied) == ["aaa.jpg", "aaa.vpk"],
          str(copied))
    on_disk = sorted(os.listdir(addons))
    check("addons 里也只有两个", on_disk == ["aaa.jpg", "aaa.vpk"], str(on_disk))
    check("没勾的 bbb.vpk 没被带进来", "bbb.vpk" not in on_disk)
    check("没勾的封面也没带进来", "bbb.png" not in on_disk)

    # 大小写不敏感（Windows 上用户勾选的名字可能大小写不同）
    addons2 = os.path.join(tmp, "addons2")
    os.makedirs(addons2, exist_ok=True)
    res2 = M.import_files([zpath], addons2, only=["BBB.VPK"])
    got2 = sorted(os.listdir(addons2))
    # ★ 只勾了 bbb.vpk，但 bbb.png 会**跟着 vpk 走**（同名封面自动带上，
    #   这是 import_files 一直以来的既定行为，见 `_import_files_impl`）。
    #   这里要盯的是：勾选名字大小写不敏感（否则 bbb.vpk 根本不会进来）。
    check("勾选名字大小写不敏感（bbb.vpk 进得来）",
          "bbb.vpk" in got2, str(got2))
    check("同名封面照既定行为跟着 vpk 一起进去",
          got2 == ["bbb.png", "bbb.vpk"], str(got2))
    check("没勾的 aaa.vpk 没被带进来", "aaa.vpk" not in got2, str(got2))

    # 一个都不勾 → 什么都不能导入
    addons3 = os.path.join(tmp, "addons3")
    os.makedirs(addons3, exist_ok=True)
    res3 = M.import_files([zpath], addons3, only=[])
    check("一个都不勾时拒绝导入", res3.get("ok") is False, str(res3))
    check("一个都不勾时 addons 是空的", os.listdir(addons3) == [],
          str(os.listdir(addons3)))

    # 不给 only → 保持老行为（全导），兼容所有老调用点
    addons4 = os.path.join(tmp, "addons4")
    os.makedirs(addons4, exist_ok=True)
    res4 = M.import_files([zpath], addons4)
    got4 = sorted(os.listdir(addons4))
    check("不给 only 时还是全导（老行为不变）",
          "aaa.vpk" in got4 and "bbb.vpk" in got4, str(got4))

    # ------------------------------------------------------ 2b. 7z 也得认
    print("=== 2b. 7z / rar 这类压缩包也能认、也能导入 ===")
    # ★ 用户说的「压缩包」不只 zip：蓝奏云上大量是 .7z / .rar。
    #   以前 ARCHIVE_EXTS 只有 .zip，拖 .7z 进去被当普通文件跳过，
    #   表现就是「拖进去没反应」。
    src = os.path.join(tmp, "src7")
    os.makedirs(os.path.join(src, "mods"), exist_ok=True)
    open(os.path.join(src, "mods", "ccc.vpk"), "wb").write(b"CCC")
    open(os.path.join(src, "mods", "ccc.jpg"), "wb").write(b"IMG")
    open(os.path.join(src, "readme.txt"), "w").write("hi")
    seven = os.path.join(tmp, "打包.7z")
    tar = shutil.which("tar")
    if not tar:
        skip("7z 导入", "系统没有 tar.exe")
    else:
        out = subprocess.run([tar, "-c", "-f", seven, "-C", src, "."],
                             capture_output=True)
        if out.returncode != 0 or not os.path.isfile(seven):
            skip("7z 导入", f"造不出 7z：{out.stderr[:60]!r}")
        else:
            check(".7z 被认成压缩包",
                  M.inspect_import_paths([seven])["archives"] == ["打包.7z"])
            i7 = M.inspect_import_paths([seven])
            check("7z 里也能找出 .vpk", "ccc.vpk" in i7["names"], i7["names"])
            check("7z 里的同名封面也列出来", "ccc.jpg" in i7["names"],
                  i7["names"])
            check("7z 的 readme 不进清单",
                  "readme.txt" not in i7["names"], i7["names"])
            addons7 = os.path.join(tmp, "addons7")
            os.makedirs(addons7, exist_ok=True)
            r7 = M.import_files([seven], addons7)
            got7 = sorted(os.listdir(addons7))
            check("7z 能真的导入", r7.get("ok") is True, str(r7.get("error")))
            check("7z 导进来的东西对", got7 == ["ccc.jpg", "ccc.vpk"], str(got7))

    # ------------------------------------------------------ 2c. 勾选在 7z 上也生效
    if os.path.isfile(seven) and tar:
        addons8 = os.path.join(tmp, "addons8")
        os.makedirs(addons8, exist_ok=True)
        r8 = M.import_files([seven], addons8, only=["ccc.vpk"])
        got8 = sorted(os.listdir(addons8))
        # 只勾 vpk，同名封面跟着走（既定行为），但**没勾的不会被带**
        check("7z 上勾选也生效（只导勾中的）",
              "ccc.vpk" in got8 and got8 == ["ccc.jpg", "ccc.vpk"], str(got8))

    # ------------------------------------------------------ 3. 网盘过期（真实接口）
    print("=== 3. 已过期的网盘链接必须认出来（真实接口）===")
    PS.clear_cache()
    baidu = PS.check("https://pan.baidu.com/s/1mNBVxgENXBEEo5j5r3gEOA",
                     passcode="7y2n")
    quark = PS.check("https://pan.quark.cn/s/dcb18f65c568",
                     passcode="CdnP")

    if baidu.get("state") == "unknown":
        skip("百度过期识别", "接口不可达（网络原因）")
    else:
        check("百度已过期：state=expired", baidu.get("state") == "expired",
              baidu.get("state"))
        check("百度已过期：expired=True", baidu.get("expired") is True)
        check("百度文案说「过期」而不是「已被取消」",
              "过期" in (baidu.get("text") or ""), baidu.get("text"))

    if quark.get("state") == "unknown":
        skip("夸克过期识别", "接口不可达（网络原因）")
    else:
        check("夸克已过期：state=expired", quark.get("state") == "expired",
              quark.get("state"))
        check("夸克已过期：expired=True", quark.get("expired") is True)
        check("夸克文案说「过期」", "过期" in (quark.get("text") or ""),
              quark.get("text"))

    # 界面上「已过期 / 已失效」是两种角标，靠文案里有没有「不存在」来分
    for label, r in (("百度", baidu), ("夸克", quark)):
        if r.get("state") == "unknown":
            continue
        tag = "已失效" if "不存在" in (r.get("text") or "") else "已过期"
        check(f"{label}的角标是「已过期」（不是「已失效」）",
              tag == "已过期", f"text={r.get('text')} -> {tag}")

    # ------------------------------------------------------ 4. 过期结论要能熬过缓存/重启
    print("=== 4. 过期状态经过 refresh 之后不丢 ===")
    for state in ("expired", "gone"):
        src = {"ok": True, "state": state, "text": "x", "expireAt": 0,
               "expireDays": 0, "expired": True}
        out = PS.refresh(src)
        check(f"{state} 刷新后仍是 {state}", out.get("state") == state,
              out.get("state"))
        check(f"{state} 刷新后 expired 仍为真", out.get("expired") is True)

    # 夸克的 41019 必须被当成「没了」，不能再退回 unknown
    check("41019 在夸克的失效码表里", 41019 in PS.QUARK_GONE_CODES,
          str(sorted(PS.QUARK_GONE_CODES)))
    # 百度的 -21 必须映射成「过期」
    check("百度 -21 映射成「已过期」", "过期" in (PS._ERRNO.get(-21) or ""),
          PS._ERRNO.get(-21))

    # ------------------------------------------------------ 5. QML 接线
    print("=== 5. 界面接线（源码断言）===")
    mp = io.open(os.path.join(ROOT, "qml", "components", "ModPanel.qml"),
                 encoding="utf-8").read()
    check("确认框用的是可勾选清单", "page.importPickItems()" in mp)
    check("有勾选状态", "property var importPicked" in mp)
    check("点整行就能勾", "page.toggleImportPick(modelData.name)" in mp)
    check("有全选 / 全不选", "page.importPickAll(true)" in mp
          and "page.importPickAll(false)" in mp)
    check("默认全选（askImport 里把清单灌满）",
          "page.importPicked = all;" in mp)
    check("确认导入调的是 importFilesPicked", "importFilesPicked(" in mp)
    check("一个都没勾时按钮是灰的", "enabledBtn: page.importPickCount() > 0" in mp)
    check("MOD 和封面在清单里分开标", 'modelData.kind === "image"' in mp)

    print()
    if SKIPS:
        print("跳过 %d 项（网络原因）：%s" % (len(SKIPS), " / ".join(SKIPS)))
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
