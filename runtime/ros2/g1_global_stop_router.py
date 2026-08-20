#!/usr/bin/env python3

import json
import re
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String


STOP_COMMANDS = {
    "停止",
    "停下",
    "立即停止",
    "紧急停止",
    "停止行走",
    "停止导览",
    "停止导览服务",
}


def normalize(text: str) -> str:
    return re.sub(
        r"[\s，。！？、,.!?]+",
        "",
        text,
    )


class GlobalStopRouter(Node):
    def __init__(self) -> None:
        super().__init__("g1_global_stop_router")

        self.route_publisher = self.create_publisher(
            String,
            "/smart_center/fixed_route_request",
            10,
        )

        self.motion_publisher = self.create_publisher(
            String,
            "/smart_center/robot_action_request",
            10,
        )

        self.create_subscription(
            String,
            "/smart_center/input_text",
            self._on_input_text,
            10,
        )

        # 兼容语音桥或台式机中继直接发出的路线停止指令。
        self.create_subscription(
            String,
            "/smart_center/fixed_route_request",
            self._on_route_request,
            10,
        )

        self.last_stop_time = 0.0

        self.get_logger().info(
            "G1全局停止路由器已启动："
            "停止导览 + 停止运动，保持当前运动模式"
        )

    def _publish_motion_stop(self) -> None:
        message = String()

        message.data = json.dumps(
            {
                "task_id": (
                    "global-stop-"
                    + str(time.time_ns())
                ),
                "action": "stop",
                "confirmed": True,
            },
            ensure_ascii=False,
        )

        self.motion_publisher.publish(message)

    def _trigger_stop(
        self,
        source: str,
        publish_route_stop: bool,
    ) -> None:
        now = time.monotonic()

        # 防止同一条停止指令通过多个话题重复执行。
        if now - self.last_stop_time < 0.6:
            return

        self.last_stop_time = now

        if publish_route_stop:
            route_message = String()
            route_message.data = "stop"
            self.route_publisher.publish(
                route_message
            )

        self._publish_motion_stop()

        self.get_logger().warning(
            "GLOBAL_STOP："
            f"来源={source}，"
            "已取消导览并停止全部运动；"
            "保持运动模式静止站立"
        )

    def _on_input_text(
        self,
        message: String,
    ) -> None:
        command = normalize(message.data)

        if command not in STOP_COMMANDS:
            return

        self._trigger_stop(
            source=f"input_text:{command}",
            publish_route_stop=True,
        )

    def _on_route_request(
        self,
        message: String,
    ) -> None:
        if normalize(message.data) != "stop":
            return

        self._trigger_stop(
            source="fixed_route_request:stop",
            publish_route_stop=False,
        )


def main() -> None:
    rclpy.init()
    node = GlobalStopRouter()

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
