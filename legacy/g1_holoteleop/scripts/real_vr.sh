#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOLO_ROOT:-/media/william/play/molospace/HoloTeleop-deploy/HoloTeleop}"
LOCAL_SIM2REAL="${ROOT}/sim2real"
REMOTE_HOST="${REMOTE_HOST:-unitree@172.18.26.133}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/unitree/HoloTeleop/sim2real}"

PC_IP="${PC_IP:-172.18.26.64}"
ROBOT_IP="${ROBOT_IP:-172.18.26.133}"
PICO_IP="${PICO_IP:-172.18.26.64}"
UDP_STREAM_PORT="${UDP_STREAM_PORT:-28704}"
POLICY_PATH="${POLICY_PATH:-assets/ckpts/G1TRACKING-06-07_11-15/policy.onnx}"
ROBOT_NET="${ROBOT_NET:-eth0}"
ROBOT_PYTHON="${ROBOT_PYTHON:-/home/unitree/miniforge3/envs/holo310/bin/python}"
ROBOT_LD_LIBRARY_PATH="${ROBOT_LD_LIBRARY_PATH:-/home/unitree/miniforge3/envs/holo310/lib:/home/unitree/workspace/cyclonedds/install/lib}"
QERR_LIMIT="${QERR_LIMIT:-0.50}"
WAIST_QERR_LIMIT="${WAIST_QERR_LIMIT:-0.25}"
WAIST_PITCH_QERR_LIMIT="${WAIST_PITCH_QERR_LIMIT:-0.18}"

CAMERA_TRANSPORT="${CAMERA_TRANSPORT:-TCP}"
CAMERA_WIDTH="${CAMERA_WIDTH:-720}"
CAMERA_HEIGHT="${CAMERA_HEIGHT:-1280}"
CAMERA_FPS="${CAMERA_FPS:-25}"
CAMERA_BITRATE="${CAMERA_BITRATE:-1500000}"
CAMERA_TRANSCODE="${CAMERA_TRANSCODE:-1}"
CAMERA_OUTPUT_WIDTH="${CAMERA_OUTPUT_WIDTH:-540}"
CAMERA_OUTPUT_HEIGHT="${CAMERA_OUTPUT_HEIGHT:-960}"

TELEOP_PYTHON="${TELEOP_PYTHON:-/home/william/miniconda3/envs/gmr/bin/python}"
TELEOP_PATH="${LOCAL_SIM2REAL}/teleop"

usage() {
  cat <<EOF
Usage: $(basename "$0") <command>

Commands:
  interactive
            Open an interactive prompt. This is the default when no command is given.
  start     Start camera, teleop, patch robot config, and deploy in background.
  camera    Start only robot camera streamer in background.
  teleop    Start only local teleop bridge in background.
  patch     Patch robot tracking.yaml for PC=${PC_IP}.
  deploy    Start only robot deploy in background.
  stop      Stop camera, teleop, and deploy.
  status    Show related processes and ports.
  logs      Show last camera/deploy startup output.

Overrides:
  PC_IP=${PC_IP} ROBOT_IP=${ROBOT_IP} PICO_IP=${PICO_IP}
  POLICY_PATH=${POLICY_PATH}
  ROBOT_PYTHON=${ROBOT_PYTHON}
  ROBOT_LD_LIBRARY_PATH=${ROBOT_LD_LIBRARY_PATH}
  CAMERA_TRANSPORT=${CAMERA_TRANSPORT}
  CAMERA_WIDTH=${CAMERA_WIDTH} CAMERA_HEIGHT=${CAMERA_HEIGHT} CAMERA_FPS=${CAMERA_FPS}
  CAMERA_BITRATE=${CAMERA_BITRATE}
  CAMERA_TRANSCODE=${CAMERA_TRANSCODE}
  CAMERA_OUTPUT_WIDTH=${CAMERA_OUTPUT_WIDTH} CAMERA_OUTPUT_HEIGHT=${CAMERA_OUTPUT_HEIGHT}
EOF
}

