"""NDJSON worker for the pinned Mem0 OSS raw-retrieval adapter.

This file is executed directly by the Python interpreter in the isolated Mem0
virtual environment.  Keep it independent from ``autopsy_memory`` imports: the
competitor environment intentionally contains Mem0 and its dependencies only.
"""

from __future__ import annotations

import gc
import importlib.metadata
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MEM0_VERSION = "2.0.11"
MEM0_COMMIT = "f2532f072fdefa4c90264acc80af0984309f8b06"
EMBEDDING_MODEL = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
EMBEDDING_REVISION = "b207367332321f8e44f96e224ef15bc607f4dbf0"
EMBEDDING_DIMENSIONS = 384
CORPUS_USER_ID = "autopsy-external-evaluation"
SEARCH_THRESHOLD = 0.1


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _distribution_direct_url(name: str) -> dict[str, Any]:
    try:
        raw = importlib.metadata.distribution(name).read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _expiration_date(value: str) -> str | None:
    parsed = _parse_timestamp(value)
    return parsed.date().isoformat() if parsed is not None else None


def _raw_document_text(document: dict[str, Any]) -> str:
    # Title and text are both fields of the query-free raw corpus. Opaque ids,
    # timestamps, repository handles, and expiration data are never embedded.
    title = str(document.get("title") or "").strip()
    text = str(document.get("text") or "").strip()
    return "\n".join(part for part in (title, text) if part)


