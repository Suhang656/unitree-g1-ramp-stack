#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"
INTERFACE="${G1_NETWORK_INTERFACE:-enP8p1s0}"
CONTROL_IP="${G1_CONTROL_IP:-192.168.123.161}"
SDK="${UNITREE_SDK2_PYTHON_PATH:-/home/unitree/unitree_sdk2_python}"
ROS_SETUP="${UNITREE_ROS2_SETUP:-/home/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash}"
CYCLONE="${CYCLONEDDS_COMPAT_PREFIX:-/home/unitree/cyclonedds-prefix}"

failures=0
check_path() {
  local label="$1" path="$2"
  if [[ -e "$path" ]]; then
    printf '[OK]   %-24s %s\n' "$label" "$path"
  else
    printf '[FAIL] %-24s %s\n' "$label" "$path"
    failures=$((failures + 1))
  fi
}

echo "===== Unitree G1 部署前只读检查 ====="
check_path "ROS Humble" /opt/ros/humble/setup.bash
check_path "Unitree ROS 2" "$ROS_SETUP"
check_path "Unitree SDK2 Python" "$SDK/unitree_sdk2py"
check_path "CycloneDDS compatibility" "$CYCLONE/lib"
check_path "内部网卡" "/sys/class/net/$INTERFACE"
check_path "项目父目录" "$(dirname "$PROJECT")"

if ping -c 1 -W 1 "$CONTROL_IP" >/dev/null 2>&1; then
  printf '[OK]   %-24s %s\n' "内部控制单元" "$CONTROL_IP"
else
  printf '[FAIL] %-24s %s\n' "内部控制单元" "$CONTROL_IP"
  failures=$((failures + 1))
fi

if [[ "$(id -un)" == "unitree" ]]; then
  echo "[OK]   当前用户                 unitree"
else
  echo "[WARN] 推荐以 unitree 用户执行，当前为 $(id -un)"
fi

if [[ "$failures" -ne 0 ]]; then
  echo "检查未通过：$failures 项。没有修改系统，也没有发送运动命令。" >&2
  exit 1
fi

echo "检查通过。该命令未修改系统，也未发送运动命令。"
