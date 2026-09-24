from glob import glob

from setuptools import find_packages, setup


package_name = "tianyi2_pico_teleop"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", glob("config/*.yaml")),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
        (f"share/{package_name}/rviz", glob("rviz/*.rviz")),
    ],
    install_requires=["setuptools", "numpy"],
    zip_safe=True,
    maintainer="shy123-arch",
    maintainer_email="3515347387@qq.com",
    description="PICO teleoperation bridge for Tianyi 2.0",
    license="Proprietary",
    entry_points={
        "console_scripts": [
            "pico_streamer = tianyi2_pico_teleop.pico_streamer:main",
            "robot_node = tianyi2_pico_teleop.ros_node:main",
            "inspect_robot_state = tianyi2_pico_teleop.diagnostics:main",
            "validate_config = tianyi2_pico_teleop.validate_config:main",
            "sim_visualizer = tianyi2_pico_teleop.sim_visualizer:main",
        ]
    },
)
