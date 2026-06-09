<!-- AUTOPSY_MEMORY_START v1 -->
## Autopsy Memory Usage

Use Autopsy memory for nontrivial repo work, debugging, releases, architecture questions, and any task where prior decisions may matter.

Default behavior is system-wide. Do not pass `--workspace` unless explicitly debugging legacy workspace resolution.

Before substantial work:
- Run `autopsy status --current-only`.
- Run `autopsy context --current-only --query "<task/context query>"` when you want a compact pre-work memory pack.
- Use `autopsy context --format text --current-only --query "<task/context query>"` when you want a ready-to-insert context block instead of JSON.
- Run `autopsy consult --current-only --query "<task/context query>"`.
- Prefer `context` for pre-work grounding and `consult` over `search` when relying on memory.
- Consult Autopsy again within the same turn when the question changes, retrieval is incomplete, lineage/staleness warnings appear, or a decision depends on memory not covered by the first read.

Live context graph:
- Context graph capture is configured for Codex hooks. Do not call `autopsy context-event`; `autopsy codex-hook` records the current Codex session id from trusted hook payloads and records allowlisted `PostToolUse` Bash command text automatically.
- Do not choose, invent, derive, or manually pass a graph thread id in Codex hook mode.
- Keep the graph visible for the whole Codex chat. At chat start, after resume or compaction, and before continuing substantial work if the Browser tab may have been closed, check whether this chat's Autopsy context graph is open in the Codex in-app Browser. If it is missing or stale, reopen it unless the user explicitly asked to hide it.
- The Autopsy menu bar LaunchAgent keeps the local graph worker warm. Agents should not run hidden keepalive commands; only reopen the Browser tab when visibility is lost.
- Get the graph URL with `autopsy context-graph-url --codex-current`. This resolves the real current Codex session id from trusted hook state. Do not pass `--thread-id`; if the command reports `no_current_codex_hook_session` or `stale_codex_hook_session`, do not retry with a fabricated id. Tell the user hooks are not trusted/observed yet, then retry after a trusted Codex tool call updates hook state.
- Do not pass `--open`; it uses the macOS default browser. Open this URL in the Codex in-app Browser, not `web.run` and not macOS `open`: use the Browser plugin/control-in-app-browser path through `mcp__node_repl.js`, connect to the `iab` browser, set visibility to true, use the selected tab or create one, then call `tab.goto(URL)`.
- Hook capture records only allowlisted command cards. It skips preflight, permission, lifecycle-only, prompt, non-Bash tool, compaction, subagent hooks, and non-allowlisted commands.
- Capture only the exact shell command text for context fetched through allowlisted commands. Never write generic graph events such as `file_read`, `web_search`, `tool_result`, `memory_consult`, `memory_write`, `turn_completed`, or status-only lifecycle events; never synthesize separate nodes for what the command read, searched, returned, or changed; never include file contents, fetched snippets, search results, metadata, secrets, or any command output in graph events.
- The context graph viewer may deterministically render semantic labels, chips, and memory relation nodes from captured command text and Autopsy's own memory graph; agents still write only the exact allowlisted command string.
- Capture is allowlisted only for context-fetching commands: capture commands where every executable shell segment, including pipeline segments, starts with `autopsy status`, `autopsy context`, `autopsy consult`, `autopsy search`, `autopsy item`, `autopsy timeline`, `autopsy history`, `autopsy neighbors`, `git status`, `git diff`, `git show`, `git log`, `rg`, `nl`, or `sed`; a leading `cd ...` setup segment is allowed. Ignore build, test, lint, package, write, shell redirection, command substitution, background operators, multiline commands, and other action commands, even when chained with an allowlisted read command.

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
- Multiple writes in one turn are valid when they capture distinct decisions, attempts, observations, procedures, questions, or resolved questions. Avoid duplicate or low-signal writes.
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
<!-- AUTOPSY_MEMORY_END -->
