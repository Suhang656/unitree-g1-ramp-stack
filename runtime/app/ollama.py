import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import Settings
from app.schemas import Message


class OllamaError(RuntimeError):
    """Raised when the Ollama service cannot satisfy a request."""


class OllamaClient:
    def __init__(self, settings: Settings, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = settings.ollama_model
        self.timeout = settings.ollama_timeout_seconds
        self.keep_alive = settings.ollama_keep_alive
        self.think = settings.ollama_think
        # 本地请求不读取系统代理，避免代理变量阻断 127.0.0.1。
        self._client = httpx.AsyncClient(timeout=self.timeout, trust_env=False)

    async def close(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[str]:
        data = await self._request("GET", "/api/tags")
        return [item["name"] for item in data.get("models", []) if "name" in item]

    async def chat(self, messages: list[Message]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [message.model_dump() for message in messages],
            "stream": False,
            "keep_alive": self.keep_alive,
            "think": self.think,
        }
        return await self._request("POST", "/api/chat", json=payload)

    async def chat_raw(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "think": self.think,
        }
        if tools:
            payload["tools"] = tools
        return await self._request("POST", "/api/chat", json=payload)

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        data = await self._request(
            "POST",
            "/api/embed",
            json={"model": model, "input": texts},
        )
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise OllamaError("Ollama returned invalid embeddings")
        return embeddings

    async def stream_chat(self, messages: list[Message]) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            "keep_alive": self.keep_alive,
            "think": self.think,
        }
        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise OllamaError(str(chunk["error"]))
                    content = (chunk.get("message") or {}).get("content")
                    if content:
                        yield content
        except OllamaError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaError(f"Ollama streaming request failed: {exc}") from exc

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc
