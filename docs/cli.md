# CLI

## Install

```bash
brew tap naveenshaji/autopsy
brew install autopsy-memory
autopsy install
autopsy version --json
autopsy doctor
```

Homebrew is the preferred macOS distribution path. It installs the `autopsy`
command, pinned Python runtime dependencies, the native Apple Silicon FalkorDB
module, and the Swift menu bar app source. `autopsy install` then repairs PATH
linkage when possible, writes global agent instructions, starts the menu bar
LaunchAgent in a normal macOS GUI session, runs `doctor`, and starts background
model warmup. The Homebrew formula requires macOS 14 Sonoma or newer on Apple
Silicon.

Use `autopsy` for real memory. Use `autopsy-dev` for source-tree development and
local experiments. `autopsy-dev` runs the same CLI code but defaults
`AUTOPSY_APP_SUPPORT_DIR`, `AUTOPSY_UNIFIED_MEMORY_ROOT`, and
`AUTOPSY_FALKORDB_LITE_PATH` to
`~/Library/Application Support/AutopsyDev`, so development writes, embedded
FalkorDB snapshots, and worker settings cannot collide with the Homebrew-managed
production memory store. If you intentionally need to point `autopsy-dev` at the
production store, set `AUTOPSY_DEV_ALLOW_PRODUCTION_MEMORY=1`; otherwise it
refuses production paths.

## First-Run Setup

```bash
autopsy install
autopsy install --dry-run
autopsy install --repo
autopsy install --skip-menubar
autopsy install --smoke-test
```

`install` is the normal first-run command. It installs managed global instruction blocks for supported agents and, on macOS, stages the menu bar app and installs the LaunchAgent that keeps it visible. The running menu bar app also keeps the resident Autopsy worker warm for local memory operations. Repo-local instructions are opt-in with `--repo`.

Use `autopsy install --smoke-test` on a new machine or after a repair. It runs
doctor, a current-state read, an abstention consult, and a temporary
write/delete check, then exits nonzero if any requested smoke check fails.

## Agent Instructions

```bash
autopsy init
autopsy init --check
autopsy init --dry-run --global --repo . --agent all
autopsy init --print
autopsy init --mcp
autopsy init --smoke-test
```

`init` is the lower-level instruction installer. It installs managed instruction blocks for global Codex, Claude Code, Gemini CLI, and OpenCode instruction files, plus repo-scoped files for Codex/AGENTS.md-aware tools, Claude Code, Gemini CLI, GitHub Copilot, and Windsurf. MCP configuration is optional and only printed when `--mcp` is passed.

## Health

```bash
autopsy version
autopsy doctor
autopsy health
autopsy diagnostics --limit 10
autopsy repair-embedded-snapshot --dry-run
autopsy status --current-only
autopsy context --current-only --query "current task"
autopsy context --current-only --format text --query "current task"
autopsy context --current-only --include-shared --shared-repo-scope /path/to/repo --format text --query "current task"
autopsy context --current-only --include-linked-shared --linked-shared-repo-scope /path/to/repo --format text --query "current task"
autopsy audit --current-only
autopsy activity
autopsy shared-server health
autopsy shared-server team-status
autopsy shared-server users
autopsy shared-server grants --repo-scope /path/to/repo
autopsy shared-server audit --repo-scope /path/to/repo
autopsy shared-server invite --email dev@example.com --role writer --repo-scope /path/to/repo
autopsy shared-server revoke-token tok_123 --repo-scope /path/to/repo
autopsy shared-server archive shared:key --repo-scope /path/to/repo --reason duplicate
autopsy shared-server list --repo-scope /path/to/repo --include-archived
autopsy shared-server context --repo-scope /path/to/repo --query "current task"
autopsy shared-server restore shared:key --repo-scope /path/to/repo --reason needed
autopsy shared-server relate shared:source shared:target --repo-scope /path/to/repo --relation depends_on
autopsy shared-server shared-relations --repo-scope /path/to/repo --source-key shared:source
autopsy shared-server unrelate rel_123 --repo-scope /path/to/repo
autopsy shared-server personal-links --repo-scope /path/to/repo --personal-key graph-note:local
autopsy shared-server personal-context --repo-scope /path/to/repo --personal-key graph-note:local
autopsy shared-server unlink plink_123 --repo-scope /path/to/repo
autopsy benchmark --sample-size 5 --include-sync
autopsy menubar
```

