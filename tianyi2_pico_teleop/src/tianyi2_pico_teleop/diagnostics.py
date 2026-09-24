"""Print arm motor IDs and feedback fields from the vendor RobotState topic."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/robot_state")
    args, ros_args = parser.parse_known_args()

    import rclpy
    from rclpy.node import Node

    from .vendor_xhumanoid import robot_state_message_type

    rclpy.init(args=ros_args)
    node = Node("tianyi2_robot_state_inspector")
    seen: set[int] = set()

    def callback(message) -> None:
        rows = []
        for status in message.arm.status:
            motor_id = int(status.name)
            seen.add(motor_id)
            rows.append(
                f"id={motor_id:3d} pos={float(status.pos): .6f} "
                f"spd={float(status.spd): .6f} cur={float(status.cur): .3f}"
            )
        node.get_logger().info("arm motors:\n" + "\n".join(rows))

    node.create_subscription(robot_state_message_type(), args.topic, callback, 10)
    node.get_logger().info(f"listening on {args.topic}; move no joints during ID discovery")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

