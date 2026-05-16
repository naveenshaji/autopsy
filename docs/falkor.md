# FalkorDB Memory Backend

## Goal
Autopsy memory is a Falkor-backed local graph runtime. Falkor is the authoritative graph backend for memory reads, writes, relations, and benchmark health.

The runtime is intentionally graph-native:
- typed node labels for semantic, operational, and timeline data
- typed structural edges for stable product relationships
- `FACT_EDGE` for semantic predicate relationships
- Falkor range indexes for exact identifiers
- Falkor full-text indexes for lexical retrieval
- Falkor vector indexes for semantic retrieval where embeddings are available

## Production Direction
The steady-state contract is:
1. Falkor is required for memory operations.
2. Memory commands fail loudly when Falkor cannot be reached or initialized.
3. The long-lived worker and CLI share the same Falkor semantics.
4. Agents should use `consult` for evidence-backed retrieval and `item`, `timeline`, and `neighbors` for inspection.
5. The benchmark gate measures the live Falkor graph directly.

## Graph Model
Every node carries `:MemoryNode` plus one or more specific labels.

Semantic labels include:
- `:SemanticItem`
- `:Decision`
- `:Attempt`
- `:Plan`
- `:Question`
- `:Preference`
- `:Summary`
- `:MemoryNote`

Operational labels include:
- `:Workspace`
- `:Repository`
- `:Thread`
- `:Worktree`
- `:Branch`

Timeline/context labels include:
- `:Episode`
- `:ContextNode`

Stable structural edges include:
- `BELONGS_TO`
- `ABOUT`
- `ATTACHED_TO`
- `CAPTURED_IN`
- `CAPTURES`
- `UPDATES`
- `FORKED_FROM`
- `PART_OF`

Semantic predicate edges use `FACT_EDGE` with `relation`, `predicate`, `fact_text`, temporal metadata, and source/target identifiers.

## Retrieval Model
Autopsy does not force every query through one universal route.

Status-like queries use an operational/status path:
- active work
- recent changes
- current workspace state

Exact lexical and architecture queries use Falkor full-text retrieval:
- identifiers
- feature names
- decisions
- implementation nouns

Implementation and semantic questions use selective hybrid retrieval:
- lexical candidate generation first
- vector search only when useful
- reranking only when the candidate shape benefits from it

Low-confidence or no-match queries should abstain rather than returning broad unrelated memory.

## Benchmark Gate
Run:

```sh
autopsy benchmark --sample-size 5 --include-sync
```

The benchmark reports:
- `operational_health`
- `recall_top1`
- `inspection_accuracy`
- `precision_abstention`
- `performance`
- `scale_readiness`
- `writes_and_relations`
- `falkor_native`

Do not claim memory health unless the benchmark passes or failures are explicitly reported.

## Guardrails
- Do not expose raw Cypher as the default agent interface.
- Do not collapse stable structural relations into one generic edge type.
- Do not treat broad operational questions as semantic search.
- Do not add alternate local persistence backends behind Falkor failures.
- Keep benchmark probes temporary and self-cleaning.
