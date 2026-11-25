"""蓝奏云直链解析 + 下载的自检。

★ 这套实现的正确性来自「四条硬要求」，缺一条就失败（都实测过）：

  1. **每次请求带随机 X-FORWARDED-FOR / CLIENT-IP**
     —— 蓝奏云的 /file/ 走阿里云 ESA，按来源 IP 风控。不带假 IP 会被下发
        `down_ip=1` 并永久回 `{"url":"?SignError"}`（换域名/换 cookie 都没用）。
  2. **Cookie 要带 `down_ip=1`**（取跳转那一步）
  3. **真直链在 302 的 Location 头里**，必须不跟随重定向去读它
  4. **分享页有两种结构**：密码页（isngis）/ 普通页（iframe → wp_sign）

所以测试重点验这四条 + 各种「解析不了」的形态要给出准确提示。

真实网络只测很少几条（蓝奏云会限流）；大部分是离线结构验证。
"""
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

import re
# Windows 控制台默认 GBK，先把输出换成 UTF-8（否则非 GBK 字符会让测试崩在中途）
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from console_utf8 import setup as _setup_utf8
    _setup_utf8()
except Exception:
    pass

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard import protect_user_data                    # noqa: E402

protect_user_data()

from app import lanzou as LZ                           # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def main() -> int:
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "lanzou.py"), encoding="utf-8").read()

    print("\n-- 1. 假 IP 头（绕开 IP 风控的关键）", flush=True)
    check("有 _rand_ip", hasattr(LZ, "_rand_ip"))
    ips = {LZ._rand_ip() for _ in range(8)}
    check("每次生成的 IP 不一样（随机）", len(ips) >= 6, f"{len(ips)}/8 个不同")
    one = LZ._rand_ip()
    check("IP 格式是四段", len(one.split(".")) == 4, one)
    check("每段 0-255", all(0 <= int(p) <= 255 for p in one.split(".")), one)
    h = LZ._headers()
    check("请求头带 X-FORWARDED-FOR", "X-FORWARDED-FOR" in h)
    check("请求头带 CLIENT-IP", "CLIENT-IP" in h)
    h2 = LZ._headers()
    check("两次请求的假 IP 不同（不会固定同一个）",
          h["X-FORWARDED-FOR"] != h2["X-FORWARDED-FOR"]
          or h["CLIENT-IP"] != h2["CLIENT-IP"])

    print("\n-- 2. Cookie 带 down_ip=1", flush=True)
    h = LZ._headers(cookie="acw_sc__v2=abc", down_ip=True)
    check("down_ip=True 时拼进 Cookie",
          h.get("Cookie") == "down_ip=1; acw_sc__v2=abc", h.get("Cookie"))
    h = LZ._headers(cookie="acw_sc__v2=abc", down_ip=False)
    check("down_ip=False 时不带", h.get("Cookie") == "acw_sc__v2=abc",
          h.get("Cookie"))

    print("\n-- 3. 不跟随重定向（真直链在 Location 里）", flush=True)
    check("有不重定向的 handler", "_NoRedirect" in src)
    check("handler 返回 None（不重定向）",
          "return None" in src and "def redirect_request" in src)
    check("用这个 opener 发请求", "_opener.open" in src)
    check("能返回 Location 头", "want_location" in src)
    check("head_location 先 HEAD 再 GET 兜底",
          "for method in (\"HEAD\", \"GET\")" in src)

    print("\n-- 4. 两种分享页结构", flush=True)
    check("认密码页（down_p / passwddiv）",
          '"function down_p" in page' in src and 'id="passwddiv"' in src)
    check("密码页取 isngis 当 sign", '_js_var(page, "isngis")' in src)
    check("密码页 POST 带 p=<密码> 和 kd=1",
          '"p": password' in src and '"kd": "1"' in src)
    check("普通页走 iframe", '<iframe[^>]*src="([^"]+)"' in src)
    check("普通页取 wp_sign", '_js_var(fn_page, "wp_sign")' in src)
    check("普通页取 ajaxdata（默认 jbEo）",
          '_js_var(fn_page, "ajaxdata") or "jbEo"' in src)
    check("普通页 POST 带 websignkey / signs / ves",
          '"websignkey": ajaxdata' in src and '"ves": "1"' in src)

    print("\n-- 5. 表单地址在独立域名", flush=True)
    check("默认 apifile.woozooo.com", 'AJAX_HOST' in src
          and "apifile.woozooo.com" in src)
    check("页面给绝对地址就用绝对地址", "abs_m.group(0)" in src)
    check("认 ajaxm.php 和 ajaxfile.php 两种",
          "ajax(?:m|file)" in src)
    fake = 'url : "ajaxfile.php?file=329737281"'
    check("相对路径补全成 apifile 域名",
          LZ._find_ajax_url(fake) ==
          "https://apifile.woozooo.com/ajaxfile.php?file=329737281",
          LZ._find_ajax_url(fake))

    print("\n-- 6. ESA 挑战算法", flush=True)
    arg1 = "5D7D11C86038D857F2D9B3CC6F4DF38739AB7C60"
    v1, v2 = LZ.acw_sc_v2(arg1), LZ.acw_sc_v2(arg1)
    check("同输入同输出（确定性）", v1 == v2 and len(v1) == 40, len(v1))
    check("长度 40（40 位 hex 两两 XOR 成 20 字节 → 40 hex 字符）",
          len(v1) == 40, len(v1))
    check("不同 arg1 不同结果", LZ.acw_sc_v2("A" * 40) != v1)
    check("短输入安全返回空", LZ.acw_sc_v2("abc") == "" or len(LZ.acw_sc_v2("abc")) == 0)
    check("认出挑战页", LZ._is_waf_challenge(f"var arg1='{arg1}';"))
    check("正常页面不算挑战",
          not LZ._is_waf_challenge("<html><body>hello</body></html>"))

    print("\n-- 7. 链接清洗与域名识别", flush=True)
    for raw, want in (
        ("https://wwbgv.删除lanzoul.com/文字b01giasjhg",
         "https://wwbgv.lanzoul.com/b01giasjhg"),
        ("https://ww删除ate.lanzou删除e.com/is删除vxE4g4o5qf",
         "https://wwate.lanzoue.com/isvxE4g4o5qf"),
        ("https://wwi.lanzoup.com/iAbCd0xyz", "https://wwi.lanzoup.com/iAbCd0xyz"),
    ):
        check(f"洗中文：{raw[:34]}…", LZ.clean_lanzou_url(raw) == want,
              LZ.clean_lanzou_url(raw))

    for host in ("lanzou.com", "lanzoui.com", "lanzoux.com", "lanzoup.com",
                 "lanzouu.com", "lanzout.com", "lanzouc.com", "lanzoul.com",
                 "lanzoum.com", "lanzoue.com"):
        if not LZ.is_lanzou(f"https://ww1.{host}/iABC123"):
            check(f"认 {host}", False)
            break
    else:
        check("认全部 10 种域名变体", True)
    check("别家网盘不误判", not LZ.is_lanzou("https://pan.baidu.com/s/1abc"))

    print("\n-- 8. 文件名 / 大小解析", flush=True)
    page = """
    <title>文件</title>
    <meta name="description" content="文件大小：49.0 M" />
    <span class="filename">栞那CODMW2026 M4 V2.7z</span>
    """
    name, size = LZ._page_meta(page)
    check("拿到文件名", name == "栞那CODMW2026 M4 V2.7z", name)
    check("拿到大小", size == "49.0 M", size)
    check("title 只有「文件」不当名字", LZ._page_meta("<title>文件</title>")[0] == "")

    print("\n-- 9. 「解析不了」的形态都说清楚", flush=True)
    # ★ 2026-11 起「文件夹分享」不再是「解析不了」的形态了 ——
    #   现在会真的把里面的文件列出来并解析第一个（见 list_folder）。
    #   所以这里改盯「确实支持了」，而不是「会提示去浏览器」。
    for kw, why in (
        ("分享页是空的", "空壳页 → 提取码错/分享失效"),
        ("提取码不对", "密码错误 → 转述蓝奏云原话"),
        ("needManual", "带 needManual，界面能引导"),
        ("没找到下载框", "页面结构变了 → 明确说"),
    ):
        check(f"有「{why}」", kw in src)
    check("文件夹分享现在会列文件", "def list_folder(" in src)
    check("文件夹里的文件能解析直链", "def _resolve_file_page(" in src)
    check("文件夹内文件用 websign='2' 且不带提取码",
          '"websign": "2"' in src)

    print("\n-- 10. 下载", flush=True)
    check("有 download_direct", hasattr(LZ, "download_direct"))
    check("下载也带假 IP 头", "_headers(referer=referer)" in src)
    check("兼容 gzip 裸流（有些节点会这么回）", "GzipFile" in src)
    check("空文件算失败", "下载下来是空文件" in src)

    print("\n-- 10b. 点「本地下载」必须有反应（这轮的 bug）", flush=True)
    # 用户报的「点了连反馈都没有」：`addPanFile` 的 @Slot 写成了 str，
    # QML 传 JS 对象被 Qt 强转成字符串 → Python 里 info.get() 抛
    # AttributeError → 被 Qt 吞掉 → 界面零反馈。
    import os as _os
    import sys as _sys

    from PySide6.QtGui import QGuiApplication as _QGui
    from app.core import Core as _Core                 # noqa: PLC0415

    _app = _QGui.instance() or _QGui([])
    _core = _Core(_app)
    globals()["_KEEP_CORE2"] = _core
    _dq = _core.downloads

    mo = _dq.metaObject()
    sig = ""
    for _i in range(mo.methodCount()):
        _m = mo.method(_i)
        _s = _m.methodSignature().data().decode()
        if "addPanFile" in _s:
            sig = _s
    check("addPanFile 的槽签名收 QVariantMap（不是 QString）",
          sig == "addPanFile(QVariantMap)", sig)

    # 传 dict 要能进队列
    before = _dq.totalCount
    r = _dq.addPanFile({"url": "https://wwi.lanzoup.com/iAbCd0xyz",
                        "name": "蓝奏云", "code": "x", "label": "测试"})
    check("传 dict 能成功入队", bool(r.get("ok")), r)
    check("任务数 +1", _dq.totalCount == before + 1, _dq.totalCount)
    # 传裸字符串也要兜住（兼容老调用方），不能抛
    try:
        r2 = _dq.addPanFile("https://wwi.lanzoup.com/iAbCd0xyz")
        check("传裸字符串也不炸", isinstance(r2, dict), r2)
    except Exception as _e:                            # noqa: BLE001
        check("传裸字符串也不炸", False, repr(_e))
    # 空 / 垃圾输入要有明确失败（不是静默）
    r3 = _dq.addPanFile({})
    check("空对象返回 ok=False", not r3.get("ok"), r3)
    check("空对象带错误原因", bool(r3.get("error")), r3.get("error"))

    # 清理（别真去下载测试链接）
    for _t in _dq.tasks:
        _dq.cancelTask(_t["id"])
    for _ in range(50):
        if _dq.activeCount == 0:
            break
        _app.processEvents()
        import time as _time
        _time.sleep(0.05)
    _dq.clearFinished()

    print("\n-- 11. 真实链接（只测 1 条，避免被限流）", flush=True)
    try:
        res = LZ.resolve_lanzou("https://wwawf.lanzouu.com/ijldw4f627uf",
                                password="9ks0", timeout=30)
        if res["ok"]:
            check("真实分享能解析出 CDN 直链", True)
            check("直链指向 CDN（不是页面）",
                  "webgetstore.com" in res["url"] or "/file/" not in res["url"],
                  res["url"][:60])
            check("文件名正确",
                  res.get("filename") == "【马格南】决斗时刻.7z",
                  res.get("filename"))
            check("大小正确", res.get("sizeText") == "747.1 K",
                  res.get("sizeText"))
        else:
            # 被限流 / 断网时不算失败，但要说清
            print("      [skip] 这条没解析成功：", (res.get("error") or "")[:70])
            check("失败时有可读原因（不是静默）", bool(res.get("error")))
    except Exception as e:                          # noqa: BLE001
        print("      [skip] 网络异常：", repr(e))

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "、".join(FAILS)), flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
