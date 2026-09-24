# sim2sim (macOS compat)

Thin compatibility layer wrapping `../../sim2real/` for macOS.

`sim2real/` is kept untouched — all patches live here.

## Setup

```bash
cd HoloTeleop/sim2sim/macos
uv sync
```

## Quick start

### Terminal 1 — simulator

```bash
uv run mjpython run_sim2sim.py --xml_path assets/g1/g1.xml --show-reference-ghost
```

### Terminal 2 — controller

```bash
uv run run_deploy.py --sim2sim
```

`--net` defaults to `lo0` (macOS), motion source defaults to `udp`.

### Terminal 3 — motion selector

```bash
uv run run_motion_select.py
```

See `sim2sim.sh` for more command examples.

## How it works

1. `sys.modules["linuxfd"]` is pre-populated with a fake module — avoids `ImportError` on macOS.
2. `common.utils.Timer` is monkey-patched with a monotonic-clock fallback from `_timer.py`.
3. `ChannelFactoryInitialize` is patched: `lo` → `lo0` on macOS.
4. `--motion-source` defaults to `udp` in sim mode.
5. The original `sim2real/src/*.py` runs unmodified via `runpy.run_path`.
