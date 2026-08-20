"""ROS 2 节点使用的异步命令处理器。"""

from app.agent import ToolContext
from app.g1_motion_commands import (
    CONTINUOUS_FORWARD_SPEED_MPS,
    CONTINUOUS_FORWARD_TARGET,
    RAMP_RETURN_TARGET,
    RAMP_PREPARE_TARGET,
    TURNING_FORWARD_TARGET,
    TURNING_RETURN_TARGET,
    FORWARD_THREE_STEPS_SPEED_MPS,
    FORWARD_THREE_STEPS_TARGET,
    MODE_TARGET_LABELS,
    get_mode_confirmation_prompt,
    is_mode_cancel_command,
    is_mode_confirmation_command,
    parse_mode_command,
    is_continuous_forward_command,
    is_ramp_return_command,
    is_ramp_prepare_command,
    is_turning_forward_command,
    is_turning_return_command,
    is_forward_three_steps_command,
    parse_forward_duration_command,
    parse_turn_command,
    parse_interaction_command,
    strip_leading_wake_words,
    is_stop_command,
)
from app.runtime import SmartCenterRuntime
from app.schemas import AgentRequest, AgentResponse, ToolExecution


class Ros2CommandProcessor:
    def __init__(self, runtime: SmartCenterRuntime, session_title: str) -> None:
        self.runtime = runtime
        self.session_title = session_title
        self.session_id: str | None = None
        self.pending_mode_target: str | None = None

    async def start(self) -> str:
        assert self.runtime.database is not None
        self.session_id = (await self.runtime.database.create_session(self.session_title)).id
        return self.session_id

    async def handle_text(self, text: str) -> AgentResponse:
        text = strip_leading_wake_words(text)

        if not self.session_id:
            await self.start()
        assert self.runtime.agent is not None and self.session_id is not None
        if is_stop_command(text):
            self.pending_mode_target = None
            execution = await self.emergency_stop()
            result = execution.result
            if execution.status == "success" and result.get("mode") == "simulation":
                content = "当前是仿真模式。"
            elif execution.status == "success" and result.get("state") == "completed":
                content = "已经停下"
            else:
                content = str(result.get("reason") or result.get("error") or "停止指令执行失败。")
            return AgentResponse(
                session_id=self.session_id,
                content=content,
                tool_executions=[execution],
            )
        mode_target = parse_mode_command(text)

        if self.pending_mode_target is not None:
            if is_mode_cancel_command(text):
                self.pending_mode_target = None

                return AgentResponse(
                    session_id=self.session_id,
                    content="已取消模式切换。",
                    tool_executions=[],
                )

            if is_mode_confirmation_command(text):
                assert self.runtime.tools is not None

                target = self.pending_mode_target
                self.pending_mode_target = None

                print(
                    "[MODE_ROUTE] deterministic confirmation "
                    f"target={target}",
                    flush=True,
                )

                execution = await self.runtime.tools.execute(
                    "execute_robot_action",
                    {
                        "action": "mode",
                        "target": target,
                    },
                    ToolContext(
                        self.session_id,
                        text,
                    ),
                )

                result = execution.result
                label = MODE_TARGET_LABELS.get(
                    target,
                    target,
                )

                if (
                    execution.status == "success"
                    and result.get("mode") == "simulation"
                ):
                    content = (
                        "当前是仿真模式，"
                        "没有切换机器人模式。"
                    )
                elif (
                    execution.status == "success"
                    and result.get("state") == "completed"
                ):
                    content = f"已切换到{label}。"
                else:
                    content = str(
                        result.get("reason")
                        or result.get("error")
                        or f"切换到{label}失败。"
                    )

                return AgentResponse(
                    session_id=self.session_id,
                    content=content,
                    tool_executions=[execution],
                )

            if mode_target is not None:
                self.pending_mode_target = mode_target

                return AgentResponse(
                    session_id=self.session_id,
                    content=get_mode_confirmation_prompt(
                        mode_target
                    ),
                    tool_executions=[],
                )

            label = MODE_TARGET_LABELS.get(
                self.pending_mode_target,
                self.pending_mode_target,
            )

            return AgentResponse(
                session_id=self.session_id,
                content=(
                    f"正在等待确认切换到{label}。"
                    "请说确认执行，或者说取消执行。"
                ),
                tool_executions=[],
            )

        if mode_target is not None:
            self.pending_mode_target = mode_target

            print(
                "[MODE_ROUTE] deterministic request "
                f"target={mode_target}",
                flush=True,
            )

            return AgentResponse(
                session_id=self.session_id,
                content=get_mode_confirmation_prompt(
                    mode_target
                ),
                tool_executions=[],
            )

        if is_mode_confirmation_command(text):
            return AgentResponse(
                session_id=self.session_id,
                content="当前没有等待确认的模式切换。",
                tool_executions=[],
            )

        if is_mode_cancel_command(text):
            return AgentResponse(
                session_id=self.session_id,
                content="当前没有需要取消的模式切换。",
                tool_executions=[],
            )

        if is_ramp_prepare_command(text):
            assert self.runtime.tools is not None

            print(
                "[MOTION_ROUTE] deterministic ramp_prepare",
                flush=True,
            )

            execution = await self.runtime.tools.execute(
                "execute_robot_action",
                {
                    "action": "move",
                    "target": RAMP_PREPARE_TARGET,
                    "speed": CONTINUOUS_FORWARD_SPEED_MPS,
                    "confirmed": True,
                },
                ToolContext(
                    self.session_id,
                    text,
                ),
            )

            result = execution.result

            if (
                execution.status == "success"
                and result.get("mode") == "simulation"
            ):
                content = (
                    "当前是仿真模式，"
                    "没有前往爬坡起点。"
                )
            elif (
                execution.status == "success"
                and result.get("state") in {
                    "running",
                    "completed",
                }
            ):
                content = "正在前往爬坡起点"
            else:
                content = str(
                    result.get("reason")
                    or result.get("error")
                    or "前往爬坡起点没有执行。"
                )

            return AgentResponse(
                session_id=self.session_id,
                content=content,
                tool_executions=[execution],
            )

        if is_turning_forward_command(text):
            assert self.runtime.tools is not None

            print(
                "[MOTION_ROUTE] deterministic turning_forward",
                flush=True,
            )

            execution = await self.runtime.tools.execute(
                "execute_robot_action",
                {
                    "action": "move",
                    "target": TURNING_FORWARD_TARGET,
                    "speed": CONTINUOUS_FORWARD_SPEED_MPS,
                    "confirmed": True,
                },
                ToolContext(
                    self.session_id,
                    text,
                ),
            )

            result = execution.result

            if (
                execution.status == "success"
                and result.get("state") in {
                    "running",
                    "completed",
                }
            ):
                content = "正在沿转弯路线前进"
            else:
                content = str(
                    result.get("reason")
                    or result.get("error")
                    or "转弯前进没有执行。"
                )

            return AgentResponse(
                session_id=self.session_id,
                content=content,
                tool_executions=[execution],
            )

        if is_turning_return_command(text):
            assert self.runtime.tools is not None

            print(
                "[MOTION_ROUTE] deterministic turning_return",
                flush=True,
            )

            execution = await self.runtime.tools.execute(
                "execute_robot_action",
                {
                    "action": "move",
                    "target": TURNING_RETURN_TARGET,
                    "speed": CONTINUOUS_FORWARD_SPEED_MPS,
                    "confirmed": True,
                },
                ToolContext(
                    self.session_id,
                    text,
                ),
            )

            result = execution.result

            if (
                execution.status == "success"
                and result.get("state") in {
                    "running",
                    "completed",
                }
            ):
                content = "正在沿转弯路线返回"
            else:
                content = str(
                    result.get("reason")
                    or result.get("error")
                    or "转弯返回没有执行。"
                )

            return AgentResponse(
                session_id=self.session_id,
                content=content,
                tool_executions=[execution],
            )

        if is_ramp_return_command(text):
            assert self.runtime.tools is not None

            print(
                "[MOTION_ROUTE] deterministic ramp_return",
                flush=True,
            )

            execution = await self.runtime.tools.execute(
                "execute_robot_action",
                {
                    "action": "move",
                    "target": RAMP_RETURN_TARGET,
                    "speed": CONTINUOUS_FORWARD_SPEED_MPS,
                    "confirmed": True,
                },
                ToolContext(
                    self.session_id,
                    text,
                ),
            )

            result = execution.result

            if (
                execution.status == "success"
                and result.get("mode") == "simulation"
            ):
                content = (
                    "当前是仿真模式，"
                    "没有驱动机器人返回。"
                )
            elif (
                execution.status == "success"
                and result.get("state") in {
                    "running",
                    "completed",
                }
            ):
                content = "正在返回"
            else:
                content = str(
                    result.get("reason")
                    or result.get("error")
                    or "返回起点没有执行。"
                )

            return AgentResponse(
                session_id=self.session_id,
                content=content,
                tool_executions=[execution],
            )

        if is_continuous_forward_command(text):
            assert self.runtime.tools is not None

            print(
                "[MOTION_ROUTE] deterministic continuous_forward "
                "speed=0.40",
                flush=True,
            )

            execution = await self.runtime.tools.execute(
                "execute_robot_action",
                {
                    "action": "move",
                    "target": CONTINUOUS_FORWARD_TARGET,
                    "speed": CONTINUOUS_FORWARD_SPEED_MPS,
                },
                ToolContext(self.session_id, text),
            )

            result = execution.result

            if (
                execution.status == "success"
                and result.get("mode") == "simulation"
            ):
                content = "当前是仿真模式，没有驱动机器人前进。"
            elif (
                execution.status == "success"
                and result.get("state") in {
                    "running",
                    "completed",
                }
            ):
                content = "正在前进"
            else:
                content = str(
                    result.get("reason")
                    or result.get("error")
                    or "持续前进没有执行。"
                )

            return AgentResponse(
                session_id=self.session_id,
                content=content,
                tool_executions=[execution],
            )

        interaction_target = parse_interaction_command(text)

        if interaction_target is not None:
            assert self.runtime.tools is not None

            print(
                f"[INTERACTION_ROUTE] deterministic interaction "
                f"target={interaction_target}",
                flush=True,
            )

            execution = await self.runtime.tools.execute(
                "execute_robot_action",
                {
                    "action": "gesture",
                    "target": interaction_target,
                },
                ToolContext(self.session_id, text),
            )

            result = execution.result

            success_messages = {
                "face_wave": "胸前挥手动作已完成。",
                "high_wave": "高举挥手动作已完成。",
                "turn_back_wave": "转身挥手动作已完成。",
                "handshake_start": "我已经伸手，可以握手了。",
                "handshake_end": "握手已经结束。",
                "release_arm": "手臂已经释放。",
                "clap": "鼓掌动作已完成。",
                "high_five": "击掌动作已完成。",
                "hug": "拥抱动作已完成。",
                "two_hand_kiss": "双手飞吻动作已完成。",
                "left_kiss": "左手飞吻动作已完成。",
                "right_kiss": "右手飞吻动作已完成。",
                "both_hands_up": "举双手动作已完成。",
                "right_hand_up": "举右手动作已完成。",
                "heart": "双手比心动作已完成。",
                "right_heart": "右手比心动作已完成。",
                "refuse": "拒绝动作已完成。",
                "ultraman_ray": "双手打叉动作已完成。",
            }

            if (
                execution.status == "success"
                and result.get("mode") == "simulation"
            ):
                content = "当前是仿真模式，没有执行交互动作。"
            elif (
                execution.status == "success"
                and result.get("state") == "completed"
            ):
                content = success_messages.get(
                    interaction_target,
                    "交互动作已经完成。",
                )
            else:
                content = str(
                    result.get("reason")
                    or result.get("error")
                    or "交互动作没有执行。"
                )

            return AgentResponse(
                session_id=self.session_id,
                content=content,
                tool_executions=[execution],
            )

        turn_command = parse_turn_command(text)

        if turn_command is not None:
            assert self.runtime.tools is not None

            direction, angle_degrees = turn_command

            print(
                f"[MOTION_ROUTE] deterministic turn "
                f"direction={direction} "
                f"angle={angle_degrees}",
                flush=True,
            )

            execution = await self.runtime.tools.execute(
                "execute_robot_action",
                {
                    "action": "turn",
                    "direction": direction,
                    "angle_deg": angle_degrees,
                },
                ToolContext(self.session_id, text),
            )

            result = execution.result
            actual_angle = float(
                result.get("angle_deg", angle_degrees)
            )
            direction_text = (
                "左转"
                if direction == "left"
                else "右转"
            )

            if (
                execution.status == "success"
                and result.get("mode") == "simulation"
            ):
                content = "当前是仿真模式，没有驱动机器人转向。"
            elif (
                execution.status == "success"
                and result.get("state") == "completed"
            ):
                content = (
                    f"已完成{direction_text}"
                    f"{actual_angle:g}度。"
                )
            else:
                content = str(
                    result.get("reason")
                    or result.get("error")
                    or "转向动作没有执行。"
                )

            return AgentResponse(
                session_id=self.session_id,
                content=content,
                tool_executions=[execution],
            )

        duration_seconds = parse_forward_duration_command(text)

        if duration_seconds is not None:
            assert self.runtime.tools is not None

            print(
                f"[MOTION_ROUTE] deterministic "
                f"forward duration={duration_seconds}",
                flush=True,
            )

            execution = await self.runtime.tools.execute(
                "execute_robot_action",
                {
                    "action": "move",
                    "direction": "forward",
                    "duration_seconds": duration_seconds,
                },
                ToolContext(self.session_id, text),
            )

            result = execution.result
            actual_duration = float(
                result.get("duration_seconds", duration_seconds)
            )

            if (
                execution.status == "success"
                and result.get("mode") == "simulation"
            ):
                content = "当前是仿真模式，没有驱动机器人前进。"
            elif (
                execution.status == "success"
                and result.get("state") == "completed"
            ):
                content = (
                    f"已完成向前直行"
                    f"{actual_duration:g}秒。"
                )
            else:
                content = str(
                    result.get("reason")
                    or result.get("error")
                    or "前进动作没有执行。"
                )

            return AgentResponse(
                session_id=self.session_id,
                content=content,
                tool_executions=[execution],
            )

        if is_forward_three_steps_command(text):
            assert self.runtime.tools is not None
            execution = await self.runtime.tools.execute(
                "execute_robot_action",
                {
                    "action": "move",
                    "target": FORWARD_THREE_STEPS_TARGET,
                    "speed": FORWARD_THREE_STEPS_SPEED_MPS,
                },
                ToolContext(self.session_id, text),
            )
            result = execution.result
            if execution.status == "success" and result.get("mode") == "simulation":
                content = "当前是仿真模式，没有驱动机器人前进。"
            elif execution.status == "success" and result.get("state") == "completed":
                content = "已完成前进三步。"
            else:
                content = str(result.get("reason") or result.get("error") or "前进动作没有执行。")
            return AgentResponse(
                session_id=self.session_id,
                content=content,
                tool_executions=[execution],
            )
        return await self.runtime.agent.run(AgentRequest(session_id=self.session_id, content=text, use_rag=True))

    async def emergency_stop(self) -> ToolExecution:
        if not self.session_id:
            await self.start()
        assert self.runtime.tools is not None and self.session_id is not None
        return await self.runtime.tools.execute(
            "execute_robot_action", {"action": "stop", "speed": 0.05}, ToolContext(self.session_id, "ROS2 紧急停止")
        )

    async def get_robot_status(self) -> dict:
        assert self.runtime.settings is not None and self.runtime.tools is not None
        if self.runtime.settings.device_simulation:
            return {"mode": "simulation", "online": True, "state": "idle", "emergency_stop": False}
        return await self.runtime.tools.device_bridge.get_status()
