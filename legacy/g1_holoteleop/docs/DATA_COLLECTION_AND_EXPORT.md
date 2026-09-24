# Data Collection And Export

This document records the current HoloTeleop data workflow.

## Directories

```text
/home/velix/project/HoloTeleop/data/pico_records
/home/velix/project/HoloTeleop/data/gmr_records
/home/velix/project/HoloTeleop/data/training_raw
/home/velix/project/HoloTeleop/data/logs
```

- `pico_records`: raw PICO body/controller records.
- `gmr_records`: online retargeted GMR/MT records.
- `training_raw`: 50 Hz motion npz files converted from `gmr_records`.
- `logs`: teleop and deploy debug logs.

## Record PICO And GMR Data

```bash
conda activate gmr
cd /home/velix/project/HoloTeleop/sim2real/teleop

PICO_RECORD_OUTPUT_DIR=/home/velix/project/HoloTeleop/data/pico_records bash teleop_pose_50hz.sh
```

Debug logs are optional. Use this only when diagnosing retarget delay or dropped frames:

```bash
mkdir -p /home/velix/project/HoloTeleop/data/logs
PICO_RECORD_OUTPUT_DIR=/home/velix/project/HoloTeleop/data/pico_records \
DEBUG_LOG_FILE=/home/velix/project/HoloTeleop/data/logs/teleop_debug_$(date +%Y%m%d_%H%M%S).log \
bash teleop_pose_50hz.sh
```

Controls:

```text
Right axis click: start recording
Left axis click: stop and save
Keyboard r: start recording
Keyboard p: stop and save
Keyboard q: save and exit
```

The recorder writes paired files:

```text
pico_records/pico_raw_*.npz
gmr_records/gmr_mt_*.npz
```

## Replay Records

List records:

```bash
cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
uv run teleop/replay_pico_gmr_mujoco.py --mode both --list-records
```

Replay raw PICO and GMR together:

```bash
uv run teleop/replay_pico_gmr_mujoco.py --mode both --index -1 --loop
```

Replay only GMR/MT:

```bash
uv run teleop/replay_pico_gmr_mujoco.py --mode gmr --index -1 --loop
```

Replay a specific file:

```bash
uv run teleop/replay_pico_gmr_mujoco.py \
  --mode gmr \
  --gmr-record /home/velix/project/HoloTeleop/data/gmr_records/gmr_mt_YYYYMMDD_HHMMSS_seg000000.npz \
  --loop
```

## Export To Training Raw

Continue exporting without overwriting existing files:

```bash
cd /home/velix/project/HoloTeleop/sim2real
.venv/bin/python ../training/scripts/data_process/convert_teleop_gmr_to_motion_npz.py
```

This converts:

```text
data/gmr_records/gmr_mt_*.npz
```

to:

```text
data/training_raw/teleop_*.npz
```

The converter skips existing outputs by default. Use `--overwrite` only when intentionally regenerating all files.

The converted `training_raw` files are resampled to `50 Hz`.

## Build Training Memmap

```bash
cd /home/velix/project/HoloTeleop/training
UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/data_process/generate_dataset.py \
  --dataset-root ../data/training_raw \
  --mem-path dataset/real_vr
```

## Current Machine (Jensen) Quick Workflow

This is the workflow when working with pre-packaged training_raw zip files
on Jensen.

### Paths

| Purpose          | Path                                                                 |
| ---------------- | -------------------------------------------------------------------- |
| zip files        | `/mnt/data/cpfs/Jensen/dataset/pico_vr/training_raw_*.zip`           |
| npz staging      | `/mnt/data/cpfs/Jensen/dataset/pico_vr/npz/`                         |
| output memmap    | `/mnt/data/cpfs/Jensen/project/teleop/dataset/pico_vr/`              |
| generate script  | `/mnt/data/cpfs/Jensen/project/teleop/HoloTeleop/training/`          |

### One-Shot: Extract And Build

```bash
# 1. Clean and extract new zip (must flatten training_raw/ subfolder)
rm -f /mnt/data/cpfs/Jensen/dataset/pico_vr/npz/*
rm -rf /mnt/data/cpfs/Jensen/dataset/pico_vr/npz/training_raw

unzip /mnt/data/cpfs/Jensen/dataset/pico_vr/training_raw_YYYYMMDD_HHMMSS.zip \
  -d /mnt/data/cpfs/Jensen/dataset/pico_vr/npz

# 2. Flatten (zip contains a training_raw/ subfolder)
mv /mnt/data/cpfs/Jensen/dataset/pico_vr/npz/training_raw/* \
   /mnt/data/cpfs/Jensen/dataset/pico_vr/npz/
rmdir /mnt/data/cpfs/Jensen/dataset/pico_vr/npz/training_raw

# 3. Clean old memmap and rebuild
rm -rf /mnt/data/cpfs/Jensen/project/teleop/dataset/pico_vr/*

cd /mnt/data/cpfs/Jensen/project/teleop/HoloTeleop/training
uv run python scripts/data_process/generate_dataset.py \
  --dataset-root /mnt/data/cpfs/Jensen/dataset/pico_vr/npz \
  --mem-path /mnt/data/cpfs/Jensen/project/teleop/dataset/pico_vr
```

### Quick Check

```bash
python3 -c "
import numpy as np, glob
fs = sorted(glob.glob('/mnt/data/cpfs/Jensen/dataset/pico_vr/npz/*.npz'))
frames = sum(len(np.load(f)['root_pos']) for f in fs)
fps = int(np.load(fs[0])['fps'])
print(f'{len(fs)} files, {frames} frames, {frames/fps/3600:.2f} h')
"
```

## Current Dataset Snapshot

After the latest export:

```text
pico_records: 189 files, 442.40 MB, 661,073 frames, 124.27 min / 2.07 h, avg 88.66 Hz
gmr_records: 189 files, 248.79 MB, 612,000 frames, 124.32 min / 2.07 h, avg 82.05 Hz
training_raw: 189 files, 541.08 MB, 372,944 frames, 124.31 min / 2.07 h, 50 Hz
```

## VLA Session Conversion

For real robot sessions with video/state/action:

```text
session_xxx/
  video.h264
  video_timestamps.csv
  reference.npz
  state.npz
  action.npz
  metadata.yaml
```

Convert reference/state to motion-select-compatible npz files:

```bash
cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env

SESSION_DIR=/path/to/session_xxx
uv run src/session_to_motion_npz.py "$SESSION_DIR" --source both
```

Outputs:

```text
session_xxx/reference_motion.npz
session_xxx/state_motion.npz
```
