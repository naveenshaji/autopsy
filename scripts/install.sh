#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
VENV_DIR="${AUTOPSY_MEMORY_VENV:-$ROOT_DIR/.venv}"
EXTRA="${AUTOPSY_MEMORY_EXTRA:-ml,dev}"

"$PYTHON" -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"
python -m pip install -U pip
python -m pip install -e "$ROOT_DIR[$EXTRA]"
autopsy doctor
