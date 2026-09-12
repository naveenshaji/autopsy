import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from autopsy_memory import backups


class BackupStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app_support = self.root / "Autopsy"
        self.cloud = self.root / "iCloud"
        self.cloud.mkdir()
        self.payload = {"schema_version": 1, "items": [{"stable_key": "memory:one", "body": "Keep café and 日本語"}], "relations": []}

    def snapshot(self, **kwargs):
        return backups.write_backup_snapshot(self.payload, app_support=self.app_support, **kwargs)

    def enable(self):
        return backups.configure_icloud_backup(app_support=self.app_support, enabled=True, directory=self.cloud)

    def test_snapshot_preserves_payload_and_uses_verified_private_compact_bytes(self):
        receipt = self.snapshot()
        path = Path(receipt["written"])
        restored = json.loads(path.read_bytes())
        self.assertEqual(restored.pop("backup_integrity"), {"schema_version": 1, "algorithm": "sha256", "manifest_required": True})
        self.assertEqual(restored, self.payload)
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(receipt["manifest"]).stat().st_mode), 0o600)
        self.assertLess(path.stat().st_size, len(json.dumps(json.loads(path.read_bytes()), indent=2).encode()))
        self.assertEqual(list(path.parent.glob("autopsy-memory-*.json")), [path])
        self.assertTrue(backups.verify_backup_snapshot(path, require_manifest=True)["valid"])

    def test_same_timestamp_still_produces_unique_paths(self):
        first = backups.unique_backup_path(app_support=self.app_support, timestamp="20260912T120000Z")
        second = backups.unique_backup_path(app_support=self.app_support, timestamp="20260912T120000Z")
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, self.app_support / "Backups")

    def test_existing_explicit_path_and_manifest_are_never_overwritten(self):
        output = self.root / "explicit.json"
        first = self.snapshot(output=output)
        original = output.read_bytes()
        with self.assertRaises(FileExistsError):
            self.snapshot(output=output)
        self.assertEqual(output.read_bytes(), original)
        orphan = self.root / "orphan.json"
        backups.backup_manifest_path(orphan).write_text("preserve")
        with self.assertRaises(FileExistsError):
            self.snapshot(output=orphan)
        self.assertFalse(orphan.exists())
        self.assertEqual(backups.backup_manifest_path(orphan).read_text(), "preserve")
        self.assertTrue(backups.verify_backup_snapshot(first["written"])["valid"])

    def test_corruption_is_detected_even_if_json_remains_valid(self):
        path = Path(self.snapshot()["written"])
        path.write_text('{"items":[]}')
        verification = backups.verify_backup_snapshot(path)
        self.assertFalse(verification["valid"])
        self.assertIn("checksum", verification["error"])

    def test_manifest_corruption_and_missing_manifest_are_distinguished(self):
        path = Path(self.snapshot()["written"])
        manifest = backups.backup_manifest_path(path)
        manifest.write_text("broken")
        self.assertFalse(backups.verify_backup_snapshot(path)["valid"])
        manifest.unlink()
        self.assertFalse(backups.verify_backup_snapshot(path, require_manifest=True)["valid"])
        self.assertFalse(backups.verify_backup_snapshot(path)["valid"])
        path = self.root / "legacy.json"
        path.write_text(json.dumps(self.payload))
        legacy = backups.verify_backup_snapshot(path)
        self.assertTrue(legacy["valid"])
        self.assertEqual(legacy["integrity"], "legacy_unverified")

    def test_invalid_json_and_nan_cannot_be_new_snapshots(self):
        with self.assertRaises(ValueError):
            backups.write_backup_snapshot({"invalid": float("nan")}, app_support=self.app_support)
        self.assertFalse((self.app_support / "Backups").exists())
        legacy = self.root / "broken.json"
        legacy.write_text("{")
        self.assertFalse(backups.verify_backup_snapshot(legacy)["valid"])

    def test_fsync_failure_never_publishes_partial_snapshot_or_leaks_temporary_files(self):
        path = self.root / "failed.json"
        with mock.patch.object(backups.os, "fsync", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                self.snapshot(output=path)
        self.assertFalse(path.exists())
        self.assertEqual(list(self.root.glob(".autopsy-backup-*.tmp")), [])

    def test_competing_writer_cannot_be_overwritten_between_check_and_publication(self):
        output = self.root / "racing.json"
        original_link = backups.os.link

        def competing_publish(source, target):
            if Path(target) == output:
                Path(target).write_bytes(b"other installation's snapshot")
            return original_link(source, target)

        with mock.patch.object(backups.os, "link", side_effect=competing_publish):
            with self.assertRaises(FileExistsError):
                self.snapshot(output=output)
        self.assertEqual(output.read_bytes(), b"other installation's snapshot")
        self.assertEqual(list(self.root.glob(".autopsy-backup-*.tmp")), [])

    def test_local_sidecar_failure_cannot_publish_a_fresh_unprotected_snapshot(self):
        output = self.app_support / "Backups" / "autopsy-memory-protected.json"
        original_write = backups._atomic_write_bytes

        def fail_manifest(path, *args, **kwargs):
            if path.suffix == ".sha256":
                raise OSError("sidecar disk failure")
            return original_write(path, *args, **kwargs)

        with mock.patch.object(backups, "_atomic_write_bytes", side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, "sidecar disk failure"):
                self.snapshot(output=output)
        self.assertFalse(output.exists())
        self.assertEqual(list(output.parent.glob("autopsy-memory-*.json")), [])
        self.assertFalse(backups.verify_backup_snapshot(output)["valid"])

    def test_disabled_by_default_is_read_only_and_never_copies(self):
        status = backups.icloud_backup_status(app_support=self.app_support)
        self.assertFalse(status["enabled"])
        self.assertFalse(self.app_support.exists())
        local = Path(self.snapshot()["written"])
        receipt = backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        self.assertEqual(receipt["status"], "disabled")
        self.assertEqual(list(self.cloud.iterdir()), [])

    def test_settings_persist_independently_and_disable_preserves_path_and_memories(self):
        status = self.enable()
        self.assertTrue(status["enabled"])
        local = Path(self.snapshot()["written"])
        mirrored = backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        backups.configure_icloud_backup(app_support=self.app_support, enabled=False)
        status = backups.icloud_backup_status(app_support=self.app_support)
        self.assertFalse(status["enabled"])
        self.assertEqual(status["directory"], str(self.cloud))
        self.assertTrue(local.exists())
        self.assertTrue(Path(mirrored["destination"]).exists())
        self.assertEqual(status["latest_success"]["destination"], mirrored["destination"])
        self.assertEqual(set(json.loads(Path(status["settings_path"]).read_text())), {"schema_version", "enabled", "directory"})

    def test_verified_mirror_is_idempotent_and_never_claims_remote_upload(self):
        self.enable()
        local = Path(self.snapshot()["written"])
        receipt = backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        destination = Path(receipt["destination"])
        self.assertEqual(receipt["status"], "copied")
        self.assertEqual(destination.read_bytes(), local.read_bytes())
        self.assertTrue(receipt["local_copy_verified"])
        self.assertEqual(receipt["cloud_upload"], "unknown")
        self.assertFalse(receipt["remote_verified"])
        modified_at = destination.stat().st_mtime_ns
        again = backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        self.assertEqual(again["status"], "already_present")
        self.assertEqual(destination.stat().st_mtime_ns, modified_at)
        self.assertEqual(len(list(self.cloud.iterdir())), 2)

    def test_missing_default_drive_is_not_created_and_error_is_persisted(self):
        home = self.root / "home"
        with mock.patch.object(backups.Path, "home", return_value=home):
            status = backups.configure_icloud_backup(app_support=self.app_support, enabled=True)
            self.assertFalse(status["directory_status"]["available"])
            receipt = backups.mirror_backup_to_icloud(self.snapshot()["written"], app_support=self.app_support)
            self.assertEqual(receipt["status"], "error")
            self.assertIn("unavailable", receipt["error"])
            self.assertFalse(home.exists())
            status = backups.icloud_backup_status(app_support=self.app_support)
            self.assertEqual(status["last_attempt"]["status"], "error")

    def test_available_default_drive_gets_backup_subfolder(self):
        home = self.root / "home"
        with mock.patch.object(backups.Path, "home", return_value=home):
            cloud_root = backups.default_icloud_directory().parent.parent
            cloud_root.mkdir(parents=True)
            backups.configure_icloud_backup(app_support=self.app_support, enabled=True)
            receipt = backups.mirror_backup_to_icloud(self.snapshot()["written"], app_support=self.app_support)
            self.assertEqual(receipt["status"], "copied")
            self.assertTrue(Path(receipt["destination"]).is_file())

    def test_missing_custom_directory_is_not_recreated_under_existing_parent(self):
        missing = self.root / "disconnected-drive"
        backups.configure_icloud_backup(app_support=self.app_support, enabled=True, directory=missing)
        receipt = backups.mirror_backup_to_icloud(self.snapshot()["written"], app_support=self.app_support)
        self.assertEqual(receipt["status"], "error")
        self.assertFalse(missing.exists())

    def test_corrupt_source_does_not_reach_cloud(self):
        self.enable()
        local = Path(self.snapshot()["written"])
        local.write_text('{"items":[]}')
        receipt = backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        self.assertEqual(receipt["status"], "error")
        self.assertIn("local backup verification", receipt["error"])
        self.assertEqual(list(self.cloud.iterdir()), [])

    def test_failed_mirror_preserves_last_success_and_local_snapshot(self):
        self.enable()
        first = Path(self.snapshot()["written"])
        successful = backups.mirror_backup_to_icloud(first, app_support=self.app_support)
        second = Path(self.snapshot()["written"])
        original_write = backups._atomic_write_bytes

        def fail_cloud(path, *args, **kwargs):
            if self.cloud in path.parents:
                raise OSError("cloud disk full")
            return original_write(path, *args, **kwargs)

        with mock.patch.object(backups, "_atomic_write_bytes", side_effect=fail_cloud):
            receipt = backups.mirror_backup_to_icloud(second, app_support=self.app_support)
        self.assertEqual(receipt["status"], "error")
        self.assertTrue(backups.verify_backup_snapshot(second, require_manifest=True)["valid"])
        status = backups.icloud_backup_status(app_support=self.app_support)
        self.assertEqual(status["last_attempt"]["error"], "cloud disk full")
        self.assertEqual(status["latest_success"]["destination"], successful["destination"])

    def test_corrupt_existing_cloud_snapshot_is_preserved(self):
        self.enable()
        local = Path(self.snapshot()["written"])
        receipt = backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        destination = Path(receipt["destination"])
        destination.write_text("preserve corrupt forensic bytes")
        receipt = backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        self.assertEqual(receipt["status"], "error")
        self.assertEqual(destination.read_text(), "preserve corrupt forensic bytes")
        self.assertFalse(receipt["local_copy_verified"])

    def test_retry_completes_matching_snapshot_after_sidecar_write_failure(self):
        self.enable()
        local = Path(self.snapshot()["written"])
        original_write = backups._atomic_write_bytes

        def fail_manifest(path, *args, **kwargs):
            if self.cloud in path.parents and path.suffix == ".sha256":
                raise OSError("interrupted sidecar write")
            return original_write(path, *args, **kwargs)

        with mock.patch.object(backups, "_atomic_write_bytes", side_effect=fail_manifest):
            first = backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        self.assertEqual(first["status"], "error")
        destination = Path(first["destination"])
        self.assertEqual(destination.read_bytes(), local.read_bytes())
        self.assertFalse(backups.backup_manifest_path(destination).exists())
        again = backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        self.assertEqual(again["status"], "already_present")
        self.assertTrue(backups.verify_backup_snapshot(destination, require_manifest=True)["valid"])

    def test_status_reads_only_small_receipts_without_opening_snapshots(self):
        self.enable()
        local = Path(self.snapshot()["written"])
        backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        with mock.patch.object(backups.Path, "read_bytes", side_effect=AssertionError("must not hydrate cloud files")):
            status = backups.icloud_backup_status(app_support=self.app_support)
        self.assertEqual(status["latest_success"]["status"], "copied")

    def test_corrupt_settings_fail_closed_without_upload(self):
        self.enable()
        settings = self.app_support / "Config" / "backup-settings.json"
        settings.write_text('{"schema_version":1,"enabled":"true","directory":"/tmp"}')
        receipt = backups.mirror_backup_to_icloud(self.snapshot()["written"], app_support=self.app_support)
        self.assertEqual(receipt["status"], "error")
        self.assertEqual(list(self.cloud.iterdir()), [])
        self.assertEqual(backups.icloud_backup_status(app_support=self.app_support)["status"], "error")

    def test_receipt_failure_is_reported_without_hiding_verified_copy(self):
        self.enable()
        local = self.snapshot()["written"]
        with mock.patch.object(backups, "_persist_mirror_receipt", side_effect=OSError("local receipt unavailable")):
            receipt = backups.mirror_backup_to_icloud(local, app_support=self.app_support)
        self.assertEqual(receipt["status"], "copied")
        self.assertTrue(receipt["local_copy_verified"])
        self.assertEqual(receipt["receipt_error"], "local receipt unavailable")


if __name__ == "__main__":
    unittest.main()
