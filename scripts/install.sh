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
VENV_DIR="${AUTOPSY_MEMORY_VENV:-$ROOT_DIR/.venv}"
EXTRA="${AUTOPSY_MEMORY_EXTRA:-dev}"

"$PYTHON" - <<'PY'
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Autopsy requires Python 3.12 or newer.")
PY

"$PYTHON" -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"
python -m pip install -U pip
python -m pip install -e "$ROOT_DIR[$EXTRA]"
autopsy doctor
