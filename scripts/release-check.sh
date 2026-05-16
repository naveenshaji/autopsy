#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ -z "${PYTHON:-}" ]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON=python3.12
  else
    PYTHON=python3
  fi
fi

cd "$ROOT_DIR"

"$PYTHON" - <<'PY'
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Autopsy requires Python 3.12 or newer.")
PY

"$PYTHON" -m compileall -q src tests
"$PYTHON" -m unittest discover -s tests
sh -n scripts/install.sh
sh -n scripts/install-global.sh

TMP_DIR="${TMPDIR:-/tmp}/autopsy-release-check-$$"
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM HUP
"$PYTHON" -m venv "$TMP_DIR/venv"
"$TMP_DIR/venv/bin/python" -m pip install -U pip >/dev/null
"$TMP_DIR/venv/bin/python" -m pip install -e ".[dev]" >/dev/null

PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" --help >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" version --json >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" doctor >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" init --check >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" instructions >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" AUTOPSY_UNIFIED_MEMORY=0 AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/app-support" AUTOPSY_FALKORDB_LITE_PATH="$TMP_DIR/app-support/FalkorDB/autopsy-memory.db" "$TMP_DIR/venv/bin/autopsy" health --workspace "$TMP_DIR/workspace" >/dev/null
cat > "$TMP_DIR/restore.json" <<'JSON'
{
  "schema_version": 1,
  "items": [
    {
      "stable_key": "release-check:restore-smoke",
      "kind": "decision",
      "title": "Release check restore smoke",
      "summary": "Release check restore smoke",
      "content": "Synthetic dry-run payload used by the release check."
    }
  ],
  "relations": [],
  "structural_edges": []
}
JSON
PATH="$TMP_DIR/venv/bin:$PATH" AUTOPSY_UNIFIED_MEMORY=0 AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/app-support" AUTOPSY_FALKORDB_LITE_PATH="$TMP_DIR/app-support/FalkorDB/autopsy-memory.db" "$TMP_DIR/venv/bin/autopsy" restore "$TMP_DIR/restore.json" --dry-run --workspace "$TMP_DIR/workspace" >/dev/null
"$TMP_DIR/venv/bin/python" -m build --wheel --outdir "$TMP_DIR/dist" >/dev/null

echo "release-check: ok"
