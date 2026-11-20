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

"""统一的 HTTP 出口：一套证书、一个复用 Session。

★ 为什么不能直接用 `requests.get` 的默认行为：

  Windows 上 requests 只信 `certifi` 自带的那份 CA 列表。而国内常见的加速/代理
  工具（Steam++ / Watt Toolkit、各种 GitHub 加速器）会在本机做 MITM，把自己的
  根证书装进 **Windows 证书库**——浏览器信、Go 程序也信，但 certifi 不信。
  于是 `api.github.com` / `api.steampowered.com` 这类域名会直接抛
  `SSLCertVerificationError`（实测 0.2 秒就失败），明明网络是通的却用不了。

  所以这里自建 SSLContext：先用 `ssl.create_default_context()` 加载**系统证书库**，
  再 `load_verify_locations(certifi.where())` **追加** certifi 的 CA —— 两边都信。
  同时复用一个 Session，省掉每次请求重新握手（第二次起明显更快）。

本项目所有出网的模块（更新检查、工坊详情、Steam 接口）都应该走这里，
这样「证书怎么配」只有一处，不会出现某个模块能连、另一个连不上的怪现象。
"""

from __future__ import annotations

import threading

import requests

_SSL_CONTEXT_CACHE: list = []
_SSL_LOCK = threading.Lock()
_SESSION_CACHE: list = []
_SESSION_LOCK = threading.Lock()


def ssl_context():
    """返回同时信任「系统证书库」与「certifi」的 SSLContext（进程内缓存）。"""
    import ssl

    if _SSL_CONTEXT_CACHE:
        return _SSL_CONTEXT_CACHE[0]
    with _SSL_LOCK:
        if _SSL_CONTEXT_CACHE:
            return _SSL_CONTEXT_CACHE[0]
        ctx = ssl.create_default_context()
        try:
            import certifi

            # load_verify_locations 是「追加」，不会冲掉上面已加载的系统证书
            ctx.load_verify_locations(certifi.where())
        except Exception:  # noqa: BLE001 —— 没有 certifi 就只用系统库
            pass
        _SSL_CONTEXT_CACHE.append(ctx)
        return ctx


class SystemTrustAdapter(requests.adapters.HTTPAdapter):
    """把 requests 的连接池换成用 `ssl_context()` 校验的版本。"""

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = ssl_context()
        return super().init_poolmanager(*args, **kwargs)


def session() -> requests.Session:
    """全局复用的 Session（自动带上面那套证书）。"""
    if _SESSION_CACHE:
        return _SESSION_CACHE[0]
    with _SESSION_LOCK:
        if not _SESSION_CACHE:
            s = requests.Session()
            adapter = SystemTrustAdapter()
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            _SESSION_CACHE.append(s)
        return _SESSION_CACHE[0]


def get(url: str, **kwargs) -> requests.Response:
    """GET 的统一出口。老版本 urllib3 不认 `ssl_context` 时退回默认行为。"""
    try:
        return session().get(url, **kwargs)
    except TypeError:
        return requests.get(url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    """POST 的统一出口（Steam 的工坊接口都是 POST）。"""
    try:
        return session().post(url, **kwargs)
    except TypeError:
        return requests.post(url, **kwargs)
