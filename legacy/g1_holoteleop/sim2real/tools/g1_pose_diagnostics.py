#!/usr/bin/env python3
"""Read-only G1 low-state diagnostics for default-pose mismatch checks."""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_ as LowStateHG


def load_controller_config() -> dict:
    with open(ROOT / "config" / "controller.yaml", "r") as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def quat_wxyz_to_rpy_deg(q: np.ndarray) -> tuple[float, float, float]:
    w, x, y, z = [float(v) for v in q]
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm > 1e-8:
        w, x, y, z = w / norm, x / norm, y / norm, z / norm

    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1 else math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return tuple(math.degrees(v) for v in (roll, pitch, yaw))


def format_counts(values: np.ndarray) -> str:
    unique, counts = np.unique(np.asarray(values).reshape(-1), return_counts=True)
    return ",".join(f"{int(v)}x{int(c)}" for v, c in zip(unique, counts))


def read_state(sub: ChannelSubscriber, timeout_s: float) -> LowStateHG:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        msg = sub.Read(0.05)
        if msg is not None:
            return msg
    raise TimeoutError(f"no lowstate received within {timeout_s:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--net", default="eth0")
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--timeout-s", type=float, default=5.0)
    args = parser.parse_args()

    cfg = load_controller_config()
    names = list(cfg["real_joint_names"])
    default_q = np.asarray(cfg["default_qpos_real"], dtype=np.float64)
    init_q = np.asarray(cfg["init_qpos_real"], dtype=np.float64)
    n = len(names)

    ChannelFactoryInitialize(0, args.net)
    sub = ChannelSubscriber(cfg["lowstate_topic"], LowStateHG)
    sub.Init()

    qs = []
    dqs = []
    taus = []
    temps = []
    modes = []
    states = []
    quats = []
    gyros = []

    print(f"[diag] reading {args.samples} lowstate samples on net={args.net} ...")
    for _ in range(args.samples):
        msg = read_state(sub, args.timeout_s)
        qs.append([msg.motor_state[i].q for i in range(n)])
        dqs.append([msg.motor_state[i].dq for i in range(n)])
        taus.append([msg.motor_state[i].tau_est for i in range(n)])
        temps.append([msg.motor_state[i].temperature[0] for i in range(n)])
        modes.append([msg.motor_state[i].mode for i in range(n)])
        states.append([msg.motor_state[i].motorstate for i in range(n)])
        quats.append(list(msg.imu_state.quaternion))
        gyros.append(list(msg.imu_state.gyroscope))
        time.sleep(0.01)

    q = np.mean(np.asarray(qs), axis=0)
    dq = np.mean(np.asarray(dqs), axis=0)
    tau = np.mean(np.asarray(taus), axis=0)
    temp = np.max(np.asarray(temps), axis=0)
    quat = np.mean(np.asarray(quats), axis=0)
    gyro = np.mean(np.asarray(gyros), axis=0)

    diff_default = q - default_q
    diff_init = q - init_q
    order = np.argsort(-np.abs(diff_default))

    print("\n[diag] IMU")
    rpy = quat_wxyz_to_rpy_deg(quat)
    print(f"quat_wxyz={np.array2string(quat, precision=4, suppress_small=True)}")
    print(f"rpy_deg=roll:{rpy[0]:.2f}, pitch:{rpy[1]:.2f}, yaw:{rpy[2]:.2f}")
    print(f"gyro_norm={float(np.linalg.norm(gyro)):.4f}, gyro={np.array2string(gyro, precision=4, suppress_small=True)}")

    print("\n[diag] motors")
    print(f"mode_counts={format_counts(np.asarray(modes)[-1])}")
    print(f"state_counts={format_counts(np.asarray(states)[-1])}")
    print(f"temp_max={int(np.max(temp))}")
    print(f"dq_max={float(np.max(np.abs(dq))):.4f}, tau_max={float(np.max(np.abs(tau))):.2f}")

    print("\n[diag] q - default_qpos_real, largest joints")
    print("rank  joint                              q       default     diff    diff_init")
    for rank, i in enumerate(order[: args.top], start=1):
        print(
            f"{rank:>4}  {names[i]:<30} "
            f"{q[i]:>7.3f} {default_q[i]:>9.3f} {diff_default[i]:>8.3f} {diff_init[i]:>10.3f}"
        )

    print("\n[diag] summary")
    print(f"default_abs_max={float(np.max(np.abs(diff_default))):.3f}@{names[int(order[0])]}")
    print(f"default_abs_mean={float(np.mean(np.abs(diff_default))):.3f}")
    print("rule_of_thumb: >0.20 rad on waist/ankle/shoulder or large IMU roll/pitch can push the policy out of distribution.")


if __name__ == "__main__":
    main()
