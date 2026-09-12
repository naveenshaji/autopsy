"""Preservation regressions for portable memory snapshots and safe restoration."""
import contextlib
import io
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from autopsy_memory import backups, cli


WORKSPACE = {"id": "restore-test", "root_path": "/tmp/autopsy-restore-test", "slug": "restore-test", "title": "Restore test"}


def empty_payload():
    return {"schema_version": 1, "items": [], "relations": [], "structural_edges": []}


def canonical_snapshot(payload):
    items = {item["stable_key"]: {key: value for key, value in item.items() if key != "entity_id"} for item in payload["items"]}
    return items, Counter(json.dumps(edge, sort_keys=True) for edge in payload["relations"]), Counter(json.dumps(edge, sort_keys=True) for edge in payload["structural_edges"])


class RestoreValidationTests(unittest.TestCase):
    def test_preserves_empty_fields_and_text_boundaries(self):
        source = {"stable_key": "note:one", "content": "\n  indented text\n", "summary": "", "title": "", "created_at": "2024-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}
        item = cli.restore_item_from_raw(source, fallback_timestamp="fallback")
        for name in ("content", "summary", "title", "created_at"):
            self.assertEqual(item[name], source[name])
        self.assertEqual(item["timestamp"], source["updated_at"])

    def test_legacy_history_body_rebuilds_query_fields(self):
        record = {"target_stable_key": "note:one", "event": "UPDATE", "old_memory": "old", "new_memory": "new", "changed_fields": ["content"], "source": "cli"}
        item = cli.restore_item_from_raw({"stable_key": "history:one", "kind": cli.MEMORY_HISTORY_EVENT_KIND, "content": json.dumps(record)}, fallback_timestamp="fallback")
        self.assertEqual(item["properties"]["target_stable_key"], "note:one")
        self.assertEqual(json.loads(item["properties"]["changed_fields"]), ["content"])

    def test_malformed_edges_fail_before_replace_can_delete_items(self):
        bad_sections = [
            ("relations", [None]),
            ("relations", [{"from": "one", "relation": "refines"}]),
            ("relations", [{"from": "one", "to": "two", "relation": "refines", "valid_at": "tomorrow"}]),
            ("relations", [{"from": "one", "to": "two", "relation": "refines", "fact_rating": float("nan")}]),
            ("structural_edges", {}),
            ("structural_edges", None),
            ("structural_edges", [{"from": "one", "to": "two", "relation": "not_a_structural_edge"}]),
        ]
        for section, value in bad_sections:
            with self.subTest(section=section, value=value):
                payload = empty_payload()
                payload[section] = value
                graph = mock.Mock()
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    cli.restore_memory_payload(graph, workspace=WORKSPACE, input_path="backup.json", payload=payload, dry_run=False, replace=True, include_operational=True)
                graph.query.assert_not_called()

    def test_malformed_or_duplicate_items_fail_before_graph_access(self):
        for items in ([None], [{"kind": "decision"}], [{"stable_key": "one"}, {"stable_key": "one"}]):
            with self.subTest(items=items):
                graph = mock.Mock()
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    cli.restore_memory_payload(graph, workspace=WORKSPACE, input_path="backup.json", payload={**empty_payload(), "items": items}, dry_run=False, replace=True, include_operational=True)
                graph.query.assert_not_called()

    def test_existing_external_endpoints_are_available_in_dry_run(self):
        payload = {**empty_payload(), "items": [{"stable_key": "new", "kind": "decision"}], "relations": [{"from": "new", "to": "existing-external", "relation": "refines"}]}
        with mock.patch.object(cli, "existing_restore_keys", return_value={"existing-external"}) as existing:
            report = cli.restore_memory_payload(mock.Mock(), workspace=WORKSPACE, input_path="backup.json", payload=payload, dry_run=True, replace=False, include_operational=True)
        self.assertEqual(set(existing.call_args.args[1]), {"new", "existing-external"})
        self.assertEqual(report["counts"]["existing_items"], 0)
        self.assertEqual(report["counts"]["would_upsert_relations"], 1)
        self.assertEqual(report["counts"]["skipped_relations_missing_endpoint"], 0)

    def test_checksum_corruption_is_rejected_by_restore_and_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = backups.write_backup_snapshot(empty_payload(), app_support=root)
            path = Path(receipt["written"])
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.load_restore_json(str(path))
            self.assertFalse(cli.restore_input_summary_or_error(str(path), include_operational=True)["valid"])

    def test_protected_backup_cannot_lose_its_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = backups.write_backup_snapshot(empty_payload(), app_support=root)
            path = Path(receipt["written"])
            backups.backup_manifest_path(path).unlink()
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.load_restore_json(str(path))
            self.assertFalse(cli.restore_input_summary_or_error(str(path), include_operational=True)["valid"])

    def test_declared_inventory_mismatch_fails_before_graph_access(self):
        payload = {**empty_payload(), "counts": {"items": 1, "relations": 0, "structural_edges": 0}}
        graph = mock.Mock()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.restore_memory_payload(graph, workspace=WORKSPACE, input_path="backup.json", payload=payload, dry_run=False, replace=True, include_operational=True)
        graph.query.assert_not_called()

    def test_cli_honors_full_backup_inventory_for_offline_dry_run_and_apply(self):
        payload = {**empty_payload(), "include_operational": True, "items": [{"stable_key": "/tmp/repo", "kind": "repository", "content": "repository context"}]}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "backup.json"
            path.write_text(json.dumps(payload))
            parser = cli.build_parser()
            output = io.StringIO()
            with contextlib.redirect_stdout(output), mock.patch.object(cli, "open_workspace_graph_checked") as opened:
                cli.cmd_restore(parser.parse_args(["restore", str(path), "--dry-run", "--offline"]))
            opened.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["counts"]["restorable_items"], 1)
            for flags in ([], ["--dry-run"]):
                with self.subTest(flags=flags), contextlib.redirect_stdout(io.StringIO()), mock.patch.object(cli, "open_workspace_graph_checked", return_value=(None, WORKSPACE, None, mock.Mock())), mock.patch.object(cli, "ensure_runtime_indexes"), mock.patch.object(cli, "restore_memory_payload", return_value={"workflow": {"status": "test"}}) as restored:
                    cli.cmd_restore(parser.parse_args(["restore", str(path), *flags]))
                self.assertTrue(restored.call_args.kwargs["include_operational"])

    def test_guarded_export_holds_write_lock_and_uses_raw_graph(self):
        raw_graph = mock.Mock()
        guarded = cli.GuardedFalkorGraph(raw_graph, lite_path="unused.db", graph_name="test")
        events = []

        @contextlib.contextmanager
        def locked(_path):
            events.append("locked")
            yield
            events.append("unlocked")

        def export(graph, **_kwargs):
            self.assertIs(graph, raw_graph)
            self.assertEqual(events, ["locked"])
            return empty_payload()

        with mock.patch.object(cli, "memory_database_guard_enabled", return_value=True), mock.patch.object(cli, "memory_database_guard_lock", side_effect=locked), mock.patch.object(cli, "assert_memory_database_guard_current", return_value={"graph_generation": 7}), mock.patch.object(cli, "_export_memory_payload", side_effect=export):
            report = cli.export_memory_payload(guarded, workspace=WORKSPACE, include_operational=True)
        self.assertEqual(events, ["locked", "unlocked"])
        self.assertTrue(report["snapshot"]["consistent"])
        self.assertEqual(report["snapshot"]["generation"], 7)


class RestoreFalkorRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import redislite.falkordb_client  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("isolated Falkor round trip requires the installed runtime dependencies")
        cls.temporary = tempfile.TemporaryDirectory(prefix="autopsy-restore-integrity-")
        cli.configure_falkordblite_runtime()
        cls.client = cli.load_falkordblite()(str(Path(cls.temporary.name) / "test.db"))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temporary.cleanup()

    def test_full_round_trip_preserves_history_properties_parallel_edges_and_idempotence(self):
        source = self.client.select_graph("source")
        target = self.client.select_graph("target")
        created = "2024-01-01T00:00:00Z"
        updated = "2026-01-01T00:00:00Z"
        history = {"target_stable_key": "note:one", "event": "UPDATE", "old_memory": "old", "new_memory": "new", "changed_fields": '["content"]', "source": "unit"}
        for identifier, key, kind in ((1, "note:one", "decision"), (2, "note:two", "observation"), (3, "history:one", cli.MEMORY_HISTORY_EVENT_KIND), (4, "/tmp/repo", "repository")):
            cli.create_memory_node(source, entity_id=identifier, kind=kind, stable_key=key, label="", summary="", detail_content="\n  preserve instruction indentation\n", confidence=0.0, source_kind="unit", created_at=created, updated_at=updated, origin="unit", tags=["preserved"], metadata={"nested": {"one": "two"}})
        source.query("MATCH (n:MemoryNode {stable_key: 'note:one'}) SET n.access_count=9, n.feedback_score=3.5, n.last_access_query='preserve usage', n.session_role='user', n.pinned_at=$timestamp, n.pin_label='Core instructions'", params={"timestamp": created})
        source.query("MATCH (n:MemoryNode {stable_key: 'history:one'}) SET n += $properties", params={"properties": history})
        for timestamp in (created, updated, updated):
            cli.create_fact_edge(source, from_entity_id=1, to_entity_id=2, relation="refines", predicate="REFINES", fact_text="\n  original fact\n", timestamp=timestamp, origin="unit", fact_rating=0.9)
        for _ in range(2):
            cli.create_structural_edge(source, from_entity_id=1, to_entity_id=4, relation="about", timestamp=updated, origin="unit")
        cli.create_structural_edge(source, from_entity_id=3, to_entity_id=1, relation="history_of", timestamp=updated, origin="unit")
        snapshot = cli.export_memory_payload(source, workspace=WORKSPACE, include_operational=True)
        self.assertEqual(snapshot["counts"], {"items": 4, "relations": 3, "structural_edges": 3})
        dry_run = cli.restore_memory_payload(target, workspace=WORKSPACE, input_path="fixture.json", payload=snapshot, dry_run=True, replace=False, include_operational=True)
        self.assertEqual(dry_run["counts"]["would_create_items"], 4)
        report = cli.restore_memory_payload(target, workspace=WORKSPACE, input_path="fixture.json", payload=snapshot, dry_run=False, replace=False, include_operational=True)
        self.assertEqual(report["counts"]["created_relations"], 3)
        restored = cli.export_memory_payload(target, workspace=WORKSPACE, include_operational=True)
        self.assertEqual(canonical_snapshot(restored), canonical_snapshot(snapshot))
        records = cli.fetch_memory_history(target, "note:one", limit=10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event"], "UPDATE")
        self.assertEqual(records[0]["old_memory"], "old")
        second = cli.restore_memory_payload(target, workspace=WORKSPACE, input_path="fixture.json", payload=snapshot, dry_run=False, replace=False, include_operational=True)
        self.assertEqual(second["counts"]["created_relations"], 0)
        self.assertEqual(canonical_snapshot(cli.export_memory_payload(target, workspace=WORKSPACE, include_operational=True)), canonical_snapshot(snapshot))


if __name__ == "__main__":
    unittest.main()
