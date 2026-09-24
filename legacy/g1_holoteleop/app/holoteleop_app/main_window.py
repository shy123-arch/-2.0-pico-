from .config import AppConfig
from .processes import ProcessManager
from .qt_compat import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from .settings import SettingsPanel
from .widgets import GuideTab, RunTab, SyncTab


class LogTabs(QTabWidget):
    def __init__(self) -> None:
        super().__init__()
        self._logs: dict[str, QPlainTextEdit] = {}
        for name in ("All", "App", "Camera", "Teleop", "Deploy", "Patch", "Sync", "Sim2Sim", "SSH"):
            self._ensure_log(name)

    def append(self, channel: str, text: str) -> None:
        channel = channel or "App"
        line = text.rstrip()
        self._append_to(channel, line)
        if channel != "All":
            prefix = f"[{channel}] " if line else ""
            self._append_to("All", prefix + line)

    def _ensure_log(self, channel: str) -> QPlainTextEdit:
        existing = self._logs.get(channel)
        if existing is not None:
            return existing

        log = QPlainTextEdit()
        log.setReadOnly(True)
        log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._logs[channel] = log
        self.addTab(log, channel)
        return log

    def _append_to(self, channel: str, text: str) -> None:
        log = self._ensure_log(channel)
        log.appendPlainText(text)
        log.verticalScrollBar().setValue(log.verticalScrollBar().maximum())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HoloTeleop")
        self.resize(960, 600)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)

        title = QLabel("HoloTeleop")
        title.setObjectName("Title")
        layout.addWidget(title)

        subtitle = QLabel("Run, sync, and configure the teleop deployment workflow.")
        subtitle.setObjectName("Subtitle")
        layout.addWidget(subtitle)

        self.processes = ProcessManager(self, self._log)
        self.logs = LogTabs()

        self.settings = SettingsPanel(AppConfig())
        tabs = QTabWidget()
        tabs.addTab(RunTab(self.current_config, self.settings.deploy_mode, self.processes), "Run")
        tabs.addTab(SyncTab(self.current_config, self.processes), "Sync")
        tabs.addTab(self.settings, "Settings")
        tabs.addTab(GuideTab(AppConfig()), "Guide")
        layout.addWidget(tabs, stretch=2)
        layout.addWidget(self.logs, stretch=1)

        self._log("App", "Ready.")

    def current_config(self) -> AppConfig:
        return self.settings.values()

    def _log(self, channel: str, text: str) -> None:
        self.logs.append(channel, text)

    def closeEvent(self, event) -> None:
        running = self.processes.running_names()
        if running:
            reply = QMessageBox.question(
                self,
                "Stop running commands?",
                "Stop running commands before exit?\n" + "\n".join(running),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.processes.stop_all()
        event.accept()
