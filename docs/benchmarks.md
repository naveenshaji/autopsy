# Benchmarks

Autopsy has an internal benchmark gate:

```bash
autopsy benchmark --sample-size 5 --include-sync
```

The gate measures:

- operational health
- top-1 recall
- inspection accuracy
- precision and abstention
- performance
- bounded context-pack graph-neighborhood expansion
- scale readiness
- writes and relations
- deterministic metadata filters for repo, cognitive memory type, kind, all-tag matching, first-class namespace matching, first-class entity-scope partitioning, typed user metadata comparisons, and advanced JSON boolean filter expressions
- memory governance audit surface, activation/retention scoring, first-class procedural memory, evidence-preserving derived observations, derived-observation freshness drift detection, access/feedback signals, usage/feedback retrieval decay, conflict detection, memory-poisoning detection, sensitive-memory detection, write-time unsafe-memory blocking, read-time unsafe-memory quarantine, temporal as-of filtering, fact-edge validity windows, relation fact-rating filters, semantic relation ontology validation, old/new memory history events, soft-expiration lifecycle filtering, pinned core-memory context injection, structured memory-block labels/limits/read-only guards, and repair plans
- session JSONL import/replay parsing and consolidation drafts
- Falkor-native sync/graph health and embedded CLI shutdown-detach behavior

This is a product regression gate, not a public leaderboard.

## Public-Style Benchmark Requirements

A credible public benchmark needs:

- fixed public corpus and data-generation recipe
- hidden or held-out query set
- relevance judgments
- stale/superseded/conflicting facts
- no-match queries that must abstain
- relation-heavy questions
- seeded large graph sizes
- latency percentiles, not only averages
- write and update correctness checks
- hardware and cost disclosure

## Practical Plan

Start with a bounded benchmark before attempting a huge public dataset:

1. Build a synthetic corpus of 10k to 100k memories with known labels and relations.
2. Add a smaller real-world corpus from public issue/PR histories.
3. Create held-out queries for recall, abstention, relation traversal, and temporal correctness.
4. Include governed-memory cases for duplicate facts, relationless outcomes, invalid source-predicate-target relation writes, opposing current facts, tag-isolated memory containers, user/agent/app/run/group entity-scope partitions, cognitive memory-type filters for semantic/episodic/procedural/observation layers, memory-poisoning payloads, sensitive-memory exposure, write-time unsafe-memory rejection and bypass behavior, read-time unsafe-memory quarantine, temporal as-of reads, old/new memory history, soft-expired memories, pinned core memories that enter context without retrieval hits, structured memory-block labels/limits/read-only guards, derived observations with explicit evidence keys, stale observation fingerprints, superseded/reverted records, expired fact edges, low-rated relation facts filtered from context, weak activation/retention scores, useful/not-useful feedback, access-frequency reinforcement, bounded usage/feedback ranking decay, session transcript replay, session-to-semantic consolidation, and repair recommendations.
5. Measure p50/p95/p99 latency for status, consult, context, audit, item, timeline, neighbors, writes, and benchmark sync.
6. Publish the harness, seed, hardware profile, and scoring script.

This keeps cost controlled while still testing the behaviors that matter for agent memory.
