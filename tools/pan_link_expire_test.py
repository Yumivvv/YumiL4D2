# -*- coding: utf-8 -*-
"""「视频有重复/多处网盘时，只检测了上面的，下面那个不检测到期时间」。

## 两个独立成因（都在 `Core` 里）

### 成因 A：`_check_pan_expiry` 只在 links 完全为空时才提取

```python
if not rec.get("links"):          # ← 已经缓存过「只有简介链接」就整个跳过
    rec["links"] = extract_links(desc)
    extra = extract_links(topComment)
    ...
```

用户的链接常常分散在**视频简介**和**置顶评论**两处。一旦 `rec["links"]`
里已经存了简介那一条（老缓存、或上次只解析了简介），置顶评论里那条
**永远进不来**，自然也就永远不会被查过期。

### 成因 B：`_detail_payload` 回填状态时按 url 建字典

```python
known = {url: link for link in rec["links"]}   # ← 同 url 会互相覆盖
```

同一个 url 出现两次（简介写一遍、评论再发一遍）时，后一条覆盖前一条，
两条显示成同一个状态 —— 看着就像「只检测了上面那条」。

## 本测试

把网络层（`PANS.check_many`）换成假的，这样离线也能精确验证
「**每一条**链接都拿到了自己的状态」。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from guard import protect_user_data  # noqa: E402

protect_user_data(verbose=False)

from app import core as C  # noqa: E402
from app import panshare as PANS  # noqa: E402

FAILS: list[str] = []

URL_B = "https://pan.baidu.com/s/1mNBVxgENXBEEo5j5r3gEOA?pwd=7y2n"
URL_Q = "https://pan.quark.cn/s/dcb18f65c568?pwd=CdnP"
FUTURE = int(time.time()) + 7 * 86400


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    real_check_many = PANS.check_many
    calls: list[list[str]] = []

    def fake_check_many(urls, workers=4, timeout=8.0, codes=None):
        items = [u for u in urls if u]
        calls.append(list(items))
        out = {}
        for u in items:
            if "baidu.com" in u:
                out[u] = {"ok": True, "state": "expired",
                          "text": "分享已过期", "expireAt": 0,
                          "expireDays": 0, "expired": True}
            elif "quark.cn" in u:
                out[u] = {"ok": True, "state": "ok",
                          "text": "2026-12-02 到期", "expireAt": FUTURE,
                          "expireDays": 7, "expired": False}
            else:
                out[u] = {"ok": False, "state": "unknown", "text": "",
                          "expireAt": 0, "expireDays": 0, "expired": False}
        return out

    PANS.check_many = fake_check_many
    try:
        # 造一个「没连 Core 全套」的轻量对象：只借 _check_pan_expiry 的逻辑。
        # ★ `_check_pan_expiry` 末尾会调 `self.detailReady.emit(self._detail_payload(rec))`，
        #   所以这两个东西都得给上，否则跑不到断言那一步就先 AttributeError 了。
        class Fake:
            _closing = False
            _detail_payload = staticmethod(C.Core._detail_payload)

            def __init__(self):
                self.emitted = []

            def detailReady_emit(self, payload):
                self.emitted.append(payload)

        fake = Fake()
        fake.detailReady = type("S", (), {"emit": lambda s, p: None})()

        # ---------------------------------------------- 成因 A
        print("=== 1. 简介之外的链接（置顶评论里）也必须被查 ===")
        rec = {
            "bvid": "BV1",
            "title": "t",
            "desc": f"百度：{URL_B}",
            "topComment": {"text": f"夸克：{URL_Q}"},
            # ★ 关键：links 里只有简介那条（模拟老缓存 / 上次只解析了简介）
            "links": [{"url": URL_B, "code": "7y2n", "name": "百度网盘"}],
        }
        calls.clear()
        C.Core._check_pan_expiry(fake, rec)
        asked = calls[-1] if calls else []
        check("查过期时把简介的链接发出去了", URL_B in asked, str(asked))
        check("★ 置顶评论里的链接也一起查了（旧代码会漏掉它）",
              URL_Q in asked, str(asked))
        check("两条都写回了 rec['links']",
              len(rec.get("links") or []) == 2,
              str([x.get("url") for x in (rec.get("links") or [])]))
        got = {x.get("url"): x for x in (rec.get("links") or [])}
        check("百度那条是「已过期」",
              got.get(URL_B, {}).get("expired") is True,
              str(got.get(URL_B, {}).get("expired")))
        check("夸克那条有自己的到期时间（不是被百度那条带成过期）",
              got.get(URL_Q, {}).get("expired") is False
              and got.get(URL_Q, {}).get("expireAt") == FUTURE,
              f"expired={got.get(URL_Q, {}).get('expired')} "
              f"at={got.get(URL_Q, {}).get('expireAt')}")

        # ---------------------------------------------- 重复 url
        print("=== 2. 同一个 url 出现两次时，两条状态各自独立 ===")
        rec2 = {
            "bvid": "BV2",
            "title": "t",
            "desc": f"夸克：{URL_Q}",
            "topComment": {"text": f"备用还是它：{URL_Q}"},
            "links": [
                {"url": URL_Q, "code": "CdnP", "name": "夸克网盘"},
            ],
        }
        calls.clear()
        C.Core._check_pan_expiry(fake, rec2)
        asked2 = calls[-1] if calls else []
        check("重复 url 只查一次（不重复发请求）",
              asked2.count(URL_Q) == 1, str(asked2))
        check("links 里不会因为重复而多出一条",
              len(rec2.get("links") or []) == 1,
              str(len(rec2.get("links") or [])))
        check("这条拿到了到期时间",
              (rec2.get("links") or [{}])[0].get("expireAt") == FUTURE,
              str((rec2.get("links") or [{}])[0].get("expireAt")))

        # ---------------------------------------------- 回填按位置
        print("=== 3. _detail_payload 回填：同 url 两条不许互相覆盖 ===")
        rec3 = {
            "bvid": "BV3",
            "title": "t",
            "desc": f"夸克：{URL_Q}",
            "links": [
                {"url": URL_Q, "code": "CdnP", "name": "夸克网盘",
                 "expired": False, "expireText": "2026-12-02 到期",
                 "expireAt": FUTURE, "expireDays": 7},
                {"url": URL_Q, "code": "CdnP", "name": "夸克网盘",
                 "expired": True, "expireText": "分享已过期",
                 "expireAt": 0, "expireDays": 0},
            ],
        }
        d3 = C.Core._detail_payload(rec3)
        l3 = d3.get("links") or []
        check("desc 里同 url 去重成 1 条", len(l3) == 1, str(len(l3)))
        check("留下的这条带状态", l3 and l3[0].get("expireAt") == FUTURE,
              str([x.get("expireAt") for x in l3]))

        # 两条**不同** url 时，各拿各的状态（这条是旧代码也能过的，防回归）
        rec4 = {
            "bvid": "BV4",
            "title": "t",
            "desc": f"百度：{URL_B}\n夸克：{URL_Q}",
            "links": [
                {"url": URL_B, "code": "7y2n", "name": "百度网盘",
                 "expired": True, "expireText": "分享已过期",
                 "expireAt": 0, "expireDays": 0},
                {"url": URL_Q, "code": "CdnP", "name": "夸克网盘",
                 "expired": False, "expireText": "2026-12-02 到期",
                 "expireAt": FUTURE, "expireDays": 7},
            ],
        }
        d4 = C.Core._detail_payload(rec4)
        l4 = d4.get("links") or []
        check("两条不同链接都在", len(l4) == 2, str(len(l4)))
        check("第一条已过期", l4[0].get("expired") is True)
        check("第二条有到期日", l4[1].get("expireAt") == FUTURE,
              str(l4[1].get("expireAt")))
        check("两条文案不同（没互相覆盖）",
              l4[0].get("expireText") != l4[1].get("expireText"),
              f"{l4[0].get('expireText')} vs {l4[1].get('expireText')}")

        # ---------------------------------------------- 源码断言
        print("=== 4. 别改回去（源码断言）===")
        src = open(os.path.join(ROOT, "app", "core.py"),
                   encoding="utf-8").read()
        seg = src.split("def _check_pan_expiry(", 1)[0][-2500:]
        check("不再有「links 为空才提取」的单条件",
              'if not rec.get("links"):\n                rec["links"] = extract_links('
              not in src)
        check("简介和置顶评论两处都参与提取",
              "for src_text in (rec.get(\"desc\")" in src)
        check("按 url 去重后再补",
              "if not u or u in seen:" in src or "u in seen_urls" in src)
        pay = src.split("def _detail_payload(", 1)[1][:4000]
        check("回填按位置对齐", "known_list[idx]" in pay)
        check("条数不一致才退回按 url", "aligned" in pay)

    finally:
        PANS.check_many = real_check_many

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
