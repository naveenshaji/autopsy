import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from autopsy_memory import mcp_bridge


class WorkerSourceFingerprintTests(unittest.TestCase):
    def test_backup_module_only_change_reloads_worker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = {name: root / filename for name, filename in (
                ("script", "mcp_bridge.py"), ("worker", "worker.py"), ("tool", "cli.py"),
            )}
            for path in paths.values():
                path.write_text("unchanged")
            backups = root / "backups.py"
            backups.write_text("old backups")
            with mock.patch.object(mcp_bridge, "script_paths", return_value=paths):
                info = {"source_fingerprint": mcp_bridge.source_fingerprint()}
                self.assertTrue(mcp_bridge.worker_info_matches_current_sources(info))
                old_stat = backups.stat()
                backups.write_text("new backups")
                os.utime(backups, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 1_000_000))
                self.assertFalse(mcp_bridge.worker_info_matches_current_sources(info))
                with mock.patch.object(mcp_bridge, "read_worker_info", return_value=info), mock.patch.object(
                    mcp_bridge, "lock_file", return_value=root / "worker.lock",
                ), mock.patch.object(mcp_bridge, "start_worker_locked", return_value={"new": True}) as start:
                    self.assertEqual(mcp_bridge.ensure_worker(), {"new": True})
                start.assert_called_once_with()

    def test_unchanged_sources_reuse_healthy_worker(self):
        info = {"source_fingerprint": mcp_bridge.source_fingerprint()}
        with mock.patch.object(mcp_bridge, "read_worker_info", return_value=info), mock.patch.object(
            mcp_bridge, "health_check", return_value=True,
        ), mock.patch.object(mcp_bridge, "start_worker_locked") as start:
            self.assertIs(mcp_bridge.ensure_worker(), info)
        start.assert_not_called()


class WorkerRequestReplaySafetyTests(unittest.TestCase):
    def setUp(self):
        self.info = {"base_url": "http://127.0.0.1:1234", "token": "test", "pid": 1234}
        for name in ("ensure_worker", "terminate_pid", "clear_worker_info", "recover_stale_falkor_socket"):
            patcher = mock.patch.object(mcp_bridge, name)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.ensure_worker.return_value = self.info

    def response(self, body=b'{"ok":true}'):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = body
        return response

    def assert_no_recovery(self):
        self.terminate_pid.assert_not_called()
        self.clear_worker_info.assert_not_called()
        self.recover_stale_falkor_socket.assert_not_called()

    def test_mutating_routes_never_replay_on_lost_response(self):
        paths = (
            "/memory/graph/note", "/memory/graph/item/update", "/memory/graph/item/delete",
            "/memory/graph/conflicts/resolve", "/memory/expire", "/memory/pin",
            "/memory/feedback", "/memory/observe", "/memory/consolidate-session",
            "/memory/import-session", "/memory/sync/workspace", "/future/write-route",
        )
        for path in paths:
            with self.subTest(path=path):
                with mock.patch.object(mcp_bridge.urllib.request, "urlopen", side_effect=[
                    urllib.error.URLError("response lost after commit"), self.response(),
                ]) as urlopen:
                    with self.assertRaisesRegex(mcp_bridge.BridgeError, "outcome is unknown.*not replayed"):
                        mcp_bridge.worker_request(path, {"request": {"body": "memory"}})
                self.assertEqual(urlopen.call_count, 1)
                self.assert_no_recovery()

    def test_mutation_stale_socket_error_is_not_replayed(self):
        error = urllib.error.HTTPError("http://local", 500, "failed", {}, io.BytesIO(
            b'{"error":"redis.socket connection refused"}',
        ))
        with mock.patch.object(mcp_bridge.urllib.request, "urlopen", side_effect=[error, self.response()]) as urlopen:
            with self.assertRaisesRegex(mcp_bridge.BridgeError, "outcome is unknown"):
                mcp_bridge.worker_request("/memory/graph/note", {"request": {}})
        self.assertEqual(urlopen.call_count, 1)
        self.assert_no_recovery()

    def test_mutation_timeout_disconnect_and_invalid_response_are_explicit(self):
        for failure in (
            TimeoutError("response timeout"), ConnectionResetError("connection closed"),
            self.response(b'{"unfinished":'), self.response(b""), self.response(b"[]"),
        ):
            with self.subTest(failure=type(failure).__name__):
                with mock.patch.object(mcp_bridge.urllib.request, "urlopen", side_effect=[failure]) as urlopen:
                    with self.assertRaisesRegex(mcp_bridge.BridgeError, "Inspect.*before retrying"):
                        mcp_bridge.worker_request("/memory/graph/item/update", {"request": {"stable_key": "test"}})
                self.assertEqual(urlopen.call_count, 1)
                self.assert_no_recovery()

    def test_read_transport_retry_preserves_original_payload_and_is_bounded(self):
        payload = {"request": {"query": "original query", "limit": 3}}
        with mock.patch.object(mcp_bridge.urllib.request, "urlopen", side_effect=[
            urllib.error.URLError("stale connection"), self.response(),
        ]) as urlopen:
            self.assertEqual(mcp_bridge.worker_request("/memory/consult", payload), {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(json.loads(urlopen.call_args_list[1].args[0].data), payload)
        self.terminate_pid.assert_called_once_with(1234)
        self.clear_worker_info.assert_called_once_with()

    def test_read_retry_stops_after_one_recovery(self):
        with mock.patch.object(mcp_bridge.urllib.request, "urlopen", side_effect=urllib.error.URLError("unavailable")) as urlopen:
            with self.assertRaisesRegex(mcp_bridge.BridgeError, "unavailable"):
                mcp_bridge.worker_request("/memory/status", {})
        self.assertEqual(urlopen.call_count, 2)
        self.terminate_pid.assert_called_once_with(1234)

    def test_read_http_retry_preserves_original_payload(self):
        payload = {"request": {"query": "original query"}}
        error = urllib.error.HTTPError("http://local", 500, "failed", {}, io.BytesIO(
            b'{"error":"redis.socket connection refused"}',
        ))
        with mock.patch.object(mcp_bridge.urllib.request, "urlopen", side_effect=[error, self.response()]) as urlopen:
            self.assertEqual(mcp_bridge.worker_request("/memory/consult", payload), {"ok": True})
        self.assertEqual(json.loads(urlopen.call_args_list[1].args[0].data), payload)
        self.recover_stale_falkor_socket.assert_called_once_with(self.info)

    def test_explicit_client_error_does_not_claim_write_committed(self):
        error = urllib.error.HTTPError("http://local", 400, "bad request", {}, io.BytesIO(b'{"error":"invalid json"}'))
        with mock.patch.object(mcp_bridge.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(mcp_bridge.BridgeError, "^invalid json$"):
                mcp_bridge.worker_request("/memory/graph/note", {})
        self.assert_no_recovery()


class WorkerFingerprintTests(unittest.TestCase):
    def test_backup_only_changes_reload_worker(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            paths = {name: directory / (name + ".py") for name in ("script", "worker", "tool")}
            for path in paths.values():
                path.write_text("# unchanged\n")
            backup = directory / "backups.py"
            backup.write_text("# backup v1\n")
            with mock.patch.object(mcp_bridge, "script_paths", return_value=paths):
                previous = {"source_fingerprint": mcp_bridge.source_fingerprint()}
                self.assertTrue(mcp_bridge.worker_info_matches_current_sources(previous))
                backup.write_text("# backup v2 with a changed size\n")
                self.assertFalse(mcp_bridge.worker_info_matches_current_sources(previous))


if __name__ == "__main__":
    unittest.main()
