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
        hook_targets = init_module.codex_hook_targets(
            home=root / "home",
            repo_path=root / "repo",
            install_global=True,
            agent="all",
        )
        self.assertEqual([target.scope for target in hook_targets], ["global", "repo"])
        self.assertEqual(hook_targets[0].path, root / "home" / ".codex" / "hooks.json")
        self.assertEqual(hook_targets[1].path, root / "repo" / ".codex" / "hooks.json")

    def test_codex_hook_json_patch_preserves_other_hooks(self):
        existing = """{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python other.py"
          },
          {
            "type": "command",
            "command": "autopsy codex-hook"
          }
        ]
      }
    ]
  }
}
"""
        new_text, action = init_module.patch_codex_hooks_json(existing, autopsy_command="/opt/homebrew/bin/autopsy")
        self.assertEqual(action, "updated")
        payload = json.loads(new_text)
        stop_handlers = [
            handler
            for group in payload["hooks"]["Stop"]
            for handler in group["hooks"]
        ]
        self.assertIn("python other.py", {handler["command"] for handler in stop_handlers})
        self.assertEqual(
            sum(1 for handler in stop_handlers if handler["command"] == "/opt/homebrew/bin/autopsy codex-hook"),
            0,
        )
        self.assertNotIn("UserPromptSubmit", payload["hooks"])
        self.assertNotIn("PreCompact", payload["hooks"])
        self.assertIn("PreToolUse", payload["hooks"])
        self.assertNotIn("PermissionRequest", payload["hooks"])
        self.assertIn("PostToolUse", payload["hooks"])
        self.assertIn("Stop", payload["hooks"])

    def test_codex_hook_json_patch_can_remove_autopsy_hooks(self):
        existing = """{
  "hooks": {
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "autopsy codex-hook"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python other.py"
          }
        ]
      }
    ]
  }
}
"""
        new_text, action = init_module.patch_codex_hooks_json(existing, enabled=False)
        self.assertEqual(action, "removed")
        payload = json.loads(new_text)
        self.assertNotIn("PostToolUse", payload["hooks"])
        self.assertIn("Stop", payload["hooks"])

    def test_codex_managed_block_uses_in_app_browser_instruction_in_cli_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "context-graph-settings.json"
            settings_path.write_text(json.dumps({"enabled": True, "mode": "cli"}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"AUTOPSY_CONTEXT_GRAPH_SETTINGS_PATH": str(settings_path)}):
                block = init_module.managed_instruction_block("codex")
        self.assertIn("Codex in-app Browser", block)
        self.assertIn("not `web.run` and not macOS `open`", block)
        self.assertIn("connect to the `iab` browser", block)
        self.assertIn("tab.goto(URL)", block)
        self.assertIn("Do not pass `--open`", block)
        self.assertNotIn('context-graph-url --thread-id "<thread-id>" --open', block)

    def test_codex_managed_block_suppresses_context_event_in_hook_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "context-graph-settings.json"
            settings_path.write_text(json.dumps({"enabled": True, "mode": "hooks"}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"AUTOPSY_CONTEXT_GRAPH_SETTINGS_PATH": str(settings_path)}):
                block = init_module.managed_instruction_block("codex")
        self.assertIn("Do not call `autopsy context-event`", block)
        self.assertIn("Codex hooks", block)
        self.assertIn("context-graph-url --codex-current", block)
        self.assertIn("Do not choose, invent, derive, or manually pass", block)
        self.assertNotIn('context-graph-url --thread-id "<thread-id>"', block)

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
            settings_path = Path(tmp_dir) / "context-graph-settings.json"
            settings_path.write_text(json.dumps({"enabled": True, "mode": "hooks"}), encoding="utf-8")
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
            with (
                mock.patch.object(init_module.Path, "home", return_value=home),
                mock.patch.dict(os.environ, {"AUTOPSY_CONTEXT_GRAPH_SETTINGS_PATH": str(settings_path)}),
            ):
                payload = init_module.build_init_payload(args)

            targets = payload["targets"]
            hooks = payload["hooks"]
            self.assertEqual({target["agent"] for target in targets}, {"codex", "claude", "gemini", "opencode"})
            self.assertTrue(all(target["scope"] == "global" for target in targets))
            self.assertTrue(all(target["state"] == "managed" for target in targets))
            self.assertTrue(all(target["action"] == "added" for target in targets))
            self.assertEqual(len(hooks), 1)
            self.assertEqual(hooks[0]["agent"], "codex")
            self.assertEqual(hooks[0]["scope"], "global")
            self.assertEqual(hooks[0]["state"], "managed")
            for target in targets:
                path = Path(target["path"])
                self.assertTrue(path.exists(), target)
                self.assertIn(init_module.MANAGED_START, path.read_text(encoding="utf-8"))
            hook_path = home / ".codex" / "hooks.json"
            self.assertTrue(hook_path.exists())
            hook_payload = json.loads(hook_path.read_text(encoding="utf-8"))
            self.assertNotIn("UserPromptSubmit", hook_payload["hooks"])
            self.assertNotIn("PreCompact", hook_payload["hooks"])
            self.assertEqual(set(hook_payload["hooks"]), {"PreToolUse", "PostToolUse"})

    def test_dry_run_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir) / "repo"
            repo.mkdir()
            settings_path = Path(tmp_dir) / "context-graph-settings.json"
            settings_path.write_text(json.dumps({"enabled": True, "mode": "hooks"}), encoding="utf-8")
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
            with mock.patch.dict(os.environ, {"AUTOPSY_CONTEXT_GRAPH_SETTINGS_PATH": str(settings_path)}):
                payload = init_module.build_init_payload(args)
            target_path = repo / "AGENTS.md"
            hook_path = repo / ".codex" / "hooks.json"
            self.assertFalse(target_path.exists())
            self.assertFalse(hook_path.exists())
            self.assertEqual(payload["targets"][0]["action"], "added")
            self.assertTrue(payload["targets"][0]["dry_run"])
            self.assertEqual(payload["hooks"][0]["action"], "added")
            self.assertTrue(payload["hooks"][0]["dry_run"])

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
