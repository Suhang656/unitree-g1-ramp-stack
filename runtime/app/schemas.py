from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)


class ChatResponse(BaseModel):
    model: str
    message: Message
    done: bool


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class SessionSummary(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class StoredMessage(BaseModel):
    id: int
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class SessionChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=20_000)
    use_rag: bool = True
    use_memory: bool = True


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    ollama_url: str
    model: str
    model_available: bool
    detail: str | None = None


class DocumentSummary(BaseModel):
    id: str
    filename: str
    content_type: str | None
    size_bytes: int
    chunk_count: int
    status: Literal["processing", "ready", "error"]
    error: str | None = None
    created_at: datetime


class KnowledgeChunk(BaseModel):
    id: int
    document_id: str
    filename: str
    position: int
    content: str
    score: float


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=5000)
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeChunk]
    embedding_used: bool


class MemoryUpsert(BaseModel):
    kind: Literal["preference", "profile", "location", "instruction"]
    key: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=5000)
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: str = Field(default="user_confirmed", max_length=200)


class MemoryRecord(MemoryUpsert):
    id: str
    created_at: datetime
    updated_at: datetime


class AgentRequest(BaseModel):
    session_id: str
    content: str = Field(min_length=1, max_length=20_000)
    use_rag: bool = True


class ToolExecution(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    status: Literal["success", "error", "denied"]


class ToolAuditRecord(ToolExecution):
    id: str
    session_id: str | None
    created_at: datetime


class AgentResponse(BaseModel):
    session_id: str
    content: str
    citations: list[KnowledgeChunk] = Field(default_factory=list)
    tool_executions: list[ToolExecution] = Field(default_factory=list)


class VoiceStatus(BaseModel):
    stt_provider: str
    stt_available: bool
    tts_provider: str
    tts_available: bool
    detail: str | None = None


class SpeechToTextResponse(BaseModel):
    text: str
    language: str | None = None
    duration_seconds: float | None = None


class TextToSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
