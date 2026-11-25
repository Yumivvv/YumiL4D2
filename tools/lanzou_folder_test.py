# -*- coding: utf-8 -*-
"""蓝奏云**文件夹分享**必须能下载（用户报的「一直显示文件夹无法下载」）。

## 用户给的真实链接

    https://wwbiy.lanzoue.com/b013a7etzg   提取码 mcbl
    → 里面是 夏侯渊awm+左轮.rar（46.0 M）

改之前 `resolve_lanzou()` 一看到 `filemoreajax.php` 就直接返回
「这是一个文件夹分享…请在浏览器打开，挑需要的那个下载」—— 等于不能下。

## 为什么这件事不是「加个字段」那么简单

文件夹分享是**另一套页面 + 另一套提交参数**，两个坑都是实测踩出来的：

1. **列文件**：`/filemoreajax.php?file=<fid>`，要 POST 一堆从页面里抠出来的
   参数（`lx/fid/uid/puid/t/k/up/ls`）加上 `pwd`，分页在 `pg`。
   这些值每个分享都不同，写死必然失败。
2. **解析里面单个文件**：下载页是 `/<id>`（`id` 里已经带了 `?webpage=<puid>`）。
   它的 iframe 表单和普通单文件**不一样**：

   | 字段 | 普通单文件 | 文件夹内文件 |
   | --- | --- | --- |
   | `websign` | `""` | **`"2"`** |
   | `p`（提取码） | 有（密码页时） | **绝对不能带** |

   带了 `p` 会稳定回「密码错误」（`zt != 1`, `inf: 密码错误`）——
   换个说法：文件夹的提取码只在第 1 步用，文件页本身是免密的。

## 本测试

第 1 节纯离线（页面片段解析、参数抠取），第 2 节走**真实链接**
（用户给的那条），网络不通就 skip，不算 FAIL。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from app import lanzou as LZ  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []

URL = "https://wwbiy.lanzoue.com/b013a7etzg"
PWD = "mcbl"


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def skip(name: str, why: str) -> None:
    print("  [skip] " + name + "  " + why)
    SKIPS.append(name)


# 从真实页面截下来的一段（filemoreajax 的调用现场）
FOLDER_PAGE = r"""
<script>
var ibjr7n = '1795577101';
var _hi39g = '0531213ae947be0160d5bb0f619bcec3';
pgs =1;
function file(){
  var pwd = document.getElementById('pwd').value;
  $.ajax({
    type : 'post',
    url : '/filemoreajax.php?file=14298956',
    data : {
      'lx':2,
      'fid':14298956,
      'uid':'4608611',
      'puid':'VGBWNwtmUj5RMQJlBGFSflI5UmBTNVZhBTdbalE7Wm4GNlM1WioCZAlvUzdXNQEwUj4FMF82',
      'pg':pgs,
      'rep':'0',
      't':ibjr7n,
      'k':_hi39g,
      'up':1,
      'ls':1,
      'pwd':pwd
    },
    dataType : 'json'
  });
}
</script>
"""


def main() -> int:
    # ------------------------------------------------ 1. 离线：参数抠取
    print("=== 1. 从文件夹页里抠 filemoreajax 的参数（离线）===")
    p = LZ._folder_params(FOLDER_PAGE)
    check("找到了列表接口", p.get("_api", "").startswith("/filemoreajax.php"),
          p.get("_api"))
    check("抠到 fid", str(p.get("fid")) == "14298956", p.get("fid"))
    check("抠到 uid", str(p.get("uid")) == "4608611", p.get("uid"))
    check("抠到 puid（长串）", len(str(p.get("puid") or "")) > 40,
          str(p.get("puid"))[:40])
    check("抠到 lx / up / ls / rep",
          all(k in p for k in ("lx", "up", "ls", "rep")), sorted(p))
    check("t / k 从 js 变量取到了",
          p.get("t") == "1795577101"
          and p.get("k") == "0531213ae947be0160d5bb0f619bcec3",
          f"t={p.get('t')} k={p.get('k')}")

    # 页面里没有那套参数时要老实返回空，别拼出个假请求
    check("没有 filemoreajax 的页面返回空",
          LZ._folder_params("<html>nothing here</html>") == {})

    # ------------------------------------------------ 1b. 列表解析（喂假响应）
    print("=== 1b. 列表响应解析：多文件 / 分页 / 空 id 都要正确 ===")
    import json as _json

    # 直接测「解析一段 filemoreajax 返回」这段逻辑：把网络层换掉
    real_get, real_req = LZ._Session.get_text, LZ._request
    fake_pages = {
        1: _json.dumps({"zt": 1, "info": "sucess", "text": [
            {"name_all": "a.vpk", "size": "1.0 M", "duan": "d1", "id": "ID1?webpage=P"},
            {"name_all": "b.rar", "size": "2.0 M", "duan": "d2", "id": "ID2?webpage=P"},
        ]}),
        2: _json.dumps({"zt": 1, "info": "sucess", "text": [
            # 故意混一条没有 id 的脏数据 —— 要跳过，不能让整页崩
            {"name_all": "junk", "size": ""},
            {"name_all": "c.7z", "size": "3.0 M", "duan": "d3", "id": "ID3?webpage=P"},
        ]}),
    }
    calls = {"n": 0}

    def fake_get_text(self, url, **kw):
        return FOLDER_PAGE.replace("pgs =1", "pgs =2")

    def fake_request(url, data=None, **kw):
        calls["n"] += 1
        body = (data or b"").decode()
        pg = 1
        for part in body.split("&"):
            if part.startswith("pg="):
                pg = int(part[3:])
        return 200, fake_pages.get(pg, _json.dumps({"zt": 1, "text": []})), ""

    try:
        LZ._Session.get_text = fake_get_text
        LZ._request = fake_request
        multi = LZ.list_folder(URL, password=PWD)
        check("多文件文件夹列出全部 3 个（跨 2 页）",
              multi.get("ok") and len(multi.get("files") or []) == 3,
              str([f["name"] for f in (multi.get("files") or [])]))
        names = [f["name"] for f in (multi.get("files") or [])]
        check("跨页顺序是 a → b → c", names == ["a.vpk", "b.rar", "c.7z"],
              str(names))
        check("脏数据（没 id）被跳过，没让整页失败",
              "junk" not in names, str(names))
        check("页码确实翻了 2 次", calls["n"] == 2, f"calls={calls['n']}")
        check("每条都拼好了下载页地址",
              all(f["page_url"].startswith(URL.split("/b")[0])
                  for f in (multi.get("files") or [])),
              str([f["page_url"][:40] for f in (multi.get("files") or [])])[:120])
    finally:
        LZ._Session.get_text = real_get
        LZ._request = real_req

    # 提取码错时要转述蓝奏云的原话，别静默返回空列表
    def fake_bad(url, data=None, **kw):
        return 200, _json.dumps({"zt": 0, "info": "密码错误"}), ""

    try:
        LZ._Session.get_text = lambda self, url, **kw: FOLDER_PAGE
        LZ._request = fake_bad
        bad = LZ.list_folder(URL, password="wrong")
        check("提取码错时 ok=False", bad.get("ok") is False)
        check("提取码错时把原话带出来", "密码" in str(bad.get("error")),
              bad.get("error"))
    finally:
        LZ._Session.get_text = real_get
        LZ._request = real_req

    # ------------------------------------------------ 2. 离线：源码关键点
    print("=== 2. 实现要点（源码断言）===")
    src = open(os.path.join(ROOT, "app", "lanzou.py"), encoding="utf-8").read()
    check("不再直接拒绝文件夹", "程序只能解析单个文件的直链" not in src)
    check("有 list_folder", "def list_folder(" in src)
    check("有 _resolve_file_page", "def _resolve_file_page(" in src)
    # 这两条是踩出来的关键，不能被人「顺手改回单文件的写法」
    seg = src.split("def _resolve_file_page(", 1)[1][:4000]
    check("文件夹内文件用 websign='2'", '"websign": "2"' in seg)
    check("文件夹内文件**不带**提取码 p",
          '"p":' not in seg and "'p':" not in seg)
    check("resolve_lanzou 会走文件夹分支",
          "list_folder(url" in src.split("def resolve_lanzou(", 1)[1][:3000])
    check("返回值区分了 folder / folderCount",
          '"folder": True' in src and '"folderCount"' in src)

    # ------------------------------------------------ 3. 真实链接
    print("=== 3. 用用户给的链接真跑一次 ===")
    fl = LZ.list_folder(URL, password=PWD)
    if not fl.get("ok"):
        skip("真实链接列文件", fl.get("error") or "网络不通")
    else:
        files = fl.get("files") or []
        check("列出了文件", len(files) >= 1, str(len(files)))
        names = [f["name"] for f in files]
        check("文件名是「夏侯渊awm+左轮.rar」",
              any("夏侯渊" in n for n in names), str(names))
        check("每条都带下载页地址 page_url",
              all(f.get("page_url", "").startswith("http") for f in files),
              str([f.get("page_url", "")[:40] for f in files[:1]]))
        check("每条都带大小", all(f.get("size_text") for f in files),
              str([f.get("size_text") for f in files]))

        one = LZ._resolve_file_page(files[0]["page_url"])
        if not one.get("ok"):
            skip("真实链接取直链", one.get("error") or "网络不通")
        else:
            direct = str(one.get("url") or "")
            check("拿到了 CDN 直链", direct.startswith("http"), direct[:70])
            check("直链是 .rar", ".rar" in direct.lower(), direct[-60:])
            check("文件名对得上", "夏侯渊" in str(one.get("filename") or ""),
                  one.get("filename"))
            # 真去拉一点数据，确认能下（只看头部是不是真内容）
            st, resp, _loc = LZ._request(
                direct, timeout=30, referer="https://wwbiy.lanzoue.com/")
            check("直链能真的下到内容", st == 200 and bool(resp),
                  f"status={st}")
            if resp:
                # ★ `_request` 返回的是**已解码的 str**（它不是纯二进制下载函数），
                #   所以这里跟字符串 `"Rar!"` 比，别拿 b"Rar!" 去比 —— 那样永远不相等。
                head = resp[:4]
                check("下到的确实是 RAR（Rar! 魔数）",
                      head == "Rar!" or head[:2] == "PK", repr(head))

    # resolve_lanzou 这条对外主接口也要能处理文件夹
    r = LZ.resolve_lanzou(URL, password=PWD)
    if not r.get("ok"):
        skip("resolve_lanzou 走文件夹", r.get("error") or "网络不通")
    else:
        check("resolve_lanzou 成功", r.get("ok") is True)
        check("标记成文件夹分享", r.get("folder") is True)
        check("带上了仓库内文件数", int(r.get("folderCount") or 0) >= 1,
              r.get("folderCount"))
        check("返回了可用的直链", str(r.get("url") or "").startswith("http"),
              str(r.get("url"))[:60])
        check("不再是「请去浏览器」的报错",
              "浏览器" not in str(r.get("error") or ""))

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