ssh_robot() {
  ssh -o ExitOnForwardFailure=no -o LogLevel=ERROR "${REMOTE_HOST}" "$@"
}

stop_local_teleop() {
  pkill -TERM -f '[x]robot_teleop_to_pose_zmq_server.py|[t]eleop_pose_50hz.sh' 2>/dev/null || true
  sleep 0.3
  pkill -KILL -f '[x]robot_teleop_to_pose_zmq_server.py|[t]eleop_pose_50hz.sh' 2>/dev/null || true
}

stop_robot() {
  ssh_robot "pkill -INT -x holoteleop_came 2>/dev/null || true
pkill -INT -f '[h]oloteleop_camera_streamer|[s]tart_camera_streamer.sh|[s]rc/deploy.py' 2>/dev/null || true
sleep 1.0
pkill -TERM -x holoteleop_came 2>/dev/null || true
pkill -TERM -f '[h]oloteleop_camera_streamer|[s]tart_camera_streamer.sh|[s]rc/deploy.py' 2>/dev/null || true
sleep 0.8
pkill -KILL -x holoteleop_came 2>/dev/null || true
pkill -KILL -f '[h]oloteleop_camera_streamer|[s]tart_camera_streamer.sh|[s]rc/deploy.py' 2>/dev/null || true
for i in 1 2 3 4 5; do
  pgrep -af '[h]oloteleop_camera_streamer|[h]oloteleop_came|[s]tart_camera_streamer.sh|[s]rc/deploy.py' >/dev/null || break
  sleep 0.2
done"
}

patch_robot() {
  ssh_robot "cd '${REMOTE_ROOT}' && PC_IP='${PC_IP}' UDP_PORT='${UDP_STREAM_PORT}' python3 - <<'PY'
import json
import os
import re
from pathlib import Path

pc_ip = os.environ['PC_IP']
udp_port = int(os.environ['UDP_PORT'])
p = Path('config/tracking.yaml')
s = p.read_text()
for port in ('28701', '28702', '28703'):
    s = s.replace(f'tcp://127.0.0.1:{port}', f'tcp://{pc_ip}:{port}')
    s = re.sub(rf'tcp://[0-9.]+:{port}', f'tcp://{pc_ip}:{port}', s)
settings = {
    'vr_transport': json.dumps('udp_stream'),
    'vr_udp_stream_bind_addr': json.dumps('0.0.0.0'),
    'vr_udp_stream_port': str(udp_port),
}
for key, value in settings.items():
    line = f'{key}: {value}'
    if re.search(rf'^{key}\\s*:', s, flags=re.MULTILINE):
        s = re.sub(rf'^{key}\\s*:.*$', line, s, flags=re.MULTILINE)
    else:
        s += '\\n' + line + '\\n'
p.write_text(s)
print(f'patched VR addresses to PC={pc_ip}; transport=udp_stream port={udp_port}')
PY"
}

