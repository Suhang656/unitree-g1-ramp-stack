#!/usr/bin/env bash
INTERFACE="${G1_NETWORK_INTERFACE:-enP8p1s0}"
export CYCLONEDDS_URI="<CycloneDDS><Domain Id=\"any\"><General><Interfaces><NetworkInterface name=\"${INTERFACE}\"/></Interfaces></General></Domain></CycloneDDS>"
set -Eeo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROS_DISTRO="${ROS_DISTRO:-humble}"
ROS_SETUP="/opt/ros/${ROS_DISTRO}/setup.bash"

if [[ ! -f "$ROS_SETUP" ]]; then
  echo "未找到 $ROS_SETUP。请先安装 ROS 2，或设置正确的 ROS_DISTRO。" >&2
  exit 1
fi

source "$ROS_SETUP"
set -u
# Humble 的 rclpy 通常绑定系统 Python 3.10；不要直接混用 Conda Python 3.11。
PYTHON_BIN="${SMART_CENTER_ROS_PYTHON:-python3}"
export PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" "$PROJECT_DIR/ros2/smart_center_node.py"
