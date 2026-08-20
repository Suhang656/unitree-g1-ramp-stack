#!/usr/bin/env bash
set -Eeo pipefail

PROJECT_DIR="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
  pwd
)"

SMART_CENTER_PID=""
VOICE_BRIDGE_PID=""
MOTION_BRIDGE_PID=""

stop_children() {
  trap - EXIT INT TERM

  for PID in \
    "$VOICE_BRIDGE_PID" \
    "$SMART_CENTER_PID" \
    "$MOTION_BRIDGE_PID"
  do
    if [[ -n "$PID" ]]
    then
      kill -TERM "$PID" 2>/dev/null || true
    fi
  done

  wait \
    "$VOICE_BRIDGE_PID" \
    "$SMART_CENTER_PID" \
    "$MOTION_BRIDGE_PID" \
    2>/dev/null || true
}

trap stop_children EXIT INT TERM

echo "启动G1本地智能中控节点……"
bash "$PROJECT_DIR/scripts/start_ros2_node.sh" &
SMART_CENTER_PID=$!

if [[ "${G1_EXTERNAL_VOICE_BRIDGE:-0}" != "1" ]]
then
  echo "启动G1内置STT/TTS语音桥……"
  bash "$PROJECT_DIR/scripts/start_g1_voice_bridge.sh" &
  VOICE_BRIDGE_PID=$!
else
  echo "G1语音桥由独立开机服务管理"
fi

echo "启动G1受控高层运动桥……"
bash "$PROJECT_DIR/scripts/start_g1_motion_bridge.sh" &
MOTION_BRIDGE_PID=$!

if [[ -n "$VOICE_BRIDGE_PID" ]]
then
  wait -n \
    "$SMART_CENTER_PID" \
    "$VOICE_BRIDGE_PID" \
    "$MOTION_BRIDGE_PID"
else
  wait -n \
    "$SMART_CENTER_PID" \
    "$MOTION_BRIDGE_PID"
fi

echo "G1语音助手核心进程退出，交由systemd重启。" >&2
exit 1
