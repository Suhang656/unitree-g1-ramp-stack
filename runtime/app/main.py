import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.staticfiles import StaticFiles

from app.agent import AgentService
from app.config import Settings, get_settings
from app.database import Database
from app.memory import remember_text_if_requested
from app.ollama import OllamaClient, OllamaError
from app.rag import DocumentError, RagService
from app.runtime import SmartCenterRuntime
from app.schemas import (
    AgentRequest,
    AgentResponse,
    ChatRequest,
    ChatResponse,
    DocumentSummary,
    HealthResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    Message,
    MemoryRecord,
    MemoryUpsert,
    SessionChatRequest,
    SessionCreate,
    SessionSummary,
    SpeechToTextResponse,
    StoredMessage,
    TextToSpeechRequest,
    ToolAuditRecord,
    VoiceStatus,
)
from app.voice import VoiceService, VoiceUnavailableError


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = await SmartCenterRuntime().start()
    assert runtime.settings and runtime.database and runtime.ollama and runtime.rag and runtime.agent and runtime.voice
    app.state.runtime = runtime
    app.state.settings = runtime.settings
    app.state.database = runtime.database
    app.state.ollama = runtime.ollama
    app.state.rag = runtime.rag
    app.state.agent = runtime.agent
    app.state.voice = runtime.voice
    try:
        yield
    finally:
        await runtime.close()


app = FastAPI(title="智能中控 API", version="1.0.0", lifespan=lifespan)


def get_database(request: Request) -> Database:
    return request.app.state.database


