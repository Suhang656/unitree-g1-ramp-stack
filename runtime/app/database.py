import asyncio
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.schemas import (
    DocumentSummary,
    MemoryRecord,
    SessionSummary,
    StoredMessage,
    ToolAuditRecord,
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._initialize_sync)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_sync(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_id_id
                ON messages(session_id, id);

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    content_type TEXT,
                    size_bytes INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK (status IN ('processing', 'ready', 'error')),
                    error TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_document_position
                ON knowledge_chunks(document_id, position);

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(kind, key)
                );

                CREATE TABLE IF NOT EXISTS tool_audit_logs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    async def create_session(self, title: str | None = None) -> SessionSummary:
        return await asyncio.to_thread(self._create_session_sync, title)

    def _create_session_sync(self, title: str | None) -> SessionSummary:
        now = self._now()
        session_id = str(uuid4())
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
        return SessionSummary(id=session_id, title=title, created_at=now, updated_at=now)

    async def get_session(self, session_id: str) -> SessionSummary | None:
        row = await asyncio.to_thread(self._fetchone, "SELECT * FROM sessions WHERE id = ?", (session_id,))
        return SessionSummary.model_validate(dict(row)) if row else None

    async def list_sessions(self, limit: int = 50) -> list[SessionSummary]:
        rows = await asyncio.to_thread(
            self._fetchall,
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [SessionSummary.model_validate(dict(row)) for row in rows]

    async def delete_session(self, session_id: str) -> bool:
        return await asyncio.to_thread(self._delete_session_sync, session_id)

    def _delete_session_sync(self, session_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0

    async def add_message(self, session_id: str, role: str, content: str) -> StoredMessage:
        return await asyncio.to_thread(self._add_message_sync, session_id, role, content)

    def _add_message_sync(self, session_id: str, role: str, content: str) -> StoredMessage:
        now = self._now()
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, now),
            )
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        return StoredMessage(
            id=int(cursor.lastrowid),
            session_id=session_id,
            role=role,
            content=content,
            created_at=now,
        )

    async def get_messages(self, session_id: str, limit: int = 100) -> list[StoredMessage]:
        rows = await asyncio.to_thread(
            self._fetchall,
            """
            SELECT * FROM (
                SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
            ) ORDER BY id ASC
            """,
            (session_id, limit),
        )
        return [StoredMessage.model_validate(dict(row)) for row in rows]

    async def create_document(
        self,
        filename: str,
        content_type: str | None,
        size_bytes: int,
    ) -> DocumentSummary:
        return await asyncio.to_thread(
            self._create_document_sync,
            filename,
            content_type,
            size_bytes,
        )

    def _create_document_sync(
        self,
        filename: str,
        content_type: str | None,
        size_bytes: int,
    ) -> DocumentSummary:
        document_id = str(uuid4())
        now = self._now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO documents
                (id, filename, content_type, size_bytes, chunk_count, status, error, created_at)
                VALUES (?, ?, ?, ?, 0, 'processing', NULL, ?)
                """,
                (document_id, filename, content_type, size_bytes, now),
            )
        return DocumentSummary(
            id=document_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            chunk_count=0,
            status="processing",
            created_at=now,
        )

    async def finish_document(
        self,
        document_id: str,
        chunks: list[tuple[int, str, list[float] | None]],
    ) -> None:
        await asyncio.to_thread(self._finish_document_sync, document_id, chunks)

    def _finish_document_sync(
        self,
        document_id: str,
        chunks: list[tuple[int, str, list[float] | None]],
    ) -> None:
        now = self._now()
        rows = [
            (
                document_id,
                position,
                content,
                json.dumps(embedding) if embedding is not None else None,
                now,
            )
            for position, content, embedding in chunks
        ]
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT INTO knowledge_chunks
                (document_id, position, content, embedding, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.execute(
                """
                UPDATE documents
                SET status = 'ready', chunk_count = ?, error = NULL
                WHERE id = ?
                """,
                (len(rows), document_id),
            )

    async def fail_document(self, document_id: str, error: str) -> None:
        await asyncio.to_thread(
            self._execute,
            "UPDATE documents SET status = 'error', error = ? WHERE id = ?",
            (error[:2000], document_id),
        )

    async def list_documents(self) -> list[DocumentSummary]:
        rows = await asyncio.to_thread(
            self._fetchall,
            "SELECT * FROM documents ORDER BY created_at DESC",
            (),
        )
        return [DocumentSummary.model_validate(dict(row)) for row in rows]

    async def delete_document(self, document_id: str) -> bool:
        return await asyncio.to_thread(self._delete_document_sync, document_id)

    def _delete_document_sync(self, document_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return cursor.rowcount > 0

    async def get_knowledge_chunks(self) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._fetchall,
            """
            SELECT c.id, c.document_id, d.filename, c.position, c.content, c.embedding
            FROM knowledge_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.status = 'ready'
            ORDER BY c.id
            """,
            (),
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw_embedding = item.pop("embedding")
            item["embedding"] = json.loads(raw_embedding) if raw_embedding else None
            results.append(item)
        return results

    async def update_chunk_embeddings(
        self, updates: list[tuple[int, list[float]]]
    ) -> None:
        await asyncio.to_thread(self._update_chunk_embeddings_sync, updates)

    def _update_chunk_embeddings_sync(
        self, updates: list[tuple[int, list[float]]]
    ) -> None:
        rows = [(json.dumps(embedding), chunk_id) for chunk_id, embedding in updates]
        with self._connection() as connection:
            connection.executemany(
                "UPDATE knowledge_chunks SET embedding = ? WHERE id = ?", rows
            )

    async def upsert_memory(
        self,
        kind: str,
        key: str,
        value: str,
        confidence: float,
        source: str,
    ) -> MemoryRecord:
        return await asyncio.to_thread(
            self._upsert_memory_sync,
            kind,
            key,
            value,
            confidence,
            source,
        )

    def _upsert_memory_sync(
        self,
        kind: str,
        key: str,
        value: str,
        confidence: float,
        source: str,
    ) -> MemoryRecord:
        now = self._now()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT id, created_at FROM memories WHERE kind = ? AND key = ?",
                (kind, key),
            ).fetchone()
            if existing:
                memory_id = existing["id"]
                created_at = existing["created_at"]
                connection.execute(
                    """
                    UPDATE memories
                    SET value = ?, confidence = ?, source = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (value, confidence, source, now, memory_id),
                )
            else:
                memory_id = str(uuid4())
                created_at = now
                connection.execute(
                    """
                    INSERT INTO memories
                    (id, kind, key, value, confidence, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (memory_id, kind, key, value, confidence, source, now, now),
                )
        return MemoryRecord(
            id=memory_id,
            kind=kind,
            key=key,
            value=value,
            confidence=confidence,
            source=source,
            created_at=created_at,
            updated_at=now,
        )

    async def list_memories(self, limit: int = 100) -> list[MemoryRecord]:
        rows = await asyncio.to_thread(
            self._fetchall,
            "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [MemoryRecord.model_validate(dict(row)) for row in rows]

    async def delete_memory(self, memory_id: str) -> bool:
        return await asyncio.to_thread(self._delete_memory_sync, memory_id)

    def _delete_memory_sync(self, memory_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0

    async def log_tool_execution(
        self,
        session_id: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        status: str,
    ) -> None:
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO tool_audit_logs
            (id, session_id, tool_name, arguments_json, result_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                session_id,
                tool_name,
                json.dumps(arguments, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                status,
                self._now(),
            ),
        )

    async def list_tool_audits(self, limit: int = 100) -> list[ToolAuditRecord]:
        rows = await asyncio.to_thread(
            self._fetchall,
            "SELECT * FROM tool_audit_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [
            ToolAuditRecord(
                id=row["id"],
                session_id=row["session_id"],
                name=row["tool_name"],
                arguments=json.loads(row["arguments_json"]),
                result=json.loads(row["result_json"]),
                status=row["status"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _fetchone(self, query: str, parameters: tuple[Any, ...]) -> sqlite3.Row | None:
        with self._connection() as connection:
            return connection.execute(query, parameters).fetchone()

    def _fetchall(self, query: str, parameters: tuple[Any, ...]) -> list[sqlite3.Row]:
        with self._connection() as connection:
            return connection.execute(query, parameters).fetchall()

    def _execute(self, query: str, parameters: tuple[Any, ...]) -> None:
        with self._connection() as connection:
            connection.execute(query, parameters)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
