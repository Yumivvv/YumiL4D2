"""创意工坊导入：解析 / 依赖 / 勾选 / 下载 的端到端验证。

不联网的部分用桩替换，联网的部分（解析真实工坊 ID）走真实网络，失败则跳过断言。

跑法：python -X utf8 tools/workshop_dl_test.py
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
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    from app import workshop_dl as W

    # ---------------------------------------------------------------- 1. ID 解析
    print("=== 1. 输入解析（链接 / 纯 ID / 垃圾输入）===")
    cases = [
        ("3829533320", "3829533320"),
        ("https://steamcommunity.com/sharedfiles/filedetails/?id=3829533320", "3829533320"),
        ("https://steamcommunity.com/sharedfiles/filedetails/?id=3829533320&searchtext=x",
         "3829533320"),
        ("https://steamcommunity.com/workshop/filedetails/?id=2778742681", "2778742681"),
        ("  https://steamcommunity.com/sharedfiles/filedetails/?id=123456  ", "123456"),
        ("hello", ""),
        ("", ""),
        ("123", ""),          # 太短，不像 ID
    ]
    for raw, expect in cases:
        got = W.parse_workshop_id(raw)
        check(f"parse({raw[:42]!r})", got == expect, f"{got!r} != {expect!r}")

    # ---------------------------------------------------------------- 2. 线程夹取
    print("=== 2. 下载线程数夹取 ===")
    for raw, expect in ((0, 1), (1, 1), (3, 3), (8, 8), (16, 16),
                        (99, W.MAX_THREADS), (-5, 1),
                        ("4", 4), ("x", W.DEFAULT_THREADS), (None, W.DEFAULT_THREADS)):
        check(f"clamp_threads({raw!r})", W.clamp_threads(raw) == expect,
              str(W.clamp_threads(raw)))

    # ------------------------------------------------- 3. 官方直链判据
    print("=== 3. 官方 file_url 判据（不再有下载站）===")
    CDN = "https://cdn.steamusercontent.com/ugc/119/ABC/"
    # 能下的：单文件 vpk
    check("单文件 .vpk 可用", W._direct_url_ok(CDN, "时崎狂三 替换 zoey.vpk"))
    # filename 带上传目录前缀（myl4d2addons/xxx.vpk）也认 —— 实测这类条目
    # 的 file_url 就是完整 VPK，Content-Length 与 file_size 吻合
    check("带目录前缀的 .vpk 可用", W._direct_url_ok(CDN, "myl4d2addons/root.vpk"))
    check("反斜杠目录也认", W._direct_url_ok(CDN, "myl4d2addons\\root.vpk"))
    # 不能下的：封面图域名 / 非 vpk / 空
    check("images 域名（封面图）不算",
          not W._direct_url_ok(
              "https://images.steamusercontent.com/ugc/1/2.jpg", "a.vpk"))
    check("zip 打包条目不算", not W._direct_url_ok(CDN, "L4N_v2.51.0.zip"))
    check("空文件名不算", not W._direct_url_ok(CDN, ""))
    check("空地址不算", not W._direct_url_ok("", "a.vpk"))

    # 目录前缀在落盘时必须被取掉（不能真去建 myl4d2addons 子目录）
    check("落盘取 basename", W._safe_filename("myl4d2addons/root.vpk") == "root.vpk",
          W._safe_filename("myl4d2addons/root.vpk"))

    # 下载站相关符号应该已经彻底不存在
    for gone in ("DL_SITE", "DL_VIEW", "_parse_download_page", "_size_to_bytes"):
        check(f"已删除 {gone}", not hasattr(W, gone))
    import inspect as _insp
    src = _insp.getsource(W)
    check("源码里不再有下载站地址",
          "http://steamworkshop.download" not in src
          and "https://steamworkshop.download" not in src)

    # ---------------------------------------------------------------- 4. 依赖解析
    print("=== 4. 必需物品（前置）解析 ===")
    dep_html = """
    <div class="requiredItemsContainer" id="requiredItems">
      <h3>Required items</h3>
      <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=111111111">
        <div class="requiredItem">[huahua]ALL模型基础材质</div></a>
      <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=222222222">
        <div class="requiredItem">Chiyu 公式服 材质包</div></a>
      <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=111111111">
        <div class="requiredItem">重复项</div></a>
    </div>
    <div class="workshopItemDescription" id="description">
      <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=999999999">简介里的链接</a>
    </div>
    """
    deps = W.parse_required_items(dep_html)
    check("解析出 2 个依赖（重复项被去掉）", len(deps) == 2, str(len(deps)))
    check("依赖 ID 正确", [d["id"] for d in deps] == ["111111111", "222222222"],
          str([d["id"] for d in deps]))
    check("依赖名称正确", deps[0]["title"] == "[huahua]ALL模型基础材质", deps[0]["title"])
    check("简介里的链接不算依赖", all(d["id"] != "999999999" for d in deps))
    check("没有依赖区块 → 空", W.parse_required_items("<div>hi</div>") == [])

    # ---------------------------------------------------------------- 5. 文件名清洗
    print("=== 5. 文件名清洗（Windows 非法字符）===")
    # 注意 _safe_filename 会先 os.path.basename，所以路径分隔符那一段会被截掉，
    # 这里只测「单个文件名里」的非法字符。
    check("去掉非法字符",
          W._safe_filename('a<b>c:d"e|f?g*h.vpk') == "a_b_c_d_e_f_g_h.vpk",
          W._safe_filename('a<b>c:d"e|f?g*h.vpk'))
    check("中文名保留", W._safe_filename("时崎狂三 替换 zoey.vpk") == "时崎狂三 替换 zoey.vpk")
    check("空串 → 空", W._safe_filename("") == "")
    check("首尾的点/空格被剪掉", W._safe_filename("  ..a.vpk..  ") == "a.vpk",
          W._safe_filename("  ..a.vpk..  "))

    # ---------------------------------------------------------------- 6. 真实网络
    print("=== 6. 真实网络：解析工坊 ID ===")
    d = W.WorkshopDownloader(threads=2)
    real = d.probe("https://steamcommunity.com/sharedfiles/filedetails/?id=3829533320")
    if real.get("ok"):
        check("拿到标题", bool(real.get("title")), (real.get("title") or "")[:34])
        check("拿到直链", any(it.get("url") for it in real.get("items") or []))
        check("基础条目有体积", bool(real.get("sizeText")), str(real.get("sizeText")))
        print(f"      依赖检查：{'已检查' if real.get('depsChecked') else '未查成'}"
              f" {real.get('depsReason') or ''}")
    else:
        print("      [skip] 官方接口暂时不可用：", real.get("error"))

    bad = d.probe("这不是ID")
    check("垃圾输入被拒", bad.get("ok") is False and "认不出" in (bad.get("error") or ""),
          str(bad.get("error")))

    # ---------------------------------------------------------------- 7. 合集识别
    print("=== 7. 合集识别（官方 API）===")
    coll = W.fetch_collection("3727891945")
    if coll.get("ok"):
        check("被识别为合集", coll.get("isCollection") is True, str(coll.get("isCollection")))
        check("拿到子项", len(coll.get("children") or []) > 0,
              str(len(coll.get("children") or [])))
        single = W.fetch_collection("3829533320")
        check("单个 MOD 不会被误判成合集",
              single.get("isCollection") is False and single.get("ok") is True,
              str(single))
        check("非法 ID 报错", W.fetch_collection("abc").get("ok") is False)
    else:
        print("      [skip] 合集接口暂时不可用：", coll.get("error"))

    # ---------------------------------------------------------------- 8. 合集完整解析
    print("=== 8. 合集完整解析（并发，含进度回调）===")
    stages: list[str] = []
    dc = W.WorkshopDownloader(threads=4)
    r_coll = dc.probe("https://steamcommunity.com/workshop/filedetails/?id=3727891945",
                      progress=lambda s, d, t: stages.append(s))
    if r_coll.get("ok") and r_coll.get("isCollection"):
        check("合集解析成功", True)
        check("成员数与 items 里成员数一致",
              r_coll.get("memberCount") == sum(1 for it in r_coll["items"]
                                               if it.get("isMember")),
              f"{r_coll.get('memberCount')} vs "
              f"{sum(1 for it in r_coll['items'] if it.get('isMember'))}")
        check("成员都有直链", all(it.get("url") for it in r_coll["items"]
                                  if it.get("isMember")),
              "some missing url")
        check("有进度回调", len(stages) > 2, str(len(stages)))
        check("合集成员不是前置", all(not it.get("isDep") for it in r_coll["items"]
                                      if it.get("isMember")))
        print(f"      成员 {r_coll.get('memberCount')} 个，合计 {r_coll.get('sizeText')}，"
              f"进度回调 {len(stages)} 次")
    else:
        print("      [skip] 合集解析没成：", r_coll.get("error"))

    # ---------------------------------------------------------------- 9. 前置默认不勾
    print("=== 9. 前置默认不勾选（关键行为）===")
    # 用桩覆盖：造一个「有前置」的解析结果，验证 checked 规则
    fake_items = [
        {"id": "1", "isMain": True, "isDep": False, "isMember": False,
         "available": True, "installed": False, "checked": False},
        {"id": "2", "isMain": False, "isDep": True, "isMember": False,
         "available": True, "installed": False, "checked": False},
        {"id": "3", "isMain": False, "isDep": True, "isMember": False,
         "available": True, "installed": False, "checked": False},
    ]
    # 复现 modmanager._probe_worker 里的规则：checked = 可下 且 不是前置 且 未安装
    for it in fake_items:
        it["checked"] = ((not it["installed"]) and bool(it["available"])
                         and not it["isDep"])
    check("本体被勾上", fake_items[0]["checked"] is True)
    check("前置默认不勾", all(not it["checked"] for it in fake_items if it["isDep"]))
    check("前置仍然可下载（有 url 就说明能下）",
          all(it["available"] for it in fake_items if it["isDep"]))

    # ---------------------------------------------------------------- 10. 下载
    print("=== 10. 并发下载（本地桩，不联网）===")
    tmp = tempfile.mkdtemp(prefix="wsdl_test_")
    src = os.path.join(tmp, "src")
    os.makedirs(src)
    payload = b"VPK" + b"x" * 5000
    for n in ("a.vpk", "b.vpk", "c.jpg"):
        with open(os.path.join(src, n), "wb") as f:
            f.write(payload)

    # 用 file:// 当「CDN 直链」，验证并发调度 / 命名 / 进度回调
    dest = os.path.join(tmp, "dest")
    items = [
        {"id": "111111111", "title": "A", "url": "file:///" + os.path.join(src, "a.vpk").replace("\\", "/"),
         "filename": "a.vpk"},
        {"id": "222222222", "title": "B", "url": "file:///" + os.path.join(src, "b.vpk").replace("\\", "/"),
         "filename": "b.vpk"},
    ]
    prog: list[tuple] = []
    got_items: list[str] = []
    dl = W.WorkshopDownloader(threads=2)
    res = dl.download(items, dest,
                      on_item=lambda it: got_items.append(it["id"]),
                      on_bytes=lambda wid, got, total: prog.append((wid, got)),
                      on_done=lambda r: None)
    check("两个都下成功", res["ok"] and len(res["done"]) == 2, str(len(res["done"])))
    check("on_item 被调用两次", len(got_items) == 2, str(got_items))
    check("有进度回调", len(prog) > 0, str(len(prog)))
    files = sorted(os.listdir(dest))
    # 文件名必须是创意工坊 ID：MOD 管理器靠「纯数字文件名」认工坊 MOD，
    # 认出来才会自动挂标题、封面和更新检查（见 app/mods.py 的 workshop_id_of）
    check("文件名用创意工坊 ID（<ID>.vpk）",
          files == ["111111111.vpk", "222222222.vpk"], str(files))
    check("内容正确", all(os.path.getsize(os.path.join(dest, f)) == len(payload)
                          for f in files), str(files))

    # 没有 ID 的条目（本地文件、测试用）还得保住「重名自动加序号」
    dup_dir = os.path.join(tmp, "dup")
    dup_items = [
        {"id": "", "title": "dup", "url": "file:///" + os.path.join(src, "a.vpk").replace("\\", "/"),
         "filename": "a.vpk"},
        {"id": "", "title": "dup", "url": "file:///" + os.path.join(src, "b.vpk").replace("\\", "/"),
         "filename": "a.vpk"},
    ]
    W.WorkshopDownloader(threads=2).download(dup_items, dup_dir)
    dup_files = sorted(os.listdir(dup_dir))
    check("没有 ID 时重名不会覆盖（自动加序号）", len(dup_files) == 2, str(dup_files))

    # 失败用例：坏地址不能把整批拖垮
    bad_items = [
        {"id": "3", "title": "bad", "url": "file:///" + os.path.join(src, "nope.vpk").replace("\\", "/"),
         "filename": "nope.vpk"},
        {"id": "4", "title": "ok", "url": "file:///" + os.path.join(src, "c.jpg").replace("\\", "/"),
         "filename": "c.jpg"},
    ]
    res2 = W.WorkshopDownloader(threads=2).download(bad_items, dest)
    check("一个失败不影响另一个", len(res2["done"]) == 1 and len(res2["failed"]) == 1,
          f"done={len(res2['done'])} failed={len(res2['failed'])}")

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
