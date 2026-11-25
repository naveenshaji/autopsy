import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autopsy_memory import onnx_models  # noqa: E402


class FakeHub:
    """Stands in for huggingface_hub.snapshot_download."""

    def __init__(self, local: Path | None, remote: Path):
        self.local = local
        self.remote = remote
        self.calls: list[dict] = []

    def snapshot_download(self, model_name, local_files_only=False, allow_patterns=None):
        self.calls.append({"local_files_only": local_files_only, "allow_patterns": allow_patterns})
        if local_files_only:
            if self.local is None:
                raise FileNotFoundError(model_name)
            return str(self.local)
        return str(self.remote)


class OnnxSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.local = self.root / "local"
        self.remote = self.root / "remote"
        for path in (self.local, self.remote):
            path.mkdir()
            (path / "tokenizer.json").write_text("{}")
        (self.remote / "onnx").mkdir()
        (self.remote / "onnx" / "model.onnx").write_bytes(b"onnx")

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, hub: FakeHub, onnx_file="onnx/model.onnx", env=None):
        module = types.SimpleNamespace(snapshot_download=hub.snapshot_download)
        environment = {"HF_HUB_OFFLINE": "", "AUTOPSY_ONNX_FILE": ""}
        environment.update(env or {})
        with mock.patch.dict(sys.modules, {"huggingface_hub": module}), mock.patch.dict("os.environ", environment, clear=False):
            return onnx_models._snapshot("org/model", onnx_file)

    def test_cached_snapshot_without_onnx_export_downloads_it(self):
        hub = FakeHub(self.local, self.remote)
        self.assertEqual(self.snapshot(hub), self.remote)
        self.assertEqual(len(hub.calls), 2)
        self.assertIn("onnx/model.onnx", hub.calls[1]["allow_patterns"])

    def test_named_onnx_file_is_part_of_the_download(self):
        hub = FakeHub(None, self.remote)
        self.snapshot(hub, onnx_file="onnx/model_O3.onnx")
        self.assertIn("onnx/model_O3.onnx", hub.calls[-1]["allow_patterns"])
        self.assertIn("onnx/model_O3.onnx_data", hub.calls[-1]["allow_patterns"])

    def test_complete_cached_snapshot_is_used_without_download(self):
        (self.local / "onnx").mkdir()
        (self.local / "onnx" / "model.onnx").write_bytes(b"onnx")
        hub = FakeHub(self.local, self.remote)
        self.assertEqual(self.snapshot(hub), self.local)
        self.assertEqual(len(hub.calls), 1)

    def test_offline_uses_cache_even_when_export_is_missing(self):
        hub = FakeHub(self.local, self.remote)
        self.assertEqual(self.snapshot(hub, env={"HF_HUB_OFFLINE": "1"}), self.local)
        self.assertEqual(len(hub.calls), 1)
        with self.assertRaises(RuntimeError):
            onnx_models._model_file(self.local, None)


class RerankActivationTests(unittest.TestCase):
    def activation(self, config):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            if config is not None:
                (path / "config.json").write_text(json.dumps(config))
            return onnx_models._sentence_transformers_sigmoid(path)

    def test_declared_identity_keeps_raw_logits(self):
        self.assertFalse(self.activation({"id2label": {"0": "LABEL_0"}, "sbert_ce_default_activation_function": "torch.nn.modules.linear.Identity"}))

    def test_declared_activation_in_sentence_transformers_block(self):
        self.assertTrue(self.activation({"sentence_transformers": {"activation_fn": "torch.nn.modules.activation.Sigmoid"}}))

    def test_single_label_without_declaration_uses_sigmoid(self):
        self.assertTrue(self.activation({"id2label": {"0": "LABEL_0"}}))

    def test_multi_label_or_missing_config_keeps_raw_logits(self):
        self.assertFalse(self.activation({"id2label": {"0": "A", "1": "B"}}))
        self.assertFalse(self.activation(None))


if __name__ == "__main__":
    unittest.main()
