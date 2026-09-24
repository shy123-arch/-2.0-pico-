"""Schematic RViz visualization for the dry-run PICO control pipeline.

This deliberately avoids pretending to be a Tianyi kinematic or dynamics model.
It visualizes the two commanded tool poses and the data path before a verified
Tianyi 2.0 URDF is available.
"""

from __future__ import annotations

import rclpy
from geometry_msgs.msg import Point, PoseStamped
from rclpy.node import Node
from visualization_msgs.msg import Marker, MarkerArray


class DryRunVisualizer(Node):
    def __init__(self) -> None:
        super().__init__("tianyi2_dry_run_visualizer")
        self.left: PoseStamped | None = None
        self.right: PoseStamped | None = None
        self.publisher = self.create_publisher(
            MarkerArray, "/tianyi2_teleop/sim_markers", 10
        )
        self.create_subscription(
            PoseStamped, "/tianyi2_teleop/left_target", self._on_left, 10
        )
        self.create_subscription(
            PoseStamped, "/tianyi2_teleop/right_target", self._on_right, 10
        )
        self.create_timer(1.0 / 30.0, self._publish)
        self.get_logger().warning(
            "schematic dry-run visualization; this is not a Tianyi dynamics model"
        )

    def _on_left(self, message: PoseStamped) -> None:
        self.left = message

    def _on_right(self, message: PoseStamped) -> None:
        self.right = message

    def _marker(self, marker_id: int, marker_type: int, name: str) -> Marker:
        marker = Marker()
        marker.header.frame_id = "base_link"
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = name
        marker.id = marker_id
        marker.type = marker_type
        marker.action = Marker.ADD
        marker.pose.orientation.w = 1.0
        marker.color.a = 1.0
        return marker

    def _body_markers(self) -> list[Marker]:
        base = self._marker(0, Marker.CYLINDER, "proxy_robot")
        base.pose.position.z = 0.14
        base.scale.x = base.scale.y = 0.55
        base.scale.z = 0.28
        base.color.r, base.color.g, base.color.b = (0.20, 0.24, 0.30)

        torso = self._marker(1, Marker.CUBE, "proxy_robot")
        torso.pose.position.z = 0.58
        torso.scale.x, torso.scale.y, torso.scale.z = (0.50, 0.30, 0.65)
        torso.color.r, torso.color.g, torso.color.b = (0.32, 0.38, 0.46)

        label = self._marker(2, Marker.TEXT_VIEW_FACING, "proxy_robot")
        label.pose.position.z = 1.10
        label.scale.z = 0.09
        label.color.r, label.color.g, label.color.b = (0.95, 0.95, 0.95)
        label.text = "TIANYI 2.0 CONTROL-PIPELINE SIM (SCHEMATIC)"
        return [base, torso, label]

    def _arm_markers(
        self,
        marker_id: int,
        side: str,
        target: PoseStamped | None,
        shoulder_x: float,
        color: tuple[float, float, float],
    ) -> list[Marker]:
        shoulder = Point(x=shoulder_x, y=0.0, z=0.78)
        if target is None:
            end = Point(x=shoulder_x, y=0.25, z=0.35)
        else:
            end = Point(
                x=target.pose.position.x,
                y=target.pose.position.y,
                z=target.pose.position.z,
            )

        line = self._marker(marker_id, Marker.LINE_STRIP, f"{side}_proxy_arm")
        line.scale.x = 0.045
        line.color.r, line.color.g, line.color.b = color
        # A midpoint makes the schematic read as a two-link arm in RViz.
        elbow = Point(
            x=(shoulder.x + end.x) * 0.5,
            y=(shoulder.y + end.y) * 0.5 - 0.08,
            z=(shoulder.z + end.z) * 0.5,
        )
        line.points = [shoulder, elbow, end]

        tool = self._marker(marker_id + 1, Marker.SPHERE, f"{side}_target")
        tool.pose.position = end
        if target is not None:
            tool.pose.orientation = target.pose.orientation
        tool.scale.x = tool.scale.y = tool.scale.z = 0.10
        tool.color.r, tool.color.g, tool.color.b = color

        caption = self._marker(marker_id + 2, Marker.TEXT_VIEW_FACING, f"{side}_target")
        caption.pose.position.x = end.x
        caption.pose.position.y = end.y
        caption.pose.position.z = end.z + 0.10
        caption.scale.z = 0.07
        caption.color.r, caption.color.g, caption.color.b = color
        caption.text = f"{side} target"
        return [line, tool, caption]

    def _publish(self) -> None:
        markers = self._body_markers()
        markers.extend(
            self._arm_markers(10, "left", self.left, -0.30, (0.20, 0.65, 1.0))
        )
        markers.extend(
            self._arm_markers(20, "right", self.right, 0.30, (1.0, 0.45, 0.20))
        )
        self.publisher.publish(MarkerArray(markers=markers))


def main() -> None:
    rclpy.init()
    node = DryRunVisualizer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
