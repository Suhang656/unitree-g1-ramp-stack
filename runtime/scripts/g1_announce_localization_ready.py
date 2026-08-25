#!/usr/bin/env python3

import json
import os
import os
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


PROJECT = Path(os.environ.get("G1_PROJECT_DIR", "/home/unitree/智能中控"))
READY_PATH = PROJECT / "data" / "ramp_platform_v3" / "localization_ready.json"

BOOT_ID_PATH = Path(
    "/proc/sys/kernel/random/boot_id"
)

ANNOUNCED_PATH = Path(
    "/run/g1-ramp/localization_announced.json"
)


def verify_ready():
    if not READY_PATH.exists():
        raise SystemExit(
            "本次开机定位许可文件不存在，不播报"
        )

    data = json.loads(
        READY_PATH.read_text(encoding="utf-8")
    )

    boot_id = BOOT_ID_PATH.read_text(
        encoding="utf-8"
    ).strip()

    if data.get("success") is not True:
        raise SystemExit(
            "定位许可未标记成功，不播报"
        )

    if data.get("boot_id") != boot_id:
        raise SystemExit(
            "定位许可不属于本次开机，不播报"
        )

    return data


def main():
    data = verify_ready()

    boot_id = data["boot_id"]

    try:
        announced = json.loads(
            ANNOUNCED_PATH.read_text(
                encoding="utf-8"
            )
        )
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
    ):
        announced = {}

    if announced.get("boot_id") == boot_id:
        print(
            "本次开机已经播报过全局定位成功",
            flush=True,
        )
        return

    rclpy.init()

    node = Node(
        "g1_localization_success_announcer"
    )

    publisher = node.create_publisher(
        String,
        os.environ.get(
            "ROS2_RESPONSE_TOPIC",
            "/invalid_unconfigured_g1/response_text",
        ),
        10,
    )

    deadline = time.monotonic() + 30.0

    while (
        publisher.get_subscription_count() < 1
        and time.monotonic() < deadline
    ):
        rclpy.spin_once(
            node,
            timeout_sec=0.2,
        )

    if publisher.get_subscription_count() < 1:
        node.destroy_node()
        rclpy.shutdown()
        raise SystemExit(
            "没有发现语音桥订阅端，未播报"
        )

    message = String()
    message.data = "全局定位成功"

    publisher.publish(message)

    for _ in range(10):
        rclpy.spin_once(
            node,
            timeout_sec=0.1,
        )

    ANNOUNCED_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = ANNOUNCED_PATH.with_suffix(
        f".{os.getpid()}.tmp"
    )

    temporary.write_text(
        json.dumps(
            {
                "boot_id": boot_id,
                "announced_at_unix": time.time(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    temporary.replace(ANNOUNCED_PATH)

    pose = data.get("pose", {})

    print(
        "全局定位成功播报已发送，姿态：",
        pose,
        flush=True,
    )

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