`health` is a lightweight product summary. It checks Falkor reachability, runtime dependencies, graph/index readiness, vector counts, backup freshness, installed instruction state, and local diagnostic log summaries. For non-empty memory graphs, the newest default backup must be valid and within the 24-hour freshness window; backups older than 7 days are reported as critical stale recovery risk. It does not replace the benchmark gate.

`diagnostics` tails sanitized local JSONL diagnostic logs. Use `--log memory-guard` or `--log memory-relations` to inspect one log. Relation diagnostics include missing relation targets and missing memory item events; summarized event payloads are whitelisted so failed memory content, raw stable keys, relation request arrays, and candidate arrays are not printed.

`repair-embedded-snapshot` is for embedded FalkorDBLite rollback events reported by `health`, `status`, or `diagnostics --log memory-guard`. The default is a dry run that plans which stale database, settings, and guard files would be quarantined and lists recent validated default backup candidates with staleness risk relative to the guard timestamp or guard generation. Its `backup_candidates.recovery_summary.best_candidate` ranks valid backups by recovery evidence, so a guard-covered backup can outrank a newer timestamp-only backup. Use `--salvage-output <path>` to write a read-only JSON export from the stale embedded snapshot before any quarantine; Autopsy closes that loaded snapshot with NOSAVE and marks the export as stale-snapshot salvage metadata. Actual repair requires both `--yes` and `--accept-data-loss`; it first writes an automatic salvage export unless `--skip-salvage` is supplied, then moves the stale snapshot into an application-support backup bundle instead of lowering the guard in place. Add `--restore-backup <backup.json>` or `--restore-latest-backup` to import a validated semantic backup into the fresh embedded store after quarantine.

`activity` is the lightweight JSON feed for UI clients. It returns recent memory writes, recent consult telemetry, attention items, and current status.

`context --include-shared` keeps local and shared provenance separate while
building one agent-ready context pack. The shared block is opt-in, source
attributed as `shared_server`, and non-fatal: if the shared server is missing or
denies access, local context still renders with a shared-context error entry.
Use `--shared-repo-scope`, `--shared-query`, `--shared-limit`,
`--shared-include-archived`, and `--shared-no-relations` to control the shared
side of the retrieval.

`context --include-linked-shared` follows the caller's private
personal-to-shared links from local context stable keys to shared memories and
renders those results in a separate source-attributed block. It does not upload
local memory content; the server receives only selected personal stable keys and
returns shared memories that are both repo-readable and linked by the caller's
own private relation records. Use `--linked-shared-personal-key` to provide
explicit keys, `--linked-shared-repo-scope` to target a repo scope, and
`--linked-shared-limit`, `--linked-shared-include-archived`, and
`--linked-shared-no-relations` to control the linked shared lookup.

