#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$ROOT_DIR/scripts/lib/python.sh"
PYTHON_BIN="$(autopsy_select_python)"

cd "$ROOT_DIR"

autopsy_check_python_version "$PYTHON_BIN"

TMP_DIR="${TMPDIR:-/tmp}/autopsy-install-matrix-$$"
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM HUP
mkdir -p "$TMP_DIR"

selector_dir="$TMP_DIR/python-selector"
python_helper="$ROOT_DIR/scripts/lib/python.sh"
mkdir -p "$selector_dir"
cat > "$selector_dir/python3" <<'SH'
#!/bin/sh
exit 0
SH
cat > "$selector_dir/python3.13" <<'SH'
#!/bin/sh
exit 0
SH
cat > "$selector_dir/python3.12" <<'SH'
#!/bin/sh
exit 0
SH
chmod 0755 "$selector_dir/python3" "$selector_dir/python3.13" "$selector_dir/python3.12"
PATH="$selector_dir" PYTHON= AUTOPSY_PYTHON_CANDIDATES="python3.12 python3.13 python3" /bin/sh -c '
. "$1"
selected="$(autopsy_select_python)"
case "$selected" in
  */python3.12) exit 0 ;;
  *) echo "expected python3.12, got $selected" >&2; exit 1 ;;
esac
' sh "$python_helper"

rm -f "$selector_dir/python3.12"
PATH="$selector_dir" PYTHON= AUTOPSY_PYTHON_CANDIDATES="python3.12 python3.13 python3" /bin/sh -c '
. "$1"
selected="$(autopsy_select_python)"
case "$selected" in
  */python3.13) exit 0 ;;
  *) echo "expected python3.13 fallback, got $selected" >&2; exit 1 ;;
esac
' sh "$python_helper"

PYTHON="$selector_dir/python3" PATH="$selector_dir" /bin/sh -c '
. "$1"
selected="$(autopsy_select_python)"
case "$selected" in
  */python3) exit 0 ;;
  *) echo "expected explicit PYTHON, got $selected" >&2; exit 1 ;;
esac
' sh "$python_helper"

empty_selector_dir="$TMP_DIR/python-selector-empty"
missing_python_err="$TMP_DIR/missing-python.err"
missing_explicit_python_err="$TMP_DIR/missing-explicit-python.err"
mkdir -p "$empty_selector_dir"
if PATH="$empty_selector_dir" PYTHON= AUTOPSY_PYTHON_CANDIDATES="python3.12 python3.13 python3" /bin/sh -c '. "$1"; autopsy_select_python >/dev/null' sh "$python_helper" 2>"$missing_python_err"; then
  echo "expected missing Python selection to fail" >&2
  exit 1
fi
grep -F "Autopsy requires Python 3.12 or newer" "$missing_python_err" >/dev/null

if PATH="$empty_selector_dir" PYTHON=missing-python /bin/sh -c '. "$1"; autopsy_select_python >/dev/null' sh "$python_helper" 2>"$missing_explicit_python_err"; then
  echo "expected missing explicit PYTHON to fail" >&2
  exit 1
fi
grep -F "Autopsy could not find PYTHON=missing-python" "$missing_explicit_python_err" >/dev/null

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
if [ "\$1" = "unlink" ] && [ "\${2:-}" = "autopsy-memory" ]; then
  /bin/rm -f "$brew_root/bin/autopsy"
  exit 0
fi
if [ "\$1" = "link" ] && [ "\${2:-}" = "--overwrite" ] && [ "\${3:-}" = "autopsy-memory" ]; then
  /bin/cat > "$brew_root/bin/autopsy" <<'WRAPPER'
#!/bin/sh
AUTOPSY_UNIFIED_MEMORY=1 exec "$target_dir/autopsy" "\$@"
WRAPPER
  /bin/chmod 0755 "$brew_root/bin/autopsy"
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

PATH="$brew_root/bin" PYTHONPATH="$ROOT_DIR/src" AUTOPSY_APP_SUPPORT_DIR="$TMP_DIR/repair-actual-support" "$PYTHON_BIN" -m autopsy_memory.cli install --skip-instructions --skip-menubar --skip-doctor --skip-model-warmup > "$TMP_DIR/install-repair-actual.json"
"$PYTHON_BIN" - "$TMP_DIR/install-repair-actual.json" "$brew_root" "$TMP_DIR/repair-actual-support" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
brew_root = Path(sys.argv[2]).resolve()
support_root = Path(sys.argv[3]).resolve()
path_repair = payload.get("path_repair") or {}
assert path_repair.get("ok") is True, path_repair
assert path_repair.get("repaired") is True, path_repair
assert Path(path_repair.get("homebrew_prefix", "")).resolve() == brew_root, path_repair
assert path_repair.get("check_before", {}).get("legacy_wrapper") is True, path_repair
assert path_repair.get("check_after", {}).get("ok") is True, path_repair
assert path_repair.get("check_after", {}).get("package_entrypoint") is True, path_repair
assert path_repair.get("check_after", {}).get("path", "").endswith("/homebrew/bin/autopsy"), path_repair
assert path_repair.get("backups"), path_repair
assert all(str(Path(backup).resolve()).startswith(str(support_root / "Backups")) for backup in path_repair.get("backups")), path_repair
commands = path_repair.get("commands") or []
assert any(command.get("args", [])[-2:] == ["unlink", "autopsy-memory"] and command.get("returncode") == 0 for command in commands), commands
assert any(command.get("args", [])[-3:] == ["link", "--overwrite", "autopsy-memory"] and command.get("returncode") == 0 for command in commands), commands
workflow = payload.get("workflow") or {}
assert workflow.get("complete") is True, workflow
assert payload.get("model_warmup", {}).get("reason") == "skip_model_warmup", payload.get("model_warmup")
assert (brew_root / "bin" / "autopsy").exists(), path_repair
assert "AUTOPSY_UNIFIED_MEMORY" in (brew_root / "bin" / "autopsy").read_text(encoding="utf-8"), path_repair
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
assert "autopsy install" in onboarding.get("message", ""), onboarding
assert payload.get("activity", {}).get("attention") == [], payload.get("activity")
assert payload.get("snapshot", {}).get("schema_version") == 1, payload.get("snapshot")
PY
elif [ "${AUTOPSY_INSTALL_MATRIX_REQUIRE_RUNTIME:-0}" = "1" ]; then
  echo "install-matrix-check: missing embedded runtime dependencies" >&2
  exit 1
else
  echo "install-matrix-check: skipped fresh activity runtime smoke; embedded runtime dependencies are not installed" >&2
fi

echo "install-matrix-check: ok"