class Mem0RawWorker:
    def __init__(self, root: Path):
        os.environ["MEM0_TELEMETRY"] = "false"
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.memory = None
        self.fingerprint = ""
        self.mem0_to_document: dict[str, str] = {}
        self.document_policy: dict[str, dict[str, str]] = {}
        self.ingestion_history: list[dict[str, Any]] = []
        self.evaluated_documents = 0
        self.evaluated_embedded = 0
        self.searches = 0
        self.resolved_embedding_revision = ""

    def handshake(self) -> dict[str, Any]:
        versions = {
            name: _distribution_version(name)
            for name in (
                "mem0ai",
                "sentence-transformers",
                "transformers",
                "torch",
                "qdrant-client",
                "pydantic",
            )
        }
        if versions["mem0ai"] != MEM0_VERSION:
            raise RuntimeError(
                f"Mem0 environment mismatch: expected mem0ai {MEM0_VERSION}, found {versions['mem0ai']}"
            )
        return {
            "protocol": "autopsy-mem0-raw-ndjson/v1",
            "python": sys.version.split()[0],
            "packages": versions,
            "mem0_direct_url": _distribution_direct_url("mem0ai"),
            "mem0_commit": MEM0_COMMIT,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_revision": EMBEDDING_REVISION,
            "embedding_dimensions": EMBEDDING_DIMENSIONS,
            "telemetry": False,
        }

    def _close_memory(self) -> None:
        if self.memory is None:
            return
        vector_store = getattr(self.memory, "vector_store", None)
        client = getattr(vector_store, "client", None)
        close = getattr(client, "close", None)
        if callable(close):
            close()
        self.memory = None
        gc.collect()

    def _new_memory(self, fingerprint: str):
        from mem0 import Memory

        self._close_memory()
        corpus_root = self.root / f"corpus-{fingerprint[:24]}"
        if corpus_root.exists():
            shutil.rmtree(corpus_root)
        qdrant_path = corpus_root / "qdrant"
        corpus_root.mkdir(parents=True, exist_ok=True)
        configuration = {
            "version": "v1.1",
            "history_db_path": str(corpus_root / "history.db"),
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": f"autopsy_mem0_{fingerprint[:20]}",
                    "embedding_model_dims": EMBEDDING_DIMENSIONS,
                    "path": str(qdrant_path),
                    "on_disk": True,
                },
            },
            "embedder": {
                "provider": "huggingface",
                "config": {
                    "model": EMBEDDING_MODEL,
                    "embedding_dims": EMBEDDING_DIMENSIONS,
                    "model_kwargs": {"revision": EMBEDDING_REVISION},
                },
            },
            # Memory constructs an LLM client even when infer=False. This
            # unreachable loopback endpoint makes accidental inference fail
            # closed; no request is made by the raw-memory path.
            "llm": {
                "provider": "openai",
                "config": {
                    "model": "disabled-for-infer-false",
                    "api_key": "not-used",
                    "openai_base_url": "http://127.0.0.1:9/v1",
                },
            },
        }
        memory = Memory.from_config(configuration)
        sentence_transformer = getattr(memory.embedding_model, "model", None)
        first_module = sentence_transformer._first_module() if sentence_transformer is not None else None
        transformer_model = getattr(first_module, "auto_model", None)
        transformer_config = getattr(transformer_model, "config", None)
        resolved_revision = str(getattr(transformer_config, "_commit_hash", None) or "")
        if resolved_revision != EMBEDDING_REVISION:
            raise RuntimeError(
                "Embedding cache revision mismatch: "
                f"expected {EMBEDDING_REVISION}, resolved {resolved_revision or 'unknown'}"
            )
        self.resolved_embedding_revision = resolved_revision
        return memory

    def prepare(self, message: dict[str, Any]) -> dict[str, Any]:
        fingerprint = str(message.get("corpus_fingerprint") or "")
        documents = message.get("documents")
        if not fingerprint or not isinstance(documents, list):
            raise ValueError("prepare requires a corpus fingerprint and document list")
        if fingerprint == self.fingerprint:
            return {
                "reused": True,
                "corpus_fingerprint": fingerprint,
                "documents": len(documents),
                "seconds": 0.0,
            }

        started = time.perf_counter()
        self.memory = self._new_memory(fingerprint)
        self.mem0_to_document.clear()
        self.document_policy.clear()
        embedded = 0
        characters = 0
        for document in documents:
            document_id = str(document.get("document_id") or "")
            if not document_id or document_id in self.document_policy:
                raise ValueError("prepared documents require unique non-empty opaque ids")
            raw_text = _raw_document_text(document)
            if not raw_text:
                raise ValueError(f"prepared document {document_id!r} has no indexable text")
            repository_id = str(document.get("repository_id") or "")
            expired_at = str(document.get("expired_at") or "")
            metadata = {"repository_id": repository_id} if repository_id else None
            result = self.memory.add(
                raw_text,
                user_id=CORPUS_USER_ID,
                metadata=metadata,
                expiration_date=_expiration_date(expired_at),
                infer=False,
            )
            rows = list(result.get("results") or [])
            if len(rows) != 1 or not rows[0].get("id"):
                raise RuntimeError("Mem0 infer=False did not return exactly one raw memory id")
            memory_id = str(rows[0]["id"])
            if memory_id in self.mem0_to_document:
                raise RuntimeError("Mem0 returned a duplicate memory id")
            self.mem0_to_document[memory_id] = document_id
            self.document_policy[document_id] = {
                "repository_id": repository_id,
                "expired_at": expired_at,
            }
            embedded += 1
            characters += len(raw_text)

        elapsed = time.perf_counter() - started
        self.fingerprint = fingerprint
        self.evaluated_documents += len(documents)
        self.evaluated_embedded += embedded
        payload = {
            "reused": False,
            "corpus_fingerprint": fingerprint,
            "documents": len(documents),
            "characters": characters,
            "relations": int(message.get("relation_count") or 0),
            "relations_indexed": 0,
            "embedded_items": embedded,
            "infer": False,
            "seconds": elapsed,
            "documents_per_second": len(documents) / elapsed if elapsed else None,
        }
        self.ingestion_history.append(payload)
        return payload

    def retrieve(self, message: dict[str, Any]) -> dict[str, Any]:
        if self.memory is None:
            raise RuntimeError("prepare must complete before retrieve")
        query = str(message.get("query") or "").strip()
        limit = int(message.get("limit") or 0)
        if not query or limit < 1:
            raise ValueError("retrieve requires a non-empty query and positive limit")
        scope = str(message.get("scope") or "system")
        repository_id = str(message.get("repository_id") or "")
        filters: dict[str, Any] = {"user_id": CORPUS_USER_ID}
        if scope == "repo" and repository_id:
            filters["repository_id"] = repository_id

        # Mem0 OSS 2.0.11 explicitly rejects reference_date. Search therefore
        # uses its native current-state behavior and reports any requested
        # as-of timestamp as unsupported instead of emulating historical state.
        candidate_limit = min(
            len(self.mem0_to_document),
            max(limit * 4, 60),
        )
        started = time.perf_counter()
        raw = self.memory.search(
            query,
            top_k=max(1, candidate_limit),
            filters=filters,
            threshold=SEARCH_THRESHOLD,
            rerank=False,
            show_expired=False,
        )
        now = datetime.now(timezone.utc)
        ranked: list[str] = []
        scores: list[float] = []
        unknown_memory_ids = 0
        scope_postfiltered = 0
        expiration_postfiltered = 0
        for row in list(raw.get("results") or []):
            document_id = self.mem0_to_document.get(str(row.get("id") or ""))
            if document_id is None:
                unknown_memory_ids += 1
                continue
            policy = self.document_policy[document_id]
            if scope == "repo" and repository_id and policy["repository_id"] != repository_id:
                scope_postfiltered += 1
                continue
            expiration = _parse_timestamp(policy["expired_at"])
            if expiration is not None and expiration <= now:
                expiration_postfiltered += 1
                continue
            ranked.append(document_id)
            scores.append(float(row.get("score") or 0.0))
            if len(ranked) >= limit:
                break
        elapsed = time.perf_counter() - started
        self.searches += 1
        requested_as_of = str(message.get("as_of") or "")
        return {
            "ranked_document_ids": ranked,
            "latency_seconds": elapsed,
            "route": "mem0-oss-native-search",
            "retrieval_reasons": [["embedding", "mem0-native-search"] for _ in ranked],
            "diagnostics": {
                "scores": scores,
                "threshold": SEARCH_THRESHOLD,
                "candidate_limit": candidate_limit,
                "native_repository_filter": scope == "repo" and bool(repository_id),
                "repository_scope_postfiltered": scope_postfiltered,
                "native_expiration_filter": True,
                "exact_expiration_postfiltered": expiration_postfiltered,
                "expiration_reference": "runtime_utc_now",
                "requested_as_of": requested_as_of,
                "native_as_of_supported": False,
                "as_of_applied": False,
                "unknown_memory_ids": unknown_memory_ids,
                "infer": False,
            },
        }

    def capabilities(self) -> dict[str, Any]:
        store_bytes = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        return {
            **self.handshake(),
            "documents": len(self.document_policy),
            "embedded_items": len(self.mem0_to_document),
            "vector_coverage": (
                len(self.mem0_to_document) / len(self.document_policy)
                if self.document_policy
                else 0.0
            ),
            "evaluated_eligible_items": self.evaluated_documents,
            "evaluated_embedded_items": self.evaluated_embedded,
            "evaluated_vector_coverage": (
                self.evaluated_embedded / self.evaluated_documents
                if self.evaluated_documents
                else 0.0
            ),
            "embedding_model_revision": EMBEDDING_REVISION,
            "embedding_model_resolved_revision": self.resolved_embedding_revision,
            "repository_scope_filter": True,
            "repository_scope_filter_mode": "native-qdrant-metadata-filter-plus-result-verification",
            "temporal_expiration_filter": True,
            "temporal_expiration_filter_mode": "mem0-native-date-plus-exact-runtime-postfilter",
            "native_as_of_support": False,
            "relation_support": False,
            "searches": self.searches,
            "store_bytes": store_bytes,
        }

    def close(self) -> dict[str, Any]:
        self._close_memory()
        return {"closed": True}


def _respond(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: mem0_worker.py STORE_ROOT")
    worker = Mem0RawWorker(Path(sys.argv[1]))
    actions = {
        "handshake": lambda message: worker.handshake(),
        "prepare": worker.prepare,
        "retrieve": worker.retrieve,
        "reset": lambda message: {"reset": True, "adaptive_query_state": False},
        "capabilities": lambda message: worker.capabilities(),
        "close": lambda message: worker.close(),
    }
    for line in sys.stdin:
        request_id = None
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise TypeError("protocol message must be an object")
            request_id = message.get("request_id")
            action = str(message.get("action") or "")
            handler = actions.get(action)
            if handler is None:
                raise ValueError(f"unsupported protocol action: {action!r}")
            result = handler(message)
            _respond({"ok": True, "request_id": request_id, "result": result})
            if action == "close":
                return 0
        except Exception as exc:
            _respond(
                {
                    "ok": False,
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
    worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
