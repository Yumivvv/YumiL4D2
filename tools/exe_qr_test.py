"""验证打包后的 exe 里 qrcode 模块可用。

这个测试必须用**打包后的 exe** 跑，不能用源码环境 ——
`qrcode` 是新加的依赖，PyInstaller 的 hiddenimports 没配好就会漏打包，
源码环境完全测不出来，只有用户点「扫码登录」时才会炸。

做法：给 exe 传一个特殊参数，让它只跑「生成一张二维码然后退出」。
（main.py 里加了 --selftest-qr 分支）
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "Yumi的L4D2工具箱.exe")

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


if not os.path.isfile(EXE):
    print("找不到 exe，跳过：", EXE)
    sys.exit(0)

print("=== 用打包后的 exe 生成一张二维码 ===")
print("  exe:", EXE, flush=True)

try:
    proc = subprocess.run(
        [EXE, "--selftest-qr"],
        capture_output=True, text=True, timeout=90,
        encoding="utf-8", errors="replace",
        cwd=ROOT,
    )
except subprocess.TimeoutExpired:
    check("exe 自检超时", False)
    sys.exit(1)

out = (proc.stdout or "") + (proc.stderr or "")
print("  退出码:", proc.returncode, flush=True)
for line in out.splitlines()[:10]:
    print("  |", line[:120], flush=True)

check("exe 自检退出码为 0", proc.returncode == 0, str(proc.returncode))
check("输出里有 QR_OK 标记", "QR_OK" in out, out[-200:] if out else "(无输出)")
check("没有 ImportError / ModuleNotFoundError",
      "ImportError" not in out and "ModuleNotFoundError" not in out)

print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
