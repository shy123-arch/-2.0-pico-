import shlex
from pathlib import Path

from .config import AppConfig, RSYNC_EXCLUDES


def quote(value: str) -> str:
    return shlex.quote(value)


def rsync_args(source: str, dest: str, delete_extra: bool) -> list[str]:
    args = ["-av"]
    if delete_extra:
        args.append("--delete")
    for item in RSYNC_EXCLUDES:
        args.extend(["--exclude", item])
    args.extend([source, dest])
    return args


def pc_to_robot_rsync(config: AppConfig, delete_extra: bool) -> list[str]:
    source = str(Path(config.local_root).expanduser()) + "/"
    dest = f"{config.remote_host}:{config.remote_root.rstrip('/')}/"
    return rsync_args(source, dest, delete_extra)


def robot_to_pc_rsync(config: AppConfig, delete_extra: bool) -> list[str]:
    source = f"{config.remote_host}:{config.remote_root.rstrip('/')}/"
    dest = str(Path(config.local_root).expanduser()) + "/"
    return rsync_args(source, dest, delete_extra)


def local_teleop_command(config: AppConfig, record_npz: bool, status_seconds: int, debug_logs: bool) -> str:
    local_root = Path(config.local_root).expanduser()
    project_root = local_root.parent
    data_root = project_root / "data"
    env_parts = [
        f"UDP_STREAM_HOST={quote(config.robot_vr_host)}",
        f"UDP_STREAM_PORT={int(config.vr_udp_stream_port)}",
        "UDP_STREAM_FPS=50",
        "UDP_STREAM_QOS=1",
    ]
    if record_npz:
        env_parts.append(f"PICO_RECORD_OUTPUT_DIR={quote(str(data_root / 'pico_records'))}")
        env_parts.append(f"RECORD_STATUS_INTERVAL_S={int(status_seconds)}")
    if debug_logs:
        env_parts.append(
            f"DEBUG_LOG_FILE={quote(str(data_root / 'logs'))}/teleop_debug_$(date +%Y%m%d_%H%M%S).log"
        )
        env_parts.append("DEBUG_RETARGET_STALL_WARN_MS=500")
        env_parts.append("DEBUG_RAW_FRESH_MS=200")
        env_parts.append("DEBUG_REPLY_PROCESS_WARN_MS=50")
        env_parts.append("DEBUG_PICO_CALLBACK_WARN_MS=100")
        env_parts.append("DEBUG_PICO_HEALTH_INTERVAL_S=3")
        env_parts.append("LOG_INTERVAL_S=3")
        env_parts.append("DEBUG_WARNING_INTERVAL_S=3")
    python_path = Path(config.teleop_python).expanduser()
    python_dir = python_path.parent
    conda_prefix = python_dir.parent
    port_check_py = """
import socket
import sys
busy = []
for port in (28701, 28702, 28703):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as exc:
        busy.append(f"{port}: {exc}")
    finally:
        sock.close()
if busy:
    print("[teleop] ZMQ port already in use: " + "; ".join(busy))
    print("[teleop] Stop Local Teleop, or run Clean Stale Teleop, then start again.")
    sys.exit(98)
"""
    port_check = f"{quote(str(python_path))} -c {quote(port_check_py)}"
    log_dir_setup = f"mkdir -p {quote(str(data_root / 'logs'))} && " if debug_logs else ""
    return (
        "unset VIRTUAL_ENV PYTHONHOME PYTHONPATH && "
        f"test -x {quote(str(python_path))} || "
        f"(echo '[teleop] missing executable: {quote(str(python_path))}' && exit 127) && "
        f"export CONDA_PREFIX={quote(str(conda_prefix))} && "
        f"export PATH={quote(str(python_dir))}:\"$PATH\" && "
        "hash -r && "
        + log_dir_setup
        + port_check
        + " && "
        + " ".join(env_parts + ["exec bash teleop_pose_50hz.sh"])
    )


def clean_local_teleop_command() -> str:
    return (
        "pkill -TERM -f '[x]robot_teleop_to_pose_zmq_server.py|[t]eleop_pose_50hz.sh' || true; "
        "sleep 0.5; "
        "pkill -KILL -f '[x]robot_teleop_to_pose_zmq_server.py|[t]eleop_pose_50hz.sh' || true; "
        "echo 'cleaned local stale teleop processes'"
    )


def robot_python_command(config: AppConfig) -> str:
    python = quote(config.robot_python)
    ld_library_path = config.robot_ld_library_path.strip()
    if ld_library_path:
        return f"LD_LIBRARY_PATH={quote(ld_library_path)}:\"$LD_LIBRARY_PATH\" {python}"
    return python


CAMERA_PROFILE = {
    "name": "DJI",
    "device_glob": "*DJI*video-index0",
    "input_format": "H264",
    "width": 720,
    "height": 1280,
    "fps": 30,
}


def _camera_cleanup_snippet() -> str:
    return (
        "PIDS=$(pgrep -x holoteleop_came || true); "
        "if [ -n \"$PIDS\" ]; then kill -INT $PIDS || true; sleep 0.15; kill -TERM $PIDS || true; sleep 0.15; kill -KILL $PIDS 2>/dev/null || true; fi; "
    )


