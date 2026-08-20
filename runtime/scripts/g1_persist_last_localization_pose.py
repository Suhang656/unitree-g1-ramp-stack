#!/usr/bin/env python3

import json
import math
import os
import time
from pathlib import Path

import rclpy

from nav_msgs.msg import Odometry
from rclpy.executors import (
    ExternalShutdownException,
)
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)


PROJECT = Path(os.environ.get("G1_PROJECT_DIR", "/home/unitree/智能中控"))
ROOT = PROJECT / "data" / "ramp_platform_v3"
MAP_PATH = os.environ.get(
    "G1_INTERNAL_MAP_PATH",
    "/home/unitree/g1_internal_panorama_v2.pcd",
)

READY_PATH = ROOT / "localization_ready.json"
LAST_PATH = ROOT / "last_localization_pose.json"
BOOT_ID_PATH = Path(
    "/proc/sys/kernel/random/boot_id"
)

last_write_monotonic = 0.0

qos = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
)


def current_boot_id():
    return BOOT_ID_PATH.read_text(
        encoding="utf-8"
    ).strip()


def ready_for_current_boot():
    try:
        data = json.loads(
            READY_PATH.read_text(
                encoding="utf-8"
            )
        )

        return (
            data.get("success") is True
            and data.get("boot_id")
            == current_boot_id()
        )
    except Exception:
        return False


def callback(message):
    global last_write_monotonic

    now = time.monotonic()

    if now - last_write_monotonic < 1.0:
        return

    if not ready_for_current_boot():
        return

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

    x = float(position.x)
    y = float(position.y)
    yaw = float(yaw)

    if not all(
        math.isfinite(value)
        for value in (x, y, yaw)
    ):
        return

    # 坡道V3地图的宽松安全边界。
    if not (
        -30.0 <= x <= 35.0
        and -15.0 <= y <= 15.0
    ):
        return

    output = {
        "success": True,
        "updated_at_unix": time.time(),
        "source_boot_id": current_boot_id(),
        "map_path": MAP_PATH,
        "pose": {
            "x": x,
            "y": y,
            "yaw": yaw,
        },
    }

    temporary = LAST_PATH.with_suffix(
        ".json.tmp"
    )

    temporary.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary.replace(LAST_PATH)
    last_write_monotonic = now


def main():
    ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    rclpy.init()

    node = rclpy.create_node(
        "g1_last_localization_pose_recorder"
    )

    subscription = node.create_subscription(
        Odometry,
        "/unitree/slam_relocation/odom",
        callback,
        qos,
    )

    print(
        "G1最后可信全局姿态记录器已启动",
        flush=True,
    )

    try:
        rclpy.spin(node)
    except (
        KeyboardInterrupt,
        ExternalShutdownException,
    ):
        pass
    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
