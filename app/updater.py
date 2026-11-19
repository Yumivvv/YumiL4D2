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

"""检查更新：走 GitHub Releases 拿最新版本号，支持镜像兜底与更新包安装。

参考 `lytvpk-master` 的 `internal/app/update.go`（Wails 项目，同样是 GitHub Releases 方案）：

* 直连 `https://api.github.com/repos/{repo}/releases` 拿 release 列表，**必须带 User-Agent**，
  否则 GitHub 直接 403；额度/限流才是 429，所以不能只靠 HTTP 状态码判断成功。
* 直连失败时（国内常见）请求 `{mirror}https://github.com/{repo}/releases/latest`，
  **从最终重定向 URL 里解析 `/tag/` 末段**拿 tag。镜像常返回 403 的网页，不能靠状态码判断，
  只能靠最终 URL。
* **镜像必须并发探测**：8 个镜像串行各超时一次实测最坏要 26 秒（gh-proxy.com、ghproxy.net
  各 ~9.5 秒读超时），并发后只等最快成功的那条，通常 2~4 秒。直连 API 与镜像探测也并发发起，
  哪条先拿到可用结果就用哪条。
* 版本用「数字段逐段比较」，不依赖字符串排序，避免 `v1.0.10` 与 `v1.0.9` 的坑。
* 下载更新包后，解压（zip）或直接取 exe，写 `.new` → 当前 exe 改名 `.old` → `.new` 改名回
  当前 exe；任何一步失败都回滚，避免把正在运行的 exe 弄坏。
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

# 本项目 GitHub 仓库（releases 页：https://github.com/Yumivvv/YumiL4D2/releases）
GITHUB_REPO = "Yumivvv/YumiL4D2"
GITHUB_API = "https://api.github.com/repos/{repo}/releases?per_page=20"
GITHUB_LATEST = "https://github.com/{repo}/releases/latest"

# 直连 GitHub 不通时的镜像前缀（顺序即优先级）。只做「拿最新 tag」的兜底。
MIRRORS = (
    "https://gh-proxy.com/",
    "https://ghfast.top/",
    "https://gh.xxooo.cf/",
    "https://ghproxy.net/",
    "https://gh.acmsz.top/",
    "https://gh.felicity.ac.cn/",
    "https://ghproxy.cxkpro.top/",
    "https://hk.gh-proxy.com/",
)

# 直连 GitHub API 的超时（秒）：能拿到完整更新日志和资产，慢一点也值得等
TIMEOUT = 10
# 镜像探测的超时（秒）：镜像只用来「拿最新 tag」，而且是并发探测的，
# 压短一点，避免个别慢镜像把整体拖住
PROBE_TIMEOUT = 6
# 下载更新包的超时（秒），包体大，放宽一些
DOWNLOAD_TIMEOUT = 120

_USER_AGENT = "YumiL4D2Toolbox-updater"
# 抓版本号用「第一个 x.y.z 形式」而不是所有数字 —— 否则 `Yumi的L4D2工具箱_1.0.10`
# 里的 `L4D2` 会把数字段搅乱。
_VER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?")
_ASSET_RE = re.compile(r'href="([^"]*releases/download/[^"]+)"', re.IGNORECASE)


# ================================================================= 版本比较
def parse_version(text: str) -> tuple:
    """把任意版本串解析成三段数字元组，解析不出来返回空元组。

    只认**第一个** ``x.y[.z]`` 形式，这样 ``v1.0``、``v1.0.0``、
    ``Yumi的L4D2工具箱_1.0.10`` 都能正确解析成三段，
    且 ``1.0.10`` 会正确大于 ``1.0.9``。
    """
    m = _VER_RE.search(text or "")
    if not m:
        return ()
    nums = [int(g) for g in m.groups() if g]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def _fmt_version(nums: tuple) -> str:
    return ".".join(str(x) for x in nums)


# ================================================================= 网络
def _headers() -> dict:
    return {
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github+json",
    }


# ---- 证书：系统证书库 + certifi 二合一 -----------------------------------
# ★ 为什么不能直接用 requests 默认的 certifi：
#   Windows 上 requests 只信 certifi 自带的 CA 列表。国内常见的 GitHub 加速
#   工具（Steam++ / Watt Toolkit 等）会在本机做 MITM，把自己的根证书装进
#   **Windows 证书库**——浏览器信、Go 程序（lytvpk 那种）也信，但 certifi 不信，
#   于是 api.github.com 直接报 SSLCertVerificationError（实测 0.2 秒就失败），
#   只能退回慢吞吞的镜像。把系统库和 certifi 合并起来两边都信，直连就能用。
_SSL_CONTEXT_CACHE: list = []


def _ssl_context():
    """返回一个同时信任「系统证书库」和「certifi」的 SSLContext。"""
    import ssl

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


class _SystemTrustAdapter(requests.adapters.HTTPAdapter):
    """把 requests 的连接池换成用 `_ssl_context()` 校验的版本。"""

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = _ssl_context()
        return super().init_poolmanager(*args, **kwargs)


_SESSION_CACHE: list = []
_SESSION_LOCK = threading.Lock()


def _session() -> requests.Session:
    """全局复用一个 Session：省掉每次检查的 TLS 握手，第二次起明显更快。"""
    if _SESSION_CACHE:
        return _SESSION_CACHE[0]
    with _SESSION_LOCK:
        if not _SESSION_CACHE:
            s = requests.Session()
            adapter = _SystemTrustAdapter()
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            _SESSION_CACHE.append(s)
        return _SESSION_CACHE[0]


def _get(url: str, **kwargs) -> requests.Response:
    """本模块所有 HTTP GET 的统一出口（统一 UA/超时/证书）。

    ★ 测试里要断网，直接替换 `updater._get` 即可。
    """
    kwargs.setdefault("headers", _headers())
    kwargs.setdefault("timeout", TIMEOUT)
    try:
        return _session().get(url, **kwargs)
    except TypeError:
        # 老版本 urllib3 的 PoolManager 不认 ssl_context，退回 requests 默认行为
        return requests.get(url, **kwargs)


def fetch_releases(repo: str = GITHUB_REPO, timeout: int = TIMEOUT) -> list:
    """直连 GitHub API 拿 release 列表（原始 dict 列表）。"""
    resp = _get(GITHUB_API.format(repo=repo), timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("GitHub 返回的内容不是列表")
    return data


def _first_of(calls: list):
    """并发执行多个探测，返回**第一个**拿到非空结果的返回值。

    `calls` 是 `[(标签, 无参函数), ...]`。串行遍历时每个慢源都要各自
    超时一次（实测 8 个镜像串行最坏 26 秒），并发后最坏只等最快成功的那个。
    剩余请求不等待，直接放手返回（工作线程是守护线程，不阻塞退出）。
    """
    if not calls:
        return None
    executor = ThreadPoolExecutor(max_workers=max(1, len(calls)))
    try:
        futures = {executor.submit(fn): label for label, fn in calls}
        for future in as_completed(futures):
            try:
                value = future.result()
            except Exception:  # noqa: BLE001 —— 单个源异常不能拖垮整次探测
                continue
            if value:
                return value
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return None


def _fetch_latest_tag(url: str, timeout: int) -> str:
    """请求单个 `/releases/latest`，从最终重定向 URL 解析 tag，失败返回空串。

    镜像常返回 403/404 的网页，所以**不判断状态码**，只认最终 URL 里是否含 `/tag/`。
    """
    try:
        resp = _get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException:
        return ""
    final_url = resp.url or ""
    if "/tag/" in final_url:
        tag = final_url.rsplit("/tag/", 1)[1].strip("/").strip()
        if tag:
            return tag
    return ""


def latest_tag_via_mirror(
    repo: str = GITHUB_REPO, timeout: int = PROBE_TIMEOUT
) -> str:
    """并发探测全部镜像，第一个解析出 tag 的立即返回。

    镜像只用来「拿最新 tag」，拿不到详细日志和资产，需要时再用
    `assets_via_page` 补。
    """
    target = GITHUB_LATEST.format(repo=repo)
    calls = [
        (mirror, lambda u=f"{mirror}{target}": _fetch_latest_tag(u, timeout))
        for mirror in MIRRORS
    ]
    return _first_of(calls) or ""


def _fetch_assets(url: str, timeout: int) -> list:
    """抓单个 `expanded_assets` 页面里的资产链接，没有则返回空列表。"""
    try:
        resp = _get(url, headers=_headers(), timeout=timeout)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    found = _ASSET_RE.findall(resp.text)
    if not found:
        return []
    # HTML 里可能是相对链接，统一转成绝对链接
    return [
        u if u.startswith("http") else f"https://github.com{u}" for u in found
    ]


def assets_via_page(
    repo: str, tag: str, timeout: int = PROBE_TIMEOUT
) -> list:
    """并发兜底拿某个 release 的下载资产链接（API 不可用时才走这里）。

    用 `releases/expanded_assets/{tag}` 这个 HTML 片段接口，比翻整个 release 页轻量。
    """
    url = f"https://github.com/{repo}/releases/expanded_assets/{tag}"
    calls = [("direct", lambda u=url: _fetch_assets(u, timeout))]
    calls += [
        (mirror, lambda m=mirror, u=url: _fetch_assets(f"{m}{u}", timeout))
        for mirror in MIRRORS
    ]
    return _first_of(calls) or []


# ================================================================= 选更新包
def pick_asset_url(assets: list) -> str:
    """从 release 资产里挑下载链接：优先 `.exe`，其次 `.zip`。"""
    if not assets or not isinstance(assets, list):
        return ""
    exe = [
        a.get("browser_download_url", "")
        for a in assets
        if (a.get("name") or "").lower().endswith(".exe")
        and a.get("browser_download_url")
    ]
    if exe:
        return exe[0]
    zip_urls = [
        a.get("browser_download_url", "")
        for a in assets
        if (a.get("name") or "").lower().endswith(".zip")
        and a.get("browser_download_url")
    ]
    if zip_urls:
        return zip_urls[0]
    first = assets[0].get("browser_download_url", "")
    return first or ""


# ================================================================= 检查更新
def check_update(repo: str = GITHUB_REPO, current: str = "") -> dict:
    """返回更新信息字典。

    键：
      ``has_update`` bool  是否发现比当前版本更新的版本
      ``current``    str   当前版本
      ``latest``     str   最新版本（tag 名或规范化版本号）
      ``note``       str   更新内容（多个版本时按版本号从旧到新聚合）
      ``url``        str   更新包下载链接
      ``error``      str   出错信息，成功为空串

    ★ 直连 API 与「镜像取 tag」是**并发**发起的：串行时 API 秒败后要逐个
    等 8 个镜像各超时一次（实测最坏 26 秒），并发后整体耗时只取决于最快
    成功的那条路，通常 2~4 秒。
    """
    info: dict[str, Any] = {
        "has_update": False,
        "current": current,
        "latest": "",
        "note": "",
        "url": "",
        "error": "",
    }

    api_box: dict = {}
    mirror_box: dict = {}
    state = {"done": 0}
    lock = threading.Lock()
    stop = threading.Event()  # 第一条路成功、或两条都跑完 → 立即停止等待

    def _finish_one() -> None:
        with lock:
            state["done"] += 1
            if state["done"] >= 2:
                stop.set()

    def _probe_api() -> None:
        try:
            rows = fetch_releases(repo)
            api_box["releases"] = rows
            if rows:
                stop.set()
        except Exception as e:  # noqa: BLE001 —— 网络/解析任何异常都要兜底
            api_box["error"] = e
        finally:
            _finish_one()

    def _probe_mirror() -> None:
        try:
            tag = latest_tag_via_mirror(repo)
        except Exception:  # noqa: BLE001
            tag = ""
        mirror_box["tag"] = tag
        if tag:
            stop.set()
        _finish_one()

    for probe in (_probe_api, _probe_mirror):
        threading.Thread(target=probe, daemon=True).start()
    stop.wait(timeout=TIMEOUT)

    releases = api_box.get("releases")
    if releases:
        return _info_from_releases(releases, current, info)

    mirror_tag = mirror_box.get("tag") or ""
    if not mirror_tag:
        err = api_box.get("error")
        info["error"] = f"检查更新失败（所有源均不可用）：{err or '没有取到版本信息'}"
        return info

    # ---- 镜像只给了 tag：没有详细更新日志和资产列表，能补多少补多少 ----
    cur = parse_version(current)
    latest_v = parse_version(mirror_tag)
    info["latest"] = mirror_tag
    if not cur or latest_v > cur:
        info["has_update"] = True
        info["note"] = (
            f"网络原因无法拉取详细更新日志，已通过镜像确认最新版本为 {mirror_tag}。"
        )
        for link in assets_via_page(repo, mirror_tag):
            if link.lower().endswith((".exe", ".zip")):
                info["url"] = link
                break
    return info


def _info_from_releases(releases: list, current: str, info: dict) -> dict:
    """直连成功时：聚合所有比当前新的版本日志，挑出最新版与下载包。"""
    cur_v = parse_version(current)
    newer: list[tuple] = []
    for r in releases:
        v = parse_version(r.get("tag_name") or "")
        if v and (not cur_v or v > cur_v):
            newer.append((v, r))

    if not newer:
        info["latest"] = current or _fmt_version(cur_v)
        return info

    newest_v, newest = max(newer, key=lambda x: x[0])
    info["has_update"] = True
    info["latest"] = newest.get("tag_name") or _fmt_version(newest_v)

    parts: list[str] = []
    for v, r in sorted(newer, key=lambda x: x[0]):
        tag = r.get("tag_name") or _fmt_version(v)
        body = (r.get("body") or "").strip()
        parts.append(f"【{tag}】\n{body}" if body else f"【{tag}】")
    info["note"] = "\n\n".join(parts)
    info["url"] = pick_asset_url(newest.get("assets") or [])
    return info


# ================================================================= 下载安装
def download_and_install(url: str, timeout: int = DOWNLOAD_TIMEOUT) -> str:
    """下载并替换当前 exe，成功返回新 exe 路径。

    * zip 包：解压出里面的 `.exe`
    * 裸 exe：直接用
    * 替换时当前 exe 改名 `.old`，成功后 `.old` 保留（方便回滚），失败则回滚
    """
    if not url:
        raise ValueError("更新包链接为空")

    exe_path = os.path.abspath(sys.executable)
    tmp_dir = tempfile.mkdtemp(prefix="yumi_update_")
    tmp_download = os.path.join(tmp_dir, "package.download")
    new_exe = os.path.join(tmp_dir, "app.new")

    try:
        # ---- 下载 ----
        with _get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=timeout, stream=True
        ) as resp:
            resp.raise_for_status()
            with open(tmp_download, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        f.write(chunk)

        # ---- 判断是 zip 还是裸 exe ----
        with open(tmp_download, "rb") as f:
            head = f.read(2)
        if head == b"PK":
            with zipfile.ZipFile(tmp_download) as zf:
                exe_name = next(
                    (
                        n
                        for n in zf.namelist()
                        if n.lower().endswith(".exe")
                        and not n.lower().endswith(".old")
                        and not n.endswith("/")
                    ),
                    None,
                )
                if not exe_name:
                    raise RuntimeError("更新包里没有找到 exe 文件")
                with zf.open(exe_name) as src, open(new_exe, "wb") as out:
                    shutil.copyfileobj(src, out)
        else:
            shutil.copyfile(tmp_download, new_exe)

        # ---- 替换当前 exe ----
        old_exe = exe_path + ".old"
        if os.path.exists(old_exe):
            try:
                os.remove(old_exe)
            except OSError:
                pass
        try:
            os.replace(exe_path, old_exe)
            os.replace(new_exe, exe_path)
        except OSError:
            # 回滚：把原 exe 换回来，避免启动不了
            if os.path.exists(old_exe):
                os.replace(old_exe, exe_path)
            raise
        return exe_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
