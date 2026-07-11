#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PACKAGED_SETUP="${REPO_ROOT}/src/autopsy_memory/evaluation/competitors/mem0/setup.sh"

if [[ ! -x "${PACKAGED_SETUP}" ]]; then
  printf 'Packaged Mem0 bootstrap is missing or not executable: %s\n' "${PACKAGED_SETUP}" >&2
  exit 1
fi

exec "${PACKAGED_SETUP}" "$@"
