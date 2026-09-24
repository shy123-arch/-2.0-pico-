# HoloTeleop Control App

Small Qt control panel for syncing `sim2real` code and launching teleop/deploy commands.
The UI is split into tabs:

- `Run`: start/stop local teleop and robot deploy
- `Sync`: rsync code between PC and robot
- `Settings`: paths, IP, policy path, and deploy mode
- `Guide`: short operating checklist

The bottom log area has separate tabs for `Teleop`, `Deploy`, `Patch`, `Sync`,
`Sim2Sim`, and `SSH`, plus an `All` tab for the combined timeline.

Install a Qt binding if needed:

```bash
cd /home/velix/project/HoloTeleop/app
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install PySide6
```

If Qt reports that the `xcb` platform plugin cannot be initialized, install the missing system XCB package:

```bash
sudo apt install libxcb-cursor0
```

Run:

```bash
cd /home/velix/project/HoloTeleop/app
bash run_holoteleop_control.sh
```

The app can:

- sync PC -> robot with `rsync`, excluding `.venv`, `.git`, caches, and teleop recordings
- sync robot -> PC with the same excludes
- start local PICO teleop bridge
- detect local ZMQ port conflicts before teleop starts
- clean stale local teleop processes if ports `28701/28702/28703` are still occupied
- launch teleop with the configured `gmr` Python executable instead of inheriting the caller shell environment
- patch robot `config/tracking.yaml` VR ZMQ addresses to the PC IP
- start robot-side `deploy.py` over SSH

Default paths:

- local: `/home/velix/project/HoloTeleop/sim2real`
- robot: `unitree-wbcd-magic:/mnt/nexus/workspace/project/HoloTeleop/sim2real`
- PC IP for VR ZMQ: `192.168.31.244`
- PICO telemetry IP: `192.168.31.85`
