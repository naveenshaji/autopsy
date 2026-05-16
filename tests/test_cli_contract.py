import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autopsy_memory import cli
from autopsy_memory import doctor


class AutopsyCLIContractTests(unittest.TestCase):
    def test_memory_prefix_is_compatibility_alias(self):
        self.assertEqual(
            cli.normalized_cli_args(["memory", "consult", "--query", "release"]),
            ["consult", "--query", "release"],
        )
        self.assertEqual(cli.normalized_cli_args(["consult"]), ["consult"])

    def test_version_json_shape(self):
        parser = cli.build_parser()
        args = parser.parse_args(["version", "--json"])
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            args.func(args)
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["package"], "autopsy-memory")
        self.assertRegex(payload["version"], r"^\d+\.\d+\.\d+")

    def test_instructions_include_required_commands(self):
        parser = cli.build_parser()
        args = parser.parse_args(["instructions"])
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            args.func(args)
        output = stream.getvalue()
        self.assertIn("autopsy status --current-only", output)
        self.assertIn("autopsy consult --current-only", output)
        self.assertIn("autopsy benchmark --sample-size 5 --include-sync", output)

    def test_export_parser_accepts_release_options(self):
        parser = cli.build_parser()
        args = parser.parse_args(["export", "--limit", "5", "--include-operational", "--output", "/tmp/out.json"])
        self.assertEqual(args.command, "export")
        self.assertEqual(args.limit, 5)
        self.assertTrue(args.include_operational)
        self.assertEqual(args.output, "/tmp/out.json")

    def test_init_parser_accepts_cli_first_options(self):
        parser = cli.build_parser()
        args = parser.parse_args(["init", "--global", "--repo", "/tmp/repo", "--agent", "claude", "--dry-run", "--mcp"])
        self.assertEqual(args.command, "init")
        self.assertTrue(args.global_scope)
        self.assertEqual(args.repo_path, "/tmp/repo")
        self.assertEqual(args.agent, "claude")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.mcp)

    def test_nohit_identifier_queries_are_detected(self):
        self.assertTrue(cli.query_has_unlikely_identifier("nohit-autopsy-init-smoke-glass-cactus"))
        self.assertTrue(cli.query_has_unlikely_identifier("trace 0123456789abcdef"))
        self.assertFalse(cli.query_has_unlikely_identifier("release process decisions"))

    def test_doctor_rejects_legacy_app_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wrapper = Path(tmp_dir) / "autopsy"
            wrapper.write_text("#!/bin/sh\nAUTOPSY_BUNDLED_MEMORY_TOOL=/tmp/legacy\n", encoding="utf-8")
            original_which = doctor.shutil.which
            doctor.shutil.which = lambda _name: str(wrapper)
            try:
                payload = doctor.installed_autopsy_command_check()
            finally:
                doctor.shutil.which = original_which
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["legacy_wrapper"])
        self.assertIn("legacy app wrapper", payload["error"])


if __name__ == "__main__":
    unittest.main()
