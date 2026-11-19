# Yumi的L4D2工具箱
# Copyright (C) 2026 ZengDeRong
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""蓝奏云直链解析 + 下载。

实现对齐了实测可用的方案（参考 `E:/mrxz/蓝奏云直链下载.zip` 里的
index.php / down.js，并用真实分享链接逐条验证过）。蓝奏云这条路有
**四个必须踩对的点**，缺一个就失败：

## 1. 假 IP 头（最关键）

蓝奏云的 /file/ 直链走阿里云 ESA，会按来源 IP 做风控。同一个出口 IP 请求多了之后
服务端下发 `down_ip=1` cookie，之后所有请求都回 `{"url":"?SignError"}`。
**换域名、换分享、换 cookie 都没用** —— 必须每次请求带一个随机的
`X-FORWARDED-FOR` / `CLIENT-IP`，让 ESA 认为来源是不同客户端。
这是「本机能解析」和「本机一直被限流」的分水岭。

## 2. Cookie 要带 `down_ip=1`

取跳转那一步必须带 `down_ip=1; acw_sc__v2=…`，只带 acw 会被拒。

## 3. 真直链在 **302 的 Location 头** 里，不在响应体

`dom + "/file/" + url` 那个地址只是「中转页」。要
  ① 先 GET 一次让它过掉 ESA 挑战（这一步的响应体是挑战页，不用管）
  ② 再 HEAD（失败回退 GET）拿 `Location` —— 那才是 `https://zip3.webgetstore.com/…`
响应体是 gzip 压缩的原始文件这条也成立，但那是**直接命中 CDN** 时的行为；
走 Location 拿到的是干净地址，不会再有压缩问题。

## 4. 分享页有两种结构

* **密码页**：`function down_p` / `id="passwddiv"`
  → 取 `var isngis` 当 sign，POST `action=downprocess&sign=…&p=<密码>&kd=1`
* **普通页**：页面里有个 `<iframe src="/fn?…">`
  → 进 iframe 取 `var wp_sign` 和 `var ajaxdata`
  → POST `action=downprocess&websignkey=<ajaxdata>&signs=<ajaxdata>&sign=<wp_sign>&websign=&kd=1&ves=1`

表单地址不在分享页那个域名：`https://apifile.woozooo.com/ajaxfile.php?file=<数字>`
（页面里可能只给相对路径，要补全）。

## 其它已知形态（明确报错，不假装）

