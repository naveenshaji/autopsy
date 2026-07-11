# Codex answerer diagnostic results

This is the aggregate result of the exploratory, retrieval-grounded Codex
answerer diagnostic described in [CODEX_DIAGNOSTIC.md](CODEX_DIAGNOSTIC.md).
It is not an official LoCoMo or LongMemEval score and is not directly
comparable to vendor-reported end-to-end memory scores.

The accepted run used clean tooling commit
`2476e379c57d6f075a10e313b9d0bde6ec4eea45`, the frozen Autopsy retrieval
artifacts from evaluation source commit
`a22c3c7b9946a7fa8a1cdb2c6dd0f50d9b58e71f`, `gpt-5.4-mini` as answerer and
`gpt-5.4` as two-pass judge, both at `medium` reasoning effort. API credentials
were removed and the Codex CLI was forced to use the cached ChatGPT login.
API-key dollar spend was `$0`; ChatGPT quota consumption was not measured.

## Aggregate result

| Population | Cases | Answerable | Judge pass rate (pass 1 / pass 2) | Judge agreement | Exact match | Token F1 | Answer coverage | Abstention F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LoCoMo stratified sample | 50 | 40 | 0.460 / 0.500 | 0.960 | 0.150 | 0.380 | 0.725 | 0.385 |
| LongMemEval-S stratified sample | 60 | 30 | 0.700 / 0.700 | 1.000 | 0.167 | 0.319 | 0.633 | 0.829 |
| Combined unweighted diagnostic | 110 | 70 | 0.591 / 0.609 | 0.982 | 0.157 | 0.354 | 0.686 | 0.708 |

The category breakdown is more informative than the combined number. LoCoMo
single-hop questions reached `0.80–0.90` judge pass rate, while multi-hop
questions reached only `0.10–0.20`. LongMemEval-S multi-session and
knowledge-update questions reached `0.882` and `0.818`, while the small
single-session-preference stratum reached `0.20`.

These results show that respectable source-evidence recall does not imply high
answer quality. Answer composition, multi-hop reasoning, abstention policy,
representation exclusions, and the answerer itself remain material failure
modes. The LongMemEval-S result is also lifted by the diagnostic's deliberate
inclusion of all 30 abstention cases, so it must not be presented as a
full-dataset accuracy estimate.

## Operational findings

The final accepted artifacts contain 14 answer batches and 28 judge batches,
or 42 accepted remote model calls. One additional answer response in the final
run was rejected for incomplete case-handle coverage and retried; the v1 score
file counts accepted calls, not rejected attempts.

Pre-publication pilots exposed three useful constraints that shaped the final
runner:

- A 32-case `xhigh` answer batch exceeded a 30-minute timeout.
- Larger strict-output batches sometimes omitted case handles.
- A prompt that allowed general knowledge conflicted with retrieval-grounding
  validation until the protocol explicitly required a case-local citation or
  abstention.

The published defaults therefore use `medium` reasoning, eight-case answer
batches, atomic per-batch persistence, exact handle-coverage checks, and
separate judge sessions. These are operational safeguards, not evidence that
model sampling is deterministic.

## Publication artifact

The aggregate-only machine-readable result is
[codex-diagnostic-aggregate.json](codex-diagnostic-aggregate.json), SHA-256
`1bae87f6b23503c54eac5f5068b4cec4604cfbf3b58c5e066e079e24882ed013`.
It contains no benchmark questions, contexts, answers, source identifiers,
case handles, local paths, or credentials. The private run directory must not
be published.
