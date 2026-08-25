#!/usr/bin/env python3
"""Smart Center ROS 2 节点。

仅使用高层文本、状态和动作话题；不直接发布 G1 关节控制指令。
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import Future
from typing import Any

from app.device_bridge import Ros2TopicBridge
from app.ros2_processor import Ros2CommandProcessor
from app.runtime import SmartCenterRuntime


class AsyncWorker:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def submit(self, coroutine: Any) -> Future:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()


def main() -> None:
    try:
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import Bool, String
    except ImportError as exc:
        raise SystemExit("未找到 rclpy。请在与 ROS 2 发行版匹配的 Python 环境中运行此节点。") from exc

    class SmartCenterRos2Node(Node):
        def __init__(self, worker: AsyncWorker, runtime: SmartCenterRuntime) -> None:
            settings = runtime.settings
            assert settings is not None and runtime.tools is not None
            super().__init__(settings.ros2_node_name)
            self.worker = worker
            self.runtime = runtime
            self.response_publisher = self.create_publisher(String, settings.ros2_response_topic, 10)
            self.status_publisher = self.create_publisher(String, settings.ros2_status_topic, 10)
            self.action_publisher = self.create_publisher(String, settings.ros2_action_request_topic, 10)
            self.bridge = Ros2TopicBridge(self._publish_action, action_result_timeout=30.0)
            runtime.tools.device_bridge = self.bridge
            self.processor = Ros2CommandProcessor(runtime, settings.ros2_session_title)
            worker.submit(self.processor.start()).result(timeout=10)
            self.create_subscription(String, settings.ros2_input_topic, self._on_input, 10)
            self.create_subscription(String, settings.ros2_robot_status_topic, self._on_robot_status, 10)
            self.create_subscription(String, settings.ros2_action_result_topic, self._on_action_result, 10)
            self.create_subscription(Bool, settings.ros2_emergency_stop_topic, self._on_emergency_stop, 10)
            self.create_timer(1.0, self._publish_status)
            self.get_logger().info("Smart Center ROS 2 节点已启动；真实动作默认禁用。")

        @staticmethod
        def _json_message(payload: dict[str, Any]) -> Any:
            message = String()
            message.data = json.dumps(payload, ensure_ascii=False)
            return message

        def _publish_action(self, payload: dict[str, Any]) -> None:
            command = dict(payload)
            command["robot_id"] = os.environ.get("G1_ROBOT_ID", "")
            self.action_publisher.publish(self._json_message(command))

        def _on_input(self, message: Any) -> None:
            text = message.data.strip()
            if not text:
                return
            self.worker.submit(self.processor.handle_text(text)).add_done_callback(self._on_agent_done)

        def _on_agent_done(self, future: Future) -> None:
            try:
                result = future.result()
                self.response_publisher.publish(self._json_message({
                    "session_id": result.session_id,
                    "text": result.content,
                    "citations": [item.model_dump(mode="json") for item in result.citations],
                    "tool_executions": [item.model_dump(mode="json") for item in result.tool_executions],
                }))
            except Exception as exc:
                self.get_logger().error(f"处理输入失败: {exc}")
                self.response_publisher.publish(self._json_message({"error": str(exc)}))

        def _on_robot_status(self, message: Any) -> None:
            try:
                status = json.loads(message.data)
                if isinstance(status, dict):
                    self.bridge.update_status(status)
            except json.JSONDecodeError:
                self.get_logger().warning("忽略非 JSON 的机器人状态消息")

        def _on_action_result(self, message: Any) -> None:
            try:
                result = json.loads(message.data)
                if isinstance(result, dict):
                    self.bridge.update_action_result(result)
            except json.JSONDecodeError:
                self.get_logger().warning("忽略非 JSON 的动作结果消息")

        def _on_emergency_stop(self, message: Any) -> None:
            if message.data:
                self.worker.submit(self.processor.emergency_stop()).add_done_callback(self._on_stop_done)

        def _on_stop_done(self, future: Future) -> None:
            try:
                result = future.result()
                self.response_publisher.publish(self._json_message({"emergency_stop": result.model_dump(mode="json")}))
            except Exception as exc:
                self.get_logger().error(f"紧急停止转发失败: {exc}")

        def _publish_status(self) -> None:
            self.worker.submit(self.processor.get_robot_status()).add_done_callback(self._on_status_done)

        def _on_status_done(self, future: Future) -> None:
            try:
                self.status_publisher.publish(self._json_message(future.result()))
            except Exception as exc:
                self.get_logger().warning(f"状态查询失败: {exc}")

    worker = AsyncWorker()
    runtime = SmartCenterRuntime()
    try:
        worker.submit(runtime.start()).result(timeout=30)
        rclpy.init()
        node = SmartCenterRos2Node(worker, runtime)
        try:
            rclpy.spin(node)
        finally:
            node.destroy_node()
            rclpy.shutdown()
    finally:
        try:
            worker.submit(runtime.close()).result(timeout=10)
        except Exception:
            pass
        worker.close()


if __name__ == "__main__":
    main()
