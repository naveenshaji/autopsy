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
  AUTOPSY_INSTALL_EXTRA  Package extra to install. ML is included by default.
  AUTOPSY_INSTALL_MENUBAR_AGENT
                         Set to 0 to skip installing the macOS menu bar
                         LaunchAgent. Defaults to 1 on macOS.
EOF
}

. "$ROOT_DIR/scripts/lib/python.sh"

PREFIX="${AUTOPSY_INSTALL_PREFIX:-}"
EXTRA="${AUTOPSY_INSTALL_EXTRA:-}"

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
      # Compatibility no-op. ML is part of the base Autopsy runtime now.
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

PYTHON_BIN="$(autopsy_select_python)"
autopsy_check_python_version "$PYTHON_BIN"

if [ -z "$PREFIX" ]; then
  if [ -d /opt/homebrew ] && [ -w /opt/homebrew ]; then
    PREFIX=/opt/homebrew
  else
    PREFIX="$HOME/.local"
  fi
fi

VERSION="$("$PYTHON_BIN" - "$ROOT_DIR/pyproject.toml" <<'PY'
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

"$PYTHON_BIN" -m venv "$VENV_DIR"
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

if [ -d "$ROOT_DIR/apps/menubar" ]; then
  mkdir -p "$TMP_DIR/menubar"
  (
    cd "$ROOT_DIR/apps/menubar"
    tar \
      --exclude target \
      --exclude .build \
      -cf - .
  ) | (
    cd "$TMP_DIR/menubar"
    tar -xf -
  )
  if [ "$(uname -s)" = "Darwin" ] && command -v swift >/dev/null 2>&1; then
    "$VENV_DIR/bin/python" -m autopsy_memory.cli menubar --dir "$TMP_DIR/menubar" --build --release >/dev/null
  else
    echo "install-global: menu bar app was not prebuilt; it will build on first macOS launch" >&2
  fi
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

if [ "$(uname -s)" = "Darwin" ] && [ "${AUTOPSY_INSTALL_MENUBAR_AGENT:-1}" != "0" ] && [ -d "$OPT_DIR/menubar" ]; then
  if ! PATH="$BIN_DIR:$PATH" "$BIN_DIR/autopsy" menubar --dir "$OPT_DIR/menubar" --install-launch-agent >/dev/null; then
    echo "install-global: menu bar LaunchAgent was not installed; run 'autopsy menubar --install-launch-agent' from a graphical macOS session" >&2
  fi
fi

cat <<EOF
Installed Autopsy Memory $VERSION
  prefix: $PREFIX
  cellar: $CELLAR_DIR
  opt: $OPT_DIR
  autopsy: $BIN_DIR/autopsy
EOF
