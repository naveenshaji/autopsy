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
PYTHON_BIN="$(command -v "$PYTHON")"

cd "$ROOT_DIR"

"$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Autopsy requires Python 3.12 or newer.")
PY

TMP_DIR="${TMPDIR:-/tmp}/autopsy-install-matrix-$$"
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM HUP
mkdir -p "$TMP_DIR"

legacy_dir="$TMP_DIR/shadow/legacy"
valid_dir="$TMP_DIR/shadow/homebrew"
target_dir="$TMP_DIR/shadow/libexec/bin"
mkdir -p "$legacy_dir" "$valid_dir" "$target_dir"

cat > "$legacy_dir/autopsy" <<'SH'
#!/bin/sh
AUTOPSY_BUNDLED_MEMORY_TOOL=/tmp/legacy
SH
chmod 0755 "$legacy_dir/autopsy"

cat > "$target_dir/autopsy" <<'PY'
from autopsy_memory.cli import main
main()
PY
chmod 0755 "$target_dir/autopsy"

cat > "$valid_dir/autopsy" <<SH
#!/bin/sh
AUTOPSY_UNIFIED_MEMORY=1 exec "$target_dir/autopsy" "\$@"
SH
chmod 0755 "$valid_dir/autopsy"

PATH="$legacy_dir:$valid_dir" PYTHONPATH="$ROOT_DIR/src" "$PYTHON_BIN" - <<'PY'
import json
from autopsy_memory import doctor

payload = doctor.installed_autopsy_command_check()
assert payload["ok"] is False, payload
assert payload["legacy_wrapper"] is True, payload
assert payload["shadowed_valid_command"].endswith("/shadow/homebrew/autopsy"), payload
assert "valid Autopsy command exists later on PATH" in payload["error"], payload
PY

brew_root="$TMP_DIR/homebrew"
mkdir -p "$brew_root/bin" "$brew_root/opt/autopsy-memory"
cat > "$brew_root/bin/brew" <<SH
#!/bin/sh
if [ "\$1" = "--prefix" ] && [ "\${2:-}" = "autopsy-memory" ]; then
  printf '%s\n' "$brew_root/opt/autopsy-memory"
  exit 0
fi
printf 'unexpected brew invocation: %s\n' "\$*" >&2
exit 2
SH
chmod 0755 "$brew_root/bin/brew"

cat > "$brew_root/bin/autopsy" <<'SH'
#!/bin/sh
AUTOPSY_BUNDLED_MEMORY_TOOL=/tmp/legacy
SH
chmod 0755 "$brew_root/bin/autopsy"

PATH="$brew_root/bin" PYTHONPATH="$ROOT_DIR/src" AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/repair-support" "$PYTHON_BIN" -m autopsy_memory.cli install --dry-run --skip-instructions --skip-menubar --skip-doctor > "$TMP_DIR/install-repair.json"
"$PYTHON_BIN" - "$TMP_DIR/install-repair.json" "$brew_root" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
brew_root = Path(sys.argv[2]).resolve()
path_repair = payload.get("path_repair") or {}
assert path_repair.get("ok") is False, path_repair
assert path_repair.get("repair_available") is True, path_repair
assert Path(path_repair.get("homebrew_prefix", "")).resolve() == brew_root, path_repair
assert path_repair.get("would_backup", "").endswith("/homebrew/bin/autopsy"), path_repair
would_run = path_repair.get("would_run") or []
assert any(command[-2:] == ["unlink", "autopsy-memory"] for command in would_run), would_run
assert any(command[-3:] == ["link", "--overwrite", "autopsy-memory"] for command in would_run), would_run
workflow = payload.get("workflow") or {}
assert workflow.get("complete") is False, workflow
assert any("Run autopsy install" in step for step in workflow.get("next_steps") or []), workflow
PY

missing_path_dir="$TMP_DIR/no-autopsy"
mkdir -p "$missing_path_dir"
cat > "$missing_path_dir/brew" <<SH
#!/bin/sh
if [ "\$1" = "--prefix" ] && [ "\${2:-}" = "autopsy-memory" ]; then
  printf '%s\n' "$brew_root/opt/autopsy-memory"
  exit 0
fi
exit 2
SH
chmod 0755 "$missing_path_dir/brew"

PATH="$missing_path_dir" PYTHONPATH="$ROOT_DIR/src" AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/missing-support" "$PYTHON_BIN" -m autopsy_memory.cli install --dry-run --skip-instructions --skip-menubar --skip-doctor > "$TMP_DIR/install-missing.json"
"$PYTHON_BIN" - "$TMP_DIR/install-missing.json" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
path_repair = payload.get("path_repair") or {}
assert path_repair.get("check_before", {}).get("path") in ("", None), path_repair
assert path_repair.get("repair_available") is True, path_repair
assert path_repair.get("would_run"), path_repair
PY

grep -F 'with_env(PATH: "#{bin}:#{ENV.fetch("PATH", "")}")' Formula/autopsy-memory.rb >/dev/null
grep -F 'with_env(PATH: "#{{bin}}:#{{ENV.fetch("PATH", "")}}")' scripts/update-homebrew-formula.py >/dev/null

runtime_available=0
if PYTHONPATH="$ROOT_DIR/src" "$PYTHON_BIN" - >/dev/null 2>&1 <<'PY'
import falkordb
import redis
import redislite.falkordb_client
PY
then
  runtime_available=1
fi

if [ "$runtime_available" = "1" ]; then
  PATH="$(dirname "$PYTHON_BIN"):$PATH" PYTHONPATH="$ROOT_DIR/src" AUTOPSY_UNIFIED_MEMORY=0 AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/fresh-app-support" AUTOPSY_FALKORDB_LITE_PATH="$TMP_DIR/fresh-app-support/FalkorDB/autopsy-memory.db" "$PYTHON_BIN" -m autopsy_memory.cli activity --workspace "$TMP_DIR/fresh-workspace" --limit 1 --section-limit 1 > "$TMP_DIR/fresh-activity.json"
  "$PYTHON_BIN" - "$TMP_DIR/fresh-activity.json" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
onboarding = payload.get("onboarding") or {}
assert onboarding.get("state") == "empty", onboarding
assert onboarding.get("empty") is True, onboarding
assert "No memory" in onboarding.get("title", ""), onboarding
assert payload.get("snapshot", {}).get("schema_version") == 1, payload.get("snapshot")
PY
elif [ "${AUTOPSY_INSTALL_MATRIX_REQUIRE_RUNTIME:-0}" = "1" ]; then
  echo "install-matrix-check: missing embedded runtime dependencies" >&2
  exit 1
else
  echo "install-matrix-check: skipped fresh activity runtime smoke; embedded runtime dependencies are not installed" >&2
fi

echo "install-matrix-check: ok"
