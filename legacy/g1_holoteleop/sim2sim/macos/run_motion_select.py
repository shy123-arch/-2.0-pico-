#!/usr/bin/env python3
"""Motion selector launcher. Wraps sim2real's motion_select.py."""

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

# ── ④ Switch to sim2real root so relative paths work
os.chdir(_SIM2REAL_ROOT)

# ── ⑤ Launch original motion_select.py ──────────────────────────────
import runpy
runpy.run_path(os.path.join(_SIM2REAL_SRC, "motion_select.py"), run_name="__main__")
