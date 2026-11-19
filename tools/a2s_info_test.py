"""A2S_INFO 解析回归测试（纯离线，用构造的字节流）。

守住一个很隐蔽的 bug：解析起始偏移写成 6（应为 5），
导致**服务器名字永远丢掉第一个字节**。

为什么难发现：
  · map / folder / game / appid / 人数都是按 \0 或固定宽度往后读，
    错位 1 字节后它们碰巧还能读对（多跳的字节被名字和地图之间的 \0 吃了）
  · 唯一症状是「名字第一字消失」，而中文一个字 3 字节，
    少 1 字节后要么变替换字符、要么整字没掉
  · 开发时自己的电脑上可能没注意（服务器名多是英文，丢一个字母不明显）
"""
import struct
import sys

sys.path.insert(0, ".")
from app.servers import _parse_info, clean_name  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


def build_info(name: str, map_code: str = "c2m1_highway",
               folder: str = "left4dead2", game: str = "Left 4 Dead 2",
               appid: int = 550, players: int = 3, maxp: int = 30,
               version: str = "2.2.4.3", tags: str = "") -> bytes:
    """按 A2S_INFO 规范拼一个回包。"""
    b = b"\xFF\xFF\xFF\xFFI"
    b += bytes([17])                       # protocol
    b += name.encode("utf-8") + b"\x00"
    b += map_code.encode("utf-8") + b"\x00"
    b += folder.encode("utf-8") + b"\x00"
    b += game.encode("utf-8") + b"\x00"
    b += struct.pack("<h", appid)
    b += bytes([players, maxp, 0])         # players, max, bots
    b += b"d"                              # 专用服务器
    b += b"w"                              # Windows
    b += bytes([0, 1])                     # 无密码, VAC
    b += version.encode("utf-8") + b"\x00"
    if tags:
        b += tags.encode("utf-8") + b"\x00"
    return b


print("=== 1. 中文名字不丢字 ===")
for nm in ("药抗小分队", "4人纯净写实专家多特 1服", "宿舍服", "测试"):
    info = _parse_info(build_info(nm))
    check(f"「{nm}」完整", info["name"] == nm, repr(info["name"]))

print()
print("=== 2. 英文名字不丢字母 ===")
for nm in ("My Server", "Abc", "Left 4 Dead 2 Server"):
    info = _parse_info(build_info(nm))
    check(f"「{nm}」完整", info["name"] == nm, repr(info["name"]))

print()
print("=== 3. 其它字段也要对（错位时它们可能碰巧对，但必须一起验）===")
info = _parse_info(build_info("药抗小分队", appid=550, players=7, maxp=30,
                              version="2.2.4.3"))
check("protocol = 17", info["protocol"] == 17, str(info["protocol"]))
check("map", info["map"] == "c2m1_highway", info["map"])
check("folder", info["folder"] == "left4dead2", info["folder"])
check("game", info["game"] == "Left 4 Dead 2", info["game"])
check("appid = 550", info["appid"] == 550, str(info["appid"]))
check("players = 7", info["players"] == 7, str(info["players"]))
check("maxPlayers = 30", info["maxPlayers"] == 30, str(info["maxPlayers"]))
check("version", info["version"] == "2.2.4.3", info["version"])

print()
print("=== 4. 带 Valve 彩色控制字符的名字 ===")
# 真实服务器名里常有 \x01-\x08 这类颜色码
colored = "\x01\x02服务器\x07名字"
raw = build_info(colored)
info = _parse_info(raw)
check("控制字符被清掉、正文保留", info["name"] == "服务器名字", repr(info["name"]))

print()
print("=== 5. 名字里带方括号标签 ===")
info = _parse_info(build_info("【CN】药抗小分队"))
check("名字完整", info["name"] == "【CN】药抗小分队", repr(info["name"]))
check("标签提取出来", info["tag"] == "CN", repr(info["tag"]))

print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
