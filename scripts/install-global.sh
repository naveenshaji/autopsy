#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
INSTALL_NAME="autopsy-memory"

usage() {
  cat <<'EOF'
Usage: scripts/install-global.sh [--prefix PATH] [--extra EXTRA] [--no-ml]

Installs the standalone Autopsy memory CLI into a versioned, Homebrew-style
layout:

  <prefix>/Cellar/autopsy-memory/<version>/
  <prefix>/opt/autopsy-memory -> <prefix>/Cellar/autopsy-memory/<version>
  <prefix>/bin/autopsy

Environment:
  PYTHON                 Python 3.12+ interpreter to bootstrap with.
  AUTOPSY_INSTALL_PREFIX Install prefix. Defaults to /opt/homebrew when writable,
                         otherwise ~/.local.
  AUTOPSY_INSTALL_EXTRA  Package extra to install. Defaults to ml.
EOF
}

PREFIX="${AUTOPSY_INSTALL_PREFIX:-}"
EXTRA="${AUTOPSY_INSTALL_EXTRA:-ml}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --prefix)
      PREFIX="${2:?missing value for --prefix}"
      shift 2
      ;;
    --extra)
      EXTRA="${2:?missing value for --extra}"
      shift 2
      ;;
    --no-ml)
      EXTRA=""
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "install-global: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ -z "${PYTHON:-}" ]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON=python3.12
  else
    PYTHON=python3
  fi
fi

"$PYTHON" - <<'PY'
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Autopsy requires Python 3.12 or newer.")
PY

if [ -z "$PREFIX" ]; then
  if [ -d /opt/homebrew ] && [ -w /opt/homebrew ]; then
    PREFIX=/opt/homebrew
  else
    PREFIX="$HOME/.local"
  fi
fi

VERSION="$("$PYTHON" - "$ROOT_DIR/pyproject.toml" <<'PY'
import sys
import tomllib
from pathlib import Path

with Path(sys.argv[1]).open("rb") as handle:
    print(tomllib.load(handle)["project"]["version"])
PY
)"

CELLAR_DIR="$PREFIX/Cellar/$INSTALL_NAME/$VERSION"
OPT_DIR="$PREFIX/opt/$INSTALL_NAME"
BIN_DIR="$PREFIX/bin"
TMP_DIR="$CELLAR_DIR.tmp.$$"
VENV_DIR="$TMP_DIR/venv"
DIST_DIR="$TMP_DIR/dist"
TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM HUP

mkdir -p "$BIN_DIR" "$(dirname "$OPT_DIR")" "$(dirname "$CELLAR_DIR")" "$DIST_DIR"

"$PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install -U pip build >/dev/null
"$VENV_DIR/bin/python" -m build --wheel --outdir "$DIST_DIR" "$ROOT_DIR" >/dev/null

WHEEL_PATH="$(find "$DIST_DIR" -maxdepth 1 -name 'autopsy_memory-*.whl' | sort | tail -1)"
if [ -z "$WHEEL_PATH" ]; then
  echo "install-global: wheel build did not produce autopsy_memory wheel" >&2
  exit 1
fi

if [ -n "$EXTRA" ]; then
  "$VENV_DIR/bin/python" -m pip install "$WHEEL_PATH[$EXTRA]" >/dev/null
else
  "$VENV_DIR/bin/python" -m pip install "$WHEEL_PATH" >/dev/null
fi

if [ -d "$ROOT_DIR/apps/observatory" ]; then
  mkdir -p "$TMP_DIR/observatory"
  (
    cd "$ROOT_DIR/apps/observatory"
    tar \
      --exclude node_modules \
      --exclude .npm-cache \
      --exclude dist \
      --exclude target \
      --exclude src-tauri/target \
      -cf - .
  ) | (
    cd "$TMP_DIR/observatory"
    tar -xf -
  )
fi

rm -rf "$CELLAR_DIR.previous"
if [ -d "$CELLAR_DIR" ]; then
  mv "$CELLAR_DIR" "$CELLAR_DIR.previous"
fi
mv "$TMP_DIR" "$CELLAR_DIR"
trap - EXIT INT TERM HUP

ln -sfn "$CELLAR_DIR" "$OPT_DIR"

backup_existing() {
  target="$1"
  if [ -e "$target" ] && ! grep -q "AUTOPSY_STANDALONE_MEMORY_WRAPPER" "$target" 2>/dev/null; then
    cp "$target" "$target.legacy-$TIMESTAMP"
  fi
}

write_wrapper() {
  target="$1"
  module="$2"
  backup_existing "$target"
  cat > "$target" <<EOF
#!/usr/bin/env sh
# AUTOPSY_STANDALONE_MEMORY_WRAPPER
set -eu
export AUTOPSY_UNIFIED_MEMORY="\${AUTOPSY_UNIFIED_MEMORY:-1}"
exec "$OPT_DIR/venv/bin/python" -m "$module" "\$@"
EOF
  chmod +x "$target"
}

write_wrapper "$BIN_DIR/autopsy" "autopsy_memory.cli"
write_wrapper "$BIN_DIR/autopsy-memory-worker" "autopsy_memory.worker"
write_wrapper "$BIN_DIR/autopsy-memory-mcp" "autopsy_memory.mcp_bridge"

PATH="$BIN_DIR:$PATH" "$BIN_DIR/autopsy" version --json >/dev/null
PATH="$BIN_DIR:$PATH" "$BIN_DIR/autopsy" doctor >/dev/null

cat <<EOF
Installed Autopsy Memory $VERSION
  prefix: $PREFIX
  cellar: $CELLAR_DIR
  opt: $OPT_DIR
  autopsy: $BIN_DIR/autopsy
EOF
