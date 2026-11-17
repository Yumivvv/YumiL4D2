"""程序入口：QML 引擎、系统托盘、单实例、窗口记忆."""
from __future__ import annotations

import os
import sys

# ---- 必须在 QGuiApplication 之前设置 ----
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
# QtMultimedia 每次播放都会把 FFmpeg 的探测信息打到 stderr，噪音太大，压一下
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg=false;qt.multimedia.ffmpeg.*=false")

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Slot  # noqa: E402
from PySide6.QtGui import QAction, QGuiApplication, QIcon  # noqa: E402
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
            self.app.quit()


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
        window.setColor(Qt.GlobalColor.transparent)

    tray = Tray(app, core, window)
    instance = SingleInstance(tray.show_window)

    # 剪贴板监听：有人复制了新东西时打一个戳，界面据此判断「这是新复制的」，
    # 而不是「程序一启动就把旧剪贴板当成新内容」。必须在主线程挂（QClipboard 是 GUI 线程对象）。
    core.servers.watch_clipboard()

    # 窗口关闭 → 收进托盘（可在设置里关掉）；关掉开关时直接退出
    def _on_closing(close):
        if core.trayOnClose and QSystemTrayIcon.isSystemTrayAvailable():
            close.accepted = False
            if isinstance(window, QQuickWindow):
                window.hide()
            # 收进托盘时也要停掉播放器，避免后台还在放声音
            core.stopVideo()
            try:
                tray.tray.showMessage(
                    "Yumi的L4D2工具箱",
                    "已最小化到托盘，有新视频时会弹通知提醒你～",
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )
            except RuntimeError:
                pass
        else:
            close.accepted = True
            core.shutdown()
            tray.tray.hide()
            QTimer.singleShot(0, app.quit)

    try:
        window.closing.connect(_on_closing)
    except AttributeError:
        pass

    # 任何方式退出都兜底停掉播放器与流代理
    app.aboutToQuit.connect(core.shutdown)

    _keep = (tray, instance)  # 防止被 GC
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