`shared-server` configures and inspects the Autopsy shared memory server used for
team graphs. `shared-server configure --from-owner-config` imports the private
owner token file created by `autopsy-server` bootstrap into
`~/Library/Application Support/Autopsy/SharedServer/config.json` with `0600`
permissions. `shared-server health` checks the remote `/health` and `/v1/me`
endpoints and always redacts the bearer token from output. The `activity` feed
includes redacted `shared_server` state so the macOS menu bar can show and check
shared-memory connectivity. `shared-server team-status` summarizes users and
repo grants for menu bar clients without echoing token material. Graph owners
can use `shared-server invite --email <email> --role reader|writer|owner
--repo-scope <repo>` to create or reuse a user, grant repo access, and issue a
one-time token in one audited operation. Global admins can also use
`shared-server users`, `create-user --email <email>`, `tokens --user-id <id>`,
`create-token --user-id <id> --label <label>`, `grants --repo-scope <repo>`,
`grant --user-id <id> --role reader|writer|owner --repo-scope <repo>`,
`revoke-token <token-id>`, and `revoke-grant --user-id <id> --repo-scope <repo>`
to manage shared access. `revoke-token` first uses the global-admin endpoint and
falls back to graph-scoped revocation, so graph owners can clean up invite-issued
tokens for repos they own without global token access. `shared-server audit
--repo-scope <repo>` lists scoped server audit events for graph owners or admins.
`--repo` resolves a local repo path; `--repo-scope` passes an exact shared-server
scope such as a repo URL, stable repo id, or `*`. `shared-server publish
<stable-key> --repo <repo>` copies a local memory item into the configured shared
graph, `shared-server list --repo <repo>` lists repo-scoped shared memories, and
`shared-server context --repo-scope <repo> --query <text>` fetches
source-attributed shared memories plus adjacent shared graph relations as a
ready-to-insert context block without importing them into the personal graph.
`shared-server link <personal-key> <shared-key> --repo <repo> --relation <name>`
creates a private personal-to-shared relation without uploading the personal
graph. `shared-server personal-links --repo-scope <repo>` lists only your own
private personal-to-shared relation records; add `--personal-key` or
`--shared-key` to filter. `shared-server personal-context --repo-scope <repo>
--personal-key <stable-key>` fetches the shared memories currently reachable
through your private personal links, plus adjacent shared graph relations unless
`--no-relations` is supplied. `shared-server unlink <relation-id> --repo-scope
<repo>` revokes one of your private relation records. `shared-server relate
<source-shared-key> <target-shared-key> --repo-scope <repo> --relation <name>`
creates a team-visible relation between two active shared memories, while
`shared-server shared-relations --repo-scope <repo>` lists shared graph edges
with optional `--source-key` and `--target-shared-key` filters. `shared-server
unrelate <relation-id> --repo-scope <repo>` revokes one shared graph edge and
requires graph-owner or admin access. `shared-server archive <shared-key>
--repo-scope <repo> --reason <text>` soft-archives a shared memory for repo
owners, and `shared-server restore <shared-key> --repo-scope <repo> --reason
<text>` restores it. Normal list reads omit archived memories; use
`--include-archived` for review or recovery.

`menubar` stages the native macOS menu bar app as a small `.app` bundle and, in a normal GUI session, installs and kickstarts the supervised LaunchAgent. Current bundles launch without rebuilding; use `autopsy menubar --build` to build and stage without launching, `autopsy menubar --rebuild` to force a rebuild before launch, `autopsy menubar --install-launch-agent` to explicitly install the supervised login item, and `autopsy menubar --print-path` to inspect resolved app paths. Installed LaunchAgents run the app executable directly with `KeepAlive`, and the app silently checks the resident worker so local memory routes stay warm.

## Retrieval

```bash
autopsy context --query "architecture decisions"
autopsy context --format text --query "architecture decisions"
autopsy consult --query "architecture decisions"
autopsy consult --scope repo --repo /path/to/repo --kind decision --query "architecture decisions"
autopsy consult --kind observation --query "architecture decisions"
autopsy consult --memory-type procedural --query "release checklist"
autopsy consult --tag release --tag repo:autopsy --query "architecture decisions"
autopsy consult --namespace release --namespace repo/autopsy --query "architecture decisions"
autopsy consult --user-id alice --agent-id planner --query "architecture decisions"
autopsy consult --metadata area=memory-layer --metadata 'score>=8' --query "architecture decisions"
autopsy consult --filter-json '{"AND":[{"OR":[{"namespace":"release"},{"metadata":{"score":{"gte":8}}}]},{"NOT":{"metadata":{"owner":"archived"}}}]}' --query "architecture decisions"
autopsy consult --min-fact-rating 0.8 --query "architecture decisions"
autopsy consult --as-of 2026-05-30T00:00:00Z --query "architecture decisions at release time"
autopsy recall --query "release process"
autopsy search --memory-type semantic --min-fact-rating 0.8 --query "Falkor"
```