def robot_camera_command(config: AppConfig) -> str:
    profile = CAMERA_PROFILE
    camera_root = config.remote_root.rstrip("/") + "/camera_streamer"
    return (
        f"cd {quote(camera_root)} && "
        + _camera_cleanup_snippet()
        +
        f"DEVICE=$(readlink -f /dev/v4l/by-id/{profile['device_glob']}) && "
        "test -n \"$DEVICE\" && "
        "CAMERA_DEVICE=\"$DEVICE\" "
        f"CAMERA_INPUT_FORMAT={profile['input_format']} "
        "CAMERA_TRANSPORT=TCP "
        f"CAMERA_WIDTH={profile['width']} "
        f"CAMERA_HEIGHT={profile['height']} "
        f"CAMERA_FPS={profile['fps']} "
        "CAMERA_CONTROL_PORT=13579 "
        "RECORD_CONTROL_PORT=13600 "
        "stdbuf -oL -eL bash scripts/start_camera_streamer.sh"
    )


def robot_camera_stop_command(config: AppConfig) -> str:
    camera_root = config.remote_root.rstrip("/") + "/camera_streamer"
    return (
        f"cd {quote(camera_root)} && "
        + _camera_cleanup_snippet()
        +
        "echo 'requested camera cleanup'"
    )


def robot_stop_command(config: AppConfig) -> str:
    return (
        f"cd {quote(config.remote_root)} && "
        "pkill -INT -f '[s]rc/deploy.py|[s]tart_camera_streamer.sh|[c]amera_streamer' || true; "
        "sleep 2; "
        "pkill -TERM -f '[s]rc/deploy.py|[s]tart_camera_streamer.sh|[c]amera_streamer' || true; "
        "echo 'requested robot deploy/camera cleanup'"
    )


def robot_zero_command(config: AppConfig) -> str:
    return (
        f"cd {quote(config.remote_root)} && "
        f"test -x {quote(config.robot_python)} || "
        f"(echo '[zero] missing robot python: {quote(config.robot_python)}' && exit 127) && "
        f"{robot_python_command(config)} scripts/send_zero_cmd.py --net {quote(config.robot_net)} --duration 2.0 --rate 50"
    )


def robot_patch_script(pc_ip: str, udp_stream_port: int) -> str:
    return f"""import json
import re
from pathlib import Path
p = Path("config/tracking.yaml")
s = p.read_text()
for port in ("28701", "28702", "28703"):
    s = s.replace(f"tcp://127.0.0.1:{{port}}", f"tcp://{pc_ip}:{{port}}")
    s = re.sub(rf"tcp://[0-9.]+:{{port}}", f"tcp://{pc_ip}:{{port}}", s)
settings = {{
    "vr_transport": json.dumps("udp_stream"),
    "vr_udp_stream_bind_addr": json.dumps("0.0.0.0"),
    "vr_udp_stream_port": "{int(udp_stream_port)}",
}}
for key, value in settings.items():
    line = f"{{key}}: {{value}}"
    if re.search(rf"^{{key}}\\s*:", s, flags=re.MULTILINE):
        s = re.sub(rf"^{{key}}\\s*:.*$", line, s, flags=re.MULTILINE)
    else:
        s += "\\n" + line + "\\n"
p.write_text(s)
print("patched VR ZMQ addresses to {pc_ip}; transport=udp_stream port={int(udp_stream_port)}")
"""


def patch_robot_command(config: AppConfig) -> str:
    return (
        f"cd {quote(config.remote_root)} && "
        f"python3 - <<'PY'\n{robot_patch_script(config.pc_ip, config.vr_udp_stream_port)}PY"
    )


def robot_deploy_command(config: AppConfig, debug_logs: bool) -> str:
    log_setup = ""
    log_arg = ""
    if debug_logs:
        remote_project_root = str(Path(config.remote_root.rstrip("/")).parent)
        remote_log_dir = remote_project_root.rstrip("/") + "/data/logs"
        log_setup = (
            f"mkdir -p {quote(remote_log_dir)} && "
            f"LOG={quote(remote_log_dir)}/deploy_debug_$(date +%Y%m%d_%H%M%S).log && "
        )
        log_arg = " --debug-log-file \"$LOG\""
    return (
        f"cd {quote(config.remote_root)} && "
        f"python3 - <<'PY'\n{robot_patch_script(config.pc_ip, config.vr_udp_stream_port)}PY\n"
        + log_setup +
        f"test -x {quote(config.robot_python)} || "
        f"(echo '[deploy] missing robot python: {quote(config.robot_python)}' && exit 127) && "
        f"unset CYCLONEDDS_URI && "
        "export PYTHONUNBUFFERED=1 && "
        f"{robot_python_command(config)} -u src/deploy.py "
        f"--net {quote(config.robot_net)} --real "
        "--enable-dex3-hands --dex3-teleop-hands "
        f"--policy-path {quote(config.policy_path)} "
        "--qerr-limit 0.35 "
        "--waist-qerr-limit 0.25 "
        "--waist-pitch-qerr-limit 0.18 "
        f"--pico-telemetry-host {quote(config.pico_telemetry_host)} "
        "--pico-telemetry-port 13601 "
        "--pico-telemetry-rate-hz 5 "
        "--temperature-audio-warning-threshold-c 100 "
        "--temperature-audio-warning-clear-c 95 "
        "--temperature-audio-warning-cooldown-s 10 "
        + log_arg
    )


def local_sim2sim_command() -> str:
    return "source $HOME/.local/bin/env && uv run src/sim2sim.py --xml_path assets/g1/g1.xml --show-reference-ghost"
