"""External evaluation orchestration and independently replayable result logs."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .adapters import create_evaluation_adapter
from .datasets import dataset_provenance, iter_cases, select_cases
from .metrics import aggregate_scores, percentile, score_case
from .models import EvaluationCorpus, RetrievalRequest, RetrievalResult

try:
    import resource
except ImportError:  # pragma: no cover - Windows portability
    resource = None  # type: ignore[assignment]


REPORT_SCHEMA = "autopsy-external-evaluation/v1"
SCORE_REPORT_SCHEMA = "autopsy-external-evaluation-score/v1"
PREDICTION_SCHEMA = "autopsy-external-retrieval-prediction/v1"
PREDICTION_REQUIRED_FIELDS = {
    "schema",
    "dataset",
    "dataset_sha256",
    "granularity",
    "representation",
    "adapter_id",
    "track",
    "adapter_config_sha256",
    "adapter_package_pin",
    "adapter_source_pin",
    "adapter_execution",
    "adapter_cost",
    "case_id",
    "corpus_id",
    "category",
    "query",
    "ranked_document_ids",
    "route",
    "retrieval_limit",
    "latency_seconds",
    "repetitions",
    "ingestion",
    "diagnostics",
}
PREDICTION_ALLOWED_FIELDS = PREDICTION_REQUIRED_FIELDS | {"retrieval_reasons"}
GOLD_METADATA_KEYS = {
    "answer",
    "evidence",
    "forbidden_document_ids",
    "has_answer",
    "relevant_document_ids",
}


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant is not allowed in predictions: {value}")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate prediction JSON key is not allowed: {key}")
        result[key] = value
    return result


def _package_version() -> str:
    try:
        return importlib.metadata.version("autopsy-memory")
    except importlib.metadata.PackageNotFoundError:
        return "development"


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _git_dirty() -> bool | None:
    try:
        output = subprocess.check_output(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "src/autopsy_memory",
                "pyproject.toml",
            ],
            cwd=Path(__file__).resolve().parents[3],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return bool(output.strip())
    except Exception:
        return None


def _source_tree_sha256() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(value for value in root.rglob("*") if value.is_file() and "__pycache__" not in value.parts):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def runtime_metadata() -> dict[str, Any]:
    from autopsy_memory import __version__ as source_version

    total_memory = None
    try:
        total_memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        pass
    peak_rss = None
    if resource is not None:
        peak_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform != "darwin":
            peak_rss *= 1024
    cpu_model = platform.processor() or None
    if sys.platform == "darwin":
        try:
            cpu_model = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip() or cpu_model
        except Exception:
            pass
    dependency_versions: dict[str, str | None] = {}
    for distribution_name in ("falkordb", "falkordblite", "redis", "sentence-transformers"):
        try:
            dependency_versions[distribution_name] = importlib.metadata.version(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            dependency_versions[distribution_name] = None
    return {
        "autopsy_version": _package_version(),
        "autopsy_source_version": source_version,
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
        "source_tree_sha256": _source_tree_sha256(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": cpu_model,
        "cpu_count": os.cpu_count(),
        "total_memory_bytes": total_memory,
        "process_peak_rss_bytes": peak_rss,
        "dependency_versions": dependency_versions,
    }


def latency_summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "samples": len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
    }


def comparison_qualification_passes(**checks: bool) -> bool:
    """Require every declared comparability and safety condition."""

    return bool(checks) and all(bool(value) for value in checks.values())


def parse_k_values(values: str | Iterable[int]) -> tuple[int, ...]:
    if isinstance(values, str):
        parsed = [int(part.strip()) for part in values.split(",") if part.strip()]
    else:
        parsed = [int(value) for value in values]
    result = tuple(sorted(set(value for value in parsed if value > 0)))
    if not result:
        raise ValueError("At least one positive k value is required.")
    return result


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> str:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            for row in rows:
                encoded = json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ) + "\n"
                stream.write(encoded)
                digest.update(encoded.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, output)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return digest.hexdigest()


def prediction_rows_sha256(rows: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        encoded = json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n"
        digest.update(encoded.encode("utf-8"))
    return digest.hexdigest()


def validate_prediction_row(row: Any, *, line_number: int | None = None) -> dict[str, Any]:
    location = f"Prediction line {line_number}" if line_number is not None else "Prediction row"
    if not isinstance(row, dict):
        raise ValueError(f"{location} must be a JSON object.")
    missing = sorted(PREDICTION_REQUIRED_FIELDS - set(row))
    unknown = sorted(set(row) - PREDICTION_ALLOWED_FIELDS)
    if missing:
        raise ValueError(f"{location} is missing required fields: {missing}")
    if unknown:
        raise ValueError(f"{location} contains unsupported fields: {unknown}")
    if row.get("schema") != PREDICTION_SCHEMA:
        raise ValueError(f"{location} has an unsupported schema: {row.get('schema')!r}")
    for key in (
        "dataset",
        "granularity",
        "representation",
        "adapter_id",
        "track",
        "case_id",
        "corpus_id",
        "category",
        "query",
        "route",
    ):
        if not isinstance(row.get(key), str) or not row[key]:
            raise ValueError(f"{location} field {key!r} must be a non-empty string.")
    digest = row.get("dataset_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{location} field 'dataset_sha256' must be a lowercase SHA-256 digest.")
    config_digest = row.get("adapter_config_sha256")
    if (
        not isinstance(config_digest, str)
        or len(config_digest) != 64
        or any(character not in "0123456789abcdef" for character in config_digest)
    ):
        raise ValueError(f"{location} field 'adapter_config_sha256' must be a lowercase SHA-256 digest.")
    ranked = row.get("ranked_document_ids")
    if not isinstance(ranked, list) or any(not isinstance(value, str) or not value for value in ranked):
        raise ValueError(f"{location} field 'ranked_document_ids' must be an array of non-empty strings.")
    if len(set(ranked)) != len(ranked):
        raise ValueError(f"{location} field 'ranked_document_ids' must contain unique values.")
    latency = row.get("latency_seconds")
    if isinstance(latency, bool) or not isinstance(latency, (int, float)) or not math.isfinite(float(latency)) or latency < 0:
        raise ValueError(f"{location} field 'latency_seconds' must be a finite non-negative number.")
    repetitions = row.get("repetitions")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError(f"{location} field 'repetitions' must be a positive integer.")
    retrieval_limit = row.get("retrieval_limit")
    if isinstance(retrieval_limit, bool) or not isinstance(retrieval_limit, int) or retrieval_limit < 1:
        raise ValueError(f"{location} field 'retrieval_limit' must be a positive integer.")
    if len(ranked) > retrieval_limit:
        raise ValueError(f"{location} contains more ranked ids than its declared retrieval_limit.")
    for key in (
        "adapter_package_pin",
        "adapter_source_pin",
        "adapter_execution",
        "adapter_cost",
        "ingestion",
        "diagnostics",
    ):
        if not isinstance(row.get(key), dict):
            raise ValueError(f"{location} field {key!r} must be an object.")
    execution = row["adapter_execution"]
    if not isinstance(execution.get("local"), bool) or not isinstance(execution.get("remote"), bool):
        raise ValueError(f"{location} adapter_execution must declare boolean local and remote fields.")
    external_cost = row["adapter_cost"].get("external_api_cost_usd")
    if (
        isinstance(external_cost, bool)
        or not isinstance(external_cost, (int, float))
        or not math.isfinite(float(external_cost))
        or external_cost < 0
    ):
        raise ValueError(f"{location} adapter_cost must declare a finite non-negative external_api_cost_usd.")
    if not isinstance(row.get("ingestion"), dict) or not isinstance(row.get("diagnostics"), dict):
        raise ValueError(f"{location} ingestion and diagnostics fields must be objects.")
    reasons = row.get("retrieval_reasons", [])
    if not isinstance(reasons, list) or any(
        not isinstance(group, list) or any(not isinstance(reason, str) for reason in group)
        for group in reasons
    ):
        raise ValueError(f"{location} field 'retrieval_reasons' must be an array of string arrays.")
    if reasons and len(reasons) != len(ranked):
        raise ValueError(f"{location} retrieval_reasons must align one-to-one with ranked_document_ids.")
    return row


def load_prediction_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = validate_prediction_row(
                json.loads(
                    line,
                    parse_constant=_reject_json_constant,
                    object_pairs_hook=_strict_json_object,
                ),
                line_number=line_number,
            )
            case_id = str(row.get("case_id") or "")
            if not case_id or case_id in seen:
                raise ValueError(f"Prediction line {line_number} has a missing or duplicate case_id: {case_id!r}")
            seen.add(case_id)
            rows.append(row)
    return rows


def _prediction_row(
    case,
    result,
    *,
    dataset_sha256: str,
    granularity: str,
    representation: str,
    retrieval_limit: int,
    ingestion: dict[str, Any],
    repetitions: int,
    adapter_manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": PREDICTION_SCHEMA,
        "dataset": case.dataset,
        "dataset_sha256": dataset_sha256,
        "granularity": granularity,
        "representation": representation,
        "adapter_id": adapter_manifest["adapter_id"],
        "track": adapter_manifest["track"],
        "adapter_config_sha256": adapter_manifest["config_sha256"],
        "adapter_package_pin": adapter_manifest["package_pin"],
        "adapter_source_pin": adapter_manifest["source_pin"],
        "adapter_execution": adapter_manifest["execution"],
        "adapter_cost": adapter_manifest["cost"],
        "case_id": case.case_id,
        "corpus_id": case.corpus_id,
        "category": case.category,
        "query": case.query,
        "ranked_document_ids": list(result.ranked_document_ids),
        "route": result.route,
        "retrieval_limit": retrieval_limit,
        "retrieval_reasons": [list(reasons) for reasons in result.retrieval_reasons],
        "latency_seconds": result.latency_seconds,
        "repetitions": repetitions,
        "ingestion": ingestion,
        "diagnostics": result.diagnostics,
    }


def _opaque_document_id(document, ordinal: int) -> str:
    """Create a stable adapter handle without hashing a source/evidence id."""

    payload = {
        "ordinal": ordinal,
        "title": document.title,
        "text": document.text,
        "timestamp": document.timestamp,
        "expired_at": document.expired_at,
        "repository_id": str(document.metadata.get("repository_id") or ""),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"doc:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:32]}"


def backend_corpus_boundary(case) -> tuple[EvaluationCorpus, dict[str, str]]:
    """Return corpus-only adapter input and its private opaque-id result map."""

    sanitized_documents = []
    source_to_opaque: dict[str, str] = {}
    opaque_to_source: dict[str, str] = {}
    for ordinal, document in enumerate(case.documents):
        source_id = str(document.document_id)
        if source_id in source_to_opaque:
            raise ValueError(f"Duplicate source document id cannot cross the adapter boundary: {source_id!r}")
        opaque_id = _opaque_document_id(document, ordinal)
        if opaque_id in opaque_to_source:
            raise ValueError("Opaque adapter document id collision.")
        source_to_opaque[source_id] = opaque_id
        opaque_to_source[opaque_id] = source_id
        sanitized_documents.append(
            replace(
                document,
                document_id=opaque_id,
                session_id="",
                metadata={
                    "repository_id": str(document.metadata.get("repository_id") or "")
                } if str(document.metadata.get("repository_id") or "") else {},
            )
        )
    sanitized_relations = []
    source_ids = sorted(source_to_opaque, key=len, reverse=True)
    for relation in case.relations:
        if relation.source_id not in source_to_opaque or relation.target_id not in source_to_opaque:
            continue
        fact_text = relation.fact_text
        for source_id in source_ids:
            fact_text = fact_text.replace(source_id, "[document]")
        sanitized_relations.append(
            replace(
                relation,
                source_id=source_to_opaque[relation.source_id],
                target_id=source_to_opaque[relation.target_id],
                fact_text=fact_text,
            )
        )
    return (
        EvaluationCorpus(
            documents=tuple(sanitized_documents),
            relations=tuple(sanitized_relations),
        ),
        opaque_to_source,
    )


def backend_corpus_without_gold(case) -> EvaluationCorpus:
    """Build the only object allowed to cross the corpus-preparation boundary."""

    return backend_corpus_boundary(case)[0]


def backend_case_without_gold(case) -> EvaluationCorpus:
    """Backward-compatible name for :func:`backend_corpus_without_gold`."""

    return backend_corpus_without_gold(case)


def audit_backend_leakage(case) -> dict[str, Any]:
    prohibited: list[dict[str, Any]] = []
    exact_query_in_text = 0
    exact_query_title = 0
    metadata_fields_stripped = 0
    normalized_query = " ".join(case.query.lower().split())
    for document in case.documents:
        keys = sorted(GOLD_METADATA_KEYS.intersection(document.metadata))
        if keys:
            prohibited.append({"document_id": document.document_id, "keys": keys})
        metadata_fields_stripped += len(set(document.metadata) - {"repository_id"})
        normalized_text = " ".join(document.text.lower().split())
        normalized_title = " ".join(document.title.lower().split())
        exact_query_in_text += int(bool(normalized_query and normalized_query in normalized_text))
        exact_query_title += int(bool(normalized_query and normalized_query == normalized_title))
    if prohibited:
        raise ValueError(f"Gold metadata would cross the backend boundary: {prohibited[:5]}")
    return {
        "documents_with_exact_query_text": exact_query_in_text,
        "documents_with_query_as_exact_title": exact_query_title,
        "prohibited_gold_metadata_documents": 0,
        "source_metadata_fields_stripped": metadata_fields_stripped,
    }


def run_evaluation(
    *,
    dataset: str,
    dataset_path: str | Path,
    granularity: str,
    representation: str = "audited",
    route: str,
    k_values: Iterable[int],
    sample_size: int,
    seed: int,
    categories: set[str] | None,
    repetitions: int,
    warmups: int,
    temporal_policy: str,
    predictions_path: str | Path,
    store_dir: str | None = None,
    keep_store: bool = False,
    adapter_id: str = "autopsy",
) -> dict[str, Any]:
    sample_size = int(sample_size)
    repetitions = int(repetitions)
    warmups = int(warmups)
    if sample_size < 0:
        raise ValueError("sample_size must be zero or greater.")
    if repetitions < 1:
        raise ValueError("repetitions must be at least one.")
    if warmups < 0:
        raise ValueError("warmups must be zero or greater.")
    if route not in {"auto", "lexical", "hybrid"}:
        raise ValueError(f"Unsupported evaluation route: {route}")
    if temporal_policy not in {"dataset", "as-of"}:
        raise ValueError(f"Unsupported temporal policy: {temporal_policy}")
    ks = parse_k_values(k_values)
    provenance = dataset_provenance(dataset, dataset_path)
    runtime = runtime_metadata()
    selected = select_cases(
        iter_cases(dataset, dataset_path, granularity=granularity, representation=representation),
        sample_size=sample_size,
        seed=int(seed),
        categories=categories,
    )
    prediction_rows: list[dict[str, Any]] = []
    case_errors: list[dict[str, str]] = []
    reason_counts: Counter[str] = Counter()
    ranking_instability = 0
    selected_case_count = 0
    leakage_totals: Counter[str] = Counter()
    first_measured_latencies: list[float] = []
    repeated_latencies: list[float] = []
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    with create_evaluation_adapter(
        adapter_id,
        store_dir=store_dir,
        keep_store=keep_store,
    ) as adapter:
        manifest = adapter.manifest()
        for case in selected:
            selected_case_count += 1
            try:
                leakage_totals.update(audit_backend_leakage(case))
                backend_corpus, opaque_to_source = backend_corpus_boundary(case)
                ingestion = adapter.prepare(backend_corpus)
                query_as_of = case.as_of if temporal_policy == "as-of" else ""
                request = RetrievalRequest(
                    query=case.query,
                    limit=max(ks),
                    route=route,
                    as_of=query_as_of,
                    scope=str(case.metadata.get("scope") or "system"),
                    repository_id=str(case.metadata.get("repository_id") or ""),
                )
                for _ in range(warmups):
                    adapter.retrieve(request)
                raw_results = [
                    adapter.retrieve(request)
                    for _ in range(repetitions)
                ]
                results = []
                for raw_result in raw_results:
                    unknown_ids = sorted(set(raw_result.ranked_document_ids) - set(opaque_to_source))
                    if unknown_ids:
                        raise ValueError(f"Adapter returned document ids outside its prepared corpus: {unknown_ids[:10]}")
                    results.append(
                        RetrievalResult(
                            ranked_document_ids=tuple(
                                opaque_to_source[document_id]
                                for document_id in raw_result.ranked_document_ids
                            ),
                            latency_seconds=raw_result.latency_seconds,
                            route=raw_result.route,
                            retrieval_reasons=raw_result.retrieval_reasons,
                            diagnostics=raw_result.diagnostics,
                        )
                    )
                first = results[0]
                if any(result.ranked_document_ids != first.ranked_document_ids for result in results[1:]):
                    ranking_instability += 1
                for reasons in first.retrieval_reasons:
                    reason_counts.update(reasons)
                latency_values = [result.latency_seconds for result in results]
                first_measured_latencies.append(latency_values[0])
                repeated_latencies.extend(latency_values[1:])
                representative = type(first)(
                    ranked_document_ids=first.ranked_document_ids,
                    latency_seconds=sum(latency_values) / len(latency_values),
                    route=first.route,
                    retrieval_reasons=first.retrieval_reasons,
                    diagnostics={
                        **first.diagnostics,
                        "latency_repetitions_seconds": latency_values,
                        "rankings_stable": all(result.ranked_document_ids == first.ranked_document_ids for result in results),
                    },
                )
                prediction_rows.append(
                    _prediction_row(
                        case,
                        representative,
                        dataset_sha256=provenance["sha256"],
                        granularity=granularity,
                        representation=representation,
                        retrieval_limit=max(ks),
                        ingestion=ingestion,
                        repetitions=repetitions,
                        adapter_manifest=manifest,
                    )
                )
            except Exception as exc:
                case_errors.append({"case_id": case.case_id, "error": f"{type(exc).__name__}: {exc}"})
        capabilities = adapter.capabilities()
        ingestion_history = adapter.ingestion_history
    if selected_case_count == 0:
        case_errors.append({"case_id": "__selection__", "error": "No evaluation cases matched the requested selection."})
    if prediction_rows:
        scored = score_predictions(
            dataset=dataset,
            dataset_path=dataset_path,
            granularity=granularity,
            representation=representation,
            predictions=prediction_rows,
            k_values=ks,
            provenance=provenance,
            scoring_runtime=runtime,
        )
    else:
        scored = {"metrics": aggregate_scores([], k_values=ks)}
    predictions_sha256 = write_jsonl(predictions_path, prediction_rows)
    expected_sha = provenance.get("expected_sha256")
    official_artifact = expected_sha is not None and provenance["sha256"] == expected_sha
    embedding_channel_used = int(reason_counts.get("embedding") or 0) > 0
    reranker_channel_used = int(reason_counts.get("reranker") or 0) > 0
    semantic_qualified: bool | None = None
    if bool(manifest.get("semantic")) and route != "lexical":
        evaluated_vector_coverage = float(capabilities.get("evaluated_vector_coverage") or 0.0)
        semantic_qualified = (
            math.isclose(evaluated_vector_coverage, 1.0, rel_tol=0.0, abs_tol=1e-12)
            and embedding_channel_used
        )
    requested_route_qualified = (
        not bool(manifest.get("semantic"))
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
        (scored.get("metrics") or {}).get("metrics", {}).get(f"forbidden_exposure@{max(ks)}") or 0.0
    )
    forbidden_memory_gate_passed = forbidden_exposure == 0.0
    ranking_stability_qualified = repetitions >= 2 and ranking_instability == 0
    code_provenance_qualified = bool(runtime.get("git_commit")) and runtime.get("git_dirty") is False
    ingested_documents = sum(int(item.get("documents") or 0) for item in ingestion_history)
    ingested_characters = sum(int(item.get("characters") or 0) for item in ingestion_history)
    ingestion_seconds = sum(float(item.get("seconds") or 0.0) for item in ingestion_history)
    qualification_notes: list[str] = []
    if not official_artifact:
        qualification_notes.append("The dataset is not the pinned, checksum-verified public artifact.")
    if sample_size > 0 or categories:
        qualification_notes.append("Sampled or category-filtered runs are diagnostic subsets, not full comparable runs.")
    if case_errors:
        qualification_notes.append(f"The run completed with {len(case_errors)} case error(s).")
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
        qualification_notes.append("The audited LongMemEval representation includes assistant turns and is not upstream-retriever-compatible.")
    if not model_revision_qualified:
        qualification_notes.append("A model contributed to ranking but its exact cached revision could not be recorded.")
    if not forbidden_memory_gate_passed:
        qualification_notes.append("At least one forbidden, stale, cross-scope, or poisoned memory was exposed.")
    if repetitions < 2:
        qualification_notes.append(
            "Ranking stability is unqualified because comparable runs require at least two measured repetitions."
        )
    elif not ranking_stability_qualified:
        qualification_notes.append(f"Repeated retrieval produced unstable rankings for {ranking_instability} case(s).")
    if not code_provenance_qualified:
        qualification_notes.append(
            "Comparable runs require clean, committed Autopsy package sources; the evaluated source is dirty or unversioned."
        )
    if not qualification_notes:
        qualification_notes.append("Retrieval qualification reflects the declared route and observed store capabilities.")
    return {
        "schema": REPORT_SCHEMA,
        "evaluation": "external-retrieval",
        "status": "complete" if not case_errors else "completed_with_errors",
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "comparable_run": comparison_qualification_passes(
            official_dataset_artifact=official_artifact,
            full_dataset=sample_size <= 0 and not categories,
            no_case_errors=not case_errors,
            requested_route_qualified=requested_route_qualified,
            metric_cutoffs_qualified=cutoff_qualified,
            upstream_temporal_policy_qualified=upstream_temporal_qualified,
            upstream_representation_qualified=representation_qualified,
            model_revision_qualified=model_revision_qualified,
            forbidden_memory_gate_passed=forbidden_memory_gate_passed,
            ranking_stability_qualified=ranking_stability_qualified,
            code_provenance_qualified=code_provenance_qualified,
        ),
        "qualification": {
            "official_dataset_artifact": official_artifact,
            "full_dataset": sample_size <= 0 and not categories,
            "no_case_errors": not case_errors,
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
            "notes": qualification_notes,
        },
        "dataset": provenance,
        "configuration": {
            "adapter_id": manifest["adapter_id"],
            "track": manifest["track"],
            "adapter_config_sha256": manifest["config_sha256"],
            "granularity": granularity,
            "representation": representation,
            "route": route,
            "k_values": list(ks),
            "sample_size": int(sample_size),
            "selection": "all" if sample_size <= 0 else "lowest-sha256(seed:case_id)",
            "seed": int(seed),
            "categories": sorted(categories or []),
            "repetitions": repetitions,
            "warmups": warmups,
            "query_state_reset": True,
            "temporal_policy": temporal_policy,
        },
        "runtime": runtime,
        "adapter": capabilities,
        "cost": manifest["cost"],
        "retrieval_channel_counts": dict(sorted(reason_counts.items())),
        "ranking_instability_cases": ranking_instability,
        "leakage_audit": {
            **dict(sorted(leakage_totals.items())),
            "questions_ingested": 0,
            "answers_ingested": 0,
            "judgments_ingested": 0,
        },
        "ingestion": {
            "corpora": len(ingestion_history),
            "documents": ingested_documents,
            "characters": ingested_characters,
            "seconds": ingestion_seconds,
            "documents_per_second": ingested_documents / ingestion_seconds if ingestion_seconds else None,
            "characters_per_second": ingested_characters / ingestion_seconds if ingestion_seconds else None,
        },
        "metrics": scored["metrics"],
        "case_errors": case_errors,
        "artifacts": {
            "predictions": str(Path(predictions_path).expanduser().resolve()),
            "predictions_sha256": predictions_sha256,
            "prediction_count": len(prediction_rows),
        },
        "timings": {"total_seconds": time.perf_counter() - started},
        "latency_profiles_seconds": {
            "first_measured_after_warmups": latency_summary(first_measured_latencies),
            "subsequent_repetitions": latency_summary(repeated_latencies),
        },
        "limitations": [
            "This report measures evidence retrieval, not answer-generation accuracy.",
            "The adapter indexes raw benchmark turns or sessions and does not evaluate automatic memory extraction or consolidation.",
            "LoCoMo adversarial and LongMemEval abstention cases treat an empty ranked list as abstention.",
            "Answer-level LongMemEval comparison requires the upstream frozen judge separately.",
        ],
    }


def score_predictions(
    *,
    dataset: str,
    dataset_path: str | Path,
    granularity: str,
    representation: str = "audited",
    predictions: list[dict[str, Any]],
    k_values: Iterable[int],
    provenance: dict[str, Any] | None = None,
    scoring_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ks = parse_k_values(k_values)
    if not predictions:
        raise ValueError("At least one prediction row is required for independent scoring.")
    provenance = provenance or dataset_provenance(dataset, dataset_path)
    by_id: dict[str, dict[str, Any]] = {}
    adapter_provenance: dict[str, Any] | None = None
    for index, unvalidated in enumerate(predictions, start=1):
        row = validate_prediction_row(unvalidated, line_number=index)
        case_id = row["case_id"]
        if case_id in by_id:
            raise ValueError(f"Prediction row {index} has a duplicate case_id: {case_id!r}")
        expected_header = {
            "dataset": dataset,
            "dataset_sha256": provenance["sha256"],
            "granularity": granularity,
            "representation": representation,
        }
        mismatches = {
            key: {"expected": expected, "actual": row.get(key)}
            for key, expected in expected_header.items()
            if row.get(key) != expected
        }
        if mismatches:
            raise ValueError(f"Prediction row {index} provenance/configuration mismatch: {mismatches}")
        row_adapter_provenance = {
            "adapter_id": row["adapter_id"],
            "track": row["track"],
            "adapter_config_sha256": row["adapter_config_sha256"],
            "adapter_package_pin": row["adapter_package_pin"],
            "adapter_source_pin": row["adapter_source_pin"],
            "adapter_execution": row["adapter_execution"],
            "adapter_cost": row["adapter_cost"],
        }
        if adapter_provenance is None:
            adapter_provenance = row_adapter_provenance
        elif row_adapter_provenance != adapter_provenance:
            raise ValueError(
                f"Prediction row {index} mixes adapter configuration or provenance within one scoring artifact."
            )
        if max(ks) > row["retrieval_limit"]:
            raise ValueError(
                f"Prediction row {index} was retrieved to depth {row['retrieval_limit']}, "
                f"which cannot support requested cutoff {max(ks)}."
            )
        by_id[case_id] = row
    matched: set[str] = set()
    scores: list[dict[str, Any]] = []
    dataset_case_count = 0
    for case in iter_cases(dataset, dataset_path, granularity=granularity, representation=representation):
        dataset_case_count += 1
        prediction = by_id.get(case.case_id)
        if prediction is None:
            continue
        expected_case_fields = {
            "corpus_id": case.corpus_id,
            "category": case.category,
            "query": case.query,
        }
        case_mismatches = {
            key: {"expected": expected, "actual": prediction.get(key)}
            for key, expected in expected_case_fields.items()
            if prediction.get(key) != expected
        }
        if case_mismatches:
            raise ValueError(f"Prediction for {case.case_id!r} does not match the dataset case: {case_mismatches}")
        unknown_documents = sorted(
            set(prediction["ranked_document_ids"])
            - {document.document_id for document in case.documents}
        )
        if unknown_documents:
            raise ValueError(
                f"Prediction for {case.case_id!r} contains document ids outside its corpus: {unknown_documents[:10]}"
            )
        matched.add(case.case_id)
        scores.append(
            score_case(
                case_id=case.case_id,
                category=case.category,
                ranked_document_ids=prediction.get("ranked_document_ids", []),
                relevant_document_ids=case.relevant_document_ids,
                forbidden_document_ids=case.forbidden_document_ids,
                expected_abstain=case.expected_abstain,
                latency_seconds=float(prediction.get("latency_seconds") or 0.0),
                k_values=ks,
                retrieval_scorable=case.retrieval_scorable,
                exclusion_reason=str(case.metadata.get("scoring_excluded_reason") or ""),
            )
        )
    unknown = sorted(set(by_id) - matched)
    prediction_integrity_valid = not unknown and len(matched) == len(predictions)
    return {
        "schema": SCORE_REPORT_SCHEMA,
        "evaluation": "external-retrieval-score",
        "status": "complete" if prediction_integrity_valid else "invalid_predictions",
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "dataset": provenance,
        "configuration": {
            "granularity": granularity,
            "representation": representation,
            "k_values": list(ks),
            **(adapter_provenance or {}),
        },
        "runtime": scoring_runtime or runtime_metadata(),
        "artifacts": {
            "prediction_rows": len(predictions),
            "canonical_predictions_sha256": prediction_rows_sha256(predictions),
        },
        "metrics": aggregate_scores(scores, k_values=ks),
        "prediction_integrity": {
            "provided": len(predictions),
            "matched": len(matched),
            "dataset_cases": dataset_case_count,
            "coverage": len(matched) / dataset_case_count if dataset_case_count else 0.0,
            "unknown_case_ids": unknown,
            "valid": prediction_integrity_valid,
            "full_dataset_complete": not unknown and len(matched) == dataset_case_count,
            "missing_dataset_cases": max(0, dataset_case_count - len(matched)),
        },
        "case_scores": scores,
    }
