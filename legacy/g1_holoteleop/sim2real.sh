## Camera ------------------------------------------------------
# 启动摄像头

ssh -tt unitree-wbcd-magic '
cd /mnt/nexus/workspace/project/HoloTeleop/sim2real/camera_streamer

CAMERA_DEVICE=$(readlink -f /dev/v4l/by-id/*DJI*video-index0) \
CAMERA_INPUT_FORMAT=H264 \
CAMERA_TRANSPORT=TCP \
CAMERA_WIDTH=720 \
CAMERA_HEIGHT=1280 \
CAMERA_FPS=30 \
CAMERA_CONTROL_PORT=13579 \
RECORD_CONTROL_PORT=13600 \
bash scripts/start_camera_streamer.sh
'

## VR --------------------------------------------------------
# sim2real

#1. 电脑端：启动 teleop bridge

conda activate gmr
cd /home/velix/project/HoloTeleop/sim2real/teleop
mkdir -p /home/velix/project/HoloTeleop/data/logs

DEBUG_LOG_FILE=/home/velix/project/HoloTeleop/data/logs/teleop_debug_$(date +%Y%m%d_%H%M%S).log \
DEBUG_RETARGET_STALL_WARN_MS=500 \
DEBUG_RAW_FRESH_MS=200 \
DEBUG_REPLY_PROCESS_WARN_MS=50 \
DEBUG_PICO_CALLBACK_WARN_MS=100 \
DEBUG_PICO_HEALTH_INTERVAL_S=3 \
LOG_INTERVAL_S=3 \
DEBUG_WARNING_INTERVAL_S=3 \
UDP_STREAM_HOST=192.168.1.103 \
UDP_STREAM_PORT=28704 \
UDP_STREAM_FPS=50 \
UDP_STREAM_QOS=1 \
bash teleop_pose_50hz.sh

#2. 电脑端：patch 机器人 VR 地址
ssh unitree-wbcd-magic '
cd /mnt/nexus/workspace/project/HoloTeleop/sim2real
python3 - <<'"'"'PY'"'"'
import json
import re
from pathlib import Path

pc_ip = "192.168.1.104"
udp_port = 28704
p = Path("config/tracking.yaml")

s = p.read_text()
for port in ("28701", "28702", "28703"):
    s = s.replace(f"tcp://127.0.0.1:{port}", f"tcp://{pc_ip}:{port}")
    s = re.sub(rf"tcp://[0-9.]+:{port}", f"tcp://{pc_ip}:{port}", s)
settings = {
    "vr_transport": json.dumps("udp_stream"),
    "vr_udp_stream_bind_addr": json.dumps("0.0.0.0"),
    "vr_udp_stream_port": str(udp_port),
}
for key, value in settings.items():
    line = f"{key}: {value}"
    if re.search(rf"^{key}\\s*:", s, flags=re.MULTILINE):
        s = re.sub(rf"^{key}\\s*:.*$", line, s, flags=re.MULTILINE)
    else:
        s += "\n" + line + "\n"
p.write_text(s)
print(f"patched VR ZMQ addresses to {pc_ip}; transport=udp_stream port={udp_port}")
PY
'

#3. 机器人端：启动 deploy

ssh -tt unitree-wbcd-magic '
cd /mnt/nexus/workspace/project/HoloTeleop/sim2real
unset CYCLONEDDS_URI
export PYTHONUNBUFFERED=1
mkdir -p /mnt/nexus/workspace/project/HoloTeleop/data/logs
LOG=/mnt/nexus/workspace/project/HoloTeleop/data/logs/deploy_debug_$(date +%Y%m%d_%H%M%S).log
PICO_TELEMETRY_HOST=${PICO_TELEMETRY_HOST:-192.168.1.100}

.venv/bin/python -u src/deploy.py \
    --net eth0 \
    --real \
    --enable-dex3-hands \
    --dex3-teleop-hands \
    --policy-path assets/ckpts/G1TRACKING-06-07_11-15/policy.onnx \
    --disable-qerr-limit \
    --pico-telemetry-host "$PICO_TELEMETRY_HOST" \
    --pico-telemetry-port 13601 \
    --pico-telemetry-rate-hz 5 \
    --temperature-audio-warning-threshold-c 100 \
    --temperature-audio-warning-clear-c 95 \
    --temperature-audio-warning-cooldown-s 10 \
    --debug-log-interval-s 3 \
    --control-health-log-interval-s 2 \
    --service-health-log-interval-s 5 \
    --debug-log-file "$LOG"
'



## Motion --------------------------------------------------------
# sim2real

# 1. 机器人端启动 deploy

ssh -tt unitree-wbcd-magic '
cd /mnt/nexus/workspace/project/HoloTeleop/sim2real
unset CYCLONEDDS_URI
export PYTHONUNBUFFERED=1

.venv/bin/python -u src/deploy.py \
    --net eth0 \
    --real \
    --motion-source udp \
    --policy-path assets/ckpts/G1TRACKING-03-16_14-15_0315.2/policy.onnx \
    --temperature-audio-warning-threshold-c 100 \
    --temperature-audio-warning-clear-c 95 \
    --temperature-audio-warning-cooldown-s 10
'

# 2. 按 G1 遥控器

# Start  -> 进入 init/default 准备
# A      -> 进入 tracking policy

# 看到类似：

# Initial policy: tracking
# Append motion 'default'
# Running high level...

# 说明已经进入 default。

# 3. 另开终端发送动作

ssh unitree-wbcd-magic '
cd /mnt/nexus/workspace/project/HoloTeleop/sim2real

.venv/bin/python src/motion_select.py \
    assets/data/corl/A_person_sees_a_floor_sticker_that_needs_closer_inspection/gen_fsq_0022_A_person_sees_a_floor_sticker_that_needs_closer_inspection.npz
'

## Tiny2 --------------------------------------------------------
# sim2real

# 0. 机器人端：启动 OBSBOT Tiny2 实时服务

ssh unitree-wbcd-magic '
cd /mnt/nexus/workspace/project/obsbot_tiny2_linux_control
bash scripts/start_realtime_service.sh
'

# 0.1 机器人端：启动 Tiny2 UDP head-follow bridge
# 这个终端要保持运行

ssh -tt unitree-wbcd-magic '
cd /mnt/nexus/workspace/project/obsbot_tiny2_linux_control
PYTHONPATH=python python3 scripts/tiny2_udp_head_bridge.py \
    --listen-host 0.0.0.0 \
    --listen-port 29900 \
    --tiny2-host 127.0.0.1 \
    --tiny2-port 29876 \
    --rate 30 \
    --alpha 1.0 \
    --dead-zone 0.0 \
    --stale-timeout 0.2 \
    --pitch-gain -1.0
'

# stop
ssh unitree-wbcd-magic '
cd /mnt/nexus/workspace/project/obsbot_tiny2_linux_control
bash scripts/stop_realtime_service.sh
'
