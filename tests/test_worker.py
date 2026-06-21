import json
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

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

    def test_health_returns_structured_runtime_failure_payload(self):
        worker = load_worker_module()
        original_context = worker.require_falkor_context
        original_failure_payload = worker.falkor_start_failure_payload_for_worker

        def fail_falkor_context(*_args, **_kwargs):
            raise RuntimeError("Autopsy memory database rollback detected")

        def failure_payload(payload, error):
            return {
                "ok": False,
                "error": str(error),
                "workflow": {
                    "status": "rollback_detected",
                    "complete": False,
                    "next_step": "restore_or_repair_embedded_memory_snapshot",
                },
                "request": payload.get("request"),
            }

        worker.require_falkor_context = fail_falkor_context
        worker.falkor_start_failure_payload_for_worker = failure_payload
        try:
            payload = worker.handle_memory_health({"request": {"repo": "/tmp/repo"}})
        finally:
            worker.require_falkor_context = original_context
            worker.falkor_start_failure_payload_for_worker = original_failure_payload

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["workflow"]["status"], "rollback_detected")
        self.assertEqual(payload["workflow"]["next_step"], "restore_or_repair_embedded_memory_snapshot")
        self.assertEqual(payload["request"], {"repo": "/tmp/repo"})

    def test_maybe_load_falkor_context_resets_lite_client_on_rollback(self):
        worker = load_worker_module()
        original_settings = worker.falkor_backend_settings
        reset_calls: list[str] = []
        sync_called: list[bool] = []

        class MemoryDatabaseRollbackError(RuntimeError):
            pass

        class Module:
            def workspace_graph_name(self, graph_name, _workspace):
                return graph_name

            def ensure_workspace_graph(self, **_kwargs):
                raise MemoryDatabaseRollbackError("Autopsy memory database rollback detected")

            def sync_workspace_payload(self, *_args, **_kwargs):
                sync_called.append(True)

            def reset_falkordb_lite_client(self, lite_path):
                reset_calls.append(lite_path)

        worker.falkor_backend_settings = lambda: {
            "host": "127.0.0.1",
            "port": 6381,
            "graph_name": "autopsy_memory",
            "lite_path": "/tmp/stale-autopsy.db",
        }
        try:
            with self.assertRaises(MemoryDatabaseRollbackError):
                worker.maybe_load_falkor_context(
                    {"tool_path": "/tmp/autopsy-cli.py"},
                    {"root_path": "/tmp/repo"},
                    Module(),
                    {},
                )
        finally:
            worker.falkor_backend_settings = original_settings
            worker._FALKOR_CONTEXT_CACHE.clear()

        self.assertEqual(reset_calls, ["/tmp/stale-autopsy.db"])
        self.assertEqual(sync_called, [])

    def test_run_falkor_operation_does_not_retry_after_rollback(self):
        worker = load_worker_module()
        reset_calls: list[str] = []
        ensure_calls: list[str] = []
        operation_calls: list[bool] = []

        class MemoryDatabaseRollbackError(RuntimeError):
            pass

        class Module:
            def ensure_graph(self, _host, _port, graph_name, lite_path=None):
                ensure_calls.append(f"{graph_name}:{lite_path}")
                raise MemoryDatabaseRollbackError("Autopsy memory database rollback detected")

            def reset_falkordb_lite_client(self, lite_path):
                reset_calls.append(lite_path)

        with self.assertRaises(MemoryDatabaseRollbackError):
            worker.run_falkor_operation(
                {
                    "module": Module(),
                    "host": "127.0.0.1",
                    "port": 6381,
                    "graph_name": "autopsy_memory",
                    "lite_path": "/tmp/stale-autopsy.db",
                },
                lambda _graph: operation_calls.append(True),
            )

        self.assertEqual(ensure_calls, ["autopsy_memory:/tmp/stale-autopsy.db"])
        self.assertEqual(reset_calls, ["/tmp/stale-autopsy.db"])
        self.assertEqual(operation_calls, [])

    def test_diagnostics_route_does_not_open_falkor_context(self):
        worker = load_worker_module()
        original_context = worker.require_falkor_context
        original_load = worker.load_falkor_module

        def fail_falkor_context(*_args, **_kwargs):
            raise AssertionError("diagnostics should not open Falkor")

        class Module:
            def build_diagnostics_command_payload(self, args):
                return {
                    "selected_log": args.log,
                    "limit": args.limit,
                    "workflow": {"status": "ok", "complete": True},
                }

        worker.require_falkor_context = fail_falkor_context
        worker.load_falkor_module = lambda tool_path: Module()
        try:
            payload = worker.handle_memory_diagnostics(
                {
                    "tool_path": "/tmp/autopsy-cli.py",
                    "request": {
                        "log": "memory-guard",
                        "limit": 2,
                    },
                }
            )
        finally:
            worker.require_falkor_context = original_context
            worker.load_falkor_module = original_load

        self.assertEqual(payload["selected_log"], "memory-guard")
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(payload["workflow"]["status"], "ok")

    def test_repair_embedded_snapshot_plan_forces_dry_run_safety_flags(self):
        worker = load_worker_module()
        original_context = worker.require_falkor_context
        original_load = worker.load_falkor_module
        original_settings = worker.falkor_backend_settings
        original_resolve_workspace = worker.resolve_workspace_reference
        captured: dict[str, object] = {}

        def fail_falkor_context(*_args, **_kwargs):
            raise AssertionError("repair preview should not open Falkor")

        class Module:
            def build_embedded_snapshot_repair_payload(self, args):
                captured["args"] = args
                return {
                    "dry_run": False,
                    "requires_confirmation": False,
                    "workflow": {"status": "ready", "complete": False},
                }

        worker.require_falkor_context = fail_falkor_context
        worker.load_falkor_module = lambda tool_path: Module()
        worker.falkor_backend_settings = lambda: {
            "host": "127.0.0.1",
            "port": 6381,
            "graph_name": "autopsy_memory",
            "lite_path": "/tmp/default-autopsy.db",
        }
        worker.resolve_workspace_reference = lambda selector, cwd: {
            "id": "/tmp/memory-root",
            "workspace_key": "/tmp/memory-root",
            "slug": "memory-root",
            "title": "MemoryRoot",
            "root_path": "/tmp/memory-root",
        }
        try:
            payload = worker.handle_memory_repair_embedded_snapshot_plan(
                {
                    "tool_path": "/tmp/autopsy-cli.py",
                    "workspace": "/tmp/requested-workspace",
                    "cwd": "/tmp/cwd",
                    "request": {
                        "restore_latest_backup": True,
                        "backup_limit": 3,
                        "include_operational": True,
                    },
                }
            )
        finally:
            worker.require_falkor_context = original_context
            worker.load_falkor_module = original_load
            worker.falkor_backend_settings = original_settings
            worker.resolve_workspace_reference = original_resolve_workspace

        args = captured["args"]
        self.assertTrue(args.dry_run)
        self.assertFalse(args.yes)
        self.assertFalse(args.accept_data_loss)
        self.assertEqual(args.lite_path, "/tmp/default-autopsy.db")
        self.assertTrue(args.restore_latest_backup)
        self.assertEqual(args.backup_limit, 3)
        self.assertEqual(args.salvage_output, "")
        self.assertEqual(args.salvage_limit, 0)
        self.assertTrue(args.skip_salvage)
        self.assertTrue(args.include_operational)
        self.assertTrue(args.skip_cleanup_workers)
        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["requires_confirmation"])
        self.assertTrue(payload["mcp_safety"]["plan_only"])
        self.assertFalse(payload["mcp_safety"]["mutations_allowed"])
        self.assertFalse(payload["mcp_safety"]["salvage_export_allowed"])

    def test_repair_embedded_snapshot_plan_returns_structured_payload_on_cli_exit(self):
        worker = load_worker_module()
        original_context = worker.require_falkor_context
        original_load = worker.load_falkor_module
        original_settings = worker.falkor_backend_settings
        original_resolve_workspace = worker.resolve_workspace_reference

        def fail_falkor_context(*_args, **_kwargs):
            raise AssertionError("repair preview should not open Falkor")

        class Module:
            def build_embedded_snapshot_repair_payload(self, _args):
                print("repair-embedded-snapshot --restore-latest-backup found no valid default Autopsy backups", file=sys.stderr)
                raise SystemExit(2)

        worker.require_falkor_context = fail_falkor_context
        worker.load_falkor_module = lambda tool_path: Module()
        worker.falkor_backend_settings = lambda: {
            "host": "127.0.0.1",
            "port": 6381,
            "graph_name": "autopsy_memory",
            "lite_path": "/tmp/default-autopsy.db",
        }
        worker.resolve_workspace_reference = lambda selector, cwd: {
            "id": "/tmp/memory-root",
            "workspace_key": "/tmp/memory-root",
            "slug": "memory-root",
            "title": "MemoryRoot",
            "root_path": "/tmp/memory-root",
        }
        try:
            payload = worker.handle_memory_repair_embedded_snapshot_plan(
                {
                    "tool_path": "/tmp/autopsy-cli.py",
                    "request": {"restore_latest_backup": True},
                }
            )
        finally:
            worker.require_falkor_context = original_context
            worker.load_falkor_module = original_load
            worker.falkor_backend_settings = original_settings
            worker.resolve_workspace_reference = original_resolve_workspace

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["requires_confirmation"])
        self.assertEqual(payload["exit_code"], 2)
        self.assertEqual(payload["workflow"]["status"], "repair_plan_unavailable")
        self.assertIn("found no valid default Autopsy backups", payload["error"])
        self.assertTrue(payload["mcp_safety"]["plan_only"])
        self.assertFalse(payload["mcp_safety"]["mutations_allowed"])

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

    def test_consult_reports_weak_signals_for_relationship_candidates(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation

        class Tool:
            def build_read_workflow(self, *_args, **_kwargs):
                return {"status": "empty", "complete": False}

        class Module:
            def build_consult_payload(self, *_args, **_kwargs):
                return {
                    "hits": [],
                    "items": [],
                    "relationship_candidate_hits": [
                        {
                            "stable_key": "graph-note:related",
                            "kind": "attempt",
                            "title": "Related repair attempt",
                        }
                    ],
                }

        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.consult_via_falkor(
                Tool(),
                {"root_path": "/tmp/autopsy-test"},
                {},
                None,
                {"module": Module(), "graph_name": "autopsy_test"},
                {"query": "relationship repair", "route": "hybrid"},
            )
        finally:
            worker.run_falkor_operation = original

        self.assertEqual(payload["workflow"]["status"], "weak_signals_only")
        self.assertFalse(payload["workflow"]["complete"])
        self.assertEqual(payload["relationship_candidate_hits"][0]["stable_key"], "graph-note:related")

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

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
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

    def test_worker_note_create_returns_blocked_missing_relation_payload(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        class MissingRelationTargetsError(Exception):
            pass

        calls = []

        class Module:
            def relation_specs_from_mapping(self, request):
                return [{"relation": "supersedes", "target": request["supersedes"][0]}]

            def relation_target_records(self, *_args, **_kwargs):
                raise MissingRelationTargetsError("missing target")

            def blocked_relation_write_payload(self, *, error, operation):
                return {"blocked": True, "reason": "missing_relation_target", "operation": operation, "message": str(error)}

            def create_graph_note_payload(self, *_args, **_kwargs):
                calls.append("create")
                return {}

        Module.MissingRelationTargetsError = MissingRelationTargetsError
        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_graph_note_create(
                {
                    "request": {
                        "title": "Needs relation",
                        "content": "This should not be written.",
                        "supersedes": ["graph-note:missing"],
                    }
                }
            )
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["reason"], "missing_relation_target")
        self.assertEqual(payload["operation"], "create")
        self.assertEqual(calls, [])

    def test_worker_update_missing_source_returns_blocked_payload_before_write_quality(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def lookup_node_by_stable_key(self, *_args, **_kwargs):
                return None

            def blocked_missing_memory_item_payload_for_graph(self, _graph, *, stable_key, operation):
                return {"blocked": True, "reason": "missing_memory_item", "stable_key": stable_key, "operation": operation}

            def build_write_quality_payload(self, *_args, **_kwargs):
                calls.append("write_quality")
                return {}

            def update_graph_item_payload(self, *_args, **_kwargs):
                calls.append("update")
                return {}

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_graph_item_update(
                {
                    "request": {
                        "stable_key": "graph-note:missing",
                        "title": "Missing source",
                        "content": "This should not be written.",
                    }
                }
            )
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["reason"], "missing_memory_item")
        self.assertEqual(payload["operation"], "update")
        self.assertEqual(calls, [])

    def test_worker_delete_missing_source_returns_blocked_payload_before_delete(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def lookup_node_by_stable_key(self, *_args, **_kwargs):
                return None

            def blocked_missing_memory_item_payload_for_graph(self, _graph, *, stable_key, operation):
                return {"blocked": True, "reason": "missing_memory_item", "stable_key": stable_key, "operation": operation}

            def delete_graph_item_payload(self, *_args, **_kwargs):
                calls.append("delete")

            def refresh_activity_snapshot(self, *_args, **_kwargs):
                calls.append("refresh")

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_graph_item_delete({"request": {"stable_key": "graph-note:missing"}})
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["reason"], "missing_memory_item")
        self.assertEqual(payload["operation"], "delete")
        self.assertEqual(calls, [])

    def test_worker_item_missing_key_returns_blocked_payload_before_detail_fetch(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def lookup_node_by_stable_key(self, *_args, **_kwargs):
                return None

            def blocked_missing_memory_item_payload_for_graph(self, _graph, *, stable_key, operation):
                return {"blocked": True, "reason": "missing_memory_item", "stable_key": stable_key, "operation": operation}

            def build_graph_item_detail_payload(self, *_args, **_kwargs):
                calls.append("detail")
                return {}

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_graph_item({"request": {"stable_key": "graph-note:missing"}})
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["reason"], "missing_memory_item")
        self.assertEqual(payload["operation"], "item")
        self.assertEqual(calls, [])

    def test_worker_feedback_missing_source_returns_blocked_payload_before_write(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def lookup_node_by_stable_key(self, *_args, **_kwargs):
                return None

            def blocked_missing_memory_item_payload_for_graph(self, _graph, *, stable_key, operation):
                return {"blocked": True, "reason": "missing_memory_item", "stable_key": stable_key, "operation": operation}

            def record_memory_feedback(self, *_args, **_kwargs):
                calls.append("feedback")
                return {}

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_feedback({"request": {"stable_key": "graph-note:missing", "rating": "useful"}})
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["reason"], "missing_memory_item")
        self.assertEqual(payload["operation"], "feedback")
        self.assertEqual(calls, [])

    def test_worker_consolidate_session_preserves_draft_request(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        class Module:
            def build_consolidate_session_payload(self, _graph, *, tool, workspace, stable_key, kind, title, max_events, write):
                return {
                    "workspace": tool.workspace_payload(workspace),
                    "stable_key": stable_key,
                    "kind": kind,
                    "title": title,
                    "max_events": max_events,
                    "write": write,
                    "workflow": {"status": "draft"},
                }

            def refresh_activity_snapshot(self, *_args, **_kwargs):
                raise AssertionError("draft consolidation should not refresh activity")

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_consolidate_session(
                {
                    "request": {
                        "stable_key": "session-import:abc",
                        "kind": "procedure",
                        "title": "Release process",
                        "max_events": 12,
                    }
                }
            )
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["stable_key"], "session-import:abc")
        self.assertEqual(payload["kind"], "procedure")
        self.assertEqual(payload["title"], "Release process")
        self.assertEqual(payload["max_events"], 12)
        self.assertFalse(payload["write"])
        self.assertEqual(payload["workspace"]["root_path"], "/tmp/autopsy-test")

    def test_worker_consolidate_session_refreshes_activity_after_write(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def build_consolidate_session_payload(self, _graph, *, tool, workspace, stable_key, kind, title, max_events, write):
                calls.append({"stable_key": stable_key, "kind": kind, "title": title, "max_events": max_events, "write": write})
                return {
                    "workspace": tool.workspace_payload(workspace),
                    "written": {"stable_key": "graph-note:consolidated"},
                    "workflow": {"status": "ok"},
                }

            def refresh_activity_snapshot(self, *_args, **_kwargs):
                calls.append("refresh")

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_consolidate_session(
                {
                    "request": {
                        "stable_key": "session-import:abc",
                        "kind": "summary",
                        "title": "Session summary",
                        "max_events": 8,
                        "write": True,
                    }
                }
            )
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["written"]["stable_key"], "graph-note:consolidated")
        self.assertEqual(payload["workspace"]["root_path"], "/tmp/autopsy-test")
        self.assertEqual(
            calls,
            [
                {
                    "stable_key": "session-import:abc",
                    "kind": "summary",
                    "title": "Session summary",
                    "max_events": 8,
                    "write": True,
                },
                "refresh",
            ],
        )

    def test_worker_consolidate_session_returns_blocked_payload_without_refresh(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def build_consolidate_session_payload(self, _graph, *, tool, workspace, stable_key, kind, title, max_events, write):
                calls.append({"stable_key": stable_key, "write": write})
                return {
                    "workspace": tool.workspace_payload(workspace),
                    "blocked": True,
                    "reason": "missing_memory_item",
                    "operation": "consolidate_session",
                    "stable_key": stable_key,
                    "write": write,
                    "workflow": {"status": "blocked_missing_memory_item"},
                }

            def refresh_activity_snapshot(self, *_args, **_kwargs):
                calls.append("refresh")

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_consolidate_session({"request": {"stable_key": "session-import:missing", "write": True}})
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["operation"], "consolidate_session")
        self.assertEqual(payload["reason"], "missing_memory_item")
        self.assertTrue(payload["write"])
        self.assertEqual(calls, [{"stable_key": "session-import:missing", "write": True}])

    def test_worker_import_session_preserves_dry_run_without_refresh(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        class Module:
            def build_import_session_payload(
                self,
                _graph,
                *,
                tool,
                workspace,
                path,
                title,
                source,
                max_events,
                dry_run,
                repository_root_path,
            ):
                return {
                    "workspace": tool.workspace_payload(workspace),
                    "path": path,
                    "title": title,
                    "source_label": source,
                    "max_events": max_events,
                    "dry_run": dry_run,
                    "repository_root_path": repository_root_path,
                    "workflow": {"status": "dry_run"},
                }

            def refresh_activity_snapshot(self, *_args, **_kwargs):
                raise AssertionError("dry-run import should not refresh activity")

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_import_session(
                {
                    "request": {
                        "path": "/tmp/session.jsonl",
                        "title": "Imported Session",
                        "source": "codex-jsonl",
                        "max_events": 25,
                        "dry_run": True,
                        "repo": "/tmp/repo",
                    }
                }
            )
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["path"], "/tmp/session.jsonl")
        self.assertEqual(payload["title"], "Imported Session")
        self.assertEqual(payload["source_label"], "codex-jsonl")
        self.assertEqual(payload["max_events"], 25)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["repository_root_path"], "/tmp/repo")
        self.assertEqual(payload["workspace"]["root_path"], "/tmp/autopsy-test")

    def test_worker_import_session_refreshes_activity_after_write(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def build_import_session_payload(
                self,
                _graph,
                *,
                tool,
                workspace,
                path,
                title,
                source,
                max_events,
                dry_run,
                repository_root_path,
            ):
                calls.append(
                    {
                        "path": path,
                        "title": title,
                        "source": source,
                        "max_events": max_events,
                        "dry_run": dry_run,
                        "repository_root_path": repository_root_path,
                    }
                )
                return {
                    "workspace": tool.workspace_payload(workspace),
                    "imported": {"session_node": "session-import:abc"},
                    "workflow": {"status": "ok"},
                }

            def refresh_activity_snapshot(self, *_args, **_kwargs):
                calls.append("refresh")

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_import_session(
                {
                    "request": {
                        "path": "/tmp/session.jsonl",
                        "title": "Imported Session",
                        "source": "codex-jsonl",
                        "max_events": 10,
                        "dry_run": False,
                        "repository_root_path": "/tmp/repo",
                    }
                }
            )
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["imported"]["session_node"], "session-import:abc")
        self.assertEqual(payload["workspace"]["root_path"], "/tmp/autopsy-test")
        self.assertEqual(
            calls,
            [
                {
                    "path": "/tmp/session.jsonl",
                    "title": "Imported Session",
                    "source": "codex-jsonl",
                    "max_events": 10,
                    "dry_run": False,
                    "repository_root_path": "/tmp/repo",
                },
                "refresh",
            ],
        )

    def test_worker_feedback_records_usage_for_existing_source(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def lookup_node_by_stable_key(self, _graph, stable_key):
                return {"stable_key": stable_key}

            def record_memory_feedback(self, _graph, stable_key, *, rating, note, source):
                calls.append({"stable_key": stable_key, "rating": rating, "note": note, "source": source})
                return {
                    "stable_key": stable_key,
                    "feedback_score": 1.0,
                    "last_feedback_rating": rating,
                    "last_feedback_note": note,
                    "last_feedback_source": source,
                }

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_feedback(
                {
                    "request": {
                        "stable_key": "graph-note:abc",
                        "rating": "useful",
                        "note": "used in relation recovery",
                        "source": "unit-test",
                    }
                }
            )
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["stable_key"], "graph-note:abc")
        self.assertEqual(payload["workspace"]["root_path"], "/tmp/autopsy-test")
        self.assertEqual(payload["workflow"]["status"], "ok")
        self.assertEqual(payload["workflow"]["next_step"], "done")
        self.assertEqual(payload["feedback"]["last_feedback_rating"], "useful")
        self.assertEqual(payload["feedback"]["last_feedback_note"], "used in relation recovery")
        self.assertEqual(payload["feedback"]["last_feedback_source"], "unit-test")
        self.assertEqual(calls, [{"stable_key": "graph-note:abc", "rating": "useful", "note": "used in relation recovery", "source": "unit-test"}])

    def test_worker_snapshot_route_preserves_stable_key_and_limit(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        class Module:
            def build_snapshot_payload(self, _graph, *, tool, workspace, stable_key, limit):
                return {
                    "workspace": tool.workspace_payload(workspace),
                    "stable_key": stable_key,
                    "limit": limit,
                }

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_snapshot({"request": {"stable_key": "graph-note:abc", "limit": 7}})
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["stable_key"], "graph-note:abc")
        self.assertEqual(payload["limit"], 7)
        self.assertEqual(payload["workspace"]["root_path"], "/tmp/autopsy-test")

    def test_worker_expire_missing_source_returns_blocked_payload_before_write(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def lookup_node_by_stable_key(self, *_args, **_kwargs):
                return None

            def blocked_missing_memory_item_payload_for_graph(self, _graph, *, stable_key, operation):
                return {"blocked": True, "reason": "missing_memory_item", "stable_key": stable_key, "operation": operation}

            def expire_graph_item_payload(self, *_args, **_kwargs):
                calls.append("expire")
                return {}

            def refresh_activity_snapshot(self, *_args, **_kwargs):
                calls.append("refresh")

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_expire({"request": {"stable_key": "graph-note:missing", "reason": "retired"}})
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["reason"], "missing_memory_item")
        self.assertEqual(payload["operation"], "expire")
        self.assertEqual(calls, [])

    def test_worker_expire_records_lifecycle_payload_for_existing_source(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def lookup_node_by_stable_key(self, _graph, stable_key):
                return {"stable_key": stable_key}

            def expire_graph_item_payload(self, _graph, *, tool, workspace, stable_key, expires_at, reason, clear):
                calls.append({"stable_key": stable_key, "expires_at": expires_at, "reason": reason, "clear": clear})
                return {
                    "workspace": tool.workspace_payload(workspace),
                    "lifecycle_operation": {
                        "operation": "clear_expiration" if clear else "expire",
                        "stable_key": stable_key,
                    },
                }

            def refresh_activity_snapshot(self, *_args, **_kwargs):
                calls.append("refresh")

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_expire(
                {
                    "request": {
                        "stable_key": "graph-note:abc",
                        "expires_at": "2026-07-01T00:00:00Z",
                        "reason": "superseded",
                        "clear": False,
                    }
                }
            )
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["lifecycle_operation"]["operation"], "expire")
        self.assertEqual(payload["workspace"]["root_path"], "/tmp/autopsy-test")
        self.assertEqual(
            calls,
            [
                {
                    "stable_key": "graph-note:abc",
                    "expires_at": "2026-07-01T00:00:00Z",
                    "reason": "superseded",
                    "clear": False,
                },
                "refresh",
            ],
        )

    def test_worker_pin_missing_source_returns_blocked_payload_before_write(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def lookup_node_by_stable_key(self, *_args, **_kwargs):
                return None

            def blocked_missing_memory_item_payload_for_graph(self, _graph, *, stable_key, operation):
                return {"blocked": True, "reason": "missing_memory_item", "stable_key": stable_key, "operation": operation}

            def pin_graph_item_payload(self, *_args, **_kwargs):
                calls.append("pin")
                return {}

            def refresh_activity_snapshot(self, *_args, **_kwargs):
                calls.append("refresh")

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_pin({"request": {"stable_key": "graph-note:missing", "label": "core"}})
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["reason"], "missing_memory_item")
        self.assertEqual(payload["operation"], "pin")
        self.assertEqual(calls, [])

    def test_worker_pin_records_core_memory_payload_for_existing_source(self):
        worker = load_worker_module()
        original = worker.run_falkor_operation
        original_context = worker.require_falkor_context

        class Tool:
            def workspace_payload(self, workspace):
                return workspace

        calls = []

        class Module:
            def lookup_node_by_stable_key(self, _graph, stable_key):
                return {"stable_key": stable_key}

            def pin_graph_item_payload(
                self,
                _graph,
                *,
                tool,
                workspace,
                stable_key,
                label,
                reason,
                description,
                block_limit,
                read_only,
                shared,
                clear,
            ):
                calls.append(
                    {
                        "stable_key": stable_key,
                        "label": label,
                        "reason": reason,
                        "description": description,
                        "block_limit": block_limit,
                        "read_only": read_only,
                        "shared": shared,
                        "clear": clear,
                    }
                )
                return {
                    "workspace": tool.workspace_payload(workspace),
                    "core_memory_operation": {
                        "operation": "unpin" if clear else "pin",
                        "stable_key": stable_key,
                    },
                }

            def refresh_activity_snapshot(self, *_args, **_kwargs):
                calls.append("refresh")

        module = Module()
        worker.require_falkor_context = lambda *_args, **_kwargs: (Tool(), module, {"root_path": "/tmp/autopsy-test"}, None, None, {"module": module, "graph_name": "autopsy_test"})
        worker.run_falkor_operation = lambda _falkor, operation: operation(object())
        try:
            payload = worker.handle_memory_pin(
                {
                    "request": {
                        "stable_key": "graph-note:abc",
                        "label": "core",
                        "reason": "always relevant",
                        "description": "Use when planning releases.",
                        "block_limit": "1200",
                        "read_only": False,
                        "shared": True,
                    }
                }
            )
        finally:
            worker.run_falkor_operation = original
            worker.require_falkor_context = original_context

        self.assertEqual(payload["core_memory_operation"]["operation"], "pin")
        self.assertEqual(payload["workspace"]["root_path"], "/tmp/autopsy-test")
        self.assertEqual(
            calls,
            [
                {
                    "stable_key": "graph-note:abc",
                    "label": "core",
                    "reason": "always relevant",
                    "description": "Use when planning releases.",
                    "block_limit": 1200,
                    "read_only": False,
                    "shared": True,
                    "clear": False,
                },
                "refresh",
            ],
        )

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
