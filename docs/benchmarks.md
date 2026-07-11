# Internal Benchmark

Autopsy has an internal benchmark gate:

```bash
autopsy benchmark --sample-size 5 --include-sync
```

The gate measures:

- operational health, verified node/relationship full-text indexes, matching
  vector-index profile, and complete current embedding coverage
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

Its recall probes deliberately query sampled item titles, its scale-readiness
probe exercises the lexical fast path, and its negative probes use synthetic
no-hit markers. Those checks are useful for catching broken indexes, routing,
and fail-open behavior, but they are easy smoke tests—not evidence of general
retrieval quality or statistical abstention calibration. Only the external
suite below may support comparative quality claims.

For public-dataset retrieval evaluation, use `autopsy evaluate`. The external
suite uses pinned LoCoMo and LongMemEval-S artifacts, held-out evidence labels,
isolated stores, deterministic selection, raw prediction logs, independent
rescoring, latency percentiles, and explicit vector-coverage qualification.
See [External Evaluation](external-evaluation.md).

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

## Implemented External Suite

The external suite now implements the public corpus, relevance, abstention,
temporal, deterministic-selection, latency, provenance, and scoring portions of
this contract. The controlled coding-memory fixture adds cross-repo isolation,
supersession, reversion, multi-hop, expiration, and poisoning cases.

Scale seeding beyond the public datasets remains separate work. Extraction and
answer generation now have explicit `extracted-retrieval` and `common-answer`
tracks; their metrics and artifacts remain separate and must not be inferred
from a `raw-retrieval` report.
