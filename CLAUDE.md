<!-- AUTOPSY_MEMORY_START v1 -->
## Autopsy Memory Usage

Use Autopsy memory for nontrivial repo work, debugging, releases, architecture questions, and any task where prior decisions may matter.

Default behavior is system-wide. Do not pass `--workspace` unless explicitly debugging legacy workspace resolution.

Before substantial work:
- Run `autopsy status --current-only`.
- Run `autopsy consult --current-only --query "<task/context query>"`.
- Prefer `consult` over `search` when relying on memory.

For repo-specific work:
- Use `autopsy consult --scope repo --repo <repo-root> --query "<query>"` when you only want memories from one repo.
- If running inside a known repo, Autopsy can infer and boost the current repo automatically.
- Use `--scope system` for cross-repo conventions, user preferences, release patterns, or machine-level debugging history.

When reading memory:
- Inspect `workflow.complete`.
- If `workflow.complete` is `false`, follow suggested next steps before relying on the result.
- If `workflow.status` is `weak_signals_only`, treat side-channel candidates as debugging hints, not an answer.
- Use `item` for exact fact inspection.
- Use `timeline` for supersession, invalidation, or stale facts.
- Use `neighbors` for related decisions, attempts, dependencies, or reversions.
- Treat memory as evidence, not absolute truth; verify drift-prone facts against code/config/git.

When writing memory:
- After material work, write durable outcomes with `autopsy capture-outcome`.
- Use specific outcomes: `decision`, `attempt`, `question`, `preference`, `plan`, `resolved-question`, or `reverted-attempt`.
- Add explicit relations when possible: `--informed-by`, `--answers`, `--supersedes`, `--reverts`, `--depends-on`, `--implements`, `--constrains`, or `--refines`.
- For repo work, either pass `--scope repo --repo <repo-root>` or `--repository-root-path <repo-root>` so writes are attributed correctly.
- Inspect `write_quality.warnings`; short or duplicate memories should usually be expanded, updated, or related to existing memories.

For backup and restore:
- Run `autopsy backup` before large memory-system changes.
- Run `autopsy restore <backup.json> --dry-run` before any restore.
- Use `autopsy restore <backup.json> --replace --yes` only when intentionally replacing matching restored keys.

For memory-system changes:
- Run `autopsy health`.
- Run `autopsy benchmark --sample-size 5 --include-sync`.
- Do not claim memory health unless the benchmark passes or failures are explicitly reported.
<!-- AUTOPSY_MEMORY_END -->
