import json
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True


def load_worker_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "src" / "autopsy_memory" / "worker.py"
    spec = importlib.util.spec_from_file_location("autopsy_ml_worker_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AutopsyMLWorkerFalkorStrictnessTests(unittest.TestCase):
    def test_int_request_argument_preserves_zero(self):
        worker = load_worker_module()
        self.assertEqual(worker.int_request_argument({"inspect_limit": 0}, "inspect_limit", 3), 0)
        self.assertEqual(worker.int_request_argument({}, "inspect_limit", 3), 3)

    def test_consult_fails_loudly_when_falkor_context_is_unavailable(self):
        worker = load_worker_module()
        original = worker.require_falkor_context

        def fail_falkor_context(*_args, **_kwargs):
            raise RuntimeError("falkor unavailable")

        worker.require_falkor_context = fail_falkor_context
        try:
            with self.assertRaisesRegex(RuntimeError, "falkor unavailable"):
                worker.handle_memory_consult({"request": {"query": "strict falkor"}})
        finally:
            worker.require_falkor_context = original

    def test_consult_preserves_requested_route(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation

        class Tool:
            def build_read_workflow(self, *_args, **_kwargs):
                return {"status": "ok", "complete": True}

        class Module:
            def build_consult_payload(self, *_args, **kwargs):
                return {
                    "route": kwargs["route"],
                    "memory_types": kwargs["memory_types"],
                    "tags": kwargs["tags"],
                    "namespaces": kwargs["namespaces"],
                    "entity_scopes": kwargs["entity_scopes"],
                    "metadata": kwargs["metadata"],
                    "filter_json": kwargs["filter_json"],
                    "min_fact_rating": kwargs["min_fact_rating"],
                    "hits": [],
                    "items": [],
                }

        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.consult_via_falkor(
                Tool(),
                {"root_path": "/tmp/autopsy-test"},
                {},
                None,
                {"module": Module(), "graph_name": "autopsy_test"},
                {
                    "query": "direct falkor",
                    "route": "hybrid",
                    "memory_types": ["procedural"],
                    "tags": ["memory-layer"],
                    "namespaces": ["repo/autopsy"],
                    "entity_scopes": ["user:alice", "agent:planner"],
                    "metadata": ["area=memory-layer"],
                    "filter_json": {"OR": [{"namespace": "release"}, {"metadata": {"score": {"gte": 8}}}]},
                    "min_fact_rating": 0.8,
                },
            )
        finally:
            worker.run_falkor_operation = original

        self.assertEqual(payload["route"], "hybrid")
        self.assertEqual(payload["memory_types"], ["procedural"])
        self.assertEqual(payload["tags"], ["memory-layer"])
        self.assertEqual(payload["namespaces"], ["repo/autopsy"])
        self.assertEqual(payload["entity_scopes"], ["user:alice", "agent:planner"])
        self.assertEqual(payload["metadata"], ["area=memory-layer"])
        self.assertEqual(payload["filter_json"], {"OR": [{"namespace": "release"}, {"metadata": {"score": {"gte": 8}}}]})
        self.assertEqual(payload["min_fact_rating"], 0.8)

    def test_history_route_preserves_stable_key_and_limit(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        class Module:
            def build_history_payload(self, *_args, **kwargs):
                return {
                    "stable_key": kwargs["stable_key"],
                    "limit": kwargs["limit"],
                }

        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.history_via_falkor(
                Tool(),
                {"root_path": "/tmp/autopsy-test"},
                {"module": Module(), "graph_name": "autopsy_test"},
                {"stable_key": "graph-note:abc", "limit": 7},
            )
        finally:
            worker.run_falkor_operation = original

        self.assertEqual(payload["stable_key"], "graph-note:abc")
        self.assertEqual(payload["limit"], 7)

    def test_observe_route_preserves_write_if_stale(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        class Module:
            def build_observe_payload(self, *_args, **kwargs):
                return {
                    "stable_key": kwargs["stable_key"],
                    "limit": kwargs["limit"],
                    "min_fact_rating": kwargs["min_fact_rating"],
                    "write": kwargs["write"],
                    "write_if_stale": kwargs["write_if_stale"],
                }

        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), None, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": Module(), "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_observe(
                {
                    "request": {
                        "stable_key": "graph-note:seed",
                        "limit": 3,
                        "min_fact_rating": 0.8,
                        "write_if_stale": True,
                    }
                }
            )
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["stable_key"], "graph-note:seed")
        self.assertEqual(payload["limit"], 3)
        self.assertEqual(payload["min_fact_rating"], 0.8)
        self.assertFalse(payload["write"])
        self.assertTrue(payload["write_if_stale"])

    def test_worker_should_exit_when_info_file_is_replaced(self):
        worker = load_worker_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            info_file = Path(temp_dir) / "ml-worker.json"
            token = "TOKEN"
            source_fingerprint = "source"
            info_file.write_text(
                json.dumps({"pid": os.getpid(), "token": token, "source_fingerprint": source_fingerprint}),
                encoding="utf-8",
            )

            class Server:
                idle_timeout_seconds = 0
                last_request_at = time.monotonic()

            self.assertEqual(
                worker.worker_should_exit(Server(), info_file=str(info_file), token=token, source_fingerprint=source_fingerprint),
                (False, ""),
            )
            info_file.write_text(
                json.dumps({"pid": os.getpid() + 1, "token": token, "source_fingerprint": source_fingerprint}),
                encoding="utf-8",
            )
            self.assertEqual(
                worker.worker_should_exit(Server(), info_file=str(info_file), token=token, source_fingerprint=source_fingerprint),
                (True, "info_file_replaced"),
            )

    def test_worker_should_exit_after_idle_timeout(self):
        worker = load_worker_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            info_file = Path(temp_dir) / "ml-worker.json"
            token = "TOKEN"
            source_fingerprint = "source"
            info_file.write_text(
                json.dumps({"pid": os.getpid(), "token": token, "source_fingerprint": source_fingerprint}),
                encoding="utf-8",
            )

            class Server:
                idle_timeout_seconds = 1
                last_request_at = time.monotonic() - 2

            self.assertEqual(
                worker.worker_should_exit(Server(), info_file=str(info_file), token=token, source_fingerprint=source_fingerprint),
                (True, "idle_timeout"),
            )


if __name__ == "__main__":
    unittest.main()
