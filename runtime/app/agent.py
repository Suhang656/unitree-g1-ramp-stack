import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo


from app.config import Settings
from app.database import Database
from app.device_bridge import DeviceBridge, HttpDeviceBridge
from app.g1_motion_commands import (
    RAMP_PREPARE_TARGET,
    RAMP_RETURN_TARGET,
    TURNING_FORWARD_TARGET,
    TURNING_RETURN_TARGET,
    is_ramp_prepare_command,
    is_ramp_return_command,
    is_turning_forward_command,
    is_turning_return_command,
    FORWARD_THREE_STEPS_TARGET,
    is_authorized_motion_command,
    is_forward_three_steps_command,
    is_mode_confirmation_command,
    normalize_motion_payload,
    parse_interaction_command,
)
from app.memory import memory_was_requested, remember_text_if_requested
from app.ollama import OllamaClient, OllamaError
from app.query_router import route_query
from app.rag import RagService
from app.schemas import AgentRequest, AgentResponse, ToolExecution


ToolHandler = Callable[[dict[str, Any], "ToolContext"], Awaitable[dict[str, Any]]]


@dataclass
class ToolContext:
    session_id: str
    user_text: str


@dataclass
class RegisteredTool:
    definition: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        rag: RagService,
        device_bridge: DeviceBridge | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.rag = rag
        self.device_bridge: DeviceBridge = device_bridge or HttpDeviceBridge(settings)
        self._tools: dict[str, RegisteredTool] = {}
        self._register_builtin_tools()

    def definitions(self, user_text: str) -> list[dict[str, Any]]:
        definitions = []
        for name, tool in self._tools.items():
            # “记住”由服务端确定性保存，避免模型漏调工具或重复保存。
            if name == "remember_user_fact":
                continue
            definitions.append(tool.definition)
        return definitions

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolExecution:
        registered = self._tools.get(name)
        if registered is None:
            execution = ToolExecution(
                name=name,
                arguments=arguments,
                result={"error": "Tool is not registered"},
                status="denied",
            )
        else:
            try:
                result = await registered.handler(arguments, context)
                if result.get("denied"):
                    status = "denied"
                elif result.get("error"):
                    status = "error"
                else:
                    status = "success"
                execution = ToolExecution(
                    name=name,
                    arguments=arguments,
                    result=result,
                    status=status,
                )
            except Exception as exc:
                execution = ToolExecution(
                    name=name,
                    arguments=arguments,
                    result={"error": str(exc)},
                    status="error",
                )
        await self.database.log_tool_execution(
            context.session_id,
            execution.name,
            execution.arguments,
            execution.result,
            execution.status,
        )
        return execution

    def _register_builtin_tools(self) -> None:
        self._register(
            "get_current_time",
            "获取中国标准时间。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            self._get_current_time,
        )
        self._register(
            "search_knowledge",
            "在本地项目文档、代码和设备手册中检索信息。",
            {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索问题"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            self._search_knowledge,
        )
        self._register(
            "remember_user_fact",
            "仅在用户明确要求记住信息时保存用户偏好、档案或物品位置。",
            {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["preference", "profile", "location", "instruction"],
                    },
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["kind", "key", "value"],
                "additionalProperties": False,
            },
            self._remember_user_fact,
        )
        self._register(
            "get_robot_status",
            "读取机器人或设备桥接器的当前状态。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            self._get_robot_status,
        )
        self._register(
            "execute_robot_action",
            "执行G1运动。只有用户明确发出运动命令时才能调用。"
            "按时间直线前进时，action必须为move，direction必须为forward，"
            "duration_seconds填写用户要求的秒数。"
            "例如前进三秒对应duration_seconds为3。"
            "中文数字、小数和时间表达需要转换成阿拉伯数字。"
            "用户未提供时间和距离时默认前进1秒。"
            "按距离前进时使用distance_m。"
            "左转或右转使用action为turn、direction为left或right、"
            "angle_deg为角度。停止使用action为stop。"
            "不要为询问、解释、假设或带有吗的句子调用运动工具。",
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["move", "turn", "stop"],
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["forward", "left", "right"],
                    },
                    "duration_seconds": {
                        "type": "number",
                        "description": "直线前进时间，单位秒",
                    },
                    "distance_m": {
                        "type": "number",
                        "description": "前进距离，单位米",
                    },
                    "angle_deg": {
                        "type": "number",
                        "description": "转向角度，单位度",
                    },
                    "target": {
                        "type": "string",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            self._execute_robot_action,
        )

    def _register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
    ) -> None:
        self._tools[name] = RegisteredTool(
            definition={
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
            handler=handler,
        )

    async def _get_current_time(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        return {"timezone": "Asia/Shanghai", "iso": now.isoformat()}

    async def _search_knowledge(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return {"error": "query is required"}
        response = await self.rag.search(query)
        return {
            "embedding_used": response.embedding_used,
            "results": [item.model_dump() for item in response.results],
        }

    async def _remember_user_fact(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        if not memory_was_requested(context.user_text):
            return {"denied": True, "reason": "用户没有明确要求保存该信息"}
        kind = str(arguments.get("kind", ""))
        if kind not in {"preference", "profile", "location", "instruction"}:
            return {"error": "invalid memory kind"}
        key = str(arguments.get("key", "")).strip()
        value = str(arguments.get("value", "")).strip()
        if not key or not value:
            return {"error": "key and value are required"}
        memory = await self.database.upsert_memory(
            kind,
            key[:200],
            value[:5000],
            1.0,
            "agent_user_confirmed",
        )
        return {"memory": memory.model_dump(mode="json")}

    async def _get_robot_status(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        if self.settings.g1_status_file:
            return await self.device_bridge.get_status()
        if self.settings.device_simulation:
            return {
                "mode": "simulation",
                "online": True,
                "state": "idle",
                "emergency_stop": False,
            }
        return await self.device_bridge.get_status()

    async def _execute_robot_action(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        action = str(arguments.get("action", "")).strip()

        if action not in {
            "move",
            "turn",
            "gesture",
            "mode",
            "stop",
        }:
            return {
                "denied": True,
                "reason": (
                    "当前只允许前进、左右转、"
                    "交互动作、模式切换和停止"
                ),
            }

        authorized = is_authorized_motion_command(
            context.user_text,
            action,
        )

        # 坡道动作由确定性语音路由授权，不交给大模型猜测。
        if action == "move":
            target = str(
                arguments.get("target", "")
            ).strip()

            if target == RAMP_PREPARE_TARGET:
                authorized = is_ramp_prepare_command(
                    context.user_text
                )

            elif target == RAMP_RETURN_TARGET:
                authorized = is_ramp_return_command(
                    context.user_text
                )

            elif target == TURNING_FORWARD_TARGET:
                authorized = is_turning_forward_command(
                    context.user_text
                )

            elif target == TURNING_RETURN_TARGET:
                authorized = is_turning_return_command(
                    context.user_text
                )

        if action == "gesture":
            authorized = (
                parse_interaction_command(context.user_text)
                == str(arguments.get("target", "")).strip()
            )

        if action == "mode":
            authorized = is_mode_confirmation_command(
                context.user_text
            )

        if action != "stop" and not authorized:
            return {
                "denied": True,
                "reason": "没有检测到明确的机器人动作指令",
            }

        payload = dict(arguments)

        if (
            action == "move"
            and arguments.get("target") == FORWARD_THREE_STEPS_TARGET
            and is_forward_three_steps_command(context.user_text)
        ):
            payload["target"] = FORWARD_THREE_STEPS_TARGET

        payload["confirmed"] = True
        payload = normalize_motion_payload(payload)

        if self.settings.device_simulation:
            return {
                "mode": "simulation",
                "accepted": True,
                "command": payload,
            }

        if action != "stop" and not self.settings.device_real_actions_enabled:
            return {
                "denied": True,
                "reason": "真实设备动作未启用",
                "proposed_command": payload,
            }

        return await self.device_bridge.execute_action(payload)

    @staticmethod
    def _memory_was_requested(text: str) -> bool:
        return memory_was_requested(text)


class AgentService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        ollama: OllamaClient,
        rag: RagService,
        tools: ToolRegistry,
    ) -> None:
        self.settings = settings
        self.database = database
        self.ollama = ollama
        self.rag = rag
        self.tools = tools

    async def run(self, request: AgentRequest) -> AgentResponse:
        session = await self.database.get_session(request.session_id)
        if session is None:
            raise ValueError("Session not found")

        route = route_query(request.content)
        selected_model = (
            self.settings.ollama_complex_model
            if route.model_role == "complex"
            else self.settings.ollama_model
        )
        effective_rag = (
            request.use_rag
            and route.use_rag
            and self.settings.rag_enabled
        )
        print(
            f"[MODEL_ROUTE] kind={route.kind} "
            f"model={selected_model} "
            f"rag={str(effective_rag).lower()}",
            flush=True,
        )
        automatic_memory = await remember_text_if_requested(
            self.database, request.content, request.session_id, "agent_keyword_trigger"
        )
        await self.database.add_message(request.session_id, "user", request.content)
        history = await self.database.get_messages(
            request.session_id,
            self.settings.max_history_messages,
        )
        citations = []
        knowledge_context = ""
        if effective_rag:
            search = await self.rag.search(request.content)
            citations = search.results
            if citations:
                blocks = [
                    f"[来源 {index}: {item.filename}，片段 {item.position}]\n{item.content}"
                    for index, item in enumerate(citations, start=1)
                ]
                knowledge_context = "\n\n本地知识库检索结果：\n" + "\n\n".join(blocks)
        memories = await self.database.list_memories(limit=30)
        memory_context = ""
        if memories:
            memory_context = "\n\n已确认的用户记忆：\n" + "\n".join(
                f"- {item.kind}/{item.key}: {item.value}" for item in memories
            )
        thinking_prefix = "" if self.settings.ollama_think else "/no_think\n"
        system = (
            thinking_prefix
            + self.settings.system_prompt
            + memory_context
            + knowledge_context
            + "\n工具调用必须依据真实需要；工具失败时向用户说明，不得伪造成功。"
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages.extend(
            {"role": item.role, "content": item.content}
            for item in history
        )
        executions: list[ToolExecution] = []
        if automatic_memory is not None:
            executions.append(
                ToolExecution(
                    name="remember_user_text",
                    arguments={"trigger": "记住"},
                    result={"memory": automatic_memory.model_dump(mode="json")},
                    status="success",
                )
            )
        final_content = ""
        context = ToolContext(request.session_id, request.content)
        definitions = self.tools.definitions(request.content)

        if not route.use_rag:
            definitions = [
                item
                for item in definitions
                if item.get("function", {}).get("name")
                != "search_knowledge"
            ]

        for _ in range(self.settings.agent_max_steps):
            result = await self.ollama.chat_raw(
                messages,
                definitions,
                model=selected_model,
            )
            message = result.get("message") or {}
            content = str(message.get("content") or "")
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                final_content = content.strip()
                break
            messages.append(message)
            for call in tool_calls:
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {"raw": arguments}
                execution = await self.tools.execute(name, arguments, context)
                executions.append(execution)
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(execution.result, ensure_ascii=False),
                    }
                )
        if not final_content:
            if executions:
                final_content = "工具调用已经完成，但模型没有生成最终说明。请查看工具执行结果。"
            else:
                raise OllamaError("Agent returned an empty response")
        await self.database.add_message(request.session_id, "assistant", final_content)
        return AgentResponse(
            session_id=request.session_id,
            content=final_content,
            citations=citations,
            tool_executions=executions,
        )
