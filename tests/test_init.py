import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autopsy_memory import init as init_module


class AutopsyInitTests(unittest.TestCase):
    def test_managed_block_is_added_and_then_updated(self):
        block = init_module.managed_instruction_block()
        new_text, action = init_module.patch_managed_block("Existing\n", block)
        self.assertEqual(action, "added")
        self.assertIn(init_module.MANAGED_START, new_text)
        updated_text, updated_action = init_module.patch_managed_block(new_text, block)
        self.assertEqual(updated_action, "unchanged")
        self.assertEqual(updated_text, new_text)

    def test_legacy_unmanaged_block_is_replaced(self):
        block = init_module.managed_instruction_block()
        existing = """# Project Instructions

## Autopsy Memory Usage

Old memory instructions.

## Other Section

Keep this.
"""
        new_text, action = init_module.patch_managed_block(existing, block)
        self.assertEqual(action, "updated")
        self.assertIn(init_module.MANAGED_START, new_text)
        self.assertNotIn("Old memory instructions", new_text)
        self.assertIn("## Other Section", new_text)

    def test_managed_update_removes_legacy_duplicate(self):
        block = init_module.managed_instruction_block()
        existing = f"""## Autopsy Memory Usage

Old memory instructions.

{block}"""
        new_text, action = init_module.patch_managed_block(existing, block)
        self.assertEqual(action, "updated")
        self.assertEqual(new_text.count(init_module.MANAGED_START), 1)
        self.assertNotIn("Old memory instructions", new_text)

    def test_target_selection_for_global_and_repo_all_agents(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets = init_module.instruction_targets(
                home=root / "home",
                repo_path=root / "repo",
                install_global=True,
                agent="all",
            )
        agents_by_scope = {
            scope: {target.agent for target in targets if target.scope == scope}
            for scope in ("global", "repo")
        }
        self.assertEqual(agents_by_scope["global"], {"codex", "claude", "gemini", "opencode"})
        self.assertEqual(agents_by_scope["repo"], {"codex", "claude", "gemini", "opencode", "cursor", "copilot", "windsurf"})
        self.assertEqual(len(targets), 11)

    def test_global_cursor_has_no_file_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets = init_module.instruction_targets(
                home=root / "home",
                repo_path=None,
                install_global=True,
                agent="cursor",
            )
        self.assertEqual(targets, [])

    def test_build_init_payload_writes_all_global_agent_targets(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir) / "home"
            args = argparse.Namespace(
                global_scope=True,
                repo_path=None,
                agent="all",
                print_instructions=False,
                mcp=False,
                dry_run=False,
                check=False,
                yes=False,
                smoke_test=False,
                skip_write_smoke=True,
                autopsy_command_path="/opt/homebrew/bin/autopsy",
            )
            with mock.patch.object(init_module.Path, "home", return_value=home):
                payload = init_module.build_init_payload(args)

            targets = payload["targets"]
            self.assertEqual({target["agent"] for target in targets}, {"codex", "claude", "gemini", "opencode"})
            self.assertTrue(all(target["scope"] == "global" for target in targets))
            self.assertTrue(all(target["state"] == "managed" for target in targets))
            self.assertTrue(all(target["action"] == "added" for target in targets))
            for target in targets:
                path = Path(target["path"])
                self.assertTrue(path.exists(), target)
                self.assertIn(init_module.MANAGED_START, path.read_text(encoding="utf-8"))

    def test_dry_run_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir) / "repo"
            repo.mkdir()
            args = argparse.Namespace(
                global_scope=False,
                repo_path=str(repo),
                agent="codex",
                print_instructions=False,
                mcp=False,
                dry_run=True,
                check=False,
                yes=False,
                smoke_test=False,
                skip_write_smoke=True,
            )
            payload = init_module.build_init_payload(args)
            target_path = repo / "AGENTS.md"
            self.assertFalse(target_path.exists())
            self.assertEqual(payload["targets"][0]["action"], "added")
            self.assertTrue(payload["targets"][0]["dry_run"])

    def test_smoke_tests_use_explicit_autopsy_command(self):
        with (
            mock.patch.object(init_module, "run_command", return_value={"ok": True}) as run_mock,
            mock.patch.object(init_module, "consult_abstention_check", return_value={"ok": True}) as consult_mock,
        ):
            init_module.smoke_tests(skip_write=True, autopsy_command="/opt/homebrew/bin/autopsy")

        self.assertEqual(run_mock.call_args_list[0].args[0], ["/opt/homebrew/bin/autopsy", "doctor"])
        self.assertEqual(
            run_mock.call_args_list[1].args[0],
            ["/opt/homebrew/bin/autopsy", "status", "--current-only", "--limit", "1", "--section-limit", "1"],
        )
        consult_mock.assert_called_once_with(autopsy_command="/opt/homebrew/bin/autopsy")

    def test_build_init_payload_passes_explicit_autopsy_command_to_smoke_tests(self):
        args = argparse.Namespace(
            global_scope=False,
            repo_path=None,
            agent="codex",
            print_instructions=False,
            mcp=False,
            dry_run=True,
            check=False,
            yes=False,
            smoke_test=True,
            skip_write_smoke=True,
            autopsy_command_path="/opt/homebrew/bin/autopsy",
        )
        with mock.patch.object(init_module, "smoke_tests", return_value=[]) as smoke_mock:
            payload = init_module.build_init_payload(args)

        self.assertEqual(payload["autopsy_command"], "/opt/homebrew/bin/autopsy")
        smoke_mock.assert_called_once_with(skip_write=True, autopsy_command="/opt/homebrew/bin/autopsy")


if __name__ == "__main__":
    unittest.main()
