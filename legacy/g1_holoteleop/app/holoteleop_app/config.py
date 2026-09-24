from dataclasses import dataclass


@dataclass
class AppConfig:
    local_root: str = "/media/william/play/molospace/HoloTeleop-deploy/HoloTeleop/sim2real"
    remote_host: str = "unitree@172.18.26.133"
    remote_root: str = "/home/unitree/HoloTeleop/sim2real"
    pc_ip: str = "172.18.26.64"
    robot_vr_host: str = "172.18.26.133"
    vr_udp_stream_port: int = 28704
    teleop_python: str = "/home/william/miniconda3/envs/gmr/bin/python"
    robot_net: str = "eth0"
    robot_uv: str = "uv"
    robot_python: str = "/home/unitree/miniforge3/envs/holo310/bin/python"
    robot_ld_library_path: str = "/home/unitree/miniforge3/envs/holo310/lib:/home/unitree/workspace/cyclonedds/install/lib"
    policy_path: str = "assets/ckpts/G1TRACKING-06-07_11-15/policy.onnx"
    pico_telemetry_host: str = "172.18.26.64"


RSYNC_EXCLUDES = [
    ".venv",
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "teleop/teleop_records",
]
