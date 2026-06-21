# Architecture

Autopsy Memory is a local-first graph memory runtime.

## Components

- `autopsy_memory.cli`: command-line interface and the core graph operations.
- `autopsy_memory.worker`: local HTTP worker used by UI clients and the MCP bridge.
- `autopsy_memory.mcp_bridge`: stdio MCP server exposing product-level memory tools.
- FalkorDB or FalkorDBLite: authoritative graph backend.
- Optional sentence-transformer models: semantic embeddings and reranking.

Short-lived CLI processes save and detach from embedded FalkorDBLite instead of terminating the Redis process on normal exit. This keeps concurrent local reads from invalidating each other's Unix socket. The resident worker and explicit lifecycle cleanup paths own process reaping.

## Storage Model

Memory is stored as graph nodes and typed relation edges.

Important node categories:

- Semantic items: decisions, attempts, observations, procedures, plans, preferences, questions, summaries, and memory notes.
- Operational nodes: workspaces, repositories, threads, worktrees, and branches.
- Context nodes: adjacent context such as episodes and memory history events.

Semantic items also project into cognitive memory types for retrieval: semantic memory covers decisions, questions, preferences, plans, summaries, and notes; episodic memory covers attempts and imported timelines; procedural memory covers reusable procedures; observation memory covers derived graph observations. Reads can filter these layers with `--memory-type` while still supporting lower-level `--kind`; when both are supplied, the effective candidate set is their intersection.

Semantic items can also carry normalized user-defined `memory_tags`, first-class memory namespaces, first-class entity scopes, and structured `memory_metadata`. Tags are stored on the node, included in search text as both raw tags and `tag:<value>` tokens, preserved through export/restore, and used as deterministic filters alongside repository, memory-type, and kind constraints. Namespaces are persisted redundantly as `namespace:<value>` tags and `metadata.namespaces` so scoped containers can be filtered even when one representation is absent. Entity scopes are persisted redundantly as `metadata.entity_scopes`, mirrored metadata fields such as `user_id`, `agent_id`, `app_id`, `run_id`, and `group_id`, and `namespace:entity/<type>/<id>` tags so user, agent, app, run/session, and group/tenant partitions survive export/restore and can be filtered through CLI, MCP, or worker reads. Metadata is stored as canonical JSON, indexed into search text as `key:value` and `metadata:key=value` tokens, preserved through export/restore, and filterable with exact, negative, substring/list containment, numeric comparison, and existence operators. Advanced `--filter-json` reads add nested boolean `AND`/`OR`/`NOT` expressions over kind, memory type, tags, namespaces, entity scopes, metadata, and item fields such as `created_at` and `updated_at`.

Memory history events are first-class context nodes rather than semantic retrieval items. Create, update, expiration, pinning, unpinning, and deletion paths write old/new snapshots, changed fields, and a target stable key so `history` can inspect how a memory changed without letting revision records pollute ordinary consult/search results.

Observation memories are derived semantic items. `observe --stable-key <memory>` reads one seed memory plus its current fact-rated semantic graph neighborhood, drafts a deterministic `observation:<sha>` record, and stores evidence metadata: policy, seed key, evidence keys, relation list, evidence count, evidence limit, fact-rating threshold, and a material evidence fingerprint. With `--write`, the observation is upserted as `source_kind=derived_observation`, linked to workspace/repo/thread context, and connected back to each evidence memory with `informed_by` fact edges. With `--write-if-stale`, Autopsy compares the stored fingerprint to current graph evidence and refreshes only when missing or stale; refreshes expire obsolete evidence edges so observations follow their supporting graph. `audit` recomputes this fingerprint and flags stale, orphaned, incomplete, or unverifiable observations.

Important relation categories:

- Structural relations: workspace/repo/thread attachment and capture lineage.
- Fact relations: `informed_by`, `answers`, `supersedes`, `reverts`, `depends_on`, `implements`, `constrains`, and `refines`. User-created fact relations are checked against a built-in semantic relation ontology before storage: relation endpoints must be memory items rather than operational nodes, and `answers` targets open questions. Fact edges can carry `valid_at`, `invalid_at`, `expired_at`, and `fact_rating`; relationship retrieval and lineage use time windows for current/as-of reads while timeline/export/restore preserve the underlying history. Fact ratings are normalized to `0.0..1.0`; unrated legacy facts read as neutral `0.5`.

## Retrieval

`consult` is the default agent-facing read path. It combines lexical, exact, graph, semantic vector retrieval, and reranking. Procedure memories are first-class semantic items for reusable instructions, checklists, and operating rules; observation memories are first-class derived context for evidence-backed cross-memory patterns. `status` and `context` surface both separately so agents can find how-to knowledge and graph-derived patterns without mixing them into ordinary decisions or attempts. `context` builds on consult by adding a bounded one-hop semantic graph neighborhood around strong hits, filtered by current/as-of fact-edge validity, optional minimum fact rating, lifecycle expiration, metadata scope, lineage currentness, and the unsafe-memory read guard. This gives agents nearby supporting decisions or attempts without requiring a separate `neighbors` call for every retrieved memory. Consult returns:

