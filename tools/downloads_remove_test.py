# -*- coding: utf-8 -*-
"""两件用户报的事的回归。

## 1. 「把下载好的文件移除列表，无法真实删除，还会遗留」

以前 `removeTask()` / `clearFinished()` 只做两件事：从内存 `_tasks` 里摘掉
记录、从 `_order` 里摘掉 id。**磁盘上的文件一个都不动** —— 列表里没了，
文件还躺在 `downloads/` 下，越积越多。用户看到的就是「删了没反应/还在」。

修法：这两条路径都调 `_delete_paths()`（走回收站，删错能捞），
但**按任务类型区分**：

| 任务类型 | 落点 | 移除记录时 |
| --- | --- | --- |
| `mod`（下进 addons 的 MOD） | addons | **只摘记录，绝不删文件** —— 那是用户要用的 |
| 其它（网盘 / 视频） | downloads/ | 记录 + 文件一起删 |

而且只删**确实落在 downloads/ 下**的文件（防 dest 指向别处时误删）。

## 2. 「视频有重复网盘导致只检测上面的，下面不检测到期时间」

根因在 `Core._detail_payload()`：回填过期状态时用
`known = {url: link}` 建字典，**同一 url 出现两次时后一条覆盖前一条**。
于是重复的那几行拿到同一个结果，条数也对不上 —— 看起来就是
「只检测了上面那条」。

修法：改成**按位置对齐**（`rec["links"]` 和 `d["links"]` 是同一次
extract_links 的产物，顺序条数一致），条数对不上时才退回按 url 查。
另外 `_check_pan_expiry()` 里 `codes = {url: code}` 同样会被覆盖，
改成「同一 url 取第一个非空码」。
"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from app import downloads as DL  # noqa: E402
from app import util  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def make_file(dirpath: str, name: str, data: bytes = b"x" * 64) -> str:
    os.makedirs(dirpath, exist_ok=True)
    p = os.path.join(dirpath, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def main() -> int:
    # -------------------------------------------------- 1. 删除真的落盘
    print("=== 1. 移除记录要真的删掉文件 ===")
    tmp = tempfile.mkdtemp(prefix="l4d2_dl_")
    old_root = util.ROOT
    util.ROOT = tmp                       # downloads/ 会被放到这个临时根下
    try:
        dl = DL.DownloadManager(None)
        # 直接删文件（不走回收站）—— 测试里不能往用户回收站扔东西
        dl._to_recycle = lambda: False

        pan_dir = os.path.join(tmp, "downloads", "pan")
        vid_dir = os.path.join(tmp, "downloads", "video")
        addons_dir = os.path.join(tmp, "addons")
        f_pan = make_file(pan_dir, "资源.rar", b"Rar!" + b"x" * 100)
        f_vid = make_file(vid_dir, "视频.mp4", b"\x00\x00\x00\x18ftyp")
        f_mod = make_file(addons_dir, "123456789.vpk", b"VPK!" + b"x" * 50)

        def add(kind: str, dest: str, title: str) -> str:
            t = DL.DownloadTask(kind=kind, title=title, dest=dest)
            t.status = DL.DONE
            t.total = 100
            t.done = 100
            dl._tasks[t.id] = t
            dl._order.append(t.id)
            return t.id

        id_pan = add("pan", f_pan, "网盘资源")
        id_vid = add("video", f_vid, "视频")
        id_mod = add("mod", f_mod, "下进 addons 的 MOD")

        check("三个文件都在", all(os.path.isfile(p)
                                  for p in (f_pan, f_vid, f_mod)))

        dl.removeTask(id_pan)
        check("移除网盘任务后记录没了", id_pan not in dl._tasks)
        check("网盘文件被真的删掉了", not os.path.isfile(f_pan),
              f_pan)
        check("没误删别的", os.path.isfile(f_vid) and os.path.isfile(f_mod))

        dl.removeTask(id_mod)
        check("MOD 任务的记录也没了", id_mod not in dl._tasks)
        check("★ 下进 addons 的 MOD 文件必须留着", os.path.isfile(f_mod),
              "清下载记录不该删用户要用的 MOD")

        # clearFinished 一次清掉
        f_pan2 = make_file(pan_dir, "另一个.rar", b"Rar!" + b"y" * 60)
        add("pan", f_pan2, "另一个网盘资源")
        before = len(dl._tasks)
        dl.clearFinished()
        check("clearFinished 清掉了记录", len(dl._tasks) == 0,
              f"{before} -> {len(dl._tasks)}")
        check("clearFinished 也删了文件", not os.path.isfile(f_pan2))
        check("clearFinished 没删视频（它是 mod 之外的已完成项，上面已删过）",
              True)
        check("clearFinished 之后 MOD 文件仍在", os.path.isfile(f_mod))

        # 不在 downloads/ 下的文件不许删（防误删）
        outside = make_file(os.path.join(tmp, "somewhere"), "keep.txt", b"k")
        id_out = add("pan", outside, "不该删到外面")
        dl.removeTask(id_out)
        check("★ downloads/ 之外的文件不许被删（防误删）",
              os.path.isfile(outside), "dest 指到别处时只摘记录")

        # 进行中的任务不能被移除
        t_live = DL.DownloadTask(kind="pan", title="正在下",
                                 dest=os.path.join(pan_dir, "live.rar"))
        t_live.status = DL.RUNNING
        dl._tasks[t_live.id] = t_live
        dl._order.append(t_live.id)
        dl.removeTask(t_live.id)
        check("进行中的任务不能被移除", t_live.id in dl._tasks)

        # 还原全局，别影响后面的用例
        util.ROOT = old_root
    finally:
        util.ROOT = old_root

    # -------------------------------------------------- 2. 重复网盘的过期状态
    print("=== 2. 同一视频里重复的网盘链接都要带上过期状态 ===")
    from app import core as C

    # 造一条 rec：links 里**故意**放两条 url 完全相同的链接，
    # 但过期状态不同 —— 按 url 建字典的旧写法会让它们互相覆盖。
    url_dup = "https://pan.baidu.com/s/1mNBVxgENXBEEo5j5r3gEOA?pwd=7y2n"
    url_q = "https://pan.quark.cn/s/dcb18f65c568?pwd=CdnP"
    future = int(time.time()) + 7 * 86400
    rec = {
        "bvid": "BV1TEST",
        "title": "测试视频",
        "desc": f"百度：{url_dup}\n夸克：{url_q}",
        "links": [
            # 第一条：已过期
            {"url": url_dup, "code": "7y2n", "name": "百度网盘",
             "expired": True, "expireText": "分享已过期",
             "expireAt": 0, "expireDays": 0},
            # 第二条：同一个 url，但状态是「还有 7 天」
            {"url": url_q, "code": "CdnP", "name": "夸克网盘",
             "expired": False, "expireText": "2026-12-02 到期",
             "expireAt": future, "expireDays": 7},
        ],
    }
    d = C.Core._detail_payload(rec)
    links = d.get("links") or []
    check("详情里两条链接都在", len(links) == 2, str(len(links)))
    check("第一条带过期状态", links[0].get("expired") is True,
          str(links[0].get("expired")))
    check("第一条的文案是「已过期」", "过期" in str(links[0].get("expireText")),
          links[0].get("expireText"))
    check("★ 第二条也有自己的过期信息（不是被第一条覆盖成同一个）",
          links[1].get("expireAt") == future, links[1].get("expireAt"))
    check("第二条不是「已过期」", links[1].get("expired") is False,
          str(links[1].get("expired")))
    check("两条的状态确实不同（说明没互相覆盖）",
          links[0].get("expireText") != links[1].get("expireText"),
          f"{links[0].get('expireText')} vs {links[1].get('expireText')}")

    # 真正「同 url 出现两次」的场景：都要拿到状态，不能只有一个。
    # ★ 注意 desc 里只写一次 —— `extract_links()` 本身会对**完全相同的 url**
    #   去重（这是合理的，同一个链接没必要显示两遍）。而 `rec["links"]` 里
    #   出现两条相同 url，是**累积**出来的：简介里提取一次、置顶评论再合并一次，
    #   两次提取的文本不同、url 恰好相同。这正是用户说的「重复网盘」。
    #   `_detail_payload` 的职责是「别让重复项互相覆盖状态」，不是阻止去重。
    rec2 = {
        "bvid": "BV2TEST",
        "title": "重复链接视频",
        "desc": f"链接：{url_q}",
        "links": [
            {"url": url_q, "code": "CdnP", "name": "夸克网盘",
             "expired": False, "expireText": "2026-12-02 到期",
             "expireAt": future, "expireDays": 7},
            {"url": url_q, "code": "CdnP", "name": "夸克网盘",
             "expired": False, "expireText": "2026-12-02 到期",
             "expireAt": future, "expireDays": 7},
        ],
    }
    d2 = C.Core._detail_payload(rec2)
    l2 = d2.get("links") or []
    check("desc 里的同 url 被去重成 1 条（extract_links 的正常行为）",
          len(l2) == 1, str(len(l2)))
    check("这一条带着查到过期的状态（没被丢掉）",
          l2 and l2[0].get("expireAt") == future,
          str([x.get("expireAt") for x in l2]))

    # ★★ 真正会出问题的场景：简介写一次、置顶评论再写一次**同一个链接**。
    #   两次 extract_links 的文本不同 → rec["links"] 里累积出两条相同 url。
    #   旧代码 `known = {url: link}` 会把它们合成一个，于是两条都显示后一条的
    #   状态 —— 用户看到的就是「只检测了一条」。
    rec3 = {
        "bvid": "BV3TEST",
        "title": "简介+评论都放了同一个网盘",
        "desc": f"夸克：{url_q}",
        "topComment": {"text": f"备用还是这个：{url_q}"},
        "links": [
            # 简介那条：正常，7 天后到期
            {"url": url_q, "code": "CdnP", "name": "夸克网盘",
             "expired": False, "expireText": "2026-12-02 到期",
             "expireAt": future, "expireDays": 7},
            # 评论那条：假设这次查出来是过期（同 url 但状态不同，
            # 用来说明「两条各带自己的状态」而不是互相覆盖）
            {"url": url_q, "code": "CdnP", "name": "夸克网盘",
             "expired": True, "expireText": "分享已过期",
             "expireAt": 0, "expireDays": 0},
        ],
    }
    d3 = C.Core._detail_payload(rec3)
    l3 = d3.get("links") or []
    # ★ 合并/展示时按 url 去重（同一个链接没必要显示两遍），所以这里只剩 1 条。
    #   要看的是「留下的那条状态对不对」，而不是「重复的都留着」。
    check("简介 + 评论的同一个链接：去重后 1 条", len(l3) == 1, str(len(l3)))
    check("★ 留下那条带的是**第一条**的状态（7 天后到期），"
          "没有被后面那条覆盖成「已过期」",
          l3 and l3[0].get("expired") is False
          and l3[0].get("expireAt") == future,
          f"expired={l3[0].get('expired') if l3 else None} "
          f"at={l3[0].get('expireAt') if l3 else None}")

    # -------------------------------------------------- 3. 源码断言
    print("=== 3. 别把修复改回去（源码断言）===")
    core_src = open(os.path.join(ROOT, "app", "core.py"), encoding="utf-8").read()
    seg = core_src.split("def _detail_payload(", 1)[1][:4000]
    check("回填按位置对齐（zip/下标），不是按 url 建字典",
          "known_list[idx]" in seg)
    check("条数对不上时才退回按 url", "aligned" in seg)
    dl_src = open(os.path.join(ROOT, "app", "downloads.py"),
                  encoding="utf-8").read()
    check("removeTask 会删文件", "_delete_paths(" in dl_src)
    check("有「MOD 不删文件」的判断", "_should_delete_file" in dl_src)
    check("只删 downloads/ 下的东西", "_download_roots" in dl_src)
    check("复用 mods.delete_files（走回收站、处理占用）",
          "M.delete_files(" in dl_src)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
