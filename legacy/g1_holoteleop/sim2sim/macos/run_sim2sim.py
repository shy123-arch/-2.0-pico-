#!/usr/bin/env python3
"""Sim2sim launcher. Wraps sim2real's sim2sim.py with cross-platform Timer.

Run with mjpython on macOS:
    uv run mjpython run_sim2sim.py --xml_path assets/g1/g1.xml --show-reference-ghost
"""

import os
import sys
import types

# ── ① Resolve paths ───────────────────────────────────────────────────
_SIM2SIM_DIR = os.path.dirname(os.path.abspath(__file__))
_SIM2REAL_ROOT = os.path.join(_SIM2SIM_DIR, "..", "..", "sim2real")
_SIM2REAL_SRC = os.path.join(_SIM2REAL_ROOT, "src")

# ── ② Fake linuxfd so sim2real code doesn't crash on import ──────────
sys.modules["linuxfd"] = types.ModuleType("linuxfd")

# ── ③ Patch sim2real's Timer with our cross-platform version ─────────
sys.path.insert(0, _SIM2REAL_SRC)

import common.utils
from _timer import Timer

common.utils.Timer = Timer

# ── ④ Patch ChannelFactoryInitialize: use lo0 on macOS ───────────────
_orig_cfi = None
try:
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize as _orig_cfi
except ImportError:
    pass

if _orig_cfi is not None:
    def _patched_cfi(domain=0, network=None):
        if network == "lo":
            network = "lo0"
        return _orig_cfi(domain, network)

    import unitree_sdk2py.core.channel as _chan
    _chan.ChannelFactoryInitialize = _patched_cfi

# ── ⑤ Switch to sim2real root so relative paths (config, assets) work
os.chdir(_SIM2REAL_ROOT)

# ── ⑥ Launch original sim2sim.py ─────────────────────────────────────
import runpy
runpy.run_path(os.path.join(_SIM2REAL_SRC, "sim2sim.py"), run_name="__main__")
