#!/usr/bin/env python3
"""Deploy launcher. Wraps sim2real's deploy.py with cross-platform Timer."""

import os
import sys
import types

# ── ① Force fork on macOS — ONNX sessions can't be pickled by spawn ──
import multiprocessing as mp
mp.set_start_method("fork", force=True)

# ── ② Resolve paths ───────────────────────────────────────────────────
_SIM2SIM_DIR = os.path.dirname(os.path.abspath(__file__))
_SIM2REAL_ROOT = os.path.join(_SIM2SIM_DIR, "..", "..", "sim2real")
_SIM2REAL_SRC = os.path.join(_SIM2REAL_ROOT, "src")

# ── ③ Fake linuxfd so sim2real code doesn't crash on import ──────────
sys.modules["linuxfd"] = types.ModuleType("linuxfd")

# ── ④ Patch sim2real's Timer with our cross-platform version ─────────
sys.path.insert(0, _SIM2REAL_SRC)

import common.utils
from _timer import Timer

common.utils.Timer = Timer

# ── ⑤ Default network interface to macOS loopback ────────────────────
if "--net" not in sys.argv:
    sys.argv.extend(["--net", "lo0"])

# ── ⑥ Default motion source to UDP (overrides config's vr) ──────────
if "--motion-source" not in sys.argv and "--real" not in sys.argv:
    sys.argv.extend(["--motion-source", "udp"])

# ── ⑦ Switch to sim2real root so relative paths (config, assets) work
os.chdir(_SIM2REAL_ROOT)

# ── ⑧ Launch original deploy.py ──────────────────────────────────────
import runpy
runpy.run_path(os.path.join(_SIM2REAL_SRC, "deploy.py"), run_name="__main__")
