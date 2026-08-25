#!/usr/bin/env bash
set -Eeo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROS_SETUP="/opt/ros/${ROS_DISTRO:-humble}/setup.bash"
UNITREE_SDK2_PYTHON_PATH="${UNITREE_SDK2_PYTHON_PATH:-/home/unitree/unitree_sdk2_python}"
CYCLONEDDS_COMPAT_PREFIX="${CYCLONEDDS_COMPAT_PREFIX:-/home/unitree/cyclonedds-prefix}"

source "$ROS_SETUP"
set -u

source "$PROJECT_DIR/scripts/require_g1_unitree_interface.sh"
INTERFACE="$G1_UNITREE_INTERFACE"
export CYCLONEDDS_URI="<CycloneDDS><Domain Id=\"any\"><General><Interfaces><NetworkInterface name=\"${INTERFACE}\"/></Interfaces></General></Domain></CycloneDDS>"
source "$PROJECT_DIR/scripts/load_g1_command_plane.sh"

export PYTHONPATH="$PROJECT_DIR:$PROJECT_DIR/vendor:$UNITREE_SDK2_PYTHON_PATH${PYTHONPATH:+:$PYTHONPATH}"
if [[ -d "$CYCLONEDDS_COMPAT_PREFIX/lib" ]]; then
  export CYCLONEDDS_HOME="$CYCLONEDDS_COMPAT_PREFIX"
  export LD_LIBRARY_PATH="$CYCLONEDDS_COMPAT_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

exec "${SMART_CENTER_ROS_PYTHON:-/usr/bin/python3}" \
  "$PROJECT_DIR/ros2/g1_motion_bridge.py" \
  "$INTERFACE" \
  --request-topic "$ROS2_ACTION_REQUEST_TOPIC" \
  --result-topic "$ROS2_ACTION_RESULT_TOPIC" \
  --response-topic "$ROS2_RESPONSE_TOPIC"
