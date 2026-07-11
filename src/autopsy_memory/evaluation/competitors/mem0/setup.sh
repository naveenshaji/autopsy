#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${1:-${HOME}/.cache/autopsy/evaluation/mem0-oss-2.0.11}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

"${PYTHON_BIN}" -c \
  'import sys; assert sys.version_info[:2] == (3, 12), "The pinned Mem0 adapter bootstrap requires Python 3.12."'
"${PYTHON_BIN}" -m venv "${VENV_DIR}"

if [[ "${OS:-}" == "Windows_NT" ]]; then
  VENV_PYTHON="${VENV_DIR}/Scripts/python.exe"
else
  VENV_PYTHON="${VENV_DIR}/bin/python"
fi

"${VENV_PYTHON}" -m pip install --upgrade 'pip==25.1.1'
"${VENV_PYTHON}" -m pip install --requirement "${SCRIPT_DIR}/requirements.txt"
MEM0_TELEMETRY=false HF_HUB_DISABLE_TELEMETRY=1 "${VENV_PYTHON}" - <<'PY'
import importlib.metadata
import json

from sentence_transformers import SentenceTransformer

model_name = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
revision = "b207367332321f8e44f96e224ef15bc607f4dbf0"
model = SentenceTransformer(model_name, revision=revision)
dimensions = model.get_sentence_embedding_dimension()
resolved_revision = getattr(model._first_module().auto_model.config, "_commit_hash", None)
if importlib.metadata.version("mem0ai") != "2.0.11":
    raise SystemExit("mem0ai version pin verification failed")
direct_url = json.loads(importlib.metadata.distribution("mem0ai").read_text("direct_url.json") or "{}")
installed_commit = (direct_url.get("vcs_info") or {}).get("commit_id")
if installed_commit != "f2532f072fdefa4c90264acc80af0984309f8b06":
    raise SystemExit(f"mem0ai source commit verification failed: {installed_commit}")
if importlib.metadata.version("sentence-transformers") != "5.1.2":
    raise SystemExit("sentence-transformers version pin verification failed")
if dimensions != 384:
    raise SystemExit(f"embedding dimension verification failed: {dimensions}")
if resolved_revision != revision:
    raise SystemExit(f"embedding revision verification failed: {resolved_revision}")
print(
    json.dumps(
        {
            "status": "ready",
            "mem0ai": importlib.metadata.version("mem0ai"),
            "mem0_commit": "f2532f072fdefa4c90264acc80af0984309f8b06",
            "sentence_transformers": importlib.metadata.version("sentence-transformers"),
            "embedding_model": model_name,
            "embedding_revision": revision,
            "embedding_dimensions": dimensions,
        },
        indent=2,
        sort_keys=True,
    )
)
PY

printf 'Set AUTOPSY_MEM0_PYTHON=%q\n' "${VENV_PYTHON}"
