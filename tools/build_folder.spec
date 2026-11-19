# -*- mode: python ; coding: utf-8 -*-
"""打包脚本（**文件夹版**）：产物是 `dist/Yumi的L4D2工具箱/` 一个目录。

和单文件版（tools/build.spec）的区别：
- 启动快（不用每次解包 400 多 MB 到临时目录）
- 想临时换 QML / 换图标，直接改 `_internal/qml` 里的文件就行
- 缺点是「导出」时要整个文件夹一起拷

用法：
    python -m PyInstaller --noconfirm --clean --distpath dist --workpath build tools\\build_folder.spec
"""
import os

block_cipher = None

# 见 build.spec 里的说明：脚本路径必须从 SPECPATH 推算
try:
    _SPEC_DIR = os.path.abspath(SPECPATH)          # noqa: F821  (PyInstaller 注入)
except NameError:
    _SPEC_DIR = os.path.dirname(os.path.abspath(__file__))

ROOT = os.path.dirname(_SPEC_DIR)
icon = os.path.join(ROOT, "assets", "icon.ico")

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "qml"), "qml"),
        (os.path.join(ROOT, "assets"), "assets"),
        (os.path.join(ROOT, "sounds"), "sounds"),
    ],
    hiddenimports=[
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtNetwork",
        "PySide6.QtWidgets",
        "PySide6.QtMultimedia",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
        "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation",
        "PySide6.QtMultimediaWidgets", "PySide6.QtNfc",
        "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtPositioning", "PySide6.QtQmlModels", "PySide6.QtQuick3D",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
        "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
        "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtTest",
        "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
        "tkinter", "unittest", "pydoc", "doctest",
        "numpy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 和单文件版一样：踢掉 Qt WebEngine 与 Qt 多语言翻译（见 build.spec 里的说明）
_BIG_DROP = ("webengine", "translations")
a.binaries = [b for b in a.binaries if not any(k in b[0].lower() for k in _BIG_DROP)]
a.datas = [d for d in a.datas if not any(k in d[0].lower() for k in _BIG_DROP)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Yumi的L4D2工具箱",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon if os.path.exists(icon) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Yumi的L4D2工具箱",
)
