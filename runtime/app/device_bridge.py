"""受限设备桥抽象：仅传递高层白名单动作。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import httpx

from app.config import Settings


class DeviceBridge(Protocol):
    async def get_status(self) -> dict[str, Any]: ...

    async def execute_action(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class HttpDeviceBridge:
    """兼容原有 HTTP 设备桥协议的客户端。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_status(self) -> dict[str, Any]:
        return await self._request("GET", "/status")

    async def execute_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/actions", payload)

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.settings.device_bridge_url:
            return {"error": "DEVICE_BRIDGE_URL is not configured"}
        headers: dict[str, str] = {}
        if self.settings.device_bridge_token:
            headers["Authorization"] = f"Bearer {self.settings.device_bridge_token}"
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.request(
                method,
                f"{self.settings.device_bridge_url.rstrip('/')}{path}",
                json=body,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"data": data}


class FileStatusBridge:
    """读取独立 ROS 2 进程写入的只读机器人状态快照。"""

    def __init__(self, status_file: Path) -> None:
        self.status_file = status_file

    async def get_status(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.status_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"online": False, "state": "waiting_for_g1_status_bridge", "mode": "g1_read_only", "emergency_stop": False}
        except (OSError, json.JSONDecodeError) as exc:
            return {"online": False, "state": "g1_status_unavailable", "mode": "g1_read_only", "error": str(exc), "emergency_stop": False}
        return payload if isinstance(payload, dict) else {"online": False, "state": "invalid_g1_status"}

    async def execute_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"denied": True, "reason": "G1 状态桥接器为只读模式，不允许发布机器人动作", "command": payload}


class Ros2TopicBridge:
    """将受控动作发布给 ROS 2/Unitree SDK 适配节点。

    不导入 rclpy，保证核心模块可在没有 ROS 2 的环境中测试。
    """

    def __init__(
        self,
        publish_action: Callable[[dict[str, Any]], None],
        action_result_timeout: float | None = None,
    ) -> None:
        self._publish_action = publish_action
        self._action_result_timeout = action_result_timeout
        self._pending_actions: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Future[dict[str, Any]]]] = {}
        self._latest_status: dict[str, Any] = {
            "online": False,
            "state": "waiting_for_robot_bridge",
            "emergency_stop": True,
            "mode": "ros2_topic",
        }

    def update_status(self, status: dict[str, Any]) -> None:
        self._latest_status = {"mode": "ros2_topic", **status}

    def update_action_result(self, result: dict[str, Any]) -> None:
        task_id = str(result.get("task_id", ""))
        pending = self._pending_actions.get(task_id)
        if pending is None:
            return
        loop, future = pending

        def complete() -> None:
            if not future.done():
                future.set_result(result)

        loop.call_soon_threadsafe(complete)

    async def get_status(self) -> dict[str, Any]:
        return dict(self._latest_status)

    async def execute_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = f"ros2-{uuid4()}"
        command = {"task_id": task_id, "source": "smart_center", **payload}
        if self._action_result_timeout is None:
            self._publish_action(command)
            return {"accepted": True, "task_id": task_id, "state": "queued", "mode": "ros2_topic"}

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_actions[task_id] = (loop, future)
        self._publish_action(command)
        try:
            result = await asyncio.wait_for(future, timeout=self._action_result_timeout)
            return {"mode": "ros2_topic", **result}
        except TimeoutError:
            return {
                "error": "等待 G1 动作结果超时",
                "task_id": task_id,
                "state": "timeout",
                "mode": "ros2_topic",
            }
        finally:
            self._pending_actions.pop(task_id, None)
