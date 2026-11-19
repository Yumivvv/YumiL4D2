"""翻译接口的回归：不许再出现「HTTP 403」，长文本必须能翻。

用户报的「翻译 HTTP 403」有两个根因，这个脚本把两条都钉住：

**根因 1：MyMemory 超长时返回 HTTP 200 + body 里 responseStatus=403。**
它的 q 参数上限是 500 **字符**，超了不返回 4xx，而是回一个
``{"responseStatus":403,"responseDetails":"QUERY LENGTH LIMIT EXCEEDED..."}``。
旧代码只判 ``resp.status != 200``，于是：
  · 这句英文提示被当成译文显示给用户；
  · 或者被当成「语向不对」反复重试，最后冒出来一句「HTTP 403」。

**根因 2：兜底接口 Yandex 已经彻底停用。**
实测（2026-11）：``srv=android`` → 403 ``{"code":405,"message":"Session is
invalid"}``；去掉 srv → 410 ``API v1 is no longer active``。
所以 MyMemory 一失败，用户看到的就是那句 Yandex 的 403。
现在兜底换成腾讯交互翻译（transmart，免 key、自动识别语种、单块 6000 字符）。

跑法：``python -X utf8 tools/translate_test.py``
需要联网；连不上时相关断言会标 SKIP 而不是 FAIL。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import protect_user_data      # noqa: E402

protect_user_data(verbose=False)

import app.workshop_net as WN            # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name
          + (("  " + str(extra)) if extra != "" else ""), flush=True)
    if not ok:
        FAILS.append(name)


def skip(name, why=""):
    print("  skip " + name + (("  " + str(why)) if why else ""), flush=True)
    SKIPS.append(name)


def online() -> bool:
    """能连上 MyMemory 就算联网。"""
    try:
        r = WN._translate_chunk_mymemory("Hello world.", "zh", 12, "en")
        return bool(r.get("ok"))
    except Exception:              # noqa: BLE001
        return False


print("=== 1. 常量与 provider 配置 ===")
check("MyMemory 有明确的字符上限常量",
      isinstance(getattr(WN, "MYMEMORY_MAX_CHARS", None), int)
      and WN.MYMEMORY_MAX_CHARS > 0, getattr(WN, "MYMEMORY_MAX_CHARS", None))
check("腾讯兜底也有上限常量",
      isinstance(getattr(WN, "TRANSMART_MAX_CHARS", None), int)
      and WN.TRANSMART_MAX_CHARS > 0,
      getattr(WN, "TRANSMART_MAX_CHARS", None))
check("腾讯的接口地址指向 transmart.qq.com",
      "transmart.qq.com" in WN.TRANSLATE_HOST, WN.TRANSLATE_HOST)
check("Yandex 的接口已经不再被引用",
      "translate.yandex" not in WN.TRANSLATE_HOST
      and not hasattr(WN, "_translate_chunk_yandex"),
      WN.TRANSLATE_HOST)
check("移除了用不上的 _yandex_ucid", not hasattr(WN, "_yandex_ucid"))

src = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app", "workshop_net.py"),
    encoding="utf-8").read()
check("provider 列表里是 mymemory + transmart",
      '("mymemory", _translate_chunk_mymemory)' in src
      and '("transmart", _translate_chunk_transmart)' in src)
check("MyMemory 会检查 body 里的 responseStatus（不只是 HTTP 状态码）",
      'j.get("responseStatus")' in src)
check("识别 QUERY LENGTH LIMIT 这个具体报错",
      "QUERY LENGTH LIMIT" in src)
check("识别 quotaFinished（额度用完）", 'j.get("quotaFinished")' in src)
check("分段上限留了余量（< MYMEMORY_MAX_CHARS）",
      "_split_chunks(src, 480)" in src)

print()
print("=== 2. MyMemory 超限必须判失败（不能当译文）===")
# ★ 这是根因 1 的复现：520 个字符 > 500，MyMemory 回 200 + responseStatus 403
long_chunk = "あ" * (WN.MYMEMORY_MAX_CHARS + 20)
r = WN._translate_chunk_mymemory(long_chunk, "zh", 12, "ja")
check("超长 chunk 直接返回失败", not r.get("ok"), r.get("ok"))
check("错误里说清楚是「太长」",
      "长" in (r.get("error") or ""), r.get("error"))
check("没有把接口的英文提示当译文返回",
      "QUERY LENGTH" not in (r.get("text") or "").upper(),
      (r.get("text") or "")[:60])

print()
print("=== 3. 腾讯兜底：MyMemory 挂了它要能顶上 ===")
if not online():
    skip("腾讯兜底实测（当前网络连不上翻译服务）")
else:
    orig_mm = WN._translate_chunk_mymemory
    orig_tm = WN._translate_chunk_transmart
    try:
        # 打瘸 MyMemory
        WN._translate_chunk_mymemory = lambda *a, **k: {
            "ok": False, "text": "", "error": "模拟失败"}
        got = WN.translate("This mod replaces the AK47 with a custom skin.")
        check("MyMemory 挂掉后仍然翻成功", got.get("ok") is True, got.get("ok"))
        check("用的是腾讯 transmart", got.get("provider") == "transmart",
              got.get("provider"))
        check("译文确实像中文", bool(got.get("text"))
              and any("\u4e00" <= ch <= "\u9fff" for ch in got["text"]),
              (got.get("text") or "")[:50])
        # 两边都挂：错误里不该再出现 Yandex 的 403
        WN._translate_chunk_mymemory = lambda *a, **k: {
            "ok": False, "text": "", "error": "A 挂了"}
        WN._translate_chunk_transmart = lambda *a, **k: {
            "ok": False, "text": "", "error": "B 挂了"}
        bad = WN.translate("This mod replaces the AK47.")
        check("两边都失败时返回 ok=False", bad.get("ok") is False)
        check("最终报错里没有「403」", "403" not in str(bad.get("error")),
              bad.get("error"))
        check("最终报错里没有 yandex", "yandex" not in str(bad).lower(),
              bad.get("error"))
    finally:
        WN._translate_chunk_mymemory = orig_mm
        WN._translate_chunk_transmart = orig_tm

print()
print("=== 4. 超长简介（>500 字符）现在能翻完 ===")
if not online():
    skip("超长文本实测（当前网络连不上翻译服务）")
else:
    LONG = ("This mod replaces the M16 rifle with a custom skin. "
            "Includes new textures, muzzle flash and sounds. ") * 20
    print("  原文 %d 字符（旧代码在这里必定报 HTTP 403）" % len(LONG))
    got = WN.translate(LONG)
    check("超长简介翻成功", got.get("ok") is True,
          got.get("error") or "")
    check("译文有内容", len(got.get("text") or "") > 20,
          len(got.get("text") or ""))
    check("没有把分段上限的报错混进译文",
          "QUERY LENGTH" not in (got.get("text") or "").upper())
    # 分段本身也必须都在上限内
    for i, c in enumerate(WN._split_chunks(LONG, 480)):
        check("第 %d 段没超 MyMemory 上限" % i,
              len(c) <= WN.MYMEMORY_MAX_CHARS, len(c))

print()
print("=== 5. 语种识别仍然正确（预料逻辑没被改坏）===")
check("英文", WN.detect_lang("This is an English description.") == "en")
check("日文", WN.detect_lang("このMODはライフルを置き換えます。") == "ja")
check("韩文", WN.detect_lang("이 모드는 총을 교체합니다.") == "ko")
check("中文不翻（直接跳过）",
      WN.looks_chinese("这是一个中文简介，用来测试跳过翻译。"))
r = WN.translate("这是一个中文简介，不需要翻译。")
check("中文走 skipped 分支",
      r.get("ok") is True and r.get("skipped") is True, str(r)[:80])

print()
print("=== 6. 通常长度的简介仍然翻得动 ===")
if not online():
    skip("短文本实测（当前网络连不上翻译服务）")
else:
    got = WN.translate("Hello world, this is a test of the translator.")
    check("短文本翻成功", got.get("ok") is True, got.get("error") or "")
    check("有中文译文", any("\u4e00" <= ch <= "\u9fff" for ch in
                           (got.get("text") or "")), (got.get("text") or "")[:40])

print()
if SKIPS:
    print("跳过 %d 项：%s" % (len(SKIPS), " / ".join(SKIPS)))
if FAILS:
    print("失败 %d 项：%s" % (len(FAILS), FAILS))
    sys.exit(1)
print("全部通过")
