#!/usr/bin/env bash
set -Eeo pipefail

PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"

unset PYTHONPATH PYTHONHOME AMENT_PREFIX_PATH CMAKE_PREFIX_PATH
unset COLCON_PREFIX_PATH CYCLONEDDS_HOME CYCLONEDDS_URI
unset ROS_LOCALHOST_ONLY

source /opt/ros/humble/setup.bash
export PYTHONPATH="$PROJECT${PYTHONPATH:+:$PYTHONPATH}"
source "$PROJECT/scripts/load_g1_command_plane.sh"

exec /usr/bin/python3 -u \
  "$PROJECT/ros2/g1_tour_executor.py"