* **文件夹分享**（`/filemoreajax.php`）：一个链接装多个文件，要人工挑
* **反刷节点**（`lanzoum.com` 回 JS 混淆页）：要执行 JS
* **空壳页**（<1600 字节、title 空）：提取码错 / 分享失效
"""

from __future__ import annotations

import gzip
import html
import json
import os
import random
import re
import time
import urllib.parse
import urllib.request
import zlib

from . import workshop_dns as WDNS

# 和参考实现一致的 UA：Chrome 72。新版 UA 反而更容易被 ESA 挑出来。
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36")

# 域名换过十几茬，用「含 lanzou」判断
LANZOU_HINT = "lanzou"

# 取直链的表单地址（不在分享页域名下）
AJAX_HOST = "https://apifile.woozooo.com/"

# ---------------------------------------------------------------------------
# 1. 假 IP 头
#
# 这些前缀是实测在国内家用宽带里常见的段，ESA 不会特判。
# 每次请求现随机一个，配合下面的 CLIENT-IP 一起发。
# ---------------------------------------------------------------------------
_IP_PREFIX = ["218", "218", "66", "66", "218", "218", "60", "60", "202", "204",
              "66", "66", "66", "59", "61", "60", "222", "221", "66", "59",
              "60", "60", "66", "218", "218", "62", "63", "64", "66", "66",
              "122", "211"]


def _rand_ip() -> str:
    """造一个看起来像国内家用宽带的 IP。"""
    def seg() -> int:
        return int(round((600000 + random.random() * (2550000 - 600000)) / 10000))
    return f"{random.choice(_IP_PREFIX)}.{seg()}.{seg()}.{seg()}"


# ---------------------------------------------------------------------------
# 2. ESA 的 acw_sc__v2 挑战
#
# 页面里 `<script>var arg1='<40位hex>';…`，算法是固定的：
#   按 POS_LIST 置换 arg1 的字符，再和 MASK 逐字节 XOR（当十六进制两两配对）。
# ---------------------------------------------------------------------------
POS_LIST = [15, 35, 29, 24, 33, 16, 1, 38, 10, 9, 19, 31, 40, 27, 22, 23,
            25, 13, 6, 11, 39, 18, 20, 8, 14, 21, 32, 26, 2, 30, 7, 4,
            17, 5, 3, 28, 34, 37, 12, 36]
MASK = "3000176000856006061501533003690027800375"


def acw_sc_v2(arg1: str) -> str:
    """算 acw_sc__v2。给固定 arg1 必得固定结果。"""
    if not arg1 or len(arg1) < 40:
        return ""
    out = [""] * 40
    for i, ch in enumerate(arg1):
        for j, pos in enumerate(POS_LIST):
            if pos == i + 1:
                out[j] = ch
    s = "".join(out)
    res = []
    limit = min(len(s), len(MASK))
    for i in range(0, limit - 1, 2):
        try:
            a = int(s[i:i + 2], 16)
            b = int(MASK[i:i + 2], 16)
        except ValueError:
            return ""
        res.append(f"{a ^ b:02x}")
    return "".join(res)


# 兼容旧名字
def _acw_v2(arg1: str) -> str:
    return acw_sc_v2(arg1)


def _is_waf_challenge(text: str) -> bool:
    return bool(text) and "var arg1=" in text and len(text) < 20000


def _solve_acw(page: str) -> str:
    """从挑战页抠 arg1 算 cookie；不是挑战页返回空串。"""
    m = re.search(r"var\s+arg1\s*=\s*['\"]([0-9a-fA-F]{40})['\"]", page, re.I)
    if not m:
        return ""
    return acw_sc_v2(m.group(1))


# ---------------------------------------------------------------------------
# 3. 带假 IP 的 HTTP
# ---------------------------------------------------------------------------
def _decode(raw: bytes, encoding: str) -> str:
    enc = (encoding or "").lower()
    if "gzip" in enc:
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    elif "deflate" in enc:
        try:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        except zlib.error:
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                pass
    return raw.decode("utf-8", "replace")


def _headers(cookie: str = "", referer: str = "", ajax: bool = False,
             down_ip: bool = False) -> dict:
    """每个请求都带一对新的假 IP —— 这是绕开 IP 风控的关键。"""
    h = {
        "User-Agent": UA,
        "X-FORWARDED-FOR": _rand_ip(),
        "CLIENT-IP": _rand_ip(),
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "*/*;q=0.8"),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }
    if ajax:
        h["Accept"] = "application/json, text/javascript, */*; q=0.01"
        h["Content-Type"] = "application/x-www-form-urlencoded"
        h["X-Requested-With"] = "XMLHttpRequest"
    if cookie:
        h["Cookie"] = f"down_ip=1; {cookie}" if down_ip else cookie
    if referer:
        h["Referer"] = referer
    return h


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """**不跟随 302** —— 拿真直链全靠读 Location，跟了就看不见了。

    urllib 默认会自动跟随 3xx，于是 `head_location()` 永远读不到 Location，
    表现就是「中转地址拿到了但拿不到最终跳转」。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None                              # 返回 None = 不重定向


_opener = urllib.request.build_opener(_NoRedirect)


def _request(url: str, data: bytes | None = None, timeout: int = 25,
             cookie: str = "", referer: str = "", ajax: bool = False,
             down_ip: bool = False, method: str | None = None,
             want_location: bool = False):
    """发一次请求。

    ``want_location=True`` 时不跟随跳转、直接返回 ``Location`` 头
    （拿真直链就靠它）。
    """
    h = _headers(cookie, referer, ajax, down_ip)
    req = urllib.request.Request(
        url, data=data, headers=h,
        method=method or ("POST" if data is not None else "GET"))
    try:
        with _opener.open(req, timeout=timeout) as r:
            loc = r.headers.get("Location") or ""
            if want_location:
                return (int(getattr(r, "status", 200) or 200), loc, "")
            body = _decode(r.read(), r.headers.get("Content-Encoding") or "")
            return (int(getattr(r, "status", 200) or 200), body, loc)
    except urllib.error.HTTPError as e:
        # 3xx 在 urllib 里也是 HTTPError（因为不跟随了），Location 在 headers 里
        loc = ""
        try:
            loc = (e.headers.get("Location") or "") if e.headers else ""
        except Exception:                        # noqa: BLE001
            loc = ""
        if want_location:
            return int(e.code), loc, ""
        try:
            raw = e.read()
            body = _decode(raw, (e.headers.get("Content-Encoding") or "")
                           if e.headers else "")
        except Exception:                        # noqa: BLE001
            body = ""
        return int(e.code), body, loc
    except Exception as e:                       # noqa: BLE001
        return 0, f"[error] {e}", ""


