# Autopsy Raw-Evidence Retrieval Evaluation

This directory is the `raw-retrieval-v1` publication scaffold for Autopsy's controlled evaluation
on LoCoMo and LongMemEval-S. It is deliberately aggregate-only: public benchmark
datasets, query-bearing predictions, per-case score records, extracted memories,
generated answers, vector stores, and model weights do not belong in the default
release bundle.

This is an evaluation release, not the software release or Git tag `v0.1.30`.
The evaluated package metadata reports version `0.1.30`, but the candidate
Autopsy source snapshot was
`a22c3c7b9946a7fa8a1cdb2c6dd0f50d9b58e71f`; the existing `v0.1.30` tag points
to `4f2e23d` and must not be cited as the evaluated code. The generated bundle
records the exact later same-commit snapshot used for all six final rows.

<!-- PUBLICATION_STATUS_START -->
**Publication status:** release candidate. Do not publish the comparison table
until every listed system has been rerun from the same clean, committed Autopsy
source revision and the independent scorer reproduces the run metrics exactly.
<!-- PUBLICATION_STATUS_END -->

## Scope of the claim

These are **raw source-evidence retrieval** results. They measure whether a
system retrieves the benchmark turns or sessions identified as evidence. They
are not answer accuracy, LLM-judge accuracy, or a complete measure of product
memory quality.

The release comparison has three precisely qualified systems:

- `autopsy`: Autopsy's isolated native hybrid retriever (package metadata
  `0.1.30`), with full
  current-profile vector coverage and observed retrieval-channel telemetry.
- `builtin-bm25`: Autopsy's deterministic Okapi BM25 implementation. It is a
  lexical control baseline, not a memory system.
- `mem0-oss-raw`: Mem0 OSS 2.0.11 at source commit
  `f2532f072fdefa4c90264acc80af0984309f8b06`, using `infer=False`, local
  on-disk Qdrant, and the pinned
  `sentence-transformers/multi-qa-MiniLM-L6-cos-v1` embedding model. It does not
  exercise Mem0's LLM extraction/consolidation or managed platform.

Do not shorten the third label to an unqualified "Mem0" in a headline. Do not
compare any row numerically with Mem0's published end-to-end answer-accuracy
scores; those use different retrieval depths, answerers, judges, exclusion
rules, and in some cases managed-platform features.

For the exact current Mem0 claims, their checked-in artifact discrepancies,
and the official LongMemEval baseline, see
[PUBLISHED_SCORE_CONTEXT.md](PUBLISHED_SCORE_CONTEXT.md).

## Frozen protocols

| Dataset | Artifact and representation | Unit | Cutoffs | Scoring population |
|---|---|---|---|---|
| LoCoMo | Git `3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376`; complete released text | turn | 1, 5, 10 | 1,534 retrieval-scored cases; 1,980 abstention-scored cases, including 446 adversarial-abstention cases |
| LongMemEval-S | HF `98d7416c24c778c2fee6e6f3006e7a073259d48f`; `upstream` user-only representation | session | 5, 10, 50 | 419 retrieval-scored cases; 449 abstention-scored cases; 51 assistant-only evidence cases excluded from retrieval scoring |

Both protocols use `--track raw-retrieval`, `--temporal-policy dataset`, the
complete pinned artifact, no category filter, no sampling, at least two measured
repetitions, and independent rescoring. LongMemEval-S's `upstream`
representation is intentionally separate from Autopsy's broader `audited`
representation.

The primary metrics are:

- **Recall-any@k:** fraction of scored questions with at least one gold evidence
  source in the first `k` results.
- **Recall-all@k:** fraction with every resolvable gold evidence source in the
  first `k` results.
- **Evidence recall@k:** macro-average fraction of each question's resolvable
  evidence sources retrieved by `k`.
- **MRR@K:** reciprocal rank of the first relevant source, averaged at the
  protocol's maximum cutoff (`K=10` for LoCoMo and `K=50` for LongMemEval-S).
- **Abstention F1:** F1 for predicting that no answer-bearing memory should be
  returned. It must be reported alongside its confusion counts.

Latency is local wall-clock retrieval latency on the hardware recorded in each
aggregate artifact. It is not a portable service-level benchmark. Ingestion and
model initialization must be reported separately from query latency.

## Release comparison matrix

Populate this table only from the final same-commit aggregate artifacts named in
the last column. Preserve more precision in those artifacts than is displayed
here.

<!-- RESULTS_TABLE_START -->
| Dataset | System | Recall-any@10 | Recall-all@10 | Evidence recall@10 | MRR@K | Abstention F1 | Mean query latency | Aggregate artifact |
|---|---|---:|---:|---:|---:|---:|---:|---|
| LoCoMo | Autopsy hybrid (package metadata 0.1.30) | pending | pending | pending | pending | pending | pending | `aggregate/locomo-autopsy.json` |
| LoCoMo | built-in BM25 control | pending | pending | pending | pending | pending | pending | `aggregate/locomo-builtin-bm25.json` |
| LoCoMo | Mem0 OSS 2.0.11 raw (`infer=False`) | pending | pending | pending | pending | pending | pending | `aggregate/locomo-mem0-oss-raw.json` |
| LongMemEval-S upstream | Autopsy hybrid (package metadata 0.1.30) | pending | pending | pending | pending | pending | pending | `aggregate/longmemeval-s-autopsy.json` |
| LongMemEval-S upstream | built-in BM25 control | pending | pending | pending | pending | pending | pending | `aggregate/longmemeval-s-builtin-bm25.json` |
| LongMemEval-S upstream | Mem0 OSS 2.0.11 raw (`infer=False`) | pending | pending | pending | pending | pending | pending | `aggregate/longmemeval-s-mem0-oss-raw.json` |
<!-- RESULTS_TABLE_END -->

