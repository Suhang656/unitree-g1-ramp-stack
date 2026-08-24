#!/usr/bin/env bash
set -Eeo pipefail

PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"
SDK_PATH="${G1_UNITREE_SDK2_PATH:-/home/unitree/unitree_sdk2_python}"
ROS_SETUP="/opt/ros/${ROS_DISTRO:-humble}/setup.bash"

[[ -f "$ROS_SETUP" ]] || {
  echo "缺少ROS环境：$ROS_SETUP" >&2
  exit 1
}

source "$ROS_SETUP"
set -u

PYTHONPATH="$PROJECT:$PROJECT/vendor:$SDK_PATH${PYTHONPATH:+:$PYTHONPATH}" \
  /usr/bin/python3 - <<'PY'
import fastapi
import httpx
import numpy
import pydantic
import pydantic_settings
import uvicorn

from app.config import Settings
from app.device_bridge import Ros2TopicBridge

print("PYTHON_RUNTIME_OK")
print("httpx", httpx.__version__)
print("pydantic", pydantic.__version__)
PY
