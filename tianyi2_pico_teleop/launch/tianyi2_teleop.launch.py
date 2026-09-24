from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("config", description="Absolute teleop YAML path"),
            Node(
                package="tianyi2_pico_teleop",
                executable="robot_node",
                name="tianyi2_pico_teleop",
                output="screen",
                arguments=["--config", LaunchConfiguration("config")],
            ),
        ]
    )

