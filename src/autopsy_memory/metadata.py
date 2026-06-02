"""Package metadata and generated instruction text."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys


PACKAGE_NAME = "autopsy-memory"
FALLBACK_VERSION = "0.1.12"

AGENT_INSTRUCTIONS = """## Autopsy Memory Usage

Use Autopsy memory for nontrivial repo work, debugging, releases, architecture questions, and any task where prior decisions may matter.

Default behavior is system-wide. Do not pass `--workspace` unless explicitly debugging legacy workspace resolution.

Before substantial work:
- Run `autopsy status --current-only`.
- Run `autopsy context --current-only --query "<task/context query>"` when you want a compact pre-work memory pack.
- Use `autopsy context --format text --current-only --query "<task/context query>"` when you want a ready-to-insert context block instead of JSON.
- Run `autopsy consult --current-only --query "<task/context query>"`.
- Prefer `context` for pre-work grounding and `consult` over `search` when relying on memory.

For repo-specific work:
- Use `autopsy consult --scope repo --repo <repo-root> --query "<query>"` when you only want memories from one repo.
- Use `autopsy context --scope repo --repo <repo-root> --format text --query "<query>"` when you want a repo-filtered context block.
- If running inside a known repo, Autopsy can infer and boost the current repo automatically.
- Use `--scope system` for cross-repo conventions, user preferences, release patterns, or machine-level debugging history.
- Use `--kind decision`, `--kind attempt`, `--kind observation`, `--kind procedure`, or comma-separated `--kind attempt,plan` when the answer should only consider specific memory kinds.
- Use `--memory-type semantic`, `--memory-type episodic`, `--memory-type procedural`, or `--memory-type observation` when the answer should target a cognitive memory layer; combine with `--kind` when both should apply.
- Use `--tag <tag>`, `--namespace <scope>`, `--entity-scope TYPE:ID`, `--user-id`, `--agent-id`, `--app-id`, `--run-id`, `--group-id`, `--metadata <key><op><value>`, and `--filter-json '<json>'` filters when you need durable topic, scoped-container, entity partition, source, owner, environment, score, tier, or boolean read constraints.
- Use `--min-fact-rating 0.0..1.0` on `consult`, `context`, `search`, or `neighbors` when relation evidence quality matters.

When reading memory:
- Inspect `workflow.complete`.
- If `workflow.complete` is `false`, follow suggested next steps before relying on the result.
- If `workflow.status` is `weak_signals_only`, treat side-channel candidates as debugging hints, not an answer.
- If `workflow.status` is `needs_lineage_review`, inspect timeline or neighbors before relying on a stale or superseded memory.
- Use `retrieval.items[].evidence` in `context` output to see why a memory was selected and what source episode/repo produced it.
- Use `retrieval.graph_context.items[]` in `context` output for bounded related memories found through semantic graph neighbors.
- Use `context_block` from JSON output, or `--format text`, when passing memory into an agent context window.
- Use `item` for exact fact inspection.
- Use `timeline` for supersession, invalidation, or stale facts.
- Use `history <stable-key>` when the answer depends on how one memory changed, especially after update, expiration, pinning, or delete operations.
- Use `neighbors` for related decisions, attempts, dependencies, or reversions.
- Use `observe --stable-key <stable-key>` to draft or `--write` an evidence-backed observation when one memory's graph neighborhood should become reusable context; use `--write-if-stale` to refresh only after evidence drift.
- Use `expire <stable-key>` for obsolete memories that should leave current reads but remain available to history and `--as-of` reconstruction.
- Use `pin <stable-key>` for core memories that should appear in `context` packs without depending on task-specific retrieval; add `--label`, `--description`, `--limit`, `--read-only`, or `--shared` when the pin should behave like an always-visible memory block.
- Use `feedback <stable-key> --rating useful|not-useful|neutral` after important reads; feedback informs audit activation and bounded consult ranking.
- Treat memory as evidence, not absolute truth; verify drift-prone facts against code/config/git.

When writing memory:
- After material work, write durable outcomes with `autopsy capture-outcome`.
- Use specific outcomes: `decision`, `attempt`, `observation`, `procedure`, `question`, `preference`, `plan`, `resolved-question`, or `reverted-attempt`.
- Add at least one explicit semantic relation for durable writes: `--informed-by`, `--answers`, `--supersedes`, `--reverts`, `--depends-on`, `--implements`, `--constrains`, or `--refines`.
- Relation flags are ontology-checked; use them between memory items, and target `--answers` at an open question.
- Use `--no-relations-ok` only when the memory is intentionally standalone and no semantic relation applies.
- Use `--tag`, `--namespace`, entity-scope flags, and `--metadata KEY=VALUE` on writes when future reads should target a durable container, scoped namespace, user/agent/app/run/group partition, or structured field.
- Use `--relation-valid-at`, `--relation-invalid-at`, or `--relation-expires-at` when a new semantic relation is only true during a known time window.
- Use `--fact-rating 0.0..1.0` on writes with semantic relation flags when later reads should filter weak relation facts.
- For repo work, either pass `--scope repo --repo <repo-root>` or `--repository-root-path <repo-root>` so writes are attributed correctly.
- Inspect `write_quality.warnings`; `missing_semantic_relation`, short, duplicate, or low-signal memories should be expanded, updated, or related before relying on them.

For backup and restore:
- Run `autopsy backup` before large memory-system changes.
- Run `autopsy restore <backup.json> --dry-run` before any restore.
- Use `autopsy restore <backup.json> --replace --yes` only when intentionally replacing matching restored keys.

For memory-system changes:
- Run `autopsy health`.
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
