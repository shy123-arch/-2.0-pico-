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
- ROS 2 X-Humanoid adapter and dry-run target topics;
- Linux/ROS 2 one-command local launch with mock PICO autostart;
- RViz schematic visualization of the two commanded tool targets.

The local simulation targets Ubuntu 22.04, ROS 2 Humble and Python 3.10. The
Python and ROS interfaces used by the simulation are available in Humble. The
hardware node remains intended for the robot's vendor-supported xos environment;
the public X-Humanoid SDK currently documents Ubuntu 24.04 and ROS 2 Jazzy.

The bundled visualization validates process startup, UDP transport, safety-state
activation, anchor mapping and ROS topic flow. It is intentionally not a precise
Tianyi kinematics/dynamics simulation because no verified Tianyi 2.0 URDF is
available in the supplied files or public SDK.

## Not yet hardware-verified

- Tianyi 2.0 motor IDs and joint names;
- Tianyi 2.0 URDF and end-effector frames;
- whether Tianyi firmware exposes the same arm topics/messages as TianGong 3.0;
- chassis and gripper topics;
- controller-to-tool orientation offsets;
- real-time rate, current limits and collision behavior.

The repository must not be described as “Tianyi real-robot verified” until these
items are measured on the target unit and the checklist is signed off.
