"""ROS 2 robot-side node for Tianyi 2.0 PICO teleoperation."""

from __future__ import annotations

import argparse
import socket
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped, Twist
from rclpy.node import Node
from std_msgs.msg import Float64
from std_srvs.srv import Trigger

from .config import TeleopConfig, load_config
from .geometry import AnchorMapper, Pose
from .pinocchio_ik import PinocchioDualArmIK
from .protocol import PicoPacket, SequenceGuard
from .safety import TeleopState, TeleopStateMachine, limit_joint_targets
from .vendor_xhumanoid import (
    XHumanoidArmBackend,
    decode_arm_positions,
    robot_state_message_type,
)


class TianyiTeleopNode(Node):
    def __init__(self, config: TeleopConfig) -> None:
        super().__init__("tianyi2_pico_teleop")
        self.config = config
        if not config.dry_run:
            config.validate(for_hardware=True)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.socket.bind((config.udp_bind_host, config.udp_port))
        self.sequence_guard = SequenceGuard()
        self.packet: PicoPacket | None = None
        self.packet_recv_ns = 0
        self.feedback_recv_ns = 0
        self.feedback_positions: dict[str, float] = {}
        self.motor_to_joint = {
            spec.motor_id: spec.model_joint for spec in config.joint_specs
        }
        self.state_machine = TeleopStateMachine()
        self.left_mapper = AnchorMapper(
            config.position_scale, config.left.controller_to_tool
        )
        self.right_mapper = AnchorMapper(
            config.position_scale, config.right.controller_to_tool
        )
        self.last_tick_ns = time.monotonic_ns()
        self.last_reason = ""
        self.ik: PinocchioDualArmIK | None = None
        self.backend: XHumanoidArmBackend | None = None

        self.left_target_publisher = self.create_publisher(
            PoseStamped, "/tianyi2_teleop/left_target", 10
        )
        self.right_target_publisher = self.create_publisher(
            PoseStamped, "/tianyi2_teleop/right_target", 10
        )
        self.base_publisher = (
            self.create_publisher(Twist, config.base_topic, 10)
            if config.base_enabled
            else None
        )
        self.left_gripper_publisher = (
            self.create_publisher(Float64, config.left_gripper_topic, 10)
            if config.grippers_enabled
            else None
        )
        self.right_gripper_publisher = (
            self.create_publisher(Float64, config.right_gripper_topic, 10)
            if config.grippers_enabled
            else None
        )

        if not config.dry_run:
            self.ik = PinocchioDualArmIK(
                config.urdf_path,
                config.left,
                config.right,
                damping=config.ik_damping,
                iterations=config.ik_iterations,
            )
            self.backend = XHumanoidArmBackend(self, config)
            self.create_subscription(
                robot_state_message_type(),
                config.robot_state_topic,
                self._on_robot_state,
                10,
            )

        self.create_service(Trigger, "~/reset_estop", self._reset_estop)
        self.timer = self.create_timer(1.0 / config.control_rate_hz, self._tick)
        mode = "DRY-RUN" if config.dry_run else "HARDWARE"
        self.get_logger().warning(
            f"{mode} mode, UDP {config.udp_bind_host}:{config.udp_port}, "
            f"rate={config.control_rate_hz:g}Hz"
        )

    def destroy_node(self):
        self.socket.close()
        return super().destroy_node()

    def _reset_estop(self, request, response):
        del request
        self.state_machine.reset_estop_locally()
        self.left_mapper.clear()
        self.right_mapper.clear()
        response.success = True
        response.message = "software e-stop reset; press PICO A to recalibrate"
        return response

    def _on_robot_state(self, message) -> None:
        decoded = decode_arm_positions(message, self.motor_to_joint)
        if decoded:
            self.feedback_positions.update(decoded)
            self.feedback_recv_ns = time.monotonic_ns()

    def _drain_udp(self) -> None:
        newest: PicoPacket | None = None
        while True:
            try:
                payload, _address = self.socket.recvfrom(32768)
            except BlockingIOError:
                break
            except OSError as exc:
                self.get_logger().error(f"UDP receive error: {exc}")
                break
            try:
                candidate = PicoPacket.from_bytes(payload)
            except (UnicodeError, ValueError) as exc:
                self.get_logger().warning(f"invalid PICO packet: {exc}")
                continue
            if self.sequence_guard.accept(candidate):
                newest = candidate
        if newest is not None:
            self.packet = newest
            self.packet_recv_ns = time.monotonic_ns()

    def _fresh(self, timestamp_ns: int, timeout_ms: float, now_ns: int) -> bool:
        return timestamp_ns > 0 and (now_ns - timestamp_ns) / 1e6 <= timeout_ms

    def _integration_ready(self, feedback_fresh: bool) -> bool:
        if self.config.dry_run:
            return True
        return (
            self.ik is not None
            and self.backend is not None
            and feedback_fresh
            and len(self.feedback_positions) == len(self.config.joint_specs)
        )

    def _calibrate(self, packet: PicoPacket) -> None:
        if self.config.dry_run:
            left_robot = Pose((-0.30, 0.25, 0.35), (0.0, 0.0, 0.0, 1.0))
            right_robot = Pose((0.30, 0.25, 0.35), (0.0, 0.0, 0.0, 1.0))
        else:
            assert self.ik is not None
            self.ik.set_joint_positions(self.feedback_positions)
            left_robot = self.ik.frame_pose("left")
            right_robot = self.ik.frame_pose("right")
        self.left_mapper.calibrate(packet.left_controller, left_robot)
        self.right_mapper.calibrate(packet.right_controller, right_robot)
        self.get_logger().warning("PICO anchors captured; teleoperation ACTIVE")

    def _pose_message(self, pose: Pose) -> PoseStamped:
        message = PoseStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "base_link"
        message.pose.position.x, message.pose.position.y, message.pose.position.z = pose.position
        (
            message.pose.orientation.x,
            message.pose.orientation.y,
            message.pose.orientation.z,
            message.pose.orientation.w,
        ) = pose.quaternion_xyzw
        return message

    def _publish_auxiliary_controls(self, packet: PicoPacket) -> None:
        if self.base_publisher is not None:
            command = Twist()
            command.linear.x = (
                packet.values.get("left_axis_y", 0.0) * self.config.max_linear_m_s
            )
            command.linear.y = (
                -packet.values.get("left_axis_x", 0.0) * self.config.max_linear_m_s
            )
            command.angular.z = (
                -packet.values.get("right_axis_x", 0.0)
                * self.config.max_angular_rad_s
            )
            self.base_publisher.publish(command)
        if self.left_gripper_publisher is not None:
            self.left_gripper_publisher.publish(
                Float64(data=float(packet.values.get("left_grip", 0.0)))
            )
        if self.right_gripper_publisher is not None:
            self.right_gripper_publisher.publish(
                Float64(data=float(packet.values.get("right_grip", 0.0)))
            )

    def _hold(self) -> None:
        if self.backend is not None and len(self.feedback_positions) == len(
            self.config.joint_specs
        ):
            self.backend.publish(self, self.feedback_positions)
        if not self.config.dry_run and self.base_publisher is not None:
            self.base_publisher.publish(Twist())

    def _tick(self) -> None:
        self._drain_udp()
        now_ns = time.monotonic_ns()
        dt = max(1e-4, min(0.1, (now_ns - self.last_tick_ns) / 1e9))
        self.last_tick_ns = now_ns
        packet_fresh = self._fresh(
            self.packet_recv_ns, self.config.packet_timeout_ms, now_ns
        )
        feedback_fresh = self.config.dry_run or self._fresh(
            self.feedback_recv_ns, self.config.feedback_timeout_ms, now_ns
        )
        buttons = {} if self.packet is None else self.packet.buttons
        decision = self.state_machine.update(
            buttons,
            packet_fresh=packet_fresh,
            feedback_fresh=feedback_fresh,
            integration_ready=self._integration_ready(feedback_fresh),
        )
        if decision.reason and decision.reason != self.last_reason:
            self.get_logger().warning(
                f"state={decision.state.value}: {decision.reason}"
            )
            self.last_reason = decision.reason
        if decision.calibrate and self.packet is not None:
            self._calibrate(self.packet)
        if decision.state is not TeleopState.ACTIVE or self.packet is None:
            self._hold()
            return
        if not self.left_mapper.calibrated or not self.right_mapper.calibrated:
            self._hold()
            return

        left_target = self.left_mapper.map(self.packet.left_controller)
        right_target = self.right_mapper.map(self.packet.right_controller)
        self.left_target_publisher.publish(self._pose_message(left_target))
        self.right_target_publisher.publish(self._pose_message(right_target))
        if self.config.dry_run:
            return

        assert self.ik is not None
        assert self.backend is not None
        self._publish_auxiliary_controls(self.packet)
        self.ik.set_joint_positions(self.feedback_positions)
        desired = self.ik.solve(left_target, right_target)
        limited = limit_joint_targets(
            self.feedback_positions,
            desired,
            self.config.joint_specs,
            dt,
            self.config.global_max_step_rad,
        )
        if limited.clipped_joints:
            self.get_logger().warning(
                "joint limiter active: " + ", ".join(limited.clipped_joints)
            )
        self.backend.publish(self, limited.positions)


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="Tianyi 2.0 robot-side teleop node")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parents[2] / "config" / "tianyi2.template.yaml"),
    )
    return parser.parse_known_args()


def main() -> None:
    args, ros_args = parse_args()
    config = load_config(args.config)
    rclpy.init(args=ros_args)
    node = TianyiTeleopNode(config)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
