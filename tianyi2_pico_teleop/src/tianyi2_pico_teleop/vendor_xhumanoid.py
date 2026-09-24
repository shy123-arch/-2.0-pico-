"""Thin adapter for the X-Humanoid ROS 2 arm message contract."""

from __future__ import annotations

from typing import Mapping

from .config import TeleopConfig


class XHumanoidArmBackend:
    """Publishes the official ``ros2_bridge_msgs/ArmCtrl`` command type.

    The public example documents ``/arm/cmd`` and ``/robot_state`` for TianGong
    3.0. Tianyi 2.0 compatibility must be confirmed on the target robot before
    ``hardware_verified`` is enabled.
    """

    def __init__(self, node, config: TeleopConfig) -> None:
        try:
            from ros2_bridge_msgs.msg import ArmCtrl, MotorCtrl
        except ImportError as exc:
            raise RuntimeError(
                "ros2_bridge_msgs is unavailable; source the robot xos workspace first"
            ) from exc
        self.ArmCtrl = ArmCtrl
        self.MotorCtrl = MotorCtrl
        self.config = config
        self.publisher = node.create_publisher(ArmCtrl, config.arm_command_topic, 10)

    def publish(self, node, positions: Mapping[str, float]) -> None:
        message = self.ArmCtrl()
        message.header.stamp = node.get_clock().now().to_msg()
        message.header.frame_id = "arm"
        message.mode = int(self.config.arm_control_mode)
        message.label = 0
        for spec in self.config.joint_specs:
            control = self.MotorCtrl()
            control.name = int(spec.motor_id)
            control.pos = float(positions[spec.model_joint])
            control.spd = float(self.config.command_speed_rad_s)
            control.cur = float(self.config.command_current_a)
            message.ctrl.append(control)
        self.publisher.publish(message)


def robot_state_message_type():
    try:
        from ros2_bridge_msgs.msg import RobotState
    except ImportError as exc:
        raise RuntimeError(
            "ros2_bridge_msgs is unavailable; source the robot xos workspace first"
        ) from exc
    return RobotState


def decode_arm_positions(message, motor_to_joint: Mapping[int, str]) -> dict[str, float]:
    positions: dict[str, float] = {}
    for status in message.arm.status:
        name = motor_to_joint.get(int(status.name))
        if name is not None:
            positions[name] = float(status.pos)
    return positions

