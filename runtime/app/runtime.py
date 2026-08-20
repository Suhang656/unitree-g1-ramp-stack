"""不依赖 FastAPI 的智能中控运行时。"""

from dataclasses import dataclass

from app.agent import AgentService, ToolRegistry
from app.config import Settings, get_settings
from app.database import Database
from app.ollama import OllamaClient
from app.rag import RagService
from app.voice import VoiceService


@dataclass
class SmartCenterRuntime:
    settings: Settings | None = None
    database: Database | None = None
    ollama: OllamaClient | None = None
    rag_ollama: OllamaClient | None = None
    rag: RagService | None = None
    tools: ToolRegistry | None = None
    agent: AgentService | None = None
    voice: VoiceService | None = None

    async def start(self) -> "SmartCenterRuntime":
        if self.agent is not None:
            return self
        self.settings = self.settings or get_settings()
        self.database = Database(self.settings.database_path)
        await self.database.initialize()
        self.ollama = OllamaClient(self.settings)
        rag_base_url = self.settings.rag_ollama_base_url
        self.rag_ollama = (
            self.ollama
            if not rag_base_url or rag_base_url.rstrip("/") == self.ollama.base_url
            else OllamaClient(self.settings, base_url=rag_base_url)
        )
        self.rag = RagService(self.settings, self.database, self.rag_ollama)
        self.tools = ToolRegistry(self.settings, self.database, self.rag)
        self.agent = AgentService(self.settings, self.database, self.ollama, self.rag, self.tools)
        self.voice = VoiceService(self.settings)
        return self

    async def close(self) -> None:
        if self.ollama is not None:
            await self.ollama.close()
        if self.rag_ollama is not None and self.rag_ollama is not self.ollama:
            await self.rag_ollama.close()
        self.ollama = None
        self.rag_ollama = None
        self.agent = None
        self.tools = None
        self.rag = None
        self.database = None
        self.voice = None
