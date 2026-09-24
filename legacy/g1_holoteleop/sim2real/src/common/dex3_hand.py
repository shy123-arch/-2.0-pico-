from __future__ import annotations

from dataclasses import dataclass

import numpy as np


DEX3_DOF = 7

# Unitree Dex3 joint order:
# left:  thumb_0, thumb_1, thumb_2, middle_0, middle_1, index_0, index_1
# right: thumb_0, thumb_1, thumb_2, index_0, index_1, middle_0, middle_1
LEFT_LIMIT_LOWER = np.array([-1.05, -0.72, 0.0, -1.57, -1.75, -1.57, -1.75], dtype=np.float64)
LEFT_LIMIT_UPPER = np.array([1.05, 1.05, 1.75, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)
RIGHT_LIMIT_LOWER = np.array([-1.05, -1.05, -1.75, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)
RIGHT_LIMIT_UPPER = np.array([1.05, 0.74, 0.0, 1.57, 1.75, 1.57, 1.75], dtype=np.float64)

DEFAULT_KP = np.array([2.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5], dtype=np.float64)
DEFAULT_KD = np.array([0.5, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1], dtype=np.float64)

# Follows GR00T's G1GripperInverseKinematicsSolver middle-close style, clipped to
# Unitree's published Dex3 ranges.
LEFT_CLOSED_FIST = np.array([0.0, 0.70, 0.70, -1.00, -1.50, -1.00, -1.50], dtype=np.float64)
RIGHT_CLOSED_FIST = np.array([0.0, -0.70, -0.70, 1.00, 1.50, 1.00, 1.50], dtype=np.float64)

LEFT_OPEN = np.zeros(DEX3_DOF, dtype=np.float64)
RIGHT_OPEN = np.zeros(DEX3_DOF, dtype=np.float64)


def make_hand_mode(motor_index: int, status: int = 0x01, timeout: int = 0x01) -> int:
    mode = motor_index & 0x0F
    mode |= (status & 0x07) << 4
    mode |= (timeout & 0x01) << 7
    return mode


def clip_left(q: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(q, dtype=np.float64), LEFT_LIMIT_LOWER, LEFT_LIMIT_UPPER)


def clip_right(q: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(q, dtype=np.float64), RIGHT_LIMIT_LOWER, RIGHT_LIMIT_UPPER)


def get_hand_pose(name: str) -> tuple[np.ndarray, np.ndarray]:
    normalized = name.strip().lower().replace("-", "_")
    if normalized in ("closed", "closed_fist", "fist"):
        return clip_left(LEFT_CLOSED_FIST), clip_right(RIGHT_CLOSED_FIST)
    if normalized == "open":
        return LEFT_OPEN.copy(), RIGHT_OPEN.copy()
    raise ValueError(f"Unknown Dex3 hand pose: {name}")


def hand_pose_from_vr_controls(
    left_trigger: float,
    left_grip: float,
    right_trigger: float,
    right_grip: float,
) -> tuple[np.ndarray, np.ndarray]:
    def _amount(index_trigger: float, rear_trigger: float) -> float:
        trigger = float(np.clip(index_trigger, 0.0, 1.0))
        if float(rear_trigger) > 1e-4:
            return 0.5 + 0.5 * trigger
        return trigger

    left_amount = _amount(left_trigger, left_grip)
    right_amount = _amount(right_trigger, right_grip)
    left_q = LEFT_OPEN + left_amount * (LEFT_CLOSED_FIST - LEFT_OPEN)
    right_q = RIGHT_OPEN + right_amount * (RIGHT_CLOSED_FIST - RIGHT_OPEN)
    return clip_left(left_q), clip_right(right_q)


@dataclass
class Dex3HandCommandPublisher:
    kp: np.ndarray | None = None
    kd: np.ndarray | None = None

    def __post_init__(self):
        from unitree_sdk2py.core.channel import ChannelPublisher
        from unitree_sdk2py.idl.default import unitree_hg_msg_dds__HandCmd_
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import HandCmd_

        self.kp = DEFAULT_KP.copy() if self.kp is None else np.asarray(self.kp, dtype=np.float64)
        self.kd = DEFAULT_KD.copy() if self.kd is None else np.asarray(self.kd, dtype=np.float64)
        self.left_cmd_pub = ChannelPublisher("rt/dex3/left/cmd", HandCmd_)
        self.right_cmd_pub = ChannelPublisher("rt/dex3/right/cmd", HandCmd_)
        self.left_cmd_pub.Init()
        self.right_cmd_pub.Init()
        self.left_cmd = unitree_hg_msg_dds__HandCmd_()
        self.right_cmd = unitree_hg_msg_dds__HandCmd_()

    def publish(self, left_q: np.ndarray, right_q: np.ndarray):
        left_q = clip_left(left_q)
        right_q = clip_right(right_q)
        for i in range(DEX3_DOF):
            mode = make_hand_mode(i)
            self.left_cmd.motor_cmd[i].mode = mode
            self.left_cmd.motor_cmd[i].q = float(left_q[i])
            self.left_cmd.motor_cmd[i].dq = 0.0
            self.left_cmd.motor_cmd[i].tau = 0.0
            self.left_cmd.motor_cmd[i].kp = float(self.kp[i])
            self.left_cmd.motor_cmd[i].kd = float(self.kd[i])

            self.right_cmd.motor_cmd[i].mode = mode
            self.right_cmd.motor_cmd[i].q = float(right_q[i])
            self.right_cmd.motor_cmd[i].dq = 0.0
            self.right_cmd.motor_cmd[i].tau = 0.0
            self.right_cmd.motor_cmd[i].kp = float(self.kp[i])
            self.right_cmd.motor_cmd[i].kd = float(self.kd[i])

        self.left_cmd_pub.Write(self.left_cmd)
        self.right_cmd_pub.Write(self.right_cmd)
