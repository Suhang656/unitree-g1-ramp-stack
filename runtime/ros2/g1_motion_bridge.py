#!/usr/bin/env python3
"""把受控参数化动作转换为 Unitree G1 高层运动调用。"""

from __future__ import annotations

import os
import subprocess

import argparse
import json
import math
import threading
import time
from pathlib import Path
from typing import Any

from app.g1_motion_commands import (
    CONTINUOUS_FORWARD_SPEED_MPS,
    CONTINUOUS_FORWARD_TARGET,
    RAMP_RETURN_TARGET,
    RAMP_PREPARE_TARGET,
    TURNING_FORWARD_TARGET,
    TURNING_RETURN_TARGET,
    TOUR_GOTO_TARGET,
    ARM_ACTIONS,
    MODE_TARGET_LABELS,
    FORWARD_SPEED_MPS,
    TURN_SPEED_RAD_S,
    TURN_STARTUP_COMPENSATION_SECONDS,
    normalize_motion_payload,
    validate_motion_payload,
)

PROJECT = Path(os.environ.get("G1_PROJECT_DIR", "/home/unitree/智能中控"))
NETWORK_INTERFACE = os.environ.get("G1_NETWORK_INTERFACE", "enP8p1s0")
SDK_PATH = os.environ.get(
    "UNITREE_SDK2_PYTHON_PATH",
    "/home/unitree/unitree_sdk2_python",
)
CYCLONE_PREFIX = os.environ.get(
    "CYCLONEDDS_COMPAT_PREFIX",
    "/home/unitree/cyclonedds-prefix",
)
INTERNAL_MAP_PATH = os.environ.get(
    "G1_INTERNAL_MAP_PATH",
    "/home/unitree/g1_internal_panorama_v2.pcd",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="G1 参数化高层运动桥")
    parser.add_argument("network_interface")
    parser.add_argument(
        "--request-topic",
        default="/smart_center/robot_action_request",
    )
    parser.add_argument(
        "--result-topic",
        default="/smart_center/robot_action_result",
    )
    args = parser.parse_args()

    try:
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String
        from nav_msgs.msg import Odometry
        from rclpy.qos import qos_profile_sensor_data
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
        from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient
        from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import (
            MotionSwitcherClient,
        )
    except ImportError as exc:
        raise SystemExit(
            f"G1 motion bridge dependency unavailable: {exc}"
        ) from exc

    ChannelFactoryInitialize(0, args.network_interface)

    class G1MotionBridge(Node):
        def __init__(self) -> None:
            super().__init__("g1_motion_bridge")

            self.result_publisher = self.create_publisher(
                String,
                args.result_topic,
                10,
            )

            self.ramp_voice_publisher = self.create_publisher(
                String,
                "/smart_center/response_text",
                10,
            )

            self.create_subscription(
                String,
                args.request_topic,
                self._on_request,
                10,
            )

            self.client = LocoClient()
            self.client.SetTimeout(10.0)
            self.client.Init()
            self.client._RegistApi(7001, 0)
            self.client._RegistApi(7002, 0)

            self.arm_client = G1ArmActionClient()
            self.arm_client.SetTimeout(10.0)
            self.arm_client.Init()

            self.switcher = MotionSwitcherClient()
            self.switcher.SetTimeout(5.0)
            self.switcher.Init()

            self.motion_lock = threading.Lock()
            self.stop_event = threading.Event()

            # STRAIGHT_HOLD_CONTROLLER_V1
            self.straight_state_lock = threading.Lock()
            self.straight_x = None
            self.straight_y = None
            self.straight_yaw = None
            self.straight_odom_time = 0.0

            # OFFICIAL_NAV_CACHE_TRANSPORT_V1
            # 运动全部使用官方SLAM导航；
            # 这里只用独立缓存读取官方里程计，
            # 避免运动桥DDS订阅打断重定位发布。
            self.ramp_odom_cache_timer = (
                self.create_timer(
                    0.2,
                    self._refresh_ramp_odom_cache,
                )
            )

            # 必须保存订阅对象引用，否则rclpy可能回收订阅，
            # 导致ROS图仍可见但回调不再更新里程计时间。
            self.handshake_active = False

            self.get_logger().info(
                "G1 parameter motion bridge ready: "
                "forward 0.3-0.9m, turn 15-90deg, stop"
            )

        def _publish_result(self, payload: dict[str, Any]) -> None:
            message = String()
            message.data = json.dumps(payload, ensure_ascii=False)
            self.result_publisher.publish(message)

        @staticmethod
        def _result_code(result: Any) -> int:
            if isinstance(result, tuple):
                return int(result[0] or 0)
            return int(result or 0)

        def _select_ai_mode(self) -> int:
            try:
                result = self.switcher.SelectMode("ai")
                if isinstance(result, tuple):
                    return int(result[0] or 0)
                return int(result or 0)
            except Exception as exc:
                self.get_logger().warning(f"切换AI模式失败：{exc}")
                return -1


        def _run_ramp_slam(
            self,
            *arguments: str,
            timeout: float = 30.0,
        ) -> int:
            command = [
                "/usr/bin/python3",
                str(PROJECT / "scripts" / "g1_slam_cli.py"),
                NETWORK_INTERFACE,
                *arguments,
            ]

            environment = os.environ.copy()

            environment["PYTHONPATH"] = (
                str(PROJECT / "vendor") + ":" + SDK_PATH
            )

            environment["CYCLONEDDS_HOME"] = (
                CYCLONE_PREFIX
            )

            previous_library_path = (
                environment.get(
                    "LD_LIBRARY_PATH",
                    "",
                )
            )

            environment["LD_LIBRARY_PATH"] = (
                CYCLONE_PREFIX + "/lib"
                + (
                    ":"
                    + previous_library_path
                    if previous_library_path
                    else ""
                )
            )

            try:
                result = subprocess.run(
                    command,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                self.get_logger().error(
                    "坡道SLAM命令执行超时："
                    + " ".join(arguments)
                )
                return 124
            except Exception as exc:
                self.get_logger().error(
                    "坡道SLAM命令执行异常："
                    f"{exc}"
                )
                return 125

            output = (
                result.stdout.strip()
                or result.stderr.strip()
            )

            if output:
                compact_output = " | ".join(
                    output.splitlines()
                )

                self.get_logger().info(
                    f"RAMP_SLAM_OUTPUT："
                    f"{compact_output}"
                )

            return int(result.returncode)


        def _stop(self) -> int:
            self.stop_event.set()

            movement_code = 0

            try:
                movement_code = int(
                    self.client.StopMove() or 0
                )
            except Exception:
                try:
                    movement_code = int(
                        self.client.SetVelocity(
                            0.0,
                            0.0,
                            0.0,
                            1.0,
                        )
                        or 0
                    )
                except Exception:
                    movement_code = 1

            pause_code = self._run_ramp_slam(
                "pause",
                timeout=12.0,
            )

            self.get_logger().warning(
                "RAMP_NAVIGATION_STOP："
                f"StopMove={movement_code}，"
                f"pause={pause_code}"
            )

            if movement_code != 0:
                return movement_code

            return pause_code

        def _on_request(self, message: Any) -> None:
            try:
                raw_payload = json.loads(message.data)
            except json.JSONDecodeError:
                self.get_logger().warning("忽略非JSON动作请求")
                return

            if not isinstance(raw_payload, dict):
                return

            task_id = str(raw_payload.get("task_id", ""))
            payload = normalize_motion_payload(raw_payload)
            payload["task_id"] = task_id

            allowed, reason = validate_motion_payload(payload)
            if not allowed:
                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "denied",
                        "denied": True,
                        "reason": reason,
                    }
                )
                return

            if payload["action"] == "stop":
                code = self._stop()
                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "completed" if code == 0 else "error",
                        "error": None if code == 0 else f"停止返回码{code}",
                    }
                )
                return

            if payload.get("action") == "mode":
                self.stop_event.set()

                threading.Thread(
                    target=self._run_mode,
                    args=(payload,),
                    daemon=True,
                ).start()
                return

            if payload.get("action") == "gesture":
                if self.motion_lock.locked():
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "denied",
                            "denied": True,
                            "reason": "机器人正在执行另一个动作",
                        }
                    )
                    return

                threading.Thread(
                    target=self._run_interaction,
                    args=(payload,),
                    daemon=True,
                ).start()
                return

            if payload.get("target") == TOUR_GOTO_TARGET:
                if self.motion_lock.locked():
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "denied",
                            "denied": True,
                            "reason": "机器人正在执行另一个动作",
                        }
                    )
                    return

                threading.Thread(
                    target=self._run_tour_goto,
                    args=(payload,),
                    daemon=True,
                ).start()
                return

            if payload.get("target") == RAMP_PREPARE_TARGET:
                if self.motion_lock.locked():
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "denied",
                            "denied": True,
                            "reason": "机器人正在执行另一个动作",
                        }
                    )
                    return

                threading.Thread(
                    target=self._run_ramp_prepare,
                    args=(payload,),
                    daemon=True,
                ).start()
                return

            if payload.get("target") in {
                TURNING_FORWARD_TARGET,
                TURNING_RETURN_TARGET,
            }:
                if self.motion_lock.locked():
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "denied",
                            "denied": True,
                            "reason": (
                                "机器人正在执行另一个动作"
                            ),
                        }
                    )
                    return

                reverse = (
                    payload.get("target")
                    == TURNING_RETURN_TARGET
                )

                threading.Thread(
                    target=self._run_turning_route,
                    args=(payload, reverse),
                    daemon=True,
                ).start()
                return

            if payload.get("target") == RAMP_RETURN_TARGET:
                if self.motion_lock.locked():
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "denied",
                            "denied": True,
                            "reason": (
                                "机器人正在执行另一个动作"
                            ),
                        }
                    )
                    return

                threading.Thread(
                    target=self._run_ramp_return,
                    args=(payload,),
                    daemon=True,
                ).start()
                return

            if payload.get("target") == CONTINUOUS_FORWARD_TARGET:
                if self.motion_lock.locked():
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "denied",
                            "denied": True,
                            "reason": "机器人正在执行另一个动作",
                        }
                    )
                    return

                threading.Thread(
                    target=self._run_continuous_forward,
                    args=(payload,),
                    daemon=True,
                ).start()
                return

            if self.motion_lock.locked():
                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "denied",
                        "denied": True,
                        "reason": "机器人正在执行另一个动作",
                    }
                )
                return

            threading.Thread(
                target=self._run_motion,
                args=(payload,),
                daemon=True,
            ).start()

        def _get_fsm_value(
            self,
            api_id: int,
        ) -> int:
            code, data = self.client._Call(
                api_id,
                "{}",
            )
            code = self._result_code(code)

            if code != 0:
                raise RuntimeError(
                    f"读取FSM失败，接口{api_id}，返回码{code}"
                )

            try:
                value = json.loads(data or "{}").get("data")
                return int(value)
            except Exception as exc:
                raise RuntimeError(
                    f"FSM返回数据无效：{data!r}"
                ) from exc

        def _wait_fsm(
            self,
            expected_id: int,
            require_static: bool = False,
            timeout: float = 12.0,
        ) -> None:
            deadline = time.monotonic() + timeout
            last_id = None
            last_mode = None

            while time.monotonic() < deadline:
                last_id = self._get_fsm_value(7001)
                last_mode = self._get_fsm_value(7002)

                if (
                    last_id == expected_id
                    and (
                        not require_static
                        or last_mode == 0
                    )
                ):
                    self.get_logger().warning(
                        f"FSM确认成功："
                        f"id={last_id}，mode={last_mode}"
                    )
                    return

                time.sleep(0.25)

            raise RuntimeError(
                f"等待FSM超时，期望id={expected_id}，"
                f"实际id={last_id}，mode={last_mode}"
            )

        def _set_verified_fsm(
            self,
            fsm_id: int,
            label: str,
            require_static: bool = False,
        ) -> int:
            code = self._result_code(
                self.client.SetFsmId(fsm_id)
            )

            self.get_logger().warning(
                f"请求切换{label}："
                f"fsm_id={fsm_id}，code={code}"
            )

            if code != 0:
                raise RuntimeError(
                    f"切换{label}失败，返回码{code}"
                )

            self._wait_fsm(
                fsm_id,
                require_static=require_static,
            )
            return code

        def _settle_position_fsm(
            self,
            fsm_id: int,
            label: str,
        ) -> None:
            self.get_logger().warning(
                f"等待6秒完成{label}姿态"
            )
            time.sleep(6.0)

            self._wait_fsm(
                fsm_id,
                require_static=True,
            )

        def _route_position_fsm(
            self,
            target_id: int,
            label: str,
            direct_from: set[int],
        ) -> int:
            current_id = self._get_fsm_value(7001)
            current_mode = self._get_fsm_value(7002)

            self.get_logger().warning(
                f"位置模式路由："
                f"current_id={current_id}，"
                f"current_mode={current_mode}，"
                f"target_id={target_id}"
            )

            if (
                current_id == target_id
                and current_mode == 0
            ):
                self.get_logger().warning(
                    f"当前已经处于{label}"
                )
                return 0

            # 动态状态只允许先进入阻尼。
            if current_mode != 0:
                self._set_verified_fsm(
                    1,
                    "阻尼模式",
                    require_static=True,
                )
                current_id = 1

            # 不在官方直接转换边内时，经阻尼中转。
            if (
                current_id != 1
                and current_id not in direct_from
            ):
                self._set_verified_fsm(
                    1,
                    "阻尼模式",
                    require_static=True,
                )

            code = self._set_verified_fsm(
                target_id,
                label,
                require_static=True,
            )

            self._settle_position_fsm(
                target_id,
                label,
            )
            return code

        def _run_mode(
            self,
            payload: dict[str, Any],
        ) -> None:
            task_id = str(payload.get("task_id", ""))
            target = str(payload.get("target", ""))
            label = MODE_TARGET_LABELS.get(target, target)

            with self.motion_lock:
                try:
                    self.get_logger().warning(
                        f"开始执行运控模式切换：{label}"
                    )

                    if target == "debug":
                        self._stop()

                        self._set_verified_fsm(
                            1,
                            "阻尼模式",
                            require_static=True,
                        )

                        time.sleep(1.0)

                        code = self._result_code(
                            self.switcher.ReleaseMode()
                        )

                    elif target == "main_control":
                        code = self._select_ai_mode()

                        if code == 0:
                            time.sleep(1.0)
                            current_id = self._get_fsm_value(
                                7001
                            )
                            current_mode = self._get_fsm_value(
                                7002
                            )
                            self.get_logger().warning(
                                "主运控恢复完成："
                                f"fsm_id={current_id}，"
                                f"fsm_mode={current_mode}"
                            )

                    else:
                        mode_code = self._select_ai_mode()

                        if mode_code != 0:
                            raise RuntimeError(
                                "恢复主运控失败，"
                                f"返回码{mode_code}"
                            )

                        time.sleep(0.5)
                        self._stop()

                        current_id = self._get_fsm_value(
                            7001
                        )
                        current_mode = self._get_fsm_value(
                            7002
                        )

                        self.get_logger().warning(
                            "官方模式路由起点："
                            f"fsm_id={current_id}，"
                            f"fsm_mode={current_mode}，"
                            f"target={target}"
                        )

                        if target == "damp":
                            code = self._set_verified_fsm(
                                1,
                                "阻尼模式",
                                require_static=True,
                            )

                        elif target == "zero_torque":
                            if (
                                current_id == 0
                                and current_mode == 0
                            ):
                                self.get_logger().warning(
                                    "当前已经处于零力矩模式"
                                )
                                code = 0
                            else:
                                self._set_verified_fsm(
                                    1,
                                    "阻尼模式",
                                    require_static=True,
                                )

                                code = self._set_verified_fsm(
                                    0,
                                    "零力矩模式",
                                    require_static=True,
                                )

                        elif target == "ready":
                            code = self._route_position_fsm(
                                4,
                                "锁定站立模式",
                                {2, 3},
                            )

                        elif target == "squat":
                            code = self._route_position_fsm(
                                2,
                                "下蹲模式",
                                {3, 4, 801},
                            )

                        elif target == "sit":
                            code = self._route_position_fsm(
                                3,
                                "落座模式",
                                {2, 4, 801},
                            )

                        elif target == "sport":
                            if current_id == 801:
                                self.get_logger().warning(
                                    "当前已经处于走跑运动模式"
                                )
                                code = 0
                            else:
                                self.get_logger().warning(
                                    "进入走跑模式官方流程："
                                    "FSM 1 -> FSM 4 -> FSM 801"
                                )

                                self._route_position_fsm(
                                    4,
                                    "锁定站立模式",
                                    {2, 3},
                                )

                                code = self._set_verified_fsm(
                                    801,
                                    "走跑运动模式",
                                )

                        elif target == "stand":
                            self._route_position_fsm(
                                4,
                                "锁定站立模式",
                                {2, 3},
                            )

                            code = self._set_verified_fsm(
                                500,
                                "常规运控模式",
                                require_static=True,
                            )

                            balance_code = self._result_code(
                                self.client.SetBalanceMode(0)
                            )

                            if balance_code != 0:
                                raise RuntimeError(
                                    "进入平衡站立失败，"
                                    f"返回码{balance_code}"
                                )

                        else:
                            raise RuntimeError(
                                "模式不在执行白名单中"
                            )

                    self.get_logger().warning(
                        f"运控模式切换结果："
                        f"target={target}，code={code}"
                    )

                    if code != 0:
                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "error",
                                "error": (
                                    f"切换{label}返回错误码{code}"
                                ),
                            }
                        )
                        return

                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "completed",
                            "completed": True,
                            "action": "mode",
                            "target": target,
                            "label": label,
                        }
                    )

                except Exception as exc:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": str(exc),
                        }
                    )

        def _run_interaction(
            self,
            payload: dict[str, Any],
        ) -> None:
            task_id = str(payload.get("task_id", ""))
            target = str(payload.get("target", ""))
            config = ARM_ACTIONS.get(target)

            with self.motion_lock:
                self.stop_event.clear()

                if config is None:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "denied",
                            "denied": True,
                            "reason": "交互动作不在ArmAction白名单中",
                        }
                    )
                    return

                if (
                    self.handshake_active
                    and target not in {
                        "handshake_end",
                        "release_arm",
                    }
                ):
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "denied",
                            "denied": True,
                            "reason": "请先说结束握手或释放手臂",
                        }
                    )
                    return

                try:
                    mode_code = self._select_ai_mode()

                    if mode_code != 0:
                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "error",
                                "error": (
                                    f"切换AI运动模式失败，"
                                    f"返回码{mode_code}"
                                ),
                            }
                        )
                        return

                    time.sleep(0.5)

                    action_id = int(config["id"])
                    label = str(config["label"])
                    wait_seconds = float(
                        config["wait_seconds"]
                    )
                    hold = bool(config["hold"])

                    self.get_logger().info(
                        f"开始执行ArmAction："
                        f"{label}，id={action_id}"
                    )

                    code = int(
                        self.arm_client.ExecuteAction(action_id)
                        or 0
                    )

                    self.get_logger().info(
                        f"ArmAction调用结果："
                        f"target={target}，"
                        f"id={action_id}，code={code}"
                    )

                    if code != 0:
                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "error",
                                "error": (
                                    f"ArmAction返回错误码{code}"
                                ),
                            }
                        )
                        return

                    if target == "handshake_start":
                        self.handshake_active = True
                    elif target in {
                        "handshake_end",
                        "release_arm",
                    }:
                        self.handshake_active = False

                    if self.stop_event.wait(wait_seconds):
                        try:
                            self.arm_client.ExecuteAction(99)
                        except Exception:
                            pass
                        self.handshake_active = False

                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "stopped",
                                "completed": False,
                            }
                        )
                        return

                    if not hold and action_id != 99:
                        release_code = int(
                            self.arm_client.ExecuteAction(99)
                            or 0
                        )

                        self.get_logger().info(
                            f"ArmAction释放结果："
                            f"code={release_code}"
                        )

                        if release_code != 0:
                            self._publish_result(
                                {
                                    "task_id": task_id,
                                    "state": "error",
                                    "error": (
                                        f"释放手臂返回错误码"
                                        f"{release_code}"
                                    ),
                                }
                            )
                            return

                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "completed",
                            "completed": True,
                            "action": "gesture",
                            "target": target,
                            "action_id": action_id,
                            "label": label,
                        }
                    )

                except Exception as exc:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": str(exc),
                        }
                    )

        @staticmethod
        def _straight_wrap_angle(
            angle: float,
        ) -> float:
            while angle > math.pi:
                angle -= 2.0 * math.pi

            while angle < -math.pi:
                angle += 2.0 * math.pi

            return angle

        def _on_straight_odom(
            self,
            message: Any,
        ) -> None:
            orientation = (
                message.pose.pose.orientation
            )

            sin_yaw = 2.0 * (
                orientation.w * orientation.z
                + orientation.x * orientation.y
            )

            cos_yaw = 1.0 - 2.0 * (
                orientation.y * orientation.y
                + orientation.z * orientation.z
            )

            yaw = math.atan2(
                sin_yaw,
                cos_yaw,
            )

            with self.straight_state_lock:
                self.straight_x = float(
                    message.pose.pose.position.x
                )
                self.straight_y = float(
                    message.pose.pose.position.y
                )
                self.straight_yaw = yaw
                self.straight_odom_time = (
                    time.monotonic()
                )


        def _refresh_ramp_odom_cache(
            self,
        ) -> bool:
            cache_path = Path(
                "/run/g1-ramp/odom.json"
            )

            try:
                data = json.loads(
                    cache_path.read_text(
                        encoding="utf-8"
                    )
                )

                boot_id = Path(
                    "/proc/sys/kernel/random/boot_id"
                ).read_text(
                    encoding="utf-8"
                ).strip()

                if data.get("boot_id") != boot_id:
                    return False

                age = (
                    time.time()
                    - float(data["updated_at_unix"])
                )

                if age < 0.0 or age > 3.0:
                    return False

                with self.straight_state_lock:
                    self.straight_x = float(
                        data["x"]
                    )
                    self.straight_y = float(
                        data["y"]
                    )
                    self.straight_yaw = float(
                        data["yaw"]
                    )
                    self.straight_odom_time = (
                        time.monotonic()
                    )

                return True
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ):
                return False


        def _ramp_odom_is_fresh(
            self,
            maximum_age: float = 3.0,
        ) -> bool:
            self._refresh_ramp_odom_cache()

            with self.straight_state_lock:
                odom_time = self.straight_odom_time

            return (
                odom_time is not None
                and odom_time > 0.0
                and time.monotonic() - odom_time
                <= maximum_age
            )


        def _wait_for_ramp_odom(
            self,
            after_time: float,
            timeout: float = 20.0,
        ) -> bool:
            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    return False

                with self.straight_state_lock:
                    odom_time = self.straight_odom_time

                if (
                    odom_time is not None
                    and odom_time >= after_time
                ):
                    self.get_logger().warning(
                        "RAMP_LOCALIZATION_READY："
                        "已取得实时重定位里程计"
                    )
                    return True

                time.sleep(0.1)

            return False


        def _publish_ramp_stopped(
            self,
            task_id: str,
        ) -> None:
            self._publish_result(
                {
                    "task_id": task_id,
                    "state": "stopped",
                    "completed": False,
                }
            )


        def _publish_ramp_voice(
            self,
            text: str,
        ) -> None:
            message = String()
            message.data = text
            self.ramp_voice_publisher.publish(message)


        def _wait_for_ramp_arrival(
            self,
            target_x: float,
            target_y: float,
            timeout: float = 300.0,
            tolerance: float = 0.25,
            hold_seconds: float = 1.0,
        ) -> bool:
            deadline = time.monotonic() + timeout
            arrived_since = None

            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    return False

                with self.straight_state_lock:
                    x = self.straight_x
                    y = self.straight_y
                    odom_time = self.straight_odom_time

                fresh = (
                    x is not None
                    and y is not None
                    and odom_time is not None
                    and odom_time > 0.0
                    and time.monotonic() - odom_time <= 2.0
                )

                if not fresh:
                    arrived_since = None
                    time.sleep(0.1)
                    continue

                distance = math.hypot(
                    target_x - x,
                    target_y - y,
                )

                if distance <= tolerance:
                    if arrived_since is None:
                        arrived_since = time.monotonic()

                    if (
                        time.monotonic() - arrived_since
                        >= hold_seconds
                    ):
                        self.get_logger().warning(
                            "RAMP_PREPARE_ARRIVED："
                            f"距离起点={distance:.3f}米"
                        )
                        return True
                else:
                    arrived_since = None

                time.sleep(0.1)

            return False


        def _run_tour_goto(
            self,
            payload: dict[str, Any],
        ) -> None:
            task_id = str(payload.get("task_id", ""))
            point_name = str(payload.get("point_name", ""))

            with self.motion_lock:
                self.stop_event.clear()

                try:
                    (
                        target_x,
                        target_y,
                        target_yaw,
                    ) = self._load_tour_point(point_name)
                except Exception as exc:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": f"读取导览点失败：{exc}",
                        }
                    )
                    return

                if not self._ramp_odom_is_fresh():
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": "当前没有实时全局定位",
                        }
                    )
                    return

                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "running",
                        "phase": "navigating",
                        "point_name": point_name,
                    }
                )

                code = self._run_ramp_slam(
                    "goto",
                    str(target_x),
                    str(target_y),
                    str(target_yaw),
                    timeout=30.0,
                )
                if code != 0:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": (
                                f"官方导航前往{point_name}失败，"
                                f"返回码{code}"
                            ),
                        }
                    )
                    return

                arrived = self._wait_for_ramp_arrival(
                    target_x,
                    target_y,
                    timeout=420.0,
                    tolerance=0.35,
                    hold_seconds=1.0,
                )
                if not arrived:
                    if self.stop_event.is_set():
                        self._publish_ramp_stopped(task_id)
                    else:
                        self._run_ramp_slam("pause", timeout=15.0)
                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "error",
                                "error": f"到达{point_name}超时",
                            }
                        )
                    return

                self._run_ramp_slam("pause", timeout=15.0)
                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "completed",
                        "completed": True,
                        "point_name": point_name,
                        "x": target_x,
                        "y": target_y,
                        "yaw": target_yaw,
                    }
                )


        @staticmethod
        def _load_tour_point(
            point_name: str,
        ) -> tuple[float, float, float]:
            config_path = PROJECT / "data" / "embodied_lab_panorama_v2" / "tour_config.json"
            point_root = PROJECT / "data" / "embodied_lab_panorama_v2"
            config = json.loads(
                config_path.read_text(encoding="utf-8")
            )
            order = config.get("order", [])
            if point_name not in order:
                raise ValueError("导览点不在当前已保存路线中")
            point_path = point_root / f"{point_name}.json"
            if point_path.parent != point_root:
                raise ValueError("导览点路径无效")
            point = json.loads(
                point_path.read_text(encoding="utf-8")
            )
            if point.get("map_path") != INTERNAL_MAP_PATH:
                raise ValueError("导览点不属于当前全景地图")
            return (
                float(point["x"]),
                float(point["y"]),
                float(point["yaw"]),
            )


        @staticmethod
        def _load_route_point(
            point_name: str,
        ) -> tuple[float, float, float]:
            allowed_names = {
                "straight_begin",
                "straight_end",
                "turn_1",
                "turn_2",
                "turn_3",
            }
            if point_name not in allowed_names:
                raise ValueError("路线点名称不在白名单中")

            point_root = (
                PROJECT / "data" / "embodied_lab_panorama_v2"
            )
            point_path = point_root / f"{point_name}.json"
            point = json.loads(
                point_path.read_text(encoding="utf-8")
            )

            point_map = str(point.get("map_path", ""))
            if point_map and point_map != INTERNAL_MAP_PATH:
                raise ValueError(
                    f"路线点{point_name}不属于当前地图："
                    f"{point_map}"
                )

            values = (
                float(point["x"]),
                float(point["y"]),
                float(point["yaw"]),
            )
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"路线点{point_name}坐标无效")
            return values


        def _navigate_to_guide_1_standby(
            self,
        ) -> tuple[bool, str]:
            try:
                target_x, target_y, target_yaw = (
                    self._load_tour_point("guide_1")
                )
            except Exception as exc:
                return False, f"读取guide_1待命点失败：{exc}"

            self.get_logger().warning(
                "GUIDE_1_STANDBY_BEGIN："
                f"目标=({target_x:.4f},{target_y:.4f},"
                f"{target_yaw:.4f})"
            )
            code = self._run_ramp_slam(
                "goto",
                str(target_x),
                str(target_y),
                str(target_yaw),
                timeout=30.0,
            )
            if code != 0:
                return False, f"前往guide_1待命点失败，返回码{code}"
            arrived = self._wait_for_ramp_arrival(
                target_x,
                target_y,
                timeout=420.0,
                tolerance=0.35,
                hold_seconds=1.0,
            )
            if not arrived:
                if self.stop_event.is_set():
                    return False, "前往guide_1期间被停止"
                self._run_ramp_slam("pause", timeout=15.0)
                return False, "到达guide_1待命点超时"
            self._run_ramp_slam("pause", timeout=15.0)
            self.get_logger().warning(
                "GUIDE_1_STANDBY_ARRIVED"
            )
            return True, ""


        def _run_ramp_prepare(
            self,
            payload: dict[str, Any],
        ) -> None:
            task_id = str(
                payload.get("task_id", "")
            )

            with self.motion_lock:
                self.stop_event.clear()

                try:
                    start_x, start_y, start_yaw = (
                        self._load_route_point("straight_begin")
                    )
                except Exception as exc:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": f"读取当前地图起点失败：{exc}",
                        }
                    )
                    return

                if not self._ramp_odom_is_fresh():
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": (
                                "坡道开机定位尚未完成，"
                                "无法前往起点"
                            ),
                        }
                    )
                    return

                self.get_logger().warning(
                    "RAMP_PREPARE_BEGIN："
                    f"目标S=({start_x:.6f},{start_y:.6f})，"
                    f"yaw={start_yaw:.6f}"
                )

                code = self._run_ramp_slam(
                    "goto",
                    str(start_x),
                    str(start_y),
                    str(start_yaw),
                    timeout=30.0,
                )

                if code != 0:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": (
                                "前往爬坡起点启动失败，"
                                f"返回码{code}"
                            ),
                        }
                    )
                    return

                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "running",
                        "error": None,
                    }
                )

                if self._wait_for_ramp_arrival(
                    start_x,
                    start_y,
                ):
                    self._publish_ramp_voice(
                        "已准备爬坡行走"
                    )
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "completed",
                            "completed": True,
                            "error": None,
                        }
                    )
                    return

                if not self.stop_event.is_set():
                    self.get_logger().error(
                        "RAMP_PREPARE_TIMEOUT："
                        "前往起点超时"
                    )
                    self._publish_ramp_voice(
                        "前往爬坡起点超时"
                    )


        def _run_continuous_forward(
            self,
            payload: dict[str, Any],
        ) -> None:
            task_id = str(
                payload.get("task_id", "")
            )

            with self.motion_lock:
                self.stop_event.clear()

                try:
                    start_x, start_y, start_yaw = (
                        self._load_route_point("straight_begin")
                    )
                    end_x, end_y, end_yaw = (
                        self._load_route_point("straight_end")
                    )
                except Exception as exc:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": f"读取当前地图直线路线失败：{exc}",
                        }
                    )
                    return

                localized = self._ramp_odom_is_fresh()

                if localized:
                    self.get_logger().info(
                        "RAMP_LOCALIZATION_REUSE："
                        "复用当前实时坡道定位"
                    )
                else:
                    self.get_logger().warning(
                        "RAMP_AUTO_LOCALIZATION_BEGIN："
                        "当前位置无重定位里程计，"
                        "使用固定起点自动初始化"
                    )

                    last_code = 1

                    for attempt in range(1, 4):
                        if self.stop_event.is_set():
                            self._publish_ramp_stopped(
                                task_id
                            )
                            return

                        self.get_logger().warning(
                            "RAMP_AUTO_LOCALIZATION_ATTEMPT："
                            f"{attempt}/3，"
                            f"初值=({start_x:.4f},"
                            f"{start_y:.4f},{start_yaw:.4f})"
                        )

                        initialization_started = (
                            time.monotonic()
                        )

                        last_code = self._run_ramp_slam(
                            "initialize",
                            INTERNAL_MAP_PATH,
                            str(start_x),
                            str(start_y),
                            str(start_yaw),
                            timeout=40.0,
                        )

                        if last_code != 0:
                            self.get_logger().warning(
                                "RAMP_AUTO_LOCALIZATION_REJECTED："
                                f"尝试{attempt}/3，"
                                f"返回码{last_code}"
                            )
                            time.sleep(2.0)
                            continue

                        if self._wait_for_ramp_odom(
                            initialization_started,
                            timeout=20.0,
                        ):
                            localized = True
                            break

                        self.get_logger().warning(
                            "RAMP_AUTO_LOCALIZATION_NO_ODOM："
                            f"尝试{attempt}/3被接受，"
                            "但没有形成实时里程计"
                        )

                        time.sleep(2.0)

                    if not localized:
                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "error",
                                "error": (
                                    "坡道自动定位失败，"
                                    f"返回码{last_code}"
                                ),
                            }
                        )
                        return

                if self.stop_event.is_set():
                    self._publish_ramp_stopped(
                        task_id
                    )
                    return

                self.get_logger().warning(
                    "RAMP_NAVIGATION_BEGIN："
                    f"S=({start_x:.4f},{start_y:.4f})，"
                    f"E=({end_x:.4f},{end_y:.4f})，"
                    f"yaw={end_yaw:.6f}"
                )

                code = self._run_ramp_slam(
                    "goto",
                    str(end_x),
                    str(end_y),
                    str(end_yaw),
                    timeout=30.0,
                )

                if code != 0:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": (
                                "坡道导航启动失败，"
                                f"返回码{code}"
                            ),
                        }
                    )
                    return

                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "running",
                        "error": None,
                    }
                )

                self.get_logger().warning(
                    "RAMP_NAVIGATION_ACCEPTED："
                    "官方导航已接受终点E，"
                    "语音动作线程已释放"
                )



        def _wait_for_turning_transition(
            self,
            target_x: float,
            target_y: float,
            target_yaw: float,
            timeout: float = 180.0,
            position_tolerance: float = 0.30,
            yaw_tolerance: float = math.radians(18.0),
        ) -> bool:
            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    return False

                self._refresh_ramp_odom_cache()

                with self.straight_state_lock:
                    x = self.straight_x
                    y = self.straight_y
                    yaw = self.straight_yaw
                    odom_time = self.straight_odom_time

                fresh = (
                    x is not None
                    and y is not None
                    and yaw is not None
                    and odom_time is not None
                    and odom_time > 0.0
                    and time.monotonic() - odom_time <= 3.0
                )

                if not fresh:
                    time.sleep(0.1)
                    continue

                distance = math.hypot(
                    target_x - x,
                    target_y - y,
                )

                yaw_error = math.atan2(
                    math.sin(target_yaw - yaw),
                    math.cos(target_yaw - yaw),
                )

                if (
                    distance <= position_tolerance
                    and abs(yaw_error) <= yaw_tolerance
                ):
                    self.get_logger().warning(
                        "TURNING_ROUTE_TRANSITION："
                        f"distance={distance:.3f}米，"
                        f"yaw_error="
                        f"{math.degrees(yaw_error):.1f}度"
                    )
                    return True

                time.sleep(0.1)

            return False


        def _run_turning_route(
            self,
            payload: dict[str, Any],
            reverse: bool,
        ) -> None:
            task_id = str(
                payload.get("task_id", "")
            )

            with self.motion_lock:
                self.stop_event.clear()

                if not self._ramp_odom_is_fresh():
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": (
                                "当前没有实时坡道定位，"
                                "无法执行转弯路线"
                            ),
                        }
                    )
                    return

                with self.straight_state_lock:
                    current_x = self.straight_x
                    current_y = self.straight_y

                try:
                    start = self._load_route_point(
                        "straight_begin"
                    )
                    end = self._load_route_point(
                        "straight_end"
                    )
                    turn_1 = self._load_route_point("turn_1")
                    turn_2 = self._load_route_point("turn_2")
                    turn_3 = self._load_route_point("turn_3")
                except Exception as exc:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": f"读取当前地图转弯路线失败：{exc}",
                        }
                    )
                    return

                if reverse:
                    route_name = "TURNING_RETURN"
                    expected_x, expected_y, _ = end
                    route_positions = [
                        ("turn_3", turn_3),
                        ("turn_2", turn_2),
                        ("turn_1", turn_1),
                        ("straight_begin", start),
                    ]
                    completion_voice = (
                        "转弯返回已到达爬坡起点"
                    )
                else:
                    route_name = "TURNING_FORWARD"
                    expected_x, expected_y, _ = start
                    route_positions = [
                        ("turn_1", turn_1),
                        ("turn_2", turn_2),
                        ("turn_3", turn_3),
                        ("straight_end", end),
                    ]
                    completion_voice = (
                        "转弯前进已到达固定终点"
                    )

                points = []
                for index, (point_name, point) in enumerate(
                    route_positions
                ):
                    target_x, target_y, marked_yaw = point
                    if index == len(route_positions) - 1:
                        target_yaw = marked_yaw
                    else:
                        next_point = route_positions[index + 1][1]
                        target_yaw = math.atan2(
                            next_point[1] - target_y,
                            next_point[0] - target_x,
                        )
                    points.append(
                        (
                            point_name,
                            target_x,
                            target_y,
                            target_yaw,
                        )
                    )

                start_distance = math.hypot(
                    expected_x - float(current_x),
                    expected_y - float(current_y),
                )

                if start_distance > 1.20:
                    location = (
                        "固定终点"
                        if reverse
                        else "爬坡起点"
                    )

                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": (
                                f"机器人不在{location}附近，"
                                "请先执行准备或对应返回指令"
                            ),
                        }
                    )
                    return

                self.get_logger().warning(
                    f"{route_name}_BEGIN："
                    f"起始偏差={start_distance:.3f}米，"
                    f"官方导航节点数={len(points)}"
                )

                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "running",
                        "error": None,
                    }
                )

                for index, point in enumerate(points):
                    if self.stop_event.is_set():
                        self._publish_ramp_stopped(
                            task_id
                        )
                        return

                    (
                        point_name,
                        target_x,
                        target_y,
                        target_yaw,
                    ) = point

                    self.get_logger().warning(
                        f"{route_name}_GOTO："
                        f"{index + 1}/{len(points)} "
                        f"{point_name}="
                        f"({target_x:.6f},"
                        f"{target_y:.6f},"
                        f"{target_yaw:.5f})"
                    )

                    code = self._run_ramp_slam(
                        "goto",
                        str(target_x),
                        str(target_y),
                        str(target_yaw),
                        timeout=30.0,
                    )

                    if code != 0:
                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "error",
                                "error": (
                                    f"官方导航前往"
                                    f"{point_name}失败，"
                                    f"返回码{code}"
                                ),
                            }
                        )
                        return

                    final_point = (
                        index == len(points) - 1
                    )

                    if final_point:
                        arrived = (
                            self._wait_for_ramp_arrival(
                                target_x,
                                target_y,
                                timeout=300.0,
                                tolerance=0.35,
                                hold_seconds=0.5,
                            )
                        )
                    else:
                        arrived = (
                            self._wait_for_turning_transition(
                                target_x,
                                target_y,
                                target_yaw,
                            )
                        )

                    if not arrived:
                        if self.stop_event.is_set():
                            self._publish_ramp_stopped(
                                task_id
                            )
                            return

                        self._run_ramp_slam(
                            "pause",
                            timeout=15.0,
                        )

                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "error",
                                "error": (
                                    f"到达{point_name}超时，"
                                    "路线已暂停"
                                ),
                            }
                        )
                        return

                if reverse:
                    standby_ok, standby_error = (
                        self._navigate_to_guide_1_standby()
                    )
                    if not standby_ok:
                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "error",
                                "error": standby_error,
                            }
                        )
                        return

                self.get_logger().warning(
                    f"{route_name}_COMPLETED"
                )

                self._publish_ramp_voice(
                    completion_voice
                )

                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "completed",
                        "completed": True,
                        "error": None,
                    }
                )


        def _run_ramp_return(
            self,
            payload: dict[str, Any],
        ) -> None:
            task_id = str(
                payload.get("task_id", "")
            )

            with self.motion_lock:
                self.stop_event.clear()

                try:
                    start_x, start_y, start_yaw = (
                        self._load_route_point("straight_begin")
                    )
                except Exception as exc:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": f"读取当前地图返回起点失败：{exc}",
                        }
                    )
                    return

                if not self._ramp_odom_is_fresh():
                    self.get_logger().error(
                        "RAMP_RETURN_NO_LOCALIZATION："
                        "没有实时坡道定位，拒绝返回"
                    )

                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": (
                                "当前没有坡道定位，"
                                "无法安全返回起点"
                            ),
                        }
                    )
                    return

                if self.stop_event.is_set():
                    self._publish_ramp_stopped(
                        task_id
                    )
                    return

                self.get_logger().warning(
                    "RAMP_RETURN_BEGIN："
                    f"目标S=({start_x:.6f},{start_y:.6f})，"
                    f"yaw={start_yaw:.6f}"
                )

                code = self._run_ramp_slam(
                    "goto",
                    str(start_x),
                    str(start_y),
                    str(start_yaw),
                    timeout=30.0,
                )

                if code != 0:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": (
                                "返回起点启动失败，"
                                f"返回码{code}"
                            ),
                        }
                    )
                    return

                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "running",
                        "error": None,
                    }
                )

                self.get_logger().warning(
                    "RAMP_RETURN_ACCEPTED："
                    "官方导航已接受起点S，"
                    "等待实际到达"
                )

                arrived = self._wait_for_ramp_arrival(
                    start_x,
                    start_y,
                    timeout=420.0,
                    tolerance=0.35,
                    hold_seconds=1.0,
                )
                if not arrived:
                    if self.stop_event.is_set():
                        self._publish_ramp_stopped(task_id)
                    else:
                        self._run_ramp_slam(
                            "pause",
                            timeout=15.0,
                        )
                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "error",
                                "error": "直线返回到达坡道起点超时",
                            }
                        )
                    return

                standby_ok, standby_error = (
                    self._navigate_to_guide_1_standby()
                )
                if not standby_ok:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": standby_error,
                        }
                    )
                    return

                self._publish_ramp_voice(
                    "已回到导览点一待命"
                )
                self._publish_result(
                    {
                        "task_id": task_id,
                        "state": "completed",
                        "completed": True,
                        "error": None,
                        "standby_point": "guide_1",
                    }
                )


        def _run_motion(self, payload: dict[str, Any]) -> None:
            task_id = str(payload.get("task_id", ""))

            with self.motion_lock:
                self.stop_event.clear()

                mode_code = self._select_ai_mode()
                if mode_code not in {0}:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": f"切换AI运动模式失败，返回码{mode_code}",
                        }
                    )
                    return

                time.sleep(0.5)

                action = payload["action"]

                if action == "move":
                    duration = float(payload["duration_seconds"])
                    distance = float(payload["distance_m"])
                    vx = FORWARD_SPEED_MPS
                    omega = 0.0
                    description = f"向前直行{duration}秒"
                else:
                    angle = float(payload["angle_deg"])
                    direction = payload["direction"]
                    vx = 0.0
                    omega = TURN_SPEED_RAD_S
                    if direction == "right":
                        omega = -omega
                    duration = (
                        TURN_STARTUP_COMPENSATION_SECONDS
                        + math.radians(angle) / TURN_SPEED_RAD_S
                    )
                    description = (
                        f"{'左转' if direction == 'left' else '右转'}"
                        f"{angle}度"
                    )

                self.get_logger().info(
                    f"开始执行：{description}，预计{duration:.2f}秒"
                )

                started = time.monotonic()

                error_code = int(
                    self.client.SetVelocity(
                        vx,
                        0.0,
                        omega,
                        duration,
                    )
                    or 0
                )

                if error_code != 0:
                    self._stop()
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": f"SetVelocity返回错误码{error_code}",
                        }
                    )
                    return

                while time.monotonic() - started < duration:
                    if self.stop_event.wait(0.05):
                        self._publish_result(
                            {
                                "task_id": task_id,
                                "state": "stopped",
                                "completed": False,
                            }
                        )
                        return

                stop_code = self._stop()

                if error_code != 0 or stop_code != 0:
                    self._publish_result(
                        {
                            "task_id": task_id,
                            "state": "error",
                            "error": (
                                f"运动返回码{error_code}，"
                                f"停止返回码{stop_code}"
                            ),
                        }
                    )
                    return

                result = {
                    "task_id": task_id,
                    "state": "completed",
                    "completed": True,
                    "action": action,
                    "description": description,
                }

                if action == "move":
                    result["duration_seconds"] = payload["duration_seconds"]
                    result["distance_m"] = payload["distance_m"]
                else:
                    result["direction"] = payload["direction"]
                    result["angle_deg"] = payload["angle_deg"]

                self._publish_result(result)

        def safe_stop(self) -> None:
            try:
                self._stop()
            except Exception as exc:
                self.get_logger().error(f"退出时停止失败：{exc}")

    rclpy.init()
    node = G1MotionBridge()

    try:
        rclpy.spin(node)
    finally:
        node.safe_stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
