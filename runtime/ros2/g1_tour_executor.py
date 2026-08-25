#!/usr/bin/env python3
"""Execute one confirmed tour station entirely on G1."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from unitree_api.msg import Request


PROJECT = Path(os.environ.get("G1_PROJECT_DIR", "/home/unitree/智能中控"))
TOUR_CONFIG_PATH = (
    PROJECT / "data" / "embodied_lab_panorama_v2" / "tour_config.json"
)
GUIDE_1_TRIGGER = "下面我将展示爬坡行走"
PREFIX = f"/{os.environ.get('G1_ROBOT_ID', '')}/smart_center"
TOUR_RESULT_TOPIC = os.environ.get("G1_TOUR_RESULT_TOPIC", f"{PREFIX}/tour_result")
TOUR_REQUEST_TOPIC = os.environ.get("G1_TOUR_REQUEST_TOPIC", f"{PREFIX}/tour_request")
ACTION_REQUEST_TOPIC = os.environ.get(
    "ROS2_ACTION_REQUEST_TOPIC",
    f"{PREFIX}/robot_action_request",
)
ACTION_RESULT_TOPIC = os.environ.get(
    "ROS2_ACTION_RESULT_TOPIC",
    f"{PREFIX}/robot_action_result",
)
RESPONSE_TOPIC = os.environ.get("ROS2_RESPONSE_TOPIC", f"{PREFIX}/response_text")


class TourExecutor(Node):
    def __init__(self) -> None:
        super().__init__("g1_tour_executor")
        self.tour_result_publisher = self.create_publisher(
            String,
            TOUR_RESULT_TOPIC,
            10,
        )
        self.motion_request_publisher = self.create_publisher(
            String,
            ACTION_REQUEST_TOPIC,
            10,
        )
        self.speech_publisher = self.create_publisher(
            String,
            RESPONSE_TOPIC,
            10,
        )
        self.arm_action_publisher = self.create_publisher(
            Request,
            "/api/arm/request",
            10,
        )
        self.create_subscription(
            String,
            TOUR_REQUEST_TOPIC,
            self._on_tour_request,
            10,
        )
        self.create_subscription(
            String,
            ACTION_RESULT_TOPIC,
            self._on_motion_result,
            10,
        )
        self.create_subscription(
            String,
            ACTION_REQUEST_TOPIC,
            self._on_motion_request,
            10,
        )

        self.worker_lock = threading.Lock()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.motion_condition = threading.Condition()
        self.motion_results: dict[str, dict[str, Any]] = {}
        self.arm_request_sequence = int(time.time() * 1000)
        self.get_logger().info("G1网页导览编排器已启动")

    def _publish_result(self, payload: dict[str, Any]) -> None:
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.tour_result_publisher.publish(message)

    def _on_motion_result(self, message: String) -> None:
        try:
            result = json.loads(message.data)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(result, dict):
            return
        task_id = str(result.get("task_id", ""))
        if not task_id.startswith("tour-motion-"):
            return
        with self.motion_condition:
            self.motion_results[task_id] = result
            self.motion_condition.notify_all()

    def _on_motion_request(self, message: String) -> None:
        try:
            payload = json.loads(message.data)
        except (json.JSONDecodeError, TypeError):
            return
        if isinstance(payload, dict) and payload.get("action") == "stop":
            self.cancel_event.set()

    def _on_tour_request(self, message: String) -> None:
        try:
            payload = json.loads(message.data)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        if payload.get("action") == "cancel":
            self.cancel_event.set()
            return
        task_id = str(payload.get("task_id", ""))
        point_name = str(payload.get("point_name", ""))
        if payload.get("action") != "visit" or payload.get("confirmed") is not True:
            self._publish_result(
                {"task_id": task_id, "state": "denied", "reason": "导览任务未确认"}
            )
            return
        try:
            config = self._load_config()
            allowed_points = set(config.get("order", []))
        except Exception as exc:
            self._publish_result(
                {
                    "task_id": task_id,
                    "state": "error",
                    "error": f"读取导览路线失败：{exc}",
                }
            )
            return
        if point_name not in allowed_points:
            self._publish_result(
                {
                    "task_id": task_id,
                    "state": "denied",
                    "reason": "导览点不在当前已保存路线中",
                }
            )
            return
        with self.worker_lock:
            if self.worker is not None and self.worker.is_alive():
                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "denied",
                        "reason": "已有导览站任务正在执行",
                    }
                )
                return
            self.cancel_event.clear()
            self.worker = threading.Thread(
                target=self._run_visit,
                args=(task_id, point_name),
                daemon=True,
            )
            self.worker.start()

    @staticmethod
    def _load_config() -> dict[str, Any]:
        return json.loads(TOUR_CONFIG_PATH.read_text(encoding="utf-8"))

    def _wait_interruptible(self, duration: float) -> bool:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            if self.cancel_event.wait(timeout=min(0.1, remaining)):
                return False
        return True

    def _send_motion(
        self,
        parent_task_id: str,
        target: str,
        *,
        point_name: str | None = None,
        timeout: float = 600.0,
    ) -> tuple[bool, str]:
        if self.cancel_event.is_set():
            return False, "导览已停止"
        task_id = f"tour-motion-{uuid4().hex[:14]}"
        payload: dict[str, Any] = {
            "task_id": task_id,
            "robot_id": os.environ.get("G1_ROBOT_ID", ""),
            "source": "g1_tour_executor",
            "action": "move",
            "target": target,
            "speed": 0.22,
            "confirmed": True,
            "parent_task_id": parent_task_id,
        }
        if point_name is not None:
            payload["point_name"] = point_name
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        with self.motion_condition:
            self.motion_results.pop(task_id, None)
        self.motion_request_publisher.publish(message)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.cancel_event.is_set():
                return False, "导览已停止"
            with self.motion_condition:
                result = self.motion_results.get(task_id)
                if result is None:
                    self.motion_condition.wait(timeout=0.2)
                    continue
            state = str(result.get("state", ""))
            if state in {"queued", "running", ""}:
                time.sleep(0.1)
                continue
            with self.motion_condition:
                self.motion_results.pop(task_id, None)
            if state == "completed":
                return True, ""
            return False, str(
                result.get("error")
                or result.get("reason")
                or f"运动任务状态：{state}"
            )
        return False, f"运动任务{target}等待超时"

    def _perform_please(self) -> tuple[bool, str]:
        deadline = time.monotonic() + 5.0
        while (
            self.arm_action_publisher.get_subscription_count() == 0
            and time.monotonic() < deadline
        ):
            if self.cancel_event.wait(0.1):
                return False, "导览已停止"
        if self.arm_action_publisher.get_subscription_count() == 0:
            return False, "没有发现/api/arm/request示教动作服务"

        self.arm_request_sequence += 1
        request = Request()
        request.header.identity.id = self.arm_request_sequence
        request.header.identity.api_id = 7108
        request.header.lease.id = 0
        request.header.policy.priority = 0
        request.header.policy.noreply = False
        request.parameter = json.dumps(
            {"action_name": "Please"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.arm_action_publisher.publish(request)
        self.get_logger().warning("TOUR_PLEASE：已发送录制动作Please")
        if not self._wait_interruptible(3.8):
            return False, "导览已停止"
        return True, ""

    def _speak(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return True
        message = String()
        message.data = text
        self.speech_publisher.publish(message)
        self.get_logger().warning(f"TOUR_SPEECH：{text}")
        return self._wait_interruptible(max(2.0, len(text) / 4.5 + 1.5))

    def _phase(self, task_id: str, point_name: str, phase: str) -> None:
        self._publish_result(
            {
                "task_id": task_id,
                "state": "running",
                "point_name": point_name,
                "phase": phase,
            }
        )

    def _run_visit(self, task_id: str, point_name: str) -> None:
        try:
            config = self._load_config()
            station = config["stations"][point_name]
            speech = str(station.get("speech", "")).strip()
        except Exception as exc:
            self._publish_result(
                {"task_id": task_id, "state": "error", "error": f"读取导览配置失败：{exc}"}
            )
            return

        self._phase(task_id, point_name, "navigating")
        ok, reason = self._send_motion(
            task_id,
            "tour_goto",
            point_name=point_name,
        )
        if not ok:
            self._publish_result({"task_id": task_id, "state": "error", "error": reason})
            return

        if not self._wait_interruptible(0.8):
            self._publish_result({"task_id": task_id, "state": "stopped"})
            return

        self._phase(task_id, point_name, "please")
        ok, reason = self._perform_please()
        if not ok:
            self._publish_result({"task_id": task_id, "state": "error", "error": reason})
            return

        self._phase(task_id, point_name, "speaking")
        if point_name == "guide_1":
            # The trigger sentence is always the final sentence immediately
            # before the fixed ramp demonstration, regardless of how the
            # editable narration is arranged in the browser.
            narration = speech.replace(GUIDE_1_TRIGGER, "").strip("。！？ ")
            if narration and not self._speak(narration):
                self._publish_result({"task_id": task_id, "state": "stopped"})
                return
            if not self._speak(GUIDE_1_TRIGGER):
                self._publish_result({"task_id": task_id, "state": "stopped"})
                return
        elif not self._speak(speech):
            self._publish_result({"task_id": task_id, "state": "stopped"})
            return

        if point_name == "guide_1":
            fixed_route = (
                ("ramp_prepare", "preparing_ramp"),
                ("turning_forward", "turning_forward"),
                ("ramp_return", "straight_return"),
            )
            for target, phase in fixed_route:
                self._phase(task_id, point_name, phase)
                ok, reason = self._send_motion(task_id, target, timeout=900.0)
                if not ok:
                    self._publish_result(
                        {"task_id": task_id, "state": "error", "error": reason}
                    )
                    return
            # ramp_return now completes only after the robot has reached the
            # ramp start and then navigated to guide_1 standby.

        order = list(config.get("order", []))
        try:
            index = order.index(point_name)
        except ValueError:
            index = -1
        next_point = order[index + 1] if 0 <= index < len(order) - 1 else None
        self._publish_result(
            {
                "task_id": task_id,
                "state": "completed",
                "completed": True,
                "point_name": point_name,
                "next_point_name": next_point,
            }
        )


def main() -> None:
    rclpy.init()
    node = TourExecutor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
