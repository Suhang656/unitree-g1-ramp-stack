#!/usr/bin/env python3

import json
import math
import statistics
import sys
import time
from pathlib import Path

import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)


if len(sys.argv) != 2:
    raise SystemExit(
        "用法：capture_turning_waypoint.py 输出JSON"
    )

output = Path(sys.argv[1])
output.parent.mkdir(
    parents=True,
    exist_ok=True,
)

samples = []

qos = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
)

rclpy.init()

node = rclpy.create_node(
    "g1_turning_waypoint_capture"
)


def odom_callback(message):
    position = message.pose.pose.position
    orientation = message.pose.pose.orientation

    yaw = math.atan2(
        2.0 * (
            orientation.w * orientation.z
            + orientation.x * orientation.y
        ),
        1.0 - 2.0 * (
            orientation.y * orientation.y
            + orientation.z * orientation.z
        ),
    )

    samples.append(
        (
            float(position.x),
            float(position.y),
            float(yaw),
        )
    )


subscription = node.create_subscription(
    Odometry,
    "/unitree/slam_relocation/odom",
    odom_callback,
    qos,
)

print("保持机器人静止，开始采集拐点……")

deadline = time.monotonic() + 15.0

while (
    time.monotonic() < deadline
    and len(samples) < 50
):
    rclpy.spin_once(
        node,
        timeout_sec=0.2,
    )

node.destroy_node()
rclpy.shutdown()

if len(samples) < 10:
    raise SystemExit(
        "采集失败：只收到"
        f"{len(samples)}个里程计样本"
    )

x = statistics.median(
    sample[0] for sample in samples
)

y = statistics.median(
    sample[1] for sample in samples
)

mean_sin = sum(
    math.sin(sample[2])
    for sample in samples
) / len(samples)

mean_cos = sum(
    math.cos(sample[2])
    for sample in samples
) / len(samples)

yaw = math.atan2(
    mean_sin,
    mean_cos,
)

position_spread = max(
    math.hypot(
        sample[0] - x,
        sample[1] - y,
    )
    for sample in samples
)

result = {
    "success": True,
    "samples": len(samples),
    "x": x,
    "y": y,
    "yaw": yaw,
    "yaw_degrees": math.degrees(yaw),
    "position_spread_meters": position_spread,
    "created_at_unix": time.time(),
}

temporary = output.with_suffix(
    output.suffix + ".tmp"
)

temporary.write_text(
    json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

temporary.replace(output)

print("===== 拐点采集成功 =====")
print("样本数：", len(samples))
print("x：", round(x, 6))
print("y：", round(y, 6))
print("yaw：", round(yaw, 6))
print(
    "朝向：",
    round(math.degrees(yaw), 3),
    "度",
)
print(
    "位置波动：",
    round(position_spread, 4),
    "米",
)
print("文件：", output)
