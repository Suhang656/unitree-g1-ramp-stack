#!/usr/bin/env bash
# Local-only ROS command plane. Source this after the ROS 2 setup file.

G1_ROBOT_ID="${G1_ROBOT_ID:-}"
if [[ ! "$G1_ROBOT_ID" =~ ^[a-z0-9][a-z0-9_-]{0,31}$ ]]; then
  echo "G1_ROBOT_ID 未配置或格式无效；拒绝启动控制节点。" >&2
  echo "请在 /etc/default/g1-ramp-stack 中为每台 G1 设置不同的小写ID。" >&2
  return 1 2>/dev/null || exit 1
fi

G1_COMMAND_ROS_DOMAIN_ID="${G1_COMMAND_ROS_DOMAIN_ID:-0}"
if [[ ! "$G1_COMMAND_ROS_DOMAIN_ID" =~ ^[0-9]+$ ]] \
  || (( G1_COMMAND_ROS_DOMAIN_ID < 0 || G1_COMMAND_ROS_DOMAIN_ID > 232 )); then
  echo "G1_COMMAND_ROS_DOMAIN_ID 必须是 0 到 232。" >&2
  return 1 2>/dev/null || exit 1
fi

G1_COMMAND_PREFIX="/${G1_ROBOT_ID}/smart_center"

export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID="$G1_COMMAND_ROS_DOMAIN_ID"
export ROS_LOCALHOST_ONLY=1
export ROS2CLI_DISABLE_DAEMON=1

# Security boundary: never allow legacy .env or a caller shell to replace these
# local, robot-scoped topics with the old shared /smart_center names.
export ROS2_INPUT_TOPIC="${G1_COMMAND_PREFIX}/input_text"
export ROS2_RESPONSE_TOPIC="${G1_COMMAND_PREFIX}/response_text"
export ROS2_ACTION_REQUEST_TOPIC="${G1_COMMAND_PREFIX}/robot_action_request"
export ROS2_ACTION_RESULT_TOPIC="${G1_COMMAND_PREFIX}/robot_action_result"
export ROS2_ROBOT_STATUS_TOPIC="${G1_COMMAND_PREFIX}/robot_status"
export ROS2_STATUS_TOPIC="${G1_COMMAND_PREFIX}/status"
export ROS2_EMERGENCY_STOP_TOPIC="${G1_COMMAND_PREFIX}/emergency_stop"
export G1_FIXED_ROUTE_TOPIC="${G1_COMMAND_PREFIX}/fixed_route_request"
export G1_TOUR_REQUEST_TOPIC="${G1_COMMAND_PREFIX}/tour_request"
export G1_TOUR_RESULT_TOPIC="${G1_COMMAND_PREFIX}/tour_result"

