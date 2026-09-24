#!/usr/bin/env bash
set -euo pipefail

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 was not found. Install/source ROS 2 first." >&2
  exit 1
fi

exec ros2 launch tianyi2_pico_teleop local_sim.launch.py "$@"
