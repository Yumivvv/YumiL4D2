# -*- mode: python ; coding: utf-8 -*-
"""打包脚本：pyinstaller 打包.bat 会调用它.

**单文件版**：所有东西（Qt 库、qml、assets、自带音效）都塞进一个 exe，
运行时自动解包到临时目录。产物：`dist/Yumi的L4D2工具箱.exe`。

用户数据（data / sounds / backgrounds）不在包里，首次运行会在 **exe 旁边**创建，
见 app/util.py 的 seed_user_dirs()。

要「文件夹版」（启动快、方便换 QML）用 tools/build_folder.spec。
"""
import os

block_cipher = None

# PyInstaller 执行 spec 时会把「spec 文件所在目录」注入成 SPECPATH，
# 而且 Analysis 里的相对脚本路径是**相对 spec 目录**解析的。
# 以前这里写 os.path.abspath(".")（= 调用时的工作目录），
# 从项目根调用 `pyinstaller tools/build.spec` 就会去找 tools/main.py，
# 直接报 "script '...\tools\main.py' not found"。
try:
    _SPEC_DIR = os.path.abspath(SPECPATH)          # noqa: F821  (PyInstaller 注入)
except NameError:                                   # 兜底：直接跑 spec 时
    _SPEC_DIR = os.path.dirname(os.path.abspath(__file__))

ROOT = os.path.dirname(_SPEC_DIR)                   # 项目根目录
icon = os.path.join(ROOT, "assets", "icon.ico")

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "qml"), "qml"),
        (os.path.join(ROOT, "assets"), "assets"),
        # 默认提示音效随包发布（用户导入的会落在 exe 旁边的 sounds/ 里）
        (os.path.join(ROOT, "sounds"), "sounds"),
    ],
    hiddenimports=[
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtNetwork",
        "PySide6.QtWidgets",
        # 播放器和自定义提示音都要它，不能 exclude
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
        # 我们不用 numpy（PIL 是可选的加速依赖，没它照样缩放）
        "numpy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# --- 瘦身：踢掉用不上的大块 -------------------------------------------------
# 1) Qt WebEngine：我们没有任何浏览器控件，但 PySide6 的钩子会把
#    Qt6WebEngineCore.dll（194 MB！）一起拖进来，占整个包的四成。
# 2) Qt 自带的多语言翻译文件（8.5 MB）：界面文案全是中文硬编码，用不上。
_BIG_DROP = ("webengine", "translations")
a.binaries = [b for b in a.binaries if not any(k in b[0].lower() for k in _BIG_DROP)]
a.datas = [d for d in a.datas if not any(k in d[0].lower() for k in _BIG_DROP)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 单文件：binaries / datas 全部交给 EXE，不再有 COLLECT
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Yumi的L4D2工具箱",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon if os.path.exists(icon) else None,
)
