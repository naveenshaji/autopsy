# Published-score context

Published memory-system scores answer a useful market question, but they are
not direct comparators for Autopsy's raw source-evidence retrieval matrix.
Retrieval depth, answer model, judge, exclusions, memory product, and metric all
change the number materially.

## Mem0's current headline versus checked-in artifacts

At pinned `memory-benchmarks` commit
[`4b61c5d`](https://github.com/mem0ai/memory-benchmarks/tree/4b61c5d31b9c668a12b4f5e78064248a02c82d2b),
the README reports these managed Mem0 platform v3 end-to-end scores:

| Dataset | Retrieval budget | README claim | Checked-in artifact |
|---|---:|---:|---:|
| LoCoMo, categories 1–4 | top 200 | 92.5% (1425/1540) | 91.558% (1410/1540) |
| LoCoMo, categories 1–4 | top 50 | 91.8% (1414/1540) | 82.662% (1273/1540) |
| LongMemEval | top 200 | 94.4% (472/500) | 93.4% (467/500) |
| LongMemEval | top 50 | 94.8% (474/500) | 90.4% (452/500) |

Primary sources:

- [Mem0 benchmark README and headline table](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/README.md#results)
- [LoCoMo top-200 artifact](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/locomo_results.json)
  and [top-50 artifact](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/locomo_top50_results.json)
- [LongMemEval top-200 artifact](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/longmemeval_results.json)
  and [top-50 artifact](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/longmemeval_top50_results.json)

The checked-in LoCoMo run metadata identifies GPT-5 answer and judge models,
Azure as provider, 1540 questions from categories 1–4, and top-200 retrieval.
It excludes LoCoMo's 446 adversarial-abstention questions. The benchmark itself
describes a three-stage memory-ingest, answer-generation, and LLM-judging
pipeline. These are judged QA pass rates, not source-evidence recall.

Mem0's 2025 paper reported a different LoCoMo protocol and much lower scores:
`66.88 ± 0.15%` for Mem0 and `68.44 ± 0.17%` for Mem0 Graph. See the
[Mem0 paper](https://arxiv.org/abs/2504.19413). Those historical results are
also end-to-end and exclude adversarial questions.

## LongMemEval's official baseline

The [LongMemEval paper](https://arxiv.org/html/2410.10813) reports answer
accuracy separately from retrieval. On LongMemEval-S, GPT-4o full-context QA
was `60.6%` directly and `64.0%` with Chain-of-Note; oracle evidence-only runs
were `87.0%` and `92.4%`. Its retrieval experiments use strict evidence recall
and NDCG under their own representation and exclusion rules. There is no
single official v1 leaderboard that makes vendor pipelines automatically
comparable.

## Why the local Mem0 run was still necessary

The same-commit comparator in this release is deliberately narrower: Mem0 OSS
2.0.11 raw-vector retrieval with `infer=False`, local Qdrant, and a pinned local
embedder. It uses the same dataset artifacts, source-evidence units, cutoffs,
temporal policy, exclusions, scorer, and evaluation-source commit as Autopsy.

That controlled run supports direct retrieval statements. The managed Mem0
headline scores support only contextual wording such as “Mem0 reports 92.5%
on its managed LoCoMo top-200 judged-QA protocol.” They do not support a claim
that Autopsy beats or trails Mem0 on the same metric.

## Safe publication boundary

Publish:

- the six-row same-commit raw-retrieval matrix and sanitized aggregates;
- Mem0's published claims as attributed context, including protocol and
  checked-in-artifact discrepancies;
- the separate aggregate-only Codex exploratory diagnostic.

Do not publish a blended leaderboard, rename Recall-any as accuracy, or compare
the 110-case diagnostic directly with vendor full-dataset scores.
