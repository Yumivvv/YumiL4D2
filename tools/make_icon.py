"""生成应用图标：把一只企鹅（原图 assets/icon_src.jpg）裁成圆角方块，导出各尺寸.

用法：
    python tools/make_icon.py                # 用 assets/icon_src.jpg
    python tools/make_icon.py 别的图.jpg      # 换源图

产出（都在 assets/ 下）：
    appLogo.png      侧栏品牌图标用的（256×256 圆角，带透明）
    icon_256/128/64/48/32/16.png
    icon.png         256 的单文件版（main.py 找不到 ico 时兜底）
    icon.ico         多尺寸 ICO（PyInstaller / 窗口 / 任务栏 / 托盘都用它）

为什么不再「纯代码画」：图标已经换成企鹅（Yumi）那张图了，
所以这里改成「从源图裁切 + 圆角」的生成脚本，保证换机器 / 换图后能一条命令重做。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
SRC = os.path.join(OUT_DIR, "icon_src.jpg")

# 源图里企鹅是竖长条，四周留白很宽。先自动找主体（非白像素）的包围盒，
# 再按包围盒居中裁成正方形，让企鹅在图标里占满 —— 不然 16/32 px 下只剩一个小点。
PAD = 0.03          # 包围盒外再留 3% 边距，别切到翅膀尖
WHITE = 244         # 比这个亮的像素当背景
# 图标圆角占边长的比例（Windows 11 应用图标大约是 22%）
RADIUS = 0.22
# 超采样倍数：先按 4 倍画圆角再缩回去，边缘才不会锯齿
SS = 4


def _subject_box(im: Image.Image):
    """找主体包围盒（非白像素）；找不到就整个图。"""
    gray = im.convert("L")
    mask = gray.point(lambda v: 255 if v < WHITE else 0)
    box = mask.getbbox()
    return box or (0, 0, im.size[0], im.size[1])


def make_base(path: str, size: int = 1024) -> Image.Image:
    """把源图裁成正方形 + 圆角，返回 size×size 的 RGBA。"""
    im = Image.open(path).convert("RGB")
    x0, y0, x1, y1 = _subject_box(im)
    bw, bh = x1 - x0, y1 - y0
    side = int(max(bw, bh) * (1 + PAD * 2))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    left, top = cx - side // 2, cy - side // 2

    # 正方形可能比源图还大（企鹅是竖长条）：先铺一块白底，再把图贴上去，
    # 直接 crop 越界的话 PIL 会补**黑色**，图标边上就会出现黑边。
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    src_box = (
        max(0, left),
        max(0, top),
        min(im.size[0], left + side),
        min(im.size[1], top + side),
    )
    if src_box[2] > src_box[0] and src_box[3] > src_box[1]:
        patch = im.crop(src_box)
        canvas.paste(patch, (src_box[0] - left, src_box[1] - top))
    im = canvas.resize((size, size), Image.LANCZOS).convert("RGBA")

    mask = Image.new("L", (size * SS, size * SS), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle(
        (0, 0, size * SS - 1, size * SS - 1), radius=int(size * SS * RADIUS), fill=255
    )
    mask = mask.resize((size, size), Image.LANCZOS)
    im.putalpha(mask)
    return im


def main(argv) -> int:
    src = argv[1] if len(argv) > 1 else SRC
    if not os.path.exists(src):
        print("找不到源图：", src)
        return 1

    base = make_base(src, 1024)
    os.makedirs(OUT_DIR, exist_ok=True)

    # 侧栏用的品牌图标
    logo = base.resize((256, 256), Image.LANCZOS)
    logo.save(os.path.join(OUT_DIR, "appLogo.png"))
    print("saved", os.path.join(OUT_DIR, "appLogo.png"))

    sizes = (256, 128, 64, 48, 32, 16)
    frames = []
    for s in sizes:
        img = base.resize((s, s), Image.LANCZOS)
        p = os.path.join(OUT_DIR, f"icon_{s}.png")
        img.save(p)
        print("saved", p)
        frames.append(img)

    big = base.resize((256, 256), Image.LANCZOS)
    big.save(os.path.join(OUT_DIR, "icon.png"))
    print("saved", os.path.join(OUT_DIR, "icon.png"))

    ico = os.path.join(OUT_DIR, "icon.ico")
    # 倒序：ICO 里最大的放前面，资源管理器缩放时更清楚
    frames[0].save(
        ico,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print("saved", ico)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
