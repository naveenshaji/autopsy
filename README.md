# Autopsy Memory

Autopsy is a local-first memory layer for coding agents. It provides a Falkor-backed graph, a CLI, an MCP bridge, typed writes, cognitive memory-type filters, first-class entity scopes, relation inspection, derived observations, and a benchmark gate so agents can remember decisions, attempts, procedures, preferences, plans, and unresolved questions across repos.

This repository is the standalone memory product extraction. It intentionally does not contain the legacy macOS Codex client.

## What It Does

- Stores durable memory in a local Falkor graph.
- Builds compact agent context packs through `context`, combining current state, retrieved facts, bounded graph-neighborhood memory, relation hints, deterministic evidence/provenance, lineage/currentness warnings, inspection commands, and a ready-to-insert text context block.
- Retrieves context through `consult`, with workflow completeness metadata.
- Drafts and materializes evidence-backed graph observations with `observe`, linking each observation back to its seed and evidence memories.
- Filters retrieval with deterministic repo, cognitive memory type, kind, entity scope, namespace, metadata, temporal, user-defined tag, relation fact-rating, and JSON boolean constraints.
- Writes typed outcomes with ontology-checked relations such as `refines`, `answers`, `supersedes`, and `depends-on`.
- Inspects exact facts and revisions through `item`, `timeline`, `history`, `neighbors`, and `snapshot`.
- Runs a benchmark gate for recall, abstention, latency, writes, relations, scale readiness, and Falkor health.
- Audits memory governance with relation coverage, duplicate, conflict, poisoning-risk, sensitive-data, low-signal, stale-lineage, and expired-fact checks.
- Reports product health with runtime, graph, index, backup, vector, and init-instruction status.
- Restores exported backups with dry-run validation, safe merge defaults, and explicit replace confirmation.
- Includes a native macOS menu bar utility for quiet memory activity, health, and backup controls.
- Exposes the same semantics through an MCP bridge for coding agents.

## Install

Install from the public repository as a Homebrew tap:

```bash
brew tap naveenshaji/autopsy https://github.com/naveenshaji/autopsy
brew install autopsy-memory
autopsy version --json
autopsy doctor
autopsy install
```

`autopsy install` installs agent instructions and, on macOS, installs a user
LaunchAgent that points at Homebrew's stable `opt/autopsy-memory` path, so the
menu bar app follows package updates.

For local development or machines without Homebrew, install the standalone CLI
into a Homebrew-style prefix:

```bash
cd /path/to/autopsy
./scripts/install-global.sh
autopsy version --json
autopsy doctor
autopsy install
```

By default this uses `/opt/homebrew` when it is writable, otherwise `~/.local`. The layout is:

```text
<prefix>/Cellar/autopsy-memory/<version>/
<prefix>/opt/autopsy-memory -> <prefix>/Cellar/autopsy-memory/<version>
<prefix>/bin/autopsy
```

On macOS, the installer also installs and starts the menu bar LaunchAgent by default so Autopsy is visible when the local install is available. Set `AUTOPSY_INSTALL_MENUBAR_AGENT=0` to skip that behavior.

Homebrew packaging details live in [docs/homebrew.md](docs/homebrew.md). Plain
`brew install autopsy-memory` without a tap requires acceptance into
`homebrew/core`; until then, use the tap command above.

Use a repo-local virtual environment for development:

```bash
cd /path/to/autopsy
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[ml,dev]"
```

If you only need lexical/Falkor operations and want to avoid model downloads:

```bash
python -m pip install -e .
```

## Quickstart

```bash
autopsy version
autopsy doctor
autopsy init --check
autopsy health
autopsy status
autopsy context --query "release decisions for this repo"
autopsy context --format text --query "release decisions for this repo"
autopsy consult --query "release decisions for this repo"
autopsy consult --memory-type procedural --query "release checklist for this repo"
autopsy consult --user-id alice --agent-id planner --query "release decisions for Alice"
autopsy audit --scope repo --repo . --kind decision --tag release
autopsy capture-outcome --outcome decision --tag release --title "Use Falkor only" --content "Falkor is the authoritative memory backend."
autopsy capture-outcome --outcome decision --user-id alice --agent-id planner --title "Alice planner preference" --content "Use scoped entity memory for Alice's planner agent."
autopsy capture-outcome --outcome procedure --tag release --title "Run release checklist" --content "Use the documented release checklist before publishing."
autopsy backup
autopsy restore ~/Library/Application\ Support/Autopsy/Backups/<backup>.json --dry-run
autopsy activity
autopsy menubar
autopsy benchmark --sample-size 5 --include-sync
```

`autopsy consult` uses the resident worker by default for standard Falkor-backed installs, so local embedding and reranker models stay warm across agent turns. Use `autopsy consult --no-worker ...` only when debugging direct-process retrieval.

