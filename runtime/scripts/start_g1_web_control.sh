#!/usr/bin/env bash
set -Eeo pipefail

PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"

source /opt/ros/humble/setup.bash
set +u
export PYTHONPATH="$PROJECT${PYTHONPATH:+:$PYTHONPATH}"
source "$PROJECT/scripts/load_g1_command_plane.sh"

exec /usr/bin/python3 -u \
"$PROJECT/scripts/g1_web_control.py" \
--host 0.0.0.0 \
--port "${G1_WEB_PORT:-8088}" \
--request-topic "$ROS2_ACTION_REQUEST_TOPIC" \
--result-topic "$ROS2_ACTION_RESULT_TOPIC" \
--tour-request-topic "$G1_TOUR_REQUEST_TOPIC" \
--tour-result-topic "$G1_TOUR_RESULT_TOPIC"
