from .config import AppConfig
from .qt_compat import QComboBox, QFormLayout, QLineEdit, QWidget


class SettingsPanel(QWidget):
    def __init__(self, config: AppConfig):
        super().__init__()
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.local_root = QLineEdit(config.local_root)
        self.remote_host = QLineEdit(config.remote_host)
        self.remote_root = QLineEdit(config.remote_root)
        self.pc_ip = QLineEdit(config.pc_ip)
        self.teleop_python = QLineEdit(config.teleop_python)
        self.robot_net = QLineEdit(config.robot_net)
        self.robot_uv = QLineEdit(config.robot_uv)
        self.robot_python = QLineEdit(config.robot_python)
        self.robot_ld_library_path = QLineEdit(config.robot_ld_library_path)
        self.policy_path = QLineEdit(config.policy_path)
        self.pico_telemetry_host = QLineEdit(config.pico_telemetry_host)
        self.mode = QComboBox()
        self.mode.addItems(["robot deploy over ssh", "local sim2sim helper"])

        form.addRow("Local sim2real", self.local_root)
        form.addRow("Remote host", self.remote_host)
        form.addRow("Remote sim2real", self.remote_root)
        form.addRow("PC IP for VR ZMQ", self.pc_ip)
        form.addRow("Teleop Python", self.teleop_python)
        form.addRow("Robot DDS net", self.robot_net)
        form.addRow("Robot uv", self.robot_uv)
        form.addRow("Robot Python", self.robot_python)
        form.addRow("Robot LD_LIBRARY_PATH", self.robot_ld_library_path)
        form.addRow("Policy path", self.policy_path)
        form.addRow("PICO telemetry IP", self.pico_telemetry_host)
        form.addRow("Deploy mode", self.mode)

    def values(self) -> AppConfig:
        return AppConfig(
            local_root=self.local_root.text().strip(),
            remote_host=self.remote_host.text().strip(),
            remote_root=self.remote_root.text().strip(),
            pc_ip=self.pc_ip.text().strip(),
            teleop_python=self.teleop_python.text().strip(),
            robot_net=self.robot_net.text().strip(),
            robot_uv=self.robot_uv.text().strip(),
            robot_python=self.robot_python.text().strip(),
            robot_ld_library_path=self.robot_ld_library_path.text().strip(),
            policy_path=self.policy_path.text().strip(),
            pico_telemetry_host=self.pico_telemetry_host.text().strip(),
        )

    def deploy_mode(self) -> str:
        return self.mode.currentText()
