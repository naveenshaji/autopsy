import io
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_worker import load_worker_module


class WorkerOperationReliabilityTests(unittest.TestCase):
    def test_partial_write_failure_is_not_replayed_or_healthy_runtime_reset(self):
        worker = load_worker_module()
        graph = object()
        module = SimpleNamespace(
            ensure_graph=mock.Mock(return_value=graph),
            reset_falkordb_lite_client=mock.Mock(),
            is_stale_falkordb_lite_error=lambda error: False,
        )
        committed_events = []

        def partial_write(_graph):
            committed_events.append("created-memory")
            raise ValueError("post-write validation failed")

        with self.assertRaisesRegex(ValueError, "post-write validation failed"):
            worker.run_falkor_operation(
                {"module": module, "host": "localhost", "port": 1,
                 "graph_name": "test", "lite_path": "/tmp/test.db"},
                partial_write,
            )

        self.assertEqual(committed_events, ["created-memory"])
        self.assertEqual(module.ensure_graph.call_count, 1)
        module.reset_falkordb_lite_client.assert_not_called()

    def test_stale_connection_is_reset_without_replaying_ambiguous_write(self):
        worker = load_worker_module()
        module = SimpleNamespace(
            ensure_graph=mock.Mock(return_value=object()),
            reset_falkordb_lite_client=mock.Mock(),
            is_stale_falkordb_lite_error=lambda error: isinstance(error, ConnectionError),
        )
        operation = mock.Mock(side_effect=ConnectionError("response lost after commit"))
        with self.assertRaisesRegex(ConnectionError, "response lost after commit"):
            worker.run_falkor_operation(
                {"module": module, "host": "localhost", "port": 1,
                 "graph_name": "test", "lite_path": "/tmp/test.db"},
                operation,
            )
        self.assertEqual(operation.call_count, 1)
        module.reset_falkordb_lite_client.assert_called_once_with("/tmp/test.db")


class WorkerModelCacheReliabilityTests(unittest.TestCase):
    def test_concurrent_cold_requests_share_one_model_per_provider(self):
        for loader_name, constructor_name in (
            ("load_sentence_transformer", "SentenceTransformer"),
            ("load_cross_encoder", "CrossEncoder"),
        ):
            with self.subTest(loader=loader_name):
                worker = load_worker_module()
                start = threading.Barrier(8)
                constructed = []

                def construct(*_args, **_kwargs):
                    model = object()
                    constructed.append(model)
                    time.sleep(0.03)
                    return model

                def load():
                    start.wait(timeout=5)
                    return getattr(worker, loader_name)("test-model", "cpu")

                module = SimpleNamespace(**{constructor_name: construct})
                with mock.patch.dict("sys.modules", {"sentence_transformers": module}):
                    with ThreadPoolExecutor(max_workers=8) as executor:
                        models = list(executor.map(lambda _i: load(), range(8)))
                self.assertEqual(len(constructed), 1)
                self.assertTrue(all(model is models[0] for model in models))

    def test_failed_model_load_can_be_retried(self):
        worker = load_worker_module()
        model = object()
        construct = mock.Mock(side_effect=[RuntimeError("temporary load failure"), model])
        with mock.patch.dict("sys.modules", {"sentence_transformers": SimpleNamespace(SentenceTransformer=construct)}):
            with self.assertRaisesRegex(RuntimeError, "temporary load failure"):
                worker.load_sentence_transformer("test-model", "cpu")
            self.assertIs(worker.load_sentence_transformer("test-model", "cpu"), model)
        self.assertEqual(construct.call_count, 2)