class _Session:
    """一次解析的会话：记住 acw cookie，遇到挑战自动解。"""

    def __init__(self) -> None:
        self.cookie = ""

    def get_text(self, url: str, referer: str = "", timeout: int = 25) -> str:
        """GET，遇到 ESA 挑战自动求解重试（最多 4 次）。"""
        for _ in range(4):
            st, body, _loc = _request(url, timeout=timeout,
                                      cookie=(f"acw_sc__v2={self.cookie}"
                                              if self.cookie else ""),
                                      referer=referer)
            if st == 0:
                return ""
            if _is_waf_challenge(body):
                ck = _solve_acw(body)
                if ck:
                    self.cookie = ck
                    continue
            return body
        return ""

    def head_location(self, url: str, referer: str, timeout: int = 25) -> str:
        """HEAD 拿 302 的 Location；没有就 GET 再看看。

        ★ 真直链只在 Location 里 —— 这是最容易漏的一步。
          直接读响应体只会拿到那个「验证并下载」的 HTML。
        """
        for method in ("HEAD", "GET"):
            st, loc, _b = _request(url, timeout=timeout,
                                   cookie=(f"acw_sc__v2={self.cookie}"
                                           if self.cookie else ""),
                                   referer=referer, down_ip=True,
                                   method=method, want_location=True)
            if loc:
                return loc
            # HEAD 不带 body，可能触发挑战；GET 一次解掉再重试 HEAD
            if method == "GET":
                st2, body, _l = _request(url, timeout=timeout,
                                         cookie=(f"acw_sc__v2={self.cookie}"
                                                 if self.cookie else ""),
                                         referer=referer, down_ip=True)
                if _is_waf_challenge(body):
                    ck = _solve_acw(body)
                    if ck:
                        self.cookie = ck
                        st3, loc3, _x = _request(
                            url, timeout=timeout,
                            cookie=f"acw_sc__v2={self.cookie}",
                            referer=referer, down_ip=True,
                            method="HEAD", want_location=True)
                        if loc3:
                            return loc3
        return ""


# ---------------------------------------------------------------------------
# 4. 地址清洗 / 识别
# ---------------------------------------------------------------------------
def clean_lanzou_url(url: str) -> str:
    """洗掉作者为了防和谐插进链接里的中文。

    实测样本：
        https://wwbgv.删除lanzoul.com/文字b01giasjhg
        https://ww删除ate.lanzou删除e.com/is删除vxE4g4o5qf
        https://wwbgv.【删】lanzoul.com/b01gih3e3e

    ★ 不能「保留 http 到第一个非 ASCII」—— 那样 `lanzoul.com` 会被截成
      `lanzou`，域名就废了。要**逐段去掉中文再拼回去**。
    """
    u = (url or "").strip().strip("\"'")
    for token in ("【删】", "（删）", "(删)", "删除", "文字", "去掉", "防和谐"):
        u = u.replace(token, "")
    u = re.sub(r"[^\x21-\x7e]", "", u)
    return u.rstrip(".,;)")


def is_lanzou(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(clean_lanzou_url(url)).hostname or "").lower()
    except ValueError:
        return False
    return LANZOU_HINT in host


