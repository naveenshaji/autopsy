"""Isolated adapter that evaluates Autopsy's real retrieval implementation."""

from __future__ import annotations

import copy
import hashlib
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .adapters import adapter_manifest, corpus_fingerprint, source_tree_pin
from .models import EvaluationCorpus, EvaluationDocument, RetrievalRequest, RetrievalResult


class AutopsyEvaluationAdapter:
    """Run direct retrieval against a dedicated temporary FalkorDBLite store.

    The adapter never resolves the production workspace and never uses the resident
    worker. Semantic documents are batch-embedded through the same versioned
    backfill path used by the product; reports disclose actual vector coverage.
    """

    def __init__(self, *, store_dir: str | None = None, keep_store: bool = False):
        from autopsy_memory import cli

        initialization_started = time.perf_counter()
        self.cli = cli
        self.keep_store = bool(keep_store)
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        if store_dir:
            self.root = Path(store_dir).expanduser().resolve()
            self.root.mkdir(parents=True, exist_ok=True)
        elif self.keep_store:
            # TemporaryDirectory removes itself during finalization, so use
            # mkdtemp when the caller explicitly asks to preserve the store.
            self.root = Path(tempfile.mkdtemp(prefix="autopsy-external-eval-"))
        else:
            self._temporary = tempfile.TemporaryDirectory(prefix="autopsy-external-eval-")
            self.root = Path(self._temporary.name)
        self.lite_path = str(self.root / "evaluation.db")
        self.graph_name = f"autopsy_external_eval_{uuid.uuid4().hex[:12]}"
        self.workspace = {
            "id": str(self.root),
            "workspace_key": str(self.root),
            "slug": "external-eval",
            "title": "Autopsy External Evaluation",
            "root_path": str(self.root),
        }
        self.config = copy.deepcopy(cli.EMBEDDINGS_CONFIG_DEFAULT)
        self._closed = False
        self._previous_guard = os.environ.get("AUTOPSY_MEMORY_GUARD_DISABLED")
        os.environ["AUTOPSY_MEMORY_GUARD_DISABLED"] = "1"
        try:
            self.graph = cli.ensure_graph("127.0.0.1", 6381, self.graph_name, lite_path=self.lite_path)
            cli.ensure_runtime_indexes(self.graph, self.config)
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise
        self._stable_to_document: dict[str, str] = {}
        self._document_to_stable: dict[str, str] = {}
        self._corpus_fingerprint = ""
        self._ingestion_history: list[dict[str, Any]] = []
        self._evaluated_eligible_items = 0
        self._evaluated_embedded_items = 0
        self._query_state_keys: set[str] = set()
        self.initialization_seconds = time.perf_counter() - initialization_started

    @staticmethod
    def _stable_key(document_id: str) -> str:
        digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:32]
        return f"external-eval:{digest}"

    def clear(self) -> None:
        self.graph.query("MATCH (node) DETACH DELETE node")
        self.cli.invalidate_graph_caches(self.graph)
        self._stable_to_document.clear()
        self._document_to_stable.clear()
        self._query_state_keys.clear()
        self._corpus_fingerprint = ""

    def _row(self, document: EvaluationDocument, entity_id: int, order: int) -> dict[str, Any]:
        timestamp = document.timestamp or (
            datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=order)
        ).isoformat().replace("+00:00", "Z")
        stable_key = self._stable_key(document.document_id)
        title = document.title.strip() or self.cli.summary_snippet(document.text, limit=120)
        summary = self.cli.summary_snippet(document.text, limit=280)
        # Dataset/session/document ids stay exclusively in the adapter's
        # out-of-band stable-key map. LongMemEval uses answer-bearing session ids,
        # so indexing any source id would leak relevance labels into retrieval.
        metadata = {
            "repository_id": str(document.metadata.get("repository_id") or "")
        } if str(document.metadata.get("repository_id") or "") else {}
        return {
            "entity_id": entity_id,
            "stable_key": stable_key,
            "kind": "memory_note",
            "label": title,
            "summary": summary,
            "detail_content": document.text,
            "search_text": self.cli.memory_search_text(
                kind="memory_note",
                label=title,
                summary=summary,
                detail_content=document.text,
                tags=["external-evaluation"],
                metadata=metadata,
            ),
            "memory_tags": "external-evaluation",
            "memory_metadata": self.cli.serialize_memory_metadata(metadata),
            "created_at": timestamp,
            "updated_at": timestamp,
            "expired_at": document.expired_at,
        }

    def prepare(self, corpus: EvaluationCorpus) -> dict[str, Any]:
        if not isinstance(corpus, EvaluationCorpus):
            raise TypeError("prepare expects an EvaluationCorpus with no query or judgments")
        fingerprint = corpus_fingerprint(corpus)
        if fingerprint == self._corpus_fingerprint:
            return {
                "reused": True,
                "corpus_fingerprint": fingerprint,
                "documents": len(corpus.documents),
                "seconds": 0.0,
            }
        self.clear()
        started = time.perf_counter()
        rows = [self._row(document, index + 1, index) for index, document in enumerate(corpus.documents)]
        for start in range(0, len(rows), 250):
            self.graph.query(
                """
                UNWIND $rows AS row
                CREATE (node:MemoryNode:SemanticItem:MemoryNote {
                    entity_id: row.entity_id,
                    stable_key: row.stable_key,
                    kind: row.kind,
                    label: row.label,
                    summary: row.summary,
                    detail_content: row.detail_content,
                    confidence: 1.0,
                    memory_tags: row.memory_tags,
                    memory_metadata: row.memory_metadata,
                    search_text: row.search_text,
                    source_kind: 'external_evaluation',
                    created_at: row.created_at,
                    updated_at: row.updated_at,
                    expired_at: row.expired_at,
                    origin: 'external_evaluation',
                    embedding: null
                })
                """,
                params={"rows": rows[start : start + 250]},
            )
        self._stable_to_document = {row["stable_key"]: document.document_id for row, document in zip(rows, corpus.documents)}
        self._document_to_stable = {value: key for key, value in self._stable_to_document.items()}
        source_document_ids = sorted(self._document_to_stable, key=len, reverse=True)
        for relation in corpus.relations:
            source = self._document_to_stable.get(relation.source_id)
            target = self._document_to_stable.get(relation.target_id)
            if source and target:
                canonical_relation = self.cli.canonical_relation_name(relation.relation)
                fact_text = relation.fact_text
                for source_document_id in source_document_ids:
                    fact_text = re.sub(
                        rf"(?<!\w){re.escape(source_document_id)}(?!\w)",
                        "[document]",
                        fact_text,
                    )
                self.cli.upsert_fact_edge(
                    self.graph,
                    from_stable_key=source,
                    to_stable_key=target,
                    relation=canonical_relation,
                    predicate=canonical_relation,
                    # Source ids remain out-of-band even when a fixture omits
                    # human-readable edge evidence.
                    fact_text=fact_text or f"External evaluation {canonical_relation} relation.",
                    timestamp=relation.valid_at or "2000-01-01T00:00:00Z",
                    origin="external_evaluation",
                    valid_at=relation.valid_at,
                    invalid_at=relation.invalid_at,
                    expired_at=relation.expired_at,
                    fact_rating=relation.fact_rating,
                )
        repository_ids = sorted(
            {
                str(document.metadata.get("repository_id") or "").strip()
                for document in corpus.documents
                if str(document.metadata.get("repository_id") or "").strip()
            }
        )
        for repository_id in repository_ids:
            repository_key = self.cli.ensure_repository_node(
                self.graph,
                {
                    "rootPath": repository_id,
                    "displayName": Path(repository_id).name or repository_id,
                    "displayPath": repository_id,
                },
                timestamp="2000-01-01T00:00:00Z",
                origin="external_evaluation",
            )
            for document in corpus.documents:
                if str(document.metadata.get("repository_id") or "").strip() != repository_id:
                    continue
                self.cli.upsert_structural_edge(
                    self.graph,
                    from_stable_key=self._document_to_stable[document.document_id],
                    to_stable_key=repository_key,
                    relation="about",
                    timestamp=document.timestamp or "2000-01-01T00:00:00Z",
                    origin="external_evaluation",
                )
        self.cli.invalidate_graph_caches(self.graph)
        embedding_backfill = self.cli.backfill_memory_embeddings(
            self.graph,
            self.config,
            batch_size=max(1, int(self.config.get("batch_size") or 16)),
        )
        if embedding_backfill.get("status") != "complete":
            raise RuntimeError(
                f"external evaluation embedding backfill failed: {embedding_backfill.get('reason') or embedding_backfill.get('failures')}"
            )
        elapsed = time.perf_counter() - started
        embedded_items = int(
            self.cli.scalar_query(self.graph, "MATCH (node:SemanticItem) WHERE node.embedding IS NOT NULL RETURN count(node)") or 0
        )
        self._evaluated_eligible_items += len(corpus.documents)
        self._evaluated_embedded_items += embedded_items
        payload = {
            "reused": False,
            "corpus_fingerprint": fingerprint,
            "documents": len(corpus.documents),
            "characters": sum(len(document.text) for document in corpus.documents),
            "relations": len(corpus.relations),
            "embedded_items": embedded_items,
            "embedding_backfill": embedding_backfill,
            "seconds": elapsed,
            "documents_per_second": len(corpus.documents) / elapsed if elapsed else None,
        }
        self._corpus_fingerprint = fingerprint
        self._ingestion_history.append(payload)
        return payload

    def ingest(self, corpus: EvaluationCorpus) -> dict[str, Any]:
        """Compatibility alias that retains the corpus-only type boundary."""

        return self.prepare(corpus)

    def reset_query_state(self) -> None:
        if not self._query_state_keys:
            return
        self.graph.query(
            """
            MATCH (node:SemanticItem)
            WHERE node.stable_key IN $stable_keys
            SET node.access_count = 0,
                node.last_accessed_at = '',
                node.last_access_source = '',
                node.last_access_query = '',
                node.feedback_score = 0.0,
                node.positive_feedback_count = 0,
                node.negative_feedback_count = 0,
                node.neutral_feedback_count = 0,
                node.last_feedback_at = '',
                node.last_feedback_rating = '',
                node.last_feedback_source = '',
                node.last_feedback_note = ''
            """,
            params={"stable_keys": sorted(self._query_state_keys)},
        )
        self._query_state_keys.clear()

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        if not isinstance(request, RetrievalRequest):
            raise TypeError("retrieve expects a query-only RetrievalRequest")
        self.reset_query_state()
        started = time.perf_counter()
        payload = self.cli.build_consult_payload(
            self.graph,
            tool=self.cli.FalkorToolShim,
            conn=None,
            workspace=self.workspace,
            config=self.config,
            query=request.query,
            limit=request.limit,
            inspect_limit=0,
            route=request.route,
            scope=request.scope,
            repository_root_path=request.repository_id or None,
            as_of=request.as_of or None,
        )
        elapsed = time.perf_counter() - started
        hits = list(payload.get("hits") or [])
        # Consult mutates access telemetry only for final hits. Remember that
        # bounded set so the next query can remove adaptive-ranking state
        # without rewriting the entire corpus before every retrieval.
        self._query_state_keys = {
            str(hit.get("stable_key") or "")
            for hit in hits
            if str(hit.get("stable_key") or "")
        }
        selected_hits = [
            (hit, self._stable_to_document[stable_key])
            for hit in hits
            if (stable_key := str(hit.get("stable_key") or "")) in self._stable_to_document
        ]
        ranked_ids = tuple(document_id for _hit, document_id in selected_hits)
        reasons = tuple(
            tuple(str(reason) for reason in hit.get("retrieval_reasons", []))
            for hit, _document_id in selected_hits
        )
        return RetrievalResult(
            ranked_document_ids=ranked_ids,
            latency_seconds=elapsed,
            route=str(payload.get("route") or request.route),
            retrieval_reasons=reasons,
            diagnostics={
                "timings": payload.get("timings") or {},
                "routing": payload.get("routing") or {},
                "read_guard": payload.get("read_guard") or {},
                "hit_stable_keys": [str(hit.get("stable_key") or "") for hit in hits],
            },
        )

    def manifest(self) -> dict[str, Any]:
        manifest = adapter_manifest(
            adapter_id="autopsy",
            implementation="autopsy-isolated-direct-v1",
            config={
                "store": "falkordblite",
                "embeddings": self.config,
                "telemetry_reset_between_queries": True,
                "telemetry_reset_mode": "prior-hit-stable-keys",
            },
            source_path=__file__,
            retrieval_family="hybrid",
            semantic=True,
        )
        manifest["source_pin"] = source_tree_pin(Path(__file__).resolve().parents[1])
        return manifest

    def capabilities(self) -> dict[str, Any]:
        eligible = int(self.cli.scalar_query(self.graph, "MATCH (node:SemanticItem) RETURN count(node)") or 0)
        embedded = int(
            self.cli.scalar_query(self.graph, "MATCH (node:SemanticItem) WHERE node.embedding IS NOT NULL RETURN count(node)") or 0
        )
        embedding_available, embedding_error = self.cli.embedding_provider_available(self.config)
        reranker_available, reranker_error = self.cli.reranker_provider_available(self.config)
        embedding_name = str(self.config.get("model") or "")
        embedding_revision = str(self.config.get("model_revision") or "")
        embedding_device = str(self.config.get("device") or "cpu")
        reranker_config = self.config.get("reranker") or {}
        reranker_name = str(reranker_config.get("model") or "")
        reranker_revision = str(reranker_config.get("model_revision") or "")
        reranker_device = str(reranker_config.get("device") or "cpu")
        # Runtime model caches are keyed by the immutable revision as well as
        # model and device.  Looking them up without the revision made genuine
        # semantic runs appear as though no pinned model had been loaded and
        # incorrectly failed the public-run provenance gate.
        embedding_runtime = self.cli._EMBEDDING_MODEL_CACHE.get(
            (embedding_name, embedding_revision, embedding_device)
        )
        reranker_runtime = self.cli._RERANKER_MODEL_CACHE.get(
            (reranker_name, reranker_revision, reranker_device)
        )
        store_bytes = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        return {
            **self.manifest(),
            "adapter": "autopsy-isolated-direct-v1",
            "store": "falkordblite",
            "production_worker_used": False,
            "telemetry_reset_between_queries": True,
            "telemetry_reset_mode": "prior-hit-stable-keys",
            "eligible_items": eligible,
            "embedded_items": embedded,
            "vector_coverage": embedded / eligible if eligible else 0.0,
            "evaluated_eligible_items": self._evaluated_eligible_items,
            "evaluated_embedded_items": self._evaluated_embedded_items,
            "evaluated_vector_coverage": (
                self._evaluated_embedded_items / self._evaluated_eligible_items
                if self._evaluated_eligible_items
                else 0.0
            ),
            "embedding_provider_available": embedding_available,
            "embedding_error": embedding_error,
            "reranker_available": reranker_available,
            "reranker_error": reranker_error,
            "embedding_model": embedding_name,
            "embedding_device": embedding_device,
            "embedding_model_loaded": embedding_runtime is not None,
            "embedding_model_revision": self._transformer_revision(embedding_runtime),
            "reranker_model": reranker_name,
            "reranker_device": reranker_device,
            "reranker_model_loaded": reranker_runtime is not None,
            "reranker_model_revision": self._transformer_revision(reranker_runtime),
            "store_path": str(self.root) if self.keep_store else "temporary-redacted",
            "store_bytes": store_bytes,
            "initialization_seconds": self.initialization_seconds,
        }

    @property
    def ingestion_history(self) -> list[dict[str, Any]]:
        return list(self._ingestion_history)

    @staticmethod
    def _transformer_revision(model: Any) -> str | None:
        if model is None:
            return None
        inner = getattr(model, "model", None)
        config = getattr(inner, "config", None)
        if config is None:
            first_module = getattr(model, "_first_module", lambda: None)()
            auto_model = getattr(first_module, "auto_model", None)
            config = getattr(auto_model, "config", None)
        revision = getattr(config, "_commit_hash", None)
        return str(revision) if revision else None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            previous = os.environ.get("AUTOPSY_FALKORDB_LITE_TERMINATE_ON_CLOSE")
            os.environ["AUTOPSY_FALKORDB_LITE_TERMINATE_ON_CLOSE"] = "1"
            try:
                self.cli.reset_falkordb_lite_client(self.lite_path)
            finally:
                if previous is None:
                    os.environ.pop("AUTOPSY_FALKORDB_LITE_TERMINATE_ON_CLOSE", None)
                else:
                    os.environ["AUTOPSY_FALKORDB_LITE_TERMINATE_ON_CLOSE"] = previous
        finally:
            if self._previous_guard is None:
                os.environ.pop("AUTOPSY_MEMORY_GUARD_DISABLED", None)
            else:
                os.environ["AUTOPSY_MEMORY_GUARD_DISABLED"] = self._previous_guard
            if self._temporary is not None and not self.keep_store:
                self._temporary.cleanup()

    def __enter__(self) -> "AutopsyEvaluationAdapter":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()
