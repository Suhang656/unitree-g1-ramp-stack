#!/usr/bin/env bash
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
PYTHON_BIN="${SMART_CENTER_ROS_PYTHON:-/usr/bin/python3}"
UNITREE_SDK2_PYTHON_PATH="${UNITREE_SDK2_PYTHON_PATH:-/home/unitree/unitree_sdk2_python}"
CYCLONEDDS_COMPAT_PREFIX="${CYCLONEDDS_COMPAT_PREFIX:-/home/unitree/cyclonedds-prefix}"
if [[ ! -d "$UNITREE_SDK2_PYTHON_PATH/unitree_sdk2py" ]]; then
  echo "未找到 Unitree SDK2 Python: $UNITREE_SDK2_PYTHON_PATH" >&2
  echo "请设置 UNITREE_SDK2_PYTHON_PATH 为 SDK 源码目录。" >&2
  exit 1
fi
if [[ -d "$CYCLONEDDS_COMPAT_PREFIX/lib" ]]; then
  export CYCLONEDDS_HOME="$CYCLONEDDS_COMPAT_PREFIX"
  export LD_LIBRARY_PATH="$CYCLONEDDS_COMPAT_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
export PYTHONPATH="$PROJECT_DIR:$PROJECT_DIR/vendor:$UNITREE_SDK2_PYTHON_PATH${PYTHONPATH:+:$PYTHONPATH}"

source "$PROJECT_DIR/scripts/require_g1_unitree_interface.sh"
G1_VOICE_NETWORK_INTERFACE="$G1_UNITREE_INTERFACE"
source "$PROJECT_DIR/scripts/load_g1_command_plane.sh"
G1_VOICE_VOLUME="${G1_VOICE_VOLUME:-60}"
G1_VOICE_WAKE_WORD="${G1_VOICE_WAKE_WORD:-小智小智}"
G1_VOICE_WAKE_ALIAS_1="${G1_VOICE_WAKE_ALIAS_1:-小志小志}"
G1_VOICE_WAKE_ALIAS_2="${G1_VOICE_WAKE_ALIAS_2:-小知小知}"
G1_VOICE_WAKE_REPLY="${G1_VOICE_WAKE_REPLY:-我在}"
G1_VOICE_WAKE_TIMEOUT="${G1_VOICE_WAKE_TIMEOUT:-10}"
G1_VOICE_MIN_COMMAND_CHARS="${G1_VOICE_MIN_COMMAND_CHARS:-2}"
G1_VOICE_ACCEPT_INTERIM="${G1_VOICE_ACCEPT_INTERIM:-true}"

VOICE_ARGS=(
  "$G1_VOICE_NETWORK_INTERFACE"
  --input-topic "$ROS2_INPUT_TOPIC"
  --response-topic "$ROS2_RESPONSE_TOPIC"
  --fixed-route-topic "$G1_FIXED_ROUTE_TOPIC"
  --volume "$G1_VOICE_VOLUME"
  --wake-word "$G1_VOICE_WAKE_WORD"
  --wake-alias "$G1_VOICE_WAKE_ALIAS_1"
  --wake-alias "$G1_VOICE_WAKE_ALIAS_2"
  --wake-reply "$G1_VOICE_WAKE_REPLY"
  --wake-timeout "$G1_VOICE_WAKE_TIMEOUT"
  --min-command-chars "$G1_VOICE_MIN_COMMAND_CHARS"
)
if [[ "$G1_VOICE_ACCEPT_INTERIM" == "true" ]]; then
  VOICE_ARGS+=(--accept-interim)
fi

exec "$PYTHON_BIN" "$PROJECT_DIR/ros2/g1_voice_bridge.py" "${VOICE_ARGS[@]}" "$@"
