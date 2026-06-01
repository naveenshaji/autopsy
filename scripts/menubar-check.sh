#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/menubar"
PYTHON="${PYTHON:-python3}"

cd "$ROOT_DIR"
PYTHONPATH="$ROOT_DIR/src" "$PYTHON" -m autopsy_memory.cli menubar --build >/dev/null
test -f "$APP_DIR/.build/debug/AutopsyMenuBar.app/Contents/Info.plist"

echo "menubar-check: ok"
