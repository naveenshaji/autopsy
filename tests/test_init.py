import argparse
import tempfile
import unittest
from pathlib import Path

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
        paths = {target.path.name for target in targets}
        self.assertEqual(paths, {"AGENTS.md", "CLAUDE.md"})
        self.assertEqual(len(targets), 4)

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


if __name__ == "__main__":
    unittest.main()
