import importlib.util
import unittest
from pathlib import Path


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
        self.assertIn("autopsy_pip_install autopsy_resource_target", formula)
        self.assertIn('next if resource.name == "falkordb-macos-arm64v8"', formula)
        self.assertIn('with_env(PATH: "#{bin}:#{ENV.fetch("PATH", "")}")', formula)
        self.assertIn("autopsy install --smoke-test", formula)


if __name__ == "__main__":
    unittest.main()
