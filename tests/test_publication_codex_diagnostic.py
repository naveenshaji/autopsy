from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path

from autopsy_memory.evaluation.models import EvaluationCase, EvaluationDocument


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "evaluation" / "publication" / "raw-retrieval-v1" / "codex_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("autopsy_publication_codex_diagnostic", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def case(
    dataset: str,
    case_id: str,
    category: str,
    *,
    abstain: bool = False,
    document_id: str = "answer_secret_session",
) -> EvaluationCase:
    return EvaluationCase(
        dataset=dataset,
        case_id=case_id,
        corpus_id=f"private:{case_id}",
        category=category,
        query=f"Question for {case_id.replace('_abs', '')}?",
        documents=(EvaluationDocument(document_id, "User said the supporting fact.", timestamp="2024-01-01T00:00:00Z"),),
        relevant_document_ids=() if abstain else (document_id,),
        expected_abstain=abstain,
        answer="The supporting fact.",
        as_of="2024-02-01T00:00:00Z",
    )


def prediction(item: EvaluationCase) -> dict:
    return {
        "dataset": item.dataset,
        "case_id": item.case_id,
        "corpus_id": item.corpus_id,
        "category": item.category,
        "query": item.query,
        "track": "raw-retrieval",
        "ranked_document_ids": [item.documents[0].document_id],
    }


