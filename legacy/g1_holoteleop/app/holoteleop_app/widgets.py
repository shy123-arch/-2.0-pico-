from pathlib import Path

from . import commands
from .config import AppConfig, RSYNC_EXCLUDES
from .qt_compat import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QTimer,
    QVBoxLayout,
    QWidget,
)


def make_button(text: str, slot, primary: bool = False, danger: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.clicked.connect(slot)
    if primary:
        button.setMinimumHeight(30)
        button.setProperty("primary", True)
    if danger:
        button.setProperty("danger", True)
    return button


class RunTab(QWidget):
    def __init__(self, get_config, get_mode, process_manager):
        super().__init__()
        self._get_config = get_config
        self._get_mode = get_mode
        self._processes = process_manager
        self._start_all_pending = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.debug_logs = QCheckBox("Debug logs")
        self.debug_logs.setToolTip("When enabled, Teleop and Deploy write timestamped logs under data/logs.")
        self.terminal_windows = QCheckBox("Terminal windows")
        self.terminal_windows.setChecked(True)
        self.terminal_windows.setToolTip("Run long-lived commands in real terminal windows instead of the embedded log pane.")

        all_box = QGroupBox("Quick Start")
        all_grid = QGridLayout(all_box)
        all_grid.addWidget(make_button("Start All", self.start_all, primary=True), 0, 0)
        all_grid.addWidget(make_button("Stop All", self.stop_all, danger=True), 0, 1)
        all_grid.addWidget(make_button("Stop Zero", self.stop_zero, danger=True), 0, 2)
        self.camera_label = QLabel()
        self._update_camera_label()
        all_grid.addWidget(self.camera_label, 0, 3)
        all_grid.addWidget(self.debug_logs, 0, 4)
        self.record_npz = QCheckBox("Record NPZ")
        self.status_secs = QSpinBox()
        self.status_secs.setRange(0, 3600)
        self.status_secs.setValue(5)
        all_grid.addWidget(self.terminal_windows, 0, 5)
        all_grid.addWidget(self.record_npz, 0, 6)
        all_grid.addWidget(QLabel("status seconds"), 0, 7)
        all_grid.addWidget(self.status_secs, 0, 8)
        all_hint = QLabel("Starts Camera and Teleop, then starts Deploy after a short delay.")
        all_hint.setObjectName("SectionHint")
        all_grid.addWidget(all_hint, 1, 0, 1, 9)
        all_grid.setColumnStretch(9, 1)
        layout.addWidget(all_box)

        manual_box = QGroupBox("Manual Control")
        manual_grid = QGridLayout(manual_box)
        self.stop_camera = make_button("Stop Camera", lambda: self._processes.stop("camera"), danger=True)
        self.stop_camera.setEnabled(False)
        self.stop_teleop = make_button("Stop Teleop", lambda: self._processes.stop("teleop"), danger=True)
        self.stop_teleop.setEnabled(False)
        self.stop_deploy = make_button("Stop Deploy", lambda: self._processes.stop("deploy"), danger=True)
        self.stop_deploy.setEnabled(False)

        manual_grid.addWidget(QLabel("Camera"), 0, 0)
        manual_grid.addWidget(make_button("Start Camera", self.start_robot_camera, primary=True), 0, 1)
        manual_grid.addWidget(self.stop_camera, 0, 2)
        manual_grid.addWidget(QLabel("Teleop"), 1, 0)
        manual_grid.addWidget(make_button("Start Teleop", self.start_local_teleop, primary=True), 1, 1)
        manual_grid.addWidget(self.stop_teleop, 1, 2)
        manual_grid.addWidget(make_button("Clean Stale Ports", self.clean_stale_teleop), 1, 3)
        manual_grid.addWidget(QLabel("Deploy"), 2, 0)
        manual_grid.addWidget(make_button("Patch VR Addr", self.patch_robot_vr_addr), 2, 1)
        manual_grid.addWidget(make_button("Start Deploy", self.start_robot_deploy, primary=True), 2, 2)
        manual_grid.addWidget(self.stop_deploy, 2, 3)
        manual_grid.addWidget(make_button("SSH Shell", self.open_ssh_shell), 2, 4)
        manual_grid.setColumnStretch(5, 1)
        layout.addWidget(manual_box)
        layout.addStretch(1)

    def start_all(self) -> None:
        self._start_all_pending = True
        self.start_robot_camera()
        self.start_local_teleop()
        self._processes.log("App", "Deploy will start after Teleop initialization delay.")
        QTimer.singleShot(2500, self._finish_start_all)

    def _finish_start_all(self) -> None:
        if not self._start_all_pending:
            self._processes.log("App", "Start All canceled before Deploy launch.")
            return
        self._start_all_pending = False
        self.start_robot_deploy()

    def stop_all(self) -> None:
        self._start_all_pending = False
        names = self._processes.stop_all()
        if names:
            self._processes.log("App", "Stopping all: " + ", ".join(names))
        else:
            self._processes.log("App", "No running commands to stop.")
        config = self._get_config()
        self._processes.run_once("Deploy", "ssh", [config.remote_host, commands.robot_stop_command(config)])
        self._processes.run_once("Teleop", "bash", ["-lc", commands.clean_local_teleop_command()])

    def stop_zero(self) -> None:
        self.stop_all()
        config = self._get_config()
        self._processes.log("App", "Stop Zero requested. Robot may go limp.")
        self._processes.run_once("Deploy", "ssh", [config.remote_host, commands.robot_zero_command(config)])

    def _update_camera_label(self) -> None:
        profile = commands.CAMERA_PROFILE
        self.camera_label.setText(f"Camera: {profile['name']} {profile['width']}x{profile['height']}")

    def start_robot_camera(self) -> None:
        config = self._get_config()
        self._run_long(
            "camera",
            "Camera",
            "ssh",
            ["-tt", config.remote_host, commands.robot_camera_command(config)],
            self.stop_camera,
        )

    def start_local_teleop(self) -> None:
        config = self._get_config()
        teleop_dir = str(Path(config.local_root).expanduser() / "teleop")
        self._run_long(
            "teleop",
            "Teleop",
            "bash",
            [
                "-lc",
                commands.local_teleop_command(
                    config,
                    self.record_npz.isChecked(),
                    self.status_secs.value(),
                    self.debug_logs.isChecked(),
                ),
            ],
            self.stop_teleop,
            cwd=teleop_dir,
        )

    def clean_stale_teleop(self) -> None:
        self._processes.run_once("Teleop", "bash", ["-lc", commands.clean_local_teleop_command()])

    def patch_robot_vr_addr(self) -> None:
        config = self._get_config()
        self._processes.run_once("Patch", "ssh", [config.remote_host, commands.patch_robot_command(config)])

    def start_robot_deploy(self) -> None:
        config = self._get_config()
        if self._get_mode() == "local sim2sim helper":
            self._run_long(
                "deploy",
                "Sim2Sim",
                "bash",
                ["-lc", commands.local_sim2sim_command()],
                self.stop_deploy,
                cwd=config.local_root,
            )
            return
        self._run_long(
            "deploy",
            "Deploy",
            "ssh",
            ["-tt", config.remote_host, commands.robot_deploy_command(config, self.debug_logs.isChecked())],
            self.stop_deploy,
        )

    def open_ssh_shell(self) -> None:
        config = self._get_config()
        self._processes.run_long("ssh", "SSH", "x-terminal-emulator", ["-e", "ssh", config.remote_host])

    def _run_long(
        self,
        key: str,
        title: str,
        program: str,
        args: list[str],
        stop_button,
        cwd: str | None = None,
    ) -> None:
        if self.terminal_windows.isChecked():
            self._processes.run_long_terminal(key, title, program, args, stop_button, cwd)
        else:
            self._processes.run_long(key, title, program, args, stop_button, cwd)


class SyncTab(QWidget):
    def __init__(self, get_config, process_manager):
        super().__init__()
        self._get_config = get_config
        self._processes = process_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        box = QGroupBox("Code Sync")
        grid = QGridLayout(box)
        self.delete_extra = QCheckBox("delete extra files with rsync --delete")
        self.delete_extra.setToolTip("Keep this off unless the target should exactly match the source.")
        grid.addWidget(make_button("Sync PC -> Robot", self.sync_to_robot, primary=True), 0, 0)
        grid.addWidget(make_button("Sync Robot -> PC", self.sync_from_robot), 0, 1)
        grid.addWidget(self.delete_extra, 1, 0, 1, 2)
        grid.setColumnStretch(2, 1)
        layout.addWidget(box)

        excludes = QTextEdit()
        excludes.setReadOnly(True)
        excludes.setPlainText("Excluded paths:\n" + "\n".join(f"  {item}" for item in RSYNC_EXCLUDES))
        excludes.setMaximumHeight(170)
        layout.addWidget(excludes)
        layout.addStretch(1)

    def sync_to_robot(self) -> None:
        self._processes.run_once("Sync", "rsync", commands.pc_to_robot_rsync(self._get_config(), self.delete_extra.isChecked()))

    def sync_from_robot(self) -> None:
        self._processes.run_once("Sync", "rsync", commands.robot_to_pc_rsync(self._get_config(), self.delete_extra.isChecked()))


class GuideTab(QWidget):
    def __init__(self, config: AppConfig):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)

        guide = QLabel(
            "1. PICO/XR：打开 XRoboToolkit PC Service，PICO 连接电脑 IP："
            f"<b>{config.pc_ip}</b>，开启 body/controller streaming。<br><br>"
            "2. Sync：先同步电脑代码到机器人。<br><br>"
            "3. Run：点击 <b>Start All</b> 一键启动 Camera、Teleop、Deploy。"
            "需要结束或中断时点击 <b>Stop All</b>。<br><br>"
            "4. 如果分步启动：先 <b>Start Camera</b>，再 <b>Start Teleop</b>，"
            "最后 <b>Patch VR Addr</b> + <b>Start Deploy</b>。<br><br>"
            "5. 控制：Unitree start 进默认姿态，Unitree B 进 tracking，"
            "PICO 右手 A 开始/恢复，PICO 左手 X 暂停，Unitree select 退出。"
        )
        guide.setObjectName("GuideText")
        guide.setWordWrap(True)
        layout.addWidget(guide)
        layout.addStretch(1)
