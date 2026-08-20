#!/usr/bin/env bash
set -Eeo pipefail

PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"

unset PYTHONPATH PYTHONHOME AMENT_PREFIX_PATH CMAKE_PREFIX_PATH
unset COLCON_PREFIX_PATH CYCLONEDDS_HOME CYCLONEDDS_URI
unset ROS_LOCALHOST_ONLY

source /opt/ros/humble/setup.bash
source "${UNITREE_ROS2_SETUP:-/home/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash}"

export PYTHONPATH="$PROJECT${PYTHONPATH:+:$PYTHONPATH}"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0

exec /usr/bin/python3 -u \
  "$PROJECT/ros2/g1_tour_executor.py"
