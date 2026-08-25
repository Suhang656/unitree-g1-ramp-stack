#!/usr/bin/env bash
set -Eeo pipefail

unset PYTHONPATH
unset PYTHONHOME
unset CYCLONEDDS_HOME
unset ROS_LOCALHOST_ONLY

source /opt/ros/humble/setup.bash
PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"
source "$PROJECT/scripts/require_g1_unitree_interface.sh"
INTERFACE="$G1_UNITREE_INTERFACE"
source "${UNITREE_ROS2_SETUP:-/home/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash}"

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="<CycloneDDS><Domain Id=\"any\"><General><Interfaces><NetworkInterface name=\"${INTERFACE}\"/></Interfaces></General></Domain></CycloneDDS>"
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0

exec /usr/bin/python3 -u \
"$PROJECT/scripts/g1_persist_last_localization_pose.py"
