#!/usr/bin/env bash
set -euo pipefail

HOLO_ROOT="${HOLO_ROOT:-/media/william/play/molospace/HoloTeleop-deploy/HoloTeleop}"
MOLMO_ROOT="${MOLMO_ROOT:-/media/william/play/molospace/molmospaces-teleop/molmospaces-teleop}"
REMOTE_HOST="${REMOTE_HOST:-unitree@172.18.26.133}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/unitree/HoloTeleop/sim2real}"
ROBOT_IP="${ROBOT_IP:-172.18.26.133}"
PC_IP="${PC_IP:-172.18.26.64}"
ROBOT_NET="${ROBOT_NET:-eth0}"

BRIDGE_PYTHON="${BRIDGE_PYTHON:-/home/william/miniconda3/envs/gmr/bin/python}"
ACTUAL_HUMAN_HEIGHT="${ACTUAL_HUMAN_HEIGHT:-1.71}"
LOOKBACK_MS="${LOOKBACK_MS:-25}"
RETARGET_FPS="${RETARGET_FPS:-60}"
GMR_VISUALIZE="${GMR_VISUALIZE:-1}"
UDP_STREAM_PORT="${UDP_STREAM_PORT:-28704}"
UDP_STREAM_FPS="${UDP_STREAM_FPS:-50}"
UDP_STREAM_QOS="${UDP_STREAM_QOS:-1}"

ROBOT_PYTHON="${ROBOT_PYTHON:-/home/unitree/miniforge3/envs/holo310/bin/python}"
ROBOT_LD_LIBRARY_PATH="${ROBOT_LD_LIBRARY_PATH:-/home/unitree/miniforge3/envs/holo310/lib:/home/unitree/workspace/cyclonedds/install/lib}"
POLICY_PATH="${POLICY_PATH:-assets/ckpts/G1TRACKING-06-07_11-15/policy.onnx}"
QERR_LIMIT="${QERR_LIMIT:-0.50}"
WAIST_QERR_LIMIT="${WAIST_QERR_LIMIT:-0.25}"
WAIST_PITCH_QERR_LIMIT="${WAIST_PITCH_QERR_LIMIT:-0.18}"

usage() {
  cat <<EOF
Usage: $(basename "$0") <bridge|deploy|patch|stop|status|logs>

Molmo baseline profile:
  bridge  Start the PICO/GMR bridge from the MolmoSpaces repo that passed simulation.
  deploy  Start Holo sim2real deploy on G1 with the selected conservative policy.
  patch   Patch robot tracking.yaml for this PC and UDP stream port.
  stop    Stop local bridge and robot deploy.
  status  Show local bridge and robot deploy status.
  logs    Show robot deploy last log.

Overrides:
  ACTUAL_HUMAN_HEIGHT=${ACTUAL_HUMAN_HEIGHT}
  LOOKBACK_MS=${LOOKBACK_MS}
  GMR_VISUALIZE=${GMR_VISUALIZE}
  POLICY_PATH=${POLICY_PATH}
  QERR_LIMIT=${QERR_LIMIT}
  WAIST_QERR_LIMIT=${WAIST_QERR_LIMIT}
  WAIST_PITCH_QERR_LIMIT=${WAIST_PITCH_QERR_LIMIT}
EOF
}

ssh_robot() {
  ssh -o ExitOnForwardFailure=no -o LogLevel=ERROR "${REMOTE_HOST}" "$@"
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
    'policy_path': json.dumps('${POLICY_PATH}'),
    'motion_source': json.dumps('vr'),
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
print(f'patched Molmo baseline: policy=${POLICY_PATH}, PC={pc_ip}, udp={udp_port}')
PY"
}

start_bridge() {
  pkill -TERM -f '[t]eleop.pose_bridge|[r]un_pose_bridge.sh|[x]robot_teleop_to_pose_zmq_server.py' 2>/dev/null || true
  sleep 0.3
  pkill -KILL -f '[t]eleop.pose_bridge|[r]un_pose_bridge.sh|[x]robot_teleop_to_pose_zmq_server.py' 2>/dev/null || true
  mkdir -p "${HOLO_ROOT}/data/logs"
  local visualize_arg=()
  if [[ "${GMR_VISUALIZE}" == "1" || "${GMR_VISUALIZE}" == "true" || "${GMR_VISUALIZE}" == "yes" ]]; then
    visualize_arg=(--visualize)
  fi
  (
    cd "${MOLMO_ROOT}"
    nohup bash -lc "
BRIDGE_PYTHON='${BRIDGE_PYTHON}' \
ACTUAL_HUMAN_HEIGHT='${ACTUAL_HUMAN_HEIGHT}' \
LOOKBACK_MS='${LOOKBACK_MS}' \
RETARGET_FPS='${RETARGET_FPS}' \
UDP_STREAM_HOST='${ROBOT_IP}' \
UDP_STREAM_PORT='${UDP_STREAM_PORT}' \
UDP_STREAM_FPS='${UDP_STREAM_FPS}' \
UDP_STREAM_QOS='${UDP_STREAM_QOS}' \
LOG_INTERVAL_S=3 \
exec bash scripts/run_pose_bridge.sh ${visualize_arg[*]}
" >"${HOLO_ROOT}/data/logs/molmo_baseline_bridge.last.log" 2>&1 &
  )
  echo "Molmo baseline bridge started -> udp://${ROBOT_IP}:${UDP_STREAM_PORT}"
  echo "GMR visualize: ${GMR_VISUALIZE}"
  echo "log: ${HOLO_ROOT}/data/logs/molmo_baseline_bridge.last.log"
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
  --disable-temperature-audio-warning \
  --debug-log-file \"\${LOG_FILE}\"
' >/tmp/holoteleop_deploy.last.log 2>&1 &"
  echo "Molmo baseline deploy started with ${POLICY_PATH}"
}

stop_all() {
  pkill -TERM -f '[t]eleop.pose_bridge|[r]un_pose_bridge.sh|[x]robot_teleop_to_pose_zmq_server.py' 2>/dev/null || true
  ssh_robot "pkill -INT -f '[s]rc/deploy.py' 2>/dev/null || true; sleep 1; pkill -TERM -f '[s]rc/deploy.py' 2>/dev/null || true"
  echo "stopped Molmo baseline bridge and robot deploy"
}

status_all() {
  echo "== local bridge =="
  pgrep -af 'teleop.pose_bridge|run_pose_bridge.sh|xrobot_teleop_to_pose_zmq_server.py' || true
  ss -lunp 2>/dev/null | grep ":${UDP_STREAM_PORT} " || true
  echo
  echo "== robot deploy =="
  ssh_robot "pgrep -af 'src/deploy.py' || true; ss -lunp 2>/dev/null | grep ':${UDP_STREAM_PORT} ' || true"
}

show_logs() {
  echo "== local Molmo bridge =="
  tail -120 "${HOLO_ROOT}/data/logs/molmo_baseline_bridge.last.log" 2>/dev/null || true
  echo
  echo "== robot deploy =="
  ssh_robot "tail -120 /home/unitree/HoloTeleop/data/logs/deploy.last.log 2>/dev/null || tail -120 /tmp/holoteleop_deploy.last.log 2>/dev/null || true"
}

case "${1:-help}" in
  bridge) start_bridge ;;
  deploy) start_deploy ;;
  patch) patch_robot ;;
  stop) stop_all ;;
  status) status_all ;;
  logs) show_logs ;;
  help|-h|--help|"") usage ;;
  *)
    usage
    exit 2
    ;;
esac
