#!/usr/bin/env python3

import json
import math
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

OUTPUT = Path("/run/g1-ramp/odom.json")
BOOT_ID = Path(
    "/proc/sys/kernel/random/boot_id"
).read_text(encoding="utf-8").strip()

last_write = 0.0


def callback(message):
    global last_write

    now = time.monotonic()

    if now - last_write < 0.1:
        return

    last_write = now

    pose = message.pose.pose
    q = pose.orientation

    yaw = math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )

    payload = {
        "boot_id": BOOT_ID,
        "updated_at_unix": time.time(),
        "x": float(pose.position.x),
        "y": float(pose.position.y),
        "yaw": float(yaw),
    }

    temporary = OUTPUT.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    temporary.replace(OUTPUT)


rclpy.init()

node = rclpy.create_node(
    "g1_ramp_odom_cache"
)

qos = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
)

subscription = node.create_subscription(
    Odometry,
    "/unitree/slam_relocation/odom",
    callback,
    qos,
)

print("G1坡道实时里程计缓存已启动")

try:
    rclpy.spin(node)
except KeyboardInterrupt:
    pass
finally:
    node.destroy_node()

    if rclpy.ok():
        rclpy.shutdown()