async def require_session(database: Database, session_id: str) -> SessionSummary:
    session = await database.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def sse(event: str, data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@app.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    client: OllamaClient = request.app.state.ollama
    try:
        models = await client.list_models()
        available = client.model in models
        return HealthResponse(
            status="ok" if available else "degraded",
            ollama_url=client.base_url,
            model=client.model,
            model_available=available,
            detail=None if available else f"Available models: {models}",
        )
    except OllamaError as exc:
        return HealthResponse(
            status="degraded",
            ollama_url=client.base_url,
            model=client.model,
            model_available=False,
            detail=str(exc),
        )


@app.post(
    "/api/sessions",
    response_model=SessionSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(body: SessionCreate, request: Request) -> SessionSummary:
    return await get_database(request).create_session(body.title)


@app.get("/api/sessions", response_model=list[SessionSummary])
async def list_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SessionSummary]:
    return await get_database(request).list_sessions(limit)


@app.get("/api/sessions/{session_id}", response_model=SessionSummary)
async def get_session(session_id: str, request: Request) -> SessionSummary:
    return await require_session(get_database(request), session_id)


@app.get("/api/sessions/{session_id}/messages", response_model=list[StoredMessage])
async def get_session_messages(
    session_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[StoredMessage]:
    database = get_database(request)
    await require_session(database, session_id)
    return await database.get_messages(session_id, limit)


@app.delete("/api/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, request: Request) -> Response:
    deleted = await get_database(request).delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    client: OllamaClient = request.app.state.ollama
    try:
        user_text = next(
            (message.content for message in reversed(body.messages) if message.role == "user"),
            None,
        )
        if user_text:
            await remember_text_if_requested(get_database(request), user_text, source="chat_keyword_trigger")
        result = await client.chat(body.messages)
        message = result.get("message") or {}
        return ChatResponse(
            model=result.get("model", client.model),
            message=Message(
                role=message.get("role", "assistant"),
                content=message.get("content", ""),
            ),
            done=bool(result.get("done", False)),
        )
    except (OllamaError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@app.post("/api/chat/stream")
async def stream_chat(body: SessionChatRequest, request: Request) -> StreamingResponse:
    database = get_database(request)
    settings: Settings = request.app.state.settings
    client: OllamaClient = request.app.state.ollama
    rag: RagService = request.app.state.rag
    await require_session(database, body.session_id)
    automatic_memory = await remember_text_if_requested(
        database, body.content, body.session_id, "stream_keyword_trigger"
    )
    user_message = await database.add_message(body.session_id, "user", body.content)
    history = await database.get_messages(body.session_id, settings.max_history_messages)
    system_prompt = settings.system_prompt
    if not settings.ollama_think:
        # 兼容尚未实现 API think 参数的旧版 Ollama/Qwen3 模板。
        system_prompt = "/no_think\n" + system_prompt
    citations = []
    if body.use_rag and settings.rag_enabled:
        search = await rag.search(body.content)
        citations = search.results
        if citations:
            system_prompt += "\n\n本地知识库检索结果：\n" + "\n\n".join(
                f"[来源 {index}: {item.filename}，片段 {item.position}]\n{item.content}"
                for index, item in enumerate(citations, start=1)
            )
    if body.use_memory:
        memories = await database.list_memories(limit=30)
        if memories:
            system_prompt += "\n\n已确认的用户记忆：\n" + "\n".join(
                f"- {item.kind}/{item.key}: {item.value}" for item in memories
            )
    model_messages = [Message(role="system", content=system_prompt)]
    model_messages.extend(Message(role=item.role, content=item.content) for item in history)

    async def generate() -> AsyncIterator[str]:
        yield sse(
            "meta",
            {
                "session_id": body.session_id,
                "user_message_id": user_message.id,
                "model": client.model,
            },
        )
        if citations:
            yield sse(
                "citations",
                {"items": [item.model_dump(mode="json") for item in citations]},
            )
        if automatic_memory is not None:
            yield sse("memory", {"item": automatic_memory.model_dump(mode="json")})
        parts: list[str] = []
        try:
            async for token in client.stream_chat(model_messages):
                parts.append(token)
                yield sse("token", {"content": token})
            content = "".join(parts).strip()
            if not content:
                raise OllamaError("Ollama returned an empty response")
            assistant_message = await database.add_message(
                body.session_id,
                "assistant",
                content,
            )
            yield sse(
                "done",
                {
                    "session_id": body.session_id,
                    "assistant_message_id": assistant_message.id,
                },
            )
        except asyncio.CancelledError:
            raise
        except OllamaError as exc:
            yield sse("error", {"detail": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )


@app.post("/api/agent", response_model=AgentResponse)
async def run_agent(body: AgentRequest, request: Request) -> AgentResponse:
    agent: AgentService = request.app.state.agent
    try:
        return await agent.run(body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@app.post(
    "/api/knowledge/documents",
    response_model=DocumentSummary,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(request: Request, file: UploadFile = File(...)) -> DocumentSummary:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required")
    content = await file.read(25 * 1024 * 1024 + 1)
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File exceeds 25 MB")
    rag: RagService = request.app.state.rag
    try:
        return await rag.ingest(file.filename, file.content_type, content)
    except DocumentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@app.get("/api/knowledge/documents", response_model=list[DocumentSummary])
async def list_documents(request: Request) -> list[DocumentSummary]:
    return await get_database(request).list_documents()


@app.delete("/api/knowledge/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, request: Request) -> Response:
    rag: RagService = request.app.state.rag
    if not await rag.delete_document(document_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    body: KnowledgeSearchRequest,
    request: Request,
) -> KnowledgeSearchResponse:
    rag: RagService = request.app.state.rag
    return await rag.search(body.query, body.top_k)


@app.post("/api/memories", response_model=MemoryRecord)
async def upsert_memory(body: MemoryUpsert, request: Request) -> MemoryRecord:
    return await get_database(request).upsert_memory(
        body.kind,
        body.key,
        body.value,
        body.confidence,
        body.source,
    )


@app.get("/api/memories", response_model=list[MemoryRecord])
async def list_memories(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MemoryRecord]:
    return await get_database(request).list_memories(limit)


@app.delete("/api/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: str, request: Request) -> Response:
    if not await get_database(request).delete_memory(memory_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/audit/tools", response_model=list[ToolAuditRecord])
async def list_tool_audits(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ToolAuditRecord]:
    return await get_database(request).list_tool_audits(limit)


@app.get("/api/voice/status", response_model=VoiceStatus)
async def voice_status(request: Request) -> VoiceStatus:
    voice: VoiceService = request.app.state.voice
    return voice.status()


@app.post("/api/voice/stt", response_model=SpeechToTextResponse)
async def speech_to_text(request: Request, file: UploadFile = File(...)) -> SpeechToTextResponse:
    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio exceeds 20 MB")
    voice: VoiceService = request.app.state.voice
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    try:
        result = await voice.transcribe(content, suffix)
        await remember_text_if_requested(
            get_database(request), result.text, source="voice_stt_keyword_trigger"
        )
        return result
    except VoiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/api/voice/tts")
async def text_to_speech(body: TextToSpeechRequest, request: Request) -> FileResponse:
    voice: VoiceService = request.app.state.voice
    try:
        path = await voice.synthesize(body.text)
    except VoiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="audio/wav",
        filename="speech.wav",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


app.mount("/", StaticFiles(directory="static", html=True), name="ui")
