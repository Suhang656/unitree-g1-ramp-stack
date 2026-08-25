#!/usr/bin/env bash
set -e

source /opt/ros/humble/setup.bash
PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"
source "$PROJECT/scripts/load_g1_command_plane.sh"

exec /usr/bin/python3 -u \
"$PROJECT/ros2/g1_global_stop_router.py"
