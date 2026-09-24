# Integration status

Updated: 2026-09-24

## Confirmed inputs

- The local G1 project already receives PICO/XRoboToolkit controller and body callbacks.
- The provided Tencent Meeting share is a 3,702,720 ms recording titled
  “天工3.0、天轶机器人操作培训”. The share has no enabled AI minutes or transcript,
  so it cannot provide machine-readable motor IDs or topic definitions.
- X-Humanoid's official Tianyi product page describes a wheeled dual-arm robot with
  remote operation capability.
- X-Humanoid's official public `xhumanoid_sdk` demonstrates ROS 2 arm commands on
  `/arm/cmd` with `ros2_bridge_msgs/ArmCtrl` and feedback on `/robot_state` for
  TianGong 3.0.

## Implemented and locally testable

- XR snapshot normalization and UDP protocol;
- sequence/reorder rejection;
- controller-to-robot anchor mapping;
- state machine and watchdog behavior;
- joint limit, velocity and step clamping;
- fail-closed YAML validation;
- optional Pinocchio dual-arm IK;
- ROS 2 X-Humanoid adapter and dry-run target topics.

## Not yet hardware-verified

- Tianyi 2.0 motor IDs and joint names;
- Tianyi 2.0 URDF and end-effector frames;
- whether Tianyi firmware exposes the same arm topics/messages as TianGong 3.0;
- chassis and gripper topics;
- controller-to-tool orientation offsets;
- real-time rate, current limits and collision behavior.

The repository must not be described as “Tianyi real-robot verified” until these
items are measured on the target unit and the checklist is signed off.

