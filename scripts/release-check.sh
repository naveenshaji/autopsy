#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$ROOT_DIR/scripts/lib/python.sh"
PYTHON_BIN="$(autopsy_select_python)"
PYTHON="$PYTHON_BIN"

cd "$ROOT_DIR"

autopsy_check_python_version "$PYTHON"

if [ -f "$ROOT_DIR/apps/context-graph/package.json" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "release-check: npm is required to build the context graph viewer assets" >&2
    exit 1
  fi
  NPM_CACHE_DIR="${AUTOPSY_NPM_CACHE_DIR:-$ROOT_DIR/.npm-cache}"
  mkdir -p "$NPM_CACHE_DIR"
  (
    cd "$ROOT_DIR/apps/context-graph"
    if [ -f package-lock.json ]; then
      npm ci --cache "$NPM_CACHE_DIR" >/dev/null
    else
      npm install --cache "$NPM_CACHE_DIR" >/dev/null
    fi
    npm run build >/dev/null
  )
  test -s "$ROOT_DIR/src/autopsy_memory/context_graph_viewer/static/index.html"
fi

"$PYTHON" -m compileall -q src tests
"$PYTHON" -m unittest discover -s tests
sh -n scripts/install.sh
sh -n scripts/install-global.sh
sh -n scripts/menubar-check.sh
sh -n scripts/install-matrix-check.sh
sh -n scripts/homebrew-current-check.sh
sh -n scripts/lib/python.sh
test -s scripts/homebrew-constraints.txt

TMP_DIR="${TMPDIR:-/tmp}/autopsy-release-check-$$"
export AUTOPSY_CLI_CONSULT_WORKER=0
release_check_pids() {
  ps -axo pid=,command= 2>/dev/null | awk -v tmp="$TMP_DIR" '
    index($0, tmp) &&
    ($0 ~ /worker\.py/ || $0 ~ /redislite\/bin\/redis-server/ || $0 ~ /\/venv\/bin\/python/ || $0 ~ /\/venv\/bin\/pip/) &&
    $0 !~ /awk -v tmp=/ &&
    $0 !~ /ps -axo/ {
      print $1
    }
  ' || true
}

cleanup_release_check_processes() {
  attempt=0
  while [ "$attempt" -lt 8 ]; do
    sleep 1
    pids="$(release_check_pids)"
    [ -n "$pids" ] || return 0
    if [ "$attempt" -lt 2 ]; then
      /bin/kill $pids >/dev/null 2>&1 || true
    else
      /bin/kill -9 $pids >/dev/null 2>&1 || true
    fi
    attempt=$((attempt + 1))
  done
  sleep 2
  pids="$(release_check_pids)"
  [ -z "$pids" ] && return 0
  echo "release-check: cleanup left temp processes: $pids" >&2
  return 1
}

cleanup() {
  status=$?
  trap - EXIT INT TERM HUP
  # Release checks use temp app-support and venv paths; do not leave workers behind.
  if ! cleanup_release_check_processes; then
    status=1
  fi
  rm -rf "$TMP_DIR"
  exit "$status"
}
trap cleanup EXIT INT TERM HUP
"$PYTHON" -m venv "$TMP_DIR/venv"
"$TMP_DIR/venv/bin/python" -m pip install -U pip >/dev/null
"$TMP_DIR/venv/bin/python" -m pip install -e ".[dev]" >/dev/null

if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  FALKORDB_NATIVE_MODULE="$TMP_DIR/falkordb.so"
  curl -fsSL -o "$FALKORDB_NATIVE_MODULE" "https://github.com/FalkorDB/FalkorDB/releases/download/v4.18.3/falkordb-macos-arm64v8.so"
  chmod 0755 "$FALKORDB_NATIVE_MODULE"
  export AUTOPSY_FALKORDB_MODULE_PATH="$FALKORDB_NATIVE_MODULE"
fi

PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" --help >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" version --json >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/doctor-app-support" "$TMP_DIR/venv/bin/autopsy" doctor > "$TMP_DIR/doctor.json"
"$PYTHON" - "$TMP_DIR/doctor.json" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
assert payload.get("ok") is True, payload
checks = {check.get("name"): check for check in payload.get("checks", [])}
warmup = checks.get("model_warmup") or {}
assert warmup.get("required") is False, warmup
assert warmup.get("state") == "not_started", warmup
assert payload.get("paths", {}).get("model_warmup_status"), payload.get("paths")
assert payload.get("paths", {}).get("model_warmup_log"), payload.get("paths")
PY
PATH="$TMP_DIR/venv/bin:$PATH" AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/fresh-app-support" AUTOPSY_UNIFIED_MEMORY_ROOT="$TMP_DIR/fresh-root" "$TMP_DIR/venv/bin/autopsy" status --current-only --limit 1 --section-limit 1 > "$TMP_DIR/fresh-status.json"
"$PYTHON" - "$TMP_DIR/fresh-status.json" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
assert payload.get("status", {}).get("summary") == "No memory has been written yet.", payload.get("status")
workflow = payload.get("workflow") or {}
assert workflow.get("status") == "empty", workflow
assert workflow.get("complete") is False, workflow
assert workflow.get("next_step") == "write_memory", workflow
assert any((step or {}).get("command") == "autopsy install" for step in workflow.get("suggested_next_steps") or []), workflow
onboarding = payload.get("onboarding") or {}
assert onboarding.get("empty") is True, onboarding
assert "autopsy install" in onboarding.get("message", ""), onboarding
PY
PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" install --dry-run --skip-menubar >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" install --dry-run --skip-menubar --smoke-test --skip-write-smoke > "$TMP_DIR/install-dry-run-smoke.json"
"$PYTHON" - "$TMP_DIR/install-dry-run-smoke.json" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
smoke = payload.get("smoke_test") or {}
assert smoke.get("skipped") is True, smoke
assert smoke.get("reason") == "dry_run", smoke
assert payload.get("workflow", {}).get("complete") is True, payload.get("workflow")
PY
mkdir -p "$TMP_DIR/install-home"
PATH="$TMP_DIR/venv/bin:$PATH" \
  HOME="$TMP_DIR/install-home" \
  AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/install-app-support" \
  AUTOPSY_UNIFIED_MEMORY_ROOT="$TMP_DIR/install-root" \
  "$TMP_DIR/venv/bin/autopsy" install \
    --skip-menubar \
    --skip-model-warmup \
    --smoke-test \
    --skip-write-smoke > "$TMP_DIR/install-real-smoke.json"
"$PYTHON" - "$TMP_DIR/install-real-smoke.json" "$TMP_DIR/install-home" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
home = Path(sys.argv[2])
assert payload.get("workflow", {}).get("complete") is True, payload.get("workflow")
assert payload.get("instructions", {}).get("workflow", {}).get("complete") is True, payload.get("instructions")
assert payload.get("model_warmup", {}).get("reason") == "skip_model_warmup", payload.get("model_warmup")
smoke = payload.get("smoke_test") or {}
assert smoke.get("ok") is True, smoke
targets = payload.get("instructions", {}).get("targets") or []
global_targets = [target for target in targets if target.get("scope") == "global"]
assert {target.get("agent") for target in global_targets} == {"codex", "claude", "gemini", "opencode"}, global_targets
for target in global_targets:
    assert target.get("state") == "managed", target
    assert target.get("action") in {"added", "updated", "unchanged"}, target
    path = Path(str(target.get("path") or ""))
    assert path.exists(), target
    assert home in path.parents, target
    text = path.read_text(encoding="utf-8")
    assert "AUTOPSY_MEMORY_START" in text and "AUTOPSY_MEMORY_END" in text, target
PY
PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" init --check >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" instructions >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" AUTOPSY_UNIFIED_MEMORY=0 AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/app-support" AUTOPSY_FALKORDB_LITE_PATH="$TMP_DIR/app-support/FalkorDB/autopsy-memory.db" "$TMP_DIR/venv/bin/autopsy" health --workspace "$TMP_DIR/workspace" >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" AUTOPSY_UNIFIED_MEMORY=0 AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/app-support" AUTOPSY_FALKORDB_LITE_PATH="$TMP_DIR/app-support/FalkorDB/autopsy-memory.db" "$TMP_DIR/venv/bin/autopsy" activity --workspace "$TMP_DIR/workspace" >/dev/null
PATH="$TMP_DIR/venv/bin:$PATH" AUTOPSY_UNIFIED_MEMORY=0 AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/fresh-empty-app-support" AUTOPSY_FALKORDB_LITE_PATH="$TMP_DIR/fresh-empty-app-support/FalkorDB/autopsy-memory.db" "$TMP_DIR/venv/bin/autopsy" activity --workspace "$TMP_DIR/fresh-empty-workspace" > "$TMP_DIR/fresh-empty-activity.json"
"$PYTHON" - "$TMP_DIR/fresh-empty-activity.json" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
onboarding = payload.get("onboarding") or {}
assert onboarding.get("empty") is True, onboarding
assert onboarding.get("state") == "empty", onboarding
assert "autopsy install" in onboarding.get("message", ""), onboarding
assert payload.get("activity", {}).get("attention") == [], payload.get("activity")
assert payload.get("snapshot", {}).get("schema_version") == 1, payload.get("snapshot")
PY
PYTHON="$TMP_DIR/venv/bin/python" AUTOPSY_INSTALL_MATRIX_SKIP_RUNTIME=1 ./scripts/install-matrix-check.sh >/dev/null
if [ "$(uname -s)" = "Darwin" ]; then
  PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" menubar --print-path >/dev/null
  PATH="$TMP_DIR/venv/bin:$PATH" "$TMP_DIR/venv/bin/autopsy" menubar --launch-agent-status >/dev/null
fi
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
if command -v swift >/dev/null 2>&1; then
  ./scripts/menubar-check.sh >/dev/null
fi

echo "release-check: ok"
