"""程序入口：QML 引擎、系统托盘、单实例、窗口记忆."""
from __future__ import annotations

import os
import sys

# ---- 必须在 QGuiApplication 之前设置 ----
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
# QtMultimedia 每次播放都会把 FFmpeg 的探测信息打到 stderr，噪音太大，压一下
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg=false;qt.multimedia.ffmpeg.*=false")


def _silence_hard_error_boxes() -> None:
    """把进程级的「硬错误弹框」关掉（Windows 默认那套）。

    ★ 为什么需要：用户报「打开软件就弹 socialclub.dll not found，点确定后
      整个程序消失」。那个框是**被加载进来的第三方 DLL**（游戏目录里被
      整合包替换过的 steam_api64.dll）弹的 —— 它在 DllMain 里找不到自己的
      依赖，就调 MessageBoxW，用户一点确定它再 TerminateProcess。

      根因那侧已经修了（`steamfriends._dll_is_genuine()` 加载前验签，
      不再把可疑 DLL 拉进进程）。这里再加一道**兜底**：

        * `SEM_FAILCRITICALERRORS` —— 缺 DLL / 缺入口点时不再弹系统框，
          而是让 LoadLibrary 直接返回错误码（我们本来就会处理）。
        * `SEM_NOGPFAULTERRORBOX` —— 访问冲突等硬崩不再弹框，安静退出
          （日志里有记录），避免用户以为「点了确定程序就没了」。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        SEM_FAILCRITICALERRORS = 0x0001
        SEM_NOGPFAULTERRORBOX = 0x0002
        SEM_NOOPENFILEERRORBOX = 0x8000
        k32 = ctypes.windll.kernel32
        # SetErrorMode 返回旧值；先读再按位或，避免覆盖掉外部已设的位
        old = k32.SetErrorMode(0)
        k32.SetErrorMode(old | SEM_FAILCRITICALERRORS
                         | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX)
    except Exception:                            # noqa: BLE001 —— 兜底失败不影响主流程
        pass


_silence_hard_error_boxes()

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Slot  # noqa: E402
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon  # noqa: E402

from app import APP_ID  # noqa: E402
from app.core import Core  # noqa: E402
from app.util import ROOT, Log, resource_path, seed_user_dirs  # noqa: E402

log = Log("app.log")


def icon_path() -> str:
    for name in ("icon.ico", "icon.png"):
        p = resource_path("assets", name)
        if os.path.exists(p):
            return p
    return ""


def _supports_transparent_window() -> bool:
    """当前系统能不能安全地用「透明窗口 + 无边框」。

    Windows 11（build >= 22000）可以；Win10 及更老版本上用不透明底色。

    为什么要判：Win10 上 frameless + transparent 在某些驱动 /
    「设置 → 个性化 → 颜色 → 透明效果 = 关」的组合下，整窗会变全黑，
    用户看到的是「软件打开一片黑」。开发机是 Win11 所以一直没暴露。

    非 Windows 平台一律返回 False（用不透明底色，最安全）。
    """
    if sys.platform != "win32":
        return False
    try:
        return sys.getwindowsversion().build >= 22000
    except Exception:                        # noqa: BLE001
        return False


class SingleInstance(QObject):
    """第二次启动时把已有窗口叫出来，而不是开第二个."""

    def __init__(self, on_activate, parent=None):
        super().__init__(parent)
        self.on_activate = on_activate
        self.server = QLocalServer(self)
        QLocalServer.removeServer(APP_ID)
        self.server.newConnection.connect(self._new_connection)
        self.server.listen(APP_ID)

    def _new_connection(self) -> None:
        sock = self.server.nextPendingConnection()
        if sock is not None:
            sock.readyRead.connect(lambda: self._read(sock))
            sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock: QLocalSocket) -> None:
        data = bytes(sock.readAll())
        if b"show" in data:
            self.on_activate()
        sock.disconnectFromServer()

    @staticmethod
    def notify_running() -> bool:
        sock = QLocalSocket()
        sock.connectToServer(APP_ID)
        if sock.waitForConnected(300):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(200)
            sock.disconnectFromServer()
            return True
        return False


class Tray(QObject):
    def __init__(self, app: QApplication, core: Core, window, parent=None):
        super().__init__(parent)
        self.app = app
        self.core = core
        self.window = window
        self.tray = QSystemTrayIcon(QIcon(icon_path()) if icon_path() else QIcon(), self)
        self.tray.setToolTip("Yumi的L4D2工具箱")
        self.menu = QMenu()
        self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.tray.show()
        core.notifier.set_tray(self.tray)

        # 菜单里的勾选状态跟窗口内的开关保持同步
        core.statusChanged.connect(self._sync_menu)

    def _sync_menu(self) -> None:
        try:
            self.act_monitor.setChecked(self.core.monitoring)
        except (RuntimeError, AttributeError):
            pass

    def _build_menu(self) -> None:
        act_show = QAction("显示主窗口", self.menu)
        act_show.triggered.connect(self.show_window)
        self.menu.addAction(act_show)

        self.act_scan = QAction("立即检查新视频", self.menu)
        self.act_scan.triggered.connect(self.core.scan_now)
        self.menu.addAction(self.act_scan)

        self.act_monitor = QAction("后台自动刷新", self.menu)
        self.act_monitor.setCheckable(True)
        self.act_monitor.setChecked(self.core.monitoring)
        self.act_monitor.triggered.connect(self._toggle_monitor)
        self.menu.addAction(self.act_monitor)

        self.menu.addSeparator()
        act_quit = QAction("退出", self.menu)
        act_quit.triggered.connect(self.quit)
        self.menu.addAction(act_quit)

    def _toggle_monitor(self, checked: bool) -> None:
        if checked:
            self.core.start_monitor()
        else:
            self.core.stop_monitor()
        self.act_monitor.setChecked(self.core.monitoring)

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    @Slot()
    def show_window(self) -> None:
        if self.window is None:
            return
        self.window.show()
        self.window.setVisible(True)
        self.window.raise_()
        self.window.requestActivate()

    def quit(self) -> None:
        try:
            self.core.config.save()
            self.core.library.save()
        finally:
            self.tray.hide()
            # ★ 不能直接 app.quit()：那会给窗口发 close 事件，而 QML 的
            #   onClosing 在「收进托盘」模式下会 accepted=false 把它拦下来，
            #   结果窗口关不掉、事件循环退不出，进程卡死。
            #   requestQuit() 会先置 forceQuit 再退出，QML 那边见到就放行。
            self.core.requestQuit()


def main() -> int:
    # 打包成单文件后，data / sounds / backgrounds 都在 exe 旁边创建，
    # 顺带把自带的默认提示音铺一份过去（见 util.seed_user_dirs）
    seed_user_dirs()
    if SingleInstance.notify_running():
        return 0

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Yumi的L4D2工具箱")
    app.setApplicationDisplayName("Yumi的L4D2工具箱")
    app.setOrganizationName("L4D2Watcher")
    app.setQuitOnLastWindowClosed(False)

    if icon_path():
        app.setWindowIcon(QIcon(icon_path()))

    if not QSystemTrayIcon.isSystemTrayAvailable():
        Core_tray_default = False
    else:
        Core_tray_default = True

    engine = QQmlApplicationEngine()
    core = Core(app)
    if not Core_tray_default:
        core.config["tray_on_close"] = False

    ctx = engine.rootContext()
    ctx.setContextProperty("core", core)

    qml_dir = resource_path("qml")
    engine.addImportPath(qml_dir)
    engine.addImportPath(os.path.join(qml_dir, "components"))

    qml_file = os.path.join(qml_dir, "Main.qml")
    engine.load(QUrl.fromLocalFile(qml_file))

    roots = engine.rootObjects()
    if not roots:
        log("QML load failed")
        return 1
    window = roots[0]
    if isinstance(window, QQuickWindow):
        if icon_path():
            window.setIcon(QIcon(icon_path()))
        # ★ 透明窗口 + 无边框在 **Windows 10** 上是高风险组合：
        #   Win11 有 DWM 的圆角/合成器打底，透明区域能正常合成；
        #   Win10 上某些显卡驱动 / 关闭「透明效果」的设置下，
        #   整窗会被合成成**全黑**或**全透明**（用户看到的是「软件一片黑」）。
        #   真正需要透明的只是我们自己的圆角外框（qml 里 frame 那个 Rectangle），
        #   所以 Win10 上直接给一个不透明底色，圆角外那点直角损失可以接受，
        #   换来的是「一定能看见界面」。
        if _supports_transparent_window():
            window.setColor(Qt.GlobalColor.transparent)
        else:
            window.setColor(QColor(10, 12, 17))     # 和 Theme.bg 的深色一致

    tray = Tray(app, core, window)
    instance = SingleInstance(tray.show_window)

    # 剪贴板监听：有人复制了新东西时打一个戳，界面据此判断「这是新复制的」，
    # 而不是「程序一启动就把旧剪贴板当成新内容」。必须在主线程挂（QClipboard 是 GUI 线程对象）。
    core.servers.watch_clipboard()

    # 窗口关闭 → 收进托盘（可在设置里关掉）；关掉开关时直接退出
    #
    # ★ 这里**不能**用 `window.closing.connect(普通Python函数)`：
    #   `closing` 信号带一个 `QQuickCloseEvent*` 参数，PySide6 无法把它
    #   转换成 Python 对象，运行时会抛
    #       TypeError: Cannot call meta function "slot(QQuickCloseEvent*)"
    #       because parameter 0 of type "QQuickCloseEvent*" cannot be converted
    #   结果是**关闭窗口时那个处理器根本没执行**（收不到托盘、也不退出）。
    #   实测复现过：connect 本身不报错，但事件触发时 handler 一次都没被调用。
    #
    #   所以关闭逻辑写在 QML 的 `onClosing` 里（QML 原生能拿到 close 事件，
    #   也能改 close.accepted），Python 这边只提供两个**无参**槽：
    #       core.hideToTray()  —— 收进托盘
    #       core.quitFromWindow() —— 真正退出
    #   QML 侧见 qml/Main.qml 顶层的 onClosing。

    # 任何方式退出都兜底停掉播放器与流代理
    app.aboutToQuit.connect(core.shutdown)

    _keep = (tray, instance)  # 防止被 GC
    return app.exec()


def _selftest_qr() -> int:
    """打包自检：只验证「二维码能生成」这条链路，然后退出。

    为什么要这个入口：`qrcode` 是新加的第三方依赖，PyInstaller 没配好就会
    漏打包 —— 源码环境完全测不出来，只有用户点「扫码登录」时才炸。
    这个分支让打包后的 exe 自己跑一遍，CI / 打包脚本能立刻发现问题。

    用法：`Yumi的L4D2工具箱.exe --selftest-qr`
    """
    try:
        from app.qrcode_gen import qr_png

        png = qr_png("https://www.bilibili.com/", scale=4, border=2)
        ok = png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 200
        print(f"QR_OK {len(png)} bytes" if ok else "QR_BAD 内容不对")
        return 0 if ok else 1
    except Exception as e:                       # noqa: BLE001
        print(f"QR_FAIL {e.__class__.__name__}: {e}")
        return 1


if __name__ == "__main__":
    if "--selftest-qr" in sys.argv:
        sys.exit(_selftest_qr())
    sys.exit(main())
