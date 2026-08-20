#!/usr/bin/env bash

set -Ee
set -o pipefail

unset PYTHONPATH
unset AMENT_PREFIX_PATH
unset CMAKE_PREFIX_PATH
unset COLCON_PREFIX_PATH
unset CYCLONEDDS_HOME

source /opt/ros/humble/setup.bash
PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"
INTERFACE="${G1_NETWORK_INTERFACE:-enP8p1s0}"
source "${UNITREE_ROS2_SETUP:-/home/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash}"

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="<CycloneDDS><Domain Id=\"any\"><General><Interfaces><NetworkInterface name=\"${INTERFACE}\"/></Interfaces></General></Domain></CycloneDDS>"
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0

exec /usr/bin/python3 -u \
"$PROJECT/scripts/g1_ramp_odom_cache.py"
