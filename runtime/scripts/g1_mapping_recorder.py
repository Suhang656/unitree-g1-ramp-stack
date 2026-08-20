#!/usr/bin/env python3
"""Record Unitree mapping PointCloud2 data to an NX-local binary PCD.

This node is read-only with respect to the robot: it subscribes to mapping
points and writes periodic atomic snapshots on the NX filesystem. It never
publishes commands and never calls a Unitree RPC service.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import threading
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import PointCloud2, PointField


class MappingRecorder(Node):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__("g1_mapping_recorder")
        self.args = args
        self.output = Path(args.output).expanduser().resolve()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.started_monotonic = time.monotonic()
        self.started_unix = time.time()
        self.last_cloud_time = 0.0
        self.last_snapshot_time = 0.0
        self.frame_count = 0
        self.raw_point_count = 0
        self.valid_point_count = 0
        self.frame_id = ""
        self.voxels: dict[tuple[int, int, int], tuple[float, float, float]] = {}
        self.lock = threading.Lock()
        self.writer: threading.Thread | None = None
        self.last_write_error: str | None = None
        self.last_written_points = 0
        self.last_written_unix = 0.0

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=4,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.subscription = self.create_subscription(
            PointCloud2,
            args.topic,
            self.on_cloud,
            qos,
        )
        self.report_timer = self.create_timer(1.0, self.report)
        self.snapshot_timer = self.create_timer(
            max(1.0, args.snapshot_seconds),
            self.request_snapshot,
        )

    @staticmethod
    def xyz_array(message: PointCloud2) -> np.ndarray:
        fields = {field.name: field for field in message.fields}
        required = ("x", "y", "z")
        if not all(name in fields for name in required):
            return np.empty((0, 3), dtype=np.float32)
        if any(fields[name].datatype != PointField.FLOAT32 for name in required):
            return np.empty((0, 3), dtype=np.float32)

        endian = ">" if message.is_bigendian else "<"
        dtype = np.dtype(
            {
                "names": list(required),
                "formats": [endian + "f4"] * 3,
                "offsets": [int(fields[name].offset) for name in required],
                "itemsize": int(message.point_step),
            }
        )
        count = int(message.width) * int(message.height)
        structured = np.frombuffer(message.data, dtype=dtype, count=count)
        return np.column_stack(
            (structured["x"], structured["y"], structured["z"])
        ).astype(np.float32, copy=False)

    def on_cloud(self, message: PointCloud2) -> None:
        points = self.xyz_array(message)
        self.last_cloud_time = time.monotonic()
        self.frame_count += 1
        self.raw_point_count += len(points)
        self.frame_id = message.header.frame_id or ""
        if not len(points):
            return

        valid = np.isfinite(points).all(axis=1)
        limit = self.args.coordinate_limit
        valid &= np.abs(points[:, 0]) <= limit
        valid &= np.abs(points[:, 1]) <= limit
        valid &= np.abs(points[:, 2]) <= self.args.height_limit
        points = points[valid]
        self.valid_point_count += len(points)
        if not len(points):
            return

        keys = np.floor(points / self.args.voxel_size).astype(np.int32)
        _, unique_indices = np.unique(keys, axis=0, return_index=True)
        keys = keys[unique_indices]
        points = points[unique_indices]

        with self.lock:
            for key, point in zip(keys, points):
                self.voxels[(int(key[0]), int(key[1]), int(key[2]))] = (
                    float(point[0]),
                    float(point[1]),
                    float(point[2]),
                )

    def snapshot_points(self) -> np.ndarray:
        with self.lock:
            if not self.voxels:
                return np.empty((0, 3), dtype=np.float32)
            return np.asarray(list(self.voxels.values()), dtype=np.float32)

    def request_snapshot(self, final: bool = False) -> None:
        if self.writer is not None and self.writer.is_alive():
            if final:
                self.writer.join(timeout=30.0)
            else:
                return

        points = self.snapshot_points()
        if not len(points):
            return

        self.writer = threading.Thread(
            target=self.write_snapshot,
            args=(points, final),
            name="g1-pcd-writer",
            daemon=not final,
        )
        self.writer.start()
        if final:
            self.writer.join(timeout=60.0)

    def write_snapshot(self, points: np.ndarray, final: bool) -> None:
        temporary = self.output.with_suffix(self.output.suffix + ".tmp")
        metadata = self.output.with_suffix(".json")
        metadata_temporary = metadata.with_suffix(metadata.suffix + ".tmp")
        try:
            header = (
                "# .PCD v0.7\n"
                "VERSION 0.7\n"
                "FIELDS x y z\n"
                "SIZE 4 4 4\n"
                "TYPE F F F\n"
                "COUNT 1 1 1\n"
                f"WIDTH {len(points)}\n"
                "HEIGHT 1\n"
                "VIEWPOINT 0 0 0 1 0 0 0\n"
                f"POINTS {len(points)}\n"
                "DATA binary\n"
            ).encode("ascii")
            with temporary.open("wb") as stream:
                stream.write(header)
                stream.write(points.astype("<f4", copy=False).tobytes(order="C"))
                stream.flush()
            temporary.replace(self.output)

            minimum = points.min(axis=0).tolist()
            maximum = points.max(axis=0).tolist()
            info = {
                "output": str(self.output),
                "updated_at_unix": time.time(),
                "final": bool(final),
                "topic": self.args.topic,
                "frame_id": self.frame_id,
                "voxel_size_m": self.args.voxel_size,
                "point_count": int(len(points)),
                "frame_count": self.frame_count,
                "raw_point_count": self.raw_point_count,
                "valid_point_count": self.valid_point_count,
                "bounds": {"minimum_xyz": minimum, "maximum_xyz": maximum},
            }
            metadata_temporary.write_text(
                json.dumps(info, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            metadata_temporary.replace(metadata)
            self.last_write_error = None
            self.last_written_points = len(points)
            self.last_written_unix = time.time()
            self.last_snapshot_time = time.monotonic()
        except Exception as exc:  # keep recording even if a snapshot fails
            self.last_write_error = repr(exc)

    def report(self) -> None:
        now = time.monotonic()
        age = now - self.last_cloud_time if self.last_cloud_time else math.inf
        with self.lock:
            voxel_count = len(self.voxels)
        status = "等待首帧" if age == math.inf else ("正常" if age <= 2.0 else "中断")
        print(
            "G1_MAP_RECORD",
            f"status={status}",
            f"age={age:.2f}s" if age != math.inf else "age=-",
            f"frames={self.frame_count}",
            f"voxels={voxel_count}",
            f"saved={self.last_written_points}",
            f"file={self.output}",
            flush=True,
        )
        if self.last_write_error:
            print("G1_MAP_RECORD_ERROR", self.last_write_error, flush=True)

    def finish(self) -> None:
        print("正在写入最终NX本地PCD，请勿关闭终端……", flush=True)
        self.request_snapshot(final=True)
        if self.output.exists():
            print(
                "NX本地PCD保存完成：",
                self.output,
                "大小=",
                self.output.stat().st_size,
                "字节",
                flush=True,
            )
        else:
            print("NX本地PCD未生成", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record G1 mapping points locally")
    parser.add_argument(
        "--output",
        default="/home/unitree/g1_embodied_lab_panorama_v2_nx.pcd",
    )
    parser.add_argument(
        "--topic",
        default="/unitree/slam_mapping/points",
    )
    parser.add_argument("--voxel-size", type=float, default=0.06)
    parser.add_argument("--snapshot-seconds", type=float, default=30.0)
    parser.add_argument("--coordinate-limit", type=float, default=500.0)
    parser.add_argument("--height-limit", type=float, default=50.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rclpy.init()
    node = MappingRecorder(args)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.finish()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
