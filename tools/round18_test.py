"""本轮三项修复的自检。

1. **换背景图无效** —— 文件名不变（永远 `background.jpeg`）+ QML `Image` 有 cache
   ⇒ source 字符串没变就不重载。修法是给 URL 带「每次换图都变」的版本号。
2. **服务器配置导出/导入** —— 攒一堆服务器分享给别人。重点是
   **面板密码绝不导出**（DPAPI 密文换台机器解不开，导出只会误导）。
3. **MOD 详情能翻译简介** —— 复用创意工坊那套 `translateTextAsync`。
"""
import io
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from guard import protect_user_data  # noqa: E402

protect_user_data()

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from app import util  # noqa: E402
from app.core import Core  # noqa: E402

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


def src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    core = Core(app)
    globals()["_KEEP"] = core

    print("\n-- 1. 换背景图必须生效", flush=True)
    bg_dir = util.BG_DIR
    os.makedirs(bg_dir, exist_ok=True)
    from PIL import Image as PILImage  # noqa: PLC0415

    red = os.path.join(bg_dir, "red.jpg")
    blue = os.path.join(bg_dir, "blue.jpg")
    PILImage.new("RGB", (32, 32), (255, 0, 0)).save(red, "JPEG")
    PILImage.new("RGB", (32, 32), (0, 0, 255)).save(blue, "JPEG")

    core.importBgImage(red)
    url1 = core.bgImageUrl
    name1 = core.bgImageName
    core.importBgImage(blue)
    url2 = core.bgImageUrl
    name2 = core.bgImageName

    check("两次导入文件名相同（这是问题的前提）", name1 == name2, (name1, name2))
    check("★ URL 必须变（否则 Image 不重载）", url1 != url2,
          f"{url1[-30:]} vs {url2[-30:]}")
    check("URL 带版本号参数", "?v=" in url1 and "?v=" in url2)
    check("版本号真的递增了",
          url1.split("?v=")[1].split("-")[0] != url2.split("?v=")[1].split("-")[0],
          (url1.split("?v=")[1][:8], url2.split("?v=")[1][:8]))
    # 源码层面确认用的是 _bg_version（mtime+size 不可靠：两张纯色 jpg 常同大小）
    core_src = src(os.path.join("app", "core.py"))
    check("用 _bg_version 计数（不是只靠 mtime）", "_bg_version" in core_src)
    check("导入时 +1", "self._bg_version += 1" in core_src)
    # 移除背景也要 +1：否则再导入同名图又「看起来没换」
    check("移除背景时也 +1",
          core_src.count("self._bg_version += 1") >= 2,
          core_src.count("self._bg_version += 1"))
    check("注释写明了「文件名不变 + cache」这个根因",
          "cache" in core_src and "文件名" in core_src)
    shutil.rmtree(bg_dir, ignore_errors=True)

    print("\n-- 2. 服务器配置导出 / 导入", flush=True)
    s = core.servers
    work = tempfile.mkdtemp(prefix="srvcfg_")
    s.clearAll()
    check("空列表导出被拒", not s.exportConfig(os.path.join(work, "x.json")).get("ok"))
    check("空路径被拒", not s.exportConfig("").get("ok"))

    s.saveServer({"addr": "1.2.3.4", "name": "宿舍服", "weight": 5,
                  "panels": [{"url": "http://panel.a.com:8080",
                              "password": "secret-pw"}]})
    s.saveServer({"addr": "5.6.7.8", "name": "海外服", "weight": 1, "panels": []})
    out = os.path.join(work, "servers.json")
    r = s.exportConfig(out)
    check("导出成功且条数对", r.get("ok") and r.get("count") == 2, r)
    check("文件真的写出来了", os.path.isfile(out))
    data = json.load(open(out, encoding="utf-8"))
    check("有 _kind 标记（导入时认得）", data.get("_kind") == "l42d.servers")
    check("地址被规范化成 ip:port",
          any(x["addr"] == "1.2.3.4:27015" for x in data["servers"]))
    check("名称和权重都导出了",
          any(x["name"] == "宿舍服" and x["weight"] == 5 for x in data["servers"]))
    text = open(out, encoding="utf-8").read()
    check("面板地址导出了", "panel.a.com" in text)
    check("★ 面板密码绝不进导出文件", "secret-pw" not in text, text[:120])
    check("pw 字段是空串",
          all((p.get("pw") or "") == ""
              for x in data["servers"] for p in (x.get("panels") or [])))

    s.clearAll()
    pre = s.previewImport(out)
    check("预览：总共 2 台全是新的",
          pre.get("ok") and pre.get("total") == 2 and pre.get("fresh") == 2, pre)
    r2 = s.importConfig(out)
    check("导入成功加了 2 台", r2.get("ok") and r2.get("added") == 2, r2)
    rows = {x["addr"]: x for x in s.servers}
    check("名称/权重/面板都带过来了",
          rows.get("1.2.3.4:27015", {}).get("name") == "宿舍服"
          and rows.get("1.2.3.4:27015", {}).get("weight") == 5
          and rows.get("1.2.3.4:27015", {}).get("panelCount") == 1, rows)
    check("导入的面板不带密码",
          rows.get("1.2.3.4:27015", {}).get("hasPassword") is False)

    r3 = s.importConfig(out)
    check("重复导入不重复加", r3.get("added") == 0 and r3.get("skipped") == 2, r3)
    check("列表还是 2 台", s.serverCount == 2, s.serverCount)

    # 不覆盖本机已有的名字/密码
    s.clearAll()
    s.saveServer({"addr": "1.2.3.4", "name": "我的名字", "weight": 9,
                  "panels": [{"url": "http://panel.a.com:8080",
                              "password": "mypw"}]})
    s.importConfig(out)
    row = {x["addr"]: x for x in s.servers}["1.2.3.4:27015"]
    check("本机名字没被覆盖", row.get("name") == "我的名字", row.get("name"))
    check("本机密码还在", row.get("hasPassword") is True)

    # 坏文件
    bad = os.path.join(work, "bad.json")
    open(bad, "w", encoding="utf-8").write("{not json")
    check("坏 JSON 被拒且有原因", not s.previewImport(bad).get("ok")
          and bool(s.previewImport(bad).get("error")))
    wrong = os.path.join(work, "wrong.json")
    json.dump({"_kind": "other.app", "servers": []}, open(wrong, "w"))
    check("别的程序的文件被拒",
          "不是本程序导出" in (s.previewImport(wrong).get("error") or ""))
    arr = os.path.join(work, "arr.json")
    json.dump(["9.9.9.9", {"addr": "8.8.8.8"}], open(arr, "w"))
    check("裸数组也宽容接受",
          s.previewImport(arr).get("ok") and s.previewImport(arr).get("total") == 2)
    mixed = os.path.join(work, "mixed.json")
    json.dump({"servers": [{"addr": "1.1.1.1"}, {"addr": "乱写"},
                           {"addr": "2.2.2.2"}]}, open(mixed, "w"))
    check("坏条目跳过、好的留下", s.previewImport(mixed).get("total") == 2)
    s.clearAll()
    shutil.rmtree(work, ignore_errors=True)

    # QML 里确实有这两颗按钮
    srv_qml = src(os.path.join("qml", "components", "ServersPage.qml"))
    main_qml = src(os.path.join("qml", "Main.qml"))
    check("QML 有导出按钮", 'objectName: "srvExportBtn"' in srv_qml)
    check("QML 有导入按钮", 'objectName: "srvImportBtn"' in srv_qml)
    check("Main.qml 有导出文件框", "srvExportDlg" in main_qml)
    check("Main.qml 有导入文件框", "srvImportDlg" in main_qml)
    check("导入前先预览确认", "previewImport" in main_qml)

    print("\n-- 3. MOD 详情翻译简介", flush=True)
    m = core.mods
    got = {}
    m.translationReady.connect(lambda r: got.update(r or {}))
    m.translateTextAsync("")
    pump(500)
    check("空简介不发请求", got.get("ok") is False, got)
    check("明确说「没有简介可以翻」",
          "没有简介" in (got.get("error") or ""), got.get("error"))

    # 真翻一句（网络不通就跳过，不算失败）
    got2 = {}
    m.translationReady.connect(lambda r: got2.update(r or {}))
    m.translateTextAsync("Hello world, this is a test.")
    for _ in range(100):
        pump(300)
        if got2:
            break
    if got2.get("ok"):
        check("真能翻出中文", any("\u4e00" <= ch <= "\u9fff"
                                  for ch in (got2.get("text") or "")),
              (got2.get("text") or "")[:60])
        print("      译文:", (got2.get("text") or "")[:60])
    else:
        print("      [skip] 翻译服务没通：", (got2.get("error") or "")[:60])
        check("失败也有可读原因（不是静默）", bool(got2.get("error")))

    mp = src(os.path.join("qml", "components", "ModPanel.qml"))
    check("有 translateDesc()", "function translateDesc(" in mp)
    check("接了 onTranslationReady", "function onTranslationReady" in mp)
    check("换 MOD 会清掉上一个的译文", "resetDescTranslation()" in mp)
    check("有「译成中文」按钮", "译成中文" in mp)
    check("有「看原文 / 看译文」切换", "看译文" in mp and "看原文" in mp)
    check("没简介时不显示翻译入口",
          '(page.qSelected.desc || "").length > 0' in mp)
    # ★ 这轮踩过：`page.mgr.toast(...)` 报
    #   `TypeError: Property 'toast' ... is not a function`
    #   —— `ModManager.toast` 当时没加 @Slot，QML 看不见它。
    #   只查代码行：注释里保留「不能这样调」的说明是对的。
    mp_code = [ln.strip() for ln in mp.splitlines()
               if ln.strip() and not ln.strip().startswith("//")]
    check("翻译失败不走 ModManager.toast（它以前不是 Slot）",
          not any("page.mgr.toast(" in ln for ln in mp_code),
          [ln for ln in mp_code if "page.mgr.toast(" in ln][:2])
    check("翻译失败改走 core.showToast", "core.showToast" in mp)
    # 顺手把 ModManager.toast 加上 @Slot，以后想调也能调
    mm_src = src(os.path.join("app", "modmanager.py"))
    check("ModManager.toast 现在带 @Slot",
          '@Slot(str, str)\n    def toast(' in mm_src)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "、".join(FAILS)), flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
