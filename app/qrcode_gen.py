"""生成登录二维码的 PNG（用成熟的 qrcode 库，不自己造轮子）。

为什么用 qrcode 库而不是自己写编码器：
  QR 编码涉及版本表、RS 纠错、分块交织、掩码评分、格式信息 BCH ——
  自己实现非常容易出错（我先试过，逐模块对比标准实现时差异上百个模块，
  扫不出来）。这是个纯 Python 的小依赖（50KB 左右，只依赖已经装了的 Pillow），
  为可靠性买单完全值得。

对外只有 qr_png(text) → PNG 字节。登录二维码内容约 60~80 字符，
版本 4~6、纠错 M 级，手机 B 站 App 一扫就开。
"""
from __future__ import annotations

import io


def qr_png(text: str, scale: int = 8, border: int = 4) -> bytes:
    """把文本编成二维码 PNG 字节（白底黑块、带安静区）。"""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(
        version=None,            # 让它按内容自动选最小版本
        error_correction=ERROR_CORRECT_M,
        box_size=scale,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_svg(text: str, border: int = 4) -> str:
    """SVG 版本（矢量，缩放不糊）。QML 的 Image 也能直接加载。"""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
    from qrcode.image.svg import SvgPathImage

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=border,
        image_factory=SvgPathImage,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8", "replace")


__all__ = ["qr_png", "qr_svg"]
