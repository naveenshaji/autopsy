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
- scale readiness
- writes and relations
- Falkor-native sync/graph health

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
4. Measure p50/p95/p99 latency for status, consult, item, timeline, neighbors, writes, and benchmark sync.
5. Publish the harness, seed, hardware profile, and scoring script.

This keeps cost controlled while still testing the behaviors that matter for agent memory.
