#!/usr/bin/env bash
set -e

PROJECT_DIR="${G1_PROJECT_DIR:-/home/unitree/智能中控}"
NETWORK_INTERFACE="${G1_NETWORK_INTERFACE:-enP8p1s0}"
CONTROL_IP="${G1_CONTROL_IP:-192.168.123.161}"
SDK_PATH="${UNITREE_SDK2_PYTHON_PATH:-/home/unitree/unitree_sdk2_python}"
CYCLONE_PREFIX="${CYCLONEDDS_COMPAT_PREFIX:-/home/unitree/cyclonedds-prefix}"

echo "等待G1内部运控计算单元……"

for attempt in $(seq 1 90)
do
    if ping -c 1 -W 1 \
        "$CONTROL_IP" \
        >/dev/null 2>&1
    then
        echo "内部运控计算单元已连接"
        break
    fi

    if [[ "$attempt" -eq 90 ]]
    then
        echo "等待${CONTROL_IP}超时" >&2
        exit 1
    fi

    sleep 1
done

export PYTHONPATH="$PROJECT_DIR/vendor:$SDK_PATH"
export CYCLONEDDS_HOME="$CYCLONE_PREFIX"
export LD_LIBRARY_PATH="$CYCLONE_PREFIX/lib"

exec /usr/bin/python3 -u \
"$PROJECT_DIR/scripts/g1_enable_navigation_services.py" \
"$NETWORK_INTERFACE"
