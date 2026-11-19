"""让测试脚本在 Windows 控制台里不会因为编码崩掉。

问题：Windows 的 cmd / PowerShell 默认代码页是 936（GBK）。
测试里 `print` 出来的东西经常不是纯 GBK（比如 `\\xd6`、emoji、生僻汉字、
从服务器抓回来的日文/俄文服务器名），`print` 就会抛：

    UnicodeEncodeError: 'gbk' codec can't encode character ...

这跟被测代码毫无关系，但会让整个测试**提前崩在中途**，
看起来像「测试失败」，实际是控制台编不出来。

用法（放在每个测试脚本输出的最前面）：

    from console_utf8 import setup
    setup()

或者干脆只用 `safe_print()`，它对不出来的字符用 ? 代替，绝不抛异常。
"""
import io
import sys


def setup() -> None:
    """把 stdout / stderr 换成 UTF-8，并且编码失败时用 ? 代替而不是抛异常。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            # 已经是 UTF-8 就不动
            if (getattr(stream, "encoding", "") or "").lower().replace("-", "") == "utf8":
                continue
            buf = getattr(stream, "buffer", None)
            if buf is None:
                continue
            setattr(
                sys, name,
                io.TextIOWrapper(buf, encoding="utf-8", errors="replace",
                                 line_buffering=True),
            )
        except Exception:                    # noqa: BLE001
            pass


def safe_print(*args, **kwargs) -> None:
    """打印；编不出来的字符退化成 ?，绝不抛 UnicodeEncodeError。"""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        enc = (getattr(sys.stdout, "encoding", "") or "utf-8")
        print(text.encode(enc, "replace").decode(enc, "replace"), **kwargs)
