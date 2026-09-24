# Network IP Switching

This project has two commonly used network layouts: router mode and phone hotspot mode.
When switching networks, update all three endpoint IPs together.

## Current Router Mode

Use this when PC, robot, and PICO are on the router network.

```text
PC:     192.168.1.104
Robot:  192.168.1.103
PICO:   192.168.1.101
```

The active SSH alias should point to the robot:

```sshconfig
Host unitree-wbcd-magic
      HostName 192.168.1.103
      User unitree
      RemoteForward 17896 127.0.0.1:7897
```

## Hotspot Mode

Use this when running through the phone hotspot.

```text
PC:     10.201.99.71
Robot:  10.201.99.124
PICO:   10.201.99.244
```

The SSH alias should point to the hotspot robot IP:

```sshconfig
Host unitree-wbcd-magic
      HostName 10.201.99.124
      User unitree
      RemoteForward 17896 127.0.0.1:7897
```

## Files To Change

Update these local files when switching networks:

```text
/home/velix/.ssh/config
/home/velix/project/HoloTeleop/app/holoteleop_app/config.py
/home/velix/project/HoloTeleop/sim2real.sh
```

In `app/holoteleop_app/config.py`:

```python
pc_ip = "<PC_IP>"
robot_vr_host = "<ROBOT_IP>"
pico_telemetry_host = "<PICO_IP>"
```

In `sim2real.sh`:

```bash
UDP_STREAM_HOST=<ROBOT_IP>
pc_ip = "<PC_IP>"
PICO_TELEMETRY_HOST=${PICO_TELEMETRY_HOST:-<PICO_IP>}
```

`PICO_TELEMETRY_HOST` controls robot-to-PICO UDP temperature telemetry. If this is wrong,
PICO will not show temperature telemetry even though deploy logs still contain `temp_max`.

## Patch Robot Tracking Config

After changing the PC IP, patch the robot-side `tracking.yaml`:

```bash
ssh unitree-wbcd-magic '
cd /mnt/nexus/workspace/project/HoloTeleop/sim2real
python3 - <<'"'"'PY'"'"'
import json
import re
from pathlib import Path

pc_ip = "192.168.1.104"  # change this when using hotspot mode
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
    if re.search(rf"^{key}\s*:", s, flags=re.MULTILINE):
        s = re.sub(rf"^{key}\s*:.*$", line, s, flags=re.MULTILINE)
    else:
        s += "\n" + line + "\n"

p.write_text(s)
print(f"patched PC={pc_ip}; transport=udp_stream port={udp_port}")
PY
'
```

For hotspot mode, change:

```python
pc_ip = "10.201.99.71"
```

## Quick Checks

Check local IP:

```bash
ip -br addr
```

Check SSH reaches the robot:

```bash
ssh unitree-wbcd-magic 'hostname; ip -br addr | grep -E "wlan0|eth0"'
```

Check PICO is reachable:

```bash
ping -c 2 -W 1 <PICO_IP>
ssh unitree-wbcd-magic 'ping -c 2 -W 1 <PICO_IP>; ip neigh show <PICO_IP>'
```

If `ip neigh` shows `INCOMPLETE`, the device is not reachable at that IP.

Check deploy telemetry target:

```bash
ssh unitree-wbcd-magic '
LOG=$(ls -t /mnt/nexus/workspace/project/HoloTeleop/data/logs/deploy_debug_*.log | head -1)
grep -m1 PicoTelemetry "$LOG"
'
```

Expected in router mode:

```text
[PicoTelemetry] UDP enabled -> 192.168.1.101:13601 @ 5.0Hz
```

Expected in hotspot mode:

```text
[PicoTelemetry] UDP enabled -> 10.201.99.244:13601 @ 5.0Hz
```

## Notes

- Restart deploy after changing `PICO_TELEMETRY_HOST`; a running deploy process keeps the old telemetry target.
- Restart local teleop after changing `UDP_STREAM_HOST`; a running teleop process keeps sending to the old robot IP.
- Camera video uses PICO's camera control connection and is separate from temperature telemetry.
- Router-mode logs currently show PICO input is mostly stable, but PC/router to robot can still have occasional large control packet gaps.
