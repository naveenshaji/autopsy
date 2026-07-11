from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from autopsy_memory.evaluation.adapters import ADAPTER_IDS, create_evaluation_adapter, source_tree_pin
from autopsy_memory.evaluation.mem0_adapter import (
    EMBEDDING_MODEL,
    EMBEDDING_REVISION,
    MEM0_COMMIT,
    MEM0_VERSION,
    Mem0OSSEvaluationAdapter,
    mem0_bootstrap_dir,
    mem0_setup_script,
)
from autopsy_memory.evaluation.models import (
    EvaluationCorpus,
    EvaluationDocument,
    RetrievalRequest,
)


FAKE_WORKER = r'''
import json
import sys

documents = []
for line in sys.stdin:
    message = json.loads(line)
    action = message["action"]
    request_id = message["request_id"]
    if action == "handshake":
        result = {
            "protocol": "autopsy-mem0-raw-ndjson/v1",
            "packages": {
                "mem0ai": "2.0.11",
                "sentence-transformers": "5.1.2",
                "transformers": "4.57.6",
                "torch": "2.8.0",
                "qdrant-client": "1.15.1",
                "pydantic": "2.11.9",
            },
            "mem0_commit": "f2532f072fdefa4c90264acc80af0984309f8b06",
            "mem0_direct_url": {
                "url": "https://github.com/mem0ai/mem0.git",
                "vcs_info": {
                    "vcs": "git",
                    "commit_id": "f2532f072fdefa4c90264acc80af0984309f8b06",
                    "requested_revision": "f2532f072fdefa4c90264acc80af0984309f8b06",
                },
            },
            "embedding_model": "sentence-transformers/multi-qa-MiniLM-L6-cos-v1",
            "embedding_revision": "b207367332321f8e44f96e224ef15bc607f4dbf0",
            "embedding_dimensions": 384,
            "telemetry": False,
        }
    elif action == "prepare":
        assert "query" not in message
        assert "answer" not in message
        assert "relevant_document_ids" not in message
        documents = [row["document_id"] for row in message["documents"]]
        result = {
            "reused": False,
            "corpus_fingerprint": message["corpus_fingerprint"],
            "documents": len(documents),
            "characters": sum(len(row["text"]) for row in message["documents"]),
            "relations": message["relation_count"],
            "relations_indexed": 0,
            "embedded_items": len(documents),
            "infer": False,
            "seconds": 0.01,
        }
    elif action == "retrieve":
        assert message["query"] == "held-out query"
        result = {
            "ranked_document_ids": documents[:message["limit"]],
            "latency_seconds": 0.001,
            "route": "mem0-oss-native-search",
            "retrieval_reasons": [["embedding", "mem0-native-search"] for _ in documents[:message["limit"]]],
            "diagnostics": {
                "requested_as_of": message["as_of"],
                "native_as_of_supported": False,
                "as_of_applied": False,
            },
        }
    elif action == "reset":
        result = {"reset": True, "adaptive_query_state": False}
    elif action == "capabilities":
        result = {
            "evaluated_eligible_items": len(documents),
            "evaluated_embedded_items": len(documents),
            "evaluated_vector_coverage": 1.0 if documents else 0.0,
            "embedding_model_revision": "b207367332321f8e44f96e224ef15bc607f4dbf0",
            "native_as_of_support": False,
        }
    elif action == "close":
        result = {"closed": True}
    else:
        raise AssertionError(action)
    print(json.dumps({"ok": True, "request_id": request_id, "result": result}), flush=True)
    if action == "close":
        break
'''


