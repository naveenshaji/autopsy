# External Evaluation

`autopsy evaluate` is a reproducible retrieval and end-to-end evaluation suite
for public long-term-memory datasets. It is separate from `autopsy benchmark`,
which remains the fast internal product regression gate.

The external suite currently supports:

- [LoCoMo](https://github.com/snap-research/locomo), pinned to Git commit
  `3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376`.
- [LongMemEval-S cleaned](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned),
  pinned to Hugging Face revision `98d7416c24c778c2fee6e6f3006e7a073259d48f`.
- The small controlled coding-memory challenge set bundled with the package.
  This fixture is a regression and
  failure-analysis set, not a public leaderboard dataset.

## Evaluation Tracks

Every run declares one of three non-interchangeable tracks:

| Track | Corpus presented to the adapter | Output scored |
|---|---|---|
| `raw-retrieval` | Sanitized raw turns or sessions | Source-evidence retrieval |
| `extracted-retrieval` | Memories produced by the query-free deterministic extractor | Source-attributed retrieval |
| `common-answer` | The same extracted memories | Retrieval plus one shared deterministic answer generator |

`raw-retrieval` remains the default, so existing commands and reports retain
their meaning. End-to-end numbers are never mixed into raw-retrieval leaderboards.

## What It Measures

All tracks measure evidence retrieval:

- Recall-any at k
- Strict recall-all at k
- Fractional evidence recall at k
- Mean reciprocal rank at the maximum declared retrieval cutoff
- Standards-correct nDCG at k
- LongMemEval-upstream-compatible nDCG at k
- Abstention precision, recall, and F1
- Forbidden/stale/cross-scope/poisoned-memory exposure at k
- Per-category macro results
- Ingestion throughput
- Retrieval p50, p95, and p99 latency
- Ranking stability across repetitions
- Actual lexical, entity, relationship, embedding, reranker, and usage-ranking
  channel contributions
- Eligible-item, embedded-item, and vector-coverage counts

The end-to-end tracks additionally report unique input corpora and documents,
extracted memory count, input/output characters, compression ratio and factor,
extraction documents/characters/memories per second, retrieved context size,
answer coverage, normalized exact match, token F1, and abstention accuracy.
Extractor and generator identity, canonical configuration hash, source pin,
execution mode, and cost metadata are recorded in every report.

The prediction JSONL contains no explicit relevance, forbidden, answer, or
abstention fields, and it is written only after retrieval. It is not a blind
artifact: upstream case/document IDs and categories can themselves carry hints
such as `_abs` or `answer`. Those identifiers remain outside the evaluated
backend and are emitted so `autopsy evaluate score` can re-open the dataset and
independently reconstruct every score.

The suite does **not** describe retrieval scores as answer accuracy. On the
`common-answer` track, generated answers are written to a gold-free JSONL file
before a separate scorer reopens the dataset. Exact match and token F1 are
deterministic local diagnostics. LongMemEval's official frozen GPT-4o judge is
not bundled; its metric is emitted with `status: unsupported` and `value: null`
rather than approximated or silently replaced.

The bundled extractor is an intentionally simple offline baseline. It splits
conversation text into bounded sentence memories, removes standalone date
lines, deduplicates exact facts only within the same repository/lifecycle
window, and preserves an out-of-band many-to-many source attribution table. Its
API receives only a corpus: no query, answer, evidence label, forbidden ID, or
abstention target can cross the extraction boundary. Source IDs likewise stay
outside the retrieval adapter. This evaluates extraction mechanics, but does
not claim learned consolidation or semantic fact synthesis.

## Dataset Acquisition

External data is not included in Autopsy.

Inspect the pinned artifacts and licenses:

```bash
autopsy evaluate datasets
```

Download after reviewing and accepting the upstream license:

```bash
autopsy evaluate fetch \
  --dataset locomo \
  --output-dir ~/.cache/autopsy/evaluation \
  --accept-license

autopsy evaluate fetch \
  --dataset longmemeval-s \
  --output-dir ~/.cache/autopsy/evaluation \
  --accept-license
```

Downloads use immutable revision URLs and are rejected unless their SHA-256
digests match. A neighboring `.provenance.json` sidecar preserves the upstream
URL, revision, checksum, license, and notice:

| Dataset | License | SHA-256 |
|---|---|---|
| LoCoMo | CC BY-NC 4.0 | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |
| LongMemEval-S cleaned | MIT | `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` |

LoCoMo is non-commercial. Do not vendor it into Autopsy or fetch its third-party
image URLs. The adapter uses the released text and BLIP captions only.

## Validate Before Running

```bash
autopsy evaluate validate \
  --dataset locomo \
  --input ~/.cache/autopsy/evaluation/locomo10.json \
  --granularity turn

autopsy evaluate validate \
  --dataset longmemeval-s \
  --input ~/.cache/autopsy/evaluation/longmemeval_s_cleaned.json \
  --granularity session
```

Validation streams the top-level JSON array and therefore does not load the
277 MB LongMemEval file into memory. It checks the artifact digest, aligned
session arrays, duplicate IDs, evidence resolution, query IDs, category counts,
and temporal anomalies.

The pinned artifacts currently validate as:

| Dataset | Queries | Retrieval-scorable | Corpora | Unique documents | Abstention |
|---|---:|---:|---:|---:|---:|
| LoCoMo | 1,986 | 1,980 | 10 | 5,882 turns | 446 |
| LongMemEval-S audited | 500 | 500 | 500 | 23,867 sessions | 30 |
| LongMemEval-S upstream | 500 | 449 | 500 | 23,867 sessions | 30 |

LongMemEval has two explicit representation modes:

- `--representation upstream` reproduces its released retriever's user-only
  source serialization: bare user content, space-joined per session, without
  role or timestamp prefixes. Autopsy then indexes that input through its native
  memory-note representation. It leaves 419 non-abstention questions with retrievable user-side
  evidence; 51 answerable assistant-memory questions are reported as unscored.
- `--representation audited` indexes both user and assistant turns and uses the
  explicit `has_answer` labels. It scores all 470 answerable questions plus the
  30 abstention cases, but is not labeled upstream-retriever-compatible.

The default is `audited`. Use `upstream` only when making a direct comparison
with the released LongMemEval retrieval harness.

The suite deliberately reports upstream anomalies. The pinned LoCoMo release
has two unresolved evidence annotations and four non-abstention rows without
usable evidence. LongMemEval-S has 13 duplicate session IDs, 211 cases with at
least one timestamp inversion, and 76 cases containing sessions at or after the
question timestamp. Duplicate sessions receive stable occurrence-qualified IDs;
they are never silently collapsed.
The two partially unresolved LoCoMo rows and four no-evidence rows are excluded
from retrieval and abstention aggregates rather than shrinking their gold
denominators. Validation and score reports expose exclusion counts by reason.

## Run A Diagnostic Sample

```bash
autopsy evaluate run \
  --dataset longmemeval-s \
  --input ~/.cache/autopsy/evaluation/longmemeval_s_cleaned.json \
  --granularity session \
  --representation audited \
  --adapter autopsy \
  --route hybrid \
  --sample-size 25 \
  --seed 42 \
  --k 1,5,10 \
  --output results/longmemeval-s-sample.json
```

For a deterministic dependency-free lexical comparator, select Autopsy's
built-in Okapi BM25 implementation:

```bash
autopsy evaluate run \
  --dataset coding-traces \
  --input coding-memory-v1.jsonl \
  --granularity turn \
  --adapter builtin-bm25 \
  --route lexical \
  --k 1,5,10 \
  --output results/coding-builtin-bm25.json
```

`builtin-bm25` is accurately reported as Autopsy's own Okapi BM25 baseline; it
is not the third-party BM25S package. It needs no network, service credentials,
or optional dependency.

For the pinned Mem0 OSS raw-retrieval competitor, bootstrap its isolated Python
3.12 environment first. In a source checkout, use the convenience wrapper:

```bash
evaluation/competitors/mem0/setup.sh /tmp/autopsy-mem0-venv
export AUTOPSY_MEM0_PYTHON=/tmp/autopsy-mem0-venv/bin/python

autopsy evaluate run \
  --dataset coding-traces \
  --input coding-memory-v1.jsonl \
  --granularity turn \
  --adapter mem0-oss-raw \
  --route hybrid \
  --temporal-policy dataset \
  --k 1,5,10 \
  --output results/coding-mem0-oss-raw.json
```

The adapter pins Mem0 `2.0.11` at source commit
`f2532f072fdefa4c90264acc80af0984309f8b06`,
`sentence-transformers==5.1.2`, and
`sentence-transformers/multi-qa-MiniLM-L6-cos-v1` at model revision
`b207367332321f8e44f96e224ef15bc607f4dbf0`. It uses `infer=False`, embedded
on-disk Qdrant, and `MEM0_TELEMETRY=false`. The environment and model download
need the network once during bootstrap; measured retrieval is a local
subprocess with inherited API credentials stripped and model loading forced
offline, needs no service credentials, and reports USD 0 external API cost.
User-only upstream sessions with no indexable text are explicitly counted and
skipped rather than embedded as synthetic placeholders; vector coverage is
computed over the remaining eligible documents.
The exact runtime dependency versions are copied into every adapter manifest.
The canonical setup script, complete lock, and README ship under
`autopsy_memory/evaluation/competitors/mem0/` in the wheel. If an installed CLI
does not find the optional environment, its error prints the absolute packaged
`setup.sh` path to run; a source checkout is not required. Source provenance
hashes the entire packaged bootstrap tree together with the adapter and worker,
not only the Python entry points.

Sampling selects the lowest SHA-256 values of `seed:case_id`. It is stable and
independent of source-file ordering. A sampled or category-filtered run always
reports `comparable_run: false`.

## Run Extraction And Answer Tracks

Evaluate retrieval after deterministic, query-free extraction:

```bash
autopsy evaluate run \
  --track extracted-retrieval \
  --dataset locomo \
  --input ~/.cache/autopsy/evaluation/locomo10.json \
  --granularity turn \
  --adapter builtin-bm25 \
  --route lexical \
  --k 1,5,10 \
  --output results/locomo-extracted.json
```

Run the same extraction/context path with the common offline answer generator:

```bash
autopsy evaluate run \
  --track common-answer \
  --dataset longmemeval-s \
  --input ~/.cache/autopsy/evaluation/longmemeval_s_cleaned.json \
  --granularity session \
  --representation audited \
  --adapter builtin-bm25 \
  --route lexical \
  --k 10 \
  --output results/longmemeval-common-answer.json
```

End-to-end runs produce separate `.predictions.jsonl`, `.extractions.jsonl`,
and, for `common-answer`, `.answers.jsonl` artifacts beside the report. Override
their paths with `--predictions`, `--extractions`, and `--answers`. The extractor
and generator are currently fixed, audited baselines named
`deterministic-sentence-v1` and `deterministic-extractive-v1`. They require no
network, model download, API key, or paid service.
The retrieval prediction sub-artifact is always labeled
`extracted-retrieval`, including inside a `common-answer` run, so it can be
rescored independently with `evaluate score --track extracted-retrieval`; the
answer sub-artifact is labeled `common-answer`.

End-to-end `comparable_run` uses the same gates as raw retrieval: pinned full
artifact, no case errors, required cutoffs, upstream temporal/representation
compatibility, qualified requested semantic route with observed channels, exact
model revisions for channels that contributed, zero forbidden-memory exposure,
and clean committed source. Like raw retrieval, it requires at least two measured
`--repetitions` with identical memory and source rankings; one repetition is
reported as stability-unqualified rather than assumed stable. Retrieval reasons,
first/subsequent latency profiles, and instability counts remain visible in the
end-to-end report and extracted-retrieval predictions.

## Run The Complete Public Dataset

Remove `--sample-size` and category filters:

```bash
autopsy evaluate run \
  --dataset locomo \
  --input ~/.cache/autopsy/evaluation/locomo10.json \
  --granularity turn \
  --route lexical \
  --k 1,5,10 \
  --repetitions 3 \
  --output results/locomo-full.json
```

A comparable full run requires the pinned artifact, every selected case to
finish without error, no sampling, and no category restriction. The report
records the dataset hash, source revision, Autopsy source commit, package and
Python versions, dependency versions, UTC run timestamps, hardware profile,
seed, route, models, timings, and raw prediction hash. Every prediction row and
summary report also binds the adapter id, evaluation track, canonical adapter
configuration hash, package/source pin, local/remote execution mode, and
external-service cost metadata.
Any exposure of a forbidden, stale, cross-scope, or poisoned memory is a hard
failure for comparability rather than a score that can be averaged away.
At least two measured repetitions must produce stable rankings; a one-repetition
run is stability-unqualified. Code provenance must come from clean,
committed Autopsy package sources. The report records the commit, dependency
versions, and a SHA-256 digest of the loaded package tree; dirty or unversioned
source remains diagnostic. Unrelated output files do not dirty the code gate.
For LongMemEval, comparability additionally requires the upstream
representation, `--temporal-policy dataset`, and the official comparison
cutoffs 5, 10, and 50.

## Adapter Isolation And Query Independence

Every adapter follows a two-phase boundary. Corpus preparation receives an
`EvaluationCorpus` containing sanitized documents and relations only. That type
has no dataset, case, query, answer, relevance, forbidden-evidence, or abstention
fields. The natural-language query arrives later in a separate
`RetrievalRequest`. The Mem0 adapter serializes those phases to separate NDJSON
subprocess messages; it never sends query content in `prepare`.

The built-in Autopsy adapter:

- creates a dedicated temporary FalkorDBLite store;
- never resolves or opens the production workspace;
- never calls the resident worker or MCP bridge;
- uses deterministic document stable keys and source timestamps;
- keeps dataset document/session IDs only in a hashed, out-of-band result map;
- ingests no benchmark query strings, QA answer fields, judgment/evidence labels,
  answer-bearing session IDs, or `has_answer` flags (the released memory turns
  themselves naturally retain their conversational content);
- preloads the pinned reranker with a fixed query-free warmup during ingestion;
- disables access-telemetry writes so every measured repetition reads the same
  frozen corpus (production consults write usage to non-indexed sidecars);
- reuses a corpus only when its sanitized document-and-relation fingerprint is
  identical;
- terminates and removes the temporary store at the end of the run unless
  `--keep-store` is explicitly requested.

Telemetry reset is important because Autopsy normally records retrieval access
and uses it as a bounded ranking prior. Without reset, query ordering would
change later benchmark results.

The Mem0 raw adapter adds a second out-of-band identity layer. Mem0-generated
UUIDs map to the runner's opaque corpus handles only inside the isolated worker;
neither UUIDs nor upstream evidence/document IDs are embedded. Repository scope
is passed through Mem0's native Qdrant metadata filter and verified again at the
result boundary. Current expiration uses Mem0's native date filter plus an exact
UTC result check. Relations are intentionally ignored in this raw-vector track.
Mem0 OSS 2.0.11 rejects its `reference_date` parameter, so native historical
`as-of` retrieval is explicitly reported as unsupported and is never silently
emulated.

## Temporal Policies

`--temporal-policy dataset` is the public-dataset default. It evaluates the
complete haystack supplied by the benchmark, matching upstream retrieval setup.

`--temporal-policy as-of` additionally applies each case's query timestamp to
Autopsy's conservative lifecycle/lineage filtering. It does not reconstruct a
prior body for a node mutated in place. Use this for the immutable-event coding-memory
challenge and for a separately labeled temporal audit. Do not compare an as-of
run directly with upstream systems that consumed the complete haystack.
Released timestamps without an explicit offset are normalized to UTC solely for
deterministic filtering; the original timestamp text remains in audited corpus
content.

## Semantic Qualification

The report distinguishes a requested route from the channels that actually
contributed. Autopsy now attempts a pinned embedding for every eligible normal
memory write and records the provider, model revision, text-template version,
source-content hash, source timestamp, dimension, and status with the vector.
The default write-failure policy is recoverable: if the provider is unavailable,
the memory write succeeds with `embedding_status: deferred`, and `autopsy
embeddings backfill` can repair it later. `autopsy embeddings status` and
`autopsy health` report current-profile coverage and vector-index drift.

Enabling embeddings is not enough to qualify a semantic result. A `hybrid` or
`auto` run with incomplete current-profile vector coverage or without observed
embedding retrieval still sets:

```json
{
  "semantic_route_qualified": false,
  "notes": ["Hybrid/auto results require full vector coverage and observed embedding retrieval."]
}
```

It does not silently present lexical fallback as semantic retrieval. A lexical
run remains a valid lexical evaluation. The isolated Autopsy evaluation adapter
batch-embeds its frozen corpus through the same versioned backfill path and
reports both evaluated vector coverage and the channels that contributed.

## Independent Rescoring

```bash
autopsy evaluate score \
  --dataset longmemeval-s \
  --input ~/.cache/autopsy/evaluation/longmemeval_s_cleaned.json \
  --granularity session \
  --predictions results/longmemeval-s-sample.predictions.jsonl \
  --k 1,5,10 \
  --output results/longmemeval-s-sample.rescored.json
```

The scorer rejects duplicate and unknown prediction IDs. It reports explicit
dataset coverage so a subset cannot be mistaken for a complete run.
Every row is also bound to the dataset SHA-256, granularity, representation,
corpus ID, category, and exact query. Mixing audited and upstream predictions,
rescoring against a changed artifact, or using malformed rows fails closed.
The row records its retrieval depth, so rescoring cannot request a cutoff the
original run did not retrieve; MRR is explicitly reported at the maximum
declared cutoff.
Run reports, score reports, and prediction rows have separate published schemas;
input, report, and prediction paths must be distinct, and writes are atomic.

Common-answer artifacts use a different schema and must be selected explicitly:

```bash
autopsy evaluate score \
  --track common-answer \
  --dataset longmemeval-s \
  --input ~/.cache/autopsy/evaluation/longmemeval_s_cleaned.json \
  --granularity session \
  --representation audited \
  --predictions results/longmemeval-common-answer.answers.jsonl \
  --output results/longmemeval-common-answer.rescored.json
```

Answer prediction rows contain the generated answer, abstention decision,
ranked memory handles, and source citations, but never the gold answer. Dataset
gold is introduced only inside the independent scoring step. Every row also
binds adapter, extractor, and generator configuration hashes plus package pin,
source pin, execution mode, and cost metadata. The scorer rejects mixed
component provenance instead of aggregating answers from different builds.

## Coding-Memory Challenge

The controlled fixture exercises behaviors conversational benchmarks miss:

- held-out paraphrase retrieval;
- supersession and reversion;
- same-title cross-repository isolation;
- hard topical abstention;
- two-hop relation evidence;
- expired-memory rejection;
- memory-poisoning quarantine.

Run it with:

```bash
autopsy evaluate fixture --output ~/.cache/autopsy/evaluation/coding-memory-v1.jsonl
autopsy evaluate run \
  --dataset coding-traces \
  --input ~/.cache/autopsy/evaluation/coding-memory-v1.jsonl \
  --granularity turn \
  --route lexical \
  --temporal-policy as-of \
  --output results/coding-memory-v1.json
```

The coding fixture has no external provenance and therefore never sets
`official_dataset_artifact: true`. It is designed for transparent regression
diagnosis, not comparative leaderboard claims.

## Result Interpretation

Do not publish one opaque composite score. Publish:

1. Dataset variant and digest.
2. Granularity and temporal policy.
3. Retrieval route and observed channel counts.
4. Vector coverage and semantic qualification.
5. All per-category retrieval and abstention metrics.
6. Error, exclusion, and unresolved-evidence counts.
7. Aggregate reports and the withheld prediction JSONL's SHA-256 digest. Publish
   row-level predictions or scores only in a separate dataset-licensed release
   after privacy and license review; they reproduce benchmark queries,
   identifiers, and per-case judgments.
8. Hardware and latency percentiles.

Keep LoCoMo, LongMemEval-S, LongMemEval oracle, and any future LongMemEval-M
results separate. Oracle retrieval is a reader diagnostic, not a memory-system
retrieval result.