start_camera() {
  ssh_robot "cd '${REMOTE_ROOT}/camera_streamer' || exit 1
pkill -TERM -x holoteleop_came 2>/dev/null || true
pkill -TERM -f '[h]oloteleop_camera_streamer|[s]tart_camera_streamer.sh' 2>/dev/null || true
sleep 0.5
pkill -KILL -x holoteleop_came 2>/dev/null || true
pkill -KILL -f '[h]oloteleop_camera_streamer|[s]tart_camera_streamer.sh' 2>/dev/null || true
for i in 1 2 3 4 5; do
  if ! pgrep -af '[h]oloteleop_camera_streamer|[h]oloteleop_came|[s]tart_camera_streamer.sh' >/dev/null && ! ss -ltn 2>/dev/null | grep -q ':13579 '; then
    break
  fi
  sleep 0.2
done
"
  ssh_robot "cd '${REMOTE_ROOT}/camera_streamer' || exit 1
nohup bash -lc '
rm -f /tmp/holoteleop_camera.last.log
CAMERA_DEVICE=\$(readlink -f /dev/v4l/by-id/*DJI*video-index0) \
CAMERA_INPUT_FORMAT=H264 \
CAMERA_TRANSPORT=${CAMERA_TRANSPORT} \
CAMERA_WIDTH=${CAMERA_WIDTH} \
CAMERA_HEIGHT=${CAMERA_HEIGHT} \
CAMERA_FPS=${CAMERA_FPS} \
CAMERA_BITRATE=${CAMERA_BITRATE} \
CAMERA_TRANSCODE=${CAMERA_TRANSCODE} \
CAMERA_OUTPUT_WIDTH=${CAMERA_OUTPUT_WIDTH} \
CAMERA_OUTPUT_HEIGHT=${CAMERA_OUTPUT_HEIGHT} \
CAMERA_OUTPUT_FPS=${CAMERA_FPS} \
CAMERA_IP_TOS=32 \
CAMERA_SOCKET_PRIORITY=0 \
CAMERA_CONTROL_PORT=13579 \
RECORD_CONTROL_PORT=13600 \
bash scripts/start_camera_streamer.sh
' >/tmp/holoteleop_camera.last.log 2>&1 &"
  sleep 0.8
  if ssh_robot "pgrep -af '[h]oloteleop_camera_streamer|[h]oloteleop_came' >/dev/null && ss -ltn 2>/dev/null | grep -q ':13579 '"; then
    echo "camera started on ${REMOTE_HOST} (${ROBOT_IP})"
  else
    echo "camera failed to stay running on ${REMOTE_HOST}; run 'logs' for details"
    return 1
  fi
}

start_teleop() {
  stop_local_teleop
  mkdir -p "${ROOT}/data/logs"
  local python_dir conda_prefix
  python_dir="$(dirname "${TELEOP_PYTHON}")"
  conda_prefix="$(dirname "${python_dir}")"
  (
    cd "${TELEOP_PATH}"
    nohup bash -lc "
unset VIRTUAL_ENV PYTHONHOME PYTHONPATH
export CONDA_PREFIX='${conda_prefix}'
export PATH='${python_dir}':\"\$PATH\"
UDP_STREAM_HOST='${ROBOT_IP}' \
UDP_STREAM_PORT='${UDP_STREAM_PORT}' \
UDP_STREAM_FPS=50 \
UDP_STREAM_QOS=1 \
exec bash teleop_pose_50hz.sh
" >/dev/null 2>&1 &
  )
  echo "teleop started locally -> udp://${ROBOT_IP}:${UDP_STREAM_PORT}"
}

start_deploy() {
  patch_robot
  ssh_robot "pkill -INT -f '[s]rc/deploy.py' 2>/dev/null || true
sleep 0.5
pkill -TERM -f '[s]rc/deploy.py' 2>/dev/null || true
sleep 0.3
pkill -KILL -f '[s]rc/deploy.py' 2>/dev/null || true"
  ssh_robot "cd '${REMOTE_ROOT}' || exit 1
nohup env \
ROBOT_PYTHON='${ROBOT_PYTHON}' \
ROBOT_LD_LIBRARY_PATH='${ROBOT_LD_LIBRARY_PATH}' \
PICO_TELEMETRY_HOST='${PICO_IP}' \
ROBOT_NET='${ROBOT_NET}' \
POLICY_PATH='${POLICY_PATH}' \
QERR_LIMIT='${QERR_LIMIT}' \
WAIST_QERR_LIMIT='${WAIST_QERR_LIMIT}' \
WAIST_PITCH_QERR_LIMIT='${WAIST_PITCH_QERR_LIMIT}' \
bash -lc '
rm -f /tmp/holoteleop_deploy.last.log
mkdir -p /home/unitree/HoloTeleop/data/logs
LOG_FILE=/home/unitree/HoloTeleop/data/logs/deploy.last.log
unset CYCLONEDDS_URI
export PYTHONUNBUFFERED=1
export LD_LIBRARY_PATH=\"\${ROBOT_LD_LIBRARY_PATH}:\${LD_LIBRARY_PATH:-}\"
\"\${ROBOT_PYTHON}\" -u src/deploy.py \
  --net \"\${ROBOT_NET}\" \
  --real \
  --enable-dex3-hands \
  --dex3-teleop-hands \
  --policy-path \"\${POLICY_PATH}\" \
  --qerr-limit \"\${QERR_LIMIT}\" \
  --waist-qerr-limit \"\${WAIST_QERR_LIMIT}\" \
  --waist-pitch-qerr-limit \"\${WAIST_PITCH_QERR_LIMIT}\" \
  --pico-telemetry-host \"\$PICO_TELEMETRY_HOST\" \
  --pico-telemetry-port 13601 \
  --pico-telemetry-rate-hz 5 \
  --disable-temperature-audio-warning \
  --debug-log-file \"\${LOG_FILE}\"
' >/tmp/holoteleop_deploy.last.log 2>&1 &"
  echo "deploy started on ${REMOTE_HOST} with ${POLICY_PATH}"
}

status_all() {
  echo "== local teleop ports =="
  ss -ltnp 2>/dev/null | grep -E ':(28701|28702|28703)\b' || true
  pgrep -af 'xrobot_teleop_to_pose_zmq_server|teleop_pose_50hz' || true
  echo
  echo "== robot processes =="
  ssh_robot "pgrep -af 'src/deploy.py|start_camera_streamer.sh|camera_streamer|holoteleop_came' || true; echo; ss -lunp 2>/dev/null | grep ':${UDP_STREAM_PORT} ' || true; ss -tanp 2>/dev/null | grep -E ':(13579|13600)\b' || true"
}

show_logs() {
  ssh_robot "echo '== camera last log =='
tail -120 /tmp/holoteleop_camera.last.log 2>/dev/null || true
echo
echo '== deploy last log =='
tail -120 /home/unitree/HoloTeleop/data/logs/deploy.last.log 2>/dev/null || tail -120 /tmp/holoteleop_deploy.last.log 2>/dev/null || true"
}

stop_all() {
  stop_local_teleop
  stop_robot
  echo "stopped camera, teleop, deploy"
}

start_all() {
  stop_all
  start_camera
  start_teleop
  start_deploy
  status_all
}

dispatch_command() {
  local cmd="$1"
  case "${cmd}" in
  start)
    start_all
    ;;
  camera) start_camera ;;
  teleop) start_teleop ;;
  patch) patch_robot ;;
  deploy) start_deploy ;;
  stop) stop_all ;;
  status) status_all ;;
  logs) show_logs ;;
  ""|-h|--help|help) usage ;;
  quit|exit|q) return 10 ;;
  *)
    usage
    return 2
    ;;
  esac
}

interactive_loop() {
  cat <<EOF
HoloTeleop real VR control
  start   camera+teleop+deploy
  status  show processes and ports
  stop    stop camera+teleop+deploy
  camera  teleop  patch  deploy  logs
  quit
EOF
  while true; do
    printf "real_vr> "
    if ! IFS= read -r cmd; then
      echo
      break
    fi
    cmd="${cmd#"${cmd%%[![:space:]]*}"}"
    cmd="${cmd%"${cmd##*[![:space:]]}"}"
    [[ -z "${cmd}" ]] && continue
    if dispatch_command "${cmd}"; then
      :
    else
      status=$?
      [[ "${status}" == "10" ]] && break
      echo "command failed: ${cmd}"
    fi
  done
}

cmd="${1:-interactive}"
if [[ "${cmd}" == "interactive" ]]; then
  interactive_loop
else
  dispatch_command "${cmd}"
fi