- candidate hits
- inspected items
- workflow completeness
- suggested next steps when coverage is weak

Agents should prefer `consult` over raw search because `consult` is designed for evidence-backed work. `consult`, `context`, `recall`, `search`, and `audit` accept memory-type, kind, tag, namespace, and entity-scope filters that require all requested values to be present, plus JSON boolean filters for cases where scoped retrieval needs alternatives, exclusions, or typed comparisons without separate graphs. `consult`, `context`, `search`, and `neighbors` also accept a minimum fact-rating threshold when relation evidence quality matters.

## Governance

`audit` is the governed-memory read path. It inspects recent semantic items for relation coverage, low-signal writes, duplicate title groups, unresolved conflict groups, memory-poisoning risk, sensitive-memory exposure, stale lineage, invalidated fact edges, and activation/retention strength. The write path runs the same unsafe-memory detectors before create/update graph mutation and blocks credential-shaped material plus persistent instruction-override, exfiltration, safety-disable, or tool-hijack directives unless `--allow-unsafe-memory` is explicitly set. The consult/context read path also screens retrieved candidates and quarantines unsafe retained memories before they can appear in hits, inspected items, side-channel candidates, or context-pack text. Temporal reads accept `--as-of` and conservatively exclude memories updated after that timestamp while evaluating lineage only against invalidation edges that already existed. Soft expiration adds lifecycle control: expired semantic memories leave current status/consult/context/search/recall results without being hard-deleted, and earlier `--as-of` reads can still reconstruct them before the expiration boundary. Memory history events are archival lifecycle records rather than current memories, so they remain inspectable through `history` without entering current reads. Pinned core memory adds an always-in-context tier: selected semantic memories appear in context packs ahead of retrieval results, while still passing through the unsafe-memory read guard. Pinned memories can also carry `core_memory_block` metadata with label, description, character limit, read-only, and shared flags; context renders these as bounded memory blocks, and ordinary update writes are rejected while a block is read-only. This complements retrieval by checking whether memory state is current, retainable, and maintainable, not just whether a record can be found.

Consult records access telemetry on returned memories, while `feedback` lets users or agents record explicit `useful`, `not-useful`, or `neutral` outcomes. Retrieval applies those signals as a bounded post-relevance ranking prior: the candidate pool is still selected by lexical, semantic, graph, temporal, lifecycle, and safety gates, then usage and feedback can reorder candidates within a conservative multiplier band without filtering them out. Audit output carries deterministic activation evidence and a repair plan. Activation scores combine currentness, relation coverage, signal density, recency, provenance, duplicate pressure, access frequency, and feedback so weak memories can be enriched, superseded, forgotten, or kept out of default task context. Conflict detection profiles current semantic memories for opposing use/avoid-style directives over the same title subject or entity; it emits repair hints instead of rewriting truth automatically. Memory-poisoning detection scans retained semantic content for persistent instruction override, instruction-hierarchy tampering, exfiltration, safety-disable, and tool-hijack directives. Sensitive-memory detection scans retained semantic content for credential-shaped material and redacts match evidence by type and line number. The repair plan maps issues to state-level operators: `ingestion` for weak writes, `revision` for relation, duplicate, conflict, or stale-lineage fixes, `forgetting` for expired fact paths, poisoning-risk memories, and sensitive memories, and `retrieval` for cases that need inspection before use.

`import-session` is the episodic replay path. It imports agent JSONL transcripts as a stable `timeline` node plus bounded `timeline_event` children linked with `part_of` and `captures`. Stable keys are derived from the transcript SHA1, so replaying the same transcript updates the same graph state. This keeps raw session evidence available for later consolidation without forcing every transcript line into curated semantic memory.

`consolidate-session` is the raw-to-semantic bridge. It reads an imported timeline and emits a deterministic semantic-memory draft from source events. With `--write`, the consolidated memory is linked back to the source timeline and event nodes through `informed_by` fact edges, preserving evidence lineage while making the session useful for normal consult/context retrieval.

## Failure Policy

Falkor is required. Autopsy does not fall back to another local database when Falkor is unavailable. This is intentional because silent backend changes create stale or split-brain memory.

Use `autopsy doctor` for dependency and path checks.

## Compatibility

The standalone CLI supports both:

```bash
autopsy consult --query "..."
autopsy memory consult --query "..."
```

The first form is preferred for the standalone product. The second form exists for existing agents and instructions.
