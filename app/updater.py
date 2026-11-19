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
* 直连失败时（国内常见）遍历镜像前缀，请求 `{mirror}https://github.com/{repo}/releases/latest`，
  **从最终重定向 URL 里解析 `/tag/` 末段**拿 tag。镜像常返回 403 的网页，不能靠状态码判断，
  只能靠最终 URL。
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
import zipfile
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

# 网络超时（秒）
TIMEOUT = 10
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


def fetch_releases(repo: str = GITHUB_REPO, timeout: int = TIMEOUT) -> list:
    """直连 GitHub API 拿 release 列表（原始 dict 列表）。"""
    resp = requests.get(
        GITHUB_API.format(repo=repo), headers=_headers(), timeout=timeout
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("GitHub 返回的内容不是列表")
    return data


def latest_tag_via_mirror(repo: str = GITHUB_REPO, timeout: int = TIMEOUT) -> str:
    """直连失败时遍历镜像，从 `/releases/latest` 的最终 URL 解析 tag。

    镜像往往返回 403/404 的网页，所以**不判断状态码**，只认最终 URL 里是否含 `/tag/`。
    """
    target = GITHUB_LATEST.format(repo=repo)
    for mirror in MIRRORS:
        try:
            resp = requests.get(
                f"{mirror}{target}",
                headers={"User-Agent": _USER_AGENT},
                timeout=timeout,
                allow_redirects=True,
            )
            final_url = resp.url or ""
        except requests.RequestException:
            continue
        if "/tag/" in final_url:
            tag = final_url.rsplit("/tag/", 1)[1].strip("/").strip()
            if tag:
                return tag
    return ""


def assets_via_page(
    repo: str, tag: str, timeout: int = TIMEOUT
) -> list:
    """拿某个 release 的下载资产链接（仅 API 不可用时的兜底）。

    用 `releases/expanded_assets/{tag}` 这个 HTML 片段接口，比翻整个 release 页轻量。
    """
    url = f"https://github.com/{repo}/releases/expanded_assets/{tag}"
    for base in ("", *MIRRORS):
        try:
            resp = requests.get(
                f"{base}{url}", headers=_headers(), timeout=timeout
            )
            if resp.status_code != 200:
                continue
            found = _ASSET_RE.findall(resp.text)
            if found:
                # HTML 里可能是相对链接，统一转成绝对链接
                return [
                    u if u.startswith("http") else f"https://github.com{u}"
                    for u in found
                ]
        except requests.RequestException:
            continue
    return []


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
    """
    info: dict[str, Any] = {
        "has_update": False,
        "current": current,
        "latest": "",
        "note": "",
        "url": "",
        "error": "",
    }

    try:
        releases = fetch_releases(repo)
    except Exception as e:  # noqa: BLE001 —— 网络/解析任何异常都要兜底
        mirror_tag = ""
        try:
            mirror_tag = latest_tag_via_mirror(repo)
        except Exception:  # noqa: BLE001
            mirror_tag = ""
        if not mirror_tag:
            info["error"] = f"检查更新失败（所有源均不可用）：{e}"
            return info

        # 镜像只给了 tag，没有详细更新日志和资产列表
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

    # ---- 直连成功：聚合所有比当前新的版本 ----
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
        with requests.get(
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
