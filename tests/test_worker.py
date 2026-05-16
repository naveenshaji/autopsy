import importlib.util
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True


def load_worker_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "src" / "autopsy_memory" / "worker.py"
    spec = importlib.util.spec_from_file_location("autopsy_ml_worker_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AutopsyMLWorkerFalkorStrictnessTests(unittest.TestCase):
    def test_consult_fails_loudly_when_falkor_context_is_unavailable(self):
        worker = load_worker_module()
        original = worker.require_falkor_context

        def fail_falkor_context(*_args, **_kwargs):
            raise RuntimeError("falkor unavailable")

        worker.require_falkor_context = fail_falkor_context
        try:
            with self.assertRaisesRegex(RuntimeError, "falkor unavailable"):
                worker.handle_memory_consult({"request": {"query": "strict falkor"}})
        finally:
            worker.require_falkor_context = original


if __name__ == "__main__":
    unittest.main()
