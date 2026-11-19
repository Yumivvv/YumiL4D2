# -*- coding: utf-8 -*-
"""检查更新：版本比较、选包、检查逻辑、下载替换。

不联网：
  · 版本解析与比较用纯函数断言
  · check_update 用 monkeypatch 掉的假 release 列表断言
  · download_and_install 用假 HTTP 响应 + 假当前 exe 断言替换 / 回滚
"""
import io
import os
import sys
import tempfile
import time as _time
import zipfile

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from guard import protect_user_data  # noqa: E402

protect_user_data()

from app import updater  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


# ================================================================= 证书与出口
print("\n[0] 证书与统一 HTTP 出口")
import ssl as _ssl  # noqa: E402

check("有统一的 _get 出口", callable(getattr(updater, "_get", None)))
_ctx = updater._ssl_context()
check("_ssl_context 返回 SSLContext", isinstance(_ctx, _ssl.SSLContext))
check("上下文里加载了 CA 证书（系统库 + certifi）", len(_ctx.get_ca_certs()) > 0,
      str(len(_ctx.get_ca_certs())))
check("Session 是复用的", updater._session() is updater._session())

# ================================================================= 版本解析
print("\n[1] 版本解析与比较")
check("v1.0.1 → (1,0,1)", updater.parse_version("v1.0.1") == (1, 0, 1))
check("1.0.2 → (1,0,2)", updater.parse_version("1.0.2") == (1, 0, 2))
check("无 v 前缀 1.0 → (1,0,0)", updater.parse_version("1.0") == (1, 0, 0))
check(
    "带中文后缀 工具箱_1.0.10 → (1,0,10)",
    updater.parse_version("Yumi的L4D2工具箱_1.0.10") == (1, 0, 10),
)
check("空串 → ()", updater.parse_version("") == ())
check(
    "1.0.10 比 1.0.9 大（不是字符串序）",
    updater.parse_version("v1.0.10") > updater.parse_version("v1.0.9"),
)
check(
    "1.0.2 比 1.0.1 大",
    updater.parse_version("v1.0.2") > updater.parse_version("v1.0.1"),
)
check(
    "同版本相等",
    updater.parse_version("v1.0.1") == updater.parse_version("1.0.1"),
)

# ================================================================= 选更新包
print("\n[2] 选更新包链接")
check(
    "优先 .exe",
    updater.pick_asset_url(
        [
            {"name": "setup.zip", "browser_download_url": "http://a/b.zip"},
            {"name": "Yumi.exe", "browser_download_url": "http://a/b.exe"},
        ]
    )
    == "http://a/b.exe",
)
check(
    "没有 exe 时用 .zip",
    updater.pick_asset_url(
        [{"name": "setup.zip", "browser_download_url": "http://a/b.zip"}]
    )
    == "http://a/b.zip",
)
check("空资产返回空串", updater.pick_asset_url([]) == "")


# ================================================================= 检查逻辑
def _release(tag, body, assets=None):
    return {"tag_name": tag, "body": body, "assets": assets or []}


print("\n[3] 检查更新逻辑")
_orig_fetch = updater.fetch_releases
_orig_mirror = updater.latest_tag_via_mirror
_orig_assets = updater.assets_via_page

# ★ 默认把「镜像」这条路掐掉：check_update 现在是直连 API 与镜像并发竞速，
#   不掐掉的话每个用例都会真的去请求 8 个镜像站（本测试必须不联网）。
updater.latest_tag_via_mirror = lambda *a, **k: ""
updater.assets_via_page = lambda *a, **k: []

try:
    # 有新版本：聚合多个版本的日志
    updater.fetch_releases = lambda *a, **k: [
        _release("v1.0.0", "初始版本"),
        _release("v1.0.1", "修复弹窗越界"),
        _release("v1.0.2", "新增检查更新"),
    ]
    info = updater.check_update(current="1.0.1")
    check("有新版本时 has_update", info["has_update"] is True)
    check("latest 是最大版本", info["latest"] == "v1.0.2", extra=info["latest"])
    check("聚合了 1.0.2 的更新日志", "新增检查更新" in info["note"])
    check("不包含已安装的 1.0.1 日志", "修复弹窗越界" not in info["note"])

    # 没有新版本
    info = updater.check_update(current="1.0.2")
    check("已是最新时 has_update 为 False", info["has_update"] is False)
    check("已是最新时 error 为空", info["error"] == "")
    check("已是最新时 latest 回落到当前版本", info["latest"] == "1.0.2")

    # 当前版本解析不出来时，任何数字版本都算更新
    info = updater.check_update(current="")
    check("当前版本为空时仍能判断有更新", info["has_update"] is True)

    # 直连失败 → 镜像兜底
    def _boom(*a, **k):
        raise RuntimeError("api 403")

    updater.fetch_releases = _boom
    updater.latest_tag_via_mirror = lambda *a, **k: "v1.0.3"
    updater.assets_via_page = lambda *a, **k: ["https://gh/x.exe"]
    info = updater.check_update(current="1.0.1")
    check("镜像兜底能拿到 tag", info["latest"] == "v1.0.3", extra=info["latest"])
    check("镜像兜底判为有更新", info["has_update"] is True)
    check("镜像兜底有下载链接", info["url"] == "https://gh/x.exe")
    check("镜像兜底无 error", info["error"] == "")

    # 直连失败 + 镜像也失败
    updater.latest_tag_via_mirror = lambda *a, **k: ""
    info = updater.check_update(current="1.0.1")
    check("所有源不可用时 error 非空", info["error"] != "")
    check("所有源不可用时 has_update 为 False", info["has_update"] is False)
