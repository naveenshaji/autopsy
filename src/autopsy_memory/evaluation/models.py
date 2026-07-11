"""Stable, backend-neutral models used by the external evaluation suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class EvaluationRelation:
    source_id: str
    target_id: str
    relation: str
    fact_text: str = ""
    valid_at: str = ""
    invalid_at: str = ""
    expired_at: str = ""
    fact_rating: float = 1.0


@dataclass(frozen=True)
class EvaluationDocument:
    document_id: str
    text: str
    title: str = ""
    timestamp: str = ""
    expired_at: str = ""
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationCase:
    dataset: str
    case_id: str
    corpus_id: str
    category: str
    query: str
    documents: tuple[EvaluationDocument, ...]
    relevant_document_ids: tuple[str, ...]
    forbidden_document_ids: tuple[str, ...] = ()
    expected_abstain: bool = False
    answer: str = ""
    as_of: str = ""
    relations: tuple[EvaluationRelation, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def retrieval_scorable(self) -> bool:
        return not self.metadata.get("scoring_excluded_reason") and (
            self.expected_abstain or bool(self.relevant_document_ids)
        )


@dataclass(frozen=True)
class EvaluationCorpus:
    """The complete payload allowed to cross the adapter preparation boundary.

    Deliberately absent are the dataset/case/corpus identifiers, query, answer,
    relevance judgments, forbidden ids, and abstention label. Document ids are
    opaque handles needed to return rankings; they carry no judgment semantics.
    """

    documents: tuple[EvaluationDocument, ...]
    relations: tuple[EvaluationRelation, ...] = ()


@dataclass(frozen=True)
class RetrievalRequest:
    """Query-time adapter input, sent only after corpus preparation completes."""

    query: str
    limit: int
    route: str
    as_of: str = ""
    scope: str = "system"
    repository_id: str = ""


@dataclass(frozen=True)
class RetrievalResult:
    ranked_document_ids: tuple[str, ...]
    latency_seconds: float
    route: str
    retrieval_reasons: tuple[tuple[str, ...], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryAttribution:
    """Auditable source mapping for one extractor-produced memory."""

    memory_id: str
    source_document_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionResult:
    """Query- and gold-free output of a memory extraction component."""

    corpus: EvaluationCorpus
    attributions: tuple[MemoryAttribution, ...]
    latency_seconds: float
    input_document_count: int
    input_characters: int
    output_characters: int
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def source_document_ids(self, memory_id: str) -> tuple[str, ...]:
        for attribution in self.attributions:
            if attribution.memory_id == memory_id:
                return attribution.source_document_ids
        return ()


@dataclass(frozen=True)
class RetrievedContext:
    """One ranked, source-attributed memory supplied to an answer generator."""

    memory_id: str
    text: str
    rank: int
    source_document_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnswerGenerationRequest:
    """Gold-free input shared by every common answer generator."""

    query: str
    contexts: tuple[RetrievedContext, ...]
    as_of: str = ""


@dataclass(frozen=True)
class AnswerGenerationResult:
    answer: str
    abstained: bool
    source_memory_ids: tuple[str, ...]
    latency_seconds: float
    diagnostics: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EvaluationRetrievalAdapter(Protocol):
    """In-process contract designed to map directly onto an NDJSON protocol.

    A future process adapter can serialize :class:`EvaluationCorpus` during a
    ``prepare`` message and :class:`RetrievalRequest` during later ``retrieve``
    messages without weakening the hidden-gold boundary.
    """

    def prepare(self, corpus: EvaluationCorpus) -> dict[str, Any]: ...

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult: ...

    def reset_query_state(self) -> None: ...

    def capabilities(self) -> dict[str, Any]: ...

    def manifest(self) -> dict[str, Any]: ...

    @property
    def ingestion_history(self) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


@runtime_checkable
class EvaluationExtractor(Protocol):
    """Corpus-only extraction contract; queries and gold cannot cross it."""

    def extract(self, corpus: EvaluationCorpus) -> ExtractionResult: ...

    def manifest(self) -> dict[str, Any]: ...


@runtime_checkable
class EvaluationAnswerGenerator(Protocol):
    """Common answer contract over retrieved context, never dataset gold."""

    def generate(self, request: AnswerGenerationRequest) -> AnswerGenerationResult: ...

    def manifest(self) -> dict[str, Any]: ...