An aggregate artifact is eligible for the table only when all of these fields
agree across the six runs:

1. `runtime.git_commit` is one exact, non-empty commit and
   `runtime.git_dirty` is `false`.
2. The dataset SHA-256 matches the pinned value in
   [ATTRIBUTION.md](ATTRIBUTION.md).
3. `comparable_run` is `true`, case errors and ranking-instability counts are
   zero, forbidden exposure is zero, and all required cutoffs are present.
4. The independent score artifact reports complete expected coverage and exact
   equality with the run's aggregate metrics.
5. Autopsy's hybrid rows have current vector coverage `1.0`, exact embedding and
   reranker revisions, and observed semantic-channel participation.
6. Adapter configuration hashes, source-tree hashes, dependency versions,
   hardware, timing definitions, exclusion counts, and raw source-report
   SHA-256 values are retained in the aggregate artifacts.

Earlier diagnostic and candidate runs may be discussed as engineering history,
but must not be substituted into this matrix. In particular, a comparator result
from an earlier commit is not a same-commit result merely because its adapter
code appears unchanged.

## Build the gated bundle

`build_release.py` uses only the Python standard library. It accepts exactly six
named run/independent-score pairs, validates every gate above before writing,
and atomically creates a new output directory:

```bash
python evaluation/publication/raw-retrieval-v1/build_release.py \
  --output-dir dist/autopsy-raw-retrieval-v1 \
  --pair locomo-autopsy RUN.json SCORE.json \
  --pair locomo-builtin-bm25 RUN.json SCORE.json \
  --pair locomo-mem0-oss-raw RUN.json SCORE.json \
  --pair longmemeval-s-autopsy RUN.json SCORE.json \
  --pair longmemeval-s-builtin-bm25 RUN.json SCORE.json \
  --pair longmemeval-s-mem0-oss-raw RUN.json SCORE.json
```

The builder does not copy or recursively redact either input. It constructs a
fixed aggregate allowlist, records each original run/score/prediction digest and
each sanitized aggregate digest in `MANIFEST.json`, fills this README's table,
copies the attribution notice and schema, and hashes every emitted file in
`SHA256SUMS`. Existing or incomplete output directories are never reused.

## Safe release layout

The distributable archive should contain only the following classes of files:

```text
autopsy-raw-retrieval-v1/
├── README.md
├── ATTRIBUTION.md
├── MANIFEST.json
├── SHA256SUMS
├── aggregate/
│   ├── locomo-autopsy.json
│   ├── locomo-builtin-bm25.json
│   ├── locomo-mem0-oss-raw.json
│   ├── longmemeval-s-autopsy.json
│   ├── longmemeval-s-builtin-bm25.json
│   └── longmemeval-s-mem0-oss-raw.json
└── schemas/
    └── aggregate-result-v1.schema.json
```

`MANIFEST.json` should bind the release name, source commit, source-tree digest,
dataset revisions and digests, run-report digests, independent-score digests,
aggregate-artifact digests, commands, hardware profile, and UTC timestamps.
`SHA256SUMS` should cover every file in the archive except itself.

The aggregate export must remove local paths, hostnames, usernames, temporary
store paths, case/query text, document text, ranked source IDs, generated text,
and per-case labels. It should retain aggregate and per-category metrics,
confusion counts, exclusions, timing summaries, channel counts, configuration
and provenance hashes, model/package pins, comparability gates, and the hashes
of the private source run and score artifacts.

Never add these paths or equivalents to the default archive:

```text
data/
predictions/
scores/per-case/
extractions/
answers/
stores/
models/
logs/
```

The full local report, independent score report, and prediction JSONL remain the
reproducibility source of truth. They should be retained privately with their
hashes. Anyone reproducing the evaluation should acquire the datasets from
upstream, accept the applicable license, rerun the published commands, and
compare hashes and aggregate metrics.

## Publishable wording

After the matrix passes its gate, a claim may use this form:

> On full, pinned, independently rescored raw-evidence retrieval runs from clean
> commit `<commit>`, Autopsy (package metadata `0.1.30`) achieved `<LoCoMo Recall-any@10>` and
> `<LoCoMo MRR@10>` on LoCoMo, and `<LongMemEval Recall-any@10>` and
> `<LongMemEval MRR@50>` on the LongMemEval-S upstream user-only
> representation. These are evidence-retrieval metrics, not end-to-end answer
> accuracy. The accompanying comparison uses Autopsy's built-in BM25 control
> and Mem0 OSS 2.0.11 raw retrieval with `infer=False`; it does not represent
> Mem0's managed or native LLM-extraction pipeline.

Do not claim "state of the art," "Autopsy beats Mem0," or report Recall-any as
"accuracy." Report negative findings, latency, exclusions, abstention behavior,
and category-level results alongside any favorable comparison.

## Exploratory answer-quality follow-up

The separate [Codex diagnostic result](CODEX_DIAGNOSTIC_RESULTS.md) evaluates a
frozen 110-case stratified sample with a retrieval-grounded Codex answerer and
two independent judge passes. It is aggregate-only, explicitly exploratory,
and not part of the raw-retrieval comparison matrix above.

For commands, schemas, and full methodology, see
[the external evaluation guide](../../../docs/external-evaluation.md). For
redistribution boundaries and notices, see [ATTRIBUTION.md](ATTRIBUTION.md).
