#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$ROOT_DIR/scripts/lib/python.sh"
PYTHON_BIN="$(autopsy_select_python)"
VENV_DIR="${AUTOPSY_MEMORY_VENV:-$ROOT_DIR/.venv}"
EXTRA="${AUTOPSY_MEMORY_EXTRA:-dev}"

autopsy_check_python_version "$PYTHON_BIN"

"$PYTHON_BIN" -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"
python -m pip install -U pip
python -m pip install -e "$ROOT_DIR[$EXTRA]"
autopsy doctor
