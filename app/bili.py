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

"""B 站接口封装：搜索 / 视频详情 / 封面下载.

接口说明：
  * 搜索走 web 端搜索接口 ``/x/web-interface/search/type``，需要带 buvid3/b_nut 等 cookie，
    所以先访问一次首页「暖场」，再带 Referer: https://search.bilibili.com/ 调接口。
  * 详情走 ``/x/web-interface/view``，稳定且有完整简介。
"""
from __future__ import annotations

import hashlib
import os
import re
import time
import urllib.parse
from typing import Callable

import requests

from .util import CACHE_DIR, COVER_DIR, UA, clean_text, norm_url

SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
VIEW_API = "https://api.bilibili.com/x/web-interface/view"
# 评论区（置顶评论要单独从 data.top.upper / data.top.admin 里取）
REPLY_MAIN_API = "https://api.bilibili.com/x/v2/reply/main"
NAV_API = "https://api.bilibili.com/x/web-interface/nav"
# buvid3 / buvid4 的发放接口（匿名可用，风控认这个 cookie）
SPI_API = "https://api.bilibili.com/x/frontend/finger/spi"
SPACE_ARC_API = "https://api.bilibili.com/x/space/wbi/arc/search"
DYNAMIC_FEED_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"

# WBI 签名的固定乱序表（B 站前端写死的，64 位）
WBI_MIXIN_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)

HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.bilibili.com/",
}


class BiliError(Exception):
    def __init__(self, message: str, kind: str = "network"):
        super().__init__(message)
        self.kind = kind  # network | limit | api | parse


