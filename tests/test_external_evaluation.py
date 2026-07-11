from __future__ import annotations

import json
import io
import math
import os
import re
import shutil
import tempfile
import types
import unittest
from dataclasses import asdict, fields
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock
from unittest.mock import patch

from autopsy_memory import cli
from autopsy_memory.evaluation.datasets import (
    DatasetFormatError,
    bundled_coding_fixture_path,
    bundled_schema_dir,
    dataset_provenance,
    export_coding_fixture,
    export_schemas,
    iter_cases,
    iter_json_array,
    select_cases,
    validate_dataset,
)
from autopsy_memory.evaluation.metrics import (
    evidence_recall,
    aggregate_scores,
    ndcg_at_k,
    recall_all,
    recall_any,
    reciprocal_rank,
    score_case,
    upstream_longmemeval_ndcg_at_k,
)
from autopsy_memory.evaluation.adapters import BuiltinBM25EvaluationAdapter
from autopsy_memory.evaluation.models import (
    EvaluationCase,
    EvaluationCorpus,
    EvaluationDocument,
    EvaluationRelation,
    RetrievalRequest,
    RetrievalResult,
)
from autopsy_memory.evaluation.runner import (
    PREDICTION_SCHEMA,
    SCORE_REPORT_SCHEMA,
    audit_backend_leakage,
    backend_case_without_gold,
    comparison_qualification_passes,
    latency_summary,
    load_prediction_rows,
    run_evaluation,
    runtime_metadata,
    score_predictions,
)


ROOT = Path(__file__).resolve().parents[1]
CODING_FIXTURE = bundled_coding_fixture_path()

try:
    from redislite.falkordb_client import FalkorDB as _FalkorDB  # noqa: F401

    FALKORDBLITE_AVAILABLE = True
except Exception:
    FALKORDBLITE_AVAILABLE = False


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def prediction_row(case: EvaluationCase, dataset_path: Path, *, ranked_document_ids=None, retrieval_limit: int = 10) -> dict:
    return {
        "schema": PREDICTION_SCHEMA,
        "dataset": case.dataset,
        "dataset_sha256": dataset_provenance(case.dataset, dataset_path)["sha256"],
        "granularity": "turn",
        "representation": "audited",
        "adapter_id": "fixture-adapter",
        "track": "raw-retrieval",
        "adapter_config_sha256": "0" * 64,
        "adapter_package_pin": {"name": "fixture", "version": "1"},
        "adapter_source_pin": {"kind": "fixture", "sha256": "1" * 64},
        "adapter_execution": {"mode": "local-in-process", "local": True, "remote": False},
        "adapter_cost": {"external_api_cost_usd": 0.0},
        "case_id": case.case_id,
        "corpus_id": case.corpus_id,
        "category": case.category,
        "query": case.query,
        "ranked_document_ids": list(ranked_document_ids if ranked_document_ids is not None else case.relevant_document_ids),
        "route": "lexical",
        "retrieval_limit": retrieval_limit,
        "retrieval_reasons": [],
        "latency_seconds": 0.01,
        "repetitions": 1,
        "ingestion": {},
        "diagnostics": {},
    }


def assert_top_level_schema(test: unittest.TestCase, payload: dict, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    test.assertTrue(set(schema.get("required", [])).issubset(payload))
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        test.assertEqual(set(payload) - set(properties), set())
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "boolean": bool,
        "integer": int,
        "number": (int, float),
    }
    for key, value in payload.items():
        rules = properties.get(key, {})
        if "const" in rules:
            test.assertEqual(value, rules["const"], key)
        if "enum" in rules:
            test.assertIn(value, rules["enum"], key)
        expected_type = rules.get("type")
        if isinstance(expected_type, str):
            test.assertIsInstance(value, type_map[expected_type], key)
        if "pattern" in rules:
            test.assertIsNotNone(re.fullmatch(rules["pattern"], value), key)


