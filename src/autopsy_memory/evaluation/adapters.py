"""Competitor-safe retrieval adapters and adapter provenance manifests.

The adapter interface is intentionally two-phase. ``prepare`` receives only a
sanitized corpus. A later ``retrieve`` call receives the query. This makes the
in-process implementation suitable for a future one-message-per-line subprocess
protocol without ever handing hidden judgments to the evaluated system.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import re
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import EvaluationCorpus, EvaluationRetrievalAdapter, RetrievalRequest, RetrievalResult


ADAPTER_IDS = ("autopsy", "builtin-bm25", "mem0-oss-raw")
RAW_RETRIEVAL_TRACK = "raw-retrieval"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_file_pin(path: str | Path) -> dict[str, str]:
    source = Path(path).resolve()
    return {
        "kind": "file-sha256",
        "path": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }


def source_tree_pin(path: str | Path) -> dict[str, str]:
    root = Path(path).resolve()
    digest = hashlib.sha256()
    for source in sorted(
        candidate
        for candidate in root.rglob("*")
        if candidate.is_file() and "__pycache__" not in candidate.parts
    ):
        digest.update(source.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return {
        "kind": "source-tree-sha256",
        "path": root.name,
        "sha256": digest.hexdigest(),
    }


def package_pin(name: str) -> dict[str, str]:
    try:
        installed_version = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        installed_version = "not-installed"
    if name == "autopsy-memory":
        from autopsy_memory import __version__ as source_version

        return {
            "name": name,
            "version": source_version,
            "installed_distribution_version": installed_version,
        }
    return {"name": name, "version": installed_version}


def local_execution_metadata() -> dict[str, Any]:
    return {
        "mode": "local-in-process",
        "local": True,
        "remote": False,
        "network_required": False,
    }


def zero_external_cost() -> dict[str, Any]:
    return {
        "currency": "USD",
        "external_api_calls": 0,
        "external_api_cost_usd": 0.0,
        "pricing_basis": "No external service is used.",
    }


def adapter_manifest(
    *,
    adapter_id: str,
    implementation: str,
    config: dict[str, Any],
    source_path: str | Path,
    retrieval_family: str,
    semantic: bool,
) -> dict[str, Any]:
    return {
        "adapter_id": adapter_id,
        "implementation": implementation,
        "track": RAW_RETRIEVAL_TRACK,
        "config": config,
        "config_sha256": canonical_json_sha256(config),
        "package_pin": package_pin("autopsy-memory"),
        "source_pin": source_file_pin(source_path),
        "execution": local_execution_metadata(),
        "cost": zero_external_cost(),
        "retrieval_family": retrieval_family,
        "semantic": bool(semantic),
    }


def corpus_fingerprint(corpus: EvaluationCorpus) -> str:
    return canonical_json_sha256(
        {
            "documents": [asdict(document) for document in corpus.documents],
            "relations": [asdict(relation) for relation in corpus.relations],
        }
    )


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


class BuiltinBM25EvaluationAdapter:
    """Deterministic, dependency-free Okapi BM25 retrieval baseline.

    This is deliberately *not* labelled BM25S: it implements the standard
    Robertson/Sparck Jones positive IDF variant directly in Autopsy so a clean
    checkout can run it without downloading code or a model.
    """

    adapter_id = "builtin-bm25"

    def __init__(self, *, k1: float = 1.5, b: float = 0.75):
        if not math.isfinite(k1) or k1 <= 0:
            raise ValueError("BM25 k1 must be a finite positive number.")
        if not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError("BM25 b must be a finite number between zero and one.")
        self.k1 = float(k1)
        self.b = float(b)
        self._documents = ()
        self._term_frequencies: list[Counter[str]] = []
        self._document_lengths: list[int] = []
        self._document_frequencies: Counter[str] = Counter()
        self._average_document_length = 0.0
        self._fingerprint = ""
        self._ingestion_history: list[dict[str, Any]] = []
        self._closed = False

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return [match.group(0).lower() for match in _TOKEN_RE.finditer(value)]

    def prepare(self, corpus: EvaluationCorpus) -> dict[str, Any]:
        if not isinstance(corpus, EvaluationCorpus):
            raise TypeError("prepare expects an EvaluationCorpus with no query or judgments")
        fingerprint = corpus_fingerprint(corpus)
        if fingerprint == self._fingerprint:
            return {
                "reused": True,
                "corpus_fingerprint": fingerprint,
                "documents": len(corpus.documents),
                "seconds": 0.0,
            }
        started = time.perf_counter()
        self._documents = corpus.documents
        self._term_frequencies = []
        self._document_lengths = []
        self._document_frequencies = Counter()
        for document in corpus.documents:
            # Opaque ids and metadata are intentionally excluded from indexed text.
            tokens = self._tokens(" ".join(value for value in (document.title, document.text) if value))
            frequencies = Counter(tokens)
            self._term_frequencies.append(frequencies)
            self._document_lengths.append(len(tokens))
            self._document_frequencies.update(frequencies.keys())
        self._average_document_length = (
            sum(self._document_lengths) / len(self._document_lengths)
            if self._document_lengths
            else 0.0
        )
        elapsed = time.perf_counter() - started
        self._fingerprint = fingerprint
        payload = {
            "reused": False,
            "corpus_fingerprint": fingerprint,
            "documents": len(corpus.documents),
            "characters": sum(len(document.text) for document in corpus.documents),
            "relations": len(corpus.relations),
            "seconds": elapsed,
            "documents_per_second": len(corpus.documents) / elapsed if elapsed else None,
        }
        self._ingestion_history.append(payload)
        return payload

    def ingest(self, corpus: EvaluationCorpus) -> dict[str, Any]:
        """Compatibility alias that retains the corpus-only type boundary."""

        return self.prepare(corpus)

    def reset_query_state(self) -> None:
        return None

    def _document_is_visible(self, index: int, request: RetrievalRequest) -> bool:
        document = self._documents[index]
        if request.scope == "repo" and request.repository_id:
            if str(document.metadata.get("repository_id") or "") != request.repository_id:
                return False
        expiration = _parse_timestamp(document.expired_at)
        if expiration is None:
            return True
        read_time = _parse_timestamp(request.as_of) or datetime.now(timezone.utc)
        return expiration > read_time

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        if not isinstance(request, RetrievalRequest):
            raise TypeError("retrieve expects a query-only RetrievalRequest")
        if request.limit < 1:
            raise ValueError("retrieval limit must be positive")
        started = time.perf_counter()
        query_terms = Counter(self._tokens(request.query))
        document_count = len(self._documents)
        scores: list[tuple[float, int]] = []
        for index, frequencies in enumerate(self._term_frequencies):
            if not self._document_is_visible(index, request):
                continue
            length = self._document_lengths[index]
            score = 0.0
            for term, query_frequency in query_terms.items():
                term_frequency = frequencies.get(term, 0)
                if not term_frequency:
                    continue
                document_frequency = self._document_frequencies[term]
                idf = math.log(1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
                normalization = term_frequency + self.k1 * (
                    1.0 - self.b
                    + self.b * (length / self._average_document_length if self._average_document_length else 0.0)
                )
                score += query_frequency * idf * (term_frequency * (self.k1 + 1.0) / normalization)
            if score > 0.0:
                scores.append((score, index))
        scores.sort(key=lambda item: (-item[0], item[1]))
        selected = scores[: request.limit]
        elapsed = time.perf_counter() - started
        return RetrievalResult(
            ranked_document_ids=tuple(self._documents[index].document_id for _score, index in selected),
            latency_seconds=elapsed,
            route="builtin-bm25-okapi",
            retrieval_reasons=tuple(("bm25",) for _score, _index in selected),
            diagnostics={
                "query_terms": len(query_terms),
                "positive_score_documents": len(scores),
                "score_formula": "Okapi BM25; log(1+(N-df+0.5)/(df+0.5))",
                "scores": [score for score, _index in selected],
            },
        )

    def manifest(self) -> dict[str, Any]:
        return adapter_manifest(
            adapter_id=self.adapter_id,
            implementation="autopsy-builtin-okapi-bm25-v1",
            config={
                "algorithm": "Okapi BM25",
                "k1": self.k1,
                "b": self.b,
                "idf": "log(1+(N-df+0.5)/(df+0.5))",
                "tokenizer": _TOKEN_RE.pattern,
                "lowercase": True,
                "indexed_fields": ["title", "text"],
                "relations_used": False,
            },
            source_path=__file__,
            retrieval_family="lexical",
            semantic=False,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            **self.manifest(),
            "documents": len(self._documents),
            "vocabulary_terms": len(self._document_frequencies),
            "relation_support": False,
            "temporal_expiration_filter": True,
            "repository_scope_filter": True,
        }

    @property
    def ingestion_history(self) -> list[dict[str, Any]]:
        return list(self._ingestion_history)

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "BuiltinBM25EvaluationAdapter":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


def create_evaluation_adapter(
    adapter_id: str,
    *,
    store_dir: str | None = None,
    keep_store: bool = False,
) -> EvaluationRetrievalAdapter:
    canonical = str(adapter_id or "autopsy").strip().lower()
    if canonical == "autopsy":
        from .autopsy_adapter import AutopsyEvaluationAdapter

        return AutopsyEvaluationAdapter(store_dir=store_dir, keep_store=keep_store)
    if canonical == "builtin-bm25":
        return BuiltinBM25EvaluationAdapter()
    if canonical == "mem0-oss-raw":
        from .mem0_adapter import Mem0OSSEvaluationAdapter

        return Mem0OSSEvaluationAdapter(store_dir=store_dir, keep_store=keep_store)
    raise ValueError(f"Unsupported evaluation adapter: {adapter_id!r}; choose one of {ADAPTER_IDS}")
