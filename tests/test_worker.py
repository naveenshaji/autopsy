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


def context_graph_test_env(temp_dir: str) -> dict[str, str]:
    return {
        "AUTOPSY_CONTEXT_GRAPH_DIR": temp_dir,
        "AUTOPSY_CONTEXT_GRAPH_SETTINGS_PATH": str(Path(temp_dir) / "context-graph-settings.json"),
    }


class AutopsyMLWorkerFalkorStrictnessTests(unittest.TestCase):
    def test_int_request_argument_preserves_zero(self):
        worker = load_worker_module()
        self.assertEqual(worker.int_request_argument({"inspect_limit": 0}, "inspect_limit", 3), 0)
        self.assertEqual(worker.int_request_argument({}, "inspect_limit", 3), 3)

    def test_context_graph_event_store_records_only_allowlisted_command_context(self):
        worker = load_worker_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(worker.os.environ, context_graph_test_env(temp_dir)):
                file_read_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "file_read",
                    "title": "Read worker.py",
                    "metadata": {"path": "src/autopsy_memory/worker.py"},
                })
                file_search_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "file_search",
                    "title": "Search context graph",
                    "metadata": {"tool": "rg"},
                })
                command_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "title": "Run pytest",
                    "content": "rg context_graph_event src/autopsy_memory/worker.py",
                    "metadata": {
                        "stdout": "never persist output",
                        "tool": "rg",
                        "tool_use_id": "tool-1",
                        "turn_id": "turn-1",
                    },
                })
                memory_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "memory_consult",
                    "title": "Memory consulted",
                    "content": "legacy context graph",
                    "metadata": {"stable_key": "graph-note:one"},
                })

                snapshot = worker.build_context_graph_snapshot("thread-1")

        self.assertTrue(file_read_result["skipped"])
        self.assertEqual(file_read_result["reason"], "generic_events_disabled")
        self.assertTrue(file_search_result["skipped"])
        self.assertEqual(file_search_result["reason"], "generic_events_disabled")
        self.assertTrue(memory_result["skipped"])
        self.assertEqual(memory_result["reason"], "generic_events_disabled")
        self.assertIn("event", command_result)
        self.assertEqual(command_result["event"]["event_type"], "command")
        self.assertEqual(command_result["event"]["title"], "rg context_graph_event src/autopsy_memory/worker.py")
        self.assertEqual(command_result["event"]["content"], "rg context_graph_event src/autopsy_memory/worker.py")
        self.assertEqual(command_result["event"]["metadata"]["command"], "rg context_graph_event src/autopsy_memory/worker.py")
        self.assertEqual(command_result["event"]["metadata"]["capture"], "command_only")
        self.assertNotIn("stdout", command_result["event"]["metadata"])
        self.assertNotIn("tool", command_result["event"]["metadata"])
        self.assertNotIn("tool_use_id", command_result["event"]["metadata"])
        self.assertNotIn("turn_id", command_result["event"]["metadata"])

        self.assertEqual(snapshot["scopeTitle"], "Current Context")
        self.assertIn("focusNodeID", snapshot)
        self.assertEqual(snapshot["thread"]["thread_id"], "thread-1")
        self.assertEqual(snapshot["thread"]["event_count"], 1)
        self.assertEqual(len(snapshot["events"]), 1)
        nodes_by_kind = {}
        for node in snapshot["nodes"]:
            nodes_by_kind.setdefault(node["kind"], []).append(node)
        self.assertIn("turn_context", nodes_by_kind)
        self.assertIn("reasoning_context", nodes_by_kind)
        self.assertIn("command_context", nodes_by_kind)
        self.assertNotIn("command_batch", nodes_by_kind)
        self.assertNotIn("file_reads", nodes_by_kind)
        self.assertNotIn("file_searches", nodes_by_kind)
        self.assertNotIn("memory_context", nodes_by_kind)
        command_node = nodes_by_kind["command_context"][0]
        self.assertEqual(command_node["label"], "Search files")
        self.assertEqual(command_node["visualKind"], "file_search_context")
        self.assertIn("pattern: context_graph_event", command_node["detailChips"])
        self.assertIn("paths: src/autopsy_memory/worker.py", command_node["detailChips"])
        self.assertEqual(command_node["provenance"]["command"], "rg context_graph_event src/autopsy_memory/worker.py")
        self.assertEqual(command_node["sourceKind"], "context_graph_event")
        self.assertNotIn("Bash", json.dumps(command_node))
        self.assertEqual(nodes_by_kind["turn_context"][0]["stateFlags"], ["current", "in_progress"])
        relations = {connection["relation"] for connection in snapshot["connections"]}
        self.assertTrue({"reasoned_with", "consulted"}.issubset(relations))

    def test_context_graph_memory_command_renders_relation_nodes_from_enrichment(self):
        worker = load_worker_module()
        enrichment = {
            "items": [
                {"stable_key": "graph-note:one", "kind": "attempt", "label": "One", "summary": "attempt"},
                {"stable_key": "graph-note:two", "kind": "decision", "label": "Two", "summary": "decision"},
            ],
            "relations": [
                {
                    "from": "graph-note:one",
                    "to": "graph-note:two",
                    "relation": "depends_on",
                    "predicate": "depends_on",
                    "fact_text": "One depends on Two",
                }
            ],
        }
        with mock.patch.object(worker, "context_graph_memory_enrichment_for_command", return_value=enrichment):
            snapshot = worker.build_context_graph_snapshot_from_state({
                "thread_id": "thread-1",
                "created_at": "2026-06-06T00:00:00Z",
                "updated_at": "2026-06-06T00:00:01Z",
                "revision": 1,
                "events": [
                    {
                        "id": "memory-item",
                        "event_type": "command",
                        "content": "autopsy item graph-note:one",
                        "metadata": {"command": "autopsy item graph-note:one"},
                        "timestamp": "2026-06-06T00:00:00Z",
                    }
                ],
            })

        self.assertEqual(snapshot["events"][0]["content"], "autopsy item graph-note:one")
        command_node = next(node for node in snapshot["nodes"] if node["kind"] == "command_context")
        self.assertEqual(command_node["label"], "Inspect memory item")
        self.assertEqual(command_node["visualKind"], "memory_item_context")
        self.assertEqual(command_node["sourceRef"], "graph-note:one")
        memory_nodes = [node for node in snapshot["nodes"] if node["kind"] == "graph_memory"]
        self.assertEqual({node["label"] for node in memory_nodes}, {"One", "Two"})
        relations = {connection["relation"] for connection in snapshot["connections"]}
        self.assertTrue({"read_memory", "depends_on"}.issubset(relations))
        depends_on = next(connection for connection in snapshot["connections"] if connection["relation"] == "depends_on")
        self.assertEqual(depends_on["factText"], "One depends on Two")
        self.assertNotIn("memory_consult", json.dumps(snapshot["events"]))

    def test_context_graph_all_allowlisted_command_families_render_semantically(self):
        worker = load_worker_module()
        commands = [
            ("autopsy status --current-only", "memory_status_context", "Check memory status"),
            ("autopsy context --current-only --query graph", "memory_query_context", "Build memory context"),
            ("autopsy consult --current-only --query graph", "memory_query_context", "Consult memory"),
            ("autopsy search graph", "memory_search_context", "Search memory"),
            ("autopsy item graph-note:one", "memory_item_context", "Inspect memory item"),
            ("autopsy timeline graph-note:one", "memory_timeline_context", "Review memory timeline"),
            ("autopsy history graph-note:one", "memory_history_context", "Review memory history"),
            ("autopsy neighbors --stable-key graph-note:one", "memory_neighbors_context", "Read memory relations"),
            ("git status --short", "git_status_context", "Check git status"),
            ("git diff -- src/autopsy_memory/worker.py", "git_diff_context", "Review git diff"),
            ("git show HEAD -- src/autopsy_memory/worker.py", "git_show_context", "Inspect git object"),
            ("git log --oneline -5", "git_log_context", "Read git history"),
            ("rg context_graph src/autopsy_memory", "file_search_context", "Search files"),
            ("nl -ba src/autopsy_memory/worker.py", "file_read_context", "Read file"),
            ("sed -n '1,40p' src/autopsy_memory/worker.py", "file_read_context", "Read file"),
            ("cd apps/context-graph && rg graph src", "file_search_context", "Search files"),
        ]

        for command, visual_kind, label in commands:
            with self.subTest(command=command):
                self.assertTrue(worker.should_capture_context_graph_command(command))
                view = worker.context_graph_command_view(command)
                self.assertEqual(view["visual_kind"], visual_kind)
                self.assertEqual(view["label"], label)
                self.assertNotEqual(view["visual_kind"], "command_context")
                self.assertNotEqual(view["label"], "Run command")

        snapshot = worker.build_context_graph_snapshot_from_state({
            "thread_id": "thread-1",
            "created_at": "2026-06-06T00:00:00Z",
            "updated_at": "2026-06-06T00:00:16Z",
            "revision": len(commands),
            "events": [
                {
                    "id": f"command-{index}",
                    "event_type": "command",
                    "content": command,
                    "metadata": {"command": command},
                    "timestamp": f"2026-06-06T00:00:{index:02d}Z",
                }
                for index, (command, _visual_kind, _label) in enumerate(commands)
            ],
        })

        command_nodes = [node for node in snapshot["nodes"] if node["kind"] == "command_context"]
        self.assertEqual(len(command_nodes), len(commands) - 1)
        self.assertFalse(any(node.get("visualKind") == "command_context" for node in command_nodes))
        self.assertFalse(any(node.get("label") == "Run command" for node in command_nodes))
        file_read_nodes = [node for node in command_nodes if node["visualKind"] == "file_read_context"]
        self.assertEqual(len(file_read_nodes), 1)
        self.assertEqual(file_read_nodes[0]["label"], "Read files")
        self.assertTrue(file_read_nodes[0]["provenance"]["collapsed"])
        self.assertEqual(file_read_nodes[0]["provenance"]["command_count"], 2)
        self.assertIn("2 read commands", file_read_nodes[0]["detailChips"])

    def test_context_graph_event_store_skips_turn_completion_events(self):
        worker = load_worker_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(worker.os.environ, context_graph_test_env(temp_dir)):
                worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "rg context_graph_event src/autopsy_memory/worker.py",
                })
                completed = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "turn_completed",
                    "title": "Turn complete",
                    "content": "assistant text should not persist",
                    "run_id": "turn-1",
                    "metadata": {"turn_id": "turn-1", "status": "complete"},
                })
                snapshot = worker.build_context_graph_snapshot("thread-1")

        self.assertTrue(completed["skipped"])
        self.assertEqual(completed["reason"], "generic_events_disabled")
        self.assertEqual(snapshot["thread"]["event_count"], 1)
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertEqual(snapshot["events"][0]["event_type"], "command")
        self.assertNotIn("assistant text should not persist", json.dumps(snapshot))
        nodes_by_kind = {}
        for node in snapshot["nodes"]:
            nodes_by_kind.setdefault(node["kind"], []).append(node)
        self.assertIn("turn_context", nodes_by_kind)
        self.assertIn("reasoning_context", nodes_by_kind)
        self.assertIn("command_context", nodes_by_kind)
        self.assertNotIn("command_batch", nodes_by_kind)
        self.assertEqual(nodes_by_kind["turn_context"][0]["stateFlags"], ["current", "in_progress"])

    def test_context_graph_snapshot_ignores_stale_lifecycle_events_for_turn_scoping(self):
        worker = load_worker_module()
        snapshot = worker.build_context_graph_snapshot_from_state({
            "thread_id": "thread-1",
            "created_at": "2026-06-06T00:00:00Z",
            "updated_at": "2026-06-06T00:00:02Z",
            "revision": 2,
            "events": [
                {
                    "id": "command-1",
                    "event_type": "command",
                    "content": "rg context_graph_event src/autopsy_memory/worker.py",
                    "run_id": "turn-1",
                    "metadata": {"command": "rg context_graph_event src/autopsy_memory/worker.py"},
                    "timestamp": "2026-06-06T00:00:00Z",
                },
                {
                    "id": "turn-complete",
                    "event_type": "turn_completed",
                    "title": "Turn complete",
                    "content": "assistant text should not render",
                    "run_id": "turn-1",
                    "timestamp": "2026-06-06T00:00:01Z",
                },
            ],
        })

        self.assertEqual(snapshot["thread"]["event_count"], 1)
        self.assertEqual([event["id"] for event in snapshot["events"]], ["command-1"])
        self.assertIn("In Progress - 1 active event", snapshot["nodes"][0]["summary"])
        self.assertEqual(snapshot["nodes"][0]["stateFlags"], ["current", "in_progress"])
        self.assertNotIn("assistant text should not render", json.dumps(snapshot))

    def test_context_graph_event_store_skips_non_allowlisted_commands(self):
        worker = load_worker_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(worker.os.environ, context_graph_test_env(temp_dir)):
                result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "ls -la",
                })
                curl_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "curl -s http://127.0.0.1/context-graph | sed -n '1,20p'",
                })
                pipeline_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "rg context_graph_event src/autopsy_memory/worker.py | head -20",
                })
                write_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "autopsy capture-outcome --kind attempt --title write",
                })
                redirect_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "rg context_graph_event src/autopsy_memory/worker.py > /tmp/context.txt",
                })
                substitution_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "rg $(autopsy item graph-note:secret) src/autopsy_memory/worker.py",
                })
                background_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "rg context_graph_event src/autopsy_memory/worker.py & npm run build",
                })
                multiline_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "rg context_graph_event src/autopsy_memory/worker.py\nnpm run build",
                })
                snapshot = worker.build_context_graph_snapshot("thread-1")

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "command_not_allowlisted")
        self.assertTrue(curl_result["skipped"])
        self.assertEqual(curl_result["reason"], "command_not_allowlisted")
        self.assertTrue(pipeline_result["skipped"])
        self.assertEqual(pipeline_result["reason"], "command_not_allowlisted")
        self.assertTrue(write_result["skipped"])
        self.assertEqual(write_result["reason"], "command_not_allowlisted")
        self.assertTrue(redirect_result["skipped"])
        self.assertEqual(redirect_result["reason"], "command_not_allowlisted")
        self.assertTrue(substitution_result["skipped"])
        self.assertEqual(substitution_result["reason"], "command_not_allowlisted")
        self.assertTrue(background_result["skipped"])
        self.assertEqual(background_result["reason"], "command_not_allowlisted")
        self.assertTrue(multiline_result["skipped"])
        self.assertEqual(multiline_result["reason"], "command_not_allowlisted")
        self.assertEqual(snapshot["thread"]["event_count"], 0)
        self.assertEqual(snapshot["events"], [])

    def test_context_graph_event_store_prunes_stale_generic_events_on_write(self):
        worker = load_worker_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(worker.os.environ, context_graph_test_env(temp_dir)):
                thread_file = worker.context_graph_thread_file("thread-1")
                thread_file.parent.mkdir(parents=True)
                thread_file.write_text(json.dumps({
                    "thread_id": "thread-1",
                    "created_at": "2026-06-06T00:00:00Z",
                    "updated_at": "2026-06-06T00:00:01Z",
                    "revision": 1,
                    "events": [
                        {
                            "id": "old-generic",
                            "event_type": "file_read",
                            "title": "Read worker.py",
                            "content": "file contents should not remain",
                            "timestamp": "2026-06-06T00:00:00Z",
                        },
                        {
                            "id": "old-non-allowlisted",
                            "event_type": "command",
                            "content": "ls -la",
                            "timestamp": "2026-06-06T00:00:01Z",
                        },
                    ],
                }), encoding="utf-8")

                result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "rg context_graph_event src/autopsy_memory/worker.py",
                    "timestamp": "2026-06-06T00:00:02Z",
                })
                saved = json.loads(thread_file.read_text(encoding="utf-8"))
                snapshot = worker.build_context_graph_snapshot("thread-1")

        self.assertIn("event", result)
        self.assertEqual(result["thread"]["event_count"], 1)
        self.assertEqual([event["id"] for event in saved["events"]], [result["event"]["id"]])
        self.assertNotIn("file contents should not remain", json.dumps(saved))
        self.assertNotIn("ls -la", json.dumps(saved))
        self.assertEqual(snapshot["thread"]["event_count"], 1)
        self.assertEqual(snapshot["allEventCount"], 1)
        self.assertEqual(len(snapshot["events"]), 1)

    def test_context_graph_event_store_rejects_generic_event_with_allowed_command(self):
        worker = load_worker_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(worker.os.environ, context_graph_test_env(temp_dir)):
                result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "file_read",
                    "title": "Read worker.py",
                    "content": "rg context_graph_event src/autopsy_memory/worker.py",
                    "metadata": {
                        "command": "rg context_graph_event src/autopsy_memory/worker.py",
                        "path": "src/autopsy_memory/worker.py",
                    },
                })
                snapshot = worker.build_context_graph_snapshot("thread-1")

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "generic_events_disabled")
        self.assertEqual(snapshot["thread"]["event_count"], 0)
        self.assertEqual(snapshot["events"], [])
        self.assertNotIn("src/autopsy_memory/worker.py", json.dumps(snapshot))

    def test_context_graph_event_store_skips_action_commands(self):
        worker = load_worker_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(worker.os.environ, context_graph_test_env(temp_dir)):
                result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "./.venv/bin/python -m pytest tests/test_worker.py",
                })
                build_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "cd apps/context-graph && npm run build",
                })
                mixed_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "npm run build && rg context_graph_event src/autopsy_memory/worker.py",
                })
                sed_write_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "sed -i '' 's/a/b/' src/autopsy_memory/worker.py",
                })
                git_output_result = worker.record_context_graph_event({
                    "thread_id": "thread-1",
                    "event_type": "command",
                    "content": "git diff --output /tmp/diff.txt",
                })
                snapshot = worker.build_context_graph_snapshot("thread-1")

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "command_not_allowlisted")
        self.assertTrue(build_result["skipped"])
        self.assertEqual(build_result["reason"], "command_not_allowlisted")
        self.assertTrue(mixed_result["skipped"])
        self.assertEqual(mixed_result["reason"], "command_not_allowlisted")
        self.assertTrue(sed_write_result["skipped"])
        self.assertEqual(sed_write_result["reason"], "command_not_allowlisted")
        self.assertTrue(git_output_result["skipped"])
        self.assertEqual(git_output_result["reason"], "command_not_allowlisted")
        self.assertEqual(len(snapshot["events"]), 0)

    def test_context_graph_snapshot_deduplicates_codex_hook_tool_lifecycle_events(self):
        worker = load_worker_module()
        snapshot = worker.build_context_graph_snapshot_from_state({
            "thread_id": "thread-1",
            "created_at": "2026-06-06T00:00:00Z",
            "updated_at": "2026-06-06T00:00:01Z",
            "revision": 2,
            "events": [
                {
                    "id": "pre-event",
                    "event_type": "command",
                    "content": "rg context_graph tests/test_worker.py",
                    "status": "in_progress",
                    "run_id": "turn-1",
                    "metadata": {
                        "command": "rg context_graph tests/test_worker.py",
                        "hook_event_name": "PreToolUse",
                        "tool_use_id": "tool-1",
                    },
                    "timestamp": "2026-06-06T00:00:00Z",
                },
                {
                    "id": "post-event",
                    "event_type": "command",
                    "content": "rg context_graph tests/test_worker.py",
                    "status": "complete",
                    "run_id": "turn-1",
                    "metadata": {
                        "command": "rg context_graph tests/test_worker.py",
                        "hook_event_name": "PostToolUse",
                        "tool_use_id": "tool-1",
                    },
                    "timestamp": "2026-06-06T00:00:01Z",
                },
            ],
        })

        self.assertEqual(snapshot["allEventCount"], 1)
        self.assertEqual(snapshot["thread"]["event_count"], 1)
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertEqual(snapshot["events"][0]["id"], "post-event")
        self.assertEqual(snapshot["events"][0]["status"], "complete")
        self.assertIn("1 active event", snapshot["nodes"][0]["summary"])

    def test_context_graph_snapshot_scopes_current_turn_to_latest_run_id_without_turn_completion(self):
        worker = load_worker_module()
        snapshot = worker.build_context_graph_snapshot_from_state({
            "thread_id": "thread-1",
            "created_at": "2026-06-06T00:00:00Z",
            "updated_at": "2026-06-06T00:00:03Z",
            "revision": 3,
            "events": [
                {
                    "id": "old-run-command",
                    "event_type": "command",
                    "content": "rg old src/autopsy_memory/worker.py",
                    "run_id": "turn-1",
                    "metadata": {"command": "rg old src/autopsy_memory/worker.py"},
                    "timestamp": "2026-06-06T00:00:00Z",
                },
                {
                    "id": "current-status",
                    "event_type": "command",
                    "content": "autopsy status --current-only",
                    "run_id": "turn-2",
                    "metadata": {"command": "autopsy status --current-only"},
                    "timestamp": "2026-06-06T00:00:01Z",
                },
                {
                    "id": "current-consult",
                    "event_type": "command",
                    "content": "autopsy consult --current-only --query graph",
                    "run_id": "turn-2",
                    "metadata": {"command": "autopsy consult --current-only --query graph"},
                    "timestamp": "2026-06-06T00:00:02Z",
                },
            ],
        })

        self.assertEqual(snapshot["allEventCount"], 2)
        self.assertEqual(snapshot["thread"]["event_count"], 2)
        self.assertEqual([event["id"] for event in snapshot["events"]], ["current-status", "current-consult"])
        self.assertTrue(all(event["run_id"] == "turn-2" for event in snapshot["events"]))
        self.assertNotIn("rg old", json.dumps(snapshot["events"]))
        self.assertIn("In Progress - 2 active events", snapshot["nodes"][0]["summary"])
        command_nodes = [node for node in snapshot["nodes"] if node["kind"] == "command_context"]
        self.assertEqual([node["label"] for node in command_nodes], ["Check memory status", "Consult memory"])
        self.assertEqual([node["visualKind"] for node in command_nodes], ["memory_status_context", "memory_query_context"])
        self.assertEqual([node["provenance"]["command"] for node in command_nodes], [
            "autopsy status --current-only",
            "autopsy consult --current-only --query graph",
        ])
        self.assertIn("query: graph", command_nodes[1]["detailChips"])
        self.assertFalse(any(node["kind"] == "command_batch" for node in snapshot["nodes"]))

    def test_context_graph_snapshot_multi_turn_setting_keeps_prior_run_commands(self):
        worker = load_worker_module()
        snapshot = worker.build_context_graph_snapshot_from_state({
            "thread_id": "thread-1",
            "created_at": "2026-06-06T00:00:00Z",
            "updated_at": "2026-06-06T00:00:03Z",
            "revision": 3,
            "_context_graph_settings": {"multi_turn": True},
            "events": [
                {
                    "id": "old-run-command",
                    "event_type": "command",
                    "content": "rg old src/autopsy_memory/worker.py",
                    "run_id": "turn-1",
                    "metadata": {"command": "rg old src/autopsy_memory/worker.py"},
                    "timestamp": "2026-06-06T00:00:00Z",
                },
                {
                    "id": "current-status",
                    "event_type": "command",
                    "content": "autopsy status --current-only",
                    "run_id": "turn-2",
                    "metadata": {"command": "autopsy status --current-only"},
                    "timestamp": "2026-06-06T00:00:01Z",
                },
                {
                    "id": "current-consult",
                    "event_type": "command",
                    "content": "autopsy consult --current-only --query graph",
                    "run_id": "turn-2",
                    "metadata": {"command": "autopsy consult --current-only --query graph"},
                    "timestamp": "2026-06-06T00:00:02Z",
                },
            ],
        })

        self.assertEqual(snapshot["turnScope"], "multi_turn")
        self.assertEqual(snapshot["scopeTitle"], "Multi-Turn Context")
        self.assertEqual(snapshot["allEventCount"], 3)
        self.assertEqual([event["id"] for event in snapshot["events"]], ["old-run-command", "current-status", "current-consult"])
        self.assertFalse(any(node["label"] == "Multi-Turn Context" for node in snapshot["nodes"]))
        turn_nodes = [node for node in snapshot["nodes"] if node["kind"] == "history_context"]
        self.assertEqual([node["label"] for node in turn_nodes], ["Turn 1"])
        self.assertEqual([node["visualKind"] for node in turn_nodes], ["turn_group_context"])
        self.assertEqual([node["sourceRef"] for node in turn_nodes], ["turn-1"])
        self.assertEqual(turn_nodes[0]["stateFlags"], ["complete"])
        current_turn_node = next(node for node in snapshot["nodes"] if node["label"] == "Current Turn")
        self.assertEqual(current_turn_node["kind"], "turn_context")
        self.assertEqual(current_turn_node["sourceRef"], "turn-2")
        self.assertEqual(current_turn_node["stateFlags"], ["current", "in_progress"])
        self.assertTrue(current_turn_node["isFocus"])
        self.assertEqual(snapshot["focusNodeID"], current_turn_node["id"])
        command_nodes = [node for node in snapshot["nodes"] if node["kind"] == "command_context"]
        self.assertEqual([node["label"] for node in command_nodes], ["Search files", "Check memory status", "Consult memory"])
        node_id_by_label = {node["label"]: node["id"] for node in snapshot["nodes"]}
        consulted_edges = {
            connection["fromNodeID"]: connection["toNodeID"]
            for connection in snapshot["connections"]
            if connection["relation"] == "consulted"
        }
        self.assertEqual(consulted_edges[node_id_by_label["Search files"]], node_id_by_label["Turn 1"])
        self.assertEqual(consulted_edges[node_id_by_label["Check memory status"]], node_id_by_label["Current Turn"])
        self.assertEqual(consulted_edges[node_id_by_label["Consult memory"]], node_id_by_label["Current Turn"])
        turn_edges = [
            connection for connection in snapshot["connections"]
            if connection["relation"] == "previous_turn"
        ]
        self.assertEqual({connection["fromNodeID"] for connection in turn_edges}, {node_id_by_label["Turn 1"]})
        self.assertEqual({connection["toNodeID"] for connection in turn_edges}, {node_id_by_label["Current Turn"]})

    def test_context_graph_snapshot_keeps_manual_no_run_command_after_latest_run_start(self):
        worker = load_worker_module()
        snapshot = worker.build_context_graph_snapshot_from_state({
            "thread_id": "thread-1",
            "created_at": "2026-06-06T00:00:00Z",
            "updated_at": "2026-06-06T00:00:03Z",
            "revision": 3,
            "events": [
                {
                    "id": "old-run-command",
                    "event_type": "command",
                    "content": "rg old src/autopsy_memory/worker.py",
                    "run_id": "turn-1",
                    "metadata": {"command": "rg old src/autopsy_memory/worker.py"},
                    "timestamp": "2026-06-06T00:00:00Z",
                },
                {
                    "id": "current-status",
                    "event_type": "command",
                    "content": "autopsy status --current-only",
                    "run_id": "turn-2",
                    "metadata": {"command": "autopsy status --current-only"},
                    "timestamp": "2026-06-06T00:00:01Z",
                },
                {
                    "id": "manual-git-status",
                    "event_type": "command",
                    "content": "git status --short",
                    "metadata": {"command": "git status --short"},
                    "timestamp": "2026-06-06T00:00:02Z",
                },
            ],
        })

        self.assertEqual([event["id"] for event in snapshot["events"]], ["current-status", "manual-git-status"])
        self.assertNotIn("rg old", json.dumps(snapshot["events"]))
        command_nodes = [node for node in snapshot["nodes"] if node["kind"] == "command_context"]
        self.assertEqual([node["label"] for node in command_nodes], ["Check memory status", "Check git status"])
        self.assertEqual([node["visualKind"] for node in command_nodes], ["memory_status_context", "git_status_context"])
        self.assertEqual([node["provenance"]["command"] for node in command_nodes], [
            "autopsy status --current-only",
            "git status --short",
        ])
        self.assertFalse(any(node["kind"] == "command_batch" for node in snapshot["nodes"]))

    def test_context_graph_snapshot_caps_rendered_command_window(self):
        worker = load_worker_module()
        events = [
            {
                "id": f"command-{index}",
                "event_type": "command",
                "content": f"rg token-{index} src/autopsy_memory/worker.py",
                "metadata": {"command": f"rg token-{index} src/autopsy_memory/worker.py"},
                "run_id": "turn-1",
                "timestamp": f"2026-06-06T00:00:{index:02d}Z",
            }
            for index in range(worker.CONTEXT_GRAPH_MAX_RENDERED_COMMAND_EVENTS + 6)
        ]
        snapshot = worker.build_context_graph_snapshot_from_state({
            "thread_id": "thread-1",
            "created_at": "2026-06-06T00:00:00Z",
            "updated_at": "2026-06-06T00:00:40Z",
            "revision": len(events),
            "events": events,
        })

        self.assertEqual(snapshot["allEventCount"], len(events))
        self.assertEqual(snapshot["thread"]["event_count"], worker.CONTEXT_GRAPH_MAX_RENDERED_COMMAND_EVENTS)
        self.assertEqual(len(snapshot["events"]), worker.CONTEXT_GRAPH_MAX_RENDERED_COMMAND_EVENTS)
        self.assertEqual(snapshot["events"][0]["id"], "command-6")
        self.assertEqual(snapshot["events"][-1]["id"], f"command-{len(events) - 1}")
        command_nodes = [node for node in snapshot["nodes"] if node["kind"] == "command_context"]
        self.assertEqual(len(command_nodes), worker.CONTEXT_GRAPH_MAX_RENDERED_COMMAND_EVENTS)
        self.assertNotIn("token-0", json.dumps(snapshot["nodes"]))

    def test_context_graph_snapshot_ignores_stale_generic_and_non_allowlisted_events(self):
        worker = load_worker_module()
        snapshot = worker.build_context_graph_snapshot_from_state({
            "thread_id": "thread-1",
            "created_at": "2026-06-06T00:00:00Z",
            "updated_at": "2026-06-06T00:00:03Z",
            "revision": 3,
            "events": [
                {
                    "id": "evt-1",
                    "event_type": "file_read",
                    "title": "Read secret prompt text",
                    "content": "rg context_graph tests/test_worker.py",
                    "metadata": {"command": "rg context_graph tests/test_worker.py"},
                    "timestamp": "2026-06-06T00:00:00Z",
                },
                {
                    "id": "evt-2",
                    "event_type": "command",
                    "title": "ls -la",
                    "content": "ls -la",
                    "timestamp": "2026-06-06T00:00:01Z",
                },
                {
                    "id": "evt-3",
                    "event_type": "command",
                    "content": "rg context_graph tests/test_worker.py",
                    "metadata": {"command": "rg context_graph tests/test_worker.py", "tool": "Bash"},
                    "timestamp": "2026-06-06T00:00:02Z",
                },
                {
                    "id": "evt-4",
                    "event_type": "memory_consult",
                    "title": "Memory contents",
                    "content": "generic memory text should not render",
                    "timestamp": "2026-06-06T00:00:03Z",
                },
            ],
        })

        self.assertEqual(snapshot["allEventCount"], 1)
        self.assertEqual(snapshot["thread"]["event_count"], 1)
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertEqual(snapshot["events"][0]["id"], "evt-3")
        labels = {node["label"] for node in snapshot["nodes"]}
        kinds = {node["kind"] for node in snapshot["nodes"]}
        self.assertIn("Search files", labels)
        self.assertIn("turn_context", kinds)
        self.assertIn("reasoning_context", kinds)
        self.assertIn("command_context", kinds)
        self.assertNotIn("command_batch", kinds)
        self.assertNotIn("file_reads", kinds)
        self.assertNotIn("memory_context", kinds)
        self.assertEqual(sum(1 for node in snapshot["nodes"] if node["kind"] == "command_context"), 1)
        command_node = next(node for node in snapshot["nodes"] if node["kind"] == "command_context")
        self.assertEqual(command_node["label"], "Search files")
        self.assertEqual(command_node["visualKind"], "file_search_context")
        self.assertEqual(command_node["provenance"]["command"], "rg context_graph tests/test_worker.py")
        self.assertNotIn("Bash", json.dumps(command_node))
        self.assertFalse(any("ls -la" in label for label in labels))
        self.assertFalse(any("secret prompt text" in label for label in labels))

    def test_context_graph_viewer_static_root_supports_direct_script_workers(self):
        worker = load_worker_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "autopsy_memory"
            static_dir = package_dir / "context_graph_viewer" / "static"
            static_dir.mkdir(parents=True)
            (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")

            with mock.patch.dict(worker.os.environ, {}, clear=True):
                with mock.patch.object(worker, "__file__", str(package_dir / "worker.py")):
                    with mock.patch.object(worker.resources, "files", side_effect=ModuleNotFoundError("missing")):
                        self.assertEqual(
                            worker.context_graph_viewer_static_root().resolve(),
                            static_dir.resolve(),
                        )

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