Compatibility aliases are preserved:

```bash
autopsy memory status
autopsy memory consult --query "prior decisions"
```

## Common Commands

```bash
autopsy status --current-only
autopsy context --current-only --query "<task/context query>"
autopsy context --current-only --format text --query "<task/context query>"
autopsy consult --current-only --query "<task/context query>"
autopsy consult --as-of 2026-05-30T00:00:00Z --query "<past-state query>"
autopsy import-session ~/.claude/projects/<project>/<session>.jsonl --dry-run
autopsy consolidate-session session-import:<sha> --write
autopsy audit --current-only
autopsy audit --format text --min-severity medium
autopsy feedback <stable-key> --rating useful --note "helped with the fix"
autopsy expire <stable-key> --reason "obsolete after release fix"
autopsy pin <stable-key> --label "release" --reason "always include during release work"
autopsy pin <stable-key> --label "policy" --description "Always-visible release policy." --limit 1000 --read-only --shared
autopsy item <stable-key>
autopsy timeline <stable-key>
autopsy history <stable-key>
autopsy neighbors --stable-key <stable-key>
autopsy observe --stable-key <stable-key>
autopsy observe --stable-key <stable-key> --min-fact-rating 0.8 --write
autopsy observe --stable-key <stable-key> --write-if-stale
autopsy snapshot <stable-key>
autopsy capture-outcome --outcome decision --title "..." --content "..."
autopsy capture-outcome --outcome procedure --title "..." --content "..."
autopsy export --output ~/Desktop/autopsy-memory-export.json
autopsy backup
autopsy restore ~/Desktop/autopsy-memory-export.json --dry-run
autopsy init --global --repo . --agent all
autopsy instructions
autopsy health
autopsy activity --limit 10
autopsy menubar --print-path
autopsy benchmark --sample-size 5 --include-sync
```

`autopsy consult` records lightweight access telemetry for returned memories, and `autopsy feedback` records useful/not-useful signals. Consult applies those signals as a bounded search-time ranking prior: recently used or useful memories can move up, stale or negatively rated memories can move down, but candidates are never filtered out by usage alone. `autopsy audit` folds the same signals into activation/retention scoring, flags possible opposing current memories that share a subject, detects likely credential material without echoing the secret value, and flags memory-poisoning payloads that try to override instructions, exfiltrate context, disable safeguards, or hijack tool choice. Stale, weakly related, conflicting, poisoned, sensitive, low-signal, duplicate-prone, or negatively rated memories can be enriched, superseded, forgotten, redacted, or kept out of default task context.

`autopsy import-session` ingests agent JSONL transcripts into episodic timeline memory. Use `--dry-run` first to inspect parsed event counts, parse errors, and deterministic `session-import:<sha>` stable keys before writing timeline and `timeline_event` nodes.

`autopsy consolidate-session` turns an imported session timeline into a traceable semantic memory draft, or writes it with `--write`. Written consolidations link back to the source session and event evidence with `informed_by` relations.

`autopsy observe --stable-key <memory>` builds a deterministic derived observation from one seed memory plus its current fact-rated graph neighborhood. Draft mode returns the proposed `observation:<sha>` stable key, summary, evidence keys, relation list, evidence fingerprint, freshness status, and read-guard status. Add `--write` to upsert the observation as a first-class semantic memory linked back to the seed and evidence items through `informed_by` relations; `--write-if-stale` writes only when the existing observation is missing or its stored evidence fingerprint no longer matches current graph evidence. Refreshes retire obsolete evidence links, and `audit` flags stale, orphaned, or unverifiable observations. `status` and `context` surface fresh observations in an `Observations` section.

Repo-scoped reads and writes:

```bash
autopsy consult --scope repo --repo /path/to/repo --query "release pattern"
autopsy context --scope repo --repo /path/to/repo --format text --query "release pattern"
autopsy consult --kind decision --query "release pattern"
autopsy consult --kind observation --query "release pattern"
autopsy consult --kind procedure --query "release checklist"
autopsy consult --memory-type semantic --query "release pattern"
autopsy consult --memory-type episodic --query "prior failed release attempts"
autopsy consult --memory-type procedural --query "release checklist"
autopsy consult --tag release --tag repo:autopsy --query "release pattern"
autopsy consult --namespace release --namespace repo/autopsy --query "release pattern"
autopsy consult --entity-scope user:alice --agent-id planner --query "release pattern"
autopsy consult --metadata area=memory-layer --metadata 'score>=8' --query "release pattern"
autopsy consult --filter-json '{"AND":[{"OR":[{"namespace":"release"},{"metadata":{"score":{"gte":8}}}]},{"NOT":{"metadata":{"owner":"archived"}}}]}' --query "release pattern"
autopsy consult --min-fact-rating 0.8 --query "release pattern"
autopsy neighbors --stable-key graph-note:abc --min-fact-rating 0.8
autopsy capture-outcome --outcome attempt --repository-root-path /path/to/repo --title "..." --content "..."
autopsy capture-outcome --outcome decision --namespace release --title "..." --content "..."
autopsy capture-outcome --outcome decision --user-id alice --agent-id planner --app-id cli --run-id ticket-42 --title "..." --content "..."
```

