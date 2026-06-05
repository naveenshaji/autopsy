#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$ROOT_DIR/scripts/lib/python.sh"
PYTHON_BIN="$(autopsy_select_python)"
autopsy_check_python_version "$PYTHON_BIN"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "homebrew-current-check: requires macOS" >&2
  exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "homebrew-current-check: requires Apple Silicon Homebrew" >&2
  exit 1
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "homebrew-current-check: Homebrew is not installed" >&2
  exit 1
fi
export HOMEBREW_NO_AUTO_UPDATE="${HOMEBREW_NO_AUTO_UPDATE:-1}"
export HOMEBREW_NO_ENV_HINTS="${HOMEBREW_NO_ENV_HINTS:-1}"

cd "$ROOT_DIR"

TMP_DIR="${TMPDIR:-/tmp}/autopsy-homebrew-current-$$"
TAP_NAME="local/autopsy-current-$$"
TAP_USER="${TAP_NAME%%/*}"
TAP_REPO="${TAP_NAME#*/}"
TAP_DIR="$(brew --repository)/Library/Taps/$TAP_USER/homebrew-$TAP_REPO"
FORMULA_PATH="$TAP_DIR/Formula/autopsy-memory.rb"
CONFLICT_TAPS="$TMP_DIR/conflict-taps"
AUTOPSY_HOMEBREW_CURRENT_INSTALL_ATTEMPTED=0
AUTOPSY_HOMEBREW_CURRENT_INSTALLED_TEMP=0
AUTOPSY_HOMEBREW_CURRENT_PREVIOUS_INSTALLED=0
AUTOPSY_HOMEBREW_CURRENT_PREVIOUS_FORMULA=""

cleanup() {
  status=$?
  if [ "$AUTOPSY_HOMEBREW_CURRENT_INSTALL_ATTEMPTED" = "1" ] && [ "${CI:-}" != "true" ] && [ "${AUTOPSY_HOMEBREW_CURRENT_KEEP_LOCAL:-0}" != "1" ]; then
    brew uninstall --force "$TAP_NAME/autopsy-memory" >/dev/null 2>&1 || brew uninstall --force autopsy-memory >/dev/null 2>&1 || true
  fi
  if [ "$AUTOPSY_HOMEBREW_CURRENT_INSTALLED_TEMP" != "1" ] || [ "${AUTOPSY_HOMEBREW_CURRENT_KEEP_LOCAL:-0}" != "1" ]; then
    brew untap --force "$TAP_NAME" >/dev/null 2>&1 || true
  fi
  if [ -f "$CONFLICT_TAPS" ]; then
    while IFS= read -r tap_name; do
      [ -n "$tap_name" ] || continue
      brew tap "$tap_name" >/dev/null 2>&1 || true
    done < "$CONFLICT_TAPS"
  fi
  if [ "$AUTOPSY_HOMEBREW_CURRENT_PREVIOUS_INSTALLED" = "1" ] && [ "${CI:-}" != "true" ] && [ "${AUTOPSY_HOMEBREW_CURRENT_KEEP_LOCAL:-0}" != "1" ] && [ "${AUTOPSY_HOMEBREW_CURRENT_RESTORE_LOCAL:-1}" != "0" ]; then
    restore_formula="$AUTOPSY_HOMEBREW_CURRENT_PREVIOUS_FORMULA"
    [ -n "$restore_formula" ] || restore_formula="autopsy-memory"
    echo "homebrew-current-check: restoring previous $restore_formula install"
    if ! HOMEBREW_NO_INSTALL_CLEANUP=1 brew install "$restore_formula" >/dev/null 2>&1; then
      echo "homebrew-current-check: failed to restore previous $restore_formula install" >&2
      status=1
    fi
  fi
  rm -rf "$TMP_DIR"
  exit "$status"
}
trap cleanup EXIT INT TERM HUP

mkdir -p "$TMP_DIR"
brew tap-new "$TAP_NAME" >/dev/null

"$PYTHON_BIN" - "$ROOT_DIR" "$TMP_DIR" "$FORMULA_PATH" <<'PY'
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tarfile

root = Path(sys.argv[1]).resolve()
tmp_dir = Path(sys.argv[2]).resolve()
formula_target = Path(sys.argv[3]).resolve()

pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE)
if not match:
    raise SystemExit("Could not read project version from pyproject.toml")
version = match.group(1)

