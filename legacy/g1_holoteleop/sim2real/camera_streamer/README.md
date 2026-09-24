# HoloTeleop Camera Streamer

Standalone low-latency camera streamer for robot-mounted USB cameras.

Design:

- V4L2 H264 passthrough when the camera supports H264.
- GStreamer `appsink max-buffers=1 drop=true sync=false`.
- Capture callback only copies the newest frame and returns.
- A sender thread transmits only the latest frame to avoid pipeline backpressure.
- Session recording is controlled by UDP `127.0.0.1:13600`.
- Recording waits for SPS/PPS + IDR so `video.h264` starts decodable.

Start on robot:

```bash
cd /mnt/nexus/workspace/project/HoloTeleop/sim2real/camera_streamer

CAMERA_DEVICE=$(readlink -f /dev/v4l/by-id/*DJI*video-index0) \
CAMERA_INPUT_FORMAT=H264 \
CAMERA_TRANSPORT=TCP \
CAMERA_WIDTH=720 \
CAMERA_HEIGHT=1280 \
CAMERA_FPS=30 \
CAMERA_BITRATE=1500000 \
CAMERA_CONTROL_PORT=13579 \
RECORD_CONTROL_PORT=13600 \
bash scripts/start_camera_streamer.sh
```

The control protocol is compatible with the existing PICO client `OPEN_CAMERA`
message. The PICO app connects to `robot_ip:13579`, then provides its receive
IP/port in the `OPEN_CAMERA` payload.

Set `CAMERA_TRANSPORT=UDP` to send video frames over UDP. Control still uses TCP
port `13579`. UDP mode fragments each H264 frame by default because keyframes can
be larger than a single UDP datagram.

Fragment packet format:

```text
0..3    magic: "HTVF"
4       version: 1
5       flags: 0
6..7    header_size: 24, big-endian
8..11   frame_id, big-endian
12..13  frag_id, big-endian, 0-based
14..15  frag_count, big-endian
16..19  frame_size, big-endian
20..21  payload_size, big-endian
22..23  reserved
24..    H264 frame fragment bytes
```

PICO should only reassemble the latest `frame_id`; stale or incomplete frames
should be dropped.