class WorkerRequestReliabilityTests(unittest.TestCase):
    def make_handler(self, worker, *, body=b"{}", headers=None):
        handler = object.__new__(worker.Handler)
        handler.server = SimpleNamespace(
            request_state_lock=threading.Lock(), active_requests=0,
            last_request_at=0.0, idle_timeout_seconds=1,
        )
        handler.path = "/memory/consult"
        handler.headers = headers or {"content-length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler._require_token = mock.Mock(return_value=True)
        handler._write_json = mock.Mock()
        return handler

    def test_active_post_is_not_idle_and_completion_resets_idle_timer(self):
        worker = load_worker_module()
        handler = self.make_handler(worker)
        with tempfile.TemporaryDirectory() as temp_dir:
            info_file = Path(temp_dir) / "worker.json"
            info_file.write_text(json.dumps({"pid": os.getpid(), "token": "token", "source_fingerprint": "source"}))

            def consult(_payload):
                self.assertEqual(handler.server.active_requests, 1)
                handler.server.last_request_at = time.monotonic() - 60
                self.assertEqual(worker.worker_should_exit(
                    handler.server, info_file=str(info_file), token="token", source_fingerprint="source",
                ), (False, ""))
                return {"ok": True}

            with mock.patch.object(worker, "handle_memory_consult", side_effect=consult):
                handler.do_POST()
        self.assertEqual(handler.server.active_requests, 0)
        self.assertLess(time.monotonic() - handler.server.last_request_at, 1)
        handler._write_json.assert_called_once_with(200, {"ok": True})

    def test_request_accounting_is_released_when_dispatch_fails(self):
        worker = load_worker_module()
        handler = self.make_handler(worker)
        with mock.patch.object(worker, "handle_memory_consult", side_effect=RuntimeError("failed request")):
            handler.do_POST()
        self.assertEqual(handler.server.active_requests, 0)
        handler._write_json.assert_called_once_with(500, {"error": "failed request"})

    def test_idle_shutdown_rechecks_request_that_started_after_monitor_check(self):
        worker = load_worker_module()
        handler = self.make_handler(worker)
        handler.server.active_requests = 1
        handler.server.last_request_at = time.monotonic() - 60
        with mock.patch.object(worker.threading, "Thread") as start_thread:
            worker.request_worker_shutdown(handler.server, "idle_timeout")
        self.assertFalse(getattr(handler.server, "shutdown_requested", False))
        start_thread.assert_not_called()

    def test_lifecycle_monitor_keeps_running_after_idle_shutdown_race(self):
        worker = load_worker_module()
        server = SimpleNamespace(shutdown_requested=False, ownership_check_seconds=0.25)

        def shutdown(_server, reason):
            if reason == "info_file_replaced":
                server.shutdown_requested = True

        with mock.patch.object(worker.time, "sleep"), mock.patch.object(
            worker, "worker_should_exit", side_effect=[(True, "idle_timeout"), (True, "info_file_replaced")],
        ), mock.patch.object(worker, "request_worker_shutdown", side_effect=shutdown) as request_shutdown:
            worker.worker_lifecycle_monitor(server, info_file="test", token="test", source_fingerprint="test")
        self.assertEqual(request_shutdown.call_count, 2)

    def test_invalid_content_length_returns_bad_request(self):
        for length in ("bad", "-1"):
            with self.subTest(length=length):
                worker = load_worker_module()
                handler = self.make_handler(worker, headers={"content-length": length})
                handler.do_POST()
                self.assertEqual(handler._write_json.call_args.args[0], 400)
                self.assertEqual(handler.server.active_requests, 0)

    def test_truncated_body_is_not_dispatched_even_when_prefix_is_valid_json(self):
        worker = load_worker_module()
        handler = self.make_handler(worker, body=b"{}", headers={"content-length": "10"})
        with mock.patch.object(worker, "handle_memory_consult") as consult:
            handler.do_POST()
        consult.assert_not_called()
        self.assertEqual(handler._write_json.call_args.args[0], 400)

    def test_non_object_json_returns_bad_request_without_dispatch(self):
        for body in (b"[]", b"null", b"7", b'"text"'):
            with self.subTest(body=body):
                worker = load_worker_module()
                handler = self.make_handler(worker, body=body)
                with mock.patch.object(worker, "handle_memory_consult") as consult:
                    handler.do_POST()
                consult.assert_not_called()
                self.assertEqual(handler._write_json.call_args.args[0], 400)


if __name__ == "__main__":
    unittest.main()
