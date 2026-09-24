"""Configuration loading and fail-closed hardware validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .geometry import Pose
from .safety import JointSpec

try:
    import yaml
except ImportError:  # The shipped template is JSON-compatible YAML.
    yaml = None


@dataclass(frozen=True)
class ArmConfig:
    end_effector_frame: str
    controller_to_tool: Pose
    joints: tuple[JointSpec, ...]


@dataclass(frozen=True)
class TeleopConfig:
    udp_bind_host: str
    udp_port: int
    control_rate_hz: float
    packet_timeout_ms: float
    feedback_timeout_ms: float
    global_max_step_rad: float
    dry_run: bool
    hardware_verified: bool
    urdf_path: str
    position_scale: float
    ik_damping: float
    ik_iterations: int
    arm_command_topic: str
    robot_state_topic: str
    arm_control_mode: int
    command_speed_rad_s: float
    command_current_a: float
    left: ArmConfig
    right: ArmConfig
    base_enabled: bool
    base_topic: str
    max_linear_m_s: float
    max_angular_rad_s: float
    grippers_enabled: bool
    left_gripper_topic: str
    right_gripper_topic: str

    @property
    def joint_specs(self) -> list[JointSpec]:
        return [*self.left.joints, *self.right.joints]

    def validate(self, *, for_hardware: bool | None = None) -> None:
        if self.udp_port <= 0 or self.udp_port > 65535:
            raise ValueError("udp_port must be in 1..65535")
        if self.control_rate_hz <= 0.0:
            raise ValueError("control_rate_hz must be positive")
        if self.packet_timeout_ms <= 0.0 or self.feedback_timeout_ms <= 0.0:
            raise ValueError("watchdog timeouts must be positive")
        if self.global_max_step_rad <= 0.0:
            raise ValueError("global_max_step_rad must be positive")
        if self.position_scale <= 0.0:
            raise ValueError("position_scale must be positive")
        if self.ik_damping <= 0.0 or self.ik_iterations <= 0:
            raise ValueError("IK damping and iterations must be positive")

        hardware = (not self.dry_run) if for_hardware is None else bool(for_hardware)
        if not hardware:
            return
        if not self.hardware_verified:
            raise ValueError(
                "hardware output is locked: set hardware_verified only after completing "
                "docs/HARDWARE_CHECKLIST.md"
            )
        if not self.urdf_path or "CHANGE_ME" in self.urdf_path:
            raise ValueError("urdf_path is not configured")
        if not self.left.end_effector_frame or "CHANGE_ME" in self.left.end_effector_frame:
            raise ValueError("left end-effector frame is not configured")
        if not self.right.end_effector_frame or "CHANGE_ME" in self.right.end_effector_frame:
            raise ValueError("right end-effector frame is not configured")
        if len(self.left.joints) != 7 or len(self.right.joints) != 7:
            raise ValueError("Tianyi 2.0 configuration must contain seven joints per arm")
        seen_ids: set[int] = set()
        seen_names: set[str] = set()
        for spec in self.joint_specs:
            spec.validate()
            if spec.motor_id in seen_ids:
                raise ValueError(f"duplicate motor id: {spec.motor_id}")
            if spec.model_joint in seen_names:
                raise ValueError(f"duplicate model joint: {spec.model_joint}")
            seen_ids.add(spec.motor_id)
            seen_names.add(spec.model_joint)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _pose(value: Any, label: str) -> Pose:
    values = list(value) if isinstance(value, (list, tuple)) else []
    if len(values) != 7:
        raise ValueError(f"{label} must be [x,y,z,qx,qy,qz,qw]")
    return Pose.from_pose7(values)


def _arm(value: Any, label: str) -> ArmConfig:
    data = _mapping(value, label)
    joints: list[JointSpec] = []
    raw_joints = data.get("joints", [])
    if not isinstance(raw_joints, list):
        raise ValueError(f"{label}.joints must be a list")
    for index, raw in enumerate(raw_joints):
        item = _mapping(raw, f"{label}.joints[{index}]")
        joints.append(
            JointSpec(
                model_joint=str(item.get("model_joint", "")),
                motor_id=int(item.get("motor_id", -1)),
                minimum=float(item.get("min_rad", -3.14)),
                maximum=float(item.get("max_rad", 3.14)),
                max_velocity=float(item.get("max_velocity_rad_s", 0.35)),
            )
        )
    return ArmConfig(
        end_effector_frame=str(data.get("end_effector_frame", "")),
        controller_to_tool=_pose(
            data.get("controller_to_tool", [0, 0, 0, 0, 0, 0, 1]),
            f"{label}.controller_to_tool",
        ),
        joints=tuple(joints),
    )


def load_config(path: str | Path) -> TeleopConfig:
    config_path = Path(path).expanduser()
    with config_path.open("r", encoding="utf-8") as handle:
        text = handle.read()
    parsed = yaml.safe_load(text) if yaml is not None else json.loads(text)
    root = _mapping(parsed, "root")
    network = _mapping(root.get("network", {}), "network")
    safety = _mapping(root.get("safety", {}), "safety")
    ik = _mapping(root.get("ik", {}), "ik")
    robot = _mapping(root.get("robot", {}), "robot")
    arms = _mapping(root.get("arms", {}), "arms")
    base = _mapping(root.get("base", {}), "base")
    grippers = _mapping(root.get("grippers", {}), "grippers")

    config = TeleopConfig(
        udp_bind_host=str(network.get("udp_bind_host", "0.0.0.0")),
        udp_port=int(network.get("udp_port", 28810)),
        control_rate_hz=float(robot.get("control_rate_hz", 50.0)),
        packet_timeout_ms=float(safety.get("packet_timeout_ms", 150.0)),
        feedback_timeout_ms=float(safety.get("feedback_timeout_ms", 200.0)),
        global_max_step_rad=float(safety.get("global_max_step_rad", 0.02)),
        dry_run=bool(safety.get("dry_run", True)),
        hardware_verified=bool(safety.get("hardware_verified", False)),
        urdf_path=str(ik.get("urdf_path", "CHANGE_ME")),
        position_scale=float(ik.get("position_scale", 1.0)),
        ik_damping=float(ik.get("damping", 1e-4)),
        ik_iterations=int(ik.get("iterations", 20)),
        arm_command_topic=str(robot.get("arm_command_topic", "/arm/cmd")),
        robot_state_topic=str(robot.get("robot_state_topic", "/robot_state")),
        arm_control_mode=int(robot.get("arm_control_mode", 0)),
        command_speed_rad_s=float(robot.get("command_speed_rad_s", 0.3)),
        command_current_a=float(robot.get("command_current_a", 5.0)),
        left=_arm(arms.get("left", {}), "arms.left"),
        right=_arm(arms.get("right", {}), "arms.right"),
        base_enabled=bool(base.get("enabled", False)),
        base_topic=str(base.get("topic", "/cmd_vel")),
        max_linear_m_s=float(base.get("max_linear_m_s", 0.2)),
        max_angular_rad_s=float(base.get("max_angular_rad_s", 0.3)),
        grippers_enabled=bool(grippers.get("enabled", False)),
        left_gripper_topic=str(grippers.get("left_topic", "/left_gripper/command")),
        right_gripper_topic=str(grippers.get("right_topic", "/right_gripper/command")),
    )
    config.validate()
    return config