class CodexDiagnosticTests(unittest.TestCase):
    def test_publication_prompt_selection_and_schema_hashes_are_frozen(self) -> None:
        diagnostic.assert_frozen_definitions()
        self.assertEqual(
            diagnostic.SELECTION_POLICY_SHA256,
            "28d4180814cbd0acf4278cd8d132fffa9e16238674d7599dbfb0d52086c67f30",
        )
        schema_dir = SCRIPT.parent / "schemas"
        self.assertEqual(
            json.loads((schema_dir / "codex-answer-output-v1.schema.json").read_text()),
            diagnostic.ANSWER_OUTPUT_JSON_SCHEMA,
        )
        self.assertEqual(
            json.loads((schema_dir / "codex-judge-output-v1.schema.json").read_text()),
            diagnostic.JUDGE_OUTPUT_JSON_SCHEMA,
        )

    def test_frozen_selection_is_exact_and_deterministic(self) -> None:
        locomo = [
            case("locomo", f"{category}:{index}", category, abstain=category == "adversarial-abstention")
            for category in diagnostic.LOCOMO_CATEGORIES
            for index in range(12)
        ]
        longmem = [
            case("longmemeval-s", f"{category}:answer:{index}", category)
            for category in diagnostic.LONGMEM_CATEGORIES
            for index in range(8)
        ]
        for category, count in zip(diagnostic.LONGMEM_CATEGORIES, (6, 12, 0, 0, 6, 6)):
            longmem.extend(
                case("longmemeval-s", f"{category}:abs:{index}_abs", category, abstain=True)
                for index in range(count)
            )
        first = diagnostic.select_diagnostic_cases({"locomo": locomo, "longmemeval-s": longmem})
        second = diagnostic.select_diagnostic_cases({"locomo": list(reversed(locomo)), "longmemeval-s": list(reversed(longmem))})
        self.assertEqual([(item.dataset, item.case_id) for item in first], [(item.dataset, item.case_id) for item in second])
        self.assertEqual(len(first), 110)
        self.assertEqual(sum(item.dataset == "locomo" for item in first), 50)
        self.assertEqual(sum(item.dataset == "longmemeval-s" and item.expected_abstain for item in first), 30)

    def test_answer_boundary_uses_only_opaque_handles_and_allowed_fields(self) -> None:
        item = case("longmemeval-s", "question_secret_abs", "multi-session")
        answer_case, private = diagnostic.build_prepared_case(item, prediction(item), b"x" * 32)
        payload = diagnostic.validate_answer_input({"schema": diagnostic.ANSWER_INPUT_SCHEMA, "cases": [answer_case]})
        serialized = diagnostic.canonical_json(payload)
        self.assertNotIn(item.case_id, serialized)
        self.assertNotIn(item.corpus_id, serialized)
        self.assertNotIn(item.documents[0].document_id, serialized)
        self.assertNotIn(item.category, serialized)
        self.assertNotIn(item.answer, serialized)
        self.assertRegex(answer_case["case_handle"], r"^Q[0-9a-f]{24}$")
        self.assertEqual(answer_case["contexts"][0]["context_handle"], "C001")
        self.assertEqual(private["case_id"], item.case_id)

    def test_answer_input_rejects_unknown_gold_field(self) -> None:
        payload = {
            "schema": diagnostic.ANSWER_INPUT_SCHEMA,
            "cases": [
                {
                    "case_handle": "Q1",
                    "question": "What?",
                    "question_date": "",
                    "contexts": [],
                    "expected_abstain": True,
                }
            ],
        }
        with self.assertRaises(diagnostic.DiagnosticError):
            diagnostic.validate_answer_input(payload)

    def test_answer_output_is_exact_and_citations_cannot_cross_cases(self) -> None:
        answer_input = {
            "schema": diagnostic.ANSWER_INPUT_SCHEMA,
            "cases": [
                {
                    "case_handle": "Q1",
                    "question": "What?",
                    "question_date": "",
                    "contexts": [{"context_handle": "C001", "rank": 1, "timestamp": "", "text": "Fact"}],
                }
            ],
        }
        diagnostic.validate_answer_output(
            {
                "schema": diagnostic.ANSWER_OUTPUT_SCHEMA,
                "answers": [{"case_handle": "Q1", "answer": "Fact", "abstained": False, "cited_context_handles": ["C001"]}],
            },
            answer_input,
        )
        with self.assertRaises(diagnostic.DiagnosticError):
            diagnostic.validate_answer_output(
                {
                    "schema": diagnostic.ANSWER_OUTPUT_SCHEMA,
                    "answers": [{"case_handle": "Q1", "answer": "Fact", "abstained": False, "cited_context_handles": ["C999"]}],
                },
                answer_input,
            )

    def test_environment_removes_api_credentials_and_command_disables_tools(self) -> None:
        environment, removed = diagnostic.sanitized_codex_environment(
            {
                "PATH": os.environ.get("PATH", ""),
                "OPENAI_API_KEY": "paid",
                "CODEX_API_KEY": "paid",
                "SOME_ACCESS_TOKEN": "secret",
            },
            Path("/tmp/isolated-codex-home"),
        )
        self.assertEqual(set(removed), {"OPENAI_API_KEY", "CODEX_API_KEY", "SOME_ACCESS_TOKEN"})
        self.assertNotIn("OPENAI_API_KEY", environment)
        command = diagnostic.codex_exec_command(
            "codex",
            model="gpt-5.4-mini",
            reasoning_effort="xhigh",
            work_dir=Path("/tmp/work"),
            output_schema=Path("/tmp/schema"),
            output_message=Path("/tmp/output"),
        )
        command_text = " ".join(command)
        self.assertIn('forced_login_method="chatgpt"', command)
        self.assertIn('web_search="disabled"', command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ephemeral", command)
        for feature in diagnostic.DISABLED_FEATURES:
            self.assertIn(f"--disable {feature}", command_text)

    def test_aggregate_scores_keeps_datasets_separate_and_reports_judge_sensitivity(self) -> None:
        private = {
            "Q1": {
                "dataset": "locomo", "category": "single-hop", "expected_abstain": False,
                "reference_answer": "blue", "question": "color?",
            },
            "Q2": {
                "dataset": "longmemeval-s", "category": "multi-session", "expected_abstain": True,
                "reference_answer": "unanswerable", "question": "unknown?",
            },
        }
        answers = {
            "Q1": {"answer": "blue", "abstained": False},
            "Q2": {"answer": "", "abstained": True},
        }
        metrics = diagnostic.aggregate_diagnostic_scores(private, answers, [{"Q1": True, "Q2": True}, {"Q1": False, "Q2": True}])
        self.assertEqual(set(metrics["by_dataset"]), {"locomo", "longmemeval-s"})
        self.assertEqual(metrics["by_dataset"]["locomo"]["exact_match"], 1.0)
        self.assertEqual(metrics["combined_unweighted_diagnostic"]["judge_unanimous_agreement"], 0.5)

    def test_parser_exposes_all_resumable_phases(self) -> None:
        parser = diagnostic.build_parser()
        for phase in ("prepare", "answer", "judge", "score", "status", "resume"):
            with self.subTest(phase=phase):
                if phase == "prepare":
                    args = parser.parse_args(
                        [
                            phase, "--run-dir", "run", "--locomo-data", "l.json",
                            "--locomo-predictions", "lp.jsonl", "--longmemeval-data", "m.json",
                            "--longmemeval-predictions", "mp.jsonl",
                        ]
                    )
                else:
                    args = parser.parse_args([phase, "--run-dir", "run"])
                self.assertEqual(args.phase, phase)


if __name__ == "__main__":
    unittest.main()