Prefer `consult` when the answer will rely on memory.

Use `context` when an agent needs a bounded context pack before work. It combines current operational state, task-specific consult hits, compact memory text, a small one-hop graph neighborhood around strong hits, relation snippets, deterministic evidence/provenance, lineage/currentness warnings, follow-up `item`/`timeline`/`neighbors` commands, and a `context_block` string. Tune the pack with `--max-chars`, `--status-limit`, `--section-limit`, `--limit`, and `--inspect-limit`.

Use `--format text` when you want only the deterministic context block for direct insertion into an agent prompt or tool-context message. The default JSON output still includes the same string in `context_block`.

If all retrieved memories are explicitly superseded, reverted, or answered by graph relations, `context` returns `workflow.status: needs_lineage_review` instead of treating stale recall as complete.

`retrieval.items[].evidence` shows why each memory was included and where it came from: retrieval reasons and scores, source kind, timestamps, source episodes, repo/workspace links, and relation counts when available.

Use deterministic filters when semantic similarity alone is too broad. `--scope repo --repo /path/to/repo` restricts consult/context retrieval to memories linked to that repository. `--kind` restricts retrieval to memory kinds such as `decision`, `attempt`, `observation`, `procedure`, `preference`, `plan`, or `question`; repeat the flag or pass comma-separated values. `--memory-type` restricts reads by cognitive layer: `semantic` maps to decisions, questions, preferences, plans, summaries, and notes; `episodic` maps to attempts and imported timelines; `procedural` maps to procedures; `observation` maps to derived observations. If `--kind` and `--memory-type` are both present, Autopsy intersects them. `--tag` restricts `consult`, `context`, `recall`, `search`, and `audit` to memories containing all requested tags; repeat the flag or pass comma-separated values. `--namespace` restricts those reads to memories in all requested scoped containers and matches either `namespace:<value>` tags or `metadata.namespaces`. `--entity-scope TYPE:ID` and convenience flags such as `--user-id`, `--agent-id`, `--app-id`, `--run-id`, and `--group-id` restrict reads to memories in all requested entity partitions and match `metadata.entity_scopes`, mirrored metadata fields, or `namespace:entity/<type>/<id>` tags. `--metadata` restricts those reads with typed metadata filters such as `area=memory-layer`, `owner!=archived`, `tier~=prod`, `score>=8`, or `source=*`. `--filter-json` adds nested boolean filters for `AND`, `OR`, `NOT`, `kind`, `memory_type`, `tag`, `namespace`, `entity_scope`, metadata fields, item fields such as `created_at` and `updated_at`, and operators such as `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `nin`, `contains`, `icontains`, and `exists`; symbol aliases such as `>=`, `!=`, and `~=` are accepted. `--min-fact-rating 0.0..1.0` filters relationship side-channel evidence for `consult`, `context`, `search`, and `neighbors`; unrated legacy facts read as neutral `0.5`.

`consult` uses the resident Autopsy worker by default when the standard Falkor configuration is in use. This keeps local embedding and reranker models warm across CLI calls. Use `--no-worker` only when debugging direct-process retrieval behavior. Set `AUTOPSY_CLI_CONSULT_WORKER=required` to fail instead of falling back to direct retrieval if the worker cannot start.

Use `--as-of <ISO-8601 timestamp>` with `status`, `consult`, `recall`, `search`, or `context` for temporal reconstruction. The read excludes records whose stored content was updated after the requested timestamp and reports temporal filter metadata under `routing.temporal` or top-level `temporal`. Context lineage is also evaluated as of that timestamp, so later superseding/answering/reverting edges do not make an earlier memory stale before the edge existed.

## Governance Audit

```bash
autopsy audit
autopsy audit --scope repo --repo /path/to/repo --kind decision --limit 50
autopsy audit --memory-type procedural --limit 50
autopsy audit --format text --min-severity medium
autopsy feedback <stable-key> --rating useful --note "used successfully in this task"
autopsy expire <stable-key> --reason "obsolete after replacement decision"
autopsy pin <stable-key> --label "release" --reason "core release workflow memory"
autopsy pin <stable-key> --label "policy" --description "Always-visible release policy." --limit 1000 --read-only --shared
autopsy import-session ~/.claude/projects/<project>/<session>.jsonl --source claude-jsonl --dry-run
autopsy consolidate-session session-import:<sha> --kind memory_note --write
autopsy observe --stable-key graph-note:<seed>
autopsy observe --stable-key graph-note:<seed> --min-fact-rating 0.8 --write
autopsy observe --stable-key graph-note:<seed> --write-if-stale
```

`audit` reviews recent semantic memories for governed-memory issues: missing semantic relations, short or low-signal content, duplicate title groups, possible conflict groups, likely memory-poisoning risk, likely sensitive-memory exposure, stale lineage from `supersedes`/`reverts`/`answers`, stale or orphaned derived observations, invalidated or expired fact edges, and weak activation/retention signals. Conflict groups are deterministic hints where two current memories share a subject but carry opposing use/avoid-style guidance; resolve them with explicit `supersedes`, `reverts`, `answers`, or scoped replacement memories. Memory-poisoning findings detect persistent instruction override, instruction-hierarchy tampering, data exfiltration, safety-disable, and tool-hijack directives; evidence reports only redacted types and line numbers. Sensitive-memory findings detect credential-shaped material such as private key headers, service tokens, bearer tokens, or credential assignments; evidence reports only redacted types and line numbers, not the matched value. The output includes issue severity, evidence, and `item`/`timeline`/`neighbors` follow-up commands so agents can repair memory state instead of blindly retrieving stale records.

The JSON output includes deterministic `activation` scores and a `repair_plan` grouped by memory. Activation is query-independent retention evidence: currentness, relation coverage, signal density, recency, provenance, duplicate pressure, access frequency, and feedback. Each repair plan item maps issues to governed-memory operators (`ingestion`, `revision`, `forgetting`, or `retrieval`) and includes command hints. Use `--format text` for an agent-readable repair checklist and `--min-severity` to focus on medium or high severity issues.

`consult` records lightweight access telemetry for returned memories: `access_count`, `last_accessed_at`, `last_access_source`, and the last query snippet. Use `feedback` to add explicit `useful`, `not-useful`, or `neutral` ratings. Consult uses access and feedback as a bounded search-time ranking prior after normal relevance gates: reinforced or useful memories can move up, stale or negatively rated memories can move down, and the multiplier stays in a conservative 0.3x to 1.5x band so usage never becomes a hard filter. Audit uses the same signals as activation and retention evidence.

Use `expire` for lifecycle management when a memory should leave current reads but remain available for history, audit, export, and point-in-time reconstruction. `autopsy expire <stable-key>` defaults to expiring now, `--expires-at <ISO-8601>` schedules or backdates the lifecycle boundary, `--reason` stores a short explanation, and `--clear` removes the expiration. `consult`, `context`, `search`, `recall`, and `status` omit expired memories from current reads, but `--as-of` before the expiration timestamp still includes them. Memory history events are archival by default: `history` can still inspect them, but they are lifecycle-marked so old snapshots do not become current memory.

Use `pin` when a memory should behave like core memory rather than ordinary retrieval memory. `autopsy pin <stable-key>` stores pin metadata on the memory, and `context` includes pinned memories in a `Pinned Memory` section even when consult has no hits for the task query. `--label`, `--description`, and `--limit` turn the pin into a structured memory block: the context pack shows the block label, purpose, bounded value, and flags. `--read-only` blocks ordinary `update` writes until `autopsy pin <stable-key> --no-read-only` changes the block metadata; `--shared` marks blocks intended for shared agent or entity-scope use. `--clear` removes it from core context. Pinned memories still pass through the unsafe-memory read guard before agent-facing context is built.

`import-session` parses agent JSONL transcripts into an episodic timeline. Dry runs report the deterministic `session-import:<sha>` key, parsed event count, parse errors, and event previews. Non-dry runs upsert one `timeline` node plus bounded `timeline_event` nodes linked with `part_of` and `captures`; repeat imports update the same stable keys instead of duplicating sessions.

`consolidate-session` builds a deterministic semantic-memory draft from an imported session's event evidence. Without `--write`, it returns the proposed stable key, title, content, source session, and source event keys. With `--write`, it upserts the semantic memory and links it back to the session and event nodes with `informed_by` relations.

`observe` builds a deterministic derived observation from one seed memory and its current semantic graph neighborhood. Draft mode returns the proposed observation stable key, evidence keys, relation list, evidence fingerprint, freshness status, read-guard result, and content. With `--write`, Autopsy upserts the observation as a first-class semantic memory and links it back to the seed and evidence memories with `informed_by` fact edges. With `--write-if-stale`, Autopsy writes only when the observation is missing or its stored evidence fingerprint differs from the current graph; refreshes retire obsolete `informed_by` evidence links. Use `--min-fact-rating` when only high-quality relation evidence should count.

The benchmark gate includes a `memory_governance` attribute that verifies the audit surface, relation coverage reporting, issue taxonomy, activation/retention scoring, access/feedback components, usage/feedback retrieval decay, conflict-detection surface, memory-poisoning detection, sensitive-memory detection, write-time unsafe-memory blocking, read-time unsafe-memory quarantine, temporal as-of filtering, fact-rating relation filters, evidence-preserving derived observations, derived-observation freshness drift detection, structured core memory blocks, first-class old/new memory history events, follow-ups, repair plans, and workflow status. It also includes a `session_import` attribute that validates JSONL replay parsing, deterministic stable-key generation, and consolidation draft generation.

## Inspection

```bash
autopsy item <stable-key>
autopsy timeline <stable-key>
autopsy history <stable-key>
autopsy neighbors --stable-key <stable-key>
autopsy neighbors --stable-key <stable-key> --min-fact-rating 0.8
autopsy snapshot <stable-key>
```

Use `timeline` before relying on memories that may have been superseded, reverted, or invalidated.

Use `history` when you need the mutation trail for one memory. It returns recorded create, update, expiration, pin, unpin, and delete events with old/new memory text, structured snapshots, and changed fields. Because history is stored as separate context nodes, `autopsy history <stable-key>` can still retrieve the delete event after the target memory has been hard-deleted.

## Writes

```bash
autopsy capture-outcome --outcome decision --title "..." --content "..."
autopsy capture-outcome --outcome attempt --tag release --title "..." --content "..."
autopsy capture-outcome --outcome observation --title "..." --content "..."
autopsy capture-outcome --outcome procedure --tag release --title "..." --content "..."
autopsy capture-outcome --outcome plan --title "..." --content "..."
autopsy decision --title "..." --content "..."
autopsy attempt --title "..." --content "..."
autopsy observation --title "..." --content "..."
autopsy procedure --title "..." --content "..."
```

## Portability

```bash
autopsy export --output ~/Desktop/autopsy-memory-export.json
autopsy export --include-operational --limit 100
autopsy backup
autopsy restore ~/Desktop/autopsy-memory-export.json --dry-run
autopsy restore ~/Desktop/autopsy-memory-export.json --dry-run --offline
autopsy restore ~/Desktop/autopsy-memory-export.json --merge
autopsy restore ~/Desktop/autopsy-memory-export.json --replace --yes
autopsy compare-backups ~/Desktop/autopsy-memory-export.json ~/Desktop/autopsy-stale-snapshot.json
autopsy repair-embedded-snapshot --dry-run
autopsy repair-embedded-snapshot --salvage-output ~/Desktop/autopsy-stale-snapshot.json
autopsy repair-embedded-snapshot --yes --accept-data-loss
autopsy repair-embedded-snapshot --yes --accept-data-loss --skip-salvage
autopsy repair-embedded-snapshot --yes --accept-data-loss --restore-backup ~/Desktop/autopsy-memory-export.json
autopsy repair-embedded-snapshot --yes --accept-data-loss --restore-latest-backup
```

`export` writes semantic memory and in-graph relations as JSON. `backup` writes the same export shape to a timestamped file under the Autopsy application-support backups directory unless `--output` is provided. Successful semantic write commands and non-dry-run restores opportunistically create a default backup when the newest default backup is missing, invalid, or older than the freshness window; set `AUTOPSY_AUTO_BACKUP_AFTER_WRITE=0` to disable that automatic backup step.

`restore` validates schema version 1 exports, defaults to safe merge mode, skips operational nodes unless `--include-operational` is set, and refuses replace mode unless `--yes` is provided. Replace mode deletes only matching keys present in the restore file before importing them; unrelated graph data is not wiped.

Use `restore --dry-run --offline` when you only want file validation and do not want to open Falkor at all. When `restore --dry-run` cannot open the memory runtime, for example during an embedded rollback guard failure, it falls back to the same offline validation and returns `offline_validation: true`. In that mode graph-dependent counts such as existing items, new/update items, and relation endpoint effects are reported as unavailable; restore runtime health or use `repair-embedded-snapshot --restore-backup` before relying on those effects.

`compare-backups` compares two schema version 1 backup/export/salvage files without opening FalkorDB. Use it during rollback recovery to compare a stale-snapshot salvage export against the newest valid backup; it reports stable keys only in each input, changed shared keys, relation differences, salvage guard metadata, and recovery guidance. `compare-exports` is an alias.

`repair-embedded-snapshot` is not a restore replacement. Use it only when the embedded database guard reports `workflow.status: rollback_detected`; it quarantines stale local database files so a new embedded snapshot can start cleanly, then optionally merges a backup file. Its dry-run output includes `backup_candidates`; use `--backup-limit` to control how many default backups are validated and shown. Each valid candidate includes `recovery_risk`, and `recovery_summary.best_candidate` ranks candidates by guard-generation coverage before timestamp-only freshness. Inspect stale backup windows and compare salvage before accepting data loss. Confirmed repair writes a stale-snapshot salvage export automatically before quarantine; use `--salvage-output` when you want to choose the path during dry-run, or `--skip-salvage` only when you intentionally do not want that extra importable recovery point.

## Agent Setup

```bash
autopsy init
autopsy instructions
```

`init` patches persistent agent instruction files. `instructions` only prints the unmanaged instruction text.

Write with repo attribution:

```bash
autopsy capture-outcome \
  --outcome decision \
  --repository-root-path /path/to/repo \
  --title "..." \
  --content "..."