Use `--memory-type` on `consult`, `recall`, `search`, `context`, or `audit` when you want a cognitive layer instead of a storage kind. `semantic` covers decisions, questions, preferences, plans, summaries, and notes; `episodic` covers attempts and imported timelines; `procedural` covers reusable procedures; `observation` covers derived graph observations. Combining `--memory-type` with `--kind` intersects both filters.

Use `--tag` to attach user-defined memory tags during `create`, `capture`, `capture-outcome`, shorthand write commands, and `update`. Use `--tag` on `consult`, `recall`, `search`, `context`, or `audit` to require all requested tags; repeat the flag or pass comma-separated values. Tags are normalized to lower-case slug-style values and are included in export/restore.

Use `--namespace` when a memory belongs to a durable scoped container such as a user, agent, repo, release stream, product area, or experiment. Writes store namespace attribution as both `namespace:<value>` tags and `metadata.namespaces`; reads on `consult`, `recall`, `search`, `context`, and `audit` require all requested namespaces and can match either representation.

Use `--entity-scope TYPE:ID` or the convenience flags `--user-id`, `--agent-id`, `--app-id`, `--run-id`, and `--group-id` when memory must be partitioned by person, agent persona, product surface, session, or tenant/group. Writes store normalized scopes in `metadata.entity_scopes`, mirrored fields such as `user_id` and `agent_id`, and `namespace:entity/<type>/<id>` tags. Reads on `consult`, `recall`, `search`, `context`, and `audit` require all requested entity scopes and can match any of those representations.

Use `--metadata KEY=VALUE` on writes to attach structured memory metadata. Use `--metadata` on `consult`, `recall`, `search`, `context`, or `audit` for typed filters: exact (`area=memory-layer`), negative (`owner!=archived`), substring/list containment (`tier~=prod`), numeric comparisons (`score>=8`), and existence (`source=*`). Metadata keys are normalized, indexed into search text, and round-trip through export/restore.