class BiliClient:
    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout
        self._session: requests.Session | None = None
        self._warm_time = 0.0
        self._wbi_key: tuple[str, str] | None = None
        self._wbi_time = 0.0
        # 登录态：{SESSDATA, bili_jct, DedeUserID}，空字典 = 没登录
        self._auth: dict[str, str] = {}

    # ------------------------------------------------------------------ 基础
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(HEADERS)
            self._seed_cookies(self._session)
            self._warm_time = time.time()
        if time.time() - self._warm_time > 1800:  # 半小时补一次 cookie
            self._seed_cookies(self._session)
            self._warm_time = time.time()
        return self._session

    def _seed_cookies(self, s: requests.Session) -> None:
        """给 session 装上 B 站风控要的 buvid3 / buvid4 / b_nut。

        ★ 这是「别人电脑上第一次启动必 412」的根因。
          原来的暖场只是 GET 一下 https://www.bilibili.com/ ——
          **实测那个请求不返回任何 Set-Cookie**（现在首页把 buvid 放在 JS 里种，
          requests 不会执行 JS）。于是搜索接口是「裸请求」，没有 buvid3，
          B 站对匿名裸请求非常容易回 412。

          改成正调它的发放接口 /x/frontend/finger/spi：
          返回 data.b_3 / data.b_4 就是 buvid3 / buvid4，免费、无需登录、
          不消耗搜索配额。实测带上之后搜索稳定返回 42 条。

          另外「开发机能用」的错觉大概是这么来的：反复调试时 B 站那边
          对同一出口 IP 发过其他 cookie，或者浏览器同源共享 —— 换台干净电脑就没有了。
        """
        try:
            r = s.get(SPI_API, timeout=self.timeout)
            data = (r.json() or {}).get("data") or {}
            b3 = str(data.get("b_3") or "")
            b4 = str(data.get("b_4") or "")
            if b3:
                s.cookies.set("buvid3", b3, domain=".bilibili.com")
            if b4:
                s.cookies.set("buvid4", b4, domain=".bilibili.com")
            # b_nut 是 buvid 的签发时间戳，很多接口要求它与 buvid3 同时存在
            s.cookies.set("b_nut", str(int(time.time())), domain=".bilibili.com")
        except (requests.RequestException, ValueError, KeyError, TypeError):
            # 拿不到就继续用空 cookie：可能仍能成功，只是更容易被限流
            pass

    def _reset(self) -> None:
        try:
            if self._session is not None:
                self._session.close()
        finally:
            self._session = None
            self._warm_time = 0.0

    # ================================================================ 登录态
    #
    # 登录用的是**扫码登录**（B 站网页版那套）：
    #   1. GET /x/passport-login/web/qrcode/generate  → 拿到 qrcode_key + 二维码内容
    #   2. 把二维码内容画成二维码给用户扫（手机 B 站 App）
    #   3. 轮询 /x/passport-login/web/qrcode/poll?qrcode_key=xxx
    #        code 86101 = 未扫码，86090 = 已扫码待确认，0 = 成功，86038 = 已过期
    #   4. 成功后 Set-Cookie 里有 SESSDATA / bili_jct / DedeUserID
    #
    # ★ 只把这三个 cookie 存下来（够用于点赞投币收藏关注），
    #   不存整份 cookie jar（里面一堆无意义的追踪 cookie）。
    #   bili_jct 就是 csrf token，所有写操作都要带它。
    #
    LOGIN_QR_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
    LOGIN_POLL_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
    # 登录后才用得上的写操作
    LIKE_API = "https://api.bilibili.com/x/web-interface/archive/like"
    COIN_API = "https://api.bilibili.com/x/web-interface/coin/add"
    FAV_FOLDERS_API = "https://api.bilibili.com/x/v3/fav/folder/created/list-all"
    FAV_ADD_API = "https://api.bilibili.com/x/v3/fav/resource/deal"
    FOLLOW_API = "https://api.bilibili.com/x/relation/modify"
    # nav 接口用来查「现在到底登录没 / 登录的是谁」
    NAV_API_LOGIN = "https://api.bilibili.com/x/web-interface/nav"

    def set_credentials(self, sessdata: str, bili_jct: str, dede_userid: str) -> None:
        """把登录态装进当前 session（启动时从配置恢复也走这里）。"""
        self._auth = {
            "SESSDATA": str(sessdata or ""),
            "bili_jct": str(bili_jct or ""),
            "DedeUserID": str(dede_userid or ""),
        }
        s = self.session()
        for k, v in self._auth.items():
            if v:
                s.cookies.set(k, v, domain=".bilibili.com")

    def credentials(self) -> dict:
        """当前保存的登录态（给上层存盘用）。"""
        return dict(self._auth)

    def clear_credentials(self) -> None:
        self._auth = {}
        # 只清登录相关 cookie，buvid 那些留着（清了反而更容易被风控）
        try:
            s = self.session()
            for k in ("SESSDATA", "bili_jct", "DedeUserID"):
                s.cookies.set(k, "", domain=".bilibili.com")
        except Exception:                    # noqa: BLE001
            pass

    def logged_in(self) -> bool:
        return bool(self._auth.get("SESSDATA") and self._auth.get("bili_jct"))

    def nav_user(self) -> dict:
        """查当前登录用户；没登录 / 失效返回空字典。

        `/x/web-interface/nav` 是 B 站自己前端用来判断登录状态的接口：
        code 0 + data.isLogin=true 才算登录，且返回 uname / face / mid。
        这是**验证 cookie 还有效**的权威方式（不用瞎试写接口）。

        ★ 这里必须 `except Exception` 而不只是 `BiliError`。
          之前写成了模块级的 `NAV_API_LOGIN`（实际是类属性），
          触发 NameError —— 它不是 BiliError，于是整个 nav_user 直接崩，
          上层拿到的是异常而不是空字典，结果是「登录成功但 UID 一直是 0、
          头像空白」（用户报的就是这个）。
          nav 查询失败不该让登录流程整个崩掉，兜住所有异常更安全。
        """
        if not self.logged_in():
            return {}
        try:
            data = self._get_json(self.NAV_API_LOGIN, {}, "https://www.bilibili.com/")
        except Exception:                    # noqa: BLE001 - 见上面的说明
            return {}
        if not data.get("isLogin"):
            return {}
        return {
            "mid": int(data.get("mid") or 0),
            "uname": str(data.get("uname") or ""),
            "face": norm_url(data.get("face") or ""),
            "level": int((data.get("level_info") or {}).get("current_level") or 0),
            "vip": bool((data.get("vipStatus") or 0) == 1),
        }

    # ---------------------------------------------------------------- 扫码登录
    def login_qrcode(self) -> dict:
        """申请一个登录二维码，返回 ``{url, key}``。

        `url` 是二维码里的字符串（QML 侧自己画成二维码），`key` 用来轮询。
        """
        try:
            r = self.session().get(self.LOGIN_QR_API, timeout=self.timeout,
                                   headers={"Referer": "https://www.bilibili.com/"})
            js = r.json() or {}
        except (requests.RequestException, ValueError) as e:
            raise BiliError(f"获取二维码失败：{e.__class__.__name__}", "network") from e
        if js.get("code") != 0:
            raise BiliError(f"获取二维码失败：{js.get('message') or js.get('code')}", "api")
        data = js.get("data") or {}
        url = str(data.get("url") or "")
        key = str(data.get("qrcode_key") or "")
        if not url or not key:
            raise BiliError("二维码返回内容不完整", "api")
        return {"url": url, "key": key}

    def login_poll(self, key: str) -> dict:
        """轮询扫码结果。返回 ``{state, message, credentials}``。

        state: waiting（未扫）/ scanned（已扫待确认）/ ok（成功）/ expired（过期）
        """
        if not key:
            return {"state": "expired", "message": "二维码已失效", "credentials": {}}
        try:
            r = self.session().get(self.LOGIN_POLL_API, params={"qrcode_key": key},
                                   timeout=self.timeout,
                                   headers={"Referer": "https://www.bilibili.com/"})
            js = r.json() or {}
        except (requests.RequestException, ValueError):
            return {"state": "waiting", "message": "网络抖动，继续等待", "credentials": {}}

        data = js.get("data") or {}
        code = data.get("code")
        if code == 86101:
            return {"state": "waiting", "message": "请用 B 站 App 扫码", "credentials": {}}
        if code == 86090:
            return {"state": "scanned", "message": "已扫码，请在手机上确认", "credentials": {}}
        if code == 86038:
            return {"state": "expired", "message": "二维码已过期，请刷新", "credentials": {}}
        if code != 0:
            return {"state": "expired",
                    "message": str(data.get("message") or "登录失败"), "credentials": {}}

        # 成功：从 Set-Cookie 里抠出三件套
        creds = {}
        for c in r.cookies:
            if c.name in ("SESSDATA", "bili_jct", "DedeUserID"):
                creds[c.name] = c.value
        # 有些情况下 cookie 落在 session 里而不是 r.cookies
        if len(creds) < 3:
            for c in self.session().cookies:
                if c.name in ("SESSDATA", "bili_jct", "DedeUserID"):
                    creds.setdefault(c.name, c.value)
        if not (creds.get("SESSDATA") and creds.get("bili_jct")):
            return {"state": "expired",
                    "message": "登录成功但没拿到凭据，请重试", "credentials": {}}
        return {"state": "ok", "message": "登录成功", "credentials": creds}

    # ---------------------------------------------------------------- 三连
    def _csrf(self) -> str:
        return str(self._auth.get("bili_jct") or "")

    def _post_auth(self, url: str, payload: dict) -> dict:
        """带登录态 POST。返回 ``{ok, code, message}``。

        `-101` = 账号未登录（凭据失效），上层据此提示重新登录。
        """
        if not self.logged_in():
            return {"ok": False, "code": -101, "message": "还没登录"}
        body = dict(payload)
        body["csrf"] = self._csrf()
        try:
            r = self.session().post(
                url, data=body, timeout=self.timeout,
                headers={"Referer": "https://www.bilibili.com/",
                         "Origin": "https://www.bilibili.com"},
            )
            js = r.json() or {}
        except (requests.RequestException, ValueError) as e:
            return {"ok": False, "code": -1, "message": f"网络错误：{e.__class__.__name__}"}
        code = int(js.get("code") or 0)
        return {
            "ok": code == 0,
            "code": code,
            "message": str(js.get("message") or ""),
        }

    def like_video(self, aid: int, like: bool = True) -> dict:
        """点赞 / 取消点赞。"""
        return self._post_auth(
            self.LIKE_API,
            {"aid": int(aid or 0), "like": 1 if like else 2},
        )

    def coin_video(self, aid: int, count: int = 1) -> dict:
        """投币（count 1 或 2）。"""
        n = 2 if int(count or 1) >= 2 else 1
        return self._post_auth(
            self.COIN_API,
            {"aid": int(aid or 0), "multiply": n, "select_like": 0},
        )

    def favorites(self) -> list:
        """当前账号的收藏夹列表（投币收藏要用它的 id）。"""
        if not self.logged_in():
            return []
        mid = str(self._auth.get("DedeUserID") or "")
        if not mid:
            return []
        try:
            data = self._get_json(
                self.FAV_FOLDERS_API,
                {"up_mid": mid},
                "https://www.bilibili.com/",
            )
        except BiliError:
            return []
        out = []
        for it in (data.get("list") or []):
            try:
                out.append({
                    "id": int(it.get("id") or 0),
                    "title": str(it.get("title") or ""),
                    "count": int(it.get("media_count") or 0),
                })
            except (TypeError, ValueError):
                continue
        return out

    def favorite_video(self, aid: int, folder_id: int) -> dict:
        """收藏到指定收藏夹（add_media_ids）。"""
        return self._post_auth(
            self.FAV_ADD_API,
            {
                "rid": int(aid or 0),
                "type": 2,
                "add_media_ids": str(int(folder_id or 0)),
                "del_media_ids": "",
            },
        )

    def follow_user(self, mid: int, follow: bool = True) -> dict:
        """关注 / 取关。"""
        return self._post_auth(
            self.FOLLOW_API,
            {
                "fid": int(mid or 0),
                "act": 1 if follow else 2,
                "re_src": 11,
            },
        )

    # ------------------------------------------------------------- WBI 签名
    def _wbi_mixin_key(self) -> str:
        """按乱序表把 img_key + sub_key 打乱，取前 32 位。"""
        if self._wbi_key is None:
            return ""
        img_key, sub_key = self._wbi_key
        raw = img_key + sub_key
        if len(raw) < 64:
            return ""
        return "".join(raw[i] for i in WBI_MIXIN_TAB)[:32]

    def _wbi_keys(self) -> str:
        """取并缓存 mixin key（B 站每天换一次，这里 6 小时刷一次）。"""
        if self._wbi_key is not None and time.time() - self._wbi_time < 6 * 3600:
            return self._wbi_mixin_key()
        try:
            s = self.session()
            r = s.get(
                NAV_API,
                headers={"Referer": "https://www.bilibili.com/"},
                timeout=self.timeout,
            )
            data = (r.json() or {}).get("data") or {}
        except (requests.RequestException, ValueError):
            return ""
        wbi = data.get("wbi_img") or {}
        img = (wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
        sub = (wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
        if not img or not sub:
            return ""
        self._wbi_key = (img, sub)
        self._wbi_time = time.time()
        return self._wbi_mixin_key()

    def _wbi_sign(self, params: dict) -> dict:
        """给参数加上 wts 和 w_rid。取不到 key 就返回空字典，调用方自行降级。"""
        mixin = self._wbi_keys()
        if not mixin:
            return {}
        signed = {k: v for k, v in params.items() if v is not None}
        signed["wts"] = int(time.time())
        # 签名只认「按 key 排序 + 去掉 !'()*」之后的串
        query = urllib.parse.urlencode(sorted(signed.items()))
        query = re.sub(r"[!'()*]", "", query)
        signed["w_rid"] = hashlib.md5(
            (query + mixin).encode("utf-8")
        ).hexdigest()
        return signed

    def _get_json(self, url: str, params: dict, referer: str) -> dict:
        """GET 并解析。遇到 412 / 风控码**自动换 cookie 重试一次**。

        ★ 「第一次启动必失败」还有一半原因在这里：原来一碰到 412 就直接
          `_reset()` + 抛错，用户看到的是一条错误提示，必须手动刷新才行。
          但其实 412 大多是「缺 buvid cookie / 这个 cookie 被标记了」——
          丢掉 session、重新领一份 buvid 再试，通常第一次就能过。
          所以现在做成：412 → 重建 session（会重新领 buvid）→ 稍等 → 重试一次；
          还不行才报错。用户几乎感觉不到，也不会再看到「第一次必失败」。
        """
        last: BiliError | None = None
        for attempt in (0, 1):
            s = self.session()
            if attempt:
                self._reset()      # 丢掉旧 session（含被标记的 cookie）
                s = self.session()  # 新建的会重新领 buvid
                time.sleep(0.8 + attempt)
            try:
                r = s.get(
                    url,
                    params=params,
                    headers={"Referer": referer},
                    timeout=self.timeout,
                )
            except requests.Timeout as e:
                raise BiliError("请求超时，请检查网络", "network") from e
            except requests.RequestException as e:
                raise BiliError(f"网络错误：{e.__class__.__name__}", "network") from e

            if r.status_code == 412:
                last = BiliError("被 B 站限流了（412），稍等几分钟再刷新", "limit")
                continue           # 换 cookie 重试
            if r.status_code != 200:
                raise BiliError(f"接口返回 HTTP {r.status_code}", "network")
            try:
                data = r.json()
            except ValueError as e:
                raise BiliError("接口返回的不是 JSON，可能被风控", "parse") from e

            code = data.get("code")
            if code == 0:
                return data.get("data") or {}
            if code in (-412, -352, -509):
                last = BiliError(f"被 B 站风控拦截（code {code}），稍等再试", "limit")
                continue           # 同样换 cookie 重试
            raise BiliError(f"接口错误：{data.get('message') or code}", "api")

        # 两次都不行，把最后那个限流错误抛出去
        self._reset()
        raise last or BiliError("请求失败", "network")

    # ------------------------------------------------------------------ 置顶评论
    def top_comment(self, aid: int, bvid: str = "") -> dict:
        """视频的置顶评论（UP 主置顶 / 管理员置顶），没有就返回空字典。

        B 站把置顶评论单独放在 `data.top.upper`（UP 置顶）和 `data.top.admin`
        （管理员置顶）里，不在普通 replies 列表头部，所以必须专门取这个字段。

        接口用 `/x/v2/reply/main`（老的 `/x/v2/reply` 也带 top，但 /main 更稳），
        并且要 WBI 签名，否则 -352。
        """
        aid = int(aid or 0)
        if aid <= 0:
            return {}
        params = {"type": 1, "oid": aid, "mode": 3, "next": 0, "ps": 20}
        try:
            signed = self._wbi_sign(dict(params))
        except BiliError:
            signed = params
        try:
            data = self._get_json(
                REPLY_MAIN_API,
                signed,
                f"https://www.bilibili.com/video/{bvid}" if bvid else "https://www.bilibili.com/",
            )
        except BiliError as e:
            log(f"top comment failed {bvid}: {e}")
            return {}

        top = data.get("top") or {}
        for key in ("upper", "admin"):
            item = top.get(key) if isinstance(top, dict) else None
            if isinstance(item, dict) and item.get("content"):
                out = self._norm_reply(item, pinned=(key == "upper"))
                if out.get("text"):
                    return out

        # 有些视频不回 top，但普通回复里带 reply_control.is_top —— 兜底扫一遍
        for item in (data.get("replies") or [])[:5]:
            rc = item.get("reply_control") or {}
            if rc.get("is_top") or rc.get("is_up_top"):
                out = self._norm_reply(item, pinned=True)
                if out.get("text"):
                    return out
        return {}

    @staticmethod
    def _norm_reply(item: dict, pinned: bool = False) -> dict:
        """把评论对象压成我们界面要的几个字段。"""
        member = item.get("member") or {}
        content = item.get("content") or {}
        text = str(content.get("message") or "").strip()
        # 简介里那种 [doge] 表情在纯文本里没意义，但保留着也不影响阅读，先原样留着
        return {
            "text": text,
            "user": str(member.get("uname") or ""),
            "mid": int(member.get("mid") or 0),
            "avatar": norm_url(member.get("avatar")),
            "like": int(item.get("like") or 0),
            "ctime": int(item.get("ctime") or 0),
            "rpid": str(item.get("rpid_str") or item.get("rpid") or ""),
            "pinned": bool(pinned),
        }

    # ------------------------------------------------------------------ 搜索
    def search(
        self,
        keyword: str,
        order: str = "pubdate",
        page: int = 1,
        max_pages: int = 1,
    ) -> list[dict]:
        """按发布时间搜索视频，返回按发布时间倒序的列表。

        page 为起始页，max_pages 为从起始页往后取几页。
        """
        out: list[dict] = []
        seen: set[str] = set()
        start = max(1, int(page))
        for p in range(start, start + max(1, max_pages)):
            data = self._get_json(
                SEARCH_API,
                {
                    "search_type": "video",
                    "keyword": keyword,
                    "order": order,
                    "page": p,
                    "page_size": 42,
                    "platform": "pc",
                },
                "https://search.bilibili.com/",
            )
            results = data.get("result") or []
            if isinstance(results, dict):  # 兼容极端返回
                results = [results]
            for item in results:
                bvid = item.get("bvid") or ""
                if not bvid or bvid in seen:
                    continue
                seen.add(bvid)
                out.append(self._norm_search_item(item))
            if len(results) < 20:
                break
            if p < max_pages:
                time.sleep(0.6)  # 别把接口打太勤
        out.sort(key=lambda v: v.get("pubdate") or 0, reverse=True)
        return out

    @staticmethod
    def _norm_search_item(item: dict) -> dict:
        return {
            "bvid": item.get("bvid") or "",
            "aid": int(item.get("aid") or 0),
            "title": clean_text(item.get("title")),
            "desc": clean_text(item.get("description")),
            "author": clean_text(item.get("author")),
            "mid": int(item.get("mid") or 0),
            "cover": norm_url(item.get("pic")),
            "pubdate": int(item.get("pubdate") or 0),
            "duration": item.get("duration") or "",
            "play": int(item.get("play") or 0),
            "danmaku": int(item.get("video_review") or 0),
            "favorites": int(item.get("favorites") or 0),
            "tag": clean_text(item.get("tag")),
            "url": f"https://www.bilibili.com/video/{item.get('bvid') or ''}",
            "detail_loaded": False,
        }

    # ------------------------------------------------------------------ UP 主
    def user_card(self, mid: int | str) -> dict:
        """取 UP 主资料：昵称、头像、签名、粉丝数。"""
        mid = int(mid or 0)
        if mid <= 0:
            raise BiliError("UP 主 ID 无效", "api")

        data = self._get_json(
            "https://api.bilibili.com/x/web-interface/card",
            {"mid": mid},
            f"https://space.bilibili.com/{mid}",
        )
        card = data.get("card") or {}
        return {
            "mid": mid,
            "name": card.get("name") or "",
            "face": norm_url(card.get("face")),
            "sign": (card.get("sign") or "").strip(),
            "fans": int(data.get("follower") or card.get("fans") or 0),
            "level": int((card.get("level_info") or {}).get("current_level") or 0),
            "spaceUrl": f"https://space.bilibili.com/{mid}",
            "uploadUrl": f"https://space.bilibili.com/{mid}/upload/video",
        }

    def _space_videos(self, mid: int, limit: int) -> list[dict]:
        """走带 WBI 签名的 space 接口取 UP 主投稿（data.list.vlist）。"""
        params = {
            "mid": mid,
            "ps": max(6, min(30, limit)),
            "pn": 1,
            "order": "pubdate",
            "platform": "web",
            "web_location": 1550101,
        }
        signed = self._wbi_sign(params)
        if not signed:
            return []
        data = self._get_json(
            SPACE_ARC_API, signed, f"https://space.bilibili.com/{mid}/video"
        )
        vlist = ((data.get("list") or {}).get("vlist")) or []
        out: list[dict] = []
        for v in vlist:
            bvid = v.get("bvid") or ""
            if not bvid:
                continue
            out.append(
                {
                    "bvid": bvid,
                    "title": clean_text(v.get("title") or ""),
                    "cover": norm_url(v.get("pic")),
                    "pubdate": int(v.get("created") or 0),
                    "duration": human_duration(v.get("length")),
                    "play": int(v.get("play") or 0),
                    "url": f"https://www.bilibili.com/video/{bvid}",
                }
            )
            if len(out) >= limit:
                break
        return out

    def user_videos(self, mid: int | str, name: str = "", limit: int = 6) -> list[dict]:
        """取 UP 主近期视频。

        B 站 space 系列接口现在都过风控（``-352 风控校验失败`` / ``-799 请求过于频繁``），
        单独一个来源随时可能空手而归，所以这里**多路合并**：
          1. ``x/space/wbi/arc/search``（带 WBI 签名，最准）
          2. ``x/polymer/web-dynamic/v1/feed/space``（动态流，投稿会自动生成动态）
          3. 搜索接口按 UP 主昵称搜再按 mid 过滤（兜底，昵称不在标题里时会漏）
        任何一路失败都静默跳过，最后按发布时间倒序去重取前 limit 条。
        """
        mid = int(mid or 0)
        if mid <= 0:
            return []

        seen: set[str] = set()
        merged: list[dict] = []
        sources = [self._space_videos, self._dynamic_videos]
        if name:
            sources.append(lambda m, n: self._search_videos(m, name, n))
        for fn in sources:
            try:
                got = fn(mid, limit) or []
            except (BiliError, requests.RequestException, ValueError, KeyError):
                continue
            for v in got:
                bvid = v.get("bvid") or ""
                if not bvid or bvid in seen:
                    continue
                seen.add(bvid)
                merged.append(v)

        merged.sort(key=lambda v: int(v.get("pubdate") or 0), reverse=True)
        return merged[:limit]

    def _search_videos(self, mid: int, name: str, limit: int) -> list[dict]:
        """兜底：按 UP 主昵称搜索，再按 mid 精确过滤。"""
        out: list[dict] = []
        seen: set[str] = set()
        # 多翻一页增加命中率（按作者名搜索时无关结果可能较多）
        for page in (1, 2):
            try:
                items = self.search(name, max_pages=1, page=page)
            except BiliError:
                break
            for v in items:
                if int(v.get("mid") or 0) != mid:
                    continue
                bvid = v.get("bvid") or ""
                if not bvid or bvid in seen:
                    continue
                seen.add(bvid)
                out.append(
                    {
                        "bvid": bvid,
                        "title": v.get("title") or "",
                        "cover": v.get("cover") or "",
                        "pubdate": int(v.get("pubdate") or 0),
                        "duration": human_duration(v.get("duration")),
                        "play": int(v.get("play") or 0),
                        "url": f"https://www.bilibili.com/video/{bvid}",
                    }
                )
                if len(out) >= limit:
                    return out
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _archive_of(item: dict) -> tuple[dict, int]:
        """从一条动态里挖出视频卡片（转发动态要看 orig）。"""
        pub_ts = 0
        for node in (item, item.get("orig") or {}):
            author = ((node.get("modules") or {}).get("module_author")) or {}
            major = (((node.get("modules") or {}).get("module_dynamic")) or {}).get(
                "major"
            ) or {}
            arch = major.get("archive") or {}
            if arch.get("bvid"):
                return arch, int(author.get("pub_ts") or 0)
            if not pub_ts:
                pub_ts = int(author.get("pub_ts") or 0)
        return {}, pub_ts

    def _dynamic_videos(self, mid: int, limit: int) -> list[dict]:
        """从 UP 主的动态流里捞视频投稿。"""
        s = self.session()
        out: list[dict] = []
        try:
            # 先看一眼空间页，把风控要的 cookie 带全
            s.get(
                f"https://space.bilibili.com/{mid}/video",
                headers={"Referer": "https://www.bilibili.com/"},
                timeout=self.timeout,
            )
            r = s.get(
                DYNAMIC_FEED_API,
                params={
                    "host_mid": mid,
                    "timezone_offset": -480,
                    "platform": "web",
                    "features": "itemOpusStyle",
                },
                headers={"Referer": f"https://space.bilibili.com/{mid}/dynamic"},
                timeout=self.timeout,
            )
            js = r.json() or {}
        except (requests.RequestException, ValueError):
            return []
        if js.get("code") != 0:
            return []
        for item in ((js.get("data") or {}).get("items") or []):
            arch, pub_ts = self._archive_of(item)
            bvid = arch.get("bvid") or ""
            if not bvid:
                continue
            stat = arch.get("stat") or {}
            out.append(
                {
                    "bvid": bvid,
                    "title": (arch.get("title") or "").strip(),
                    "cover": norm_url(arch.get("cover")),
                    "pubdate": pub_ts,
                    "duration": human_duration(arch.get("duration_text")),
                    "play": int(stat.get("play") or 0),
                    "url": f"https://www.bilibili.com/video/{bvid}",
                }
            )
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------ 详情
    def video_detail(self, bvid: str) -> dict:
        data = self._get_json(
            VIEW_API, {"bvid": bvid}, "https://www.bilibili.com/video/" + bvid
        )
        stat = data.get("stat") or {}
        owner = data.get("owner") or {}
        pages = data.get("pages") or []
        desc = (data.get("desc") or "").strip()
        if not desc:
            desc = (data.get("dynamic") or "").strip()
        return {
            "bvid": data.get("bvid") or bvid,
            "aid": int(data.get("aid") or 0),
            "title": data.get("title") or "",
            "desc": desc,
            "author": owner.get("name") or "",
            "mid": int(owner.get("mid") or 0),
            "avatar": norm_url(owner.get("face")),
            "cover": norm_url(data.get("pic")),
            "pubdate": int(data.get("pubdate") or 0),
            "ctime": int(data.get("ctime") or 0),
            "duration": data.get("duration") or 0,
            "tname": data.get("tname") or "",
            "pages": len(pages),
            "views": int(stat.get("view") or 0),
            "danmaku": int(stat.get("danmaku") or 0),
            "reply": int(stat.get("reply") or 0),
            "favorite": int(stat.get("favorite") or 0),
            "coin": int(stat.get("coin") or 0),
            "like": int(stat.get("like") or 0),
            "share": int(stat.get("share") or 0),
            "url": f"https://www.bilibili.com/video/{bvid}",
        }

    # ------------------------------------------------------------------ 播放流
    def video_stream(self, bvid: str, qn: int = 64) -> tuple[str, int]:
        """取合并流（MP4，带音轨）地址，返回 (url, 字节数)。

        用 fnval=1 拿 durl 的 mp4，而不是 DASH —— 因为 DASH 音视频分离，
        QtMultimedia 直接播只有画面没声音。
        """
        # 1) 拿 cid（分P列表的第一P）
        page = self._get_json(
            "https://api.bilibili.com/x/player/pagelist",
            {"bvid": bvid},
            f"https://www.bilibili.com/video/{bvid}",
        )
        cid = 0
        if isinstance(page, list) and page:
            cid = int(page[0].get("cid") or 0)
        elif isinstance(page, dict):
            cid = int(page.get("cid") or 0)
        if not cid:
            raise BiliError("拿不到视频 cid，可能视频已失效", "api")

        # 2) 取播放地址
        data = self._get_json(
            "https://api.bilibili.com/x/player/playurl",
            {"bvid": bvid, "cid": cid, "qn": qn, "fnval": 1, "fourk": 0},
            f"https://www.bilibili.com/video/{bvid}",
        )
        durl = data.get("durl") or []
        if durl:
            first = durl[0]
            url = first.get("url") or ""
            if url:
                return norm_url(url), int(first.get("size") or 0)

        raise BiliError("这个视频没有可用的 MP4 流（可能是直播 / 番剧 / 付费内容）", "api")

    def download_stream(
        self,
        url: str,
        bvid: str,
        path: str,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> bool:
        """带 Referer 下载视频流（CDN 会校验 Referer，缺了会 403/503）。"""
        headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Referer": f"https://www.bilibili.com/video/{bvid}",
            "Origin": "https://www.bilibili.com",
            "Accept": "*/*",
            "Range": "bytes=0-",
        }

        # 503 多半是 upos 节点临时抽风，换一个 session / 重试一次通常就好
        last_status = 0
        for attempt in range(3):
            try:
                r = self.session().get(url, headers=headers, timeout=(15, 120), stream=True)
            except requests.RequestException as e:
                if attempt == 2:
                    raise BiliError(
                        f"连接视频服务器失败：{e.__class__.__name__}", "network"
                    ) from e
                self._reset()
                time.sleep(1.2)
                continue

            if r.status_code in (200, 206):
                return self._write_stream(r, path, on_progress)

            last_status = r.status_code
            r.close()
            if r.status_code in (403, 503):
                self._reset()  # cookie 可能失效，重连一次
                time.sleep(1.0 + attempt)
                continue
            break

        raise BiliError(f"视频服务器返回 {last_status}，稍后再试", "network")

    @staticmethod
    def _write_stream(
        r: requests.Response,
        path: str,
        on_progress: Callable[[int, int], None] | None,
    ) -> bool:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                got += len(chunk)
                if on_progress is not None and total:
                    on_progress(got, total)
        r.close()
        return got > 64 * 1024

    # ------------------------------------------------------------------ 封面
    def download_cover(self, url: str, bvid: str) -> str:
        """下载封面到本地缓存，返回本地路径（失败返回空串）。"""
        if not url:
            return ""
        name = hashlib.md5(url.encode("utf-8")).hexdigest()[:16] + ".jpg"
        path = os.path.join(COVER_DIR, name)
        if os.path.exists(path) and os.path.getsize(path) > 1024:
            return path
        try:
            # 图片走 CDN，不需要 cookie，单独发请求避免多线程共用 Session
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
                timeout=self.timeout,
            )
            if r.status_code == 200 and len(r.content) > 1024:
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(r.content)
                os.replace(tmp, path)
                return path
        except (requests.RequestException, OSError):
            pass
        return ""


def human_duration(value) -> str:
    """duration 可能是 '3:27' 字符串，也可能是秒数。"""
    if isinstance(value, str) and ":" in value:
        return value
    try:
        sec = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


__all__ = ["BiliClient", "BiliError", "human_duration", "CACHE_DIR"]
