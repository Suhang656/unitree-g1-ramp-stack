#!/usr/bin/env bash
set -Eeo pipefail

PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"

source /opt/ros/humble/setup.bash
set +u

unset CYCLONEDDS_URI
unset CYCLONEDDS_HOME

export PYTHONPATH="$PROJECT${PYTHONPATH:+:$PYTHONPATH}"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0

exec /usr/bin/python3 -u \
"$PROJECT/scripts/g1_web_control.py" \
--host 0.0.0.0 \
--port "${G1_WEB_PORT:-8088}"
