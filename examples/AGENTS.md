## Autopsy Memory Usage

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
