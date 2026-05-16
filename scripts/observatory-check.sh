#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/observatory"

cd "$APP_DIR"

npm install --cache .npm-cache
npm run check
npm run build

cd "$APP_DIR/src-tauri"
cargo fmt --check
cargo check

echo "observatory-check: ok"
