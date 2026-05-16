"""Package metadata and generated instruction text."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys


PACKAGE_NAME = "autopsy-memory"
FALLBACK_VERSION = "0.1.0"

AGENT_INSTRUCTIONS = """## Autopsy Memory Usage

Use Autopsy memory for nontrivial repo work, debugging, releases, architecture questions, and any task where prior decisions may matter.

Before substantial work:
- Run `autopsy status --current-only`.
- Run `autopsy consult --current-only --query "<task/context query>"`.
- Prefer `consult` over `search` when relying on memory.

When reading memory:
- Inspect `workflow.complete`.
- If `workflow.complete` is `false`, follow suggested next steps before relying on the result.
- Use `item`, `timeline`, and `neighbors` for exact fact inspection.
- Treat memory as evidence, not absolute truth; verify drift-prone facts against code/config/git.

When writing memory:
- After material work, write durable outcomes with `autopsy capture-outcome`.
- Use specific outcomes: `decision`, `attempt`, `question`, `preference`, `plan`, `resolved-question`, or `reverted-attempt`.
- Add explicit relations when possible: `--informed-by`, `--answers`, `--supersedes`, `--reverts`, `--depends-on`, `--implements`, `--constrains`, or `--refines`.
- For repo work, pass `--repository-root-path <repo-root>` or `--scope repo --repo <repo-root>`.

For memory-system changes:
- Run `autopsy benchmark --sample-size 5 --include-sync`.
- Do not claim memory health unless the benchmark passes or failures are explicitly reported.
"""


def package_version() -> str:
    try:
        return importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return FALLBACK_VERSION


def cmd_version(args: argparse.Namespace) -> None:
    payload = {
        "version": package_version(),
        "package": PACKAGE_NAME,
        "python": sys.version.split()[0],
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(payload["version"])


def cmd_instructions(args: argparse.Namespace) -> None:
    if getattr(args, "json", False):
        print(json.dumps({"instructions": AGENT_INSTRUCTIONS}, indent=2))
    else:
        print(AGENT_INSTRUCTIONS.rstrip())
