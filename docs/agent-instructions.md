# Agent Instructions

Use Autopsy memory for nontrivial repo work, debugging, releases, architecture questions, and any task where prior decisions may matter.

Default behavior is system-wide. Do not pass `--workspace` unless explicitly debugging workspace resolution.

## Before Substantial Work

Run:

```bash
autopsy status --current-only
autopsy context --current-only --query "<task/context query>"
autopsy consult --current-only --query "<task/context query>"
```

Prefer `context` for a compact pre-work memory pack. Use `autopsy context --format text --current-only --query "<task/context query>"` when you want a ready-to-insert context block instead of JSON. Prefer `consult` over `search` when relying on memory.

Consult Autopsy again within the same turn when the question changes, retrieval is incomplete, lineage/staleness warnings appear, or a decision depends on memory not covered by the first read.

Compatibility form:

```bash
autopsy memory status --current-only
autopsy memory consult --current-only --query "<task/context query>"
```

## Repo-Specific Work

Use repo scope when only one repository should influence the answer:

```bash
autopsy consult --scope repo --repo <repo-root> --query "<query>"
autopsy context --scope repo --repo <repo-root> --format text --query "<query>"
```

If running inside a known repo, Autopsy can infer and boost the current repo automatically.

Use kind filters when the answer should only consider one memory type:

```bash
autopsy consult --kind decision --query "<query>"
autopsy consult --kind attempt,plan --query "<query>"
autopsy consult --kind observation --query "<query>"
autopsy consult --kind procedure --query "<query>"
```

Use cognitive memory-type filters when the answer should target a layer rather than a storage kind:

```bash
autopsy consult --memory-type semantic --query "<query>"
autopsy consult --memory-type episodic --query "<query>"
autopsy consult --memory-type procedural --query "<query>"
autopsy consult --memory-type observation --query "<query>"
```

`--memory-type` can be combined with `--kind`; Autopsy intersects the two filters.

Use tag filters when a task should only consider a tagged memory container. All requested tags must be present:

```bash
autopsy consult --tag release --tag repo:autopsy --query "<query>"
autopsy context --tag release,repo:autopsy --format text --query "<query>"
```

Use namespace filters when a task should only consider memories in a scoped user, agent, repo, release, product-area, or experiment container. All requested namespaces must be present:

```bash
autopsy consult --namespace release --namespace repo/autopsy --query "<query>"
autopsy context --namespace release,repo/autopsy --format text --query "<query>"
```

Use entity-scope filters when a task should only consider one user, agent, app, run/session, or group/tenant partition. All requested entity scopes must be present:

```bash
autopsy consult --entity-scope user:alice --agent-id planner --query "<query>"
autopsy context --user-id alice --app-id cli --run-id ticket-42 --format text --query "<query>"
```

Use `--filter-json` when a read needs boolean logic across kind, tags, namespaces, entity scopes, metadata, or item fields:

```bash
autopsy consult --filter-json '{"AND":[{"OR":[{"namespace":"release"},{"entity_scope":"user:alice"},{"metadata":{"score":{"gte":8}}}]},{"NOT":{"metadata":{"owner":"archived"}}}]}' --query "<query>"
```

Use `--min-fact-rating 0.0..1.0` on `consult`, `context`, `search`, or `neighbors` when relation evidence should only include facts at or above a quality threshold. Unrated legacy facts read as neutral `0.5`.

Use system scope for cross-repo conventions, user preferences, release patterns, or machine-level debugging history:

```bash
autopsy consult --scope system --query "<query>"
```

## Reading Memory

Inspect `workflow.complete`.

If `workflow.complete` is `false`, follow suggested next steps before relying on the result.

If `workflow.status` is `weak_signals_only`, treat relationship/vector candidates as debugging hints, not as a reliable answer.

If `workflow.status` is `needs_lineage_review`, inspect `timeline` or `neighbors` before relying on a stale or superseded memory.

Use `retrieval.items[].evidence` in `context` output to see why a memory was selected and what source episode/repo produced it.

Use `context_block` from JSON output, or `--format text`, when passing memory into an agent context window. It is bounded by the same context budget and includes workflow status, lineage warnings, evidence annotations, bounded related-memory graph expansion, and follow-up inspection commands.

Use exact inspection commands when the answer depends on a specific memory:

```bash
autopsy item <stable-key>
autopsy timeline <stable-key>
autopsy history <stable-key>
autopsy neighbors --stable-key <stable-key>
autopsy observe --stable-key <stable-key>
```

Use `autopsy history <stable-key>` when the answer depends on how one memory changed, especially after update, expiration, pinning, or delete operations.

Use `autopsy observe --stable-key <stable-key>` to draft an evidence-backed observation from one memory's graph neighborhood. Add `--write` when the derived observation should become reusable context, or `--write-if-stale` when refreshing an existing observation only if its evidence fingerprint has drifted.

Use `autopsy expire <stable-key>` when a memory should leave current reads but remain available for history and `--as-of` reconstruction. Use `autopsy pin <stable-key>` when a memory should appear in `context` packs without depending on task-specific retrieval. Add `--label`, `--description`, `--limit`, `--read-only`, or `--shared` when the pinned memory should behave like an always-visible memory block.

Use `autopsy feedback <stable-key> --rating useful|not-useful|neutral` after important reads. Feedback now informs audit activation and bounded consult ranking, so useful memories are reinforced and repeatedly unhelpful memories drift down without being deleted.