Use `--filter-json` on `consult`, `recall`, `search`, `context`, or `audit` when all-of filters are too restrictive. The JSON expression supports `AND`, `OR`, `NOT`, `kind`, `memory_type`, `tag`, `namespace`, `entity_scope`, metadata fields, item fields such as `created_at` and `updated_at`, and operators such as `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `nin`, `contains`, `icontains`, and `exists`. Symbol aliases such as `>=`, `!=`, and `~=` are accepted for CLI ergonomics.

Use `--min-fact-rating 0.0..1.0` on `consult`, `context`, `search`, or `neighbors` when relationship side-channel evidence should only include relation facts at or above a quality threshold. Unrated legacy facts read as neutral `0.5`.

Durable writes are expected to include at least one semantic relation:

```bash
autopsy capture-outcome --outcome decision --title "..." --content "..." --informed-by graph-note:abc --refines graph-note:def
```

Relation flags are validated as semantic fact edges before storage. The source and target must be memory items, not operational workspace/repository/thread nodes; `--answers` must target an open question.

When a semantic relation is only true during a known window, add fact-edge validity metadata on the write:

```bash
autopsy capture-outcome --outcome decision --title "..." --content "..." --refines graph-note:def --relation-valid-at 2026-05-01T00:00:00Z --relation-invalid-at 2026-06-01T00:00:00Z
```

Relation validity windows are preserved in timeline/export/restore and current/as-of relationship retrieval omits fact edges before `valid_at`, at or after `invalid_at`, or at or after `relation-expires-at`.

Use `--fact-rating 0.0..1.0` on a write with relation flags to attach a quality rating to the newly created semantic fact edges. The rating is shown in `item`, `timeline`, `neighbors`, `snapshot`, export, restore, and relationship side-channel retrieval.

Use `--no-relations-ok` only when the memory is intentionally standalone and no semantic relation applies.

Autopsy also screens create/update writes before graph mutation for credential-shaped material and persistent instruction-override, exfiltration, safety-disable, or tool-hijack directives. Unsafe writes are rejected by default and return `write_quality.unsafe_write_guard.blocked=true`; use `--allow-unsafe-memory` only for deliberate incident evidence after redaction decisions are understood. `consult` and `context` run the same unsafe-memory guard on retrieved candidates and quarantine unsafe retained memories out of agent-facing output with redacted `read_guard` metadata.

Use `--as-of <ISO-8601 timestamp>` on `status`, `consult`, `recall`, `search`, or `context` when reconstructing past memory state. As-of reads conservatively exclude records updated after the requested timestamp and evaluate lineage against invalidations that existed by that time.

Use `autopsy expire <stable-key>` to soft-expire obsolete memories without deleting history. Current reads omit expired memories, while `--as-of` reads before the expiration timestamp can still reconstruct the earlier state. Use `autopsy expire <stable-key> --clear` to restore a memory to current reads.

Use `autopsy pin <stable-key>` for core memory that should enter `context` packs even when the task query would not retrieve it. Pinned memories can act as structured memory blocks with `--label`, `--description`, `--limit`, `--read-only`, and `--shared`; context output renders the label, block purpose, flags, and bounded value. Read-only blocks reject ordinary `update` writes until `autopsy pin <stable-key> --no-read-only` changes the block metadata. Pinned memories are still screened by the unsafe-memory read guard and can be removed from core context with `autopsy pin <stable-key> --clear`.

Use `autopsy history <stable-key>` when you need to inspect how one memory changed over time. Create, update, expiration, pinning, unpinning, and hard delete operations record old/new snapshots with changed fields; history remains queryable by the target stable key even after the target memory is deleted.

## Data Location

By default, Autopsy uses:

```text
~/Library/Application Support/Autopsy/FalkorDB/autopsy-memory.db
~/Library/Application Support/Autopsy/Config/memory-settings.json
~/Library/Application Support/Autopsy/MemoryRoot
```

Override with:

```bash
export AUTOPSY_APP_SUPPORT_DIR="$HOME/Library/Application Support/Autopsy"
export AUTOPSY_FALKORDB_LITE_PATH="$AUTOPSY_APP_SUPPORT_DIR/FalkorDB/autopsy-memory.db"
export AUTOPSY_UNIFIED_MEMORY=1
export AUTOPSY_UNIFIED_MEMORY_ROOT="$AUTOPSY_APP_SUPPORT_DIR/MemoryRoot"
```

Autopsy has no alternate local persistence fallback. If Falkor cannot initialize, commands fail loudly.

## MCP

Run the MCP bridge with:

```bash
autopsy-memory-mcp
```

For Codex-style MCP configuration:

```toml
[mcp_servers.autopsy_falkor_memory]
command = "autopsy-memory-mcp"
env = { AUTOPSY_UNIFIED_MEMORY = "1" }
```

The bridge exposes product-level memory tools such as `autopsy_memory_status`, `autopsy_memory_consult`, `autopsy_memory_item`, `autopsy_memory_timeline`, `autopsy_memory_history`, `autopsy_memory_neighbors`, `autopsy_memory_observe`, `autopsy_memory_search`, and write/update/delete tools.

## Agent Instructions

Copy [docs/agent-instructions.md](docs/agent-instructions.md) into an agent or repo `AGENTS.md`. A ready-to-use example lives at [examples/AGENTS.md](examples/AGENTS.md).

## Benchmark Gate

For memory-system changes:

```bash
autopsy benchmark --sample-size 5 --include-sync
```

Do not claim memory health unless the benchmark passes or failures are explicitly reported.

The current internal benchmark is a product gate, not a public leaderboard. Public-style benchmarking requires seeded corpora, hidden queries, relevance judgments, large-graph latency measurements, and cost reporting. See [docs/benchmarks.md](docs/benchmarks.md).

## Release Checks

Before publishing a release:

```bash
./scripts/release-check.sh
/opt/homebrew/opt/python@3.12/libexec/bin/python scripts/update-homebrew-formula.py --version <version> --python /opt/homebrew/opt/python@3.12/libexec/bin/python
```

The release checklist lives at [docs/release-checklist.md](docs/release-checklist.md).

## Menu Bar App

The native macOS menu bar utility lives in [apps/menubar](apps/menubar). It is intentionally small: tabbed recent memory writes and consult telemetry, global agent instruction status, attention states, manual health, backup, restart, and quit controls. It does not browse the graph or own memory storage; the `autopsy` CLI and Falkor graph remain canonical.

```bash
autopsy menubar
autopsy menubar --install-launch-agent
```

From a checkout, you can also run the app directly:

```bash
./scripts/menubar-check.sh
cd apps/menubar
swift run AutopsyMenuBar
```

The app polls `autopsy activity`, which is the lightweight JSON feed for UI clients. See [docs/menubar.md](docs/menubar.md).
The global installer starts a supervised LaunchAgent by default, and `autopsy menubar --install-launch-agent` can refresh it manually.

## Repository Split

This repo is intended to be published as `naveenshaji/autopsy`.

The previous Swift macOS Codex client should live separately as `autopsy-client-legacy`. The client may integrate with this memory layer through the CLI, worker, or MCP bridge, but it should not own the canonical memory implementation.
