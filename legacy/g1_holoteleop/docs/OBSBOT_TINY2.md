# OBSBOT Tiny2 Head Follow

This document describes the recommended HoloTeleop integration for the OBSBOT Tiny2 gimbal camera on the robot.

## Architecture

Use the robot to control the USB gimbal locally, and use the PC only to send lightweight head-pose commands:

```text
PICO / XRoboToolkit on PC
  -> HoloTeleop teleop bridge
  -> UDP yaw/pitch packets
  -> robot tiny2_udp_head_bridge.py
  -> robot Tiny2 realtime service
  -> OBSBOT Tiny2 USB gimbal
```

This avoids running XR/GMR on the robot and avoids controlling the USB camera directly from the PC.

## Robot Side

Start the Tiny2 realtime service on the robot:

```bash
ssh unitree-wbcd-magic
cd /mnt/nexus/workspace/project/obsbot_tiny2_linux_control
bash scripts/start_realtime_service.sh
```

Check logs if needed:

```bash
cd /mnt/nexus/workspace/project/obsbot_tiny2_linux_control
bash scripts/logs_realtime_service.sh
```

Start the UDP head-pose bridge on the robot:

```bash
cd /mnt/nexus/workspace/project/obsbot_tiny2_linux_control
PYTHONPATH=python python3 scripts/tiny2_udp_head_bridge.py \
  --listen-host 0.0.0.0 \
  --listen-port 29900 \
  --tiny2-host 127.0.0.1 \
  --tiny2-port 29876 \
  --rate 30 \
  --alpha 1.0 \
  --dead-zone 0.0 \
  --pitch-gain -1.0
```

The `--pitch-gain -1.0` matches the headset pitch convention used by the XR head-follow reference.
The `--alpha 1.0 --dead-zone 0.0` settings disable software smoothing/dead-zone in the robot UDP bridge.

Stop the Tiny2 service:

```bash
cd /mnt/nexus/workspace/project/obsbot_tiny2_linux_control
bash scripts/stop_realtime_service.sh
```

## PC Side

Start the HoloTeleop PICO bridge with Tiny2 head-pose publishing enabled.

For the `unitree-wbcd-magic` network, the robot is currently reachable as `192.168.1.103`:

```bash
conda activate gmr
cd /home/velix/project/HoloTeleop/sim2real/teleop
TINY2_HEAD_FOLLOW_HOST=192.168.1.103 bash teleop_pose_50hz.sh
```

Optional tuning:

```bash
TINY2_HEAD_FOLLOW_HOST=192.168.1.103 \
TINY2_HEAD_FOLLOW_PORT=29900 \
TINY2_HEAD_FOLLOW_RATE_HZ=30 \
TINY2_HEAD_FOLLOW_YAW_GAIN=1.0 \
TINY2_HEAD_FOLLOW_PITCH_GAIN=1.0 \
TINY2_HEAD_FORWARD_AXIS=z \
bash teleop_pose_50hz.sh
```

If the gimbal moves in the wrong pitch direction, prefer changing `--pitch-gain` on the robot bridge first.

## Notes

- The PC sends raw headset yaw/pitch relative to the XR pelvis.
- The robot bridge applies low-pass filtering, dead-zone, limits, and final pitch/yaw gains.
- The Tiny2 AI mode is disabled by the service/bridge before manual control so auto-tracking does not fight the commanded pose.
- This path is independent of sim2sim/deploy. It can run while HoloTeleop teleop, sim2sim, or real deploy are running.