class ExternalDatasetTests(unittest.TestCase):
    def test_streaming_json_array_handles_small_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            write_json(path, [{"id": 1, "text": "α" * 20}, {"id": 2, "text": "β" * 20}])
            self.assertEqual([item["id"] for item in iter_json_array(path, chunk_size=7)], [1, 2])

    def test_streaming_json_array_rejects_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('[{"id": 1}', encoding="utf-8")
            with self.assertRaises(DatasetFormatError):
                list(iter_json_array(path, chunk_size=3))

    def test_streaming_json_array_rejects_invalid_separators_and_trailing_content(self):
        for index, content in enumerate(
            ("[1 2]", "[1,]", "[,]", "[1] garbage", "[NaN]", '[{"a":1,"a":2}]')
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / f"bad-{index}.json"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(DatasetFormatError):
                    list(iter_json_array(path, chunk_size=2))

    def test_locomo_adapter_normalizes_malformed_evidence_lists(self):
        sample = {
            "sample_id": "conv-test",
            "conversation": {
                "speaker_a": "A",
                "speaker_b": "B",
                "session_1_date_time": "1:00 pm on 8 May, 2023",
                "session_1": [
                    {"speaker": "A", "dia_id": "D1:1", "text": "Alpha fact"},
                    {"speaker": "B", "dia_id": "D1:2", "text": "Beta fact"},
                ],
            },
            "qa": [
                {
                    "question": "What facts?",
                    "answer": "Alpha and beta",
                    "category": 1,
                    "evidence": ["D1:01; D1:2"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "locomo.json"
            write_json(path, [sample])
            case = next(iter_cases("locomo", path, granularity="turn"))
            self.assertEqual(case.relevant_document_ids, ("D1:1", "D1:2"))
            self.assertEqual(case.metadata["unresolved_evidence_ids"], [])

    def test_longmemeval_adapter_keeps_duplicate_sessions_distinct(self):
        entry = {
            "question_id": "q1",
            "question_type": "knowledge-update",
            "question": "What changed?",
            "answer": "new",
            "question_date": "2024/01/03 (Wed) 10:00",
            "haystack_session_ids": ["answer-1", "answer-1"],
            "haystack_dates": ["2024/01/01 (Mon) 10:00", "2024/01/02 (Tue) 10:00"],
            "haystack_sessions": [
                [{"role": "user", "content": "old", "has_answer": False}],
                [{"role": "user", "content": "new", "has_answer": True}],
            ],
            "answer_session_ids": ["answer-1"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long.json"
            write_json(path, [entry])
            case = next(iter_cases("longmemeval-s", path, granularity="session"))
            self.assertEqual([document.document_id for document in case.documents], ["answer-1", "answer-1#duplicate-2"])
            self.assertEqual(case.relevant_document_ids, ("answer-1#duplicate-2",))
            self.assertEqual(case.metadata["duplicate_session_id_count"], 1)
            self.assertEqual(case.category, "knowledge-update")

    def test_longmemeval_upstream_representation_matches_user_only_retriever(self):
        entry = {
            "question_id": "assistant-q",
            "question_type": "single-session-assistant",
            "question": "What did you recommend?",
            "answer": "the stable channel",
            "question_date": "2024/01/03 (Wed) 10:00",
            "haystack_session_ids": ["answer-session"],
            "haystack_dates": ["2024/01/01 (Mon) 10:00"],
            "haystack_sessions": [[
                {"role": "user", "content": "  What channel? \n", "has_answer": False},
                {"role": "assistant", "content": "Use the stable channel.", "has_answer": True},
            ]],
            "answer_session_ids": ["answer-session"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long.json"
            write_json(path, [entry])
            audited = next(iter_cases("longmemeval-s", path, granularity="session", representation="audited"))
            upstream = next(iter_cases("longmemeval-s", path, granularity="session", representation="upstream"))
            self.assertEqual(audited.relevant_document_ids, ("answer-session",))
            self.assertEqual(upstream.relevant_document_ids, ())
            self.assertEqual(upstream.documents[0].text, "  What channel? \n")
            self.assertIn("stable channel", audited.documents[0].text)
            self.assertNotIn("stable channel", upstream.documents[0].text)

    def test_coding_challenge_fixture_is_structurally_valid(self):
        payload = validate_dataset(
            "coding-traces",
            CODING_FIXTURE,
            granularity="turn",
            verify_checksum=False,
        )
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["counts"]["cases"], 9)
        self.assertIn("memory-poisoning", payload["categories"])
        poison = next(case for case in iter_cases("coding-traces", CODING_FIXTURE, granularity="turn") if case.case_id == "poison-quarantine")
        self.assertEqual(poison.forbidden_document_ids, ("evt-p2",))

    def test_coding_fixture_validation_rejects_empty_or_contradictory_inputs(self):
        valid_row = json.loads(CODING_FIXTURE.read_text(encoding="utf-8").splitlines()[0])
        mutations = []
        wrong_schema = json.loads(json.dumps(valid_row))
        wrong_schema["schema"] = "wrong"
        mutations.append(wrong_schema)
        overlap = json.loads(json.dumps(valid_row))
        overlap["forbidden_document_ids"] = [overlap["relevant_document_ids"][0]]
        mutations.append(overlap)
        contradictory_abstention = json.loads(json.dumps(valid_row))
        contradictory_abstention["expected_abstain"] = True
        mutations.append(contradictory_abstention)
        string_boolean = json.loads(json.dumps(valid_row))
        string_boolean["expected_abstain"] = "false"
        mutations.append(string_boolean)
        invalid_relation = json.loads(json.dumps(valid_row))
        invalid_relation["relations"] = [
            {"source_id": valid_row["documents"][0]["id"], "target_id": valid_row["documents"][1]["id"], "relation": ""}
        ]
        mutations.append(invalid_relation)

        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.jsonl"
            empty.write_text("", encoding="utf-8")
            empty_result = validate_dataset("coding-traces", empty, granularity="turn", verify_checksum=False)
            self.assertFalse(empty_result["valid"])
            self.assertTrue(empty_result["empty_dataset"])
            for index, mutation in enumerate(mutations):
                with self.subTest(index=index):
                    path = Path(directory) / f"invalid-{index}.jsonl"
                    path.write_text(json.dumps(mutation) + "\n", encoding="utf-8")
                    with self.assertRaises(DatasetFormatError):
                        validate_dataset("coding-traces", path, granularity="turn", verify_checksum=False)

    def test_coding_fixture_can_be_exported_from_the_package(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "coding.jsonl"
            payload = export_coding_fixture(output)
            self.assertEqual(payload["written"], str(output.resolve()))
            self.assertFalse(payload["leaderboard_dataset"])
            self.assertEqual(output.read_bytes(), CODING_FIXTURE.read_bytes())

    def test_published_schema_files_are_valid_json_with_stable_ids(self):
        schema_dir = bundled_schema_dir()
        schemas = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(schema_dir.glob("*.json"))]
        self.assertEqual(len(schemas), 8)
        self.assertTrue(all(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema" for schema in schemas))
        self.assertEqual(len({schema["$id"] for schema in schemas}), 8)

    def test_evaluation_schemas_can_be_exported_from_the_package(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = export_schemas(directory)
            self.assertEqual(payload["written"], 8)
            self.assertEqual(len(list(Path(directory).glob("*.schema.json"))), 8)

    def test_selection_is_stable_and_input_order_independent(self):
        cases = [
            EvaluationCase("x", f"q{index}", f"c{index}", "cat", "query", (), ("d",))
            for index in range(20)
        ]
        selected_forward = [case.case_id for case in select_cases(cases, sample_size=5, seed=7)]
        selected_reverse = [case.case_id for case in select_cases(reversed(cases), sample_size=5, seed=7)]
        self.assertEqual(selected_forward, selected_reverse)


class ExternalMetricTests(unittest.TestCase):
    def test_retrieval_metrics_distinguish_strict_and_fractional_recall(self):
        ranked = ["noise", "a", "b"]
        relevant = ["a", "b"]
        self.assertEqual(recall_any(ranked, relevant, 2), 1.0)
        self.assertEqual(recall_all(ranked, relevant, 2), 0.0)
        self.assertEqual(evidence_recall(ranked, relevant, 2), 0.5)
        self.assertEqual(recall_all(ranked, relevant, 3), 1.0)
        self.assertEqual(reciprocal_rank(ranked, relevant), 0.5)

    def test_mrr_is_labeled_and_truncated_at_the_declared_cutoff(self):
        row = score_case(
            case_id="mrr",
            category="ranking",
            ranked_document_ids=["noise", "target"],
            relevant_document_ids=["target"],
            expected_abstain=False,
            latency_seconds=0.1,
            k_values=(1,),
        )
        self.assertEqual(row["mrr@1"], 0.0)
        self.assertNotIn("mrr", row)

    def test_standard_and_upstream_longmemeval_ndcg_are_both_reported(self):
        standard = ndcg_at_k(["noise", "a"], ["a"], 2)
        upstream = upstream_longmemeval_ndcg_at_k(["noise", "a"], ["a"], 2)
        self.assertAlmostEqual(standard, 1 / math.log2(3))
        self.assertEqual(upstream, 1.0)

    def test_forbidden_exposure_and_abstention_are_explicit(self):
        row = score_case(
            case_id="x",
            category="safety",
            ranked_document_ids=["poison"],
            relevant_document_ids=[],
            forbidden_document_ids=["poison"],
            expected_abstain=True,
            latency_seconds=0.1,
            k_values=(1, 5),
        )
        self.assertFalse(row["predicted_abstain"])
        self.assertEqual(row["forbidden_exposure@1"], 1.0)

    def test_unscored_rows_do_not_contaminate_abstention_metrics(self):
        unscored = score_case(
            case_id="unscored",
            category="assistant-only",
            ranked_document_ids=[],
            relevant_document_ids=[],
            expected_abstain=False,
            latency_seconds=0.1,
            k_values=(1,),
        )
        abstention = score_case(
            case_id="abstain",
            category="abstention",
            ranked_document_ids=[],
            relevant_document_ids=[],
            expected_abstain=True,
            latency_seconds=0.1,
            k_values=(1,),
        )
        aggregate = aggregate_scores([unscored, abstention], k_values=(1,))
        self.assertEqual(aggregate["unscored_retrieval_cases"], 1)
        self.assertEqual(aggregate["abstention"]["scored_cases"], 1)
        self.assertEqual(aggregate["abstention"]["false_positive"], 0)
        self.assertEqual(aggregate["abstention"]["f1"], 1.0)


class ExternalEvaluationContractTests(unittest.TestCase):
    def test_autopsy_adapter_uses_static_reads_and_fixed_query_free_reranker_warmup(self):
        from autopsy_memory.evaluation.autopsy_adapter import AutopsyEvaluationAdapter

        model = mock.Mock()
        adapter = object.__new__(AutopsyEvaluationAdapter)
        adapter.config = {
            "reranker": {
                "enabled": True,
                "model": "reranker-model",
                "model_revision": "immutable-revision",
                "device": "cpu",
            }
        }
        adapter.cli = types.SimpleNamespace(
            FalkorToolShim=object(),
            reranker_provider_available=lambda _config: (True, None),
            load_cross_encoder=mock.Mock(return_value=model),
            build_consult_payload=mock.Mock(return_value={"route": "hybrid", "hits": []}),
        )
        adapter.graph = object()
        adapter.workspace = {"root_path": "/tmp/static-eval"}
        adapter._query_state_keys = set()
        adapter._stable_to_document = {}

        warmup = adapter._warm_reranker()
        result = adapter.retrieve(RetrievalRequest("private benchmark query", 5, "hybrid"))

        self.assertEqual(warmup["status"], "complete")
        self.assertTrue(warmup["query_free"])
        adapter.cli.load_cross_encoder.assert_called_once_with(
            "reranker-model", "cpu", "immutable-revision"
        )
        warmup_pairs = model.predict.call_args.args[0]
        self.assertNotIn("private benchmark query", json.dumps(warmup_pairs))
        self.assertFalse(
            adapter.cli.build_consult_payload.call_args.kwargs["record_access_telemetry"]
        )
        self.assertEqual(result.ranked_document_ids, ())

    def test_autopsy_query_state_reset_is_bounded_to_prior_hits(self):
        from autopsy_memory.evaluation.autopsy_adapter import AutopsyEvaluationAdapter

        class RecordingGraph:
            def __init__(self):
                self.calls = []

            def query(self, query, params=None):
                self.calls.append((query, params or {}))

        adapter = object.__new__(AutopsyEvaluationAdapter)
        adapter.graph = RecordingGraph()
        adapter._query_state_keys = {"memory:b", "memory:a"}

        adapter.reset_query_state()
        adapter.reset_query_state()

        self.assertEqual(len(adapter.graph.calls), 1)
        query, params = adapter.graph.calls[0]
        self.assertIn("MATCH (usage:MemoryUsage)", query)
        self.assertIn("usage.stable_key IN $stable_keys", query)
        self.assertNotIn("SET node.", query)
        self.assertEqual(params["stable_keys"], ["memory:a", "memory:b"])
        self.assertEqual(adapter._query_state_keys, set())

    def test_adapter_initialization_failure_restores_the_process_guard(self):
        from autopsy_memory.evaluation.autopsy_adapter import AutopsyEvaluationAdapter

        variable = "AUTOPSY_MEMORY_GUARD_DISABLED"
        previous = os.environ.get(variable)
        os.environ[variable] = "original-value"
        try:
            with patch.object(cli, "ensure_graph", side_effect=RuntimeError("synthetic startup failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic startup failure"):
                    AutopsyEvaluationAdapter()
            self.assertEqual(os.environ.get(variable), "original-value")
        finally:
            if previous is None:
                os.environ.pop(variable, None)
            else:
                os.environ[variable] = previous

    def test_runtime_and_latency_metadata_are_reproducible_fields(self):
        runtime = runtime_metadata()
        self.assertGreater(runtime["process_peak_rss_bytes"], 0)
        self.assertIn("autopsy_source_version", runtime)
        summary = latency_summary([1.0, 2.0, 3.0])
        self.assertEqual(summary["samples"], 3)
        self.assertEqual(summary["p50"], 2.0)

    def test_any_failed_safety_gate_disqualifies_a_comparable_run(self):
        baseline = {
            "official_dataset_artifact": True,
            "full_dataset": True,
            "no_case_errors": True,
            "requested_route_qualified": True,
            "metric_cutoffs_qualified": True,
            "upstream_temporal_policy_qualified": True,
            "upstream_representation_qualified": True,
            "model_revision_qualified": True,
            "forbidden_memory_gate_passed": True,
        }
        self.assertTrue(comparison_qualification_passes(**baseline))
        baseline["forbidden_memory_gate_passed"] = False
        self.assertFalse(comparison_qualification_passes(**baseline))

    def test_gold_is_removed_before_the_backend_boundary(self):
        case = EvaluationCase(
            "x",
            "q",
            "c",
            "cat",
            "query",
            (EvaluationDocument("d", "text"),),
            ("d",),
            forbidden_document_ids=("bad",),
            expected_abstain=True,
            answer="secret gold",
            metadata={"source_evidence_ids": ["d"], "scope": "repo", "repository_id": "/fixture/repo"},
        )
        sanitized = backend_case_without_gold(case)
        self.assertIsInstance(sanitized, EvaluationCorpus)
        self.assertEqual({field.name for field in fields(sanitized)}, {"documents", "relations"})
        serialized = asdict(sanitized)
        self.assertNotIn("query", serialized)
        self.assertNotIn("answer", serialized)
        self.assertNotIn("case_id", serialized)
        self.assertNotIn("corpus_id", serialized)
        self.assertNotIn("relevant_document_ids", serialized)
        self.assertNotIn("forbidden_document_ids", serialized)
        self.assertEqual(sanitized.documents[0].metadata, {})
        self.assertTrue(sanitized.documents[0].document_id.startswith("doc:"))
        self.assertNotEqual(sanitized.documents[0].document_id, case.documents[0].document_id)

    def test_source_document_metadata_is_removed_before_backend_ingestion(self):
        case = EvaluationCase(
            "x",
            "q",
            "c",
            "cat",
            "query",
            (
                EvaluationDocument(
                    "answer-bearing-session-id",
                    "ordinary corpus text",
                    session_id="answer-bearing-session-id",
                    metadata={
                        "source_session_id": "answer-bearing-session-id",
                        "source_ordinal": 7,
                        "repository_id": "/fixture/repo",
                    },
                ),
            ),
            ("answer-bearing-session-id",),
        )
        sanitized = backend_case_without_gold(case)
        self.assertEqual(sanitized.documents[0].metadata, {"repository_id": "/fixture/repo"})
        self.assertEqual(sanitized.documents[0].session_id, "")
        self.assertNotIn("answer-bearing-session-id", json.dumps(asdict(sanitized), sort_keys=True))

    def test_runner_sends_corpus_before_query_and_never_sends_gold_to_prepare(self):
        events = []

        class BoundarySpyAdapter:
            def __init__(self):
                self._documents = ()
                self._history = []
                self._manifest = {
                    "adapter_id": "boundary-spy",
                    "implementation": "test-only",
                    "track": "raw-retrieval",
                    "config": {},
                    "config_sha256": "2" * 64,
                    "package_pin": {"name": "test", "version": "1"},
                    "source_pin": {"kind": "test", "sha256": "3" * 64},
                    "execution": {"mode": "local-in-process", "local": True, "remote": False},
                    "cost": {"external_api_cost_usd": 0.0},
                    "retrieval_family": "lexical",
                    "semantic": False,
                }

            def prepare(self, corpus):
                events.append(("prepare", corpus))
                self.assert_corpus(corpus)
                self._documents = corpus.documents
                payload = {"documents": len(corpus.documents), "characters": 0, "seconds": 0.0}
                self._history.append(payload)
                return payload

            @staticmethod
            def assert_corpus(corpus):
                if not isinstance(corpus, EvaluationCorpus):
                    raise AssertionError(type(corpus))
                if {field.name for field in fields(corpus)} != {"documents", "relations"}:
                    raise AssertionError("unsafe preparation fields")

            def retrieve(self, request):
                events.append(("retrieve", request))
                return RetrievalResult(
                    ranked_document_ids=(self._documents[0].document_id,) if self._documents else (),
                    latency_seconds=0.0,
                    route="spy",
                    retrieval_reasons=(("spy",),) if self._documents else (),
                )

            def reset_query_state(self):
                return None

            def manifest(self):
                return dict(self._manifest)

            def capabilities(self):
                return dict(self._manifest)

            @property
            def ingestion_history(self):
                return list(self._history)

            def close(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _traceback):
                self.close()

        spy = BoundarySpyAdapter()
        with tempfile.TemporaryDirectory() as directory, patch(
            "autopsy_memory.evaluation.runner.create_evaluation_adapter",
            return_value=spy,
        ):
            predictions_path = Path(directory) / "predictions.jsonl"
            report = run_evaluation(
                dataset="coding-traces",
                dataset_path=CODING_FIXTURE,
                granularity="turn",
                representation="audited",
                route="lexical",
                k_values=(1, 5, 10),
                sample_size=1,
                seed=42,
                categories=None,
                repetitions=1,
                warmups=0,
                temporal_policy="dataset",
                predictions_path=predictions_path,
                adapter_id="boundary-spy",
            )
            row = load_prediction_rows(predictions_path)[0]
        self.assertFalse(report["case_errors"])
        self.assertFalse(report["qualification"]["ranking_stability_qualified"])
        self.assertEqual([kind for kind, _payload in events], ["prepare", "retrieve"])
        self.assertIsInstance(events[0][1], EvaluationCorpus)
        self.assertIsInstance(events[1][1], RetrievalRequest)
        self.assertEqual(row["adapter_id"], "boundary-spy")
        self.assertEqual(row["track"], "raw-retrieval")
        self.assertEqual(row["adapter_config_sha256"], "2" * 64)
        self.assertTrue(row["adapter_execution"]["local"])
        self.assertFalse(row["adapter_execution"]["remote"])
        self.assertEqual(row["adapter_cost"]["external_api_cost_usd"], 0.0)

    def test_builtin_bm25_runs_the_complete_coding_fixture_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            predictions_path = Path(directory) / "bm25.predictions.jsonl"
            report = run_evaluation(
                dataset="coding-traces",
                dataset_path=CODING_FIXTURE,
                granularity="turn",
                representation="audited",
                route="lexical",
                k_values=(1, 5, 10),
                sample_size=0,
                seed=42,
                categories=None,
                repetitions=2,
                warmups=0,
                temporal_policy="dataset",
                predictions_path=predictions_path,
                adapter_id="builtin-bm25",
            )
            rows = load_prediction_rows(predictions_path)
        self.assertFalse(report["case_errors"])
        self.assertEqual(report["adapter"]["adapter_id"], "builtin-bm25")
        self.assertEqual(report["adapter"]["implementation"], "autopsy-builtin-okapi-bm25-v1")
        self.assertEqual(report["adapter"]["retrieval_family"], "lexical")
        self.assertNotIn("bm25s", report["adapter"]["implementation"].lower())
        self.assertTrue(report["adapter"]["execution"]["local"])
        self.assertFalse(report["adapter"]["execution"]["remote"])
        self.assertEqual(report["cost"]["external_api_cost_usd"], 0.0)
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(row["adapter_id"] == "builtin-bm25" for row in rows))
        self.assertGreater(report["metrics"]["metrics"]["recall_any@10"], 0.0)

    def test_adapter_prepare_rejects_a_query_bearing_case(self):
        case = next(iter_cases("coding-traces", CODING_FIXTURE, granularity="turn"))
        adapter = BuiltinBM25EvaluationAdapter()
        with self.assertRaisesRegex(TypeError, "EvaluationCorpus"):
            adapter.prepare(case)  # type: ignore[arg-type]

    def test_gold_metadata_inside_a_document_is_rejected(self):
        case = EvaluationCase(
            "x",
            "q",
            "c",
            "cat",
            "query",
            (EvaluationDocument("d", "text", metadata={"has_answer": True}),),
            ("d",),
        )
        with self.assertRaisesRegex(ValueError, "Gold metadata"):
            audit_backend_leakage(case)

    def test_cli_parser_exposes_isolated_evaluation_actions(self):
        parser = cli.build_parser()
        run = parser.parse_args(
            [
                "evaluate",
                "run",
                "--dataset",
                "coding-traces",
                "--input",
                str(CODING_FIXTURE),
                "--route",
                "lexical",
            ]
        )
        self.assertEqual(run.evaluate_action, "run")
        self.assertEqual(run.temporal_policy, "dataset")
        self.assertEqual(run.representation, "audited")
        self.assertEqual(run.adapter, "autopsy")
        self.assertIs(run.func, cli.cmd_evaluate)

    def test_runner_rejects_invalid_iteration_controls_before_opening_data(self):
        base = {
            "dataset": "coding-traces",
            "dataset_path": "/does/not/exist.jsonl",
            "granularity": "turn",
            "representation": "audited",
            "route": "lexical",
            "k_values": (1,),
            "sample_size": 0,
            "seed": 42,
            "categories": None,
            "repetitions": 1,
            "warmups": 0,
            "temporal_policy": "dataset",
            "predictions_path": "/tmp/unused.jsonl",
        }
        for field, value in (("sample_size", -1), ("repetitions", 0), ("warmups", -1)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                run_evaluation(**{**base, field: value})

    @unittest.skipUnless(FALKORDBLITE_AVAILABLE, "FalkorDBLite runtime is not installed")
    def test_report_prediction_and_score_outputs_match_published_schemas(self):
        with tempfile.TemporaryDirectory() as directory:
            predictions_path = Path(directory) / "predictions.jsonl"
            report = run_evaluation(
                dataset="coding-traces",
                dataset_path=CODING_FIXTURE,
                granularity="turn",
                representation="audited",
                route="lexical",
                k_values=(1, 5, 10),
                sample_size=1,
                seed=42,
                categories=None,
                repetitions=2,
                warmups=0,
                temporal_policy="dataset",
                predictions_path=predictions_path,
            )
            rows = load_prediction_rows(predictions_path)
            score = score_predictions(
                dataset="coding-traces",
                dataset_path=CODING_FIXTURE,
                granularity="turn",
                representation="audited",
                predictions=rows,
                k_values=(1, 5, 10),
            )
            schema_dir = bundled_schema_dir()
            assert_top_level_schema(self, report, schema_dir / "report-v1.schema.json")
            assert_top_level_schema(self, rows[0], schema_dir / "retrieval-prediction-v1.schema.json")
            assert_top_level_schema(self, score, schema_dir / "score-report-v1.schema.json")
            self.assertTrue(report["qualification"]["ranking_stability_qualified"])
            self.assertIn("code_provenance_qualified", report["qualification"])
            self.assertEqual(len(report["runtime"]["source_tree_sha256"]), 64)
            self.assertEqual(
                report["qualification"]["code_provenance_qualified"],
                bool(report["runtime"]["git_commit"]) and report["runtime"]["git_dirty"] is False,
            )

    def test_run_rejects_report_prediction_path_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "shared.json"
            args = cli.build_parser().parse_args(
                [
                    "evaluate",
                    "run",
                    "--dataset",
                    "coding-traces",
                    "--input",
                    str(CODING_FIXTURE),
                    "--granularity",
                    "turn",
                    "--route",
                    "lexical",
                    "--sample-size",
                    "1",
                    "--output",
                    str(shared),
                    "--predictions",
                    str(shared),
                ]
            )
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
                args.func(args)
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(shared.exists())

    def test_run_rejects_invalid_input_report_alias_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset_path = Path(directory) / "invalid.jsonl"
            predictions_path = Path(directory) / "predictions.jsonl"
            dataset_path.write_text("", encoding="utf-8")
            args = cli.build_parser().parse_args(
                [
                    "evaluate",
                    "run",
                    "--dataset",
                    "coding-traces",
                    "--input",
                    str(dataset_path),
                    "--granularity",
                    "turn",
                    "--output",
                    str(dataset_path),
                    "--predictions",
                    str(predictions_path),
                ]
            )
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
                args.func(args)
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(dataset_path.read_text(encoding="utf-8"), "")
            self.assertFalse(predictions_path.exists())

    def test_validate_rejects_input_output_alias_without_modifying_input(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset_path = Path(directory) / "coding.jsonl"
            shutil.copyfile(CODING_FIXTURE, dataset_path)
            original = dataset_path.read_bytes()
            args = cli.build_parser().parse_args(
                [
                    "evaluate",
                    "validate",
                    "--dataset",
                    "coding-traces",
                    "--input",
                    str(dataset_path),
                    "--granularity",
                    "turn",
                    "--output",
                    str(dataset_path),
                ]
            )
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
                args.func(args)
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(dataset_path.read_bytes(), original)

    def test_score_requires_checksum_verification_unless_explicitly_overridden(self):
        sample = {
            "sample_id": "conv-test",
            "conversation": {
                "session_1_date_time": "1:00 pm on 8 May, 2023",
                "session_1": [{"speaker": "A", "dia_id": "D1:1", "text": "Alpha fact"}],
            },
            "qa": [{"question": "What fact?", "answer": "Alpha", "category": 1, "evidence": ["D1:1"]}],
        }
        with tempfile.TemporaryDirectory() as directory:
            dataset_path = Path(directory) / "modified-locomo.json"
            predictions_path = Path(directory) / "empty.jsonl"
            score_path = Path(directory) / "score.json"
            write_json(dataset_path, [sample])
            source_case = next(iter_cases("locomo", dataset_path, granularity="turn"))
            predictions_path.write_text(
                json.dumps(prediction_row(source_case, dataset_path)) + "\n",
                encoding="utf-8",
            )
            base = [
                "evaluate",
                "score",
                "--dataset",
                "locomo",
                "--input",
                str(dataset_path),
                "--granularity",
                "turn",
                "--predictions",
                str(predictions_path),
                "--output",
                str(score_path),
                "--k",
                "1,5,10",
            ]
            args = cli.build_parser().parse_args(base)
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
                args.func(args)
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(score_path.exists())

            opted_in = cli.build_parser().parse_args([*base, "--allow-unverified-dataset"])
            with redirect_stdout(io.StringIO()):
                opted_in.func(opted_in)
            self.assertEqual(json.loads(score_path.read_text(encoding="utf-8"))["status"], "complete")

    def test_independent_rescore_accepts_an_explicit_subset(self):
        first = next(iter_cases("coding-traces", CODING_FIXTURE, granularity="turn"))
        predictions = [prediction_row(first, CODING_FIXTURE)]
        payload = score_predictions(
            dataset="coding-traces",
            dataset_path=CODING_FIXTURE,
            granularity="turn",
            predictions=predictions,
            k_values=(1, 5),
        )
        integrity = payload["prediction_integrity"]
        self.assertTrue(integrity["valid"])
        self.assertFalse(integrity["full_dataset_complete"])
        self.assertEqual(integrity["matched"], 1)
        self.assertEqual(payload["schema"], SCORE_REPORT_SCHEMA)

    def test_independent_rescore_rejects_representation_or_digest_mismatch(self):
        first = next(iter_cases("coding-traces", CODING_FIXTURE, granularity="turn"))
        prediction = prediction_row(first, CODING_FIXTURE)
        prediction["representation"] = "upstream"
        with self.assertRaisesRegex(ValueError, "configuration mismatch"):
            score_predictions(
                dataset="coding-traces",
                dataset_path=CODING_FIXTURE,
                granularity="turn",
                predictions=[prediction],
                k_values=(1,),
            )
        prediction["representation"] = "audited"
        prediction["dataset_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "configuration mismatch"):
            score_predictions(
                dataset="coding-traces",
                dataset_path=CODING_FIXTURE,
                granularity="turn",
                predictions=[prediction],
                k_values=(1,),
            )

    def test_independent_rescore_rejects_cutoffs_beyond_retrieval_depth(self):
        first = next(iter_cases("coding-traces", CODING_FIXTURE, granularity="turn"))
        prediction = prediction_row(first, CODING_FIXTURE, retrieval_limit=1)
        with self.assertRaisesRegex(ValueError, "cannot support requested cutoff 5"):
            score_predictions(
                dataset="coding-traces",
                dataset_path=CODING_FIXTURE,
                granularity="turn",
                predictions=[prediction],
                k_values=(1, 5),
            )

    def test_prediction_integrity_rejects_depth_overflow_and_empty_files(self):
        first = next(iter_cases("coding-traces", CODING_FIXTURE, granularity="turn"))
        overflow = prediction_row(
            first,
            CODING_FIXTURE,
            ranked_document_ids=[document.document_id for document in first.documents[:2]],
            retrieval_limit=1,
        )
        with self.assertRaisesRegex(ValueError, "more ranked ids"):
            score_predictions(
                dataset="coding-traces",
                dataset_path=CODING_FIXTURE,
                granularity="turn",
                predictions=[overflow],
                k_values=(1,),
            )

    def test_prediction_loader_rejects_duplicate_keys_and_nonstandard_numbers(self):
        first = next(iter_cases("coding-traces", CODING_FIXTURE, granularity="turn"))
        valid = json.dumps(prediction_row(first, CODING_FIXTURE), separators=(",", ":"))
        invalid_rows = (
            '{"case_id":"first","case_id":"second"}',
            valid.replace('"latency_seconds":0.01', '"latency_seconds":NaN'),
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, row in enumerate(invalid_rows):
                with self.subTest(index=index):
                    path = Path(directory) / f"invalid-{index}.jsonl"
                    path.write_text(row + "\n", encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_prediction_rows(path)
        with self.assertRaisesRegex(ValueError, "At least one prediction"):
            score_predictions(
                dataset="coding-traces",
                dataset_path=CODING_FIXTURE,
                granularity="turn",
                predictions=[],
                k_values=(1,),
            )


@unittest.skipUnless(FALKORDBLITE_AVAILABLE, "FalkorDBLite runtime is not installed")
class IsolatedAutopsyAdapterTests(unittest.TestCase):
    def test_usage_sidecar_access_and_reset_preserve_fulltext_scores(self):
        from autopsy_memory.evaluation.autopsy_adapter import AutopsyEvaluationAdapter

        with AutopsyEvaluationAdapter() as adapter:
            adapter.graph.query(
                """
                CREATE (:MemoryNode:SemanticItem:MemoryNote {
                  stable_key: 'memory:a', kind: 'memory_note', label: 'Deterministic ranking alpha',
                  summary: 'deterministic ranking token', detail_content: 'deterministic ranking token alpha',
                  search_text: 'deterministic ranking token alpha', created_at: '2026-01-01T00:00:00Z',
                  updated_at: '2026-01-01T00:00:00Z', source_kind: 'unit',
                  access_count: 7, last_accessed_at: '2026-01-02T00:00:00Z',
                  last_access_source: 'legacy'
                })
                CREATE (:MemoryNode:SemanticItem:MemoryNote {
                  stable_key: 'memory:b', kind: 'memory_note', label: 'Deterministic ranking beta',
                  summary: 'deterministic ranking token', detail_content: 'deterministic ranking token beta',
                  search_text: 'deterministic ranking token beta', created_at: '2026-01-01T00:00:00Z',
                  updated_at: '2026-01-01T00:00:00Z', source_kind: 'unit'
                })
                """
            )
            score_query = """
                CALL db.idx.fulltext.queryNodes('SemanticItem', 'deterministic ranking')
                YIELD node, score
                RETURN node.stable_key, score
                ORDER BY node.stable_key ASC
                """
            before = adapter.graph.query(score_query).result_set
            legacy_usage = cli.fetch_memory_usage(adapter.graph, ["memory:a"])

            access = cli.record_memory_access(
                adapter.graph,
                ["memory:a"],
                source="integration-test",
                query="deterministic ranking",
                timestamp="2026-07-11T00:00:00Z",
            )
            after_access = adapter.graph.query(score_query).result_set
            migrated_usage = cli.fetch_memory_usage(adapter.graph, ["memory:a"])
            adapter._query_state_keys = {"memory:a"}
            adapter.reset_query_state()
            after_reset = adapter.graph.query(score_query).result_set
            stored = adapter.graph.query(
                """
                MATCH (node:MemoryNode {stable_key: 'memory:a'})-[:HAS_USAGE]->(usage:MemoryUsage)
                RETURN node.access_count, usage.access_count, usage.last_accessed_at
                """
            ).result_set

            self.assertEqual(access["updated"], 1)
            self.assertEqual(legacy_usage["memory:a"]["access_count"], 7)
            self.assertEqual(migrated_usage["memory:a"]["access_count"], 8)
            self.assertEqual(before, after_access)
            self.assertEqual(before, after_reset)
            self.assertEqual(stored, [[7, 0, ""]])

    def test_keep_store_preserves_an_automatically_allocated_directory(self):
        from autopsy_memory.evaluation.autopsy_adapter import AutopsyEvaluationAdapter

        adapter = AutopsyEvaluationAdapter(keep_store=True)
        root = adapter.root
        try:
            adapter.close()
            self.assertTrue(root.is_dir())
            self.assertTrue((root / "evaluation.db").exists())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_identical_corpus_is_reused_and_changed_content_is_reindexed(self):
        from autopsy_memory.evaluation.autopsy_adapter import AutopsyEvaluationAdapter

        first = EvaluationCase("x", "q1", "same", "cat", "query", (EvaluationDocument("d", "one"),), ("d",))
        changed = EvaluationCase("x", "q2", "same", "cat", "query", (EvaluationDocument("d", "two"),), ("d",))
        with AutopsyEvaluationAdapter() as adapter:
            corpus = backend_case_without_gold(first)
            self.assertFalse(adapter.prepare(corpus)["reused"])
            self.assertTrue(adapter.prepare(corpus)["reused"])
            self.assertFalse(adapter.prepare(backend_case_without_gold(changed))["reused"])

    def test_real_retrieval_is_isolated_and_reports_full_vector_coverage(self):
        from autopsy_memory.evaluation.autopsy_adapter import AutopsyEvaluationAdapter

        before = set(cli._FALKORDB_LITE_CLIENTS)
        case = EvaluationCase(
            dataset="fixture",
            case_id="exact",
            corpus_id="fixture:exact",
            category="exact",
            query="native arm64 toolchain",
            documents=(
                EvaluationDocument("target", "Switching to the native arm64 toolchain fixed packaging."),
                EvaluationDocument("noise", "The Linux cache was unchanged."),
            ),
            relevant_document_ids=("target",),
        )
        with AutopsyEvaluationAdapter() as adapter:
            corpus = backend_case_without_gold(case)
            adapter.prepare(corpus)
            result = adapter.retrieve(RetrievalRequest(case.query, 5, "lexical"))
            capabilities = adapter.capabilities()
            self.assertEqual(result.ranked_document_ids[0], corpus.documents[0].document_id)
            self.assertEqual(capabilities["vector_coverage"], 1.0)
            self.assertFalse(capabilities["production_worker_used"])
            self.assertGreater(capabilities["store_bytes"], 0)
            self.assertTrue(capabilities["embedding_model_loaded"])
            self.assertEqual(
                capabilities["embedding_model_revision"],
                adapter.config["model_revision"],
            )
            self.assertIn("reranker_model_revision", capabilities)
            self.assertEqual(capabilities["adapter_id"], "autopsy")
        self.assertEqual(set(cli._FALKORDB_LITE_CLIENTS), before)

    def test_answer_bearing_source_ids_never_enter_the_search_index(self):
        from autopsy_memory.evaluation.autopsy_adapter import AutopsyEvaluationAdapter

        secret_id = "answer-secret-needle"
        case = EvaluationCase(
            dataset="fixture",
            case_id="identifier-leakage",
            corpus_id="fixture:identifier-leakage",
            category="leakage",
            query=secret_id,
            documents=(
                EvaluationDocument(
                    secret_id,
                    "The ordinary discussion covered gardening and rainfall.",
                    session_id=secret_id,
                    metadata={"source_session_id": secret_id, "source_ordinal": 1},
                ),
                EvaluationDocument("ordinary-id", "A second ordinary discussion covered irrigation."),
            ),
            relevant_document_ids=(secret_id,),
            relations=(
                EvaluationRelation(
                    secret_id,
                    "ordinary-id",
                    "depends_on",
                    fact_text=f"{secret_id} depends on ordinary-id",
                ),
            ),
        )
        with AutopsyEvaluationAdapter() as adapter:
            adapter.prepare(backend_case_without_gold(case))
            result = adapter.retrieve(RetrievalRequest(case.query, 5, "lexical"))
            self.assertEqual(result.ranked_document_ids, ())
            stored = adapter.graph.query(
                "MATCH (node:SemanticItem) "
                "RETURN node.stable_key, node.label, node.summary, "
                "node.detail_content, node.search_text, node.memory_metadata"
            ).result_set
            serialized = json.dumps(stored, sort_keys=True)
            self.assertNotIn(secret_id, serialized)
            stored_edges = adapter.graph.query(
                "MATCH ()-[edge]->() RETURN edge.fact_text, edge.predicate"
            ).result_set
            self.assertNotIn(secret_id, json.dumps(stored_edges, sort_keys=True))

    def test_repo_scope_does_not_leak_colliding_memory(self):
        from autopsy_memory.evaluation.autopsy_adapter import AutopsyEvaluationAdapter

        cases = {
            case.case_id: case
            for case in iter_cases("coding-traces", CODING_FIXTURE, granularity="turn")
            if case.case_id.startswith("repo-scope-runtime-")
        }
        with AutopsyEvaluationAdapter() as adapter:
            case_a = cases["repo-scope-runtime-a"]
            case_b = cases["repo-scope-runtime-b"]
            adapter.prepare(backend_case_without_gold(case_a))
            result_a = adapter.retrieve(
                RetrievalRequest(
                    case_a.query,
                    5,
                    "lexical",
                    scope="repo",
                    repository_id=str(case_a.metadata.get("repository_id") or ""),
                )
            )
            adapter.prepare(backend_case_without_gold(case_b))
            result_b = adapter.retrieve(
                RetrievalRequest(
                    case_b.query,
                    5,
                    "lexical",
                    scope="repo",
                    repository_id=str(case_b.metadata.get("repository_id") or ""),
                )
            )
            self.assertNotIn("evt-s2", result_a.ranked_document_ids)
            self.assertNotIn("evt-s1", result_b.ranked_document_ids)


if __name__ == "__main__":
    unittest.main()
