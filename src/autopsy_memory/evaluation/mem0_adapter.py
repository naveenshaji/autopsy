"""Process-isolated Mem0 OSS raw-retrieval evaluation adapter."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .adapters import (
    canonical_json_sha256,
    corpus_fingerprint,
    source_file_pin,
    source_tree_pin,
    zero_external_cost,
)
from .models import EvaluationCorpus, RetrievalRequest, RetrievalResult


MEM0_ADAPTER_ID = "mem0-oss-raw"
MEM0_VERSION = "2.0.11"
MEM0_COMMIT = "f2532f072fdefa4c90264acc80af0984309f8b06"
MEM0_REPOSITORY = "https://github.com/mem0ai/mem0"
EMBEDDING_MODEL = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
EMBEDDING_REVISION = "b207367332321f8e44f96e224ef15bc607f4dbf0"
EMBEDDING_DIMENSIONS = 384
SENTENCE_TRANSFORMERS_VERSION = "5.1.2"


def default_mem0_python() -> Path:
    configured = os.environ.get("AUTOPSY_MEM0_PYTHON")
    if configured:
        return Path(os.path.abspath(os.fspath(Path(configured).expanduser())))
    root = Path.home() / ".cache" / "autopsy" / "evaluation" / f"mem0-oss-{MEM0_VERSION}"
    executable = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return Path(os.path.abspath(os.fspath(executable)))


def mem0_bootstrap_dir() -> Path:
    """Return the canonical bootstrap asset directory shipped in the wheel."""

    return Path(__file__).with_name("competitors") / "mem0"


def mem0_setup_script() -> Path:
    return mem0_bootstrap_dir() / "setup.sh"


def mem0_adapter_bundle_pin(worker_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Hash every executable/source/bootstrap file needed by the adapter."""

    bootstrap_root = mem0_bootstrap_dir()
    selected_worker = (
        Path(worker_path).expanduser().resolve()
        if worker_path
        else Path(__file__).with_name("mem0_worker.py")
    )
    entries = {
        "adapter/mem0_adapter.py": source_file_pin(__file__)["sha256"],
        "adapter/mem0_worker.py": source_file_pin(selected_worker)["sha256"],
    }
    for asset in sorted(
        path
        for path in bootstrap_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ):
        entries[f"bootstrap/{asset.relative_to(bootstrap_root).as_posix()}"] = source_file_pin(asset)["sha256"]
    return {
        "kind": "mem0-adapter-bundle-sha256",
        "sha256": canonical_json_sha256(entries),
        "files": entries,
    }


