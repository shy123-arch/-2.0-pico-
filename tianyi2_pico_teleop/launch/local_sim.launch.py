from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    package_share = FindPackageShare("tianyi2_pico_teleop")
    default_config = PathJoinSubstitution(
        [package_share, "config", "tianyi2.sim.yaml"]
    )
    rviz_config = PathJoinSubstitution(
        [package_share, "rviz", "tianyi2_dry_run.rviz"]
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument("config", default_value=default_config),
            DeclareLaunchArgument("rviz", default_value="true"),
            Node(
                package="tianyi2_pico_teleop",
                executable="robot_node",
                name="tianyi2_pico_teleop",
                output="screen",
                arguments=["--config", LaunchConfiguration("config")],
            ),
            Node(
                package="tianyi2_pico_teleop",
                executable="sim_visualizer",
                name="tianyi2_dry_run_visualizer",
                output="screen",
            ),
            ExecuteProcess(
                cmd=[
                    "pico_streamer",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "28810",
                    "--mock",
                    "--mock-autostart",
                ],
                output="screen",
            ),
            Node(
                package="rviz2",
                executable="rviz2",
                name="rviz2",
                output="screen",
                arguments=["-d", rviz_config],
                condition=IfCondition(LaunchConfiguration("rviz")),
            ),
        ]
    )