def _js_var(page: str, name: str) -> str:
    """取 `var <name> = '…'` 的值（也认纯数字，如 `var kdns = 1;`）。"""
    out = ""
    for m in re.finditer(rf"\b{name}\s*=\s*(['\"])(.*?)\1", page, re.S):
        val = m.group(2).strip()
        if val:
            out = val
    if out:
        return out
    for m in re.finditer(rf"\b{name}\s*=\s*(-?\d+(?:\.\d+)?)\s*[;,\n]", page):
        out = m.group(1)
    return out


def _find_ajax_url(page: str, origin: str = "") -> str:
    """找取直链的表单地址。

    页面里可能写相对路径，但接口其实在独立域名 `apifile.woozooo.com` 上
    （分享页那个域名不提供这个接口）。
    """
    dec = str(page or "").replace("\\/", "/")
    m = re.search(r"ajax(?:m|file)\.php\?file=\d+", dec, re.I)
    if not m:
        return ""
    abs_m = re.search(r"https?://[^'\"\s<>]+?ajax(?:m|file)\.php\?file=\d+",
                      dec, re.I)
    if abs_m:
        return abs_m.group(0)
    return AJAX_HOST + m.group(0)


# 兼容旧名字
def _ajax_url(page: str) -> str:
    return _find_ajax_url(page)


def _page_meta(page: str) -> tuple[str, str]:
    """抠 `(文件名, 大小文本)`。新版 title 只有「文件」两字。"""
    name = ""
    size_text = ""
    m = re.search(r'<span[^>]*class="[^"]*filename[^"]*"[^>]*>(.*?)</span>',
                  page, re.S | re.I)
    if m:
        name = _strip_tags(m.group(1))
    m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"',
                  page, re.I)
    if m:
        desc = html.unescape(m.group(1))
        sm = re.search(r"文件大小[:：]\s*([\d.]+\s*[A-Za-z]+)", desc)
        if sm:
            size_text = sm.group(1).strip()
        elif "：" in desc and not desc.startswith("文件大小"):
            name = name or desc.split("：", 1)[1].strip()
    m = re.search(r'class="[^"]*n_filesize[^"]*"[^>]*>(.*?)<', page, re.S | re.I)
    if m and not size_text:
        sm = re.search(r"([\d.]+\s*[A-Za-z]+)", _strip_tags(m.group(1)))
        if sm:
            size_text = sm.group(1).strip()
    if not name:
        m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
        if m:
            t = html.unescape(_strip_tags(m.group(1))).strip()
            t = re.split(r"\s*-\s*蓝奏云", t)[0].strip()
            if t and t not in ("文件", "下载", "蓝奏云"):
                name = t
    return name, size_text


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]{1,200}>", "", s or "")).strip()


def _safe_filename(name: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(name or "")).strip()
    return s.strip(". ")[:120]


