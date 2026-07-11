from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "evaluation" / "publication" / "raw-retrieval-v1" / "build_release.py"
SPEC = importlib.util.spec_from_file_location("autopsy_publication_builder", BUILDER_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


COMMIT = "a" * 40
TREE_SHA = "b" * 64
SECRET_PATH = "/Users/private/person/benchmark.json"
SECRET_QUERY = "private benchmark query that must never enter the bundle"

CATEGORY_CASES = {
    "locomo": {
        "adversarial-abstention": (446, 446),
        "multi-hop": (282, 280),
        "open-domain": (96, 92),
        "single-hop": (841, 841),
        "temporal": (321, 321),
    },
    "longmemeval-s": {
        "knowledge-update": (78, 78),
        "multi-session": (133, 133),
        "single-session-assistant": (56, 5),
        "single-session-preference": (30, 30),
        "single-session-user": (70, 70),
        "temporal-reasoning": (133, 133),
    },
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def runtime(*, dirty: bool = False, commit: str = COMMIT) -> dict:
    return {
        "autopsy_source_version": "0.1.30",
        "autopsy_version": "0.1.30",
        "cpu_count": 8,
        "dependency_versions": {
            "falkordb": "1.6.1",
            "falkordblite": "0.10.0",
            "redis": "7.4.1",
            "sentence-transformers": "5.6.0",
        },
        "git_commit": commit,
        "git_dirty": dirty,
        "machine": "arm64",
        "platform": "macOS-test-arm64",
        "process_peak_rss_bytes": 123456,
        "processor": "Synthetic CPU",
        "python": "3.12.13",
        "source_tree_sha256": TREE_SHA,
        "total_memory_bytes": 16_000_000_000,
    }


def abstention(scored_cases: int) -> dict:
    return {
        "f1": 0.0,
        "false_negative": 0,
        "false_positive": 0,
        "precision": 0.0,
        "recall": 0.0,
        "scored_cases": scored_cases,
        "true_negative": scored_cases,
        "true_positive": 0,
    }


def metric_map(k_values: tuple[int, ...], base: float) -> dict:
    result = {}
    for cutoff in k_values:
        result.update({
            f"evidence_recall@{cutoff}": base,
            f"forbidden_exposure@{cutoff}": 0.0,
            f"ndcg@{cutoff}": base,
            f"recall_all@{cutoff}": base,
            f"recall_any@{cutoff}": base,
            f"upstream_longmemeval_ndcg@{cutoff}": base,
        })
    result[f"mrr@{max(k_values)}"] = base
    return result


def adapter_payload(spec, config_sha: str) -> dict:
    execution = {"local": True, "mode": "local-in-process", "network_required": False, "remote": False}
    cost = {"currency": "USD", "external_api_calls": 0, "external_api_cost_usd": 0.0}
    if spec.adapter_id == "autopsy":
        return {
            "adapter_id": "autopsy",
            "config": {"query_state_mode": "static-read"},
            "config_sha256": config_sha,
            "cost": cost,
            "embedding_model": "BAAI/bge-base-en-v1.5",
            "embedding_model_revision": builder.AUTOPSY_EMBEDDING_REVISION,
            "evaluated_eligible_items": 100,
            "evaluated_embedded_items": 100,
            "evaluated_vector_coverage": 1.0,
            "execution": execution,
            "implementation": "autopsy-isolated-direct-v1",
            "package_pin": {"installed_distribution_version": "0.1.30", "name": "autopsy-memory", "version": "0.1.30"},
            "reranker_model": "BAAI/bge-reranker-base",
            "reranker_model_revision": builder.AUTOPSY_RERANKER_REVISION,
            "retrieval_family": "hybrid",
            "semantic": True,
            "source_pin": {"kind": "source-tree-sha256", "path": "autopsy_memory", "sha256": digest("autopsy-source")},
            "track": "raw-retrieval",
        }
    if spec.adapter_id == "builtin-bm25":
        return {
            "adapter_id": "builtin-bm25",
            "config": {},
            "config_sha256": config_sha,
            "cost": cost,
            "execution": execution,
            "implementation": "autopsy-builtin-okapi-bm25-v1",
            "package_pin": {"installed_distribution_version": "0.1.30", "name": "autopsy-memory", "version": "0.1.30"},
            "retrieval_family": "lexical",
            "semantic": False,
            "source_pin": {"kind": "file-sha256", "path": "adapters.py", "sha256": digest("bm25-source")},
            "track": "raw-retrieval",
        }
    execution.update({
        "bootstrap_network_required": True,
        "external_service_credentials_required": False,
        "initial_model_download_network_required": True,
        "mode": "local-isolated-subprocess",
        "runtime_offline_enforced": True,
    })
    return {
        "adapter_id": "mem0-oss-raw",
        "bootstrap_setup_path": "/private/bootstrap/setup.sh",
        "config": {
            "isolation": {"inherited_api_credentials": False, "runtime_network": "offline"},
            "mem0": {"commit": builder.MEM0_COMMIT, "infer": False, "telemetry": False, "version": "2.0.11"},
            "vector_store": {"mode": "embedded-local-path", "on_disk": True, "provider": "qdrant"},
        },
        "config_sha256": config_sha,
        "cost": cost,
        "embedding_model": "sentence-transformers/multi-qa-MiniLM-L6-cos-v1",
        "embedding_model_revision": builder.MEM0_EMBEDDING_REVISION,
        "evaluated_eligible_items": 99,
        "evaluated_embedded_items": 99,
        "evaluated_vector_coverage": 1.0,
        "execution": execution,
        "implementation": "mem0-oss-2.0.11-raw-infer-false-v1",
        "package_pin": {
            "embedding_model": {"name": "sentence-transformers/multi-qa-MiniLM-L6-cos-v1", "revision": builder.MEM0_EMBEDDING_REVISION},
            "name": "mem0ai",
            "required_version": "2.0.11",
            "runtime_dependencies": {"mem0ai": "2.0.11", "qdrant-client": "1.18.0"},
            "version": "2.0.11",
        },
        "python_executable": "/private/venv/bin/python",
        "retrieval_family": "dense-semantic",
        "semantic": True,
        "source_pin": {
            "adapter_bundle": {"files": {"private/adapter.py": digest("file")}, "kind": "mem0-adapter-bundle-sha256", "sha256": digest("bundle")},
            "adapter_sha256": digest("adapter"),
            "bootstrap_assets": {"kind": "source-tree-sha256", "path": "mem0", "sha256": digest("bootstrap")},
            "commit": builder.MEM0_COMMIT,
            "kind": "upstream-git-commit-plus-complete-adapter-bundle",
            "repository": "https://github.com/mem0ai/mem0",
            "tag": "v2.0.11",
            "worker_sha256": digest("worker"),
        },
        "track": "raw-retrieval",
    }


def make_artifacts(spec, *, base: float) -> tuple[dict, dict]:
    dataset_sha = builder.LOCOMO_SHA256 if spec.dataset == "locomo" else builder.LONGMEM_SHA256
    dataset = {
        "bytes": 1234,
        "dataset": spec.dataset,
        "expected_sha256": dataset_sha,
        "homepage": "https://example.invalid/dataset",
        "license": "CC-BY-NC-4.0" if spec.dataset == "locomo" else "MIT",
        "path": SECRET_PATH,
        "sha256": dataset_sha,
        "source_url": "https://example.invalid/data.json",
        "version": "git-3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376" if spec.dataset == "locomo" else "hf-98d7416c24c778c2fee6e6f3006e7a073259d48f",
    }
    config_sha = digest(spec.name + "-config")
    adapter = adapter_payload(spec, config_sha)
    overall = metric_map(spec.k_values, base)
    by_category = {
        category: {
            "abstention": abstention(scored),
            "cases": cases,
            "metrics": metric_map(spec.k_values, base),
        }
        for category, (cases, scored) in CATEGORY_CASES[spec.dataset].items()
    }
    metrics = {
        "abstention": abstention(spec.abstention_scored_cases),
        "abstention_scored_cases": spec.abstention_scored_cases,
        "by_category": by_category,
        "cases": spec.cases,
        "exclusions": {"synthetic_exclusion": spec.unscored_retrieval_cases},
        "latency_seconds": {"mean": 0.01 + base / 100, "p50": 0.01, "p95": 0.02, "p99": 0.03},
        "metrics": overall,
        "retrieval_scored_cases": spec.retrieval_scored_cases,
        "unscored_retrieval_cases": spec.unscored_retrieval_cases,
    }
    config = {
        "adapter_config_sha256": config_sha,
        "adapter_id": spec.adapter_id,
        "categories": [],
        "granularity": spec.granularity,
        "k_values": list(spec.k_values),
        "query_state_reset": True,
        "repetitions": 2,
        "representation": spec.representation,
        "route": spec.route,
        "sample_size": 0,
        "seed": 42,
        "selection": "all",
        "temporal_policy": "dataset",
        "track": "raw-retrieval",
        "warmups": 0,
    }
    prediction_sha = digest(spec.name + "-predictions")
    qualification = {key: True for key in builder.QUALIFICATION_GATES}
    qualification.update({
        "required_metric_cutoffs": list(spec.k_values),
        "semantic_route_qualified": None if spec.adapter_id == "builtin-bm25" else True,
    })
    run = {
        "adapter": adapter,
        "artifacts": {"prediction_count": spec.cases, "predictions": "/private/predictions.jsonl", "predictions_sha256": prediction_sha},
        "case_errors": [],
        "comparable_run": True,
        "completed_at": "2026-07-12T01:00:00+00:00",
        "configuration": config,
        "dataset": dataset,
        "evaluation": "external-retrieval",
        "ingestion": {"characters": 1000, "documents": 100, "seconds": 1.0},
        "latency_profiles_seconds": {
            "first_measured_after_warmups": {"mean": 0.01, "p50": 0.01, "p95": 0.02, "p99": 0.03, "samples": spec.cases},
            "subsequent_repetitions": {"mean": 0.01, "p50": 0.01, "p95": 0.02, "p99": 0.03, "samples": spec.cases},
        },
        "leakage_audit": {
            "answers_ingested": 0,
            "documents_with_exact_query_text": 1,
            "documents_with_query_as_exact_title": 0,
            "judgments_ingested": 0,
            "prohibited_gold_metadata_documents": 0,
            "questions_ingested": 0,
            "source_metadata_fields_stripped": 5,
        },
        "metrics": metrics,
        "qualification": qualification,
        "ranking_instability_cases": 0,
        "retrieval_channel_counts": {"embedding": 1 if spec.adapter_id != "builtin-bm25" else 0, "lexical": 10},
        "runtime": runtime(),
        "schema": "autopsy-external-evaluation/v1",
        "started_at": "2026-07-12T00:00:00+00:00",
        "status": "complete",
        "timings": {"total_seconds": 2.0},
    }
    score = {
        "artifacts": {
            "canonical_predictions_sha256": prediction_sha,
            "prediction_rows": spec.cases,
            "source_predictions_path": "/private/predictions.jsonl",
            "source_predictions_sha256": prediction_sha,
        },
        "case_scores": [{"case_id": f"private-{index}", "query": SECRET_QUERY} for index in range(spec.cases)],
        "configuration": {
            "adapter_config_sha256": config_sha,
            "adapter_cost": copy.deepcopy(adapter["cost"]),
            "adapter_execution": copy.deepcopy(adapter["execution"]),
            "adapter_id": spec.adapter_id,
            "adapter_package_pin": copy.deepcopy(adapter["package_pin"]),
            "adapter_source_pin": copy.deepcopy(adapter["source_pin"]),
            "granularity": spec.granularity,
            "k_values": list(spec.k_values),
            "representation": spec.representation,
            "track": "raw-retrieval",
        },
        "dataset": copy.deepcopy(dataset),
        "evaluation": "external-retrieval-score",
        "metrics": copy.deepcopy(metrics),
        "prediction_integrity": {
            "coverage": 1.0,
            "dataset_cases": spec.cases,
            "full_dataset_complete": True,
            "matched": spec.cases,
            "missing_dataset_cases": 0,
            "provided": spec.cases,
            "unknown_case_ids": [],
            "valid": True,
        },
        "runtime": runtime(),
        "schema": "autopsy-external-evaluation-score/v1",
        "scored_at": "2026-07-12T01:01:00+00:00",
        "status": "complete",
    }
    return run, score


def materialize_pairs(root: Path) -> tuple[dict[str, tuple[Path, Path]], dict[str, tuple[dict, dict]]]:
    pairs = {}
    payloads = {}
    for index, spec in enumerate(builder.ROW_SPECS):
        run, score = make_artifacts(spec, base=0.50 + index / 100)
        run_path = root / f"{spec.name}.run.json"
        score_path = root / f"{spec.name}.score.json"
        write_json(run_path, run)
        write_json(score_path, score)
        pairs[spec.name] = (run_path, score_path)
        payloads[spec.name] = (run, score)
    return pairs, payloads


class PublicationBuilderTests(unittest.TestCase):
    def test_build_is_deterministic_aggregate_only_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pairs, _ = materialize_pairs(root)
            first = root / "release-one"
            second = root / "release-two"
            builder.build_release(pairs, first)
            builder.build_release(pairs, second)

            first_files = {path.relative_to(first): path.read_bytes() for path in first.rglob("*") if path.is_file()}
            second_files = {path.relative_to(second): path.read_bytes() for path in second.rglob("*") if path.is_file()}
            self.assertEqual(first_files, second_files)
            self.assertEqual(len(list((first / "aggregate").glob("*.json"))), 6)
            self.assertNotIn("pending", (first / "README.md").read_text(encoding="utf-8").lower())

            combined_json = b"".join(path.read_bytes() for path in first.rglob("*.json"))
            self.assertNotIn(SECRET_PATH.encode(), combined_json)
            self.assertNotIn(SECRET_QUERY.encode(), combined_json)
            self.assertNotIn(b"case_scores", combined_json)
            self.assertNotIn(b"python_executable", combined_json)
            self.assertNotIn(b"source_predictions_path", combined_json)

            manifest = json.loads((first / "MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["release"]["source_commit"], COMMIT)
            self.assertFalse(manifest["dataset_artifacts_redistributed"])
            self.assertEqual(len(manifest["rows"]), 6)
            for row in manifest["rows"]:
                aggregate = first / row["sanitized_aggregate"]["relative_file"]
                self.assertEqual(builder.sha256_file(aggregate), row["sanitized_aggregate"]["sha256"])

            checksums = {}
            for line in (first / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
                checksum, relative = line.split("  ", 1)
                checksums[relative] = checksum
            expected = {path.relative_to(first).as_posix() for path in first.rglob("*") if path.is_file() and path.name != "SHA256SUMS"}
            self.assertEqual(set(checksums), expected)
            for relative, checksum in checksums.items():
                self.assertEqual(builder.sha256_file(first / relative), checksum)

    def test_builder_fails_closed_for_missing_or_invalid_release_gate(self):
        mutations = {
            "mixed commit": lambda run, score: (run["runtime"].__setitem__("git_commit", "c" * 40), score["runtime"].__setitem__("git_commit", "c" * 40)),
            "dirty source": lambda run, score: run["runtime"].__setitem__("git_dirty", True),
            "not comparable": lambda run, score: run.__setitem__("comparable_run", False),
            "ranking instability": lambda run, score: run.__setitem__("ranking_instability_cases", 1),
            "case error": lambda run, score: run["case_errors"].append({"error": "synthetic"}),
            "forbidden exposure": lambda run, score: (run["metrics"]["metrics"].__setitem__("forbidden_exposure@10", 1.0), score["metrics"]["metrics"].__setitem__("forbidden_exposure@10", 1.0)),
            "metric mismatch": lambda run, score: score["metrics"]["metrics"].__setitem__("recall_any@10", 0.01),
            "invalid independent coverage": lambda run, score: score["prediction_integrity"].__setitem__("valid", False),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pairs, payloads = materialize_pairs(root)
                name = builder.ROW_SPECS[0].name
                run, score = payloads[name]
                mutate(run, score)
                write_json(pairs[name][0], run)
                write_json(pairs[name][1], score)
                output = root / "release"
                with self.assertRaises(builder.PublicationError):
                    builder.build_release(pairs, output)
                self.assertFalse(output.exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pairs, _ = materialize_pairs(root)
            pairs.pop(next(iter(pairs)))
            output = root / "release"
            with self.assertRaises(builder.PublicationError):
                builder.build_release(pairs, output)
            self.assertFalse(output.exists())

    def test_aggregate_schema_is_strict_and_publication_specific(self):
        schema_path = BUILDER_PATH.parent / "schemas" / "aggregate-result-v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schema"]["const"], builder.AGGREGATE_SCHEMA)
        self.assertIn("integrity", schema["required"])
        self.assertNotIn("case_scores", json.dumps(schema))


if __name__ == "__main__":
    unittest.main()
