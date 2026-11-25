#!/usr/bin/env sh

autopsy_select_python() {
  if [ -n "${PYTHON:-}" ]; then
    if command -v "$PYTHON" >/dev/null 2>&1; then
      command -v "$PYTHON"
      return 0
    fi
    echo "Autopsy could not find PYTHON=$PYTHON." >&2
    return 127
  fi

  for candidate in ${AUTOPSY_PYTHON_CANDIDATES:-python3.12 python3.13 python3.14 python3}; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done

  echo "Autopsy requires Python 3.12 or newer. Install python3.12 or set PYTHON=/path/to/python." >&2
  return 127
}

autopsy_check_python_version() {
  python_bin="${1:?missing python path}"
  "$python_bin" - <<'PY'
import os
import sys

version = sys.version.split()[0]
if sys.version_info < (3, 12):
    raise SystemExit(f"Autopsy requires Python 3.12 or newer; {sys.executable} reports Python {version}.")
if sys.version_info >= (3, 15) and os.environ.get("AUTOPSY_ALLOW_UNTESTED_PYTHON") != "1":
    raise SystemExit(
        f"Autopsy supports Python 3.12 to 3.14; {sys.executable} reports Python {version}, "
        "which its embedded FalkorDB has no prebuilt packages for yet. Install Python 3.13 "
        "(for example: sudo dnf install python3.13) and rerun with PYTHON=python3.13, "
        "or set AUTOPSY_ALLOW_UNTESTED_PYTHON=1 to try anyway."
    )
PY
}
