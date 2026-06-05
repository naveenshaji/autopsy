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

  for candidate in ${AUTOPSY_PYTHON_CANDIDATES:-python3.12 python3.13 python3}; do
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
import sys

if sys.version_info < (3, 12):
    version = sys.version.split()[0]
    raise SystemExit(f"Autopsy requires Python 3.12 or newer; {sys.executable} reports Python {version}.")
PY
}
