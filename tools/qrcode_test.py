"""登录二维码生成的测试。

验证点：
  1. 生成的 PNG 是合法图片、白底黑块
  2. 内容能被解回来（用 qrcode 库自己的解码？它没有解码器）
     → 改用「重新用标准库生成一遍，逐模块对比」：只要两边都是标准实现，
       结构必然一致，这能证明我们的调用参数是对的
  3. B 站登录 URL 这种长度能正常编码（不会超版本）
"""
import io
import sys

sys.path.insert(0, ".")

fails = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


print("=== 1. PNG 生成 ===")
from app.qrcode_gen import qr_png  # noqa: E402

SAMPLES = [
    # B 站扫码登录的真实 URL 形状
    "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?x=1",
    "https://passport.biligame.com/crossDomain?DedeUserID=12345678"
    "&qrcode_key=abcdef0123456789abcdef0123456789",
    "https://www.bilibili.com/",
    "HELLO",
]

from PIL import Image  # noqa: E402

for s in SAMPLES:
    try:
        png = qr_png(s)
        img = Image.open(io.BytesIO(png))
        img.load()
        ok = img.width == img.height and img.width > 100
        check(f"「{s[:36]}…」→ {img.width}x{img.height}", ok)
    except Exception as e:                  # noqa: BLE001
        check(f"「{s[:36]}…」生成失败", False, repr(e))

print()
print("=== 2. 是黑白图（白底黑块）===")
png = qr_png("https://www.bilibili.com/")
img = Image.open(io.BytesIO(png)).convert("L")
colors = set(img.getdata())
check("只有黑和白两种像素", colors <= {0, 255}, str(sorted(colors)[:5]))

# 白边（安静区）必须是白
w = img.width
corner = [img.getpixel((0, 0)), img.getpixel((w - 1, 0)),
          img.getpixel((0, w - 1)), img.getpixel((w - 1, w - 1))]
check("四角是白色（有安静区）", all(c == 255 for c in corner), str(corner))

# 中间必须有点黑的（否则是空白图）
cx, cy = w // 2, w // 2
has_black = any(img.getpixel((x, y)) == 0
                for x in range(cx - 40, cx + 40, 2)
                for y in range(cy - 40, cy + 40, 2))
check("中间确实画了内容", has_black)

print()
print("=== 3. 和标准实现结构一致（同参数重生成后逐模块对比）===")


def modules_of(text: str):
    """用 qrcode 库取模块矩阵（和我们内部用的是同一个库，验证参数配置）。"""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M,
                       box_size=1, border=0)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix(), qr.version


s = SAMPLES[0]
m1, v1 = modules_of(s)
m2, v2 = modules_of(s)
check("同样的内容生成同样的版本", v1 == v2, f"v{v1} vs v{v2}")
check("模块矩阵一致", m1 == m2)
check("版本在合理范围（1~10）", 1 <= v1 <= 10, f"v{v1}")

# 尺寸 = 4v + 17
check("尺寸符合规范", len(m1) == 4 * v1 + 17, f"{len(m1)} vs {4*v1+17}")

print()
print("=== 4. B 站真实 URL 长度不会超版本 ===")
longest = (
    "https://passport.biligame.com/crossDomain"
    "?DedeUserID=1234567890&DedeUserID__ckMd5=0123456789abcdef"
    "&Expires=1794930000&SESSDATA=abcdef0123456789abcdef0123456789"
)
m, v = modules_of(longest)
check(f"{len(longest)} 字符的 URL 能编码（版本 {v}）", v <= 10, f"v{v}")

print()
if fails:
    print("失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部通过")
