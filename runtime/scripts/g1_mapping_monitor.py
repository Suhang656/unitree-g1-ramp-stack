#!/usr/bin/env python3
"""Read-only terminal monitor for Unitree G1 SLAM mapping.

The node only subscribes to ROS 2 topics. It never publishes commands and
never calls a Unitree RPC service.
"""

from __future__ import annotations

import argparse
from collections import deque
import math
import struct
import sys
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import PointCloud2


def finite(value: float) -> bool:
    return math.isfinite(value)


class MappingMonitor(Node):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__("g1_mapping_monitor")
        self.args = args
        self.started = time.monotonic()
        self.last_cloud_time = 0.0
        self.frame_times: deque[float] = deque()
        self.frame_count = 0
        self.current_points = 0
        self.total_points = 0
        self.sampled_valid_points = 0
        self.frame_id = "-"
        self.minimum_x = math.inf
        self.maximum_x = -math.inf
        self.minimum_y = math.inf
        self.maximum_y = -math.inf
        self.minimum_z = math.inf
        self.maximum_z = -math.inf
        self.voxels: set[tuple[int, int]] = set()
        self.previous_voxel_count = 0
        self.odom: dict[str, dict[str, float | None]] = {}

        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=2,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )

        self.cloud_subscription = self.create_subscription(
            PointCloud2,
            args.cloud_topic,
            self.on_cloud,
            sensor_qos,
        )

        self.odom_subscriptions = []
        for topic in args.odom_topics:
            self.odom[topic] = {
                "time": 0.0,
                "x": None,
                "y": None,
                "distance": 0.0,
            }
            subscription = self.create_subscription(
                Odometry,
                topic,
                lambda message, name=topic: self.on_odom(name, message),
                sensor_qos,
            )
            self.odom_subscriptions.append(subscription)

        self.timer = self.create_timer(args.interval, self.report)

    def on_cloud(self, message: PointCloud2) -> None:
        now = time.monotonic()
        self.last_cloud_time = now
        self.frame_times.append(now)
        while self.frame_times and now - self.frame_times[0] > 5.0:
            self.frame_times.popleft()

        point_count = int(message.width) * int(message.height)
        self.frame_count += 1
        self.current_points = point_count
        self.total_points += point_count
        self.frame_id = message.header.frame_id or "-"

        fields = {field.name: field for field in message.fields}
        if not all(name in fields for name in ("x", "y", "z")):
            return

        step = max(1, point_count // self.args.maximum_samples)
        byte_order = ">" if message.is_bigendian else "<"
        data = memoryview(message.data)
        point_step = int(message.point_step)
        offsets = tuple(int(fields[name].offset) for name in ("x", "y", "z"))
        unpack_float = struct.Struct(byte_order + "f").unpack_from
        voxel_size = self.args.voxel_size

        for index in range(0, point_count, step):
            base = index * point_step
            try:
                x = unpack_float(data, base + offsets[0])[0]
                y = unpack_float(data, base + offsets[1])[0]
                z = unpack_float(data, base + offsets[2])[0]
            except (struct.error, IndexError):
                break

            if not (finite(x) and finite(y) and finite(z)):
                continue

            if abs(x) > self.args.coordinate_limit or abs(y) > self.args.coordinate_limit:
                continue

            self.sampled_valid_points += 1
            self.minimum_x = min(self.minimum_x, x)
            self.maximum_x = max(self.maximum_x, x)
            self.minimum_y = min(self.minimum_y, y)
            self.maximum_y = max(self.maximum_y, y)
            self.minimum_z = min(self.minimum_z, z)
            self.maximum_z = max(self.maximum_z, z)
            self.voxels.add((math.floor(x / voxel_size), math.floor(y / voxel_size)))

    def on_odom(self, topic: str, message: Odometry) -> None:
        now = time.monotonic()
        x = float(message.pose.pose.position.x)
        y = float(message.pose.pose.position.y)
        state = self.odom[topic]
        previous_x = state["x"]
        previous_y = state["y"]

        if previous_x is not None and previous_y is not None:
            delta = math.hypot(x - float(previous_x), y - float(previous_y))
            # Ignore localization jumps; this is a progress indicator, not odometry.
            if delta <= 1.0:
                state["distance"] = float(state["distance"]) + delta

        state["time"] = now
        state["x"] = x
        state["y"] = y

    def newest_odom(self) -> tuple[str, dict[str, float | None]] | None:
        candidates = [item for item in self.odom.items() if float(item[1]["time"]) > 0.0]
        if not candidates:
            return None
        return max(candidates, key=lambda item: float(item[1]["time"]))

    def report(self) -> None:
        now = time.monotonic()
        age = now - self.last_cloud_time if self.last_cloud_time else math.inf
        if len(self.frame_times) >= 2:
            fps = (len(self.frame_times) - 1) / (self.frame_times[-1] - self.frame_times[0])
        else:
            fps = 0.0

        if self.args.clear and sys.stdout.isatty():
            print("\033[2J\033[H", end="")

        print("===== G1 建图实时反馈（只读） =====")
        print("运行时间：", round(now - self.started, 1), "秒")
        if age == math.inf:
            print("点云状态：等待首帧")
        else:
            status = "正常" if age <= 2.0 else "中断/过期"
            print("点云状态：", status, "年龄=", round(age, 2), "秒")
        print("点云话题：", self.args.cloud_topic)
        print("坐标系：", self.frame_id)
        print("帧率：", round(fps, 2), "Hz")
        print("累计帧数：", self.frame_count)
        print("当前帧点数：", self.current_points)
        print("累计输入点数：", self.total_points)

        voxel_count = len(self.voxels)
        new_voxels = voxel_count - self.previous_voxel_count
        self.previous_voxel_count = voxel_count
        print(
            "覆盖网格：",
            voxel_count,
            f"个（{self.args.voxel_size:.2f}m网格，本周期新增{new_voxels}）",
        )

        if self.sampled_valid_points:
            span_x = self.maximum_x - self.minimum_x
            span_y = self.maximum_y - self.minimum_y
            print(
                "地图边界X：",
                round(self.minimum_x, 2),
                "至",
                round(self.maximum_x, 2),
                "跨度=",
                round(span_x, 2),
                "米",
            )
            print(
                "地图边界Y：",
                round(self.minimum_y, 2),
                "至",
                round(self.maximum_y, 2),
                "跨度=",
                round(span_y, 2),
                "米",
            )
            print(
                "高度范围Z：",
                round(self.minimum_z, 2),
                "至",
                round(self.maximum_z, 2),
                "米",
            )
        else:
            print("地图边界：等待有效XYZ点")

        odom = self.newest_odom()
        if odom is None:
            print("里程计：当前没有可用建图里程计（不影响点云监控）")
        else:
            topic, state = odom
            odom_age = now - float(state["time"])
            print(
                "里程计：",
                topic,
                "x=",
                round(float(state["x"]), 3),
                "y=",
                round(float(state["y"]), 3),
                "估算行程=",
                round(float(state["distance"]), 2),
                "米",
                "年龄=",
                round(odom_age, 2),
                "秒",
            )

        if age > 2.0:
            print("告警：建图点云超过2秒未更新，请停止移动并检查SLAM。")
        elif fps < 5.0 and self.frame_count > 5:
            print("告警：建图点云帧率偏低。")
        else:
            print("建议：缓慢行走、保持重叠、形成闭环，最后回到起点。")
        print("按 Ctrl+C 只会退出监控，不会停止建图。", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="G1 SLAM mapping read-only monitor")
    parser.add_argument(
        "--cloud-topic",
        default="/unitree/slam_mapping/points",
    )
    parser.add_argument(
        "--odom-topic",
        action="append",
        dest="odom_topics",
        default=None,
        help="May be repeated; defaults to mapping and relocation odometry topics.",
    )
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--voxel-size", type=float, default=0.20)
    parser.add_argument("--maximum-samples", type=int, default=5000)
    parser.add_argument("--coordinate-limit", type=float, default=500.0)
    parser.add_argument("--no-clear", action="store_false", dest="clear")
    parser.set_defaults(clear=True)
    args = parser.parse_args()
    if args.odom_topics is None:
        args.odom_topics = [
            "/unitree/slam_mapping/odom",
            "/unitree/slam_relocation/odom",
        ]
    return args


def main() -> None:
    args = parse_args()
    rclpy.init()
    node = MappingMonitor(args)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
