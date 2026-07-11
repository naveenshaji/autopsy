from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autopsy_memory.evaluation.datasets import EVALUATION_SCHEMA_FILENAMES, export_schemas
from autopsy_memory.evaluation.e2e import (
    ANSWER_PREDICTION_SCHEMA,
    COMMON_ANSWER_TRACK,
    EXTRACTED_RETRIEVAL_TRACK,
    DeterministicExtractiveAnswerGenerator,
    DeterministicSentenceExtractor,
    answer_exact_match,
    answer_token_f1,
    extraction_artifact_row,
    load_answer_prediction_rows,
    run_end_to_end_evaluation,
    score_answer_predictions,
    validate_answer_prediction_row,
    validate_extraction_artifact_row,
)
from autopsy_memory.evaluation.models import (
    AnswerGenerationRequest,
    EvaluationCorpus,
    EvaluationDocument,
    RetrievedContext,
)


def component_provenance(component_id: str, config_sha256: str) -> dict:
    return {
        "component_id": component_id,
        "implementation": f"{component_id}-test",
        "config_sha256": config_sha256,
        "package_pin": {"name": "test", "version": "1"},
        "source_pin": {"kind": "test", "sha256": "f" * 64},
        "execution": {"local": True, "remote": False},
        "cost": {"external_api_cost_usd": 0.0},
    }


class DeterministicExtractionTests(unittest.TestCase):
    def test_extractor_is_deterministic_query_free_and_source_attributed(self):
        corpus = EvaluationCorpus(
            (
                EvaluationDocument(
                    "d1",
                    "2025-01-01T00:00:00Z\nassistant: CI requires Node.js 22. CI requires Node.js 22.",
                    metadata={"repository_id": "/fixture/repo"},
                ),
                EvaluationDocument(
                    "d2",
                    "assistant: CI requires Node.js 22.",
                    metadata={"repository_id": "/fixture/repo"},
                ),
            )
        )
        extractor = DeterministicSentenceExtractor()
        first = extractor.extract(corpus)
        second = extractor.extract(corpus)
        self.assertEqual(first.corpus, second.corpus)
        self.assertEqual(first.attributions, second.attributions)
        self.assertEqual(len(first.corpus.documents), 1)
        self.assertEqual(first.attributions[0].source_document_ids, ("d1", "d2"))
        self.assertNotIn("query", extractor.manifest()["config"])
        self.assertFalse(extractor.manifest()["config"]["query_access"])
        self.assertFalse(extractor.manifest()["config"]["gold_access"])

    def test_extraction_artifact_contains_sources_but_no_query_or_gold(self):
        corpus = EvaluationCorpus((EvaluationDocument("source", "The formatter is Ruff with 100 columns."),))
        extractor = DeterministicSentenceExtractor()
        result = extractor.extract(corpus)
        row = extraction_artifact_row(
            dataset="coding-traces",
            dataset_sha256="0" * 64,
            granularity="turn",
            representation="audited",
            corpus_id="corpus",
            input_fingerprint="1" * 64,
            result=result,
            extractor_manifest=extractor.manifest(),
        )
        self.assertIs(validate_extraction_artifact_row(row), row)
        encoded = json.dumps(row)
        self.assertNotIn('"query"', encoded)
        self.assertNotIn('"answer"', encoded)
        self.assertEqual(row["memories"][0]["source_document_ids"], ["source"])


