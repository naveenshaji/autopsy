#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/menubar"

cd "$APP_DIR"
swift build

echo "menubar-check: ok"