# ---------------------------------------------------------------------------
# 5. 主流程
# ---------------------------------------------------------------------------
def resolve_lanzou(url: str, password: str = "", timeout: int = 25) -> dict:
    """解析蓝奏云分享链接，返回 ``{ok, url, filename, size, sizeText, error}``。

    ``url`` 是**最终 CDN 直链**（`https://zip3.webgetstore.com/…`），
    可以直接下载。
    """
    url = clean_lanzou_url(url)
    if not url:
        return {"ok": False, "url": "", "filename": "", "size": 0,
                "error": "链接是空的"}
    if not is_lanzou(url):
        return {"ok": False, "url": "", "filename": "", "size": 0,
                "error": "不是蓝奏云的链接"}

    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(url))
    sess = _Session()

    page = sess.get_text(url, timeout=timeout)
    if not page:
        return {"ok": False, "url": "", "filename": "", "size": 0,
                "error": "打不开分享页（网络不通或链接失效）"}

    filename, size_text = _page_meta(page)

    # ---- 已知的「解析不了」形态，先认出来，别白跑 ----
    if "filemoreajax.php" in page or ("folder" in page and "infomores" in page):
        return {"ok": False, "url": "", "filename": filename, "size": 0,
                "sizeText": size_text, "needManual": True,
                "error": "这是一个文件夹分享（里面有好几个文件），"
                         "程序只能解析单个文件的直链。"
                         "请在浏览器打开，挑需要的那个下载"}
    if len(page) < 1600 and not filename and not _is_waf_challenge(page):
        hint = "（提取码可能不对）" if password else "（这个分享要提取码）"
        return {"ok": False, "url": "", "filename": "", "size": 0,
                "error": f"分享页是空的，拿不到文件信息{hint}"}

    # ---- 两种页面结构 ----
    is_pwd_page = ("function down_p" in page) or ('id="passwddiv"' in page)
    post_data: dict = {}
    ajax_url = ""
    ajax_referer = url

    if is_pwd_page:
        # 密码页：取 isngis 当 sign
        if not password:
            return {"ok": False, "url": "", "filename": filename, "size": 0,
                    "sizeText": size_text,
                    "error": "这个分享需要提取码"}
        sign = _js_var(page, "isngis")
        ajax_url = _find_ajax_url(page, origin)
        if not sign or not ajax_url:
            return {"ok": False, "url": "", "filename": filename, "size": 0,
                    "sizeText": size_text,
                    "error": "密码页解析失败（找不到 sign / 接口地址）"}
        post_data = {"action": "downprocess", "sign": sign,
                     "p": password, "kd": "1"}
    else:
        # 普通页：进 iframe 取 wp_sign
        m = re.search(r'<iframe[^>]*src="([^"]+)"', page, re.I)
        if not m:
            return {"ok": False, "url": "", "filename": filename, "size": 0,
                    "sizeText": size_text,
                    "error": "分享页里没找到下载框（页面结构可能变了）"}
        fn_path = html.unescape(m.group(1))
        fn_url = urllib.parse.urljoin(origin + "/", fn_path)
        fn_page = sess.get_text(fn_url, referer=url, timeout=timeout)
        if not fn_page:
            return {"ok": False, "url": "", "filename": filename, "size": 0,
                    "sizeText": size_text, "error": "下载页打不开"}
        wp_sign = _js_var(fn_page, "wp_sign")
        ajaxdata = _js_var(fn_page, "ajaxdata") or "jbEo"
        ajax_url = _find_ajax_url(fn_page, origin)
        if not wp_sign or not ajax_url:
            return {"ok": False, "url": "", "filename": filename, "size": 0,
                    "sizeText": size_text,
                    "error": "下载页解析失败（找不到 wp_sign / 接口地址）"}
        post_data = {"action": "downprocess", "websignkey": ajaxdata,
                     "signs": ajaxdata, "sign": wp_sign,
                     "websign": "", "kd": "1", "ves": "1"}
        ajax_referer = fn_url

    # ---- POST 换中转地址 ----
    body_bytes = urllib.parse.urlencode(post_data).encode()
    st, resp, _loc = _request(
        ajax_url, data=body_bytes, timeout=timeout,
        cookie=(f"acw_sc__v2={sess.cookie}" if sess.cookie else ""),
        referer=ajax_referer, ajax=True)
    if st == 0:
        return {"ok": False, "url": "", "filename": filename, "size": 0,
                "sizeText": size_text, "error": "取中转地址失败（网络不通）"}

    # 撞挑战页就解了再试一次
    if _is_waf_challenge(resp):
        ck = _solve_acw(resp)
        if ck:
            sess.cookie = ck
            st, resp, _loc = _request(
                ajax_url, data=body_bytes, timeout=timeout,
                cookie=f"acw_sc__v2={sess.cookie}",
                referer=ajax_referer, ajax=True)

    try:
        data = json.loads(resp)
    except ValueError:
        return {"ok": False, "url": "", "filename": filename, "size": 0,
                "sizeText": size_text,
                "error": f"取中转地址失败：{resp[:80]}"}

    if str(data.get("zt")) != "1":
        inf = str(data.get("inf") or "")
        if "密码" in inf:
            return {"ok": False, "url": "", "filename": filename, "size": 0,
                    "sizeText": size_text,
                    "error": f"提取码不对（蓝奏云说：{inf}）"}
        return {"ok": False, "url": "", "filename": filename, "size": 0,
                "sizeText": size_text,
                "error": f"蓝奏云拒绝了这次请求：{inf or '未知原因'}"}

    dom = str(data.get("dom") or "").rstrip("/")
    mid = str(data.get("url") or "").lstrip("/")
    if not dom or not mid:
        return {"ok": False, "url": "", "filename": filename, "size": 0,
                "sizeText": size_text, "error": "没拿到中转地址"}
    if not filename:
        filename = str(data.get("inf") or "").strip()

    relay = f"{dom}/file/{mid}"

    # ---- 先 GET 一次过掉挑战（只为了拿 cookie，不用它的响应体）----
    sess.get_text(relay, referer=url, timeout=timeout)

    # ---- 再 HEAD/GET 拿 302 的 Location：这才是真直链 ----
    loc = sess.head_location(relay, referer=origin, timeout=timeout)
    if not loc:
        return {"ok": False, "url": "", "filename": filename, "size": 0,
                "sizeText": size_text, "needManual": True,
                "error": "拿到文件信息"
                         f"（{filename or '文件'}，{size_text or '大小未知'}），"
                         "但没拿到最终跳转地址。"
                         "请过一会儿再试，或直接在浏览器打开这条链接下载"}

    final = urllib.parse.urljoin(relay, loc)
    if not filename:
        # CDN 地址里常带 ?fn=<文件名>
        q = urllib.parse.urlparse(final)
        fn = urllib.parse.parse_qs(q.query).get("fn", [""])[0]
        if fn:
            filename = fn
        elif pos := os.path.basename(q.path):
            filename = urllib.parse.unquote(pos)

    return {"ok": True, "url": final, "filename": filename, "size": 0,
            "sizeText": size_text, "error": "", "verified": True}