class Mem0AdapterContractTests(unittest.TestCase):
    def _fake_worker(self, directory: str) -> Path:
        worker = Path(directory) / "fake_mem0_worker.py"
        worker.write_text(textwrap.dedent(FAKE_WORKER), encoding="utf-8")
        return worker

    def test_two_phase_protocol_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = self._fake_worker(directory)
            with Mem0OSSEvaluationAdapter(
                python_executable=sys.executable,
                worker_path=worker,
            ) as adapter:
                corpus = EvaluationCorpus(
                    documents=(
                        EvaluationDocument(
                            "opaque-document-handle",
                            "Corpus content only.",
                            title="Raw document",
                            metadata={"repository_id": "/repo/a"},
                        ),
                    )
                )
                ingestion = adapter.prepare(corpus)
                result = adapter.retrieve(
                    RetrievalRequest(
                        "held-out query",
                        5,
                        "hybrid",
                        as_of="2025-01-01T00:00:00Z",
                        scope="repo",
                        repository_id="/repo/a",
                    )
                )
                manifest = adapter.manifest()
                capabilities = adapter.capabilities()

        self.assertEqual(ingestion["documents"], 1)
        self.assertTrue(ingestion["infer"] is False)
        self.assertEqual(result.ranked_document_ids, ("opaque-document-handle",))
        self.assertEqual(result.retrieval_reasons, (("embedding", "mem0-native-search"),))
        self.assertFalse(result.diagnostics["native_as_of_supported"])
        self.assertFalse(result.diagnostics["as_of_applied"])
        self.assertEqual(manifest["adapter_id"], "mem0-oss-raw")
        self.assertEqual(manifest["package_pin"]["version"], MEM0_VERSION)
        self.assertEqual(manifest["source_pin"]["commit"], MEM0_COMMIT)
        bootstrap_pin = manifest["source_pin"]["bootstrap_assets"]
        self.assertEqual(bootstrap_pin, source_tree_pin(mem0_bootstrap_dir()))
        self.assertEqual(
            set(manifest["source_pin"]["adapter_bundle"]["files"]),
            {
                "adapter/mem0_adapter.py",
                "adapter/mem0_worker.py",
                "bootstrap/README.md",
                "bootstrap/requirements.txt",
                "bootstrap/setup.sh",
            },
        )
        self.assertEqual(
            manifest["package_pin"]["embedding_model"],
            {"name": EMBEDDING_MODEL, "revision": EMBEDDING_REVISION},
        )
        self.assertEqual(manifest["execution"]["mode"], "local-isolated-subprocess")
        self.assertTrue(manifest["execution"]["local"])
        self.assertFalse(manifest["execution"]["remote"])
        self.assertEqual(manifest["cost"]["external_api_cost_usd"], 0.0)
        self.assertEqual(capabilities["evaluated_vector_coverage"], 1.0)
        self.assertFalse(capabilities["native_as_of_support"])

    def test_prepare_rejects_query_bearing_case(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = self._fake_worker(directory)
            with Mem0OSSEvaluationAdapter(
                python_executable=sys.executable,
                worker_path=worker,
            ) as adapter:
                with self.assertRaisesRegex(TypeError, "EvaluationCorpus"):
                    adapter.prepare(object())  # type: ignore[arg-type]

    def test_missing_environment_fails_with_bootstrap_instruction(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-python"
            with self.assertRaisesRegex(RuntimeError, "setup.sh") as raised:
                Mem0OSSEvaluationAdapter(python_executable=missing)
        setup = mem0_setup_script()
        self.assertIn(str(setup), str(raised.exception))
        self.assertTrue(setup.is_file())
        self.assertTrue(os.access(setup, os.X_OK))
        self.assertTrue((setup.parent / "requirements.txt").is_file())
        self.assertTrue((setup.parent / "README.md").is_file())

    def test_factory_exposes_lazy_mem0_adapter(self):
        self.assertIn("mem0-oss-raw", ADAPTER_IDS)
        sentinel = object()
        with mock.patch(
            "autopsy_memory.evaluation.mem0_adapter.Mem0OSSEvaluationAdapter",
            return_value=sentinel,
        ) as constructor:
            result = create_evaluation_adapter(
                "mem0-oss-raw",
                store_dir="/tmp/mem0-eval-test",
                keep_store=True,
            )
        self.assertIs(result, sentinel)
        constructor.assert_called_once_with(store_dir="/tmp/mem0-eval-test", keep_store=True)


@unittest.skipUnless(importlib.util.find_spec("build"), "the build frontend is not installed")
class Mem0CleanWheelTests(unittest.TestCase):
    def test_wheel_contains_executable_bootstrap_and_installed_error_points_to_it(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel_dir = root / "wheel"
            target = root / "installed"
            wheel_dir.mkdir()
            subprocess.run(
                [sys.executable, "-m", "build", "--wheel", "--outdir", str(wheel_dir)],
                cwd=repository,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            wheels = list(wheel_dir.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as archive:
                setup_name = "autopsy_memory/evaluation/competitors/mem0/setup.sh"
                setup_info = archive.getinfo(setup_name)
                self.assertTrue((setup_info.external_attr >> 16) & 0o111)
                for info in archive.infolist():
                    archive.extract(info, target)
                    mode = (info.external_attr >> 16) & 0o777
                    extracted = target / info.filename
                    if mode and extracted.exists():
                        extracted.chmod(mode)
            probe = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    """
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from autopsy_memory.evaluation.mem0_adapter import (
    Mem0OSSEvaluationAdapter,
    mem0_adapter_bundle_pin,
    mem0_bootstrap_dir,
    mem0_setup_script,
)
setup = mem0_setup_script()
try:
    Mem0OSSEvaluationAdapter(python_executable=Path(sys.argv[1]) / 'missing-python')
except RuntimeError as exc:
    error = str(exc)
else:
    raise AssertionError('missing Mem0 environment unexpectedly succeeded')
print(json.dumps({
    'setup': str(setup),
    'setup_exists': setup.is_file(),
    'setup_executable': os.access(setup, os.X_OK),
    'requirements_exists': (mem0_bootstrap_dir() / 'requirements.txt').is_file(),
    'readme_exists': (mem0_bootstrap_dir() / 'README.md').is_file(),
    'error_mentions_setup': str(setup) in error,
    'bundle': mem0_adapter_bundle_pin(),
}))
""",
                    str(target),
                ],
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = json.loads(probe.stdout)
            expected_setup = (
                target
                / "autopsy_memory"
                / "evaluation"
                / "competitors"
                / "mem0"
                / "setup.sh"
            )
            self.assertEqual(Path(payload["setup"]), expected_setup)
        self.assertTrue(payload["setup_exists"])
        self.assertTrue(payload["setup_executable"])
        self.assertTrue(payload["requirements_exists"])
        self.assertTrue(payload["readme_exists"])
        self.assertTrue(payload["error_mentions_setup"])
        self.assertEqual(
            set(payload["bundle"]["files"]),
            {
                "adapter/mem0_adapter.py",
                "adapter/mem0_worker.py",
                "bootstrap/README.md",
                "bootstrap/requirements.txt",
                "bootstrap/setup.sh",
            },
        )


@unittest.skipUnless(
    os.environ.get("AUTOPSY_MEM0_INTEGRATION") == "1" and os.environ.get("AUTOPSY_MEM0_PYTHON"),
    "set AUTOPSY_MEM0_INTEGRATION=1 and AUTOPSY_MEM0_PYTHON for the pinned integration test",
)
class Mem0PinnedEnvironmentIntegrationTests(unittest.TestCase):
    def test_real_worker_filters_scope_and_expiration(self):
        corpus = EvaluationCorpus(
            documents=(
                EvaluationDocument(
                    "opaque-current",
                    "The verified deployment procedure checks the signed manifest.",
                    metadata={"repository_id": "/repo/a"},
                ),
                EvaluationDocument(
                    "opaque-other-repo",
                    "The verified deployment procedure bypasses the release gate.",
                    metadata={"repository_id": "/repo/b"},
                ),
                EvaluationDocument(
                    "opaque-expired",
                    "The old verified deployment procedure uses an expired mirror.",
                    expired_at="2020-01-01T00:00:00Z",
                    metadata={"repository_id": "/repo/a"},
                ),
            )
        )
        with Mem0OSSEvaluationAdapter() as adapter:
            ingestion = adapter.prepare(corpus)
            result = adapter.retrieve(
                RetrievalRequest(
                    "What is the verified deployment procedure?",
                    10,
                    "hybrid",
                    as_of="2019-01-01T00:00:00Z",
                    scope="repo",
                    repository_id="/repo/a",
                )
            )
            capabilities = adapter.capabilities()
        self.assertEqual(ingestion["embedded_items"], 3)
        self.assertIn("opaque-current", result.ranked_document_ids)
        self.assertNotIn("opaque-other-repo", result.ranked_document_ids)
        self.assertNotIn("opaque-expired", result.ranked_document_ids)
        self.assertFalse(result.diagnostics["as_of_applied"])
        self.assertEqual(capabilities["evaluated_vector_coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
