"""Embedding and reranking models on ONNX Runtime, without torch.

The ``onnx`` provider runs the same Hugging Face models as ``sentence_transformers``
(their published ``onnx/model.onnx`` exports) through onnxruntime and tokenizers.
Vectors and scores match sentence-transformers, but a resident worker needs about a
fifth of the memory: no torch, no autograd, and no allocator arena that keeps the
largest batch it ever saw.

The objects expose the small part of the sentence-transformers interface Autopsy
uses: ``SentenceTransformer.encode`` and ``CrossEncoder.predict``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np

MAX_TOKENS = 512


def available() -> tuple[bool, str | None]:
    try:
        __import__("onnxruntime")
        __import__("tokenizers")
    except Exception as exc:
        return False, f"onnxruntime unavailable: {exc}"
    return True, None


def _snapshot(model_name: str) -> Path:
    path = Path(model_name).expanduser()
    if path.is_dir():
        return path
    from huggingface_hub import snapshot_download

    offline = str(os.environ.get("HF_HUB_OFFLINE") or "").lower() in {"1", "true", "yes", "on"}
    try:
        return Path(snapshot_download(model_name, local_files_only=True))
    except Exception:
        if offline:
            raise
        return Path(snapshot_download(model_name, allow_patterns=[
            "*.json", "*.txt", "onnx/model.onnx", "1_Pooling/*", "tokenizer*", "vocab*", "special_tokens_map.json",
        ]))


def _session(model_file: Path):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, int(os.environ.get("AUTOPSY_ONNX_THREADS") or min(8, os.cpu_count() or 4)))
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False      # the arena keeps the biggest batch's buffers forever
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(model_file), options, providers=["CPUExecutionProvider"])


def _tokenizer(snapshot: Path, max_tokens: int):
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(snapshot / "tokenizer.json"))
    limit = max_tokens
    try:
        config = json.loads((snapshot / "tokenizer_config.json").read_text())
        limit = min(limit, int(config.get("model_max_length") or limit))
    except Exception:
        pass
    tokenizer.enable_truncation(limit)
    tokenizer.no_padding()
    return tokenizer


def _model_file(snapshot: Path, name: str | None) -> Path:
    candidate = snapshot / (name or os.environ.get("AUTOPSY_ONNX_FILE") or "onnx/model.onnx")
    if not candidate.exists():
        raise RuntimeError(f"no ONNX export at {candidate}")
    return candidate


def _batch_feed(session, encodings) -> dict[str, np.ndarray]:
    width = max(len(e.ids) for e in encodings)
    ids = np.zeros((len(encodings), width), dtype=np.int64)
    mask = np.zeros_like(ids)
    types = np.zeros_like(ids)
    for row, enc in enumerate(encodings):
        n = len(enc.ids)
        ids[row, :n], mask[row, :n], types[row, :n] = enc.ids, enc.attention_mask, enc.type_ids
    feed = {"input_ids": ids, "attention_mask": mask}
    if any(i.name == "token_type_ids" for i in session.get_inputs()):
        feed["token_type_ids"] = types
    return feed


def _length_batches(lengths: list[int], batch_size: int):
    """Indices grouped by length so batches carry little padding."""
    order = sorted(range(len(lengths)), key=lambda i: lengths[i])
    for start in range(0, len(order), batch_size):
        yield order[start:start + batch_size]


class SentenceTransformer:
    def __init__(self, model_name: str, onnx_file: str | None = None, max_tokens: int = MAX_TOKENS):
        snapshot = _snapshot(model_name)
        self.session = _session(_model_file(snapshot, onnx_file))
        self.tokenizer = _tokenizer(snapshot, max_tokens)
        pooling = {}
        try:
            pooling = json.loads((snapshot / "1_Pooling" / "config.json").read_text())
        except Exception:
            pass
        self.cls = bool(pooling.get("pooling_mode_cls_token")) and not pooling.get("pooling_mode_mean_tokens")

    def encode(self, texts, batch_size: int = 16, normalize_embeddings: bool = True, **_ignored):
        single = isinstance(texts, str)
        texts = [texts] if single else list(texts)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        encodings = self.tokenizer.encode_batch(texts)
        out: list[np.ndarray | None] = [None] * len(texts)
        for batch in _length_batches([len(e.ids) for e in encodings], max(1, batch_size)):
            feed = _batch_feed(self.session, [encodings[i] for i in batch])
            hidden = self.session.run(None, feed)[0]
            if self.cls:
                vectors = hidden[:, 0]
            else:
                mask = feed["attention_mask"][..., None].astype(np.float32)
                vectors = (hidden * mask).sum(1) / np.clip(mask.sum(1), 1e-9, None)
            if normalize_embeddings:
                vectors = vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)
            for row, index in enumerate(batch):
                out[index] = vectors[row].astype(np.float32)
        result = np.stack(out)
        return result[0] if single else result


class CrossEncoder:
    def __init__(self, model_name: str, onnx_file: str | None = None, max_tokens: int = MAX_TOKENS):
        snapshot = _snapshot(model_name)
        self.session = _session(_model_file(snapshot, onnx_file))
        self.tokenizer = _tokenizer(snapshot, max_tokens)
        # longest_first, like sentence-transformers' CrossEncoder (truncation=True): with a short
        # query only the passage is cut, as before; "only_second" raised "Sequence to truncate too
        # short" whenever the query alone filled the window (a long pasted prompt as the query).
        self.tokenizer.enable_truncation(self.tokenizer.truncation["max_length"], strategy="longest_first")
        # raw logits, like sentence-transformers' CrossEncoder.predict for these models
        self.sigmoid = str(os.environ.get("AUTOPSY_ONNX_RERANK_SIGMOID") or "").lower() in {"1", "true", "yes"}

    def predict(self, pairs, batch_size: int = 8, **_ignored):
        pairs = [(str(a), str(b)) for a, b in pairs]
        if not pairs:
            return np.zeros((0,), dtype=np.float32)
        encodings = self.tokenizer.encode_batch(pairs)
        scores = np.zeros((len(pairs),), dtype=np.float32)
        for batch in _length_batches([len(e.ids) for e in encodings], max(1, batch_size)):
            logits = self.session.run(None, _batch_feed(self.session, [encodings[i] for i in batch]))[0]
            values = logits[:, 0] if logits.ndim == 2 else logits
            if self.sigmoid:
                values = 1.0 / (1.0 + np.exp(-values))
            scores[batch] = values
        return scores


def load(kind: str, model_name: str, options: dict[str, Any] | None = None):
    options = options or {}
    cls = SentenceTransformer if kind == "embedding" else CrossEncoder
    return cls(model_name, onnx_file=options.get("onnx_file"), max_tokens=int(options.get("max_tokens") or MAX_TOKENS))
