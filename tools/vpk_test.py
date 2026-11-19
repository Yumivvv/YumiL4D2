"""VPK 内部解析自检：目录树 / addoninfo / 预览图 / 内容识别。

跑法：python -X utf8 tools/vpk_test.py

不依赖真实游戏文件：用标准 VPK 格式现场**造**几个测试文件，
再对真实 addons 目录做一次只读抽样（有就测，没有就跳过）。
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

import struct
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
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 造一个最小合法的 VPK v1
# ---------------------------------------------------------------------------
def build_vpk(path: str, files: dict[str, bytes]) -> str:
    """按 VPK v1 格式写一个文件。

    `files` 是 {"目录/文件名.扩展名": 内容}，例如
    {"addoninfo.txt": b'...', "materials/x.vmt": b'...'}
    """
    # 1) 把文件按 (扩展名, 目录, 文件名) 分组，构造目录树字节
    groups: dict[str, dict[str, list[tuple[str, bytes]]]] = {}
    for full, data in files.items():
        folder, name = os.path.split(full)
        stem, ext = os.path.splitext(name)
        ext = ext.lstrip(".")
        folder_field = (folder.replace("\\", "/") + "/") if folder else " "
        groups.setdefault(ext, {}).setdefault(folder_field, []).append((stem, data))

    tree = bytearray()
    # 内容区：所有文件数据顺序排列，记录每个的偏移
    datas = bytearray()
    offsets: dict[tuple[str, str, str], tuple[int, int]] = {}
    for ext in sorted(groups):
        for folder in sorted(groups[ext]):
            for stem, data in sorted(groups[ext][folder]):
                start = len(datas)
                datas += data
                offsets[(ext, folder, stem)] = (start, len(data))

    for ext in sorted(groups):
        tree += ext.encode() + b"\0"
        for folder in sorted(groups[ext]):
            tree += folder.encode() + b"\0"
            for stem, data in sorted(groups[ext][folder]):
                start, ln = offsets[(ext, folder, stem)]
                tree += stem.encode() + b"\0"
                tree += struct.pack("<IHHII", 0, 0, 0x7FFF, start, ln)
                tree += struct.pack("<H", 0xFFFF)
            tree += b"\0"          # 该目录结束
        tree += b"\0"              # 扩展名层结束
    tree += b"\0"                  # 整棵树结束

    header = struct.pack("<III", 0x55AA1234, 1, len(tree))
    with open(path, "wb") as f:
        f.write(header)
        f.write(tree)
        f.write(datas)
    return path


def main() -> int:
    from app import vpk_reader as V

    tmp = tempfile.mkdtemp(prefix="vpk_test_")

    # ---------------------------------------------------------------- 1. 基本解析
    print("=== 1. 目录树 + addoninfo.txt ===")
    addoninfo = (
        '"AddonInfo"\n'
        '{\n'
        '\t"addontitle"\t\t"【测试】飞鸟凑榴弹发射器"\n'
        '\t"addonauthor"\t\t"某位作者"\n'
        '\t"addonversion"\t\t"1.2.3"\n'
        '\t"addondescription"\t\t"替换了 grenade_launcher\\n还改了音效"\n'
        '}\n'
    )
    p1 = build_vpk(os.path.join(tmp, "mod1.vpk"), {
        "addoninfo.txt": addoninfo.encode("utf-8"),
        "materials/models/weapons/grenade.vmt": b"x" * 200,
        "sound/weapons/grenade.wav": b"y" * 100,
    })
    r1 = V.read_vpk_meta(p1)
    check("解析成功", r1["ok"] is True, r1.get("error") or "")
    check("版本号是 v1", r1["version"] == 1, str(r1.get("version")))
    check("读到 3 个文件", r1["fileCount"] == 3, str(r1.get("fileCount")))
    check("标题正确", r1["info"]["title"] == "【测试】飞鸟凑榴弹发射器", r1["info"]["title"])
    check("作者正确", r1["info"]["author"] == "某位作者", r1["info"]["author"])
    check("版本号正确", r1["info"]["version"] == "1.2.3", r1["info"]["version"])
    check("简介里的 \\n 还原成换行", "\n" in r1["info"]["desc"],
          repr(r1["info"]["desc"]))

    # ---------------------------------------------------------------- 2. 预览图
    print("=== 2. 预览图（addonimage.jpg）===")
    fake_jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 500 + b"\xff\xd9"
    p2 = build_vpk(os.path.join(tmp, "mod2.vpk"), {
        "addoninfo.txt": b'"addontitle" "With Cover"',
        "addonimage.jpg": fake_jpg,
    })
    r2 = V.read_vpk_meta(p2)
    check("找到预览图", r2["image"] is not None)
    if r2["image"]:
        check("认出是 jpg", r2["image"]["ext"] == ".jpg", r2["image"]["ext"])
        check("图片字节完整", r2["image"]["data"] == fake_jpg,
              f"{len(r2['image']['data'])} vs {len(fake_jpg)}")

    png_magic = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    check("PNG 魔数识别", V.guess_image_ext(png_magic) == ".png")
    check("GIF 魔数识别", V.guess_image_ext(b"GIF89a" + b"\x00" * 20) == ".gif")
    check("乱数据不算图片", V.guess_image_ext(b"not an image at all") == "")

    # ---------------------------------------------------------------- 3. 内容识别
    print("=== 3. 内容识别（地图 / 人物 / 武器）===")
    p3 = build_vpk(os.path.join(tmp, "map.vpk"), {
        "maps/c1m1_hotel.bsp": b"x" * 100,
        "maps/c1m1_hotel.nav": b"x" * 50,
    })
    r3 = V.read_vpk_meta(p3)
    check("有 .bsp → 判定为地图", r3["hasBsp"] is True)
    check("有 .nav 也认", r3["hasNav"] is True)

    p4 = build_vpk(os.path.join(tmp, "char.vpk"), {
        "models/survivors/zoey/zoey_body.mdl": b"x" * 100,
        "materials/models/survivors/zoey/body.vmt": b"x" * 100,
    })
    r4 = V.read_vpk_meta(p4)
    check("有角色模型 → hasCharacter", r4["hasCharacter"] is True)
    check("能认出 Zoey",
          "Zoey" in V.detect_character("", r4["fileList"]),
          str(V.detect_character("", r4["fileList"])))

    # HUD 资源不该被当成人物证据
    p5 = build_vpk(os.path.join(tmp, "hud.vpk"), {
        "materials/vgui/hud/zoey_hud.vmt": b"x" * 100,
        "resource/zoey_ui.res": b"x" * 100,
    })
    r5 = V.read_vpk_meta(p5)
    check("HUD 目录不算角色证据（关键：界面 MOD 不该被判成人物）",
          r5["hasCharacter"] is False)
    check("HUD 里也不推断出角色名",
          V.detect_character("", r5["fileList"]) == [],
          str(V.detect_character("", r5["fileList"])))

    p6 = build_vpk(os.path.join(tmp, "wpn.vpk"), {
        "models/weapons/v_m16.mdl": b"x" * 100,
    })
    r6 = V.read_vpk_meta(p6)
    check("有武器模型 → hasWeapon", r6["hasWeapon"] is True)
    check("从标题认出 M16",
          "M16" in V.detect_weapon("替换 m16 ak47", []),
          str(V.detect_weapon("替换 m16 ak47", [])))

    # ---------------------------------------------------------------- 4. addoninfo 变体
    print("=== 4. addoninfo.txt 的几种写法 ===")
    v1 = V.parse_addoninfo('"addontitle" "带引号的标题"')
    check("键值都带引号", v1["title"] == "带引号的标题", v1["title"])
    v2 = V.parse_addoninfo('addontitle "键不带引号"')
    check("键不带引号", v2["title"] == "键不带引号", v2["title"])
    v3 = V.parse_addoninfo("// 注释行\n\n\"addonauthor\" \"作者A\"")
    check("注释和空行不影响", v3["author"] == "作者A", v3["author"])
    v4 = V.parse_addoninfo('"AddonInfo"\n{\n"addontitle" "X"\n}')
    check("结构标记被跳过", v4["title"] == "X", v4["title"])
    check("空内容不崩", V.parse_addoninfo("")["title"] == "")

    # ---------------------------------------------------------------- 5. 容错
    print("=== 5. 容错（坏文件不能把程序带崩）===")
    bad = os.path.join(tmp, "bad.vpk")
    with open(bad, "wb") as f:
        f.write(b"NOPE" + b"\x00" * 40)
    rb = V.read_vpk_meta(bad)
    check("magic 不对 → ok=False 但不抛异常", rb["ok"] is False)
    check("有错误说明", bool(rb.get("error")), str(rb.get("error"))[:40])

    tiny = os.path.join(tmp, "tiny.vpk")
    with open(tiny, "wb") as f:
        f.write(b"\x34\x12\xaa\x55")
    rt = V.read_vpk_meta(tiny)
    check("文件太小 → ok=False", rt["ok"] is False)

    check("文件不存在 → ok=False", V.read_vpk_meta(
        os.path.join(tmp, "nope.vpk"))["ok"] is False)

    trunc = os.path.join(tmp, "trunc.vpk")
    with open(trunc, "wb") as f:
        # 头说目录树很大，实际没那么多数据
        f.write(struct.pack("<III", 0x55AA1234, 1, 999999))
        f.write(b"abc")
    rtr = V.read_vpk_meta(trunc)
    check("目录树被截断 → ok=False", rtr["ok"] is False, str(rtr.get("error"))[:40])

    # ---------------------------------------------------------------- 6. 真实文件
    print("=== 6. 真实 addons 目录抽样（只读）===")
    real = r"E:\SteamLibrary\steamapps\common\Left 4 Dead 2\left4dead2\addons"
    if os.path.isdir(real):
        import glob

        vpks = sorted(glob.glob(os.path.join(real, "*.vpk")))[:5]
        if vpks:
            ok_n = 0
            titled = 0
            for p in vpks:
                rr = V.read_vpk_meta(p)
                if rr["ok"]:
                    ok_n += 1
                    if rr["info"]["title"]:
                        titled += 1
            check(f"抽样 {len(vpks)} 个真实 VPK 都能解析", ok_n == len(vpks),
                  f"{ok_n}/{len(vpks)}")
            print(f"      其中 {titled} 个带 addoninfo 标题")
        else:
            print("      [skip] 目录里没有 vpk")
    else:
        print("      [skip] 没找到真实游戏目录")

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
