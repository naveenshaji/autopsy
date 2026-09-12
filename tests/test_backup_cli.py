import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autopsy_memory import cli, backups


class BackupCLIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.support = Path(self.temp.name) / "Support"
        self.cloud = Path(self.temp.name) / "Cloud"
        self.cloud.mkdir()
        self.patch = mock.patch.object(cli, "APP_SUPPORT_DIR_DEFAULT", self.support)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.payload = {
            "schema_version": 1, "include_operational": True,
            "items": [{"stable_key": "test:write", "kind": "decision", "content": "Preserve this"}],
            "relations": [], "structural_edges": [],
        }

    def run_backup(self, *arguments):
        args = cli.build_parser().parse_args(["backup", *arguments])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            args.func(args)
        return json.loads(output.getvalue())

    def test_enable_then_write_mirrors_full_snapshot_and_status_needs_no_runtime(self):
        with mock.patch.object(cli, "open_workspace_graph", return_value=(None, {}, None, object())), mock.patch.object(cli, "export_memory_payload", return_value=self.payload) as export:
            receipt = self.run_backup("--enable-icloud", "--icloud-directory", str(self.cloud))
        self.assertTrue(export.call_args.kwargs["include_operational"])
        self.assertEqual(receipt["icloud"]["status"], "copied")
        self.assertEqual(Path(receipt["written"]).read_bytes(), Path(receipt["icloud"]["destination"]).read_bytes())
        with mock.patch.object(cli, "open_workspace_graph", side_effect=AssertionError("runtime opened")):
            status = self.run_backup("--status")
            retry = self.run_backup("--retry-icloud")
        self.assertTrue(status["backup"]["valid"])
        self.assertEqual(status["icloud"]["cloud_upload"], "unknown")
        self.assertEqual(retry["icloud"]["status"], "already_present")

    def test_new_write_is_backed_up_and_cloud_failure_preserves_local_copy(self):
        backups.configure_icloud_backup(app_support=self.support, enabled=True, directory=self.cloud)
        with mock.patch.object(cli, "export_memory_payload", return_value=self.payload), mock.patch.object(cli.backup_storage, "mirror_backup_to_icloud", return_value={"status": "error", "error": "drive offline"}):
            result = cli.attach_auto_backup_after_write({}, object(), {}, reason="test_write")
        self.assertEqual(result["auto_backup"]["status"], "created")
        self.assertTrue(backups.verify_backup_snapshot(result["auto_backup"]["written"], require_manifest=True)["valid"])
        self.assertFalse(result["workflow"]["complete"])
        self.assertIn("local backup is safe", result["write_recovery"]["message"])

    def test_partial_recovery_backups_rejected_before_opening_runtime(self):
        with mock.patch.object(cli, "open_workspace_graph", side_effect=AssertionError("runtime opened")):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.run_backup("--limit", "1")

    def test_health_does_not_claim_cloud_coverage_of_an_older_snapshot(self):
        state = {"count": 1, "latest": "/new.json", "valid": True, "age_seconds": 0,
                 "icloud": {"enabled": True, "last_attempt": {"status": "copied", "source": "/old.json"}}}
        self.assertEqual(cli.backup_freshness_status(state, item_count=1)["status"], "icloud_copy_pending")

    def test_checksum_corruption_is_visible_in_local_status(self):
        receipt = backups.write_backup_snapshot(self.payload, app_support=self.support)
        path = Path(receipt["written"])
        path.write_text(path.read_text().replace("Preserve this", "Modified text"))
        state = cli.latest_backup_status()
        self.assertFalse(state["valid"])
        self.assertIn("checksum", state["validation_error"])

    def test_changing_cloud_directory_requires_a_copy_in_the_new_destination(self):
        receipt = backups.write_backup_snapshot(self.payload, app_support=self.support)
        backups.configure_icloud_backup(app_support=self.support, enabled=True, directory=self.cloud)
        backups.mirror_backup_to_icloud(receipt["written"], app_support=self.support)
        other = Path(self.temp.name) / "NewCloud"
        other.mkdir()
        backups.configure_icloud_backup(app_support=self.support, enabled=True, directory=other)
        self.assertEqual(cli.backup_freshness_status(cli.latest_backup_status(), item_count=1)["status"], "icloud_copy_pending")

    def test_custom_output_can_be_retried_without_a_default_backup(self):
        custom = Path(self.temp.name) / "custom.json"
        backups.write_backup_snapshot(self.payload, app_support=self.support, output=custom)
        backups.configure_icloud_backup(app_support=self.support, enabled=True, directory=self.cloud)
        with mock.patch.object(cli, "open_workspace_graph", side_effect=AssertionError("runtime opened")):
            result = self.run_backup("--retry-icloud", "--output", str(custom))
        self.assertEqual(result["icloud"]["status"], "copied")


if __name__ == "__main__":
    unittest.main()
