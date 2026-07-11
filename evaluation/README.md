# Evaluation Artifacts

This directory contains Autopsy-authored schemas and controlled fixtures only.
Public benchmark data is downloaded on demand and must not be committed here.

- `src/autopsy_memory/evaluation/fixtures/coding-memory-v1.jsonl` is the
  transparent development challenge set bundled with the package. It is
  synthetic and not a leaderboard corpus. Copy it with `autopsy evaluate
  fixture --output ./coding-memory-v1.jsonl`.
- `src/autopsy_memory/evaluation/schemas/coding-memory-case-v1.schema.json`
  describes one challenge row.
- `src/autopsy_memory/evaluation/schemas/retrieval-prediction-v1.schema.json`
  describes the judgment-field-free prediction rows emitted after retrieval by
  `autopsy evaluate run`. Upstream identifiers may still encode label hints and
  never cross into the evaluated backend.
- `src/autopsy_memory/evaluation/schemas/report-v1.schema.json` describes the
  stable top-level report fields. Export all schemas with `autopsy evaluate
  schemas --output-dir ./schemas`.
- `src/autopsy_memory/evaluation/schemas/score-report-v1.schema.json` describes
  independently reconstructed score reports.
- `src/autopsy_memory/evaluation/schemas/extraction-artifact-v1.schema.json`
  describes query-free extracted memories and their source attributions.
- `src/autopsy_memory/evaluation/schemas/answer-prediction-v1.schema.json`
  describes generated-answer rows that deliberately omit dataset gold.
- `src/autopsy_memory/evaluation/schemas/answer-score-v1.schema.json` describes
  independently reconstructed exact-match/token-F1 answer scores and explicit
  unsupported official judge metrics.
- `src/autopsy_memory/evaluation/schemas/end-to-end-report-v1.schema.json`
  describes extraction/context/common-answer reports.

See [the external evaluation guide](../docs/external-evaluation.md) for pinned
dataset revisions, licenses, methodology, and commands.

Optional competitor environments are not Autopsy runtime dependencies. The
canonical pinned Mem0 OSS bootstrap assets live in the wheel under
`src/autopsy_memory/evaluation/competitors/mem0/`; the
[`competitors/mem0/`](competitors/mem0/) directory is a source-checkout
convenience wrapper.

Publication bundles are separately gated and aggregate-only. The
[`publication/raw-retrieval-v1/`](publication/raw-retrieval-v1/) scaffold defines the claim
language, same-commit comparison gate, attribution requirements, and safe
release layout; public benchmark data and query-bearing artifacts remain
outside the repository.
