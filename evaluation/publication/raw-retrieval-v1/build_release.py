#!/usr/bin/env python3
"""Build the deterministic, aggregate-only Autopsy raw-retrieval-v1 bundle.

This script intentionally uses only the Python standard library. It validates
the six frozen run/independent-score pairs before creating any output, then
constructs each public aggregate from a fixed allowlist. It never edits or
"sanitizes in place" an input report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


RELEASE_NAME = "autopsy-raw-retrieval-v1"
AGGREGATE_SCHEMA = "autopsy-publication-aggregate-result/v1"
MANIFEST_SCHEMA = "autopsy-publication-manifest/v1"
TRANSFORMATION_ID = "autopsy-aggregate-allowlist/v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:/@ -]{0,199}$")

LOCOMO_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
LONGMEM_SHA256 = "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
AUTOPSY_EMBEDDING_REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
AUTOPSY_RERANKER_REVISION = "2cfc18c9415c912f9d8155881c133215df768a70"
MEM0_COMMIT = "f2532f072fdefa4c90264acc80af0984309f8b06"
MEM0_EMBEDDING_REVISION = "b207367332321f8e44f96e224ef15bc607f4dbf0"

STATUS_START = "<!-- PUBLICATION_STATUS_START -->"
STATUS_END = "<!-- PUBLICATION_STATUS_END -->"
TABLE_START = "<!-- RESULTS_TABLE_START -->"
TABLE_END = "<!-- RESULTS_TABLE_END -->"

QUALIFICATION_GATES = (
    "code_provenance_qualified",
    "forbidden_memory_gate_passed",
    "full_dataset",
    "metric_cutoffs_qualified",
    "model_revision_qualified",
    "no_case_errors",
    "official_dataset_artifact",
    "ranking_stability_qualified",
    "requested_route_qualified",
    "upstream_representation_qualified",
    "upstream_temporal_policy_qualified",
)

LEAKAGE_ZERO_FIELDS = (
    "answers_ingested",
    "judgments_ingested",
    "prohibited_gold_metadata_documents",
    "questions_ingested",
)

FORBIDDEN_OUTPUT_KEYS = {
    "answer",
    "answers",
    "case_id",
    "case_scores",
    "dataset_path",
    "detail_content",
    "document_text",
    "forbidden_document_ids",
    "path",
    "paths",
    "python_executable",
    "query",
    "ranked_document_ids",
    "relevant_document_ids",
    "source_predictions_path",
    "text",
}


class PublicationError(ValueError):
    """Raised when an input cannot safely enter the publication bundle."""


@dataclass(frozen=True)
class RowSpec:
    name: str
    dataset: str
    adapter_id: str
    output_filename: str
    display_dataset: str
    display_system: str
    qualifier: str
    route: str
    granularity: str
    representation: str
    k_values: tuple[int, ...]
    cases: int
    retrieval_scored_cases: int
    abstention_scored_cases: int
    unscored_retrieval_cases: int
    categories: tuple[str, ...]


ROW_SPECS = (
    RowSpec(
        "locomo-autopsy", "locomo", "autopsy", "locomo-autopsy.json",
        "LoCoMo", "Autopsy hybrid (package metadata 0.1.30)", "native-hybrid-raw-evidence-retrieval",
        "hybrid", "turn", "audited", (1, 5, 10), 1986, 1534, 1980, 6,
        ("adversarial-abstention", "multi-hop", "open-domain", "single-hop", "temporal"),
    ),
    RowSpec(
        "locomo-builtin-bm25", "locomo", "builtin-bm25", "locomo-builtin-bm25.json",
        "LoCoMo", "built-in BM25 control", "lexical-control-not-memory-system",
        "lexical", "turn", "audited", (1, 5, 10), 1986, 1534, 1980, 6,
        ("adversarial-abstention", "multi-hop", "open-domain", "single-hop", "temporal"),
    ),
    RowSpec(
        "locomo-mem0-oss-raw", "locomo", "mem0-oss-raw", "locomo-mem0-oss-raw.json",
        "LoCoMo", "Mem0 OSS 2.0.11 raw (`infer=False`)", "restricted-raw-vector-adapter-not-native-memory-pipeline",
        "hybrid", "turn", "audited", (1, 5, 10), 1986, 1534, 1980, 6,
        ("adversarial-abstention", "multi-hop", "open-domain", "single-hop", "temporal"),
    ),
    RowSpec(
        "longmemeval-s-autopsy", "longmemeval-s", "autopsy", "longmemeval-s-autopsy.json",
        "LongMemEval-S upstream", "Autopsy hybrid (package metadata 0.1.30)", "native-hybrid-raw-evidence-retrieval",
        "hybrid", "session", "upstream", (5, 10, 50), 500, 419, 449, 51,
        ("knowledge-update", "multi-session", "single-session-assistant", "single-session-preference", "single-session-user", "temporal-reasoning"),
    ),
    RowSpec(
        "longmemeval-s-builtin-bm25", "longmemeval-s", "builtin-bm25", "longmemeval-s-builtin-bm25.json",
        "LongMemEval-S upstream", "built-in BM25 control", "lexical-control-not-memory-system",
        "lexical", "session", "upstream", (5, 10, 50), 500, 419, 449, 51,
        ("knowledge-update", "multi-session", "single-session-assistant", "single-session-preference", "single-session-user", "temporal-reasoning"),
    ),
    RowSpec(
        "longmemeval-s-mem0-oss-raw", "longmemeval-s", "mem0-oss-raw", "longmemeval-s-mem0-oss-raw.json",
        "LongMemEval-S upstream", "Mem0 OSS 2.0.11 raw (`infer=False`)", "restricted-raw-vector-adapter-not-native-memory-pipeline",
        "hybrid", "session", "upstream", (5, 10, 50), 500, 419, 449, 51,
        ("knowledge-update", "multi-session", "single-session-assistant", "single-session-preference", "single-session-user", "temporal-reasoning"),
    ),
)
ROW_BY_NAME = {spec.name: spec for spec in ROW_SPECS}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationError(message)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f"{label} must be an array")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    _require(value >= minimum, f"{label} must be >= {minimum}")
    return value


def _number(value: Any, label: str, *, minimum: float | None = None) -> float | int:
    _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{label} must be numeric")
    _require(math.isfinite(float(value)), f"{label} must be finite")
    if minimum is not None:
        _require(float(value) >= minimum, f"{label} must be >= {minimum}")
    return value


def _sha256(value: Any, label: str) -> str:
    _require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, f"{label} must be lowercase SHA-256")
    return value


def _commit(value: Any, label: str) -> str:
    _require(isinstance(value, str) and COMMIT_RE.fullmatch(value) is not None, f"{label} must be a 40-character commit")
    return value


def _revision(value: Any, label: str) -> str:
    _require(
        isinstance(value, str)
        and (COMMIT_RE.fullmatch(value) is not None or SHA256_RE.fullmatch(value) is not None),
        f"{label} must be a 40- or 64-character lowercase revision",
    )
    return value


def _safe_token(value: Any, label: str) -> str:
    _require(isinstance(value, str) and SAFE_TOKEN_RE.fullmatch(value) is not None, f"{label} contains unsupported text")
    return value


def _timestamp(value: Any, label: str) -> str:
    _require(isinstance(value, str) and len(value) <= 64, f"{label} must be a bounded timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationError(f"{label} must be ISO-8601") from exc
    _require(parsed.tzinfo is not None, f"{label} must include an offset")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PublicationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise PublicationError(f"invalid non-finite JSON number: {value}")


def read_json(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"artifact does not exist: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicationError(f"cannot read strict JSON artifact {path}: {exc}") from exc
    return _mapping(value, str(path))


def canonical_json(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PublicationError(f"value is not canonical JSON: {exc}") from exc


def pretty_json(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PublicationError(f"value is not serializable JSON: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_clone(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _validate_numeric_tree(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _require(isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9@._-]+", key) is not None, f"{label} has an unsafe key")
            _validate_numeric_tree(child, f"{label}.{key}")
        return
    _number(value, label)


def _walk_forbidden_metrics(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.startswith("forbidden_exposure@"):
                _require(_number(child, f"{label}.{key}") == 0, f"{label}.{key} is nonzero")
            _walk_forbidden_metrics(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden_metrics(child, f"{label}[{index}]")


def _runtime_profile(runtime: Mapping[str, Any]) -> dict[str, Any]:
    dependencies = _mapping(runtime.get("dependency_versions"), "runtime.dependency_versions")
    for key, value in dependencies.items():
        _safe_token(key, "runtime dependency name")
        _safe_token(value, f"runtime dependency {key}")
    return {
        "autopsy_source_version": _safe_token(runtime.get("autopsy_source_version"), "runtime.autopsy_source_version"),
        "autopsy_version": _safe_token(runtime.get("autopsy_version"), "runtime.autopsy_version"),
        "cpu_count": _integer(runtime.get("cpu_count"), "runtime.cpu_count", minimum=1),
        "dependency_versions": dict(sorted(dependencies.items())),
        "machine": _safe_token(runtime.get("machine"), "runtime.machine"),
        "platform": _safe_token(runtime.get("platform"), "runtime.platform"),
        "processor": _safe_token(runtime.get("processor"), "runtime.processor"),
        "python": _safe_token(runtime.get("python"), "runtime.python"),
        "total_memory_bytes": _integer(runtime.get("total_memory_bytes"), "runtime.total_memory_bytes", minimum=1),
    }


def _dataset_fields(dataset: Mapping[str, Any], spec: RowSpec, label: str) -> dict[str, Any]:
    expected = {
        "locomo": (LOCOMO_SHA256, "git-3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376", "CC-BY-NC-4.0"),
        "longmemeval-s": (LONGMEM_SHA256, "hf-98d7416c24c778c2fee6e6f3006e7a073259d48f", "MIT"),
    }[spec.dataset]
    _require(dataset.get("dataset") == spec.dataset, f"{label}.dataset mismatch")
    _require(dataset.get("sha256") == expected[0], f"{label}.sha256 is not the pinned artifact")
    _require(dataset.get("expected_sha256") == expected[0], f"{label}.expected_sha256 mismatch")
    _require(dataset.get("version") == expected[1], f"{label}.version mismatch")
    _require(dataset.get("license") == expected[2], f"{label}.license mismatch")
    return {
        "bytes": _integer(dataset.get("bytes"), f"{label}.bytes", minimum=1),
        "dataset": spec.dataset,
        "expected_sha256": expected[0],
        "license": expected[2],
        "sha256": expected[0],
        "version": expected[1],
    }


def _safe_package_pin(pin: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("name", "version", "required_version", "installed_distribution_version"):
        if pin.get(key) is not None:
            result[key] = _safe_token(pin[key], f"package_pin.{key}")
    embedding = pin.get("embedding_model")
    if embedding is not None:
        embedding = _mapping(embedding, "package_pin.embedding_model")
        result["embedding_model"] = {
            "name": _safe_token(embedding.get("name"), "package_pin.embedding_model.name"),
            "revision": _revision(embedding.get("revision"), "package_pin.embedding_model.revision"),
        }
    dependencies = pin.get("runtime_dependencies")
    if dependencies is not None:
        dependencies = _mapping(dependencies, "package_pin.runtime_dependencies")
        safe_dependencies: dict[str, str] = {}
        for key, value in dependencies.items():
            safe_dependencies[_safe_token(key, "package dependency name")] = _safe_token(value, f"package dependency {key}")
        result["runtime_dependencies"] = dict(sorted(safe_dependencies.items()))
    _require(result.get("name"), "package_pin.name is required")
    return result


def _safe_source_pin(pin: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("kind", "tag"):
        if pin.get(key) is not None:
            result[key] = _safe_token(pin[key], f"source_pin.{key}")
    for key in ("sha256", "adapter_sha256", "worker_sha256"):
        if pin.get(key) is not None:
            result[key] = _sha256(pin[key], f"source_pin.{key}")
    if pin.get("commit") is not None:
        result["commit"] = _commit(pin["commit"], "source_pin.commit")
    if pin.get("repository") is not None:
        repository = _safe_token(pin["repository"], "source_pin.repository")
        _require(repository.startswith("https://"), "source_pin.repository must be HTTPS")
        result["repository"] = repository
    for key in ("adapter_bundle", "bootstrap_assets"):
        if pin.get(key) is not None:
            nested = _mapping(pin[key], f"source_pin.{key}")
            result[key] = {
                "kind": _safe_token(nested.get("kind"), f"source_pin.{key}.kind"),
                "sha256": _sha256(nested.get("sha256"), f"source_pin.{key}.sha256"),
            }
    _require(result.get("kind"), "source_pin.kind is required")
    _require(any(key in result for key in ("sha256", "commit")), "source_pin needs a digest or commit")
    return result


def _safe_execution(execution: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "local": execution.get("local"),
        "mode": _safe_token(execution.get("mode"), "execution.mode"),
        "network_required": execution.get("network_required"),
        "remote": execution.get("remote"),
    }
    for key in (
        "bootstrap_network_required",
        "external_service_credentials_required",
        "initial_model_download_network_required",
        "runtime_offline_enforced",
    ):
        if key in execution:
            result[key] = execution[key]
    for key, value in result.items():
        if key != "mode":
            _require(isinstance(value, bool), f"execution.{key} must be boolean")
    _require(result["local"] is True and result["remote"] is False and result["network_required"] is False, "measured execution must be local and offline")
    return result


def _safe_cost(cost: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "currency": _safe_token(cost.get("currency"), "cost.currency"),
        "external_api_calls": _integer(cost.get("external_api_calls"), "cost.external_api_calls"),
        "external_api_cost_usd": _number(cost.get("external_api_cost_usd"), "cost.external_api_cost_usd", minimum=0),
    }


def _validate_adapter(run: Mapping[str, Any], spec: RowSpec) -> dict[str, Any]:
    adapter = _mapping(run.get("adapter"), f"{spec.name}.adapter")
    _require(adapter.get("adapter_id") == spec.adapter_id, f"{spec.name}: adapter id mismatch")
    _require(adapter.get("track") == "raw-retrieval", f"{spec.name}: adapter track mismatch")
    _require(adapter.get("config_sha256") == run["configuration"].get("adapter_config_sha256"), f"{spec.name}: adapter config digest mismatch")
    package_pin = _safe_package_pin(_mapping(adapter.get("package_pin"), f"{spec.name}.adapter.package_pin"))
    source_pin = _safe_source_pin(_mapping(adapter.get("source_pin"), f"{spec.name}.adapter.source_pin"))
    execution = _safe_execution(_mapping(adapter.get("execution"), f"{spec.name}.adapter.execution"))
    cost = _safe_cost(_mapping(adapter.get("cost"), f"{spec.name}.adapter.cost"))
    _require(cost["external_api_calls"] == 0 and cost["external_api_cost_usd"] == 0, f"{spec.name}: external API use is not allowed")

    result: dict[str, Any] = {
        "adapter_id": spec.adapter_id,
        "config_sha256": _sha256(adapter.get("config_sha256"), f"{spec.name}.adapter.config_sha256"),
        "cost": cost,
        "execution": execution,
        "implementation": _safe_token(adapter.get("implementation"), f"{spec.name}.adapter.implementation"),
        "package_pin": package_pin,
        "qualifier": spec.qualifier,
        "retrieval_family": _safe_token(adapter.get("retrieval_family"), f"{spec.name}.adapter.retrieval_family"),
        "semantic": adapter.get("semantic"),
        "source_pin": source_pin,
    }
    _require(isinstance(result["semantic"], bool), f"{spec.name}: adapter semantic flag must be boolean")

    if spec.adapter_id == "autopsy":
        _require(result["implementation"] == "autopsy-isolated-direct-v1", f"{spec.name}: unexpected Autopsy implementation")
        _require(result["retrieval_family"] == "hybrid" and result["semantic"] is True, f"{spec.name}: Autopsy must be semantic hybrid")
        _require(package_pin.get("name") == "autopsy-memory" and package_pin.get("version") == "0.1.30", f"{spec.name}: Autopsy package pin mismatch")
        _require(adapter.get("embedding_model") == "BAAI/bge-base-en-v1.5", f"{spec.name}: Autopsy embedding model mismatch")
        _require(adapter.get("embedding_model_revision") == AUTOPSY_EMBEDDING_REVISION, f"{spec.name}: Autopsy embedding revision mismatch")
        _require(adapter.get("reranker_model") == "BAAI/bge-reranker-base", f"{spec.name}: Autopsy reranker mismatch")
        _require(adapter.get("reranker_model_revision") == AUTOPSY_RERANKER_REVISION, f"{spec.name}: Autopsy reranker revision mismatch")
        _require(adapter.get("evaluated_vector_coverage") == 1.0, f"{spec.name}: Autopsy vector coverage must be 1.0")
        _require(adapter.get("evaluated_eligible_items") == adapter.get("evaluated_embedded_items"), f"{spec.name}: Autopsy embedded count mismatch")
        channels = _mapping(run.get("retrieval_channel_counts"), f"{spec.name}.retrieval_channel_counts")
        _require(_integer(channels.get("embedding"), f"{spec.name}.retrieval_channel_counts.embedding") > 0, f"{spec.name}: no observed embedding retrieval")
        result["embedding"] = {
            "eligible_items": _integer(adapter.get("evaluated_eligible_items"), f"{spec.name}.eligible_items", minimum=1),
            "embedded_items": _integer(adapter.get("evaluated_embedded_items"), f"{spec.name}.embedded_items", minimum=1),
            "model": "BAAI/bge-base-en-v1.5",
            "revision": AUTOPSY_EMBEDDING_REVISION,
            "vector_coverage": 1.0,
        }
        result["reranker"] = {"model": "BAAI/bge-reranker-base", "revision": AUTOPSY_RERANKER_REVISION}
        result["restrictions"] = {"access_telemetry_recorded": False, "query_state_mode": "static-read"}
    elif spec.adapter_id == "builtin-bm25":
        _require(result["implementation"] == "autopsy-builtin-okapi-bm25-v1", f"{spec.name}: unexpected BM25 implementation")
        _require(result["retrieval_family"] == "lexical" and result["semantic"] is False, f"{spec.name}: BM25 must be lexical")
        _require(package_pin.get("name") == "autopsy-memory" and package_pin.get("version") == "0.1.30", f"{spec.name}: BM25 package pin mismatch")
        result["restrictions"] = {"lexical_control": True, "memory_system": False}
    else:
        _require(result["implementation"] == "mem0-oss-2.0.11-raw-infer-false-v1", f"{spec.name}: unexpected Mem0 implementation")
        _require(result["retrieval_family"] == "dense-semantic" and result["semantic"] is True, f"{spec.name}: Mem0 must be dense semantic")
        _require(package_pin.get("name") == "mem0ai" and package_pin.get("version") == "2.0.11", f"{spec.name}: Mem0 package pin mismatch")
        _require(source_pin.get("commit") == MEM0_COMMIT, f"{spec.name}: Mem0 source commit mismatch")
        config = _mapping(adapter.get("config"), f"{spec.name}.adapter.config")
        mem0 = _mapping(config.get("mem0"), f"{spec.name}.adapter.config.mem0")
        vector_store = _mapping(config.get("vector_store"), f"{spec.name}.adapter.config.vector_store")
        isolation = _mapping(config.get("isolation"), f"{spec.name}.adapter.config.isolation")
        _require(mem0.get("infer") is False and mem0.get("telemetry") is False and mem0.get("commit") == MEM0_COMMIT, f"{spec.name}: Mem0 infer/telemetry/commit mismatch")
        _require(vector_store.get("provider") == "qdrant" and vector_store.get("on_disk") is True and vector_store.get("mode") == "embedded-local-path", f"{spec.name}: Mem0 must use local on-disk Qdrant")
        _require(isolation.get("runtime_network") == "offline" and isolation.get("inherited_api_credentials") is False, f"{spec.name}: Mem0 isolation mismatch")
        _require(execution.get("runtime_offline_enforced") is True, f"{spec.name}: Mem0 runtime must enforce offline mode")
        _require(adapter.get("embedding_model") == "sentence-transformers/multi-qa-MiniLM-L6-cos-v1", f"{spec.name}: Mem0 embedding model mismatch")
        _require(adapter.get("embedding_model_revision") == MEM0_EMBEDDING_REVISION, f"{spec.name}: Mem0 embedding revision mismatch")
        _require(adapter.get("evaluated_vector_coverage") == 1.0, f"{spec.name}: Mem0 vector coverage must be 1.0")
        _require(adapter.get("evaluated_eligible_items") == adapter.get("evaluated_embedded_items"), f"{spec.name}: Mem0 embedded count mismatch")
        result["embedding"] = {
            "eligible_items": _integer(adapter.get("evaluated_eligible_items"), f"{spec.name}.eligible_items", minimum=1),
            "embedded_items": _integer(adapter.get("evaluated_embedded_items"), f"{spec.name}.embedded_items", minimum=1),
            "model": "sentence-transformers/multi-qa-MiniLM-L6-cos-v1",
            "revision": MEM0_EMBEDDING_REVISION,
            "vector_coverage": 1.0,
        }
        result["restrictions"] = {
            "infer": False,
            "local_qdrant": True,
            "native_llm_extraction": False,
            "runtime_offline": True,
            "telemetry": False,
        }
    return result


def _validate_configuration(run: Mapping[str, Any], score: Mapping[str, Any], spec: RowSpec) -> dict[str, Any]:
    config = _mapping(run.get("configuration"), f"{spec.name}.configuration")
    expected = {
        "adapter_id": spec.adapter_id,
        "categories": [],
        "granularity": spec.granularity,
        "k_values": list(spec.k_values),
        "query_state_reset": True,
        "representation": spec.representation,
        "route": spec.route,
        "sample_size": 0,
        "selection": "all",
        "temporal_policy": "dataset",
        "track": "raw-retrieval",
    }
    for key, value in expected.items():
        _require(config.get(key) == value, f"{spec.name}: configuration.{key} mismatch")
    _require(_integer(config.get("repetitions"), f"{spec.name}.configuration.repetitions", minimum=2) >= 2, f"{spec.name}: at least two repetitions are required")
    config_sha = _sha256(config.get("adapter_config_sha256"), f"{spec.name}.configuration.adapter_config_sha256")
    score_config = _mapping(score.get("configuration"), f"{spec.name}.score.configuration")
    for key in ("adapter_id", "granularity", "k_values", "representation", "track"):
        _require(score_config.get(key) == config.get(key), f"{spec.name}: score configuration.{key} mismatch")
    _require(score_config.get("adapter_config_sha256") == config_sha, f"{spec.name}: score adapter config digest mismatch")
    return {
        "adapter_config_sha256": config_sha,
        "granularity": spec.granularity,
        "k_values": list(spec.k_values),
        "repetitions": config["repetitions"],
        "representation": spec.representation,
        "route": spec.route,
        "temporal_policy": "dataset",
        "track": "raw-retrieval",
    }


def _validate_metrics(metrics: Mapping[str, Any], spec: RowSpec) -> dict[str, Any]:
    expected_counts = {
        "cases": spec.cases,
        "retrieval_scored_cases": spec.retrieval_scored_cases,
        "abstention_scored_cases": spec.abstention_scored_cases,
        "unscored_retrieval_cases": spec.unscored_retrieval_cases,
    }
    for key, value in expected_counts.items():
        _require(metrics.get(key) == value, f"{spec.name}: metrics.{key} must be {value}")
    overall = _mapping(metrics.get("metrics"), f"{spec.name}.metrics.metrics")
    abstention = _mapping(metrics.get("abstention"), f"{spec.name}.metrics.abstention")
    categories = _mapping(metrics.get("by_category"), f"{spec.name}.metrics.by_category")
    exclusions = _mapping(metrics.get("exclusions"), f"{spec.name}.metrics.exclusions")
    latency = _mapping(metrics.get("latency_seconds"), f"{spec.name}.metrics.latency_seconds")
    _require(set(categories) == set(spec.categories), f"{spec.name}: category set mismatch")
    required_metric_names = {
        *(f"recall_any@{k}" for k in spec.k_values),
        *(f"recall_all@{k}" for k in spec.k_values),
        *(f"evidence_recall@{k}" for k in spec.k_values),
        *(f"forbidden_exposure@{k}" for k in spec.k_values),
        f"mrr@{max(spec.k_values)}",
    }
    _require(required_metric_names.issubset(overall), f"{spec.name}: required metrics are missing")
    _validate_numeric_tree(overall, f"{spec.name}.metrics.overall")
    _validate_numeric_tree(abstention, f"{spec.name}.metrics.abstention")
    _validate_numeric_tree(categories, f"{spec.name}.metrics.by_category")
    _validate_numeric_tree(exclusions, f"{spec.name}.metrics.exclusions")
    _validate_numeric_tree(latency, f"{spec.name}.metrics.latency_seconds")
    _walk_forbidden_metrics(metrics, f"{spec.name}.metrics")
    for key in ("f1", "precision", "recall"):
        value = float(_number(abstention.get(key), f"{spec.name}.abstention.{key}"))
        _require(0.0 <= value <= 1.0, f"{spec.name}: abstention {key} is outside [0,1]")
    return {
        "counts": {**expected_counts, "exclusions": _json_clone(exclusions)},
        "metrics": {
            "abstention": _json_clone(abstention),
            "by_category": _json_clone(categories),
            "overall": _json_clone(overall),
        },
        "latency": _json_clone(latency),
    }


def _safe_numeric_object(value: Any, label: str) -> dict[str, Any]:
    result = _mapping(value, label)
    _validate_numeric_tree(result, label)
    return _json_clone(result)


def validate_pair(spec: RowSpec, run_path: Path, score_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    run = read_json(run_path)
    score = read_json(score_path)
    _require(run.get("schema") == "autopsy-external-evaluation/v1", f"{spec.name}: unsupported run schema")
    _require(run.get("evaluation") == "external-retrieval" and run.get("status") == "complete", f"{spec.name}: run is not complete raw retrieval")
    _require(run.get("comparable_run") is True, f"{spec.name}: run is not comparable")
    _require(score.get("schema") == "autopsy-external-evaluation-score/v1", f"{spec.name}: unsupported score schema")
    _require(score.get("evaluation") == "external-retrieval-score" and score.get("status") == "complete", f"{spec.name}: independent score is incomplete")

    run_dataset = _dataset_fields(_mapping(run.get("dataset"), f"{spec.name}.dataset"), spec, f"{spec.name}.dataset")
    score_dataset = _dataset_fields(_mapping(score.get("dataset"), f"{spec.name}.score.dataset"), spec, f"{spec.name}.score.dataset")
    _require(run_dataset == score_dataset, f"{spec.name}: run/score dataset provenance mismatch")
    protocol = _validate_configuration(run, score, spec)

    run_runtime = _mapping(run.get("runtime"), f"{spec.name}.runtime")
    score_runtime = _mapping(score.get("runtime"), f"{spec.name}.score.runtime")
    commit = _commit(run_runtime.get("git_commit"), f"{spec.name}.runtime.git_commit")
    tree_sha = _sha256(run_runtime.get("source_tree_sha256"), f"{spec.name}.runtime.source_tree_sha256")
    _require(run_runtime.get("git_dirty") is False, f"{spec.name}: run source is dirty")
    _require(score_runtime.get("git_dirty") is False, f"{spec.name}: score source is dirty")
    _require(score_runtime.get("git_commit") == commit, f"{spec.name}: run and score commits differ")
    _require(score_runtime.get("source_tree_sha256") == tree_sha, f"{spec.name}: run and score source trees differ")
    runtime_profile = _runtime_profile(run_runtime)
    _require(_runtime_profile(score_runtime) == runtime_profile, f"{spec.name}: run and score runtime profiles differ")

    qualification = _mapping(run.get("qualification"), f"{spec.name}.qualification")
    for gate in QUALIFICATION_GATES:
        _require(qualification.get(gate) is True, f"{spec.name}: qualification gate {gate} did not pass")
    _require(qualification.get("required_metric_cutoffs") == list(spec.k_values), f"{spec.name}: qualification cutoffs mismatch")
    if spec.adapter_id != "builtin-bm25":
        _require(qualification.get("semantic_route_qualified") is True, f"{spec.name}: semantic route is not qualified")
    _require(run.get("case_errors") == [], f"{spec.name}: case errors are present")
    _require(run.get("ranking_instability_cases") == 0, f"{spec.name}: rankings are unstable")

    leakage = _mapping(run.get("leakage_audit"), f"{spec.name}.leakage_audit")
    for key in LEAKAGE_ZERO_FIELDS:
        _require(leakage.get(key) == 0, f"{spec.name}: leakage audit {key} is nonzero")
    safe_leakage = {key: _integer(value, f"{spec.name}.leakage_audit.{key}") for key, value in leakage.items()}

    run_metrics = _mapping(run.get("metrics"), f"{spec.name}.metrics")
    score_metrics = _mapping(score.get("metrics"), f"{spec.name}.score.metrics")
    _require(canonical_json(run_metrics) == canonical_json(score_metrics), f"{spec.name}: run and independent-score metrics differ")
    public_metrics = _validate_metrics(run_metrics, spec)

    prediction_integrity = _mapping(score.get("prediction_integrity"), f"{spec.name}.score.prediction_integrity")
    _require(prediction_integrity.get("valid") is True and prediction_integrity.get("full_dataset_complete") is True, f"{spec.name}: prediction integrity is not complete")
    _require(prediction_integrity.get("coverage") == 1.0, f"{spec.name}: prediction coverage is not 1.0")
    for key in ("dataset_cases", "provided", "matched"):
        _require(prediction_integrity.get(key) == spec.cases, f"{spec.name}: prediction_integrity.{key} mismatch")
    _require(prediction_integrity.get("missing_dataset_cases") == 0 and prediction_integrity.get("unknown_case_ids") == [], f"{spec.name}: prediction IDs are incomplete or unknown")
    _require(len(_list(score.get("case_scores"), f"{spec.name}.score.case_scores")) == spec.cases, f"{spec.name}: independent score lacks per-case coverage")

    run_artifacts = _mapping(run.get("artifacts"), f"{spec.name}.artifacts")
    score_artifacts = _mapping(score.get("artifacts"), f"{spec.name}.score.artifacts")
    predictions_sha = _sha256(run_artifacts.get("predictions_sha256"), f"{spec.name}.artifacts.predictions_sha256")
    _require(run_artifacts.get("prediction_count") == spec.cases, f"{spec.name}: run prediction count mismatch")
    _require(score_artifacts.get("prediction_rows") == spec.cases, f"{spec.name}: score prediction count mismatch")
    _require(score_artifacts.get("source_predictions_sha256") == predictions_sha, f"{spec.name}: score source prediction digest mismatch")
    _require(score_artifacts.get("canonical_predictions_sha256") == predictions_sha, f"{spec.name}: canonical prediction digest mismatch")

    system = _validate_adapter(run, spec)
    score_config = _mapping(score.get("configuration"), f"{spec.name}.score.configuration")
    _require(canonical_json(score_config.get("adapter_package_pin")) == canonical_json(run["adapter"].get("package_pin")), f"{spec.name}: score package pin mismatch")
    _require(canonical_json(score_config.get("adapter_source_pin")) == canonical_json(run["adapter"].get("source_pin")), f"{spec.name}: score source pin mismatch")
    _require(canonical_json(score_config.get("adapter_execution")) == canonical_json(run["adapter"].get("execution")), f"{spec.name}: score execution provenance mismatch")

    channels = _safe_numeric_object(run.get("retrieval_channel_counts"), f"{spec.name}.retrieval_channel_counts")
    ingestion = _safe_numeric_object(run.get("ingestion"), f"{spec.name}.ingestion")
    timings = _safe_numeric_object(run.get("timings"), f"{spec.name}.timings")
    latency_profiles = _safe_numeric_object(run.get("latency_profiles_seconds"), f"{spec.name}.latency_profiles_seconds")
    source_timestamps = {
        "run_completed_at": _timestamp(run.get("completed_at"), f"{spec.name}.completed_at"),
        "run_started_at": _timestamp(run.get("started_at"), f"{spec.name}.started_at"),
        "score_scored_at": _timestamp(score.get("scored_at"), f"{spec.name}.score.scored_at"),
    }
    public_runtime = {
        **runtime_profile,
        "git_commit": commit,
        "git_dirty": False,
        "process_peak_rss_bytes": _integer(run_runtime.get("process_peak_rss_bytes"), f"{spec.name}.runtime.process_peak_rss_bytes", minimum=1),
        "source_tree_sha256": tree_sha,
    }
    public_qualification = {key: True for key in QUALIFICATION_GATES}
    public_qualification["semantic_route_qualified"] = qualification.get("semantic_route_qualified")
    public_qualification["required_metric_cutoffs"] = list(spec.k_values)
    public_qualification["passed"] = True

    aggregate = {
        "schema": AGGREGATE_SCHEMA,
        "release": {"name": RELEASE_NAME, "source_commit": commit, "source_tree_sha256": tree_sha},
        "row": {"dataset": spec.dataset, "name": spec.name, "system": spec.adapter_id},
        "dataset": run_dataset,
        "protocol": protocol,
        "system": system,
        "runtime": public_runtime,
        "qualification": public_qualification,
        "counts": public_metrics["counts"],
        "metrics": public_metrics["metrics"],
        "timing": {
            "ingestion": ingestion,
            "latency_profiles_seconds": latency_profiles,
            "latency_seconds": public_metrics["latency"],
            "total": timings,
        },
        "retrieval_channel_counts": channels,
        "leakage_audit": dict(sorted(safe_leakage.items())),
        "source_timestamps": source_timestamps,
        "integrity": {
            "independent_metric_equality": True,
            "prediction_integrity": {
                "coverage": 1.0,
                "dataset_cases": spec.cases,
                "full_dataset_complete": True,
                "matched": spec.cases,
                "missing_dataset_cases": 0,
                "provided": spec.cases,
                "unknown_case_count": 0,
                "valid": True,
            },
            "source_predictions_sha256": predictions_sha,
            "source_run_sha256": sha256_file(run_path),
            "source_score_sha256": sha256_file(score_path),
            "transformation": {
                "id": TRANSFORMATION_ID,
                "excluded_classes": [
                    "absolute-and-local-paths",
                    "answers-and-generated-text",
                    "case-identifiers-and-labels",
                    "dataset-conversation-and-query-text",
                    "ranked-relevant-and-forbidden-source-identifiers",
                ],
                "sanitized_sha256_location": "MANIFEST.json",
            },
        },
    }
    assert_public_safe(aggregate, spec.name)
    metadata = {
        "commit": commit,
        "runtime_profile": runtime_profile,
        "source_tree_sha256": tree_sha,
        "source_run_sha256": aggregate["integrity"]["source_run_sha256"],
        "source_score_sha256": aggregate["integrity"]["source_score_sha256"],
        "source_predictions_sha256": predictions_sha,
    }
    return aggregate, metadata


def _looks_like_local_path(value: str) -> bool:
    if value.startswith(("/", "~/", "file://", "\\\\")):
        return True
    return re.match(r"^[A-Za-z]:[\\/]", value) is not None


def assert_public_safe(value: Any, label: str = "aggregate") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            _require(lowered not in FORBIDDEN_OUTPUT_KEYS and not lowered.endswith("_path"), f"{label}: forbidden output key {key}")
            assert_public_safe(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_public_safe(child, f"{label}[{index}]")
    elif isinstance(value, str):
        _require(not _looks_like_local_path(value), f"{label}: local path leaked into output")


def _replace_block(text: str, start: str, end: str, replacement: str) -> str:
    _require(text.count(start) == 1 and text.count(end) == 1, f"README template needs exactly one {start}/{end} block")
    before, remainder = text.split(start, 1)
    _, after = remainder.split(end, 1)
    return before + start + "\n" + replacement.rstrip() + "\n" + end + after


def _format_metric(value: Any) -> str:
    return f"{float(_number(value, 'README metric')):.4f}"


def render_readme(template: str, aggregates: Mapping[str, dict[str, Any]], commit: str) -> str:
    status = (
        f"**Publication status:** all six aggregate rows passed the same-clean-commit "
        f"release gate at `{commit}`. See `MANIFEST.json` and `SHA256SUMS` for the "
        "source and sanitized artifact bindings."
    )
    rows = [
        "| Dataset | System | Recall-any@10 | Recall-all@10 | Evidence recall@10 | MRR@K | Abstention F1 | Mean query latency | Aggregate artifact |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for spec in ROW_SPECS:
        aggregate = aggregates[spec.name]
        overall = aggregate["metrics"]["overall"]
        abstention = aggregate["metrics"]["abstention"]
        latency_ms = float(aggregate["timing"]["latency_seconds"]["mean"]) * 1000.0
        rows.append(
            "| "
            + " | ".join(
                (
                    spec.display_dataset,
                    spec.display_system,
                    _format_metric(overall["recall_any@10"]),
                    _format_metric(overall["recall_all@10"]),
                    _format_metric(overall["evidence_recall@10"]),
                    _format_metric(overall[f"mrr@{max(spec.k_values)}"]),
                    _format_metric(abstention["f1"]),
                    f"{latency_ms:.2f} ms",
                    f"`aggregate/{spec.output_filename}`",
                )
            )
            + " |"
        )
    text = _replace_block(template, STATUS_START, STATUS_END, status)
    text = _replace_block(text, TABLE_START, TABLE_END, "\n".join(rows))
    locomo = aggregates["locomo-autopsy"]["metrics"]["overall"]
    longmem = aggregates["longmemeval-s-autopsy"]["metrics"]["overall"]
    replacements = {
        "<commit>": commit,
        "<LoCoMo Recall-any@10>": f"{_format_metric(locomo['recall_any@10'])} Recall-any@10",
        "<LoCoMo MRR@10>": f"{_format_metric(locomo['mrr@10'])} MRR@10",
        "<LongMemEval Recall-any@10>": f"{_format_metric(longmem['recall_any@10'])} Recall-any@10",
        "<LongMemEval MRR@50>": f"{_format_metric(longmem['mrr@50'])} MRR@50",
    }
    for needle, replacement in replacements.items():
        text = text.replace(needle, replacement)
    _require(" pending " not in f" {text.lower()} ", "generated README still contains pending result cells")
    return text if text.endswith("\n") else text + "\n"


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(value)


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    return {"bytes": path.stat().st_size, "relative_file": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}


def build_release(
    pairs: Mapping[str, tuple[Path, Path]],
    output_dir: Path,
    *,
    readme_template: Path | None = None,
) -> dict[str, Any]:
    expected_names = set(ROW_BY_NAME)
    _require(set(pairs) == expected_names, f"expected exactly these pair names: {', '.join(sorted(expected_names))}")
    output_dir = output_dir.resolve()
    _require(not output_dir.exists(), f"output directory already exists: {output_dir}")
    source_dir = Path(__file__).resolve().parent
    readme_template = (readme_template or source_dir / "README.md").resolve()
    attribution_template = source_dir / "ATTRIBUTION.md"
    schema_source = source_dir / "schemas" / "aggregate-result-v1.schema.json"
    for path in (readme_template, attribution_template, schema_source):
        _require(path.is_file(), f"publication source file is missing: {path}")

    aggregates: dict[str, dict[str, Any]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for spec in ROW_SPECS:
        run_path, score_path = pairs[spec.name]
        aggregates[spec.name], metadata[spec.name] = validate_pair(spec, Path(run_path).resolve(), Path(score_path).resolve())
    commits = {item["commit"] for item in metadata.values()}
    trees = {item["source_tree_sha256"] for item in metadata.values()}
    profiles = {canonical_json(item["runtime_profile"]) for item in metadata.values()}
    _require(len(commits) == 1, "all six run/score pairs must use the same clean commit")
    _require(len(trees) == 1, "all six run/score pairs must use the same source tree")
    _require(len(profiles) == 1, "all six run/score pairs must use the same runtime/hardware profile")
    commit = next(iter(commits))
    tree_sha = next(iter(trees))

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        aggregate_dir = stage / "aggregate"
        aggregate_dir.mkdir()
        aggregate_paths: dict[str, Path] = {}
        for spec in ROW_SPECS:
            path = aggregate_dir / spec.output_filename
            _write_bytes(path, pretty_json(aggregates[spec.name]))
            aggregate_paths[spec.name] = path

        readme_text = readme_template.read_text(encoding="utf-8")
        _write_bytes(stage / "README.md", render_readme(readme_text, aggregates, commit).encode("utf-8"))
        _write_bytes(stage / "ATTRIBUTION.md", attribution_template.read_bytes())
        _write_bytes(stage / "schemas" / schema_source.name, schema_source.read_bytes())

        output_records = [
            _file_record(stage, path)
            for path in sorted((path for path in stage.rglob("*") if path.is_file()), key=lambda item: item.relative_to(stage).as_posix())
        ]
        rows = []
        for spec in ROW_SPECS:
            rows.append({
                "dataset": spec.dataset,
                "name": spec.name,
                "sanitized_aggregate": _file_record(stage, aggregate_paths[spec.name]),
                "source_artifacts": {
                    "predictions_sha256": metadata[spec.name]["source_predictions_sha256"],
                    "run_sha256": metadata[spec.name]["source_run_sha256"],
                    "score_sha256": metadata[spec.name]["source_score_sha256"],
                },
                "system": spec.adapter_id,
            })
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "release": {"name": RELEASE_NAME, "source_commit": commit, "source_tree_sha256": tree_sha},
            "builder": {"name": Path(__file__).name, "sha256": sha256_file(Path(__file__).resolve()), "standard_library_only": True},
            "dataset_artifacts_redistributed": False,
            "output_artifacts": output_records,
            "rows": rows,
            "transformation": {
                "id": TRANSFORMATION_ID,
                "policy": "fixed-field-allowlist; no input artifact is rewritten or copied",
                "row_level_artifacts_redistributed": False,
            },
        }
        assert_public_safe(manifest, "manifest")
        _write_bytes(stage / "MANIFEST.json", pretty_json(manifest))

        checksum_paths = sorted(
            (path for path in stage.rglob("*") if path.is_file() and path.name != "SHA256SUMS"),
            key=lambda item: item.relative_to(stage).as_posix(),
        )
        checksum_text = "".join(f"{sha256_file(path)}  {path.relative_to(stage).as_posix()}\n" for path in checksum_paths)
        _write_bytes(stage / "SHA256SUMS", checksum_text.encode("utf-8"))
        os.replace(stage, output_dir)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {
        "status": "complete",
        "output_dir": str(output_dir),
        "source_commit": commit,
        "aggregate_files": len(ROW_SPECS),
        "manifest_sha256": sha256_file(output_dir / "MANIFEST.json"),
    }


def parse_pairs(values: Sequence[Sequence[str]]) -> dict[str, tuple[Path, Path]]:
    pairs: dict[str, tuple[Path, Path]] = {}
    for name, run, score in values:
        _require(name not in pairs, f"duplicate pair name: {name}")
        pairs[name] = (Path(run), Path(score))
    return pairs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pair",
        action="append",
        nargs=3,
        required=True,
        metavar=("NAME", "RUN_JSON", "SCORE_JSON"),
        help="Named run and independent-score pair; repeat for all six required rows.",
    )
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory to create atomically.")
    parser.add_argument("--readme-template", type=Path, help="README template; defaults to the scaffold README beside this script.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_release(parse_pairs(args.pair), args.output_dir, readme_template=args.readme_template)
    except PublicationError as exc:
        print(f"publication build blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