Treat memory as evidence, not absolute truth. Verify drift-prone facts against code, config, git, or external sources.

## Writing Memory

After material work, write durable outcomes:

```bash
autopsy capture-outcome --outcome decision --title "..." --content "..."
autopsy capture-outcome --outcome attempt --title "..." --content "..."
autopsy capture-outcome --outcome observation --title "..." --content "..."
autopsy capture-outcome --outcome procedure --title "..." --content "..."
autopsy capture-outcome --outcome plan --title "..." --content "..."
autopsy capture-outcome --outcome preference --title "..." --content "..."
autopsy capture-outcome --outcome question --title "..." --content "..."
autopsy capture-outcome --outcome resolved-question --title "..." --content "..."
autopsy capture-outcome --outcome reverted-attempt --title "..." --content "..."
```

Multiple writes in one turn are valid when they capture distinct decisions, attempts, observations, procedures, questions, or resolved questions. Avoid duplicate or low-signal writes.

For repo work, attribute writes:

```bash
autopsy capture-outcome --outcome decision --repository-root-path <repo-root> --title "..." --content "..."
```

Use `--tag` on writes when the memory belongs to a durable container such as a release stream, product area, or experiment:

```bash
autopsy capture-outcome --outcome decision --tag release --title "..." --content "..."
```

Use `--namespace` on writes when future reads should target a durable scoped container:

```bash
autopsy capture-outcome --outcome decision --namespace release --title "..." --content "..."
```

Use `--entity-scope TYPE:ID` or `--user-id`, `--agent-id`, `--app-id`, `--run-id`, and `--group-id` on writes when future reads should isolate memory by person, agent persona, app, session, or group:

```bash
autopsy capture-outcome --outcome decision --user-id alice --agent-id planner --title "..." --content "..."
```

Use `--metadata KEY=VALUE` on writes when future reads should filter by structured fields such as product area, source, owner, environment, tier, or score. Use `--metadata` on `consult`, `context`, `recall`, `search`, or `audit` with filters such as `area=memory-layer`, `owner!=archived`, `tier~=prod`, `score>=8`, or `source=*`.

Add at least one explicit semantic relation for durable writes:

```bash
autopsy capture-outcome \
  --outcome decision \
  --title "..." \
  --content "..." \
  --informed-by <stable-key> \
  --supersedes <stable-key> \
  --depends-on <stable-key> \
  --implements <stable-key> \
  --constrains <stable-key> \
  --refines <stable-key>
```

Relation flags are ontology-checked; use them between memory items, and target `--answers` at an open question.

Relation targets can be exact stable keys or unambiguous stable-key wrappers copied from Autopsy JSON, such as `sourceRef=graph-note:...` or `{"item":{"stableKey":"graph-note:..."}}`. Autopsy unwraps one clear key before lookup and fails closed when pasted text contains zero or multiple possible keys.

If a write returns a blocked JSON payload with `reason: "missing_relation_target"`, do not retry with `--no-relations-ok`. Inspect the target with the suggested `item`, `history`, or `search` commands, then write a corrected relation or make an explicitly standalone write only when the memory truly has no semantic relation.

If a stable-key command such as `item`, `timeline`, `neighbors --stable-key`, `snapshot`, `feedback`, `observe`, `consolidate-session`, update, delete, expire, or pin returns a blocked JSON payload with `reason: "missing_memory_item"`, do not recreate the key and do not retry as standalone. Inspect the missing key with the suggested `history` or `search` commands, then choose an existing memory or write a new explicitly related outcome. If a selector command such as `neighbors --entity-id` returns the same reason, resolve a current stable key before retrying.

When a relation is time-bound, add `--relation-valid-at`, `--relation-invalid-at`, or `--relation-expires-at` so current/as-of reads can omit fact edges outside their validity window while timelines preserve the history.

When a relation has known evidence quality, add `--fact-rating 0.0..1.0` on the write so later reads can filter weak relation facts with `--min-fact-rating`.

Supported relation flags:

```text
--informed-by
--answers
--supersedes
--reverts
--depends-on
--implements
--constrains
--refines
```

Use `--no-relations-ok` only when the memory is intentionally standalone and no semantic relation applies.

Inspect `write_quality.warnings` after writes. If a write has `missing_semantic_relation`, is short, low-signal, or possibly duplicate, expand it, update an existing item, or add explicit relations before relying on it as durable memory.

## Backup And Restore

Before large memory-system changes, run:

```bash
autopsy backup
```

Before any restore, validate first:

```bash
autopsy restore <backup.json> --dry-run
```

If that dry run reports `offline_validation: true`, the backup file is valid but
Autopsy could not inspect the target graph. Do not infer existing-key,
new/update, or relation endpoint effects from an offline validation.
Use `autopsy restore <backup.json> --dry-run --offline` when you only need file
validation and should not touch the memory runtime.

Use replace only when intentionally replacing matching restored keys:

```bash
autopsy restore <backup.json> --replace --yes
```

## Memory-System Changes

Run:

```bash
autopsy health
autopsy benchmark --sample-size 5 --include-sync
```

Do not claim memory health unless the benchmark passes or failures are explicitly reported.

Run `autopsy doctor` when Falkor, dependency, or data-path issues are suspected.