archive_path = tmp_dir / f"autopsy-{version}.tar.gz"
prefix = f"autopsy-{version}"
paths = [
    raw.decode()
    for raw in subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
    ).split(b"\0")
    if raw
]

with tarfile.open(archive_path, "w:gz") as archive:
    for rel in sorted(paths):
        path = root / rel
        if not path.exists() or path.is_dir():
            continue
        info = archive.gettarinfo(str(path), arcname=f"{prefix}/{rel}")
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.mtime = 0
        with path.open("rb") as handle:
            archive.addfile(info, handle)

sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
formula = (root / "Formula" / "autopsy-memory.rb").read_text(encoding="utf-8")
formula = re.sub(
    r'url "https://github\.com/naveenshaji/autopsy/archive/refs/tags/v[^"]+\.tar\.gz"',
    f'url "{archive_path.as_uri()}"',
    formula,
    count=1,
)
formula = re.sub(r'sha256 "[0-9a-f]{64}"', f'sha256 "{sha256}"', formula, count=1)
if archive_path.as_uri() not in formula:
    raise SystemExit("Failed to patch formula URL to current checkout archive")

formula_target.parent.mkdir(parents=True, exist_ok=True)
formula_target.write_text(formula, encoding="utf-8")
print(f"homebrew-current-check: wrote {formula_target}")
print(f"homebrew-current-check: source {archive_path}")
PY

brew style "$FORMULA_PATH"

if [ "${AUTOPSY_HOMEBREW_CURRENT_INSTALL:-0}" != "1" ]; then
  echo "homebrew-current-check: skipped install; set AUTOPSY_HOMEBREW_CURRENT_INSTALL=1 to install/test"
  exit 0
fi

if [ "${CI:-}" != "true" ] && [ "${AUTOPSY_HOMEBREW_CURRENT_ALLOW_LOCAL:-0}" != "1" ]; then
  echo "homebrew-current-check: refusing local install without AUTOPSY_HOMEBREW_CURRENT_ALLOW_LOCAL=1" >&2
  exit 1
fi

if brew list --formula autopsy-memory >/dev/null 2>&1; then
  AUTOPSY_HOMEBREW_CURRENT_PREVIOUS_INSTALLED=1
  AUTOPSY_HOMEBREW_CURRENT_PREVIOUS_FORMULA="$(brew list --formula --full-name autopsy-memory 2>/dev/null | sed -n '1p' || true)"
  if [ "${CI:-}" = "true" ] || [ "${AUTOPSY_HOMEBREW_CURRENT_REPLACE_LOCAL:-0}" = "1" ]; then
    brew uninstall --force autopsy-memory
  else
    echo "homebrew-current-check: autopsy-memory is already installed; use CI or a disposable Homebrew prefix for current-source install checks" >&2
    echo "homebrew-current-check: set AUTOPSY_HOMEBREW_CURRENT_REPLACE_LOCAL=1 only if replacing the local install is intentional" >&2
    echo "homebrew-current-check: by default the previous install is restored after the check unless AUTOPSY_HOMEBREW_CURRENT_KEEP_LOCAL=1 is set" >&2
    exit 1
  fi
fi

tap_dir_for() {
  tap_user="${1%%/*}"
  tap_repo="${1#*/}"
  printf '%s/Library/Taps/%s/homebrew-%s\n' "$(brew --repository)" "$tap_user" "$tap_repo"
}

: > "$CONFLICT_TAPS"
for tap_name in $(brew tap); do
  [ "$tap_name" != "$TAP_NAME" ] || continue
  if [ -f "$(tap_dir_for "$tap_name")/Formula/autopsy-memory.rb" ]; then
    echo "$tap_name" >> "$CONFLICT_TAPS"
  fi
done
while IFS= read -r tap_name; do
  [ -n "$tap_name" ] || continue
  echo "homebrew-current-check: temporarily untapping $tap_name"
  brew untap "$tap_name" >/dev/null
done < "$CONFLICT_TAPS"

AUTOPSY_HOMEBREW_CURRENT_INSTALL_ATTEMPTED=1
HOMEBREW_NO_INSTALL_CLEANUP=1 brew install --build-from-source "$TAP_NAME/autopsy-memory"
AUTOPSY_HOMEBREW_CURRENT_INSTALLED_TEMP=1
HOMEBREW_NO_INSTALL_CLEANUP=1 brew test --force "$TAP_NAME/autopsy-memory"
echo "homebrew-current-check: ok"
