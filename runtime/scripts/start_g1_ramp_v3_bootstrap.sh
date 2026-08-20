#!/usr/bin/env bash
set -Eeo pipefail

PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"
INTERFACE="${G1_NETWORK_INTERFACE:-enP8p1s0}"
MAP_PATH="${G1_INTERNAL_MAP_PATH:-/home/unitree/g1_internal_panorama_v2.pcd}"
START_X="${G1_FIXED_START_X:-0.024735889031391838}"
START_Y="${G1_FIXED_START_Y:--0.08662520735348705}"
START_YAW="${G1_FIXED_START_YAW:--0.3986063585212273}"
SDK_PATH="${UNITREE_SDK2_PYTHON_PATH:-/home/unitree/unitree_sdk2_python}"
CYCLONE_PREFIX="${CYCLONEDDS_COMPAT_PREFIX:-/home/unitree/cyclonedds-prefix}"
UNITREE_ROS_SETUP="${UNITREE_ROS2_SETUP:-/home/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash}"
DATA="$PROJECT/data/ramp_platform_v3"
RESULT="$DATA/fixed_start_result.json"
READY="$DATA/localization_ready.json"
ANNOUNCER="$PROJECT/scripts/g1_announce_localization_ready.py"

RETRY_SECONDS="${G1_LOCALIZATION_RETRY_SECONDS:-2}"
SLAM_RESET_WAIT_SECONDS="${G1_SLAM_RESET_WAIT_SECONDS:-3}"

mkdir -p "$DATA"

# 每次开机重新生成许可。
rm -f "$READY"

source /opt/ros/humble/setup.bash
source "$UNITREE_ROS_SETUP"

unset CYCLONEDDS_HOME

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="<CycloneDDS><Domain Id=\"any\"><General><Interfaces><NetworkInterface name=\"${INTERFACE}\"/></Interfaces></General></Domain></CycloneDDS>"
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0
export ROS2CLI_DISABLE_DAEMON=1

echo "G1固定起点快速定位：等待Mid360数据……"

SENSOR_READY=0

for ATTEMPT in \
1 2 3 4 5 6 7 8 9 10
do
    if \
        timeout 3s ros2 topic echo \
        /utlidar/cloud_livox_mid360 \
        sensor_msgs/msg/PointCloud2 \
        --once \
        --field width \
        >/dev/null 2>&1 \
        && \
        timeout 3s ros2 topic echo \
        /utlidar/imu_livox_mid360 \
        sensor_msgs/msg/Imu \
        --once \
        --field header.stamp \
        >/dev/null 2>&1
    then
        SENSOR_READY=1
        echo "Mid360点云和IMU已就绪"
        break
    fi

    echo "等待传感器：$ATTEMPT/10"
    sleep 1
done

if [[ "$SENSOR_READY" != "1" ]]
then
    echo "Mid360点云或IMU未就绪" >&2
    exit 1
fi

# 验证器启动时仍会读取结果文件，
# 固定模式下实际候选由环境变量覆盖。
/usr/bin/python3 - "$RESULT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])

data = {
    "success": False,
    "estimate": {},
    "coarse_candidates": [],
    "refined_candidates": [],
    "quality": {},
    "validation": {},
}

path.write_text(
    json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
PY

echo "清理旧的官方SLAM会话……"

PYTHONPATH="$PROJECT/vendor:$SDK_PATH" \
CYCLONEDDS_HOME="$CYCLONE_PREFIX" \
LD_LIBRARY_PATH="$CYCLONE_PREFIX/lib" \
timeout 12s \
/usr/bin/python3 -u \
"$PROJECT/scripts/g1_slam_cli.py" \
"$INTERFACE" \
close \
|| true

echo "等待官方SLAM完成内部清理……"
sleep "$SLAM_RESET_WAIT_SECONDS"

ATTEMPT=0

while true
do
    ATTEMPT=$((ATTEMPT + 1))

    echo "开始固定起点快速定位，第${ATTEMPT}轮……"

    set +e

    G1_FIXED_START_FAST_BOOT=1 \
    G1_FIXED_START_X="$START_X" \
    G1_FIXED_START_Y="$START_Y" \
    G1_FIXED_START_YAW="$START_YAW" \
    G1_LOCALIZATION_CANDIDATE_DELAY_SECONDS=0.15 \
    /usr/bin/python3 -u \
    "$PROJECT/scripts/g1_verify_global_candidates.py" \
    --result "$RESULT" \
    --map "$MAP_PATH" \
    --interface "$INTERFACE" \
    --ready "$READY"

    VERIFY_STATUS=$?

    set -e

    if [[ "$VERIFY_STATUS" == "0" && -s "$READY" ]]
    then
        if /usr/bin/python3 - "$READY" <<'PY'
import json
import sys
from pathlib import Path

ready_path = Path(sys.argv[1])
boot_id = Path(
    "/proc/sys/kernel/random/boot_id"
).read_text(encoding="utf-8").strip()
data = json.loads(
    ready_path.read_text(encoding="utf-8")
)

raise SystemExit(
    0
    if (
        data.get("success") is True
        and data.get("boot_id") == boot_id
    )
    else 1
)
PY
        then
            echo "G1固定起点快速定位完成，共${ATTEMPT}轮"

            env \
            -u CYCLONEDDS_URI \
            -u CYCLONEDDS_HOME \
            RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
            ROS_DOMAIN_ID=0 \
            ROS_LOCALHOST_ONLY=0 \
            /usr/bin/python3 -u \
            "$ANNOUNCER" \
            || echo "定位成功，但语音播报发送失败" >&2

            exit 0
        fi
    fi

    echo "第${ATTEMPT}轮定位未成功，重置SLAM后重试"

    PYTHONPATH="$PROJECT/vendor:$SDK_PATH" \
    CYCLONEDDS_HOME="$CYCLONE_PREFIX" \
    LD_LIBRARY_PATH="$CYCLONE_PREFIX/lib" \
    timeout 8s \
    /usr/bin/python3 -u \
    "$PROJECT/scripts/g1_slam_cli.py" \
    "$INTERFACE" \
    close \
    || true

    sleep "$SLAM_RESET_WAIT_SECONDS"
    sleep "$RETRY_SECONDS"
done
