"""单独把 WorkshopPage.qml 编译一遍，用最快的速度抓 QML 语法/属性错误。

比整窗口起来快得多：不加载 Main.qml，不连网络，只做 QML 解析 + 实例化。
用法：python -X utf8 tools/ws_qml_check.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine

from app.util import ROOT

app = QGuiApplication(sys.argv[:1])
engine = QQmlEngine()
q = os.path.join(ROOT, "qml")
engine.addImportPath(q)
engine.addImportPath(os.path.join(q, "components"))

target = os.path.join(q, "components", "WorkshopPage.qml")
comp = QQmlComponent(engine, QUrl.fromLocalFile(target))
if comp.isError():
    print("QML ERROR:")
    for err in comp.errors():
        print("  ", err.toString())
    sys.exit(1)

obj = comp.create()
if obj is None:
    print("CREATE FAILED:")
    for err in comp.errors():
        print("  ", err.toString())
    sys.exit(1)

print("OK  WorkshopPage.qml 编译通过")
print("    objectName =", obj.property("objectName"))
print("    kind       =", obj.property("kind"))
print("    includeDeps=", obj.property("includeDeps"))
sys.exit(0)