finally:
    updater.fetch_releases = _orig_fetch
    updater.latest_tag_via_mirror = _orig_mirror
    updater.assets_via_page = _orig_assets


# ================================================================= 并发竞速
# 用户实测的问题：8 个镜像串行各超时一次 → 「一直加载」约 26 秒。
# 现在两条路并发，谁先拿到可用结果就用谁，慢的那条不许拖住快的。
print("\n[4] 并发竞速（慢的源不拖住快的源）")
try:
    # 直连快、镜像慢 2 秒 → 应立刻返回直连结果
    updater.fetch_releases = lambda *a, **k: [
        _release("v1.0.0", "初始"),
        _release("v9.9.9", "快路径"),
    ]
    updater.latest_tag_via_mirror = lambda *a, **k: (_time.sleep(2), "v8.8.8")[1]
    t0 = _time.time()
    info = updater.check_update(current="1.0.1")
    cost = _time.time() - t0
    check("慢镜像不拖慢直连结果", cost < 1.0, extra=f"{cost:.2f}s")
    check("结果来自直连 API", info["latest"] == "v9.9.9", extra=info["latest"])

    # 直连慢 2 秒且无结果、镜像秒回 → 应立刻用镜像结果
    updater.fetch_releases = lambda *a, **k: (_time.sleep(2), [])[1]
    updater.latest_tag_via_mirror = lambda *a, **k: "v7.7.7"
    updater.assets_via_page = lambda *a, **k: []
    t0 = _time.time()
    info = updater.check_update(current="1.0.1")
    cost = _time.time() - t0
    check("快镜像不等慢直连", cost < 1.0, extra=f"{cost:.2f}s")
    check("结果来自镜像 tag", info["latest"] == "v7.7.7", extra=info["latest"])
    check("镜像结果判为有更新", info["has_update"] is True)
    check("镜像结果 error 为空", info["error"] == "")

    # 两条都秒失败 → 立刻报错，不空等超时
    updater.fetch_releases = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("api 403")
    )
    updater.latest_tag_via_mirror = lambda *a, **k: ""
    t0 = _time.time()
    info = updater.check_update(current="1.0.1")
    cost = _time.time() - t0
    check("全失败时不空等超时", cost < 1.0, extra=f"{cost:.2f}s")
    check("全失败时 error 非空", info["error"] != "")
finally:
    updater.fetch_releases = _orig_fetch
    updater.latest_tag_via_mirror = _orig_mirror
    updater.assets_via_page = _orig_assets


# ================================================================= 下载安装
class _FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.url = "http://fake/x"

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


print("\n[5] 下载安装")
_orig_get = updater._get
_orig_exe = updater.sys.executable
tmp = tempfile.mkdtemp(prefix="update_test_")
try:
    exe_path = os.path.join(tmp, "Yumi.exe")
    with open(exe_path, "wb") as f:
        f.write(b"OLD")

    # 造一个 zip，里面带 exe
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Yumi.exe", b"NEW")
    zip_bytes = buf.getvalue()

    updater.sys.executable = exe_path
    updater._get = lambda *a, **k: _FakeResp(zip_bytes)
    new_path = updater.download_and_install("https://example.com/pkg.zip")

    with open(exe_path, "rb") as f:
        check("zip 包里的 exe 已替换当前 exe", f.read() == b"NEW")
    check("返回新 exe 路径", new_path == exe_path)
    old_path = exe_path + ".old"
    check("原 exe 保留为 .old", os.path.exists(old_path))
    if os.path.exists(old_path):
        with open(old_path, "rb") as f:
            check(".old 里是旧内容（可回滚）", f.read() == b"OLD")

    # 裸 exe 包
    exe_path2 = os.path.join(tmp, "bare.exe")
    with open(exe_path2, "wb") as f:
        f.write(b"OLD2")
    updater.sys.executable = exe_path2
    updater._get = lambda *a, **k: _FakeResp(b"NEW2")
    updater.download_and_install("https://example.com/pkg.exe")
    with open(exe_path2, "rb") as f:
        check("裸 exe 直接替换", f.read() == b"NEW2")

    # zip 里没有 exe → 报错，且不能把当前 exe 弄坏
    exe_path3 = os.path.join(tmp, "noexe.exe")
    with open(exe_path3, "wb") as f:
        f.write(b"KEEP")
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("readme.txt", b"no exe here")
    updater.sys.executable = exe_path3
    updater._get = lambda *a, **k: _FakeResp(buf2.getvalue())
    try:
        updater.download_and_install("https://example.com/bad.zip")
        check("zip 里没 exe 应该报错", False)
    except Exception:
        check("zip 里没 exe 会报错", True)
    with open(exe_path3, "rb") as f:
        check("失败时当前 exe 没被破坏", f.read() == b"KEEP")
finally:
    updater._get = _orig_get
    updater.sys.executable = _orig_exe


print()
if fails:
    print(f"更新检查测试失败 {len(fails)} 项：")
    for name in fails:
        print("  - " + name)
    sys.exit(1)
print("更新检查测试全部通过")
