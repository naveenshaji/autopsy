import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock


def load_generator():
    path = Path(__file__).resolve().parents[1] / "scripts" / "update-homebrew-formula.py"
    spec = importlib.util.spec_from_file_location("autopsy_homebrew_formula_generator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HomebrewFormulaGeneratorTests(unittest.TestCase):
    def test_wheel_resources_are_rendered_for_explicit_wheel_install(self):
        generator = load_generator()
        original_report = generator.pip_dependency_report
        try:
            generator.pip_dependency_report = lambda _python: [
                {
                    "metadata": {"name": "sentence-transformers", "version": "5.5.1"},
                    "download_info": {
                        "url": "https://files.pythonhosted.org/packages/example/sentence_transformers-5.5.1-py3-none-any.whl",
                        "archive_info": {"hashes": {"sha256": "abc123"}},
                    },
                },
                {
                    "metadata": {"name": "autopsy-memory", "version": "0.1.22"},
                    "download_info": {"url": "file:///tmp/autopsy"},
                },
            ]
            resources = generator.resource_blocks("python3.12")
        finally:
            generator.pip_dependency_report = original_report

        self.assertIn('resource "sentence-transformers"', resources)
        self.assertIn("using: :nounzip", resources)
        self.assertNotIn('resource "autopsy-memory"', resources)

        formula = generator.render_formula("0.1.22", "https://example.com/autopsy.tar.gz", "deadbeef", resources)
        self.assertIn("def autopsy_pip_install(target)", formula)
        self.assertIn("def autopsy_python", formula)
        self.assertIn("def validate_autopsy_python!", formula)
        self.assertIn('system autopsy_python, "-m", "pip"', formula)
        self.assertIn("virtualenv_create(libexec, autopsy_python", formula)
        self.assertIn("Autopsy requires Homebrew python@3.12", formula)
        self.assertIn("depends_on macos: :sonoma", formula)
        self.assertIn("autopsy_pip_install autopsy_resource_target", formula)
        self.assertIn('next if resource.name == "falkordb-macos-arm64v8"', formula)
        self.assertIn('with_env(PATH: "#{bin}:#{ENV.fetch("PATH", "")}")', formula)
        self.assertIn("autopsy install --smoke-test", formula)
        self.assertIn("install --dry-run --skip-menubar --smoke-test --skip-write-smoke", formula)
        self.assertIn('if install_payload["smoke_test"]', formula)
        self.assertIn('install_payload.dig("smoke_test", "reason") == "dry_run"', formula)
        self.assertIn("empty_status = JSON.parse", formula)
        self.assertIn('empty_status.dig("status", "summary")', formula)
        self.assertIn('empty_status.dig("workflow", "next_step")', formula)
        self.assertIn('empty_status.dig("onboarding", "empty")', formula)

    def test_formula_generator_rejects_wrong_python_version(self):
        generator = load_generator()
        original_report = generator.python_platform_report
        try:
            generator.python_platform_report = lambda _python: {
                "python_version": "3.13",
                "macos_version": "14.7",
                "system": "Darwin",
                "machine": "arm64",
            }
            with self.assertRaisesRegex(RuntimeError, "requires Python 3.12"):
                generator.validate_formula_python("python3.13")
        finally:
            generator.python_platform_report = original_report

    def test_formula_generator_rejects_non_arm_macos(self):
        generator = load_generator()
        original_report = generator.python_platform_report
        try:
            generator.python_platform_report = lambda _python: {
                "python_version": "3.12",
                "macos_version": "",
                "system": "Linux",
                "machine": "x86_64",
            }
            with self.assertRaisesRegex(RuntimeError, "Apple Silicon macOS"):
                generator.validate_formula_python("python3.12")
        finally:
            generator.python_platform_report = original_report

    def test_formula_generator_accepts_macos_arm_python_312(self):
        generator = load_generator()
        original_report = generator.python_platform_report
        report = {
            "python_version": "3.12",
            "macos_version": "14.7",
            "system": "Darwin",
            "machine": "arm64",
        }
        try:
            generator.python_platform_report = lambda _python: report
            self.assertEqual(generator.validate_formula_python("python3.12"), report)
        finally:
            generator.python_platform_report = original_report

    def test_formula_generator_rejects_macos_before_sonoma(self):
        generator = load_generator()
        original_report = generator.python_platform_report
        try:
            generator.python_platform_report = lambda _python: {
                "python_version": "3.12",
                "macos_version": "13.6",
                "system": "Darwin",
                "machine": "arm64",
            }
            with self.assertRaisesRegex(RuntimeError, "macOS 14 Sonoma"):
                generator.validate_formula_python("python3.12")
        finally:
            generator.python_platform_report = original_report

    def test_pip_dependency_report_uses_homebrew_constraints(self):
        generator = load_generator()
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            report_path = Path(command[command.index("--report") + 1])
            report_path.write_text(json.dumps({"install": []}), encoding="utf-8")

        with mock.patch.object(generator.subprocess, "run", side_effect=fake_run):
            self.assertEqual(generator.pip_dependency_report("python3.12"), [])

        command = calls[0]
        self.assertIn("--constraint", command)
        self.assertEqual(
            command[command.index("--constraint") + 1],
            str(generator.HOMEBREW_CONSTRAINTS),
        )

    def test_homebrew_constraints_file_must_exist_and_have_entries(self):
        generator = load_generator()
        original_constraints = generator.HOMEBREW_CONSTRAINTS
        try:
            generator.HOMEBREW_CONSTRAINTS = Path("/tmp/autopsy-missing-constraints.txt")
            with self.assertRaisesRegex(RuntimeError, "constraints file is missing"):
                generator.homebrew_constraints_path()

            with mock.patch.object(
                generator.Path, "exists", return_value=True
            ), mock.patch.object(
                generator.Path, "read_text", return_value="# empty\n"
            ):
                generator.HOMEBREW_CONSTRAINTS = Path("/tmp/autopsy-empty-constraints.txt")
                with self.assertRaisesRegex(RuntimeError, "constraints file is empty"):
                    generator.homebrew_constraints_path()
        finally:
            generator.HOMEBREW_CONSTRAINTS = original_constraints


if __name__ == "__main__":
    unittest.main()