class DeterministicAnswerTests(unittest.TestCase):
    def test_generator_uses_only_query_and_ranked_context(self):
        request = AnswerGenerationRequest(
            "Which runtime does CI require?",
            (
                RetrievedContext("noise", "The cache lasts seven days.", 1, ("d2",)),
                RetrievedContext("fact", "assistant: CI requires Node.js 22.", 2, ("d1",)),
            ),
        )
        generator = DeterministicExtractiveAnswerGenerator()
        result = generator.generate(request)
        self.assertEqual(result.answer, "CI requires Node.js 22.")
        self.assertEqual(result.source_memory_ids, ("fact",))
        self.assertFalse(result.abstained)
        self.assertFalse(generator.manifest()["config"]["gold_access"])

    def test_deterministic_answer_metrics_normalize_articles_and_tokens(self):
        self.assertEqual(answer_exact_match("The Node.js 22", "node js 22"), 1.0)
        self.assertGreater(answer_token_f1("Node.js 22 is mandatory", "Node 22"), 0.5)
        self.assertEqual(answer_token_f1("Ruff 100", "Black 88"), 0.0)

    def test_answer_artifact_rejects_gold_fields(self):
        row = {
            "schema": ANSWER_PREDICTION_SCHEMA,
            "dataset": "coding-traces",
            "dataset_sha256": "0" * 64,
            "granularity": "turn",
            "representation": "audited",
            "adapter_id": "builtin-bm25",
            "adapter_config_sha256": "3" * 64,
            "track": COMMON_ANSWER_TRACK,
            "extractor_id": "deterministic-sentence-v1",
            "extractor_config_sha256": "1" * 64,
            "generator_id": "deterministic-extractive-v1",
            "generator_config_sha256": "2" * 64,
            "adapter_provenance": component_provenance("builtin-bm25", "3" * 64),
            "extractor_provenance": component_provenance("deterministic-sentence-v1", "1" * 64),
            "generator_provenance": component_provenance("deterministic-extractive-v1", "2" * 64),
            "case_id": "case",
            "corpus_id": "corpus",
            "category": "fact",
            "query": "Which runtime?",
            "answer": "Node.js 22.",
            "abstained": False,
            "ranked_memory_ids": ["memory"],
            "source_memory_ids": ["memory"],
            "source_document_ids": ["document"],
            "retrieval_latency_seconds": 0.1,
            "generation_latency_seconds": 0.01,
            "diagnostics": {},
        }
        self.assertIs(validate_answer_prediction_row(row), row)
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            validate_answer_prediction_row({**row, "gold_answer": "Node.js 22."})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.jsonl"
            encoded = json.dumps(row, separators=(",", ":"))
            duplicate = encoded[:-1] + ',"case_id":"duplicate"}'
            path.write_text(duplicate + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate evaluation artifact JSON key"):
                load_answer_prediction_rows(path)
            path.write_text(encoded.replace("0.1", "NaN", 1) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Non-standard JSON constant"):
                load_answer_prediction_rows(path)


class EndToEndEvaluationTests(unittest.TestCase):
    def test_cli_requires_an_explicit_named_track_value(self):
        from autopsy_memory import cli

        parser = cli.build_parser()
        run = parser.parse_args(
            [
                "evaluate", "run", "--dataset", "coding-traces", "--input", "fixture.jsonl",
                "--track", "common-answer", "--adapter", "builtin-bm25",
            ]
        )
        self.assertEqual(run.track, "common-answer")
        self.assertEqual(run.extractor, "deterministic-sentence-v1")
        self.assertEqual(run.generator, "deterministic-extractive-v1")
        score = parser.parse_args(
            [
                "evaluate", "score", "--dataset", "coding-traces", "--input", "fixture.jsonl",
                "--predictions", "answers.jsonl", "--track", "common-answer",
            ]
        )
        self.assertEqual(score.track, "common-answer")

    def test_common_answer_track_runs_offline_and_writes_separate_artifacts(self):
        fixture = {
            "schema": "autopsy-coding-memory-case/v1",
            "case_id": "runtime",
            "category": "single-hop",
            "query": "Which JavaScript runtime does CI require?",
            "documents": [
                {"id": "target", "text": "The JavaScript runtime CI requires is Node.js 22."},
                {"id": "noise", "text": "The Python formatter is Ruff with 100 columns."},
            ],
            "relevant_document_ids": ["target"],
            "answer": "The JavaScript runtime CI requires is Node.js 22.",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset_path = root / "fixture.jsonl"
            dataset_path.write_text(json.dumps(fixture) + "\n", encoding="utf-8")
            retrieval_path = root / "retrieval.jsonl"
            extraction_path = root / "extraction.jsonl"
            answer_path = root / "answers.jsonl"
            report = run_end_to_end_evaluation(
                track=COMMON_ANSWER_TRACK,
                dataset="coding-traces",
                dataset_path=dataset_path,
                granularity="turn",
                representation="audited",
                route="lexical",
                k_values=(1,),
                sample_size=0,
                seed=42,
                categories=None,
                repetitions=2,
                warmups=1,
                temporal_policy="dataset",
                predictions_path=retrieval_path,
                extraction_artifacts_path=extraction_path,
                answers_path=answer_path,
                adapter_id="builtin-bm25",
            )
            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["track"], COMMON_ANSWER_TRACK)
            self.assertEqual(report["extraction"]["memory_count"], 2)
            self.assertEqual(report["answer_metrics"]["answer_coverage"], 1.0)
            self.assertEqual(report["answer_metrics"]["exact_match"], 1.0)
            self.assertEqual(report["answer_metrics"]["answer_accuracy_exact_match"], 1.0)
            self.assertEqual(report["generator"]["component_id"], "deterministic-extractive-v1")
            self.assertTrue(report["qualification"]["ranking_stability_qualified"])
            self.assertEqual(report["ranking_instability_cases"], 0)
            self.assertGreater(report["retrieval_channel_counts"]["bm25"], 0)
            report_schema = json.loads(
                (Path("src/autopsy_memory/evaluation/schemas/end-to-end-report-v1.schema.json")).read_text(encoding="utf-8")
            )
            self.assertTrue(set(report_schema["required"]).issubset(report))
            self.assertTrue(set(report).issubset(report_schema["properties"]))
            self.assertEqual(len(load_answer_prediction_rows(answer_path)), 1)
            extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
            self.assertNotIn("query", extraction)
            self.assertNotIn("answer", extraction)
            answer = json.loads(answer_path.read_text(encoding="utf-8"))
            self.assertNotIn("gold_answer", answer)
            self.assertEqual(answer["source_document_ids"], ["target"])
            answer_schema = json.loads(
                Path("src/autopsy_memory/evaluation/schemas/answer-prediction-v1.schema.json").read_text(encoding="utf-8")
            )
            self.assertTrue(set(answer_schema["required"]).issubset(answer))
            self.assertTrue(set(answer).issubset(answer_schema["properties"]))
            retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
            self.assertEqual(retrieval["repetitions"], 2)
            self.assertEqual(retrieval["retrieval_reasons"], [["bm25"]])
            self.assertTrue(retrieval["diagnostics"]["rankings_stable"])

    def test_streaming_extraction_metrics_survive_bounded_runtime_cache(self):
        fixtures = [
            {
                "schema": "autopsy-coding-memory-case/v1",
                "case_id": f"case-{index}",
                "category": "single-hop",
                "query": f"Which value belongs to item {index}?",
                "documents": [{"id": f"document-{index}", "text": f"Item {index} uses value token-{index}."}],
                "relevant_document_ids": [f"document-{index}"],
            }
            for index in range(18)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset_path = root / "fixtures.jsonl"
            dataset_path.write_text("".join(json.dumps(row) + "\n" for row in fixtures), encoding="utf-8")
            report = run_end_to_end_evaluation(
                track=EXTRACTED_RETRIEVAL_TRACK,
                dataset="coding-traces",
                dataset_path=dataset_path,
                granularity="turn",
                representation="audited",
                route="lexical",
                k_values=(1,),
                sample_size=0,
                seed=42,
                categories=None,
                temporal_policy="dataset",
                predictions_path=root / "retrieval.jsonl",
                extraction_artifacts_path=root / "extraction.jsonl",
                adapter_id="builtin-bm25",
            )
            self.assertEqual(report["extraction"]["corpora"], 18)
            self.assertEqual(report["artifacts"]["extraction_rows"], 18)
            self.assertEqual(report["artifacts"]["retrieval_prediction_rows"], 18)

    def test_longmemeval_score_marks_official_llm_judge_unsupported(self):
        dataset = [
            {
                "question_id": "q1",
                "question": "Which runtime is required?",
                "answer": "Node.js 22",
                "question_type": "single-session-user",
                "question_date": "2025/02/01",
                "haystack_session_ids": ["s1"],
                "haystack_dates": ["2025/01/01"],
                "answer_session_ids": ["s1"],
                "haystack_sessions": [[{"role": "user", "content": "CI requires Node.js 22", "has_answer": True}]],
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long.json"
            path.write_text(json.dumps(dataset), encoding="utf-8")
            provenance_sha = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            row = {
                "schema": ANSWER_PREDICTION_SCHEMA,
                "dataset": "longmemeval-s",
                "dataset_sha256": provenance_sha,
                "granularity": "session",
                "representation": "audited",
                "adapter_id": "builtin-bm25",
                "adapter_config_sha256": "3" * 64,
                "track": COMMON_ANSWER_TRACK,
                "extractor_id": "deterministic-sentence-v1",
                "extractor_config_sha256": "1" * 64,
                "generator_id": "deterministic-extractive-v1",
                "generator_config_sha256": "2" * 64,
                "adapter_provenance": component_provenance("builtin-bm25", "3" * 64),
                "extractor_provenance": component_provenance("deterministic-sentence-v1", "1" * 64),
                "generator_provenance": component_provenance("deterministic-extractive-v1", "2" * 64),
                "case_id": "q1",
                "corpus_id": "longmemeval-s:q1:session",
                "category": "single-session-user",
                "query": "Which runtime is required?",
                "answer": "Node.js 22",
                "abstained": False,
                "ranked_memory_ids": ["m1"],
                "source_memory_ids": ["m1"],
                "source_document_ids": ["s1"],
                "retrieval_latency_seconds": 0.1,
                "generation_latency_seconds": 0.01,
                "diagnostics": {},
            }
            score = score_answer_predictions(
                dataset="longmemeval-s",
                dataset_path=path,
                granularity="session",
                representation="audited",
                predictions=[row],
            )
            unsupported = score["metrics"]["unsupported_official_metrics"]
            self.assertEqual(unsupported[0]["metric"], "official_llm_judge_accuracy")
            self.assertEqual(unsupported[0]["status"], "unsupported")
            self.assertIsNone(unsupported[0]["value"])
            self.assertEqual(score["metrics"]["exact_match"], 1.0)
            tampered = json.loads(json.dumps(row))
            tampered["generator_provenance"]["source_pin"]["sha256"] = "e" * 64
            with self.assertRaisesRegex(ValueError, "mixes adapter/extractor/generator configurations"):
                score_answer_predictions(
                    dataset="longmemeval-s",
                    dataset_path=path,
                    granularity="session",
                    representation="audited",
                    predictions=[row, tampered],
                )

    def test_all_evaluation_schemas_export(self):
        self.assertEqual(len(EVALUATION_SCHEMA_FILENAMES), 8)
        with tempfile.TemporaryDirectory() as directory:
            payload = export_schemas(directory)
            self.assertEqual(payload["written"], 8)
            self.assertEqual({path.name for path in Path(directory).glob("*.schema.json")}, EVALUATION_SCHEMA_FILENAMES)


if __name__ == "__main__":
    unittest.main()
