# Attribution and Release Boundaries

This file records the publication rules for the Autopsy `raw-retrieval-v1` aggregate
raw-evidence retrieval report. It is operational guidance, not legal advice.

## Autopsy-authored material

Autopsy's evaluation implementation, schemas, synthetic coding-memory fixture,
methodology, and aggregate-only publication files are Autopsy-authored and are
covered by the repository's Apache License 2.0. Preserve the repository license
and copyright notice when redistributing them.

The controlled coding-memory fixture may accompany Autopsy as a transparent
regression fixture, but it must be labeled synthetic and must not be presented
as public leaderboard evidence.

## LoCoMo

- Project: [LoCoMo](https://github.com/snap-research/locomo), SNAP Research.
- Pinned revision: `3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376`.
- Evaluated file SHA-256:
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- License: [Creative Commons Attribution-NonCommercial 4.0
  International](https://creativecommons.org/licenses/by-nc/4.0/).
- Source file: `data/locomo10.json` at the pinned revision.

Dataset/paper authors: Adyasha Maharana, Dong-Ho Lee, Sergey Tulyakov, Mohit
Bansal, Francesco Barbieri, and Yuwei Fang.

```bibtex
@article{maharana2024evaluating,
  title={Evaluating very long-term conversational memory of llm agents},
  author={Maharana, Adyasha and Lee, Dong-Ho and Tulyakov, Sergey and Bansal, Mohit and Barbieri, Francesco and Fang, Yuwei},
  journal={arXiv preprint arXiv:2402.17753},
  year={2024}
}
```

Any publication of LoCoMo-derived material must identify the project and
authors, link the source and license, indicate that Autopsy's evaluation output
is a derived analysis, describe material modifications, and remain within the
license's non-commercial restriction unless separate permission has been
obtained. The aggregate metrics and provenance in this bundle contain no
conversation or query text, but attribution is still retained.

Do not put the LoCoMo dataset, benchmark queries, raw prediction rows, per-case
score records, extracted memories, generated answers, or fetched image content
inside Autopsy's Apache-licensed distribution. Query-bearing prediction files
and text-bearing extraction/answer files are dataset-derived artifacts, not
Apache-only Autopsy source.

Suggested notice:

> LoCoMo evaluation uses the dataset released by SNAP Research at revision
> `3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376`, licensed under CC BY-NC 4.0.
> Autopsy converted its evidence annotations into aggregate retrieval metrics;
> no benchmark conversations or queries are redistributed here.

The controlling dataset terms are the upstream [CC BY-NC 4.0 license
notice](https://github.com/snap-research/locomo/blob/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/LICENSE.txt)
and [license deed](https://creativecommons.org/licenses/by-nc/4.0/). This
evaluation bundle does not replace or narrow those terms.

## LongMemEval-S cleaned

- Project: [LongMemEval](https://github.com/xiaowu0162/LongMemEval).
- Cleaned artifact: [longmemeval-cleaned](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned).
- Pinned Hugging Face revision:
  `98d7416c24c778c2fee6e6f3006e7a073259d48f`.
- Evaluated file SHA-256:
  `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
- License: MIT. Preserve the upstream copyright and permission notice with any
  redistributed copy or substantial dataset-derived artifact.

Dataset/paper authors: Di Wu, Hongwei Wang, Wenhao Yu, Yuwei Zhang, Kai-Wei
Chang, and Dong Yu.

```bibtex
@article{wu2024longmemeval,
  title={LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory},
  author={Di Wu and Hongwei Wang and Wenhao Yu and Yuwei Zhang and Kai-Wei Chang and Dong Yu},
  year={2024},
  eprint={2410.10813},
  archivePrefix={arXiv},
  primaryClass={cs.CL},
  url={https://arxiv.org/abs/2410.10813}
}
```

The default Autopsy bundle publishes aggregate metrics only. It does not ship
LongMemEval sessions, questions, prediction rows, per-case scores, extracted
memories, or generated answers. This conservative default also avoids
republishing conversational filler and personal-looking identifiers found in
the benchmark artifact.

Suggested notice:

> LongMemEval-S evaluation uses the cleaned artifact at Hugging Face revision
> `98d7416c24c778c2fee6e6f3006e7a073259d48f`, distributed under the upstream
> MIT license. Autopsy evaluated the upstream-compatible user-only retrieval
> representation and publishes aggregate metrics without redistributing the
> benchmark text.

### Complete upstream MIT notice

```text
MIT License

Copyright (c) 2024 Di Wu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Comparator and model provenance

The comparator results are measurements, not redistributed competitor products.
The aggregate files must retain these qualifications:

- `builtin-bm25` is Autopsy-authored Okapi BM25 and is a lexical baseline, not a
  standalone memory product.
- `mem0-oss-raw` pins Mem0 OSS 2.0.11 to
  `f2532f072fdefa4c90264acc80af0984309f8b06`, runs with `infer=False`, local
  Qdrant, telemetry disabled, no service credentials, and zero external API
  calls during measurement.
- Mem0's embedding model is
  `sentence-transformers/multi-qa-MiniLM-L6-cos-v1` at revision
  `b207367332321f8e44f96e224ef15bc607f4dbf0`.
- Autopsy's embedding model is `BAAI/bge-base-en-v1.5` at revision
  `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`; its reranker is
  `BAAI/bge-reranker-base` at revision
  `2cfc18c9415c912f9d8155881c133215df768a70`.

No Mem0 source tree, Qdrant store, Python environment, third-party model weight,
or model cache belongs in the publication archive. If a future bundle includes
any of those materials, audit and preserve each upstream license separately.
Model names and revision hashes are provenance references, not a grant to
redistribute model files.

Mem0 vendor-published LoCoMo or LongMemEval scores may be discussed only in a
separate background section. They must be labeled vendor-reported end-to-end
answer accuracy with their original protocol, answerer, judge, retrieval depth,
exclusions, and managed-versus-OSS status. They must not share a numeric table or
axis with Autopsy's raw-evidence retrieval metrics.

## Artifact classification

| Artifact | Default public bundle | Treatment |
|---|---|---|
| Aggregate metrics, category metrics, confusion counts | Include | Attribute datasets; retain protocol and provenance hashes |
| Sanitized runtime/configuration manifest | Include | Remove local paths and machine identifiers beyond the declared hardware profile |
| Evaluation schemas and methodology | Include | Autopsy Apache-2.0 material |
| Synthetic coding fixture | Optional | Label synthetic regression fixture, never leaderboard data |
| Raw dataset or cache | Exclude | Obtain directly from the pinned upstream source |
| Raw retrieval prediction JSONL | Exclude | Reproduces benchmark queries and identifiers |
| Full per-case score artifact | Exclude | Reconstructs case labels and evidence judgments |
| Extraction or answer artifact | Exclude | Reproduces substantial benchmark text |
| Temporary graph/vector store | Exclude | Contains benchmark-derived indexed content |
| Model weights and caches | Exclude | Obtain from model publishers under their licenses |
| API keys, environment dumps, absolute local paths | Exclude | Sensitive or machine-specific material |

Before release, inspect every staged file, calculate SHA-256 digests, and verify
that the archive contains no unlisted file class. The release manifest should
point to upstream acquisition instructions rather than embedding either public
benchmark.
