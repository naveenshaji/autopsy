#!/usr/bin/env sh
set -eu

REPO="naveenshaji/autopsy"
VERSION="${AUTOPSY_VERSION:-${1:-}}"
PREFIX="${AUTOPSY_INSTALL_PREFIX:-}"

usage() {
  cat <<'EOF'
Usage: scripts/install-release.sh [VERSION]

Downloads an Autopsy release tarball from GitHub and runs scripts/install-global.sh
from the unpacked source tree. This is the non-Homebrew recovery path for Macs
where `brew update`, `brew upgrade`, or `brew reinstall` is blocked.

Environment:
  AUTOPSY_VERSION        Release version or tag, e.g. 0.1.30 or v0.1.30.
  AUTOPSY_INSTALL_PREFIX Install prefix passed through to install-global.sh.
  PYTHON                 Python 3.12+ interpreter used by install-global.sh.
EOF
}

case "${VERSION:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

if ! command -v curl >/dev/null 2>&1; then
  echo "install-release: curl is required" >&2
  exit 127
fi

if [ -z "$VERSION" ]; then
  VERSION="$(
    curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" |
      sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' |
      head -1
  )"
fi

if [ -z "$VERSION" ]; then
  echo "install-release: could not resolve latest release; pass AUTOPSY_VERSION=vX.Y.Z" >&2
  exit 1
fi

case "$VERSION" in
  v*) TAG="$VERSION" ;;
  *) TAG="v$VERSION" ;;
esac

TMP_DIR="${TMPDIR:-/tmp}/autopsy-release-install-$$"
ARCHIVE="$TMP_DIR/$TAG.tar.gz"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM HUP

mkdir -p "$TMP_DIR"
curl -fL "https://codeload.github.com/$REPO/tar.gz/refs/tags/$TAG" -o "$ARCHIVE"
tar -xzf "$ARCHIVE" -C "$TMP_DIR"

SOURCE_DIR="$TMP_DIR/autopsy-${TAG#v}"
if [ ! -x "$SOURCE_DIR/scripts/install-global.sh" ]; then
  echo "install-release: unpacked release is missing scripts/install-global.sh" >&2
  exit 1
fi

if [ -n "$PREFIX" ]; then
  AUTOPSY_INSTALL_PREFIX="$PREFIX" "$SOURCE_DIR/scripts/install-global.sh"
else
  "$SOURCE_DIR/scripts/install-global.sh"
fi
