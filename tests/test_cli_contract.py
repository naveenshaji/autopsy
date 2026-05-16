import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autopsy_memory import cli


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


if __name__ == "__main__":
    unittest.main()
