# HoloTeleop Setup

This workspace keeps the runnable HoloTeleop code under one root:

```text
/home/velix/project/HoloTeleop
├── app/                 # Qt helper app, independent Python venv
├── sim2real/            # deployment/sim2sim/teleop bridge code
├── training/            # policy training, evaluation, and export code
└── teleop_ws/           # external GitHub dependencies, ignored by the main repo
```

`teleop_ws/` contains independent Git repositories. They are intentionally ignored by the main HoloTeleop repository so the main repo does not vendor third-party history or generated build files.

## External Dependencies

Current local dependency repositories:

```bash
cd /home/velix/project/HoloTeleop
mkdir -p teleop_ws

git clone https://github.com/YanjieZe/GMR.git teleop_ws/GMR
git clone https://github.com/Axellwppr/XRoboToolkit-PC-Service-Pybind teleop_ws/XRoboToolkit-PC-Service-Pybind
```

Current verified commits in this machine:

```text
GMR: bb1bbe40774794fceb2a7c579a3464a28e68c844
XRoboToolkit-PC-Service-Pybind: 1f54475cfbcde7ed511c6ba3b1a2bba45bbdfe6f
```

The XRoboToolkit pybind repo also needs the native SDK header/library:

```text
teleop_ws/XRoboToolkit-PC-Service-Pybind/include/PXREARobotSDK.h
teleop_ws/XRoboToolkit-PC-Service-Pybind/include/nlohmann/
teleop_ws/XRoboToolkit-PC-Service-Pybind/lib/libPXREARobotSDK.so
```

If these are missing, rebuild/copy them following `sim2real/teleop/README.md`.

## Teleop Conda Environment

The PICO/GMR teleop bridge uses the conda env `gmr`:

```bash
conda activate gmr
```

Install/update the editable GMR path to this HoloTeleop workspace:

```bash
/home/velix/miniconda3/envs/gmr/bin/python -m pip install \
  --no-build-isolation --no-deps -e \
  /home/velix/project/HoloTeleop/teleop_ws/GMR
```

Install the XRoboToolkit Python binding from the HoloTeleop copy:

```bash
cd /home/velix/project/HoloTeleop/teleop_ws/XRoboToolkit-PC-Service-Pybind
CMAKE_PREFIX_PATH=/home/velix/miniconda3/envs/gmr \
  /home/velix/miniconda3/envs/gmr/bin/python setup.py install
```

Verify:

```bash
/home/velix/miniconda3/envs/gmr/bin/python - <<'PY'
import general_motion_retargeting
import xrobotoolkit_sdk
import zmq
print("teleop env OK")
print(general_motion_retargeting.__file__)
PY
```

Expected GMR path:

```text
/home/velix/project/HoloTeleop/teleop_ws/GMR/general_motion_retargeting/__init__.py
```

## Run Local Teleop Bridge

```bash
conda activate gmr
cd /home/velix/project/HoloTeleop/sim2real/teleop
bash teleop_pose_50hz.sh
```

## Qt App Environment

The Qt app has its own venv:

```bash
cd /home/velix/project/HoloTeleop/app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install PySide6
```

If Qt reports an `xcb` plugin error:

```bash
sudo apt install libxcb-cursor0
```

Run:

```bash
cd /home/velix/project/HoloTeleop/app
bash run_holoteleop_control.sh
```

## Training Environment

The training code is a separate `uv` project so its heavy simulation and learning dependencies do not mix with the runtime environment:

```bash
cd /home/velix/project/HoloTeleop/training
uv sync
```

Training data defaults to `training/dataset/`, or set `MEMPATH` to the shared dataset root:

```bash
cd /home/velix/project/HoloTeleop/training

MEMPATH=/path/to/dataset \
CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7 \
UV_CACHE_DIR=/tmp/uv-cache \
UV_LINK_MODE=copy \
MPLCONFIGDIR=/tmp/matplotlib \
bash train.sh
```

For a longer run, use:

```bash
cd /home/velix/project/HoloTeleop/training

MEMPATH=/path/to/dataset \
CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7 \
UV_CACHE_DIR=/tmp/uv-cache \
UV_LINK_MODE=copy \
MPLCONFIGDIR=/tmp/matplotlib \
bash train_long.sh
```

Deployment exports should use the final finetune checkpoint and `+exp=finetune` so the exported model is a single-input student policy:

```bash
cd /home/velix/project/HoloTeleop/training

MEMPATH=/path/to/dataset \
CUDA_VISIBLE_DEVICES=0 \
UV_CACHE_DIR=/tmp/uv-cache \
UV_LINK_MODE=copy \
MPLCONFIGDIR=/tmp/matplotlib \
uv run python scripts/export_deploy.py \
  task=G1/G1_tracking \
  +exp=finetune \
  checkpoint_path=/path/to/checkpoint_final.pt \
  +export_dir=/home/velix/project/HoloTeleop/sim2real/assets/ckpts/G1TRACKING-MM-DD_HH-MM \
  wandb.mode=disabled
```

After export, check that `policy.json` contains `in_keys: ["policy"]`.

Tracker evaluation notes are in
[`benchmarks/g1_tracking/docs/EVALUATION.md`](benchmarks/g1_tracking/docs/EVALUATION.md).
Data collection and training-data export notes are in
[`docs/DATA_COLLECTION_AND_EXPORT.md`](docs/DATA_COLLECTION_AND_EXPORT.md).

## Robot Deploy Over SSH

The PC runs PICO/XR/GMR teleop. The robot runs only `deploy.py`.

From the PC:

```bash
ssh unitree-wbcd
cd /mnt/nexus/workspace/project/HoloTeleop/sim2real
unset CYCLONEDDS_URI
/mnt/nexus/bin/uv run src/deploy.py --net eth0 --real
```

Robot-side `config/tracking.yaml` must point VR ZMQ to the PC IP, for example:

```yaml
vr_req_addr: "tcp://192.168.1.159:28701"
vr_rep_addr: "tcp://192.168.1.159:28702"
vr_ctrl_addr: "tcp://192.168.1.159:28703"
```

The Qt app can patch these addresses and launch deploy over SSH.

## Sync Code To Robot

Use rsync; do not sync environments or caches:

```bash
rsync -av \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '.pytest_cache' \
  --exclude '.mypy_cache' \
  --exclude '.ruff_cache' \
  --exclude 'teleop/teleop_records' \
  /home/velix/project/HoloTeleop/sim2real/ \
  unitree-wbcd:/mnt/nexus/workspace/project/HoloTeleop/sim2real/
```

The Qt app uses the same exclude strategy.
