#!/usr/bin/env bash
set -Eeo pipefail

PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"
source "$PROJECT/scripts/require_g1_unitree_interface.sh"
INTERFACE="$G1_UNITREE_INTERFACE"

unset PYTHONPATH
unset PYTHONHOME
unset AMENT_PREFIX_PATH
unset CMAKE_PREFIX_PATH
unset COLCON_PREFIX_PATH
unset CYCLONEDDS_HOME
unset CYCLONEDDS_URI
unset ROS_LOCALHOST_ONLY

source /opt/ros/humble/setup.bash
source "${UNITREE_ROS2_SETUP:-/home/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash}"

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0
export ROS2CLI_DISABLE_DAEMON=1
export CYCLONEDDS_URI="<CycloneDDS><Domain Id=\"any\"><General><Interfaces><NetworkInterface name=\"${INTERFACE}\"/></Interfaces></General></Domain></CycloneDDS>"

exec /usr/bin/python3 -u \
"$PROJECT/scripts/g1_mapping_recorder.py" \
"$@"
