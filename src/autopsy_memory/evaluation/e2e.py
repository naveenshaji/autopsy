"""Deterministic extraction, context, and answer evaluation tracks.

The extraction boundary receives only :class:`EvaluationCorpus`; the answer
boundary receives only a query and retrieved contexts.  Gold answers and
relevance labels are loaded later by :func:`score_answer_predictions` so a
generated-answer artifact can be inspected or rescored independently.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
import unicodedata
from collections import Counter, OrderedDict, defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .adapters import (
    canonical_json_sha256,
    create_evaluation_adapter,
    corpus_fingerprint,
    local_execution_metadata,
    package_pin,
    source_file_pin,
    zero_external_cost,
)
from .datasets import dataset_provenance, iter_cases, select_cases
from .metrics import aggregate_scores, score_case
from .models import (
    AnswerGenerationRequest,
    AnswerGenerationResult,
    EvaluationAnswerGenerator,
    EvaluationCorpus,
    EvaluationDocument,
    EvaluationExtractor,
    EvaluationRelation,
    ExtractionResult,
    MemoryAttribution,
    RetrievalRequest,
    RetrievedContext,
)
from .runner import backend_corpus_boundary, latency_summary, runtime_metadata


RAW_RETRIEVAL_TRACK = "raw-retrieval"
EXTRACTED_RETRIEVAL_TRACK = "extracted-retrieval"
COMMON_ANSWER_TRACK = "common-answer"
EVALUATION_TRACKS = (RAW_RETRIEVAL_TRACK, EXTRACTED_RETRIEVAL_TRACK, COMMON_ANSWER_TRACK)

EXTRACTION_ARTIFACT_SCHEMA = "autopsy-external-extraction-artifact/v1"
ANSWER_PREDICTION_SCHEMA = "autopsy-external-answer-prediction/v1"
ANSWER_SCORE_SCHEMA = "autopsy-external-answer-score/v1"
END_TO_END_REPORT_SCHEMA = "autopsy-external-end-to-end-evaluation/v1"

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
_DATE_ONLY_RE = re.compile(
    r"^(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[T ][0-9:.+Z-]+)?|"
    r"\d{1,2}:\d{2}\s*(?:AM|PM)?\s+on\s+.+)$",
    re.IGNORECASE,
)
_ROLE_PREFIX_RE = re.compile(r"^(?:user|assistant|speaker(?:_[12])?|human|agent)\s*:\s*", re.IGNORECASE)
_ARTICLES = {"a", "an", "the"}
_ANSWER_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "did", "do", "does", "for",
    "from", "had", "has", "have", "how", "in", "is", "it", "of", "on", "or", "that",
    "the", "this", "to", "was", "were", "what", "when", "where", "which", "who", "why",
    "with",
}


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant is not allowed in evaluation artifacts: {value}")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate evaluation artifact JSON key is not allowed: {key}")
        result[key] = value
    return result


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _component_manifest(component_id: str, config: dict[str, Any], *, component: str) -> dict[str, Any]:
    return {
        "component": component,
        "component_id": component_id,
        "config": config,
        "config_sha256": canonical_json_sha256(config),
        "package_pin": package_pin("autopsy-memory"),
        "source_pin": source_file_pin(__file__),
        "execution": local_execution_metadata(),
        "cost": zero_external_cost(),
    }


def _prediction_component_provenance(manifest: dict[str, Any]) -> dict[str, Any]:
    component_id = str(manifest.get("adapter_id") or manifest.get("component_id") or "")
    return {
        "component_id": component_id,
        "implementation": str(manifest.get("implementation") or component_id),
        "config_sha256": str(manifest.get("config_sha256") or ""),
        "package_pin": dict(manifest.get("package_pin") or {}),
        "source_pin": dict(manifest.get("source_pin") or {}),
        "execution": dict(manifest.get("execution") or {}),
        "cost": dict(manifest.get("cost") or {}),
    }


def _canonical_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _chunks(value: str, maximum: int) -> list[str]:
    value = _canonical_text(value)
    if len(value) <= maximum:
        return [value] if value else []
    result: list[str] = []
    remaining = value
    while remaining:
        if len(remaining) <= maximum:
            result.append(remaining)
            break
        split_at = remaining.rfind(" ", 0, maximum + 1)
        if split_at < maximum // 2:
            split_at = maximum
        result.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return [item for item in result if item]


class DeterministicSentenceExtractor:
    """Offline sentence/chunk extractor with explicit source attribution.

    It performs no query-dependent filtering.  Identical facts are deduplicated
    only inside the same repository and lifecycle window so scope or expiration
    semantics cannot be collapsed accidentally.
    """

    extractor_id = "deterministic-sentence-v1"

    def __init__(self, *, minimum_tokens: int = 3, maximum_memory_characters: int = 512):
        if minimum_tokens < 1:
            raise ValueError("minimum_tokens must be positive")
        if maximum_memory_characters < 64:
            raise ValueError("maximum_memory_characters must be at least 64")
        self.minimum_tokens = int(minimum_tokens)
        self.maximum_memory_characters = int(maximum_memory_characters)

    def manifest(self) -> dict[str, Any]:
        return _component_manifest(
            self.extractor_id,
            {
                "algorithm": "line-aware sentence splitting with lifecycle-safe exact deduplication",
                "minimum_tokens": self.minimum_tokens,
                "maximum_memory_characters": self.maximum_memory_characters,
                "query_access": False,
                "gold_access": False,
                "source_attribution": "complete source document id list",
            },
            component="extractor",
        )

    def _document_facts(self, document: EvaluationDocument) -> list[str]:
        facts: list[str] = []
        for raw_line in str(document.text or "").splitlines():
            line = _canonical_text(raw_line)
            if not line or _DATE_ONLY_RE.fullmatch(line):
                continue
            pieces = _SENTENCE_BOUNDARY_RE.split(line)
            for piece in pieces:
                for chunk in _chunks(piece, self.maximum_memory_characters):
                    chunk = _ROLE_PREFIX_RE.sub("", chunk).strip()
                    if len(_TOKEN_RE.findall(chunk)) >= self.minimum_tokens:
                        facts.append(chunk)
        return facts

    def extract(self, corpus: EvaluationCorpus) -> ExtractionResult:
        if not isinstance(corpus, EvaluationCorpus):
            raise TypeError("extract expects a query- and gold-free EvaluationCorpus")
        started = time.perf_counter()
        records: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        source_to_memories: dict[str, list[str]] = defaultdict(list)
        for document in corpus.documents:
            repository_id = str(document.metadata.get("repository_id") or "")
            for fact in self._document_facts(document):
                normalized = _canonical_text(fact)
                key = (repository_id, document.timestamp, document.expired_at, normalized.casefold())
                record = records.get(key)
                if record is None:
                    identity = canonical_json_sha256(
                        {
                            "repository_id": repository_id,
                            "timestamp": document.timestamp,
                            "expired_at": document.expired_at,
                            "text": normalized.casefold(),
                        }
                    )
                    memory_id = f"memory:{identity[:24]}"
                    record = {
                        "memory_id": memory_id,
                        "text": normalized,
                        "title": document.title,
                        "timestamp": document.timestamp,
                        "expired_at": document.expired_at,
                        "repository_id": repository_id,
                        "sources": [],
                    }
                    records[key] = record
                if document.document_id not in record["sources"]:
                    record["sources"].append(document.document_id)
                source_to_memories[document.document_id].append(record["memory_id"])

        memories: list[EvaluationDocument] = []
        attributions: list[MemoryAttribution] = []
        for record in records.values():
            source_ids = tuple(record["sources"])
            # Source ids remain in the out-of-band attribution table.  They are
            # deliberately absent from the corpus passed to an evaluated adapter.
            metadata: dict[str, Any] = {}
            if record["repository_id"]:
                metadata["repository_id"] = record["repository_id"]
            memories.append(
                EvaluationDocument(
                    document_id=record["memory_id"],
                    text=record["text"],
                    title=record["title"],
                    timestamp=record["timestamp"],
                    expired_at=record["expired_at"],
                    metadata=metadata,
                )
            )
            attributions.append(MemoryAttribution(record["memory_id"], source_ids))

        extracted_relations: list[EvaluationRelation] = []
        for relation in corpus.relations:
            sources = source_to_memories.get(relation.source_id, [])
            targets = source_to_memories.get(relation.target_id, [])
            if not sources or not targets:
                continue
            extracted_relations.append(
                replace(relation, source_id=sources[-1], target_id=targets[0])
            )
        elapsed = time.perf_counter() - started
        input_characters = sum(len(document.text) for document in corpus.documents)
        output_characters = sum(len(memory.text) for memory in memories)
        return ExtractionResult(
            corpus=EvaluationCorpus(tuple(memories), tuple(extracted_relations)),
            attributions=tuple(attributions),
            latency_seconds=elapsed,
            input_document_count=len(corpus.documents),
            input_characters=input_characters,
            output_characters=output_characters,
            diagnostics={
                "input_relations": len(corpus.relations),
                "output_relations": len(extracted_relations),
                "documents_without_memory": sum(
                    1 for document in corpus.documents if not source_to_memories.get(document.document_id)
                ),
                "deduplicated_source_mentions": sum(len(item.source_document_ids) for item in attributions) - len(attributions),
            },
        )


class DeterministicExtractiveAnswerGenerator:
    """Offline common generator selecting one sentence from ranked context."""

    generator_id = "deterministic-extractive-v1"

    def __init__(self, *, minimum_overlap_score: float = 0.0, maximum_answer_characters: int = 320):
        if not math.isfinite(minimum_overlap_score) or minimum_overlap_score < 0:
            raise ValueError("minimum_overlap_score must be finite and non-negative")
        if maximum_answer_characters < 32:
            raise ValueError("maximum_answer_characters must be at least 32")
        self.minimum_overlap_score = float(minimum_overlap_score)
        self.maximum_answer_characters = int(maximum_answer_characters)

    def manifest(self) -> dict[str, Any]:
        return _component_manifest(
            self.generator_id,
            {
                "algorithm": "rank-aware query-token overlap sentence extraction",
                "minimum_overlap_score": self.minimum_overlap_score,
                "maximum_answer_characters": self.maximum_answer_characters,
                "gold_access": False,
                "external_model": False,
            },
            component="answer-generator",
        )

    @staticmethod
    def _query_tokens(value: str) -> set[str]:
        tokens = {token.lower() for token in _TOKEN_RE.findall(value)}
        informative = tokens - _ANSWER_STOPWORDS
        return informative or tokens

    @staticmethod
    def _answer_text(value: str) -> str:
        lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
        while lines and _DATE_ONLY_RE.fullmatch(lines[0]):
            lines.pop(0)
        text = " ".join(lines)
        return _ROLE_PREFIX_RE.sub("", text).strip()

    def generate(self, request: AnswerGenerationRequest) -> AnswerGenerationResult:
        if not isinstance(request, AnswerGenerationRequest):
            raise TypeError("generate expects a gold-free AnswerGenerationRequest")
        started = time.perf_counter()
        query_tokens = self._query_tokens(request.query)
        candidates: list[tuple[float, int, int, RetrievedContext, str]] = []
        for context in request.contexts:
            pieces = _SENTENCE_BOUNDARY_RE.split(_canonical_text(context.text))
            for sentence_index, piece in enumerate(pieces):
                answer = self._answer_text(piece)
                candidate_tokens = {token.lower() for token in _TOKEN_RE.findall(answer)}
                overlap = len(query_tokens.intersection(candidate_tokens))
                lexical = overlap / max(1, len(query_tokens))
                rank_bonus = 1.0 / max(1, context.rank)
                score = lexical + (0.001 * rank_bonus)
                if answer:
                    candidates.append((score, -context.rank, -sentence_index, context, answer))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        if not candidates or candidates[0][0] < self.minimum_overlap_score:
            return AnswerGenerationResult(
                answer="",
                abstained=True,
                source_memory_ids=(),
                latency_seconds=time.perf_counter() - started,
                diagnostics={"candidate_sentences": len(candidates), "best_overlap_score": None},
            )
        score, _rank, _sentence, context, answer = candidates[0]
        answer = answer[: self.maximum_answer_characters].rstrip()
        return AnswerGenerationResult(
            answer=answer,
            abstained=not bool(answer),
            source_memory_ids=(context.memory_id,) if answer else (),
            latency_seconds=time.perf_counter() - started,
            diagnostics={"candidate_sentences": len(candidates), "best_overlap_score": score},
        )


def create_extractor(extractor_id: str = DeterministicSentenceExtractor.extractor_id) -> EvaluationExtractor:
    if str(extractor_id).strip().lower() == DeterministicSentenceExtractor.extractor_id:
        return DeterministicSentenceExtractor()
    raise ValueError(f"Unsupported extractor: {extractor_id!r}")


def create_answer_generator(
    generator_id: str = DeterministicExtractiveAnswerGenerator.generator_id,
) -> EvaluationAnswerGenerator:
    if str(generator_id).strip().lower() == DeterministicExtractiveAnswerGenerator.generator_id:
        return DeterministicExtractiveAnswerGenerator()
    raise ValueError(f"Unsupported answer generator: {generator_id!r}")


class _AtomicJsonlWriter:
    """Stream a potentially large artifact while preserving atomic publication."""

    def __init__(self, path: str | Path):
        self.output = Path(path).expanduser().resolve()
        self.temporary: Path | None = None
        self.stream = None
        self.digest = hashlib.sha256()
        self.rows = 0
        self.sha256 = ""

    def __enter__(self) -> "_AtomicJsonlWriter":
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.stream = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.output.parent,
            prefix=f".{self.output.name}.", suffix=".tmp", delete=False,
        )
        self.temporary = Path(self.stream.name)
        return self

    def write(self, row: dict[str, Any]) -> None:
        if self.stream is None:
            raise RuntimeError("JSONL writer is not open")
        encoded = json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ) + "\n"
        self.stream.write(encoded)
        self.digest.update(encoded.encode("utf-8"))
        self.rows += 1

    def __exit__(self, exc_type, _exc, _traceback) -> None:
        try:
            if self.stream is not None:
                self.stream.flush()
                os.fsync(self.stream.fileno())
                self.stream.close()
            if exc_type is None and self.temporary is not None:
                os.replace(self.temporary, self.output)
                self.sha256 = self.digest.hexdigest()
        finally:
            if self.temporary is not None and self.temporary.exists():
                self.temporary.unlink()


def _write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> str:
    writer = _AtomicJsonlWriter(path)
    with writer:
        for row in rows:
            writer.write(row)
    return writer.sha256


def extraction_artifact_row(
    *,
    dataset: str,
    dataset_sha256: str,
    granularity: str,
    representation: str,
    corpus_id: str,
    input_fingerprint: str,
    result: ExtractionResult,
    extractor_manifest: dict[str, Any],
    source_id_map: dict[str, str] | None = None,
    track: str = EXTRACTED_RETRIEVAL_TRACK,
) -> dict[str, Any]:
    source_id_map = source_id_map or {}
    attribution_map = {
        item.memory_id: [source_id_map.get(source_id, source_id) for source_id in item.source_document_ids]
        for item in result.attributions
    }
    return {
        "schema": EXTRACTION_ARTIFACT_SCHEMA,
        "dataset": dataset,
        "dataset_sha256": dataset_sha256,
        "granularity": granularity,
        "representation": representation,
        "track": track,
        "corpus_id": corpus_id,
        "input_corpus_sha256": input_fingerprint,
        "extractor": extractor_manifest,
        "input": {
            "documents": result.input_document_count,
            "characters": result.input_characters,
        },
        "output": {
            "memories": len(result.corpus.documents),
            "characters": result.output_characters,
            "relations": len(result.corpus.relations),
        },
        "memories": [
            {
                "memory_id": memory.document_id,
                "title": memory.title,
                "text": memory.text,
                "timestamp": memory.timestamp,
                "expired_at": memory.expired_at,
                "source_document_ids": attribution_map.get(memory.document_id, []),
            }
            for memory in result.corpus.documents
        ],
        "relations": [asdict(relation) for relation in result.corpus.relations],
        "latency_seconds": result.latency_seconds,
        "diagnostics": result.diagnostics,
    }


def validate_extraction_artifact_row(row: Any) -> dict[str, Any]:
    required = {
        "schema", "dataset", "dataset_sha256", "granularity", "representation", "track", "corpus_id",
        "input_corpus_sha256", "extractor", "input", "output", "memories", "relations", "latency_seconds",
        "diagnostics",
    }
    if not isinstance(row, dict) or set(row) != required:
        raise ValueError("Extraction artifact row has missing or unsupported fields.")
    if row["schema"] != EXTRACTION_ARTIFACT_SCHEMA or row["track"] not in {
        EXTRACTED_RETRIEVAL_TRACK,
        COMMON_ANSWER_TRACK,
    }:
        raise ValueError("Extraction artifact row has an unsupported schema or track.")
    if not _is_sha256(row["dataset_sha256"]) or not _is_sha256(row["input_corpus_sha256"]):
        raise ValueError("Extraction artifact digests must be lowercase SHA-256 values.")
    if "query" in row or "answer" in row or "relevant_document_ids" in row:
        raise ValueError("Extraction artifacts must not contain query or gold fields.")
    memory_ids: set[str] = set()
    for memory in row.get("memories", []):
        if set(memory) != {"memory_id", "title", "text", "timestamp", "expired_at", "source_document_ids"}:
            raise ValueError("Extraction memory has missing or unsupported fields.")
        memory_id = memory.get("memory_id")
        sources = memory.get("source_document_ids")
        if not isinstance(memory_id, str) or not memory_id or memory_id in memory_ids:
            raise ValueError("Extraction memory ids must be non-empty and unique.")
        if not isinstance(sources, list) or not sources or any(not isinstance(value, str) or not value for value in sources):
            raise ValueError("Every extracted memory requires one or more source document ids.")
        memory_ids.add(memory_id)
    if row["output"].get("memories") != len(memory_ids):
        raise ValueError("Extraction output memory count does not match its memory rows.")
    latency = row["latency_seconds"]
    if isinstance(latency, bool) or not isinstance(latency, (int, float)) or not math.isfinite(latency) or latency < 0:
        raise ValueError("Extraction latency must be finite and non-negative.")
    return row


ANSWER_PREDICTION_REQUIRED_FIELDS = {
    "schema", "dataset", "dataset_sha256", "granularity", "representation", "adapter_id", "track",
    "adapter_config_sha256", "extractor_id", "extractor_config_sha256", "generator_id", "generator_config_sha256", "case_id",
    "corpus_id", "category", "query", "answer", "abstained", "ranked_memory_ids", "source_memory_ids",
    "source_document_ids", "retrieval_latency_seconds", "generation_latency_seconds", "diagnostics",
    "adapter_provenance", "extractor_provenance", "generator_provenance",
}


def validate_answer_prediction_row(row: Any, *, line_number: int | None = None) -> dict[str, Any]:
    location = f"Answer prediction line {line_number}" if line_number else "Answer prediction"
    if not isinstance(row, dict):
        raise ValueError(f"{location} must be an object.")
    missing = ANSWER_PREDICTION_REQUIRED_FIELDS - set(row)
    unknown = set(row) - ANSWER_PREDICTION_REQUIRED_FIELDS
    if missing or unknown:
        raise ValueError(f"{location} has missing fields {sorted(missing)} or unsupported fields {sorted(unknown)}.")
    if row["schema"] != ANSWER_PREDICTION_SCHEMA or row["track"] != COMMON_ANSWER_TRACK:
        raise ValueError(f"{location} has an unsupported schema or track.")
    if "gold_answer" in row or "expected_answer" in row or "relevant_document_ids" in row:
        raise ValueError(f"{location} must not contain gold fields.")
    for key in ("dataset", "dataset_sha256", "granularity", "representation", "adapter_id", "adapter_config_sha256", "extractor_id",
                "extractor_config_sha256", "generator_id", "generator_config_sha256", "case_id", "corpus_id",
                "category", "query"):
        if not isinstance(row[key], str) or not row[key]:
            raise ValueError(f"{location} field {key!r} must be a non-empty string.")
    for key in ("dataset_sha256", "adapter_config_sha256", "extractor_config_sha256", "generator_config_sha256"):
        if not _is_sha256(row[key]):
            raise ValueError(f"{location} field {key!r} must be a lowercase SHA-256 digest.")
    provenance_expectations = {
        "adapter_provenance": (row["adapter_id"], row["adapter_config_sha256"]),
        "extractor_provenance": (row["extractor_id"], row["extractor_config_sha256"]),
        "generator_provenance": (row["generator_id"], row["generator_config_sha256"]),
    }
    provenance_fields = {
        "component_id", "implementation", "config_sha256", "package_pin", "source_pin", "execution", "cost",
    }
    for key, (expected_id, expected_config) in provenance_expectations.items():
        provenance = row[key]
        if not isinstance(provenance, dict) or set(provenance) != provenance_fields:
            raise ValueError(f"{location} field {key!r} has missing or unsupported provenance fields.")
        if provenance["component_id"] != expected_id:
            raise ValueError(f"{location} field {key!r} does not match its declared component id.")
        if expected_config is not None and provenance["config_sha256"] != expected_config:
            raise ValueError(f"{location} field {key!r} does not match its declared config hash.")
        if not _is_sha256(provenance["config_sha256"]):
            raise ValueError(f"{location} field {key!r} requires a lowercase config SHA-256.")
        for object_key in ("package_pin", "source_pin", "execution", "cost"):
            if not isinstance(provenance[object_key], dict):
                raise ValueError(f"{location} field {key!r}.{object_key} must be an object.")
    if not isinstance(row["answer"], str) or not isinstance(row["abstained"], bool):
        raise ValueError(f"{location} answer/abstained fields have invalid types.")
    if row["abstained"] != (not bool(row["answer"].strip())):
        raise ValueError(f"{location} abstained must agree with the normalized answer.")
    for key in ("ranked_memory_ids", "source_memory_ids", "source_document_ids"):
        values = row[key]
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise ValueError(f"{location} field {key!r} must be an array of non-empty strings.")
        if len(values) != len(set(values)):
            raise ValueError(f"{location} field {key!r} must be unique.")
    if not set(row["source_memory_ids"]).issubset(row["ranked_memory_ids"]):
        raise ValueError(f"{location} source_memory_ids must be selected from ranked_memory_ids.")
    if row["abstained"] and (row["source_memory_ids"] or row["source_document_ids"]):
        raise ValueError(f"{location} abstentions cannot cite answer sources.")
    if not row["abstained"] and (not row["source_memory_ids"] or not row["source_document_ids"]):
        raise ValueError(f"{location} generated answers require memory and source-document citations.")
    for key in ("retrieval_latency_seconds", "generation_latency_seconds"):
        value = row[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{location} field {key!r} must be finite and non-negative.")
    if not isinstance(row["diagnostics"], dict):
        raise ValueError(f"{location} diagnostics must be an object.")
    return row


def load_answer_prediction_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = validate_answer_prediction_row(
                json.loads(
                    line,
                    parse_constant=_reject_json_constant,
                    object_pairs_hook=_strict_json_object,
                ),
                line_number=line_number,
            )
            if row["case_id"] in seen:
                raise ValueError(f"Answer prediction line {line_number} duplicates case_id {row['case_id']!r}.")
            seen.add(row["case_id"])
            rows.append(row)
    return rows


def normalize_answer(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
    tokens = [token for token in _TOKEN_RE.findall(normalized) if token not in _ARTICLES]
    return " ".join(tokens)


def answer_exact_match(prediction: str, gold: str) -> float:
    return float(normalize_answer(prediction) == normalize_answer(gold))


def answer_token_f1(prediction: str, gold: str) -> float:
    predicted = normalize_answer(prediction).split()
    expected = normalize_answer(gold).split()
    if not predicted or not expected:
        return float(predicted == expected)
    common = Counter(predicted) & Counter(expected)
    overlap = sum(common.values())
    if not overlap:
        return 0.0
    precision = overlap / len(predicted)
    recall = overlap / len(expected)
    return 2 * precision * recall / (precision + recall)


def _mean_or_none(values: list[float]) -> float | None:
    return mean(values) if values else None


def _aggregate_answer_scores(rows: list[dict[str, Any]], *, dataset: str) -> dict[str, Any]:
    answer_rows = [row for row in rows if row["answer_scorable"]]
    generated = [row for row in answer_rows if not row["predicted_abstain"]]
    abstention_accuracy = [float(row["expected_abstain"] == row["predicted_abstain"]) for row in rows]
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)

    def summarize(category_rows: list[dict[str, Any]]) -> dict[str, Any]:
        scorable = [row for row in category_rows if row["answer_scorable"]]
        covered = [row for row in scorable if not row["predicted_abstain"]]
        return {
            "cases": len(category_rows),
            "answer_scorable_cases": len(scorable),
            "generated_answers": len(covered),
            "answer_coverage": len(covered) / len(scorable) if scorable else None,
            "exact_match": _mean_or_none([row["exact_match"] for row in scorable]),
            "answer_accuracy_exact_match": _mean_or_none([row["exact_match"] for row in scorable]),
            "token_f1": _mean_or_none([row["token_f1"] for row in scorable]),
            "abstention_accuracy": _mean_or_none(
                [float(row["expected_abstain"] == row["predicted_abstain"]) for row in category_rows]
            ),
        }

    unsupported = []
    if dataset == "longmemeval-s":
        unsupported.append(
            {
                "metric": "official_llm_judge_accuracy",
                "status": "unsupported",
                "value": None,
                "reason": "The frozen upstream judge is not bundled; exact match and token F1 are deterministic diagnostics, not substitutes.",
            }
        )
    return {
        "cases": len(rows),
        "answer_scorable_cases": len(answer_rows),
        "generated_answers": len(generated),
        "answer_coverage": len(generated) / len(answer_rows) if answer_rows else None,
        "exact_match": _mean_or_none([row["exact_match"] for row in answer_rows]),
        "answer_accuracy_exact_match": _mean_or_none([row["exact_match"] for row in answer_rows]),
        "token_f1": _mean_or_none([row["token_f1"] for row in answer_rows]),
        "abstention_accuracy": _mean_or_none(abstention_accuracy),
        "by_category": {key: summarize(value) for key, value in sorted(by_category.items())},
        "unsupported_official_metrics": unsupported,
        "metric_scope": "Deterministic normalized exact match/token F1; no LLM judge emulation.",
    }


def score_answer_predictions(
    *,
    dataset: str,
    dataset_path: str | Path,
    granularity: str,
    representation: str,
    predictions: list[dict[str, Any]],
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not predictions:
        raise ValueError("At least one answer prediction is required.")
    provenance = provenance or dataset_provenance(dataset, dataset_path)
    by_id: dict[str, dict[str, Any]] = {}
    component_header: dict[str, Any] | None = None
    for index, candidate in enumerate(predictions, start=1):
        row = validate_answer_prediction_row(candidate, line_number=index)
        expected = {
            "dataset": dataset,
            "dataset_sha256": provenance["sha256"],
            "granularity": granularity,
            "representation": representation,
        }
        mismatches = {key: (value, row.get(key)) for key, value in expected.items() if row.get(key) != value}
        if mismatches:
            raise ValueError(f"Answer prediction {index} provenance mismatch: {mismatches}")
        row_components = {
            key: row[key]
            for key in (
                "adapter_id", "track", "extractor_id", "extractor_config_sha256",
                "generator_id", "generator_config_sha256",
            )
        }
        row_components.update(
            {
                "adapter_config_sha256": row["adapter_config_sha256"],
                "adapter_provenance": row["adapter_provenance"],
                "extractor_provenance": row["extractor_provenance"],
                "generator_provenance": row["generator_provenance"],
            }
        )
        if component_header is None:
            component_header = row_components
        elif row_components != component_header:
            raise ValueError(f"Answer prediction {index} mixes adapter/extractor/generator configurations.")
        if row["case_id"] in by_id:
            raise ValueError(f"Duplicate answer prediction case_id: {row['case_id']!r}")
        by_id[row["case_id"]] = row
    case_scores: list[dict[str, Any]] = []
    matched: set[str] = set()
    dataset_cases = 0
    for case in iter_cases(dataset, dataset_path, granularity=granularity, representation=representation):
        dataset_cases += 1
        prediction = by_id.get(case.case_id)
        if prediction is None:
            continue
        for key, expected in (("corpus_id", case.corpus_id), ("category", case.category), ("query", case.query)):
            if prediction[key] != expected:
                raise ValueError(f"Answer prediction {case.case_id!r} field {key!r} does not match the dataset.")
        unknown_sources = set(prediction["source_document_ids"]) - {doc.document_id for doc in case.documents}
        if unknown_sources:
            raise ValueError(f"Answer prediction {case.case_id!r} cites unknown sources: {sorted(unknown_sources)}")
        matched.add(case.case_id)
        answer_scorable = not case.expected_abstain and bool(case.answer.strip())
        predicted_abstain = bool(prediction["abstained"])
        case_scores.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "answer_scorable": answer_scorable,
                "expected_abstain": case.expected_abstain,
                "predicted_abstain": predicted_abstain,
                "exact_match": answer_exact_match(prediction["answer"], case.answer) if answer_scorable else None,
                "token_f1": answer_token_f1(prediction["answer"], case.answer) if answer_scorable else None,
            }
        )
    unknown = sorted(set(by_id) - matched)
    integrity = not unknown and len(matched) == len(predictions)
    return {
        "schema": ANSWER_SCORE_SCHEMA,
        "evaluation": "external-answer-score",
        "track": COMMON_ANSWER_TRACK,
        "status": "complete" if integrity else "invalid_predictions",
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "dataset": provenance,
        "configuration": {
            "granularity": granularity,
            "representation": representation,
            **(component_header or {}),
        },
        "artifacts": {
            "prediction_rows": len(predictions),
            "canonical_predictions_sha256": canonical_json_sha256(predictions),
        },
        "metrics": _aggregate_answer_scores(case_scores, dataset=dataset),
        "prediction_integrity": {
            "provided": len(predictions),
            "matched": len(matched),
            "dataset_cases": dataset_cases,
            "coverage": len(matched) / dataset_cases if dataset_cases else 0.0,
            "unknown_case_ids": unknown,
            "valid": integrity,
            "full_dataset_complete": integrity and len(matched) == dataset_cases,
        },
        "case_scores": case_scores,
    }


def _source_rankings(
    memory_ids: Iterable[str],
    result: ExtractionResult,
    opaque_to_source: dict[str, str],
    retrieval_reasons: Iterable[Iterable[str]] = (),
) -> tuple[list[str], tuple[tuple[str, ...], ...]]:
    ranked: list[str] = []
    ranked_reasons: list[tuple[str, ...]] = []
    reason_groups = [tuple(str(reason) for reason in group) for group in retrieval_reasons]
    for index, memory_id in enumerate(memory_ids):
        reasons = reason_groups[index] if index < len(reason_groups) else ()
        for opaque_id in result.source_document_ids(memory_id):
            source_id = opaque_to_source.get(opaque_id, opaque_id)
            if source_id not in ranked:
                ranked.append(source_id)
                ranked_reasons.append(reasons)
    return ranked, tuple(ranked_reasons)


def _retrieval_prediction(
    *, case, result, source_ids: list[str], source_reasons: tuple[tuple[str, ...], ...],
    manifest: dict[str, Any], dataset_sha256: str, granularity: str, representation: str,
    retrieval_limit: int, ingestion: dict[str, Any], track: str, repetitions: int,
) -> dict[str, Any]:
    # This is deliberately the same normalized shape used by retrieval-only
    # scoring.  Ranked memory ids remain in diagnostics; only audited source ids
    # cross into evidence scoring.
    return {
        "schema": "autopsy-external-retrieval-prediction/v1",
        "dataset": case.dataset,
        "dataset_sha256": dataset_sha256,
        "granularity": granularity,
        "representation": representation,
        "adapter_id": manifest["adapter_id"],
        "track": track,
        "adapter_config_sha256": manifest["config_sha256"],
        "adapter_package_pin": manifest["package_pin"],
        "adapter_source_pin": manifest["source_pin"],
        "adapter_execution": manifest["execution"],
        "adapter_cost": manifest["cost"],
        "case_id": case.case_id,
        "corpus_id": case.corpus_id,
        "category": case.category,
        "query": case.query,
        "ranked_document_ids": source_ids[:retrieval_limit],
        "route": result.route,
        "retrieval_limit": retrieval_limit,
        "retrieval_reasons": [list(reasons) for reasons in source_reasons[:retrieval_limit]],
        "latency_seconds": result.latency_seconds,
        "repetitions": repetitions,
        "ingestion": ingestion,
        "diagnostics": {**result.diagnostics, "ranked_memory_ids": list(result.ranked_document_ids)},
    }


def run_end_to_end_evaluation(
    *,
    track: str,
    dataset: str,
    dataset_path: str | Path,
    granularity: str,
    representation: str,
    route: str,
    k_values: Iterable[int],
    sample_size: int,
    seed: int,
    categories: set[str] | None,
    repetitions: int = 1,
    warmups: int = 0,
    temporal_policy: str,
    predictions_path: str | Path,
    extraction_artifacts_path: str | Path,
    answers_path: str | Path | None = None,
    adapter_id: str = "autopsy",
    extractor_id: str = DeterministicSentenceExtractor.extractor_id,
    generator_id: str = DeterministicExtractiveAnswerGenerator.generator_id,
    store_dir: str | None = None,
    keep_store: bool = False,
) -> dict[str, Any]:
    if track not in {EXTRACTED_RETRIEVAL_TRACK, COMMON_ANSWER_TRACK}:
        raise ValueError(f"End-to-end runner requires {EXTRACTED_RETRIEVAL_TRACK!r} or {COMMON_ANSWER_TRACK!r}.")
    if track == COMMON_ANSWER_TRACK and answers_path is None:
        raise ValueError("The common-answer track requires an answers artifact path.")
    if int(sample_size) < 0:
        raise ValueError("sample_size must be zero or greater.")
    repetitions = int(repetitions)
    warmups = int(warmups)
    if repetitions < 1:
        raise ValueError("repetitions must be at least one.")
    if warmups < 0:
        raise ValueError("warmups must be zero or greater.")
    if route not in {"auto", "lexical", "hybrid"}:
        raise ValueError(f"Unsupported evaluation route: {route!r}")
    ks = tuple(sorted({int(value) for value in k_values if int(value) > 0}))
    if not ks:
        raise ValueError("At least one positive retrieval cutoff is required.")
    if temporal_policy not in {"dataset", "as-of"}:
        raise ValueError("temporal_policy must be dataset or as-of")
    provenance = dataset_provenance(dataset, dataset_path)
    runtime = runtime_metadata()
    extractor = create_extractor(extractor_id)
    generator = create_answer_generator(generator_id) if track == COMMON_ANSWER_TRACK else None
    extractor_manifest = extractor.manifest()
    generator_manifest = generator.manifest() if generator else None
    selected = select_cases(
        iter_cases(dataset, dataset_path, granularity=granularity, representation=representation),
        sample_size=int(sample_size), seed=int(seed), categories=categories,
    )
    cache: OrderedDict[str, ExtractionResult] = OrderedDict()
    seen_corpora: set[str] = set()
    retrieval_rows: list[dict[str, Any]] = []
    answer_rows: list[dict[str, Any]] = []
    retrieval_scores: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    extraction_seconds = 0.0
    input_documents = 0
    input_characters = 0
    output_memories = 0
    output_characters = 0
    source_attribution_links = 0
    context_characters = 0
    context_memories = 0
    selected_case_count = 0
    reason_counts: Counter[str] = Counter()
    ranking_instability = 0
    first_measured_latencies: list[float] = []
    repeated_latencies: list[float] = []
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    adapter = create_evaluation_adapter(adapter_id, store_dir=store_dir, keep_store=keep_store)
    extraction_writer = _AtomicJsonlWriter(extraction_artifacts_path)
    try:
        with extraction_writer:
            adapter_manifest = adapter.manifest()
            for case in selected:
                selected_case_count += 1
                try:
                    raw_corpus, opaque_to_source = backend_corpus_boundary(case)
                    fingerprint = corpus_fingerprint(raw_corpus)
                    cache_key = f"{case.corpus_id}:{fingerprint}"
                    extraction = cache.get(cache_key)
                    if extraction is None:
                        extraction = extractor.extract(raw_corpus)
                        cache[cache_key] = extraction
                        if len(cache) > 16:
                            cache.popitem(last=False)
                        if cache_key not in seen_corpora:
                            seen_corpora.add(cache_key)
                            extraction_seconds += extraction.latency_seconds
                            input_documents += extraction.input_document_count
                            input_characters += extraction.input_characters
                            output_memories += len(extraction.corpus.documents)
                            output_characters += extraction.output_characters
                            source_attribution_links += sum(
                                len(attribution.source_document_ids) for attribution in extraction.attributions
                            )
                            extraction_row = extraction_artifact_row(
                                dataset=dataset, dataset_sha256=provenance["sha256"], granularity=granularity,
                                representation=representation, corpus_id=case.corpus_id, input_fingerprint=fingerprint,
                                result=extraction, extractor_manifest=extractor_manifest,
                                source_id_map=opaque_to_source,
                                track=track,
                            )
                            validate_extraction_artifact_row(extraction_row)
                            extraction_writer.write(extraction_row)
                    else:
                        cache.move_to_end(cache_key)
                    ingestion = adapter.prepare(extraction.corpus)
                    request = RetrievalRequest(
                        query=case.query,
                        limit=max(ks),
                        route=route,
                        as_of=case.as_of if temporal_policy == "as-of" else "",
                        scope=str(case.metadata.get("scope") or "system"),
                        repository_id=str(case.metadata.get("repository_id") or ""),
                    )
                    for _ in range(warmups):
                        adapter.retrieve(request)
                    raw_results = [adapter.retrieve(request) for _ in range(repetitions)]
                    memory_id_set = {memory.document_id for memory in extraction.corpus.documents}
                    mapped_results: list[tuple[list[str], tuple[tuple[str, ...], ...]]] = []
                    for raw_result in raw_results:
                        if len(raw_result.ranked_document_ids) != len(set(raw_result.ranked_document_ids)):
                            raise ValueError("Adapter returned duplicate extracted-memory ids.")
                        if len(raw_result.ranked_document_ids) > request.limit:
                            raise ValueError("Adapter returned more extracted memories than the requested limit.")
                        if raw_result.retrieval_reasons and (
                            len(raw_result.retrieval_reasons) != len(raw_result.ranked_document_ids)
                        ):
                            raise ValueError("Adapter retrieval reasons do not align with extracted-memory ids.")
                        unknown_ids = sorted(set(raw_result.ranked_document_ids) - memory_id_set)
                        if unknown_ids:
                            raise ValueError(
                                f"Adapter returned memory ids outside its prepared extracted corpus: {unknown_ids[:10]}"
                            )
                        mapped_results.append(
                            _source_rankings(
                                raw_result.ranked_document_ids,
                                extraction,
                                opaque_to_source,
                                raw_result.retrieval_reasons,
                            )
                        )
                    first_raw = raw_results[0]
                    source_ids, source_reasons = mapped_results[0]
                    rankings_stable = all(
                        result.ranked_document_ids == first_raw.ranked_document_ids
                        and mapped[0] == source_ids
                        for result, mapped in zip(raw_results[1:], mapped_results[1:])
                    )
                    if not rankings_stable:
                        ranking_instability += 1
                    for reasons in first_raw.retrieval_reasons:
                        reason_counts.update(reasons)
                    latency_values = [result.latency_seconds for result in raw_results]
                    first_measured_latencies.append(latency_values[0])
                    repeated_latencies.extend(latency_values[1:])
                    retrieval = type(first_raw)(
                        ranked_document_ids=first_raw.ranked_document_ids,
                        latency_seconds=sum(latency_values) / len(latency_values),
                        route=first_raw.route,
                        retrieval_reasons=first_raw.retrieval_reasons,
                        diagnostics={
                            **first_raw.diagnostics,
                            "latency_repetitions_seconds": latency_values,
                            "rankings_stable": rankings_stable,
                        },
                    )
                    retrieval_rows.append(
                        _retrieval_prediction(
                            case=case, result=retrieval, source_ids=source_ids,
                            source_reasons=source_reasons, manifest=adapter_manifest,
                            dataset_sha256=provenance["sha256"], granularity=granularity,
                            representation=representation, retrieval_limit=max(ks), ingestion=ingestion,
                            track=EXTRACTED_RETRIEVAL_TRACK, repetitions=repetitions,
                        )
                    )
                    retrieval_scores.append(
                        score_case(
                            case_id=case.case_id, category=case.category, ranked_document_ids=source_ids,
                            relevant_document_ids=case.relevant_document_ids,
                            forbidden_document_ids=case.forbidden_document_ids,
                            expected_abstain=case.expected_abstain, latency_seconds=retrieval.latency_seconds,
                            k_values=ks, retrieval_scorable=case.retrieval_scorable,
                            exclusion_reason=str(case.metadata.get("scoring_excluded_reason") or ""),
                        )
                    )
                    if generator is not None and generator_manifest is not None:
                        memories = {memory.document_id: memory for memory in extraction.corpus.documents}
                        contexts = tuple(
                            RetrievedContext(
                                memory_id=memory_id,
                                text=memories[memory_id].text,
                                rank=rank,
                                source_document_ids=(),
                            )
                            for rank, memory_id in enumerate(retrieval.ranked_document_ids, start=1)
                            if memory_id in memories
                        )
                        context_memories += len(contexts)
                        context_characters += sum(len(context.text) for context in contexts)
                        answer = generator.generate(AnswerGenerationRequest(case.query, contexts, request.as_of))
                        source_documents: list[str] = []
                        for memory_id in answer.source_memory_ids:
                            for opaque_id in extraction.source_document_ids(memory_id):
                                source_id = opaque_to_source.get(opaque_id, opaque_id)
                                if source_id not in source_documents:
                                    source_documents.append(source_id)
                        answer_row = {
                            "schema": ANSWER_PREDICTION_SCHEMA,
                            "dataset": dataset,
                            "dataset_sha256": provenance["sha256"],
                            "granularity": granularity,
                            "representation": representation,
                            "adapter_id": adapter_manifest["adapter_id"],
                            "adapter_config_sha256": adapter_manifest["config_sha256"],
                            "track": COMMON_ANSWER_TRACK,
                            "extractor_id": extractor_manifest["component_id"],
                            "extractor_config_sha256": extractor_manifest["config_sha256"],
                            "generator_id": generator_manifest["component_id"],
                            "generator_config_sha256": generator_manifest["config_sha256"],
                            "adapter_provenance": _prediction_component_provenance(adapter_manifest),
                            "extractor_provenance": _prediction_component_provenance(extractor_manifest),
                            "generator_provenance": _prediction_component_provenance(generator_manifest),
                            "case_id": case.case_id,
                            "corpus_id": case.corpus_id,
                            "category": case.category,
                            "query": case.query,
                            "answer": answer.answer,
                            "abstained": answer.abstained,
                            "ranked_memory_ids": list(retrieval.ranked_document_ids),
                            "source_memory_ids": list(answer.source_memory_ids),
                            "source_document_ids": source_documents,
                            "retrieval_latency_seconds": retrieval.latency_seconds,
                            "generation_latency_seconds": answer.latency_seconds,
                            "diagnostics": answer.diagnostics,
                        }
                        validate_answer_prediction_row(answer_row)
                        answer_rows.append(answer_row)
                except Exception as exc:
                    errors.append({"case_id": case.case_id, "error": f"{type(exc).__name__}: {exc}"})
            capabilities = adapter.capabilities()
    finally:
        adapter.close()
    if selected_case_count == 0:
        errors.append({"case_id": "__selection__", "error": "No evaluation cases matched the requested selection."})
    extraction_sha = extraction_writer.sha256
    retrieval_sha = _write_jsonl(predictions_path, retrieval_rows)
    answer_sha = _write_jsonl(answers_path, answer_rows) if answers_path is not None else None
    answer_score = (
        score_answer_predictions(
            dataset=dataset, dataset_path=dataset_path, granularity=granularity,
            representation=representation, predictions=answer_rows, provenance=provenance,
        )
        if answer_rows else None
    )
    retrieval_metrics = aggregate_scores(retrieval_scores, k_values=ks)
    expected_sha = provenance.get("expected_sha256")
    official_artifact = expected_sha is not None and provenance.get("sha256") == expected_sha
    full_dataset = int(sample_size) <= 0 and not categories
    embedding_channel_used = int(reason_counts.get("embedding") or 0) > 0
    reranker_channel_used = int(reason_counts.get("reranker") or 0) > 0
    semantic_qualified: bool | None = None
    if bool(adapter_manifest.get("semantic")) and route != "lexical":
        evaluated_vector_coverage = float(capabilities.get("evaluated_vector_coverage") or 0.0)
        semantic_qualified = (
            math.isclose(evaluated_vector_coverage, 1.0, rel_tol=0.0, abs_tol=1e-12)
            and embedding_channel_used
        )
    requested_route_qualified = (
        not bool(adapter_manifest.get("semantic"))
        or route == "lexical"
        or semantic_qualified is True
    )
    model_revision_qualified = (
        (not embedding_channel_used or bool(capabilities.get("embedding_model_revision")))
        and (not reranker_channel_used or bool(capabilities.get("reranker_model_revision")))
    )
    required_cutoffs = {5, 10, 50} if dataset == "longmemeval-s" else {1, 5, 10}
    cutoff_qualified = required_cutoffs.issubset(set(ks))
    upstream_temporal_qualified = temporal_policy == "dataset"
    representation_qualified = dataset != "longmemeval-s" or representation == "upstream"
    forbidden_exposure = float(
        retrieval_metrics.get("metrics", {}).get(f"forbidden_exposure@{max(ks)}") or 0.0
    )
    forbidden_memory_gate_passed = forbidden_exposure == 0.0
    ranking_stability_qualified = repetitions >= 2 and ranking_instability == 0
    code_provenance_qualified = bool(runtime.get("git_commit")) and runtime.get("git_dirty") is False
    comparable_run = all(
        (
            official_artifact,
            full_dataset,
            not errors,
            requested_route_qualified,
            cutoff_qualified,
            upstream_temporal_qualified,
            representation_qualified,
            model_revision_qualified,
            forbidden_memory_gate_passed,
            ranking_stability_qualified,
            code_provenance_qualified,
        )
    )
    qualification_notes: list[str] = []
    if not official_artifact:
        qualification_notes.append("The dataset is not the pinned, checksum-verified public artifact.")
    if not full_dataset:
        qualification_notes.append("Sampled or category-filtered end-to-end runs are diagnostic subsets.")
    if errors:
        qualification_notes.append(f"The run completed with {len(errors)} case error(s).")
    if semantic_qualified is False:
        coverage = float(capabilities.get("evaluated_vector_coverage") or 0.0)
        qualification_notes.append(
            "Hybrid/auto results are not semantic-qualified because full vector coverage and observed embedding retrieval "
            f"are required (coverage={coverage:.6f}, embedding_channel_used={embedding_channel_used})."
        )
    if not cutoff_qualified:
        qualification_notes.append(f"The run omitted required comparison cutoffs: {sorted(required_cutoffs - set(ks))}.")
    if not upstream_temporal_qualified:
        qualification_notes.append("Native as-of filtering is a separate temporal audit and is not upstream-comparable.")
    if not representation_qualified:
        qualification_notes.append(
            "The audited LongMemEval representation includes assistant turns and is not upstream-retriever-compatible."
        )
    if not model_revision_qualified:
        qualification_notes.append("A model contributed to ranking but its exact cached revision could not be recorded.")
    if not forbidden_memory_gate_passed:
        qualification_notes.append("At least one forbidden, stale, cross-scope, or poisoned memory was exposed.")
    if repetitions < 2:
        qualification_notes.append(
            "Ranking stability is unqualified because end-to-end comparable runs require at least two measured repetitions."
        )
    elif ranking_instability:
        qualification_notes.append(f"Repeated retrieval produced unstable rankings for {ranking_instability} case(s).")
    if not code_provenance_qualified:
        qualification_notes.append(
            "Comparable runs require clean, committed Autopsy package sources; the evaluated source is dirty or unversioned."
        )
    if dataset == "longmemeval-s" and track == COMMON_ANSWER_TRACK:
        qualification_notes.append(
            "LongMemEval exact match/token F1 are comparable deterministic diagnostics, not official LLM-judge accuracy."
        )
    if not qualification_notes:
        qualification_notes.append("Comparison is valid only against reports with the same declared track and component hashes.")
    return {
        "schema": END_TO_END_REPORT_SCHEMA,
        "evaluation": "external-end-to-end",
        "track": track,
        "status": "complete" if not errors else "completed_with_errors",
        "comparable_run": comparable_run,
        "qualification": {
            "official_dataset_artifact": official_artifact,
            "full_dataset": full_dataset,
            "no_case_errors": not errors,
            "semantic_route_qualified": semantic_qualified,
            "requested_route_qualified": requested_route_qualified,
            "metric_cutoffs_qualified": cutoff_qualified,
            "required_metric_cutoffs": sorted(required_cutoffs),
            "upstream_temporal_policy_qualified": upstream_temporal_qualified,
            "upstream_representation_qualified": representation_qualified,
            "model_revision_qualified": model_revision_qualified,
            "forbidden_memory_gate_passed": forbidden_memory_gate_passed,
            "ranking_stability_qualified": ranking_stability_qualified,
            "code_provenance_qualified": code_provenance_qualified,
            "within_track_only": True,
            "notes": qualification_notes,
        },
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "dataset": provenance,
        "configuration": {
            "track": track, "adapter_id": adapter_manifest["adapter_id"],
            "adapter_config_sha256": adapter_manifest["config_sha256"], "route": route,
            "k_values": list(ks), "granularity": granularity, "representation": representation,
            "sample_size": int(sample_size), "seed": int(seed), "categories": sorted(categories or []),
            "repetitions": repetitions, "warmups": warmups, "query_state_reset": True,
            "temporal_policy": temporal_policy,
        },
        "adapter": capabilities,
        "extractor": extractor_manifest,
        "generator": generator_manifest,
        "runtime": runtime,
        "cost": adapter_manifest["cost"],
        "retrieval_channel_counts": dict(sorted(reason_counts.items())),
        "ranking_instability_cases": ranking_instability,
        "leakage_audit": {
            "extractor_received_query_fields": 0,
            "extractor_received_gold_fields": 0,
            "adapter_received_source_document_ids": 0,
            "adapter_received_gold_fields": 0,
            "generator_received_gold_fields": 0,
            "gold_answers_written_to_prediction_artifact": 0,
        },
        "extraction": {
            "corpora": len(seen_corpora), "input_documents": input_documents, "input_characters": input_characters,
            "memory_count": output_memories, "output_characters": output_characters,
            "source_attribution_links": source_attribution_links,
            "source_attribution_coverage": 1.0 if output_memories else None,
            "compression_ratio": output_characters / input_characters if input_characters else None,
            "compression_factor": input_characters / output_characters if output_characters else None,
            "seconds": extraction_seconds,
            "documents_per_second": input_documents / extraction_seconds if extraction_seconds else None,
            "characters_per_second": input_characters / extraction_seconds if extraction_seconds else None,
            "memories_per_second": output_memories / extraction_seconds if extraction_seconds else None,
        },
        "context": {
            "retrieved_memories": context_memories,
            "retrieved_characters": context_characters,
            "mean_memories_per_answer": context_memories / len(answer_rows) if answer_rows else None,
            "mean_characters_per_answer": context_characters / len(answer_rows) if answer_rows else None,
        },
        "retrieval_metrics": retrieval_metrics,
        "answer_metrics": answer_score["metrics"] if answer_score else {
            "status": "not_run", "reason": "The extracted-retrieval track does not generate answers."
        },
        "case_errors": errors,
        "artifacts": {
            "extraction": str(Path(extraction_artifacts_path).expanduser().resolve()),
            "extraction_sha256": extraction_sha,
            "extraction_rows": extraction_writer.rows,
            "retrieval_predictions": str(Path(predictions_path).expanduser().resolve()),
            "retrieval_predictions_sha256": retrieval_sha,
            "retrieval_prediction_rows": len(retrieval_rows),
            "answer_predictions": str(Path(answers_path).expanduser().resolve()) if answers_path else None,
            "answer_predictions_sha256": answer_sha,
            "answer_prediction_rows": len(answer_rows),
        },
        "timings": {"total_seconds": time.perf_counter() - started},
        "latency_profiles_seconds": {
            "first_measured_after_warmups": latency_summary(first_measured_latencies),
            "subsequent_repetitions": latency_summary(repeated_latencies),
        },
        "limitations": [
            "The bundled extractor and answer generator are deterministic offline baselines, not learned systems.",
            "Answer prediction artifacts contain generated text and citations but no gold answers or relevance labels.",
            "LongMemEval official LLM-judge accuracy is explicitly unsupported unless the upstream frozen judge is run separately.",
        ],
    }