class Mem0OSSEvaluationAdapter:
    """Evaluate Mem0 2.0.11 without adding it to Autopsy's runtime graph.

    The process protocol serializes a complete query-free corpus in ``prepare``
    and sends the query only in a later ``retrieve`` message. Mem0-generated
    UUIDs are mapped to the already-opaque corpus handles exclusively inside
    the worker; neither identifier is included in embedding text.
    """

    adapter_id = MEM0_ADAPTER_ID

    def __init__(
        self,
        *,
        store_dir: str | None = None,
        keep_store: bool = False,
        python_executable: str | os.PathLike[str] | None = None,
        worker_path: str | os.PathLike[str] | None = None,
    ):
        self.keep_store = bool(keep_store)
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        if store_dir:
            self.root = Path(store_dir).expanduser().resolve()
            self.root.mkdir(parents=True, exist_ok=True)
        elif self.keep_store:
            self.root = Path(tempfile.mkdtemp(prefix="autopsy-mem0-eval-"))
        else:
            self._temporary = tempfile.TemporaryDirectory(prefix="autopsy-mem0-eval-")
            self.root = Path(self._temporary.name)
        # Do not resolve the virtualenv's Python symlink: invoking its real
        # target bypasses pyvenv.cfg and silently loses the pinned environment.
        self.python_executable = (
            Path(os.path.abspath(os.fspath(Path(python_executable).expanduser())))
            if python_executable
            else default_mem0_python()
        )
        self.worker_path = (
            Path(worker_path).expanduser().resolve()
            if worker_path
            else Path(__file__).with_name("mem0_worker.py").resolve()
        )
        if not self.python_executable.is_file():
            setup = mem0_setup_script()
            self._cleanup_root()
            if not setup.is_file():
                raise RuntimeError(
                    "The installed autopsy-memory package is missing its Mem0 bootstrap assets: "
                    f"{setup}"
                )
            raise RuntimeError(
                "The pinned Mem0 evaluation environment is not installed. "
                f"Run the packaged setup script {setup} or set AUTOPSY_MEM0_PYTHON to its Python executable "
                f"(expected {self.python_executable})."
            )
        if not self.worker_path.is_file():
            self._cleanup_root()
            raise RuntimeError(f"Mem0 evaluation worker is missing: {self.worker_path}")

        self._stderr_path = self.root / "mem0-worker.stderr.log"
        self._stderr_stream = self._stderr_path.open("w", encoding="utf-8")
        self.process: subprocess.Popen[str] | None = None
        self._request_number = 0
        self._closed = False
        self._fingerprint = ""
        self._ingestion_history: list[dict[str, Any]] = []
        environment = os.environ.copy()
        for key in tuple(environment):
            if key.endswith("_API_KEY") or key in {"HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"}:
                environment.pop(key, None)
        environment.update(
            {
                "MEM0_TELEMETRY": "false",
                "MEM0_DIR": str(self.root / "mem0-home"),
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "DO_NOT_TRACK": "1",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        try:
            self.process = subprocess.Popen(
                [str(self.python_executable), str(self.worker_path), str(self.root / "store")],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_stream,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=environment,
            )
            self._handshake = self._request("handshake")
            self._verify_handshake()
        except Exception:
            self.close()
            raise

    def _cleanup_root(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def _stderr_tail(self, limit: int = 4000) -> str:
        try:
            self._stderr_stream.flush()
            content = self._stderr_path.read_text(encoding="utf-8", errors="replace")
            return content[-limit:]
        except Exception:
            return ""

    def _request(self, action: str, **payload: Any) -> dict[str, Any]:
        if getattr(self, "_closed", False):
            raise RuntimeError("Mem0 evaluation adapter is closed")
        process = self.process
        if process is None:
            raise RuntimeError("Mem0 evaluation worker did not start")
        if process.poll() is not None:
            raise RuntimeError(
                f"Mem0 evaluation worker exited with code {process.returncode}: {self._stderr_tail()}"
            )
        self._request_number += 1
        request_id = self._request_number
        message = {"action": action, "request_id": request_id, **payload}
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Mem0 evaluation worker pipes are unavailable")
        process.stdin.write(json.dumps(message, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(
                f"Mem0 evaluation worker closed its protocol stream: {self._stderr_tail()}"
            )
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Mem0 worker emitted non-JSON protocol output: {line[:500]!r}") from exc
        if response.get("request_id") != request_id:
            raise RuntimeError("Mem0 worker response id did not match its request")
        if response.get("ok") is not True:
            raise RuntimeError(
                f"Mem0 worker {response.get('error_type') or 'error'}: {response.get('error') or 'unknown failure'}"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Mem0 worker response did not contain an object result")
        return result

    def _verify_handshake(self) -> None:
        packages = self._handshake.get("packages") or {}
        if packages.get("mem0ai") != MEM0_VERSION:
            raise RuntimeError(
                f"Pinned adapter requires mem0ai {MEM0_VERSION}; worker reported {packages.get('mem0ai')!r}"
            )
        if packages.get("sentence-transformers") != SENTENCE_TRANSFORMERS_VERSION:
            raise RuntimeError(
                "Pinned adapter requires sentence-transformers "
                f"{SENTENCE_TRANSFORMERS_VERSION}; worker reported {packages.get('sentence-transformers')!r}"
            )
        if self._handshake.get("mem0_commit") != MEM0_COMMIT:
            raise RuntimeError("Mem0 worker source commit declaration does not match the adapter pin")
        direct_url = self._handshake.get("mem0_direct_url") or {}
        vcs_info = direct_url.get("vcs_info") if isinstance(direct_url, dict) else None
        installed_commit = vcs_info.get("commit_id") if isinstance(vcs_info, dict) else None
        if installed_commit != MEM0_COMMIT:
            raise RuntimeError(
                "Pinned adapter requires a PEP 610 Mem0 install from commit "
                f"{MEM0_COMMIT}; worker reported {installed_commit or 'no source commit'}"
            )
        if self._handshake.get("embedding_revision") != EMBEDDING_REVISION:
            raise RuntimeError("Mem0 worker embedding revision does not match the adapter pin")

    @staticmethod
    def _document_payload(document) -> dict[str, Any]:
        return {
            "document_id": document.document_id,
            "title": document.title,
            "text": document.text,
            "expired_at": document.expired_at,
            "repository_id": str(document.metadata.get("repository_id") or ""),
        }

    def prepare(self, corpus: EvaluationCorpus) -> dict[str, Any]:
        if not isinstance(corpus, EvaluationCorpus):
            raise TypeError("prepare expects an EvaluationCorpus with no query or judgments")
        fingerprint = corpus_fingerprint(corpus)
        result = self._request(
            "prepare",
            corpus_fingerprint=fingerprint,
            documents=[self._document_payload(document) for document in corpus.documents],
            relation_count=len(corpus.relations),
        )
        self._fingerprint = fingerprint
        if not result.get("reused"):
            self._ingestion_history.append(result)
        return result

    def ingest(self, corpus: EvaluationCorpus) -> dict[str, Any]:
        return self.prepare(corpus)

    def reset_query_state(self) -> None:
        self._request("reset")

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        if not isinstance(request, RetrievalRequest):
            raise TypeError("retrieve expects a query-only RetrievalRequest")
        if not self._fingerprint:
            raise RuntimeError("prepare must complete before retrieve")
        result = self._request(
            "retrieve",
            query=request.query,
            limit=request.limit,
            route=request.route,
            as_of=request.as_of,
            scope=request.scope,
            repository_id=request.repository_id,
        )
        return RetrievalResult(
            ranked_document_ids=tuple(str(value) for value in result.get("ranked_document_ids") or []),
            latency_seconds=float(result.get("latency_seconds") or 0.0),
            route=str(result.get("route") or "mem0-oss-native-search"),
            retrieval_reasons=tuple(
                tuple(str(reason) for reason in reasons)
                for reasons in result.get("retrieval_reasons") or []
            ),
            diagnostics=dict(result.get("diagnostics") or {}),
        )

    def _config(self) -> dict[str, Any]:
        return {
            "mem0": {
                "package": "mem0ai",
                "version": MEM0_VERSION,
                "repository": MEM0_REPOSITORY,
                "commit": MEM0_COMMIT,
                "infer": False,
                "telemetry": False,
            },
            "embedding": {
                "provider": "huggingface",
                "model": EMBEDDING_MODEL,
                "revision": EMBEDDING_REVISION,
                "dimensions": EMBEDDING_DIMENSIONS,
                "sentence_transformers_version": SENTENCE_TRANSFORMERS_VERSION,
            },
            "vector_store": {
                "provider": "qdrant",
                "mode": "embedded-local-path",
                "on_disk": True,
            },
            "search": {
                "api": "Memory.search",
                "threshold": 0.1,
                "rerank": False,
                "relation_support": False,
            },
            "isolation": {
                "process": True,
                "prepare_receives_query": False,
                "mem0_uuid_mapping": "out-of-band",
                "empty_document_policy": "skip-and-report-ineligible",
                "runtime_network": "offline",
                "inherited_api_credentials": False,
            },
            "temporal": {
                "native_current_expiration": True,
                "exact_runtime_expiration_postfilter": True,
                "native_as_of": False,
            },
        }

    def manifest(self) -> dict[str, Any]:
        packages = dict(self._handshake.get("packages") or {})
        config = self._config()
        worker_pin = source_file_pin(self.worker_path)
        adapter_pin = source_file_pin(__file__)
        bootstrap_pin = source_tree_pin(mem0_bootstrap_dir())
        bundle_pin = mem0_adapter_bundle_pin(self.worker_path)
        return {
            "adapter_id": self.adapter_id,
            "implementation": "mem0-oss-2.0.11-raw-infer-false-v1",
            "track": "raw-retrieval",
            "config": config,
            "config_sha256": canonical_json_sha256(config),
            "package_pin": {
                "name": "mem0ai",
                "version": packages.get("mem0ai"),
                "required_version": MEM0_VERSION,
                "runtime_dependencies": packages,
                "embedding_model": {
                    "name": EMBEDDING_MODEL,
                    "revision": EMBEDDING_REVISION,
                },
            },
            "source_pin": {
                "kind": "upstream-git-commit-plus-complete-adapter-bundle",
                "repository": MEM0_REPOSITORY,
                "commit": MEM0_COMMIT,
                "tag": f"v{MEM0_VERSION}",
                "adapter_sha256": adapter_pin["sha256"],
                "worker_sha256": worker_pin["sha256"],
                "bootstrap_assets": bootstrap_pin,
                "adapter_bundle": bundle_pin,
            },
            "execution": {
                "mode": "local-isolated-subprocess",
                "local": True,
                "remote": False,
                "network_required": False,
                "runtime_offline_enforced": True,
                "bootstrap_network_required": True,
                "initial_model_download_network_required": True,
                "external_service_credentials_required": False,
            },
            "cost": {
                **zero_external_cost(),
                "local_compute": "CPU embedding and embedded-Qdrant storage are not priced as API cost.",
            },
            "retrieval_family": "dense-semantic",
            "semantic": True,
        }

    def capabilities(self) -> dict[str, Any]:
        worker = self._request("capabilities")
        store_bytes = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        return {
            **self.manifest(),
            **worker,
            "adapter": "mem0-oss-raw-subprocess-v1",
            "python_executable": str(self.python_executable),
            "production_store_used": False,
            "query_state_adaptive": False,
            "store_path": str(self.root) if self.keep_store else "temporary-redacted",
            "store_bytes": store_bytes,
            "bootstrap_setup_path": str(mem0_setup_script()),
            "bootstrap_setup_executable": os.access(mem0_setup_script(), os.X_OK),
            "limitations": [
                "Mem0 OSS 2.0.11 does not support native reference-date/as-of search.",
                "Raw retrieval uses infer=False and does not evaluate Mem0's LLM extraction pipeline.",
                "Evaluation relations are not indexed because this adapter measures Mem0 raw vector retrieval.",
            ],
        }

    @property
    def ingestion_history(self) -> list[dict[str, Any]]:
        return list(self._ingestion_history)

    def close(self) -> None:
        if getattr(self, "_closed", True):
            stderr_stream = getattr(self, "_stderr_stream", None)
            if stderr_stream is not None and not stderr_stream.closed:
                stderr_stream.close()
            self._cleanup_root()
            return
        self._closed = True
        process = getattr(self, "process", None)
        if process is not None and process.poll() is None:
            try:
                if process.stdin is not None:
                    self._request_number += 1
                    process.stdin.write(
                        json.dumps(
                            {"action": "close", "request_id": self._request_number},
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    process.stdin.flush()
                process.wait(timeout=10)
            except Exception:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        stderr_stream = getattr(self, "_stderr_stream", None)
        if stderr_stream is not None and not stderr_stream.closed:
            stderr_stream.close()
        self._cleanup_root()

    def __enter__(self) -> "Mem0OSSEvaluationAdapter":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


__all__ = [
    "EMBEDDING_MODEL",
    "EMBEDDING_REVISION",
    "MEM0_ADAPTER_ID",
    "MEM0_COMMIT",
    "MEM0_VERSION",
    "Mem0OSSEvaluationAdapter",
    "default_mem0_python",
    "mem0_adapter_bundle_pin",
    "mem0_bootstrap_dir",
    "mem0_setup_script",
]
