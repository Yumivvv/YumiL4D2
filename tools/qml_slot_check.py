"""守住一类很容易犯、又只在运行时才炸的错：

**QML 里调用了 Python 方法，但那个方法没加 `@Slot()`** —— QML 会抛
`TypeError: Property 'xxx' of object ... is not a function`，
而且这个异常会**中断整个 onClicked 处理函数**，后面的语句全部不执行
（「一键导入没效果」就是这么来的：`noteClipboardHandled()` 抛异常，
紧跟着的 `importFromText()` 永远没跑到）。

这个脚本从 qml 源码里抓出 `core.servers.xxx(` / `core.mods.xxx(` 这些调用，
逐个确认在对应的 Python 类上确实暴露给了 QML。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QObject  # noqa: E402

from app.servers import ServerManager  # noqa: E402


def qml_sources():
    for sub in ("qml",):
        base = os.path.join(ROOT, sub)
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if fn.endswith(".qml"):
                    yield os.path.join(dirpath, fn)


def slots_of(cls):
    """返回该类真正暴露给 QML 的槽名集合。"""
    names = set()
    for name in dir(cls):
        attr = getattr(cls, name, None)
        # PySide 把 @Slot 记在 __wrapped__ / pyqtMethod，最稳的判定是
        # 「这个属性是 Qt 元对象里的槽」——用 metaObject 查。
        if callable(attr) or isinstance(attr, property):
            names.add(name)
    meta = cls.staticMetaObject if hasattr(cls, "staticMetaObject") else None
    if meta is not None:
        exposed = set()
        for i in range(meta.methodOffset(), meta.methodCount()):
            m = meta.method(i)
            if m is not None:
                exposed.add(bytes(m.name()).decode("utf-8", "replace"))
        return exposed
    return names


# QML 里只可能调这几个「后端门面」对象
TARGETS = {
    "servers": ServerManager,
}


def main():
    exposed = {k: slots_of(v) for k, v in TARGETS.items()}
    problems = []
    checked = 0
    for path in qml_sources():
        text = open(path, encoding="utf-8").read()
        for obj, cls_name in re.findall(r"core\.(\w+)\.(\w+)\s*\(", text):
            if obj not in TARGETS:
                continue
            checked += 1
            if cls_name not in exposed[obj]:
                problems.append((os.path.relpath(path, ROOT), obj, cls_name))
    print(f"扫描到 {checked} 处 core.<门面>.<方法>( 调用")

    # 去重后报告
    seen = set()
    uniq = []
    for rel, obj, name in problems:
        key = (obj, name)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((rel, obj, name))

    if not uniq:
        print("全部都能被 QML 调到")
        return 0
    print()
    print("以下方法没暴露给 QML（缺 @Slot），QML 调用会抛 TypeError：")
    for rel, obj, name in uniq:
        print(f"  core.{obj}.{name}()   <- {rel}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
