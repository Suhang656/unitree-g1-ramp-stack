import asyncio
import httpx
import math
import re
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any

from app.config import Settings
from app.database import Database
from app.ollama import OllamaClient, OllamaError
from app.schemas import DocumentSummary, KnowledgeChunk, KnowledgeSearchResponse


SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".yaml", ".yml", ".csv", ".log", ".pdf", ".docx",
}


class DocumentError(ValueError):
    pass


class DocumentParser:
    @staticmethod
    def extract(filename: str, content: bytes) -> str:
        extension = Path(filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise DocumentError(f"Unsupported document type: {extension or 'unknown'}")
        if extension == ".pdf":
            return DocumentParser._extract_pdf(content)
        if extension == ".docx":
            return DocumentParser._extract_docx(content)
        return DocumentParser._decode_text(content)

    @staticmethod
    def _decode_text(content: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise DocumentError("Unable to decode text document")

    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(content))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:
            raise DocumentError(f"Unable to parse PDF: {exc}") from exc

    @staticmethod
    def _extract_docx(content: bytes) -> str:
        try:
            from docx import Document

            document = Document(BytesIO(content))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        except Exception as exc:
            raise DocumentError(f"Unable to parse DOCX: {exc}") from exc


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    cleaned = re.sub(r"\r\n?", "\n", text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        if end < len(cleaned):
            boundary = max(
                cleaned.rfind("\n\n", start, end),
                cleaned.rfind("\n#", start, end),
                cleaned.rfind("。", start, end),
                cleaned.rfind("！", start, end),
                cleaned.rfind("？", start, end),
                cleaned.rfind(". ", start, end),
            )
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


class LocalQwenReranker:
    """Lazy local Qwen3 cross-encoder reranker.

    The prompt and yes/no scoring follow Qwen's official Qwen3-Reranker
    Transformers example. Loading is deferred until the first query so the
    application still works with hybrid retrieval when the optional package or
    model has not yet been installed.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._loaded = False
        self._torch: Any = None
        self._tokenizer: Any = None
        self._model: Any = None
        self._prefix_tokens: list[int] = []
        self._suffix_tokens: list[int] = []
        self._true_token_id = 0
        self._false_token_id = 0

    def _load(self) -> None:
        if self._loaded:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        requested_device = self.settings.rag_reranker_device.lower()
        device = "cuda" if requested_device == "auto" and torch.cuda.is_available() else requested_device
        if device == "auto":
            device = "cpu"
        kwargs: dict[str, Any] = {}
        if device == "cuda":
            kwargs["torch_dtype"] = torch.float16
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.settings.rag_reranker_model,
            padding_side="left",
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            self.settings.rag_reranker_model,
            **kwargs,
        ).to(device).eval()
        self._torch = torch
        self._false_token_id = self._tokenizer.convert_tokens_to_ids("no")
        self._true_token_id = self._tokenizer.convert_tokens_to_ids("yes")
        prefix = (
            '<|im_start|>system\nJudge whether the Document meets the requirements '
            'based on the Query and the Instruct provided. Note that the answer can '
            'only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
        )
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        self._prefix_tokens = self._tokenizer.encode(prefix, add_special_tokens=False)
        self._suffix_tokens = self._tokenizer.encode(suffix, add_special_tokens=False)
        self._loaded = True

    def score(self, query: str, documents: list[str]) -> list[float]:
        self._load()
        assert self._torch is not None and self._tokenizer is not None and self._model is not None
        instruction = (
            "Given a Chinese robot-control or project question, retrieve passages "
            "that directly answer it with accurate operational details."
        )
        pairs = [
            f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {document}"
            for document in documents
        ]
        scores: list[float] = []
        max_length = self.settings.rag_reranker_max_length
        batch_size = self.settings.rag_reranker_batch_size
        for start in range(0, len(pairs), batch_size):
            current_pairs = pairs[start : start + batch_size]
            encoded = self._tokenizer(
                current_pairs,
                padding=False,
                truncation="longest_first",
                return_attention_mask=False,
                max_length=max_length - len(self._prefix_tokens) - len(self._suffix_tokens),
            )
            for index, token_ids in enumerate(encoded["input_ids"]):
                encoded["input_ids"][index] = self._prefix_tokens + token_ids + self._suffix_tokens
            inputs = self._tokenizer.pad(encoded, padding=True, return_tensors="pt", max_length=max_length)
            inputs = {key: value.to(self._model.device) for key, value in inputs.items()}
            with self._torch.no_grad():
                logits = self._model(**inputs).logits[:, -1, :]
                yes = logits[:, self._true_token_id]
                no = logits[:, self._false_token_id]
                probabilities = self._torch.softmax(self._torch.stack([no, yes], dim=1), dim=1)[:, 1]
            scores.extend(float(score) for score in probabilities.detach().cpu().tolist())
        return scores


class RagService:
    def __init__(self, settings: Settings, database: Database, ollama: OllamaClient) -> None:
        self.settings = settings
        self.database = database
        self.ollama = ollama
        self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
        self.last_embedding_error: str | None = None
        self.last_reranker_error: str | None = None
        self._reranker: LocalQwenReranker | None = None

    async def ingest(self, filename: str, content_type: str | None, content: bytes) -> DocumentSummary:
        document = await self.database.create_document(filename, content_type, len(content))
        safe_name = Path(filename).name
        stored_path = self.settings.upload_dir / f"{document.id}_{safe_name}"
        try:
            text = DocumentParser.extract(safe_name, content)
            chunks = split_text(text, self.settings.rag_chunk_size, self.settings.rag_chunk_overlap)
            if not chunks:
                raise DocumentError("Document contains no extractable text")
            stored_path.write_bytes(content)
            embeddings = await self._embed_or_none(chunks)
            rows = [(index, chunk, embeddings[index] if embeddings else None) for index, chunk in enumerate(chunks)]
            await self.database.finish_document(document.id, rows)
            document.status = "ready"
            document.chunk_count = len(rows)
            return document
        except Exception as exc:
            await self.database.fail_document(document.id, str(exc))
            stored_path.unlink(missing_ok=True)
            raise

    async def delete_document(self, document_id: str) -> bool:
        documents = await self.database.list_documents()
        document = next((item for item in documents if item.id == document_id), None)
        deleted = await self.database.delete_document(document_id)
        if deleted and document:
            for path in self.settings.upload_dir.glob(f"{document.id}_*"):
                path.unlink(missing_ok=True)
        return deleted

    async def search(self, query: str, top_k: int | None = None) -> KnowledgeSearchResponse:
        limit = top_k or self.settings.rag_top_k
        chunks = await self.database.get_knowledge_chunks()
        if not chunks:
            return KnowledgeSearchResponse(query=query, results=[], embedding_used=False)
        query_embedding = await self._embed_query(query)
        embedding_used = query_embedding is not None and any(item["embedding"] for item in chunks)
        lexical_ranking = self._bm25_rank(query, chunks)
        dense_ranking = self._dense_rank(query_embedding, chunks) if embedding_used else []
        candidate_count = min(max(limit, self.settings.rag_candidate_k), len(chunks))
        fused = self._rrf_fuse(lexical_ranking, dense_ranking, candidate_count)
        reranked = await self._rerank_or_none(query, fused)
        final_ranking = reranked if reranked is not None else fused
        results = [
            KnowledgeChunk(
                id=item["id"], document_id=item["document_id"], filename=item["filename"],
                position=item["position"], content=item["content"], score=round(score, 6),
            )
            for score, item in final_ranking[:limit]
        ]
        return KnowledgeSearchResponse(query=query, results=results, embedding_used=embedding_used)

    async def _remote_rerank(
        self, query: str, documents: list[str]
    ) -> list[float]:
        base_url = self.settings.rag_reranker_base_url
        if not base_url:
            raise RuntimeError("远程精排地址未配置")

        endpoint = f"{base_url.rstrip('/')}/rerank"
        payload = {
            "query": query,
            "documents": documents,
            "top_k": len(documents),
        }

        async with httpx.AsyncClient(
            timeout=self.settings.rag_reranker_timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()

        results = data.get("results")
        if not isinstance(results, list) or len(results) != len(documents):
            raise RuntimeError("远程精排服务返回的结果数量异常")

        scores: list[float | None] = [None] * len(documents)
        for item in results:
            if not isinstance(item, dict):
                raise RuntimeError("远程精排服务返回格式异常")
            index = item.get("index")
            if not isinstance(index, int) or not 0 <= index < len(documents):
                raise RuntimeError("远程精排服务返回了无效索引")
            scores[index] = float(item["score"])

        if any(score is None for score in scores):
            raise RuntimeError("远程精排服务返回不完整")
        return [float(score) for score in scores]

    async def _rerank_or_none(self, query: str, candidates: list[tuple[float, dict[str, Any]]]) -> list[tuple[float, dict[str, Any]]] | None:
        if not candidates or not self.settings.rag_reranker_enabled or self.last_reranker_error:
            return None
        try:
            documents = [item["content"] for _, item in candidates]
            if self.settings.rag_reranker_base_url:
                scores = await self._remote_rerank(query, documents)
            else:
                if self._reranker is None:
                    self._reranker = LocalQwenReranker(self.settings)
                scores = await asyncio.to_thread(self._reranker.score, query, documents)
            self.last_reranker_error = None
            return sorted(zip(scores, [item for _, item in candidates], strict=True), key=lambda pair: pair[0], reverse=True)
        except Exception as exc:
            self.last_reranker_error = str(exc)
            return None

    def _bm25_rank(self, query: str, chunks: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
        query_terms = self._terms(query)
        if not query_terms:
            return []
        documents = [self._terms_with_frequency(item["content"]) for item in chunks]
        document_count = len(documents)
        average_length = sum(sum(counter.values()) for counter in documents) / max(document_count, 1)
        document_frequency = Counter(term for terms in documents for term in terms)
        scores: list[tuple[float, dict[str, Any]]] = []
        for item, terms in zip(chunks, documents, strict=True):
            length = max(sum(terms.values()), 1)
            score = 0.0
            for term in query_terms:
                frequency = terms.get(term, 0)
                if not frequency:
                    continue
                idf = math.log(1 + (document_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                numerator = frequency * (self.settings.rag_bm25_k1 + 1)
                denominator = frequency + self.settings.rag_bm25_k1 * (1 - self.settings.rag_bm25_b + self.settings.rag_bm25_b * length / max(average_length, 1.0))
                score += idf * numerator / denominator
            if score > 0:
                scores.append((score, item))
        return sorted(scores, key=lambda pair: pair[0], reverse=True)

    def _dense_rank(self, query_embedding: list[float] | None, chunks: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
        if query_embedding is None:
            return []
        ranking = [(max(0.0, self._cosine(query_embedding, item["embedding"])), item) for item in chunks if item["embedding"]]
        return sorted((pair for pair in ranking if pair[0] > 0), key=lambda pair: pair[0], reverse=True)

    def _rrf_fuse(self, lexical: list[tuple[float, dict[str, Any]]], dense: list[tuple[float, dict[str, Any]]], candidate_count: int) -> list[tuple[float, dict[str, Any]]]:
        rrf_k = self.settings.rag_rrf_k
        scores: dict[int, float] = {}
        items: dict[int, dict[str, Any]] = {}
        for ranking in (lexical[:candidate_count], dense[:candidate_count]):
            for rank, (_, item) in enumerate(ranking, start=1):
                chunk_id = int(item["id"])
                items[chunk_id] = item
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
        return sorted(((score, items[chunk_id]) for chunk_id, score in scores.items()), key=lambda pair: pair[0], reverse=True)[:candidate_count]

    async def _embed_or_none(self, texts: list[str]) -> list[list[float]] | None:
        if not self.settings.rag_enabled or self.last_embedding_error:
            return None
        try:
            embeddings: list[list[float]] = []
            for start in range(0, len(texts), 16):
                embeddings.extend(await self.ollama.embed(texts[start : start + 16], self.settings.rag_embedding_model))
            self.last_embedding_error = None
            return embeddings
        except OllamaError as exc:
            self.last_embedding_error = str(exc)
            return None

    async def _embed_query(self, query: str) -> list[float] | None:
        if not self.settings.rag_enabled or self.last_embedding_error:
            return None
        try:
            result = await self.ollama.embed([query], self.settings.rag_embedding_model)
            self.last_embedding_error = None
            return result[0]
        except OllamaError as exc:
            self.last_embedding_error = str(exc)
            return None

    @staticmethod
    def _terms(text: str) -> set[str]:
        return set(RagService._terms_with_frequency(text))

    @staticmethod
    def _terms_with_frequency(text: str) -> Counter[str]:
        lowered = text.lower()
        terms: list[str] = re.findall(r"[a-z0-9_\-]{2,}", lowered)
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
        terms.extend(chinese[index : index + 2] for index in range(max(0, len(chinese) - 1)))
        terms.extend(chinese[index] for index in range(len(chinese)))
        return Counter(terms)

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)