```

Write with relations:

```bash
autopsy capture-outcome \
  --outcome decision \
  --title "..." \
  --content "..." \
  --informed-by graph-note:abc \
  --refines graph-note:def
```

Durable writes are expected to include at least one semantic relation. Use `--no-relations-ok` only when a memory is intentionally standalone and no semantic relation applies; otherwise `write_quality.complete` is `false` with a `missing_semantic_relation` warning.

Relation flags are ontology-checked before storage. The source and target must be memory items rather than operational workspace/repository/thread nodes, and `--answers` must point at an open question. Invalid source-predicate-target combinations fail before create/update mutation when Autopsy can preflight them.

Relation targets may be pasted as an exact stable key or as an unambiguous wrapper copied from Autopsy JSON, such as `"graph-note:..."`, `` `graph-note:...` ``, `sourceRef=graph-note:...`, `{"sourceRef":"graph-note:..."}`, or `{"item":{"stableKey":"graph-note:..."}}`. Autopsy unwraps these before lookup. If pasted text contains zero or multiple possible stable keys, the target is left unchanged and the write fails with missing-target diagnostics instead of guessing.

When a requested relation target does not exist, `capture-outcome` and `update` fail before mutating memory and emit a structured blocked JSON payload with `reason: "missing_relation_target"`, `retry_policy.retry_with_no_relations_ok: false`, relation diagnostics, and follow-up commands. Treat that as a lineage repair task, not a prompt to retry the same memory as standalone.

When a stable-key command such as `item`, `timeline`, `neighbors --stable-key`, `snapshot`, `feedback`, `observe`, `consolidate-session`, update, delete, expire, or pin targets a missing item, the command fails with `reason: "missing_memory_item"` and `retry_policy.retry_as_create: false`; write and derived-write commands fail before mutation. Treat that as a stale-key or lineage problem: inspect the suggested `history` or `search` commands and select an existing memory or write a new explicitly related outcome. Selector misses, such as `neighbors --entity-id`, use the same reason with a `selector` object and should be retried only after resolving a current stable key.

Use `--tag` on write commands to attach normalized memory tags, and on `update` to replace a memory's tags. Tags are lower-case slug-style values, are included in search text as `tag:<value>`, and round-trip through export/restore.

Use `--namespace` on write commands to attach scoped memory containers. Namespaces are normalized like tags, persisted as `namespace:<value>` tags plus `metadata.namespaces`, indexed for search, and round-trip through export/restore.

Use `--entity-scope TYPE:ID` or `--user-id`, `--agent-id`, `--app-id`, `--run-id`, and `--group-id` on write commands to attach first-class entity partitions. Autopsy persists each scope as `metadata.entity_scopes`, mirrored metadata fields such as `user_id`, and `namespace:entity/<type>/<id>` tags, so later reads can isolate user, agent, app, session, or group memory without hand-authored metadata filters.

Use `--metadata KEY=VALUE` on write commands to attach structured metadata such as `area`, `source`, `owner`, `score`, `tier`, or `environment`. Metadata values parse booleans, nulls, numbers, strings, and JSON arrays/objects; metadata is included in search text and export/restore.

Use `--relation-valid-at`, `--relation-invalid-at`, and `--relation-expires-at` on write commands when newly created semantic relations have a known temporal validity window. Autopsy stores those timestamps on the fact edge, shows them in timelines and exports, and filters relationship retrieval for current/as-of reads so stale or not-yet-valid facts do not enter context.

Use `--fact-rating 0.0..1.0` on a write with relation flags to attach a quality rating to newly created semantic fact edges. The rating is shown by `item`, `timeline`, `neighbors`, `snapshot`, export/restore, and relationship side-channel retrieval; use `--min-fact-rating` on reads when low-quality relations should not enter context.

Create/update writes are also guarded before storage. Credential-shaped material and persistent instruction-override, exfiltration, safety-disable, or tool-hijack directives set `write_quality.unsafe_write_guard.blocked=true` and reject the write before graph mutation. Use `--allow-unsafe-memory` only for deliberate incident evidence; the unsafe warnings remain redacted in `write_quality`.

`consult` and `context` also run the unsafe-memory guard on retrieved candidates. Unsafe retained memories are withheld from `hits`, inspected `items`, side-channel candidates, and context text by default; the response keeps redacted `read_guard` metadata with blocked stable keys, finding types, and severity so the memory can be audited, deleted, superseded, or kept quarantined without injecting its content into agent context.

## Compatibility Prefix

Both forms are valid:

```bash
autopsy consult --query "..."
autopsy memory consult --query "..."
```

Standalone docs use the shorter top-level form.