# ---------------------------------------------------------------------------
# 6. 下载
#
# 拿到的是 CDN 直链，正常 GET 就是文件本体。为了稳妥仍然：
#   · 带假 IP / Referer（CDN 也看 Referer）
#   · 嗅一眼前 2 字节，若是 gzip 裸流就边下边解（有些节点会这么回）
# ---------------------------------------------------------------------------
def download_direct(url: str, dest_dir: str, filename: str = "",
                    referer: str = "", progress=None,
                    timeout: int = 300) -> dict:
    """下载直链到 ``dest_dir``，返回 ``{ok, path, bytes, error}``。"""
    import io as _io

    url = (url or "").strip()
    if not url:
        return {"ok": False, "path": "", "bytes": 0, "error": "没有下载地址"}
    os.makedirs(dest_dir, exist_ok=True)

    name = _safe_filename(filename) or "lanzou_file"
    dst = os.path.join(dest_dir, name)
    stem, ext = os.path.splitext(name)
    n = 1
    while os.path.exists(dst):
        dst = os.path.join(dest_dir, f"{stem} ({n}){ext}")
        n += 1
        if n > 999:
            return {"ok": False, "path": "", "bytes": 0, "error": "同名文件太多"}

    headers = _headers(referer=referer)
    tmp = dst + ".part"
    got = 0
    try:
        req = urllib.request.Request(url, headers=headers)
        with WDNS.urlopen(req, timeout=timeout) as r:
            total = int(r.headers.get("Content-Length") or 0)
            head = r.read(2)
            body_gz = head[:2] == b"\x1f\x8b"
            with open(tmp, "wb") as f:
                if body_gz:
                    gz = gzip.GzipFile(fileobj=_io.BytesIO(head))
                    chunk = gz.read(256 * 1024)
                    while chunk:
                        f.write(chunk)
                        got += len(chunk)
                        if progress:
                            progress(got, total)
                        chunk = gz.read(256 * 1024)
                    gz2 = gzip.GzipFile(fileobj=r)
                    while True:
                        chunk = gz2.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if progress:
                            progress(got, total)
                else:
                    f.write(head)
                    got += len(head)
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if progress:
                            progress(got, total)
        if got == 0:
            return {"ok": False, "path": "", "bytes": 0,
                    "error": "下载下来是空文件（直链可能已过期）"}
        os.replace(tmp, dst)
    except Exception as e:                          # noqa: BLE001
        for p in (tmp, dst):
            try:
                if p == dst and os.path.isfile(dst) and os.path.getsize(dst) > 0:
                    continue
                os.remove(p)
            except OSError:
                pass
        return {"ok": False, "path": "", "bytes": got,
                "error": f"下载失败：{e.__class__.__name__} {e}"}

    return {"ok": True, "path": dst, "bytes": got, "error": ""}
